"""``JobWatchSource``: a full run once a developer job has ended (no GitHub event says so).

The same look as the cron ``loop-jobwatch`` (jobwatch.py): the enabled developer jobs against the
last look in ``cache/dev-jobs.json``. Both share that file, so a job end fires one run, in whichever
of the two looks first. One local file read per look, no GitHub call.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from loop import config
from loop.signals import Signal, full_run
from loop.sources.polling import PollingSource
from loop.tick import scheduled_jobs

logger = logging.getLogger(__name__)

STATE = "dev-jobs.json"


def ended_jobs(state: Path, jobs: set[str]) -> set[str]:
    """The jobs enabled at the last look and gone now; remembers ``jobs`` for the next look.

    The first look (no state yet) only remembers: it cannot know what ended before it.
    """
    try:
        before = set(json.loads(state.read_text()))
    except (OSError, ValueError):
        before = None
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(sorted(jobs)))
    return set() if before is None else before - jobs


def look() -> set[str]:
    """The developer jobs that ended since the last look ({} if the job list is unreadable)."""
    jobs = scheduled_jobs(Path(config.DEV_JOBS))  # None: unreadable, already logged
    return set() if jobs is None else ended_jobs(Path(config.CACHE_DIR) / STATE, jobs)


class JobWatchSource(PollingSource):
    """A full-run signal after a look that found an ended developer job."""

    name = "jobwatch"

    def poll(self) -> Signal | None:
        """A full run if a job ended since the last look."""
        ended = look()
        if not ended:
            return None
        logger.info("developer job(s) ended: %s, full run", ", ".join(sorted(ended)))
        return full_run("jobwatch")
