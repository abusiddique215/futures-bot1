"""CLI integration for --bots."""
from __future__ import annotations

from pathlib import Path

import pytest

from bot.runtime.cli import build_parser


def test_parser_accepts_bots_dir() -> None:
    p = build_parser()
    ns = p.parse_args(["--bots", "config/bots/"])
    assert ns.bots == Path("config/bots/")
    assert ns.config is None


def test_parser_accepts_config_still() -> None:
    p = build_parser()
    ns = p.parse_args(["--config", "config/bot.yml"])
    assert ns.config == Path("config/bot.yml")
    assert ns.bots is None


def test_parser_rejects_both_config_and_bots() -> None:
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--config", "config/bot.yml", "--bots", "config/bots/"])


def test_parser_rejects_neither() -> None:
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args([])


def test_check_flag_still_works_with_bots() -> None:
    p = build_parser()
    ns = p.parse_args(["--bots", "config/bots/", "--check"])
    assert ns.check is True
