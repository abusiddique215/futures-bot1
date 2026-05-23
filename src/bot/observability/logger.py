"""JSON-lines logger configuration on top of loguru.

`configure_json_logger(path, level)` is the single entrypoint: it registers a
file sink that serializes each record as one JSON object per line. Plan 8's
log-scraping is downstream of this — keep the schema stable (loguru's default
`serialize=True` shape: `{"text": "...", "record": {...}}`).

Callers are responsible for `logger.remove()` if they need a clean slate;
configure_json_logger does NOT remove the default stderr sink so dev runs still
see colored output.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

LogLevel = str  # "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"


def configure_json_logger(path: Path, level: LogLevel = "INFO") -> int:
    """Add a JSON-lines sink at `path`. Returns the loguru handler id.

    Creates parent directories as needed. The sink uses loguru's `serialize=True`
    flag — each line is a JSON object with a `record` key holding level, time,
    message, and any fields bound via `logger.bind(...)`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handler_id: int = logger.add(
        str(path),
        level=level,
        serialize=True,
        enqueue=False,  # synchronous writes — tests assert immediately
    )
    return handler_id
