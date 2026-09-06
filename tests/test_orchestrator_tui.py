"""Smoke tests for the shared Textual split-pane app (simplon.orchestrator.tui): drive it headlessly via
run_test() and assert the worker ran every step to its real state, that the LEFT pane is the plan tree and
that the RIGHT pane answers for both kinds of row - a leaf's output, an aggregate's children with their exit
codes. Skipped when Textual is not installed. The pure-data half of the same tree (state derivation, the
fallbacks, the text rendering) is in test_orchestrator_rows.py and needs no terminal.
"""
import asyncio

import pytest

pytest.importorskip("textual")

from simplon.orchestrator.manifest import load as manifest_load  # noqa: E402
from simplon.orchestrator.steps import Outcome, Pipeline, Step, StepState  # noqa: E402
from simplon.orchestrator.tui import _StepApp  # noqa: E402

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
  deploy:
    commands:
      up: { task: "up" }
      bringup: { help: "Full bring-up.", depends_on: ["prep", "up"] }
env_groups: [deploy]
"""


def _pipeline() -> Pipeline:
    return Pipeline("smoke", [
        Step(label="passes", action=lambda: Outcome(rc=0, output="all good")),
        Step(label="fails", action=lambda: Outcome(rc=1, output="boom")),
    ])


def _planned_pipeline(rc_by_name: dict[str, int] | None = None) -> Pipeline:
    """A Pipeline shaped exactly as `run_command` builds one: deploy.bringup over build.prep
    (build.install, build.compile) and deploy.up."""
    rc_by_name = rc_by_name or {}
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    steps = [Step(label=leaf.name, command=leaf.path,
                  action=lambda name=leaf.name: Outcome(rc=rc_by_name.get(name, 0), output=f"{name} ran"))
             for leaf in tree.leaves()]
    return Pipeline("bringup", steps, False, tree, tree.path)


def _details(app) -> str:
    from textual.widgets import RichLog
    return "\n".join(str(line) for line in app.query_one("#details", RichLog).lines)


def _rows(app) -> list[str]:
    """Every VISIBLE row of the LEFT pane, in display order - so a collapsed node would be missing."""
    from textual.widgets import Tree
    return [str(line.node.label) for line in app.query_one("#steps", Tree)._tree_lines]


def _focus_line(app, line: int) -> None:
    from textual.widgets import Tree
    app.query_one("#steps", Tree).cursor_line = line


def test_tui_app_runs_every_step_and_renders_details():
    # arrange
    pipeline = _pipeline()

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()   # the @work(thread=True) step runner
            await pilot.pause()
            # highlight the first (passing) step - line 0 is the root row, so its leaves start at 1
            _focus_line(app, 1)
            await pilot.pause()
            return _details(app)

    # act
    rendered = asyncio.run(_drive())

    # assert: both steps reached their real states, and the passing step's output rendered
    assert pipeline.steps[0].state.name == "OK"
    assert pipeline.steps[1].state.name == "FAILED"
    assert "all good" in rendered


def test_the_step_list_shows_the_speaking_name_and_the_details_pane_the_exact_command():
    """The left pane is `where am I`, the right pane is `what exactly ran`.

    Regression guard: `_row` used to render `command or label`, so a pipeline whose steps run native
    docker argv turned the step list into a wall of argv while a pipeline built from short shell
    invocations looked fine. That made ONE renderer look like two - the bring-up read well and the image
    build did not - and it is invisible in a test that only uses label-only steps.
    """
    from simplon.orchestrator.steps import argv_step

    # arrange: exactly the shape that exposed it - a speaking label over a long real command
    real = ("docker run --rm -v /work:/work -e GRADLE_USER_HOME=/home/gradle/.gradle "
            "netctl-builder:local gradle :web:bootJar -Pvaadin.productionMode --no-daemon")
    # a harmless argv carrying the REAL command as its identity: the assertion is about what each pane
    # renders, and running a docker build to find out would make this test need a daemon
    pipeline = Pipeline("smoke", [argv_step("package: web jar", ["sh", "-c", "true"], command=real)])

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            _focus_line(app, 1)
            await pilot.pause()
            return app._row(0), _details(app)

    # act
    row, details = asyncio.run(_drive())

    # assert
    assert "package: web jar" in row, f"the step list must show the speaking name, got: {row}"
    assert "docker run" not in row, f"the step list must not render the argv, got: {row}"
    assert "docker run" in details, (
        "the details pane must still carry the exact command - that is what the section-header "
        f"convention is for, got: {details}")


def test_the_left_pane_is_the_plan_tree_fully_expanded_with_dotted_paths():
    # arrange
    pipeline = _planned_pipeline()

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _rows(app)      # every node visible = nothing was left collapsed

    # act
    rows = asyncio.run(_drive())

    # assert: the aggregates survive as rows and every row is a dotted path (the #52 duration column is
    # a separate concern, pinned in its own tests, so it is trimmed off here)
    assert [row.split(" ", 1)[1].split("  ")[0] for row in rows] == [
        "deploy.bringup", "build.prep", "build.install", "build.compile", "deploy.up"]


def test_an_aggregate_row_lists_its_children_with_their_exit_codes():
    """An aggregate has no output of its own; what it can answer is what is under it and how it went."""
    # arrange
    pipeline = _planned_pipeline({"compile": 3})

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 1)     # build.prep
            await pilot.pause()
            return _details(app)

    # act
    rendered = asyncio.run(_drive())

    # assert
    assert "build.install" in rendered and "rc 0" in rendered
    assert "build.compile" in rendered and "rc 3" in rendered
    assert "install ran" not in rendered, "an aggregate must not pretend to have the child's output"


def test_the_root_row_explains_a_dependency_that_dedup_left_without_a_row():
    """Finding 2 of netctl#1276: an aggregate whose whole subtree was already planned is absent from the
    tree. The rule is right; the silence is not."""
    # arrange: bringup declares `build`, whose only dependency `prep` is planned before it
    manifest = """
tasks:
  install: { impl: "demo.impls:install", help: "Install host prereqs." }

groups:
  build:
    commands:
      install: { task: "install" }
      prep: { help: "Install.", depends_on: ["install"] }
      build: { help: "The full build.", depends_on: ["prep"] }
  deploy:
    commands:
      bringup: { help: "Full bring-up.", depends_on: ["prep", "build"] }
env_groups: [deploy]
"""
    tree = manifest_load(manifest).plan_tree_for("bringup")
    steps = [Step(label=leaf.name, command=leaf.path, action=lambda: Outcome(rc=0, output=""))
             for leaf in tree.leaves()]
    pipeline = Pipeline("bringup", steps, False, tree, tree.path)

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 0)     # the root, deploy.bringup
            await pilot.pause()
            return _rows(app), _details(app)

    # act
    rows, rendered = asyncio.run(_drive())

    # assert: no row for `build` anywhere, and the parent that declared it names it by its BARE name -
    # asserting `"build" in rendered` would pass on the substring of any `build.*` row, including with the
    # bare-name half, which is the case this test exists for, deleted outright
    assert not any("build.build" in row or row.endswith(" build") for row in rows)
    assert "already planned earlier in this run, so it carries no row here: build" in rendered


def test_the_tree_auto_focuses_the_first_failure_when_the_run_is_done():
    # arrange: the SECOND leaf fails, so a working auto-focus has to move off the root
    pipeline = _planned_pipeline({"compile": 1})

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import Tree
            return str(app.query_one("#steps", Tree).cursor_node.label), _details(app)

    # act
    label, rendered = asyncio.run(_drive())

    # assert
    assert "build.compile" in label, f"the first failure must be focused, got: {label}"
    assert "compile ran" in rendered


def test_the_tree_leaves_the_cursor_on_the_root_when_nothing_failed():
    """The negative case: auto-focus is for failures, not a cursor that wanders on every green run."""
    # arrange
    pipeline = _planned_pipeline()

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import Tree
            return str(app.query_one("#steps", Tree).cursor_node.label)

    # act
    label = asyncio.run(_drive())

    # assert
    assert "deploy.bringup" in label


def test_a_row_whose_text_did_not_change_is_not_written_again(monkeypatch):
    """Every finished leaf touches its ancestors, and an ancestor that stays RUNNING has nothing new to
    show. Textual's set_label marks every visible line of the node's subtree dirty, so writing the root
    unconditionally repaints the whole pane twice per step for no gain (measured on a 17-leaf plan: 978
    dirty-line marks against 120 when unchanged rows are elided)."""
    from textual.widgets.tree import TreeNode

    # arrange: 3 leaves under 2 aggregates, so the root stays RUNNING across most transitions
    pipeline = _planned_pipeline()
    # PER NODE, because global label uniqueness is a different claim: it would false-fail the moment two
    # steps share a label, and it would pass a run that repainted one row while eliding another's change
    writes: dict[int, list[str]] = {}
    original = TreeNode.set_label

    def recording(self, label):
        writes.setdefault(id(self), []).append(str(label))
        return original(self, label)

    monkeypatch.setattr(TreeNode, "set_label", recording)

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

    # act
    asyncio.run(_drive())

    # assert: no NODE was ever written a text it already showed, and the root went pending -> running -> ok
    # in two writes rather than one per leaf transition
    for node_writes in writes.values():
        assert all(new != previous for previous, new in zip(node_writes, node_writes[1:])), node_writes
    root_writes = [w for w in writes.values() if any("deploy.bringup" in text for text in w)]
    assert root_writes == [["▶ deploy.bringup", "✓ deploy.bringup  <0.1s"]], root_writes


def test_every_row_including_the_derived_ones_repaints_to_ok_when_the_run_finished():
    """Renamed from an "only once" claim it never made: this asserts the END state of the pane. The
    progressive half - an aggregate staying RUNNING until its LAST leaf is done - is the derivation's own
    behaviour and is pinned at the data layer, in test_orchestrator_rows.py."""
    # arrange
    pipeline = _planned_pipeline()

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _rows(app)

    # act
    rows = asyncio.run(_drive())

    # assert: the derived rows carry the OK icon, not the pending dot they were mounted with
    assert all(row.startswith("✓") for row in rows), rows
    assert all(step.state == StepState.OK for step in pipeline.steps)


def test_a_pipeline_whose_root_IS_its_only_step_still_paints_and_streams():
    """`plan_tree_for` of an impl-bearing command returns a childless node, so the root row carries the
    step itself. Recording only the chains reached through `children` left that pipeline with no chain at
    all, and every reader no-opped in silence: the row kept its pending dot and the pane said "running"
    over a step that had already exited 0. `run_command` is public kernel API, so this shape is reachable
    without going through an aggregate."""
    # arrange
    manifest = """
tasks:
  seed: { impl: "demo.impls:seed", help: "Seed the lab." }

groups:
  deploy:
    commands:
      seed: { task: "seed" }
env_groups: [deploy]
"""
    tree = manifest_load(manifest).plan_tree_for("seed")
    assert tree.children == () and len(tree.leaves()) == 1, "the shape under test is a leaf-rooted tree"
    step = Step(label="seed", command="deploy.seed",
                stream=lambda emit: (emit("seeding site zh"), Outcome(rc=0, output="seeding site zh"))[1])
    pipeline = Pipeline("seed", [step], False, tree, tree.path)

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _rows(app), _details(app)

    # act
    rows, rendered = asyncio.run(_drive())

    # assert: the single row reached OK, and its output is in the pane rather than a stale "(running…)"
    assert rows == ["✓ deploy.seed  <0.1s"], rows
    assert "seeding site zh" in rendered
    assert "(running" not in rendered and "(pending)" not in rendered


def test_the_flat_fallback_still_gives_every_step_a_working_row():
    """The count-mismatch degradation is pinned at the data layer; this pins that the TUI built on that
    shape still repaints and streams for EVERY step, rather than quietly losing the chains."""
    # arrange: the plan's three leaves against two steps, so build_rows drops to the flat shape
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("bringup")
    pipeline = Pipeline("bringup", [
        Step(label="install", action=lambda: Outcome(rc=0, output="install ran")),
        Step(label="compile", action=lambda: Outcome(rc=4, output="compile blew up")),
    ], False, tree, tree.path)

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _rows(app), _details(app)

    # act
    rows, rendered = asyncio.run(_drive())

    # assert: root plus both steps, each painted with its real outcome, and the failure auto-focused
    assert rows == ["✗ deploy.bringup  <0.1s", "✓ install  <0.1s", "✗ compile  <0.1s"], rows
    assert "compile blew up" in rendered


def test_the_tui_runner_skips_the_aborted_subtree_and_keeps_running_its_siblings():
    """Both runners must reach the same verdict for the same plan (netctl#1317). The headless half of this
    is pinned in test_orchestrator_steps.py; here the Textual worker has its own loop, which used to hold a
    single `stopped` latch and could therefore only express "stop the whole run"."""
    # arrange: `prep` stops on failure, the bring-up around it does not, and prep's first leaf dies
    manifest = """
tasks:
  install: { impl: "demo.impls:install", help: "Install host prereqs." }
  compile: { impl: "demo.impls:compile", help: "Compile the artefacts." }
  up: { impl: "demo.impls:up", help: "Deploy up." }

groups:
  build:
    commands:
      install: { task: "install" }
      compile: { task: "compile" }
      prep:
        help: "Install + compile."
        depends_on: ["install", "compile"]
        stop_on_failure: true
  deploy:
    commands:
      up: { task: "up" }
      bringup: { help: "Full bring-up.", depends_on: ["prep", "up"] }
env_groups: [deploy]
"""
    tree = manifest_load(manifest).plan_tree_for("bringup")
    pipeline = Pipeline("bringup", [
        Step(label=leaf.name, command=leaf.path,
             action=lambda name=leaf.name: Outcome(rc=1 if name == "install" else 0, output=f"{name} ran"))
        for leaf in tree.leaves()], False, tree, tree.path)

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _rows(app)

    # act
    rows = asyncio.run(_drive())

    # assert: prep's remaining leaf is skipped, prep's SIBLING still ran, and every row paints its
    # verdict - AND the skipped row carries no duration while every row that ran does (#52). `⊘
    # build.compile` bare is the assertion, not an omission: `0.0s` there would claim it finished
    # instantly instead of never starting.
    assert rows == ["✗ deploy.bringup  <0.1s", "✗ build.prep  <0.1s", "✗ build.install  <0.1s",
                    "⊘ build.compile", "✓ deploy.up  <0.1s"]
    assert [step.state for step in pipeline.steps] == [
        StepState.FAILED, StepState.SKIPPED, StepState.OK]


def test_the_details_pane_tells_a_skipped_step_which_subtree_stopped_it():
    """The headless runner prints `deploy.up stopped on a failure` beside every step it skips; the TUI used
    to show a bare ⊘ and nothing else, so the operator watching a forty-minute bring-up on a TTY - the one
    who most needs to know - never learned which subtree decided."""
    # arrange: prep stops on failure, its first leaf dies, and the cursor lands on the skipped row
    manifest = """
tasks:
  install: { impl: "demo.impls:install", help: "Install host prereqs." }
  compile: { impl: "demo.impls:compile", help: "Compile the artefacts." }
  up: { impl: "demo.impls:up", help: "Deploy up." }

groups:
  build:
    commands:
      install: { task: "install" }
      compile: { task: "compile" }
      prep:
        help: "Install + compile."
        depends_on: ["install", "compile"]
        stop_on_failure: true
  deploy:
    commands:
      up: { task: "up" }
      bringup: { help: "Full bring-up.", depends_on: ["prep", "up"] }
env_groups: [deploy]
"""
    tree = manifest_load(manifest).plan_tree_for("bringup")
    pipeline = Pipeline("bringup", [
        Step(label=leaf.name, command=leaf.path,
             action=lambda name=leaf.name: Outcome(rc=1 if name == "install" else 0, output=""))
        for leaf in tree.leaves()], False, tree, tree.path)

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 3)     # build.compile, the skipped one
            await pilot.pause()
            return _details(app)

    # act
    rendered = asyncio.run(_drive())

    # assert
    assert "skipped: build.prep stopped on a failure" in rendered
    assert "(pending)" not in rendered, "a step that will never run must not still read as pending"


# --- copy and save: getting the text OUT of a pane that holds the mouse -----------------------------

def test_c_copies_the_focused_steps_output_to_the_clipboard():
    """Textual holds the mouse while it runs, so the terminal's own selection does not work and the
    output is visible and unreachable at once. `c` is the way out that does not involve a file."""
    async def scenario():
        app = _StepApp(_pipeline())
        async with app.run_test() as pilot:
            await pilot.pause()
            while any(s.state in (StepState.PENDING, StepState.RUNNING) for s in app.pipeline.steps):
                await pilot.pause(0.05)
            copied: list[str] = []
            app.copy_to_clipboard = copied.append
            await pilot.press("down", "down")
            await pilot.press("c")
            await pilot.pause()
            return copied, app._details_text(app._cursor_row())

    copied, shown = asyncio.run(scenario())
    # What is COPIED is what is DISPLAYED - asserted against the pane's own text rather than against a
    # guess about which row two `down` presses land on.
    assert copied == [shown]
    assert shown.startswith("$ ")


def test_s_writes_the_focused_steps_output_and_says_where():
    """The same text, for the case where the clipboard is not reachable - an SSH session whose terminal
    does not do OSC 52, a run someone wants to attach to a ticket."""
    async def scenario():
        app = _StepApp(_pipeline())
        async with app.run_test() as pilot:
            await pilot.pause()
            while any(s.state in (StepState.PENDING, StepState.RUNNING) for s in app.pipeline.steps):
                await pilot.pause(0.05)
            saved: list[tuple] = []
            notes: list[str] = []
            app._save_details_to = lambda ident, text: (saved.append((ident, text)), "/tmp/x.log")[1]
            app.notify = lambda message, **kw: notes.append(message)
            await pilot.press("down", "down")
            await pilot.press("s")
            await pilot.pause()
            return saved, notes

    saved, notes = asyncio.run(scenario())
    assert len(saved) == 1
    assert any("/tmp/x.log" in note for note in notes)
