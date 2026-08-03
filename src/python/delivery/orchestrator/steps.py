"""A small step-pipeline abstraction: the backbone the TUI renders and the headless fallback prints.

A Pipeline is an ordered list of Steps; each Step has a label and an `action` that returns an Outcome
(the REAL subprocess exit code + its captured output). Keeping the action injectable makes the runner
logic - state transitions, overall pass/fail = worst step's rc - unit-testable with fake steps, and is
the seam product pipelines plug into. The Textual UI (tui.py) and the headless runner here consume the
SAME Pipeline, so step pass/fail always reflects the real rc, never the UI state (#102).
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from delivery import log
from delivery.run import run_stream

# A sink for a step's live output lines (the TUI appends to a RichLog; headless prints them).
Emit = Callable[[str], None]


def _noop(_line: str) -> None:
    pass


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"   # not run: a previous step failed in a stop_on_failure pipeline (e.g. build)


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


def run_headless(pipeline: Pipeline) -> int:
    """Run every step sequentially, printing the same info/ok/warn lines the rest of netctl uses (and a
    streaming step's lines live, indented), and return the overall exit code (0 iff every step passed).
    This is the TTY-fallback / CI path - no Textual. The overall result is the worst step's rc, never
    derived from any UI state."""
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
        if outcome.ok:
            log.ok(title)
        else:
            failures += 1
            log.warn(f"{title} - failed (rc {outcome.rc})")
            if pipeline.stop_on_failure:
                stopped = True
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
