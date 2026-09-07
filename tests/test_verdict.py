"""Unit tests for simplon.verdict (#30): the four outcomes a gate can have, and the record a later reader
gets.

The thing under test is not a formatter. It is the claim that "red" is two different statements - the suite
ran and found something, versus the suite never ran - and that the second one survives into what is
written. So what is pinned here is the WORDING and the precedence, because those are what a later reader
actually meets; that the rc of both cases stays identical - deliberately, since an rc is one bit - is
pinned next to the runner, in tests/test_tasks_testrun.py.

AAA throughout, negative cases included.
"""
import json
import shlex
import signal
import sys

import pytest

from simplon import run as run_module
from simplon import verdict as verdict_module
from simplon.verdict import GateVerdict, RunVerdict, Verdict


# --- the vocabulary ---------------------------------------------------------------------------------------


def test_onlyAPassedOrFailedGateIsEvidenceAboutTheProduct():
    # arrange / act / assert: the predicate the whole module turns on
    assert Verdict.PASSED.ran and Verdict.FAILED.ran
    assert not Verdict.SETUP_FAILED.ran and not Verdict.NOT_RUN.ran and not Verdict.KILLED.ran


def test_everyOutcomeIsRanked_soANewOneCannotBeAddedWithoutSayingHowWeakItIs():
    # arrange / act / assert: `rank` is a dict lookup, and a member missing from it would not degrade -
    # `RunVerdict.worst` would raise on the first run that produced it
    assert sorted(v.rank for v in Verdict) == list(range(len(Verdict)))


def test_aSetupFailureSaysTheSuiteNeverRan_ratherThanOnlyThatItWasRed():
    # arrange
    gv = GateVerdict("system", Verdict.SETUP_FAILED, 1, "preamble")

    # act
    line = gv.line

    # assert: the two things a reader needs - where it broke, and what may NOT be concluded from it
    assert "setup failed" in line
    assert "preamble" in line
    assert "never ran" in line
    assert "nothing about the product" in line


def test_aRedSuiteSaysItRanAndReportedFailures_soItIsNotMistakenForABrokenLab():
    # arrange
    gv = GateVerdict("system", Verdict.FAILED, 1)

    # act / assert
    assert gv.line == "failed (rc 1) - the suite ran and reported failures"


def test_aGateThatNeverStartedSaysTheEarlierArchiveStands():
    # arrange: the precondition refused, so nothing was cleared and nothing written into the results
    gv = GateVerdict("system", Verdict.NOT_RUN, 7, "precondition")

    # act / assert
    assert "not run" in gv.line and "precondition" in gv.line
    assert "previous archive stands" in gv.line


def test_aStageCannotRideOnAVerdictAboutTheProduct_becauseTheSuiteDidRunThere():
    # arrange / act / assert: a stage names where the run stopped SHORT of the suite; on a red suite it
    # would claim something outside the suite decided the outcome
    with pytest.raises(ValueError, match="stopped SHORT of the suite"):
        GateVerdict("system", Verdict.FAILED, 1, "preamble")


def test_aPassingGateCannotCarryANonZeroRc_becauseThatPairIsAContradiction():
    # arrange / act / assert
    with pytest.raises(ValueError, match="cannot carry rc 1"):
        GateVerdict("system", Verdict.PASSED, 1)


# --- the run's own claim ----------------------------------------------------------------------------------


def test_aRunReportsTheWeakestClaimItContains_soABrokenSetupOutranksARedSuite():
    # arrange: one gate probed the product and found something; another never probed at all
    run = RunVerdict((GateVerdict("acceptance", Verdict.SETUP_FAILED, 1, "preamble"),
                      GateVerdict("system", Verdict.FAILED, 1)))

    # act / assert: the run cannot claim to have probed the product, whatever the OTHER gate found - and
    # the gate order must not decide it, so the weakest claim is deliberately not the last one here
    assert run.verdict is Verdict.SETUP_FAILED
    assert run.line.startswith("acceptance: setup failed")


def test_theMoreSpecificNonVerdictWins_becauseItNamesAStageAReaderCanActOn():
    # arrange: the weaker claim FIRST, so a run that simply reported its last gate would get this wrong
    run = RunVerdict((GateVerdict("b", Verdict.SETUP_FAILED, 1, "preamble"),
                      GateVerdict("a", Verdict.NOT_RUN, 7, "precondition")))

    # act / assert
    assert run.verdict is Verdict.SETUP_FAILED


def test_aRunWithNoGateAtAllIsNotRun_ratherThanPassed():
    # arrange / act / assert: the empty record is the one that must never read as green
    assert RunVerdict().verdict is Verdict.NOT_RUN
    assert RunVerdict().line == "not run - no gate reported"


def test_anAllGreenRunSaysPassedWithoutNamingAGate():
    # arrange
    run = RunVerdict((GateVerdict("system", Verdict.PASSED), GateVerdict("acceptance", Verdict.PASSED)))

    # act / assert
    assert run.verdict is Verdict.PASSED and run.line == "passed"


def test_theAllureEnvironmentCarriesTheRunsClaimAndOneLinePerGate():
    # arrange
    run = RunVerdict((GateVerdict("system", Verdict.SETUP_FAILED, 1, "provision"),
                      GateVerdict("acceptance", Verdict.PASSED)))

    # act
    env = run.environment()

    # assert: what somebody handed only the HTML archive sees
    assert env["verdict"] == "setup-failed"
    assert env["verdict.summary"].startswith("system: setup failed (provision, rc 1)")
    assert env["verdict.gate.acceptance"] == "passed"


# --- the stamp beside the report --------------------------------------------------------------------------


def test_write_stamp_recordsTheRunEvenWhenNothingRan_becauseSilenceReadsAsTheLastGreenRun(tmp_path):
    # arrange: the exact case that produced this module - a run whose setup fell over
    reports = tmp_path / "reports"
    run = RunVerdict((GateVerdict("system", Verdict.SETUP_FAILED, 1, "provision"),))

    # act
    path = verdict_module.write_stamp(str(reports), run)

    # assert: the file exists and says WHY, rather than being absent and leaving last week's verdict up
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert path.endswith("test-verdict.json")
    assert data["verdict"] == "setup-failed"
    assert data["gates"][0]["stage"] == "provision"
    assert "never ran" in data["gates"][0]["line"]
    assert data["written"]


def test_write_stamp_overwritesTheEarlierRunsRecord_soTheStampIsAlwaysThisInvocations(tmp_path):
    # arrange: a green stamp from an earlier run
    reports = str(tmp_path / "reports")
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.PASSED),)))

    # act: a later run whose setup fell over
    verdict_module.write_stamp(reports,
                               RunVerdict((GateVerdict("system", Verdict.SETUP_FAILED, 1, "provision"),)))

    # assert: no trace of the green one is left to be read as current
    data = verdict_module.read_stamp(reports)
    assert data is not None and data["verdict"] == "setup-failed"


def test_read_stamp_returnsNothingForAReportDirNobodyHasRunAGateInto(tmp_path):
    # arrange / act / assert: a missing stamp is not an error and, above all, not a pass
    assert verdict_module.read_stamp(str(tmp_path)) is None


# --- the invariant that was missing in the other direction (#30, review 2) --------------------------------


def test_aRedVerdictCannotCarryRcZero_becauseThatIsARedRecordWithAGreenExitCode():
    # arrange / act / assert: the pair `simplon.cli._rc` would turn into a successful process while the
    # record says the setup broke - this ticket's failure class with its two halves swapped
    with pytest.raises(ValueError, match="cannot carry rc 0"):
        GateVerdict("system", Verdict.SETUP_FAILED, 0, "provision")
    with pytest.raises(ValueError, match="cannot carry rc 0"):
        GateVerdict("system", Verdict.FAILED, 0)
    with pytest.raises(ValueError, match="cannot carry rc 0"):
        GateVerdict("system", Verdict.NOT_RUN, 0, "precondition")


# --- a step that runs no suite gets its own words (#30, review 3) -----------------------------------------


def test_detail_replacesTheClauseWrittenForAGateThatRunsASuite():
    # arrange: the report step renders an archive and runs no tests at all
    gv = GateVerdict("report", Verdict.FAILED, 1, detail="a render tool was present and wrote no archive")

    # act / assert: the outcome and the rc stay the value object's, the sentence about WHAT ran is the
    # producer's - and the default, which talks about a suite, would be false here
    assert gv.line == "failed (rc 1) - a render tool was present and wrote no archive"
    assert "the suite ran" not in gv.line


def test_aGateWithoutADetailStillGetsTheWordingWrittenForASuite():
    # arrange / act / assert: the default is not lost by making it overridable
    assert GateVerdict("system", Verdict.FAILED, 1).line.endswith("the suite ran and reported failures")


# --- one gate states one gate (#30, review 4) -------------------------------------------------------------


def test_aSingleGatesEnvironmentHoldsOnlyItsOwnLine_neverTheRunsVerdict():
    # arrange
    gv = GateVerdict("system", Verdict.SETUP_FAILED, 1, "preamble")

    # act
    env = gv.environment()

    # assert: the environment write is a last-wins merge over a shared dir, so a gate that also stated
    # `verdict=` would have a later green gate overwrite this finding
    assert list(env) == ["verdict.gate.system"]


def test_owns_results_isFalseForARunWhoseGatesAllRefusedBeforeTouchingAnything():
    # arrange / act / assert: the condition under which the run's verdict may enter the archive at all
    assert not RunVerdict((GateVerdict("a", Verdict.NOT_RUN, 7, "precondition"),)).owns_results
    assert RunVerdict((GateVerdict("a", Verdict.NOT_RUN, 7, "precondition"),
                       GateVerdict("b", Verdict.FAILED, 1, owned_results=True))).owns_results
    assert not RunVerdict().owns_results


def test_owns_results_asksTheGatesAndDoesNotInferOwnershipFromAVerdict():
    # arrange: si#69. A gate whose runner is the product's own returns a number and touches nothing, so
    # `passed` says nothing about a results dir. The old rule - anything but NOT_RUN owned the dir - was
    # true of a gate the kernel runs and false of this one, and it was held out of reach by a load-time
    # refusal rather than by being right
    took_nothing = GateVerdict("ui", Verdict.PASSED, 0)
    took_the_dir = GateVerdict("ui", Verdict.PASSED, 0, owned_results=True)

    # act / assert: the verdict is identical in both and the ownership is not
    assert took_nothing.verdict is took_the_dir.verdict
    assert not RunVerdict((took_nothing,)).owns_results, (
        "a run of gates that took no results dir still claims the archive standing in it")
    assert RunVerdict((took_the_dir,)).owns_results

    # assert: and it holds for every outcome, not only the green one - a red product-owned gate wrote no
    # result file either
    for outcome, rc in ((Verdict.FAILED, 1), (Verdict.SETUP_FAILED, 1), (Verdict.KILLED, -15)):
        stage = "provision" if outcome is Verdict.SETUP_FAILED else ""
        assert not RunVerdict((GateVerdict("ui", outcome, rc, stage),)).owns_results


# --- an exploratory run's record says so (#30, review 1) --------------------------------------------------


def test_anExploratoryRunWritesItsOwnStampFile_soItCannotOverwriteTheCanonicalOne(tmp_path):
    # arrange: the canonical record of a full, red gate
    reports = str(tmp_path / "reports")
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.FAILED, 1),)))

    # act: a green one-test hunt afterwards
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.PASSED),), filtered=True))

    # assert: two records, each about its own kind of run, neither overwriting the other
    assert verdict_module.read_stamp(reports)["verdict"] == "failed"
    assert verdict_module.read_stamp(reports, filtered=True)["verdict"] == "passed"
    assert verdict_module.stamp_name(filtered=True) != verdict_module.stamp_name()


def test_anExploratoryRunSaysSoInItsSentenceAndItsEnvironment():
    # arrange
    run = RunVerdict((GateVerdict("system", Verdict.FAILED, 1),), filtered=True)

    # act / assert: a reader handed only the sentence must not read a one-test hunt as a full gate
    assert run.line.startswith("partial run - ")
    assert run.environment()["verdict.partial"] == "true"
    assert run.as_dict()["filtered"] is True


# --- a run a signal ended (#55) ---------------------------------------------------------------------------


def test_aKilledRunIsNotEvidence_becauseTheSuiteWasShotRatherThanHavingReported():
    # arrange: the exact rc the field produced - a pytest child terminated by SIGTERM
    gv = GateVerdict("unit", Verdict.KILLED, -15)

    # act
    line = gv.line

    # assert: the sentence a reader used to get here claimed the suite had reported failures
    assert not gv.verdict.ran
    assert "the suite ran and reported failures" not in line
    assert "reported nothing" in line and "nothing about the product" in line


def test_aKilledRunNamesTheSignal_andNotTheNegativeNumberThatSaysNothing():
    # arrange / act / assert: SIGTERM tells a reader that something asked the run to stop; -15 does not,
    # and it reads like an exit code while it is there
    assert GateVerdict("unit", Verdict.KILLED, -15).line.startswith("killed (SIGTERM)")
    assert "-15" not in GateVerdict("unit", Verdict.KILLED, -15).line
    assert GateVerdict("unit", Verdict.KILLED, -9).line.startswith("killed (SIGKILL)")
    assert GateVerdict("unit", Verdict.KILLED, -6).line.startswith("killed (SIGABRT)")
    assert GateVerdict("unit", Verdict.KILLED, -11).line.startswith("killed (SIGSEGV)")


def test_signal_name_stillReadsAsASignal_forANumberThisPlatformKnowsNoSignalBy():
    # arrange: a wait status is produced by whatever killed the child, so the set is not closed
    unknown = max(int(member) for member in signal.Signals) + 1

    # act / assert: a fallback rather than a ValueError raised from inside a log line
    assert verdict_module.signal_name(-unknown) == f"signal {unknown}"


def test_aKilledVerdictCannotCarryANonNegativeRc_becauseThenItNamesNoSignal():
    # arrange / act / assert: the outcome is READ OFF a signal, so a value object holding one without a
    # wait status would have `line` spelling out a signal nobody sent
    with pytest.raises(ValueError, match="read off a signal"):
        GateVerdict("unit", Verdict.KILLED, 1)
    with pytest.raises(ValueError, match="read off a signal"):
        GateVerdict("unit", Verdict.KILLED, 0)


def test_aKilledGateOutranksEveryOtherOutcome_soTheSignalIsWhatTheRunReports():
    # arrange: a run in which one gate's lab broke and another was shot - the shot one LAST, so a run that
    # simply reported its final gate would also pass this by accident
    run = RunVerdict((GateVerdict("system", Verdict.SETUP_FAILED, 1, "provision"),
                      GateVerdict("unit", Verdict.KILLED, -15)))

    # act / assert: a reader told "setup failed" about a run that was actually shot hunts a healthy lab
    assert run.verdict is Verdict.KILLED
    assert run.line.startswith("unit: killed (SIGTERM)")
    assert run.environment()["verdict"] == "killed"


def test_aKilledGateOwnedTheResultsDir_soTheRunsRecordStillBelongsInTheArchive():
    # arrange / act / assert: unlike `not-run`, a shot pytest gate had already cleared and started filling
    # the results, so leaving the archive alone would leave the LAST run's verdict standing in it. It is
    # the GATE that reports having taken the dir (si#69) - `simplon.tasks.testrun._written` sets it on
    # every outcome that got that far - rather than the reader inferring it from `killed`
    assert RunVerdict((GateVerdict("unit", Verdict.KILLED, -15, owned_results=True),)).owns_results


def test_write_stamp_recordsTheSignalInTheSentenceAndTheWaitStatusInTheField(tmp_path):
    # arrange
    run = RunVerdict((GateVerdict("unit", Verdict.KILLED, -15),))

    # act
    path = verdict_module.write_stamp(str(tmp_path), run)

    # assert: the human half names the signal, the machine half keeps the number it was read from
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["verdict"] == "killed"
    assert data["gates"][0]["rc"] == -15
    assert "SIGTERM" in data["gates"][0]["line"]


# --- the second half of the same defect: the number the shell gets (#55) ----------------------------------


def test_of_subprocess_readsAChildsWaitStatus_andOnlyANegativeOneNamesASignal():
    # arrange / act / assert
    assert verdict_module.of_subprocess(0) is Verdict.PASSED
    assert verdict_module.of_subprocess(1) is Verdict.FAILED
    assert verdict_module.of_subprocess(-15) is Verdict.KILLED


def test_exit_code_handsOnTheNumberAShellItselfWritesForAChildKilledByThatSignal():
    # arrange: the SAME child twice - once through the kernel's subprocess seam, once under a shell that
    # reports its own $? - so neither number in this test is typed from memory
    killer = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    quoted = f"{shlex.quote(sys.executable)} -c {shlex.quote(killer)}"
    observed = run_module.run([sys.executable, "-c", killer]).rc
    reported = run_module.run(["sh", "-c", f"{quoted}; echo $?"]).out.strip()

    # act / assert: the translation is exactly the shell's own, and it is never green
    assert observed == -15
    assert verdict_module.exit_code(observed) == int(reported)
    assert verdict_module.exit_code(observed) != 0


def test_exit_code_removesTheNumberSysExitWouldHaveManufacturedFromTheWaitStatus():
    # arrange: what handing the raw wait status to `sys.exit` actually does - the modulo, measured, not
    # quoted from a document
    mangled = run_module.run([sys.executable, "-c", "import sys; sys.exit(-15)"]).rc

    # act / assert: 241 is neither the signal nor anything reserved, and it reads like an ordinary rc
    assert mangled == 241
    assert verdict_module.exit_code(-15) != mangled


def test_exit_code_leavesAnOrdinaryReturnCodeExactlyWhereItWas():
    # arrange / act / assert: only a wait status is translated; everything else is the rc it always was
    assert [verdict_module.exit_code(rc) for rc in (0, 1, 2, 7, 255)] == [0, 1, 2, 7, 255]


# --- the exit code is translated only where a signal was actually observed (si#71) ------------------------
#
# `exit_code` maps a negative wait status onto 128+n. It was applied to every gate's rc, including an
# `impl:` gate's - a Python callable's RETURN VALUE, which names no signal however negative it is. Harmless
# in every case measured, because both numbers were non-zero; but the function's docstring spoke of a child
# and the use did not, and #55 kept `of_subprocess` narrow for exactly this reason.


def test_exit_code_ofAKilledGateIsThe128PlusNAShellWouldReport():
    # arrange / act / assert: the case the translation exists for - `sys.exit(-15)` leaves 241, which is
    # neither the signal nor anything reserved
    assert GateVerdict("system", Verdict.KILLED, -15).exit_code == 143
    assert GateVerdict("system", Verdict.KILLED, -9).exit_code == 137


def test_exit_code_leavesAProductRunnersNegativeReturnValueAlone():
    # arrange: `simplon.waits.device_count` answers -1 for "could not read" in this very repository, and a
    # product body may do the same. A gate whose runner is the product's own reports FAILED with that rc
    gv = GateVerdict("ui", Verdict.FAILED, -1, detail="the product's own runner returned this rc")

    # act / assert: no signal is invented - it stays the number the body returned
    assert gv.exit_code == -1, (
        "a callable's return value was read as a wait status, so the process exits on a number that "
        "names a signal nobody sent")
    assert verdict_module.exit_code(-1) == 129, (
        "the free function is the one that translates; the point is that it is no longer applied here")


def test_exit_code_passesAnOrdinaryRcThrough():
    # arrange / act / assert: every non-killed outcome hands on exactly what it holds
    assert GateVerdict("unit", Verdict.PASSED, 0).exit_code == 0
    assert GateVerdict("unit", Verdict.FAILED, 1).exit_code == 1
    assert GateVerdict("unit", Verdict.SETUP_FAILED, 2, "preamble").exit_code == 2
    assert GateVerdict("unit", Verdict.NOT_RUN, 7, "precondition").exit_code == 7
