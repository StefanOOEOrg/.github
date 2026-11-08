"""Job watch: a full engine run as soon as a developer job has ended (no Hermes change).

The end of a developer job frees its instance, but no GitHub event says so: without this a card
waits on Goal for the next webhook or the hourly run. A no-agent cron of the sw-lead profile runs
``python3 -m loop jobwatch`` every minute; it compares the enabled developer jobs with the last
look (``cache/dev-jobs.json``) and runs the engine over the whole board when one is gone. Cheap
when nothing changed: one local file read, no GitHub call.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from loop import config
from loop.tick import scheduled_jobs, tick

logger = logging.getLogger(__name__)


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


def jobwatch(dry_run: bool = False) -> int:
    """Run the engine once if a developer job ended since the last look; 0 on success."""
    jobs = scheduled_jobs(Path(config.DEV_JOBS))
    if jobs is None:
        return 0  # unreadable now, already logged: the next look decides
    ended = ended_jobs(Path(config.CACHE_DIR) / "dev-jobs.json", jobs)
    if not ended:
        return 0
    logger.info("developer job(s) ended: %s, full run", ", ".join(sorted(ended)))
    return tick(dry_run=dry_run, full=True)
