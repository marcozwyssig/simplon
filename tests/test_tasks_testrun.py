"""Unit tests for simplon.tasks.testrun (netctl#1406): the lab-based suite runner, whose every product
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

from simplon import context
from simplon import allure
from simplon.tasks import testrun
from simplon.context import ProductContext
from simplon import verdict as verdict_module
from simplon.verdict import GateVerdict, RunVerdict, Verdict


def _gv(name, rc):
    """The verdict a stubbed gate hands back: green on 0, a red SUITE (not a red setup) otherwise - the
    default a chain test wants, because the setup distinction has its own tests below."""
    return GateVerdict(name, Verdict.PASSED if rc == 0 else Verdict.FAILED, rc)


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


# --- the gate callback's name resolution (netctl#1469 plan 2) --------------------------------------------


def test_gate_runs_the_suite_the_command_pinned_rather_than_its_invocation_name(monkeypatch, tmp_path):
    # arrange: a command pinned via `with: { name: ... }` takes `name` off the command line entirely, so
    # the callback must resolve the gate from the parameter rather than from ctx.info_name
    _register(monkeypatch, tmp_path, _data())
    seen = {}
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered: seen.update(gate=gate.name)
                        or GateVerdict(gate.name, Verdict.PASSED))
    ctx = SimpleNamespace(info_name="whatever-this-command-is-called", args=[])

    # act: `gate` returns the rc rather than raising `typer.Exit` itself (netctl#1444/#defect2) - the
    # wrapper that binds it (`simplon.cli._bound`, or the generated module's template) is the one place
    # that turns a returned int into the process exit code, so the body stays a plain framework-free call
    rc = testrun.gate(ctx, name="acceptance-dataplane")

    # assert
    assert rc == 0
    assert seen["gate"] == "acceptance-dataplane"


def test_gate_falls_back_to_the_invocation_name_when_no_name_is_pinned(monkeypatch, tmp_path):
    # arrange: the transitional path for a product that has not migrated (netctl#1406) - two commands
    # bound to this one body are told apart by the name each was invoked as
    _register(monkeypatch, tmp_path, _data())
    seen = {}
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered: seen.update(gate=gate.name)
                        or GateVerdict(gate.name, Verdict.PASSED))
    ctx = SimpleNamespace(info_name="system", args=[])

    # act: same rc-return contract as above
    rc = testrun.gate(ctx)

    # assert
    assert rc == 0
    assert seen["gate"] == "system"


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

    # assert: the shared dir holds nothing of the earlier run - only this run's own verdict (#30) - and
    # the transient render dir is gone
    assert os.listdir(results) == [allure.ENVIRONMENT]
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
    assert "system-result.json" in os.listdir(results)
    assert sorted(os.listdir(results)) == sorted([allure.ENVIRONMENT, "system-result.json"])


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


# --- what a hook's return value means (#8) ---------------------------------------------------------------
#
# These four exist because mypy had been reporting this file's `if rc != 0` sites for months
# (`Incompatible return value type (got "object", expected "int")`) inside a set of findings everybody had
# agreed to read as environment noise. They were not noise. A hook is an ordinary Python function a product
# wrote, and an ordinary Python function that just does its work returns None - which was neither 0 nor a
# verdict, and aborted the gate it had just declared healthy.


def test_aPreconditionThatReturnsNothingIsNotAFailure_soTheSuiteStillRuns(monkeypatch, tmp_path, runner):
    # arrange: a healthy precondition written the ordinary way - it does its work and returns nothing
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.setattr(testrun, "resolve_ref",
                        lambda ref, where: (lambda: runner["hooks"].append(ref)))

    # act
    rc = testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: the gate ran its suite and reported the suite's verdict, not the hook's missing one
    assert rc == 0
    assert runner["argv"] is not None


def test_aPreconditionThatReturnsSomethingOtherThanAnRcIsNotAFailure(monkeypatch, tmp_path, runner):
    # arrange: a hook whose return value is a result object, written when the value could not matter
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.setattr(testrun, "resolve_ref",
                        lambda ref, where: (lambda: SimpleNamespace(healthy=True)))

    rc = testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)

    assert rc == 0
    assert runner["argv"] is not None


def test_aGateDeclaredAsAnImplThatReturnsNothingReportsGreen_ratherThanNone(monkeypatch, tmp_path, runner):
    # arrange: the product's own runner for a level, returning nothing
    data = _data()
    data["suites"]["gates"].append({"name": "acceptance-ui", "impl": "product.tooling:ui"})
    _register(monkeypatch, tmp_path, data)
    cfg = testrun.config()
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: None))

    rc = testrun.run_gate(cfg.gate("acceptance-ui"), cfg, [], filtered=False)

    # an rc of None would reach `any(rc != 0 ...)` in `accept` as a RED verdict and reach the process as 0
    assert rc == 0


def test_theHookVerdictRuleIsTheSameOneTheCliAppliesToACommandBody():
    # The two spellings are deliberate (a task must not import the binding layer), so this holds them
    # together: whatever `simplon.cli._rc` calls an exit code, a hook's verdict calls the same thing.
    from simplon import cli as simplon_cli

    for value in (0, 1, 7, -1, None, True, False, "ok", 1.5, SimpleNamespace()):
        assert testrun._verdict(value) == simplon_cli._rc(value), value


def test_aHookThatReturnsTrueMeansSuccess_becauseIntTrueWouldExitOne():
    # ABSOLUTE, not relative. The test above is a COUPLING test: it catches either rule drifting away from
    # the other, and stays green when both drift together - which is exactly what happens when somebody
    # "simplifies" both to `int(value)`. `return True` from a body that means success would then exit 1,
    # the trap both docstrings spend a paragraph on, and no test would have noticed.
    from simplon import cli as simplon_cli

    assert testrun._verdict(True) == 0
    assert simplon_cli._rc(True) == 0
    assert testrun._verdict(False) == 0
    assert simplon_cli._rc(False) == 0
    # and the neighbouring cases the rule is drawn against, so the boundary is stated and not implied
    assert testrun._verdict(1) == 1
    assert testrun._verdict(None) == 0


def test_run_gate_stillPropagatesARealNonZeroVerdict(monkeypatch, tmp_path, runner):
    # the coercion must not swallow the case the abort exists for
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    runner["rc:product.health:check"] = 7

    assert testrun.run_gate(cfg.gates[0], cfg, [], filtered=False) == 7
    assert runner["argv"] is None


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
    assert os.listdir(shared) == ["full-run-result.json"]  # not even a verdict: this run never touched it
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

    # assert: the quarantine dir holds only this run - its verdict and nothing of the earlier one
    assert os.listdir(quarantine) == [allure.ENVIRONMENT]


# --- accept: the whole chain ------------------------------------------------------------------------------


def _stub_chain(monkeypatch, rcs, report_rc=0):
    """Record the gates accept ran (with the args each received) and inject each one's rc."""
    ran = []
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered: ran.append((gate.name, extra, filtered))
                        or _gv(gate.name, rcs.get(gate.name, 0)))
    monkeypatch.setattr(testrun, "report",
                        lambda cfg=None, *, filtered=False, run=None:
                        ran.append(("report", [], filtered)) or report_rc)
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
    monkeypatch.setattr(testrun.allure, "render_report",
                        lambda *a, **k: merged.update(rendered=(a, k))
                        or allure.Render(report="/r/allure-1.html", tool="allure"))

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
                        lambda report_dir, results, prefix="allure": seen.update(results=results, prefix=prefix)
                        or allure.Render(report="/r/allure-1.html", tool="allure"))

    # act
    testrun.report(filtered=True)

    # assert
    assert seen["results"] == str(tmp_path / "test/reports/allure-results-filtered")
    assert seen["prefix"] == "allure-filtered"


def test_report_isRed_whenARenderToolWasPresentAndTheRenderFailed(monkeypatch, tmp_path, runner):
    # arrange: allure (or docker) IS installed and the render failed - the run has no archive and used to
    # say so with a warning behind rc 0, which no CI reads (#6)
    _register(monkeypatch, tmp_path, _data())
    monkeypatch.setattr(testrun.allure, "merge_results", lambda *a, **k: None)
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **k: allure.Render(tool="docker"))

    # act
    rc = testrun.report()

    # assert: the missing archive reaches the exit code
    assert rc == 1


def test_report_staysGreen_whenNoRenderToolIsInstalledAtAll(monkeypatch, tmp_path, runner):
    # arrange: no allure CLI and no docker. The rule stands: archiving must not itself be the reason a run
    # is red when the host simply has no render tool.
    _register(monkeypatch, tmp_path, _data())
    monkeypatch.setattr(testrun.allure, "merge_results", lambda *a, **k: None)
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **k: allure.Render())

    # act
    rc = testrun.report()

    # assert
    assert rc == 0


def test_accept_isRed_whenTheArchiveRenderFailed_eventhoughEveryGateWasGreen(monkeypatch, tmp_path, runner):
    # arrange: every gate green, the report step red - accept must not swallow the report's rc, or the
    # second entry point keeps exactly the blind spot the first one just lost
    _register(monkeypatch, tmp_path, _data())
    ran = _stub_chain(monkeypatch, {}, report_rc=1)

    # act
    rc = testrun.accept([])

    # assert: red, and every gate still ran
    assert rc == 1
    assert [name for name, _, _ in ran] == ["system", "acceptance-dataplane", "report"]


# --- setup failed versus probe red (#30) ------------------------------------------------------------------
#
# A gate can be red for two reasons and the exit code cannot tell them apart. These tests sabotage the
# SETUP - the same shape of failure that produced the ticket, where a product's provisioning fell over and
# the archive kept showing last week's `passed` - and pin that the distinction survives into what is
# WRITTEN, since that is the only place it can survive: the rc stays one bit, on purpose.


def test_aSabotagedPreambleIsSetupFailed_andTheSuiteNeverRuns(monkeypatch, tmp_path, runner):
    # arrange: provisioning falls over, exactly as `provision` did in the case behind the ticket
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    runner["rc:product.lab:ready"] = 1

    # act
    gv = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: the verdict says the SETUP broke, names the stage, and pytest was never invoked - the fix
    # that matters, because the old code dropped the preamble's rc and ran the suite against a lab that
    # was not there
    assert gv.verdict is Verdict.SETUP_FAILED
    assert gv.stage == "preamble"
    assert runner["argv"] is None


def test_aRedSuiteAndABrokenSetupCarryTheSameRc_soTheDistinctionCannotLiveInIt(monkeypatch, tmp_path, runner):
    # arrange: two runs of the same gate, red for the two different reasons, both rc 1
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    runner["rc"] = 1
    red_suite = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)
    runner["rc"], runner["rc:product.lab:ready"] = 0, 1

    # act
    broken_setup = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: indistinguishable by exit code - which is why the ticket forbids putting it there - and
    # distinguishable in every written form
    assert red_suite.rc == broken_setup.rc == 1
    assert testrun.run_gate(cfg.gates[0], cfg, [], filtered=False) == 1
    assert red_suite.verdict is Verdict.FAILED and broken_setup.verdict is Verdict.SETUP_FAILED
    assert "the suite ran" in red_suite.line and "never ran" in broken_setup.line


def test_aBrokenSetupWritesSetupFailedIntoTheArchiveItself_notOnlyRed(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    runner["rc:product.lab:ready"] = 1

    # act
    testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: allure's own Environment widget - the one thing a reader handed only the HTML still sees
    written = (tmp_path / "test/reports/allure-results" / allure.ENVIRONMENT).read_text(encoding="utf-8")
    assert "verdict=setup-failed" in written
    assert "setup failed (preamble, rc 1)" in written


def test_aGateWhoseSetupBrokeStampsSetupFailed_ratherThanLeavingLastWeeksPassedStanding(monkeypatch, tmp_path,
                                                                                        runner):
    # arrange: the ticket's case end to end - an earlier run's green stamp, then a run that never probed
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.PASSED),)))
    runner["rc:product.lab:ready"] = 1
    ctx = SimpleNamespace(info_name="system", args=[])

    # act
    rc = testrun.gate(ctx, name="system")

    # assert: red on the terminal AND red in the record, and the record says WHY
    assert rc == 1
    stamp = verdict_module.read_stamp(reports)
    assert stamp is not None
    assert stamp["verdict"] == "setup-failed"
    assert stamp["gates"][0]["stage"] == "preamble"


def test_aSuiteThatReportsItsOwnBrokenSetupIsBelieved_evenThoughTheKernelCannotSeeIt(monkeypatch, tmp_path,
                                                                                     runner):
    # arrange: the shape of the case behind the ticket - the lab is built inside a pytest session fixture,
    # so from out here a broken provision is just a non-zero pytest rc. The suite drops the marker the
    # kernel offered it in the environment.
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    runner["rc"] = 2

    def fake_pytest(argv, **kw):
        with open(os.environ[testrun.SETUP_MARKER_ENV], "w", encoding="utf-8") as fh:
            fh.write("provision\n")
        return SimpleNamespace(rc=runner["rc"])

    monkeypatch.setattr(testrun, "run", fake_pytest)

    # act
    gv = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: the suite's own claim, in the suite's own words, and the rc it really had
    assert gv.verdict is Verdict.SETUP_FAILED
    assert gv.stage == "provision" and gv.rc == 2


def test_aMarkerLeftByAnEarlierRunCannotBeReadAsThisRunsVerdict(monkeypatch, tmp_path, runner):
    # arrange: a stale "setup failed" marker is the same defect as a stale "passed", pointing the other way
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    reports = tmp_path / "test/reports"
    reports.mkdir(parents=True)
    (reports / testrun.SETUP_MARKER).write_text("provision\n", encoding="utf-8")

    # act: this run's suite prepares fine and passes
    gv = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert
    assert gv.verdict is Verdict.PASSED


def test_aSuiteThatClaimsABrokenSetupAndStillExitsZeroIsNotGreen(monkeypatch, tmp_path, runner):
    # arrange: a suite whose setup broke and whose rc says otherwise. Believing the rc there is exactly the
    # "red run, green record" this exists against, so the claim wins.
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()

    def fake_pytest(argv, **kw):
        open(os.environ[testrun.SETUP_MARKER_ENV], "w", encoding="utf-8").close()
        return SimpleNamespace(rc=0)

    monkeypatch.setattr(testrun, "run", fake_pytest)

    # act
    gv = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: an empty marker still counts, and gets the generic wording rather than being dropped
    assert gv.verdict is Verdict.SETUP_FAILED
    assert gv.stage == "the suite's own setup"


def test_theMarkerPathIsHandedToTheSuiteAndRestoredAfterwards(monkeypatch, tmp_path, runner):
    # arrange: the environment must not be left mutated for whatever runs next in this process
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.delenv(testrun.SETUP_MARKER_ENV, raising=False)
    seen = {}
    monkeypatch.setattr(testrun, "run",
                        lambda argv, **kw: seen.update(path=os.environ[testrun.SETUP_MARKER_ENV])
                        or SimpleNamespace(rc=0))

    # act
    testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert
    assert seen["path"] == str(tmp_path / "test/reports" / testrun.SETUP_MARKER)
    assert testrun.SETUP_MARKER_ENV not in os.environ


def test_aGateThatNeverStartedWritesNothingIntoTheArchive_butStillStampsThatItDidNotRun(monkeypatch,
                                                                                        tmp_path, runner):
    # arrange: the precondition refuses, so the last real run's archive must stand untouched - and yet the
    # attempt must not be silent, which is the half agile-cockpit's conftest could not do
    _register(monkeypatch, tmp_path, _data())
    runner["rc:product.health:check"] = 7
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    (results / "stale-result.json").write_text("{}", encoding="utf-8")
    ctx = SimpleNamespace(info_name="system", args=[])

    # act
    rc = testrun.gate(ctx, name="system")

    # assert: the archive is exactly as it was, and the stamp beside it says this attempt never ran
    assert rc == 7
    assert os.listdir(results) == ["stale-result.json"]
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert stamp is not None and stamp["verdict"] == "not-run"
    assert stamp["gates"][0]["stage"] == "precondition"


def test_accept_reportsTheWeakestClaimOfTheWholeRun_soOneBrokenSetupIsNotHiddenByARedSuite(monkeypatch,
                                                                                           tmp_path, runner):
    # arrange: one gate probed and found something, the other never probed at all
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    monkeypatch.setattr(testrun, "report", lambda cfg=None, *, filtered=False, run=None: 0)
    verdicts = {"system": GateVerdict("system", Verdict.FAILED, 1),
                "acceptance-dataplane": GateVerdict("acceptance-dataplane", Verdict.SETUP_FAILED, 1,
                                                    "preamble")}
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered: verdicts[gate.name])

    # act
    rc = testrun.accept([])

    # assert: one red bit out, and a record that still tells the two gates apart
    assert rc == 1
    stamp = verdict_module.read_stamp(reports)
    assert stamp is not None and stamp["verdict"] == "setup-failed"
    assert [g["verdict"] for g in stamp["gates"]] == ["failed", "setup-failed", "passed"]


def test_accept_stampsThatItNeverStarted_whenTheSectionPreconditionRefuses(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    runner["rc:product.health:check"] = 7
    _stub_chain(monkeypatch, {})

    # act
    rc = testrun.accept([])

    # assert: the fast abort is kept, and it is no longer silent
    assert rc == 7
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert stamp is not None and stamp["verdict"] == "not-run"


def test_report_putsTheRunsVerdictIntoTheArchiveItArchives(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **kw: allure.Render(report="r.html",
                                                                                       tool="allure"))
    run = RunVerdict((GateVerdict("system", Verdict.SETUP_FAILED, 1, "provision"),))

    # act
    testrun.report(cfg, run=run)

    # assert
    written = (tmp_path / "test/reports/allure-results" / allure.ENVIRONMENT).read_text(encoding="utf-8")
    assert "verdict=setup-failed" in written
