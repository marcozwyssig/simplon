"""si#655: `log` paints colour only where a person is looking - a terminal, with `NO_COLOR` unset.

The launcher forwards `NO_COLOR` into the kernel container, and piped output lands in CI logs and step
transcripts, so an escape written there is noise that a reader has to strip. Colour is decided per
stream: stdout for info/ok/warn, stderr for error/die.
"""
from __future__ import annotations

import io
import sys

import pytest

from simplon.kernel import log

ESC = "\x1b"


class Stream(io.StringIO):
    """A stream that answers `isatty` the way it is told to - the one property this ticket turns on."""

    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _emit(monkeypatch, *, stdout_tty: bool, stderr_tty: bool) -> tuple[str, str]:
    out, err = Stream(stdout_tty), Stream(stderr_tty)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    log.info("i")
    log.ok("o")
    log.warn("w")
    log.error("e")
    with pytest.raises(SystemExit):
        log.die("d")
    return out.getvalue(), err.getvalue()


def test_a_terminal_without_NO_COLOR_keeps_its_colour(monkeypatch):
    # arrange
    monkeypatch.delenv("NO_COLOR", raising=False)

    # act
    out, err = _emit(monkeypatch, stdout_tty=True, stderr_tty=True)

    # assert: every line still carries its badge, so the fix did not trade colour away everywhere
    assert out.count("\x1b[1;34m") == 1 and out.count("\x1b[1;32m") == 1 and out.count("\x1b[1;33m") == 1
    assert err.count("\x1b[1;31m") == 2


def test_NO_COLOR_takes_the_colour_off_even_on_a_terminal(monkeypatch):
    # arrange
    monkeypatch.setenv("NO_COLOR", "1")

    # act
    out, err = _emit(monkeypatch, stdout_tty=True, stderr_tty=True)

    # assert: the words are all there, the escapes are not
    assert ESC not in out and ESC not in err
    assert "==> i" in out and " OK o" in out and "  ! w" in out
    assert "ERR e" in err and "ERR d" in err


def test_an_empty_NO_COLOR_is_not_set(monkeypatch):
    # arrange: no-color.org - "when present and not an empty string"
    monkeypatch.setenv("NO_COLOR", "")

    # act
    out, err = _emit(monkeypatch, stdout_tty=True, stderr_tty=True)

    # assert
    assert ESC in out and ESC in err


def test_a_pipe_gets_no_escape(monkeypatch):
    # arrange
    monkeypatch.delenv("NO_COLOR", raising=False)

    # act
    out, err = _emit(monkeypatch, stdout_tty=False, stderr_tty=False)

    # assert
    assert ESC not in out and ESC not in err
    assert "==> i" in out and "ERR e" in err


def test_colour_is_decided_per_stream(monkeypatch):
    # arrange: `2>log.txt` on a terminal - stdout is looked at, stderr is a file
    monkeypatch.delenv("NO_COLOR", raising=False)

    # act
    out, err = _emit(monkeypatch, stdout_tty=True, stderr_tty=False)
    out_piped, err_tty = _emit(monkeypatch, stdout_tty=False, stderr_tty=True)

    # assert
    assert ESC in out and ESC not in err
    assert ESC not in out_piped and ESC in err_tty


def test_the_repainted_line_drops_its_colour_under_NO_COLOR_but_still_repaints(monkeypatch):
    # arrange: `inplace` is called only on a terminal (fetch asks `isatty` first), so NO_COLOR is the
    # one switch that reaches it; the erase-to-end and carriage return are cursor control, not colour
    monkeypatch.setenv("NO_COLOR", "1")
    out = Stream(True)
    monkeypatch.setattr(sys, "stdout", out)

    # act
    log.inplace("50%")

    # assert
    assert "\x1b[1;34m" not in out.getvalue() and "\x1b[0m" not in out.getvalue()
    assert out.getvalue().endswith("50%\x1b[K\r")
