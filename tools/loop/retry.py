"""Retry of a failed run: a marker in the cache that the job watch turns into a full run.

A run that fails (GitHub unreachable after all attempts, the lock not free, a crash) loses the
event that fired it; without a retry the next try is the hourly run. The failed run leaves
``cache/loop-retry.json``; the job watch (every minute) runs the engine over the whole board once
the last failure is ``RETRY_MINUTES`` old, and a successful full run removes the marker. Silent
unless the failure lasts ``RETRY_REPORT_MINUTES``: then one notice to the Lead, and one when the
runs work again.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from loop import config

logger = logging.getLogger(__name__)

MARKER = "loop-retry.json"


def marker_path() -> Path:
    """The marker in the cache directory (read from config at call time, tests patch it)."""
    return Path(config.CACHE_DIR) / MARKER


def _read(path: Path) -> dict | None:
    """The marker, None without one; an unreadable marker counts as a failure of unknown age."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logger.warning("retry marker unreadable, treated as due: %s: %s", path, error)
        return {}
    return data if isinstance(data, dict) else {}


def _time(value: object, default: datetime | None) -> datetime | None:
    """An ISO timestamp of the marker, ``default`` if it is missing or broken."""
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return default


def _minutes(since: datetime, now: datetime) -> int:
    return int((now - since).total_seconds() // 60)


def record(path: Path, reason: str, now: datetime, retrying: str | None = None) -> str | None:
    """Remember a failed run; returns the Lead's notice once it fails ``RETRY_REPORT_MINUTES``.

    ``retrying`` says who retries how often (default: the job watch).
    """
    old = _read(path) or {}
    since = _time(old.get("since"), now) or now
    marker = {"since": since.isoformat(), "last_try": now.isoformat(), "reason": reason[:300],
              "reported": bool(old.get("reported"))}
    minutes = _minutes(since, now)
    notice = None
    if not marker["reported"] and minutes >= config.RETRY_REPORT_MINUTES:
        marker["reported"] = True
        notice = (f"Loop-Engine: Läufe scheitern seit {minutes} min ({since:%H:%M} UTC): "
                  f"{reason[:200]}. "
                  f"{retrying or f'Der Job-Watch versucht es alle {config.RETRY_MINUTES} min.'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker))
    logger.info("failed run recorded for a retry (failing for %d min)", minutes)
    return notice


def due(path: Path, now: datetime) -> dict | None:
    """The marker if a retry is due (the last failure ``RETRY_MINUTES`` ago), else None."""
    marker = _read(path)
    if marker is None:
        return None
    last = _time(marker.get("last_try"), None)
    if last is None or now - last >= timedelta(minutes=config.RETRY_MINUTES):
        return marker
    return None


def clear(path: Path, now: datetime) -> str | None:
    """Remove the marker after a successful full run; the Lead's notice if the failure was told."""
    marker = _read(path)
    if marker is None:
        return None
    path.unlink(missing_ok=True)
    since = _time(marker.get("since"), now) or now
    logger.info("runs work again after %d min of failures", _minutes(since, now))
    if marker.get("reported"):
        return f"Loop-Engine läuft wieder (nach {_minutes(since, now)} min Ausfall)."
    return None
