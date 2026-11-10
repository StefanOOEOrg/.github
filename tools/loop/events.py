"""A webhook delivery as the dispatcher sees it: filter, signal JSON and event time.

The filter is the one of the former Hermes route ``loop`` (webhook_subscriptions.json): the org,
the events and actions below, no echo of the engine's own writes, no pull request from a fork.
The signal is the JSON the route rendered for ``HERMES_CRON_EVENT``, so ``scope.scope_of`` reads it
unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from loop import config
from loop.scope import Scope, scope_of

ACTIONS = {
    "issues": {"opened", "edited", "closed", "reopened", "assigned", "unassigned", "deleted",
               "transferred"},
    "issue_comment": {"created"},
    "pull_request": {"opened", "edited", "closed", "reopened", "ready_for_review",
                     "converted_to_draft", "review_requested", "review_request_removed"},
    "pull_request_review": {"submitted", "dismissed"},
    "projects_v2_item": {"created", "edited", "deleted", "archived", "restored", "converted"},
    "ping": None,  # any action
}
ENGINE_WRITES = {("projects_v2_item", "edited"), ("issues", "assigned"),
                 ("issues", "unassigned"), ("issue_comment", "created")}
# where the payload says when the change happened, most specific first
TIME_FIELDS = (("review", "submitted_at"), ("comment", "updated_at"),
               ("projects_v2_item", "updated_at"), ("pull_request", "updated_at"),
               ("issue", "updated_at"))


@dataclass(frozen=True)
class Event:
    """One accepted delivery; ``signal`` None stands for a full run (start, recovery)."""

    delivery: str
    at: datetime  # event time from the payload, else the time of receipt
    signal: dict | None

    @property
    def scope(self) -> Scope:
        """The scope this event alone needs (same semantics as HERMES_CRON_EVENT)."""
        return Scope(None, self.delivery) if self.signal is None else scope_of(
            json.dumps(self.signal))


def _get(payload: dict, *path: str) -> object:
    node: object = payload
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def rejection(kind: str, payload: dict) -> str | None:
    """Why the route filter drops this delivery, None if it passes."""
    action = str(payload.get("action") or "")
    if kind not in ACTIONS:
        return f"event {kind}"
    if ACTIONS[kind] is not None and action not in ACTIONS[kind]:
        return f"{kind}.{action}"
    if _get(payload, "organization", "login") != config.ORG:
        return "other org"
    if _get(payload, "sender", "login") == config.LEAD and (kind, action) in ENGINE_WRITES:
        return "engine write"
    head_owner = _get(payload, "pull_request", "head", "repo", "owner", "login")
    if head_owner and head_owner != config.ORG:
        return "fork"
    return None


def signal(kind: str, payload: dict) -> dict:
    """The route's signal JSON: {event, action, repo, issue, pr, item, sender}."""
    def text(*path: str) -> str:
        value = _get(payload, *path)
        return "" if value is None else str(value)
    return {"event": kind, "action": text("action"), "repo": text("repository", "full_name"),
            "issue": text("issue", "number"), "pr": text("pull_request", "number"),
            "item": text("projects_v2_item", "content_node_id"), "sender": text("sender", "login")}


def event_time(payload: dict, received: datetime) -> datetime:
    """When the change happened per the payload; the time of receipt if it says nothing."""
    for path in TIME_FIELDS:
        value = _get(payload, *path)
        try:
            found = datetime.fromisoformat(str(value))
        except ValueError:
            continue
        if found.tzinfo is not None:
            return found
    return received


def accept(kind: str, delivery: str, payload: dict, received: datetime) -> Event | None:
    """The event for the queue, None if the filter drops it."""
    if rejection(kind, payload):
        return None
    return Event(delivery, event_time(payload, received), signal(kind, payload))
