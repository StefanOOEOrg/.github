"""Data model of the loop engine: what the rules read, built once per run from GitHub.

Frozen dataclasses, no I/O. The task order lives in the issue body: a `Branch: \\`x\\`` line
(optionally `(base: \\`y\\`)`) and an `Allowed files: \\`a\\` \\`b/*\\`` line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

BRANCH_RE = re.compile(r"Branch:\s*`([^`]+)`(?:\s*\(base:\s*`([^`]+)`\))?")
ALLOWED_RE = re.compile(r"Allowed files:(.*)")
CLOSING_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", re.IGNORECASE)


@dataclass(frozen=True)
class Ref:
    """Where an issue or PR lives."""

    repo: str
    number: int
    url: str = ""
    owner: str = ""  # PR: owner of the head repository (a fork if not the org)
    writable: bool = True  # the Lead may triage/write in this repository (assignees, status)


@dataclass(frozen=True)
class Review:
    """One submitted PR review."""

    author: str
    state: str  # APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED
    commit: str
    submitted_at: datetime | None = None
    first_line: str = ""


@dataclass(frozen=True)
class PullRequest:
    """A pull request, as linked to a card or found in the org."""

    ref: Ref
    state: str  # OPEN, CLOSED, MERGED
    head: str
    body: str = ""
    requested: frozenset[str] = frozenset()
    reviews: tuple[Review, ...] = ()
    ci: str | None = None  # statusCheckRollup of the head commit, None without checks

    @property
    def is_open(self) -> bool:
        """True while the PR is open."""
        return self.state == "OPEN"

    @property
    def has_closing_line(self) -> bool:
        """True if the body links an issue with Closes/Fixes/Resolves #n."""
        return CLOSING_RE.search(self.body or "") is not None

    def last_review(self, login: str) -> Review | None:
        """The latest review of one person, or None."""
        mine = [r for r in self.reviews if r.author == login]
        return mine[-1] if mine else None

    def change_requests(self, login: str) -> int:
        """How many formal change requests one person made on this PR."""
        return sum(r.author == login and r.state == "CHANGES_REQUESTED" for r in self.reviews)


@dataclass(frozen=True)
class Blocker:
    """An issue that blocks a card."""

    repo: str
    number: int
    is_open: bool

    @property
    def key(self) -> tuple[str, int]:
        """Repository and number."""
        return self.repo, self.number


@dataclass(frozen=True)
class CardState:
    """Board fields and lifecycle of a card."""

    is_open: bool
    status: str | None
    changed: datetime | None = None  # when the Status value was last set
    instance: str | None = None
    closed_at: datetime | None = None
    item: str = ""  # project item id (for field writes and archiving)
    reopened_at: datetime | None = None  # the issue's latest reopen


@dataclass(frozen=True)
class Task:
    """The issue as a work order."""

    body: str = ""
    issue_type: str | None = None
    sub_issues: int = 0

    @property
    def is_feature(self) -> bool:
        """True for the issue type Feature (never started, its tasks are)."""
        return self.issue_type == "Feature"

    @property
    def branch(self) -> tuple[str, str] | None:
        """(branch, base) of the task order, or None."""
        match = BRANCH_RE.search(self.body or "")
        return (match.group(1), match.group(2) or "main") if match else None

    @property
    def allowed_files(self) -> tuple[str, ...]:
        """Paths and globs of the Allowed files line."""
        line = ALLOWED_RE.search(self.body or "")
        return tuple(re.findall(r"`([^`]+)`", line.group(1))) if line else ()

    @property
    def has_order(self) -> bool:
        """True if the dispatcher can start it: Branch line and Allowed files line."""
        return self.branch is not None and "Allowed files:" in (self.body or "")

    @property
    def refined(self) -> bool:
        """A task is refined with its Branch line; a feature once it has sub-issues."""
        return self.sub_issues > 0 if self.is_feature else self.branch is not None


@dataclass(frozen=True)
class Activity:
    """The latest human signals on an issue."""

    assigned_by: str | None = None  # actor of the latest assignment
    assigned_to: str | None = None  # assignee of the latest assignment
    assigned_at: datetime | None = None
    commented_by: str | None = None  # author of the latest comment
    commented_at: datetime | None = None


@dataclass(frozen=True)
class Card:
    """One issue on the board together with what the rules need about it."""

    ref: Ref
    state: CardState
    task: Task = Task()
    assignees: frozenset[str] = frozenset()
    blockers: tuple[Blocker, ...] = ()
    prs: tuple[PullRequest, ...] = ()
    activity: Activity = Activity()

    @property
    def key(self) -> tuple[str, int]:
        """Repository and number: unique across the org."""
        return self.ref.repo, self.ref.number

    @property
    def open_prs(self) -> tuple[PullRequest, ...]:
        """The linked PRs that are still open."""
        return tuple(p for p in self.prs if p.is_open)

    @property
    def open_blockers(self) -> tuple[Blocker, ...]:
        """The blockers that are still open."""
        return tuple(b for b in self.blockers if b.is_open)


@dataclass(frozen=True)
class Board:
    """The board in its order, plus the org-wide views a full run reads in the same query."""

    cards: tuple[Card, ...]
    open_prs: tuple[PullRequest, ...] = ()  # every open PR of the org (W5, W6)
    merged_outer_loop: tuple[PullRequest, ...] = ()  # .github PRs merged since yesterday (W15)
    off_board: tuple[Ref, ...] = ()  # open org issues missing from the project (W7)

    def by_key(self) -> dict[tuple[str, int], Card]:
        """Cards by (repo, number)."""
        return {c.key: c for c in self.cards}
