"""Steps that do not wait for each other (si#147): the schedule, the bound, what a failure does to a fan,
and what a CI log looks like afterwards.

WHY THE PROOF IS A CLOCK AND NOT A COUNT. "Two steps were scheduled" is an assertion about the code that
was written, and every implementation of this feature passes it, including one that runs them one after
another. So the sleeping-step tests below measure WALL CLOCK and compare the same plan to itself with the
flag off: the sequential run takes the sum, the parallel run does not. That comparison is also why they
are not flaky thresholds - a machine under load slows both halves.

The timings are deliberately the smallest that separate the two readings on a loaded box: three steps of
`_SLEEP` seconds sum to three times it and peak at one, and the assertions leave half of the gap as
headroom either way.
"""
from __future__ import annotations

import re
import threading
import time

import pytest

from simplon.orchestrator.manifest import load as manifest_load
from simplon.orchestrator.steps import (
    Fan,
    _HeadlessOutput,
    Outcome,
    Pipeline,
    RunHooks,
    Step,
    StepState,
    build_rows,
    failure_report,
    max_parallel,
    overall_rc,
    run_headless,
    run_plan,
    schedule_for,
    status_line,
)

#: One step's sleep. Short enough that the suite pays ~1s for the whole module, long enough that the
#: difference between 3x and 1x survives a scheduler hiccup on a busy machine.
_SLEEP = 0.25


_FAN_MANIFEST = """
tasks:
  a: { impl: "demo.impls:a", help: "Image a." }
  b: { impl: "demo.impls:b", help: "Image b." }
  c: { impl: "demo.impls:c", help: "Image c." }
  verify: { impl: "demo.impls:verify", help: "Check what was built." }

groups:
  build:
    commands:
      a: { task: "a" }
      b: { task: "b" }
      c: { task: "c" }
      verify: { task: "verify" }
      images:
        help: "The three images."
        depends_on: ["a", "b", "c"]
        parallel: PARALLEL_FLAG
      build:
        help: "The images, then the check over them."
        depends_on: ["images", "verify"]
        stop_on_failure: STOP_FLAG
env_groups: []
"""

# A fan whose branches are CHAINS, which is the shape the kernel's own #901 idiom produces: an aggregate
# `[builder-image, web-jar-only]` whose two members carry no edge and are ordered by their position.
# Flattening a fan to its leaves would run these two at once and build the jar in an image that does not
# exist yet - so the schedule keeps the branches whole.
#
#     build.both          <- parallel
#       build.left          -> left-first, left-second
#       build.right         -> right-first, right-second
_CHAINED_FAN_MANIFEST = """
tasks:
  left-first: { impl: "demo.impls:lf", help: "Left, first." }
  left-second: { impl: "demo.impls:ls", help: "Left, second." }
  right-first: { impl: "demo.impls:rf", help: "Right, first." }
  right-second: { impl: "demo.impls:rs", help: "Right, second." }

groups:
  build:
    commands:
      left-first: { task: "left-first" }
      left-second: { task: "left-second" }
      right-first: { task: "right-first" }
      right-second: { task: "right-second" }
      left: { help: "The left chain.", depends_on: ["left-first", "left-second"] }
      right: { help: "The right chain.", depends_on: ["right-first", "right-second"] }
      both: { help: "Both chains at once.", depends_on: ["left", "right"], parallel: true }
env_groups: []
"""


def _manifest(text: str, *, parallel: bool = False, stop: bool = False) -> str:
    return text.replace("PARALLEL_FLAG", str(parallel).lower()).replace("STOP_FLAG", str(stop).lower())


def _planned(text: str, root: str, action=None) -> Pipeline:
    """A Pipeline built exactly as `run_command` builds one: one step per plan leaf, in leaf order, each
    stamped with its dotted identity so the leaf-to-step pairing verifies and the tree is usable."""
    tree = manifest_load(text).plan_tree_for(root)
    steps = [Step(label=leaf.name, command=leaf.path,
                  action=(lambda: Outcome(rc=0, output="")) if action is None else action(leaf.name))
             for leaf in tree.leaves()]
    return Pipeline(root, steps, tree.spec.stop_on_failure, tree, tree.path)


def _sleeper(seconds: float):
    def action_for(_name: str):
        def action() -> Outcome:
            time.sleep(seconds)
            return Outcome(rc=0, output="")
        return action
    return action_for


def _failing(*names: str):
    """Every named step fails after `_SLEEP`; the rest pass after `_SLEEP`. Both sleep, so a failure
    cannot win the race merely by being instant."""
    def action_for(name: str):
        rc = 1 if name in names else 0
        def action() -> Outcome:
            time.sleep(_SLEEP)
            return Outcome(rc=rc, output=f"{name} says {rc}")
        return action
    return action_for


def _elapsed(pipeline: Pipeline) -> float:
    start = time.perf_counter()
    run_plan(pipeline)
    return time.perf_counter() - start


# --- the schedule ------------------------------------------------------------------------------------


def test_a_plan_that_declares_nothing_is_the_flat_sequence_it_has_always_been():
    # Arrange: the same manifest with the flag off - which is every manifest that exists today
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=False), "build")
    # Act
    schedule = schedule_for(pipeline)
    # Assert: indices, in order, no fan anywhere. This is the no-regression property, and it is the one
    # worth asserting structurally rather than by timing: the measurement behind si#147 found that 466 of
    # the 541 unordered leaf pairs in the reachable manifests would BREAK if run together, so the default
    # has to be exactly what it was.
    assert schedule == (0, 1, 2, 3)


def test_a_parallel_aggregate_becomes_a_fan_and_what_follows_it_is_the_join():
    # Arrange
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "build")
    # Act
    schedule = schedule_for(pipeline)
    # Assert: the three images are branches of one fan, and `verify` sits AFTER it in the same tuple -
    # which is the join, expressed with no new concept: `depends_on` already means "after".
    assert schedule == (Fan(((0,), (1,), (2,))), 3)


def test_a_fan_keeps_each_branch_whole_instead_of_flattening_it_to_leaves():
    # Arrange: two chains that may run beside each other but not inside each other (the #901 shape)
    pipeline = _planned(_CHAINED_FAN_MANIFEST, "both")
    # Act
    schedule = schedule_for(pipeline)
    # Assert: two branches of two ordered steps, not one fan of four
    assert schedule == (Fan(((0, 1), (2, 3))),)


def test_a_pipeline_with_no_usable_tree_is_sequential_whatever_a_manifest_said():
    # Arrange: `doctor` and the other hand-built pipelines have no tree at all
    pipeline = Pipeline("doctor", [Step(label="docker", action=lambda: Outcome(rc=0, output="")),
                                   Step(label="disk", action=lambda: Outcome(rc=0, output=""))])
    # Act / Assert: `parallel` is declared on a NODE, so with no verified node there is nothing to read it
    # off - and a display-level degrade must not decide that two subprocesses may share a machine
    assert schedule_for(pipeline) == (0, 1)


# --- the clock: max rather than sum ------------------------------------------------------------------


def test_a_fan_of_sleeping_steps_takes_the_max_where_the_same_plan_in_order_takes_the_sum():
    # Arrange: the SAME three sleeping steps, once ordered and once fanned
    sequential = _planned(_manifest(_FAN_MANIFEST, parallel=False), "images", action=_sleeper(_SLEEP))
    parallel = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images", action=_sleeper(_SLEEP))
    # Act
    took_in_order = _elapsed(sequential)
    took_at_once = _elapsed(parallel)
    # Assert: the ordered run pays for all three, the fanned one pays for about one. Compared against each
    # OTHER and not against a fixed number, so a loaded machine slows both halves and the verdict stands.
    assert took_in_order >= 3 * _SLEEP
    assert took_at_once < took_in_order / 2
    assert overall_rc(parallel) == 0


def test_the_join_waits_for_every_branch_before_the_step_after_the_fan_starts():
    # Arrange: three sleeping images, then a `verify` that records when it began
    began_at: list[float] = []

    def action_for(name: str):
        def action() -> Outcome:
            if name == "verify":
                began_at.append(time.perf_counter())
                return Outcome(rc=0, output="")
            time.sleep(_SLEEP)
            return Outcome(rc=0, output="")
        return action

    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "build", action=action_for)
    # Act
    run_plan(pipeline)
    # Assert: every image had ENDED before verify started. The join is not a claim about the schedule's
    # shape - it is this inequality, which is the only thing a step after a fan actually needs.
    latest_end = max(step.ended_at or 0.0 for step in pipeline.steps if step.label != "verify")
    assert began_at and began_at[0] >= latest_end


# --- the bound ---------------------------------------------------------------------------------------


def test_the_bound_comes_from_the_machine_and_one_permit_serialises_a_fan(monkeypatch):
    # Arrange: the manifest says these three may share a machine; the machine says one at a time
    monkeypatch.setenv("SIMPLON_MAX_PARALLEL", "1")
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images", action=_sleeper(_SLEEP))
    # Act
    took = _elapsed(pipeline)
    # Assert: the sum again - the declaration says WHAT may share a machine, the environment says HOW MANY
    # fit, and a host that can only afford one still runs the plan correctly
    assert max_parallel() == 1
    assert took >= 3 * _SLEEP


def test_a_bound_that_is_not_a_step_count_warns_and_falls_back_instead_of_meaning_one(monkeypatch, capsys):
    # Arrange
    monkeypatch.setenv("SIMPLON_MAX_PARALLEL", "lots")
    # Act
    value = max_parallel()
    # Assert: a typo that silently serialised every run would be the "cannot tell nothing-to-do from
    # failed" defect wearing a number - the operator is told that what they asked for is not what happens
    assert value >= 1
    assert "SIMPLON_MAX_PARALLEL" in capsys.readouterr().out


# --- a failure with steps in flight -------------------------------------------------------------------


def test_two_parallel_steps_that_both_fail_are_both_named_and_the_run_fails_once(capsys):
    # Arrange: a and c fail at the same time; b passes
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images", action=_failing("a", "c"))
    # Act
    rc = run_headless(pipeline)
    # Assert: one rc, two failures, and NEITHER of them is "the last one wins" - the verdict is derived
    # from every step's state and the report walks every FAILED one
    assert rc == 1 and overall_rc(pipeline) == 1
    report = "\n".join(failure_report(pipeline))
    assert "build.a" in report and "build.c" in report
    assert [step.state for step in pipeline.steps] == [
        StepState.FAILED, StepState.OK, StepState.FAILED]
    printed = capsys.readouterr().out
    assert "2/3 step(s) failed" in printed


def test_a_step_already_running_when_a_sibling_fails_is_left_to_finish_and_keeps_its_own_verdict():
    # Arrange: `a` fails immediately, `b` and `c` are already in flight and take a while
    def action_for(name: str):
        def action() -> Outcome:
            if name == "a":
                return Outcome(rc=1, output="a failed at once")
            time.sleep(_SLEEP)
            return Outcome(rc=0, output=f"{name} finished anyway")
        return action

    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True, stop=True), "build", action=action_for)
    # Act
    run_plan(pipeline)
    # Assert: cancelling them was rejected because a killed subprocess exits non-zero and that number
    # cannot be told from the step having failed on its own. So they finish, and the run says which
    # happened: an in-flight sibling carries its OWN rc, and only work that never began is `⊘`.
    states = {step.label: step.state for step in pipeline.steps}
    assert states == {"a": StepState.FAILED, "b": StepState.OK, "c": StepState.OK,
                      "verify": StepState.SKIPPED}


def test_a_joined_step_does_not_run_when_a_parallel_step_it_depends_on_failed():
    # Arrange: `build` stops on failure; its plan is the fan, then `verify` over what the fan produced
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True, stop=True), "build",
                        action=_failing("b"))
    # Act
    rc = run_headless(pipeline)
    # Assert: checking images one of which was never built is doomed work, and it did not run
    verify = pipeline.steps[-1]
    assert verify.label == "verify"
    assert verify.state == StepState.SKIPPED and verify.rc is None
    assert rc == 1


def test_without_a_stop_flag_the_join_still_runs_after_a_failed_branch():
    # Arrange: the same fan, no stop_on_failure anywhere
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True, stop=False), "build",
                        action=_failing("b"))
    # Act
    run_headless(pipeline)
    # Assert: `parallel` changes WHEN steps run, never WHETHER they do - that stays stop_on_failure's, and
    # the two compose with no special case between them
    assert pipeline.steps[-1].state == StepState.OK
    assert overall_rc(pipeline) == 1


# --- the output ----------------------------------------------------------------------------------------


def _streaming(name: str, lines: int, gap: float):
    """A step that emits `lines` numbered lines with a gap between them - so two of them running together
    really do interleave in time, which is the condition the log has to survive."""
    def stream(emit) -> Outcome:
        for n in range(lines):
            emit(f"{name} line {n}")
            time.sleep(gap)
        return Outcome(rc=0, output="\n".join(f"{name} line {n}" for n in range(lines)))
    return stream


def test_two_streams_at_once_come_out_of_a_headless_run_one_block_after_the_other(capsys):
    # Arrange: three steps whose lines really do interleave in time
    text = _manifest(_FAN_MANIFEST, parallel=True)
    tree = manifest_load(text).plan_tree_for("images")
    steps = [Step(label=leaf.name, command=leaf.path, stream=_streaming(leaf.name, 5, 0.02))
             for leaf in tree.leaves()]
    pipeline = Pipeline("images", steps, False, tree, tree.path)
    # Act
    run_headless(pipeline)
    printed = capsys.readouterr().out
    # Assert: a CI log is ONE file and interleaved lines cannot be untangled afterwards, so each step's
    # lines are contiguous and the blocks stand in PLAN order whichever branch won the race.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", printed)      # the log is coloured; the ORDER is what is read
    positions = {name: [plain.index(f"{name} line {n}") for n in range(5)] for name in ("a", "b", "c")}
    for name, found in positions.items():
        assert found == sorted(found), f"{name}'s own lines are out of order"
    assert max(positions["a"]) < min(positions["b"]), "a's block is not finished before b's begins"
    assert max(positions["b"]) < min(positions["c"]), "b's block is not finished before c's begins"
    # ... and a block is not one write, so its VERDICT line is inside it too
    assert plain.index("OK build.a") < min(positions["b"]), "a's verdict landed inside b's block"
    assert plain.index("OK build.b") < min(positions["c"]), "b's verdict landed inside c's block"
    # ... and nothing was dropped to achieve it: a green streamed step's output reached the log before
    # this change and must still reach it
    assert plain.count("line 4") == 3


def test_a_second_flusher_waits_instead_of_printing_into_a_block_that_is_still_being_written(monkeypatch):
    """The lock in `_HeadlessOutput._flush`, asserted against a scheduling the test CONTROLS.

    The first version of the flusher guarded only the pointer - two branches finishing together each
    popped a different index and printed at once, so `a`'s chunks, `b`'s chunks and `a`'s own OK line came
    out woven together. It was found on a real four-step plan of `sh -c` children, and the integration
    test above did NOT catch it: with the whole block printing inside one 5ms GIL slice, a deliberately
    unlocked flusher passed two runs in five, and raising the line count to four thousand only moved it
    to three in five. A test that fails three times in five is not a guard, it is a coin.

    So this one does not race the scheduler, it pins it: `print` blocks in the middle of `a`'s block, the
    second flusher is released exactly there, and the assertion is that it is still waiting. That is the
    property in one sentence, and it cannot pass for a lucky reason."""
    import builtins

    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images")
    out = _HeadlessOutput(pipeline, show_passing=False)
    inside_the_first_block = threading.Event()
    let_the_first_finish = threading.Event()
    printed: list[str] = []

    def holding_print(text: str = "", **_kwargs: object) -> None:
        printed.append(str(text))
        if str(text).strip() == "a line 1":
            inside_the_first_block.set()
            let_the_first_finish.wait(10)

    monkeypatch.setattr(builtins, "print", holding_print)
    out._fan_start((0, 1, 2))
    for index, name in ((0, "a"), (1, "b")):
        for n in range(3):
            out._line(index, f"{name} line {n}")

    # Act: the first branch finishes and gets stuck mid-block; the second finishes while it is stuck
    first = threading.Thread(target=out._finish, args=(0,))
    first.start()
    assert inside_the_first_block.wait(10), "the first flusher never reached the held line"
    second = threading.Thread(target=out._finish, args=(1,))
    second.start()
    second.join(0.5)
    still_waiting = second.is_alive()
    let_the_first_finish.set()
    first.join(10)
    second.join(10)

    # Assert
    assert still_waiting, "the second flusher printed into the first one's block"
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in printed]
    assert plain.index("  b line 0") > plain.index("  a line 2"), "b started before a's block ended"


def test_a_headless_fan_says_that_its_blocks_are_held_so_the_timestamps_can_be_read(capsys):
    # Arrange
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images")
    # Act
    run_headless(pipeline)
    printed = capsys.readouterr().out
    # Assert: `log.info` stamps the line it PRINTS, so a held block carries flush times. The run says so
    # once rather than leaving a reader to work it out from durations that disagree with the stamps.
    assert "3 steps side by side" in printed
    assert "held and printed one step at a time, in plan order" in printed


def test_nothing_is_held_back_when_the_plan_declares_no_fan(capsys):
    # Arrange: the same steps, ordered
    text = _manifest(_FAN_MANIFEST, parallel=False)
    tree = manifest_load(text).plan_tree_for("images")
    steps = [Step(label=leaf.name, command=leaf.path, stream=_streaming(leaf.name, 2, 0.0))
             for leaf in tree.leaves()]
    # Act
    run_headless(Pipeline("images", steps, False, tree, tree.path))
    printed = capsys.readouterr().out
    # Assert: no group header, and a streamed step is not reprinted - the bytes a sequential run has
    # always produced
    assert "side by side" not in printed
    assert printed.count("a line 0") == 1


# --- what the run says while it is happening ----------------------------------------------------------


def test_the_status_bar_names_two_running_steps_at_once(monkeypatch):
    # Arrange: si#148 built the bar plural on purpose ("execution is sequential today ... a line that could
    # render only one name would have to be rebuilt for it"). This is the test that it held.
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images")
    for step in pipeline.steps[:2]:
        step.state = StepState.RUNNING
        step.started_at = 100.0
    # Act
    line = status_line(build_rows(pipeline), now=101.0)
    # Assert: both names, the longest-running elapsed, and it is still ONE line
    assert "build.a" in line and "build.b" in line
    assert "\n" not in line


def test_the_status_bar_summarises_the_rest_when_a_whole_fan_is_in_flight():
    # Arrange: three running, a bar that is one line
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images")
    for step in pipeline.steps:
        step.state = StepState.RUNNING
        step.started_at = 100.0
    # Act
    line = status_line(build_rows(pipeline), now=101.0)
    # Assert: two named, the third counted - the shape NAMED_RUNNING was chosen for
    assert "+1 more" in line
    assert "\n" not in line


# --- the hooks -----------------------------------------------------------------------------------------


def test_a_branch_that_raises_takes_the_run_down_rather_than_stopping_silently():
    # Arrange: a step whose action raises, inside a fan
    def action_for(name: str):
        def action() -> Outcome:
            if name == "b":
                raise RuntimeError("the factory broke")
            return Outcome(rc=0, output="")
        return action

    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True), "images", action=action_for)
    # Act / Assert: left to `threading`, the exception would print to stderr and the branch would simply
    # stop - a partial run reporting steps that never ran, with no reason anywhere. It is re-raised on the
    # calling thread instead, exactly as a sequential step that raises always has been.
    with pytest.raises(RuntimeError, match="the factory broke"):
        run_plan(pipeline)


def test_the_hooks_report_every_step_exactly_once_whichever_branch_it_ran_on():
    # Arrange
    pipeline = _planned(_manifest(_FAN_MANIFEST, parallel=True, stop=True), "build",
                        action=_failing("a"))
    started: list[int] = []
    finished: list[int] = []
    skipped: list[tuple[int, str]] = []
    fans: list[tuple[int, ...]] = []
    # Act
    run_plan(pipeline, RunHooks(on_start=started.append, on_finish=finished.append,
                                on_skip=lambda i, why: skipped.append((i, why)),
                                on_fan_start=fans.append))
    # Assert: one start and one finish per step that ran, one skip for the one that did not, and the fan
    # announced with its indices in plan order - the contract `_HeadlessOutput` flushes by
    assert sorted(started) == [0, 1, 2] and sorted(finished) == [0, 1, 2]
    assert [i for i, _ in skipped] == [3]
    assert "stopped on a failure" in skipped[0][1]
    assert fans == [(0, 1, 2)]
