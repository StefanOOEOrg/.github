"""status(card): the Status transitions the engine owns (all project workflows are off).

The engine only sets its own transitions and leaves the ones made by hand alone: Backlog and Goal
are the product owner's. Evaluated level-triggered from the facts, so a missed event is repaired
by the next run.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from loop import config
from loop.model import Card


def transition(card: Card, *,
               verify_back_to_action: bool = config.VERIFY_BACK_TO_ACTION) -> str | None:
    """Return the Status the card should have now, or None if the engine leaves it as it is.

    Args:
        card: The card with its linked PRs.
        verify_back_to_action: Proposal switch: Verify -> Action when no linked PR is open
            and none was merged (the PR was closed without a merge).

    Returns:
        The desired Status, or None for no change.
    """
    status = card.state.status
    if not card.state.is_open:
        return "Done" if status != "Done" else None
    if status is None:
        return "Triage"  # item added to the project
    if status == "Done":
        return "Triage" if reopened_after_done(card) else None  # else: closed, see close_due
    if status == "Action" and card.open_prs:
        return "Verify"  # a PR is linked
    closed_unmerged = card.prs and not any(p.state == "MERGED" for p in card.prs)
    if status == "Verify" and verify_back_to_action and not card.open_prs and closed_unmerged:
        return "Action"
    return None


def reopened_after_done(card: Card) -> bool:
    """True if the open issue was reopened after its Status was last set (to Done).

    Without that, the card was moved to Done by hand: the engine closes the issue instead of
    sending the card back to Triage.
    """
    reopened, changed = card.state.reopened_at, card.state.changed
    return reopened is not None and (changed is None or reopened > changed)


def close_due(card: Card) -> bool:
    """True if the issue must be closed: open on Done, moved there by hand (not reopened)."""
    return card.state.is_open and card.state.status == "Done" and not reopened_after_done(card)


def archive_due(card: Card, now: datetime, days: int = config.ARCHIVE_DAYS) -> bool:
    """True if a closed Done card has been closed long enough to be archived."""
    closed = card.state.closed_at
    return (card.state.status == "Done" and not card.state.is_open and closed is not None
            and now - closed >= timedelta(days=days))
