"""assignee(card): exactly one assignee per card, whoever acts next. First matching rule wins.

A1..A10 are the rules of assignee_sync.next_actor, P1..P3 the blocker rules of its plan().
"""

from __future__ import annotations

from loop import config
from loop.model import Board, Card, PullRequest

MANUAL_WINS = ("Triage", "Backlog", "Verify", None)  # a manual assignment of the owner wins (A2)


def manual_assignee(card: Card) -> str | None:
    """The person the product owner assigned by hand, while that assignment still wins (A2)."""
    act = card.activity
    by_owner = act.assigned_by == config.OWNER and act.assigned_to in card.assignees
    return act.assigned_to if by_owner and card.state.status in MANUAL_WINS else None


def pr_actor(pr: PullRequest) -> str:
    """Who acts next on an open PR (A3)."""
    if config.LEAD in pr.requested:
        return config.LEAD
    owner = pr.last_review(config.OWNER)
    if owner and owner.state == "APPROVED":
        return config.LEAD  # merge
    lead = pr.last_review(config.LEAD)
    if lead and lead.state == "APPROVED":
        return config.OWNER
    if lead and lead.state == "CHANGES_REQUESTED":
        limited = pr.change_requests(config.LEAD) >= config.ROUND_LIMIT
        return config.OWNER if limited else config.DEV
    return config.LEAD


def _goal(card: Card) -> str:
    """A4: without a task order the Lead refines it; A6: else the developer."""
    return config.DEV if card.task.has_order else config.LEAD


def _action(card: Card) -> str:
    """A5: handed over to the owner as stuck (D2); A6: else the developer."""
    return config.OWNER if config.OWNER in card.assignees else config.DEV


def _triage(card: Card) -> str:
    """A9: refined or held by the owner -> owner, else the Lead refines it."""
    held = card.task.refined or config.OWNER in card.assignees
    return config.OWNER if held else config.LEAD


def _backlog(card: Card) -> str | None:
    """A10: nobody, or the owner while he holds it."""
    return config.OWNER if config.OWNER in card.assignees else None


STATUS_ACTOR = {
    "Goal": _goal,
    "Action": _action,
    "Verify": lambda card: config.LEAD,  # A7: Verify without PR, the board is wrong
    "Done": lambda card: config.OWNER,  # A8: open but outside the flow
    None: lambda card: config.OWNER,  # A8
    "Triage": _triage,
    "Backlog": _backlog,
}


def next_actor(card: Card) -> str | None:
    """The login that acts next on this card alone, or None for nobody (A1..A10)."""
    if not card.state.is_open:
        return None  # A1
    manual = manual_assignee(card)
    if manual:
        return manual  # A2
    if card.open_prs:
        return pr_actor(card.open_prs[0])  # A3
    return STATUS_ACTOR.get(card.state.status, _backlog)(card)


def _parked(card: Card) -> bool:
    """An open Backlog card nobody assigned by hand: only the owner can pull it."""
    return card.state.is_open and card.state.status == "Backlog" and manual_assignee(card) is None


def plan(board: Board) -> dict[tuple[str, int], str | None]:
    """The next actor per card, following the blockers of the cards on Goal (P1..P3)."""
    cards = board.by_key()
    wants = {key: next_actor(card) for key, card in cards.items()}
    waiting = {key: [b.key for b in card.open_blockers] for key, card in cards.items()
               if card.state.status == "Goal" and card.state.is_open}
    waiting = {key: blockers for key, blockers in waiting.items() if blockers}
    for blockers in waiting.values():
        for blocker in blockers:
            if blocker in cards and _parked(cards[blocker]):
                wants[blocker] = config.OWNER  # P1: it stops a pulled card
    for key, blockers in waiting.items():
        if not any(b in cards for b in blockers):
            wants[key] = config.OWNER  # P2: the blocker is not on the board
    for _ in range(config.MAX_BLOCKER_CHAIN):  # P3: one link of a chain per pass
        for key, blockers in waiting.items():
            known = [wants[b] for b in blockers if wants.get(b)]
            if known:
                wants[key] = known[0]
    return wants


def round_limit_pr(card: Card) -> int | None:
    """The number of an open PR on which the Lead reached the round limit, else None."""
    for pr in card.open_prs:
        last = pr.last_review(config.LEAD)
        if last and last.state == "CHANGES_REQUESTED" \
                and pr.change_requests(config.LEAD) >= config.ROUND_LIMIT:
            return pr.ref.number
    return None
