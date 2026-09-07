"""WHY a gate is red - the four outcomes, and the record the later reader gets (#30).

A gate can be red for two different reasons, and an exit code cannot tell them apart:

  - THE PROBE IS RED. The suite ran and found something. This is a statement about the product.
  - THE SETUP FAILED. The suite never ran, because the preparation fell over first. This is a statement
    about the lab, and it says NOTHING about the product.

Both are rc != 0. For the operator at the screen that is enough - the output is right there. For whoever
reads the archived report a week later it is not, and the failure that produced this module is exactly
that gap: a product's session fixture wrote its stamp only AFTER provisioning, so a run whose setup fell
over wrote no stamp at all and the archive still showed `passed` with last week's date. The run was red
and the record said green. BEING red and SAYING red are two different promises.

WHY THIS IS NOT A RETURN VALUE. An rc is one bit of judgement: zero or not. Widening it - a reserved 2 for
"setup failed", say - would push the distinction through the one channel every caller already interprets
(`if rc: fail`), and CI, shells and `simplon.cli._rc` would each have to learn a private convention to
avoid mistaking a setup failure for a passing run. So the rc keeps meaning exactly what it means today,
and the distinction lives in what gets WRITTEN: the stamp beside the report, the allure environment inside
it, and the summary line in the log.

WHY NOT A THIRD `StepState`. `simplon.orchestrator.steps.StepState` was the obvious candidate and it is the
wrong one, for two reasons that are worth stating because the question will be asked again:

  1. THE LOAD-BEARING ONE. `SKIPPED` already occupies the neighbouring meaning: NOT RUN because a failure
     aborted the subtree this step belongs to. A gate whose setup failed is not that. It ran, it did work,
     and it failed. Its step is `FAILED` and should stay `FAILED`; what differs is not the step's fate but
     WHAT THE GATE LEARNED, which is a property of the gate's result and of nothing else. A third state
     would put an answer to a second question into a vocabulary that answers the first.
  2. `Step.run` derives its state from `Outcome.ok` - that is, from the rc alone. The output travels
     alongside it and both runners print it, but no state is read out of it, and the rc by the paragraph
     above deliberately does not carry this. So a third state would have nothing to be computed FROM
     without inventing the reserved rc the paragraph above rejects. (This is the supporting argument, not
     the decisive one: a state could in principle be set from something other than the rc. The reason not
     to is (1).)

So this is a property of the GATE RESULT. `simplon.tasks.testrun` produces one per gate, and the run's
record is what a later reader consults.

THE FOURTH OUTCOME, and why it is not just "red". A gate whose `precondition` says no aborts BEFORE the
shared results dir is cleared, deliberately: nothing ran, so the archive of the last real run must survive
untouched. That run therefore has nothing to say about the product either, and it says so as `not-run`
rather than borrowing the vocabulary of a run that happened.

THE FIFTH OUTCOME, and why it is not `failed` (#55). A run a signal ended did not report anything - it was
shot. The evidence is right there in the exit code: `subprocess.returncode` is negative and carries the
signal number, which is POSIX's own encoding and not a convention invented here. But the four outcomes
above offered no word for it, so it arrived as `FAILED` and the record said "the suite ran and reported
failures" about a run whose output was empty. Measured three times in one day on one product, with three
different causes - a rate limit, a stray `gh auth refresh`, an unexplained hang - and the sentence was the
same false one every time. `KILLED` is that case: `ran` is False, like the other two non-verdicts, and the
line names the SIGNAL rather than the negative number, because `SIGTERM` tells a reader that something
asked the run to stop and `-15` tells them nothing.

WHERE THAT DERIVATION IS HONEST AND WHERE IT IS NOT. A negative rc means "terminated by signal" only when
it is a CHILD PROCESS'S wait status. A number returned by a Python callable is just a number, and this
repository already has one that answers -1 to mean "could not parse" (`simplon.waits.device_count`). So
`of_subprocess` is the seam and it is named after what it may be applied to: `simplon.tasks.testrun` hands
it the rc it read off the pytest child and nothing else, and a gate whose runner is the product's own stays
exactly as opaque as it was.

AND THE EXIT CODE, which is the same defect on the way out. `sys.exit(-15)` is taken modulo 256, so a shell
reads 241 - measured - a number that is neither the signal nor anything reserved and that looks exactly
like an ordinary exit code. `exit_code` translates a signal rc to 128+n instead, which is what every shell
already writes into `$?` for a child killed by signal n. This is NOT the widened rc the paragraph above
rejects: it carries no new distinction for a caller to decode and no caller has to learn a private
convention. It only stops the distinction the operating system already made from being mangled on the way
through `sys.exit`.
"""
from __future__ import annotations

import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# The stamp's file name, beside the report dir and NOT inside the allure results - a `clear` gate wipes
# the results, and a record that a run's own first step deletes is no record.
#
# An EXPLORATORY run (one carrying `-k` or any other passthrough arg) gets its own, for exactly the reason
# it already gets its own results dir and its own archive prefix: it is PARTIAL. A one-test hunt writing
# over the canonical stamp produces two records of the same directory that contradict each other in
# silence - a green `-k` stamping `passed` over the finding of a red full gate is the worse direction, and
# it is the same "a partial run that does not look like one" the quarantine rule exists for.
STAMP = "test-verdict.json"
STAMP_FILTERED = "test-verdict-filtered.json"

# The setup stages the KERNEL itself sequences and can therefore name on its own.
PRECONDITION = "precondition"
PREAMBLE = "preamble"


class Verdict(str, Enum):
    """What a gate learned. Ordered by nothing; `rank` states the precedence explicitly."""

    PASSED = "passed"
    FAILED = "failed"
    SETUP_FAILED = "setup-failed"
    NOT_RUN = "not-run"
    KILLED = "killed"

    @property
    def ran(self) -> bool:
        """True when the suite actually executed, so the outcome is a statement about the PRODUCT.

        The whole point of the module in one predicate: only `PASSED` and `FAILED` are evidence. The other
        three are reports about the lab or about the invocation - a setup that broke, a gate that refused,
        a run a signal ended - and a reader who treats them as evidence draws the conclusion this module
        exists to prevent.
        """
        return self in (Verdict.PASSED, Verdict.FAILED)

    @property
    def rank(self) -> int:
        """How WEAK the claim is - higher is weaker, and the run reports the weakest claim it contains.

        Not "how bad": a red suite is worse news than a broken lab, but it is a stronger statement. A run
        that contains a gate which never ran cannot claim to have probed the product, whatever its other
        gates found, so the non-verdicts outrank the verdicts. Between the two non-verdicts the more
        specific one wins, because `setup-failed` names a stage a reader can act on where `not-run` names
        only an abort.

        `killed` outranks all of them, and that is the one placement worth arguing. A signal did not come
        from the suite, the lab or the manifest: it ended the INVOCATION from outside, so it is the fact
        that explains whatever else the run appears to have found - a gate whose preamble then fell over, a
        suite that then reported nothing. A reader told "setup failed" about a run that was actually shot
        goes looking for a broken lab that may be perfectly healthy.
        """
        return {Verdict.PASSED: 0, Verdict.FAILED: 1, Verdict.NOT_RUN: 2, Verdict.SETUP_FAILED: 3,
                Verdict.KILLED: 4}[self]


@dataclass(frozen=True)
class GateVerdict:
    """One gate's result: not only whether it was red, but whether it was red ABOUT anything.

    `stage` names where the run stopped short of the suite - the gate that refused, or the preparation
    that broke - and is empty for the two outcomes that are about the product. It is a free string rather
    than an enum, deliberately: the kernel names the two stages
    it sequences itself (`precondition`, `preamble`), and a suite that prepares its own lab inside a
    session fixture names its own - `provision`, `sweep`, whatever it calls the step - through the marker
    file `simplon.tasks.testrun` hands it. A vocabulary the kernel fixed would force every product to
    describe its lab in the kernel's words, which is precisely the product knowledge the kernel must not
    hold.

    `detail` replaces the explanatory half of `line` for a step that is not a pytest gate. The default
    wording talks about A SUITE, because that is what a gate runs; the report step is the counter-example
    that forced the field - it renders an archive and runs no tests at all, so "the suite ran and reported
    failures" would be a false statement of exactly the kind this module exists to remove, produced by the
    module itself.

    `owned_results` SAYS WHETHER THIS GATE TOOK THE RUN'S RESULTS DIR (si#69) - cleared it, filled it, or
    both. It is a fact about the artefact and not about the product, which is why it sits beside the
    verdict rather than inside it, and it has to be REPORTED by the producer rather than derived from the
    verdict, because the two questions have different answers. A gate the kernel ran itself owned the dir
    whatever it found; a gate whose runner is the product's own owns it only if the taxonomy said so, and
    writes into it in no case at all. `RunVerdict.owns_results` is the whole reason it exists: that is the
    condition under which the run's verdict may be written into the archive, and it used to be guessed
    from `verdict is not NOT_RUN` - which said True for a run of product-owned gates that had written
    nothing anywhere. It was unreachable while the load path refused such a taxonomy; si#61 let one load.
    """

    gate: str
    verdict: Verdict
    rc: int = 0
    stage: str = ""
    detail: str = ""
    owned_results: bool = False

    def __post_init__(self) -> None:
        # A stage belongs to the two outcomes in which the suite never ran, and to no other: `not-run`
        # names the gate that refused (`precondition`), `setup-failed` the preparation that broke. On a
        # verdict ABOUT the product a stage would be a claim that something outside the suite decided it,
        # which is the confusion running the other way.
        if self.stage and self.verdict.ran:
            raise ValueError(f"'{self.gate}': a stage names where the run stopped SHORT of the suite, so "
                             f"it cannot be carried by a '{self.verdict.value}' verdict")
        # The pair of contradictions, and BOTH directions matter. A passing gate with a non-zero rc was
        # obvious; the reverse - a red verdict carrying rc 0 - is the one that got through review, and it
        # is the worse of the two: `simplon.cli._rc` turns a 0 into a green exit, so the record would say
        # "setup failed" while CI reported success. A red run that exits green is the whole failure class
        # this module is against, so the value object refuses to hold that pair at all and every producer
        # has to decide what rc it means.
        if self.verdict is Verdict.PASSED and self.rc != 0:
            raise ValueError(f"'{self.gate}': a passing gate cannot carry rc {self.rc}")
        # A `killed` verdict is READ OFF a signal - it is the one outcome that is observed rather than
        # decided - so a non-negative rc names no signal and `line` would have nothing to spell out.
        # Checked before the rc-0 rule below so this outcome always gets the reason that applies to it.
        if self.verdict is Verdict.KILLED and self.rc >= 0:
            raise ValueError(f"'{self.gate}': a 'killed' verdict is read off a signal, so it cannot carry "
                             f"rc {self.rc} - only a child's negative wait status names one")
        if self.verdict is not Verdict.PASSED and self.rc == 0:
            raise ValueError(f"'{self.gate}': a '{self.verdict.value}' verdict cannot carry rc 0 - a red "
                             f"record with a green exit code is the confusion this exists to prevent")

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.PASSED

    @property
    def line(self) -> str:
        """The one sentence a human reads - in the log, in the allure environment, in the stamp.

        It says the outcome, what produced it and, for the two outcomes that are not evidence, WHAT THAT
        MEANS. "failed (rc 1)" alone is the ambiguity this module removes; spelling out "the suite never
        ran" is the removal. `detail`, where a producer set one, replaces that explanatory half - the
        outcome and the rc are the value object's to state, the sentence about WHAT ran is the producer's.
        """
        if self.verdict is Verdict.PASSED:
            return "passed"
        if self.verdict is Verdict.FAILED:
            return f"failed (rc {self.rc}) - {self.detail or 'the suite ran and reported failures'}"
        if self.verdict is Verdict.KILLED:
            # THE SIGNAL NAME, AND NOT THE NUMBER. Every other line here carries its rc because the rc is
            # what a reader would otherwise go looking for; here it is the thing that misleads - it reads
            # as an exit code - and the stamp's machine-readable `rc` field keeps it anyway.
            return (f"killed ({signal_name(self.rc)}) - "
                    + (self.detail or "the suite was ended by a signal and reported nothing, so this says "
                                      "nothing about the product"))
        if self.verdict is Verdict.SETUP_FAILED:
            return (f"setup failed ({self.stage}, rc {self.rc}) - "
                    + (self.detail or "the suite never ran, so this says nothing about the product"))
        return (f"not run ({self.stage or PRECONDITION}, rc {self.rc}) - "
                + (self.detail or "nothing was prepared, cleared or written, and the previous archive "
                                  "stands"))

    def as_dict(self) -> dict[str, object]:
        """The stamp's per-gate entry: the machine-readable fields AND the sentence, because a reader who
        opens the file by hand should not have to reconstruct it from an enum value."""
        return {"gate": self.gate, "verdict": self.verdict.value, "rc": self.rc,
                "stage": self.stage, "line": self.line}

    def environment(self) -> dict[str, str]:
        """This ONE gate's line, and nothing else.

        Deliberately not the run's keys. A gate writes into a results dir several gates share, and
        `allure.write_environment` merges last-wins, so a gate that stated the RUN's verdict from its own
        knowledge alone would have a later green gate overwrite `verdict=setup-failed` with
        `verdict=passed` - the precedence rule defeated in the one artefact it was built to protect. Whoever
        holds every gate of the run writes the run's keys; a single gate writes its own.
        """
        return {f"verdict.gate.{self.gate}": self.line}


@dataclass(frozen=True)
class RunVerdict:
    """Every gate of ONE invocation, and the single claim that invocation is entitled to make.

    `filtered` marks an EXPLORATORY invocation - one carrying passthrough args, which by construction ran
    a subset. It changes where the stamp goes (`STAMP_FILTERED`) and says so in the record, because the
    quarantine is only half a quarantine if the archive is separated and the verdict beside it is not.
    """

    gates: tuple[GateVerdict, ...] = ()
    filtered: bool = False

    @property
    def worst(self) -> GateVerdict | None:
        """The gate carrying the weakest claim - the one the run as a whole has to report. None for a run
        with no gates at all, which is the empty record and not a green one."""
        return max(self.gates, key=lambda g: g.verdict.rank, default=None)

    @property
    def verdict(self) -> Verdict:
        """The run's own outcome. A run with no gates is `NOT_RUN`: nothing happened, and calling that
        `passed` is the exact confusion this module is against."""
        worst = self.worst
        return worst.verdict if worst is not None else Verdict.NOT_RUN

    @property
    def owns_results(self) -> bool:
        """True when some gate of this run took the run's results dir - the ONE condition under which the
        run's verdict may be written into the archive.

        IT ASKS THE GATES RATHER THAN THEIR VERDICTS (si#69), and that is the fix. It used to read
        `verdict is not NOT_RUN`, on the argument that `NOT_RUN` is exactly "nothing was prepared,
        cleared or written" and every other outcome implies a dir that was taken - true of a gate the
        kernel runs, false of one whose runner is the product's own, which returns a number and touches
        nothing. Measured: `wrote_results: True` beside `results dir: []`.

        The old docstring answered the objection by saying such a run could not reach here - `declared`
        required exactly one CLEARING gate, it had to be the first, and an impl gate was forbidden from
        declaring the clear, so every valid taxonomy opened with a pytest gate that owned the dir. That
        was a statement about the LOAD PATH and not about this property, and the property is what a
        caller holds. si#61 let an impl-only taxonomy load; the load-time scaffolding is gone and the
        seam now stands on its own, which is what it was always supposed to do.

        The value each gate reports is `owned_results`; a run with no gates at all owns nothing.
        """
        return any(gate.owned_results for gate in self.gates)

    @property
    def line(self) -> str:
        worst = self.worst
        if worst is None:
            return "not run - no gate reported"
        said = worst.line if worst.ok else f"{worst.gate}: {worst.line}"
        # An exploratory run says so FIRST. Its record lives in its own file, but a reader who was handed
        # only the sentence must not read a one-test hunt as the verdict of a full gate.
        return f"partial run - {said}" if self.filtered else said

    def environment(self) -> dict[str, str]:
        """What the allure report's Environment widget shows: the run's claim, plus one line per gate.

        This is the half a later reader actually meets. The report is the artefact that outlives the
        terminal, so the distinction has to be legible INSIDE it and not only beside it.
        """
        env = {"verdict": self.verdict.value, "verdict.summary": self.line}
        if self.filtered:
            env["verdict.partial"] = "true"
        for gate in self.gates:
            env.update(gate.environment())
        return env

    def as_dict(self, *, now: datetime | None = None) -> dict[str, object]:
        return {"written": (now or datetime.now()).isoformat(timespec="seconds"),
                "verdict": self.verdict.value, "line": self.line, "filtered": self.filtered,
                "gates": [gate.as_dict() for gate in self.gates]}


def signal_name(rc: int) -> str:
    """The signal a child's negative wait status names - `SIGTERM` for -15 - or a plain rendering of the
    number where this platform knows no signal by it.

    The fallback is not decoration. `signal.Signals` knows only the signals the running platform defines,
    and a wait status is produced by whatever killed the child, so a number outside that set is possible
    and has to keep reading as a signal instead of raising from inside a log line.
    """
    try:
        return signal.Signals(-rc).name
    except ValueError:
        return f"signal {-rc}"


def of_subprocess(rc: int) -> Verdict:
    """What a gate learned from the exit status of the CHILD PROCESS it ran: green, red, or shot.

    Only from a child's status - that is the whole precondition, and it is in the name because getting it
    wrong invents a signal. A Python callable's return value may be negative for reasons of its own, and a
    `killed (SIGHUP)` conjured out of some body's `return -1` would be a fabricated statement about the
    product, produced by the very module that exists to remove them.
    """
    if rc < 0:
        return Verdict.KILLED
    return Verdict.PASSED if rc == 0 else Verdict.FAILED


def exit_code(rc: int) -> int:
    """The number a gate hands the PROCESS, given the rc it observed from its child.

    A pass-through for everything but a signal status, which does not survive `sys.exit` intact: the value
    is taken modulo 256, so -15 leaves the process as 241 and -9 as 247 - measured - and neither number
    says "signal" to anything downstream. 128+n is what a shell already writes into `$?` for a child killed
    by signal n, so it is the one translation nobody has to be told about; and red stays red, because
    128+n is never zero.
    """
    return 128 - rc if rc < 0 else rc


def stamp_name(*, filtered: bool = False) -> str:
    """Which stamp a run writes: the canonical one, or the exploratory run's own."""
    return STAMP_FILTERED if filtered else STAMP


def write_stamp(reports_dir: str, run: RunVerdict, *, now: datetime | None = None) -> str:
    """Write this invocation's stamp beside the report dir and return its path.

    ALWAYS, including for a run that never started. That is the whole fix: the stamp is written from the
    knowledge the caller has at the end of the invocation, never from inside the preparation that may not
    survive, so there is no path through the code on which a run leaves the previous run's verdict
    standing as if it were its own.

    WHICH stamp comes from the run itself: an exploratory run writes its own file and cannot touch the
    canonical one, the same rule its results already follow.
    """
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, stamp_name(filtered=run.filtered))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(run.as_dict(now=now), fh, indent=2, sort_keys=False)
        fh.write("\n")
    return path


def read_stamp(reports_dir: str, *, filtered: bool = False) -> dict[str, object] | None:
    """The stamp of the last invocation, or None where there is none. A missing stamp is not an error - it
    is a report dir nobody has run a gate into - but it is also not a pass, and returning None rather than
    an empty verdict keeps a caller from spelling it as one."""
    path = os.path.join(reports_dir, stamp_name(filtered=filtered))
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else None
