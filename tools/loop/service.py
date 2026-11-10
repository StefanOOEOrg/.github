"""``python3 -m loop listen``: the listener as a long-running service (systemd).

Wiring (wiring.py picks the adapters): signal sources (default ``LOOP_SOURCES=webhook,timer``:
the HTTP server for the org webhook and the clock) -> one in-memory queue -> dispatcher
(dispatcher.py) in the main thread, one engine run at a time (tick.run_scope, in-process) ->
delivery thread (delivery.py) -> output sink (default ``LOOP_SINK=command``: LOOP_DELIVER_CMD).
The queue lives in memory, so every start queues a full run first: whatever happened while the
service was down is read from GitHub. SIGTERM stops the sources, lets the dispatcher make one last
run over what waits and gives the open deliveries ``SHUTDOWN_SECONDS``; what is left is logged
(signals) or kept (messages).
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

from loop import config, wiring
from loop.delivery import PENDING, Deliverer
from loop.dispatcher import Dispatcher, Engine
from loop.ports import OutputSink, SignalSource
from loop.signals import Signal, full_run
from loop.tick import run_scope

logger = logging.getLogger(__name__)


def startup_event() -> Signal:
    """The full run every start begins with (recovery: the queue does not survive a restart)."""
    return full_run("startup")


def serve(engine: Engine = run_scope, stop: threading.Event | None = None,
          sources: list[SignalSource] | None = None, sink: OutputSink | None = None) -> int:
    """Run the service until SIGTERM/SIGINT (or ``stop``); 0 after a clean shutdown.

    ``sources`` and ``sink`` default to the configuration (wiring.py).
    """
    stop = stop or threading.Event()
    sources = wiring.build_sources() if sources is None else sources
    sink = sink or wiring.build_sink()
    deliverer = Deliverer(sink.deliver, Path(config.CACHE_DIR) / PENDING)
    dispatcher = Dispatcher(engine, deliverer.put)
    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: stop.set())
    deliverer.start()
    dispatcher.submit(startup_event())
    started: list[SignalSource] = []
    try:
        for source in sources:
            source.start(dispatcher.submit)
            started.append(source)
        logger.info("listener running: sources %s, sink %s",
                    ", ".join(source.name for source in sources), sink.name)
        dispatcher.serve(stop)
    finally:
        for source in started:
            source.stop()  # nothing is accepted after this
        dispatcher.finish()
        deliverer.stop(config.SHUTDOWN_SECONDS)
        logger.info("listener stopped")
    return 0
