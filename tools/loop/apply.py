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
from loop.starter import start
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
        added.append(f"Neu im Project (Triage): {ref.repo}#{ref.number} {ref.url}")
    return added


def _comments(out: Decisions, writer: GitHubWriter, store: Store, now: datetime) -> None:
    for card, reason in out.blocked:
        if store.first_comment(f"{card.ref.url}|{reason}", now):
            _safely("comment", writer.comment, card.ref,
                    f"Not started: {reason}. It stays on Goal and starts as soon as this is "
                    "resolved.")
    for card in out.stuck:
        if store.first_comment(f"{card.ref.url}|stuck", now):
            _safely("comment", writer.comment, card.ref,
                    f"@{config.OWNER} Stuck: on Action for {config.STUCK_MINUTES} minutes without "
                    "a PR and without a developer job. Move it back to Goal to start it again.")
            _safely("assignees", writer.assignees, card, {config.OWNER}, set())
    for pr, reminder in out.reminders:
        if store.reminder_due(reminder.key, now):
            _safely("reminder", writer.comment, pr.ref, reminder.text)


def _starts(out: Decisions, writer: GitHubWriter, store: Store, now: datetime) -> list[str]:
    lines = []
    for planned in out.starts:
        card = planned.card
        failed = start(card, planned.instance, writer)
        if failed:
            reason = f"the start failed while {failed}, see the engine log"
            if store.first_comment(f"{card.ref.url}|{reason}", now):
                _safely("comment", writer.comment, card.ref, f"Not started: {reason}.")
            continue
        moved = card.state.changed
        seconds = f", Goal→Action {round((now - moved).total_seconds())} s" if moved else ""
        lines.append(f"{planned.instance}: gestartet {card.ref.repo}#{card.ref.number}{seconds}")
    return lines


def apply(out: Decisions, writer: GitHubWriter, store: Store, now: datetime,
          full: bool) -> tuple[list[str], list[str]]:
    """Execute the decisions; return (lines for the Lead, lines for the local log)."""
    added = _board(out, writer, store, now)
    _comments(out, writer, store, now)
    log = _starts(out, writer, store, now)
    return added + store.due_notices(out.notices, now, full), log
