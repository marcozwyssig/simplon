"""si#516: copying out of the TUI says whether it worked.

Textual copies by writing OSC 52 to the terminal, and a VTE terminal (Tilix, GNOME Terminal) drops it
without a word - so "copied to the clipboard" was printed over a copy that never happened. On a desktop
session the kernel now hands the text to a clipboard tool whose exit status it can read, and falls back to
OSC 52 only when there is none, saying then that delivery cannot be confirmed.

The tools are real executables on a PATH this test controls, so what is asserted is what a child process
actually received on its stdin - not what a mock was called with.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from simplon.ui import clipboard


def _tool(bin_dir: Path, name: str, *, rc: int = 0, stderr: str = "") -> Path:
    """A clipboard tool that writes its argv and its stdin next to itself and exits `rc`."""
    received = bin_dir / f"{name}.received"
    script = bin_dir / name
    script.write_text("#!/bin/sh\n"
                      f'printf "%s\\n" "$*" > "{received}.argv"\n'
                      f'/bin/cat > "{received}"\n'
                      + (f'echo "{stderr}" >&2\n' if stderr else "")
                      + f"exit {rc}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return received


def _env(bin_dir: Path, **display: str) -> dict[str, str]:
    return {"PATH": str(bin_dir), **display}


def test_wayland_hands_the_text_to_wl_copy(tmp_path):
    # arrange
    received = _tool(tmp_path, "wl-copy")
    _tool(tmp_path, "xclip")

    # act
    result = clipboard.copy("über the wire\n", env=_env(tmp_path, WAYLAND_DISPLAY="wayland-0", DISPLAY=":0"))

    # assert: Wayland wins when both are set - XWayland's DISPLAY is a compatibility shim
    assert result.state is clipboard.State.CONFIRMED
    assert result.route == "wl-copy"
    assert received.read_text() == "über the wire\n"


def test_x11_hands_the_text_to_xclip_on_the_clipboard_selection(tmp_path):
    # arrange
    received = _tool(tmp_path, "xclip")

    # act
    result = clipboard.copy("hello", env=_env(tmp_path, DISPLAY=":0"))

    # assert: the CLIPBOARD selection, not PRIMARY - ctrl+v pastes CLIPBOARD
    assert result.state is clipboard.State.CONFIRMED
    assert result.route == "xclip"
    assert received.read_text() == "hello"
    assert Path(f"{received}.argv").read_text().split() == ["-selection", "clipboard"]


def test_x11_without_xclip_falls_to_xsel(tmp_path):
    # arrange
    received = _tool(tmp_path, "xsel")

    # act
    result = clipboard.copy("hello", env=_env(tmp_path, DISPLAY=":0"))

    # assert
    assert result.state is clipboard.State.CONFIRMED
    assert result.route == "xsel"
    assert received.read_text() == "hello"
    assert Path(f"{received}.argv").read_text().split() == ["--clipboard", "--input"]


def test_a_tool_that_fails_is_a_failure_with_its_reason_and_never_reads_as_copied(tmp_path):
    """The recurring defect, at this seam: a copy that did not happen must not be reported as one."""
    # arrange
    _tool(tmp_path, "xclip", rc=1, stderr="Error: Can't open display: :0")

    # act
    result = clipboard.copy("hello", env=_env(tmp_path, DISPLAY=":0"))

    # assert
    assert result.state is clipboard.State.FAILED
    assert result.route == "xclip"
    assert "exited 1" in result.detail
    assert "Can't open display" in result.detail


def test_no_display_means_osc52_and_says_it_cannot_be_confirmed(tmp_path):
    """An SSH session: no desktop to hand the text to, so the terminal escape is the only route left -
    and the one route whose outcome nobody can see."""
    # arrange: tools present, but no display to reach them through
    _tool(tmp_path, "wl-copy")
    _tool(tmp_path, "xclip")

    # act
    result = clipboard.copy("hello", env=_env(tmp_path))

    # assert
    assert result.state is clipboard.State.UNCONFIRMED
    assert result.route == "osc52"


def test_a_display_with_no_tool_installed_means_osc52(tmp_path):
    # act
    result = clipboard.copy("hello", env=_env(tmp_path, WAYLAND_DISPLAY="wayland-0", DISPLAY=":0"))

    # assert
    assert result.state is clipboard.State.UNCONFIRMED
    assert result.route == "osc52"


def test_a_tool_that_forks_a_server_does_not_hang_the_copy(tmp_path):
    """xclip and wl-copy fork a child that stays alive to serve the selection, and that child inherits
    whatever the parent's stdout and stderr were. If those were pipes, waiting for them to close would
    wait for the next copy by somebody else."""
    # arrange: a tool that leaves a sleeper holding its stdout and stderr
    script = tmp_path / "xclip"
    script.write_text("#!/bin/sh\n/bin/cat > /dev/null\n( /bin/sleep 30 ) &\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    # act
    import time
    started = time.monotonic()
    result = clipboard.copy("hello", env=_env(tmp_path, DISPLAY=":0"))
    took = time.monotonic() - started

    # assert
    assert result.state is clipboard.State.CONFIRMED
    assert took < 5, f"the copy waited {took:.1f}s on a forked selection server"


def test_the_real_environment_is_the_default(monkeypatch, tmp_path):
    # arrange
    received = _tool(tmp_path, "wl-copy")
    monkeypatch.setattr(os, "environ", _env(tmp_path, WAYLAND_DISPLAY="wayland-0"))

    # act
    result = clipboard.copy("x")

    # assert
    assert result.state is clipboard.State.CONFIRMED
    assert received.read_text() == "x"
