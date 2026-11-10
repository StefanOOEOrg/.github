"""Contract tests of the output sinks: deliver(message) -> accepted, nothing lost or altered."""

import sys

import pytest

from loop import outbox
from loop.sinks import CommandSink, FileSink, HermesBotChatSink, StdoutSink


def test_stdout_sink_prints_the_message(capsys):
    """The Hermes cron path: stdout is the delivery."""
    assert StdoutSink().deliver("Zeile 1\nZeile 2")
    assert capsys.readouterr().out == "Zeile 1\nZeile 2\n"


def test_file_sink_appends(tmp_path):
    """Every message once, in order; an unwritable path is refused."""
    sink = FileSink(tmp_path / "sub" / "out.txt")
    assert sink.deliver("a") and sink.deliver("b")
    assert (tmp_path / "sub" / "out.txt").read_text() == "a\n\nb\n\n"
    (tmp_path / "dir").mkdir()
    assert not FileSink(tmp_path / "dir").deliver("x")


def test_command_sink_reads_the_exit_code(tmp_path):
    """Message on stdin, exit 0 accepted, anything else refused."""
    target = tmp_path / "out.txt"
    script = f"import sys; open({str(target)!r}, 'w').write(sys.stdin.read())"
    assert CommandSink(f"{sys.executable} -c \"{script}\"", 10).deliver("hallo")
    assert target.read_text() == "hallo"
    assert not CommandSink(f"{sys.executable} -c 'raise SystemExit(2)'", 10).deliver("x")


def test_hermes_bot_chat_sink_spools_into_the_outbox(tmp_path, monkeypatch):
    """In the spool means accepted, even if the trigger of loop-deliver fails."""
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("loop.config.OUTBOX_TRIGGER", "/nonexistent/hermes cron run x")
    assert HermesBotChatSink().deliver("Notiz")
    assert outbox.drain(outbox.spool()) == "Notiz"


@pytest.mark.parametrize("sink", [StdoutSink(), HermesBotChatSink(), FileSink(None),
                                  CommandSink("true", 1)])
def test_every_sink_has_a_name(sink):
    """The name is what the log and the configuration show."""
    assert isinstance(sink.name, str) and sink.name
