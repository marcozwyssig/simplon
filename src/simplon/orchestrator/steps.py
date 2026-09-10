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
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

from simplon import log
from simplon import steplog
from simplon.run import run_stream

if TYPE_CHECKING:   # type-only: the step model is the LOWEST layer and must not import the manifest
    from simplon.orchestrator.manifest import PlanNode

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


#: The clock `Step.run` measures with, as a module attribute rather than a bare `time.perf_counter()`
#: call - so a test can freeze it (#68). What those tests assert on is the FORMAT of a duration, not how
#: fast this machine happened to be, and a wall clock inside an assertion turns machine load into a
#: verdict: `format_duration` prints `<0.1s` below 0.05s, so a step doing nothing at all printed `0.1s`
#: whenever the box was busy. Measured three times red, twice of them while verifying an unrelated merge.
#: Production never rebinds this; it exists so a test can state the elapsed time it means.
clock: Callable[[], float] = time.perf_counter


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
    # The command's own one-line summary from the manifest, where the step was built for a planned
    # command; "" for a hand-built probe, whose prose `label` already is its description. Shown when a
    # step is ENTERED and nowhere else (#49): the manifest makes `help` mandatory on every command and it
    # was reaching no runner at all, so a reader saw `build.reference` and had to look the name up. Not
    # in the retraced tree - one help text per row would turn a column into a paragraph, and the tree's
    # job is the shape, not the prose.
    help: str = ""
    state: StepState = StepState.PENDING
    output: str = ""
    # The segments this step has produced SO FAR: THE SAME LIST the streaming action collects into,
    # handed over by reference when the Step is built (see `argv_step`). Not a copy kept beside it for
    # the pane, which is what si#144 rules out - a copy is a second in-memory version of the step log,
    # and it goes stale the moment the action appends to its own.
    #
    # A hand-built `stream=` action that is not handed its list leaves this empty, and the pane then
    # says `(running…)` exactly as it did before - a degradation, not a wrong answer. Recording inside
    # `Step.run` instead, by wrapping the `Emit`, was built and rolled back: it makes `argv_step`'s
    # action correct only when it is reached through `run`, and calling it directly - which two of this
    # kernel's own tests do - then writes an EMPTY step log and says nothing.
    #
    # It exists because `Outcome.output` is only built after the action RETURNS (si#144, mechanism A): a
    # row highlighted while its step was running showed `(running…)` however much the step had printed,
    # and the lines that went by while another row was selected were gone. si#148's follow mode moved
    # the cursor to the running step, which covers the operator who touches nothing and leaves this
    # exactly as it was for the operator who navigates.
    #
    # The alternative si#144 names is to write `steplog` incrementally and let the pane tail the file.
    # Rejected: `steplog.write` returns None with no product context registered and on an unwritable
    # checkout, so the backlog would be missing in exactly the degraded cases - and the pane would take
    # file I/O into its render path to get it. An `action` step fills this with nothing, which is the
    # truth: it captures rather than streams, and has no output before it returns.
    live: list[str] = field(default_factory=list)
    rc: int | None = None
    # When this step was entered and when it was left, on the MONOTONIC clock (#52). Wall time, because
    # wall time is what an operator waits through and what the tools themselves report - `collected
    # modules in 31966 ms`. CPU time would be more precise and useless for this question: a step that
    # spends 32 of its 46 seconds downloading a theme module (#52's evidence, on a cold module cache -
    # the same fetch takes 1.6s warm) costs those 32 seconds of an operator's day either way.
    #
    # Both stay None until `run` sets them, and NOTHING else sets them. That is the whole guarantee #52
    # asks for: a step that was SKIPPED or is still PENDING never called `run`, so it has no duration -
    # not `0.0s`, which would claim it finished instantly and is exactly the value this repo hunts, one
    # that cannot tell "nothing to do" from "done and fast".
    started_at: float | None = None
    ended_at: float | None = None

    @property
    def shown_output(self) -> str:
        """What a reader should see: the finished output, or the segments produced so far while it runs.

        `output` wins once it is set, because it is the action's own last word - an action that returns
        different text than it streamed (a summary, a captured stderr) means that text."""
        return self.output or "\n".join(self.live)

    @property
    def duration(self) -> float | None:
        """Seconds from entering this step to leaving it, or None for a step that did not FINISH one -
        never run, still running, or ended by a raise."""
        if self.started_at is None or self.ended_at is None:
            return None
        return self.ended_at - self.started_at

    def __post_init__(self) -> None:
        if (self.action is None) == (self.stream is None):
            raise ValueError("a Step needs exactly one of action / stream")

    def run(self, emit: Emit = _noop) -> Outcome:
        self.state = StepState.RUNNING
        self.started_at = clock()
        if self.stream is not None:
            outcome = self.stream(emit)
        elif self.action is not None:
            outcome = self.action()
        else:
            # `__post_init__` refuses a Step with neither, so this is the invariant restated at the one
            # place that depends on it. It is not dead code: a Step is mutable, so the invariant holds
            # only for a Step nobody has reached into since it was built - and writing it out is what
            # makes `run` total instead of leaving `self.action()` as a call on `Callable | None`.
            raise ValueError("a Step needs exactly one of action / stream")
        # After the action and before the verdict fields: a step that raised leaves `ended_at` unset and
        # therefore carries no duration, which is the truth - it never finished one.
        self.ended_at = clock()
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

        A rejected tree is WARNED about, once, naming what is lost AND why it was rejected: the display
        shape is the smaller half, the stop SCOPE is the safety-relevant one. Dropping every subtree's
        `stop_on_failure` back onto a root that says `false` reinstates exactly the defect netctl#1317
        exists to fix, and it would do so with no signal beyond a tree that came out flat. The concrete
        fault rides along because the warning is the only thing standing between a voided manifest
        declaration and a run that looks normal: a reader who is told which step named what can fix the
        factory, where one told only that "the pairing failed" reads past it (#42)."""
        if self._verified is None:
            fault = _pairing_fault(self.tree.leaves(), self.steps) if self.tree is not None else ""
            self._verified = self.tree is not None and not fault
            if fault:
                stops = "the whole run stops" if self.stop_on_failure else "nothing is skipped"
                log.warn(f"{self.name}: the plan tree does not pair with the steps that will run, so it is "
                         f"not used - the display falls back to a flat list AND every subtree's "
                         f"stop_on_failure is dropped, so a failure now means {stops}; {fault}")
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
    def finished(self) -> bool:
        """True when nothing under this row can still change: every leaf below it has run or been
        skipped. The test a SPAN needs - an aggregate's own start and end are only both known once
        everything inside it is over (#52). A childless aggregate is vacuously finished and has no times,
        so it reports no duration either."""
        if self.step is not None:
            return self.step.state in (StepState.OK, StepState.FAILED, StepState.SKIPPED)
        return all(child.finished for child in self.children)

    @property
    def started_at(self) -> float | None:
        """When work under this row began, or None when none of it did."""
        if self.step is not None:
            return self.step.started_at
        starts = [start for start in (child.started_at for child in self.children) if start is not None]
        return min(starts) if starts else None

    @property
    def ended_at(self) -> float | None:
        """When the last work under this row ended, or None when none of it ran."""
        if self.step is not None:
            return self.step.ended_at
        ends = [end for end in (child.ended_at for child in self.children) if end is not None]
        return max(ends) if ends else None

    @property
    def duration(self) -> float | None:
        """How long this row took, or None - and None is an ANSWER here, not a gap (#52).

        A leaf's duration is its own step's. An aggregate's is its SPAN: from the moment its first child
        started to the moment its last one ended. #52 left the choice open between the span and the SUM of
        the children, and the span wins for three reasons:

        - It is what the operator waited through. The sum is always <= the span, and the difference is
          the gaps BETWEEN the children - a re-entered shim, a venv check, a process spawn per step. A
          number that is smaller than the truth is the misleading direction for a cost figure, and #27
          (46 seconds of doc build on a cold module cache, 32 of them fetching a theme module) is
          precisely a cost somebody had to go looking for.
        - It keeps ONE meaning in one column. A leaf's number is already a span; a sum beside it would be
          a different quantity wearing the same units, and "what does this value mean on the far side of
          the seam" is the question this repo keeps losing to.
        - It cannot invent a zero. A sum over no contributing child is `0.0`, which would put `0.0s` on
          an aggregate whose every leaf was skipped - the exact claim this ticket forbids. A span over no
          observations has no value at all, and says so.

        None, never `0.0s`, for anything that did not run or is not over yet: a step that was SKIPPED or
        is still PENDING never entered `Step.run`, so it has no start; and an aggregate reports nothing
        while a leaf under it can still change the answer.
        """
        if self.step is not None:
            return self.step.duration      # a leaf has ONE duration and the Step owns it
        if not self.finished:
            return None
        start, end = self.started_at, self.ended_at
        return end - start if start is not None and end is not None else None

    def elapsed(self, now: float) -> float | None:
        """How long this row has taken SO FAR, on the same monotonic clock `duration` uses - the live
        value a running row and the status bar need, and the one `duration` deliberately does not give
        (si#148 items 2 and 8).

        `duration` answers None for anything not over, which is the right answer to its own question
        ("how long did this take") and the wrong one to this one ("how long has this been going"). The two
        are kept apart rather than merged because `duration` is what the transcript and `render_tree`
        print, and a number that grows between two reads has no business in a record of a finished run.

        `now` is a PARAMETER and not a `clock()` call, for the reason the `clock` attribute above states:
        a test that watched this tick by sleeping would be slow, flaky, and would prove less than one that
        states the instant it means.

        It never invents a zero, exactly as `duration` does not: a row that has not started has no
        elapsed, because `0.0s` is the one value a reader could mistake for "did not run".
        """
        duration = self.duration
        if duration is not None:
            return duration
        start = self.started_at
        return now - start if start is not None else None

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


def _pairing_fault(leaves: "tuple[PlanNode, ...]", steps: list[Step]) -> str:
    """Why `steps[i]` is not the step built for `leaves[i]`, named concretely - or "" when the pairing
    holds. As much of the `Pipeline.tree` contract as the kernel can check without knowing how a product
    builds its steps.

    Cardinality alone is not the check. Equal counts in the wrong ORDER pair every row with the wrong
    result: a probe that built the steps in reverse leaf order produced a tree blaming `build.install` for
    `deploy.up`'s rc 7 and painting `deploy.up` green, which is worse than no tree at all.

    What the kernel owns is `Step.command`, the exact-command identity. A step built for a planned leaf
    carries that leaf's dotted path (`StepFactoryContext.for_shim` stamps it as `path_by_name` with the
    bare name as its fallback for a name the manifest cannot resolve unambiguously; netctl's own factory
    spells the same thing `manifest_command(name)`), so the pairing is verifiable and BOTH spellings are
    accepted.

    A step that names NOTHING is not verifiable, and since netctl#1317 that is a rejection rather than a
    tolerance. The tolerance was written when this verdict only chose a display shape, where trusting an
    unnamed step costs a mislabelled row; it now also chooses what does NOT RUN, where the same trust
    reversed the steps and skipped `build.image` for a failure inside `deploy.up`, a subtree it is not even
    in. A hand-built step legitimately carries no command - and a hand-built pipeline has no tree, so it
    never reaches this function. On the path that does reach it, an unverifiable pairing must degrade
    (loudly, see `Pipeline.usable_tree`) rather than be trusted.

    The verdict is a REASON rather than a bool because its only consumer is that warning, and a warning
    that says the pairing is wrong without saying WHICH step and which leaf sends its reader into the
    kernel to find out. The three faults read differently to whoever has to fix one: a count mismatch is a
    step list built beside the plan, a step that names nothing is a factory that never stamped an identity
    (#42, the shape the scaffolder shipped), and a mismatched name is the reordering the check exists
    for."""
    if len(leaves) != len(steps):
        return f"step count {len(steps)} does not match the plan's {len(leaves)} leaves"
    for index, (leaf, step) in enumerate(zip(leaves, steps)):
        if step.command not in (leaf.path, leaf.name):
            named = f"names '{step.command}'" if step.command else "names nothing"
            return (f"step {index} ({step.label}) {named}, but the plan's leaf there is "
                    f"'{leaf.path or leaf.name}'")
    return ""


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


# How many TRAILING lines of a failed step's output the summary shows. The last ones, because a tool
# prints its diagnosis immediately before it exits - `Found 3 errors`, the traceback's final frame, the
# compiler's summary. "Meist" is not a rule, which is why the tail is never shown ALONE: #49 settles that
# question as BOTH or NEITHER - the lines AND the path to the whole file, or an explicit sentence saying
# the reason is not known here. A truncated cause on its own is worse than a path, because it reads as
# the whole answer.
FAILURE_TAIL_LINES = 10


def failure_report(pipeline: Pipeline, tail: int = FAILURE_TAIL_LINES) -> list[str]:
    """Why each FAILED step failed, as text lines - empty for a run with no failure (#49).

    The gap this closes: a red run said HOW MANY steps failed and the tree said WHICH, while the reason
    sat in `build/logs/<step>.log` and the run named the DIRECTORY. With three files a reader finds it;
    with twenty steps the reader searches for something the run knew exactly. Nothing here is new
    information - it is the output the step already captured and the file it was already written to.

    Three shapes, and the difference between them is the point:

    - output AND a log file: the last `tail` lines, then the path to the rest. When lines were dropped,
      the count of them is said, so nothing pretends to be the whole.
    - output but no log file: a hand-built `action` step keeps its text in the Outcome and writes
      nothing; the lines are all there is, and the report says so rather than naming a path to nothing.
    - no output at all: the report says the run does not know the reason. An empty block under a failed
      step would read as "nothing was wrong", which is this repo's recurring defect wearing a summary.

    Pure: it returns lines and prints none of them, so both runners can place it where their own output
    wants it and a test can read it without a terminal.
    """
    lines: list[str] = []
    for step in pipeline.steps:
        if step.state != StepState.FAILED:
            continue
        identity = step.command or step.label
        lines.append(f"why {identity} failed (rc {step.rc}):")
        body = step.output.rstrip("\n").splitlines()
        if len(body) > tail:
            lines.append(f"  ... {len(body) - tail} earlier line(s) not shown")
        lines += [f"  {text}" for text in body[-tail:]]
        if not body:
            lines.append("  this step printed nothing, so the run does not know why it failed")
        path = steplog.existing_log(identity)
        if path is not None:
            lines.append(f"  full output: {path}")
        elif body:
            lines.append("  full output: not written to a file - the lines above are all of it")
    return lines


def format_duration(seconds: float) -> str:
    """One row's duration as the narrow text a column can hold (#52): `<0.1s` for the immeasurably
    quick, `2.4s` under a minute, `16m04s` over it. Pure, and the ONE spelling both runners use, so a CI
    log and a TTY read alike.

    `0.0s` is never printed, and that is the point rather than a rounding preference. This column's whole
    contract is that a step which did NOT run carries nothing; a literal zero on a step that did run in
    300 microseconds would be the one string a reader could mistake for that absence. `<0.1s` says
    "measured, and too fast to matter", which is a different sentence from an empty column."""
    if seconds < 0.05:
        return "<0.1s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}m{rest:02d}s"


# --- the bottom bar: what is ACTIVE, and how the run is doing (si#148 items 2 and 8) -------------------
#
# THE ONE THING ON SCREEN THAT FOLLOWS THE PROCESS RATHER THAN THE CURSOR. Both panes of the TUI follow
# the cursor - the tree row is where the operator navigated to, the details pane is that row's output -
# so an operator who navigates away has nothing left that says what is running or how long it has been
# running, which is the question asked immediately before someone presses Ctrl-C. A permanent line
# answers it once and keeps answering it while the operator reads something else.
#
# PURE, over the DISPLAY tree plus an injected `now`. Over the display tree because that is where the
# identity a reader scans for lives - `_label`'s dotted path, never the argv - and because the derived
# aggregate state is already computed there. With an injected `now` because the value has to travel
# `started_at -> Row.elapsed -> format_duration -> the text` and a test that stated no instant could only
# assert that path by sleeping.
#
# The separator is wide on purpose: three groups of numbers on one line need to be separable at a glance
# by an operator who is WATCHING rather than reading. Posting's status bar is denser because its user is
# composing something; density that helps an editor hides a state change in a monitor.
_BAR = "  ·  "

#: How many running steps the bar NAMES before it summarises the rest. Execution is sequential today, so
#: this is one name in practice - but si#147 is an open ticket for a parallel executor with a join, and a
#: line that could render only one name would have to be rebuilt for it. Nothing here supports parallel
#: execution; what it does is refuse a shape that would have to be thrown away. Two, because the bar is
#: ONE line and a fan-out of eight has to stay one line.
NAMED_RUNNING = 2


@dataclass(frozen=True)
class RunSummary:
    """How a run is doing, counted over the LEAVES of the display tree - the aggregates are derived and
    counting them would count the same work several times."""

    ok: int = 0
    failed: int = 0
    skipped: int = 0
    running: int = 0
    pending: int = 0
    total: int = 0

    @property
    def finished(self) -> bool:
        """True when nothing can still change: every leaf has run or been skipped. A run with no steps at
        all is finished and did not pass, which is the distinction `passed` keeps."""
        return self.total > 0 and self.ok + self.failed + self.skipped == self.total

    @property
    def passed(self) -> bool:
        """True only for a finished run in which every leaf is OK. An empty run passed NOTHING, and
        calling that green is the defect this repo keeps hunting."""
        return self.finished and self.ok == self.total

    @property
    def counts(self) -> str:
        """The categories that have a member, and only those. A bar reading `0 ok · 0 failed · 0 skipped ·
        0 running · 3 pending` spends four fifths of its width on nothing having happened, and the
        operator then has to read it to find out that nothing has."""
        parts = [f"{count} {name}" for count, name in
                 ((self.ok, "ok"), (self.failed, "failed"), (self.skipped, "skipped"),
                  (self.running, "running"), (self.pending, "pending")) if count]
        return " · ".join(parts) if parts else "no steps"


def leaf_rows(root: Row) -> tuple[Row, ...]:
    """Every EXECUTABLE row under `root`, in display order - the rows that carry a step and therefore an
    rc of their own."""
    if root.step is not None:
        return (root,)
    return tuple(leaf for child in root.children for leaf in leaf_rows(child))


def summarise(root: Row) -> RunSummary:
    """Count the display tree's leaves by state. Pure."""
    states = [leaf.state for leaf in leaf_rows(root)]
    return RunSummary(ok=states.count(StepState.OK), failed=states.count(StepState.FAILED),
                      skipped=states.count(StepState.SKIPPED), running=states.count(StepState.RUNNING),
                      pending=states.count(StepState.PENDING), total=len(states))


def running_rows(root: Row) -> tuple[Row, ...]:
    """The leaves that are RUNNING right now, in display order. A TUPLE rather than an optional single
    row: see NAMED_RUNNING for why the plural is the shape even while execution is sequential."""
    return tuple(leaf for leaf in leaf_rows(root) if leaf.state == StepState.RUNNING)


def run_elapsed(root: Row, now: float) -> float | None:
    """How long the RUN has been going, or None before anything started - the root row's own elapsed, so
    a finished run stops at its last step instead of following the wall clock into the operator's reading
    time."""
    return root.elapsed(now)


def _active_text(rows: tuple[Row, ...], now: float) -> str:
    """The left half while something is running: up to NAMED_RUNNING identities, then how many more, then
    the elapsed of the one that has been going longest."""
    named = ", ".join(row.label for row in rows[:NAMED_RUNNING])
    tail = f" +{len(rows) - NAMED_RUNNING} more" if len(rows) > NAMED_RUNNING else ""
    elapsed = max((value for value in (row.elapsed(now) for row in rows) if value is not None),
                  default=None)
    # The ellipsis is one character and it is the difference between `12.0s` on a row that finished in
    # twelve seconds and `12.0s…` on one that has been going for twelve and may go for sixty more.
    shown = f"  {format_duration(elapsed)}…" if elapsed is not None else ""
    return f"{STATE_ICON[StepState.RUNNING]} {named}{tail}{shown}"


def _last_finished(root: Row) -> Row | None:
    """The leaf that ended most recently, for the window in which nothing is running and the run is not
    over. Narrow but real: an aborted subtree is marked SKIPPED one step at a time with a repaint between
    each, and during that stretch no step is RUNNING."""
    ended = [leaf for leaf in leaf_rows(root) if leaf.ended_at is not None]
    return max(ended, key=lambda row: row.ended_at or 0.0) if ended else None


def _verdict_text(summary: RunSummary) -> str:
    """What a finished run's bar says - the verdict, because it is the last thing an operator reads before
    pressing q, and because the details pane it was reading is gone the moment the app exits."""
    if summary.passed:
        return f"{STATE_ICON[StepState.OK]} all {summary.total} steps passed"
    if summary.total == 0:
        return "nothing ran"
    tail = f", {summary.skipped} skipped" if summary.skipped else ""
    return f"{STATE_ICON[StepState.FAILED]} {summary.failed} of {summary.total} steps failed{tail}"


def status_line(root: Row, now: float) -> str:
    """The bottom bar's whole text: what is active right now, how the run is doing, and how long it has
    been going. Pure; plain text, so nothing here can leak markup into a log.

    FOUR STATES AND NONE OF THEM IS BLANK. A bar that empties reads as a broken widget, and three of the
    four are easy to leave empty by accident:

      - nothing has started - `waiting to start`. One frame in practice, because `on_mount` paints before
        the worker thread has entered the first step, but the frame exists and it is the first thing an
        operator sees.
      - something is running - the identity, the elapsed, the counts, the run's own clock.
      - nothing is running and the run is not over - the step that finished LAST, marked as such. See
        `_last_finished` for when this window occurs.
      - the run is over - the verdict.
    """
    summary = summarise(root)
    elapsed = run_elapsed(root, now)
    clock_text = f"{_BAR}run {format_duration(elapsed)}" if elapsed is not None else ""
    running = running_rows(root)
    if running:
        return f"{_active_text(running, now)}{_BAR}{summary.counts}{clock_text}"
    if summary.finished:
        return f"{_verdict_text(summary)}{clock_text}"
    last = _last_finished(root)
    if last is not None:
        duration = last.duration
        shown = f"  {format_duration(duration)}" if duration is not None else ""
        head = f"last: {STATE_ICON[last.state]} {last.label}{shown}"
        return f"{head}{_BAR}{summary.counts}{clock_text}"
    return f"waiting to start{_BAR}{summary.counts}"


def step_header(step: Step) -> str:
    """One step's identity line: its EXACT command, plus the command's own help text when the manifest
    gave it one (#49). The dotted path is what a reader SCANS for; this is what makes a pasted excerpt
    reproducible, which is why it appears where a step is entered and in the transcript, and never on a
    tree row.

    Pure, and shared: the TUI's details pane and the run transcript render the identical line. It sits in
    this module rather than in the TUI because the transcript is written on the HEADLESS path too, and a
    second spelling of the same sentence is how two artefacts of one run come to disagree.
    """
    identity = step.command or step.label
    return f"$ {identity} - {step.help}" if step.help else f"$ {identity}"


def transcript(pipeline: Pipeline, header: Sequence[str]) -> list[str]:
    """The WHOLE run as text lines: every step in the order it ran, each with its exact command, its rc
    and its duration, then why each failure failed, then the verdict (si#148 item 3).

    THE GAP IT CLOSES. `steplog.write` keeps what one step printed and `failure_report` prints the
    failures once the app has exited. Neither is the artefact somebody attaches to a ticket, and a nicer
    pane cannot become one: a pane is gone when the app is.

    IN EXECUTION ORDER, not as a tree. `render_tree` already draws the shape and both runners show it;
    what it cannot show is the ORDER, which is the half a reader reconstructing an incident needs - and
    the order is `pipeline.steps`, which is what actually ran.

    IT REUSES RATHER THAN RESTATES. `step_header` is the pane's own line, `failure_report` is the block
    both runners already print (tail plus the path to the whole file, or the sentence saying the run does
    not know), and the verdict is the status bar's. Composing them is the work; a second rendering of any
    of them would be a second answer to a question that has one.

    NO OUTPUT BODIES. The full text of every step is already on disk one file per step, and inlining it
    here would produce a transcript nobody opens for a build that prints 40 000 lines. What a failure
    contributes is `failure_report`'s tail AND the path to the rest - #49's both-or-neither rule.

    Pure: it returns lines and prints none of them, and it is plain text throughout, so nothing here can
    put markup or an escape into a file a reader attaches to a ticket (si#144's warning about a pty,
    applied to the artefact rather than to the stream).
    """
    lines = list(header)
    if lines:
        lines.append("")
    for step in pipeline.steps:
        identity = step.command or step.label
        icon = STATE_ICON[step.state]
        if step.state == StepState.SKIPPED:
            lines.append(f"{icon} {identity}  (skipped: {_skip_note(pipeline, step)})")
        elif step.rc is None:
            # Never entered `Step.run` and was not skipped either: the run stopped before it, which is
            # what a transcript of a TUI run the operator quit half way through has to be able to say.
            lines.append(f"{icon} {identity}  ({step.state.value})")
        else:
            duration = step.duration
            shown = f"  {format_duration(duration)}" if duration is not None else ""
            lines.append(f"{icon} {identity}  rc {step.rc}{shown}")
        lines.append(f"    {step_header(step)}")
    failures = failure_report(pipeline)
    if failures:
        lines += [""] + failures
    lines += ["", f"verdict: {_verdict_text(summarise(build_rows(pipeline)))}"]
    return lines


def _skip_note(pipeline: Pipeline, skipped: Step) -> str:
    """Which subtree declined to run `skipped`, in the words `Abort.reason` uses - the same content the
    TUI's pane and the headless runner already show beside a `⊘`, recomputed here rather than carried,
    because a Step does not hold it and the transcript is written after the fact.

    It asks the FIRST failure whose abort claims this step. Later failures may claim it too; the first
    one is the one that decided, exactly as both runners' `setdefault` records it.
    """
    index = next((i for i, step in enumerate(pipeline.steps) if step is skipped), None)
    if index is None:
        return "a previous step failed"
    for i, step in enumerate(pipeline.steps[:index]):
        if step.state == StepState.FAILED:
            abort = abort_after(pipeline, i)
            if index in abort.indices:
                return abort.reason
    return "a previous step failed"


def write_run_transcript(pipeline: Pipeline, started: datetime) -> Path | None:
    """Write the run transcript beside the per-step logs; returns the path, or None when there was
    nowhere to put it.

    CALLED ON BOTH PATHS, and that is a decision rather than an oversight. The run that most needs to be
    attachable to a ticket is a red CI run, which is exactly the headless path - a transcript written
    only under the TUI would exist only on the machine where the operator could already read the screen.
    It costs a CI run one file under `build/`, which `clean` removes, and it degrades to nothing when no
    product context is registered, the way `steplog.write` already does.

    The TUI's caller writes it AFTER `App.run()` returns rather than from `_on_done`, so a run the
    operator quit half way through still leaves a record of what did happen. That is why the body above
    has a branch for a step that was neither run nor skipped.

    THE GUARD IS ROUND THE WHOLE COMPOSITION, not just the file write, and one frame's difference is the
    entire point. `steplog.write_run` catches `OSError` because that is the only thing WRITING can raise;
    everything before it - `run_header`, and `transcript` with its `STATE_ICON` lookups, its `abort_after`
    traversal and its `failure_report` - is rendering, and a rendering fault there propagates out of
    `run_headless` and `run_pipeline`. It would then take the process down BEFORE the exit code is
    returned and before the failure summary is printed, on exactly the red run this artefact exists for:
    a file meant to explain a failure would instead replace the explanation with its own traceback.
    A courtesy that raises is a defect, and the courtesy is the whole call, not its last line.

    The cost is stated rather than hidden: a bug in the rendering leaves no transcript, and says so once
    where an unguarded version would announce it loudly. That is the same trade `steplog.write` already
    makes, and it goes the same way - the RUN's verdict is what a caller came for.
    """
    try:
        text = "\n".join(transcript(pipeline, steplog.run_header(pipeline.name, started)))
    except Exception as exc:  # noqa: BLE001 - see the paragraph above; nothing here may cost a run
        log.warn(f"{pipeline.name}: the run transcript could not be composed ({exc})")
        return None
    return steplog.write_run(text)


def render_tree(root: Row, indent: str = "  ") -> list[str]:
    """The display tree as text lines, one per row, indented by depth - what `run_headless` prints so a CI
    log shows the structure the TUI draws.

    Since #52 a row that RAN carries its duration in a right-hand column, padded to one width so the
    numbers line up and can be scanned. A COLUMN and not a paragraph: the run gains no line, green or red.
    A row that did not run carries nothing there, and no trailing blank either - `⊘ deploy.up` ends where
    the name ends, because the absence is the statement."""
    rows: list[tuple[str, str]] = []

    def walk(row: Row, depth: int) -> None:
        duration = row.duration
        rows.append((f"{indent * depth}{STATE_ICON[row.state]} {row.label}",
                     format_duration(duration) if duration is not None else ""))
        for child in row.children:
            walk(child, depth + 1)

    walk(root, 0)
    width = max((len(text) for text, shown in rows if shown), default=0)
    return [f"{text:<{width}}  {shown}" if shown else text for text, shown in rows]


def argv_step(label: str, argv: list[str], command: str | None = None, help: str = "") -> Step:
    """A STREAMING Step that runs an arbitrary command and feeds its output live into the details pane.
    The build pipeline uses it to render each image build (a docker build/run) as its own step.
    `command` is the step's exact-command identity for the section header; it defaults to the real argv
    (shlex-joined), so a native docker/argv step displays the command it actually runs.

    THE OUTPUT IS ALSO WRITTEN TO A FILE (simplon.steplog), on every run and whatever the rc: the TUI
    that shows these lines is a Textual app, and Textual holds the mouse, so what is on screen cannot be
    selected or copied out of it. Writing on success only would hand back a log for every run except
    the interesting one."""
    identity = command if command is not None else shlex.join(argv)

    # The collector, built HERE rather than inside `stream`, so the Step below can be handed the SAME
    # list and a pane can read what this step has produced while it is still producing it (si#144).
    lines: list[str] = []

    def stream(emit: Emit) -> Outcome:
        lines.clear()      # a Step can be run twice; the pane must not show the previous run's output

        def on_line(line: str) -> None:
            lines.append(line)
            emit(line)

        rc = run_stream(argv, on_line)
        output = "\n".join(lines)
        steplog.write(identity, output)
        return Outcome(rc=rc, output=output)
    return Step(label=label, stream=stream, live=lines, command=identity, help=help)


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
    run, and the plan itself is already implied by the per-step lines above it.

    A RED run then adds `failure_report` between that tree and the verdict line (#49): the tree says which
    steps failed, the report says why each of them did, and the count stays last. A green run adds
    nothing - the normal case must not pay for the exceptional one, which is #49's own acceptance.

    It also leaves a RUN TRANSCRIPT behind (si#148 item 3), and headless is not the afterthought path for
    it: the run that most needs to be attachable to a ticket is a red CI run, and this is the runner CI
    uses. See `write_run_transcript`."""
    started = datetime.now()
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
        # The help text rides on the ENTRY line, not on a line of its own and not in the retraced tree
        # (#49): a green run keeps exactly the lines it had, one of them wider. `build.reference` alone
        # made a reader look the command up in the manifest to learn what it was about to do.
        log.info(f"{title} - {step.help}" if step.help else title)
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
        # The reasons go BETWEEN the tree and the verdict: the tree says which steps failed, this says
        # why each of them did, and the count stays the last line so the verdict is where it has always
        # been. A green run reaches none of this (#49).
        for line in failure_report(pipeline):
            print(line, flush=True)
    # ONE call for both outcomes: what goes into the transcript does not depend on the verdict, and the
    # verdict lines below are the last thing a reader sees either way.
    write_run_transcript(pipeline, started)
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
        from simplon.orchestrator.tui import run_pipeline
        return run_pipeline(pipeline)
    except ImportError:
        return run_headless(pipeline)


def overall_rc(pipeline: Pipeline) -> int:
    """0 iff every step is OK, else 1 - the authoritative verdict for both runners."""
    return 0 if all(s.state == StepState.OK for s in pipeline.steps) else 1
