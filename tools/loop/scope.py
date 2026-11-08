"""Scope of a run from the webhook event (Hermes patch A: ``HERMES_CRON_EVENT``).

The route renders a JSON line of signals; Hermes prefixes it with a sentence, so the last line
that parses as JSON is the event. Unresolved template fields stay as ``{field}`` and count as
missing. Without a usable event the run is full: the hourly run and a coalesced re-fire.

Only events that cannot change another card are narrowed to one card. Everything that can start
a card (status, PR opened or closed, issue closed or edited, assignments) reads the whole board:
dispatch and the blocker rules need it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

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


def _value(event: dict, key: str) -> str:
    value = str(event.get(key) or "")
    return "" if value.startswith("{") else value


def parse_event(context: str | None) -> dict:
    """The signal JSON of the trigger context, {} if there is none."""
    for line in reversed((context or "").strip().splitlines()):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            return event
    return {}


def scope_of(context: str | None) -> Scope:
    """The scope this trigger needs."""
    event = parse_event(context)
    kind, action = _value(event, "event"), _value(event, "action")
    repo, issue = _value(event, "repo"), _value(event, "issue")
    if (kind, action) in CARD_ONLY and repo and issue.isdigit():
        return Scope((repo, int(issue)), f"{kind}.{action}")
    return Scope(None, f"{kind}.{action}" if kind else "full")
