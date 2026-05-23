"""Plan 9 T10: end-to-end smoke test.

Runs `python -m bot.runtime --config config/bot.example.yml --check` in a
subprocess and asserts exit code 0. The example config uses broker=sim so
no real broker is touched — this is the load-bearing integration test
that proves the 8-step startup contract works end-to-end without mocks.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CFG = PROJECT_ROOT / "config" / "bot.example.yml"


def test_smoke_check_exits_zero() -> None:
    """`python -m bot.runtime --config config/bot.example.yml --check` exits 0."""
    assert EXAMPLE_CFG.is_file(), f"example config missing: {EXAMPLE_CFG}"
    # Clean env so test doesn't pick up the developer's TOPSTEPX_* / IB_*.
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("TOPSTEPX_", "IB_"))
    }
    # Ensure PYTHONPATH lets the subprocess find the package via src/ layout.
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "bot.runtime", "--config", str(EXAMPLE_CFG), "--check"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke test failed: rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
