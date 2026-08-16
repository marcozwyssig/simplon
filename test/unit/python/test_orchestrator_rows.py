"""Tests for the DISPLAY tree both runners render (delivery.orchestrator.steps: Row, build_rows,
omitted_note, render_tree) and for the headless print of it - netctl#1276.

No Textual here: the tree is plain data plus a text renderer, so its structure, its derived aggregate
states and its two fallbacks are testable without a terminal. The Textual half (mounting these rows as a
`Tree`, the right pane, the auto-focus) lives in test_orchestrator_tui.py, which skips when Textual is
absent. AAA throughout.
"""
from __future__ import annotations

from delivery.orchestrator.manifest import load as manifest_load
from delivery.orchestrator.steps import (
    Outcome,
    Pipeline,
    Row,
    Step,
    StepState,
    build_rows,
    omitted_note,
    render_tree,
    run_headless,
)

# `bringup` is an impl-less aggregate over `prep` (itself an aggregate), `build` (an aggregate whose whole
# subtree `prep` already planned, so dedup leaves it with no node at all), `install` (a LEAF `prep` already
# planned) and the leaf `up`. That gives one manifest carrying both flavours of an omitted dependency plus
# a genuinely nested plan:
#
#     deploy.bringup
#       build.prep
#         build.install
#         build.compile
#       deploy.up
_NESTED_MANIFEST = """
groups:
  build:
    install: { impl: "demo.impls:install", help: "Install host prereqs." }
    compile: { impl: "demo.impls:compile", help: "Compile the artefacts." }
    prep:    { help: "Install + compile.", depends_on: [install, compile] }
    build:   { help: "The full build.", depends_on: [prep] }
  deploy:
    up:      { impl: "demo.impls:up", help: "Deploy up." }
    bringup: { help: "Full bring-up.", depends_on: [prep, build, install, up] }
env_groups: [deploy]
"""


def _step(label: str, rc: int = 0, output: str = "") -> Step:
    return Step(label=label, action=lambda: Outcome(rc=rc, output=output))


def _planned_pipeline() -> Pipeline:
    """A Pipeline built exactly as `run_command` builds one: steps from the tree's leaves, in leaf order."""
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    steps = [_step(leaf.name) for leaf in tree.leaves()]
    return Pipeline(name="bringup", steps=steps, stop_on_failure=False, tree=tree,
                    root_path=tree.path)


def _aggregate(*states: StepState) -> Row:
    """An aggregate row over one leaf per given state - the shape the derivation rules are stated in."""
    children = []
    for index, state in enumerate(states):
        step = _step(f"leaf{index}")
        step.state = state
        children.append(Row(label=f"leaf{index}", step=step))
    return Row(label="aggregate", children=tuple(children))


# --------------------------------------------------------------------- derived aggregate state


def test_an_aggregate_is_pending_while_no_child_has_started():
    # arrange
    row = _aggregate(StepState.PENDING, StepState.PENDING)
    # act / assert
    assert row.state == StepState.PENDING


def test_an_aggregate_is_running_as_soon_as_one_child_runs():
    # arrange
    row = _aggregate(StepState.OK, StepState.RUNNING, StepState.PENDING)
    # act / assert
    assert row.state == StepState.RUNNING


def test_an_aggregate_is_ok_when_every_child_is_ok():
    # arrange
    row = _aggregate(StepState.OK, StepState.OK)
    # act / assert
    assert row.state == StepState.OK


def test_an_aggregate_is_failed_as_soon_as_one_child_fails():
    # arrange
    row = _aggregate(StepState.OK, StepState.FAILED, StepState.SKIPPED)
    # act / assert
    assert row.state == StepState.FAILED


def test_an_aggregate_is_skipped_when_every_child_is_skipped():
    # arrange
    row = _aggregate(StepState.SKIPPED, StepState.SKIPPED)
    # act / assert
    assert row.state == StepState.SKIPPED


def test_a_failed_child_outranks_a_still_running_sibling():
    """The negative case for "RUNNING as soon as a child runs": steps run sequentially, so an aggregate
    keeps running leaves after one of them failed. Reporting RUNNING there would hide the verdict."""
    # arrange
    row = _aggregate(StepState.FAILED, StepState.RUNNING)
    # act / assert
    assert row.state == StepState.FAILED


def test_an_aggregate_with_finished_and_unstarted_children_is_running_not_pending():
    """The gap between two leaves: nothing is running this instant, but the aggregate is under way."""
    # arrange
    row = _aggregate(StepState.OK, StepState.PENDING)
    # act / assert
    assert row.state == StepState.RUNNING


def test_an_aggregate_with_no_children_at_all_is_pending_rather_than_ok():
    """A vacuous "all children are OK" must not read as a green verdict for something that ran nothing."""
    # arrange
    row = Row(label="empty")
    # act / assert
    assert row.state == StepState.PENDING


def test_a_nested_aggregate_derives_its_state_through_the_intermediate_node():
    # arrange: bringup -> prep -> [install FAILED, compile PENDING], plus a pending leaf beside prep
    pipeline = _planned_pipeline()
    pipeline.steps[0].state = StepState.FAILED
    rows = build_rows(pipeline)
    # act
    prep = rows.children[0]
    # assert: the failure climbs both levels
    assert prep.state == StepState.FAILED
    assert rows.state == StepState.FAILED


# --------------------------------------------------------------------- the tree's shape


def test_build_rows_mirrors_the_plan_tree_and_labels_every_row_with_its_dotted_path():
    # arrange
    pipeline = _planned_pipeline()
    # act
    rows = build_rows(pipeline)
    # assert
    assert rows.label == "deploy.bringup"
    assert [child.label for child in rows.children] == ["build.prep", "deploy.up"]
    assert [leaf.label for leaf in rows.children[0].children] == ["build.install", "build.compile"]


def test_build_rows_attaches_each_planned_leaf_to_the_step_that_runs_it():
    """The contract `Pipeline.tree` states - steps[i] is the step for tree.leaves()[i] - is what lets an
    aggregate read its children's results. Wire it the wrong way round and every rc is mis-attributed."""
    # arrange
    pipeline = _planned_pipeline()
    # act
    rows = build_rows(pipeline)
    # assert: leaf order is post-order, so install, compile, up
    assert [row.step for row in (rows.children[0].children + (rows.children[1],))] == pipeline.steps
    assert rows.step is None and rows.children[0].step is None


def test_build_rows_reports_a_leafs_own_rc_and_leaves_an_aggregate_without_one():
    # arrange
    pipeline = _planned_pipeline()
    pipeline.steps[0].run()
    # act
    rows = build_rows(pipeline)
    # assert
    assert rows.children[0].children[0].rc == 0
    assert rows.children[0].rc is None, "an aggregate has no exit code of its own"


def test_build_rows_falls_back_to_the_root_path_with_flat_children_when_there_is_no_tree():
    """`doctor` and `up` build their Pipeline by hand: no plan, but still one root and its probes."""
    # arrange
    pipeline = Pipeline("doctor", [_step("docker engine"), _step("host egress")],
                        root_path="support.doctor")
    # act
    rows = build_rows(pipeline)
    # assert
    assert rows.label == "support.doctor"
    assert [child.label for child in rows.children] == ["docker engine", "host egress"]
    assert all(child.step is not None for child in rows.children)


def test_build_rows_uses_the_bare_pipeline_name_only_when_no_root_path_was_set():
    """The bare name is the LAST resort, not the fallback for every tree-less pipeline: reaching for it
    whenever the tree is missing would reintroduce the second vocabulary this change removes."""
    # arrange
    pipeline = Pipeline("smoke", [_step("probe")])
    # act
    rows = build_rows(pipeline)
    # assert
    assert rows.label == "smoke"


def test_build_rows_shows_the_speaking_label_never_the_argv_of_a_hand_built_step():
    # arrange: a speaking label over a long real command, the shape that turned the pane into argv
    real = "docker run --rm -v /work:/work netctl-builder:local gradle :web:bootJar --no-daemon"
    step = Step(label="package: web jar", action=lambda: Outcome(rc=0, output=""), command=real)
    # act
    rows = build_rows(Pipeline("build", [step], root_path="build.package"))
    # assert
    assert rows.children[0].label == "package: web jar"
    assert "docker run" not in rows.children[0].label


def test_build_rows_ignores_a_tree_whose_leaf_count_disagrees_with_the_steps():
    """Nothing types the leaf-to-step contract, so a broken one must degrade to the flat shape rather than
    silently attribute one leaf's result to another leaf's row - or abort a running pipeline."""
    # arrange: the plan's three leaves, but a pipeline carrying only two steps
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    pipeline = Pipeline("bringup", [_step("install"), _step("compile")], False, tree, "deploy.bringup")
    # act
    rows = build_rows(pipeline)
    # assert: root identity kept, structure dropped
    assert rows.label == "deploy.bringup"
    assert [child.label for child in rows.children] == ["install", "compile"]


# --------------------------------------------------------------------- the omitted-dependency note


def test_omitted_note_names_the_dependency_that_dedup_left_without_a_row():
    """`build`'s whole subtree was already planned, so it has no node anywhere; `install` has one, but not
    under `bringup`. An operator who goes looking for either finds a gap, and a gap explains nothing."""
    # arrange
    rows = build_rows(_planned_pipeline())
    # act
    note = omitted_note(rows)
    # assert: the aggregate that vanished by its bare name, the deduped leaf by the row that does hold it
    assert "already planned earlier in this run" in note
    assert "build" in note and "build.install" in note


def test_omitted_note_is_empty_for_a_row_whose_declared_dependencies_all_have_one():
    # arrange: prep's two dependencies are both planned under it
    rows = build_rows(_planned_pipeline())
    # act
    note = omitted_note(rows.children[0])
    # assert
    assert note == ""


def test_omitted_note_is_empty_for_a_leaf():
    # arrange
    rows = build_rows(_planned_pipeline())
    # act / assert
    assert omitted_note(rows.children[1]) == ""


# --------------------------------------------------------------------- the text rendering


def test_render_tree_indents_a_nested_plan_by_depth():
    # arrange
    rows = build_rows(_planned_pipeline())
    # act
    lines = render_tree(rows)
    # assert
    assert lines == [
        "· deploy.bringup",
        "  · build.prep",
        "    · build.install",
        "    · build.compile",
        "  · deploy.up",
    ]


def test_render_tree_shows_each_rows_state_icon_including_the_derived_ones():
    # arrange: run install and compile green, leave up pending
    pipeline = _planned_pipeline()
    pipeline.steps[0].run()
    pipeline.steps[1].run()
    # act
    lines = render_tree(build_rows(pipeline))
    # assert: prep is OK because both its children are, bringup is RUNNING because up has not started
    assert lines[0].startswith("▶ deploy.bringup")
    assert lines[1].strip().startswith("✓ build.prep")
    assert lines[4].strip().startswith("· deploy.up")


def test_run_headless_prints_the_same_tree_after_running_the_steps(capsys):
    """One structure in CI and on a TTY: the headless runner ends with the tree the TUI draws."""
    # arrange
    pipeline = _planned_pipeline()
    # act
    rc = run_headless(pipeline, verbose=False)
    # assert
    printed = capsys.readouterr().out
    assert rc == 0
    for line in ("✓ deploy.bringup", "  ✓ build.prep", "    ✓ build.install", "  ✓ deploy.up"):
        assert line in printed, f"missing tree line {line!r} in:\n{printed}"


def test_run_headless_prints_the_root_path_tree_for_a_hand_built_pipeline(capsys):
    # arrange
    pipeline = Pipeline("doctor", [_step("docker engine"), _step("host egress", rc=1)],
                        root_path="support.doctor")
    # act
    rc = run_headless(pipeline, verbose=False)
    # assert: the root is the invoked command's dotted path, and its failure climbs to it
    printed = capsys.readouterr().out
    assert rc == 1
    assert "✗ support.doctor" in printed
    assert "  ✓ docker engine" in printed
    assert "  ✗ host egress" in printed
