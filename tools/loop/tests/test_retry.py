"""Retry of a failed run: marker, backoff, notice to the Lead, the job watch and the full run."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from loop import __main__ as cli
from loop import jobwatch, retry, tick
from loop.engine import Decisions
from loop.github_client import GitHubError
from loop.scope import Scope

T0 = datetime(2026, 11, 10, 7, 18, tzinfo=UTC)


@pytest.fixture(name="cache")
def fixture_cache(tmp_path, monkeypatch):
    """Cache and developer job list in a temporary directory, no job running."""
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": []}))
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("loop.config.DEV_JOBS", str(jobs))
    return tmp_path


def test_a_failure_is_recorded_silently(cache):
    """The first failure writes the marker and tells nobody."""
    assert retry.record(retry.marker_path(), "error connecting to api.github.com", T0) is None
    marker = json.loads((cache / retry.MARKER).read_text())
    assert marker["since"] == marker["last_try"] == T0.isoformat()
    assert not marker["reported"]


def test_a_long_failure_is_told_to_the_lead_once(cache):
    """After RETRY_REPORT_MINUTES one notice; the first failure stays the start."""
    path = cache / retry.MARKER
    retry.record(path, "first", T0)
    assert retry.record(path, "again", T0 + timedelta(minutes=29)) is None
    notice = retry.record(path, "still", T0 + timedelta(minutes=31))
    assert "31 min" in notice and "still" in notice
    assert retry.record(path, "still", T0 + timedelta(minutes=40)) is None
    assert json.loads(path.read_text())["since"] == T0.isoformat()


@pytest.mark.parametrize("minutes, is_due", [(1, False), (2, False), (3, True), (10, True)])
def test_a_retry_is_due_only_after_the_backoff(cache, minutes, is_due):
    """One retry per RETRY_MINUTES (3) after the last failure, not every minute."""
    retry.record(cache / retry.MARKER, "x", T0)
    found = retry.due(cache / retry.MARKER, T0 + timedelta(minutes=minutes))
    assert (found is not None) is is_due


def test_no_marker_no_retry_and_a_broken_marker_is_due(cache):
    """Without a marker nothing is due; an unreadable one is retried at once."""
    path = cache / retry.MARKER
    assert retry.due(path, T0) is None
    path.write_text("{broken")
    assert retry.due(path, T0) == {}


@pytest.mark.parametrize("told, expected", [(False, None), (True, "nach 45 min")])
def test_clear_removes_the_marker_and_tells_the_end_only_if_the_start_was_told(cache, told,
                                                                               expected):
    """A successful full run ends the retries; the Lead hears of it only after a notice."""
    path = cache / retry.MARKER
    path.write_text(json.dumps({"since": T0.isoformat(), "reported": told}))
    line = retry.clear(path, T0 + timedelta(minutes=45))
    assert not path.exists()
    assert line is None if expected is None else expected in line
    assert retry.clear(path, T0) is None


@pytest.mark.parametrize("age, runs", [(1, []), (5, [True])])
def test_jobwatch_retries_a_failed_run_as_a_full_run(cache, monkeypatch, age, runs):
    """The job watch turns a due marker into a full run, even with no job ended."""
    retry.record(cache / retry.MARKER, "x", T0)
    called = []
    monkeypatch.setattr(jobwatch, "tick", lambda dry_run, full: called.append(full) or 0)
    assert jobwatch.jobwatch(now=T0 + timedelta(minutes=age)) == 0 and called == runs


def failing(error):
    """A run that raises ``error``."""
    def run(dry_run=False):
        raise error
    return run


def test_a_failed_tick_leaves_the_marker_and_exits_1(cache, monkeypatch):
    """GitHub unreachable: exit 1 as before, and the job watch has something to retry."""
    monkeypatch.setattr(cli, "tick", failing(GitHubError("error connecting to api.github.com")))
    assert cli.main(["tick"]) == 1
    assert "api.github.com" in json.loads((cache / retry.MARKER).read_text())["reason"]


def test_a_dry_run_leaves_no_marker(cache, monkeypatch):
    """A dry run writes nothing, not even the marker."""
    monkeypatch.setattr(cli, "tick", failing(TimeoutError("lock")))
    assert cli.main(["tick", "--dry-run"]) == 1
    assert not (cache / retry.MARKER).exists()


def test_a_crash_leaves_the_marker_too(cache, monkeypatch):
    """An unexpected error still propagates (traceback in the log), but is retried."""
    monkeypatch.setattr(cli, "tick", failing(KeyError("bug")))
    with pytest.raises(KeyError):
        cli.main(["tick"])
    assert json.loads((cache / retry.MARKER).read_text())["reason"] == "crashed"


def test_the_notice_of_a_long_failure_exits_0_to_reach_the_lead(cache, monkeypatch, capsys):
    """Hermes delivers only a successful run's output: the one notice exits 0."""
    (cache / retry.MARKER).write_text(json.dumps({"since": "2026-01-01T00:00:00+00:00"}))
    monkeypatch.setattr(cli, "tick", failing(GitHubError("502")))
    assert cli.main(["tick"]) == 0
    assert "Loop-Engine" in capsys.readouterr().out
    assert cli.main(["tick"]) == 1  # told once


@pytest.mark.parametrize("full, kept", [(True, False), (False, True)])
def test_only_a_successful_full_run_removes_the_marker(cache, monkeypatch, full, kept):
    """A one-card run may not cover the lost event; the full run does."""
    retry.record(cache / retry.MARKER, "x", T0)
    monkeypatch.setattr(tick, "scope_of", lambda event: Scope(("O/r", 1), "issues.edited"))
    monkeypatch.setattr(tick, "GitHubClient", lambda: None)
    monkeypatch.setattr(tick, "decide_scope", lambda client, scope, now: Decisions())
    monkeypatch.setattr(tick, "GitHubWriter", lambda dry_run: None)
    monkeypatch.setattr(tick, "apply", lambda *args: ([], []))
    assert tick.tick(full=full) == 0
    assert (cache / retry.MARKER).exists() is kept
