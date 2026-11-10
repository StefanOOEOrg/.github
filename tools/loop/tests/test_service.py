"""The service as a whole: a start begins with a full run, a stop ends cleanly."""

import sys
import threading
from types import SimpleNamespace

from loop import service


def test_start_runs_the_whole_board_and_stop_ends_cleanly(tmp_path, monkeypatch):
    """serve(): the startup full run, its lines through LOOP_DELIVER_CMD, then a clean stop."""
    out = tmp_path / "lead.txt"
    script = f"import sys; open({str(out)!r}, 'a').write(sys.stdin.read())"
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("loop.config.LISTEN_PORT", 0)
    monkeypatch.setattr("loop.config.SHUTDOWN_SECONDS", 5)
    monkeypatch.setattr("loop.config.DELIVER_CMD", f"{sys.executable} -c \"{script}\"")
    monkeypatch.setenv("LOOP_WEBHOOK_SECRET", "s")
    scopes, stop = [], threading.Event()

    def engine(scope):
        scopes.append(scope)
        stop.set()  # one run is enough for this test
        return ["Notiz an den Lead"]
    assert service.serve(engine, stop) == 0
    assert len(scopes) == 1 and scopes[0].full
    assert out.read_text() == "Notiz an den Lead"




def test_the_clock_queues_full_runs_until_stopped():
    """Every interval one full-run event until stop; 0 switches the clock off."""
    stop, queued = threading.Event(), []

    def submit(event):
        queued.append(event)
        if len(queued) == 2:
            stop.set()
    service.clock(SimpleNamespace(submit=submit), stop, seconds=0)
    assert not queued
    service.clock(SimpleNamespace(submit=submit), stop, seconds=0.01)
    assert len(queued) == 2 and all(event.scope.full for event in queued)
