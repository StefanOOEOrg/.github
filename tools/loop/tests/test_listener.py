"""Webhook listener: signature, route filter, signal, event time and the HTTP answers."""

import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime

import pytest

from loop import events, listener

SECRET = b"test-secret"
T0 = datetime(2026, 11, 10, 10, 49, 20, tzinfo=UTC)


def payload(sender="StefanOOE", org="StefanOOEOrg", **extra):
    """A minimal org webhook payload."""
    return {"action": "submitted", "organization": {"login": org}, "sender": {"login": sender},
            "repository": {"full_name": "StefanOOEOrg/Argus"}, **extra}


def sign(body: bytes, secret: bytes = SECRET) -> str:
    """The X-Hub-Signature-256 header GitHub would send."""
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_signature_matches_only_with_the_secret():
    """The right HMAC passes; another secret, a changed body or no header do not."""
    body = b'{"a": 1}'
    assert listener.signature_ok(SECRET, body, sign(body))
    assert not listener.signature_ok(SECRET, body, sign(body, b"other"))
    assert not listener.signature_ok(SECRET, body + b" ", sign(body))
    assert not listener.signature_ok(SECRET, body, None)


@pytest.mark.parametrize("kind, data, reason", [
    ("pull_request_review", payload(), None),
    ("ping", payload(action=None), None),
    ("push", payload(), "event push"),
    ("pull_request", payload(action="synchronize"), "pull_request.synchronize"),
    ("pull_request_review", payload(org="Other"), "other org"),
    ("projects_v2_item", payload("StefanOOELeadBot", action="edited"), "engine write"),
    ("issues", payload("StefanOOELeadBot", action="assigned"), "engine write"),
    ("issue_comment", payload("StefanOOELeadBot", action="created"), "engine write"),
    ("issues", payload("StefanOOELeadBot", action="closed"), None),  # not an engine write
    ("pull_request", payload(action="opened", pull_request={
        "head": {"repo": {"owner": {"login": "someone"}}}}), "fork"),
    ("pull_request", payload(action="opened", pull_request={
        "head": {"repo": {"owner": {"login": "StefanOOEOrg"}}}}), None),
])
def test_route_filter(kind, data, reason):
    """The filter of the former Hermes route `loop`."""
    assert events.rejection(kind, data) == reason


def test_signal_is_the_route_json_and_scopes_like_hermes_cron_event():
    """{event, action, repo, issue, pr, item, sender}; an owner comment is a one-card run."""
    data = payload(action="created", issue={"number": 109},
                   comment={"updated_at": "2026-11-10T10:49:20Z"})
    event = events.accept("issue_comment", "d1", data, datetime(2027, 1, 1, tzinfo=UTC))
    assert event.signal == {"event": "issue_comment", "action": "created",
                            "repo": "StefanOOEOrg/Argus", "issue": "109", "pr": "", "item": "",
                            "sender": "StefanOOE"}
    assert event.scope.card == ("StefanOOEOrg/Argus", 109)
    assert event.at == T0


def test_event_time_falls_back_to_the_receipt():
    """A payload without a time field is ordered by when it arrived."""
    assert events.event_time({"issue": {"updated_at": None}}, T0) == T0


@pytest.fixture(name="server")
def fixture_server():
    """A live listener on a free port; yields (url, queued events)."""
    queued = []
    seen = set()

    def submit(event):
        if event.delivery in seen:
            return False
        seen.add(event.delivery)
        queued.append(event)
        return True
    server = listener.WebhookServer(("127.0.0.1", 0), SECRET, submit)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/hook", queued
    server.shutdown()
    server.server_close()


def post(url, kind, data, delivery="d1", signature=None):
    """POST like GitHub; returns (status, text)."""
    body = json.dumps(data).encode()
    request = urllib.request.Request(url, body, method="POST", headers={
        "X-GitHub-Event": kind, "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": signature or sign(body), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_http_accepts_a_signed_event_at_once(server):
    """202 queued; the engine has not run (the queue holds it)."""
    url, queued = server
    assert post(url, "pull_request_review", payload()) == (202, "queued")
    assert [e.delivery for e in queued] == ["d1"]


def test_http_rejects_a_bad_signature(server):
    """401, nothing queued."""
    url, queued = server
    assert post(url, "pull_request_review", payload(), signature="sha256=00")[0] == 401
    assert not queued


def test_http_ignores_filtered_events_and_redeliveries(server):
    """A filtered event and a redelivery are answered 200 and not queued (again)."""
    url, queued = server
    assert post(url, "push", payload()) == (200, "ignored")
    assert post(url, "issues", payload(action="opened"), "d2")[0] == 202
    assert post(url, "issues", payload(action="opened"), "d2") == (202, "duplicate")
    assert len(queued) == 1


def test_secret_from_a_file(tmp_path, monkeypatch):
    """LOOP_WEBHOOK_SECRET_FILE is read and stripped; no secret at all is refused."""
    monkeypatch.delenv("LOOP_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("LOOP_WEBHOOK_SECRET_FILE", raising=False)
    with pytest.raises(ValueError):
        listener.load_secret()
    (tmp_path / "s").write_text("abc\n")
    monkeypatch.setenv("LOOP_WEBHOOK_SECRET_FILE", str(tmp_path / "s"))
    assert listener.load_secret() == b"abc"
