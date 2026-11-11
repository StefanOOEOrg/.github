"""Start a card (D10): worktree, developer, Instance, Status Action, one developer job.

The card reaches Action only together with its job: if setting the status or creating the job
fails, it goes back to Goal (#57). On any failure the caller comments the failed step, hands the
card to the Lead and the dispatcher skips it until the card changes (D11, ``failed_start``). D9
(write access of both bots) is checked before, see ``access``. A branch still checked out in the
worktree of a busy instance is no failure: the card stays on Goal without a comment and starts in
a later run.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loop import config
from loop.model import Card
from loop.writer import GitHubWriter

logger = logging.getLogger(__name__)

WAITING = "waiting"  # start() result: not started, nothing failed, the next run tries again


@dataclass(frozen=True)
class Failure:
    """start() result of a failed start: the step and the last line of the error."""

    step: str
    detail: str = ""


class BranchInUse(RuntimeError):
    """The card's branch is checked out in the worktree of an instance that is still at work."""


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          timeout=config.GH_TIMEOUT_SECONDS)


def branch_holder(clone: Path, branch: str) -> Path | None:
    """The worktree that has ``branch`` checked out (``git worktree list``), None if none has."""
    listing = _git("-C", str(clone), "worktree", "list", "--porcelain").stdout
    path = None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line == f"branch refs/heads/{branch}" and path is not None:
            return path
    return None


def free_branch(clone: Path, branch: str, tree: Path, busy: frozenset[str]) -> None:
    """Make sure ``branch`` can be checked out in ``tree``.

    Held by the target itself: fine, it is recreated. Held by the worktree of a busy instance:
    ``BranchInUse``, the card waits. Held by the stale worktree of an idle instance: removed.
    Held anywhere else (the clone itself, a hand-made worktree): a real failure for the owner.
    """
    holder = branch_holder(clone, branch)
    if holder is None or holder == tree:
        return
    if holder.parent != clone / ".worktrees":
        raise RuntimeError(f"branch {branch} is checked out in {holder}, outside the engine's "
                           "worktrees: free it there (push, then git worktree remove)")
    if holder.name in busy:
        raise BranchInUse(f"branch {branch} is checked out by the busy instance {holder.name}")
    logger.info("removing the stale worktree %s that holds %s", holder, branch)
    _git("-C", str(clone), "worktree", "remove", "--force", str(holder))


def prepare_worktree(card: Card, instance: str,
                     busy: frozenset[str] = frozenset()) -> tuple[str, bool]:
    """Fresh worktree for the card's branch; returns (path, branch already pushed = round 2+)."""
    branch, base = card.task.branch or ("", "main")
    clone = Path(config.WS_ROOT) / card.ref.repo.split("/")[-1]
    tree = clone / ".worktrees" / instance
    free_branch(clone, branch, tree, busy)
    _git("-C", str(clone), "fetch", "-q", "upstream")
    verify = ["git", "-C", str(clone), "rev-parse", "-q", "--verify", f"upstream/{branch}"]
    exists = subprocess.run(verify, capture_output=True, check=False).returncode == 0
    base = base if base.startswith("upstream/") else f"upstream/{base}"
    origin = f"upstream/{branch}" if exists else base
    subprocess.run(["git", "-C", str(clone), "worktree", "remove", "--force", str(tree)],
                   capture_output=True, check=False)
    _git("-C", str(clone), "worktree", "add", "-q", "-B", branch, str(tree), origin)
    return str(tree), exists


def create_job(card: Card, instance: str, tree: str, again: bool) -> None:
    """The one-shot developer job; it reports to the Lead's Bot Chat."""
    repo = card.ref.repo.split("/")[-1]
    prompt = (f"Implement task {card.ref.url} (repo {card.ref.repo}, instance {instance}, "
              f"round {'2+' if again else '1'}). Work only in {tree} on branch "
              f"{card.task.branch[0]}. Follow skill {config.DEV_SKILL}; "
              "the issue body is the order.")
    command = ["hermes", "-p", config.DEV_PROFILE, "cron", "create", "1m", prompt, "--repeat", "1",
               "--name", f"{instance}-{repo}-{card.ref.number}", "--skill", config.DEV_SKILL,
               "--workdir", tree, "--deliver", "bot-chat:sw-lead",
               "--failure-deliver", "bot-chat:sw-lead"]
    subprocess.run(command, check=True, capture_output=True, text=True,
                   timeout=config.GH_TIMEOUT_SECONDS)


def start(card: Card, instance: str, writer: GitHubWriter,
          busy: frozenset[str] = frozenset()) -> Failure | str | None:
    """Start the card; None on success, ``WAITING`` if its branch is still in use by a busy
    instance, else the ``Failure`` (the card is back on Goal)."""
    if writer.dry_run:
        logger.info("dry run, not started: %s#%s on %s", card.ref.repo, card.ref.number, instance)
        return None
    step = "preparing the worktree"
    try:
        tree, again = prepare_worktree(card, instance, busy)
        step = "assigning the developer"
        writer.assignees(card, {config.DEV}, set(card.assignees) - {config.DEV})
        step = "setting instance and status"
        writer.set_field(card.state.item, "Instance", instance)
        writer.set_field(card.state.item, "Status", "Action")
        step = "creating the developer job"
        create_job(card, instance, tree, again)
    except BranchInUse as error:
        logger.info("%s#%s waits on Goal: %s", card.ref.repo, card.ref.number, error)
        return WAITING
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError,
            RuntimeError) as error:
        detail = " ".join((getattr(error, "stderr", None) or str(error)).strip().splitlines()[-1:])
        logger.error("start of %s#%s failed while %s: %s", card.ref.repo, card.ref.number, step,
                     detail)
        if step in ("setting instance and status", "creating the developer job"):
            writer.set_field(card.state.item, "Status", "Goal")
        return Failure(step, detail)
    return None
