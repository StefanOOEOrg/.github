"""Base of the sources that look at something every few seconds in their own thread."""

from __future__ import annotations

import logging
import threading

from loop.ports import Submit
from loop.signals import Signal

logger = logging.getLogger(__name__)


class PollingSource:
    """Calls ``poll`` every ``seconds`` in a daemon thread and submits what it returns.

    ``seconds`` 0 or less switches the source off: ``start`` starts no thread.
    """

    name = "polling"

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll(self) -> Signal | None:
        """The signal for this look, None if there is nothing to report."""
        raise NotImplementedError

    def start(self, submit: Submit) -> None:
        """Start the thread (nothing if switched off)."""
        if self.seconds <= 0:
            logger.info("source %s switched off", self.name)
            return
        self._thread = threading.Thread(target=self._run, args=(submit,),
                                        name=f"loop-{self.name}", daemon=True)
        self._thread.start()

    def _run(self, submit: Submit) -> None:
        while not self._stop.wait(self.seconds):
            found = self.poll()
            if found is not None and not self._stop.is_set():
                submit(found)

    def stop(self) -> None:
        """End the thread; nothing is submitted after this returns."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.seconds, 1) + 5)
