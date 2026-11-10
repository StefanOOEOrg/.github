"""Dispatcher of the webhook listener: one engine run at a time, in event-time order, none lost.

Guarantee: an accepted event leaves the queue only through a successful engine run that started
after it was queued. Events queued while a run is in flight wait for the next run. A failed run
(GitHubError, TimeoutError, OSError) puts its events back and waits ``BACKOFF_FIRST_SECONDS``,
doubled up to ``BACKOFF_MAX_SECONDS``; events never get dropped. Any other error ends the process
(systemd restarts it, and the start's full run reads the whole board again).

Several waiting events become ONE full run: it reads the board after every one of them was
queued, so the state each of them changed is in what it reads, and a full run makes every
decision a one-card run makes. One event alone keeps its own scope (scope.py).
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from loop import config, retry
from loop.events import Event
from loop.github_client import GitHubError
from loop.scope import Scope

logger = logging.getLogger(__name__)

RETRYABLE = (GitHubError, TimeoutError, OSError)
MARKER = "loop-listener-retry.json"  # not the cron marker: the job watch must not retry these
RETRYING = "Der Listener versucht es mit Backoff weiter, kein Event geht verloren."

Engine = Callable[[Scope], list[str]]
Deliver = Callable[[str], None]


def now_utc() -> datetime:
    """The current time (a function, so tests can replace it)."""
    return datetime.now(UTC)


class RecentIds(OrderedDict[str, None]):
    """The last ``size`` delivery IDs, thread-safe: a redelivery is recognised."""

    def __init__(self, size: int) -> None:
        super().__init__()
        self._size, self._lock = size, threading.Lock()

    def add(self, delivery: str) -> bool:
        """Remember ``delivery``; False if it was already there."""
        with self._lock:
            if delivery in self:
                return False
            self[delivery] = None
            while len(self) > self._size:
                self.popitem(last=False)
            return True


class Dispatcher:
    """Queue of accepted events and the serial engine runs over it."""

    def __init__(self, engine: Engine, deliver: Deliver, clock: Callable[[], datetime] = now_utc,
                 ) -> None:
        self._engine, self._deliver, self._clock = engine, deliver, clock
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seen = RecentIds(config.DEDUPE_DELIVERIES)
        self._sequence = itertools.count()  # ties in event time keep the order of receipt
        self.backoff = 0.0  # seconds to wait before the next run, 0 after a success

    def submit(self, event: Event) -> bool:
        """Queue an event; False for a delivery already seen (a redelivery)."""
        if not self._seen.add(event.delivery):
            return False
        self._queue.put((event.at, next(self._sequence), event))
        logger.info("queued %s (%s)", event.delivery, event.scope.reason)
        return True

    def pending(self) -> int:
        """Number of events waiting."""
        return self._queue.qsize()

    def waiting(self) -> list[str]:
        """The delivery IDs waiting, in the order the next run takes them."""
        return [entry[2].delivery for entry in sorted(self._queue.queue, key=lambda e: e[:2])]

    def _take(self, timeout: float) -> list[tuple]:
        """Every waiting event, oldest event time first; [] if none came within ``timeout``."""
        try:
            batch = [self._queue.get(timeout=timeout)]
        except queue.Empty:
            return []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                return sorted(batch, key=lambda entry: entry[:2])

    def run_once(self, timeout: float = 1.0) -> bool | None:
        """One engine run over what waits: True ok, False failed (requeued), None nothing."""
        batch = self._take(timeout)
        if not batch:
            return None
        events = [entry[2] for entry in batch]
        scope = events[0].scope if len(events) == 1 else Scope(None, f"{len(events)} events")
        ids = ", ".join(event.delivery for event in events)
        logger.info("run %s for %s", scope.reason, ids)
        try:
            lines = self._engine(scope)
        except RETRYABLE as error:
            for entry in batch:
                self._queue.put(entry)
            self.backoff = min(max(self.backoff * 2, config.BACKOFF_FIRST_SECONDS),
                               config.BACKOFF_MAX_SECONDS)
            logger.error("run failed, %d event(s) back in the queue, next try in %.0f s: %s",
                         len(batch), self.backoff, error)
            notice = retry.record(self.marker(), str(error), self._clock(), RETRYING)
            if notice:
                self._deliver(notice)
            return False
        self.backoff = 0.0
        recovered = retry.clear(self.marker(), self._clock())
        if recovered:
            lines = [*lines, recovered]
        if lines:
            self._deliver("\n".join(lines))
        return True

    @staticmethod
    def marker() -> Path:
        """The listener's failure marker (only for the Lead's notice; retries happen here)."""
        return Path(config.CACHE_DIR) / MARKER

    def serve(self, stop: threading.Event) -> None:
        """Run until ``stop`` is set."""
        while not stop.is_set():
            if self.backoff and stop.wait(self.backoff):
                break
            self.run_once(timeout=1.0)

    def finish(self) -> list[str]:
        """Shutdown, after the HTTP server stopped: one last try over what waits.

        Returns the delivery IDs that could not run; the next start's full run covers them.
        """
        if not self.pending() or self.run_once(timeout=0) is not False:
            return []
        left = [entry[2].delivery for entry in self._take(0)]
        logger.error("shutdown with %d event(s) not run: %s; the full run at the next start "
                     "covers them", len(left), ", ".join(left))
        return left
