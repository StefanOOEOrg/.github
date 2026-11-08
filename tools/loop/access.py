"""D9: can both bots write to a repository? Read once per repository and run (REST, no GraphQL).

Called only for Goal cards that could start, so most runs make no call here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from loop import config
from loop.github_client import GitHubError, Runner, run_gh

logger = logging.getLogger(__name__)
WRITE = ("admin", "maintain", "write")


def check(repo: str, run: Runner) -> str | None:
    """None if both bots can write to ``repo``, else the reason."""
    try:
        lead = json.loads(run(["api", f"repos/{repo}"])).get("permissions") or {}
        dev = json.loads(run(["api", f"repos/{repo}/collaborators/{config.DEV}/permission"]))
    except (GitHubError, ValueError) as error:
        logger.warning("permissions of %s unreadable: %s", repo, error)
        return f"the bot permissions on {repo} cannot be read"
    missing = [who for who, ok in (("the Lead bot", lead.get("push")),
                                   (config.DEV, dev.get("permission") in WRITE)) if not ok]
    return f"{' and '.join(missing)} cannot write to {repo}" if missing else None


def access_checker(run: Runner = run_gh) -> Callable[[str], str | None]:
    """``access(repo)`` with a per-run cache."""
    cache: dict[str, str | None] = {}

    def access(repo: str) -> str | None:
        if repo not in cache:
            cache[repo] = check(repo, run)
        return cache[repo]
    return access
