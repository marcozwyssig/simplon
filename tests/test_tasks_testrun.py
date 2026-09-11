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
import sys
import time
from types import SimpleNamespace

import pytest

from simplon import context
from simplon.tasks import allure
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


def test_declared_acceptsAnImplGateThatClaimsTheClear_becauseItNowActuallyClears():
    # arrange: this used to be refused, on the ground that the clear was dropped on the impl branch and
    # an accepted key that does nothing is worse than a refused one. True of the code, and the wrong
    # repair: the clear could hang on no other kind of gate, so a product whose only runner is its own
    # could write no loadable section at all (si#61). The branch honours it now - see
    # tests/test_suites_impl_only.py, which measures the clearing - so the declaration is no longer inert
    data = _data()
    data["suites"]["gates"] = [{"name": "ui", "impl": "product.tooling:ui", "results": "clear"},
                               data["suites"]["gates"][1]]

    # act
    cfg = testrun.declared(data, source="sample.yaml")

    # assert: it loads, and the gate that owns the run's results dir is the product's own
    assert cfg.gates[0].impl == "product.tooling:ui" and cfg.gates[0].clears
    assert not cfg.gates[1].clears


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


def test_declared_defaultsTheReportsDirToTestsReports_whenTheManifestNamesNone():
    # arrange: every product wrote the same line, so the kernel says it instead. `reports:` was REQUIRED
    # until now, which made a universal answer look like a per-product decision.
    data = _data()
    del data["suites"]["reports"]

    # act
    cfg = testrun.declared(data, source="sample.yaml")

    # assert
    assert cfg.reports == "tests/reports"


def test_declared_letsADeclaredReportsDirWinOverTheDefault():
    # arrange: the default is a default, not a rule - a product whose outputs belong elsewhere says so
    data = _data(reports="build/reports")

    # act
    cfg = testrun.declared(data, source="sample.yaml")

    # assert
    assert cfg.reports == "build/reports"


def test_declared_stillRejectsAnEmptyReportsDir_ratherThanFallingBackToTheDefault():
    # arrange: `reports: ""` is a statement, not an absence. Reading it as "use the default" would turn a
    # typo into a silently different output directory, which is what the default must NOT buy.
    data = _data(reports="")

    # act / assert
    with pytest.raises(ValueError, match="'reports' must be a non-empty string"):
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


def test_assess_gate_everyPytestGateReportsThatItTookTheResultsDir(monkeypatch, tmp_path, runner):
    # arrange: si#69. A gate the KERNEL runs owns the dir whatever it finds there - it made it, it ran
    # pytest into it and it wrote the environment - and it has to SAY so, because the run's verdict may
    # only enter an archive some gate of that run took. Every outcome that reaches `_written` counts,
    # not only the green one, so the clearing gate and the appending gate are both measured
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()

    # act / assert
    for gate in cfg.gates[:2]:
        gv = testrun.assess_gate(gate, cfg, [], filtered=False)
        assert gv.owned_results is True, (
            f"the pytest gate '{gate.name}' does not report taking the results dir it just filled, so "
            f"the run cannot state its verdict in the archive it wrote")
    assert RunVerdict(tuple(testrun.assess_gate(g, cfg, [], filtered=False)
                            for g in cfg.gates[:2])).owns_results


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


# --- what an `impl:` gate is entitled to say about itself (si#65, si#59) ----------------------------------


def _impl_gate(monkeypatch, tmp_path, body):
    """A taxonomy whose second level is a bare `impl:` gate, with `body` as the product's own runner.

    The runner is registered through `resolve_ref` rather than through the `runner` fixture, because
    these tests are about what the KERNEL says when the product's runner does or does not speak - so the
    body has to be able to write the marker file, and a fixture that only records the ref cannot.
    """
    data = _data()
    data["suites"]["gates"].append({"name": "acceptance-ui", "impl": "product.tooling:ui"})
    _register(monkeypatch, tmp_path, data)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: body)
    cfg = testrun.config()
    return cfg, cfg.gate("acceptance-ui")


def test_aRedImplGateDoesNotClaimTheSuiteRanAndReportedFailures(monkeypatch, tmp_path):
    # arrange: the product's own runner comes back red - a Gradle build that stopped in :compileJava, in
    # the measured case, having compiled nothing and run no test at all
    cfg, gate = _impl_gate(monkeypatch, tmp_path, lambda: 1)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: the outcome and the rc are unchanged; the SENTENCE no longer describes a suite the kernel
    # never saw. This is the whole of si#65 - the old line said the suite had run and reported failures
    # about a build that had not compiled.
    assert gv.verdict is Verdict.FAILED
    assert gv.rc == 1
    assert "the suite ran and reported failures" not in gv.line
    assert gv.line == f"failed (rc 1) - {testrun.IMPL_DETAIL}"


def test_aRedImplGateSaysWhatTheKernelSaw_andSaysThatTheRestIsNotItsToState(monkeypatch, tmp_path):
    # arrange: same red runner, read for what the replacement sentence CLAIMS rather than for its text
    cfg, gate = _impl_gate(monkeypatch, tmp_path, lambda: 7)

    # act
    line = testrun.assess_gate(gate, cfg, [], filtered=False).line

    # assert: it names the one thing the kernel observed - a runner that returned an rc - and then says it
    # cannot tell whether a suite ran. Silence about the suite, not silence about the ignorance: "I do not
    # know" is a statement a record may carry, "the suite reported" is not.
    assert "the product's own runner returned this rc" in line
    assert "cannot say whether one ran at all" in line
    assert "rc 7" in line


def test_aGreenImplGateIsUnchanged_becauseAPassingGateNeverMadeAFalseClaim(monkeypatch, tmp_path):
    # arrange
    cfg, gate = _impl_gate(monkeypatch, tmp_path, lambda: 0)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: `passed` says exactly what happened and carries no explanatory half to be wrong about
    assert gv.verdict is Verdict.PASSED
    assert gv.line == "passed"
    assert gv.stage == ""


def test_anImplGateThatSaysNothingGetsNoStageInvented_theKernelStaysAsOpaqueAsItWas(monkeypatch, tmp_path):
    # arrange: the ordinary runner - it returns an rc and writes no marker, which is every runner that
    # was ever written against this kernel
    cfg, gate = _impl_gate(monkeypatch, tmp_path, lambda: 2)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: opening the marker must not have MANUFACTURED the outcome it makes reachable. A fix that
    # answered `setup-failed` for a runner that never claimed one would have moved si#65's defect instead
    # of removing it, and stayed green while doing so.
    assert gv.verdict is Verdict.FAILED
    assert gv.stage == ""
    assert "setup" not in gv.line
    assert not os.path.exists(os.path.join(str(tmp_path / "test/reports"), testrun.SETUP_MARKER))


def test_anImplRunnerCanSayItsOwnSetupFellOver_throughTheMarkerTheKernelNowOpens(monkeypatch, tmp_path):
    # arrange: a product-owned runner that KNOWS its preparation broke - the Gradle case, where the build
    # never reached :test - and writes the stage into the marker the kernel points it at
    def compile_then_test():
        with open(os.environ[testrun.SETUP_MARKER_ENV], "w", encoding="utf-8") as fh:
            fh.write("compile\n")
        return 1

    cfg, gate = _impl_gate(monkeypatch, tmp_path, compile_then_test)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: the third outcome, reached by an impl gate for the first time (si#59). The kernel invented
    # nothing - `compile` is the product's own word for its own stage, which is why the marker carries a
    # free string rather than an enum.
    assert gv.verdict is Verdict.SETUP_FAILED
    assert gv.stage == "compile"
    assert not gv.verdict.ran
    assert gv.line == "setup failed (compile, rc 1) - the suite never ran, so this says nothing about the product"


def test_anImplRunnerThatDropsTheMarkerAndStillReturnsZeroIsNotGreen(monkeypatch, tmp_path):
    # arrange: the direction that would otherwise be a red run with a green exit - a runner whose setup
    # broke and whose rc says nothing about it
    def broken_but_quiet():
        open(os.environ[testrun.SETUP_MARKER_ENV], "w", encoding="utf-8").close()
        return 0

    cfg, gate = _impl_gate(monkeypatch, tmp_path, broken_but_quiet)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: the claim wins over the rc, and the kernel supplies the rc the record needs - same
    # precedence a pytest gate's marker gets, so the two runners cannot drift apart
    assert gv.verdict is Verdict.SETUP_FAILED
    assert gv.rc == testrun.SETUP_FAILED_RC
    assert gv.stage == "the suite's own setup"
    assert testrun.run_gate(gate, cfg, [], filtered=False) != 0


def test_aStaleMarkerFromAnEarlierGateIsNotReadAsThisImplGatesVerdict(monkeypatch, tmp_path):
    # arrange: a marker left lying in the reports dir, and a runner that says nothing at all
    reports = tmp_path / "test/reports"
    reports.mkdir(parents=True)
    (reports / testrun.SETUP_MARKER).write_text("last week's provisioning\n", encoding="utf-8")
    cfg, gate = _impl_gate(monkeypatch, tmp_path, lambda: 0)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: a stale "setup failed" is the same defect as a stale "passed", pointing the other way. The
    # window removes the file on the way in, and that has to hold for the branch it was just opened to.
    assert gv.verdict is Verdict.PASSED
    assert gv.stage == ""


def test_theImplMarkerWindowLeavesNoEnvironmentVariableBehind(monkeypatch, tmp_path):
    # arrange
    monkeypatch.delenv(testrun.SETUP_MARKER_ENV, raising=False)
    seen = {}
    cfg, gate = _impl_gate(monkeypatch, tmp_path,
                           lambda: seen.update(path=os.environ.get(testrun.SETUP_MARKER_ENV)) or 0)

    # act
    testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: the runner saw the path, and the process is as it was afterwards
    assert seen["path"] and seen["path"].endswith(testrun.SETUP_MARKER)
    assert testrun.SETUP_MARKER_ENV not in os.environ


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


def _stub_chain(monkeypatch, rcs, report_rc=0, seen=None):
    """Record the gates accept ran (with the args each received) and inject each one's rc.

    `seen`, when a caller passes one, also collects the keyword arguments the report step was handed -
    kept out of `ran` so the ordering assertions every caller writes stay about the ORDER."""
    ran = []
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered, earlier=():
                        ran.append((gate.name, extra, filtered)) or _gv(gate.name, rcs.get(gate.name, 0)))

    def _report(cfg=None, *, filtered=False, run=None, since=None):
        ran.append(("report", [], filtered))
        if seen is not None:
            seen.update(filtered=filtered, run=run, since=since)
        return report_rc

    monkeypatch.setattr(testrun, "report", _report)
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


# --- the cutoff a gate hands the merge (si#70) ------------------------------------------------------------


def test_started_floorsTheCutoffToTheWholeSecond(monkeypatch):
    """The floor is the whole reason si#70's cutoff is safe to hand out, and nothing asserted it (si#86).

    Two different things put a result this run really wrote on the wrong side of a cutoff taken
    mid-second. A filesystem carrying mtime at one- or two-second granularity truncates the file
    backwards, past the cutoff. And even where mtime is nanosecond-exact, the instant this process reads
    and the instant the kernel stamps an inode with are two reads of CLOCK_REALTIME taken in different
    places, which are not ordered with respect to each other: measured at up to 7047 ns apart, the wrong
    way round, across a CPU migration between the two.

    Flooring costs at most a second of the previous run's leavings, which the merge line then names.
    Not flooring drops a genuine result in silence, and only one of those two is recoverable by a reader.
    """
    # arrange: a run that began 937 ms into its second
    monkeypatch.setattr(testrun, "time", SimpleNamespace(time=lambda: 1_700_000_000.937))

    # act / assert: the cutoff is that second, not that instant
    assert testrun._started() == 1_700_000_000.0


# --- the report step --------------------------------------------------------------------------------------


def test_report_mergesTheDeclaredResultDirs_intoTheSharedResults(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    merged = {}
    monkeypatch.setattr(testrun.allure, "merge_results",
                        lambda dst, srcs, parent_suite="Unit", not_before=None:
                        merged.update(dst=dst, srcs=srcs, parent_suite=parent_suite,
                                      not_before=not_before)
                        or allure.Merge(parent_suite=parent_suite, tagged=1, present=tuple(srcs)))
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
    # a standalone report step has no run behind it, so it merges what is present (si#70)
    assert merged["not_before"] is None

    # act / assert: and a report step that DOES know when its run began hands that on, or the whole
    # distinction stops at this function's own signature
    testrun.report(since=1234.0)
    assert merged["not_before"] == 1234.0, (
        "the report step knows when the run began and does not tell the merge, so the merge takes "
        "whatever lies in the product's dirs - which is the previous run's")


def _report_lines(monkeypatch, tmp_path, capsys, *, merge):
    """Run the report step over real source dirs and hand back the lines it printed."""
    _register(monkeypatch, tmp_path, _data(report={"merge": merge, "parent_suite": "Java"}))
    monkeypatch.setattr(testrun.allure, "render_report",
                        lambda *a, **k: allure.Render(report="/r/allure-1.html", tool="allure"))
    capsys.readouterr()
    testrun.report()
    return capsys.readouterr().out


def test_report_saysWhatTheMergeDid_notThatItCalledIt(monkeypatch, tmp_path, capsys, runner):
    # arrange: one real source dir holding one allure result
    src = tmp_path / "mod/build/allure-results"
    src.mkdir(parents=True)
    (src / "a-result.json").write_text('{"name": "t", "labels": []}', encoding="utf-8")

    # act
    out = _report_lines(monkeypatch, tmp_path, capsys, merge=["mod/build/allure-results"])

    # assert: the old line was `per-module results merged (parentSuite=Java)` whatever had happened. It
    # now carries counted numbers, so two different outcomes cannot print the same sentence.
    assert "1 tagged parentSuite=Java" in out
    assert "1 of 1 declared source dirs" in out


def test_report_saysNothingWasMerged_whenTheDeclaredSourceIsNotThere(monkeypatch, tmp_path, capsys,
                                                                    runner):
    # arrange: the measured case - Gradle stopped in :compileJava, so the dir the manifest declares was
    # never written. `merge_results` skips it deliberately, and the run used to report a successful merge.
    # act
    out = _report_lines(monkeypatch, tmp_path, capsys, merge=["build/junit-xml"])

    # assert: "nothing to do" says so, names the dir a reader has to go and look for, and does not wear
    # the OK badge a real merge gets
    assert "nothing merged" in out
    assert str(tmp_path / "build/junit-xml") in out
    assert "per-module results merged" not in out


def test_report_doesNotDieWhenAProductDeclaresItsOwnResultsDirAsAMergeSource(monkeypatch, tmp_path,
                                                                             capsys, runner):
    """si#138, through the path a product actually takes. `report.merge:` naming the results dir is a
    plausible misreading of "the directory the results are in", and on origin/main it ended the report
    step with `shutil.SameFileError: '.../ctest.xml' and '.../ctest.xml' are the same file`, three frames
    down, naming neither the key nor anything a reader could act on - out of the one module that names
    the offending key in every other refusal.

    The archive is still rendered, because nothing is wrong with it: the files are already at the
    destination. What was missing is the sentence saying the key can never do anything.
    """
    # arrange: the destination, declared as its own source, holding a file the copy branch would take.
    # The render is wired by hand rather than through `_report_lines`, because "it still renders" is half
    # of what this test claims and a helper that throws the rc away cannot say it
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    (results / "ctest.xml").write_text('<testsuite tests="1"><testcase name="A"/></testsuite>',
                                       encoding="utf-8")
    _register(monkeypatch, tmp_path,
              _data(report={"merge": ["test/reports/allure-results"], "parent_suite": "Java"}))
    rendered = []
    monkeypatch.setattr(testrun.allure, "render_report",
                        lambda *a, **k: rendered.append(a)
                        or allure.Render(report="/r/allure-1.html", tool="allure"))
    capsys.readouterr()

    # act
    rc = testrun.report()
    out = capsys.readouterr().out

    # assert: a sentence naming the directory and what to do, not a traceback - and the archive is still
    # written, because nothing is wrong with it
    assert "is the destination itself and was not merged" in out, out
    assert str(results) in out, out
    assert "drop the key" in out, out
    assert (results / "ctest.xml").is_file()
    assert rendered, "the report step reported the mistake and then skipped the archive"
    assert rc == 0


def test_report_doesNotAnnounceAParentSuiteForAJunitXmlThatCannotCarryOne(monkeypatch, tmp_path, capsys,
                                                                         runner):
    # arrange: Gradle's JUnit XML, which falls into the verbatim branch - three test cases arrived in the
    # measured archive with parentSuite=None under a line saying parentSuite=Java
    src = tmp_path / "build/junit-xml"
    src.mkdir(parents=True)
    (src / "TEST-demo.CalculatorTest.xml").write_text("<testsuite/>", encoding="utf-8")

    # act
    out = _report_lines(monkeypatch, tmp_path, capsys, merge=["build/junit-xml"])

    # assert: the sentence claims no tagging, says the file went through untagged - and the FILE is there,
    # because that verbatim copy is how a Java product's results reach the report at all
    assert "tagged parentSuite" not in out
    assert "1 copied unchanged, carrying no parentSuite" in out
    assert (tmp_path / "test/reports/allure-results/TEST-demo.CalculatorTest.xml").is_file()


def _badge(out, phrase):
    """The colour the line carrying `phrase` was logged with - `log.ok` is green, `log.warn` yellow."""
    line = next(l for l in out.splitlines() if phrase in l)
    return {"\033[1;32m": "ok", "\033[1;33m": "warn"}.get(line[:7], line[:7])


def test_report_doesNotWearTheOkBadge_whenTheDeclaredParentSuiteReachedNothing(monkeypatch, tmp_path,
                                                                              capsys, runner):
    # arrange: si#79. The manifest declares `parent_suite: Java`, the runner writes JUnit XML, and allure
    # cannot be told a parentSuite for one - measured five ways against the pinned image. The run used to
    # report OK, so a product learned that its declared grouping had done nothing only by missing a level
    # in the Suites tree afterwards
    src = tmp_path / "build/junit-xml"
    src.mkdir(parents=True)
    (src / "TEST-demo.CalculatorTest.xml").write_text("<testsuite/>", encoding="utf-8")

    # act
    out = _report_lines(monkeypatch, tmp_path, capsys, merge=["build/junit-xml"])

    # assert: the badge, and the reason on the same line
    assert _badge(out, "per-module results") == "warn"
    assert "parentSuite=Java reached nothing" in out
    assert "Merge *-result.json to group a module, or drop the key" in out


def test_report_keepsTheOkBadge_whenTheParentSuiteActuallyReachedSomething(monkeypatch, tmp_path, capsys,
                                                                          runner):
    # arrange: the same warning fired on a merge that DID tag would turn every pytest product's green run
    # yellow, which is the diagnosis being too broad rather than absent
    src = tmp_path / "mod/build/allure-results"
    src.mkdir(parents=True)
    (src / "a-result.json").write_text('{"name": "t", "labels": []}', encoding="utf-8")

    # act
    out = _report_lines(monkeypatch, tmp_path, capsys, merge=["mod/build/allure-results"])

    # assert
    assert _badge(out, "per-module results") == "ok"
    assert "reached nothing" not in out


def test_report_rendersAFilteredRunUnderItsOwnPrefix_soItCannotPassAsTheCanonicalArchive(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    seen = {}
    monkeypatch.setattr(testrun.allure, "merge_results",
                        lambda *a, **k: allure.Merge(tagged=1, present=("src",)))
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
    monkeypatch.setattr(testrun.allure, "merge_results",
                        lambda *a, **k: allure.Merge(tagged=1, present=("src",)))
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **k: allure.Render(tool="docker"))

    # act
    rc = testrun.report()

    # assert: the missing archive reaches the exit code
    assert rc == 1


def test_report_staysGreen_whenNoRenderToolIsInstalledAtAll(monkeypatch, tmp_path, runner):
    # arrange: no allure CLI and no docker. The rule stands: archiving must not itself be the reason a run
    # is red when the host simply has no render tool.
    _register(monkeypatch, tmp_path, _data())
    monkeypatch.setattr(testrun.allure, "merge_results",
                        lambda *a, **k: allure.Merge(tagged=1, present=("src",)))
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
    rc = testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: an empty marker still counts, and gets the generic wording rather than being dropped
    assert gv.verdict is Verdict.SETUP_FAILED
    assert gv.stage == "the suite's own setup"
    # AND the gate is red on the way out. A `setup-failed` record handed back with rc 0 is a red run that
    # CI reports as a success - the failure class of this ticket with its two halves swapped, and the half
    # this test's name has always promised to measure.
    assert gv.rc != 0 and rc != 0


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
    monkeypatch.setattr(testrun, "report", lambda cfg=None, *, filtered=False, run=None, since=None: 0)
    verdicts = {"system": GateVerdict("system", Verdict.FAILED, 1),
                "acceptance-dataplane": GateVerdict("acceptance-dataplane", Verdict.SETUP_FAILED, 1,
                                                    "preamble")}
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered, earlier=(): verdicts[gate.name])

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


# --- a step that RAISED still leaves this run's record (si#63) --------------------------------------------


def test_accept_tellsTheReportStepWhenTheRunBegan_soItCannotMergeTheLastRunsResults(monkeypatch,
                                                                                     tmp_path, runner):
    # arrange: si#70. The declared merge sources belong to the PRODUCT and no gate of either kind empties
    # them, so without this instant the report step merged whatever the last run left there. Measured on
    # a real Java product: a build that stopped in `:compileJava` shipped `{"failed":0,"passed":3,
    # "total":3}` out of a file 66 seconds older than the run
    _register(monkeypatch, tmp_path, _data())
    seen = {}
    before = time.time()
    _stub_chain(monkeypatch, {}, seen=seen)

    # act
    testrun.accept([])

    # assert: the report step got an instant, and it is this run's rather than any later one
    assert seen["since"] is not None, "the report step was told nothing about when this run began"
    assert seen["since"] <= time.time()
    # floored to the whole second, deliberately: a coarse-granularity filesystem must not make this run's
    # own output look older than the run (a second of the previous run's leavings is the cheaper error)
    assert seen["since"] == float(int(seen["since"]))
    assert seen["since"] >= float(int(before))


def test_accept_takesTheInstantBeforeTheFirstGateRuns_notAfterIt(monkeypatch, tmp_path, runner):
    # arrange: a gate that takes measurable time. If the instant were read at the report step, everything
    # the gates wrote would already be older than it and the whole run's results would count as stale
    _register(monkeypatch, tmp_path, _data())
    seen = {}
    ran = []
    monkeypatch.setattr(testrun, "assess_gate",
                        lambda gate, cfg, extra, *, filtered, earlier=():
                        (ran.append(time.time()), time.sleep(1.1))
                        and None or _gv(gate.name, 0))

    def _report(cfg=None, *, filtered=False, run=None, since=None):
        seen.update(since=since)
        return 0

    monkeypatch.setattr(testrun, "report", _report)

    # act
    testrun.accept([])

    # assert: every gate started at or after the instant handed to the report step
    assert seen["since"] <= min(ran), (
        "the run's start was read after the gates ran, so this run's own results would be merged as the "
        "previous run's")


def _raising_report(monkeypatch, exc):
    """A report step that raises - the measured case is an `IsADirectoryError` out of `merge_results`."""
    def boom(cfg=None, *, filtered=False, run=None, since=None):
        raise exc
    monkeypatch.setattr(testrun, "report", boom)


def test_accept_doesNotLeaveAStampSayingPassed_whenTheReportStepRaised(monkeypatch, tmp_path, runner):
    # arrange: every gate green, and the step after them falls over - the measured run, where
    # `merge_results` met Gradle's `test-results/test/binary` and the process ended with rc 1
    _register(monkeypatch, tmp_path, _data())
    _stub_chain(monkeypatch, {})
    _raising_report(monkeypatch, IsADirectoryError(21, "Is a directory", "/p/build/test-results/test/binary"))

    # act
    with pytest.raises(IsADirectoryError):
        testrun.accept([])

    # assert: THE WHOLE OF si#63. The gates really were green; the run was not, and the record a reader
    # consults a week later is the record of the RUN. It used to say `"verdict": "passed"`.
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert stamp is not None
    assert stamp["verdict"] == "failed"
    assert stamp["line"] != "passed"


def test_theAbandonedRecordNamesTheStepAndTheCause_notMerelyThatSomethingWentWrong(monkeypatch, tmp_path,
                                                                                  runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    _stub_chain(monkeypatch, {})
    _raising_report(monkeypatch, OSError("No space left on device"))

    # act
    with pytest.raises(OSError):
        testrun.accept([])

    # assert: a stamp that said only "failed" would be the defect wearing a hat. It names the step that
    # raised, the exception type and its message, because that is what a week-old record is FOR.
    entry = verdict_module.read_stamp(str(tmp_path / "test/reports"))["gates"][-1]
    assert entry["gate"] == "report"
    assert "OSError" in entry["line"]
    assert "No space left on device" in entry["line"]
    assert "abandoned" in entry["line"]


def test_theAbandonedRecordKeepsTheGatesThatDidFinish(monkeypatch, tmp_path, runner):
    # arrange: one red gate, one green, then a report step that raises
    _register(monkeypatch, tmp_path, _data())
    _stub_chain(monkeypatch, {"system": 1})
    _raising_report(monkeypatch, ValueError("a broken result file"))

    # act
    with pytest.raises(ValueError):
        testrun.accept([])

    # assert: the record is CUMULATIVE, not a single line about the crash - what the run did learn before
    # it was cut short is exactly what a reader came for
    gates = verdict_module.read_stamp(str(tmp_path / "test/reports"))["gates"]
    assert [g["gate"] for g in gates] == ["system", "acceptance-dataplane", "report"]
    assert [g["verdict"] for g in gates] == ["failed", "passed", "failed"]


def test_aGateThatRaisesIsRecordedUnderItsOwnName_notUnderTheReportStep(monkeypatch, tmp_path, runner):
    # arrange: the same property one step earlier. `assess_gate` does filesystem work and calls product
    # hooks, so it can raise for reasons of its own, and the stamp of the gate BEFORE it would then be the
    # run's whole record.
    _register(monkeypatch, tmp_path, _data())

    def assess(gate, cfg, extra, *, filtered, earlier=()):
        if gate.name == "acceptance-dataplane":
            raise RuntimeError("the product's preamble hook blew up")
        return _gv(gate.name, 0)

    monkeypatch.setattr(testrun, "assess_gate", assess)

    # act
    with pytest.raises(RuntimeError):
        testrun.accept([])

    # assert: the run is red, and it says WHICH step ended it
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert stamp["verdict"] == "failed"
    assert [g["gate"] for g in stamp["gates"]] == ["system", "acceptance-dataplane"]
    assert "RuntimeError" in stamp["gates"][-1]["line"]


def test_anAbandonedExploratoryRunStampsIntoItsOwnFile_leavingTheCanonicalRecordAlone(monkeypatch,
                                                                                     tmp_path, runner):
    # arrange: a full green run's record, then a one-test hunt that falls over in the report step
    reports = str(tmp_path / "test/reports")
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.PASSED),)))
    _register(monkeypatch, tmp_path, _data())
    _stub_chain(monkeypatch, {})
    _raising_report(monkeypatch, OSError("boom"))

    # act
    with pytest.raises(OSError):
        testrun.accept(["-k", "one_test"])

    # assert: the quarantine holds on the way out too - an exploratory crash must not overwrite the
    # finding of the last full gate, which is the rule the whole filtered path exists for
    assert verdict_module.read_stamp(reports)["verdict"] == "passed"
    assert verdict_module.read_stamp(reports, filtered=True)["verdict"] == "failed"


def test_accept_isUnchangedWhenNothingRaises_soTheRecordingDidNotBecomeTheVerdict(monkeypatch, tmp_path,
                                                                                 runner):
    # arrange: the ordinary green chain, through the same try
    _register(monkeypatch, tmp_path, _data())
    _stub_chain(monkeypatch, {})

    # act
    rc = testrun.accept([])

    # assert: no `report`-that-raised entry invented, and the exit code is the one it always was
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert rc == 0
    assert stamp["verdict"] == "passed"
    assert [g["gate"] for g in stamp["gates"]] == ["system", "acceptance-dataplane", "report"]
    assert all("raised" not in g["line"] for g in stamp["gates"])


def test_report_putsTheRunsVerdictIntoTheArchiveItArchives(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **kw: allure.Render(report="r.html",
                                                                                       tool="allure"))
    # `owned_results` is what the pytest gate that ran this dir reports (si#69); without it the run owns
    # no archive to speak in, which is the case the test below covers
    run = RunVerdict((GateVerdict("system", Verdict.SETUP_FAILED, 1, "provision", owned_results=True),))

    # act
    testrun.report(cfg, run=run)

    # assert
    written = (tmp_path / "test/reports/allure-results" / allure.ENVIRONMENT).read_text(encoding="utf-8")
    assert "verdict=setup-failed" in written


def test_report_leavesTheArchiveAloneForARunOfGatesThatTookNothing(monkeypatch, tmp_path, runner):
    # arrange: the last real run's archive, and a run made only of product-owned gates that appended -
    # they returned a number, took no dir and wrote no file, so the archive standing there is not theirs
    # (si#69). This used to be written over, because the run's verdict was derived from `not NOT_RUN`
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **kw: allure.Render(report="r.html",
                                                                                       tool="allure"))
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    allure.write_environment(str(results), {"verdict": "failed", "verdict.summary": "last run was red"})
    run = RunVerdict((GateVerdict("ui", Verdict.PASSED, 0),))

    # act
    assert not run.owns_results
    testrun.report(cfg, run=run)

    # assert: the last real run's verdict still stands, unaltered by a run that owned nothing
    written = allure.read_environment(str(results / allure.ENVIRONMENT))
    assert written["verdict"] == "failed", (
        f"a run that took no results dir wrote its verdict into somebody else's archive: {written}")
    assert written["verdict.summary"] == "last run was red"


# --- an exploratory run must not speak for the archive it did not run (#30, review 1) ---------------------
#
# The quarantine rule already keeps a `-k` run's RESULTS out of the shared archive. Its VERDICT has to
# follow, or the two records of one directory contradict each other in silence: a green one-test hunt
# stamping `passed` over the finding of a red full gate is the worse direction, and it is exactly the
# "partial run that does not look like one" the quarantine exists for.


def _run_gate_as_command(name, args, tmp_path):
    """Invoke the gate the way the CLI does, so the stamp is written by the code path a user reaches."""
    return testrun.gate(SimpleNamespace(info_name=name, args=list(args)), name=name)


def test_anExploratoryRunStampsIntoItsOwnFile_leavingTheFullGatesRecordAlone(monkeypatch, tmp_path, runner):
    # arrange: a full, green gate has stamped the canonical record
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    _run_gate_as_command("system", [], tmp_path)

    # act: a one-test hunt that goes red
    runner["rc"] = 1
    rc = _run_gate_as_command("system", ["-k", "one_test"], tmp_path)

    # assert: red on the way out, its own record written, and the canonical one untouched
    assert rc == 1
    assert verdict_module.read_stamp(reports)["verdict"] == "passed"
    partial = verdict_module.read_stamp(reports, filtered=True)
    assert partial["verdict"] == "failed" and partial["filtered"] is True
    assert partial["line"].startswith("partial run - ")


def test_aGreenExploratoryRunCannotStampOverTheFindingOfARedFullGate(monkeypatch, tmp_path, runner):
    # arrange: the worse direction - a red full gate's finding is the thing that must survive
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    runner["rc"] = 1
    _run_gate_as_command("system", [], tmp_path)

    # act: a green `-k` run afterwards
    runner["rc"] = 0
    _run_gate_as_command("system", ["-k", "the_one_that_passes"], tmp_path)

    # assert: the canonical record still says the full gate was red
    assert verdict_module.read_stamp(reports)["verdict"] == "failed"
    assert verdict_module.read_stamp(reports, filtered=True)["verdict"] == "passed"


def test_accept_stampsAnExploratoryRunIntoItsOwnFileToo(monkeypatch, tmp_path, runner):
    # arrange
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.PASSED),)))
    _stub_chain(monkeypatch, {"system": 1})

    # act
    testrun.accept(["-k", "one"])

    # assert
    assert verdict_module.read_stamp(reports)["verdict"] == "passed"
    assert verdict_module.read_stamp(reports, filtered=True)["verdict"] == "failed"


def test_accept_stampsAnExploratoryAbortIntoTheExploratoryFile_notTheCanonicalOne(monkeypatch, tmp_path,
                                                                                  runner):
    # arrange: the section precondition refuses a `-k` run - the abort must be quarantined like the run
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    verdict_module.write_stamp(reports, RunVerdict((GateVerdict("system", Verdict.PASSED),)))
    runner["rc:product.health:check"] = 7
    _stub_chain(monkeypatch, {})

    # act
    assert testrun.accept(["-k", "one"]) == 7

    # assert
    assert verdict_module.read_stamp(reports)["verdict"] == "passed"
    assert verdict_module.read_stamp(reports, filtered=True)["verdict"] == "not-run"


# --- the run's verdict in the archive, not one gate's guess (#30, review 4) -------------------------------


def test_aLaterGreenGateCannotOverwriteAnEarlierGatesSetupFailureInTheArchive(monkeypatch, tmp_path, runner):
    # arrange: gate 1's setup fell over; gate 2 then runs green into the SAME results dir
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    broke = GateVerdict("system", Verdict.SETUP_FAILED, 1, "preamble")

    # act
    testrun.assess_gate(cfg.gates[1], cfg, [], filtered=False, earlier=(broke,))

    # assert: the archive states the RUN's weakest claim, not the last gate's own - the environment write
    # is a last-wins merge, so a gate stating a run verdict from its own knowledge would defeat the
    # precedence rule inside the one artefact it protects
    written = (tmp_path / "test/reports/allure-results" / allure.ENVIRONMENT).read_text(encoding="utf-8")
    assert "verdict=setup-failed" in written
    assert "verdict.gate.system=setup failed (preamble, rc 1)" in written
    assert "verdict.gate.acceptance-dataplane=passed" in written


def test_report_leavesTheLastRealRunsArchiveAlone_whenNoGateOfThisRunEverStarted(monkeypatch, tmp_path,
                                                                                 runner):
    # arrange: a full run's archive, and a run whose every gate refused before touching anything
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    results = tmp_path / "test/reports/allure-results"
    results.mkdir(parents=True)
    allure.write_environment(str(results), {"verdict": "passed"})
    monkeypatch.setattr(testrun.allure, "render_report", lambda *a, **kw: allure.Render())

    # act
    testrun.report(cfg, run=RunVerdict((GateVerdict("system", Verdict.NOT_RUN, 7, "precondition"),)))

    # assert: untouched - stating this run's verdict there is the stale-verdict defect pointing the
    # other way
    assert "verdict=passed" in (results / allure.ENVIRONMENT).read_text(encoding="utf-8")


# --- the report step gets its own words (#30, review 3) ---------------------------------------------------


def test_theReportStepIsNotDescribedAsASuiteThatRanAndFoundSomething(monkeypatch, tmp_path, runner):
    # arrange: every gate green, the archive render red (#6)
    _register(monkeypatch, tmp_path, _data())
    reports = str(tmp_path / "test/reports")
    _stub_chain(monkeypatch, {}, report_rc=1)

    # act
    assert testrun.accept([]) == 1

    # assert: it ran no suite, so it must not borrow the sentence written for one - the stamp would
    # otherwise carry a false statement of exactly the kind this whole change removes
    stamp = verdict_module.read_stamp(reports)
    step = [g for g in stamp["gates"] if g["gate"] == "report"][0]
    assert step["verdict"] == "failed"
    assert "the suite ran" not in step["line"]
    assert "no archive" in step["line"] or "wrote no archive" in step["line"]


def test_aRedReportStepThatIsTheWeakestElementDoesNotPutSuiteWordingIntoTheRunSummary(monkeypatch, tmp_path,
                                                                                      runner):
    # arrange: gates green, render red - the report step IS then the run's weakest element
    _register(monkeypatch, tmp_path, _data())
    _stub_chain(monkeypatch, {}, report_rc=1)

    # act
    testrun.accept([])

    # assert
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert stamp["line"].startswith("report: failed")
    assert "the suite ran" not in stamp["line"]


# --- a run a signal ended (#55) ---------------------------------------------------------------------------
#
# THE SUBPROCESS SEAM IS NOT STUBBED IN THIS SECTION, and that is the whole point of it. Every other test in
# this file hands `assess_gate` an rc; a rc typed into a test would prove only that the branch exists, and
# the defect was never in the branch - it was in the claim the kernel made about a process it had actually
# watched die. So the "pytest" these tests run is a real child that raises a real signal on itself, `run`
# is the kernel's own, and the rc travels the seam it travels in the field. The output is empty here for
# the same reason it was empty in the report that opened #55: nobody was left to write any.


def _shot_gate(monkeypatch, tmp_path, signum):
    """A one-gate taxonomy whose suite is a real child process that kills itself with `signum`.

    Everything the gate needs OFF the machine is still stubbed - the keep-awake window and the per-suite
    venv - because neither is what is under test. The subprocess call is not.
    """
    data = _data()
    data["suites"]["gates"] = [{"name": "unit", "suite": "test/unit/python", "results": "clear",
                                "junit": "junit.xml"}]
    _register(monkeypatch, tmp_path, data)
    (tmp_path / "test/unit/python").mkdir(parents=True)
    monkeypatch.setattr(testrun, "keep_awake", contextlib.nullcontext)
    monkeypatch.setattr(testrun.pyvenv, "venv_python_pip", lambda d: (sys.executable, "pip"))
    monkeypatch.setattr(testrun.allure, "integration_pytest_argv",
                        lambda py, results, junit, extra: [
                            py, "-c", f"import os, signal; os.kill(os.getpid(), {signum})"])
    return testrun.config()


def test_aSuiteThatWasShotDoesNotClaimToHaveRunAndReportedFailures(monkeypatch, tmp_path):
    # arrange: a real child, terminated by a real SIGTERM
    cfg = _shot_gate(monkeypatch, tmp_path, 15)

    # act
    gv = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: the rc the operating system produced, and a sentence that is about the RUN and not about the
    # product - the old one said "the suite ran and reported failures" about an empty output
    assert gv.rc == -15
    assert gv.verdict is Verdict.KILLED
    assert not gv.verdict.ran
    assert gv.line == ("killed (SIGTERM) - the suite was ended by a signal and reported nothing, so this "
                       "says nothing about the product")


def test_everySignalGetsItsOwnNameFromARealChild_notOneNegativeNumberForAllOfThem(monkeypatch, tmp_path):
    # arrange / act: the three other signals #55 names, each shot for real
    lines = {}
    for signum in (9, 6, 11):
        cfg = _shot_gate(monkeypatch, tmp_path / str(signum), signum)
        lines[signum] = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False).line

    # assert: three different sentences where the kernel used to produce one
    assert lines[9].startswith("killed (SIGKILL)")
    assert lines[6].startswith("killed (SIGABRT)")
    assert lines[11].startswith("killed (SIGSEGV)")


def test_aShotGateSaysSoInTheArchiveAndInTheStamp_notOnlyOnTheTerminal(monkeypatch, tmp_path):
    # arrange: the gate is invoked the way the CLI invokes it, so the stamp is written too
    cfg = _shot_gate(monkeypatch, tmp_path, 15)
    ctx = SimpleNamespace(info_name="unit", args=[])

    # act
    rc = testrun.gate(ctx, name="unit")

    # assert: red on the terminal, and both written records say WHAT ended it rather than claiming a
    # suite reported something
    assert rc != 0
    written = (tmp_path / "test/reports/allure-results" / allure.ENVIRONMENT).read_text(encoding="utf-8")
    assert "verdict=killed" in written
    assert "killed (SIGTERM)" in written
    stamp = verdict_module.read_stamp(str(tmp_path / "test/reports"))
    assert stamp is not None
    assert stamp["verdict"] == "killed" and stamp["gates"][0]["rc"] == -15
    assert "SIGTERM" in stamp["line"]


def test_aShotGateExitsWithTheNumberAShellWritesForThatSignal_ratherThanTheModuloOfIt(monkeypatch, tmp_path):
    # arrange: the same shot gate, through both callers that hand an rc to the process
    cfg = _shot_gate(monkeypatch, tmp_path, 15)
    ctx = SimpleNamespace(info_name="unit", args=[])

    # act
    from_run_gate = testrun.run_gate(cfg.gates[0], cfg, [], filtered=False)
    from_callback = testrun.gate(ctx, name="unit")

    # assert: 143, which is what `sh` reported for the identical child in tests/test_verdict.py - and NOT
    # the 241 `sys.exit(-15)` would have manufactured. The record keeps the wait status either way.
    assert from_run_gate == from_callback == verdict_module.exit_code(-15)
    assert from_run_gate != 241 and from_run_gate != 0
    assert testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False).rc == -15


def test_aRunThatWasShotOutranksAGateWhoseSetupMerelyBroke(monkeypatch, tmp_path, runner):
    # arrange: one gate's lab fell over, another was shot - the state after a signal reached a process
    # group rather than a single child
    shot = GateVerdict("unit", Verdict.KILLED, -15)
    broken = GateVerdict("system", Verdict.SETUP_FAILED, 1, "preamble")

    # act
    run = RunVerdict((shot, broken))

    # assert: the run reports the signal, because it is what explains the broken lab and not the reverse
    assert run.verdict is Verdict.KILLED
    assert run.line.startswith("unit: killed (SIGTERM)")


def test_aGateThatMerelyExitsNonZeroIsStillARedSuite_soTheSignalReadingDidNotSwallowIt(monkeypatch,
                                                                                       tmp_path):
    # arrange: the ordinary red run, through the same unstubbed seam - a child that exits 1 by itself
    cfg = _shot_gate(monkeypatch, tmp_path, 15)
    monkeypatch.setattr(testrun.allure, "integration_pytest_argv",
                        lambda py, results, junit, extra: [py, "-c", "import sys; sys.exit(1)"])

    # act
    gv = testrun.assess_gate(cfg.gates[0], cfg, [], filtered=False)

    # assert: unchanged wording and an unchanged exit code for the case that was never broken
    assert gv.verdict is Verdict.FAILED
    assert gv.line == "failed (rc 1) - the suite ran and reported failures"
    assert testrun.run_gate(cfg.gates[0], cfg, [], filtered=False) == 1


# --- what the gate command hands the process (si#71) -----------------------------------------------------


def test_gate_handsOnAnImplRunnersNegativeReturnValueWithoutCallingItASignal(monkeypatch, tmp_path,
                                                                            runner):
    # arrange: an `impl:` gate whose body answers -1 - "could not read", which is what
    # `simplon.waits.device_count` means by it in this repository - not a child killed by SIGHUP
    data = _data()
    data["suites"]["gates"] = [data["suites"]["gates"][0],
                               {"name": "ui", "impl": "product.tooling:ui"}]
    _register(monkeypatch, tmp_path, data)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: -1))
    cfg = testrun.config()

    # act
    rc = testrun.run_gate(cfg.gate("ui"), cfg, [], filtered=False)

    # assert: red, and not 129 - the translation belongs to a wait status and this is a return value
    assert rc == -1, f"a product runner's return value was translated as a signal status: {rc}"


def test_run_gate_stillTranslatesTheWaitStatusOfASuiteASignalKilled(monkeypatch, tmp_path, runner):
    # arrange: the case the translation exists for (#55) - the pytest child's negative wait status, which
    # `sys.exit` would otherwise take modulo 256 and leave a shell reading 241
    _register(monkeypatch, tmp_path, _data())
    cfg = testrun.config()
    monkeypatch.setattr(testrun, "run", lambda *a, **k: SimpleNamespace(rc=-15))

    # act
    rc = testrun.run_gate(cfg.gates[1], cfg, [], filtered=False)

    # assert
    assert rc == 143
