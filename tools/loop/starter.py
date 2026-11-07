"""Start a card (D10): worktree, developer, Instance, Status Action, one-shot developer job.

The card reaches Action only together with its job: if setting the status or creating the job
fails, it goes back to Goal and the caller comments the failed step (#57). D9 (write access of
both bots) is checked before, see ``access``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from loop import config
from loop.model import Card
from loop.writer import GitHubWriter

logger = logging.getLogger(__name__)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          timeout=config.GH_TIMEOUT_SECONDS)


def prepare_worktree(card: Card, instance: str) -> tuple[str, bool]:
    """Fresh worktree for the card's branch; returns (path, branch already pushed = round 2+)."""
    branch, base = card.task.branch or ("", "main")
    clone = Path(config.WS_ROOT) / card.ref.repo.split("/")[-1]
    tree = clone / ".worktrees" / instance
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


def start(card: Card, instance: str, writer: GitHubWriter) -> str | None:
    """Start the card; None on success, else the step that failed (the card is back on Goal)."""
    if writer.dry_run:
        logger.info("dry run, not started: %s#%s on %s", card.ref.repo, card.ref.number, instance)
        return None
    step = "preparing the worktree"
    try:
        tree, again = prepare_worktree(card, instance)
        step = "assigning the developer"
        writer.assignees(card, {config.DEV}, set(card.assignees) - {config.DEV})
        step = "setting instance and status"
        writer.set_field(card.state.item, "Instance", instance)
        writer.set_field(card.state.item, "Status", "Action")
        step = "creating the developer job"
        create_job(card, instance, tree, again)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError,
            RuntimeError) as error:
        detail = (getattr(error, "stderr", None) or str(error)).strip().splitlines()[-1:]
        logger.error("start of %s#%s failed while %s: %s", card.ref.repo, card.ref.number, step,
                     " ".join(detail))
        if step in ("setting instance and status", "creating the developer job"):
            writer.set_field(card.state.item, "Status", "Goal")
        return step
    return None
