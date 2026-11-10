"""Composition root: which signal sources and which output sink the loop runs with.

The registries below map a configuration name to a factory; ``LOOP_SOURCES``, ``LOOP_SINK`` and
``LOOP_TICK_SINK`` (config.py) pick from them. Nothing else in the engine names an adapter. A new
adapter: a class that fulfils ``SignalSource`` or ``OutputSink`` (ports.py), one entry here (or
``register_source`` / ``register_sink`` at start), its name in the configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loop import config
from loop.listener import load_secret
from loop.ports import OutputSink, SignalSource
from loop.sinks import CommandSink, FileSink, HermesBotChatSink, StdoutSink
from loop.sources.github_webhook import GitHubWebhookSource
from loop.sources.hermes_cron import HermesCronSource
from loop.sources.jobwatch import JobWatchSource
from loop.sources.timer import TimerSource

# factories read config when called, so a test (or a start) sees the current values
SOURCES: dict[str, Callable[[], SignalSource]] = {
    "webhook": lambda: GitHubWebhookSource(config.LISTEN_HOST, config.LISTEN_PORT,
                                           load_secret()),
    "timer": lambda: TimerSource(config.FULL_RUN_MINUTES * 60),
    "jobwatch": lambda: JobWatchSource(config.JOBWATCH_SECONDS),
    "hermes-cron": HermesCronSource,
}
SINKS: dict[str, Callable[[], OutputSink]] = {
    "command": lambda: CommandSink(config.DELIVER_CMD, config.DELIVER_TIMEOUT_SECONDS),
    "hermes-outbox": HermesBotChatSink,
    "stdout": StdoutSink,
    "file": lambda: FileSink(Path(config.FILE_SINK)),
}


def register_source(name: str, factory: Callable[[], SignalSource]) -> None:
    """Add (or replace) a signal source under ``name``."""
    SOURCES[name] = factory


def register_sink(name: str, factory: Callable[[], OutputSink]) -> None:
    """Add (or replace) an output sink under ``name``."""
    SINKS[name] = factory


def names(setting: str) -> list[str]:
    """The names in a comma-separated setting, without blanks and repeats, in order."""
    found: list[str] = []
    for name in (part.strip() for part in setting.split(",")):
        if name and name not in found:
            found.append(name)
    return found


def _known(name: str, registry: dict) -> None:
    if name not in registry:
        raise ValueError(f"unknown adapter {name!r}; known: {', '.join(sorted(registry))}")


def build_sources(setting: str | None = None) -> list[SignalSource]:
    """The sources named in ``setting`` (default ``LOOP_SOURCES``); an unknown name is refused."""
    chosen = names(config.SOURCES if setting is None else setting)
    if not chosen:
        raise ValueError("no signal source configured (LOOP_SOURCES)")
    for name in chosen:
        _known(name, SOURCES)
    return [SOURCES[name]() for name in chosen]


def build_sink(name: str | None = None) -> OutputSink:
    """The sink named ``name`` (default ``LOOP_SINK``); an unknown name is refused."""
    name = (config.SINK if name is None else name).strip()
    _known(name, SINKS)
    return SINKS[name]()


def tick_sink() -> OutputSink:
    """The output of the cron runs (``LOOP_TICK_SINK``, default stdout)."""
    return build_sink(config.TICK_SINK)
