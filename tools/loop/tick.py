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

from loop import config, retry
from loop.access import access_checker
from loop.apply import apply
from loop.engine import Decisions, card_decisions, decide
from loop.github_client import GitHubClient, NotAnIssue, NotFound, OffProject
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
    try:
        card = client.card(repo, number)
    except NotAnIssue:
        logger.info("%s#%s is a pull request: a comment on it changes no card", repo, number)
        return out
    except NotFound:  # a 404 on the subject is not a failure of the run (#66)
        logger.warning("skip: %s#%s not resolvable", repo, number)
        return out
    except OffProject as missing:
        if repo.split("/")[-1] != config.OUTER_LOOP_REPO:
            out.board.add = [missing.ref]
        return out
    card_decisions(card, None, jobs, now, out)
    out.board.assignee = []  # the blocker rules need the board: a full run's job
    return out


def summary(scope: Scope, out: Decisions, printed: int) -> str:
    """The one line per run that is scanned: it never hides a write (#72)."""
    return (f"run {scope.reason}: {len(out.board.status)} status, {len(out.board.assignee)} "
            f"assignee, {len(out.board.close)} close(s), {len(out.starts)} start(s), "
            f"{printed} notice(s) printed")


def tick(dry_run: bool = False, full: bool = False) -> int:
    """The run; 0 on success. ``full`` reads the whole board whatever the trigger was."""
    now = datetime.now(UTC)
    scope = Scope(None, "full") if full else scope_of(os.environ.get("HERMES_CRON_EVENT"))
    cache = Path(config.CACHE_DIR)
    with run_lock(cache / "loop.lock"):
        out = decide_scope(GitHubClient(), scope, now)
        store = Store(cache / "loop-state.json", legacy=cache)
        lines, log = apply(out, GitHubWriter(dry_run=dry_run), store, now, scope.full)
        if not dry_run:
            store.save(scope.full)
            recovered = retry.clear(cache / retry.MARKER, now) if scope.full else None
            if recovered:  # a failed run is caught up: no retry left (retry.py)
                lines.append(recovered)
    for line in log:
        logger.info("%s", line)
    logger.info("%s", summary(scope, out, len(lines)))
    print("\n".join(lines))
    return 0
