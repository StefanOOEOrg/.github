"""Fakes of the ports (ports.py): a source that submits on demand, a recording sink."""

from __future__ import annotations

from loop.ports import Submit
from loop.signals import Signal
from loop.sinks import BaseSink


class FakeSource:
    """A source that submits the given signals at start, and ``push`` later ones."""

    def __init__(self, name: str, *signals: Signal) -> None:
        self.name, self.signals = name, list(signals)
        self.submit: Submit | None = None
        self.stopped = False

    def start(self, submit: Submit) -> None:
        """Remember ``submit`` and hand over the initial signals."""
        self.submit = submit
        for signal in self.signals:
            submit(signal)

    def push(self, signal: Signal) -> bool:
        """Submit one more signal (from the test's thread)."""
        assert self.submit is not None and not self.stopped
        return self.submit(signal)

    def stop(self) -> None:
        """Remember the stop."""
        self.stopped = True


class FakeSink(BaseSink):
    """Records every message; refuses the first ``refusals`` ones."""

    name = "fake"

    def __init__(self, refusals: int = 0) -> None:
        self.messages: list[str] = []
        self.refusals = refusals

    def deliver(self, message: str) -> bool:
        """Accept (and record) unless a refusal is left."""
        if self.refusals:
            self.refusals -= 1
            return False
        self.messages.append(message)
        return True
