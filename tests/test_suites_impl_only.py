"""si#61: what an IMPL-ONLY test taxonomy runs into, measured against the mechanism rather than argued.

THE CASE. A product whose only test runner is its own - a Gradle build, a browser journey suite - wants
to write the `suites:` section si#26 names: one gate, `impl:`, no pytest anywhere in the product. It does
not load. Both spellings were run against a real Java product and both were refused: without
`results: clear` because no gate declares the clear, and with `results: clear` on the impl gate because an
impl gate may not declare it. So a Java product ships a Python test that asserts nothing about the product,
purely to own the shared allure results dir.

WHY THIS FILE EXISTS RATHER THAN A PATCH. The ticket reads the pair as an EXPRESSION RULE - the kind that
costs flexibility, and the only kind that owes an argument. The census in `test_refusal_census.py` sorts a
refusal by one question: *would the refused manifest have produced a WORKING product, just a different
one?* That question is answerable by measurement, and the answer decides whether the fix is a looser rule
or a better message. So it is measured here, at the mechanism, and the census entries for these two
refusals cite these tests.

WHAT THE MEASUREMENTS SAY.

  - Nothing but a CLEARING GATE ever clears the shared results dir. `report()` merges into whatever is
    already there, so a taxonomy with no clearing gate merges run N into run N-1's results forever. The
    refused manifest would NOT have produced a working product -> diagnosis.
  - `results: clear` on an impl gate PARSES (`Gate.clears` is True) and CLEARS NOTHING: `assess_gate`
    returns on the impl branch before the clear is reached. The declaration is inert -> diagnosis.

AND THE HALF A FIX MUST NOT INVENT. An impl gate writes NOTHING into the shared results dir - the kernel
calls the product's runner for its rc and learns nothing else - yet `RunVerdict.wrote_results` already says
True for a run made only of impl gates. Today that pair is unreachable, held apart by the very refusals
above. The day an impl-only taxonomy is allowed to load, it is reachable, and a fix that lets the run write
its verdict into an archive no gate filled would have MOVED the defect rather than removed it. So what
stays EMPTY is pinned here beside what runs.

Every gate below is built by calling `Gate`/`Suites` directly, deliberately: that is the only way past
`declared` to the mechanism underneath it, and the mechanism is the thing under test. The two tests that
DO go through `declared` are the two that pin the refusals themselves.

AAA throughout.
"""
import os

import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.tasks import testrun
from simplon.verdict import GateVerdict, RunVerdict, Verdict

#: The results dir every canonical gate writes into, relative to the product's report dir. Read off the
#: module rather than retyped, so a rename of the convention cannot leave this file measuring a path
#: nothing uses.
RESULTS = testrun.RESULTS

#: The taxonomy si#26 asks for and si#61 measured: one gate, the product's own runner, no pytest.
IMPL_ONLY_GATE = {"name": "unit", "impl": "orchestrator.gradle:test"}


def _section(*gates, **overrides):
    """An otherwise complete `suites:` section around the given gates, so a refusal below can only be
    about the gates - every other key it needs is present and valid."""
    section = {"reports": "build/reports", "gates": list(gates),
               "report": {"parent_suite": "Java", "merge": ["build/junit-xml"]}}
    section.update(overrides)
    return {"suites": section}


def _register(monkeypatch, tmp_path):
    """A product context rooted at `tmp_path`, so every path the module computes lands under the tmpdir
    and the measurements below run against a real filesystem rather than a stubbed one."""
    ctx = ProductContext("javademo", tmp_path, tmp_path / "javademo.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    return ctx


def _results_dir(tmp_path):
    return tmp_path / "build" / "reports" / RESULTS


def _cfg(*gates, merge=()):
    return testrun.Suites(reports="build/reports", filtered_results=f"{RESULTS}-filtered",
                          gates=gates, merge=tuple(merge), parent_suite="Java")


# --- the two refusals, pinned against their real messages ------------------------------------------------


def test_an_impl_only_taxonomy_is_refused_because_no_gate_declares_the_clear():
    """Horn one, as si#26 wrote the section: the manifest the Java use case actually wants."""
    # arrange
    data = _section(IMPL_ONLY_GATE)

    # act / assert
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="javademo.yaml")

    assert "exactly one gate must declare results: clear" in str(refused.value), (
        f"the refusal no longer names the missing clear: {refused.value}")
    assert "got none" in str(refused.value), (
        f"the refusal no longer says WHICH gates clear (none): {refused.value}")


def test_an_impl_gate_may_not_declare_the_clear_that_would_have_satisfied_the_first_refusal():
    """Horn two: the obvious answer to horn one, and the trap closing. Note what the two messages between
    them do NOT say - that an impl-only product has no third spelling at all."""
    # arrange
    data = _section({**IMPL_ONLY_GATE, "results": "clear"})

    # act / assert
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="javademo.yaml")

    assert "an 'impl' gate cannot declare 'results'" in str(refused.value), (
        f"the refusal no longer names the offending key: {refused.value}")
    assert "only calls its runner for the rc" in str(refused.value), (
        f"the refusal no longer gives its reason: {refused.value}")


def test_the_two_refusals_leave_an_impl_only_product_no_loadable_spelling():
    """The pair, as a pair. Either refusal alone would be an inconvenience; together they are the finding,
    and a fix that removes only one of them still leaves the section unwritable."""
    # arrange: every way an impl-only taxonomy can spell the clear
    spellings = [_section(IMPL_ONLY_GATE),
                 _section({**IMPL_ONLY_GATE, "results": "clear"}),
                 _section({**IMPL_ONLY_GATE, "results": "append"})]

    # act
    refused = []
    for data in spellings:
        with pytest.raises(ValueError) as raised:
            testrun.declared(data, source="javademo.yaml")
        refused.append(str(raised.value))

    # assert: all three, and each for a stated reason rather than the same one three times
    assert len(refused) == len(spellings)
    assert len({line.split(": ", 1)[-1] for line in refused}) == 2, (
        f"the three spellings were expected to fail for two distinct stated reasons: {refused}")


# --- the property the refusals protect, measured -------------------------------------------------------


def test_only_a_clearing_gate_clears_the_shared_results_dir(monkeypatch, tmp_path):
    """THE MEASUREMENT THAT SORTS THE REFUSAL. If the report step cleared, an impl-only taxonomy with no
    clearing gate would have produced a working product and the refusal would be an expression rule.

    It does not clear. A file staged as the leftover of an imaginary earlier run survives the whole report
    step and is merged into this run's archive - which is exactly the forever-appending archive the
    clear-versus-append rule exists to prevent. So the refusal takes nothing away: the manifest it refuses
    could not have worked, and that is diagnosis.

    If this ever goes green, the classification has changed: say so in `test_refusal_census.py` rather
    than deleting the assertion.
    """
    # arrange: last run's result still sitting in the shared dir, and this run's merge source beside it
    _register(monkeypatch, tmp_path)
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    (results / "STALE-from-an-earlier-run-result.json").write_text("{}", encoding="utf-8")
    merged_from = tmp_path / "build" / "junit-xml"
    merged_from.mkdir(parents=True)
    (merged_from / "TEST-demo.CalculatorTest.xml").write_text("<testsuite/>", encoding="utf-8")
    monkeypatch.setattr(testrun.allure, "render_report",
                        lambda *a, **kw: testrun.allure.Render(report="archive.html", tool="allure"))

    # act: the report step of an impl-only run - the only step such a run has that touches the dir
    rc = testrun.report(_cfg(testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test"),
                             merge=["build/junit-xml"]),
                        run=RunVerdict((GateVerdict("unit", Verdict.PASSED, 0),)))

    # assert: this run's merge landed, AND last run's result is still there beside it
    assert rc == 0
    written = {path.name for path in results.iterdir()}
    assert "TEST-demo.CalculatorTest.xml" in written, f"the merge did not run at all: {sorted(written)}"
    assert "STALE-from-an-earlier-run-result.json" in written, (
        "the report step cleared the shared results dir - nothing but a clearing gate used to do that, "
        "which is the whole reason the missing-clear refusal is diagnosis and not an expression rule")


def test_results_clear_on_an_impl_gate_parses_and_then_clears_nothing(monkeypatch, tmp_path):
    """The second refusal's reason, measured rather than read off a comment.

    `results: clear` on an impl gate is not merely redundant: `Gate.clears` says True, so it would satisfy
    the exactly-one-clearing-gate rule, while `assess_gate` returns on the impl branch before the clear is
    ever reached. A declaration that counts and does nothing is the shape this repository refuses on
    sight, and refusing it takes nothing away - diagnosis, not an expression rule.
    """
    # arrange: an impl gate that says it clears, and something in the dir for it to clear
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    (results / "STALE-from-an-earlier-run-result.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test", results=testrun.CLEAR)

    # act
    assert gate.clears, "the taxonomy would not even have counted this gate as the clearing one"
    gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

    # assert: it passed, and the dir it claimed to clear is untouched
    assert gv.verdict is Verdict.PASSED
    assert (results / "STALE-from-an-earlier-run-result.json").exists(), (
        "the impl branch now honours results: clear - if that is deliberate, the refusal in `_gate` has "
        "become an expression rule and the census must say so")


# --- what a fix must not invent ------------------------------------------------------------------------


def test_an_impl_gate_writes_nothing_into_the_shared_results_dir(monkeypatch, tmp_path):
    """The empty half, pinned beside the running half (CLAUDE.md: a fix must not invent the missing
    capability). The kernel calls the product's runner for its rc and has no honest basis for saying more,
    so an impl gate contributes no allure result and no environment of its own. A fix that lets an
    impl-only taxonomy load must leave this assertion standing.
    """
    # arrange: an empty results dir and an impl gate that succeeds
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test")

    # act
    gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

    # assert: green, and it left nothing behind - not even the environment every pytest gate writes
    assert gv.verdict is Verdict.PASSED
    assert sorted(path.name for path in results.iterdir()) == [], (
        "an impl gate wrote into the shared results dir; the kernel knows only this gate's rc, so "
        "anything in there is a statement about the product that nobody made")
    assert not (results / "environment.properties").exists()


def test_a_run_of_only_impl_gates_already_claims_it_wrote_results(monkeypatch, tmp_path):
    """The seam the two refusals are currently holding shut, named so a fix cannot walk into it.

    `RunVerdict.wrote_results` is the one condition under which a run's verdict may be written into the
    archive, and its docstring says an impl-only run cannot reach it True by accident - because `declared`
    refuses such a taxonomy. That is true of the LOAD PATH and not of the property: the value is computed
    from the gate verdicts alone, and a passing impl gate that wrote nothing already answers True.

    So the refusal is load-time scaffolding around a seam that does not defend itself. Whoever lets an
    impl-only taxonomy load owns this too.
    """
    # arrange: the run an impl-only taxonomy would produce, and the dir it did not write
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test")
    gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

    # act
    run = RunVerdict((gv,))

    # assert: it says the run wrote results, and the dir is the second source saying it did not
    assert run.wrote_results is True
    assert sorted(path.name for path in results.iterdir()) == []
    assert run.verdict is Verdict.PASSED


# --- what the product does instead today ----------------------------------------------------------------


def test_the_taxonomy_that_loads_is_the_one_with_a_python_test_in_front_of_the_java_one(monkeypatch,
                                                                                        tmp_path):
    """The workaround si#26 had to build to measure anything at all, pinned as the price.

    The section loads only once a pytest gate stands in front of the product's own runner, owning the
    shared results dir. What that gate tests is not the kernel's business - and in the measured product it
    was `assert True`, because the product has no Python to test.
    """
    # arrange: exactly the section the Java product ships today
    data = _section({"name": "bootstrap", "suite": "tests/bootstrap", "junit": "bootstrap-junit.xml",
                     "results": "clear"},
                    IMPL_ONLY_GATE)

    # act
    cfg = testrun.declared(data, source="javademo.yaml")

    # assert: it loads, and the gate that owns the dir is the Python one rather than the product's own
    assert [gate.name for gate in cfg.gates] == ["bootstrap", "unit"]
    assert cfg.gates[0].suite == "tests/bootstrap" and cfg.gates[0].clears
    assert cfg.gates[1].impl and not cfg.gates[1].clears


def test_a_pytest_gate_that_declares_no_junit_name_would_have_written_to_a_directory(tmp_path):
    """A neighbour refusal in the same section, measured for the census beside the two above: a pytest
    gate without `junit:` is refused, and the reason is not tidiness. The name is spliced into the argv,
    and an empty one leaves pytest writing its junit report to the reports DIRECTORY."""
    # arrange
    data = _section({"name": "unit", "suite": "tests/unit", "results": "clear"})

    # act / assert: refused, naming the key
    with pytest.raises(ValueError, match="must declare its own 'junit' file name"):
        testrun.declared(data, source="javademo.yaml")

    # assert: and what it would have produced - a --junit-xml pointing at a directory, not a file
    argv = testrun.allure.integration_pytest_argv("py", str(tmp_path / RESULTS),
                                                  os.path.join(str(tmp_path), ""), [])
    junit_arg = next(arg for arg in argv if arg.startswith("--junit-xml="))
    assert junit_arg.endswith(os.sep), f"the empty junit name no longer degenerates to a dir: {junit_arg}"
