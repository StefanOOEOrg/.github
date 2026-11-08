"""The only local state: what was already reported (decision of 7.11.: local, small, rebuildable).

Three sections in ``cache/loop-state.json``:
- notices: Lead notices by key -> last time printed. Repeated after REMIND_MINUTES while due,
  ``once`` notices never. A full run forgets keys that are no longer due.
- comments: one-time comments (blocked reason, stuck handover) by key, kept while the reason lasts.
- reminders: approve reminders by key (PR + head) -> last time, repeated after OWNER_REPEAT_HOURS.
Losing the file costs at most one repeated notice or comment.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from loop import config
from loop.rules.checks import Finding

logger = logging.getLogger(__name__)


class Store:
    """Load once per run, ask, save once at the end."""

    def __init__(self, path: Path, legacy: Path | None = None) -> None:
        self.path = path
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = _seed(legacy) if legacy else {}
        self.notices: dict[str, str] = data.get("notices", {})
        self.comments: dict[str, str] = data.get("comments", {})
        self.reminders: dict[str, str] = data.get("reminders", {})
        self._seen_comments: set[str] = set()

    def due_notices(self, found: list[Finding], now: datetime, full: bool) -> list[str]:
        """The notice texts to print now; remembers them."""
        due, current = [], {}
        for finding in found:
            last = self.notices.get(finding.key)
            repeat = not finding.once and last is not None and \
                now - datetime.fromisoformat(last) >= timedelta(minutes=config.REMIND_MINUTES)
            if last is None or repeat:
                due.append(finding.text if last is None else f"Erinnerung: {finding.text}")
                current[finding.key] = now.isoformat()
            else:
                current[finding.key] = last
        self.notices = current if full else {**self.notices, **current}
        return due

    def first_comment(self, key: str, now: datetime) -> bool:
        """True the first time a one-time comment is due (and remember it)."""
        self._seen_comments.add(key)
        if key in self.comments:
            return False
        self.comments[key] = now.isoformat()
        return True

    def reminder_due(self, key: str, now: datetime) -> bool:
        """True if an approve reminder may be posted now (and remember it)."""
        last = self.reminders.get(key)
        if last and now - datetime.fromisoformat(last) < timedelta(hours=config.OWNER_REPEAT_HOURS):
            return False
        self.reminders[key] = now.isoformat()
        return True

    def save(self, full: bool) -> None:
        """Write the state; a full run forgets one-time comments whose reason is gone."""
        if full:
            self.comments = {k: v for k, v in self.comments.items() if k in self._seen_comments}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"notices": self.notices, "comments": self.comments,
                                   "reminders": self.reminders}, sort_keys=True))
        tmp.replace(self.path)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _seed(cache: Path) -> dict:
    """Migration: take over what the old scripts already reported, so nothing is sent twice.

    github-watch-state.json (notices), dispatch-reported.json (one-time comments, same keys)
    and approve-reminders.json ({pr url: {head, at}}) in the profile's cache directory.
    """
    watch = _read(cache / "github-watch-state.json")
    notices = {k: v for k, v in watch.items() if isinstance(v, str)}
    comments = {k: "migrated" for k in _read(cache / "dispatch-reported.json")}
    reminders = {f"remind:{url}@{v['head']}": v["at"]
                 for url, v in _read(cache / "approve-reminders.json").items()
                 if isinstance(v, dict) and "head" in v and "at" in v}
    return {"notices": notices, "comments": comments, "reminders": reminders}
