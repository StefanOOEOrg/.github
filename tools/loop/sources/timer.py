"""``TimerSource``: the clock, a full run every ``LOOP_FULL_RUN_MINUTES``.

The time rules (D2 stuck, W6 reminders, repeats, archive) need a run even when nothing happens on
GitHub, and a full run catches a webhook GitHub failed to deliver. Not polling GitHub: the signal
only asks the dispatcher for a run.
"""

from __future__ import annotations

from loop.signals import Signal, full_run
from loop.sources.polling import PollingSource


class TimerSource(PollingSource):
    """A full-run signal every ``seconds``; 0 switches it off."""

    name = "timer"

    def poll(self) -> Signal | None:
        """Always a full run."""
        return full_run(self.name)
