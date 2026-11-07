#!/usr/bin/env python3
"""Filter script of the Hermes webhook route `loop` (webhook concept, step 3: shadow mode).

Hermes passes the GitHub payload as JSON on stdin. In shadow mode the script only records what
arrived - event, action, repository, item, sender - as one JSON line in
`cache/webhook-events.jsonl` of the profile and answers `[SILENT]`, so Hermes starts nothing.
The log shows whether every board change produces an event before the tick is switched on.

The event type is not in the payload (GitHub sends it as a header), so it is derived from the
payload's keys. Nothing from the payload is executed; fork PRs are only recorded.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

LOG_NAME = "webhook-events.jsonl"
MAX_LOG_BYTES = 5_000_000  # rotate once: the shadow phase runs for days, not months
SILENT = "[SILENT]"


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
    """Return `repo#number` for issues and PRs, the item node id for project items, else ''."""
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
        "changed": sorted(changes),
        "fork": bool(pull) and head_repo is not None and head_repo != base_repo,
    }


def append(log: Path, record: dict) -> None:
    """Append one record, rotating the log once it passes MAX_LOG_BYTES."""
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
        log.replace(log.with_suffix(".jsonl.1"))
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> int:
    """Record the delivery and tell Hermes to ignore it."""
    log = Path(__file__).resolve().parent.parent / "cache" / LOG_NAME
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        append(log, {"at": datetime.now(UTC).isoformat(timespec="seconds"),
                     "event": "invalid", "error": str(error)[:200]})
        print(SILENT)
        return 0
    append(log, summary(payload if isinstance(payload, dict) else {}))
    print(SILENT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
