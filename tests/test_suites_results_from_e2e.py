"""si#133 DRIVEN: a real non-pytest runner's results reach the rendered Allure archive, and a level that
contributed none goes RED.

WHY THIS FILE DECIDES WHETHER THE FEATURE EXISTS. `tests/test_suites_results_from.py` writes a JUnit XML
with `Path.write_text` and asserts it arrives in a directory. That proves the kernel copied a file; it
cannot prove allure READS it, and the ticket's own warning is that an archive rendered with a level
missing looks exactly like one where the level passed. simplon 0.8.0 shipped a uniform build no product
could drive because every test behind it stubbed `run`. So this one compiles a real CMake project in the
pinned clang image, runs `ctest --output-junit`, merges what ctest wrote through the gate, renders the
single-file archive with the pinned allure image, and reads the CASE NAMES back out of it.

THE TWO MEASUREMENTS THE DESIGN REFUSED TO ASSUME, made before this file was written (2026-09-09):

  * `allure generate` reads raw allure `*-result.json`, ctest's JUnit XML and a `dotnet test` TRX out of
    ONE directory - 2 + 3 + 1 = 6 in the rendered summary, three suites. The pinned image ships
    `junit-xml-plugin`, `xunit-xml-plugin` and `trx-plugin` beside the allure2 reader. No conversion and
    no second directory;
  * the .NET SDK image ships the TRX logger with no `PackageReference`; `--logger junit` answers
    `Could not find a test logger ... 'junit'` and exits 1. Nothing here depends on the second answer.

WHY THE GATE BELOW IS AN `impl:` AND NOT THE `command:` THE TICKET DESCRIBES. It was measured rather
than chosen, and the measurement has since been repaired. When this file was written a `command:` gate
could NOT name a `toolchain:run` command: `run_toolchain`'s first parameter is a `typer.Context` and
`_command` refused any body that took one, while every si#106 test resolved to
`simplon.test_impls:pinned_rc`, a body with no context - so nothing caught it and both case chapters
promised a shape neither had driven. si#136 fixed that (a gate hands such a body a `GateContext`), and
`tests/test_suites_command_gate_e2e.py` is where the real coordinate is now driven. The `impl:` gate
stays HERE because this file is about `results_from:` and not about the gate kind: it is javademo's real
shape, it exercises the merge through a runner the kernel cannot see, and rewriting it onto the other
kind would put a second change in a diff whose whole claim is the first.

WHY THE SKIP IS ON DOCKER AND NOTHING ELSE - the rule `tests/test_buildfiles_e2e.py` states: the tool is
what is being measured, so its absence is a skip and everything else is a failure. A missing image is not
a skip, because "the image could not be fetched" and "the level contributed nothing" must never arrive as
the same verdict.

AAA throughout.
"""
import base64
import json
import re
import shutil
import textwrap
from pathlib import Path

import pytest

from simplon import context
from simplon.context import ProductContext
from simplon.run import run
from simplon.tasks import profiles, testrun, toolchain
from simplon.verdict import Verdict

#: The C++ toolchain a product on this kernel really gets, read out of the kernel's own table rather than
#: typed here - so a table entry that stops working takes this suite with it.
CPP = profiles.profile("cpp", version="19")

#: Where the product's runner writes and what its gate declares. One constant: a test in which the two
#: differ by a typo would be measuring the typo.
WROTE_INTO = "build/test-results"

_DOCKER = shutil.which("docker") is not None and run(["docker", "version"]).ok

needs_docker = pytest.mark.skipif(
    not _DOCKER, reason="no docker daemon here to compile, test and render in")


# --- the product -------------------------------------------------------------------------------------

#: Three ctest cases over one binary. Small on purpose: what is under test is where the results go, not
#: what they say. Three rather than one so a report that carries "a case" can be told from one that
#: carries THIS LEVEL's cases.
SOURCES = {
    "CMakeLists.txt": textwrap.dedent("""\
        cmake_minimum_required(VERSION 3.20)
        project(e2edemo CXX)
        enable_testing()
        add_executable(calc_test calc_test.cpp)
        add_test(NAME AddsTwoNumbers COMMAND calc_test add)
        add_test(NAME MultipliesTwoNumbers COMMAND calc_test mul)
        add_test(NAME SubtractsTwoNumbers COMMAND calc_test sub)
        """),
    "calc_test.cpp": textwrap.dedent("""\
        #include <cstring>

        int main(int argc, char** argv) {
            if (argc < 2) return 1;
            if (std::strcmp(argv[1], "add") == 0) return (2 + 3 == 5) ? 0 : 1;
            if (std::strcmp(argv[1], "mul") == 0) return (2 * 3 == 6) ? 0 : 1;
            if (std::strcmp(argv[1], "sub") == 0) return (5 - 3 == 2) ? 0 : 1;
            return 1;
        }
        """),
}

MANIFEST = textwrap.dedent("""\
    product: e2edemo
    groups:
      build:
        commands:
          unit:
            task: "toolchain:run"
            with:
              image: "silkeh/clang:19"
              workdir: "/src"
              argv: ["ctest", "--test-dir", "build", "--output-on-failure"]
            help: "ctest."
    """)


def _product(monkeypatch, tmp_path):
    """A real C++ product on disk with its context registered, and a manifest that declares the raw
    toolchain command a product really writes."""
    for rel, text in SOURCES.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    (tmp_path / "e2edemo.yaml").write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("e2edemo", tmp_path, tmp_path / "e2edemo.yaml"))
    return tmp_path


def _in_image(argv, workdir="/src"):
    """One invocation in the profile's image, assembled by the kernel's own `docker_argv`.

    Not a `docker run` written here: the mount, the working directory and the `--user` are the kernel's
    decisions, and a drive that made them itself could prove the feature works under an invocation no
    product makes. It is also the exact shape a product's own gate body has to use today - see the module
    head on why `run_toolchain` itself is out of reach from a gate.
    """
    cfg = toolchain.declared({"image": CPP.image, "argv": list(argv), "workdir": workdir}, "build unit")
    product = context.current()
    return run(toolchain.docker_argv(cfg, root=product.root, product=product.name, instance="",
                                     extra=[]), capture=False).rc


# --- the product's own runner, as a gate's `impl:` reaches it -----------------------------------------


def compile_it() -> int:
    """Configure and compile - the preparation a test command needs, and nothing else."""
    rc = _in_image(["cmake", "-S", ".", "-B", "build"])
    return rc or _in_image(["cmake", "--build", "build", "-j"])


def ctest_writing_junit() -> int:
    """ctest, told where to put its JUnit XML. `--output-junit` creates the directory itself (measured)."""
    return _in_image([*CPP.commands["unit"]["argv"], "--output-junit", f"/src/{WROTE_INTO}/ctest.xml"])


def ctest_selecting_a_label_nothing_carries() -> int:
    """ctest asked for `--output-junit` AND for a label no test in this project has.

    The trap one layer past the empty directory, measured in `silkeh/clang:19` on 2026-09-09: this exits
    **0**, prints `No tests were found!!!`, and WRITES THE FILE - a suite element carrying `tests="0"`
    and no case in it. So a check that counts files is satisfied and the level reports green with nothing
    in the archive.

    It matters now rather than in principle: si#131 gives the generated CMake tree real ctest LABELS, so
    `ctest -L unit` becomes the ordinary way a level selects, and a label that does not match is one typo
    away.
    """
    return _in_image([*CPP.commands["unit"]["argv"], "-L", "no-test-here-carries-this",
                      "--output-junit", f"/src/{WROTE_INTO}/ctest.xml"])


def ctest_as_the_profile_runs_it() -> int:
    """ctest EXACTLY as the kernel's own cpp profile declares it - and it writes no results file at all.

    This is the red half, and it is the kernel's own argv rather than a crippled one invented for the
    test: `profiles.PROFILES["cpp"]["commands"]["unit"]` has no `--output-junit`, so a product that
    declares `results_from:` and nothing else gets rc 0, three passing tests on the terminal, and an
    archive with the level missing. That is precisely the pair si#133 exists to break up.
    """
    return _in_image(CPP.commands["unit"]["argv"])


# --- reading the archive back -------------------------------------------------------------------------

#: How `allure generate --single-file` embeds its data files. Measured on the pinned image: 35 payloads,
#: base64, and `grep AddsTwoNumbers` over the 2.6 MB HTML answers 0 on a FULL archive - the trap the Java
#: chapter already had to warn about once.
PAYLOAD = re.compile(r"d\('([^']+)','([^']*)'\)")


def _archive(reports: Path) -> Path:
    """The single archive this run rendered, or a failure naming what was there instead."""
    found = sorted(reports.glob("allure-*.html"))
    assert len(found) == 1, f"expected one rendered archive in {reports}, found {[p.name for p in found]}"
    return found[0]


def _embedded(archive: Path, name: str) -> dict:
    """One embedded data file, decoded. Raises rather than returning an empty dict for a file that is not
    there: a helper that answers "nothing" for "I could not look" is the defect this suite hunts."""
    html = archive.read_text(encoding="utf-8")
    for path, payload in PAYLOAD.findall(html):
        if path == name:
            return json.loads(base64.b64decode(payload).decode("utf-8"))
    raise AssertionError(f"the archive embeds no {name} (it embeds {len(PAYLOAD.findall(html))} files)")


def _cases(archive: Path) -> set:
    """Every test case name the rendered report carries, read out of its own suites tree.

    The walk starts at the ROOT'S CHILDREN and not at the root, because an EMPTY report's root is a
    childless node named `suites` - which a walk that also visited the root would count as a test case
    called `suites`, and this file would then report an archive with a case in it as empty. Measured:
    that is exactly what the first version of this helper did.
    """
    names: set = set()

    def walk(node):
        children = node.get("children")
        if children:
            for child in children:
                walk(child)
        elif node.get("name"):
            names.add(node["name"])

    for child in _embedded(archive, "data/suites.json").get("children") or []:
        walk(child)
    return names


def _cfg(reports="build/reports"):
    return testrun.Suites(reports=reports, filtered_results=f"{testrun.RESULTS}-filtered",
                          gates=(), merge=(), parent_suite="Cpp")


# --- the drive ------------------------------------------------------------------------------------------


@needs_docker
def test_a_levels_own_ctest_results_reach_the_rendered_archive(monkeypatch, tmp_path):
    """THE CLAIM si#133 MAKES, driven: a level whose runner is not pytest declares where it wrote, and
    the rendered report carries that level's cases.

    One test rather than four: compiling, testing, merging and rendering are four steps of ONE claim, and
    splitting them would either repeat the build three times or leave three tests depending on each
    other's leftovers.
    """
    # arrange: a compiled C++ product, and a gate that names where ctest will write
    root = _product(monkeypatch, tmp_path)
    assert compile_it() == 0, "the fixture project did not compile, so nothing below is evidence"
    cfg = _cfg()
    gate = testrun.Gate(name="unit", impl="test_suites_results_from_e2e:ctest_writing_junit",
                        results="clear", results_from=WROTE_INTO)

    # act: the gate, then the report step that renders the archive
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)
    rendered = testrun.report(cfg)

    # assert: green gate, rendered archive, and the level's own three cases inside it
    assert gv.verdict is Verdict.PASSED, gv.line
    assert rendered == 0
    archive = _archive(root / "build" / "reports")
    assert _cases(archive) == {"AddsTwoNumbers", "MultipliesTwoNumbers", "SubtractsTwoNumbers"}
    assert _embedded(archive, "widgets/summary.json")["statistic"]["total"] == 3


@needs_docker
def test_a_level_whose_runner_wrote_no_results_is_red_and_the_archive_is_empty(monkeypatch, tmp_path):
    """THE RED THIS FEATURE IS FOR, driven with the kernel's own profile argv.

    ctest exits 0 and prints `100% tests passed`; it writes no results file, because the profile's `unit`
    command has no `--output-junit` in it. Before si#133 that was a green gate and an archive with the
    level silently missing - indistinguishable from an archive where the level passed. It is now a red
    gate that names the directory, and the archive that comes out is empty rather than plausible.
    """
    # arrange
    root = _product(monkeypatch, tmp_path)
    assert compile_it() == 0
    cfg = _cfg()
    gate = testrun.Gate(name="unit", impl="test_suites_results_from_e2e:ctest_as_the_profile_runs_it",
                        results="clear", results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)
    testrun.report(cfg)

    # assert: red, and the report proves there was nothing to be green about
    assert gv.verdict is Verdict.FAILED, f"a level that contributed nothing reported {gv.line}"
    assert gv.rc != 0
    assert WROTE_INTO in gv.line, gv.line
    archive = _archive(root / "build" / "reports")
    assert _cases(archive) == set()
    assert _embedded(archive, "widgets/summary.json")["statistic"]["total"] == 0


# --- the limit this drive met, measured rather than assumed --------------------------------------------


def test_a_command_gate_can_name_the_toolchain_run_command_this_product_declares(monkeypatch, tmp_path):
    """si#106's own case, reachable at last (si#136), and kept HERE because this is where it was found.

    The predecessor of this test asserted the refusal - `'build unit' takes a CLI context, which a gate
    has none of to give it` - and said in as many words that the day somebody fixed it, this record had
    to change. It changed. What it holds now is the same join from the other side: the manifest above is
    a real product's, its `build unit` is a real `toolchain:run` command, and a `command:` gate resolves
    it instead of refusing it.

    It stops at the RESOLUTION and runs no container, deliberately: `tests/test_suites_command_gate_e2e.py`
    drives the verdict end to end, and a second full compile here would buy nothing but a minute.
    """
    # arrange: the manifest a real C++ product writes, and a gate that names its test command
    _product(monkeypatch, tmp_path)
    gate = testrun.Gate(name="unit", command="build unit", results="clear")

    # act
    runner = testrun._command(gate.command, f"gates.{gate.name}.command")

    # assert: it resolved to a callable, and to the body the manifest's `task:` names
    assert callable(runner)
    assert context.current().manifest().commands["build"]["unit"].impl == \
        "simplon.tasks.toolchain:run_toolchain"


@needs_docker
def test_a_level_whose_runner_selected_nothing_is_red_even_though_it_wrote_a_file(monkeypatch, tmp_path):
    """THE SAME RED ONE LAYER LATER, and it is the half a file-counting check would miss.

    `ctest -L <a label nothing carries>` is not a broken runner: it exits 0, says `No tests were found!!!`
    and writes a perfectly well-formed JUnit file with `tests="0"` in it. A reader meeting that line in a
    log needs to know the gate is not fooled by it, and this is where that is true rather than intended.
    """
    # arrange
    root = _product(monkeypatch, tmp_path)
    assert compile_it() == 0
    cfg = _cfg()
    gate = testrun.Gate(name="unit",
                        impl="test_suites_results_from_e2e:ctest_selecting_a_label_nothing_carries",
                        results="clear", results_from=WROTE_INTO)

    # act
    gv = testrun.assess_gate(gate, cfg, [], filtered=False)
    testrun.report(cfg)

    # assert: the file really did arrive, and the level is red anyway
    assert (root / WROTE_INTO / "ctest.xml").is_file(), (
        "ctest wrote no file at all, so this test is measuring the empty-directory case instead")
    assert gv.verdict is Verdict.FAILED, f"a file with no case in it counted as results: {gv.line}"
    assert "holds a test case" in gv.line, gv.line
    archive = _archive(root / "build" / "reports")
    assert _cases(archive) == set()
    assert _embedded(archive, "widgets/summary.json")["statistic"]["total"] == 0
