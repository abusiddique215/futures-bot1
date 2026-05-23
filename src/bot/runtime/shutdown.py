"""SIGTERM clean shutdown handler.

`install_shutdown_handler(stop_event, signals=(SIGTERM, SIGINT))` wires the
running asyncio loop's signal handlers so any of the listed signals sets
`stop_event`. The LiveTradingLoop checks this event at the top of every
iteration and exits cleanly — drains any pending force-flatten, lets the
caller close the journal in its `finally`.

The actual signal-handler wiring uses `loop.add_signal_handler` which only
works on POSIX with a running loop. Tests pass a synthetic Event directly
and use `signal.raise_signal` to drive the handler.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable

log = logging.getLogger(__name__)

_DEFAULT_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)


def install_shutdown_handler(
    stop_event: asyncio.Event,
    *,
    signals: Iterable[signal.Signals] = _DEFAULT_SIGNALS,
) -> asyncio.Event:
    """Register signal handlers that set `stop_event` when any of `signals`
    arrives. Must be called from inside a running asyncio loop.

    Returns `stop_event` for caller convenience (chainable construction).

    Re-installing on an existing signal overwrites the prior handler — POSIX
    semantics; loop.add_signal_handler is a setter, not an appender.
    """
    loop = asyncio.get_running_loop()

    def _on_signal(sig: signal.Signals) -> None:
        log.info("shutdown signal received: %s", sig.name)
        stop_event.set()

    for sig in signals:
        loop.add_signal_handler(sig, _on_signal, sig)
    return stop_event
