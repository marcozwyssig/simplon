"""Smoke tests for the shared Textual split-pane app (simplon.orchestrator.tui): drive it headlessly via
run_test() and assert the worker ran every step to its real state, that the LEFT pane is the plan tree and
that the RIGHT pane answers for both kinds of row - a leaf's output, an aggregate's children with their exit
codes. Skipped when Textual is not installed. The pure-data half of the same tree (state derivation, the
fallbacks, the text rendering) is in test_orchestrator_rows.py and needs no terminal.
"""
import asyncio
import time

import pytest

pytest.importorskip("textual")

from simplon.orchestrator.manifest import load as manifest_load  # noqa: E402
from simplon.orchestrator.steps import Outcome, Pipeline, Step, StepState  # noqa: E402
from simplon.orchestrator import steps as steps_mod  # noqa: E402
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


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Every duration this module asserts on comes from a clock the TEST holds still (#68).

    These assertions are about the FORMAT of a row - `<0.1s` for a step too fast to matter - not about
    how fast this machine happened to be. With the real `perf_counter`, a step whose action does nothing
    still measured over `format_duration`'s 0.05s threshold whenever the box was busy, and printed
    `0.1s`. That went red three times, twice while verifying an unrelated merge, and each time it said
    something about the machine's load and nothing about the code.

    A frozen clock does NOT weaken what is checked, which is the point of freezing it here rather than
    dropping the duration from the assertions: the value still travels start -> finish ->
    `format_duration` -> row text. Advance this clock and the rows say `2.4s`; both halves seen red.
    """
    monkeypatch.setattr(steps_mod, "clock", lambda: 0.0)

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


def test_the_tree_does_not_jump_anywhere_when_nothing_failed():
    """The negative case: auto-focus is for FAILURES, and `_on_done` must not move the cursor on a green
    run.

    si#148 changed where a green run leaves the cursor, and this test moved with it rather than being
    weakened. Follow mode takes the cursor to each step as it starts, so a run nobody touched ends on the
    LAST step - which is `_follow_to`'s doing and not `_on_done`'s. What is asserted is therefore that the
    cursor is where following left it, and not on some failure that does not exist."""
    # arrange
    pipeline = _planned_pipeline()

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import Tree
            return str(app.query_one("#steps", Tree).cursor_node.label), app._follow

    # act
    label, following = asyncio.run(_drive())

    # assert
    assert following is True, "nobody touched this run, so it never stopped following itself"
    assert "deploy.up" in label, "the last step to run, which is where following left it"


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
    assert root_writes == [["↻ deploy.bringup", "✓ deploy.bringup  <0.1s"]], root_writes


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


# --- the bottom bar: what is ACTIVE, whatever the cursor is doing (si#148 items 2 and 8) -------------

def _status(app) -> str:
    from textual.widgets import Static
    return str(app.query_one("#status", Static).content)


class _Clock:
    """A clock the TEST holds and moves, so an elapsed counter is asserted at a stated instant instead of
    watched with a sleep - `simplon.tasks.allure.report_filename`'s injectable `now`, one layer down."""

    def __init__(self) -> None:
        self.at = 0.0

    def __call__(self) -> float:
        return self.at


def _blocking_pipeline(release: "threading.Event") -> Pipeline:
    """A two-leaf plan whose FIRST step blocks until the test lets it go, so the run can be observed
    mid-flight rather than after the fact."""
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("prep")
    steps = []
    for index, leaf in enumerate(tree.leaves()):
        if index == 0:
            def action(event=release) -> Outcome:
                event.wait(5.0)
                return Outcome(rc=0, output="held")
        else:
            def action() -> Outcome:                      # type: ignore[misc]
                return Outcome(rc=0, output="ran")
        steps.append(Step(label=leaf.name, command=leaf.path, action=action))
    return Pipeline("prep", steps, False, tree, tree.path)


async def _until_running(pilot, pipeline: Pipeline, tries: int = 250) -> None:
    """Wait for the worker thread to enter the first step - BOUNDED, and failing with a sentence rather
    than hanging.

    An unbounded `while` here would turn a future regression that stalls the worker into a CI timeout with
    no diagnosis attached, which is the same defect class as a green verdict that lies: the test would
    stop saying anything at all. 250 x 20ms is five seconds, two orders of magnitude above what this
    actually takes, and it is a ceiling rather than a delay - nothing waits for it in the normal case."""
    for _ in range(tries):
        if pipeline.steps[0].state == StepState.RUNNING:
            return
        await pilot.pause(0.02)
    raise AssertionError(f"the worker never entered step 0; it is {pipeline.steps[0].state}")


def test_the_bar_names_the_running_step_while_the_cursor_is_somewhere_else(monkeypatch):
    """THE feature. Both panes follow the cursor, so an operator who navigated away had nothing left that
    said what was running - which is the question asked immediately before someone presses Ctrl-C."""
    import threading

    clock = _Clock()
    monkeypatch.setattr(steps_mod, "clock", clock)
    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            # arrange: the operator navigates AWAY from the running step, to the root
            _focus_line(app, 0)
            clock.at = 12.0
            app._tick()
            await pilot.pause()
            shown = _status(app)
            cursor = app._cursor_row()
            release.set()
            await app.workers.wait_for_complete()
            return shown, cursor

    # act
    shown, cursor = asyncio.run(scenario())

    # assert: the cursor really is elsewhere - on the root aggregate, not on the running leaf - and the
    # bar answers anyway
    assert cursor is not None and cursor.label == "build.prep"
    assert "build.install" in shown, f"the bar must name the running step, got: {shown}"
    assert "12.0s…" in shown, f"the bar must say how long it has been running, got: {shown}"
    assert "run 12.0s" in shown, f"the bar must carry the RUN's own clock too, got: {shown}"


def test_the_bar_carries_the_verdict_once_the_run_is_over():
    async def scenario():
        app = _StepApp(_planned_pipeline({"compile": 1}))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _status(app)

    shown = asyncio.run(scenario())
    assert "1 of 3 steps failed" in shown, shown


def test_the_bar_is_never_blank_not_even_before_the_first_step(monkeypatch):
    """A bar that empties reads as a broken widget, and `on_mount` paints before the worker thread has
    entered the first step."""
    import threading

    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        shown_at_mount: list[str] = []
        original = app._repaint_status

        def record() -> None:
            original()
            shown_at_mount.append(_status(app))

        app._repaint_status = record
        async with app.run_test() as pilot:
            await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()
            return shown_at_mount

    shown = asyncio.run(scenario())
    assert shown and all(line.strip() for line in shown), shown


def test_the_running_rows_own_label_counts_up_without_the_test_sleeping(monkeypatch):
    """si#148 item 2: while a step runs its row carried nothing at all, so 'compiling for three minutes'
    and 'hung' looked identical. The counter is driven by the injected clock, never by a sleep."""
    import threading

    clock = _Clock()
    monkeypatch.setattr(steps_mod, "clock", clock)
    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            before = app._row(0)
            clock.at = 12.0
            app._tick()
            await pilot.pause()
            after = app._row(0)
            release.set()
            await app.workers.wait_for_complete()
            return before, after

    before, after = asyncio.run(scenario())
    assert before == "↻ build.install  <0.1s…", before
    assert after == "↻ build.install  12.0s…", after
    assert "…" in after, "a running row's number must not be readable as a finished one"


def test_the_bar_follows_the_runs_state_in_its_css_class():
    async def scenario():
        app = _StepApp(_planned_pipeline({"compile": 1}))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import Static
            return set(app.query_one("#status", Static).classes)

    classes = asyncio.run(scenario())
    assert "-failed" in classes, classes


def test_the_tui_path_leaves_the_same_transcript_behind(tmp_path, monkeypatch):
    """si#148 item 3, the other half of the both-paths decision: `run_pipeline` writes AFTER `App.run()`
    returns, so a run the operator quit half way through still leaves a record of what did happen."""
    from simplon import context
    from simplon.context import ProductContext
    from simplon.orchestrator.tui import run_pipeline

    # arrange: a TTY, a registered product, and an app that quits itself the moment the run is done
    monkeypatch.setattr(context, "_current", ProductContext("cleon", tmp_path, tmp_path / "cleon.yaml"))
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    pipeline = _planned_pipeline({"compile": 1})
    real_on_done = _StepApp._on_done

    def quit_when_done(self) -> None:
        real_on_done(self)
        self.exit()

    monkeypatch.setattr(_StepApp, "_on_done", quit_when_done)

    # act
    rc = run_pipeline(pipeline)

    # assert
    assert rc == 1
    written = tmp_path / "build" / "logs" / "run-transcript.log"
    assert written.is_file(), "the TUI path must leave the same artefact the headless path does"
    text = written.read_text(encoding="utf-8")
    assert "=== simplon run transcript: bringup ===" in text
    assert "✗ build.compile  rc 1" in text


# --- follow mode (si#148 item 1) ----------------------------------------------------------------------

def test_the_cursor_follows_each_step_as_it_starts():
    """`on_mount` showed the root and the cursor stayed wherever it was, so an operator who touched
    nothing watched an aggregate listing while the interesting output went past unseen - `_on_line` only
    writes a live line when that step's own row is highlighted."""
    seen: list[str] = []

    async def scenario():
        pipeline = _planned_pipeline()
        app = _StepApp(pipeline)
        original = app._follow_to

        def record(index: int) -> None:
            original(index)
            row = app._cursor_row()
            if row is not None:
                seen.append(row.label)

        app._follow_to = record
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())
    assert seen == ["build.install", "build.compile", "deploy.up"], seen


def test_navigating_by_hand_switches_following_off():
    import threading

    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            # mid-run, so there is somewhere below the cursor to navigate TO
            await _until_running(pilot, pipeline)
            before = app._follow
            await pilot.press("down")
            await pilot.pause()
            after = app._follow
            release.set()
            await app.workers.wait_for_complete()
            return before, after

    before, after = asyncio.run(scenario())
    assert before is True, "a run nobody has touched follows itself"
    assert after is False, "the moment the operator navigates, the app stops moving the cursor"


def test_the_follow_key_switches_it_back_on_and_the_cursor_jumps_to_what_is_running(monkeypatch):
    import threading

    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            _focus_line(app, 0)                  # the operator navigates away, following stops
            await pilot.pause()
            off = app._follow
            await pilot.press("f")               # ... and asks for it back
            await pilot.pause()
            on, row = app._follow, app._cursor_row()
            release.set()
            await app.workers.wait_for_complete()
            return off, on, row

    off, on, row = asyncio.run(scenario())
    assert off is False
    assert on is True
    assert row is not None and row.label == "build.install", \
        "resuming follow does not wait for the next step - it goes to what is running now"


# --- finding a failure in a tree of forty (si#148 item 5) ---------------------------------------------

def _scattered_pipeline() -> Pipeline:
    """Failures among passes, which is the shape the ticket describes: scanning icons is the only way to
    find them today."""
    return _planned_pipeline({"install": 1, "up": 1})


def test_n_walks_the_failures_and_wraps():
    async def scenario():
        app = _StepApp(_scattered_pipeline())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 0)                       # start from the root, deliberately
            await pilot.pause()
            landed = []
            for _ in range(3):
                await pilot.press("n")
                await pilot.pause()
                row = app._cursor_row()
                landed.append(row.label if row is not None else None)
            return landed

    landed = asyncio.run(scenario())
    assert landed == ["build.install", "deploy.up", "build.install"], landed


def test_n_on_a_green_run_says_so_rather_than_moving_the_cursor_somewhere_arbitrary():
    async def scenario():
        app = _StepApp(_planned_pipeline())
        notes: list[str] = []
        app.notify = lambda message, **kw: notes.append(message)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 0)
            await pilot.press("n")
            await pilot.pause()
            row = app._cursor_row()
            return notes, row

    notes, row = asyncio.run(scenario())
    assert any("no failure" in note for note in notes), notes
    assert row is not None and row.label == "deploy.bringup", "the cursor stayed where it was"


def test_slash_filters_the_tree_to_the_matching_rows_and_the_rows_that_carry_them():
    async def scenario():
        app = _StepApp(_planned_pipeline())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("/")
            await pilot.press(*"compile")
            await pilot.pause()
            filtered = _rows(app)
            await pilot.press("/")                # toggles the box shut and clears the filter
            await pilot.pause()
            return filtered, _rows(app)

    filtered, restored = asyncio.run(scenario())
    # the match, plus the ancestors that carry it, and nothing else
    assert [row.split(" ", 1)[1].split("  ")[0] for row in filtered] == \
        ["deploy.bringup", "build.prep", "build.compile"], filtered
    assert len(restored) == 5, restored


def test_a_filter_that_matches_nothing_leaves_the_root_rather_than_an_empty_pane():
    async def scenario():
        app = _StepApp(_planned_pipeline())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("/")
            await pilot.press(*"zzz")
            await pilot.pause()
            return _rows(app), app._cursor_row()

    rows, cursor = asyncio.run(scenario())
    assert len(rows) == 1, rows
    assert cursor is not None, "a pane with no cursor has nothing to show on the right"


def test_a_run_keeps_painting_through_a_filter_that_hides_the_running_row(monkeypatch):
    """The filter remounts the tree, so a step finishing while a filter is up finds no node of its own.
    Five readers already tolerate a missing chain by design (`_mount_tree`); this asserts the filter does
    not turn that tolerance into a wrong row."""
    import threading

    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            await pilot.press("/")
            await pilot.press(*"zzz")             # hides everything, the running step included
            await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("/")                # clear it again
            await pilot.pause()
            return _rows(app)

    rows = asyncio.run(scenario())
    assert any("✓ build.install" in row for row in rows), rows


def test_every_new_key_is_in_the_footer():
    """A binding nobody can discover is a binding nobody uses. Asserted against what the footer really
    renders - `Screen.active_bindings` filtered by `show` - rather than against the BINDINGS literal,
    which says what was declared and not what a reader can see."""
    async def scenario():
        app = _StepApp(_planned_pipeline())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return {key for key, active in app.screen.active_bindings.items()
                    if active.binding.show}

    shown = asyncio.run(scenario())
    # `slash` is Textual's own name for the key; what the footer renders is the description beside it.
    assert {"f", "n", "slash"} <= shown, shown


# --- the details pane's scroll (si#148 item 6) --------------------------------------------------------

def _long_output_pipeline() -> Pipeline:
    """Two steps, each printing far more than a pane can hold, so there is somewhere to scroll TO."""
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("prep")
    steps = [Step(label=leaf.name, command=leaf.path,
                  action=lambda name=leaf.name: Outcome(
                      rc=0, output="\n".join(f"{name} line {n}" for n in range(200))))
             for leaf in tree.leaves()]
    return Pipeline("prep", steps, False, tree, tree.path)


def _details_log(app):
    from textual.widgets import RichLog
    return app.query_one("#details", RichLog)


def test_a_reader_who_scrolled_up_is_not_yanked_back_by_the_next_line():
    """MEASURED first, from `RichLog.write`: `auto_scroll` defaults to True and its `scroll_end` branch is
    unconditional - it never asks where the reader is. So every line a running step emitted pulled a
    reader who had scrolled up back to the bottom, and following a running step by READING it was
    impossible. This test was red against that before the fix."""
    async def scenario():
        app = _StepApp(_long_output_pipeline())
        async with app.run_test(size=(100, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 1)                       # build.install, with 200 lines behind it
            await pilot.pause()
            log = _details_log(app)
            log.scroll_to(y=10, animate=False)
            await pilot.pause()
            before = log.scroll_offset.y
            app._on_line(0, "a line arriving while the reader is elsewhere")
            await pilot.pause()
            return before, log.scroll_offset.y

    before, after = asyncio.run(scenario())
    assert before == 10, f"the test itself has to have scrolled, got {before}"
    assert after == before, "a line must not move a reader who is not at the bottom"


def test_a_reader_who_is_at_the_bottom_keeps_being_carried_along():
    """The other half, and the reason this is a sticky bottom rather than auto_scroll switched off: an
    operator watching the tail of a running step must go on seeing the tail."""
    async def scenario():
        app = _StepApp(_long_output_pipeline())
        async with app.run_test(size=(100, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 1)
            await pilot.pause()
            log = _details_log(app)
            log.scroll_end(animate=False)
            await pilot.pause()
            app._on_line(0, "the newest line")
            await pilot.pause()
            return log.is_vertical_scroll_end

    assert asyncio.run(scenario()) is True


def test_the_scroll_position_survives_a_trip_to_another_row_and_back():
    """`_show_details` clears the pane and rewrites it, so somebody who found a place in a long step's
    output, looked elsewhere and came back had to find it again."""
    async def scenario():
        app = _StepApp(_long_output_pipeline())
        async with app.run_test(size=(100, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            _focus_line(app, 1)                       # build.install
            await pilot.pause()
            log = _details_log(app)
            log.scroll_to(y=42, animate=False)
            await pilot.pause()
            found = log.scroll_offset.y
            _focus_line(app, 2)                       # build.compile - a different row entirely
            await pilot.pause()
            _focus_line(app, 1)                       # ... and back
            await pilot.pause()
            return found, _details_log(app).scroll_offset.y

    found, back = asyncio.run(scenario())
    assert found == 42, found
    assert back == found, f"the reader's place must survive the round trip, was {found}, came back {back}"


# --- state as colour, additively (si#148 item 7) ------------------------------------------------------

def _node_style(app, index: int):
    """The Rich style the LEFT pane really rendered step `index`'s row with."""
    return app._chain_nodes[index][-1].label.style


def test_a_failed_row_is_red_and_bold_so_it_is_findable_in_a_tree_of_forty():
    async def scenario():
        app = _StepApp(_planned_pipeline({"compile": 1}))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _node_style(app, 1), app.current_theme.error

    style, error = asyncio.run(scenario())
    assert style.color is not None and style.color.name.lower() == error.lower(), style
    assert style.bold, "bold as well as red - finding one row among forty is the whole item"


def test_a_passing_row_is_green_and_a_pending_one_is_merely_dim(monkeypatch):
    import threading

    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            running, pending = _node_style(app, 0), _node_style(app, 1)
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            return running, pending, _node_style(app, 0), app.current_theme

    running, pending, done, theme = asyncio.run(scenario())
    assert running.color is not None and running.color.name.lower() == theme.warning.lower()
    assert pending.color is None and pending.dim, "nothing has happened; a colour here spends attention"
    assert done.color is not None and done.color.name.lower() == theme.success.lower()


def test_the_glyphs_stay_so_a_colour_is_never_the_only_channel():
    """A state that is only a colour is invisible to a reader with a colour vision deficiency, to a
    terminal with a broken palette and to a log file."""
    async def scenario():
        app = _StepApp(_planned_pipeline({"compile": 1}))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return _rows(app)

    rows = asyncio.run(scenario())
    assert any(row.startswith("✗ ") for row in rows), rows
    assert any(row.startswith("✓ ") for row in rows), rows


def test_the_plain_text_paths_carry_no_markup_at_all():
    """The other half, and it is the one that would go wrong silently: `STATE_ICON` is shared with the
    HEADLESS renderer, and the run transcript is a file somebody attaches to a ticket. Colour belongs
    where the widget is rendered, never in the shared label helper."""
    from simplon.orchestrator.steps import build_rows, render_tree, transcript

    # arrange
    pipeline = _planned_pipeline({"compile": 1})
    steps_mod.run_headless(pipeline, verbose=False)
    # act
    text = "\n".join(render_tree(build_rows(pipeline)) + transcript(pipeline, header=[]))
    # assert
    assert "\x1b" not in text, "no ANSI escape reaches a CI log or a transcript"
    assert "[bold" not in text and "[/" not in text, "no rich markup either"


def test_a_row_label_stays_a_plain_string_so_painted_can_still_compare_it():
    """`_refresh_row` writes a node only when the text really changed, and it compares what `_label`
    returned. Comparing objects instead of content would repaint every row on every tick, or none."""
    app = _StepApp(_planned_pipeline())
    label = app._label(app.rows)
    assert isinstance(label, str), type(label)


def test_changing_the_theme_repaints_the_rows_in_the_new_themes_colours():
    async def scenario():
        app = _StepApp(_planned_pipeline({"compile": 1}))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            before = _node_style(app, 1).color.name
            # A theme of the test's own, not one of Textual's: several built-in themes happen to share
            # an error colour (textual-light and textual-dark are both #ba3c5b), so a swap between them
            # would assert nothing at all.
            from textual.theme import Theme
            app.register_theme(Theme(name="probe", primary="#112233", error="#ff00ff",
                                     success="#00ff00", warning="#ffaa00"))
            app.theme = "probe"
            await pilot.pause()
            return before, _node_style(app, 1).color.name, app.current_theme.error

    before, after, error = asyncio.run(scenario())
    assert after.lower() == error.lower(), (after, error)
    assert after != before, "the whole point of reading the theme is that it follows the theme"


# --- the command palette (si#148 item 9) --------------------------------------------------------------

def test_every_action_this_runner_has_is_in_the_command_palette():
    """A footer holds about five bindings before it becomes noise. The palette is where somebody FINDS
    an action instead of remembering a key."""
    async def scenario():
        app = _StepApp(_planned_pipeline())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return [command.title for command in app.get_system_commands(app.screen)]

    titles = asyncio.run(scenario())
    for wanted in ("Follow", "Next failure", "Filter", "Copy", "Save", "Transcript"):
        assert any(wanted in title for title in titles), (wanted, titles)


def test_the_theme_picker_comes_free_with_the_palette():
    """Textual's own system commands are kept, so the answer to a terminal whose palette makes our green
    unreadable costs nothing: the operator picks another theme and the rows follow it."""
    async def scenario():
        app = _StepApp(_planned_pipeline())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            return [command.title for command in app.get_system_commands(app.screen)]

    titles = asyncio.run(scenario())
    assert "Theme" in titles, titles


def test_the_palette_can_write_the_transcript_before_the_run_is_over(tmp_path, monkeypatch):
    from simplon import context
    from simplon.context import ProductContext

    monkeypatch.setattr(context, "_current", ProductContext("cleon", tmp_path, tmp_path / "cleon.yaml"))

    async def scenario():
        app = _StepApp(_planned_pipeline({"compile": 1}))
        notes: list[str] = []
        app.notify = lambda message, **kw: notes.append(message)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.action_save_transcript()
            await pilot.pause()
            return notes

    notes = asyncio.run(scenario())
    written = tmp_path / "build" / "logs" / "run-transcript.log"
    assert written.is_file(), notes
    assert "✗ build.compile" in written.read_text(encoding="utf-8")


def test_following_puts_the_live_lines_in_front_of_an_operator_who_touched_nothing():
    """si#148 item 1's stated payoff, asserted rather than argued: `_on_line` writes a live line only when
    that step's own row is highlighted (si#144 mechanism A), so an untouched run showed an aggregate
    listing while the output went past unseen. With the cursor following the run, the common case is
    covered - and mechanism A is still there for the operator who navigates away, which is what the bar
    exists for."""
    tree = manifest_load(_NESTED_MANIFEST).plan_tree_for("prep")

    def streaming(emit):
        emit("configure: checking for a C compiler")
        emit("configure: yes")
        return Outcome(rc=0, output="configure: checking for a C compiler\nconfigure: yes")

    steps = [Step(label=leaf.name, command=leaf.path,
                  stream=(streaming if index == 0 else lambda emit: Outcome(rc=0, output="")))
             for index, leaf in enumerate(tree.leaves())]
    pipeline = Pipeline("prep", steps, False, tree, tree.path)

    seen: list[str] = []

    async def scenario():
        app = _StepApp(pipeline)
        original = app._on_line

        def record(index: int, line: str) -> None:
            original(index, line)
            seen.append(_details(app))

        app._on_line = record
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())
    assert seen, "no line was ever streamed - the test is not exercising the path"
    assert "checking for a C compiler" in seen[-1], seen[-1]


def test_a_row_highlighted_mid_run_shows_what_the_step_has_already_produced(tmp_path):
    """si#144 mechanism A, driven the way the ticket specifies: run a step that produces output slowly,
    keep a DIFFERENT row highlighted while it does, then highlight the step's own row and read the pane.

    si#148's follow mode covers the operator who touches nothing - the cursor rides the running step and
    `_on_line` writes each line as it arrives. This is the operator who navigated away and came back,
    for whom the pane used to say `(running…)` and nothing else, however much the step had printed.

    A REAL child through the real `run_stream`, not a fake stream action: what broke here was the
    plumbing between the reader and the pane, and a fake action does not have any. The child waits for a
    file rather than sleeping, so what is asserted is "before it exited" and not "faster than this
    machine".
    """
    from simplon.orchestrator.steps import argv_step

    release = tmp_path / "release"
    slow = argv_step("slow", ["sh", "-c",
                              f"printf 'compiling one\\ncompiling two\\n'; "
                              f"while [ ! -f {release} ]; do sleep 0.02; done; echo done"],
                     command="build.compile")
    pipeline = Pipeline("smoke", [
        slow,
        Step(label="after", command="deploy.up", action=lambda: Outcome(rc=0, output="up")),
    ])

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 10       # a deadline, so a broken backlog FAILS and never hangs
            while len(slow.live) < 2 and time.monotonic() < deadline:
                await pilot.pause()
            _focus_line(app, 2)                    # the OTHER row, while the first step is still running
            await pilot.pause()
            _focus_line(app, 1)                    # ... and back to the running step
            await pilot.pause()
            mid_run = _details(app)
            release.write_text("go", encoding="utf-8")
            await app.workers.wait_for_complete()
            return mid_run

    # act
    rendered = asyncio.run(_drive())

    # assert: the backlog is there, and the pane is not claiming it has nothing
    assert "compiling one" in rendered
    assert "compiling two" in rendered
    assert "(running…)" not in rendered


# --- si#162: the state alphabet and the tree's own alphabet must not overlap ---------------------------

def _tree_own_alphabet() -> set[str]:
    """Every character a Textual `Tree` puts on a row BY ITSELF, read out of the pinned version rather
    than typed here: the two node icons and every guide variant in `Tree.LINES` - the default `│ └─ ├─`,
    the BOLD `┃ ┗━ ┣━` (reachable, because `_state_styles` renders a FAILED row bold) and the double one.
    """
    from textual.widgets import Tree
    chars = set(Tree.ICON_NODE + Tree.ICON_NODE_EXPANDED)
    for variant in Tree.LINES.values():
        chars |= set("".join(variant))
    return {ch for ch in chars if not ch.isspace()}


def test_no_state_icon_is_a_character_the_tree_already_draws():
    """si#162's first half, and the reason it is asserted over the WHOLE table rather than for RUNNING
    alone: `STATE_ICON[RUNNING]` was `▶`, which is exactly `Tree.ICON_NODE`, so a running row with
    children rendered `├── ▶ ▶ win2019   13m51s…` - two identical arrows, two unrelated meanings, on
    precisely the rows that carry work.

    Checking the other four was the ticket's own instruction and not a courtesy: `·`, `✓`, `✗` and `⊘`
    are clear, but "confirm rather than assume" is what this assertion is for, and it is what keeps the
    next glyph anybody adds from re-opening the collision silently."""
    from simplon.orchestrator.steps import STATE_ICON
    collisions = {state: icon for state, icon in STATE_ICON.items() if icon in _tree_own_alphabet()}
    assert not collisions, f"these state icons are also drawn by the tree itself: {collisions}"


def test_a_running_row_with_children_shows_one_arrow_and_it_is_the_trees(monkeypatch):
    """The screenshot, reproduced: the row REALLY RENDERED for a collapsed aggregate whose child is
    running. Asserted against the strip the widget produced, not against `_label` - the collision only
    exists once the tree has added its own icon, so a test that reads our text alone cannot see it."""
    import threading

    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            from textual.widgets import Tree
            tree = app.query_one("#steps", Tree)
            tree.root.collapse()          # the state the screenshot was in: children hidden
            await pilot.pause()
            rendered = "".join(seg.text for seg in tree.render_line(0))
            release.set()
            await app.workers.wait_for_complete()
            return rendered

    rendered = asyncio.run(scenario())
    assert "build.prep" in rendered, rendered
    assert rendered.count("▶") == 1, \
        f"exactly one ▶, the tree's own disclosure marker, belongs on this row: {rendered!r}"
    assert "↻" in rendered, f"and the state has to be visible beside it: {rendered!r}"


# --- si#162: what is on screen must follow the run, not the last time the cursor was there ------------

def _visible(log) -> str:
    """Only the lines the reader can actually SEE - the viewport, not the buffer behind it. The whole of
    si#162's second half is a pane that HELD the newest output and was scrolled somewhere else."""
    top = log.scroll_offset.y
    return "\n".join(str(line) for line in log.lines[top:top + log.size.height])


def test_coming_back_to_a_running_step_lands_on_its_tail_and_goes_on_following_it(tmp_path):
    """si#162 candidate two, driven as the ticket demands: a REAL child through the real `run_stream`,
    the cursor moved away deliberately, output produced while it is away, and the pane read back.

    si#144's backlog is not the hole - it was measured present, all 37 lines of it. What was wrong is
    WHERE the pane was pointed. `_show_details` restored the y offset the row had when it was left, and
    the row was left holding five lines that fitted the pane whole: offset 0, and at the end. Coming back
    to 37 lines, `scroll_to(y=0)` is the TOP. Measured: the pane showed `line 1` while the step was at
    `line 65`, and `_on_line`'s sticky bottom - which asks `is_vertical_scroll_end` before every write -
    never carried it again, so it stayed there for the rest of the step.

    The child is gated on files rather than timed, so every count below is exact and nothing here is a
    race against this machine."""
    from simplon.orchestrator.steps import argv_step

    gate_one, gate_two, release = (tmp_path / name for name in ("one", "two", "go"))
    slow = argv_step("slow", ["sh", "-c", f"""
        for n in $(seq 1 5); do echo "line $n"; done
        while [ ! -f {gate_one} ]; do sleep 0.02; done
        for n in $(seq 6 80); do echo "line $n"; done
        while [ ! -f {gate_two} ]; do sleep 0.02; done
        for n in $(seq 81 100); do echo "line $n"; done
        while [ ! -f {release} ]; do sleep 0.02; done
    """], command="build.compile")
    pipeline = Pipeline("smoke", [
        slow,
        Step(label="after", command="deploy.up", action=lambda: Outcome(rc=0, output="up")),
    ])

    async def _until(pilot, count: int) -> None:
        deadline = time.monotonic() + 20     # bounded, so a regression FAILS instead of hanging
        while len(slow.live) < count and time.monotonic() < deadline:
            await pilot.pause(0.02)
        assert len(slow.live) >= count, f"the child only produced {len(slow.live)} of {count} lines"

    async def _drive():
        app = _StepApp(pipeline)
        async with app.run_test(size=(100, 24)) as pilot:
            await _until(pilot, 5)
            # arrange: the operator leaves the running step while its output still fits the pane whole
            _focus_line(app, 2)
            await pilot.pause()
            gate_one.write_text("go", encoding="utf-8")
            await _until(pilot, 80)
            # act: ... and comes back to a step that has long outgrown it
            _focus_line(app, 1)
            await pilot.pause()
            log = _details_log(app)
            landed_at_the_tail, on_return = log.is_vertical_scroll_end, _visible(log)
            # ... and it has to keep following from there
            gate_two.write_text("go", encoding="utf-8")
            await _until(pilot, 100)
            # `Step.live` is appended to BEFORE the line is handed to `emit`, so reaching 100 there says
            # nothing about the UI thread having processed the hundredth `call_from_thread`. Pumped until
            # it has, bounded - one `pause()` happens to be enough today and that is not a guarantee.
            deadline = time.monotonic() + 10
            while "line 100" not in _visible(_details_log(app)) and time.monotonic() < deadline:
                await pilot.pause(0.02)
            still_following = _visible(_details_log(app))
            release.write_text("go", encoding="utf-8")
            await app.workers.wait_for_complete()
            return landed_at_the_tail, on_return, still_following

    # act
    landed_at_the_tail, on_return, still_following = asyncio.run(_drive())

    # assert
    assert landed_at_the_tail, "the reader was at the tail when they left; they have to come back to it"
    assert "line 80" in on_return, f"the newest line has to be ON SCREEN, not merely in the buffer:\n{on_return}"
    assert "line 1'" not in on_return, f"and the pane must not be back at the top:\n{on_return}"
    assert "line 100" in still_following, \
        f"a line arriving after the return has to appear too:\n{still_following}"


def test_an_aggregate_listing_moves_while_the_step_under_it_runs(monkeypatch):
    """si#162 candidate three, and it is a second defect rather than a second symptom of the first.

    Measured on 0.10.0: with the cursor on `build.prep` and its child streaming, the rendered pane was
    BYTE-IDENTICAL over 1.5 seconds in which the child produced 30 more lines. Two causes at once - the
    listing said `(running)`, which cannot change, and nothing repainted it between step boundaries,
    which a long step does not produce. Both had to go, and this test would stay green against a fix for
    either one alone only if the other were already right."""
    import threading

    clock = _Clock()
    monkeypatch.setattr(steps_mod, "clock", clock)
    release = threading.Event()
    pipeline = _blocking_pipeline(release)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            _focus_line(app, 0)                 # the operator moves to the root to see the whole shape
            await pilot.pause()
            first = _details(app)
            clock.at = 12.0                     # the clock the TEST holds, never a sleep
            app._tick()
            await pilot.pause()
            later = _details(app)
            release.set()
            await app.workers.wait_for_complete()
            return first, later

    # act
    first, later = asyncio.run(scenario())

    # assert
    assert "build.install" in first, first
    assert first != later, "an aggregate whose child is running may not render the same pane forever"
    assert "12.0s" in later, f"and what changed has to be how long it has been running:\n{later}"


def _wide_manifest(count: int) -> str:
    """A plan of ONE aggregate over `count` leaves, so its details listing is longer than the pane."""
    tasks = "\n".join(f'  t{i}: {{ impl: "demo.impls:t{i}", help: "Task {i}." }}' for i in range(count))
    commands = "\n".join(f'      c{i}: {{ task: "t{i}" }}' for i in range(count))
    depends = ", ".join(f'"c{i}"' for i in range(count))
    return (f"tasks:\n{tasks}\n\ngroups:\n  build:\n    commands:\n{commands}\n"
            f'      wide: {{ help: "All of them.", depends_on: [{depends}] }}\nenv_groups: []\n')


def test_the_repaint_of_an_aggregate_does_not_drag_a_reader_back_to_the_bottom(monkeypatch):
    """The regression the si#162 repaint could have introduced, and it is the reason this test exists
    rather than only the one above.

    `_show_details` remembers a place for the row it is LEAVING, so a repaint of the row already on
    screen finds nothing remembered and opens at the BOTTOM. Once a second, over a forty-child listing,
    that is si#148 item 6's defect - a reader yanked out of what they were reading - moved one pane over
    by the fix for a different one. Seen red against the first draft of that fix."""
    import threading

    clock = _Clock()
    monkeypatch.setattr(steps_mod, "clock", clock)
    release = threading.Event()
    tree = manifest_load(_wide_manifest(40)).plan_tree_for("wide")
    steps = []
    for index, leaf in enumerate(tree.leaves()):
        if index == 0:
            def action(event=release) -> Outcome:
                event.wait(5.0)
                return Outcome(rc=0, output="held")
        else:
            def action() -> Outcome:                      # type: ignore[misc]
                return Outcome(rc=0, output="ran")
        steps.append(Step(label=leaf.name, command=leaf.path, action=action))
    pipeline = Pipeline("wide", steps, False, tree, tree.path)

    async def scenario():
        app = _StepApp(pipeline)
        async with app.run_test(size=(100, 24)) as pilot:
            await pilot.pause()
            await _until_running(pilot, pipeline)
            _focus_line(app, 0)                     # the root, whose listing is 40 rows long
            await pilot.pause()
            log = _details_log(app)
            log.scroll_to(y=5, animate=False)       # ... and the reader is READING it, not tailing it
            await pilot.pause()
            found = log.scroll_offset.y
            clock.at = 12.0                         # the tick that now repaints the listing
            app._tick()
            await pilot.pause()
            after = _details_log(app).scroll_offset.y
            release.set()
            await app.workers.wait_for_complete()
            return found, after

    # act
    found, after = asyncio.run(scenario())

    # assert
    assert found == 5, f"the test itself has to have scrolled, got {found}"
    assert after == found, f"a repaint must not move a reader who is not at the bottom, went to {after}"
