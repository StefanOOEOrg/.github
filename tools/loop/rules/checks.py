"""checks: anomalies the process must not hide (D2, W5, W6, W12, W13).

Time rules kept by decision of 7.11.: D2 (stuck Action card) and W6 (approve reminder).
W10, W14 and W16 are dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from loop import config
from loop.model import Card, PullRequest
from loop.rules.status import round_done


@dataclass(frozen=True)
class Finding:
    """One anomaly. ``key`` dedupes it in the local "already reported" store."""

    key: str
    text: str
    once: bool = False  # reported a single time, never repeated


def job_suffix(card: Card) -> str:
    """The developer job of a card is named ``<instance>-<repo>-<number>``."""
    return f"-{card.ref.repo.split('/')[-1]}-{card.ref.number}"


def is_stuck(card: Card, jobs: set[str] | None, now: datetime,
             minutes: int = config.STUCK_MINUTES) -> bool:
    """D2: Action, no scheduled developer job, for ``minutes`` since it got Action, and the round
    not handed to review: no linked PR, or an open PR without the Lead's review request (#75).

    ``jobs`` None means the job list is unknown: then nothing counts as stuck.
    """
    if jobs is None or not card.state.is_open or card.state.status != "Action" or round_done(card):
        return False
    if any(name.endswith(job_suffix(card)) for name in jobs):
        return False
    changed = card.state.changed
    return changed is not None and now - changed >= timedelta(minutes=minutes)


def card_findings(card: Card) -> list[Finding]:
    """W12 and W13: the board contradicts the PRs."""
    found = []
    name = f"{card.ref.repo}#{card.ref.number} {card.ref.url}"
    if card.state.status == "Triage" and card.open_prs:
        found.append(Finding(f"triage-pr:{card.ref.url}",
                             f"PR #{card.open_prs[0].ref.number} zu einer Triage-Karte, "
                             f"die nicht begonnen werden darf: {name}"))
    if card.state.status == "Verify" and not card.open_prs:
        found.append(Finding(f"board:{card.ref.url}",
                             f"board: ⚠️ steht auf Verify ohne verlinkten PR: {name}"))
    return found


def orphan_pr(pr: PullRequest) -> Finding | None:
    """W5: an open PR without a Closes line (the outer loop repository is exempt)."""
    if pr.ref.repo.split("/")[-1] == config.OUTER_LOOP_REPO or pr.has_closing_line:
        return None
    text = f"pr: ⚠️ ohne Closes-Zeile: {pr.ref.repo}#{pr.ref.number} {pr.ref.url}"
    return Finding(f"orphan:{pr.ref.url}", text, once=True)


def approve_reminder(pr: PullRequest, now: datetime) -> Finding | None:
    """W6: the owner is requested, the Lead approved the current head, CI is green, 2 h passed.

    The key carries the head, so a new push restarts the reminder; the 24 h repeat is the
    store's job (``OWNER_REPEAT_HOURS``).
    """
    lead = [r for r in pr.reviews if r.author == config.LEAD and r.commit == pr.head]
    approved = lead[-1] if lead else None
    if config.OWNER not in pr.requested or not approved or approved.state != "APPROVED":
        return None
    if pr.ci not in (None, "SUCCESS") or approved.submitted_at is None:
        return None
    waited = now - approved.submitted_at
    if waited < timedelta(hours=config.OWNER_WAIT_HOURS):
        return None
    hours = int(waited.total_seconds() // 3600)
    return Finding(f"remind:{pr.ref.url}@{pr.head}",
                   f"@{config.OWNER} this PR has waited {hours} h only for your approval: the Lead "
                   f"approved the current head `{pr.head[:7]}`, CI is green. After your approval "
                   "the Lead merges it.")
