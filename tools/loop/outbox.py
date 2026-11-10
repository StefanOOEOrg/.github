"""Default delivery command: a spool in cache/outbox and the Hermes cron job that empties it.

``python3 -m loop deliver`` (LOOP_DELIVER_CMD default) writes stdin as one file into the spool and
fires the no-agent cron ``loop-deliver`` (LOOP_OUTBOX_TRIGGER). That job runs loop-deliver.sh,
``python3 -m loop outbox``, which prints every spooled message in order and removes it; Hermes
delivers the output to bot-chat:sw-lead through its asynchronous pending lane (local patch). A
message that is in the spool counts as accepted: if the trigger fails, the next message's trigger
or the job's own schedule delivers it.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from loop import config

logger = logging.getLogger(__name__)


def spool() -> Path:
    """The spool directory (read from config at call time, tests patch it)."""
    return Path(config.CACHE_DIR) / "outbox"


def put(directory: Path, text: str) -> Path:
    """Write one message atomically; names sort in the order of writing."""
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{os.getpid()}.txt"
    temporary = directory / f".{name}"
    temporary.write_text(text, encoding="utf-8")
    temporary.rename(directory / name)
    return directory / name


def drain(directory: Path) -> str:
    """Every spooled message in order, removed from the spool."""
    if not directory.is_dir():
        return ""
    texts = []
    for path in sorted(directory.glob("*.txt")):
        texts.append(path.read_text(encoding="utf-8").strip())
        path.unlink()
    return "\n\n".join(text for text in texts if text)


def deliver(text: str) -> int:
    """Spool ``text`` and fire the delivery job; 1 only if the spool could not be written."""
    if not text.strip():
        return 0
    try:
        put(spool(), text)
    except OSError as error:
        logger.error("outbox not writable: %s", error)
        return 1
    try:
        done = subprocess.run(shlex.split(config.OUTBOX_TRIGGER), capture_output=True, text=True,
                              timeout=config.DELIVER_TIMEOUT_SECONDS, check=False)
        if done.returncode:
            logger.warning("trigger exited %d: %s", done.returncode, done.stderr.strip()[-300:])
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("trigger failed, the message waits in the outbox: %s", error)
    return 0


def main(command: str) -> int:
    """``deliver`` (stdin into the spool) or ``outbox`` (print and empty the spool)."""
    if command == "deliver":
        return deliver(sys.stdin.read())
    text = drain(spool())
    if text:
        print(text)
    return 0
