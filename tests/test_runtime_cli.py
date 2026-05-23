"""Plan 9 T8: python -m bot.runtime CLI.

argparse with --config PATH (required) + --check (optional flag).
Returns the exit code from bot.runtime.main.main.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.runtime.cli import build_parser, cli_main


def test_parser_requires_config() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_parses_config_and_check() -> None:
    parser = build_parser()
    ns = parser.parse_args(["--config", "config/bot.example.yml", "--check"])
    assert ns.config == Path("config/bot.example.yml")
    assert ns.check is True


def test_parser_check_default_false() -> None:
    parser = build_parser()
    ns = parser.parse_args(["--config", "config/bot.example.yml"])
    assert ns.check is False


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--config" in out
    assert "--check" in out


async def test_cli_main_passes_args_to_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """cli_main constructs the right args and forwards to runtime.main."""
    captured: dict[str, object] = {}

    async def _stub_main(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("bot.runtime.cli._runtime_main", _stub_main)
    exit_code = await cli_main(["--config", "config/bot.example.yml", "--check"])
    assert exit_code == 0
    assert captured["config_path"] == Path("config/bot.example.yml")
    assert captured["check_only"] is True


async def test_cli_main_propagates_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """cli_main returns whatever runtime.main returns."""
    monkeypatch.setattr(
        "bot.runtime.cli._runtime_main", AsyncMock(return_value=5),
    )
    exit_code = await cli_main(["--config", "config/bot.example.yml", "--check"])
    assert exit_code == 5
