"""A small step-pipeline abstraction: the backbone the TUI renders and the headless fallback prints.

A Pipeline is an ordered list of Steps; each Step has a label and an `action` that returns an Outcome
(the REAL subprocess exit code + its captured output). Keeping the action injectable makes the runner
logic - state transitions, overall pass/fail = worst step's rc - unit-testable with fake steps, and is
the seam product pipelines plug into. The Textual UI (tui.py) and the headless runner here consume the
SAME Pipeline, so step pass/fail always reflects the real rc, never the UI state (#102).
"""
from __future__ import annotations

import contextlib
import os
import re
import shlex
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator, Mapping, Sequence, TextIO

from simplon import log
from simplon import steplog
from simplon.run import LINE_BREAK, run_stream

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
#
# RUNNING IS NOT A TRIANGLE, AND THAT IS THE POINT (si#162). It was `▶` until a screenshot of a real
# Packer build showed `├── ▶ ▶ win2019   13m51s…` - because `Tree.ICON_NODE` is `▶ ` and
# `ICON_NODE_EXPANDED` is `▼ `, so every running row that had children rendered two identical arrows with
# two unrelated meanings, and the collision fell exactly on the rows carrying work.
#
# The alphabet a Textual `Tree` draws on its own account was read out of the pinned 8.2.8 rather than
# guessed: the two node icons above, plus `Tree.LINES` - `│ └─ ├─` by default, `┃ ┗━ ┣━` under a bold
# row style and `║ ╚═ ╠═` under a double one. The bold variant is reachable here, because `_state_styles`
# renders a FAILED row bold. Rendering the pane at 100, 40 and 24 columns changed none of it: a narrow
# terminal truncates the labels and keeps the same guides. `↻` is in neither set, and neither are the
# other four - `·`, `✓`, `✗` and `⊘` were checked against the same list rather than assumed.
#
# STATIC, DELIBERATELY. A spinner would read better in the tree and be wrong in the two places this table
# is ALSO rendered - `render_tree`'s headless rows and si#148's `build/logs/run-transcript.log`, where a
# frame of an animation is a character somebody has to explain. One glyph, every renderer.
#
# It is also one cell narrower than what it replaces, which is a bonus rather than the reason: `▶` and
# `·` are East_Asian_Width AMBIGUOUS and render double-wide in a CJK locale, while `↻` is Neutral.
STATE_ICON = {
    StepState.PENDING: "·",
    StepState.RUNNING: "↻",
    StepState.OK: "✓",
    StepState.FAILED: "✗",
    StepState.SKIPPED: "⊘",
}


# THE SAME VOCABULARY IN ASCII, for a stream that cannot carry the one above (si#161). On Windows a
# non-console stdout defaults to the legacy code page, and four of those five glyphs have no cp1252
# encoding at all, so the headless runner raised `UnicodeEncodeError` out of its tree print. Measured
# with `io.TextIOWrapper(io.BytesIO(), encoding="cp1252")`, which is the same object type `sys.stdout`
# is there: `'charmap' codec can't encode character '\u2717' in position 0`, raised from the `print` in
# `run_headless`'s tree loop AFTER every step had run and the exit code was already decided. A green
# pipeline came out of CI as a traceback and a non-zero exit, on exactly the path a CI runner and a
# piped run take.
#
# EVERY SPELLING STILL NAMES ITS STATE, and that is the requirement `errors="replace"` fails: `?` says a
# character was lost, not which state the row is in, and a verdict that reads `?` is worse than the
# crash, because the crash is at least visible. Each value below is a PREFIX of the matching
# `StepState.value`, which is the property the test asserts - "it is ASCII" would be satisfied by `+`
# and `-` too, and neither of those says anything to a reader.
#
# THE WHOLE TABLE DEGRADES TOGETHER even though `·` alone survives cp1252 (0xB7). One run must not mix
# two alphabets, or a reader of that log has to work out which rows were rendered in which.
STATE_ICON_ASCII = {
    StepState.PENDING: "pend",
    StepState.RUNNING: "run",
    StepState.OK: "ok",
    StepState.FAILED: "fail",
    StepState.SKIPPED: "skip",
}


def icons_for(stream: TextIO) -> Mapping[StepState, str]:
    """The state alphabet `stream` can actually carry: `STATE_ICON`, or its ASCII twin when the stream's
    encoding cannot encode the glyphs (si#161).

    THE DECISION LIVES HERE rather than in the table or in the streams. Two alternatives were rejected:
    reconfiguring `sys.stdout` to UTF-8 at startup changes the encoding of a stream the kernel did not
    open, for every other writer to it - the product's own prints, `log.info`, anything a library does -
    to fix one runner's five characters; and flattening `STATE_ICON` itself to ASCII would take the
    glyphs away from every terminal that can draw them, which si#148 and si#162 spent their whole
    argument on.

    ASKED ONCE PER RUN, not once per printed line. `render_tree` emits one line per row and the answer
    cannot change between them, so the runner asks once and hands the table down.

    A stream with no `encoding` at all (a `StringIO`, a test double) keeps the glyphs: it takes `str` and
    cannot raise on one, and guessing ASCII there would degrade callers that never had the problem.

    It ignores the stream's ERROR HANDLER on purpose. A stream opened with `errors="replace"` does not
    raise, it prints `?` - and si#161 rules that worse than the crash, so the question asked here is what
    the encoding can CARRY, not what the stream would do about what it cannot.
    """
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return STATE_ICON
    try:
        "".join(STATE_ICON.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        # LookupError rides along because an encoding NAME nothing can resolve is the same situation from
        # the runner's side: the glyphs will not reach the reader, and a verdict must not be the thing
        # that raises.
        return STATE_ICON_ASCII
    return STATE_ICON


@dataclass(frozen=True)
class Outcome:
    """What a step's action returns: the real exit code and the combined output to show in details."""
    rc: int
    output: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


# --- a step that BLEW UP rather than failed (si#182) ---------------------------------------------------
#
# WHAT A RAISE MEANS, decided rather than discovered. A step whose `action` or `stream` raised never
# answered: it has no exit code of its own, because the thing that would have produced one did not get
# that far. That is a different sentence from "it ran and said no", and si#182 asks which of the two the
# kernel is going to tell.
#
# THE ANSWER IS ALREADY IN THIS REPOSITORY, in `simplon.verdict`'s module docstring, which argued the
# same question for the neighbouring case (a gate whose SETUP fell over rather than whose probe went
# red) and rejected both of si#182's own candidates:
#
#   - NOT A RESERVED rc. "An rc is one bit of judgement: zero or not." A reserved number pushes a second
#     distinction through the one channel every caller already interprets as `if rc: fail`, so CI, a
#     shell and `simplon.cli._rc` would each have to learn a private convention in order not to mistake
#     a crash for something else. The rc here is therefore 1 - red, exactly as red as it has always been
#     and carrying no new claim.
#   - NOT A SIXTH `StepState`. `SKIPPED` already holds the neighbouring meaning (did not run because a
#     failure aborted its subtree), and a crashed step is not that: it was entered, it did work, and it
#     did not pass. FAILED IS ITS FATE and it should stay FAILED. A sixth state would also cost an entry
#     in `STATE_ICON`, in `STATE_ICON_ASCII` (both alphabets degrade together, si#161) and a new case in
#     `Row.state`, `Row.finished`, `RunSummary`, `_verdict_text`, `failure_report`, `_skip_note`,
#     `abort_after` and the TUI's row styles - measured at eleven places over three files, every one of
#     them a chance for the five-state renderers a product ships to meet a state they do not map.
#
# SO THE DISTINCTION LIVES IN WHAT GETS WRITTEN, which is the third thing `verdict.py` says: `Step.crash`
# below holds the traceback, `failure_report` says "crashed" instead of "failed (rc 1)", the transcript
# says so too, and `steplog` keeps the whole of it in a file the report names. Nothing is swallowed - the
# exception is not re-raised, and it is also not lost: it is live on the log as it happens, in the pane,
# in the per-step file and in the run transcript, which is four more places than today's traceback on
# stderr followed by a dead run.
#
# THE rc THIS RETURNS IS 1 AND IT IS DELIBERATELY INDISTINGUISHABLE from an ordinary red step's, because
# distinguishing it is not the rc's job. `overall_rc` is unchanged, `abort_after` scopes the crash exactly
# as it scopes a failure, and `stop_on_failure: false` keeps meaning what it says - which si#174 depends
# on, since one body raising must not take the rest of a pipeline down.
CRASH_RC = 1


def crash_text(exc: BaseException) -> str:
    """The record a raise leaves: the whole traceback, then one sentence saying it is a crash.

    THE SENTENCE GOES LAST, and that is the only interesting thing about this function. `failure_report`
    shows a step's LAST `FAILURE_TAIL_LINES` lines, so a header at the top of a forty-frame traceback is
    the first thing cut - and what a reader would then see is an unannotated stack in a block labelled
    like every other failure. Put last, it is inside the tail whatever the traceback's length, and it
    sits directly under the exception line, which is the pairing a reader wants.
    """
    return ("".join(traceback.format_exception(exc)).rstrip("\n")
            + "\n\nthis step raised, so it never returned an exit code of its own; simplon recorded it "
              "as a failed step and the run went on to its end")


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
    # TWO THREADS TOUCH IT AND THERE IS NO LOCK, which the alias makes worth stating. The runner thread
    # appends (the TUI runs `_run_steps` under `@work(thread=True)`); the UI thread reads, on ordinary
    # cursor movement that is not synchronised with the runner at all. It is safe under CPython for a
    # reason and not by luck: `list.append` is one bytecode, and `str.join` over a list of `str` runs to
    # completion without releasing the GIL, so a reader sees a PREFIX of the output and never a torn
    # list. A free-threaded build is what would end that, and it is what to revisit here.
    #
    # The alternative si#144 names is to write `steplog` incrementally and let the pane tail the file.
    # Rejected: `steplog.write` returns None with no product context registered and on an unwritable
    # checkout, so the backlog would be missing in exactly the degraded cases - and the pane would take
    # file I/O into its render path to get it. An `action` step fills this with nothing, which is the
    # truth: it captures rather than streams, and has no output before it returns.
    live: list[str] = field(default_factory=list)
    rc: int | None = None
    # The traceback of the exception that ENDED this step, or "" for every step that answered for itself
    # (si#182). This field IS the distinction between a step that failed and a step that blew up - see
    # `CRASH_RC` for why it is not an rc and not a sixth state - and it is the one both renderers read:
    # `failure_report` says "crashed" on the strength of it, and `transcript` prints `crashed` where it
    # would otherwise print `rc 1`.
    #
    # It is set by `Step.run` alone, and only ever from "" to a traceback, so a reader of a finished step
    # can take a non-empty value as proof rather than as a hint.
    crash: str = ""
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
        never run, or still running.

        A step that RAISED has one since si#182: `run` stamps `ended_at` in a `finally`, so the time a
        crash took is measured like any other. It is the run's honest figure - the operator waited
        through those seconds - and a crashed step with no duration was half of what left si#182's step
        looking like it was still going."""
        if self.started_at is None or self.ended_at is None:
            return None
        return self.ended_at - self.started_at

    def __post_init__(self) -> None:
        if (self.action is None) == (self.stream is None):
            raise ValueError("a Step needs exactly one of action / stream")

    def run(self, emit: Emit = _noop) -> Outcome:
        """Run this step and leave a verdict on it, whether the action returned or blew up (si#182).

        EVERY PATH THROUGH THIS METHOD ENDS WITH A STATE, AN rc AND AN `ended_at`. Before si#182 the
        three were set only after the call returned, so a body that raised left the step `RUNNING`
        forever - no rc, no duration - and the exception went on to take `run_plan` and `run_headless`
        down with it, past the retraced tree, past `failure_report` and past the transcript. Losing that
        transcript is the worst of it: the artefact exists precisely for the run that went wrong, and it
        was written for every run except that one.

        WHAT IT DOES NOT CATCH IS AS DELIBERATE AS WHAT IT DOES. `Exception`, not `BaseException`: a
        `KeyboardInterrupt` is the operator saying stop and a `SystemExit` is the code saying exit, and
        neither is a step blowing up. Both still leave through here and still end the run - what changed
        for them is `run_headless`'s `finally`, which now writes the record on their way past. A body
        that means to turn `sys.exit(...)` into an rc says so by being built with `capturing` (si#174),
        which owns that translation because it is the one that knows the body reports by printing.

        NOT RE-RAISED, AND NOT SILENT EITHER. The exception is turned into a verdict rather than passed
        on, because the run reaching its end is the whole point; and it is recorded in five places
        instead of the one it had - `log.error` as it happens, `self.crash`, `self.output` (so the
        details pane and the report show it), the per-step file `steplog` writes, and the transcript.

        THE LOG FILE IS WRITTEN HERE rather than left to the action, and the reason is `failure_report`'s
        ten-line tail: a traceback is routinely longer than that, and a report that shows its last ten
        lines and then says "the lines above are all of it" would be claiming the evidence does not
        exist. With the file on disk the report names the path to the rest, which is #49's both-or-
        neither rule. A step whose action already wrote its own log had not reached that write when it
        raised, so nothing is overwritten.
        """
        self.state = StepState.RUNNING
        self.started_at = clock()
        try:
            if self.stream is not None:
                outcome = self.stream(emit)
            elif self.action is not None:
                outcome = self.action()
            else:
                # `__post_init__` refuses a Step with neither, so this is the invariant restated at the
                # one place that depends on it. It is not dead code: a Step is mutable, so the invariant
                # holds only for a Step nobody has reached into since it was built - and writing it out
                # is what makes `run` total instead of leaving `self.action()` as a call on
                # `Callable | None`.
                raise ValueError("a Step needs exactly one of action / stream")
        except Exception as exc:  # noqa: BLE001 - a crash becomes this step's verdict; see the docstring
            outcome = self._crashed(exc)
        finally:
            # IN A `finally`, so a `KeyboardInterrupt` through a step is measured too: the transcript
            # `run_headless` writes on its way past then shows how long the step the operator stopped had
            # been going, instead of leaving the one step anybody is asking about without a number.
            self.ended_at = clock()
        self.output = outcome.output
        self.rc = outcome.rc
        self.state = StepState.OK if outcome.ok else StepState.FAILED
        return outcome

    def _crashed(self, exc: Exception) -> Outcome:
        """Turn the exception that ended this step into the Outcome it never produced.

        The output is what the step had already streamed AND the traceback, in that order, because the
        lines before the crash are half the evidence: a body that printed its way to the item it fell
        over on has named that item, and a block holding only the stack throws that away.
        """
        self.crash = crash_text(exc)
        produced = "\n".join(self.live).rstrip("\n")
        output = f"{produced}\n\n{self.crash}" if produced else self.crash
        identity = self.command or self.label
        log.error(f"{identity} - crashed: {type(exc).__name__}: {exc}")
        steplog.write(identity, output)
        return Outcome(rc=CRASH_RC, output=output)


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


def abort_after(pipeline: Pipeline, failed: int, started: frozenset[int] | None = None) -> Abort:
    """Which of the remaining steps a failure at step `failed` skips - the ONE place both runners ask
    (netctl#1317). `stop_on_failure` is declared per command, so it is a property of the SUBTREE that
    declares it, not of the run.

    "REMAINING" IS "NOT COMMITTED TO", and `started` is what says so (si#147). While execution was
    sequential that was the same sentence as "after the failed one" - every later step was also every step
    that had not begun - so the index was the whole answer. With a fan in flight the two come apart in
    both directions: a sibling with a HIGHER index may already be running, and one with a LOWER index may
    be waiting on the bound. The set the scheduler passes therefore holds every step already RUNNING or
    finished, plus every step in the other branches of any fan the failed one sits in - see
    `parallel_siblings` for why a fan's members are committed as a group rather than raced.

    Omitting it keeps the index reading, which is what `_skip_note` wants when it recomputes a reason
    after the run, and what a caller with no scheduler behind it gets.

    A step that IS running when the failure lands is never skipped: it is left to finish. See `run_plan`
    for why cancelling was rejected.

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
    remaining = (tuple(index for index in range(len(steps)) if index not in started)
                 if started is not None else tuple(range(failed + 1, len(steps))))
    tree = pipeline.usable_tree()
    if tree is None:
        return (Abort(scope="", indices=frozenset(remaining))
                if pipeline.stop_on_failure else _NOTHING_ABORTED)
    leaves = tree.leaves()
    scope = next((node for node in _chain_to(tree, leaves[failed]) if node.spec.stop_on_failure), None)
    if scope is None:
        return _NOTHING_ABORTED
    within = {id(leaf) for leaf in scope.leaves()}
    indices = frozenset(index for index in remaining if id(leaves[index]) in within)
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
        # WHY, IN THE STEP'S OWN TERMS (si#182). A crashed step did not exit 1 - it never exited at all,
        # and `rc 1` is simplon's verdict on it rather than a number the step produced. Saying "failed
        # (rc 1)" over a traceback is precisely the reading this repository hunts: it invites a reader to
        # go looking for the gate that returned 1.
        if step.crash:
            lines.append(f"why {identity} crashed (it raised, so it has no exit code of its own):")
        else:
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

    IN PLAN ORDER, not as a tree. `render_tree` already draws the shape and both runners show it; what it
    cannot show is the sequence, which is the half a reader reconstructing an incident needs - and the
    sequence is `pipeline.steps`.

    PLAN order and not COMPLETION order, which is a distinction si#147 created and it is worth being
    exact about: while every step waited for the one before it the two were the same list. A plan that
    declares `parallel:` runs some of them at once, so this is the order the manifest declares rather
    than the order the clock saw. It stays the right reading order - it is the order the tree, the
    headless log and the manifest all use, so a reader compares like with like - and the wall-clock
    truth is not lost: every line carries that step's own duration, off its own `started_at`.

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
            # `crashed` rather than `rc 1` for a step that raised (si#182), for the reason
            # `failure_report` states: the rc is the kernel's verdict and not the step's answer. The
            # duration stays, because the seconds were real.
            verdict = "crashed" if step.crash else f"rc {step.rc}"
            lines.append(f"{icon} {identity}  {verdict}{shown}")
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
    one is the one that decided, exactly as `run_plan`'s `setdefault` records it.

    It recomputes WITHOUT the started set, so it reads `abort_after`'s index rule rather than the
    scheduler's (si#147). That is deliberate and it is safe for what this function is asked: the wider
    set it computes can only claim steps that in fact ran, and this is only ever called for a step that
    IS skipped - so the reason it finds is the reason that step got. Passing a started set would mean
    keeping one until after the run, to answer a question that is already answered.
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


def write_run_transcript(pipeline: Pipeline, started: datetime,
                         extra: Sequence[str] = ()) -> Path | None:
    """Write the run transcript beside the per-step logs; returns the path, or None when there was
    nowhere to put it.

    `extra` is APPENDED to the header `steplog.run_header` composes, for a run that knows something about
    itself the kernel cannot - si#205's walk adds who answered, against which product version, and over
    which selection of scenarios. Appended and not substituted, so the facts si#148 and si#125 settled sit
    on every transcript whatever wrote it, and a caller with something to add cannot lose them by
    forgetting to restate them.

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
        text = "\n".join(transcript(pipeline,
                                    list(steplog.run_header(pipeline.name, started)) + list(extra)))
    except Exception as exc:  # noqa: BLE001 - see the paragraph above; nothing here may cost a run
        log.warn(f"{pipeline.name}: the run transcript could not be composed ({exc})")
        return None
    return steplog.write_run(text)


def render_tree(root: Row, indent: str = "  ",
                icons: Mapping[StepState, str] | None = None) -> list[str]:
    """The display tree as text lines, one per row, indented by depth - what `run_headless` prints so a CI
    log shows the structure the TUI draws.

    Since #52 a row that RAN carries its duration in a right-hand column, padded to one width so the
    numbers line up and can be scanned. A COLUMN and not a paragraph: the run gains no line, green or red.
    A row that did not run carries nothing there, and no trailing blank either - `⊘ deploy.up` ends where
    the name ends, because the absence is the statement.

    `icons` is the state alphabet to render in, and it defaults to the glyphs. `run_headless` passes
    `icons_for(sys.stdout)` so a stream that cannot encode them gets the ASCII twin instead of a
    `UnicodeEncodeError` (si#161); nothing else overrides it."""
    table = STATE_ICON if icons is None else icons
    # The icon column is padded to the widest spelling in the table, so the labels line up whichever
    # alphabet is in use. Under `STATE_ICON` every value is one character and this pads nothing, which is
    # why the glyph output is byte-identical to what it was.
    icon_width = max(len(icon) for icon in table.values())
    rows: list[tuple[str, str]] = []

    def walk(row: Row, depth: int) -> None:
        duration = row.duration
        rows.append((f"{indent * depth}{table[row.state]:<{icon_width}} {row.label}",
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


# --- a body that REPORTS BY PRINTING (si#174) ---------------------------------------------------------
#
# THE GAP. `Step` takes an in-process `stream` callable, which is what lets a product run its own
# functions in the TUI instead of shelling out - but a body that already exists reports by PRINTING, and
# the kernel had nothing that turned a print into the step's emit. Measured on the installed package
# before this: no `redirect_stdout` and no `StringIO` anywhere in it. The product that found this carries
# ~1500 lines of command bodies ported one careful step at a time from Invoke-Build, all of which print.
# The three ways to run those are to rewrite every body to take an `emit` (a rewrite of the thing you are
# trying not to touch), to re-launch each as a subprocess (a process launch for no reason), or to
# redirect stdout for the length of the call. This is the third, done once here rather than once per
# product.
#
# WHY IT IS NOT `contextlib.redirect_stdout` PER STEP, and this is the part worth shipping. `sys.stdout`
# is process-global and si#147 made steps run side by side, so a per-step redirect is not a per-step
# anything. Measured with two threads each redirecting round three prints, 50 ms apart:
#
#     branch A captured ['A line 0']
#     branch B captured ['B line 0', 'A line 1', 'B line 1', 'A line 2', 'B line 2']
#     sys.stdout afterwards: branch A's writer, which is dead
#
# Three separate faults in one run of eleven lines: five of A's and B's six lines went into the wrong
# step, an unrelated thread printing at the same time was swallowed by whichever step happened to be
# capturing, and - the one that outlives the run - `redirect_stdout` restores what IT saved on entry, so
# interleaved enter/exit left `sys.stdout` pointing at a finished step's buffer for the rest of the
# process. "Restoration on every path" is not something a hand-rolled swap or a nested `redirect_stdout`
# can promise under a fan.
#
# SO THERE IS ONE REDIRECT AND IT ROUTES BY THREAD. `_Routing` installs a single `_StdoutRouter` as
# `sys.stdout` while any capturing step is running and takes it down when the last one ends; the router
# holds a thread-local writer and hands a write to the writer of the thread that made it, or to the real
# stdout when that thread has none. Two capturing branches therefore do not see each other's output, an
# uncaptured thread keeps printing to the terminal, and the restore happens once, from a counter under a
# lock, rather than once per step from a saved value that may be stale. The alternative - a lock held for
# the length of each capturing step - is four lines and correct, and it silently serialises a fan the
# manifest declared parallel, which is the kind of quiet this repository refuses.
#
# WHAT IT DOES NOT FIX is the process-global fact itself: a thread this kernel never started, spawned by
# a captured body, has no thread-local writer and prints to the terminal rather than into its step.


class _StdoutRouter:
    """The ONE object installed as `sys.stdout` while capturing steps run: a write goes to the writer
    registered for the CALLING thread, or to the stream this replaced.

    IT SUBCLASSES NOTHING, and that is measured rather than stylistic. `io.TextIOBase` was the obvious
    base and it is the wrong one: its `encoding` is a read-only C attribute, so carrying the replaced
    stream's encoding raises `AttributeError: attribute 'encoding' of '_io._TextIOBase' objects is not
    writable` - at RUNTIME, from inside the first capturing step, while mypy passed the same code. And
    the encoding has to be carried: `icons_for(sys.stdout)` reads it to decide whether the console can
    hold the state glyphs, and a None there is read as "a test double" and rewarded with the glyphs -
    the wrong answer on exactly the Windows console si#161's ASCII table exists for. So this declares
    the members a writer is asked for and nothing else.

    `isatty` answers False to a captured thread on purpose, and it is not cosmetic. `rich.Console` asks
    it (so does `simplon.fetch`), and a Rich console that believes it is on a terminal emits ANSI and
    cursor moves into what is about to become a step log and a run transcript. si#144 spent its whole
    argument on keeping escapes out of that file.

    `fileno` delegates rather than refusing, because the honest answer to "which descriptor is the
    console" is the console's - it is what a library asks in order to measure the terminal, not in order
    to write. A library that wrote BYTES to that descriptor would bypass the capture; nothing on this
    path does, and refusing would break the measuring caller to defend against the hypothetical one.
    """

    def __init__(self, under: TextIO) -> None:
        self.under = under
        self.encoding = getattr(under, "encoding", "utf-8") or "utf-8"
        self.errors = getattr(under, "errors", None)
        self._local = threading.local()

    def target(self) -> _LineWriter | None:
        writer: _LineWriter | None = getattr(self._local, "writer", None)
        return writer

    def take(self, writer: _LineWriter | None) -> _LineWriter | None:
        """Point THIS thread at `writer` and return what it was pointing at, so a nested capture can put
        the previous one back."""
        previous = self.target()
        self._local.writer = writer
        return previous

    def write(self, text: str) -> int:
        writer = self.target()
        if writer is None:
            return self.under.write(text)
        return writer.write(text)

    def writelines(self, texts: Sequence[str]) -> None:
        for text in texts:
            self.write(text)

    def flush(self) -> None:
        writer = self.target()
        if writer is None:
            self.under.flush()
        else:
            writer.flush()

    def isatty(self) -> bool:
        return False if self.target() is not None else self.under.isatty()

    def fileno(self) -> int:
        return self.under.fileno()

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    @property
    def closed(self) -> bool:
        return self.under.closed


class _Routing:
    """Installs and removes the one router, counting the capturing steps that need it.

    A COUNTER UNDER A LOCK rather than a saved-and-restored value per step: the restore then happens once,
    when the last capture ends, and cannot be performed by a thread holding a stale idea of what stdout
    was. It only restores if `sys.stdout` is still the router - something else may legitimately have
    wrapped it since (a test's own `redirect_stdout`), and putting our saved value back over theirs would
    be the same defect one layer up."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._router: _StdoutRouter | None = None
        self._active = 0

    @contextlib.contextmanager
    def to(self, writer: _LineWriter) -> Iterator[None]:
        """Route this thread's stdout into `writer` for the length of the block, on every way out.

        TWO NESTED `finally`s rather than one, because they undo two different things and the inner one
        can fail. `_install` has already incremented the counter by the time `take` is called, so a fault
        between them would leave the router installed for the rest of the process with nobody left to
        remove it - `sys.stdout` permanently pointing at a router whose threads have all gone. The
        release is therefore guarded from the instant the counter moves."""
        router = self._install()
        try:
            previous = router.take(writer)
            try:
                yield
            finally:
                router.take(previous)
        finally:
            self._remove(router)


    @contextlib.contextmanager
    def suspended(self) -> Iterator[None]:
        """Un-route this thread for the length of the block - what an emit is delivered under.

        THIS IS THE HANG si#174 WAS WRITTEN TO PREVENT, and it only shows on the path a developer at a
        terminal does not take. The headless runner's emit PRINTS, so delivering a line to it with the
        redirect still in force feeds that print straight back into the writer that produced it:
        `maximum recursion depth exceeded` on the first line of the first step. The TUI's emit appends to
        a widget and does not print, so an interactive run is fine and the fault waits for the first
        piped or CI run."""
        router = self._router
        if router is None:                      # nothing is capturing; there is nothing to suspend
            yield
            return
        previous = router.take(None)
        try:
            yield
        finally:
            router.take(previous)

    def _install(self) -> _StdoutRouter:
        with self._lock:
            if self._router is None:
                self._router = _StdoutRouter(sys.stdout)
                sys.stdout = self._router
            self._active += 1
            return self._router

    def _remove(self, router: _StdoutRouter) -> None:
        with self._lock:
            self._active -= 1
            if self._active > 0:
                return
            self._router = None
            if sys.stdout is router:
                sys.stdout = router.under
            else:
                log.warn("stdout was replaced while a step was capturing it, so simplon left it alone "
                         "rather than putting its own back over somebody else's")


#: The ONE routing for the process. Module state, because `sys.stdout` is module state: two of these
#: would each install a router over the other's and reintroduce exactly the interleaving measured above.
_ROUTING = _Routing()


#: The escape sequences a captured body can emit: CSI (colour, cursor moves) and OSC (window title and
#: friends). Removed from every captured line - see `_LineWriter._deliver` for the measurement.
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


class _LineWriter:
    """The file a captured body writes to: it collects text and hands over COMPLETE lines.

    LINE-BUFFERED RATHER THAN WRITE-THROUGH, because Rich writes one visual line in several calls and a
    pane of fragments is not a pane of lines. The break rule is `simplon.run.LINE_BREAK`, the same one
    `run_stream` segments a child's pipe with, so an in-process step and a subprocess step disagree about
    nothing.

    WHAT HAPPENS TO A HALF LINE, which is the case si#144 measured for subprocesses and this is its
    in-process twin. Three answers, and none of them is "lose it":

    - a `flush()` hands it over immediately. `print(..., flush=True)` and `rich.Console` both flush, so a
      body that means its half line to be seen gets it seen.
    - the end of the step hands over whatever is left (see `capturing`), including on the path where the
      body raised - so the line it fell over on is in the record beside the traceback.
    - between those two it waits. `run_stream` also hands over on an idle timer, and that is deliberately
      NOT carried across: there the pump thread has nothing else to do, while here the only thread that
      could hand the bytes over is the body's own, and a second thread per step to publish text the body
      has not finished writing would race the body for the same buffer. The bound is the step, not the
      run.
    """

    def __init__(self, emit: Emit, routing: _Routing) -> None:
        self._emit = emit
        self._routing = routing
        self._partial = ""

    def write(self, text: str) -> int:
        self._partial += text
        parts = LINE_BREAK.split(self._partial)
        self._partial = parts.pop()             # what follows the last break is not finished yet
        for part in parts:
            self._deliver(part)
        return len(text)

    def flush(self) -> None:
        if self._partial:
            self._deliver(self._partial)
            self._partial = ""

    def _deliver(self, line: str) -> None:
        """Hand one finished line over, with its escape sequences removed.

        WHY THE STRIPPING IS HERE AND NOT LEFT TO THE PRODUCT (rich 15.0.0, measured). `isatty()` answers
        False to a captured thread, and that is NOT enough: `Console.is_terminal` does follow it - it
        flipped to False the moment stdout was swapped - but `Console._color_system` is detected ONCE, in
        `__init__`, and rich renders a style whenever that is truthy. So a console a product built at
        module import, while stdout really was a terminal, keeps writing `\x1b[1;31m...` for the rest of
        the process however the capture answers. Measured: `EIGHT_BIT` cached at construction, and
        `[bold red]a warning[/]` arriving as `\x1b[1;31ma warning\x1b[0m`.

        All three destinations of a captured line refuse those bytes. The details pane is a
        `RichLog(markup=False)`, which renders them as literal escape characters; `steplog` writes them
        into a file somebody greps; and the run transcript is the artefact si#144 spent its whole
        argument on keeping plain, because it is what gets attached to a ticket.

        THE OPPOSITE CHOICE IN `run_stream` IS NOT AN INCONSISTENCY. There the bytes come from a foreign
        child and editing another program's output is not the kernel's business - which is exactly why
        si#144 chose a pipe over a pty, so that the escapes would not be CREATED rather than removed
        afterwards. Here the writer is the kernel's own and there is no equivalent lever: the one it has
        (`isatty`) is measured above as insufficient."""
        with self._routing.suspended():
            self._emit(_ESCAPES.sub("", line))


def _exit_rc(exit: SystemExit, hand_over: Emit) -> int:
    """What `sys.exit(...)` inside a captured body means as an rc - CPython's own rule, not one invented
    here: no argument or `None` is success, an int is that int, and anything else is printed and exits 1.

    The message is handed over as a LINE of the step rather than dropped, because `sys.exit("no docker
    found")` is a body saying why it stopped, and that sentence is the whole reason the step is red."""
    code = exit.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    hand_over(str(code))
    return 1


def capturing(label: str, work: Callable[[], None], command: str = "", help: str = "") -> Step:
    """A Step that runs `work()` in-process and turns what it PRINTS into the step's output (si#174).

    For a body that already exists and already reports by printing: it needs no `emit` parameter, no
    rewrite and no subprocess. Each completed line reaches the pane live through `emit`, the accumulated
    text is the Outcome's output (so the pane keeps it after the step ends), and `steplog` writes the
    whole of it to a file the failure report can name.

    THE THREE WAYS A BODY REPORTS, ALL OF WHICH BECOME AN rc:

    - it RETURNS - rc 0. The return VALUE is ignored; a body that wants to choose its own code says so
      with `sys.exit(code)`, which is the spelling the ported bodies already use and the one a reader
      cannot mistake for an accidental fall-through.
    - it calls `sys.exit(...)` - `_exit_rc`, which is CPython's rule.
    - it RAISES - a FAILED step, never an escaping exception, because one item blowing up must not take
      the rest of the pipeline down: that is the opposite of what `stop_on_failure: false` promises. This
      is where si#182 is load-bearing rather than merely adjacent: the exception is left to `Step.run`,
      which stamps `ended_at`, records the traceback in `Step.crash`, composes it with the lines this
      writer had already collected (they are the same list) and writes the file. Catching it here would
      duplicate all four and would set none of them on a Step it does not have.

    RESTORATION IS THE `with`, not a pair of assignments. `_Routing.to` puts this thread's stdout back on
    every path out - a return, a `sys.exit`, a raise, a nested capture - which a hand-rolled swap cannot,
    and which a per-step `contextlib.redirect_stdout` gets wrong under a fan for the measured reasons
    stated above this class.

    RICH REACHES IT, MEASURED RATHER THAN ASSUMED (rich 15.0.0), AND IT REACHES IT ONLY HALF WAY.
    `Console.file` is a property that reads `sys.stdout` at every access when no `file=` was passed, so a
    console built at a product's module import - before any of this exists - does write here, and
    `Console.is_terminal` follows the capture too. What does NOT follow is the colour: `_color_system` is
    detected once in `__init__`, so a console built while stdout really was a terminal goes on emitting
    ANSI for the rest of the process. `_LineWriter._deliver` removes it, and says why there.

    The one console this cannot reach at all is `Console(file=sys.stdout)`, which resolves the handle at
    construction and then holds the real terminal for ever: measured, its output bypassed the capture
    entirely and went to the screen. That is a product-side spelling to avoid, and it is named here
    because the failure is silent - the step's pane is simply empty.
    """
    identity = command or label
    # The collector, built HERE rather than inside `stream`, so the Step below can be handed the SAME
    # list: the pane reads what the step has produced while it is still producing it (si#144), and
    # `Step.run` composes a crash's output from it (si#182).
    lines: list[str] = []

    def stream(emit: Emit) -> Outcome:
        lines.clear()      # a Step can be run twice; the pane must not show the previous run's output

        def hand_over(line: str) -> None:
            lines.append(line)
            emit(line)

        writer = _LineWriter(hand_over, _ROUTING)
        rc = 0
        try:
            with _ROUTING.to(writer):
                # THE HALF LINE IS HANDED OVER ON BOTH PATHS, and they are written out separately
                # rather than as one `finally`, because only one of them is unwinding (code review).
                # On the raising path this flush is what puts the line the body fell over on into
                # `lines` before `Step.run` composes the crash record out of them - and it is a
                # COURTESY, running while the body's own exception is already travelling. If the emit
                # behind it raised (in the TUI it is a `call_from_thread`, which can), that fault would
                # become the exception `Step.run` records: `__context__` would still carry the body's,
                # but `failure_report` shows a step's LAST ten lines, so the traceback a reader needs
                # would be pushed out of exactly the window si#182 built the tail rule around. The
                # body's exception wins; a fault in the courtesy is dropped. On the ordinary path
                # nothing is travelling, so a flush fault is real news and propagates.
                try:
                    work()
                except BaseException:
                    with contextlib.suppress(Exception):
                        writer.flush()
                    raise
                writer.flush()
        except SystemExit as exit:
            # Caught here and not in `Step.run`, which deliberately lets `SystemExit` past: a body saying
            # `sys.exit` means to end ITS OWN work, and only this function knows the body was written
            # that way. Outside the `with`, so the message line below goes out on a restored stdout.
            rc = _exit_rc(exit, hand_over)
        output = "\n".join(lines)
        steplog.write(identity, output)
        return Outcome(rc=rc, output=output)

    return Step(label=label, stream=stream, live=lines, command=identity, help=help)


# --- running the plan: what may happen at the same time, and what has to wait (si#147) ---------------

#: The env var a MACHINE limits parallelism with, and the count used when it says nothing.
#:
#: THE SPLIT IS DELIBERATE AND IT IS THE WHOLE DESIGN OF THE BOUND. The manifest declares WHAT may share
#: a machine - a property of the work, which the product knows and which is true wherever it runs. How
#: MANY of them fit is a property of the HOST, which the manifest cannot know: netctl's fan of eight
#: image builds is eight `docker build`s, and that is not the same act on a two-core CI runner as on a
#: fourteen-core workstation. A `max_parallel:` key in the manifest would be a machine fact written into
#: a file that travels between machines, which is the second-source shape this repository refuses
#: everywhere else.
#:
#: FOUR, NOT `cpu_count()`. The work in a fan is whole subprocesses - a docker build, a gradle run, a
#: pytest suite - each of which already uses every core it can find, so the count is about how many
#: CONTAINERS, caches and daemons are in flight, not about CPUs. Four is small enough that a plan of
#: forty steps cannot start forty of them and large enough to pay for itself on the shapes that exist
#: (the largest fan in any reachable manifest is netctl's eight images). The `cpu_count` floor is there
#: so a one- or two-core runner does not get four anyway.
MAX_PARALLEL_ENV = "SIMPLON_MAX_PARALLEL"
DEFAULT_MAX_PARALLEL = 4


def max_parallel() -> int:
    """How many steps may RUN at once, from the environment or the default above.

    A value that is not a step count WARNS and falls back rather than being read as 1 or as "no limit":
    a typo that silently serialises a run is this repository's recurring defect wearing a number, and the
    operator who typed it has to be told that what they asked for is not what is happening."""
    raw = os.environ.get(MAX_PARALLEL_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value >= 1:
            return value
        log.warn(f"{MAX_PARALLEL_ENV}={raw!r} is not a step count of 1 or more; "
                 f"using {min(DEFAULT_MAX_PARALLEL, os.cpu_count() or 1)}")
    return min(DEFAULT_MAX_PARALLEL, os.cpu_count() or 1)


@dataclass(frozen=True)
class Fan:
    """Branches that may run at the SAME time, each branch itself an ordered `Schedule`.

    A branch and not a step, because a `parallel:` aggregate's dependency may itself be a chain: netctl's
    `web-jar` is `[builder-image, web-jar-only]`, and a fan that flattened its members to leaves would
    run gradle in an image that does not exist yet. What runs side by side is the SUBTREES."""
    branches: tuple["Schedule", ...]


#: One thing after another: a step INDEX into `Pipeline.steps`, or a `Fan` whose branches are not
#: ordered against each other. Everything after a `Fan` in the same tuple is its JOIN - it starts when
#: every branch has finished - which is why no separate barrier exists: `depends_on` already means
#: "after", and a fan is the one place it stops meaning it.
Schedule = tuple["int | Fan", ...]


def schedule_indices(schedule: Schedule) -> tuple[int, ...]:
    """Every step index in `schedule`, nested fans included, in PLAN order.

    SORTED rather than in traversal order, and that is the property the headless log rests on: a reader
    of a CI log follows the plan, not the scheduler, so the blocks come out in the order the tree
    declares them whichever branch happened to finish first."""
    flat: list[int] = []
    for item in schedule:
        if isinstance(item, Fan):
            flat += [index for branch in item.branches for index in schedule_indices(branch)]
        else:
            flat.append(item)
    return tuple(sorted(flat))


def parallel_siblings(schedule: Schedule) -> dict[int, frozenset[int]]:
    """Step index -> the steps that are running BESIDE it by declaration: every index in the other
    branches of every fan it sits in. Empty for a step no fan contains.

    WHAT IT IS FOR, and it is the sharpest decision in si#147. When a step fails, `abort_after` skips the
    work in its scope that has not begun - and inside a fan "has not begun" is a RACE. Three branches
    start within microseconds of each other; if the first one fails instantly, whether the other two were
    far enough along to count as started depends on the OS scheduler, the bound, and the machine's load.
    A run whose set of executed steps varies between two runs of the same plan is unreproducible, and
    unreproducible is worse than either answer to the question.

    So a fan's members are never skipped FOR EACH OTHER, and the reason is the declaration itself rather
    than a tie-break: `parallel:` says these subtrees do not have to wait for each other, which is a
    statement that none of them needs what another produces. A failure in one therefore does not make
    another's work doomed - their results are still worth having, which is the whole reason they were
    declared parallel. What IS doomed is whatever comes after the join, and that is skipped exactly as it
    always was.

    Within ONE branch nothing changes: a branch is an ordered chain, so the step after a failed one is
    doomed in the ordinary way and is skipped by the ordinary rule.

    The cost is stated: a fan of forty in which the first fails still runs the other thirty-nine. The
    lever for that is the bound, and the manifest cannot express "stop the fan too" - v1 declines to add a
    second flag for a shape no reachable manifest has."""
    out: dict[int, frozenset[int]] = {}

    def walk(sched: Schedule, inherited: frozenset[int]) -> None:
        for item in sched:
            if isinstance(item, Fan):
                own = [frozenset(schedule_indices(branch)) for branch in item.branches]
                whole = frozenset[int]().union(*own) if own else frozenset[int]()
                for branch, mine in zip(item.branches, own):
                    walk(branch, inherited | (whole - mine))
            else:
                out[item] = inherited

    walk(schedule, frozenset())
    return out


def schedule_for(pipeline: Pipeline) -> Schedule:
    """What this pipeline may do at the same time, read off its plan tree (si#147).

    DECLARED, NOT DERIVED, and that was a measurement rather than a preference. Deriving would have been
    better if it held - `depends_on` is already a graph, and everything unconnected in a graph is by
    definition free - so the question was measured before it was designed: over the six manifests this
    kernel can reach (`simplon.surface.CONSUMERS` plus its own), **541 pairs of planned leaves have no
    edge between them, and 466 of those would break if run together**. The reason is uniform and it is
    visible in every one of the six: an aggregate's dependencies are a LIST, and the order between
    siblings is stated by their position in it and nowhere else. simplon's own `build docs` says so in
    prose - "Siblings execute in list order, so [reference, site] IS the edge" - asbundle's build chain
    says "in the order listed", biz-cockpit's `build` puts its type checker before its images by an owner
    decision recorded only as list order, and the kernel's own #901 idiom for chaining under the
    impl-XOR-depends_on lock (an aggregate `[builder-image, web-jar-only]`) makes every chained build
    exactly such a pair. A derived executor would have broken all of it, silently, under load.

    So a fan exists only where a node says `parallel: true`, and a manifest that says it nowhere gets the
    tuple of indices it has always run - this function's whole output for every manifest that exists
    today.

    NO USABLE TREE, NO PARALLELISM. `parallel` is declared on a NODE, so without a verified leaf-to-step
    pairing there is nothing to read it off; and a display-level degrade must not decide that two
    subprocesses may share a machine. `Pipeline.usable_tree` already warns when it rejects one."""
    tree = pipeline.usable_tree()
    if tree is None:
        return tuple(range(len(pipeline.steps)))
    index_of = {id(leaf): index for index, leaf in enumerate(tree.leaves())}

    def walk(node: "PlanNode") -> Schedule:
        # `leaves()` is post-order - a node's own step comes after its children's - and this mirrors it,
        # because the schedule and the step list have to agree about what "after" means.
        # `index_of[...]` unguarded, deliberately: `usable_tree` has already verified that every leaf
        # pairs with a step, so a missing one is a broken invariant and a KeyError says so. A `.get` here
        # would DROP that step from the schedule - it would never run and nothing would say why, which is
        # the "cannot tell nothing-to-do from failed" defect at the one place it would be invisible.
        own: Schedule = ((index_of[id(node)],) if node.is_leaf else ())
        if not node.children:
            return own
        if node.spec.parallel:
            return (Fan(tuple(walk(child) for child in node.children)),) + own
        return tuple(item for child in node.children for item in walk(child)) + own

    return walk(tree)


def _noop_start(_index: int) -> None:
    pass


def _noop_line(_index: int, _line: str) -> None:
    pass


def _noop_fan(_indices: "tuple[int, ...]") -> None:
    pass


@dataclass(frozen=True)
class RunHooks:
    """What a runner wants to be told while the plan runs. Every hook defaults to doing nothing, so a
    caller that only wants the steps executed passes none of them.

    ONE SET FOR BOTH RUNNERS. The TUI's worker thread and the headless loop each carried their own copy
    of the walk - the abort set, the skip marking, the state transitions - and the two agreed only
    because somebody kept them agreeing. A fan is exactly the kind of change that would have been made
    in one of them; the walk is `run_plan` now and the difference between the runners is these six
    callbacks.

    `on_fan_start` / `on_fan_end` receive every step index in the fan, in PLAN order. The TUI ignores
    them - its pane has been per-step since si#144 - and the headless runner uses them to keep a CI log
    readable; see `_HeadlessOutput`."""
    on_start: Callable[[int], None] = _noop_start
    on_line: Callable[[int, str], None] = _noop_line
    on_finish: Callable[[int], None] = _noop_start
    on_skip: Callable[[int, str], None] = _noop_line
    on_fan_start: Callable[["tuple[int, ...]"], None] = _noop_fan
    on_fan_end: Callable[["tuple[int, ...]"], None] = _noop_fan


class _Run:
    """The state one `run_plan` call shares across its branch threads: which steps have begun, which are
    doomed, and how many may be in flight.

    Two threads touch each field and both are guarded, unlike `Step.live`, whose lock-free read is argued
    for at its own declaration: that one is a single reader of an append-only list, these are read-modify
    -write on a set and a dict from any number of branches."""

    def __init__(self, pipeline: Pipeline, hooks: RunHooks, schedule: Schedule) -> None:
        self.pipeline = pipeline
        self.hooks = hooks
        self.siblings = parallel_siblings(schedule)
        self.lock = threading.Lock()
        self.permits = threading.BoundedSemaphore(max_parallel())
        self.aborted: dict[int, str] = {}
        self.started: set[int] = set()


def run_plan(pipeline: Pipeline, hooks: RunHooks | None = None) -> None:
    """Run every step of `pipeline`, in the order `schedule_for` says, telling `hooks` what happens.

    A FAILURE WITH STEPS IN FLIGHT LETS THEM FINISH, and starts nothing new outside the fan it happened
    in (`parallel_siblings` argues that boundary). The alternative - cancel the siblings for a faster
    verdict - was rejected on three counts, and the first is decisive: there is no
    way to cancel a subprocess that leaves a verdict a reader can trust. A killed `docker build` exits
    non-zero, and that number is indistinguishable from the build having failed on its own - the
    "cannot tell nothing-to-do from failed" defect this repository hunts, manufactured deliberately.
    Second, `abort_after` has always meant "which of the remaining steps do not START", never "stop what
    is running", so one rule keeps covering both runners. Third, a half-killed build or a half-deployed
    lab costs more to clean up than the seconds the faster verdict saved.

    What it costs is stated rather than hidden: a fan of eight in which the first fails still takes as
    long as its slowest member. The run SAYS so, which is the half that makes the choice readable rather
    than merely taken: every member of the fan carries its OWN rc in the tree, the report and the
    transcript, and only work the run declined to begin is `⊘` with the scope that stopped it.

    THE EXIT CODE IS NOT "THE LAST ONE WINS". Nothing here counts failures; `overall_rc` reads every
    step's final state and `failure_report` walks every FAILED one, so two simultaneous failures are two
    entries and one rc. That was already true and it is why the verdict needed no change - what needed
    the change is the counting `run_headless` used to do inside its loop, which a fan would have raced.

    A branch that RAISES takes the run down, the way a sequential step that raises always has. Left to
    `threading`'s default, that exception would be printed to stderr and the branch would simply stop,
    leaving a run that reports its remaining steps as never having run and no reason anywhere - a silent
    partial run being the one outcome worse than a crash."""
    schedule = schedule_for(pipeline)
    _walk(schedule, _Run(pipeline, hooks if hooks is not None else RunHooks(), schedule))


def _walk(schedule: Schedule, run: _Run) -> None:
    for item in schedule:
        if isinstance(item, Fan):
            _run_fan(item, run)
        else:
            _run_step(item, run)


def _run_fan(fan: Fan, run: _Run) -> None:
    indices = schedule_indices((fan,))
    run.hooks.on_fan_start(indices)
    faults: list[BaseException] = []

    def branch(schedule: Schedule) -> None:
        try:
            _walk(schedule, run)
        except BaseException as exc:   # noqa: BLE001 - re-raised on the calling thread below
            faults.append(exc)

    # ONE THREAD PER BRANCH, and the bound is on the STEPS rather than on the threads - so a fan of forty
    # creates forty threads of which at most `max_parallel()` are doing anything. That is the tradeoff,
    # named rather than discovered: a bounded pool would create four, and it would deadlock the moment a
    # branch containing a nested fan held a worker while waiting for workers its children cannot get. A
    # blocked thread costs a stack and nothing else; a deadlocked plan costs the run.
    threads = [threading.Thread(target=branch, args=(schedule,),
                                name=f"simplon-fan{indices[0]}-branch{n}", daemon=True)
               for n, schedule in enumerate(fan.branches)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    run.hooks.on_fan_end(indices)
    # EVERY fault is named and only the first is raised (si#147, code review). An exception can carry one
    # cause, so a second branch raising at the same time has nowhere to go in the traceback - and dropping
    # it is the silent partial failure this whole function's docstring refuses to accept, applied to
    # itself. The ones that are not raised are logged, so a run with two broken branches says two things
    # rather than one.
    for extra in faults[1:]:
        log.warn(f"{run.pipeline.name}: another branch of this fan raised at the same time and is not "
                 f"the exception below: {extra!r}")
    if faults:
        raise faults[0]


def _run_step(index: int, run: _Run) -> None:
    step = run.pipeline.steps[index]
    # A step already doomed when its branch reaches it is skipped WITHOUT taking a permit (si#147, code
    # review). The authoritative check is the one below, under the permit, because a failure can land
    # while this step waits for one; this is a fast path, not a second decision. Without it, the 36
    # doomed steps of a bounded fan of 40 each queue for a permit in order to do nothing, and the run's
    # verdict arrives one finishing step at a time.
    with run.lock:
        already_doomed = run.aborted.get(index)
    if already_doomed is not None:
        step.state = StepState.SKIPPED
        run.hooks.on_skip(index, already_doomed)
        return
    with run.permits:      # the bound, held only while the step RUNS - never while a branch waits
        with run.lock:
            reason = run.aborted.get(index)
            if reason is None:
                run.started.add(index)
        if reason is not None:
            step.state = StepState.SKIPPED
            run.hooks.on_skip(index, reason)
            return
        step.state = StepState.RUNNING
        # Before the hook, not after: `Step.run` sets it again from the same clock, and the hook repaints
        # a row and a status bar that count from this value. A counter started after the repaint
        # under-reports every step by the cost of the repaint (#52's measurement, kept).
        step.started_at = clock()
        run.hooks.on_start(index)
        outcome = step.run(lambda line: run.hooks.on_line(index, line))
    run.hooks.on_finish(index)
    if not outcome.ok:
        with run.lock:
            # The started set is what the run has COMMITTED to, not merely what has begun: a fan's other
            # branches are in it whether or not the scheduler has reached them yet, so which steps a
            # failure takes down is the same on every machine. See `parallel_siblings`.
            abort = abort_after(run.pipeline, index,
                                started=frozenset(run.started) | run.siblings.get(index, frozenset()))
            for doomed in abort.indices:
                run.aborted.setdefault(doomed, abort.reason)


def _print_captured(output: str) -> None:
    """Print an action step's captured output with the SAME two-space indent the streamed lines use, so
    both kinds of step read identically headlessly."""
    for line in output.rstrip("\n").splitlines():
        print(f"  {line}", flush=True)


class _HeadlessOutput:
    """What a CI log shows while the plan runs - and, in a fan, what it HOLDS BACK so that it can still
    be read afterwards (si#147).

    THE PROBLEM PARALLELISM CREATES HERE IS NOT THE ONE IT CREATES IN THE TUI. The pane has been per-step
    since si#144 put a step's own lines in `Step.live`, so two streams are two backlogs and the reader
    picks one. A CI log is ONE file. Interleaved, two `docker build`s produce a file in which neither
    build can be followed and nothing can be untangled after the fact, because the lines carry no step
    identity - and a log nobody can read is the same as no log, on exactly the red run it exists for.

    SO A FAN BUFFERS, AND FLUSHES IN PLAN ORDER. Each step inside a fan collects its lines; a step's
    whole block - entry line, output, verdict - is printed once that step is done AND every
    earlier-planned step of the fan has been printed. The result is a log whose blocks stand in the order
    the manifest declares, whichever branch won the race, so two runs of the same plan read the same way.
    Nothing is dropped: a passing streamed step's output is printed in full on flush, because it went out
    live before this change and a green build's log must not get shorter for having been faster.

    Incremental rather than "flush the whole fan at the end", which was the simpler version and is the
    wrong one: eight five-minute image builds would print nothing for five minutes, and a CI log that
    goes quiet is how an operator decides a job has hung.

    ONE COST, STATED RATHER THAN DISCOVERED: `log.info` stamps the line with the time it is PRINTED, so a
    buffered block carries flush times, not the moment the step began. The group header says so; the
    honest timings are the durations in the tree and the transcript, which come off `Step.started_at`.

    NOTHING IS BUFFERED OUTSIDE A FAN. A plan with no `parallel:` anywhere - every manifest that exists
    today - takes the same branches it always did and prints the same bytes it always did."""

    def __init__(self, pipeline: Pipeline, show_passing: bool) -> None:
        self.pipeline = pipeline
        self.show_passing = show_passing
        self.lock = threading.Lock()         # guards the bookkeeping below
        # A SECOND lock, held across the PRINTING of a block, and it is not redundant (si#147). The first
        # version guarded only the pointer: two branches finishing at once each popped a different index
        # and then printed at the same time, so `a`'s chunks, `b`'s chunks and `a`'s own OK line came out
        # woven together - the exact defect the buffering exists to prevent, reintroduced by the code
        # meant to prevent it. Measured on a real four-step plan of `sh -c` children, not reasoned about.
        # It cannot deadlock: a flusher takes this one and then `lock`, and nothing takes them the other
        # way round - `on_line`, which is the hot path, takes `lock` alone and is never blocked by a
        # printing block.
        self.flushing = threading.Lock()
        self.depth = 0                       # nested fans flush through the OUTERMOST one's order
        self.pending: tuple[int, ...] = ()   # the fan's indices, in plan order, not yet printed
        self.finished: dict[int, str] = {}   # index -> "" when it ran, else the skip reason
        self.lines: dict[int, list[str]] = {}

    def hooks(self) -> RunHooks:
        return RunHooks(on_start=self._start, on_line=self._line, on_finish=self._finish,
                        on_skip=self._skip, on_fan_start=self._fan_start, on_fan_end=self._fan_end)

    def _title(self, index: int) -> str:
        step = self.pipeline.steps[index]
        return step.command or step.label    # exact-command identity when the step carries one (#897)

    def _fan_start(self, indices: "tuple[int, ...]") -> None:
        with self.lock:
            self.depth += 1
            if self.depth > 1:
                return
            self.pending = indices
            self.finished = {}
            self.lines = {index: [] for index in indices}
        names = ", ".join(self._title(index) for index in indices)
        log.info(f"{len(indices)} steps side by side (at most {max_parallel()} at once): {names}")
        log.info("their output is held and printed one step at a time, in plan order, so the timestamps "
                 "in those blocks are when they were printed rather than when the step ran")

    def _fan_end(self, _indices: "tuple[int, ...]") -> None:
        with self.lock:
            self.depth -= 1
            still_open = self.depth > 0
        if still_open:
            return
        self._flush(final=True)

    def _buffering(self, index: int) -> bool:
        with self.lock:
            return index in self.lines and self.depth > 0

    def _start(self, index: int) -> None:
        if not self._buffering(index):
            self._entry_line(index)

    def _entry_line(self, index: int) -> None:
        """The line a step is ENTERED with. The help text rides on it, not on a line of its own and not in
        the retraced tree (#49): a green run keeps exactly the lines it had, one of them wider.
        `build.reference` alone made a reader look the command up in the manifest."""
        step = self.pipeline.steps[index]
        log.info(f"{self._title(index)} - {step.help}" if step.help else self._title(index))

    def _line(self, index: int, line: str) -> None:
        if self._buffering(index):
            with self.lock:
                self.lines[index].append(line)
            return
        print(f"  {line}", flush=True)

    def _finish(self, index: int) -> None:
        if self._buffering(index):
            with self.lock:
                self.finished[index] = ""
            self._flush()
            return
        self._verdict(index)

    def _skip(self, index: int, reason: str) -> None:
        if self._buffering(index):
            with self.lock:
                self.finished[index] = reason
            self._flush()
            return
        log.warn(f"{self._title(index)} - skipped ({reason})")

    def _verdict(self, index: int) -> None:
        """The three lines a finished step contributes, buffered or not - one place, so a fan's block and
        a sequential step's are the same text."""
        step = self.pipeline.steps[index]
        if step.stream is None and step.output and (step.rc != 0 or self.show_passing):
            _print_captured(step.output)
        if step.rc == 0:
            log.ok(self._title(index))
        elif step.crash:
            # NOT `failed (rc 1)` (si#182). `Step.run` has just said `crashed` on this step's own line;
            # two lines disagreeing about the same step, one of them naming an exit code the step never
            # produced, is the reading the crash contract exists to prevent.
            log.warn(f"{self._title(index)} - crashed (it raised)")
        else:
            log.warn(f"{self._title(index)} - failed (rc {step.rc})")

    def _flush(self, final: bool = False) -> None:
        """Print every leading step of the fan that is done, in plan order. `final` says the fan is over,
        so a step that has not finished never will.

        ONE FLUSHER AT A TIME (`flushing`), because two branches can finish within microseconds of each
        other and a block is not one write. A second flusher that merely took the next index would print
        into the middle of the first one's block. Waiting rather than skipping: the waiting thread then
        prints whatever became ready, so a block is never left sitting because somebody else was busy.

        THE `final` PASS EXISTS BECAUSE OF A RAISE (si#147, code review). A step's action that raises never
        reaches `on_finish`, so mid-fan it leaves a hole in the plan order - and a flusher that stops at
        the first unfinished index would then never print the branches AFTER it, however much output they
        had already captured and however successfully they ran. Three steps, the middle one raising, and
        the log showed the first one only: the buffering that makes a fan readable would have destroyed
        exactly the evidence a crash needs. At the end of a fan nothing more can arrive, so the remaining
        finished blocks are printed in plan order and the hole is NAMED rather than skipped over - an
        absent block that says nothing is the same defect one step further on.

        The BOOKKEEPING lock is taken and released per step rather than held across the printing, so a
        block of thousands of lines does not stall the other branches' `on_line` for its duration."""
        with self.flushing:
            while True:
                with self.lock:
                    if not self.pending:
                        return
                    index = self.pending[0]
                    unfinished = index not in self.finished
                    if unfinished and not final:
                        return
                    self.pending = self.pending[1:]
                    reason = "" if unfinished else self.finished[index]
                    held = self.lines.get(index, [])
                if unfinished:
                    log.warn(f"{self._title(index)} - no verdict: it was still running when the fan ended")
                    continue
                if reason:
                    log.warn(f"{self._title(index)} - skipped ({reason})")
                    continue
                self._entry_line(index)
                for line in held:
                    print(f"  {line}", flush=True)
                self._verdict(index)


def _write_the_record(pipeline: Pipeline, started: datetime) -> None:
    """Everything a finished run leaves behind: the retraced tree, the reasons under it, and the
    transcript on disk. Called from `run_headless`'s `finally`, so it runs for a run that ended by
    raising as well as for one that ended (si#182).

    IT MAY NOT RAISE, and that is a harder rule here than the one `write_run_transcript` already keeps
    for itself. An exception thrown inside a `finally` REPLACES the one that was already travelling, so a
    fault in the tree print would not merely lose the tree - it would swap the operator's Ctrl-C, or the
    real crash, for a `UnicodeEncodeError` from the code that was trying to report it. si#161 measured
    that very fault on this very loop.

    So the rendering is guarded and the transcript is written OUTSIDE the guard, last: `write_run_
    transcript` already catches its own composition and its own `OSError`, and putting it after means a
    broken tree print cannot cost the file. What a guarded fault costs is stated where it happens rather
    than swallowed - one warn naming what was lost."""
    try:
        # A header, because the two blocks can legitimately name the same step differently: the per-step
        # line uses `command or label` (the exact-command identity, netctl#897) and a tree row uses the
        # row's display identity, which for a hand-built pipeline is the prose label. Without a line
        # saying so, a CI log lists one run twice under two vocabularies.
        log.info("the same steps, as the TUI draws them:")
        # The ONE place the shared glyph vocabulary reaches a stream this kernel did not open, so it is
        # the one place that asks what that stream can encode (si#161). See `icons_for`.
        for line in render_tree(build_rows(pipeline), icons=icons_for(sys.stdout)):
            print(line, flush=True)
        # The reasons go BETWEEN the tree and the verdict: the tree says which steps failed, this says
        # why each of them did, and the count stays the last line so the verdict is where it has always
        # been. A green run reaches none of this (#49).
        for line in failure_report(pipeline):
            print(line, flush=True)
    except Exception as exc:  # noqa: BLE001 - see the paragraph above; nothing here may replace a verdict
        log.warn(f"{pipeline.name}: the retraced tree could not be printed ({exc}); the transcript below "
                 f"carries the same steps")
    # ONE call for both outcomes: what goes into the transcript does not depend on the verdict, and the
    # verdict lines are the last thing a reader sees either way.
    write_run_transcript(pipeline, started)


def run_headless(pipeline: Pipeline, verbose: bool | None = None) -> int:
    """Run every step in the order `schedule_for` says, printing the same info/ok/warn lines the rest of
    netctl uses (and a streaming step's lines live, indented), and return the overall exit code (0 iff
    every step passed). This is the TTY-fallback / CI path - no Textual. The overall result is the worst
    step's rc, never derived from any UI state.

    THE WALK ITSELF IS `run_plan`'S (si#147), not this function's. It was a `for` loop over
    `pipeline.steps` here and a second one in the TUI's worker thread, and the two agreed about the abort
    set, the skip marking and the state transitions only because somebody kept them agreeing. A plan may
    now declare that some of its steps need not wait for each other, and that is exactly the change that
    would have been made in one runner and not the other. What is left here is the printing - and a fan's
    printing is its own problem, argued at `_HeadlessOutput`.

    An `action` step CAPTURES its output instead of streaming it, so nothing of it has been shown when it
    returns: this runner prints it (netctl#1073). Before the fix only `.ok`/`.rc` were read here and the
    text died with the Outcome - the TUI's details pane was its only reader - so a failing gate printed
    `failed (rc 1)` and swallowed the diagnosis it had just composed, on exactly the runs (CI, the in-`up`
    rebuild) nobody watches. Failures always print; a PASSING step's output only when `verbose` (default:
    the DELIVERY_VERBOSE env var), so a green `doctor` stays a checklist. A `stream` step OUTSIDE a fan is
    never reprinted: its lines already went out live through `emit` and `outcome.output` is the same text
    again. Inside a fan they did not go out live - they were held so the log stays readable - so there
    they are printed once, on flush, whatever the rc. A green build's log must not get shorter for having
    been faster.

    After the last step it prints the SAME tree the TUI draws (netctl#1276), indented, with each row's
    final icon - so a CI log and a TTY show one structure in one vocabulary. It goes at the END rather than
    up front on purpose: the tree's value is the aggregate verdicts, which only exist once the leaves have
    run, and the plan itself is already implied by the per-step lines above it.

    A RED run then adds `failure_report` between that tree and the verdict line (#49): the tree says which
    steps failed, the report says why each of them did, and the count stays last. A green run adds
    nothing - the normal case must not pay for the exceptional one, which is #49's own acceptance.

    That tree is also the ONLY thing this runner prints in the shared glyph vocabulary, and on a stream
    whose encoding cannot carry the glyphs it prints their ASCII twin instead (si#161) - a Windows CI
    job with a redirected stdout used to end a GREEN pipeline with a `UnicodeEncodeError` from this very
    loop, after the exit code had already been decided. The transcript is unaffected: `steplog` writes it
    UTF-8 by name, so the file keeps the glyphs whatever the console can show.

    It also leaves a RUN TRANSCRIPT behind (si#148 item 3), and headless is not the afterthought path for
    it: the run that most needs to be attachable to a ticket is a red CI run, and this is the runner CI
    uses. See `write_run_transcript`."""
    started = datetime.now()
    show_passing = _verbose_env() if verbose is None else verbose
    try:
        run_plan(pipeline, _HeadlessOutput(pipeline, show_passing).hooks())
    finally:
        # THE RECORD IS WRITTEN WHATEVER LEAVES THE WALK (si#182). `Step.run` turns a body's crash into a
        # verdict, so the ordinary way out of `run_plan` is a return - but three things still leave here
        # by raising, and each is a run whose record is worth more than most: a `KeyboardInterrupt` on a
        # twenty-minute build, a `SystemExit` from inside a body, and a fault in a runner's own hook.
        # Without this, those three lose the retraced tree, the failure report and the transcript, which
        # is exactly the loss si#182 is about - and the transcript is the half that outlives the terminal.
        _write_the_record(pipeline, started)
    # COUNTED FROM THE STATES, not tallied in the loop (si#147). A counter incremented as each step
    # returned was correct while one step returned at a time and would have been a race the moment two
    # did. It also had a second reader disagreeing with it: `overall_rc` and `failure_report` already
    # derive their answers from the same states, so the count is now the third derivation rather than an
    # independent tally that could differ from either.
    failures = sum(1 for step in pipeline.steps if step.state == StepState.FAILED)
    skipped = sum(1 for step in pipeline.steps if step.state == StepState.SKIPPED)
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
