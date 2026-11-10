"""Read-only GitHub client: one GraphQL query per scope, via gh (its token stays in gh's config).

Migration step 1: reads only. Retries the transient 502/504 answers GitHub gives on project
queries now and then; a hung call is cut after ``GH_TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Callable
from datetime import date, timedelta

from loop import config
from loop.model import Board, Card, Ref
from loop.parse import parse_board, parse_card
from loop.queries import BOARD_QUERY, CARD_QUERY

logger = logging.getLogger(__name__)

Runner = Callable[[list[str]], str]


class GitHubError(RuntimeError):
    """A GitHub read failed after all attempts, or answered with errors."""


class NotFound(GitHubError):
    """GitHub cannot resolve the subject (repository or issue gone, renamed or not visible, #66).

    Not retried: the answer is the same on every attempt.
    """


class NotAnIssue(LookupError):
    """The number of a one-card event is a pull request (a comment on a PR)."""


class OffProject(LookupError):
    """The issue of a one-card event is not on the project; ``ref`` carries its author (#84)."""

    def __init__(self, ref: Ref) -> None:
        super().__init__(f"{ref.repo}#{ref.number} is not on the project")
        self.ref = ref


def run_gh(args: list[str]) -> str:
    """Run one gh call with timeout and retries; return its stdout."""
    last: Exception | None = None
    for attempt in range(config.GH_ATTEMPTS):
        try:
            return subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                                  timeout=config.GH_TIMEOUT_SECONDS).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            last = error
            if "Could not resolve to" in (getattr(error, "stderr", "") or ""):
                raise NotFound(error.stderr.strip()[:200]) from error
            logger.warning("gh call failed (attempt %d of %d): %s", attempt + 1, config.GH_ATTEMPTS,
                           (getattr(error, "stderr", "") or str(error)).strip()[:200])
        if attempt < len(config.GH_BACKOFF_SECONDS):
            time.sleep(config.GH_BACKOFF_SECONDS[attempt])
    raise GitHubError(str(last))


class GitHubClient:
    """Reads the scopes of a run. ``run`` is injectable for tests."""

    def __init__(self, run: Runner = run_gh) -> None:
        self._run = run

    def _graphql(self, query: str, variables: dict[str, str | int | bool]) -> dict:
        args = ["api", "graphql", "-f", f"query={query}"]
        for name, value in variables.items():
            flag = "-F" if isinstance(value, (int, bool)) else "-f"
            args += [flag, f"{name}={str(value).lower() if isinstance(value, bool) else value}"]
        answer = json.loads(self._run(args))
        if answer.get("errors"):
            raise GitHubError(json.dumps(answer["errors"])[:500])
        cost = (answer["data"].get("rateLimit") or {})
        logger.debug("graphql cost %s, remaining %s", cost.get("cost"), cost.get("remaining"))
        return answer["data"]

    def board_pages(self, today: date) -> list[dict]:
        """The raw pages of the board query (kept raw for fixtures and debugging)."""
        since = (today - timedelta(days=1)).isoformat()
        base = {"org": config.ORG, "num": config.PROJECT_NUMBER,
                "prs": f"is:pr is:open org:{config.ORG}",
                "merged": (f"is:pr is:merged repo:{config.ORG}/{config.OUTER_LOOP_REPO} "
                           f"merged:>={since}"),
                "issues": f"is:issue is:open archived:false org:{config.ORG}"}
        pages, after = [], None
        while True:
            variables = {**base, "first": after is None, **({"after": after} if after else {})}
            data = self._graphql(BOARD_QUERY, variables)
            pages.append(data)
            info = data["organization"]["projectV2"]["items"]["pageInfo"]
            if not info["hasNextPage"]:
                return pages
            after = info["endCursor"]

    def board(self, today: date) -> Board:
        """The whole board with the org-wide views (scope of the hourly run)."""
        return parse_board(self.board_pages(today))

    def card(self, repo: str, number: int) -> Card:
        """One card (scope of an event on one issue).

        Raises:
            NotAnIssue: the number is a pull request.
            OffProject: the issue is not on the project.
            NotFound: GitHub cannot resolve the repository or the number.
        """
        owner, name = repo.split("/", 1)
        data = self._graphql(CARD_QUERY, {"owner": owner, "name": name, "number": number})
        issue = (data.get("repository") or {}).get("issueOrPullRequest")
        if issue and issue.get("__typename") == "PullRequest":
            raise NotAnIssue(f"{repo}#{number} is a pull request")
        if not issue:
            raise NotFound(f"{repo}#{number} not found")
        items = [n for n in issue["projectItems"]["nodes"]
                 if n["project"]["number"] == config.PROJECT_NUMBER]
        if not items:
            raise OffProject(parse_card({}, issue).ref)
        return parse_card(items[0], issue)
