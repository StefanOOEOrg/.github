"""Adapters of the port ``OutputSink`` (ports.py): where the engine's lines go.

``deliver`` is synchronous and says whether the message was accepted; a sink that may wait (a
command, Hermes) is decoupled from the engine runs by ``delivery.Deliverer`` in the listener.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

from loop import outbox

logger = logging.getLogger(__name__)


class BaseSink:
    """What every sink shares: ``deliver_lines`` on top of the adapter's ``deliver``."""

    name = "base"

    def deliver(self, message: str) -> bool:
        """Hand over one message (each adapter implements it)."""
        raise NotImplementedError

    def deliver_lines(self, lines: list[str]) -> bool:
        """The lines of one run as one message; nothing (and True) without lines."""
        return not lines or self.deliver("\n".join(lines))


class StdoutSink(BaseSink):
    """Prints the message: the Hermes cron path, where Hermes delivers stdout to the Lead."""

    name = "stdout"

    def deliver(self, message: str) -> bool:
        """Print and flush."""
        print(message, flush=True)
        return True


class CommandSink(BaseSink):
    """Runs a command (no shell) with the message on stdin; exit 0 means accepted."""

    name = "command"

    def __init__(self, command: str, timeout: float) -> None:
        self.argv, self.timeout = shlex.split(command), timeout

    def deliver(self, message: str) -> bool:
        """Run the command once."""
        try:
            done = subprocess.run(self.argv, input=message, text=True, capture_output=True,
                                  timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("delivery command failed: %s", error)
            return False
        if done.returncode:
            logger.warning("delivery command exited %d: %s", done.returncode,
                           done.stderr.strip()[-300:])
        return done.returncode == 0


class HermesBotChatSink(BaseSink):
    """The outbox (``cache/outbox``) and the no-agent cron ``loop-deliver`` → Bot Chat.

    The same as the default command ``python3 -m loop deliver``, in-process (outbox.py).
    """

    name = "hermes-outbox"

    def deliver(self, message: str) -> bool:
        """Spool and fire the cron; accepted once the message is in the spool."""
        return outbox.deliver(message) == 0


class FileSink(BaseSink):
    """Appends each message and a blank line to a file (tests, a dry run, a log for a human)."""

    name = "file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def deliver(self, message: str) -> bool:
        """Append; False if the file cannot be written."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n\n")
        except OSError as error:
            logger.warning("file sink %s not writable: %s", self.path, error)
            return False
        return True
