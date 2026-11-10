"""Composition root and several sources at once: one serial queue, one sink, no signal lost."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from loop import service, tick, wiring
from loop.signals import Signal, Subject, full_run
from loop.sinks import CommandSink, StdoutSink
from loop.sources.github_webhook import GitHubWebhookSource
from loop.sources.timer import TimerSource
from loop.tests.fakes import FakeSink, FakeSource

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def comment(delivery, minute=0):
    """A webhook signal for an owner comment on Argus#109."""
    return Signal("webhook", delivery, T0 + timedelta(minutes=minute),
                  Subject("issue_comment", "created", "StefanOOEOrg/Argus", "109"))


def test_defaults_are_the_listener_as_built(monkeypatch):
    """No configuration: webhook + timer, LOOP_DELIVER_CMD; cron runs print to stdout."""
    monkeypatch.setenv("LOOP_WEBHOOK_SECRET", "s")
    sources = wiring.build_sources()
    assert [type(source) for source in sources] == [GitHubWebhookSource, TimerSource]
    assert isinstance(wiring.build_sink(), CommandSink)
    assert isinstance(wiring.tick_sink(), StdoutSink)


def test_sources_and_sink_are_chosen_by_name(monkeypatch, tmp_path):
    """LOOP_SOURCES / LOOP_SINK pick from the registry; blanks and repeats do not matter."""
    monkeypatch.setattr("loop.config.FILE_SINK", str(tmp_path / "o.txt"))
    sources = wiring.build_sources(" timer, jobwatch,timer ,")
    assert [source.name for source in sources] == ["timer", "jobwatch"]
    assert wiring.build_sink("file").deliver("x") and (tmp_path / "o.txt").exists()


@pytest.mark.parametrize("call", [lambda: wiring.build_sources("timer,nope"),
                                  lambda: wiring.build_sources(" , "),
                                  lambda: wiring.build_sink("nope")])
def test_unknown_or_no_adapter_is_refused(call):
    """A typo stops the start instead of running without a source or output."""
    with pytest.raises(ValueError):
        call()


def test_a_new_adapter_is_one_registration(monkeypatch):
    """register_source / register_sink: the name works in the configuration."""
    monkeypatch.setattr(wiring, "SOURCES", dict(wiring.SOURCES))
    monkeypatch.setattr(wiring, "SINKS", dict(wiring.SINKS))
    wiring.register_source("fake", lambda: FakeSource("fake"))
    wiring.register_sink("fake", FakeSink)
    assert wiring.build_sources("fake")[0].name == "fake"
    assert isinstance(wiring.build_sink("fake"), FakeSink)


def test_several_sources_feed_one_serial_queue(tmp_path, monkeypatch):
    """Two sources at once: every signal runs, never two runs at once, every message delivered."""
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("loop.config.SHUTDOWN_SECONDS", 5)
    monkeypatch.setattr("loop.config.BACKOFF_FIRST_SECONDS", 0.01)
    first = FakeSource("hook", comment("a"), comment("b", minute=1))
    second = FakeSource("clock", full_run("clock", T0))
    sink, stop, scopes, active = FakeSink(refusals=1), threading.Event(), [], []

    def engine(scope):
        active.append(1)
        assert len(active) == 1  # never two runs at once
        scopes.append(scope)
        active.pop()
        stop.set()  # the shutdown's last run takes what still waits
        return [f"run {len(scopes)}"]
    assert service.serve(engine, stop, [first, second], sink) == 0
    assert first.stopped and second.stopped
    assert 1 <= len(scopes) <= 2 and all(scope.full for scope in scopes)
    assert sink.messages == [f"run {n}" for n in range(1, len(scopes) + 1)]  # refusal retried


def test_tick_delivers_to_the_given_sink(monkeypatch):
    """The cron run: HermesCronSource -> scope -> engine -> sink; no lines, no message."""
    monkeypatch.setenv("HERMES_CRON_EVENT", '{"event": "issues", "action": "opened", '
                                            '"repo": "O/r", "issue": "4"}')
    seen, sink = [], FakeSink()
    monkeypatch.setattr(tick, "run_scope", lambda scope, dry_run: seen.append(scope) or ["x"])
    assert tick.tick(sink=sink) == 0 and seen[0].card == ("O/r", 4) and sink.messages == ["x"]
    monkeypatch.setattr(tick, "run_scope", lambda scope, dry_run: [])
    assert tick.tick(full=True, sink=sink) == 0 and sink.messages == ["x"]
