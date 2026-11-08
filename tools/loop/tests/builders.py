"""Small builders for rule tests: a card or PR in one line, defaults for everything else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loop import config
from loop.model import (
    Activity,
    Blocker,
    Board,
    Card,
    CardState,
    PullRequest,
    Ref,
    Review,
    Task,
)

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
REPO = "StefanOOEOrg/repo-a"
ORDER = "Branch: `wp/x`\nAllowed files: `src/a.py`"


def ago(minutes: float) -> datetime:
    """A time ``minutes`` before NOW."""
    return NOW - timedelta(minutes=minutes)


def review(author: str, state: str, commit: str = "h1", minutes_ago: float = 10) -> Review:
    """One review."""
    return Review(author, state, commit, ago(minutes_ago))


def pr(*reviews: Review, **extra) -> PullRequest:
    """A PR with reviews in order; ``extra``: number, state, requested, head, body, ci, repo."""
    number = extra.get("number", 7)
    ref = Ref(extra.get("repo", REPO), number, f"https://x/{number}")
    return PullRequest(ref, extra.get("state", "OPEN"), extra.get("head", "h1"),
                       extra.get("body", "Closes #1"), frozenset(extra.get("requested", ())),
                       tuple(reviews), extra.get("ci", "SUCCESS"))


def card(number: int = 1, status: str | None = "Goal", *, body: str = ORDER,
         is_open: bool = True, **extra) -> Card:
    """A card; ``extra`` sets assignees, blockers, prs, activity, instance, changed, task, repo."""
    state = CardState(is_open, status, extra.get("changed"), extra.get("instance"),
                      extra.get("closed_at"), reopened_at=extra.get("reopened_at"))
    task = extra.get("task") or Task(body, extra.get("issue_type"), extra.get("sub_issues", 0))
    blockers = tuple(Blocker(REPO, n, True) for n in extra.get("blocked_by", ()))
    return Card(Ref(extra.get("repo", REPO), number, f"https://x/i{number}"), state, task,
                frozenset(extra.get("assignees", ())), blockers, tuple(extra.get("prs", ())),
                extra.get("activity", Activity()))


def board(*cards: Card) -> Board:
    """A board in this order."""
    return Board(tuple(cards))


OWNER, LEAD, DEV = config.OWNER, config.LEAD, config.DEV
