"""si#391: the kernel reads what the layers above register, and an unregistered run says so.

The step log, the transcript header and the interactive UI used to be imported by the kernel from the
layers above it (`context`, `outputs`, `labinstance`, `cli`, `orchestrator.tui`). `cli.main` now registers
a `runhost.RunHost`, and these tests hold the two halves: the kernel uses what is registered, and nothing
registered is an answer the run states, never a quiet headless run. AAA throughout.
"""
from __future__ import annotations

import dataclasses

import pytest

from simplon import cli, runhost, steplog
from simplon.orchestrator.steps import NO_TUI_ENV, Outcome, Pipeline, Step, dispatch


def _pipeline() -> Pipeline:
    return Pipeline("build", [Step(label="compile", action=lambda: Outcome(rc=0, output=""))])


def test_an_unregistered_run_says_it_runs_headless_rather_than_doing_it_quietly(monkeypatch, capsys):
    # arrange: nothing registered a host, and nobody asked for headless
    runhost.register(None)
    monkeypatch.delenv(NO_TUI_ENV, raising=False)
    taken: list[str] = []
    monkeypatch.setattr("simplon.orchestrator.steps.run_headless",
                        lambda pipeline: (taken.append("headless"), 0)[1])

    # act
    rc = dispatch(_pipeline())

    # assert
    assert rc == 0 and taken == ["headless"]
    assert "nothing registered a UI for this run" in capsys.readouterr().out


def test_a_registered_ui_draws_the_run(monkeypatch):
    # arrange
    monkeypatch.delenv(NO_TUI_ENV, raising=False)
    drawn: list[str] = []
    runhost.register(dataclasses.replace(cli.run_host(),
                                         render=lambda pipeline: (drawn.append(pipeline.name), 3)[1]))

    # act
    rc = dispatch(_pipeline())

    # assert: the UI's rc is the run's
    assert drawn == ["build"] and rc == 3


def test_a_ui_whose_toolkit_is_not_installed_falls_back_to_headless(monkeypatch, capsys):
    """Textual is optional; the cli's renderer imports it inside the call, so its absence arrives as
    ImportError, and that alone is the headless run it always was."""
    # arrange
    monkeypatch.delenv(NO_TUI_ENV, raising=False)

    def _absent(_pipeline):
        raise ImportError("No module named 'textual'")

    runhost.register(dataclasses.replace(cli.run_host(), render=_absent))
    monkeypatch.setattr("simplon.orchestrator.steps.run_headless", lambda pipeline: 0)

    # act / assert
    assert dispatch(_pipeline()) == 0
    assert "nothing registered" not in capsys.readouterr().out


def test_an_unregistered_run_writes_no_step_log_and_names_no_environment_or_instance():
    # arrange
    runhost.register(None)

    # act / assert: the documented answers, not a guess
    assert steplog.log_directory() is None
    assert steplog.write("build.compile", "output") is None
    assert steplog._environment_name() == "not set"
    assert steplog._instance_id() == "not declared"


def test_the_cli_registers_its_host_before_anything_runs(monkeypatch):
    """`cli.main` is where every run starts; the host has to be there before Typer dispatches."""
    # arrange
    runhost.register(None)
    seen: list[object] = []

    class _Stop(Exception):
        pass

    def _taxonomy_reached():
        seen.append(runhost.current())
        raise _Stop

    context = type("Ctx", (), {"manifest": lambda self: type("M", (), {"taxonomy": staticmethod(
        _taxonomy_reached)})(), "name": "demo"})()
    monkeypatch.setattr("sys.argv", ["demo", "build"])

    # act
    with pytest.raises(_Stop):
        cli.main(app=None, context=context, environments=None, aliases={})

    # assert
    assert isinstance(seen[0], runhost.RunHost) and seen[0].render is cli._render
