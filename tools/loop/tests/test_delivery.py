"""Delivery to the Lead: decoupled, ordered, retried, kept over a restart; the outbox spool."""

import sys
import threading

from loop import delivery, outbox
from loop.sinks import CommandSink


def test_put_never_waits_for_the_lead(tmp_path):
    """A send that hangs does not block put(); the message arrives once the Lead is free."""
    free, sent = threading.Event(), []

    def slow(text):
        free.wait(5)
        sent.append(text)
        return True
    deliverer = delivery.Deliverer(slow, tmp_path / "p.jsonl")
    deliverer.start()
    deliverer.put("a")
    deliverer.put("b")  # returns at once although "a" is still in flight
    free.set()
    assert not deliverer.stop(timeout=5) and sent == ["a", "b"]


def test_a_failed_send_is_retried_in_order(tmp_path, monkeypatch):
    """Exit != 0: the same message again after the backoff, the next one only after it."""
    monkeypatch.setattr("loop.config.BACKOFF_FIRST_SECONDS", 0.01)
    answers, sent = [False, True, True], []

    def flaky(text):
        sent.append(text)
        return answers.pop(0)
    deliverer = delivery.Deliverer(flaky, tmp_path / "p.jsonl")
    deliverer.start()
    deliverer.put("a")
    deliverer.put("b")
    assert not deliverer.stop(timeout=5) and sent == ["a", "a", "b"]


def test_open_messages_survive_a_restart(tmp_path, monkeypatch):
    """At shutdown the unsent rest goes to the pending file; the next start sends it first."""
    monkeypatch.setattr("loop.config.BACKOFF_FIRST_SECONDS", 0.01)
    pending = tmp_path / "p.jsonl"
    down = delivery.Deliverer(lambda text: False, pending)
    down.start()
    down.put("eins\nzwei")
    assert down.stop(timeout=0.1) == ["eins\nzwei"]
    sent = []
    up = delivery.Deliverer(lambda text: sent.append(text) or True, pending)
    up.start()
    assert not up.stop(timeout=5) and sent == ["eins\nzwei"] and not pending.exists()


def test_command_sender_passes_stdin_and_reads_the_exit_code(tmp_path):
    """The command gets the message on stdin; exit 0 means accepted."""
    target = tmp_path / "out.txt"
    script = f"import sys; open({str(target)!r}, 'w').write(sys.stdin.read())"
    assert CommandSink(f"{sys.executable} -c \"{script}\"", 10).deliver("hallo")
    assert target.read_text() == "hallo"
    assert not CommandSink(f"{sys.executable} -c 'raise SystemExit(3)'", 10).deliver("x")
    assert not CommandSink("/nonexistent/command", 10).deliver("x")


def test_outbox_spools_in_order_and_drains_once(tmp_path):
    """put() keeps the order; drain() prints everything once and empties the spool."""
    outbox.put(tmp_path, "erste")
    outbox.put(tmp_path, "zweite")
    assert outbox.drain(tmp_path) == "erste\n\nzweite"
    assert outbox.drain(tmp_path) == "" and not list(tmp_path.iterdir())


def test_deliver_accepts_once_spooled_even_if_the_trigger_fails(tmp_path, monkeypatch):
    """The message is in the spool: exit 0, the job delivers it at its next run."""
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("loop.config.OUTBOX_TRIGGER", "/nonexistent/hermes cron run x")
    assert outbox.deliver("Notiz") == 0
    assert outbox.drain(outbox.spool()) == "Notiz"
    assert outbox.deliver("   ") == 0 and not list(outbox.spool().iterdir())
