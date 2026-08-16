"""A small step-pipeline abstraction: the backbone the TUI renders and the headless fallback prints.

A Pipeline is an ordered list of Steps; each Step has a label and an `action` that returns an Outcome
(the REAL subprocess exit code + its captured output). Keeping the action injectable makes the runner
logic - state transitions, overall pass/fail = worst step's rc - unit-testable with fake steps, and is
the seam product pipelines plug into. The Textual UI (tui.py) and the headless runner here consume the
SAME Pipeline, so step pass/fail always reflects the real rc, never the UI state (#102).
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable

from delivery import log
from delivery.run import run_stream

if TYPE_CHECKING:   # type-only: the step model is the LOWEST layer and must not import the manifest
    from delivery.orchestrator.manifest import PlanNode

# A sink for a step's live output lines (the TUI appends to a RichLog; headless prints them).
Emit = Callable[[str], None]

# Opt-in (=1): headless, print a PASSING action step's captured output too. A FAILING step's output is
# ALWAYS printed (netctl#1073) - the reason a gate said no is the whole point of the gate; a green run
# keeps the compact checklist instead of dumping every probe's `docker version` into the log.
VERBOSE_ENV = "DELIVERY_VERBOSE"


def _noop(_line: str) -> None:
    pass


def _verbose_env() -> bool:
    return os.environ.get(VERBOSE_ENV, "0") == "1"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"   # not run: a previous step failed in a stop_on_failure pipeline (e.g. build)


# The ONE state vocabulary both runners render: the TUI's tree rows and the headless tree print use these
# icons, so a CI log and a TTY show the same structure in the same alphabet (netctl#1276).
STATE_ICON = {
    StepState.PENDING: "·",
    StepState.RUNNING: "▶",
    StepState.OK: "✓",
    StepState.FAILED: "✗",
    StepState.SKIPPED: "⊘",
}


@dataclass(frozen=True)
class Outcome:
    """What a step's action returns: the real exit code and the combined output to show in details."""
    rc: int
    output: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


@dataclass
class Step:
    """One pipeline step. Either a quick `action` (returns an Outcome) OR a `stream` action (receives an
    Emit and returns an Outcome, feeding output lines live as it runs - for long steps like build/up).
    Exactly one is set. Mutable result fields fill in as it runs so the UI can render
    PENDING -> RUNNING -> OK/FAILED.

    `command` is the step's exact-command identity: the verbatim command path this step runs (a dotted
    CLI path like 'test.unit', or a real argv like 'docker build ...'). Both runners render
    `command or label` as the section header, so every section shows the EXACT command instead of a
    prose label; empty means the step has no command identity and the label stands (netctl#897, which
    reverses the earlier name+help label vocabulary of netctl#722 for the header)."""
    label: str
    action: Callable[[], Outcome] | None = None
    stream: Callable[[Emit], Outcome] | None = None
    command: str = ""
    state: StepState = StepState.PENDING
    output: str = ""
    rc: int | None = None

    def __post_init__(self) -> None:
        if (self.action is None) == (self.stream is None):
            raise ValueError("a Step needs exactly one of action / stream")

    def run(self, emit: Emit = _noop) -> Outcome:
        self.state = StepState.RUNNING
        outcome = self.stream(emit) if self.stream is not None else self.action()
        self.output = outcome.output
        self.rc = outcome.rc
        self.state = StepState.OK if outcome.ok else StepState.FAILED
        return outcome


@dataclass
class Pipeline:
    name: str
    steps: list[Step] = field(default_factory=list)
    # When true, a failed step skips the rest (they go SKIPPED) instead of running doomed work - the build
    # pipeline sets this so a red unit gate or web jar does not burn minutes building images that cannot
    # succeed. Default false keeps the bring-up pipeline's run-everything behaviour.
    stop_on_failure: bool = False
    # The plan as a TREE (#1275) plus the dotted path of the command that was INVOKED (`root_path` - named
    # for the dotted path it holds, not a node). Both are display metadata: the runners execute `steps`
    # exactly as before, and a pipeline built by hand (doctor) leaves them unset. APPENDED after
    # stop_on_failure deliberately - a dozen tests construct Pipeline positionally, so a field inserted
    # earlier would silently rebind their arguments rather than fail.
    # CONTRACT: when `tree` is set, `steps[i]` is the step built for `tree.leaves()[i]` - `run_command`
    # builds both from one comprehension over that same leaf order. Nothing enforces this at the type
    # level, so a future change that inserts, drops or reorders a step without the matching tree change
    # would silently mis-attribute a leaf's result; a reader that derives an aggregate's state from its
    # children's steps (a future slice) depends on this holding.
    tree: "PlanNode | None" = None
    root_path: str = ""


@dataclass(frozen=True, eq=False)
class Row:
    """One row of the DISPLAY tree both runners render (netctl#1276): the TUI mounts it as a Textual
    `Tree` node, `render_tree` prints it indented for CI. `eq=False` keeps identity semantics, so a row can
    key a dict even though the `Step` it points at is mutable.

    A row is either EXECUTABLE (`step` set: a planned leaf, or one hand-built step of a tree-less pipeline)
    or an AGGREGATE (`step` unset: the invoked command itself, or an impl-less node of its plan). An
    aggregate is never run; its state is DERIVED from its children, which is the whole reason the tree can
    show a verdict for a node that has no exit code of its own.

    `label` is the row's identity: the dotted `group.command` path for anything the manifest planned, the
    step's prose label for the internal probes of a pipeline built by hand. `omitted` names the declared
    dependencies that carry no row UNDER THIS ROW because dedup had already planned them, by their dotted
    path when the tree holds them elsewhere and by their bare name when the whole subtree was deduped away
    - see `omitted_note`.
    """
    label: str
    children: tuple["Row", ...] = ()
    step: Step | None = None
    omitted: tuple[str, ...] = ()

    @property
    def is_leaf(self) -> bool:
        """True when this row runs something (and therefore has its own rc), False for an aggregate."""
        return self.step is not None

    @property
    def rc(self) -> int | None:
        """The row's own exit code, or None for an aggregate and for a leaf that has not finished."""
        return self.step.rc if self.step is not None else None

    @property
    def state(self) -> StepState:
        """A leaf's own state, or an aggregate's state DERIVED from its children.

        The order of the tests is the semantics, and two of the cases the design left open are settled
        here:

        - FAILED beats RUNNING. Steps run sequentially, so an aggregate whose third leaf failed keeps
          running its fourth; reporting RUNNING there would hide the verdict behind a progress icon. The
          running leaf still shows its own icon on its own row, so nothing is lost by making the aggregate
          sticky-red.
        - A mix of finished and not-yet-started children is RUNNING, not PENDING: the aggregate is under
          way even in the gap between two of its leaves.

        SKIPPED is tested before PENDING, and on "some skipped, none OK" rather than "all skipped". A
        `stop_on_failure` run marks the doomed steps SKIPPED one at a time with a repaint between each, so
        a downstream aggregate passes through [SKIPPED, PENDING] on its way to [SKIPPED, SKIPPED]. Reading
        that as RUNNING would paint a row that will never run again as busy for a frame. It converges
        either way; a status line that is briefly wrong is still wrong.

        A terminal mix of OK and SKIPPED with no failure below it reads OK. It cannot actually occur in a
        planned tree - a node's leaves are contiguous in the flat execution order, so the failure that
        caused the skip would itself be a descendant and win above - but the rule is stated rather than
        left to fall through.
        """
        if self.step is not None:
            return self.step.state
        states = [child.state for child in self.children]
        if not states:
            return StepState.PENDING
        if StepState.FAILED in states:
            return StepState.FAILED
        if StepState.RUNNING in states:
            return StepState.RUNNING
        if StepState.SKIPPED in states and StepState.OK not in states:
            return StepState.SKIPPED       # nothing here ran, and nothing here will
        if all(state == StepState.PENDING for state in states):
            return StepState.PENDING
        if StepState.PENDING in states:
            return StepState.RUNNING       # some children finished, others have not started yet
        return StepState.OK


def _paths_by_name(node: "PlanNode", into: dict[str, str]) -> dict[str, str]:
    """Index every planned node's bare name to its dotted path, so an OMITTED dependency can be pointed at
    the row that does carry it."""
    into[node.name] = node.path
    for child in node.children:
        _paths_by_name(child, into)
    return into


def _pairs_with_leaves(leaves: "tuple[PlanNode, ...]", steps: list[Step]) -> bool:
    """Whether `steps[i]` really is the step built for `leaves[i]` - as much of the `Pipeline.tree` contract
    as the kernel can check without knowing how a product builds its steps.

    Cardinality alone is not the check. Equal counts in the wrong ORDER pair every row with the wrong
    result: a probe that built the steps in reverse leaf order produced a tree blaming `build.install` for
    `deploy.up`'s rc 7 and painting `deploy.up` green, which is worse than no tree at all.

    What the kernel owns is `Step.command`, the exact-command identity. A step built for a planned leaf
    carries that leaf's dotted path (netctl's factory spells it `manifest_command(name)`, which is
    `path_by_name` with the bare name as its fallback for a name the manifest cannot resolve
    unambiguously), so the pairing is verifiable: BOTH spellings are accepted, and an empty `command` is
    tolerated because a hand-built step legitimately has none. Only a step that names something else is
    evidence of a real mis-pairing."""
    if len(leaves) != len(steps):
        return False
    return all(not step.command or step.command in (leaf.path, leaf.name)
               for leaf, step in zip(leaves, steps))


def build_rows(pipeline: Pipeline) -> Row:
    """The display tree for a pipeline (netctl#1276). One rule for every pipeline: the ROOT row is the
    invoked command, and the children are either planned commands (dotted paths) or, for a pipeline built
    by hand, that command's internal probes (prose labels).

    With `pipeline.tree` set, the structure is the plan's own and each planned leaf carries the Step built
    for it, relying on the contract `Pipeline.tree` states: `steps[i]` is the step for `tree.leaves()[i]`.
    Nothing types that contract, so `_pairs_with_leaves` checks as much of it as the kernel can see before
    it is used, and the renderer drops to the flat shape when the check fails. A display defect must not
    silently relabel results, and it must not abort a running pipeline either.

    Without a usable tree (`doctor`, `up` - both built by hand), the root is `pipeline.root_path` and the
    steps hang off it flat. The bare `pipeline.name` is only the last resort for a pipeline that set no
    path at all: falling back to it whenever a tree is missing would reintroduce the second vocabulary this
    change exists to remove."""
    tree = pipeline.tree
    if tree is not None:
        leaves = tree.leaves()
        if _pairs_with_leaves(leaves, pipeline.steps):
            step_of = {id(leaf): step for leaf, step in zip(leaves, pipeline.steps)}
            paths = _paths_by_name(tree, {})

            def visit(node: "PlanNode") -> Row:
                children = tuple(visit(child) for child in node.children)
                planned = {child.name for child in node.children}
                omitted = tuple(paths.get(dep, dep) for dep in node.spec.depends_on if dep not in planned)
                return Row(label=node.path or node.name, children=children,
                           step=step_of.get(id(node)), omitted=omitted)

            return visit(tree)
    return Row(label=pipeline.root_path or pipeline.name,
               children=tuple(Row(label=step.label or step.command, step=step) for step in pipeline.steps))


def omitted_note(row: Row) -> str:
    """The line that explains a GAP in the tree, or "" when there is none (netctl#1276).

    Dedup plans every command once, so an aggregate whose whole subtree was already planned contributes no
    node at all: an operator who goes looking for `build` inside `bringup` finds nothing, and an absence
    explains nothing by itself. The rule is right - running the same gate twice would be worse - so the fix
    is to SAY it, on the one row that can: the parent that declared the dependency."""
    if not row.omitted:
        return ""
    return ("already planned earlier in this run, so it carries no row here: "
            + ", ".join(row.omitted))


def render_tree(root: Row, indent: str = "  ") -> list[str]:
    """The display tree as text lines, one per row, indented by depth - what `run_headless` prints so a CI
    log shows the structure the TUI draws."""
    lines: list[str] = []

    def walk(row: Row, depth: int) -> None:
        lines.append(f"{indent * depth}{STATE_ICON[row.state]} {row.label}")
        for child in row.children:
            walk(child, depth + 1)

    walk(root, 0)
    return lines


def argv_step(label: str, argv: list[str], command: str | None = None) -> Step:
    """A STREAMING Step that runs an arbitrary command and feeds its output live into the details pane.
    The build pipeline uses it to render each image build (a docker build/run) as its own step.
    `command` is the step's exact-command identity for the section header; it defaults to the real argv
    (shlex-joined), so a native docker/argv step displays the command it actually runs."""
    def stream(emit: Emit) -> Outcome:
        lines: list[str] = []

        def on_line(line: str) -> None:
            lines.append(line)
            emit(line)

        rc = run_stream(argv, on_line)
        return Outcome(rc=rc, output="\n".join(lines))
    return Step(label=label, stream=stream, command=command if command is not None else shlex.join(argv))


def _print_captured(output: str) -> None:
    """Print an action step's captured output with the SAME two-space indent the streamed lines use, so
    both kinds of step read identically headlessly."""
    for line in output.rstrip("\n").splitlines():
        print(f"  {line}", flush=True)


def run_headless(pipeline: Pipeline, verbose: bool | None = None) -> int:
    """Run every step sequentially, printing the same info/ok/warn lines the rest of netctl uses (and a
    streaming step's lines live, indented), and return the overall exit code (0 iff every step passed).
    This is the TTY-fallback / CI path - no Textual. The overall result is the worst step's rc, never
    derived from any UI state.

    An `action` step CAPTURES its output instead of streaming it, so nothing of it has been shown when it
    returns: this runner prints it (netctl#1073). Before the fix only `.ok`/`.rc` were read here and the
    text died with the Outcome - the TUI's details pane was its only reader - so a failing gate printed
    `failed (rc 1)` and swallowed the diagnosis it had just composed, on exactly the runs (CI, the in-`up`
    rebuild) nobody watches. Failures always print; a PASSING step's output only when `verbose` (default:
    the DELIVERY_VERBOSE env var), so a green `doctor` stays a checklist. A `stream` step is never
    reprinted here: its lines already went out live through `emit` and `outcome.output` is the same text
    again.

    After the last step it prints the SAME tree the TUI draws (netctl#1276), indented, with each row's
    final icon - so a CI log and a TTY show one structure in one vocabulary. It goes at the END rather than
    up front on purpose: the tree's value is the aggregate verdicts, which only exist once the leaves have
    run, and the plan itself is already implied by the per-step lines above it."""
    show_passing = _verbose_env() if verbose is None else verbose
    failures = 0
    skipped = 0
    stopped = False
    for step in pipeline.steps:
        title = step.command or step.label      # exact-command identity when the step carries one (#897)
        if stopped:
            step.state = StepState.SKIPPED
            skipped += 1
            log.warn(f"{title} - skipped (a previous step failed)")
            continue
        log.info(title)
        outcome = step.run(lambda line: print(f"  {line}", flush=True))
        if step.stream is None and outcome.output and (not outcome.ok or show_passing):
            _print_captured(outcome.output)
        if outcome.ok:
            log.ok(title)
        else:
            failures += 1
            log.warn(f"{title} - failed (rc {outcome.rc})")
            if pipeline.stop_on_failure:
                stopped = True
    # A header, because the two blocks can legitimately name the same step differently: the per-step line
    # above uses `command or label` (the exact-command identity, netctl#897) and a tree row uses the row's
    # display identity, which for a hand-built pipeline is the prose label. Without a line saying so, a CI
    # log lists one run twice under two vocabularies - the exact complaint this change answers.
    log.info("the same steps, as the TUI draws them:")
    for line in render_tree(build_rows(pipeline)):
        print(line, flush=True)
    if failures:
        tail = f", {skipped} skipped" if skipped else ""
        log.warn(f"{pipeline.name}: {failures}/{len(pipeline.steps)} step(s) failed{tail}")
        return 1
    log.ok(f"{pipeline.name}: all {len(pipeline.steps)} steps passed")
    return 0


def dispatch(pipeline: Pipeline) -> int:
    """Run a pipeline in the Textual TUI when it is importable, else headless - the one tui-or-headless
    dispatcher shared by every command that renders a Pipeline (build, up, doctor, bringup). Named
    `dispatch` (not `run`) to avoid colliding with the subprocess helpers this module imports. Kept in
    the lowest layer so callers depend downward on it, not on each other."""
    try:
        from delivery.orchestrator.tui import run_pipeline
        return run_pipeline(pipeline)
    except ImportError:
        return run_headless(pipeline)


def overall_rc(pipeline: Pipeline) -> int:
    """0 iff every step is OK, else 1 - the authoritative verdict for both runners."""
    return 0 if all(s.state == StepState.OK for s in pipeline.steps) else 1
