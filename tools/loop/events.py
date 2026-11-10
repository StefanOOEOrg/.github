"""A GitHub webhook delivery as a signal (signals.py): filter, subject and event time.

The filter is the one of the former Hermes route ``loop`` (webhook_subscriptions.json): the org,
the events and actions below, no echo of the engine's own writes, no pull request from a fork.
The subject holds the fields the route rendered into ``HERMES_CRON_EVENT``, so ``scope.scope_for``
decides as before.
"""

from __future__ import annotations

from datetime import datetime

from loop import config
from loop.signals import Signal, Subject

SOURCE = "webhook"
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


def subject(kind: str, payload: dict) -> Subject:
    """The change the delivery reports (the route's fields)."""
    def text(*path: str) -> str:
        value = _get(payload, *path)
        return "" if value is None else str(value)
    return Subject(kind, text("action"), text("repository", "full_name"), text("issue", "number"),
                   text("pull_request", "number"), text("projects_v2_item", "content_node_id"),
                   text("sender", "login"))


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


def accept(kind: str, delivery: str, payload: dict, received: datetime) -> Signal | None:
    """The signal for the queue, None if the filter drops it."""
    if rejection(kind, payload):
        return None
    return Signal(SOURCE, delivery, event_time(payload, received), subject(kind, payload))
