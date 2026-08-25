"""Unit tests for delivery.tasks.testrun (netctl#1406): the lab-based suite runner, whose every product
decision - which suite lives where, which gate CLEARS the shared allure results versus APPENDS into it, what
the report merges - arrives as manifest DATA rather than as a branch in here.

The two things worth pinning are the ones a wrong answer would make silently wrong rather than loudly
broken: the clear-versus-append rule (a second clear deletes the first gate's results; a missing one lets a
run report last week's) and the quarantine of an argument-filtered run (a partial run in the shared dir is
an archive that reports one test and looks like a full gate). AAA throughout, negative cases included.
"""
import contextlib
import os
from types import SimpleNamespace

import pytest

from delivery import context
from delivery.tasks import testrun
from delivery.context import ProductContext


def _data(**overrides):
    """A minimal but COMPLETE two-gate taxonomy, shaped like a product's real one: a clearing pytest gate
    that takes the passthrough args, an appending pytest gate, and a report step that merges two dirs."""
    section = {
        "reports": "test/reports",
        "precondition": "product.health:check",
        "gates": [
            {"name": "system", "suite": "test/system/python", "results": "clear",
             "junit": "junit.xml", "args": True, "precondition": "product.health:check",
             "preamble": "product.lab:ready", "announce": "system gate"},
            {"name": "acceptance-dataplane", "suite": "test/acceptance/python", "results": "append",
             "junit": "junit-acceptance-dataplane.xml", "preamble": "product.lab:ready"},
        ],
        "report": {"merge": ["a/build/allure-results", "b/build/allure-results"], "parent_suite": "Unit"},
    }
    section.update(overrides)
    return {"suites": section}


def _register(monkeypatch, tmp_path, data):
    """Register a ProductContext whose root is tmp_path and whose manifest yields `data`."""
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: data)
    return ctx


@pytest.fixture
def runner(monkeypatch, tmp_path):
    """Stub the two subprocess seams (venv creation, pytest) and the product hooks, and record what ran."""
    seen = {"argv": None, "cwd": None, "hooks": [], "rc": 0}

    monkeypatch.setattr(testrun, "keep_awake", contextlib.nullcontext)   # no caffeinate/systemd-inhibit here
    monkeypatch.setattr(testrun.pyvenv, "venv_python_pip", lambda d: (os.path.join(d, ".venv/bin/python"), "pip"))
    monkeypatch.setattr(testrun, "run",
                        lambda argv, **kw: seen.update(argv=argv, cwd=kw.get("cwd"))
                        or SimpleNamespace(rc=seen["rc"]))
    monkeypatch.setattr(testrun, "resolve_ref",
                        lambda ref, where: (lambda: seen["hooks"].append(ref) or seen.get(f"rc:{ref}", 0)))
    return seen


# --- the taxonomy read ----------------------------------------------------------------------------------


def test_declared_readsTheGatesInManifestOrder_withTheirClearVersusAppendRule(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, _data())

    # act
    cfg = testrun.config()

    # assert: order is the manifest's, and exactly the first gate clears the shared results
    assert [g.name for g in cfg.gates] == ["system", "acceptance-dataplane"]
    assert cfg.gates[0].clears and not cfg.gates[1].clears
    assert cfg.merge == ("a/build/allure-results", "b/build/allure-results")


def test_declared_rejectsASecondClearingGate_becauseItWouldDeleteTheFirstGatesResults(monkeypatch, tmp_path):
    # arrange: both gates claim the clear
    data = _data()
    data["suites"]["gates"][1]["results"] = "clear"

    # act / assert
    with pytest.raises(ValueError, match="exactly one gate must declare results: clear"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsATaxonomyWhereNoGateClears_becauseEveryRunWouldAppendForever():
    # arrange: every gate appends
    data = _data()
    data["suites"]["gates"][0]["results"] = "append"

    # act / assert
    with pytest.raises(ValueError, match="exactly one gate must declare results: clear"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsAClearingGateThatIsNotTheFirstToRun():
    # arrange: the clearing gate sits second, so it would wipe what the gate before it wrote
    data = _data()
    data["suites"]["gates"][0]["results"] = "append"
    data["suites"]["gates"][1]["results"] = "clear"

    # act / assert
    with pytest.raises(ValueError, match="is not the FIRST gate"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsAGateDeclaringBothASuiteAndAnImpl():
    # arrange: suite XOR impl is the lock that keeps a level's runner unambiguous
    data = _data()
    data["suites"]["gates"][0]["impl"] = "product.tooling:ui"

    # act / assert
    with pytest.raises(ValueError, match="exactly one of 'suite'"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsAnImplGateThatClaimsTheClear_becauseItWouldNeverActuallyClear():
    # arrange: an `impl:` gate is opaque - the kernel calls the product's runner for its rc and nothing
    # else - so a clear declared on one is dropped at runtime. Accepting it would satisfy the
    # exactly-one-clearing-gate rule while nothing ever cleared: the silent forever-appending archive
    data = _data()
    data["suites"]["gates"] = [{"name": "ui", "impl": "product.tooling:ui", "results": "clear"},
                               data["suites"]["gates"][1]]

    # act / assert
    with pytest.raises(ValueError, match="an 'impl' gate cannot declare 'results'"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsAnImplGateThatDeclaresPytestOnlyKeys():
    # arrange: the same reasoning for the other three keys the impl branch never reads
    data = _data()
    data["suites"]["gates"].append({"name": "ui", "impl": "product.tooling:ui", "args": True,
                                    "preamble": "product.lab:ready"})

    # act / assert: both are named, so the author sees every offending key at once
    with pytest.raises(ValueError, match="'args', 'preamble'"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsASecondGateTakingThePassthroughArgs():
    # arrange: two gates claiming the args would each get the same -k verbatim, and an expression written
    # for one suite filters the other down to nothing while still reporting green
    data = _data()
    data["suites"]["gates"][1]["args"] = True

    # act / assert
    with pytest.raises(ValueError, match="at most one gate may declare args"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsANonPathEntryInTheReportMergeList():
    # arrange: a stray non-string would stringify into a nonsense path that merge_results then SKIPS
    # silently (a missing dir is not an error there), so the typo has to fail here or it never fails
    data = _data()
    data["suites"]["report"]["merge"] = ["a/build/allure-results", None]

    # act / assert
    with pytest.raises(ValueError, match="holds a non-path entry"):
        testrun.declared(data, source="sample.yaml")


def test_declared_rejectsAMissingSection_ratherThanRunningNothing():
    # arrange / act / assert: an absent section must name itself, not surface as an empty gate list
    with pytest.raises(ValueError, match="the 'suites' section is missing"):
        testrun.declared({}, source="sample.yaml")


def test_gate_lookup_failsLoudly_forACommandNameTheTaxonomyDoesNotDeclare(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()

    # act / assert: a command bound to the runner with no matching gate is a manifest typo
    with pytest.raises(ValueError, match="declares no gate 'integration'"):
        cfg.gate("integration")


# --- the canonical run ----------------------------------------------------------------------------------


def test_run_gate_clearsTheSharedResults_forTheFirstGateOnly(monkeypatch, tmp_path, runner):
    # arrange: a stale results dir + a stale render scratch dir from an earlier run
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    (results / "stale-result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "test/reports/allure-report").mkdir()

    # act
    testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: the shared dir is fresh and the transient render dir is gone
    assert os.listdir(results) == []
    assert not (tmp_path / "test/reports/allure-report").exists()


def test_run_gate_appendsIntoTheSharedResults_forALaterGate(monkeypatch, tmp_path, runner):
    # arrange: the first gate's results are already there
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    (results / "system-result.json").write_text("{}", encoding="utf-8")

    # act
    testrun.run_gate(cfg.gates[1], cfg, [], filtered=False)

    # assert: the appending gate left the earlier gate's results in place
    assert os.listdir(results) == ["system-result.json"]


def test_run_gate_runsPytestFromTheSuiteRoot_intoTheSharedResultsAndItsOwnJunitFile(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()

    # act
    rc = testrun.run_gate(cfg.gates[1], cfg, [], filtered=False)

    # assert: cwd is the level's python root (so its conftest loads) and the two output flags are the
    # taxonomy's - notably NOT the system suite's junit.xml, which CI publishes as a separate check
    assert rc == 0
    assert runner["cwd"] == str(tmp_path / "test/acceptance/python")
    assert f"--alluredir={tmp_path / 'test/reports/allure-results'}" in runner["argv"]
    assert f"--junit-xml={tmp_path / 'test/reports/junit-acceptance-dataplane.xml'}" in runner["argv"]


def test_run_gate_runsThePreconditionBeforeThePreamble_andThePreambleBeforePytest(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()

    # act
    testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: both product hooks ran, in that order, and the suite ran after them
    assert runner["hooks"] == ["product.health:check", "product.lab:ready"]
    assert runner["argv"] is not None


def test_run_gate_abortsWithoutClearingAnything_whenThePreconditionIsRed(monkeypatch, tmp_path, runner):
    # arrange: an unhealthy verdict, and a stale results dir that must survive a gate that never started
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    runner["rc:product.health:check"] = 7
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    (results / "stale-result.json").write_text("{}", encoding="utf-8")

    # act
    rc = testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: the precondition's code propagates, no suite ran, and nothing was cleared
    assert rc == 7
    assert runner["argv"] is None
    assert os.listdir(results) == ["stale-result.json"]


def test_run_gate_callsTheProductsOwnRunner_forAGateDeclaredAsAnImpl(monkeypatch, tmp_path, runner):
    # arrange: a level whose runner is the product's (a browser journey suite, say)
    data = _data()
    data["suites"]["gates"].append({"name": "acceptance-ui", "impl": "product.tooling:ui"})
    _register(monkeypatch, tmp_path, data)
    cfg = testrun.config()
    runner["rc:product.tooling:ui"] = 3

    # act
    rc = testrun.run_gate(cfg.gate("acceptance-ui"), cfg, [], filtered=False)

    # assert: its rc is the gate's rc, and no venv/pytest was involved
    assert rc == 3
    assert runner["argv"] is None


# --- the exploratory (argument-filtered) run --------------------------------------------------------------


def test_run_gate_passesExtraArgsThroughToPytestVerbatim(monkeypatch, tmp_path, runner):
    # arrange: the whole point of the passthrough - a single-test hunt instead of the full gate
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()

    # act
    testrun.run_gate(cfg.gates[0], cfg, ["-k", "peer_loopback"], filtered=True)

    # assert: appended last, unchanged
    assert runner["argv"][-2:] == ["-k", "peer_loopback"]


def test_run_gate_quarantinesAFilteredRun_leavingTheSharedArchiveUntouched(monkeypatch, tmp_path, runner):
    # arrange: a full run's results are in the shared dir; a filtered run must not half-clear them
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    shared = tmp_path / "test/reports/allure-results"
    shared.mkdir(parents=True)
    (shared / "full-run-result.json").write_text("{}", encoding="utf-8")

    # act: the CLEARING gate, filtered
    testrun.run_gate(cfg.gates[0], cfg, ["-k", "one"], filtered=True)

    # assert: the shared archive survived intact and the run wrote into its own dir instead
    assert os.listdir(shared) == ["full-run-result.json"]
    quarantine = tmp_path / "test/reports/allure-results-filtered"
    assert f"--alluredir={quarantine}" in runner["argv"]
    assert f"--junit-xml={tmp_path / 'test/reports/junit-filtered.xml'}" in runner["argv"]


def test_run_gate_clearsTheQuarantineDir_soAFilteredRunIsNeverMixedWithTheLastOne(monkeypatch, tmp_path, runner):
    # arrange: an earlier filtered run left results behind
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    quarantine = tmp_path / "test/reports/allure-results-filtered"
    quarantine.mkdir(parents=True)
    (quarantine / "earlier-result.json").write_text("{}", encoding="utf-8")

    # act
    testrun.run_gate(cfg.gates[0], cfg, ["-k", "one"], filtered=True)

    # assert: the quarantine dir holds only this run
    assert os.listdir(quarantine) == []


# --- accept: the whole chain ------------------------------------------------------------------------------


def _stub_chain(monkeypatch, rcs):
    """Record the gates accept ran (with the args each received) and inject each one's rc."""
    ran = []
    monkeypatch.setattr(testrun, "run_gate",
                        lambda gate, cfg, extra, *, filtered: ran.append((gate.name, extra, filtered))
                        or rcs.get(gate.name, 0))
    monkeypatch.setattr(testrun, "report", lambda cfg=None, *, filtered=False: ran.append(("report", [], filtered)) or 0)
    return ran


def test_accept_runsEveryGateInTaxonomyOrder_thenTheReport(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    ran = _stub_chain(monkeypatch, {})

    # act
    rc = testrun.accept([])

    # assert
    assert rc == 0
    assert [name for name, _, _ in ran] == ["system", "acceptance-dataplane", "report"]


def test_accept_reportsRed_whenAnyGateIsRed_butStillRunsTheRestAndArchives(monkeypatch, tmp_path, runner):
    # arrange: the FIRST gate is red (#571: the full picture matters more than fail-fast here)
    _register(monkeypatch, tmp_path, _data())
    ran = _stub_chain(monkeypatch, {"system": 1})

    # act
    rc = testrun.accept([])

    # assert: red verdict, yet every later gate ran and the report was archived
    assert rc == 1
    assert [name for name, _, _ in ran] == ["system", "acceptance-dataplane", "report"]


def test_accept_abortsFast_whenTheSectionLevelPreconditionIsRed(monkeypatch, tmp_path, runner):
    # arrange: an unhealthy cluster must abort in seconds rather than waste the whole collection
    _register(monkeypatch, tmp_path, _data())
    runner["rc:product.health:check"] = 7
    ran = _stub_chain(monkeypatch, {})

    # act
    rc = testrun.accept([])

    # assert
    assert rc == 7
    assert ran == []


def test_accept_givesTheExtraArgsOnlyToTheGateThatDeclaresThem_andQuarantinesTheWholeRun(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    ran = _stub_chain(monkeypatch, {})

    # act
    testrun.accept(["-k", "one"])

    # assert: only the args-declaring gate sees them, and EVERY step of the run is quarantined - a partly
    # filtered run in the shared dir is exactly the half-cleared archive the quarantine exists to prevent
    assert ran == [("system", ["-k", "one"], True), ("acceptance-dataplane", [], True), ("report", [], True)]


# --- the report step --------------------------------------------------------------------------------------


def test_report_mergesTheDeclaredResultDirs_intoTheSharedResults(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    merged = {}
    monkeypatch.setattr(testrun.allure, "merge_results",
                        lambda dst, srcs, parent_suite="Unit": merged.update(dst=dst, srcs=srcs,
                                                                             parent_suite=parent_suite))
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **k: merged.update(rendered=(a, k)))

    # act
    rc = testrun.report()

    # assert: the manifest's dirs, resolved under the product root, tagged with its parent suite
    assert rc == 0
    assert merged["dst"] == str(tmp_path / "test/reports/allure-results")
    assert merged["srcs"] == [str(tmp_path / "a/build/allure-results"), str(tmp_path / "b/build/allure-results")]
    assert merged["parent_suite"] == "Unit"


def test_report_rendersAFilteredRunUnderItsOwnPrefix_soItCannotPassAsTheCanonicalArchive(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    seen = {}
    monkeypatch.setattr(testrun.allure, "merge_results", lambda *a, **k: None)
    monkeypatch.setattr(testrun.allure, "render_report",
                        lambda report_dir, results, prefix="allure": seen.update(results=results, prefix=prefix))

    # act
    testrun.report(filtered=True)

    # assert
    assert seen["results"] == str(tmp_path / "test/reports/allure-results-filtered")
    assert seen["prefix"] == "allure-filtered"
