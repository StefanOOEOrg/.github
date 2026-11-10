"""Job watch: a full engine run once a developer job has ended or a run failed (no Hermes change).

The end of a developer job frees its instance, but no GitHub event says so: without this a card
waits on Goal for the next webhook or the hourly run. A no-agent cron of the sw-lead profile runs
``python3 -m loop jobwatch`` every minute; it makes the look of ``JobWatchSource``
(sources/jobwatch.py: the enabled developer jobs against ``cache/dev-jobs.json``) and runs the
engine over the whole board when one is gone. Cheap when nothing changed: one local file read, no
GitHub call. The same full run retries a failed run (``cache/loop-retry.json``, retry.py) at most
every ``RETRY_MINUTES``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from loop import retry
from loop.ports import OutputSink
from loop.sources.jobwatch import look
from loop.tick import tick

logger = logging.getLogger(__name__)


def jobwatch(dry_run: bool = False, now: datetime | None = None,
             sink: OutputSink | None = None) -> int:
    """Run the engine once if a developer job ended or a failed run is due; 0 on success."""
    ended = look()
    pending = retry.due(retry.marker_path(), now or datetime.now(UTC))
    if ended:
        logger.info("developer job(s) ended: %s, full run", ", ".join(sorted(ended)))
    if pending is not None:
        logger.info("retry of a failed run (failing since %s: %s), full run",
                    pending.get("since", "?"), pending.get("reason", "?"))
    if not ended and pending is None:
        return 0
    return tick(dry_run=dry_run, full=True, sink=sink)
