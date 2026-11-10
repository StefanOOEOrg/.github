"""Contract tests of the signal sources: start submits Signals, stop ends cleanly and twice."""

import hashlib
import hmac
import json
import threading
import urllib.request

import pytest

from loop.scope import scope_for
from loop.signals import Signal
from loop.sources.github_webhook import GitHubWebhookSource
from loop.sources.hermes_cron import HermesCronSource
from loop.sources.jobwatch import JobWatchSource
from loop.sources.timer import TimerSource


def collect(count=1):
    """A submit that records signals; ``done`` is set after ``count`` of them."""
    got, done = [], threading.Event()

    def submit(signal):
        assert isinstance(signal, Signal)
        got.append(signal)
        if len(got) >= count:
            done.set()
        return True
    return submit, got, done


def test_timer_submits_full_runs_until_stopped():
    """Every interval one full-run signal; nothing after stop."""
    submit, got, done = collect(2)
    source = TimerSource(0.01)
    source.start(submit)
    assert done.wait(5)
    source.stop()
    source.stop()
    count = len(got)
    assert all(signal.full and signal.source == "timer" for signal in got)
    threading.Event().wait(0.05)
    assert len(got) == count


def test_timer_zero_is_switched_off():
    """0 minutes: no thread, no signal."""
    submit, got, _ = collect()
    source = TimerSource(0)
    source.start(submit)
    source.stop()
    assert not got


def test_jobwatch_source_signals_an_ended_job(tmp_path, monkeypatch):
    """A job gone since the last look: one full run; the first look only remembers."""
    jobs = tmp_path / "jobs.json"
    monkeypatch.setattr("loop.config.DEV_JOBS", str(jobs))
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    jobs.write_text(json.dumps({"jobs": [{"name": "dev-1-r-1", "enabled": True}]}))
    source = JobWatchSource(60)
    assert source.poll() is None
    jobs.write_text(json.dumps({"jobs": []}))
    signal = source.poll()
    assert signal.full and signal.source == "jobwatch"
    assert source.poll() is None


@pytest.mark.parametrize("context, card", [
    (None, None),
    ('Event:\n{"event": "issue_comment", "action": "created", "repo": "O/r", "issue": "7"}',
     ("O/r", 7)),
    ('{"event": "{event}", "action": "{action}"}', None),
])
def test_hermes_cron_source_reads_the_cron_event(context, card, monkeypatch):
    """One signal per start: the route JSON's subject, or a full run without one."""
    monkeypatch.delenv("HERMES_CRON_EVENT", raising=False)
    submit, got, _ = collect()
    source = HermesCronSource(context)
    source.start(submit)
    source.stop()
    assert len(got) == 1 and got[0].source == "hermes-cron"
    assert scope_for(got[0]).card == card


def test_hermes_cron_source_reads_the_environment(monkeypatch):
    """Without a context the variable HERMES_CRON_EVENT is read."""
    monkeypatch.setenv("HERMES_CRON_EVENT", '{"event": "issues", "action": "opened", '
                                            '"repo": "O/r", "issue": "3"}')
    assert scope_for(HermesCronSource().read()).card == ("O/r", 3)


def test_webhook_source_serves_until_stopped():
    """A signed delivery becomes a webhook signal; after stop the port is closed."""
    submit, got, done = collect()
    source = GitHubWebhookSource("127.0.0.1", 0, b"s")
    source.start(submit)
    host, port = source.address
    body = json.dumps({"action": "opened", "organization": {"login": "StefanOOEOrg"},
                       "repository": {"full_name": "StefanOOEOrg/Argus"},
                       "issue": {"number": 5}}).encode()
    request = urllib.request.Request(f"http://{host}:{port}/", body, method="POST", headers={
        "X-GitHub-Event": "issues", "X-GitHub-Delivery": "d9",
        "X-Hub-Signature-256": "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()})
    with urllib.request.urlopen(request, timeout=5) as answer:
        assert answer.status == 202
    assert done.wait(5) and got[0].source == "webhook" and got[0].delivery_id == "d9"
    source.stop()
    source.stop()
    with pytest.raises(OSError), urllib.request.urlopen(request, timeout=2):
        pass
