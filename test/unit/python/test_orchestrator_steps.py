"""Engine tests for the shared steps-runner (delivery.orchestrator.steps): the product-agnostic step
model + runners moved out of netctl. Fake actions (no real subprocess, no Textual) so the state
transitions + overall verdict are tested in isolation. This is now the home of the generic runner + its
coverage (moved here from netctl's test_steps.py)."""
from __future__ import annotations

import pytest

from delivery.orchestrator.steps import (
    Outcome,
    Pipeline,
    Step,
    StepState,
    argv_step,
    overall_rc,
    run_headless,
)


def _step(label: str, rc: int, output: str = "") -> Step:
    return Step(label=label, action=lambda: Outcome(rc=rc, output=output))


def test_step_run_transitions_to_ok_and_records_output():
    # Arrange: a passing step
    s = _step("docker engine", rc=0, output="Server: 28.0")
    # Act
    outcome = s.run()
    # Assert: OK state, output + rc captured, outcome reflects success
    assert s.state == StepState.OK
    assert s.rc == 0 and s.output == "Server: 28.0"
    assert outcome.ok is True


def test_step_run_transitions_to_failed_on_nonzero_rc():
    # Arrange: a failing step
    s = _step("host egress", rc=22, output="curl: (22) blocked")
    # Act
    s.run()
    # Assert
    assert s.state == StepState.FAILED
    assert s.rc == 22


def test_run_headless_returns_zero_when_all_pass():
    # Arrange: a pipeline of three passing steps
    p = Pipeline("doctor", [_step("a", 0), _step("b", 0), _step("c", 0)])
    # Act
    rc = run_headless(p)
    # Assert: overall success, every step OK
    assert rc == 0
    assert all(s.state == StepState.OK for s in p.steps)


def test_run_headless_returns_one_when_any_step_fails():
    # Arrange: one failing step among passing ones
    p = Pipeline("doctor", [_step("a", 0), _step("b", 1), _step("c", 0)])
    # Act
    rc = run_headless(p)
    # Assert: overall failure, but the later step still ran (no short-circuit)
    assert rc == 1
    assert p.steps[2].state == StepState.OK


def test_overall_rc_matches_step_states():
    # Arrange
    p = Pipeline("doctor", [_step("a", 0), _step("b", 0)])
    for s in p.steps:
        s.run()
    # Act / Assert
    assert overall_rc(p) == 0
    p.steps[1].state = StepState.FAILED
    assert overall_rc(p) == 1


def test_step_requires_exactly_one_of_action_or_stream():
    # Arrange / Act / Assert: neither, and both, are rejected
    with pytest.raises(ValueError):
        Step(label="x")
    with pytest.raises(ValueError):
        Step(label="x", action=lambda: Outcome(0, ""), stream=lambda emit: Outcome(0, ""))


def test_streaming_step_feeds_lines_live_and_records_output():
    # Arrange: a streaming action that emits two lines then succeeds
    seen: list[str] = []

    def stream(emit):
        emit("line-1")
        emit("line-2")
        return Outcome(rc=0, output="line-1\nline-2")

    s = Step(label="build", stream=stream)
    # Act
    s.run(seen.append)
    # Assert: the emit saw each line live, and the final state/output are recorded
    assert seen == ["line-1", "line-2"]
    assert s.state == StepState.OK
    assert s.output == "line-1\nline-2"


def test_argv_step_is_a_streaming_step_for_an_arbitrary_command():
    # Arrange / Act: a build step wrapping a docker command
    s = argv_step("web image", ["docker", "build", "-t", "netctl-web:local", "."])
    # Assert: it streams (not a quick capture action)
    assert s.stream is not None
    assert s.action is None


def test_stop_on_failure_skips_the_steps_after_a_failure():
    # Arrange: a stop_on_failure pipeline whose middle step fails (e.g. the build's web jar)
    p = Pipeline("build", [_step("unit gate", 0), _step("web jar", 1), _step("web image", 0)],
                 stop_on_failure=True)
    # Act
    rc = run_headless(p)
    # Assert: the failed step is FAILED, the one after it is SKIPPED (never run), overall is a failure
    assert p.steps[0].state == StepState.OK
    assert p.steps[1].state == StepState.FAILED
    assert p.steps[2].state == StepState.SKIPPED
    assert p.steps[2].rc is None                 # the skipped step's action never ran
    assert rc == 1


def test_without_stop_on_failure_a_failed_step_does_not_skip_the_rest():
    # Arrange: the default (bring-up) pipeline runs every step even after a failure
    p = Pipeline("bringup", [_step("a", 0), _step("b", 1), _step("c", 0)])
    # Act
    rc = run_headless(p)
    # Assert: the step after the failure still ran (no SKIPPED), overall still a failure
    assert p.steps[2].state == StepState.OK
    assert rc == 1
