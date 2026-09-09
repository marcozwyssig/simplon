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
import textwrap

import pytest

from simplon import context, test_impls
from simplon.context import ProductContext
from simplon.tasks import testrun

RESULTS = testrun.RESULTS

#: The same C++ product `test_suites_command_gate.py` uses, trimmed to what this file needs: one body,
#: two commands over it, and a gate command. Its manifest is real and is read off the disk, because a
#: gate resolves a command through the product's own tree and a stubbed resolution would verify the stub.
MANIFEST = """
product: cppdemo
tasks:
  toolchain: {{ impl: "simplon.test_impls:pinned_rc", help: "Run a pinned toolchain image." }}
  gate:      {{ impl: "simplon.tasks.testrun:gate", help: "Run a declared level.", passthrough_args: true }}
groups:
  build:
    commands:
      compile: {{ task: toolchain, with: {{ rc: {compile_rc}, tag: "compile" }}, help: "Compile." }}
      unit:    {{ task: toolchain, with: {{ rc: {unit_rc}, tag: "unit", marker: "{marker}" }}, help: "ctest." }}
  test:
    commands:
      unit: {{ task: gate, with: {{ name: "unit" }}, help: "The gate itself." }}
"""


@pytest.fixture(autouse=True)
def _calls():
    """`test_impls.CALLS` is module level, so the isolation is structural rather than a line every
    arrange has to remember."""
    test_impls.CALLS.clear()
    yield
    test_impls.CALLS.clear()


def _product(monkeypatch, tmp_path, *, compile_rc=0, unit_rc=0, marker=""):
    """A product rooted at `tmp_path` whose manifest declares the two toolchain commands."""
    (tmp_path / "cppdemo.yaml").write_text(
        textwrap.dedent(MANIFEST.format(compile_rc=compile_rc, unit_rc=unit_rc, marker=marker)),
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
