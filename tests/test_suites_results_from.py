"""si#133: a gate names the directory its own runner wrote results into, and a level that contributed
nothing goes red.

THE FINDING, and it is not the one the ticket's title states. `allure.merge_results` is
technology-agnostic and always was - its own docstring names foreign sources, it copies non-result files
through unchanged, and si#70's cutoff keeps a previous run's leavings out. javademo gets a real Allure
archive out of a Gradle run today by writing an `impl:` gate that CALLS that merge itself. So the merge
is not missing; the declarative way to reach it is. A product that declares the natural shape - a
`command:` gate over a toolchain command (si#106) - got an exit code and the sentence "the kernel ran a
command here, not a suite, and cannot say whether one ran at all".

`results_from:` is that way in, and the whole of the risk is in the second half. An Allure report
rendered with a level MISSING looks exactly like one where the level passed, so a merge that contributed
nothing must not be a green gate. Every red below is the point of the file rather than a guard around it;
`tests/test_suites_results_from_e2e.py` drives the same claim through a real ctest run and a rendered
archive, because a directory of hand-written files cannot say whether allure would read them.

AAA throughout.
"""
import contextlib
import os
import textwrap
from types import SimpleNamespace

import pytest

from simplon import context, test_impls
from simplon.context import ProductContext
from simplon.tasks import testrun
from simplon.verdict import Verdict

RESULTS = testrun.RESULTS

#: What a runner writes. Real ctest output rather than an invented shape: `ctest --output-junit` was run
#: against a three-test CMake project in `silkeh/clang:19` while this file was written, and this is what
#: came back, `name="(empty)"` included. A fixture that says `<testsuite name="unit">` would be a nicer
#: file than the one the tool actually produces, and the point of the merge is what the tool produces.
CTEST_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="(empty)" tests="1" failures="0" disabled="0" skipped="0" time="0">
\t<testcase name="AddsTwoNumbers" classname="AddsTwoNumbers" time="0.001" status="run"/>
</testsuite>
"""


#: What ctest writes when the selection matched nothing. The EXACT bytes, measured on 2026-09-09 in
#: `silkeh/clang:19`: `ctest --test-dir build -L <a label nothing carries> --output-junit <path>` prints
#: `No tests were found!!!`, exits 0, and writes this - a suite element with `tests="0"` and no case in
#: it. A file arrived, and the report it reaches has nothing in it.
EMPTY_CTEST_JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="(empty)"
\ttests="0"
\tfailures="0"
\tdisabled="0"
\tskipped="0"
\thostname=""
\ttime="0"
\ttimestamp="2026-09-09T20:00:39"/>
"""


def writes_empty_results(into: str = "") -> int:
    """A runner that exits 0 and writes a results file carrying no test case - `ctest -L` over a label
    nothing carries, and the same shape `dotnet test --filter` produces when the filter matches nothing.
    """
    directory = context.current().root / into
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ctest-junit.xml").write_text(EMPTY_CTEST_JUNIT, encoding="utf-8")
    test_impls.CALLS.append(("writes_empty_results", into, 0))
    return 0


def writes_unreadable_results(into: str = "") -> int:
    """A runner that exits 0 and writes its results in a format the kernel has no table entry for.

    It is a RUNNER rather than a file the test lays beside the run, and that is si#86's lesson applied
    one module over. A pre-placed file carries whatever second the fixture happened to land in, and the
    cutoff `_started` hands the merge is floored to the whole second, so a fixture written in second N
    and a gate that starts in second N+1 is left behind as the previous run's - by exactly the rule that
    exists to protect this run's own output. Seen red on the CI runner and reproduced here by ageing the
    tree one second at the instant the cutoff is taken. A file the RUN writes cannot fall on the wrong
    side of the run's own cutoff, and it is what a real runner does anyway.
    """
    directory = context.current().root / into
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.ndjson").write_text('{"name": "a case", "ok": true}\n', encoding="utf-8")
    test_impls.CALLS.append(("writes_unreadable_results", into, 0))
    return 0


def writes_results(rc: int = 0, into: str = "", name: str = "ctest-junit.xml") -> int:
    """A body standing in for a toolchain command that WRITES ITS RESULTS and returns an rc.

    `simplon.test_impls.pinned_rc` cannot do this half: it returns a pinned rc and records the call, and
    giving it a fourth parameter would change the `it takes: marker, rc, tag` refusal
    `test_suites_command_gate.py` pins. So this file keeps its own body, the way that file keeps
    `framed_body` - a local body is cheaper than a shared one that two suites then have to agree about.

    An empty `into` writes NOTHING, which is the case the whole feature is about: a runner that exits 0
    having produced no results at all.
    """
    if into:
        directory = context.current().root / into
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(CTEST_JUNIT, encoding="utf-8")
    test_impls.CALLS.append(("writes_results", into, rc))
    return rc

#: The same C++ product `test_suites_command_gate.py` uses, trimmed to what this file needs: one body,
#: two commands over it, and a gate command. Its manifest is real and is read off the disk, because a
#: gate resolves a command through the product's own tree and a stubbed resolution would verify the stub.
MANIFEST = """
product: cppdemo
tasks:
  toolchain: {{ impl: "simplon.test_impls:pinned_rc", help: "Run a pinned toolchain image." }}
  writer:    {{ impl: "test_suites_results_from:writes_results", help: "A runner that writes results." }}
  hollow:    {{ impl: "test_suites_results_from:writes_empty_results", help: "A runner that selects nothing." }}
  ndjson:    {{ impl: "test_suites_results_from:writes_unreadable_results", help: "A foreign format." }}
  gate:      {{ impl: "simplon.tasks.testrun:gate", help: "Run a declared level.", passthrough_args: true }}
groups:
  build:
    commands:
      compile: {{ task: toolchain, with: {{ rc: {compile_rc}, tag: "compile" }}, help: "Compile." }}
      marked:  {{ task: toolchain, with: {{ rc: 0, tag: "marked", marker: "{marker}" }}, help: "ctest." }}
      unit:    {{ task: writer, with: {{ rc: {unit_rc}, into: "{into}" }}, help: "ctest." }}
      hollow:  {{ task: hollow, with: {{ into: "{into}" }}, help: "ctest over a label nothing carries." }}
      ndjson:  {{ task: ndjson, with: {{ into: "{into}" }}, help: "A runner in a foreign format." }}
  test:
    commands:
      unit: {{ task: gate, with: {{ name: "unit" }}, help: "The gate itself." }}
"""

#: Where the product's runner is told to write, and what its gate then declares. One constant, because a
#: test in which the two differ by a typo would be measuring the typo.
WROTE_INTO = "build/test-results"


@pytest.fixture(autouse=True)
def _calls():
    """`test_impls.CALLS` is module level, so the isolation is structural rather than a line every
    arrange has to remember."""
    test_impls.CALLS.clear()
    yield
    test_impls.CALLS.clear()


def _product(monkeypatch, tmp_path, *, compile_rc=0, unit_rc=0, marker="", into=WROTE_INTO):
    """A product rooted at `tmp_path` whose manifest declares the two toolchain commands."""
    (tmp_path / "cppdemo.yaml").write_text(
        textwrap.dedent(MANIFEST.format(compile_rc=compile_rc, unit_rc=unit_rc, marker=marker,
                                        into=into)),
        encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("cppdemo", tmp_path, tmp_path / "cppdemo.yaml"))
    return tmp_path


def _section(*gates, **overrides):
    """An otherwise complete `suites:` section around the given gates, so a refusal can only be about
    the gates - every other key it needs is present and valid."""
    section = {"reports": "build/reports", "gates": list(gates),
               "report": {"parent_suite": "Cpp", "merge": []}}
    section.update(overrides)
    return {"suites": section}


# --- the key loads, on every kind -------------------------------------------------------------------


def test_a_command_gate_may_name_where_its_runner_wrote_its_results():
    """The shape si#133 exists for: a toolchain command produces JUnit XML somewhere in the product's
    tree, and the gate says where, rather than the product writing Python to merge it."""
    # arrange
    data = _section({"name": "unit", "command": "build unit", "results": "clear",
                     "results_from": "build/test-results"})

    # act
    cfg = testrun.declared(data, source="cppdemo.yaml")

    # assert
    assert cfg.gates[0].results_from == "build/test-results"


def test_an_impl_gate_may_name_it_too_because_that_is_the_hand_wiring_being_replaced():
    """javademo's `impl:` gate runs gradle and then calls `merge_results` itself. That call is what this
    key declares, so refusing it on the kind that already does it by hand would leave the one product
    that proved the capability outside the feature."""
    # arrange
    data = _section({"name": "unit", "impl": "orchestrator.gradle:test", "results": "clear",
                     "results_from": "build/junit-xml"})

    # act
    cfg = testrun.declared(data, source="javademo.yaml")

    # assert
    assert cfg.gates[0].results_from == "build/junit-xml"


def test_a_pytest_gate_may_name_it_as_well_and_that_is_a_decision():
    """NOT an oversight, and the reason is `results:`'s own (si#61): a key that means the same thing on
    every kind is not refused on some of them. The mechanism does not vary - a directory is merged and
    the contribution is checked - so a refusal here would be a rule with no defect behind it, and
    `rules.md`'s sorting question answers that the refused manifest would have worked. A pytest gate
    rarely wants it, because the kernel already points `--alluredir` at the shared results dir; wanting
    it rarely is not the same as being unable to say it."""
    # arrange
    data = _section({"name": "unit", "suite": "test/unit/python", "junit": "junit-unit.xml",
                     "results": "clear", "results_from": "build/extra-results"})

    # act
    cfg = testrun.declared(data, source="sample.yaml")

    # assert
    assert cfg.gates[0].results_from == "build/extra-results"


def test_an_empty_results_from_is_refused_rather_than_read_as_not_declared():
    """The rule every other key in this section already gets. `""` is a statement, and reading a typo as
    "the gate declares nothing" is exactly the silence this feature is against - the level would then
    contribute nothing and nothing would say so."""
    # arrange
    data = _section({"name": "unit", "command": "build unit", "results": "clear", "results_from": ""})

    # act
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="cppdemo.yaml")

    # assert
    said = str(refused.value)
    assert "'results_from' must be a non-empty string" in said, said


def test_a_gate_that_names_nothing_carries_the_empty_string():
    """The default has to be falsy rather than absent: every branch that acts on this key asks whether
    the gate declared one, and `None` would make that question a type check."""
    # arrange
    data = _section({"name": "unit", "command": "build unit", "results": "clear"})

    # act
    cfg = testrun.declared(data, source="cppdemo.yaml")

    # assert
    assert cfg.gates[0].results_from == ""


def _cfg(*gates, merge=()):
    return testrun.Suites(reports="build/reports", filtered_results=f"{RESULTS}-filtered",
                          gates=gates, merge=tuple(merge), parent_suite="Cpp")


def _results_dir(tmp_path):
    return tmp_path / "build" / "reports" / RESULTS


def _merged(tmp_path):
    """The file names this run's results dir holds, minus the environment allure writes itself."""
    directory = _results_dir(tmp_path)
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.name != "environment.properties")


# --- the level contributes ---------------------------------------------------------------------------


def test_a_command_gate_whose_runner_wrote_results_contributes_them_and_passes(monkeypatch, tmp_path):
    """The shape the ticket asks for, end to end minus the render: the product's own runner writes JUnit
    XML where it likes, the gate says where that is, and the file is in this run's results."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: green, and the level really is in the archive's inputs
    assert gv.verdict is Verdict.PASSED, gv.line
    assert _merged(tmp_path) == ["ctest-junit.xml"], (
        f"the declared results never reached the run: {_merged(tmp_path)}")


def test_the_merge_line_a_gate_prints_names_the_gate(monkeypatch, tmp_path, capsys):
    """A run of three harvesting gates prints three merge lines before the report step prints a fourth,
    and the report step's wording is anonymous by design (it is quoted on two pages and pinned). So a
    gate says which level the sentence is about, or a reader cannot tell them apart."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert "unit results: merged 1 file" in capsys.readouterr().out


def test_an_impl_gate_contributes_the_same_way_without_the_product_writing_the_merge(monkeypatch,
                                                                                     tmp_path):
    """The hand-wiring being replaced. javademo's `impl:` body runs gradle and then calls
    `merge_results` itself; declaring `results_from:` is that call, said in the manifest."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", impl="test_suites_results_from:writes_results",
                        results="clear", results_from=WROTE_INTO)
    # An impl gate's hook is called with NO arguments, and this body's `into` is a parameter rather than
    # a constant so the same body can also stand in for a runner that writes nothing. So the ref is
    # resolved to a call that pins it, which is what a product's own zero-argument body would hold.
    monkeypatch.setattr(testrun, "resolve_ref",
                        lambda ref, where: (lambda: writes_results(rc=0, into=WROTE_INTO)))

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.PASSED, gv.line
    assert _merged(tmp_path) == ["ctest-junit.xml"]


# --- the red this feature is made of -----------------------------------------------------------------


def test_a_green_runner_that_contributed_no_results_is_not_a_green_gate(monkeypatch, tmp_path):
    """THE DEFECT THIS TICKET IS ABOUT. An Allure report rendered with a level MISSING looks exactly
    like one where the level passed, so a gate that declared where its results land and contributed
    none of them must not report green - whatever its runner's exit code says."""
    # arrange: the command exits 0 and writes nothing at all
    _product(monkeypatch, tmp_path, into="")
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED, f"a level that contributed nothing reported {gv.line}"
    assert gv.rc != 0, "a red record with a green exit is the confusion the verdict module is against"
    assert WROTE_INTO in gv.line, f"the line does not name the directory that was empty: {gv.line}"
    assert "contributed no results" in gv.line, gv.line


def test_a_directory_holding_only_the_previous_runs_results_is_the_same_red(monkeypatch, tmp_path):
    """si#70's cutoff, at gate scope, and it is what stops this feature shipping the defect it fixes.
    Nothing on the kernel's side of the seam ever empties a product's own results directory, so a runner
    that wrote nothing would otherwise contribute the LAST run's results and the gate would go green
    over them."""
    # arrange: yesterday's results are lying in the declared directory, and this run writes none
    _product(monkeypatch, tmp_path, into="")
    stale = tmp_path / WROTE_INTO
    stale.mkdir(parents=True)
    (stale / "ctest-junit.xml").write_text(CTEST_JUNIT, encoding="utf-8")
    os.utime(stale / "ctest-junit.xml", (0, 0))
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: red, the file stayed where it was, and the line says WHY rather than "empty"
    assert gv.verdict is Verdict.FAILED, gv.line
    assert "the previous run's" in gv.line, gv.line
    assert _merged(tmp_path) == [], "the previous run's results were presented as this run's"


# --- a runner that was already red keeps its own sentence --------------------------------------------


def test_a_red_runner_keeps_its_own_rc_and_its_own_sentence_and_its_results_still_travel(monkeypatch,
                                                                                        tmp_path):
    """The rc is the primary fact when there is one. A failing `ctest` writes results for the cases that
    ran, and those belong in the archive; what must NOT happen is the record replacing "'build unit'
    returned this rc" with a sentence about a directory."""
    # arrange: the command is red AND wrote its results
    _product(monkeypatch, tmp_path, unit_rc=8)
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED and gv.rc == 8
    assert "'build unit' returned this rc" in gv.line, gv.line
    assert _merged(tmp_path) == ["ctest-junit.xml"], "a red level's own results did not reach the report"


def test_a_red_runner_that_wrote_nothing_still_reports_the_rc_it_returned(monkeypatch, tmp_path):
    """Both facts are true and only one of them is the cause. A reader who is told "the level
    contributed nothing" about a command that exited 8 goes looking for a misdeclared path."""
    # arrange
    _product(monkeypatch, tmp_path, unit_rc=8, into="")
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.rc == 8 and "'build unit' returned this rc" in gv.line, gv.line


# --- nothing is harvested for a gate that never ran its body -----------------------------------------


def test_a_failed_preamble_merges_nothing_because_the_body_never_ran(monkeypatch, tmp_path):
    """si#106's rule, and harvesting would undo it: the build failed, the test command never ran, and
    whatever is lying in its results directory is by definition not this run's."""
    # arrange: the compile is red, and the last run's results are still in the declared directory
    _product(monkeypatch, tmp_path, compile_rc=2)
    (tmp_path / WROTE_INTO).mkdir(parents=True)
    (tmp_path / WROTE_INTO / "ctest-junit.xml").write_text(CTEST_JUNIT, encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build unit", preamble="build compile", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.SETUP_FAILED, gv.line
    assert _merged(tmp_path) == [], "a gate whose body never ran contributed results anyway"


def test_a_failed_precondition_merges_nothing_and_leaves_the_previous_archive(monkeypatch, tmp_path):
    """NOT_RUN touches nothing at all - that is the whole of the outcome - and a harvest would be the
    one thing it touched."""
    # arrange
    _product(monkeypatch, tmp_path, compile_rc=1)
    _results_dir(tmp_path).mkdir(parents=True)
    (_results_dir(tmp_path) / "from-the-last-run.json").write_text("{}", encoding="utf-8")
    (tmp_path / WROTE_INTO).mkdir(parents=True)
    (tmp_path / WROTE_INTO / "ctest-junit.xml").write_text(CTEST_JUNIT, encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build unit", precondition="build compile",
                        results="clear", results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.NOT_RUN
    assert _merged(tmp_path) == ["from-the-last-run.json"]


def test_a_runner_that_said_its_own_setup_broke_is_not_judged_on_its_results(monkeypatch, tmp_path):
    """The marker is the runner's claim about a run that did not happen, and it wins over the rc (#59).
    A level that then also reported "contributed nothing" would be answering a question nobody asked."""
    # arrange: the command exits 0, writes no results, and drops the marker
    _product(monkeypatch, tmp_path, marker="the container never started")
    gate = testrun.Gate(name="unit", command="build marked", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.SETUP_FAILED and gv.stage == "the container never started", gv.line
    assert _merged(tmp_path) == []


# --- a gate that says nothing is untouched ------------------------------------------------------------


def test_a_gate_that_declares_no_results_from_behaves_exactly_as_it_did(monkeypatch, tmp_path):
    """The feature acts on the DECLARATION and on nothing else. A runner that writes results into a
    directory the gate never named contributes nothing, and that is not an error: it is a product that
    has not asked for this yet."""
    # arrange: the runner writes, the gate says nothing
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build unit", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.PASSED
    assert _merged(tmp_path) == []


# --- the pytest branch harvests too -------------------------------------------------------------------


def test_a_pytest_gate_harvests_what_its_own_run_wrote_elsewhere(monkeypatch, tmp_path):
    """The key is legal on every kind, so the branch that runs pytest has to honour it as well. The
    subprocess seam is stubbed here and driven for real in the e2e file: what is under test is that the
    harvest is reached on this branch, not that pytest works."""
    # arrange: a pytest gate whose child writes a result file into the declared directory
    _product(monkeypatch, tmp_path)
    (tmp_path / "test" / "unit").mkdir(parents=True)

    def fake_pytest(argv, **kwargs):
        writes_results(rc=0, into=WROTE_INTO)
        return SimpleNamespace(rc=0)

    monkeypatch.setattr(testrun, "keep_awake", contextlib.nullcontext)
    monkeypatch.setattr(testrun.pyvenv, "venv_python_pip",
                        lambda d: (os.path.join(d, ".venv/bin/python"), "pip"))
    monkeypatch.setattr(testrun, "run", fake_pytest)
    gate = testrun.Gate(name="unit", suite="test/unit", junit="junit-unit.xml", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.PASSED, gv.line
    assert _merged(tmp_path) == ["ctest-junit.xml"]


def test_a_pytest_gate_that_contributed_nothing_from_the_directory_it_named_is_red(monkeypatch,
                                                                                   tmp_path):
    """Same branch, the other half. A green pytest run does not excuse a declared directory that is
    empty; the level said where its results land and none arrived."""
    # arrange
    _product(monkeypatch, tmp_path)
    (tmp_path / "test" / "unit").mkdir(parents=True)
    monkeypatch.setattr(testrun, "keep_awake", contextlib.nullcontext)
    monkeypatch.setattr(testrun.pyvenv, "venv_python_pip",
                        lambda d: (os.path.join(d, ".venv/bin/python"), "pip"))
    monkeypatch.setattr(testrun, "run", lambda argv, **kwargs: SimpleNamespace(rc=0))
    gate = testrun.Gate(name="unit", suite="test/unit", junit="junit-unit.xml", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED and "contributed no results" in gv.line, gv.line


# --- a harvesting gate owns the dir it filled ---------------------------------------------------------


def test_an_appending_gate_that_contributed_results_owns_them(monkeypatch, tmp_path):
    """si#69's property, which this key changes the answer to. `owned_results` says whether the gate
    took the run's results dir - cleared it, filled it, or both - and it decides whether the run's
    verdict may be written into the archive standing there. Its docstring's reasoning was that an
    APPENDING gate whose runner is the product's own 'takes nothing, writes nothing and leaves the dir
    exactly as it found it'. A gate that names `results_from:` writes into it, so a run made only of
    such gates would otherwise fill an archive with this run's results and leave the PREVIOUS run's
    verdict standing in it."""
    # arrange: appending, not clearing, and its runner writes
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build unit", results="append",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.owned_results, "a gate that filled the results dir reported owning nothing"
    assert _merged(tmp_path) == ["ctest-junit.xml"]


def test_an_appending_gate_that_contributed_nothing_owns_nothing(monkeypatch, tmp_path):
    """The other side of the same fact, and it is not symmetry for its own sake: a gate that neither
    cleared nor filled the directory has no claim on the archive standing in it, and saying otherwise
    would let a run that wrote nothing restate its verdict over a run that did."""
    # arrange
    _product(monkeypatch, tmp_path, into="")
    gate = testrun.Gate(name="unit", command="build unit", results="append",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED and not gv.owned_results


def test_an_environment_file_on_its_own_is_not_a_contribution(monkeypatch, tmp_path):
    """The hole a review found in the check, and it is in exactly the class this ticket exists to close.

    `Merge.empty` counts every entry a merge handled, `environment.properties` included, which is the
    right question for the report step: did the merge do anything at all. A GATE asks something
    narrower - did this LEVEL produce evidence - and an environment file is not evidence. A runner that
    writes one (an allure-native one does) and then falls over before writing a single result would
    otherwise answer "not empty" and report green with no case in the archive.
    """
    # arrange: the runner writes the environment file and nothing else
    _product(monkeypatch, tmp_path, into="")
    source = tmp_path / WROTE_INTO
    source.mkdir(parents=True)
    (source / "environment.properties").write_text("Runner=ctest\n", encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED, f"an environment file counted as a level's results: {gv.line}"
    assert "contributed no results" in gv.line, gv.line


def test_a_results_file_carrying_no_test_case_is_not_a_contribution(monkeypatch, tmp_path):
    """THE TRAP ONE STEP LATER, and it is reachable rather than theoretical: `ctest -L <a label nothing
    carries>` exits 0, prints `No tests were found!!!` and - with `--output-junit` - writes a suite
    element with `tests="0"`.

    A file arrives, so a check that counts FILES is satisfied and the level reports green with not one
    case in the archive. That is the same green-over-nothing the empty directory produces, one layer up,
    and it has to be closed the same way or the key only catches the easier half.
    """
    # arrange: the runner exits 0 and writes a results file with nothing in it
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build hollow", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED, f"a file with no test case in it counted as results: {gv.line}"
    assert "contributed no results" in gv.line, gv.line
    assert "holds a test case" in gv.line, f"the line does not say what was wrong with the file: {gv.line}"


def test_a_format_the_kernel_cannot_count_is_trusted_rather_than_refused(monkeypatch, tmp_path):
    """The rule that keeps the check above from becoming a table of formats with a failure mode.

    The kernel counts cases in the shapes it demonstrably meets - the JUnit family, xunit's own XML and
    TRX - and a file it cannot read is a CONTRIBUTION, not an emptiness. Allure reads more formats than
    this kernel knows about, and calling a level empty because the kernel could not parse its evidence
    would be a false red invented by the checker, which is the same defect pointing the other way.
    """
    # arrange: a runner whose results are in no format the kernel knows. The file is written BY THE RUN
    # rather than laid beside it, because a pre-placed one is a second boundary away from being read as
    # the previous run's - see `writes_unreadable_results` (si#86)
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build ndjson", results="clear",
                        results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.PASSED, f"a format the kernel cannot read was called empty: {gv.line}"


# --- a gate that names the destination (si#138) -------------------------------------------------------


def test_a_gate_whose_results_from_is_the_destination_is_red_rather_than_a_traceback(monkeypatch,
                                                                                     tmp_path):
    """si#138 through si#133's own key, which is the likelier of the two ways in because the key is new.

    `results_from:` names the directory THIS GATE'S RUNNER wrote into, and a product that reads it as
    "the directory the results are in" points it at the kernel's results dir. On origin/main the merge
    then copied a file onto itself and the gate ended in `shutil.SameFileError` out of `shutil.copy`.

    Red rather than green, and that is the honest answer rather than a convenience: nothing travelled, so
    this level contributed no evidence of its own, and the line says which directory to name instead.
    """
    # arrange: the runner writes straight into the run's results dir, and the gate declares that dir
    destination = f"build/reports/{RESULTS}"
    _product(monkeypatch, tmp_path, into=destination)
    gate = testrun.Gate(name="unit", command="build unit", results="clear",
                        results_from=destination)

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: a verdict with a sentence, not an exception
    assert gv.verdict is Verdict.FAILED, gv.line
    assert "is the destination itself and was not merged" in gv.line, gv.line
    assert destination in gv.line, gv.line
    assert _merged(tmp_path) == ["ctest-junit.xml"], "the runner's own file was disturbed"


def test_a_gate_cannot_go_green_over_results_another_gate_left_in_the_destination(monkeypatch, tmp_path):
    """THE HALF THE TICKET DOES NOT MENTION, and the worse one, because it never crashed.

    A self-source holding `*-result.json` reached the tag-and-rewrite branch instead of `shutil.copy`.
    Measured on origin/main (2026-09-11): a gate whose runner wrote nothing at all reported
    `merged 3 files from 1 of 1 declared source dirs: 3 tagged parentSuite=Unit` and PASSED, over three
    results an earlier gate had put in the shared dir. That is exactly the green-over-nothing si#133
    exists to prevent, reached through si#133's own key.
    """
    # arrange: an earlier gate's results are in the destination, THIS run's (so si#70's cutoff cannot be
    # what saves the gate), and this gate's runner writes nothing
    _product(monkeypatch, tmp_path, into="")
    results = _results_dir(tmp_path)
    results.mkdir(parents=True)
    for name in ("a", "b", "c"):
        (results / f"{name}-result.json").write_text('{"name": "t", "labels": []}', encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build unit", results="append",
                        results_from=f"build/reports/{RESULTS}")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: red, and the other gate's evidence is still there and still untagged
    assert gv.verdict is Verdict.FAILED, f"a level went green over another gate's results: {gv.line}"
    assert "contributed no results" in gv.line, gv.line
    assert (results / "a-result.json").read_text(encoding="utf-8") == '{"name": "t", "labels": []}', \
        "the merge rewrote a file the destination already held"
