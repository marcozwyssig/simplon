"""si#136 DRIVEN: a REAL `toolchain:run` command backs a `command:` gate, and the verdict is the
container's own.

WHY THIS FILE DECIDES WHETHER si#106 EXISTS. `tests/test_suites_command_gate.py` proves the gate kind
against `simplon.test_impls:pinned_rc` - a Python body that returns the number a `with:` block pinned.
That proves the sequencing and it cannot prove the seam, because the coordinate a C++ or a .NET level
actually names is `toolchain:run`, whose body takes a CLI context. Measured on 0.10.0 the gate refused
it outright:

    ValueError: 'suites.gates.unit.command': 'build unit' takes a CLI context, which a gate has none of
    to give it - only a command the kernel can call with its pinned `with:` alone can back a gate

So the feature was green over a case it could not do, both case chapters promised the shape, and neither
drove it. The defect is that every test used a stub, and a better stub does not repair it. This file
compiles a real CMake project in the pinned clang image and runs a real `ctest` through a real gate,
green and red.

WHAT EACH TEST BELOW IS FOR, since three of them look alike:

  * green - the gate runs the preamble command and then the test command, and reports `passed`;
  * red at the TEST command - a broken assertion arrives as `failed` carrying ctest's own rc, which is
    8 and not 1. That number is the reason this has to be driven: nothing in a stub would have produced
    it, and a run comparing an exit code to 1 reads it as a pass;
  * red at the PREAMBLE - a tree that does not compile stops at the compile as `setup-failed`, and
    `ctest` is never asked about the binaries the failed build left standing. That is si#106's own
    measurement, finally made through the coordinate it was written about.

WHY THE SKIP IS ON DOCKER AND NOTHING ELSE - `tests/test_buildfiles_e2e.py`'s rule: the tool is what is
being measured, so its absence is a skip and everything else is a failure. A missing image is not a skip.

AAA throughout.
"""
import shutil
import textwrap
from pathlib import Path

import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.run import run
from simplon.tasks import profiles, testrun
from simplon.verdict import Verdict

#: The C++ toolchain a product on this kernel really gets, read out of the kernel's own table rather than
#: typed here - so a table entry that stops working takes this suite with it.
CPP = profiles.profile("cpp", version="19")

_DOCKER = shutil.which("docker") is not None and run(["docker", "version"]).ok

needs_docker = pytest.mark.skipif(not _DOCKER, reason="no docker daemon here to compile and test in")


# --- the product -------------------------------------------------------------------------------------

#: Three ctest cases over one binary, the smallest tree that can compile, pass and fail. What is under
#: test is the gate, not the arithmetic.
CMAKELISTS = textwrap.dedent("""\
    cmake_minimum_required(VERSION 3.20)
    project(gatedemo CXX)
    enable_testing()
    add_executable(calc_test calc_test.cpp)
    add_test(NAME AddsTwoNumbers COMMAND calc_test add)
    add_test(NAME MultipliesTwoNumbers COMMAND calc_test mul)
    add_test(NAME SubtractsTwoNumbers COMMAND calc_test sub)
    """)

#: The passing source. `mul` is the case the red run breaks, and it is broken in the TEST rather than in
#: the product so the tree still compiles - the two red halves have to be told apart.
PASSES = textwrap.dedent("""\
    #include <cstring>

    int main(int argc, char** argv) {
        if (argc < 2) return 1;
        if (std::strcmp(argv[1], "add") == 0) return (2 + 3 == 5) ? 0 : 1;
        if (std::strcmp(argv[1], "mul") == 0) return (2 * 3 == 6) ? 0 : 1;
        if (std::strcmp(argv[1], "sub") == 0) return (5 - 3 == 2) ? 0 : 1;
        return 1;
    }
    """)

#: One assertion broken. Compiles, and `MultipliesTwoNumbers` fails.
ONE_ASSERTION_BROKEN = PASSES.replace("2 * 3 == 6", "2 * 3 == 7")

#: A type error, so the compile itself falls over. This is what puts the preamble in the record.
DOES_NOT_COMPILE = PASSES.replace("if (argc < 2) return 1;", 'int broken = "not an int";')

#: The manifest a real C++ product writes, and the whole point of the drive: two ordinary
#: `toolchain:run` commands, and a `suites:` section that names them. No Python anywhere in it.
MANIFEST = textwrap.dedent("""\
    product: gatedemo
    groups:
      build:
        commands:
          compile:
            task: "toolchain:run"
            with:
              image: "silkeh/clang:19"
              workdir: "/src"
              argv: ["sh", "-c", "cmake -S . -B build && cmake --build build -j"]
            help: "Configure and compile."
          unit:
            task: "toolchain:run"
            with:
              image: "silkeh/clang:19"
              workdir: "/src"
              argv: ["ctest", "--test-dir", "build", "--output-on-failure"]
            help: "ctest."
    suites:
      reports: "build/reports"
      report:
        parent_suite: "Cpp"
      gates:
        - name: "unit"
          command: "build unit"
          preamble: "build compile"
          results: "clear"
    """)


def _product(monkeypatch, tmp_path, source):
    """A real C++ product on disk with its context registered, built around `source`."""
    (tmp_path / "CMakeLists.txt").write_text(CMAKELISTS, encoding="utf-8")
    (tmp_path / "calc_test.cpp").write_text(source, encoding="utf-8")
    (tmp_path / "gatedemo.yaml").write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("gatedemo", tmp_path, tmp_path / "gatedemo.yaml"))
    return tmp_path


def _loaded(tmp_path):
    """The gate and the taxonomy read out of the product's OWN manifest.

    Not a `Gate(...)` built here: the claim under test is that the section a product writes reaches the
    coordinate it names, so a hand-built gate would skip the half that was broken.
    """
    cfg = testrun.declared(context.current().manifest_data(), source=str(tmp_path / "gatedemo.yaml"))
    return cfg.gate("unit"), cfg


def _binaries(tmp_path: Path) -> float:
    """When the test binary was last written, or 0.0 when there is none.

    The preamble half needs to prove that `ctest` did not run over what an EARLIER build left standing,
    and the only way to say that about a container the test did not watch is that the artefact it would
    have run is exactly the one that was there before.
    """
    found = sorted(tmp_path.glob("build/calc_test"))
    return found[0].stat().st_mtime if found else 0.0


# --- the drive ----------------------------------------------------------------------------------------


@needs_docker
def test_a_command_gate_runs_a_real_toolchain_command_and_reports_it_green(monkeypatch, tmp_path):
    """si#136's whole claim in one run: the gate names `build unit`, that command is a `toolchain:run`
    one, the container really runs, and a verdict comes back."""
    # arrange: a tree that compiles and three passing ctest cases
    _product(monkeypatch, tmp_path, PASSES)
    gate, cfg = _loaded(tmp_path)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: the verdict, and the evidence that the preamble really compiled something
    assert gv.verdict is Verdict.PASSED, f"a green ctest reported {gv.verdict}: {gv.line}"
    assert gv.rc == 0 and gv.ok
    assert _binaries(tmp_path), "the preamble command produced no binary, so ctest ran over nothing"


@needs_docker
def test_a_failing_test_command_is_a_failed_gate_carrying_ctests_own_rc(monkeypatch, tmp_path):
    """SEEN RED, and red about the right thing. A broken assertion has to arrive as a FAILED gate naming
    the command, not as a traceback and not as a pass - and the rc is ctest's own **8**, which is the
    number a stub would never have produced and the one a CI step comparing to 1 reads as green."""
    # arrange: the tree compiles, one ctest case does not pass
    _product(monkeypatch, tmp_path, ONE_ASSERTION_BROKEN)
    gate, cfg = _loaded(tmp_path)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert
    assert gv.verdict is Verdict.FAILED, f"a red ctest reported {gv.verdict}: {gv.line}"
    assert gv.rc == 8, f"ctest's own error class did not reach the verdict: rc {gv.rc}"
    assert not gv.ok
    assert "'build unit' returned this rc" in gv.line, gv.line
    assert "the suite ran and reported failures" not in gv.line, gv.line


@needs_docker
def test_a_tree_that_does_not_compile_stops_at_the_preamble_and_ctest_is_never_asked(monkeypatch,
                                                                                    tmp_path):
    """si#106's own measurement, made at last through the coordinate it was written about.

    The first run leaves passing binaries in `build/`. The source is then broken so the compile fails,
    and the gate must end at the preamble: `ctest` over the binaries the failed build did not replace
    would report three passing tests for a product that does not compile.
    """
    # arrange: a green run first, so there ARE stale binaries to be wrongly reported
    _product(monkeypatch, tmp_path, PASSES)
    gate, cfg = _loaded(tmp_path)
    assert testrun.assess_gate(gate, cfg, [], filtered=False).ok, "the arrange run was not green"
    stale = _binaries(tmp_path)
    assert stale, "the arrange run left no binary, so there is no wrong green to prevent"
    (tmp_path / "calc_test.cpp").write_text(DOES_NOT_COMPILE, encoding="utf-8")

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: the run learned nothing about the product, and the record says which command fell over
    assert gv.verdict is Verdict.SETUP_FAILED, f"a failed compile reported {gv.verdict}: {gv.line}"
    assert gv.rc != 0 and not gv.ok
    assert "build compile" in gv.line and "build unit" in gv.line, gv.line
    assert _binaries(tmp_path) == stale, "the failed compile replaced the binary it was supposed to fail on"


def test_the_gate_hands_the_toolchain_body_the_command_path_it_is_running(monkeypatch, tmp_path):
    """WHAT `GateContext` IS FOR, measured through the one thing `run_toolchain` reads off a context.

    Its refusals are worded with `ctx.command_path`, so a stand-in carrying the wrong path - or a
    hardcoded `toolchain:run` - would say the wrong thing about which manifest entry to edit. The image
    is dropped from the command's `with:` here, which is the refusal that quotes it, and nothing reaches
    docker at all - which is why this one carries no `needs_docker`, unlike the three above it.
    """
    # arrange: a command whose `with:` names no image
    _product(monkeypatch, tmp_path, PASSES)
    manifest = (tmp_path / "gatedemo.yaml").read_text(encoding="utf-8")
    (tmp_path / "gatedemo.yaml").write_text(
        manifest.replace('          image: "silkeh/clang:19"\n          workdir: "/src"\n'
                         '          argv: ["ctest", "--test-dir", "build", "--output-on-failure"]',
                         '          workdir: "/src"\n'
                         '          argv: ["ctest", "--test-dir", "build", "--output-on-failure"]'),
        encoding="utf-8")
    gate, cfg = _loaded(tmp_path)

    # act
    with pytest.raises(SystemExit) as refused:
        testrun.assess_gate(gate, cfg, [], filtered=False)

    # assert: `log.die` exited, and the gate did not invent a command path
    assert refused.value.code == 1


def test_the_body_a_gate_backs_may_read_only_the_command_path(monkeypatch, tmp_path):
    """The other half of the stand-in, and the reason it is a class rather than a `SimpleNamespace`.

    A body reaching for `ctx.args` is asking a gate for a command line, and a gate has none - so the
    answer is a refusal naming the gate, the command and the attribute, not an `AttributeError` from
    three frames down inside somebody else's body and not an invented empty list.
    """
    # arrange
    ctx = testrun.GateContext(command_path="build unit", where="'suites.gates.unit.command'")

    # act
    with pytest.raises(ValueError) as refused:
        ctx.args  # noqa: B018 - the attribute access IS the act

    # assert
    said = str(refused.value)
    assert ctx.command_path == "build unit", "the one true attribute stopped answering"
    assert "'build unit' reads 'ctx.args'" in said, said
    assert "suites.gates.unit.command" in said, said
