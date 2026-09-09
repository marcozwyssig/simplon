"""si#102: the generated build files DRIVEN - configured, compiled, tested and executed.

WHY THIS FILE IS THE REASON 0.9.0 EXISTS. simplon 0.8.0 shipped a uniform build no product could
drive, because every test behind it stubbed `run`: the shape was asserted, the thing was never done,
and the first product to type the command met four faults at once. A generator is exactly the same
trap one level down - `tests/test_buildfiles_cmake.py` and `tests/test_buildfiles_dotnet.py` compare
strings, and a string comparison cannot tell a CMakeLists.txt from a CMakeLists.txt that CMake
refuses. So this file runs the real compilers over the real output and asserts on what came back.

WHAT IS REAL HERE AND WHAT IS NOT, stated rather than left to be discovered:

  * the product TREE is real, on disk, and every generated file is written by the coordinate's own
    function rather than by a helper this file keeps;
  * the IMAGE and the ARGV are the kernel's own profile (`simplon.tasks.profiles`), read out of the
    table rather than typed here - so the run is the one a product gets from `support:toolchain`,
    and a table entry that stops working takes this suite with it;
  * the CONTAINER is driven through `toolchain:run`'s own body, so the mount, the workdir and the
    `--user` are the kernel's decisions and not this file's;
  * `simplon init` is NOT run. Scaffolding a product means provisioning a venv and installing this
    kernel into it, which is a network operation and minutes long, and what it would add over
    `ProductContext` plus a manifest is the launcher script - which is not what si#102 wrote. The
    reachability half is covered without docker instead:
    `test_a_product_that_declares_the_coordinate_gets_a_command_that_takes_nothing` assembles a real
    product CLI from a manifest and invokes the command through it, which is the si#105 failure
    (a coordinate that cannot be bound to a manifest) caught in the place it happened.

WHY THE SKIP IS ON DOCKER AND NOTHING ELSE. `shutil.which` plus one `docker version` probe is the
shape `simplon.docker._daemon_reachable` uses and the shape `tests/test_completiongen.py` uses for
bash: the tool is the thing being measured, so its absence is a skip and everything else is a
failure. A missing image is NOT a skip - `docker run` pulls it, and a pull that fails is a red suite
saying so, because "the image could not be fetched" and "the generated project does not compile"
must never arrive as the same verdict.

AAA throughout.
"""
import shutil
import types

import pytest
import typer
import yaml
from typer.testing import CliRunner

from simplon import catalogue as catalogue_mod
from simplon import cli, context
from simplon.context import ProductContext
from simplon.orchestrator import manifest as manifest_mod
from simplon.run import run
from simplon.tasks import buildfiles, profiles, toolchain

#: The two profiles this file drives, resolved from the kernel's own table. The versions are the ones
#: the case chapters pin, so the images are the ones a product on this kernel really runs.
CPP = profiles.profile("cpp", version="19")
DOTNET = profiles.profile("dotnet", version="9.0")

#: Docker, or the reason there will be no verdict. Probed once at import: `which` first so a host
#: without the CLI never pays for a subprocess, then one `docker version` because an installed CLI
#: with no daemon behind it fails in a way that looks like a broken generator.
_DOCKER = shutil.which("docker") is not None and run(["docker", "version"]).ok

needs_docker = pytest.mark.skipif(
    not _DOCKER, reason="no docker daemon here to compile the generated tree in")


# --- the product this file builds ------------------------------------------------------------------

#: The symbol the co-located unit test defines and nothing else does. It is the whole of si#134's
#: proof: a name that can only have come from `calculator_test.cpp`, looked for in `libcalculator.a`.
#: `main` alone would not do - every test file has one, and so does every executable - so the check
#: needs a symbol whose presence in the archive has exactly one explanation.
UNIT_TEST_MARKER = "e2edemo_unit_test_marker"

#: A C++ product carrying every shape this lane decides (si#131, si#134, si#132), and no more than
#: that - what is under test is the build files, not the code:
#:
#:   * `src/calculator/` - a static library whose sources are NESTED one level down (`detail/mul.cpp`)
#:     and whose unit test sits BESIDE it (`calculator_test.cpp`);
#:   * `src/plugin/` - a second library, declared `kind: shared`;
#:   * `src/e2edemo/` - the executable, which links both and repeats NO include path;
#:   * `tests/system/` - a system-level test, so `ctest -L` has two levels to tell apart.
CPP_SOURCES = {
    "src/calculator/calculator.h": (
        "#pragma once\n"
        "\n"
        "namespace demo {\n"
        "int add(int a, int b);\n"
        "int mul(int a, int b);\n"
        "}\n"
    ),
    "src/calculator/calculator.cpp": (
        '#include "calculator.h"\n'
        "\n"
        "namespace demo {\n"
        "int add(int a, int b) { return a + b; }\n"
        "}\n"
    ),
    # NESTED, and the only definition of `demo::mul` there is. A generator that reads direct children
    # only does not compile this file, and the failure is an undefined symbol at link time rather than
    # a missing file - which is si#131's first face, and is why the definition lives down here.
    "src/calculator/detail/mul.cpp": (
        '#include "../calculator.h"\n'
        "\n"
        "namespace demo {\n"
        "int mul(int a, int b) { return a * b; }\n"
        "}\n"
    ),
    # CO-LOCATED, beside the unit it tests, and it names neither a dependency nor an include path: it
    # sits inside the library's own directory, so the tree already says both (si#134).
    "src/calculator/calculator_test.cpp": (
        "#include <cstdio>\n"
        "\n"
        '#include "calculator.h"\n'
        "\n"
        f"int {UNIT_TEST_MARKER}() {{ return 7; }}\n"
        "\n"
        "int main() {\n"
        f"    if ({UNIT_TEST_MARKER}() != 7) {{ return 1; }}\n"
        '    if (demo::add(2, 3) != 5) { std::puts("add: wrong"); return 1; }\n'
        '    if (demo::mul(4, 5) != 20) { std::puts("mul: wrong"); return 1; }\n'
        '    std::puts("calculator: 2 of 2");\n'
        "    return 0;\n"
        "}\n"
    ),
    "src/plugin/plugin.h": (
        "#pragma once\n"
        "\n"
        "namespace demo {\n"
        "int twice(int a);\n"
        "}\n"
    ),
    "src/plugin/plugin.cpp": (
        '#include "plugin.h"\n'
        "\n"
        "namespace demo {\n"
        "int twice(int a) { return 2 * a; }\n"
        "}\n"
    ),
    "src/e2edemo/main.cpp": (
        "#include <cstdio>\n"
        "\n"
        '#include "calculator.h"\n'
        '#include "plugin.h"\n'
        "\n"
        "int main() {\n"
        '    std::printf("e2edemo: 2 + 3 = %d\\n", demo::add(2, 3));\n'
        '    std::printf("e2edemo: 2 * 4 = %d\\n", demo::twice(4));\n'
        "    return 0;\n"
        "}\n"
    ),
    "tests/system/smoke_test.cpp": (
        "#include <cstdio>\n"
        "\n"
        '#include "calculator.h"\n'
        "\n"
        "int main() {\n"
        '    if (demo::add(1, 1) != 2) { std::puts("smoke: wrong"); return 1; }\n'
        '    std::puts("smoke: 1 of 1");\n'
        "    return 0;\n"
        "}\n"
    ),
}

#: THE WHOLE OF WHAT THE TREE CANNOT SAY, and its shortness is itself the assertion (si#131).
#:
#: There is no `include:` key anywhere any more. si#102's version needed one on both targets that
#: reached `calculator.h`, because the library's include directory was PRIVATE and therefore inherited
#: by nothing. A library that EXPORTS its own directory makes every one of those entries a repetition
#: of a fact the link already carries - so if any of these targets still needed one, the compile would
#: say so, on the header the manifest no longer names.
#:
#: `kind: shared` is the other half: a directory of sources cannot show whether it wants an archive or
#: a shared object, and this is the one word that says it.
CPP_TARGETS = {
    "e2edemo": {"depends": ["calculator", "plugin"]},
    "plugin": {"kind": "shared"},
    "smoke_test": {"depends": ["calculator"]},
}

#: The .NET product, in the shapes the same table names for that language: a class library directory,
#: an executable directory (`Program.cs` is the main), and a project directory under `tests/`.
#:
#: `using System;` IS WRITTEN OUT, and that is a property of the generated project rather than a
#: habit. `dotnet new` sets `<ImplicitUsings>enable</ImplicitUsings>`; the generator does not, because
#: the design's section 5 keeps property groups out of scope - so a top-level `Console.WriteLine` with
#: no using is `error CS0103: The name 'Console' does not exist in the current context`, measured.
DOTNET_SOURCES = {
    "src/Calculator/Calculator.cs": (
        "namespace Demo;\n"
        "\n"
        "public static class Calculator\n"
        "{\n"
        "    public static int Add(int a, int b) => a + b;\n"
        "    public static int Mul(int a, int b) => a * b;\n"
        "}\n"
    ),
    "src/E2eDemo/Program.cs": (
        "using System;\n"
        "\n"
        "using Demo;\n"
        "\n"
        'Console.WriteLine($"e2edemo: 2 + 3 = {Calculator.Add(2, 3)}");\n'
    ),
    "tests/Calculator.Tests/CalculatorTests.cs": (
        "using Demo;\n"
        "\n"
        "namespace Demo.Tests;\n"
        "\n"
        "public static class CalculatorTests\n"
        "{\n"
        "    public static bool Adds() => Calculator.Add(2, 3) == 5;\n"
        "}\n"
    ),
}

DOTNET_TARGETS = {
    "E2eDemo": {"depends": ["Calculator"]},
    "Calculator.Tests": {"depends": ["Calculator"]},
}

#: What the .NET SDK needs to run as somebody. `docker.user_args()` runs the container as the CALLING
#: uid, which the image has no passwd entry for, so `$HOME` is `/` and the CLI's first-run
#: configuration dies on `Access to the path '/.dotnet' is denied` (measured as uid 1000; as uid 0 it
#: passes, which is exactly why it has to be measured rather than assumed).
DOTNET_ENV = {"DOTNET_CLI_HOME": "/tmp"}


def _product(monkeypatch, tmp_path, name, sources, targets):
    """A real product on disk with its context registered: the sources, and a manifest carrying the
    `build: targets:` block. Nothing is stubbed - the manifest is read back off the disk by the task.

    The context goes on through `monkeypatch` rather than `set_current`, so a product built for one
    test is not still registered for the next one - the process-wide registration is exactly the kind
    of leftover the third row of the C++ chapter's table is about.
    """
    for rel, text in sources.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    manifest = {"product": name, "build": {"targets": targets}}
    (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext(name, tmp_path, tmp_path / f"{name}.yaml"))
    return tmp_path


def _in_image(profile, argv, *, workdir="/src", where="build run", env=None):
    """One `toolchain:run` invocation over the registered product's tree, in the profile's own image.

    Driven through the coordinate's own body rather than through a `docker run` written here, so the
    mount, the working directory and the `--user` are the kernel's decisions and this file cannot
    accidentally prove the generator works under an invocation no product makes.

    `ctx` carries one attribute because `run_toolchain` reads one - the command path it names in a
    refusal. A real `typer.Context` cannot be built without a Click command to hang it on, and
    building one here would be testing Click.
    """
    ctx = types.SimpleNamespace(command_path=where)
    return toolchain.run_toolchain(ctx, image=profile.image, argv=list(argv), workdir=workdir,
                                   env=dict(env or {}))


def _drain(capfd):
    """Everything the container said, both streams as one text.

    BOTH, and it is the compiler that makes it necessary rather than tidiness: clang writes its
    diagnostics to stderr, so a check that read stdout alone would find a failed build indistinguishable
    from a silent one - which is this repository's own recurring defect, read backwards.
    """
    captured = capfd.readouterr()
    return captured.out + captured.err


def _step(profile, command, env=None):
    """One of the profile's OWN commands, argv and workdir included - `build configure` as a product
    that ran `support:toolchain` really gets it."""
    body = profile.commands[command]
    return _in_image(profile, body["argv"], workdir=str(body["workdir"]),
                     where=f"build {command}", env=env)


# --- the coordinate is reachable from a manifest (no docker) ----------------------------------------


def test_a_product_that_declares_the_coordinate_gets_a_command_that_takes_nothing(
        monkeypatch, tmp_path):
    """si#105's failure, caught where it happened: a coordinate whose impl the loader cannot bind.

    `toolchain:run` was declared, scaffolded and unusable, because the manifest's keys and the impl's
    parameters were two different lists and nothing compared them until a person typed the command.
    These two take no parameters at all, so the assertion is that a product declaring them gets a
    command that runs on the bare word - and it is made by assembling a REAL Typer app from a REAL
    manifest against the REAL catalogue, which is the only place that claim can be false.
    """
    # arrange
    root = _product(monkeypatch, tmp_path, "e2edemo", CPP_SOURCES, CPP_TARGETS)
    text = yaml.safe_dump({
        "product": "e2edemo",
        "groups": {"build": {"commands": {"cmake-files": {"task": "build:cmake-files"},
                                          "dotnet-solution": {"task": "build:dotnet-solution"}}}},
        "build": {"targets": CPP_TARGETS},
    }, sort_keys=False)
    (root / "e2edemo.yaml").write_text(text, encoding="utf-8")
    parsed = manifest_mod.load(text, catalogue=catalogue_mod.load())
    app = typer.Typer()
    cli.assemble(app, parsed, product="e2edemo")

    # act
    result = CliRunner().invoke(app, ["build", "cmake-files"])

    # assert: the command exists, takes nothing, and did the work
    assert result.exit_code == 0, result.output
    assert (root / "CMakeLists.txt").is_file()
    assert (root / "src" / "calculator" / "CMakeLists.txt").is_file()


# --- C++: generated, configured, compiled, tested, executed -----------------------------------------


def _inspect(*argv_lines):
    """Run a line of shell in the toolchain image over the built tree, for `file` and `nm`.

    WHY A SHELL LINE AND NOT AN ARGV. What is being read here is not a tool's exit code, it is a tool's
    OUTPUT, and several tools have to be asked about several files in one container. `silkeh/clang:19`
    carries `file`, `nm`, `readelf` and `objdump` (probed, 2026-09-09), so the reading needs nothing
    the compile did not already need.

    The rc is returned like every other step's, because a `file` that could not open the artefact and a
    `file` that answered are two different things and only the rc tells them apart.
    """
    return _in_image(CPP, ["bash", "-c", "; ".join(argv_lines)], where="build inspect")


@needs_docker
def test_the_generated_cmake_tree_configures_compiles_tests_and_runs(monkeypatch, tmp_path, capfd):
    """THE ONE THAT MAKES THE OTHER TWO SUITES MEAN SOMETHING. Everything up to here compares strings;
    this hands the strings to CMake and to clang and asserts on what they said.

    One test rather than four, deliberately: `configure`, `compile`, `unit` and the binary are four
    steps of ONE claim - that what the generator wrote is a project - and splitting them would either
    repeat the whole build three times or leave three tests silently depending on each other's
    leftovers, which is the exact defect the C++ chapter's third row is about.
    """
    # arrange
    _product(monkeypatch, tmp_path, "e2edemo", CPP_SOURCES, CPP_TARGETS)
    assert buildfiles.cmake() == 0
    capfd.readouterr()

    # act: the profile's own three commands, in the image the profile names
    configured = _step(CPP, "configure")
    compiled = _step(CPP, "compile")
    tested = _step(CPP, "unit")
    # ... and then the binary itself. WHERE IT IS is a property of the generated tree rather than a
    # guess: `add_subdirectory` puts a target's output under its own directory, so an executable
    # declared in `src/<name>/` lands at `build/src/<name>/<name>` and NOT at `build/<name>`, which is
    # what a hand-written top-level CMakeLists.txt produces and what the C++ chapter's `deploy up`
    # argv still names.
    ran = _in_image(CPP, ["./build/src/e2edemo/e2edemo"], where="deploy up")
    output = _drain(capfd)

    # assert: every step of the loop, and the rc is the tool's own
    assert (configured, compiled, tested, ran) == (0, 0, 0, 0), output

    # assert: and each one really did the thing, rather than exiting 0 having done nothing
    assert "Build files have been written to" in output
    assert "Linking CXX static library libcalculator.a" in output
    assert "Linking CXX shared library libplugin.so" in output
    assert "Linking CXX executable e2edemo" in output
    assert "100% tests passed, 0 tests failed out of 2" in output
    assert "e2edemo: 2 + 3 = 5" in output
    # ... and the nested source really was compiled INTO the library it sits under (si#131). `mul` is
    # defined nowhere else, so a generator reading direct children only fails the link above rather
    # than this line - which is the point: the defect is not a missing file, it is a missing symbol.
    assert "e2edemo: 2 * 4 = 8" in output


@needs_docker
def test_the_artefacts_the_generator_named_are_the_artefacts_that_came_out(monkeypatch, tmp_path,
                                                                          capfd):
    """si#131 and si#132, READ OFF THE PRODUCED FILES - which is the only place either claim is true.

    THIS IS THE PROOF STANDARD AND NOT A SECOND OPINION. `add_library(plugin SHARED ...)` appears in
    the generated text whether or not CMake produced a shared object, `-DCMAKE_BUILD_TYPE` appears in
    an argv whether or not the compiler was given `-g`, and si#102's own review read both kinds of
    string and saw nothing. So nothing here greps a CMakeLists: it builds, and then asks `file` and
    `nm` what is on the disk.

    THE DEBUG CHECK LOOKS FOR `with debug_info` AND DELIBERATELY NOT FOR `not stripped`. Measured in
    this image on 2026-09-09: a build with NO build type at all is already `not stripped`, and gains
    `with debug_info` only when one is set. An assertion on the first word would be green on exactly
    the tree si#132 was opened about - a check that cannot fail, which is the defect this repository
    spends most of its time hunting.
    """
    # arrange
    _product(monkeypatch, tmp_path, "e2edemo", CPP_SOURCES, CPP_TARGETS)
    assert buildfiles.cmake() == 0
    capfd.readouterr()

    # act
    configured = _step(CPP, "configure")
    compiled = _step(CPP, "compile")
    read = _inspect(
        "file build/src/plugin/libplugin.so",
        "file build/src/calculator/libcalculator.a",
        "file build/src/e2edemo/e2edemo",
        "echo '--- symbols in the library archive ---'",
        "nm build/src/calculator/libcalculator.a",
    )
    output = _drain(capfd)

    # assert
    assert (configured, compiled, read) == (0, 0, 0), output

    # assert: the kind a target declared is the kind that came out (si#131)
    assert "libplugin.so: ELF" in output and "shared object" in output, output
    assert "libcalculator.a: current ar archive" in output, output

    # assert: the run carried a build type, and the binary can be debugged (si#132)
    assert "with debug_info" in output, output

    # assert: THE si#134 DEFECT, which no string assertion over the generated text can see - the unit
    # test sits INSIDE the library's directory, and its code must not be inside the library
    symbols = output.split("--- symbols in the library archive ---", 1)[-1]
    assert UNIT_TEST_MARKER not in symbols, symbols
    assert "T main" not in symbols, symbols
    # ... and the archive is not empty either, or the two lines above would hold over nothing
    assert "T _ZN4demo3addEii" in symbols, symbols
    assert "T _ZN4demo3mulEii" in symbols, symbols


@needs_docker
def test_a_level_is_a_label_ctest_can_select_on(monkeypatch, tmp_path, capfd):
    """si#134's other half: `tests/` holds two levels now, so the generated build has to tell them
    apart - and the place a level becomes a fact rather than a path is ctest's own label.

    THE ASSERTION IS ON THE ACCOUNTING LINE AND NOT ON THE EXIT CODE, and that is measured rather than
    careful: `ctest -L nosuchlabel` exits **0** and prints `No tests were found!!!`. A level check that
    read the rc would be green for a label nothing carries, which is the same green-that-cannot-fail
    the debug-symbol check above avoids one file over.
    """
    # arrange
    _product(monkeypatch, tmp_path, "e2edemo", CPP_SOURCES, CPP_TARGETS)
    assert buildfiles.cmake() == 0
    capfd.readouterr()
    assert _step(CPP, "configure") == 0
    assert _step(CPP, "compile") == 0
    capfd.readouterr()

    # act
    unit = _in_image(CPP, ["ctest", "--test-dir", "build", "-L", "unit", "--output-on-failure"],
                     where="build unit")
    unit_said = _drain(capfd)
    system = _in_image(CPP, ["ctest", "--test-dir", "build", "-L", "system", "--output-on-failure"],
                       where="build unit")
    system_said = _drain(capfd)

    # assert: each level ran, and ran ONE test - the count is what an empty selection cannot fake
    assert (unit, system) == (0, 0), unit_said + system_said
    assert "100% tests passed, 0 tests failed out of 1" in unit_said, unit_said
    assert "100% tests passed, 0 tests failed out of 1" in system_said, system_said

    # assert: and it ran the RIGHT one. Both halves, because a label that selected everything would
    # satisfy the first assertion of each pair on a suite of one test per level
    assert "calculator_test" in unit_said and "smoke_test" not in unit_said, unit_said
    assert "smoke_test" in system_said and "calculator_test" not in system_said, system_said


@needs_docker
def test_a_dependency_the_manifest_did_not_declare_is_a_compile_error_and_not_a_guess(
        monkeypatch, tmp_path, capfd):
    """The rejected alternative, driven. Guessing dependencies from include paths was refused in the
    design because an approximate answer fails at LINK time in a message about symbols; the other half
    of that decision is that a DECLARED dependency is what makes the link work, and both halves are
    only checkable against a real compiler.

    So the same tree is generated with an empty `targets:` block: the includes are gone, the link is
    gone, and the build fails on the header the manifest was supposed to name.
    """
    # arrange
    _product(monkeypatch, tmp_path, "e2edemo", CPP_SOURCES, {})
    assert buildfiles.cmake() == 0
    capfd.readouterr()

    # act
    configured = _step(CPP, "configure")
    compiled = _step(CPP, "compile")
    output = _drain(capfd)

    # assert: the project is still a project - it is the target that cannot be built
    assert configured == 0, output
    assert compiled != 0
    assert "calculator.h" in output


# --- .NET: generated, built, executed ---------------------------------------------------------------


@needs_docker
def test_the_generated_solution_builds_and_the_output_runs_in_the_image_that_built_it(
        monkeypatch, tmp_path, capfd):
    """The .NET half, as far as the toolchain image allows - and the second clause of the name is the
    finding rather than decoration.

    `dotnet test` is NOT driven: a test project needs the test SDK's package references, which the
    design's section 5 keeps out of scope, so `IsTestProject` states the intent the tree shows and
    nothing more. What IS driven is the whole of what the generator claims: three projects, one
    solution, a `ProjectReference` between them, `dotnet build` over the solution, and then the
    produced assembly EXECUTED - which is the step that caught `TargetFramework` naming a runtime the
    SDK image does not carry.
    """
    # arrange
    _product(monkeypatch, tmp_path, "e2edemo", DOTNET_SOURCES, DOTNET_TARGETS)
    assert buildfiles.dotnet() == 0
    capfd.readouterr()

    # act
    built = _step(DOTNET, "compile", env=DOTNET_ENV)
    assembly = f"src/E2eDemo/bin/Debug/{buildfiles.TARGET_FRAMEWORK}/E2eDemo.dll"
    ran = _in_image(DOTNET, ["dotnet", assembly], where="deploy up", env=DOTNET_ENV)
    output = _drain(capfd)

    # assert
    assert (built, ran) == (0, 0), output
    assert "Build succeeded." in output
    assert "0 Error(s)" in output
    assert "e2edemo: 2 + 3 = 5" in output

    # assert: the solution really is what was built - all three projects, by name
    for project in ("Calculator", "Calculator.Tests", "E2eDemo"):
        assert f"{project} -> " in output
