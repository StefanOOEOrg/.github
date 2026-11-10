"""Scope of an engine run: the whole board or one card, from a signal (signals.py).

Only events that cannot change another card are narrowed to one card. Everything that can start
a card (status, PR opened or closed, issue closed or edited, assignments) reads the whole board:
dispatch and the blocker rules need it. A signal without a subject (start, clock, job end, a cron
run without an event) is a full run.
"""

from __future__ import annotations

from dataclasses import dataclass

from loop.signals import Signal, now_utc, parse_context, subject_of

CARD_ONLY = {("issue_comment", "created"), ("issues", "opened"), ("issues", "reopened")}


@dataclass(frozen=True)
class Scope:
    """``card`` (repo, number) for a one-card run, None for the whole board."""

    card: tuple[str, int] | None = None
    reason: str = "full"

    @property
    def full(self) -> bool:
        """True for a run over the whole board."""
        return self.card is None


def scope_for(signal: Signal) -> Scope:
    """The scope this signal alone needs."""
    subject = signal.subject
    if subject is None:
        return Scope(None, signal.delivery_id or "full")
    reason = f"{subject.kind}.{subject.action}"
    if (subject.kind, subject.action) in CARD_ONLY and subject.repo and subject.issue.isdigit():
        return Scope((subject.repo, int(subject.issue)), reason)
    return Scope(None, reason)


def scope_of(context: str | None) -> Scope:
    """The scope of a trigger context (the route JSON, as in ``HERMES_CRON_EVENT``)."""
    subject = subject_of(parse_context(context))
    return scope_for(Signal("context", "" if subject else "full", now_utc(), subject))
