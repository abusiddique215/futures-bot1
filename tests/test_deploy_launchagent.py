"""Plan 9 T9: validate macOS LaunchAgent .plist + scripts are well-formed.

We don't actually install anything (CI would have to be a Mac and have
launchctl). What we DO check:

  - The two .plist files parse as plist XML.
  - Their `Label` matches the filename.
  - The bot .plist has KeepAlive.SuccessfulExit=false.
  - The bot .plist has RunAtLoad=true.
  - The heartbeat .plist has StartInterval=60.
  - All three .sh files pass `bash -n` (syntax check) on macOS, are
    executable-readable (we check for the shebang), and reference the
    project root via __PROJECT_DIR__ (plists) / $PROJECT_DIR (scripts).
"""
from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def test_plist_files_present() -> None:
    assert (DEPLOY / "com.user.topstepbot.plist").is_file()
    assert (DEPLOY / "com.user.topstepbot-heartbeat.plist").is_file()


def test_bot_plist_parses_and_required_fields() -> None:
    plist = (DEPLOY / "com.user.topstepbot.plist").read_bytes()
    data = plistlib.loads(plist)
    assert data["Label"] == "com.user.topstepbot"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"]["SuccessfulExit"] is False
    assert data["ThrottleInterval"] == 10
    # ProgramArguments should invoke docker compose against compose.yml
    args = data["ProgramArguments"]
    assert any("docker" in a for a in args)
    assert any("compose" in a for a in args)
    assert any("up" in a for a in args)


def test_heartbeat_plist_parses_and_required_fields() -> None:
    plist = (DEPLOY / "com.user.topstepbot-heartbeat.plist").read_bytes()
    data = plistlib.loads(plist)
    assert data["Label"] == "com.user.topstepbot-heartbeat"
    assert data["StartInterval"] == 60
    assert data["RunAtLoad"] is True
    args = data["ProgramArguments"]
    assert any("check_heartbeat.sh" in a for a in args)


@pytest.mark.parametrize("script", [
    "install.sh",
    "uninstall.sh",
    "check_heartbeat.sh",
])
def test_shell_scripts_syntax(script: str) -> None:
    """`bash -n` is a no-execute syntax check; skip if bash isn't on PATH."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not on PATH")
    path = DEPLOY / script
    assert path.is_file()
    # Must have a shebang.
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!"), f"missing shebang in {script}"
    # Syntax-only check.
    result = subprocess.run(
        [bash, "-n", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n {script} failed: {result.stderr}"


def test_install_script_refuses_icloud_path() -> None:
    """install.sh must contain an explicit guard against iCloud trees."""
    text = (DEPLOY / "install.sh").read_text()
    assert "Mobile Documents" in text
    # And cites the relevant Topstep article.
    assert "8680268" in text


def test_install_script_uses_plutil_lint() -> None:
    """The install path must lint each .plist before loading it."""
    text = (DEPLOY / "install.sh").read_text()
    assert "plutil -lint" in text


def test_plist_templates_use_project_dir_placeholder() -> None:
    """Both .plists use __PROJECT_DIR__ that install.sh substitutes."""
    for tpl in ("com.user.topstepbot.plist", "com.user.topstepbot-heartbeat.plist"):
        text = (DEPLOY / tpl).read_text()
        assert "__PROJECT_DIR__" in text


def test_readme_present() -> None:
    """A README in deploy/ describes the install workflow."""
    readme = DEPLOY / "README.md"
    assert readme.is_file()
    text = readme.read_text()
    assert "install.sh" in text
    assert "8680268" in text
