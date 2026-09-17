"""The bottom bar's text, as pure data (si#148 items 2 and 8).

The bar is the one thing on screen that follows the PROCESS rather than the cursor, so what it says is
the feature and not a rendering detail. It is therefore computed by a pure function over the display tree
plus an injected `now`, and asserted here without a terminal; test_orchestrator_tui.py asserts that the
widget carries what this function returns.

The injected `now` is the same decision `simplon.tasks.allure.report_filename` made about `datetime.now`.
A test that watched a counter tick by sleeping would be slow, flaky and would prove less: the value has to
travel `started_at -> Row.elapsed -> format_duration -> the text`, and stating the `now` is what makes
that path assertable at all. Nothing here sleeps.

AAA throughout.
"""
from __future__ import annotations

from simplon.orchestrator.manifest import load as manifest_load
from simplon.orchestrator.steps import (
    Outcome,
    Pipeline,
    Row,
    RunSummary,
    Step,
    StepState,
    build_rows,
    running_rows,
    run_elapsed,
    status_line,
    summarise,
)

_MANIFEST = """
tasks:
  install: { impl: "demo.impls:install", help: "Install host prereqs." }
  compile: { impl: "demo.impls:compile", help: "Compile the artefacts." }
  up: { impl: "demo.impls:up", help: "Deploy up." }

groups:
  build:
    commands:
      install: { task: "install" }
      compile: { task: "compile" }
      prep: { help: "Install + compile.", depends_on: ["install", "compile"] }
  deploy:
    commands:
      up: { task: "up" }
      bringup: { help: "Full bring-up.", depends_on: ["prep", "up"] }
env_groups: [deploy]
"""


def _planned_rows() -> Row:
    """The display tree of a three-leaf plan - build.install, build.compile, deploy.up - untouched, so
    every leaf is still PENDING."""
    tree = manifest_load(_MANIFEST).plan_tree_for("bringup")
    steps = [Step(label=leaf.name, command=leaf.path, action=lambda: Outcome(rc=0, output=""))
             for leaf in tree.leaves()]
    return build_rows(Pipeline("bringup", steps, False, tree, tree.path))


def _leaves(root: Row) -> list[Row]:
    if root.step is not None:
        return [root]
    return [leaf for child in root.children for leaf in _leaves(child)]


def _enter(row: Row, at: float) -> None:
    """Put one leaf into RUNNING as of `at`, the way `Step.run` does before it calls the action."""
    step = row.step
    assert step is not None
    step.state = StepState.RUNNING
    step.started_at = at


def _finish(row: Row, at: float, rc: int = 0) -> None:
    step = row.step
    assert step is not None
    step.ended_at = at
    step.rc = rc
    step.state = StepState.OK if rc == 0 else StepState.FAILED


# --- the counts ---------------------------------------------------------------------------------------


def test_a_fresh_run_is_all_pending_and_says_only_that():
    # arrange
    root = _planned_rows()
    # act
    summary = summarise(root)
    # assert: the zero categories are absent, because a bar reading `0 ok · 0 failed · 0 skipped` spends
    # three quarters of its width on nothing having happened
    assert summary == RunSummary(ok=0, failed=0, skipped=0, running=0, pending=3, total=3)
    assert summary.counts == "3 pending"


def test_the_counts_name_every_category_that_has_a_member():
    # arrange
    root = _planned_rows()
    install, compile_, up = _leaves(root)
    _enter(install, 0.0)
    _finish(install, 1.0)
    _enter(compile_, 1.0)
    _finish(compile_, 2.0, rc=1)
    up.step.state = StepState.SKIPPED       # type: ignore[union-attr]
    # act
    summary = summarise(root)
    # assert
    assert summary.counts == "1 ok · 1 failed · 1 skipped"


def test_a_summary_over_no_steps_at_all_is_not_a_green_one():
    # arrange: a pipeline with no steps still renders a root row
    root = build_rows(Pipeline("empty", []))
    # act
    summary = summarise(root)
    # assert
    assert summary.total == 0
    assert summary.counts == "no steps"
    assert not summary.passed, "an empty run passed nothing; calling it green is the defect this repo hunts"


# --- who is running -----------------------------------------------------------------------------------


def test_nothing_is_running_before_the_run_starts():
    assert running_rows(_planned_rows()) == ()


def test_the_running_leaf_is_the_one_reported():
    # arrange
    root = _planned_rows()
    install, _, _ = _leaves(root)
    _enter(install, 0.0)
    # act
    running = running_rows(root)
    # assert: the LEAF, not the aggregates above it, which are RUNNING by derivation
    assert [row.label for row in running] == ["build.install"]


def test_two_running_leaves_are_both_reported_so_the_shape_survives_si147():
    """si#147 wants a parallel executor with a join. Nothing here runs two steps at once - this test
    constructs the state by hand - but the reporter must not be one that would have to be rebuilt."""
    # arrange
    root = _planned_rows()
    install, compile_, _ = _leaves(root)
    _enter(install, 0.0)
    _enter(compile_, 0.0)
    # act
    running = running_rows(root)
    # assert
    assert [row.label for row in running] == ["build.install", "build.compile"]


# --- the run's own clock ------------------------------------------------------------------------------


def test_the_run_has_no_elapsed_before_anything_started():
    assert run_elapsed(_planned_rows(), now=99.0) is None


def test_a_live_run_measures_from_its_first_step_to_now():
    # arrange
    root = _planned_rows()
    install, compile_, _ = _leaves(root)
    _enter(install, 10.0)
    _finish(install, 12.0)
    _enter(compile_, 12.0)
    # act + assert: 10.0 -> 34.0, not the running step's own 22
    assert run_elapsed(root, now=34.0) == 24.0


def test_a_finished_run_stops_measuring_at_its_last_step():
    # arrange
    root = _planned_rows()
    for index, leaf in enumerate(_leaves(root)):
        _enter(leaf, float(index))
        _finish(leaf, float(index) + 1.0)
    # act + assert: the wall clock has moved on; the run has not
    assert run_elapsed(root, now=900.0) == 3.0


# --- the line itself ----------------------------------------------------------------------------------


def test_before_the_first_step_the_bar_says_it_is_waiting_rather_than_nothing():
    """A bar that goes blank reads as a broken widget, and `on_mount` paints before the worker thread has
    entered the first step, so this frame really exists."""
    # act
    line = status_line(_planned_rows(), now=0.0)
    # assert
    assert line == "waiting to start  ·  3 pending"


def test_a_running_bar_names_the_step_its_elapsed_the_counts_and_the_runs_own_clock():
    # arrange
    root = _planned_rows()
    install, compile_, _ = _leaves(root)
    _enter(install, 0.0)
    _finish(install, 2.0)
    _enter(compile_, 2.0)
    # act
    line = status_line(root, now=14.0)
    # assert: the dotted identity, the elapsed with the mark that says it is still counting, and both
    # numbers - the step's 12 seconds and the run's 14
    assert line == "↻ build.compile  12.0s…  ·  1 ok · 1 running · 1 pending  ·  run 14.0s"


def test_a_running_step_is_named_by_its_row_identity_and_never_by_its_argv():
    """The same rule and the same reason as `_label`'s docstring: `package.web-jar` is what an operator
    scans for, and `docker run --rm -v ...` is a wall. The argv stays in the right pane's header."""
    # arrange
    argv = "docker run --rm -v /work:/work netctl-builder:local gradle :web:bootJar"
    step = Step(label="package: web jar", command=argv, action=lambda: Outcome(rc=0, output=""))
    root = build_rows(Pipeline("package", [step], root_path="package"))
    _enter(_leaves(root)[0], 0.0)
    # act
    line = status_line(root, now=1.0)
    # assert
    assert "package: web jar" in line
    assert "docker run" not in line


def test_three_running_steps_render_as_two_names_and_a_tail():
    # arrange
    tree = manifest_load(_MANIFEST).plan_tree_for("bringup")
    steps = [Step(label=leaf.name, command=leaf.path, action=lambda: Outcome(rc=0, output=""))
             for leaf in tree.leaves()]
    root = build_rows(Pipeline("bringup", steps, False, tree, tree.path))
    for leaf in _leaves(root):
        _enter(leaf, 0.0)
    # act
    line = status_line(root, now=5.0)
    # assert: the bar is one line and stays one line whatever si#147 hands it
    assert line.startswith("↻ build.install, build.compile +1 more  5.0s…")


def test_between_two_steps_the_bar_names_the_last_one_rather_than_going_blank():
    """The window is narrow but real: an aborted subtree is marked SKIPPED one step at a time with a
    repaint between each, and during that stretch no step is RUNNING and the run is not over."""
    # arrange
    root = _planned_rows()
    install, _, _ = _leaves(root)
    _enter(install, 0.0)
    _finish(install, 2.0)
    # act
    line = status_line(root, now=3.0)
    # assert
    assert line == "last: ✓ build.install  2.0s  ·  1 ok · 2 pending  ·  run 3.0s"


def test_a_finished_green_run_ends_on_its_verdict():
    # arrange
    root = _planned_rows()
    for index, leaf in enumerate(_leaves(root)):
        _enter(leaf, float(index))
        _finish(leaf, float(index) + 1.0)
    # act
    line = status_line(root, now=99.0)
    # assert: the verdict, because it is the last thing an operator reads before pressing q
    assert line == "✓ all 3 steps passed  ·  run 3.0s"


def test_a_finished_red_run_says_how_many_failed_and_how_many_never_ran():
    # arrange
    root = _planned_rows()
    install, compile_, up = _leaves(root)
    _enter(install, 0.0)
    _finish(install, 1.0)
    _enter(compile_, 1.0)
    _finish(compile_, 2.0, rc=1)
    up.step.state = StepState.SKIPPED       # type: ignore[union-attr]
    # act
    line = status_line(root, now=99.0)
    # assert
    assert line == "✗ 1 of 3 steps failed, 1 skipped  ·  run 2.0s"


# --- Row.elapsed --------------------------------------------------------------------------------------


def test_a_finished_row_reports_its_duration_and_ignores_the_clock():
    # arrange
    root = _planned_rows()
    install = _leaves(root)[0]
    _enter(install, 0.0)
    _finish(install, 2.0)
    # act + assert
    assert install.elapsed(now=900.0) == 2.0


def test_a_running_row_reports_how_long_it_has_been_running():
    # arrange
    root = _planned_rows()
    install = _leaves(root)[0]
    _enter(install, 4.0)
    # act + assert
    assert install.elapsed(now=16.0) == 12.0


def test_a_running_aggregate_measures_from_its_first_child():
    # arrange
    root = _planned_rows()
    install, compile_, _ = _leaves(root)
    _enter(install, 4.0)
    _finish(install, 6.0)
    _enter(compile_, 6.0)
    prep = root.children[0]
    # act + assert
    assert prep.label == "build.prep"
    assert prep.elapsed(now=16.0) == 12.0


def test_a_row_that_did_not_run_has_no_elapsed_and_never_a_zero():
    """The same guarantee `Row.duration` gives, restated for the live value: an absent number means 'did
    not run', so a step that never started must not answer 0.0 just because the clock is readable."""
    # arrange
    root = _planned_rows()
    install, _, up = _leaves(root)
    up.step.state = StepState.SKIPPED       # type: ignore[union-attr]
    # act + assert
    assert install.elapsed(now=5.0) is None, "PENDING"
    assert up.elapsed(now=5.0) is None, "SKIPPED"
