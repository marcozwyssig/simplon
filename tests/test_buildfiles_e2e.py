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

#: A C++ product with all three shapes the design's table names: a library directory, an executable
#: directory, and a test file. Small on purpose - what is under test is the build files, not the code.
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
        "int mul(int a, int b) { return a * b; }\n"
        "}\n"
    ),
    "src/e2edemo/main.cpp": (
        "#include <cstdio>\n"
        "\n"
        '#include "calculator.h"\n'
        "\n"
        "int main() {\n"
        '    std::printf("e2edemo: 2 + 3 = %d\\n", demo::add(2, 3));\n'
        "    return 0;\n"
        "}\n"
    ),
    "tests/calculator_test.cpp": (
        "#include <cstdio>\n"
        "\n"
        '#include "calculator.h"\n'
        "\n"
        "int main() {\n"
        '    if (demo::add(2, 3) != 5) { std::puts("add: wrong"); return 1; }\n'
        '    if (demo::mul(4, 5) != 20) { std::puts("mul: wrong"); return 1; }\n'
        '    std::puts("calculator: 2 of 2");\n'
        "    return 0;\n"
        "}\n"
    ),
}

#: The one thing the tree cannot say. `main.cpp` and `calculator_test.cpp` both include a header that
#: lives in the library's directory, so both targets need the dependency AND the include path - which
#: is the whole of what `build: targets:` exists for.
CPP_TARGETS = {
    "e2edemo": {"depends": ["calculator"], "include": ["src/calculator"]},
    "calculator_test": {"depends": ["calculator"], "include": ["src/calculator"]},
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
    assert "Linking CXX executable e2edemo" in output
    assert "100% tests passed, 0 tests failed out of 1" in output
    assert "e2edemo: 2 + 3 = 5" in output


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
