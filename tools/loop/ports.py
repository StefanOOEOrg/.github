"""The ports of the loop engine: where signals come from and where its lines go.

The engine and the dispatcher know only these protocols; the adapters live in ``sources/`` and
``sinks.py``, and ``wiring.py`` (the composition root) picks them by configuration. A new signal
giver or output is one class that fulfils a protocol plus one line in the registry of
``wiring.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from loop.signals import Signal

# hands one signal to the dispatcher's queue; False for a delivery ID already seen
Submit = Callable[[Signal], bool]


class SignalSource(Protocol):
    """A signal giver (event source or clock).

    ``start`` returns at once: a source that waits for something runs its own daemon thread and
    calls ``submit`` from there; a one-shot source submits before it returns. ``stop`` ends the
    thread, so that nothing is submitted after it returns; calling it twice is harmless.
    """

    name: str

    def start(self, submit: Submit) -> None:
        """Begin handing signals to ``submit``."""

    def stop(self) -> None:
        """Stop handing signals; returns once nothing more is submitted."""


class OutputSink(Protocol):
    """An output for the engine's lines (one message: the lines of one run, or a notice)."""

    name: str

    def deliver(self, message: str) -> bool:
        """Hand over one message; True once it is accepted (the caller retries a False)."""

    def deliver_lines(self, lines: list[str]) -> bool:
        """The lines of one run as one message; nothing (and True) without lines."""
