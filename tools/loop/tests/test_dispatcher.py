"""Dispatcher: order, dedupe, coalescing, retry without loss, notices, start and shutdown."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from loop import dispatcher, service
from loop.events import Event
from loop.github_client import GitHubError

T0 = datetime(2026, 11, 10, 10, 49, tzinfo=UTC)


def event(delivery, minute=0, issue="109", action="created", kind="issue_comment"):
    """An accepted event at T0 + ``minute``."""
    return Event(delivery, T0 + timedelta(minutes=minute), {
        "event": kind, "action": action, "repo": "StefanOOEOrg/Argus", "issue": issue,
        "pr": "", "item": "", "sender": "StefanOOE"})


def fake_engine(failures=0, lines=("line",)):
    """A fake engine that records its scopes in ``.scopes`` and fails ``failures`` times first."""
    left = [failures]

    def run(scope):
        run.scopes.append(scope)
        if left[0]:
            left[0] -= 1
            raise GitHubError("error connecting to api.github.com")
        return list(lines)
    run.scopes = []
    return run


@pytest.fixture(name="setup")
def fixture_setup(tmp_path, monkeypatch):
    """Dispatcher with a fake engine and the delivered messages."""
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    delivered = []

    def make(engine):
        return dispatcher.Dispatcher(engine, delivered.append, clock=lambda: T0)
    return make, delivered


def test_one_event_keeps_its_own_scope(setup):
    """A lone owner comment is a one-card run, its lines go to the Lead."""
    make, delivered = setup
    engine = fake_engine()
    run = make(engine)
    run.submit(event("a"))
    assert run.run_once(timeout=0) is True
    assert engine.scopes[0].card == ("StefanOOEOrg/Argus", 109)
    assert delivered == ["line"]


def test_waiting_events_become_one_full_run(setup):
    """Three queued events: one run over the whole board, nothing left."""
    make, _ = setup
    engine = fake_engine()
    run = make(engine)
    for name in "abc":
        run.submit(event(name))
    assert run.run_once(timeout=0) is True
    assert len(engine.scopes) == 1 and engine.scopes[0].full
    assert run.pending() == 0


def test_events_are_taken_in_event_time_order(setup):
    """A later-arriving older event comes first."""
    make, _ = setup
    run = make(fake_engine())
    run.submit(event("late", minute=5))
    run.submit(event("early", minute=1))
    run.submit(event("middle", minute=3))
    assert run.waiting() == ["early", "middle", "late"]


def test_a_redelivery_is_dropped(setup):
    """The same X-GitHub-Delivery is queued once."""
    make, _ = setup
    run = make(fake_engine())
    assert run.submit(event("a")) and not run.submit(event("a"))
    assert run.pending() == 1


def test_a_failed_run_keeps_every_event_and_backs_off(setup):
    """GitHub down: the events stay, the backoff doubles; then the retry runs them."""
    make, delivered = setup
    engine = fake_engine(failures=2)
    run = make(engine)
    run.submit(event("a"))
    run.submit(event("b"))
    assert run.run_once(timeout=0) is False and run.pending() == 2 and run.backoff == 5
    assert run.run_once(timeout=0) is False and run.pending() == 2 and run.backoff == 10
    run.submit(event("c"))  # arrived during the outage: joins the retry
    assert run.run_once(timeout=0) is True and run.pending() == 0 and run.backoff == 0
    assert engine.scopes[-1].full and delivered == ["line"]


def test_a_long_failure_is_told_and_the_recovery_too(setup, monkeypatch):
    """After RETRY_REPORT_MINUTES one notice, and one when runs work again."""
    _, delivered = setup
    now = [T0]
    engine = fake_engine(failures=2, lines=())
    run = dispatcher.Dispatcher(engine, delivered.append, clock=lambda: now[0])
    monkeypatch.setattr("loop.config.RETRY_REPORT_MINUTES", 30)
    run.submit(event("a"))
    run.run_once(timeout=0)
    now[0] = T0 + timedelta(minutes=31)
    run.run_once(timeout=0)
    run.run_once(timeout=0)
    assert len(delivered) == 2
    assert "seit 31 min" in delivered[0] and "Listener" in delivered[0]
    assert "läuft wieder" in delivered[1]


def test_an_unexpected_error_ends_the_dispatcher(setup):
    """A bug is not retried forever: it propagates (systemd restarts, start = full run)."""
    make, _ = setup

    def broken(scope):
        raise KeyError("bug")
    run = make(broken)
    run.submit(event("a"))
    with pytest.raises(KeyError):
        run.run_once(timeout=0)


def test_startup_event_is_a_full_run():
    """The recovery run at start reads the whole board."""
    assert service.startup_event().scope.full


def test_finish_runs_what_waits_and_names_what_failed(setup):
    """Shutdown: one last run; if it fails, the IDs are returned (and logged)."""
    make, _ = setup
    run = make(fake_engine())
    run.submit(event("a"))
    assert not run.finish() and run.pending() == 0
    failing = make(fake_engine(failures=1))
    failing.submit(event("b"))
    assert failing.finish() == ["b"]


def test_serve_stops_on_the_signal(setup):
    """serve() runs events until stop is set."""
    make, delivered = setup
    run = make(fake_engine())
    stop = threading.Event()
    thread = threading.Thread(target=run.serve, args=(stop,))
    thread.start()
    run.submit(event("a"))
    for _ in range(50):
        if delivered:
            break
        stop.wait(0.05)
    stop.set()
    thread.join(timeout=5)
    assert delivered == ["line"] and not thread.is_alive()
