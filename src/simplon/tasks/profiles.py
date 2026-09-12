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
            # TWO TASKS, AND THE SECOND ONE IS THE MEASUREMENT (si#122). `compile` used to be
            # `gradle build`, which depends on `check` and therefore RUNS THE TESTS - so a broken
            # assertion made the COMPILE red, and si#106's gate shape (`command: "build unit"` with
            # `preamble: "build compile"`) then reported `setup-failed` for a product fault. That is
            # precisely the distinction the preamble exists to draw. Measured in `gradle:jdk25`
            # (Gradle 9.7.1) on 2026-09-10, one class and two JUnit 5 cases, `mul` returning `a + b`:
            # `gradle build` -> `CalculatorTest > multiplies() FAILED`, BUILD FAILED, rc 1.
            #
            # THE TICKET'S OWN TWO CANDIDATES ARE BOTH WRONG, and for a half it did not look for.
            # `gradle assemble` over a tree whose TEST SOURCE does not compile:
            # `compileJava classes jar assemble`, BUILD SUCCESSFUL, rc 0 - it never runs
            # `compileTestJava`, so a test that does not compile is green in the compile and red in the
            # unit gate, the same wrong verdict pointing the other way. `gradle build -x test` produces
            # the IDENTICAL task list plus an empty `:check`, because `-x` drops the excluded task's
            # exclusive dependencies too and `compileTestJava` is one of them.
            #
            # `assemble testClasses` is the pair that means what the two commands are called, measured
            # both ways on the same trees: rc 1 with `error: incompatible types: String cannot be
            # converted to int` on the broken test source, and rc 0 on the tree whose assertion is
            # broken - where `gradle test` is then rc 1 with `There were failing tests`.
            "compile": {"workdir": "/work",
                        "argv": ["gradle", "assemble", "testClasses",
                                 "--no-daemon", "--console=plain"]},
            "unit": {"workdir": "/work", "argv": ["gradle", "test", "--no-daemon", "--console=plain"]},
            # AND NO `analyse`, WHICH IS A DECISION RATHER THAN AN OMISSION (si#122). The other three
            # languages have one; java's slot stays empty because the kernel has nothing true to put in
            # it, and a missing command with a reason beats a command that cannot fail.
            #
            # Tested rather than repeated from the ticket, in the same image, over a file carrying a raw
            # type, an unused import, a dead store and a guaranteed NullPointerException.
            # `gradle check --dry-run` on a stock `java` plugin lists
            # `compileJava classes compileTestJava testClasses test check` - `check` IS `unit` under
            # another name. And `gradle check -x test` over those four defects runs `> Task :check`
            # ALONE, no javac at all, BUILD SUCCESSFUL, rc 0. That is si#111's clang-tidy finding in its
            # purest form: a command that cannot go red, and a gate naming it green forever.
            #
            # The one thing in the image that does go red is `javac -Xlint:all -Werror` (rc 1, 1 error,
            # 4 warnings) - unusable here, because it went red only for a file NAMED on the command
            # line, and the kernel knows neither the product's source layout nor its test classpath,
            # which are the two things Gradle exists to know. It also said nothing about the certain
            # NPE. SpotBugs, PMD, Checkstyle and ErrorProne are all plugins the product's own
            # `build.gradle` applies, so a product that wants one adds a `build analyse` command of its
            # own - which is a manifest line, exactly like everything else the scaffolder writes.
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
        # THE IMAGE STAYS, AND A COMMAND INSTALLS THE TOOLS (si#121). `python:3.12` carries neither
        # pytest nor mypy, so both commands used to exit 127 - `exec: "pytest": executable file not
        # found in $PATH` - before the product was looked at at all.
        #
        # WHY NOT A FATTER IMAGE, which is the obvious repair and the one that looks free. There is no
        # official python image carrying the two, so it means pinning a third party's supply chain into
        # the kernel's own table for two wheels pip installs in six seconds - and it would STILL be
        # wrong, because no prebuilt image can carry the PRODUCT's dependencies. mypy over a tree whose
        # imports are not installed reports missing stubs rather than type errors, which is precisely
        # why `typecheck.py` runs the kernel's own mypy in the host venv instead of in a container. An
        # image answer fixes the 127 and leaves `analyse` saying nothing true. A product-BUILT image
        # fails for a different reason: the profile's whole promise is a starting point that runs before
        # the product has built anything.
        #
        # WHY NOT A `caches:` VOLUME, which is the one candidate that fits the existing mechanism and is
        # already measured dead in this repository. `case-java.md`: a named docker volume is created
        # ROOT-owned, `--user <uid>:<gid>` cannot write into it, and gradle died unpacking a shared
        # object with no mention of permissions anywhere. `toolchain:run` runs EVERY container as the
        # caller, so no `caches:` entry in any profile could ever be written into.
        #
        # SO THE TOOLS GO INTO THE BIND MOUNT, the one directory in the container the caller provably
        # owns, through a `deps` command of its own - the two-command shape si#121 named, with the
        # volume replaced by the mount. `unit` and `analyse` then reach the tools with `python -m`,
        # which needs no PATH: a `--user` install puts its scripts somewhere pip itself warns is not on
        # one.
        #
        # AND `python -m` IS NOT ONLY THE PATH DODGE, which is the measurement that settles the choice.
        # `python -m` prepends the CWD to `sys.path`; a console script does not. On the same tree, with
        # the user base's `bin` put on PATH so the console script is reachable, `pytest -q` is
        # `ModuleNotFoundError: No module named 'pydemo'` and rc 2 where `python -m pytest -q` is
        # `2 passed` and rc 0 - because the product is a source tree that was never installed, which is
        # what a product tree in a container IS. (rc 2, not 1: collection error. Same rule as ctest's 8
        # and `dotnet format`'s 2 above - compare to 0, never to 1.)
        #
        # DRIVEN ON 2026-09-10 AS A NON-ROOT CALLER (`--user 1000:1000` over a tree owned by 1000),
        # because running it as root would have hidden every permission question in it:
        #
        #   deps     6.0s cold, 0.9s warm, user base left owned by 1000:1000, no root-owned droppings
        #   unit     `2 passed` rc 0; `1 failed, 1 passed` rc 1 with the assertion broken
        #   analyse  `Success: no issues found in 3 source files` rc 0; rc 1 with
        #            `Incompatible return value type (got "int", expected "str")  [return-value]`
        #
        # Three further measurements, so the next reader does not re-derive them:
        #
        #   * `unit` and `analyse` need NO NETWORK once `deps` has run - both green under
        #     `--network none`. `deps` needs one, and being a separate command is how the other two
        #     avoid paying for it on every run.
        #   * THE LEADING DOT IN THE USER BASE IS LOAD-BEARING. mypy reports `3 source files` and pytest
        #     collects 2 over a tree whose user base holds thousands of `.py`, because both skip
        #     dot-directories by default. Named without it, every run would analyse site-packages.
        #   * `--no-cache-dir` buys a CLEAN TRANSCRIPT, not behaviour: without it the same run answers
        #     `WARNING: The directory '/.cache/pip' ... is not writable by the current user. The cache
        #     has been disabled.` - a `--user`-mapped container has no writable HOME either way.
        #
        # WHAT IT COSTS THE TREE, measured rather than waved at: the user base is 80 MB, and it lands
        # beside `.mypy_cache` and `.pytest_cache`, which a containerised run would have produced
        # anyway. `simplon init` scaffolds no `.gitignore` at all, so there is no kernel-owned file to
        # add them to and this is the product's line to write - named here so it is a known cost rather
        # than a surprise in somebody's first commit.
        #
        # THE PINS ARE THE POINT OF `deps`, for `docker.pinned_image`'s own reason one level in: a build
        # whose output depends on when it ran is not a build, and unpinned the first install on a fresh
        # tree takes whatever was newest that day. What the pins do NOT buy was measured too - an
        # unpinned WARM install is offline as well, because pip short-circuits on "already satisfied"
        # without querying the index.
        #
        # `analyse` EXCLUDES THE ORCHESTRATOR, and that is the one thing the docker runs above could not
        # have found - it took driving a real `simplon init` product. `mypy .` over a scaffolded pydemo
        # is rc 1 with FIVE errors and every one of them in the kernel's own scaffold:
        # `deploy/provision/orchestrator/.../cli.py: Cannot find implementation or library stub for
        # module named "simplon"` (and `typer`, and `simplon.environments`). Not one was about the
        # product. The orchestrator is HOST-venv Python by construction - its `requirements.txt`
        # installs the kernel into `.venv`, and `test:typecheck-python` is the command that checks it,
        # in the environment where its imports exist. A container that has neither can only produce
        # import-not-found noise about it, so the two commands' jobs are disjoint and the flag is what
        # says so. Measured with it: `Success: no issues found in 3 source files`, rc 0; with a
        # deliberate type error in the product's own package, rc 1 and one error naming that file.
        #
        # The path is `simplon.bootstrap.DEFAULT_ORCH_DIR`, declared twice on purpose and held together
        # by `test_the_python_analyse_excludes_the_directory_the_scaffolder_writes`: an import would
        # give this table behaviour, which is the one thing the module head promises it does not have. A
        # product that moved it with `--orch-dir`, or that states its roots in a `mypy.ini` the way the
        # kernel does for itself, edits the scaffolded line - which is what scaffolding is for.
        #
        # AND THE PRODUCT'S OWN DEPENDENCIES NEED NO MANIFEST EDIT. `toolchain:run`'s variadic `extra`
        # appends, so `build deps -r requirements.txt` installs them beside the two tools; measured, and
        # `python -c "import yaml, pytest, mypy"` then answers in the same container. Pinning it into
        # the manifest instead is a one-line diff the product owns, which is what the scaffold is for -
        # and it is deliberately not the default, because a starting point that dies on a file a fresh
        # product does not have is si#105's defect wearing a new hat.
        #
        # AND `unit` AND `analyse` NAME THEIR NETWORK: NONE (si#202). si#121 had already measured that
        # both are green under `--network none` and treated it as a nice-to-have; si#197 measured what
        # the default costs and it is not one. An acceptance container started with no `network:` did not
        # fail to reach its target - the service name resolved through the HOST's upstream resolver to
        # 185.199.109.153 (GitHub Pages), which answered 404, so the scenario reported a defect in a
        # product it had never touched. A 404 made it a false red; a 200 would have made it a false
        # green. A container that is not supposed to reach anything and is not TOLD so is one DNS answer
        # away from ruling on something else.
        #
        # `deps` keeps the default, because it is the one command that has to reach the index - which is
        # exactly why si#121 made it a command of its own. And a level that has to reach a DEPLOYED
        # product names the network that product is on; the kernel cannot know it, so the profile pins
        # only where it has measured, which is here.
        commands={
            "deps": {"workdir": "/src",
                     "env": {"PYTHONUSERBASE": "/src/.simplon-toolchain"},
                     "argv": ["python", "-m", "pip", "install", "--user", "--no-cache-dir",
                              "--disable-pip-version-check", "--no-warn-script-location",
                              "pytest==9.1.1", "mypy==2.3.1"]},
            "unit": {"workdir": "/src", "network": "none",
                     "env": {"PYTHONUSERBASE": "/src/.simplon-toolchain"},
                     "argv": ["python", "-m", "pytest", "-q"]},
            "analyse": {"workdir": "/src", "network": "none",
                        "env": {"PYTHONUSERBASE": "/src/.simplon-toolchain"},
                        "argv": ["python", "-m", "mypy",
                                 "--exclude", "^deploy/provision/orchestrator/", "."]},
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
