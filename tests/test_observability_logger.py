"""Plan 7 T2: JSON-lines logger config.

`configure_json_logger(path, level)` configures loguru to write one JSON object
per line to `path`. Tests round-trip a few messages and assert the shape so
log-scraping (Plan 8) can rely on a stable schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from loguru import logger

from bot.observability.logger import configure_json_logger


@pytest.fixture(autouse=True)
def _reset_loguru():
    # Remove every sink so tests don't leak into each other (or stderr).
    logger.remove()
    yield
    logger.remove()


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_configure_json_logger_writes_jsonlines(tmp_path):
    log_path = tmp_path / "today.jsonl"
    configure_json_logger(log_path, level="INFO")

    logger.info("hello world")

    lines = _read_lines(log_path)
    assert len(lines) == 1
    record = lines[0]["record"]
    assert record["message"] == "hello world"
    assert record["level"]["name"] == "INFO"


def test_configure_json_logger_filters_below_level(tmp_path):
    log_path = tmp_path / "today.jsonl"
    configure_json_logger(log_path, level="WARNING")

    logger.debug("ignored")
    logger.info("ignored too")
    logger.warning("kept")

    lines = _read_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["record"]["message"] == "kept"


def test_configure_json_logger_includes_extra_fields(tmp_path):
    log_path = tmp_path / "today.jsonl"
    configure_json_logger(log_path, level="INFO")

    logger.bind(kind="ORDER_APPROVED", client_order_id="abc-1").info("order approved")

    lines = _read_lines(log_path)
    assert lines[0]["record"]["extra"]["kind"] == "ORDER_APPROVED"
    assert lines[0]["record"]["extra"]["client_order_id"] == "abc-1"


def test_configure_json_logger_default_level_is_info(tmp_path):
    log_path = tmp_path / "today.jsonl"
    configure_json_logger(log_path)  # no level arg

    logger.debug("ignored")
    logger.info("kept")

    lines = _read_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["record"]["message"] == "kept"


def test_configure_json_logger_creates_parent_dir(tmp_path):
    nested = tmp_path / "deep" / "nest" / "today.jsonl"
    configure_json_logger(nested, level="INFO")
    logger.info("ok")
    assert nested.exists()
