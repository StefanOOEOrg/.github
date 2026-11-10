"""The signal model: what any signal source hands to the engine (ports.py).

A ``Signal`` is the envelope (source, delivery ID, event time) around an optional ``Subject``, the
change GitHub reported: the fields of the former route JSON ``{event, action, repo, issue, pr,
item, sender}``. A signal without a subject asks for a full run over the whole board (the start,
the clock, the end of a developer job, a cron run without an event). ``scope.scope_for`` maps a
signal to the scope of the engine run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

# the subject's fields in the route JSON, in its order; the JSON key of ``kind`` is "event"
ROUTE_KEYS = ("event", "action", "repo", "issue", "pr", "item", "sender")


def now_utc() -> datetime:
    """The current time (a function, so tests can replace it)."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Subject:
    """The change behind a signal: event kind and action, repository, issue, PR, item, sender."""

    kind: str = ""
    action: str = ""
    repo: str = ""
    issue: str = ""
    pr: str = ""
    item: str = ""
    sender: str = ""

    def route_json(self) -> dict[str, str]:
        """The route JSON (the shape Hermes rendered into ``HERMES_CRON_EVENT``)."""
        return dict(zip(ROUTE_KEYS, (self.kind, self.action, self.repo, self.issue, self.pr,
                                     self.item, self.sender), strict=True))


@dataclass(frozen=True)
class Signal:
    """One signal for the engine; ``subject`` None stands for a full run."""

    source: str  # name of the adapter that produced it (webhook, timer, jobwatch, hermes-cron, ...)
    delivery_id: str  # unique per signal: X-GitHub-Delivery, or source + time
    occurred_at: datetime  # when the change happened; the queue orders by it
    subject: Subject | None = None

    @property
    def full(self) -> bool:
        """True for a run over the whole board whatever happened."""
        return self.subject is None


def full_run(source: str, at: datetime | None = None) -> Signal:
    """A full-run signal of ``source``, its delivery ID made unique by the time."""
    at = at or now_utc()
    return Signal(source, f"{source}-{at:%Y%m%dT%H%M%S%f}", at)


def _field(event: dict, key: str) -> str:
    """One route field; an unresolved template field ``{name}`` counts as missing."""
    value = str(event.get(key) or "")
    return "" if value.startswith("{") else value


def subject_of(event: dict) -> Subject | None:
    """The subject of a route JSON, None if it names no event."""
    values = [_field(event, key) for key in ROUTE_KEYS]
    return Subject(*values) if values[0] else None


def parse_context(context: str | None) -> dict:
    """The route JSON in a trigger context, {} if there is none.

    Hermes prefixes the JSON line with a sentence, so the last line that parses as an object wins.
    """
    for line in reversed((context or "").strip().splitlines()):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            return event
    return {}
