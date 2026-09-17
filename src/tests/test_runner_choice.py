"""WHICH RUNNER RUNS, AND WHO CHOSE IT (si#223).

A pipeline can be rendered in the Textual runner or walked headless, and before this file the choice was
made by two accidents and announced by nobody: `sys.stdout.isatty()`, and an `except Exception` around the
Textual construction that turned ANY fault into a clean-looking headless run. So a broken Textual install
and a deliberate CI redirection arrived at the same place by the same road - this repository's recurring
defect (an outcome that cannot tell "chosen" from "failed") sitting in the mechanism that chooses.

si#223 decided against a `kind:` in the manifest: the kind of a task is decided by a branch INSIDE a body
(`swi`'s `publish(..., check=False)` reports or acts on that pin), so no declaration could be a second
source that is checkable - only one that can drift. `steps.dispatch` is therefore the declaration: a
command that reaches it renders. What is left to fix is what happens AT that door, which is this file.

TWO PROPERTIES, and they are different in kind:

  - THE DOOR TAKES AN ANSWER (point 3). `SIMPLON_NO_TUI=1` - and the `--no-tui` that sets it - is an
    explicit "headless, please", decided BEFORE Textual is imported. The variable and not only the flag,
    because every planned step is a `./<product>.sh <leaf>` SUBPROCESS that no flag on the parent reaches.
  - THE DOOR NO LONGER SWALLOWS (point 2). Only `ImportError` falls back, because a kernel without Textual
    installed is a configuration this repository supports on purpose (`tui.py`'s own module head). Every
    other fault propagates instead of arriving as a green headless run.

AAA throughout.
"""
from __future__ import annotations

import pytest

import sys
import types

from simplon.orchestrator.steps import NO_TUI_ENV, Outcome, Pipeline, Step, dispatch, tui_disabled
from simplon import cli


def _step(label: str, rc: int = 0) -> Step:
    return Step(label=label, action=lambda: Outcome(rc=rc, output=""))


def _pipeline() -> Pipeline:
    return Pipeline("build", [_step("compile"), _step("package")])


# --- point 3: the door takes an answer ----------------------------------------------------------------


def test_the_variable_sends_a_run_headless_even_with_a_terminal_attached(monkeypatch):
    """The whole point of the lever: a TTY is no longer the only thing that decides."""
    # Arrange: a terminal is attached, and the run asks for headless anyway
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv(NO_TUI_ENV, "1")
    taken: list[str] = []
    monkeypatch.setattr("simplon.orchestrator.steps.run_headless",
                        lambda pipeline: (taken.append("headless"), 0)[1])
    # Act
    rc = dispatch(_pipeline())
    # Assert: the headless runner ran, and the rc is its own
    assert taken == ["headless"]
    assert rc == 0


def test_the_variable_is_read_before_the_tui_is_reached(monkeypatch):
    """Not a micro-optimisation: on a machine whose Textual is broken, asking for headless has to be
    ENOUGH. If the TUI were reached first, the explicit lever would be the one thing that could not rescue
    the run it was invented for.

    The stand-in RAISES rather than being absent, deliberately: a missing module would make `dispatch`
    fall back through its own `except ImportError` and the test would pass without the variable ever being
    read."""
    # Arrange: a terminal is attached, headless is asked for, and reaching the TUI is a test failure
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv(NO_TUI_ENV, "1")

    def _reached(_pipeline):
        raise AssertionError("the TUI was reached although headless was asked for")

    monkeypatch.setitem(sys.modules, "simplon.orchestrator.tui",
                        types.SimpleNamespace(run_pipeline=_reached))
    monkeypatch.setattr("simplon.orchestrator.steps.run_headless", lambda pipeline: 0)
    # Act / Assert
    assert dispatch(_pipeline()) == 0


def test_an_unset_variable_leaves_the_choice_exactly_where_it_was(monkeypatch):
    # Arrange
    monkeypatch.delenv(NO_TUI_ENV, raising=False)
    # Act / Assert
    assert tui_disabled() is False


def test_a_value_the_reader_does_not_understand_warns_and_keeps_the_runner(capsys, monkeypatch):
    """`max_parallel`'s rule, for a boolean: an operator who typed something has to be told that what they
    asked for is not what is happening. Silently reading `true` as "off" is the defect this repository
    hunts wearing a word."""
    # Arrange
    monkeypatch.setenv(NO_TUI_ENV, "true")
    # Act
    disabled = tui_disabled()
    # Assert: unchanged behaviour, and the operator is told which variable and which value
    assert disabled is False
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert NO_TUI_ENV in said and "true" in said


def test_the_flag_is_consumed_from_the_argv_and_never_reaches_click(monkeypatch):
    """`--no-tui` is stripped in `cli.main` rather than registered on a root callback, because the root app
    belongs to the PRODUCT and `assemble` registers no callback on it - adding one would silently overwrite
    a product's own on upgrade."""
    # Arrange
    argv = ["simplon", "--no-tui", "dev", "build"]
    # Act
    asked = cli.consume_no_tui(argv)
    # Assert: the flag is gone and the leading env token is still where the env-first dispatch looks
    assert asked is True
    assert argv == ["simplon", "dev", "build"]


def test_a_run_that_did_not_ask_leaves_the_argv_alone(monkeypatch):
    # Arrange
    argv = ["simplon", "dev", "build"]
    # Act
    asked = cli.consume_no_tui(argv)
    # Assert
    assert asked is False
    assert argv == ["simplon", "dev", "build"]


def test_the_flag_is_not_taken_out_of_a_passthrough_commands_trailing_args():
    """A `passthrough_args` command forwards unrecognised trailing args to an underlying tool, so a token
    after the command name is that tool's, not this kernel's. Only the LEADING option run is ours."""
    # Arrange: the flag sits where a pytest option would
    argv = ["simplon", "test", "unit", "--no-tui"]
    # Act
    asked = cli.consume_no_tui(argv)
    # Assert: untouched, and the underlying tool still gets what was typed for it
    assert asked is False
    assert argv == ["simplon", "test", "unit", "--no-tui"]


# --- point 2: the door no longer swallows -------------------------------------------------------------


def test_a_textual_fault_that_is_not_a_missing_install_is_not_a_headless_run(monkeypatch):
    """Finding 6 of si#223, and the one this file exists for. `except Exception` made a half-installed
    Textual, an incompatible version and a construction fault indistinguishable from deliberate CI
    redirection - all four arrived as a green headless run."""
    pytest.importorskip("textual")
    from simplon.orchestrator import tui
    # Arrange: a terminal is attached and constructing the app falls over for a reason that is not absence
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    def _broken(_pipeline):
        raise RuntimeError("Widget.__init__() got an unexpected keyword argument 'markup'")

    monkeypatch.setattr(tui, "_StepApp", _broken)
    # `tui` imported the runner into its OWN namespace, so this is the name it calls - patching the one
    # `steps` exports would leave the guard inert and the test green for the wrong reason.
    monkeypatch.setattr(tui, "run_headless",
                        lambda pipeline: pytest.fail("a broken Textual became a headless run"))
    # Act / Assert: the fault reaches the caller instead of being dressed as a runner choice
    with pytest.raises(RuntimeError, match="unexpected keyword argument"):
        tui.run_pipeline(_pipeline())


def test_textual_being_absent_is_still_a_headless_run(monkeypatch):
    """The supported configuration, and the reason the narrowing is to `ImportError` rather than to
    nothing: `tui.py`'s module head says the headless path must not hard-require Textual."""
    pytest.importorskip("textual")
    from simplon.orchestrator import tui
    # Arrange
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    def _absent(_pipeline):
        raise ImportError("No module named 'textual'")

    monkeypatch.setattr(tui, "_StepApp", _absent)
    taken: list[str] = []
    monkeypatch.setattr(tui, "run_headless", lambda pipeline: (taken.append("headless"), 0)[1])
    # Act
    rc = tui.run_pipeline(_pipeline())
    # Assert
    assert taken == ["headless"] and rc == 0
