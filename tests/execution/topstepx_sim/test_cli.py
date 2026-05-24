"""CLI runner tests (Plan 11 T6)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.execution.topstepx_sim.cli import build_parser, run


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bot.execution.topstepx_sim", *args],
        capture_output=True, text=True, check=False,
    )


def test_parser_requires_scenario_argument() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_rejects_unknown_scenario() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--scenario", "totally-not-a-real-scenario"])


def test_parser_accepts_known_scenario() -> None:
    parser = build_parser()
    args = parser.parse_args(["--scenario", "combine_pass_50k"])
    assert args.scenario == "combine_pass_50k"


async def test_run_combine_pass_reports_passed_stage(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = await run(scenario="combine_pass_50k", json_out=None)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "stage=combine_passed" in captured.out


async def test_run_combine_fail_mll_reports_failed_stage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = await run(scenario="combine_fail_mll_50k", json_out=None)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "stage=combine_failed" in captured.out


async def test_run_hard_flat_reports_at_least_one_reject(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = await run(scenario="hard_flat_at_1510_ct", json_out=None)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "rejected=" in captured.out


async def test_run_with_json_out_writes_account_snapshot(tmp_path: Path) -> None:
    out_path = tmp_path / "result.json"
    exit_code = await run(scenario="combine_pass_50k", json_out=out_path)
    assert exit_code == 0
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["scenario"] == "combine_pass_50k"
    assert data["stage"] == "combine_passed"
    assert "balance" in data
    assert "equity" in data


def test_subprocess_combine_pass_exits_zero() -> None:
    result = _run_module("--scenario", "combine_pass_50k")
    assert result.returncode == 0, result.stderr
    assert "stage=combine_passed" in result.stdout


def test_subprocess_unknown_scenario_exits_nonzero() -> None:
    result = _run_module("--scenario", "completely-bogus")
    assert result.returncode != 0
    assert "completely-bogus" in result.stderr or "completely-bogus" in result.stdout
