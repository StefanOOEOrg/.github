"""``GitHubWebhookSource``: the org webhook over HTTP (listener.py, events.py).

HMAC check, the route filter, 202 at once; every accepted delivery becomes a signal. A delivery ID
already seen is answered ``duplicate`` (the dispatcher's dedupe says so through ``submit``).
"""

from __future__ import annotations

import logging
import threading

from loop.listener import WebhookServer
from loop.ports import Submit

logger = logging.getLogger(__name__)


class GitHubWebhookSource:
    """The HTTP server in its own thread; ``stop`` ends it, nothing is accepted after that."""

    name = "webhook"

    def __init__(self, host: str, port: int, secret: bytes) -> None:
        self._address, self._secret = (host, port), secret
        self._server: WebhookServer | None = None

    @property
    def address(self) -> tuple[str, int]:
        """The bound address (the real port once started with port 0)."""
        if self._server is None:
            return self._address
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self, submit: Submit) -> None:
        """Bind and serve in a daemon thread."""
        self._server = WebhookServer(self._address, self._secret, submit)
        threading.Thread(target=self._server.serve_forever, name="loop-http", daemon=True).start()
        logger.info("webhook listening on %s:%s", *self.address)

    def stop(self) -> None:
        """Stop serving and close the socket."""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
