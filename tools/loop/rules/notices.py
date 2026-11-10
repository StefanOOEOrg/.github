"""inbox: notices to the Lead (W1..W3 per PR, W8, W9, W11 per card, W15 per merged .github PR)
and W4, the owner's review request the engine posts itself.

A notice is repeated after ``REMIND_MINUTES`` while it is still due, unless it is ``once``; that
bookkeeping is the store's job, the rules only say what is due now.
"""

from __future__ import annotations

from loop import config
from loop.model import Card, PullRequest
from loop.rules.assignee import triage_turn
from loop.rules.checks import Finding


def _name(pr: PullRequest) -> str:
    return f"{pr.ref.repo}#{pr.ref.number} {pr.ref.url}"


def pr_notices(pr: PullRequest) -> list[Finding]:
    """W1..W3: what an open PR needs from the Lead."""
    found = []
    name = _name(pr)
    owner = pr.last_review(config.OWNER)
    if config.LEAD in pr.requested:
        found.append(Finding(f"review:{pr.ref.url}", f"Inbox – Review wartet: {name}"))  # W1
    if owner and owner.state == "APPROVED":
        found.append(Finding(f"merge:{pr.ref.url}",
                             f"Inbox – Stefan hat approved, mergen: {name}"))  # W2
    if owner and owner.state == "CHANGES_REQUESTED" and owner.commit == pr.head:  # W3
        text = f"Inbox – Stefan will Änderungen: {name}\n  {owner.first_line[:200]}".rstrip()
        found.append(Finding(f"changes:{pr.ref.url}@{pr.head}", text))
    return found


def owner_review_due(pr: PullRequest) -> bool:
    """W4: the Lead approved the current head and the owner is not asked yet -> the engine asks.

    Again after every new Lead approval the owner has not reviewed since. Not in the outer loop
    repository (the owner authors those PRs and cannot be asked).
    """
    owner, lead = pr.last_review(config.OWNER), pr.last_review(config.LEAD)
    if pr.ref.repo.split("/")[-1] == config.OUTER_LOOP_REPO or config.OWNER in pr.requested:
        return False
    if not lead or lead.state != "APPROVED" or lead.commit != pr.head:
        return False
    return not owner or bool(owner.submitted_at and lead.submitted_at
                             and owner.submitted_at < lead.submitted_at)


def card_notices(card: Card) -> list[Finding]:
    """W8, W9, W11: what a card needs from the Lead."""
    found = []
    act = card.activity
    name = f"{card.ref.repo}#{card.ref.number} {card.ref.url}"
    lead_turn = card.state.status == "Triage" and triage_turn(card) == config.LEAD
    if act.commented_by == config.OWNER and (config.LEAD in card.assignees or lead_turn):  # W8
        found.append(Finding(f"owner-comment:{card.ref.url}@{act.commented_at}",
                             f"Inbox – Stefan hat kommentiert: {name}"))
    answered = (act.commented_by == config.LEAD and act.commented_at and act.assigned_at
                and act.commented_at > act.assigned_at)
    if act.assigned_by == config.OWNER and act.assigned_to == config.LEAD and not answered:  # W9
        found.append(Finding(f"owner-assigned:{card.ref.url}@{act.assigned_at}",
                             f"Inbox – Stefan hat dir das zugewiesen: {name}"))
    new = triage_new(card)
    if new:
        found.append(new)
    if card.state.status == "Goal" and not card.task.has_order and not card.task.is_feature:  # W11
        found.append(_refine(card, name))
    return found


def _refine(card: Card, name: str) -> Finding:
    """W11: refine an unrefined Goal card, unless a linked PR is merged: then ask instead (#80)."""
    merged = [p.ref.number for p in card.prs if p.state == "MERGED"]
    if merged:
        return Finding(f"merged-on-goal:{card.ref.url}", "plan: ⚠️ auf Goal, aber die Arbeit ist "
                       f"schon gemergt (PR #{merged[0]}), schließen oder klären: {name}", once=True)
    return Finding(f"refine:{card.ref.url}", "Inbox – auf Goal gezogen, aber nicht "
                   f"verfeinert, jetzt verfeinern: {name}")


def triage_new(card: Card) -> Finding | None:
    """A Triage card the Lead has to refine and was not told about otherwise (once)."""
    act = card.activity
    told = act.assigned_to == config.LEAD or config.LEAD in (act.commented_by, act.edited_by,
                                                            card.ref.author)
    if card.state.status != "Triage" or card.task.refined or told:
        return None
    if triage_turn(card) != config.LEAD:
        return None
    return Finding(f"triage-new:{card.ref.url}", f"Neu im Project (Triage): {card.ref.repo}#"
                   f"{card.ref.number} {card.ref.url}", once=True)


def post_merge(pr: PullRequest) -> Finding:
    """W15: the Lead reviews a merged .github PR afterwards (reported once)."""
    return Finding(f"postmerge:{pr.ref.url}",
                   f"Inbox – nach dem Merge prüfen: #{pr.ref.number} {pr.ref.url}", once=True)
