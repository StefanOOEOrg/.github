"""apply(): turn ``Decisions`` into GitHub writes and the lines for the Lead (stdout).

One failing write must not stop the others: each is logged and the run goes on.
"""

from __future__ import annotations

import logging
from datetime import datetime

from loop import config
from loop.engine import Decisions
from loop.github_client import GitHubError
from loop.model import Card
from loop.rules.assignee import round_limit_pr
from loop.rules.dispatch import Dispatch
from loop.rules.failed_start import failed_start_text
from loop.starter import Failure, start
from loop.store import Store
from loop.writer import GitHubWriter

logger = logging.getLogger(__name__)


def _safely(what: str, action, *args) -> bool:
    """Run one write; log and continue on failure."""
    try:
        action(*args)
        return True
    except (GitHubError, StopIteration, KeyError, ValueError) as error:
        logger.error("%s failed: %s", what, error)
        return False


def _assign(card: Card, want: str | None, writer: GitHubWriter, store: Store,
            now: datetime) -> None:
    have = set(card.assignees)
    add, remove = ({want} if want else set()) - have, have - ({want} if want else set())
    if _safely("assignees", writer.assignees, card, add, remove) and want == config.OWNER:
        limited = round_limit_pr(card)
        if limited and store.first_comment(f"round:{card.ref.url}#{limited}", now):
            _safely("comment", writer.comment, card.ref,
                    f"@{config.OWNER} round limit reached: {config.ROUND_LIMIT} change requests on "
                    f"#{limited}. The open findings are in its latest review.")


def _board(out: Decisions, writer: GitHubWriter, store: Store, now: datetime) -> list[str]:
    for card, status in out.board.status:
        _safely("status", writer.set_field, card.state.item, "Status", status)
    for card, want in out.board.assignee:
        _assign(card, want, writer, store, now)
    for card in out.board.close:
        _safely("close", writer.close, card)
    for card in out.board.archive:
        _safely("archive", writer.archive, card)
    added = []
    for ref in out.board.add:
        try:
            item = writer.add_item(ref)
        except (GitHubError, ValueError) as error:
            logger.error("adding %s#%s failed: %s", ref.repo, ref.number, error)
            continue
        if item:
            _safely("status", writer.set_field, item, "Status", "Triage")
        if ref.author != config.LEAD:  # the Lead filed it himself: no news for him (#84)
            added.append(f"Neu im Project (Triage): {ref.repo}#{ref.number} {ref.url}")
    return added


def _stuck_text(card: Card) -> str:
    """D2 handover: what is missing, a PR or the review request on the open PR (#75)."""
    missing = (f"a review request on PR #{card.open_prs[0].ref.number}" if card.open_prs
               else "a PR")
    return (f"@{config.OWNER} Stuck: on Action for {config.STUCK_MINUTES} minutes without "
            f"{missing} and without a developer job. Move it back to Goal to start it again.")


def _comments(out: Decisions, writer: GitHubWriter, store: Store, now: datetime) -> None:
    for card, reason in out.dispatch.blocked:
        if store.first_comment(f"{card.ref.url}|{reason}", now):
            _safely("comment", writer.comment, card.ref,
                    f"Not started: {reason}. It stays on Goal and starts as soon as this is "
                    "resolved.")
    for card in out.stuck:
        if store.first_comment(f"{card.ref.url}|stuck", now):
            _safely("comment", writer.comment, card.ref, _stuck_text(card))
            _safely("assignees", writer.assignees, card, {config.OWNER}, set())
    for pr in out.ask_owner:
        _safely("review request", writer.request_review, pr.ref, config.OWNER)
    for pr, reminder in out.reminders:
        if store.reminder_due(reminder.key, now):
            _safely("reminder", writer.comment, pr.ref, reminder.text)


def _failed(card: Card, failure: Failure, writer: GitHubWriter) -> str:
    """D11: comment the cause with the skip marker, hand the card to the Lead, tell the Lead."""
    _safely("comment", writer.comment, card.ref, failed_start_text(failure.step, failure.detail))
    remove = (set(card.assignees) | {config.DEV}) - {config.LEAD}
    _safely("assignees", writer.assignees, card, {config.LEAD}, remove)
    cause = f"{failure.step}: {failure.detail}" if failure.detail else failure.step
    return (f"Start fehlgeschlagen: {card.ref.repo}#{card.ref.number} ({cause}). Bleibt auf Goal "
            f"beim Lead und wird übersprungen, bis sich die Karte ändert: {card.ref.url}")


def _starts(run: Dispatch, writer: GitHubWriter, now: datetime) -> tuple[list[str], list[str]]:
    """Run the planned starts; a card that fails or waits frees its instance for the next one.

    Returns (lines for the Lead, lines for the local log).
    """
    lead, log = [], []
    tried: set[tuple[str, int]] = set()
    plan = list(run.starts)
    while plan:
        planned = plan.pop(0)
        card = planned.card
        if card.key in tried:
            continue  # started before a replan: the replan keeps the order before a failure
        tried.add(card.key)
        result = start(card, planned.instance, writer, planned.busy)
        if result is None:
            run.started.append(planned)
            moved = card.state.changed
            seconds = f", Goal→Action {round((now - moved).total_seconds())} s" if moved else ""
            log.append(f"{planned.instance}: gestartet {card.ref.repo}#{card.ref.number}{seconds}")
            continue
        if isinstance(result, Failure):  # WAITING: its branch is still in use, no comment
            run.failed.append(planned)
            lead.append(_failed(card, result, writer))
        if run.replan:
            plan = run.replan(frozenset(tried - {s.card.key for s in run.started}))
    return lead, log


def apply(out: Decisions, writer: GitHubWriter, store: Store, now: datetime,
          full: bool) -> tuple[list[str], list[str]]:
    """Execute the decisions; return (lines for the Lead, lines for the local log)."""
    added = _board(out, writer, store, now)
    _comments(out, writer, store, now)
    failed, log = _starts(out.dispatch, writer, now)
    lines = added + failed + store.due_notices(out.notices, now, full)
    for ref in out.board.add:  # its "Neu im Project" line went out now: not again next run
        store.notices.setdefault(f"triage-new:{ref.url}", now.isoformat())
    return lines, log
