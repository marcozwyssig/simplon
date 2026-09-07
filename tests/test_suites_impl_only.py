"""si#61: an IMPL-ONLY test taxonomy, measured against the mechanism rather than argued.

THE CASE. A product whose only test runner is its own - a Gradle build, a browser journey suite - wants
to write the `suites:` section si#26 names: one gate, `impl:`, no pytest anywhere in the product. It did
not load. Both spellings were run against a real Java product and both were refused: without
`results: clear` because no gate declared the clear, and with `results: clear` on the impl gate because
an impl gate might not declare it. So a Java product shipped a Python test that asserts nothing about
the product, purely to own the shared allure results dir.

WHAT THE MEASUREMENTS SAID, AND WHICH ONE WAS THE REPAIR.

  - Nothing but a CLEARING GATE ever clears the shared results dir. `report()` merges into whatever is
    already there, so a taxonomy with no clearing gate merges run N into run N-1's results forever. That
    is still true and it is why `declared` still requires exactly one clearing gate.
  - `results: clear` on an impl gate PARSED (`Gate.clears` was True) and CLEARED NOTHING: `assess_gate`
    returned on the impl branch before the clear was reached. A key that counts and does nothing is
    worse than one that is refused - and refusing it was the wrong repair, because the clear could hang
    on no other kind of gate. **The inert branch is where the defect was, and it is fixed there**: an
    impl gate now honours `results: clear`, and the refusal that stood in for the fix is gone.

AND THE HALF THE FIX MUST NOT INVENT (CLAUDE.md). An impl gate CLEARS the dir and writes NOTHING into
it - the kernel calls the product's runner for its rc and learns nothing else. Those are two different
claims and a fix that let the second follow from the first would have moved the defect rather than
removed it: a run's verdict written into an archive no gate ever filled, over a report whose numbers came
from somewhere else. So what stays EMPTY is pinned here beside what runs, in the same tests.

Every gate below is built by calling `Gate`/`Suites` directly, deliberately: that is the only way past
`declared` to the mechanism underneath it, and the mechanism is the thing under test. The tests that DO
go through `declared` are the ones that pin what loads and what does not.

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


# --- what an impl-only taxonomy may now say, and what it still may not -----------------------------


def test_an_impl_only_taxonomy_loads_once_its_own_gate_owns_the_results_dir():
    """THE FIX, at the load path: the section si#26 asks for, with the clear on the product's own gate.

    Before si#61 this was refused - "an 'impl' gate cannot declare 'results'" - and the spelling without
    it was refused too, which between them left an impl-only product no loadable section at all.
    """
    # arrange: one gate, the product's own runner, no pytest anywhere
    data = _section({**IMPL_ONLY_GATE, "results": "clear"})

    # act
    cfg = testrun.declared(data, source="javademo.yaml")

    # assert: it loads, and the gate that owns the run's results dir is the product's own
    assert [gate.name for gate in cfg.gates] == ["unit"]
    assert cfg.gates[0].impl == "orchestrator.gradle:test" and not cfg.gates[0].suite
    assert cfg.gates[0].clears


def test_an_impl_only_taxonomy_that_declares_no_clear_is_still_refused():
    """The rule that did NOT go. Somebody has to own the dir, and the measurement below says why: nothing
    else empties it, so a taxonomy with no clearing gate merges this run into the last one's results
    forever. What changed is who may own it, not whether anybody must."""
    # arrange
    data = _section(IMPL_ONLY_GATE)

    # act / assert
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="javademo.yaml")

    assert "exactly one gate must declare results: clear" in str(refused.value), (
        f"the refusal no longer names the missing clear: {refused.value}")
    assert "got none" in str(refused.value), (
        f"the refusal no longer says WHICH gates clear (none): {refused.value}")


def test_the_refusal_names_the_way_out_and_not_only_the_cause():
    """CLAUDE.md: a message that names the cause and the way out is worth writing; one that says
    something went wrong is the defect wearing a hat. This one used to name only the rule, which for an
    impl-only product pointed at a spelling the next refusal then rejected."""
    # arrange
    data = _section(IMPL_ONLY_GATE)

    # act
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="javademo.yaml")

    # assert: it says who may carry the clear, which is the whole of what the reader has to do next
    said = str(refused.value)
    assert "'impl' one included" in said, f"the refusal names no way out: {said}"


def test_an_impl_gate_still_may_not_declare_the_three_keys_that_do_nothing_on_it():
    """The rest of the opacity lock, which si#61 did not touch. `junit`, `args` and `preamble` are still
    inert on a gate the kernel only calls for an rc, so declaring one is still refused and still named."""
    # arrange
    stray = {"junit": "unit.xml", "args": True, "preamble": "orchestrator.lab:ready"}

    # act / assert: each on its own, so the message is about the key and not about the set
    for key, value in stray.items():
        with pytest.raises(ValueError) as refused:
            testrun.declared(_section({**IMPL_ONLY_GATE, "results": "clear", key: value}),
                             source="javademo.yaml")
        assert f"an 'impl' gate cannot declare '{key}'" in str(refused.value), (
            f"the refusal no longer names the offending key '{key}': {refused.value}")
        assert "only calls its runner for the rc" in str(refused.value), (
            f"the refusal no longer gives its reason: {refused.value}")


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


def test_results_clear_on_an_impl_gate_now_actually_clears(monkeypatch, tmp_path):
    """THE FIX, at the mechanism. This test used to assert the opposite and named the condition under
    which it would change: "if that is deliberate, the refusal in `_gate` has become an expression rule".
    It did not become one - it went, because the inert branch was the defect and the refusal was standing
    in for the repair.

    What an impl gate declaring the clear does is exactly what it says: the run's results dir starts
    empty. Nothing else about the gate changed.
    """
    # arrange: an impl gate that says it clears, and last run's leftovers for it to clear
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    (results / "STALE-from-an-earlier-run-result.json").write_text("{}", encoding="utf-8")
    scratch = tmp_path / "build" / "reports" / testrun.SCRATCH
    scratch.mkdir(parents=True)
    (scratch / "index.html").write_text("last run's render", encoding="utf-8")
    gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test", results=testrun.CLEAR)

    # act
    assert gate.clears, "the taxonomy would not even have counted this gate as the clearing one"
    gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

    # assert: green, the dir is there and it is empty, and the stale render went with it
    assert gv.verdict is Verdict.PASSED
    assert results.is_dir(), "the clear removed the results dir instead of emptying it"
    assert sorted(path.name for path in results.iterdir()) == [], (
        "an impl gate declaring results: clear left the previous run's results standing - which is the "
        "forever-appending archive the clear-versus-append rule exists to prevent")
    assert not scratch.exists(), "the transient render dir of the last run survived the clear"


def test_an_appending_impl_gate_clears_nothing(monkeypatch, tmp_path):
    """The other half of the same key, so the fix is a distinction and not a blanket. A gate that does
    not declare the clear must leave the dir exactly as it found it - otherwise the second gate of a run
    would delete the first one's results, which is what the rule is against."""
    # arrange
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    (results / "EARLIER-GATE-of-this-run-result.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="ui", suite="", impl="orchestrator.journeys:run")

    # act
    assert not gate.clears
    gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.PASSED
    assert (results / "EARLIER-GATE-of-this-run-result.json").exists(), (
        "an appending impl gate deleted what an earlier gate of the same run had written")


def test_a_clearing_impl_gate_of_an_exploratory_run_clears_the_quarantine_and_not_the_archive(
        monkeypatch, tmp_path):
    """The quarantine rule reaches the new branch too. An exploratory run is partial by construction, so
    its clear must land in `filtered_results` and the canonical archive of the last full gate must be
    untouched - the same guarantee a pytest gate already had, and a fix that opened the clear to a second
    branch without carrying that rule across would have re-opened it."""
    # arrange: a full archive beside an empty quarantine
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    archive = _results_dir(tmp_path)
    archive.mkdir(parents=True)
    (archive / "THE-LAST-FULL-GATE-result.json").write_text("{}", encoding="utf-8")
    quarantine = tmp_path / "build" / "reports" / f"{RESULTS}-filtered"
    quarantine.mkdir(parents=True)
    (quarantine / "LAST-HUNT-result.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test", results=testrun.CLEAR)

    # act
    testrun.assess_gate(gate, _cfg(gate), ["-k", "adds"], filtered=True)

    # assert
    assert (archive / "THE-LAST-FULL-GATE-result.json").exists(), (
        "a one-test hunt cleared the canonical archive of the last full gate")
    assert sorted(path.name for path in quarantine.iterdir()) == [], (
        "the exploratory run did not clear its own quarantined results dir")


# --- what a fix must not invent ------------------------------------------------------------------------


def test_an_impl_gate_writes_nothing_into_the_shared_results_dir(monkeypatch, tmp_path):
    """The empty half, pinned beside the running half (CLAUDE.md: a fix must not invent the missing
    capability). The kernel calls the product's runner for its rc and has no honest basis for saying more,
    so an impl gate contributes no allure result and no environment of its own. A fix that lets an
    impl-only taxonomy load must leave this assertion standing.
    """
    # arrange: an empty results dir and an impl gate that succeeds - BOTH spellings of `results`, because
    # si#61 opened the clear to this branch and clearing a dir is not the same claim as filling one
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    for spelling in (testrun.APPEND, testrun.CLEAR):
        gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test", results=spelling)

        # act
        gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

        # assert: green, and it left nothing behind - not even the environment every pytest gate writes
        assert gv.verdict is Verdict.PASSED
        assert sorted(path.name for path in results.iterdir()) == [], (
            f"an impl gate with results: {spelling} wrote into the shared results dir; the kernel knows "
            f"only this gate's rc, so anything in there is a statement about the product that nobody made")
        assert not (results / "environment.properties").exists()


def test_a_run_of_only_impl_gates_does_not_claim_an_archive_it_never_filled(monkeypatch, tmp_path):
    """si#69, the seam the two refusals used to hold shut - now that one of them is gone.

    `RunVerdict.owns_results` is the one condition under which a run's verdict may be written into the
    archive. Its predecessor was derived from the gate verdicts alone (`anything but not-run`), and its
    docstring answered the obvious objection by saying an impl-only run could not reach it - because
    `declared` refused such a taxonomy. That was true of the LOAD PATH and not of the property. si#61
    let an impl-only taxonomy load, so the scaffolding is gone and the property has to stand by itself.

    It does now, by asking each gate what it took rather than what it found.
    """
    # arrange: the run an impl-only taxonomy produces, and the dir it did not write
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    appending = testrun.Gate(name="ui", suite="", impl="orchestrator.journeys:run")
    gv = testrun.assess_gate(appending, _cfg(appending), [], filtered=False)

    # act
    run = RunVerdict((gv,))

    # assert: green, empty, and it no longer claims to have written the archive standing there
    assert run.verdict is Verdict.PASSED
    assert sorted(path.name for path in results.iterdir()) == []
    assert run.owns_results is False, (
        "a run of product-owned gates that wrote nothing still claims the results dir; the archive in "
        "there belongs to whichever run last filled it, and stating this run's verdict in it is the "
        "stale-verdict defect with the sign flipped")


def test_a_clearing_impl_gate_owns_the_dir_it_emptied_but_still_wrote_nothing(monkeypatch, tmp_path):
    """The other side, and the reason `owned_results` is not simply False on this branch. A gate that
    cleared the dir DID take it: the archive there is this run's, empty or not, and the run's verdict
    belongs in it - an empty report that says why is the honest artefact, and it is the one si#70 asks
    for. What the gate still did not do is write a result, and both halves are asserted here so a later
    fix cannot trade one for the other."""
    # arrange
    _register(monkeypatch, tmp_path)
    monkeypatch.setattr(testrun, "resolve_ref", lambda ref, where: (lambda: 0))
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    (results / "STALE-from-an-earlier-run-result.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="unit", suite="", impl="orchestrator.gradle:test", results=testrun.CLEAR)

    # act
    gv = testrun.assess_gate(gate, _cfg(gate), [], filtered=False)

    # assert: it owns the dir, and the dir is empty
    assert RunVerdict((gv,)).owns_results is True, (
        "the gate that emptied the results dir does not own it, so the run has nowhere to state its "
        "verdict and an impl-only product gets an archive with no verdict widget at all")
    assert sorted(path.name for path in results.iterdir()) == [], (
        "owning the dir was read as filling it - the kernel knows one number here and no result")


# --- the mixed taxonomy, which is what most products have ------------------------------------------------


def test_a_pytest_gate_may_still_own_the_dir_for_an_impl_gate_behind_it():
    """The workaround si#26 had to build is still a legal taxonomy - it just is not the only one any
    more. This is what every existing product declares (a pytest first gate, a product-owned runner
    behind it), and si#61 must not have taken it away: measured over all seven reachable manifests, two
    declare a `suites:` section and both open with a clearing pytest gate.
    """
    # arrange: the section the Java product had to ship before si#61
    data = _section({"name": "bootstrap", "suite": "tests/bootstrap", "junit": "bootstrap-junit.xml",
                     "results": "clear"},
                    IMPL_ONLY_GATE)

    # act
    cfg = testrun.declared(data, source="javademo.yaml")

    # assert: unchanged - it loads, and the Python gate still owns the dir
    assert [gate.name for gate in cfg.gates] == ["bootstrap", "unit"]
    assert cfg.gates[0].suite == "tests/bootstrap" and cfg.gates[0].clears
    assert cfg.gates[1].impl and not cfg.gates[1].clears


def test_a_clearing_impl_gate_must_still_be_the_first_one():
    """The ordering rule reaches the new spelling as well. A clear that runs second deletes what the
    first gate wrote, and whether the clearing gate is the kernel's or the product's changes nothing
    about that."""
    # arrange: the clear on the impl gate, and a pytest gate ahead of it
    data = _section({"name": "bootstrap", "suite": "tests/bootstrap", "junit": "bootstrap-junit.xml"},
                    {**IMPL_ONLY_GATE, "results": "clear"})

    # act / assert
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="javademo.yaml")
    assert "is not the FIRST gate" in str(refused.value), (
        f"a clearing impl gate was allowed to run second: {refused.value}")


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
