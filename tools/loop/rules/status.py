"""status(card): the Status transitions the engine owns (all project workflows are off).

The engine only sets its own transitions and leaves the ones made by hand alone: Backlog and Goal
are the product owner's, with one exception: the Lead's change request on the current head sends a
Verify card back to Goal for the next round (#81). Evaluated level-triggered from the facts, so a
missed event is repaired by the next run.
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
    if status == "Action" and round_done(card):
        return "Verify"  # a PR is linked and the developer handed it to review
    if status == "Verify" and next_round(card):
        return "Goal"  # the Lead requested changes: the dispatcher starts the next round
    closed_unmerged = card.prs and not any(p.state == "MERGED" for p in card.prs)
    if status == "Verify" and verify_back_to_action and not card.open_prs and closed_unmerged:
        return "Action"
    return None


def round_done(card: Card) -> bool:
    """True if a developer round on Action is finished: an open PR asks the Lead for a review.

    In round 2+ the PR is open from the start, so an open PR alone is not the end of the round:
    the developer requests the Lead's review as the last step of every round. A review submitted
    after the card got Action counts as well (the request is gone once the Lead has reviewed).
    """
    since = card.state.changed
    for pr in card.open_prs:
        if config.LEAD in pr.requested:
            return True
        if since and any(r.submitted_at and r.submitted_at > since for r in pr.reviews):
            return True
    return False


def next_round(card: Card) -> bool:
    """True if the Lead's latest review requests changes on the head of an open PR (#81).

    Only on the current head: a change request on a superseded commit was already answered by a
    push. From ``ROUND_LIMIT`` change requests on the PR the product owner decides instead, so the
    card stays on Verify with the owner as assignee.
    """
    for pr in card.open_prs:
        lead = pr.last_review(config.LEAD)
        if lead and lead.state == "CHANGES_REQUESTED" and lead.commit == pr.head \
                and pr.change_requests(config.LEAD) < config.ROUND_LIMIT:
            return True
    return False


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
