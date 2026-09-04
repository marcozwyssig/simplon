"""Contract-parity tests for launch.cmd, the Windows counterpart of launch.sh (platform#78).

launch.cmd cannot be executed here -- CI and every developer box in this family run Linux -- so these
tests assert the properties that would silently DRIFT instead: the two launchers must demand the same
four LAUNCH_* parameters, run the module the same way, and refresh the venv by the same rule. A
Windows launcher that quietly grew a different contract is the failure mode worth guarding; whether
cmd.exe parses it is something only Windows can answer. AAA throughout.
"""
from pathlib import Path

import pytest

SH = Path(__file__).resolve().parents[3] / "src" / "sh" / "launch.sh"
CMD = Path(__file__).resolve().parents[3] / "src" / "sh" / "launch.cmd"

REQUIRED = ("LAUNCH_PRODUCT", "LAUNCH_ROOT", "LAUNCH_ORCH_DIR", "LAUNCH_MODULE")


def test_the_windows_launcher_ships_beside_the_posix_one():
    assert CMD.is_file(), "launch.cmd is missing; a product's shim differs only by extension"


@pytest.mark.parametrize("name", REQUIRED)
def test_both_launchers_demand_the_same_parameter(name):
    # Arrange
    sh, cmd = SH.read_text(), CMD.read_text()
    # Act / Assert
    assert name in sh, f"{name} vanished from launch.sh"
    assert name in cmd, f"launch.cmd does not demand {name}; the two contracts have drifted"


def test_the_windows_launcher_fails_fast_on_each_missing_parameter():
    # Arrange
    cmd = CMD.read_text()
    # Act / Assert - one guard per parameter, each exiting nonzero
    for name in REQUIRED:
        assert f'if "%{name}%"==""' in cmd, f"no guard for {name}"
    assert cmd.count("exit /b 1") >= len(REQUIRED)


def test_the_windows_launcher_runs_the_module_unbuffered_and_forwards_args():
    # Arrange
    cmd = CMD.read_text()
    # Act / Assert
    assert "-u -m %LAUNCH_MODULE% %*" in cmd, "the exec contract differs from launch.sh's"
    assert "exit /b %ERRORLEVEL%" in cmd.rstrip().splitlines()[-1], \
        "cmd has no exec, so the child's exit code must be handed back explicitly"


def test_both_launchers_refresh_the_venv_by_the_same_stamp_rule():
    # Arrange
    sh, cmd = SH.read_text(), CMD.read_text()
    # Act / Assert
    assert ".deps-stamp" in sh and ".deps-stamp" in cmd
    assert "requirements.txt" in cmd
    assert "--disable-pip-version-check" in cmd, "pip is invoked differently than in launch.sh"


def test_batch_line_endings_are_pinned_to_crlf():
    """cmd.exe mis-parses multi-line blocks in an LF-only .cmd, and the file is authored on Linux."""
    # Arrange
    attrs = Path(__file__).resolve().parents[5] / ".gitattributes"
    # Act / Assert
    assert attrs.is_file(), ".gitattributes is missing"
    assert "*.cmd text eol=crlf" in attrs.read_text()
