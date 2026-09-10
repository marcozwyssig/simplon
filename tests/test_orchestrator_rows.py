"""Tests for the DISPLAY tree both runners render (simplon.orchestrator.steps: Row, build_rows,
omitted_note, render_tree) and for the headless print of it - netctl#1276.

No Textual here: the tree is plain data plus a text renderer, so its structure, its derived aggregate
states and its two fallbacks are testable without a terminal. The Textual half (mounting these rows as a
`Tree`, the right pane, the auto-focus) lives in test_orchestrator_tui.py, which skips when Textual is
absent. AAA throughout.
"""
from __future__ import annotations

from simplon.orchestrator.manifest import load as manifest_load
import time

from simplon.orchestrator.steps import (
    STATE_ICON,
    Outcome,
    Pipeline,
    Row,
    Step,
    StepState,
    build_rows,
    format_duration,
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
      build: { help: "The full build.", depends_on: ["prep"] }
  deploy:
    commands:
      up: { task: "up" }
      bringup: { help: "Full bring-up.", depends_on: ["prep", "build", "install", "up"] }
env_groups: [deploy]
"""


def _step(label: str, rc: int = 0, output: str = "") -> Step:
    return Step(label=label, action=lambda: Outcome(rc=rc, output=output))


def _command_step(command: str, rc: int = 0) -> Step:
    """A step carrying its exact-command identity, the way a product's step factory builds one."""
    return Step(label=command, action=lambda: Outcome(rc=rc, output=""), command=command)


def _planned_pipeline() -> Pipeline:
    """A Pipeline built exactly as `run_command` builds one: steps from the tree's leaves, in leaf order,
    each stamped with its leaf's exact-command identity the way a product's step factory stamps it - which
    is what makes the pairing verifiable at all (netctl#1317)."""
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    steps = [_command_step(leaf.path) for leaf in tree.leaves()]
    return Pipeline(name="bringup", steps=steps, stop_on_failure=False, tree=tree,
                    root_path=tree.path)


_STOPPING_MANIFEST = """
tasks:
  install: { impl: "demo.impls:install", help: "Install host prereqs." }
  compile: { impl: "demo.impls:compile", help: "Compile the artefacts." }

groups:
  build:
    commands:
      install: { task: "install" }
      compile: { task: "compile" }
      prep:
        help: "Install + compile."
        depends_on: ["install", "compile"]
        stop_on_failure: true
env_groups: [build]
"""


def _stop_on_failure_pipeline() -> Pipeline:
    """A plan whose first leaf FAILS and whose subtree stops on it, so the second leaf never runs - the
    shape that produces a `⊘` row and therefore the shape #52's guarantee is about."""
    tree = manifest_load(_STOPPING_MANIFEST).plan_tree_for("prep")
    steps = [_command_step(leaf.path, rc=1 if leaf.name == "install" else 0)
             for leaf in tree.leaves()]
    return Pipeline(name="prep", steps=steps, stop_on_failure=True, tree=tree, root_path=tree.path)


def _sleeping_step(command: str, seconds: float) -> Step:
    """A step that really takes a measurable moment, so a span and a sum are distinguishable."""
    def action() -> Outcome:
        time.sleep(seconds)
        return Outcome(rc=0, output="")
    return Step(label=command, action=action, command=command)


def _walk(row: Row) -> list[Row]:
    """Every row of the display tree, root first."""
    return [row] + [descendant for child in row.children for descendant in _walk(child)]


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


def test_an_aggregate_being_skipped_one_child_at_a_time_never_reads_running():
    """A stop_on_failure run marks the doomed steps SKIPPED one at a time with a repaint between each, so a
    downstream aggregate is momentarily [SKIPPED, PENDING]. Reading that as RUNNING paints a row that will
    never run again as busy. It converges either way; a status line that is briefly wrong is still wrong."""
    # arrange
    row = _aggregate(StepState.SKIPPED, StepState.PENDING)
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


def test_an_aggregate_stays_running_until_the_LAST_leaf_below_it_is_done():
    """The "only once" half of "OK when all children are OK": finishing both of prep's leaves turns prep
    green but not bringup, which still has deploy.up outstanding."""
    # arrange
    pipeline = _planned_pipeline()
    rows = build_rows(pipeline)
    prep, up = rows.children
    seen = []
    # act: finish the leaves one at a time, recording what each level says after every one
    for step in pipeline.steps:
        step.run()
        seen.append((prep.state, rows.state))
    # assert: prep goes OK on its second leaf, bringup only on the third
    assert seen == [
        (StepState.RUNNING, StepState.RUNNING),   # install done, compile pending
        (StepState.OK, StepState.RUNNING),        # prep complete, deploy.up pending
        (StepState.OK, StepState.OK),             # deploy.up done
    ]
    assert up.state == StepState.OK


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


def test_build_rows_ignores_a_tree_whose_steps_are_in_the_wrong_order():
    """Cardinality alone is not the check. Equal counts paired the wrong way round put every result on the
    wrong row: before the identity check this shape rendered `build.install` red for `deploy.up`'s rc 7 and
    painted `deploy.up` green - worse than showing no tree at all."""
    # arrange: the right steps, built in REVERSE leaf order, each carrying its own dotted identity
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    steps = [_command_step(leaf.path, rc=7 if leaf.name == "up" else 0)
             for leaf in reversed(tree.leaves())]
    pipeline = Pipeline("bringup", steps, False, tree, "deploy.bringup")
    # act
    rows = build_rows(pipeline)
    # assert: flat, so nothing claims a structure whose rows would lie
    assert [child.label for child in rows.children] == ["deploy.up", "build.compile", "build.install"]
    assert rows.children[0].step is steps[0], "the flat shape still pairs each row with its own step"


def test_build_rows_drops_a_tree_whose_steps_name_nothing_the_kernel_can_check():
    """Reversed by netctl#1317. An empty `command` used to be tolerated here, because the verdict only
    chose a display shape and a hand-built step legitimately has none. The same verdict now also decides
    what does NOT RUN, and an unverifiable pairing cannot be trusted with that: the probe that reversed
    such steps skipped `build.image` for a failure inside `deploy.up`, a subtree it is not in. A hand-built
    pipeline has no tree, so it never reaches the guard - only a plan whose factory declined to stamp its
    steps does, and that degrades (loudly) instead."""
    # arrange
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    pipeline = Pipeline("bringup", [_step(leaf.name) for leaf in tree.leaves()], False, tree,
                        "deploy.bringup")
    # act
    rows = build_rows(pipeline)
    # assert: root identity kept, structure dropped
    assert rows.label == "deploy.bringup"
    assert [child.label for child in rows.children] == ["install", "compile", "up"]


def test_build_rows_keeps_the_tree_when_a_steps_command_is_the_leafs_bare_name():
    """`manifest_command` falls back to the bare name for a command the manifest cannot resolve to one
    unambiguous path (the #519 `test all` / `deploy all` shape), so both spellings must pass the guard."""
    # arrange
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    pipeline = Pipeline("bringup", [_command_step(leaf.name) for leaf in tree.leaves()], False, tree,
                        "deploy.bringup")
    # act
    rows = build_rows(pipeline)
    # assert
    assert [child.label for child in rows.children] == ["build.prep", "deploy.up"]


# --------------------------------------------------------------------- the omitted-dependency note


def test_omitted_note_names_the_dependency_that_dedup_left_without_a_row():
    """`build`'s whole subtree was already planned, so it has no node anywhere; `install` has one, but not
    under `bringup`. An operator who goes looking for either finds a gap, and a gap explains nothing."""
    # arrange
    rows = build_rows(_planned_pipeline())
    # act
    note = omitted_note(rows)
    # assert: the whole line, because "build" is a substring of "build.install" - asserting membership
    # would pass with the bare-name half, which is the case the finding is about, deleted outright
    assert note == ("already planned earlier in this run, so it carries no row here: "
                    "build, build.install")
    assert rows.omitted == ("build", "build.install"), (
        "the aggregate that vanished entirely is named bare; the deduped leaf by the row that does hold it")


def test_omitted_note_is_empty_for_a_row_whose_declared_dependencies_all_have_one():
    # arrange: prep's two dependencies are both planned under it
    rows = build_rows(_planned_pipeline())
    # act
    note = omitted_note(rows.children[0])
    # assert
    assert note == ""


def test_omitted_note_is_empty_for_a_command_that_declares_no_dependencies():
    """Named for what it checks. A LEAF cannot have an omitted dependency at all - the v1 manifest lock
    makes `impl` and `depends_on` mutually exclusive - so a test claiming to cover "a leaf" would be
    passing on that lock rather than on anything this code does."""
    # arrange
    rows = build_rows(_planned_pipeline())
    # act / assert
    up = rows.children[1]
    assert up.step is not None and up.omitted == ()
    assert omitted_note(up) == ""


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
    assert lines[0].startswith("↻ deploy.bringup")
    assert lines[1].strip().startswith("✓ build.prep")
    assert lines[4].strip().startswith("· deploy.up")


def test_the_headless_rows_carry_one_static_glyph_per_state_and_no_markup():
    """si#162 moved the RUNNING glyph, and `render_tree` is the second place the same table is rendered -
    a CI log, where a colour is a lie and an animation is a character nobody can read back. Every icon
    stays exactly one plain character, whatever the TUI does with it on a terminal."""
    # arrange: a run stopped between two steps, so a RUNNING row is really in the tree
    pipeline = _planned_pipeline()
    pipeline.steps[0].run()
    # act
    text = "\n".join(render_tree(build_rows(pipeline)))
    # assert
    assert all(len(icon) == 1 for icon in STATE_ICON.values()), STATE_ICON
    assert STATE_ICON[StepState.RUNNING] in text, text
    assert "\x1b" not in text, "no ANSI escape reaches a CI log"
    assert "[/" not in text and "[bold" not in text, "no rich markup either"


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


def test_run_headless_labels_the_tree_block_so_a_ci_log_is_not_two_vocabularies(capsys):
    """The per-step lines use the exact-command identity and the tree rows use the display identity, so a
    hand-built pipeline lists the same steps twice under different names. One header ties them together."""
    # arrange: a step whose command and label differ, which is exactly when the two blocks diverge
    step = Step(label="docker engine", action=lambda: Outcome(rc=0, output=""),
                command="./netctl.sh support doctor")
    # act
    run_headless(Pipeline("doctor", [step], root_path="support.doctor"), verbose=False)
    # assert
    printed = capsys.readouterr().out
    assert "./netctl.sh support doctor" in printed, "the per-step header keeps the exact command"
    assert "the same steps, as the TUI draws them:" in printed
    assert printed.index("the same steps") < printed.index("✓ support.doctor")


# --------------------------------------------------------------------- #52: what a run cost


def test_a_step_that_ran_carries_its_duration():
    # arrange
    step = _step("build.site")
    # act
    step.run()
    # assert
    assert step.duration is not None and step.duration >= 0


def test_a_step_that_never_ran_carries_no_duration():
    """The one #52 exists to guarantee: `0.0s` on a step nobody started would be a number that cannot
    tell 'nothing to do' from 'done and fast'."""
    # arrange
    step = _step("build.site")
    # act / assert: PENDING out of the box, and SKIPPED is set without ever entering run()
    assert step.duration is None
    step.state = StepState.SKIPPED
    assert step.duration is None


def test_a_skipped_row_carries_no_duration_while_its_siblings_do():
    """Seen red: a run in which `prep` stops on a failure, so `build.compile` never starts. Its row must
    be bare - not `0.0s`."""
    # arrange
    pipeline = _stop_on_failure_pipeline()
    run_headless(pipeline, verbose=False)
    rows = build_rows(pipeline)
    by_label = {row.label: row for row in _walk(rows)}
    # assert
    assert by_label["build.compile"].state == StepState.SKIPPED
    assert by_label["build.compile"].duration is None, "a step that never ran must carry no duration"
    assert by_label["build.install"].duration is not None


def test_a_pending_aggregate_carries_no_duration_either():
    # arrange: nothing has run
    rows = build_rows(_planned_pipeline())
    # act / assert
    assert rows.state == StepState.PENDING
    assert rows.duration is None


def test_an_aggregate_reports_its_own_span_and_not_the_sum_of_its_children():
    """#52's open question, decided in favour of the SPAN: it is what the operator waited through, and it
    contains the gaps between the children that a sum silently drops."""
    # arrange: two leaves that each take a measurable moment, with a gap between them
    slow = Pipeline("prep", [_sleeping_step("build.install", 0.02),
                             _sleeping_step("build.compile", 0.02)])
    run_headless(slow, verbose=False)
    rows = build_rows(slow)
    # act
    span = rows.duration
    total = sum(child.duration or 0.0 for child in rows.children)
    # assert: the span covers the children AND what happened between them
    assert span is not None
    assert span > total, "the span must contain what happened BETWEEN the children, the sum does not"


def test_an_aggregate_whose_every_leaf_was_skipped_carries_no_duration():
    """A SUM over no contributing child would be `0.0` - the exact claim this ticket forbids, one level
    up. A span over no observation has no value at all."""
    # arrange
    pipeline = _stop_on_failure_pipeline()
    for step in pipeline.steps:
        step.state = StepState.SKIPPED
    # act
    rows = build_rows(pipeline)
    # assert
    assert rows.state == StepState.SKIPPED
    assert rows.duration is None


def test_an_aggregate_reports_nothing_while_a_leaf_under_it_can_still_change_the_answer():
    # arrange: first leaf done, second not started
    pipeline = _planned_pipeline()
    pipeline.steps[0].run()
    rows = build_rows(pipeline)
    # act / assert: the finished leaf has its own number, the unfinished aggregate has none
    prep = rows.children[0]
    assert prep.children[0].duration is not None
    assert prep.duration is None and rows.duration is None


def test_the_duration_is_a_column_so_a_green_run_gains_no_line():
    """#52's acceptance 3 and #49's acceptance 3 are the same sentence: the normal case must not pay."""
    # arrange
    pipeline = _planned_pipeline()
    before = len(render_tree(build_rows(pipeline)))
    # act
    run_headless(pipeline, verbose=False)
    after = render_tree(build_rows(pipeline))
    # assert: same number of rows, and every ran row now carries a number on its own line
    assert len(after) == before
    assert all("s" in line.split("  ")[-1] for line in after)


def test_a_skipped_row_ends_where_its_name_ends():
    # arrange
    pipeline = _stop_on_failure_pipeline()
    run_headless(pipeline, verbose=False)
    # act
    lines = render_tree(build_rows(pipeline))
    # assert: no padding, no trailing blank, nothing at all in the column
    skipped = [line for line in lines if "⊘" in line]
    assert skipped == ["  ⊘ build.compile"]
    assert skipped[0] == skipped[0].rstrip(), "no padding either - the column is simply absent"


def test_the_duration_column_is_aligned_so_the_numbers_can_be_scanned():
    # arrange
    pipeline = _planned_pipeline()
    run_headless(pipeline, verbose=False)
    # act
    lines = render_tree(build_rows(pipeline))
    # assert: every duration starts at the same offset
    starts = {len(line) - len(line.rsplit(" ", 1)[-1]) for line in lines}
    assert len(starts) == 1, lines


def test_format_duration_never_prints_a_literal_zero():
    """The column's contract is that an absent number means 'did not run'. `0.0s` would be the one
    string a reader could mistake for that, so a measured-but-instant step says `<0.1s` instead."""
    assert format_duration(0.0) == "<0.1s"
    assert format_duration(0.0004) == "<0.1s"


def test_format_duration_reads_as_seconds_below_a_minute_and_as_minutes_above_one():
    assert format_duration(2.44) == "2.4s"
    assert format_duration(46.0) == "46.0s"
    assert format_duration(964.0) == "16m04s"
