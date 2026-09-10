"""si#95: the ready-made toolchain configurations. DATA, and inert after the scaffold.

The whole assurance a profile table needs is that a broken entry cannot ship, so the first test walks
every profile and holds it against the SHAPE `toolchain.declared()` requires: a non-empty `argv` list, a
`workdir` string, and an image template that formats with the profile's own parameters.

WHY THE SHAPE AND NOT THE FUNCTION. `simplon.tasks.toolchain` is being written in parallel (the plan's
Tasks 1-3), so this file cannot import it without coupling one half of si#95 to the other half's landing
order. The round-trip - every profile body through `toolchain.declared()`, which is the assertion that
the two halves actually agree - belongs in the integration once both are on main. It is a KNOWN gap, not
a forgotten one; the shape asserted below is the contract `declared()` states, and the day the two
disagree is the day the round-trip is worth more than this.

THAT DAY ARRIVED FOR ONE KEY (si#121). Both halves are on main, and the python profile now pins `env:` -
a key no profile had ever carried, so the shape asserted here says nothing about whether `declared()`
accepts it. `test_the_python_bodies_survive_the_toolchain_gate` takes the round trip, for the python
bodies only: exactly as far as the new key reaches, and no further, because the rest of the gap is still
somebody's decision rather than this ticket's.
"""
import pytest

from simplon.tasks import profiles, toolchain


def test_every_profile_declares_a_body_the_toolchain_gate_will_accept():
    # arrange: a broken profile must not be shippable
    for language, prof in profiles.PROFILES.items():
        # act
        resolved = profiles.profile(language, version="1")

        # assert: the image template is a template, and it names a version once formatted
        assert "{" not in resolved.image and resolved.image.endswith("1")
        for name, body in prof.commands.items():
            where = f"{language}.{name}"
            assert isinstance(body["argv"], list) and body["argv"], where
            assert all(isinstance(word, str) for word in body["argv"]), where
            assert isinstance(body["workdir"], str) and body["workdir"], where


def test_the_cpp_profile_compiles_tests_and_analyses():
    # arrange / act
    prof = profiles.profile("cpp", compiler="clang", version="19")

    # assert: the spec's table, as data
    assert prof.image == "silkeh/clang:19"
    assert prof.commands["compile"]["argv"][:2] == ["cmake", "--build"]
    assert "ctest" in prof.commands["unit"]["argv"]
    assert "run-clang-tidy" in prof.commands["analyse"]["argv"]


def test_the_cpp_configure_command_asks_for_a_build_type_that_carries_symbols():
    """si#132: with a single-config generator an EMPTY `CMAKE_BUILD_TYPE` means no optimisation and no
    `-g` at all, so the binary si#102 compiled and ran carried no debug symbols. Nothing set it, and
    the generated `CMakeLists.txt` deliberately does not - a committed `set(CMAKE_BUILD_TYPE ...)`
    would decide it for every consumer of that tree forever. The RUN is where it belongs, and this
    table is the run: `support:toolchain` scaffolds it into the product's own manifest.

    Held as a property rather than as one literal: what matters is that a type is asked for and that
    the one asked for carries debug information. `Release` would pass the first half and fail the
    second, which is the whole reason the choice is written down.
    """
    # arrange / act
    argv = profiles.profile("cpp", version="19").commands["configure"]["argv"]
    asked = [word for word in argv if word.startswith("-DCMAKE_BUILD_TYPE=")]

    # assert
    assert asked, f"nothing asks for a build type, so the build has neither symbols nor -O: {argv}"
    assert asked[0].split("=", 1)[1] in ("Debug", "RelWithDebInfo"), asked


def test_the_cpp_compile_command_does_not_name_a_configuration_of_its_own():
    """The other half of si#132, and the one that keeps the two commands from disagreeing.

    `CMAKE_BUILD_TYPE` is a SINGLE-config generator's knob: the type is fixed at configure time and the
    build step must not carry a second answer. Ninja Multi-Config and the Visual Studio generators are
    the opposite - they ignore the cache variable and take `--config` on the build - so a profile
    naming both would be right on neither.
    """
    # arrange / act
    argv = profiles.profile("cpp", version="19").commands["compile"]["argv"]

    # assert
    assert "--config" not in argv, argv


def test_the_cpp_analyse_command_names_the_sources_it_analyses():
    """si#111: `clang-tidy -p build` takes its sources as POSITIONAL arguments and was given none, so it
    refused every run with `no input files specified` (rc 1). Measured in `silkeh/clang:19` over a real
    CMake product: `run-clang-tidy -p build` walks the compile database itself - 3 files out of 3, rc 0.

    Held as a rule rather than as a literal, because the property is what matters: the argv either names
    an input or it names a driver that finds its own. Bare `clang-tidy` does neither.
    """
    # arrange / act
    argv = profiles.profile("cpp", version="19").commands["analyse"]["argv"]

    # assert: the driver, and the compile database it walks
    assert argv[0] == "run-clang-tidy", f"a bare clang-tidy has no input to analyse: {argv}"
    assert argv[1:3] == ["-p", "build"], argv


def test_every_analyse_command_can_actually_fail():
    """The verdict has to follow the step. Measured in the pinned images on 2026-09-09: `dotnet format
    --verify-no-changes` exits 2 on a formatting fault and `mypy .` exits 1 on a type error, but
    `run-clang-tidy` exits 0 with the finding printed - a clean null-dereference report and rc 0 - so an
    analyse command without `-warnings-as-errors` is a check that cannot go red and a gate naming it is
    green forever.
    """
    # arrange / act
    argv = profiles.profile("cpp", version="19").commands["analyse"]["argv"]

    # assert
    assert "-warnings-as-errors=*" in argv, (
        f"clang-tidy reports its findings as WARNINGS and still exits 0: {argv}")


def test_the_java_compile_command_does_not_run_the_tests():
    """si#122: `gradle build` depends on `check`, so the COMPILE went red on a broken assertion - and a
    gate's `preamble:` then reported `setup-failed` for a product fault, which is the one distinction
    the preamble exists to draw.

    Measured in `gradle:jdk25` (Gradle 9.7.1) on 2026-09-10, and the ticket's own two candidates both
    fail the OTHER half: `gradle assemble` and `gradle build -x test` produce the identical task list,
    neither runs `compileTestJava`, and both are rc 0 over a test source that does not compile. So the
    rule held here is both halves at once - the tests are not RUN, and the test sources are still
    COMPILED.
    """
    # arrange / act
    argv = profiles.profile("java", version="25").commands["compile"]["argv"]

    # assert
    assert "build" not in argv, f"`gradle build` depends on `check`, so this runs the tests: {argv}"
    assert "test" not in argv, f"a compile command may not run a test task: {argv}"
    assert "testClasses" in argv, (
        f"without `testClasses` a test source that does not compile is green here: {argv}")


def test_the_java_profile_carries_no_analyse_because_gradle_cannot_supply_one():
    """si#122, and it is a DECISION pinned rather than a repair - a missing command with a reason beats
    a command that cannot fail.

    Measured in `gradle:jdk25` on 2026-09-10 over a file carrying a raw type, an unused import, a dead
    store and a guaranteed NullPointerException. `gradle check --dry-run` on a stock `java` plugin lists
    `compileJava classes compileTestJava testClasses test check` - it IS the unit command under another
    name. `gradle check -x test` runs `> Task :check` alone, no javac at all, rc 0 over all four
    defects: si#111's clang-tidy shape in its purest form, a check that cannot go red and a gate naming
    it green forever.

    The one thing in the image that DOES go red is `javac -Xlint:all -Werror` (rc 1, 4 warnings) - and
    only because the file was named on the command line, which the kernel cannot do: it knows neither
    the product's source layout nor its test classpath, which are the two things Gradle exists to know.
    SpotBugs, PMD, Checkstyle and ErrorProne are all plugins the product's own `build.gradle` applies.

    This goes red the day somebody adds one anyway, which is the point.
    """
    # arrange / act
    commands = profiles.profile("java", version="25").commands

    # assert
    assert "analyse" not in commands, (
        "java has no analyse the KERNEL can name: `gradle check` is `test` again and `gradle check "
        f"-x test` is rc 0 over four deliberate defects. Got: {sorted(commands)}")


def test_the_other_three_languages_carry_their_own_toolchain():
    # arrange / act
    java = profiles.profile("java", version="25")
    dotnet = profiles.profile("dotnet", version="9.0")
    python = profiles.profile("python", version="3.12")

    # assert: the compiler AND its version are manifest data, so both reach the image reference
    assert java.image == "gradle:jdk25" and java.commands["compile"]["argv"][0] == "gradle"
    assert dotnet.image.endswith("sdk:9.0") and dotnet.commands["unit"]["argv"][:2] == ["dotnet", "test"]
    # python reaches its tools through `python -m` rather than by name, see the two tests below
    assert python.image == "python:3.12" and python.commands["analyse"]["argv"][:3] == [
        "python", "-m", "mypy"]


def test_the_python_profile_installs_its_own_tools_before_it_runs_them():
    """si#121: `python:3.12` carries neither pytest nor mypy, so BOTH commands exited 127 before the
    product was looked at - `exec: "pytest": executable file not found in $PATH`.

    No prebuilt image fixes that honestly. mypy over a product whose dependencies are not importable
    reports missing stubs rather than type errors, which is exactly why `typecheck.py` runs the kernel's
    own mypy in the host venv - and no image on any registry carries a product's wheels. So the tools are
    installed by a command of their own, into the one directory in the container the caller provably
    owns: the bind mount. A named `caches:` volume cannot be that directory, and this repository has
    already paid to learn it (`case-java.md`: a named volume is created root-owned and `--user` cannot
    write into it).

    Driven in `python:3.12` as a NON-ROOT caller on 2026-09-10 - `--user 1000:1000` over a tree owned by
    1000, because root would have hidden every permission question. `deps` 6.0s cold and 0.9s warm, the
    user base left owned by 1000:1000; `unit` 2 passed / rc 0 and 1 failed / rc 1 on a broken assertion;
    `analyse` rc 0 clean and rc 1 with `Incompatible return value type (got "int", expected "str")`.
    """
    # arrange / act
    python = profiles.profile("python", version="3.12")

    # assert: three commands, and the two that check the product run offline once the first has run
    assert set(python.commands) == {"deps", "unit", "analyse"}, sorted(python.commands)
    for name, body in python.commands.items():
        base = body["env"]["PYTHONUSERBASE"]
        assert base.startswith(body["workdir"] + "/."), (
            f"{name}: the user base must sit INSIDE the mount, and start with a dot so neither pytest "
            f"nor mypy walks it - measured: mypy reports 3 source files over a tree whose user base "
            f"holds thousands of .py. Got {base!r} against workdir {body['workdir']!r}")
    for name in ("unit", "analyse"):
        assert python.commands[name]["argv"][:2] == ["python", "-m"], (
            f"{name}: a --user install puts its scripts in a directory that is not on PATH, so the tool "
            f"is reached as a module: {python.commands[name]['argv']}")


def test_the_python_deps_command_pins_the_tools_it_installs():
    """`docker.pinned_image`'s own rule, one level in: a build whose output depends on when it ran is not
    a build. Unpinned, the first install on a fresh tree picks whatever was newest that day.

    What pinning does NOT buy was measured too, so nobody re-derives it: an unpinned WARM install is
    offline as well (rc 0 under `--network none`), because pip short-circuits on "already satisfied"
    without querying the index. The pins are the product's to bump, in its own manifest.
    """
    # arrange / act
    argv = profiles.profile("python", version="3.12").commands["deps"]["argv"]
    installed = [word for word in argv if not word.startswith("-") and "==" in word]

    # assert
    assert argv[:5] == ["python", "-m", "pip", "install", "--user"], argv
    assert {word.split("==")[0] for word in installed} == {"pytest", "mypy"}, (
        f"deps must install exactly the two tools the other commands run, pinned: {argv}")


def test_the_python_analyse_excludes_the_directory_the_scaffolder_writes():
    """si#121, and this one only showed up when a REAL `simplon init` product was driven rather than a
    hand-made tree: `mypy .` on a scaffolded pydemo is rc 1 with five errors, and every one of them is
    `Cannot find implementation or library stub for module named "simplon"` (or `typer`) inside
    `deploy/provision/orchestrator/`. Not one is about the product.

    The orchestrator is HOST-venv Python by construction - its own `requirements.txt` installs the
    kernel into `.venv`, and `test:typecheck-python` is the command that checks it, in the environment
    where its imports exist. A container that has neither can only produce import noise about it.

    THE PATH IS DECLARED TWICE ON PURPOSE. `profiles` is a table with no behaviour and no imports beyond
    `log`, so it carries the literal rather than importing `bootstrap`; this assertion is what keeps the
    two from drifting, exactly the way the releases page's FLOOR is held to the page's own prose.
    """
    # arrange
    from simplon import bootstrap

    # act
    argv = profiles.profile("python", version="3.12").commands["analyse"]["argv"]
    excluded = argv[argv.index("--exclude") + 1] if "--exclude" in argv else ""

    # assert
    assert bootstrap.DEFAULT_ORCH_DIR in excluded, (
        f"the scaffolded orchestrator lives at {bootstrap.DEFAULT_ORCH_DIR!r} and this excludes "
        f"{excluded!r}; mypy in a container cannot resolve its host-venv imports")


def test_the_python_bodies_survive_the_toolchain_gate():
    """The round trip the module head calls a KNOWN gap, taken for the one key that needed it (si#121).

    `env:` is a key no profile had ever carried, and `toolchain.declared()` is what has to accept it -
    the shape asserted at the top of this file says nothing about that. Held here as the real function
    rather than as a second copy of its contract, because a second copy is what drifts.
    """
    # arrange
    prof = profiles.profile("python", version="3.12")

    for name, body in prof.commands.items():
        # act
        cfg = toolchain.declared({"image": prof.image, **body}, f"build {name}")

        # assert: the image is pinned, the env survives, and the argv arrives word for word
        assert cfg.image == "python:3.12"
        assert cfg.env == body["env"]
        assert cfg.argv == body["argv"]
        assert cfg.workdir == body["workdir"]


def test_an_unknown_language_is_refused_and_lists_what_exists(monkeypatch):
    # arrange
    monkeypatch.setattr(profiles.log, "die", lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))

    # act / assert
    with pytest.raises(RuntimeError) as e:
        profiles.profile("cobol")
    assert "cobol" in str(e.value) and "cpp" in str(e.value)
