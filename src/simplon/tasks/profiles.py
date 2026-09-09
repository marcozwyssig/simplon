"""The ready-made toolchain configurations (si#95): DATA, scaffolded once, then inert.

WHY THE KERNEL MAY CARRY LANGUAGE KNOWLEDGE HERE, having refused it for modules. The design says the
kernel learns no CMake, no MSBuild and no pip, because four language modules would be four surfaces that
age. This file does not break that rule, it stays on the other side of it: a profile is a TABLE of argv
and paths - no behaviour, nothing to call, nothing that decides anything at run time.

And it is not read at run time either, which is the property that makes it safe. `support:toolchain`
writes the profile INTO the product's own manifest, and from that moment the product owns what it runs:
the expanded form sits in its file, reviewable, editable, pinned. A profile resolved on every build would
mean a kernel bump could silently change how a product compiles - the same class of defect as an
unpinned image, one level up - and that is exactly what the scaffold step buys away. The table below can
therefore evolve freely: it moves nobody's build, and a wrong entry is fixed by editing a manifest
rather than by waiting for a kernel release.

The commands are the spec's convention (`compile`, `unit`, `analyse`), documented rather than enforced,
and the image is a TEMPLATE the product's own parameters fill in - so compiler and version are manifest
data, and swapping 19 for 20 is a one-line diff.
"""
from __future__ import annotations

from dataclasses import dataclass

from simplon import log


@dataclass(frozen=True)
class Profile:
    """One language's ready-made configuration: the image template, and the command bodies for it.

    A command body is exactly what a `toolchain:run` command's `with:` block takes minus the image -
    a non-empty `argv` and the `workdir` it runs in - so the scaffolder writes it out verbatim.
    """

    image: str
    commands: dict[str, dict[str, object]]


#: The kernel's starting points, one per language. Data, not behaviour: nothing here runs, and after
#: `support:toolchain` has written a copy into a product's manifest, nothing here reaches that product
#: again either.
PROFILES: dict[str, Profile] = {
    "cpp": Profile(
        image="silkeh/clang:{version}",
        commands={
            # THE BUILD TYPE IS SAID HERE AND NOWHERE ELSE (si#132). With a single-config generator an
            # EMPTY `CMAKE_BUILD_TYPE` means no optimisation and no `-g` at all, so the binary si#102
            # compiled and ran carried no debug symbols; nothing set it, and the generated
            # `CMakeLists.txt` deliberately does not either, because a committed
            # `set(CMAKE_BUILD_TYPE ...)` would decide it for every consumer of that tree forever. A
            # build type belongs to the RUN, and this table IS the run: `support:toolchain` scaffolds
            # it into the product's own manifest, where it is a line a reviewer reads and a one-word
            # diff to change. That is why si#132 needed no new manifest key.
            #
            # RelWithDebInfo rather than Debug or Release, and the choice silently decides what a stack
            # trace from a CI failure looks like: `Debug` gives symbols and no optimisation, `Release`
            # gives optimisation and nothing to read a trace with. A CI build is the one run whose
            # artefact ships AND whose failure has to be explicable, and only the third is both.
            #
            # A CALLER STILL OVERRIDES IT, measured on 2026-09-09 rather than assumed: si#105 gave
            # `toolchain:run` a variadic tail, and `cmake ... -DCMAKE_BUILD_TYPE=RelWithDebInfo
            # -DCMAKE_BUILD_TYPE=Debug` leaves `CMAKE_BUILD_TYPE:STRING=Debug` in the cache. So
            # `build configure -DCMAKE_BUILD_TYPE=Debug` is the debuggable build, and the pin is the
            # default rather than a decree.
            #
            # `compile` below needs no `--config` and the two therefore cannot disagree: this image
            # produces Unix Makefiles, where the type is fixed at configure time. Ninja Multi-Config
            # and the Visual Studio generators IGNORE `CMAKE_BUILD_TYPE` and take `--config` on the
            # BUILD step instead - the kernel ships neither, and a flag silently ignored is exactly the
            # shape that produces a green run with the wrong artefact, so it is named here.
            "configure": {"workdir": "/src",
                          "argv": ["cmake", "-S", ".", "-B", "build",
                                   "-DCMAKE_BUILD_TYPE=RelWithDebInfo"]},
            "compile": {"workdir": "/src", "argv": ["cmake", "--build", "build", "-j"]},
            # ctest EXITS 8, not 1, on a failed test - measured again on 2026-09-09: three cases, one
            # broken, `67% tests passed, 1 tests failed out of 3`, rc 8. It reports its own error class
            # in the exit code and the kernel passes the number through untouched, so anything that
            # compares a toolchain command's rc to `1` rather than to `0` reads this run as a pass.
            "unit": {"workdir": "/src", "argv": ["ctest", "--test-dir", "build", "--output-on-failure"]},
            # THE DRIVER, NOT THE CHECKER, and both of the extra words are measured rather than taste
            # (si#111). `clang-tidy` takes its sources as POSITIONAL arguments, so `clang-tidy -p build`
            # named none and refused every run it was ever given - `no input files specified`, rc 1, in
            # both directions, because a caller appending one file would still analyse one file.
            # `run-clang-tidy` ships in the same image, reads the compile database `configure` already
            # wrote, and analyses everything the project really compiles: 3 files out of 3, rc 0.
            #
            # `-quiet` drops the several-hundred-line dump of every enabled check that the driver prints
            # ahead of the run, and keeps the findings.
            #
            # `-warnings-as-errors=*` is what makes the command a CHECK. Measured on a deliberate null
            # dereference: the driver PRINTS `clang-analyzer-core.NullDereference` and still exits 0,
            # because clang-tidy reports findings as warnings - so without this flag `analyse` is green
            # on every tree, and a gate naming it is green forever. With it, the same tree is rc 1 and a
            # clean one is still rc 0. It is the C++ spelling of what `dotnet format
            # --verify-no-changes` (rc 2) and `mypy .` (rc 1) do by themselves.
            "analyse": {"workdir": "/src",
                        "argv": ["run-clang-tidy", "-p", "build", "-quiet",
                                 "-warnings-as-errors=*"]},
        },
    ),
    "java": Profile(
        image="gradle:jdk{version}",
        commands={
            # DRIVEN AND LEFT AS IT IS (si#122): both commands run and both are green on a green tree,
            # but `gradle build` depends on `check`, so `compile` runs the tests too and a broken
            # assertion makes the COMPILE red - which is the distinction a gate's `preamble:` exists to
            # draw. And there is no `analyse` here, because Java's checkers are Gradle plugins the
            # product's own `build.gradle` has to apply rather than a word the kernel can put in an argv.
            "compile": {"workdir": "/work", "argv": ["gradle", "build", "--no-daemon", "--console=plain"]},
            "unit": {"workdir": "/work", "argv": ["gradle", "test", "--no-daemon", "--console=plain"]},
        },
    ),
    "dotnet": Profile(
        image="mcr.microsoft.com/dotnet/sdk:{version}",
        commands={
            "compile": {"workdir": "/src", "argv": ["dotnet", "build"]},
            "unit": {"workdir": "/src", "argv": ["dotnet", "test"]},
            # `dotnet format --verify-no-changes` EXITS 2, not 1, on a formatting fault - measured
            # again on 2026-09-09: two stray spaces, `error WHITESPACE: Fix whitespace formatting`,
            # rc 2. Same rule as ctest's 8 above: compare to 0, never to 1.
            "analyse": {"workdir": "/src", "argv": ["dotnet", "format", "--verify-no-changes"]},
        },
    ),
    "python": Profile(
        image="python:{version}",
        # DRIVEN AND BROKEN, and left for si#121 rather than guessed at here: the official `python:3.12`
        # carries neither tool, so both commands exit 127 before the product is looked at. What the entry
        # should say is the same kind of open question si#111 was - name a product-built image, install
        # into a cache volume first, or drop the profile because Python's toolchain is a per-product set
        # of wheels rather than a compiler.
        commands={
            "unit": {"workdir": "/src", "argv": ["pytest", "-q"]},
            "analyse": {"workdir": "/src", "argv": ["mypy", "."]},
        },
    ),
}


def profile(language: str, **params: str) -> Profile:
    """The profile for a language, with its image resolved from the caller's parameters.

    An unknown language is refused by NAME and told what exists, because the answer a reader needs there
    is which four words are spelled how - not that the lookup failed.

    `cpp`'s `compiler` parameter is accepted and unused in this first cut: the image reference decides
    the compiler, so `compiler: gcc` would select a different profile entry rather than a different
    format field. That is a table entry when a product asks for it, not a knob to grow now.
    """
    if language not in PROFILES:
        log.die(
            f"no toolchain profile for '{language}' - the kernel carries: {', '.join(sorted(PROFILES))}"
        )
        raise SystemExit(1)
    prof = PROFILES[language]
    return Profile(image=prof.image.format(**params), commands=prof.commands)
