#!/usr/bin/env python3
"""Filter script of the Hermes webhook route `loop` (webhook concept, step 4: the tick).

Hermes passes the GitHub payload as JSON on stdin. Every delivery is recorded as one JSON line in
`cache/webhook-events.jsonl` of the profile. A delivery that can change what someone must do
next lets Hermes fire the tick job (`loop-tick.sh`): the script answers with a JSON object.
Everything else is answered with `[SILENT]` and starts nothing.

The payload is only a trigger: the tick reads the whole state again. Not triggering: other
organisations, fork PRs, pings, reordering, pushes to a PR, and the Lead bot's own writes
(status, assignees, comments) - they would only echo the tick that made them. Hermes drops a
trigger while the tick runs, so every trigger also stamps `cache/tick-requested`; the tick runs
once more if a stamp is newer than its start.

A move to Goal is stamped per card in `cache/goal-since.json`; the dispatcher logs the time from
Goal to Action when it starts the card.

The event type is not in the payload (GitHub sends it as a header), so it is derived from the
payload's keys. Nothing from the payload is executed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

LOG_NAME = "webhook-events.jsonl"
MAX_LOG_BYTES = 5_000_000  # rotate once
SILENT = "[SILENT]"
ORG = os.environ.get("GH_ORG", "StefanOOEOrg")
LEAD = os.environ.get("LEAD_LOGIN", "StefanOOELeadBot")
TRIGGERS = {
    "issues": {"opened", "edited", "closed", "reopened", "assigned", "unassigned", "deleted",
               "transferred"},
    "issue_comment": {"created"},
    "pull_request": {"opened", "edited", "closed", "reopened", "ready_for_review",
                     "converted_to_draft", "review_requested", "review_request_removed"},
    "pull_request_review": {"submitted", "dismissed"},
    "projects_v2_item": {"created", "edited", "deleted", "archived", "restored", "converted"},
}
LEAD_ECHOES = {("projects_v2_item", "edited"), ("issues", "assigned"), ("issues", "unassigned"),
               ("issue_comment", "created")}


def event_type(payload: dict) -> str:
    """Return the GitHub event name for a payload, derived from its keys."""
    if "zen" in payload and "hook_id" in payload:
        return "ping"
    if "projects_v2_item" in payload:
        return "projects_v2_item"
    if "review" in payload and "pull_request" in payload:
        return "pull_request_review"
    if "comment" in payload and "issue" in payload:
        return "issue_comment"
    if "pull_request" in payload:
        return "pull_request"
    if "issue" in payload:
        return "issues"
    return "unknown"


def subject(payload: dict) -> str:
    """Return `repo#number` for issues and PRs, the item content id for project items, else ''."""
    item = payload.get("pull_request") or payload.get("issue")
    repo = (payload.get("repository") or {}).get("full_name", "")
    if item and repo:
        return f"{repo}#{item.get('number')}"
    project_item = payload.get("projects_v2_item")
    return project_item.get("content_node_id", "") if project_item else ""


def summary(payload: dict) -> dict:
    """Return the record written for one webhook delivery."""
    changes = payload.get("changes") or {}
    pull = payload.get("pull_request") or {}
    head_repo = ((pull.get("head") or {}).get("repo") or {}).get("full_name")
    base_repo = (payload.get("repository") or {}).get("full_name")
    field_value = changes.get("field_value") if isinstance(changes.get("field_value"), dict) else {}
    to_value = field_value.get("to") if isinstance(field_value.get("to"), dict) else {}
    return {
        "field": field_value.get("field_name"),
        "to": to_value.get("name"),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "event": event_type(payload),
        "action": payload.get("action"),
        "subject": subject(payload),
        "sender": (payload.get("sender") or {}).get("login"),
        "org": (payload.get("organization") or {}).get("login"),
        "changed": sorted(changes),
        "fork": bool(pull) and head_repo is not None and head_repo != base_repo,
    }


def triggers(record: dict) -> bool:
    """True if the delivery can change what someone must do next."""
    if record["org"] != ORG or record["fork"]:
        return False
    if record["action"] not in TRIGGERS.get(record["event"], set()):
        return False
    return not (record["sender"] == LEAD and (record["event"], record["action"]) in LEAD_ECHOES)


def append(log: Path, record: dict) -> None:
    """Append one record, rotating the log once it passes MAX_LOG_BYTES."""
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
        log.replace(log.with_suffix(".jsonl.1"))
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def stamp_goal(cache: Path, record: dict) -> None:
    """Remember when a card was moved to Goal, for the Goal-to-Action measurement."""
    if record["field"] != "Status" or record["to"] != "Goal" or not record["subject"]:
        return
    path = cache / "goal-since.json"
    try:
        since = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        since = {}
    since[record["subject"]] = time.time()
    path.write_text(json.dumps(since, sort_keys=True))


def main() -> int:
    """Record the delivery; fire the tick for a relevant one, otherwise stay silent."""
    cache = Path(__file__).resolve().parent.parent / "cache"
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        append(cache / LOG_NAME, {"at": datetime.now(UTC).isoformat(timespec="seconds"),
                                  "event": "invalid", "error": str(error)[:200]})
        print(SILENT)
        return 0
    record = summary(payload if isinstance(payload, dict) else {})
    record["trigger"] = triggers(record)
    append(cache / LOG_NAME, record)
    if not record["trigger"]:
        print(SILENT)
        return 0
    stamp_goal(cache, record)
    (cache / "tick-requested").write_text(f"{time.time():.0f}\n")
    print(json.dumps({"event": record["event"], "action": record["action"],
                      "subject": record["subject"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
