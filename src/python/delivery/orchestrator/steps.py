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
    SKIPPED = "skipped"   # not run: a failure aborted the subtree this step belongs to (see abort_after)


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
    # The pipeline-wide stop flag, and the ONLY one for a pipeline with no usable `tree`: when true, a
    # failed step skips ALL the rest (they go SKIPPED) instead of running doomed work. `doctor` and the
    # other hand-built pipelines live here. With a usable tree the flag is per NODE and this field is not
    # consulted - see `abort_after`, which `run_command` keeps consistent by setting this to the ROOT
    # node's own flag, so degrading to the flat shape degrades to the root's decision rather than to some
    # unrelated default.
    stop_on_failure: bool = False
    # The plan as a TREE (#1275) plus the dotted path of the command that was INVOKED (`root_path` - named
    # for the dotted path it holds, not a node). `root_path` is display metadata; `tree` is display metadata
    # PLUS the one thing execution reads from it, each node's `stop_on_failure` (netctl#1317). The runners
    # still walk the flat `steps` list in order; what the tree changes is which of the remaining steps a
    # failure skips. A pipeline built by hand (doctor) leaves both unset. APPENDED after
    # stop_on_failure deliberately - a dozen tests construct Pipeline positionally, so a field inserted
    # earlier would silently rebind their arguments rather than fail.
    # CONTRACT: when `tree` is set, `steps[i]` is the step built for `tree.leaves()[i]` - `run_command`
    # builds both from one comprehension over that same leaf order. Nothing enforces this at the type
    # level, so a future change that inserts, drops or reorders a step without the matching tree change
    # would silently mis-attribute a leaf's result AND mis-scope what a failure skips; `usable_tree` is
    # where that contract is checked, once.
    tree: "PlanNode | None" = None
    root_path: str = ""
    # The remembered verdict of that check: None = not yet asked. Not an init field - it is derived, and a
    # caller must never be able to assert a pairing the kernel has not verified.
    _verified: "bool | None" = field(default=None, init=False, repr=False, compare=False)

    def usable_tree(self) -> "PlanNode | None":
        """The plan tree when the kernel can VERIFY the leaf-to-step pairing, else None - the ONE verdict
        `build_rows` (display) and `abort_after` (execution) both read.

        Computed once and remembered, deliberately. Both consumers ask at different points of a run, over a
        mutable `steps` list of mutable `Step`s, and "they happen to call the same helper" is a claim
        nothing enforces: three independent evaluations could disagree, and a display that shows the plan
        while execution scopes a failure by something else is the one outcome worse than either failing
        alone. The verdict is a property of how the pipeline was BUILT, so asking once is also the honest
        reading of it.

        A rejected tree is WARNED about, once, naming what is lost: the display shape is the smaller half,
        the stop SCOPE is the safety-relevant one. Dropping every subtree's `stop_on_failure` back onto a
        root that says `false` reinstates exactly the defect netctl#1317 exists to fix, and it would do so
        with no signal beyond a tree that came out flat."""
        if self._verified is None:
            self._verified = self.tree is not None and _pairs_with_leaves(self.tree.leaves(), self.steps)
            if self.tree is not None and not self._verified:
                stops = "the whole run stops" if self.stop_on_failure else "nothing is skipped"
                log.warn(f"{self.name}: the plan tree does not pair with the steps that will run, so it is "
                         f"not used - the display falls back to a flat list AND every subtree's "
                         f"stop_on_failure is dropped, so a failure now means {stops}")
        return self.tree if self._verified else None


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
    unambiguously), so the pairing is verifiable and BOTH spellings are accepted.

    A step that names NOTHING is not verifiable, and since netctl#1317 that is a rejection rather than a
    tolerance. The tolerance was written when this verdict only chose a display shape, where trusting an
    unnamed step costs a mislabelled row; it now also chooses what does NOT RUN, where the same trust
    reversed the steps and skipped `build.image` for a failure inside `deploy.up`, a subtree it is not even
    in. A hand-built step legitimately carries no command - and a hand-built pipeline has no tree, so it
    never reaches this function. On the path that does reach it, an unverifiable pairing must degrade
    (loudly, see `Pipeline.usable_tree`) rather than be trusted."""
    if len(leaves) != len(steps):
        return False
    return all(step.command in (leaf.path, leaf.name) for leaf, step in zip(leaves, steps))


# --- what a failure aborts (netctl#1317) --------------------------------------------------------------


@dataclass(frozen=True)
class Abort:
    """What ONE step failure aborts: the indices of the steps that must not run, and the dotted path of the
    subtree whose flag decided it (empty when the decision came from the pipeline's own single flag, so a
    reader can tell "the whole run stops" from "this subtree stops").

    INVARIANT: a named scope skips at least one step. An `Abort` that names a subtree and skips nothing
    would let `reason` announce that some node stopped a run in which nothing was stopped, and the shape is
    reachable - a flagged aggregate whose LAST leaf is the one that fails has no remainder to abort. That
    case is not a scope with an empty set, it is no abort at all, so it is constructed as one."""
    scope: str
    indices: frozenset[int]

    def __post_init__(self) -> None:
        if self.scope and not self.indices:
            raise ValueError("an Abort that skips no step must not name a scope")

    @property
    def reason(self) -> str:
        """The one line a runner shows beside a step it is not going to run."""
        return f"{self.scope} stopped on a failure" if self.scope else "a previous step failed"


_NOTHING_ABORTED = Abort(scope="", indices=frozenset())


def _chain_to(node: "PlanNode", target: "PlanNode") -> tuple["PlanNode", ...]:
    """The nodes from `node` down to `target` inclusive, or () when `target` is not in that subtree.

    Matched by IDENTITY, not equality: PlanNode is a NamedTuple and therefore compares by value, so two
    structurally identical leaves would be indistinguishable by `==`. The tree and the leaves come from one
    traversal, so the objects are the same objects."""
    if node is target:
        return (node,)
    for child in node.children:
        found = _chain_to(child, target)
        if found:
            return (node,) + found
    return ()


def abort_after(pipeline: Pipeline, failed: int) -> Abort:
    """Which of the remaining steps a failure at step `failed` skips - the ONE place both runners ask
    (netctl#1317). `stop_on_failure` is declared per command, so it is a property of the SUBTREE that
    declares it, not of the run.

    With a usable tree the scope is the OUTERMOST ancestor of the failed leaf whose flag is TRUE, and the
    skip set is that node's remaining leaves. The reason it is the outermost and not the nearest: the
    nearest one aborts its own subtree, that abort is itself a failure its parent sees, and each further
    ancestor then decides by its own flag whether to carry on with its siblings. A `false` ancestor
    declines to stop for a failure; it does not absorb it. An explicit `false` is therefore
    indistinguishable from an unset flag and cannot shield its subtree from an outer `true` - the manifest
    has no way to say "stop here but no further", and this change does not add one.

    The failed leaf itself is part of the chain, so a `true` on a LEAF would scope to a subtree of one and
    abort nothing. `load()` rejects it there for exactly that reason, the same stance it takes on
    `keep_awake` and `hidden`.

    The behaviour restored here is the PRE-aggregate one: a failing `up` aborts its own phases and the
    `test all` around it carries on to the next gate.

    LIMITATION (netctl#1317): `plan_tree_for` is a DFS SPANNING tree, so a dependency reached along several
    paths is planned at its FIRST occurrence only. A flagged aggregate that declared such a dependency but
    lost it to an earlier sibling is not on that leaf's chain, and therefore does not stop for its own
    dependency's failure. Fixing that here would mean changing what a plan tree is, not what this function
    reads, so the sharpest edge of it is GUARDED at load time instead (netctl#1319): `load()` rule 6
    rejects a manifest in which two aggregates ONE plan reaches DIRECTLY declare the same dependency and
    disagree on `stop_on_failure`. The limitation is narrowed by that, not removed - two shapes still reach
    this function, and both are the declaration-graph scoping's job:
      - declarers that AGREE. The dependency is still planned under one of them only, so the abort scope
        comes out as that carrier's, which can be narrower than the loser asked for.
      - a flagged ANCESTOR of a declarer. Rule 6 compares each declarer's OWN flag, never its effective
        policy, so two unflagged declarers pass the guard while one of them sits under a `true` - and that
        ancestor then does not stop for the failure of a dependency its own subtree declared. This is
        netctl#1319's opening shape one level up, and it is documented, not endorsed.
    The full cure - scoping the abort by the DECLARATION graph rather than by tree ancestry - stays open,
    and closes both.

    WITHOUT a usable tree, the pipeline's single `stop_on_failure` decides for the whole run, exactly as
    before: `doctor` and the other hand-built pipelines have no tree at all, and a tree whose leaf-to-step
    pairing the kernel cannot verify must not be trusted with an execution decision either. The verdict
    comes from `Pipeline.usable_tree`, the same one `build_rows` reads and the place that warns when it is
    negative: a degraded display and a degraded stop-scope have one cause, and a display-level degrade must
    never silently change EXECUTION semantics."""
    steps = pipeline.steps
    tree = pipeline.usable_tree()
    if tree is None:
        return (Abort(scope="", indices=frozenset(range(failed + 1, len(steps))))
                if pipeline.stop_on_failure else _NOTHING_ABORTED)
    leaves = tree.leaves()
    scope = next((node for node in _chain_to(tree, leaves[failed]) if node.spec.stop_on_failure), None)
    if scope is None:
        return _NOTHING_ABORTED
    within = {id(leaf) for leaf in scope.leaves()}
    indices = frozenset(index for index in range(failed + 1, len(leaves)) if id(leaves[index]) in within)
    # A flagged node whose LAST leaf failed has no remainder: nothing is aborted, so nothing names a scope.
    return Abort(scope=scope.path or scope.name, indices=indices) if indices else _NOTHING_ABORTED


def build_rows(pipeline: Pipeline) -> Row:
    """The display tree for a pipeline (netctl#1276). One rule for every pipeline: the ROOT row is the
    invoked command, and the children are either planned commands (dotted paths) or, for a pipeline built
    by hand, that command's internal probes (prose labels).

    With a usable `pipeline.tree`, the structure is the plan's own and each planned leaf carries the Step
    built for it, relying on the contract `Pipeline.tree` states: `steps[i]` is the step for
    `tree.leaves()[i]`. Nothing types that contract, so `Pipeline.usable_tree` checks as much of it as the
    kernel can see - once, for this renderer and for `abort_after` alike - and the renderer drops to the
    flat shape when the check fails. A display defect must not silently relabel results, and it must not
    abort a running pipeline either.

    Without a usable tree (`doctor`, `up` - both built by hand), the root is `pipeline.root_path` and the
    steps hang off it flat. The bare `pipeline.name` is only the last resort for a pipeline that set no
    path at all: falling back to it whenever a tree is missing would reintroduce the second vocabulary this
    change exists to remove."""
    tree = pipeline.usable_tree()
    if tree is not None:
        step_of = {id(leaf): step for leaf, step in zip(tree.leaves(), pipeline.steps)}
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
    # Step index -> why it will not run. A set of doomed indices rather than a `stopped` latch, because a
    # failure now aborts a SUBTREE and not necessarily the tail of the run (netctl#1317): the steps after an
    # aborted subtree may well be its siblings, which still run. The first abort that claims an index owns
    # the reason printed for it.
    aborted: dict[int, str] = {}
    for index, step in enumerate(pipeline.steps):
        title = step.command or step.label      # exact-command identity when the step carries one (#897)
        if index in aborted:
            step.state = StepState.SKIPPED
            skipped += 1
            log.warn(f"{title} - skipped ({aborted[index]})")
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
            abort = abort_after(pipeline, index)
            for doomed in abort.indices:
                aborted.setdefault(doomed, abort.reason)
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
