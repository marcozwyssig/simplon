"""si#106: a gate whose runner is a COMMAND in the product's own tree, and the wrong green it removes.

THE CASE, measured on a containerised toolchain rather than argued. `simplon.tasks.testrun.Gate` took a
pytest root (`suite:`) or a product callable (`impl:`). A `toolchain:run` command is neither - it is a
COMMAND in the tree - so a product whose test runner is `ctest`, `dotnet test` or `gradle test` got an
exit code and no verdict at all: no `setup-failed`, no `SIMPLON_SETUP_FAILED` marker, no allure results,
no archive.

AND ONE STEP WORSE THAN THAT, which is what the first test below pins. On the C++ product:

    $ ./cppdemo.sh build compile     # a deliberate type error
    error: cannot initialize a variable of type 'int' with an lvalue of type 'const char *'
    rc 2
    $ ./cppdemo.sh build unit        # ctest, over the binaries the failed compile did not replace
    100% tests passed, 0 tests failed out of 3
    rc 0

Two commands, no gate between them, and the second one is a POSITIVELY WRONG GREEN: three passing tests
reported for a product that does not compile. Nothing in the kernel could see the pair, because neither
half was a gate.

WHAT THE FIX IS. A gate may name a command (`command: "build unit"`), and its setup may name one too
(`preamble: "build compile"`). The kernel runs the setup first, and a non-zero setup rc is `SETUP_FAILED`
with the body NEVER RUN - the same rule a pytest gate's preamble has always had, which is exactly the
sentence this case needs: the suite did not run, so the run has learned nothing about the product.

Every command here resolves through the product's real manifest, deliberately: the gate runs a command
the way the CLI runs it - the impl the `task:` names, with the command's own `with:` pinned - so a test
that stubbed the resolution would verify the stub and not the seam.

AAA throughout.
"""
import textwrap

import pytest
import typer

from simplon import context, test_impls
from simplon.context import ProductContext
from simplon.tasks import testrun
from simplon.verdict import Verdict

RESULTS = testrun.RESULTS

#: A C++ product's build commands, as the manifest declares them: two commands over one body, each
#: pinning the rc the measurement above observed. `pinned_rc` records its call, so a test can assert
#: that a command did NOT run - which is half of what the wrong green is about.
MANIFEST = """
product: cppdemo
tasks:
  toolchain: {{ impl: "simplon.test_impls:pinned_rc", help: "Run a pinned toolchain image." }}
  gate:      {{ impl: "simplon.tasks.testrun:gate", help: "Run a declared level.", passthrough_args: true }}
  strict:    {{ impl: "simplon.test_impls:needs_a_value", help: "Needs a value nothing pins." }}
  framed:    {{ impl: "test_suites_command_gate:framed_body", help: "A body with a typer default." }}
groups:
  build:
    commands:
      compile: {{ task: toolchain, with: {{ rc: {compile_rc}, tag: "compile" }}, help: "Compile." }}
      unit:    {{ task: toolchain, with: {{ rc: {unit_rc}, tag: "unit", marker: "{marker}" }}, help: "ctest." }}
      loose:   {{ task: strict, help: "Nothing pinned at all." }}
      framed:  {{ task: framed, help: "A body whose default is a typer declaration." }}
      all:     {{ depends_on: ["compile"], help: "Plans other commands, runs none of its own." }}
  test:
    commands:
      unit: {{ task: gate, with: {{ name: "unit" }}, help: "The gate itself." }}
"""


def _product(monkeypatch, tmp_path, *, compile_rc=0, unit_rc=0, marker=""):
    """A product rooted at `tmp_path` whose manifest declares the two toolchain commands."""
    (tmp_path / "cppdemo.yaml").write_text(
        textwrap.dedent(MANIFEST.format(compile_rc=compile_rc, unit_rc=unit_rc, marker=marker)),
        encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("cppdemo", tmp_path, tmp_path / "cppdemo.yaml"))
    test_impls.CALLS.clear()


def _section(*gates, **overrides):
    """An otherwise complete `suites:` section around the given gates, so a refusal can only be about
    the gates - every other key it needs is present and valid."""
    section = {"reports": "build/reports", "gates": list(gates),
               "report": {"parent_suite": "Cpp", "merge": ["build/test-results"]}}
    section.update(overrides)
    return {"suites": section}


def _results_dir(tmp_path):
    return tmp_path / "build" / "reports" / RESULTS


def framed_body(deep: bool = typer.Option(False, "--deep", help="A typer DECLARATION, not a value.")):
    """A body in the shape two consumer products still write: its default is a `typer.Option(...)`.

    Typer resolves that into the value behind it; a direct call does not. It lives here rather than in
    `simplon.test_impls`, whose bodies are deliberately framework-free.
    """
    test_impls.CALLS.append(("framed_body", deep))
    return 0


def _cfg(*gates, merge=()):
    return testrun.Suites(reports="build/reports", filtered_results=f"{RESULTS}-filtered",
                          gates=gates, merge=tuple(merge), parent_suite="Cpp")


def _ran():
    """The tags of the commands that actually ran, in order."""
    return [call[1] for call in test_impls.CALLS if call[0] == "pinned_rc"]


# --- the wrong green -----------------------------------------------------------------------------


def test_a_gate_whose_build_command_failed_never_reports_the_test_command_as_passed(monkeypatch,
                                                                                    tmp_path):
    """si#106's measurement, as a gate: the compile exits 2 and the test command must not run at all,
    let alone report green off the binaries the failed compile left standing."""
    # arrange: the compile fails, the test command would pass
    _product(monkeypatch, tmp_path, compile_rc=2, unit_rc=0)
    gate = testrun.Gate(name="unit", command="build unit", preamble="build compile", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: the run learned nothing about the product, and says so
    assert gv.verdict is Verdict.SETUP_FAILED, f"a failed build reported {gv.verdict}: {gv.line}"
    assert gv.rc == 2, f"the gate lost the build's own rc: {gv.rc}"
    assert not gv.ok
    assert _ran() == ["compile"], (
        f"the test command ran over the binaries a failed compile left behind: {_ran()}")


def test_the_setup_that_succeeded_lets_the_body_run_and_the_gate_reports_it(monkeypatch, tmp_path):
    """The other half of the pair: a compile that works is not a verdict of its own, it is the setup the
    test command needed, and what the gate reports is what the test command found."""
    # arrange: both commands green
    _product(monkeypatch, tmp_path, compile_rc=0, unit_rc=0)
    gate = testrun.Gate(name="unit", command="build unit", preamble="build compile", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: both ran, in that order, and the verdict is the body's
    assert _ran() == ["compile", "unit"], f"the gate ran {_ran()}"
    assert gv.verdict is Verdict.PASSED and gv.rc == 0 and gv.ok


def test_a_red_command_gate_names_the_command_and_claims_nothing_about_a_suite(monkeypatch, tmp_path):
    """#65 on the new kind. The kernel ran a command, not a suite, so the record says which command
    returned the rc rather than borrowing 'the suite ran and reported failures' - a sentence about
    something nobody here observed."""
    # arrange: the test command itself is red
    _product(monkeypatch, tmp_path, unit_rc=1)
    gate = testrun.Gate(name="unit", command="build unit", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED and gv.rc == 1
    assert "'build unit' returned this rc" in gv.line, gv.line
    assert "the suite ran and reported failures" not in gv.line, gv.line


def test_the_gate_runs_the_command_with_the_with_block_the_manifest_pinned(monkeypatch, tmp_path):
    """THE SEAM, stated as a measurement: the gate runs the command the way the CLI runs it - the body
    its `task:` names, with its own `with:` pinned - so the verdict is about the command a person types
    and the two cannot drift into meaning different things."""
    # arrange: the manifest pins a different rc and tag per command over ONE body
    _product(monkeypatch, tmp_path, compile_rc=0, unit_rc=3)
    gate = testrun.Gate(name="unit", command="build unit", preamble="build compile", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: each call carries the values ITS command pinned, not the other's
    assert test_impls.CALLS == [("pinned_rc", "compile", 0), ("pinned_rc", "unit", 3)]
    assert gv.rc == 3


def test_a_command_gate_reaches_the_setup_marker_like_every_other_gate(monkeypatch, tmp_path):
    """#59 carried over. A runner that knows its own preparation fell over says so through the marker
    file, and its claim wins over the rc it returned - including over a green one."""
    # arrange: the command exits 0 and drops the marker anyway
    _product(monkeypatch, tmp_path, unit_rc=0, marker="the container never started")
    gate = testrun.Gate(name="unit", command="build unit", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.SETUP_FAILED, f"the marker was ignored: {gv.line}"
    assert gv.stage == "the container never started"
    assert gv.rc != 0, "a red record with a green exit is the confusion the marker exists against"


def test_a_command_precondition_stops_the_gate_and_clears_nothing(monkeypatch, tmp_path):
    """A command gate's precondition is a command too - a product with no Python in it must not have to
    write a Python body to reach a hook. A failed one is NOT_RUN: nothing was prepared or cleared, and
    the previous archive stands."""
    # arrange: the health check is red, and there is a previous run's archive to protect
    _product(monkeypatch, tmp_path, compile_rc=1)
    _results_dir(tmp_path).mkdir(parents=True)
    (_results_dir(tmp_path) / "from-the-last-run.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build unit", precondition="build compile",
                        results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert gv.verdict is Verdict.NOT_RUN and gv.rc == 1
    assert _ran() == ["compile"], f"the body ran after a red precondition: {_ran()}"
    assert (_results_dir(tmp_path) / "from-the-last-run.json").exists(), (
        "a gate that never started cleared the last real run's archive")


def test_a_command_gate_may_own_the_results_dir_and_still_writes_nothing_into_it(monkeypatch, tmp_path):
    """si#61's property on the third kind. `results: clear` says whose run the directory is, not what
    the kernel learned - and the kernel learns exactly one number from a command."""
    # arrange
    _product(monkeypatch, tmp_path)
    _results_dir(tmp_path).mkdir(parents=True)
    (_results_dir(tmp_path) / "from-the-last-run.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build unit", results="clear")

    # act
    gv = testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: emptied, owned, and left empty
    assert gv.owned_results
    assert list(_results_dir(tmp_path).iterdir()) == []


# --- what the kernel refuses to run as a gate ------------------------------------------------------


def test_a_command_the_tree_does_not_hold_is_refused_by_name(monkeypatch, tmp_path):
    """A manifest typo, and the message has to be the one a reader can act on: which command was named
    and which ones exist."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build ctest", results="clear")

    # act
    with pytest.raises(ValueError) as refused:
        testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    said = str(refused.value)
    assert "'build ctest' is not a command in this product's tree" in said, said
    assert "build unit" in said, f"the refusal lists no commands that DO exist: {said}"


def test_a_gate_that_cannot_start_does_not_clear_the_last_runs_archive(monkeypatch, tmp_path):
    """The reason the resolution happens before the clear. A mistyped command used to be discovered
    after the directory had been emptied, so a typo cost the last real run's report."""
    # arrange
    _product(monkeypatch, tmp_path)
    _results_dir(tmp_path).mkdir(parents=True)
    (_results_dir(tmp_path) / "from-the-last-run.json").write_text("{}", encoding="utf-8")
    gate = testrun.Gate(name="unit", command="build ctest", results="clear")

    # act
    with pytest.raises(ValueError):
        testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert (_results_dir(tmp_path) / "from-the-last-run.json").exists()


def test_an_aggregate_cannot_back_a_gate(monkeypatch, tmp_path):
    """An aggregate plans other commands and runs no body of its own, so there is no single rc for a
    gate to report. Refused with the way out, not with a TypeError three frames down."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build all", results="clear")

    # act
    with pytest.raises(ValueError) as refused:
        testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert "plans other commands and runs no body of its own" in str(refused.value)


def test_the_gate_command_itself_cannot_back_a_gate(monkeypatch, tmp_path):
    """The loop, closed by the rule that was there for another reason: `test:gate`'s body takes a CLI
    context, and a gate has none to give it. So a gate cannot name the command it is invoked as."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="test unit", results="clear")

    # act
    with pytest.raises(ValueError) as refused:
        testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert
    assert "takes a CLI context" in str(refused.value)


def test_a_parameter_the_command_does_not_pin_is_refused_pointing_at_with(monkeypatch, tmp_path):
    """A gate has no command line, so every parameter the body needs has to be pinned in the command's
    own `with:`. Refused by NAME, so the manifest edit is obvious."""
    # arrange: a body whose parameter is required, instantiated by a command that pins nothing
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build loose", results="clear")

    # act
    with pytest.raises(ValueError) as refused:
        testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: it names the parameter and where to put it
    said = str(refused.value)
    assert "needs value" in said, said
    assert "`with:`" in said, f"the refusal does not name the way out: {said}"


# --- what the section may say -----------------------------------------------------------------------


def test_a_command_only_taxonomy_loads_and_its_gate_owns_the_results_dir():
    """The section si#106 asks for: no pytest, no product-owned Python, two commands the product already
    has."""
    # arrange
    data = _section({"name": "unit", "command": "build unit", "preamble": "build compile",
                     "results": "clear"})

    # act
    cfg = testrun.declared(data, source="cppdemo.yaml")

    # assert
    assert cfg.gates[0].command == "build unit" and not cfg.gates[0].suite and not cfg.gates[0].impl
    assert cfg.gates[0].preamble == "build compile"
    assert cfg.gates[0].clears


def test_declaring_two_kinds_is_refused_and_the_refusal_names_all_three():
    """The exactly-one-kind lock, widened rather than duplicated - and the message has to offer the kind
    a reader has not met yet, or the third kind is one nobody finds."""
    # arrange
    data = _section({"name": "unit", "command": "build unit", "impl": "orchestrator.jvm:test",
                     "results": "clear"})

    # act
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="cppdemo.yaml")

    # assert
    said = str(refused.value)
    assert "declare exactly one of 'suite'" in said, said
    assert "'command'" in said, f"the refusal does not offer the third kind: {said}"


@pytest.mark.parametrize("key,value", [("junit", "unit.xml"), ("args", True)])
def test_a_command_gate_is_opaque_in_the_same_two_ways_an_impl_gate_is(key, value):
    """The kernel runs a command for its rc and writes no junit of its own, so those two keys are as
    inert here as on an impl gate and are refused for the same reason."""
    # arrange
    data = _section({"name": "unit", "command": "build unit", "results": "clear", key: value})

    # act
    with pytest.raises(ValueError) as refused:
        testrun.declared(data, source="cppdemo.yaml")

    # assert
    assert f"a 'command' gate cannot declare '{key}'" in str(refused.value)


def test_the_preamble_is_the_one_key_that_parts_the_two_opaque_kinds():
    """It is refused on an impl gate, where it does nothing, and it MEANS something on a command gate -
    which is the whole of si#106."""
    # arrange
    impl_gate = _section({"name": "unit", "impl": "orchestrator.jvm:test", "results": "clear",
                          "preamble": "build compile"})
    command_gate = _section({"name": "unit", "command": "build unit", "results": "clear",
                             "preamble": "build compile"})

    # act
    with pytest.raises(ValueError) as refused:
        testrun.declared(impl_gate, source="cppdemo.yaml")
    loaded = testrun.declared(command_gate, source="cppdemo.yaml")

    # assert
    assert "an 'impl' gate cannot declare 'preamble'" in str(refused.value)
    assert loaded.gates[0].preamble == "build compile"


def test_a_typer_declaration_standing_in_for_a_default_is_refused_rather_than_passed(monkeypatch,
                                                                                     tmp_path):
    """The half of "minus the command line" that would otherwise be silent. Typer turns a
    `typer.Option(...)` default into the value behind it; a direct call hands the body the OptionInfo
    OBJECT. A wrong value passed quietly is worse than a refusal, so the parameter counts as unpinned."""
    # arrange
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build framed", results="clear")

    # act
    with pytest.raises(ValueError) as refused:
        testrun.assess_gate(gate, _cfg(), [], filtered=False)

    # assert: named, and the body never saw the sentinel
    assert "needs deep" in str(refused.value), str(refused.value)
    assert not [call for call in test_impls.CALLS if call[0] == "framed_body"]
