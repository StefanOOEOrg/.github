"""decide(): every rule over the scope -> what differs from the desired state.

Pure: board, scheduled developer jobs, time and write access in, ``Decisions`` out. ``apply``
executes them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from loop import config
from loop.model import Board, Card, PullRequest, Ref
from loop.rules.assignee import plan
from loop.rules.checks import (
    Finding,
    approve_reminder,
    card_findings,
    is_stuck,
    orphan_pr,
)
from loop.rules.dispatch import Start, dispatch
from loop.rules.notices import card_notices, post_merge, pr_notices
from loop.rules.status import archive_due, close_due, transition


@dataclass
class BoardChanges:
    """Field and item changes on the board."""

    status: list[tuple[Card, str]] = field(default_factory=list)  # (card, wanted status)
    assignee: list[tuple[Card, str | None]] = field(default_factory=list)  # (card, wanted actor)
    archive: list[Card] = field(default_factory=list)
    close: list[Card] = field(default_factory=list)  # moved to Done by hand, issue still open
    add: list[Ref] = field(default_factory=list)  # W7: open org issues missing from the project


@dataclass
class Decisions:
    """What the engine has to do in this run."""

    board: BoardChanges = field(default_factory=BoardChanges)
    starts: list[Start] = field(default_factory=list)
    blocked: list[tuple[Card, str]] = field(default_factory=list)  # comment once while it lasts
    stuck: list[Card] = field(default_factory=list)  # D2: hand over to the owner
    notices: list[Finding] = field(default_factory=list)  # to the Lead, via stdout
    reminders: list[tuple[PullRequest, Finding]] = field(default_factory=list)  # W6 PR comments


def card_decisions(card: Card, want: str | None, jobs: set[str] | None, now: datetime,
                   out: Decisions) -> None:
    """The per-card part: status, assignee, stuck, archive, notices."""
    status = transition(card)
    if status:
        out.board.status.append((card, status))
    if card.ref.writable and set(card.assignees) != ({want} if want else set()):
        out.board.assignee.append((card, want))
    if is_stuck(card, jobs, now) and config.OWNER not in card.assignees:
        out.stuck.append(card)
    if close_due(card) and card.ref.writable:
        out.board.close.append(card)
    if archive_due(card, now):
        out.board.archive.append(card)
    if card.state.is_open:
        out.notices += card_notices(card) + card_findings(card)


def decide(board: Board, jobs: set[str] | None, now: datetime,
           access: Callable[[str], str | None]) -> Decisions:
    """The full run: every card, the dispatcher and the org-wide views."""
    out = Decisions()
    wants = plan(board)
    for card in board.cards:
        card_decisions(card, wants[card.key], jobs, now, out)
    starts = dispatch(board, jobs, now, access)
    out.starts, out.blocked = starts.starts, starts.blocked
    for pr in board.open_prs:
        out.notices += pr_notices(pr)
        orphan = orphan_pr(pr)
        if orphan:
            out.notices.append(orphan)
        reminder = approve_reminder(pr, now)
        if reminder:
            out.reminders.append((pr, reminder))
    out.notices += [post_merge(pr) for pr in board.merged_outer_loop]
    out.board.add = list(board.off_board)
    return out
