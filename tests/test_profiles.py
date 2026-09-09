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
"""
import pytest

from simplon.tasks import profiles


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


def test_the_other_three_languages_carry_their_own_toolchain():
    # arrange / act
    java = profiles.profile("java", version="25")
    dotnet = profiles.profile("dotnet", version="9.0")
    python = profiles.profile("python", version="3.12")

    # assert: the compiler AND its version are manifest data, so both reach the image reference
    assert java.image == "gradle:jdk25" and java.commands["compile"]["argv"][0] == "gradle"
    assert dotnet.image.endswith("sdk:9.0") and dotnet.commands["unit"]["argv"][:2] == ["dotnet", "test"]
    assert python.image == "python:3.12" and python.commands["analyse"]["argv"][0] == "mypy"


def test_an_unknown_language_is_refused_and_lists_what_exists(monkeypatch):
    # arrange
    monkeypatch.setattr(profiles.log, "die", lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))

    # act / assert
    with pytest.raises(RuntimeError) as e:
        profiles.profile("cobol")
    assert "cobol" in str(e.value) and "cpp" in str(e.value)
