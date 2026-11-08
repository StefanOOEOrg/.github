"""One engine run: lock, scope, read, decide, apply, print the Lead's lines.

Called as ``python3 -m loop tick`` from loop-tick.sh (Hermes cron, webhook-triggered and hourly).
stdout is the delivery to the Lead; everything else goes to the log on stderr.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from loop import config
from loop.access import access_checker
from loop.apply import apply
from loop.engine import Decisions, card_decisions, decide
from loop.github_client import GitHubClient
from loop.model import Ref
from loop.scope import Scope, scope_of
from loop.store import Store
from loop.writer import GitHubWriter

logger = logging.getLogger(__name__)


@contextmanager
def run_lock(path: Path):
    """One run at a time; a second one waits up to LOCK_WAIT_SECONDS, then skips quietly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        deadline = time.monotonic() + config.LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() > deadline:
                    raise TimeoutError("another engine run holds the lock") from error
                time.sleep(1)
        yield


def scheduled_jobs(jobs_file: Path) -> set[str] | None:
    """Names of the enabled developer jobs, None if the job list cannot be read."""
    try:
        jobs = json.loads(jobs_file.read_text()).get("jobs") or []
    except (OSError, ValueError) as error:
        logger.warning("developer job list unreadable: %s: %s", jobs_file, error)
        return None
    return {j.get("name") or "" for j in jobs if j.get("enabled")}


def decide_scope(client: GitHubClient, scope: Scope, now: datetime) -> Decisions:
    """Read what the scope needs and decide. A card not on the project is added (W7)."""
    jobs = scheduled_jobs(Path(config.DEV_JOBS))
    if scope.full:
        return decide(client.board(now.date()), jobs, now, access_checker())
    out = Decisions()
    repo, number = scope.card
    card = client.card(repo, number)
    if card is None:
        if repo.split("/")[-1] != config.OUTER_LOOP_REPO:
            out.board.add = [Ref(repo, number, f"https://github.com/{repo}/issues/{number}")]
        return out
    card_decisions(card, None, jobs, now, out)
    out.board.assignee = []  # the blocker rules need the board: a full run's job
    return out


def tick(dry_run: bool = False) -> int:
    """The run; 0 on success."""
    now = datetime.now(UTC)
    scope = scope_of(os.environ.get("HERMES_CRON_EVENT"))
    cache = Path(config.CACHE_DIR)
    with run_lock(cache / "loop.lock"):
        out = decide_scope(GitHubClient(), scope, now)
        store = Store(cache / "loop-state.json", legacy=cache)
        lines, log = apply(out, GitHubWriter(dry_run=dry_run), store, now, scope.full)
        if not dry_run:
            store.save(scope.full)
    for line in log:
        logger.info("%s", line)
    logger.info("run %s: %d status, %d assignee, %d start(s), %d notice(s) printed", scope.reason,
                len(out.board.status), len(out.board.assignee), len(out.starts), len(lines))
    print("\n".join(lines))
    return 0
