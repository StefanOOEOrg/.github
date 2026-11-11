"""A failed start (D11): the card waits on Goal with the Lead until it changes.

Stateless, from what GitHub keeps: the engine's comment on the failed start carries ``MARKER``.
While that comment is the card's latest one and nothing changed on the card after it, the
dispatcher skips the card and the Lead is its assignee. A change is a newer comment (by anyone),
an edit of the body, a status change, a reopen, or an assignment that is not the engine's own
assignment of the Lead.
"""

from __future__ import annotations

from loop import config
from loop.model import Card

MARKER = "<!-- loop:start-failed -->"


def failed_start_text(step: str, detail: str) -> str:
    """The comment on a failed start; its marker makes the dispatcher skip the card."""
    cause = f": {detail}" if detail else ""
    return (f"Not started: the start failed while {step}{cause}. The card stays on Goal, assigned "
            "to the Lead, and the dispatcher skips it until the card changes (a comment, an edit "
            "of the body, a status change or a new assignment), then it tries again.\n\n"
            f"{MARKER}")


def start_failed(card: Card) -> bool:
    """True while the engine's failed-start comment is the latest thing that happened to it."""
    act = card.activity
    since = act.commented_at
    if since is None or MARKER not in card.task.last_comment:
        return False
    later = [at for at in (act.edited_at, card.state.changed, card.state.reopened_at)
             if at and at > since]
    own = act.assigned_by == config.LEAD and act.assigned_to == config.LEAD
    if act.assigned_at and act.assigned_at > since and not own:
        later.append(act.assigned_at)
    return not later
