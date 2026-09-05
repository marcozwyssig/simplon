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

import pytest

from simplon import verdict as verdict_module
from simplon.verdict import GateVerdict, RunVerdict, Verdict


# --- the vocabulary ---------------------------------------------------------------------------------------


def test_onlyAPassedOrFailedGateIsEvidenceAboutTheProduct():
    # arrange / act / assert: the predicate the whole module turns on
    assert Verdict.PASSED.ran and Verdict.FAILED.ran
    assert not Verdict.SETUP_FAILED.ran and not Verdict.NOT_RUN.ran


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


def test_wrote_results_isFalseForARunWhoseGatesAllRefusedBeforeTouchingAnything():
    # arrange / act / assert: the condition under which the run's verdict may enter the archive at all
    assert not RunVerdict((GateVerdict("a", Verdict.NOT_RUN, 7, "precondition"),)).wrote_results
    assert RunVerdict((GateVerdict("a", Verdict.NOT_RUN, 7, "precondition"),
                       GateVerdict("b", Verdict.FAILED, 1))).wrote_results
    assert not RunVerdict().wrote_results


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
