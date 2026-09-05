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

  1. A `Step`'s state is computed from an `Outcome`, and an `Outcome` is a subprocess rc plus its output. A
     step runs a whole CLI command in another process; the only thing that survives that boundary is the
     rc - and the rc, by the paragraph above, deliberately cannot carry this. A third state would therefore
     be a state nothing on that layer could ever legitimately set.
  2. `SKIPPED` already occupies the neighbouring meaning: NOT RUN because a failure aborted the subtree
     this step belongs to. A gate whose setup failed is not that. It ran, it did work, and it failed. Its
     step is `FAILED` and should stay `FAILED`; what differs is not the step's fate but WHAT THE GATE
     LEARNED, which is a property of the gate's result and of nothing else.

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
STAMP = "test-verdict.json"

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
    """

    gate: str
    verdict: Verdict
    rc: int = 0
    stage: str = ""

    def __post_init__(self) -> None:
        # A stage belongs to the two outcomes in which the suite never ran, and to no other: `not-run`
        # names the gate that refused (`precondition`), `setup-failed` the preparation that broke. On a
        # verdict ABOUT the product a stage would be a claim that something outside the suite decided it,
        # which is the confusion running the other way.
        if self.stage and self.verdict.ran:
            raise ValueError(f"'{self.gate}': a stage names where the run stopped SHORT of the suite, so "
                             f"it cannot be carried by a '{self.verdict.value}' verdict")
        if self.verdict is Verdict.PASSED and self.rc != 0:
            raise ValueError(f"'{self.gate}': a passing gate cannot carry rc {self.rc}")

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.PASSED

    @property
    def line(self) -> str:
        """The one sentence a human reads - in the log, in the allure environment, in the stamp.

        It says the outcome, what produced it and, for the two outcomes that are not evidence, WHAT THAT
        MEANS. "failed (rc 1)" alone is the ambiguity this module removes; spelling out "the suite never
        ran" is the removal.
        """
        if self.verdict is Verdict.PASSED:
            return "passed"
        if self.verdict is Verdict.FAILED:
            return f"failed (rc {self.rc}) - the suite ran and reported failures"
        if self.verdict is Verdict.SETUP_FAILED:
            return (f"setup failed ({self.stage}, rc {self.rc}) - the suite never ran, so this says "
                    f"nothing about the product")
        return (f"not run ({self.stage or PRECONDITION}, rc {self.rc}) - nothing was prepared, cleared or "
                f"written, and the previous archive stands")

    def as_dict(self) -> dict[str, object]:
        """The stamp's per-gate entry: the machine-readable fields AND the sentence, because a reader who
        opens the file by hand should not have to reconstruct it from an enum value."""
        return {"gate": self.gate, "verdict": self.verdict.value, "rc": self.rc,
                "stage": self.stage, "line": self.line}


@dataclass(frozen=True)
class RunVerdict:
    """Every gate of ONE invocation, and the single claim that invocation is entitled to make."""

    gates: tuple[GateVerdict, ...] = ()

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
    def line(self) -> str:
        worst = self.worst
        if worst is None:
            return "not run - no gate reported"
        return worst.line if worst.ok else f"{worst.gate}: {worst.line}"

    def environment(self) -> dict[str, str]:
        """What the allure report's Environment widget shows: the run's claim, plus one line per gate.

        This is the half a later reader actually meets. The report is the artefact that outlives the
        terminal, so the distinction has to be legible INSIDE it and not only beside it.
        """
        env = {"verdict": self.verdict.value, "verdict.summary": self.line}
        for gate in self.gates:
            env[f"verdict.gate.{gate.gate}"] = gate.line
        return env

    def as_dict(self, *, now: datetime | None = None) -> dict[str, object]:
        return {"written": (now or datetime.now()).isoformat(timespec="seconds"),
                "verdict": self.verdict.value, "line": self.line,
                "gates": [gate.as_dict() for gate in self.gates]}


def write_stamp(reports_dir: str, run: RunVerdict, *, now: datetime | None = None) -> str:
    """Write this invocation's stamp beside the report dir and return its path.

    ALWAYS, including for a run that never started. That is the whole fix: the stamp is written from the
    knowledge the caller has at the end of the invocation, never from inside the preparation that may not
    survive, so there is no path through the code on which a run leaves the previous run's verdict
    standing as if it were its own.
    """
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, STAMP)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(run.as_dict(now=now), fh, indent=2, sort_keys=False)
        fh.write("\n")
    return path


def read_stamp(reports_dir: str) -> dict[str, object] | None:
    """The stamp of the last invocation, or None where there is none. A missing stamp is not an error - it
    is a report dir nobody has run a gate into - but it is also not a pass, and returning None rather than
    an empty verdict keeps a caller from spelling it as one."""
    path = os.path.join(reports_dir, STAMP)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else None
