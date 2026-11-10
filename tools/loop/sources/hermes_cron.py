"""``HermesCronSource``: the one signal of a Hermes cron run (``python3 -m loop tick``).

The Hermes route ``loop`` renders the route JSON into ``HERMES_CRON_EVENT`` (Hermes patch A); a
run without it (the hourly schedule, a coalesced re-fire, a manual run) is a full run. One-shot:
``start`` submits the signal and returns.
"""

from __future__ import annotations

import os

from loop.ports import Submit
from loop.signals import Signal, full_run, now_utc, parse_context, subject_of

VARIABLE = "HERMES_CRON_EVENT"


class HermesCronSource:
    """The signal in ``HERMES_CRON_EVENT`` (or ``context``, for tests)."""

    name = "hermes-cron"

    def __init__(self, context: str | None = None) -> None:
        self._context = context

    def read(self) -> Signal:
        """The signal of this run; a full run without a usable event."""
        context = self._context if self._context is not None else os.environ.get(VARIABLE)
        subject = subject_of(parse_context(context))
        if subject is None:
            return full_run(self.name)
        at = now_utc()
        return Signal(self.name, f"{self.name}-{at:%Y%m%dT%H%M%S%f}", at, subject)

    def start(self, submit: Submit) -> None:
        """Submit the one signal."""
        submit(self.read())

    def stop(self) -> None:
        """Nothing to stop: the source is done after ``start``."""
