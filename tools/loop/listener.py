"""HTTP listener for the GitHub org webhook: verify, filter, queue, answer at once.

POST only. ``X-Hub-Signature-256`` is checked against the secret (401 if it does not match), the
route filter of events.py decides (200 ``ignored``), a delivery already seen is answered 200
``duplicate``, an accepted one is queued and answered 202 before any engine run starts. GitHub
waits 10 s for an answer; this one takes milliseconds.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loop import config
from loop.events import Event, accept, rejection

logger = logging.getLogger(__name__)

Submit = Callable[[Event], bool]


def load_secret() -> bytes:
    """The webhook secret from LOOP_WEBHOOK_SECRET or LOOP_WEBHOOK_SECRET_FILE; never logged."""
    secret = os.environ.get("LOOP_WEBHOOK_SECRET", "")
    path = os.environ.get("LOOP_WEBHOOK_SECRET_FILE", "")
    if not secret and path:
        secret = Path(path).read_text(encoding="utf-8").strip()
    if not secret:
        raise ValueError("LOOP_WEBHOOK_SECRET or LOOP_WEBHOOK_SECRET_FILE required")
    return secret.encode()


def signature_ok(secret: bytes, body: bytes, header: str | None) -> bool:
    """True if ``header`` is the HMAC-SHA256 of ``body`` under ``secret``."""
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(expected, str(header))


class WebhookServer(ThreadingHTTPServer):
    """The HTTP server with what its handlers need."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], secret: bytes, submit: Submit) -> None:
        super().__init__(address, WebhookHandler)
        self.secret, self.submit = secret, submit


class WebhookHandler(BaseHTTPRequestHandler):
    """One request."""

    server: WebhookServer

    def _answer(self, code: int, text: str) -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes | None:
        """The request body, None (after answering) if it is too large or malformed."""
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = -1
        if length < 0 or length > config.MAX_BODY_BYTES:
            self._answer(413, "body too large or malformed")
            return None
        return self.rfile.read(length)

    def handle_post(self) -> None:
        """Verify, filter and queue one delivery."""
        if config.LISTEN_PATH and self.path.split("?")[0] != config.LISTEN_PATH:
            self._answer(404, "not found")
            return
        body = self._body()
        if body is None:
            return
        if not signature_ok(self.server.secret, body, self.headers.get("X-Hub-Signature-256")):
            logger.warning("rejected: bad signature from %s", self.client_address[0])
            self._answer(401, "bad signature")
            return
        kind = self.headers.get("X-GitHub-Event") or ""
        delivery = self.headers.get("X-GitHub-Delivery") or ""
        try:
            payload = json.loads(body)
        except ValueError:
            self._answer(400, "no JSON")
            return
        if not isinstance(payload, dict) or not delivery:
            self._answer(400, "no delivery")
            return
        event = accept(kind, delivery, payload, datetime.now(UTC))
        if event is None:
            logger.info("ignored %s %s: %s", delivery, kind, rejection(kind, payload))
            self._answer(200, "ignored")
            return
        self._answer(202, "queued" if self.server.submit(event) else "duplicate")

    do_POST = handle_post  # the name http.server dispatches to

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """No access line per request: the handler logs what matters."""
        logger.debug("%s %s -> %s", self.command, self.path, code)
