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
"""
from __future__ import annotations

import json
import os
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

    @property
    def ran(self) -> bool:
        """True when the suite actually executed, so the outcome is a statement about the PRODUCT.

        The whole point of the module in one predicate: only `PASSED` and `FAILED` are evidence. The other
        two are reports about the lab, and a reader who treats them as evidence draws the conclusion this
        module exists to prevent.
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
        """
        return {Verdict.PASSED: 0, Verdict.FAILED: 1, Verdict.NOT_RUN: 2, Verdict.SETUP_FAILED: 3}[self]


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
    """

    gate: str
    verdict: Verdict
    rc: int = 0
    stage: str = ""
    detail: str = ""

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
    def wrote_results(self) -> bool:
        """True when some gate of this run created or filled the run's results dir - the ONE condition
        under which the run's verdict may be written into the archive.

        `NOT_RUN` is exactly "nothing was prepared, cleared or written", so a run made only of those must
        leave the last real run's archive alone; writing into it would be the original defect with the
        sign flipped. An impl-only run cannot reach here with this True by accident: `declared` requires
        exactly one CLEARING gate, it must be the first, and an impl gate is forbidden from declaring the
        clear - so every valid taxonomy opens with a pytest gate that owns the dir.
        """
        return any(gate.verdict is not Verdict.NOT_RUN for gate in self.gates)

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
