"""dispatch(board): which Goal card starts on which free instance (D1, D3..D9).

A decision about the whole board: free instances, overlapping Allowed files and the order of the
Goal column belong to it. Stuck Action cards (D2, see checks) no longer hold their instance.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from loop import config
from loop.model import Board, Card
from loop.rules.checks import is_stuck
from loop.rules.failed_start import start_failed


@dataclass(frozen=True)
class Start:
    """Start this card on this instance; ``busy`` are the instances still at work in this run."""

    card: Card
    instance: str
    busy: frozenset[str] = frozenset()


@dataclass
class Dispatch:
    """The dispatcher's decisions for one run."""

    starts: list[Start] = field(default_factory=list)
    blocked: list[tuple[Card, str]] = field(default_factory=list)  # (card, reason): comment once
    waiting: list[Card] = field(default_factory=list)  # overlap or no free instance: silent
    # the starts again without the given cards: a failed start frees its instance in the same run
    replan: Callable[[frozenset[tuple[str, int]]], list[Start]] | None = None
    started: list[Start] = field(default_factory=list)  # filled by apply: the starts that worked
    failed: list[Start] = field(default_factory=list)  # filled by apply: the starts that failed


def overlaps(first: Iterable[str], second: Iterable[str]) -> bool:
    """True if two lists of paths or globs can touch the same file (D8)."""
    second = tuple(second)
    return any(a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a)
               for a in first for b in second)


def why_not(card: Card, access: Callable[[str], str | None]) -> str | None:
    """The reason a Goal card cannot start, independent of the other cards (D4, D6, D7, D9)."""
    if card.task.is_feature:
        return "a feature is never started, pull its tasks"  # D4
    blockers = card.open_blockers
    if blockers:
        return "blocked by " + ", ".join(f"#{b.number}" for b in blockers)  # D6
    if not card.task.has_order:
        return "the task has no `Branch:` or no `Allowed files` line"  # D7
    return access(card.ref.repo)  # D9: None when both bots can write


def job_instances(jobs: set[str] | None) -> set[str]:
    """Instances with a scheduled developer job (``<instance>-<repo>-<number>``): still at work."""
    return {i for i in config.INSTANCES for name in (jobs or ()) if name.startswith(f"{i}-")}


def own_instance(card: Card) -> str | None:
    """D3: the instance a round 2+ card must return to, None if any free instance will do.

    From round 2 the branch is pushed and checked out in the worktree of the instance the card
    had; git allows a branch in one worktree only, so the card waits for that instance.
    """
    inst = card.state.instance
    return inst if inst in config.INSTANCES and card.open_prs else None


def held_by_owner(card: Card) -> bool:
    """D5: the round limit handed it to the owner, who decides."""
    return config.OWNER in card.assignees and bool(card.open_prs)


def dispatch(board: Board, jobs: set[str] | None, now: datetime,
             access: Callable[[str], str | None],
             skip: frozenset[tuple[str, int]] = frozenset()) -> Dispatch:
    """Decide the starts of this run.

    Args:
        board: The board in its order.
        jobs: Names of the scheduled developer jobs, None if unknown (then nothing is stuck).
        now: The time of the run.
        access: Repo -> None if both bots can write, else the reason (D9).
        skip: Cards whose start failed or waits in this run: the next card takes the instance.

    Returns:
        Starts, blocked cards with their reason, and silently waiting cards.
    """
    active = [c for c in board.cards if c.state.is_open and c.state.status == "Action"
              and not is_stuck(c, jobs, now)]
    busy = {c.state.instance for c in active} | job_instances(jobs)
    free = [i for i in config.INSTANCES if i not in busy]  # D1
    running = [(c.ref.repo, c.task.allowed_files) for c in active]
    result = Dispatch()
    for card in (c for c in board.cards if c.state.is_open and c.state.status == "Goal"):  # D3
        if held_by_owner(card) or start_failed(card) or card.key in skip:
            continue  # D5; D11: a failed start waits with the Lead until the card changes
        reason = why_not(card, access)
        if reason:
            result.blocked.append((card, reason))
            continue
        files = card.task.allowed_files
        own = own_instance(card)
        if not free or (own and own not in free) \
                or any(r == card.ref.repo and overlaps(files, o) for r, o in running):
            result.waiting.append(card)  # D8, no free instance, or its own instance is busy
            continue
        inst = card.state.instance if card.state.instance in free else free[0]
        result.starts.append(Start(card, inst, frozenset(busy)))
        free.remove(inst)
        running.append((card.ref.repo, files))
    return result
