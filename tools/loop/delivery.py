"""Delivery of the engine's lines, decoupled from the dispatcher.

The dispatcher only queues a message; one thread hands it to the configured output sink
(sinks.py, port ``OutputSink``; default ``LOOP_DELIVER_CMD``), in order, retrying a refused
message with backoff. So no engine run ever waits for the Lead agent. Messages still open at
shutdown go to ``cache/loop-deliver-pending.jsonl`` and are sent first at the next start.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from loop import config

logger = logging.getLogger(__name__)

PENDING = "loop-deliver-pending.jsonl"

Sender = Callable[[str], bool]  # OutputSink.deliver


class Deliverer:
    """One thread that sends the queued messages in order and never drops one."""

    def __init__(self, send: Sender, pending: Path) -> None:
        self._send, self._pending = send, pending
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="loop-deliver", daemon=True)
        self._current: str | None = None

    def put(self, text: str) -> None:
        """Queue one message; returns at once."""
        self._queue.put(text)

    def start(self) -> None:
        """Queue what the last shutdown left, then start sending."""
        try:
            lines = self._pending.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        for line in lines:
            self._queue.put(json.loads(line))
        self._pending.unlink(missing_ok=True)
        if lines:
            logger.info("%d message(s) from the last shutdown queued", len(lines))
        self._thread.start()

    def _run(self) -> None:
        backoff = 0.0
        while not self._stop.is_set():
            if self._current is None:
                try:
                    self._current = self._queue.get(timeout=1.0)
                except queue.Empty:
                    continue
            if self._send(self._current):
                self._current, backoff = None, 0.0
                continue
            backoff = min(max(backoff * 2, config.BACKOFF_FIRST_SECONDS),
                          config.BACKOFF_MAX_SECONDS)
            self._stop.wait(backoff)

    def stop(self, timeout: float) -> list[str]:
        """Send what waits for up to ``timeout`` s, then keep the rest for the next start."""
        waited = 0.0
        while (self._current is not None or not self._queue.empty()) and waited < timeout:
            self._stop.wait(0.2)
            waited += 0.2
        self._stop.set()
        self._thread.join(timeout=config.DELIVER_TIMEOUT_SECONDS + 1)
        left = [] if self._current is None else [self._current]
        while not self._queue.empty():
            left.append(self._queue.get_nowait())
        if left:
            self._pending.parent.mkdir(parents=True, exist_ok=True)
            with self._pending.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(text) + "\n" for text in left)
            logger.warning("%d message(s) kept for the next start in %s", len(left), self._pending)
        return left
