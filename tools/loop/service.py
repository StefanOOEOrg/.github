"""``python3 -m loop listen``: the webhook listener as a long-running service (systemd).

Wiring: HTTP server (listener.py) in its own thread -> in-memory queue -> dispatcher
(dispatcher.py) in the main thread, one engine run at a time (tick.run_scope, in-process) ->
delivery thread (delivery.py) -> LOOP_DELIVER_CMD -> Lead. The queue lives in memory, so every
start queues a full run first: whatever happened while the service was down is read from GitHub.
A clock queues one more every ``FULL_RUN_MINUTES`` for the time rules (it replaces the hourly cron).
SIGTERM stops the HTTP server, lets the dispatcher make one last run over what waits and gives the
open deliveries ``SHUTDOWN_SECONDS``; what is left is logged (events) or kept (messages).
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

from loop import config
from loop.delivery import PENDING, Deliverer, command_sender
from loop.dispatcher import Dispatcher, Engine, now_utc
from loop.events import Event
from loop.listener import WebhookServer, load_secret
from loop.tick import run_scope

logger = logging.getLogger(__name__)


def startup_event() -> Event:
    """The full run every start begins with (recovery: the queue does not survive a restart)."""
    return Event(f"startup-{now_utc():%Y%m%dT%H%M%S%f}", now_utc(), None)


def clock(dispatcher: Dispatcher, stop: threading.Event, seconds: float) -> None:
    """Queue a full run every ``seconds`` until ``stop`` (same serial path as the events)."""
    while seconds > 0 and not stop.wait(seconds):
        dispatcher.submit(Event(f"clock-{now_utc():%Y%m%dT%H%M%S%f}", now_utc(), None))


def serve(engine: Engine = run_scope, stop: threading.Event | None = None) -> int:
    """Run the service until SIGTERM/SIGINT (or ``stop``); 0 after a clean shutdown."""
    stop = stop or threading.Event()
    deliverer = Deliverer(command_sender(config.DELIVER_CMD, config.DELIVER_TIMEOUT_SECONDS),
                          Path(config.CACHE_DIR) / PENDING)
    dispatcher = Dispatcher(engine, deliverer.put)
    server = WebhookServer((config.LISTEN_HOST, config.LISTEN_PORT), load_secret(),
                           dispatcher.submit)
    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: stop.set())
    deliverer.start()
    dispatcher.submit(startup_event())
    http = threading.Thread(target=server.serve_forever, name="loop-http", daemon=True)
    http.start()
    threading.Thread(target=clock, args=(dispatcher, stop, config.FULL_RUN_MINUTES * 60),
                     name="loop-clock", daemon=True).start()
    logger.info("listening on %s:%s, delivering with %r", config.LISTEN_HOST,
                config.LISTEN_PORT, config.DELIVER_CMD)
    try:
        dispatcher.serve(stop)
    finally:
        server.shutdown()  # nothing is accepted after this
        server.server_close()
        dispatcher.finish()
        deliverer.stop(config.SHUTDOWN_SECONDS)
        logger.info("listener stopped")
    return 0
