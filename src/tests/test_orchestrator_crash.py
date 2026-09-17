"""A step that BLEW UP rather than failed (si#182): the verdict it gets, and the record the run leaves.

Before si#182 a body that raised left its `Step` on `RUNNING` for ever - no rc, no `ended_at`, no
duration - and the exception went on out of `run_plan` and `run_headless`, so the run died before the
retraced tree, before `failure_report` and before the transcript. Under the TUI, Textual catches a
worker's exception, so `_on_done` was never reached and the operator watched a row on `↻` with a timer
counting upwards for ever.

Every test here names a property that was broken and is now held. `crash_text` and `Step.crash` are the
vocabulary: FAILED is the step's fate (`simplon.verdict` argues why a sixth state and a reserved rc are
both wrong), and the distinction between failing and blowing up lives in what gets WRITTEN.
"""
from __future__ import annotations

import asyncio

import pytest

from simplon import context, steplog
from simplon.context import ProductContext
from simplon.orchestrator.steps import (CRASH_RC, Outcome, Pipeline, Step, StepState, failure_report,
                                        run_headless, transcript)


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    """A real product context, so `steplog` actually writes - two of the assertions below are about a
    file existing on disk rather than about a string."""
    monkeypatch.setattr(context, "_current",
                        ProductContext("probe", tmp_path, tmp_path / "probe.yaml"))


def _crashing_step(command: str = "probe.crash", message: str = "the device answered nothing") -> Step:
    def action() -> Outcome:
        raise RuntimeError(message)
    return Step(label=command, command=command, action=action)


def _ok_step(command: str) -> Step:
    return Step(label=command, command=command, action=lambda: Outcome(rc=0, output="fine"))


# --- the step itself ----------------------------------------------------------------------------------


def test_a_step_whose_action_raises_ends_failed_with_an_rc_and_a_duration():
    # Arrange: the three fields si#182 found unset for ever
    step = _crashing_step()
    # Act
    outcome = step.run()
    # Assert: it has a verdict, not a spinner
    assert step.state == StepState.FAILED
    assert step.rc == CRASH_RC
    assert step.ended_at is not None and step.duration is not None
    assert outcome.rc == CRASH_RC


def test_the_traceback_is_kept_on_the_step_rather_than_swallowed():
    # Arrange
    step = _crashing_step(message="the device answered nothing")
    # Act
    step.run()
    # Assert: the exception's own text, its type, and the sentence that says this is a crash
    assert "Traceback (most recent call last):" in step.crash
    assert "RuntimeError: the device answered nothing" in step.crash
    assert "never returned an exit code of its own" in step.crash.splitlines()[-1]


def test_a_step_that_answered_carries_no_crash_text():
    """The field is the PROOF a reader may act on, so it must be empty for every ordinary failure -
    otherwise `failure_report` and the transcript would call a red gate a crash."""
    # Arrange
    step = Step(label="gate", command="gate", action=lambda: Outcome(rc=2, output="found 3 errors"))
    # Act
    step.run()
    # Assert
    assert step.state == StepState.FAILED and step.crash == ""


def test_what_a_streaming_body_printed_before_it_blew_up_is_kept_beside_the_traceback():
    """Half the evidence is the lines, not the stack: a body that printed its way to the item it fell
    over on has NAMED that item, and a record holding only the traceback throws that away."""
    # Arrange: a stream step that emits two lines and then raises
    produced: list[str] = []

    def stream(emit):
        for line in ("inventory: leaf-01", "inventory: leaf-02"):
            produced.append(line)
            emit(line)
        raise ValueError("leaf-03 did not answer")

    step = Step(label="inventory", command="probe.inventory", stream=stream, live=produced)
    # Act
    step.run()
    # Assert
    assert "inventory: leaf-01" in step.output and "inventory: leaf-02" in step.output
    assert "ValueError: leaf-03 did not answer" in step.output


def test_the_whole_traceback_goes_to_a_file_because_the_report_only_shows_its_tail(tmp_path):
    """`failure_report` shows the last ten lines. A traceback is routinely longer, and a report that
    showed ten of them and then said "the lines above are all of it" would claim the evidence does not
    exist. With the file written, the report names the path to the rest (#49's both-or-neither rule)."""
    # Arrange
    step = _crashing_step()
    # Act
    step.run()
    # Assert
    path = steplog.existing_log("probe.crash")
    assert path is not None and "RuntimeError: the device answered nothing" in path.read_text()


def test_an_interrupt_is_not_a_crash_and_still_leaves_the_step_a_duration():
    """`Exception`, not `BaseException`: a `KeyboardInterrupt` is the operator saying stop, not a body
    blowing up, so it still ends the run. What si#182 adds for it is the `finally` - the step the
    operator stopped is the one everybody asks about, and it now carries how long it had been going."""
    # Arrange
    def action() -> Outcome:
        raise KeyboardInterrupt
    step = Step(label="long", command="probe.long", action=action)
    # Act / Assert
    with pytest.raises(KeyboardInterrupt):
        step.run()
    assert step.ended_at is not None and step.duration is not None
    assert step.crash == ""          # it did not blow up, so it is not recorded as having done so


# --- what the renderers say ---------------------------------------------------------------------------


def test_the_failure_report_says_crashed_rather_than_naming_an_exit_code_the_step_never_produced():
    # Arrange
    pipeline = Pipeline("probe", [_crashing_step()])
    pipeline.steps[0].run()
    # Act
    lines = failure_report(pipeline)
    # Assert
    assert lines[0] == "why probe.crash crashed (it raised, so it has no exit code of its own):"
    assert not any("failed (rc" in line for line in lines)


def test_the_transcript_says_crashed_where_it_would_otherwise_print_an_rc():
    # Arrange
    pipeline = Pipeline("probe", [_crashing_step()])
    pipeline.steps[0].run()
    # Act
    lines = transcript(pipeline, [])
    # Assert
    assert any(line.startswith("✗ probe.crash  crashed") for line in lines)
    assert not any("probe.crash  rc " in line for line in lines)


# --- the run reaches its end --------------------------------------------------------------------------


def test_a_crashed_step_does_not_take_the_headless_run_down(capsys):
    """The whole of si#182 in one assertion: `run_headless` RETURNS, and it returns the verdict rather
    than a traceback on stderr."""
    # Arrange
    pipeline = Pipeline("probe", [_ok_step("probe.first"), _crashing_step(), _ok_step("probe.last")])
    # Act
    rc = run_headless(pipeline)
    # Assert
    assert rc == 1
    assert pipeline.steps[2].state == StepState.OK          # the run went ON, it did not die
    assert "the same steps, as the TUI draws them:" in capsys.readouterr().out


def test_the_run_that_went_wrong_is_the_one_that_leaves_a_transcript(tmp_path):
    """Losing this file is the worst part of the old behaviour: the artefact exists precisely for the run
    that went wrong, and it was written for every run except that one. The assertion is the file."""
    # Arrange
    pipeline = Pipeline("probe", [_crashing_step()])
    # Act
    run_headless(pipeline)
    # Assert
    written = tmp_path / "build" / "logs" / steplog.RUN_TRANSCRIPT
    assert written.is_file()
    assert "✗ probe.crash  crashed" in written.read_text()


def test_the_record_is_written_even_when_the_walk_itself_raises(tmp_path, monkeypatch):
    """`Step.run` turns a BODY's crash into a verdict, so what is left leaving `run_plan` is a
    `KeyboardInterrupt`, a `SystemExit` and a fault in a runner's own hook. Each of those is a run whose
    record is worth more than most, and each lost all three artefacts before the `finally`."""
    # Arrange: a hook that raises, which is the fault no step-level catch can reach
    from simplon.orchestrator import steps as steps_module

    def exploding_walk(pipeline, hooks=None):
        pipeline.steps[0].run()
        raise RuntimeError("the runner's own hook fell over")

    monkeypatch.setattr(steps_module, "run_plan", exploding_walk)
    pipeline = Pipeline("probe", [_ok_step("probe.first")])
    # Act
    with pytest.raises(RuntimeError):
        run_headless(pipeline)
    # Assert: the transcript survived the exception it did not catch
    assert (tmp_path / "build" / "logs" / steplog.RUN_TRANSCRIPT).is_file()


def test_a_broken_tree_print_does_not_replace_the_exception_that_was_already_travelling(monkeypatch):
    """An exception raised inside a `finally` REPLACES the one in flight, so a fault in the retraced tree
    would swap the operator's Ctrl-C for a `UnicodeEncodeError` from the code reporting it - si#161
    measured that very fault on that very loop."""
    # Arrange
    from simplon.orchestrator import steps as steps_module

    def exploding_tree(*args, **kwargs):
        raise UnicodeEncodeError("charmap", "✗", 0, 1, "cannot encode")

    monkeypatch.setattr(steps_module, "render_tree", exploding_tree)
    pipeline = Pipeline("probe", [_crashing_step()])
    # Act
    rc = run_headless(pipeline)
    # Assert: the run still reported its own verdict, and the transcript still landed
    assert rc == 1
    assert steplog.existing_log("probe.crash") is not None


# --- the TUI half -------------------------------------------------------------------------------------


def test_the_tui_reaches_its_done_handler_when_a_body_blows_up():
    """Textual CATCHES a worker's exception, so before si#182 `_on_done` was simply never reached: the
    app did not die, it just stopped saying anything, and the row stayed on `↻` with its timer running.
    Nothing on the screen said the run had ended."""
    # Arrange
    pytest.importorskip("textual")
    from simplon.orchestrator.tui import _StepApp
    pipeline = Pipeline("probe", [_ok_step("probe.first"), _crashing_step(), _ok_step("probe.last")])

    async def drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return app.sub_title

    # Act
    sub_title = asyncio.run(drive())
    # Assert: a verdict on screen, and no row left claiming to be busy
    assert sub_title == "done - failures (press q)"
    assert not any(step.state == StepState.RUNNING for step in pipeline.steps)
    assert pipeline.steps[1].crash and pipeline.steps[2].state == StepState.OK
