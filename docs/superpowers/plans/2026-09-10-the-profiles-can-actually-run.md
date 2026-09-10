# The profiles can actually run - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every command in `simplon.tasks.profiles.PROFILES` runs in the image the profile pins, and
every `analyse` in there can go red. Two entries are wrong today in two different ways: `python` names an
image carrying neither of its tools, so both commands exit 127 before the product is looked at; `java`
names a `compile` that runs the tests, so a broken assertion arrives as a broken BUILD.

**Tickets:** [si#121](https://github.com/marcozwyssig/simplon/issues/121) (python),
[si#122](https://github.com/marcozwyssig/simplon/issues/122) (java).

**Tech Stack:** Python 3.11+, pytest, mypy. No new dependency, **no new catalogue coordinate** - both
fixes are edits to one table plus the tests and pages that read it.

## The standard this plan is held to

si#111's, restated because it is the whole reason these two are tickets rather than typos: **an argv that
nobody ran is not a profile entry.** 0.8.0 shipped a uniform build no product could drive because every
test behind it stubbed the runner, and si#102's first container drive found `net8.0` builds in a 9.0 SDK
image within minutes. So each argv below was executed in the profile's own pinned image over a real tree,
and each `analyse`-shaped command was ALSO driven over a deliberately broken tree, because a check that
exits 0 over a defect is worse than no check - a gate naming it is green forever, which is exactly what
si#111 measured for `clang-tidy` without `-warnings-as-errors=*`.

Every transcript below is from this machine, 2026-09-10, via
`docker run --rm --user <uid>:<gid> -v <tree>:<workdir> -w <workdir> <image> <argv>` - the line
`simplon.tasks.toolchain.docker_argv` assembles, typed out by hand so the measurement is of the argv and
not of the kernel.

## si#122, part one: `compile` runs the tests, and `assemble` is not the fix either

The ticket's finding reproduces exactly. `gradle:jdk25` (Gradle 9.7.1), one class, two JUnit 5 cases,
`Calculator.mul` returning `a + b`:

```text
$ ... gradle:jdk25 gradle build --no-daemon --console=plain
CalculatorTest > multiplies() FAILED
    org.opentest4j.AssertionFailedError at CalculatorTest.java:8
2 tests completed, 1 failed
BUILD FAILED in 4s
rc 1
```

The ticket then proposes `gradle assemble` or `gradle build -x test`, and **both are wrong for a second
reason the ticket did not look for.** On a tree whose TEST SOURCE does not compile:

```text
$ ... gradle:jdk25 gradle clean assemble --no-daemon --console=plain
> Task :compileJava
> Task :classes
> Task :jar
> Task :assemble
BUILD SUCCESSFUL in 2s
rc 0
```

`assemble` never runs `compileTestJava`, so a test that does not compile is GREEN there and red at the
`unit` gate - the same wrong verdict as today, pointing the other way. `gradle build -x test` produces
the identical task list plus an empty `:check`: Gradle's `-x` drops the excluded task's exclusive
dependencies too, and `compileTestJava` is one.

`gradle assemble testClasses` is the pair that means what the two commands are called. Same broken test
source:

```text
> Task :compileTestJava FAILED
  /work/src/test/java/demo/BrokenTest.java:6: error: incompatible types: String cannot be converted to int
BUILD FAILED in 3s
rc 1
```

and on the tree whose ASSERTION is broken, compile GREEN and unit RED:

```text
$ ... gradle clean assemble testClasses ...   -> BUILD SUCCESSFUL in 4s, rc 0
$ ... gradle test ...                          -> Execution failed for task ':test'.
                                                  > There were failing tests. rc 1
```

**So yes, the two really can be separated**, and the answer is neither of the two the ticket named.

## si#122, part two: java gets no `analyse`, and the measurement is why

The ticket's claim is that Java's checkers are Gradle plugins the product's own `build.gradle` applies.
Tested rather than repeated, on a file carrying a raw type, an unused import, a dead store and a
guaranteed `NullPointerException`:

```text
$ ... gradle check --dry-run --no-daemon --console=plain
:compileJava SKIPPED  :classes SKIPPED  :compileTestJava SKIPPED  :testClasses SKIPPED
:test SKIPPED  :check SKIPPED
```

`check` on a stock `java` plugin IS `test`, so it is the `unit` command under another name - and it is
rc 0 over that file, because nothing in it reads Java. The obvious repair is worse:

```text
$ ... gradle clean check -x test --no-daemon --console=plain
> Task :clean
> Task :check
BUILD SUCCESSFUL in 2s
rc 0
```

`check -x test` does not even COMPILE. One task, no javac, rc 0 over four defects. That is si#111's
clang-tidy shape in its purest form: a command that cannot go red, and a gate naming it green forever.

The one thing in the image that does go red is `javac` itself:

```text
$ ... javac -Xlint:all -Werror -d /tmp/out src/main/java/demo/Sloppy.java
  missing type arguments for generic class ArrayList<E>
warning: [unchecked] unchecked call to add(E) as a member of the raw type List
error: warnings found and -Werror specified
1 error / 4 warnings
rc 1
```

and it is not usable: it went red only because the file was NAMED on the command line, and the kernel
knows neither the product's source layout nor its test classpath - the two things Gradle exists to know.
It also said nothing about the certain NPE.

**Decision: the java profile carries no `analyse`, and a test pins the absence with this measurement in
it.** A missing command with a reason beats a command that cannot fail.

## si#121: the python image, the decision, and its cost

Reproduced first, both halves, rc 127 before the tree is read:

```text
$ ... python:3.12 pytest -q
docker: ... exec: "pytest": executable file not found in $PATH: unknown.   rc 127
$ ... python:3.12 mypy .
docker: ... exec: "mypy": executable file not found in $PATH: unknown.     rc 127
```

**The image stays `python:{version}`.** The three alternatives were weighed against one constraint the
ticket names and the others miss: mypy over a product whose dependencies are not importable reports
missing stubs, not type errors - which is exactly why `typecheck.py` runs the kernel's own mypy in the
host venv rather than in a container. **No prebuilt image can carry a product's wheels**, so every
"fatter image" answer solves the 127 and leaves `analyse` wrong.

* **a third-party image carrying pytest and mypy** - there is no official one, so it means pinning
  somebody else's supply chain into the kernel's own table for two wheels that `pip` installs in six
  seconds, and it still does not carry the product's dependencies;
* **a product-built image** - the profile's whole promise is a starting point that runs before the
  product has built anything;
* **a named `caches:` volume** - already measured dead in this repository. `case-java.md`: a named docker
  volume is created ROOT-owned, `--user <uid>:<gid>` cannot write into it, and the failure names no
  permission anywhere. `toolchain:run` runs every container as the caller, so no `caches:` entry in any
  profile could work.

**So the tools are installed, into the bind mount, by a command of their own.** `deps` installs pytest
and mypy into a `PYTHONUSERBASE` inside the product tree - the one directory in the container the caller
provably owns - and `unit`/`analyse` invoke them with `python -m`, which needs no PATH.

Driven as a NON-ROOT caller (`--user 1000:1000`, tree owned by 1000), because root would have hidden
every permission question:

```text
$ ... -e PYTHONUSERBASE=/src/.simplon-toolchain python:3.12 \
      python -m pip install --user --no-cache-dir --disable-pip-version-check \
                            --no-warn-script-location pytest==9.1.1 mypy==2.3.1
Successfully installed ... mypy-2.3.1 ... pytest-9.1.1 ...
rc 0        real 0m6.0s        # cold
rc 0        real 0m0.9s        # warm, everything already satisfied

$ ls -ld /tmp/wt-121-lab/pydemo/.simplon-toolchain
drwxr-xr-x 4 1000 1000 ...                        # no root-owned droppings

$ ... python -m pytest -q     ->  2 passed in 0.00s                      rc 0
$ ... python -m mypy .        ->  Success: no issues found in 3 source files   rc 0
```

Red, each for its own reason:

```text
$ ... python -m pytest -q          # mul returns a + b
FAILED tests/test_calculator.py::test_multiplies - assert 5 == 6
1 failed, 1 passed in 0.01s        rc 1

$ ... python -m mypy .             # a str-returning function returns an int
pydemo/broken.py:6: error: Incompatible return value type (got "int", expected "str")  [return-value]
Found 1 error in 1 file (checked 4 source files)                          rc 1
```

Four further measurements that decide details of the entry:

* **`unit` and `analyse` need no network.** Both green with `--network none` once `deps` has run. `deps`
  needs one, and that is the cost: it is a separate command precisely so the other two do not pay it.
* **mypy and pytest do not walk `.simplon-toolchain`.** mypy reports `3 source files` over a tree whose
  user base holds thousands of `.py`, and pytest collects 2. Both skip dot-directories by default, which
  is why the name starts with a dot rather than reading `simplon-toolchain`.
* **`--no-cache-dir` buys a clean transcript, not behaviour.** Without it the same run answers
  `WARNING: The directory '/.cache/pip' ... is not writable by the current user. The cache has been
  disabled.` - a `--user`-mapped container has no writable HOME either way.
* **the caller's tail reaches pip.** `toolchain:run`'s variadic `extra` appends, so
  `build deps -r requirements.txt` installs the product's own dependencies beside the two tools, and
  `python -c "import yaml, pytest, mypy"` then answers `6.0.3` in the same container. That is what makes
  `analyse` mean something for a product with dependencies, and it needs no manifest edit at all.

**The tool versions are pinned** (`pytest==9.1.1`, `mypy==2.3.1`) for `pinned_image`'s own reason one
level in: unpinned, the first install on a fresh tree picks whatever is newest that day, and a build
whose output depends on when it ran is not a build. What pinning does NOT buy was measured too - an
unpinned warm install is offline as well, because pip short-circuits on "already satisfied" without
querying the index. The pins are the product's to bump, in its own manifest, like everything else the
scaffolder writes.

## Tasks

### Task 1: the plan lands first

- [ ] Commit this file, so the measurements above exist in the history before any code moves.

### Task 2: java `compile` compiles and nothing else

- [ ] RED: extend `tests/test_profiles.py` with a test asserting the java `compile` argv does not run
      the tests - it names `assemble` and `testClasses` and does not name `build`. It fails against the
      current table.
- [ ] GREEN: change `PROFILES["java"]["compile"]` to
      `["gradle", "assemble", "testClasses", "--no-daemon", "--console=plain"]`.
- [ ] Rewrite the java entry's comment with the four transcripts above: `build` red on an assertion,
      `assemble` green on a test source that does not compile, `-x test` identical to `assemble`, and
      the pair that works.
- [ ] Verify: `./simplon.sh test all` and the four docker runs re-driven.

### Task 3: java's missing `analyse` becomes a decision the table states

- [ ] RED: add a test asserting `PROFILES["java"]` carries no `analyse`, whose failure message is the
      `check -x test` measurement. (It passes immediately - it is a pin on a decision, not a repair, and
      it goes red the day somebody adds `gradle check`.)
- [ ] Write the measurement into the java comment.
- [ ] Verify: `./simplon.sh test all`.

### Task 4: the python profile runs

- [ ] RED: extend `tests/test_profiles.py` - the python commands are `deps`, `unit`, `analyse`; each
      names its tool through `python -m`; each pins `PYTHONUSERBASE` under the workdir; `deps` pins both
      tool versions with `==`. Fails against the current table.
- [ ] GREEN: rewrite `PROFILES["python"]`.
- [ ] Add a round-trip test putting every python body through `toolchain.declared()`. `env:` is a key no
      profile has ever carried, and `declared()` is what has to accept it - this is the "KNOWN gap" the
      `test_profiles.py` docstring names, closed exactly as far as the new key reaches.
- [ ] Update `test_the_other_three_languages_carry_their_own_toolchain`, which asserts
      `python.commands["analyse"]["argv"][0] == "mypy"`.
- [ ] Write the whole decision into the python entry's comment: why the image stays, the three
      alternatives and their costs, the four measurements.
- [ ] Verify: `./simplon.sh test all`, `./simplon.sh test typecheck-python`, and the docker runs
      re-driven green AND red.

### Task 5: drive it through a real product's own CLI

- [ ] `simplon init pydemo` against this working tree, place `support:toolchain`, run
      `support toolchain python 3.12`, and drive `build deps`, `build unit`, `build analyse` - green,
      then red. The docker runs above prove the argv; this proves the SCAFFOLDER writes a manifest that
      assembles and runs, which is the half si#105 found broken by not doing it.
- [ ] Same for java: `support toolchain java 25`, `build compile` green over a broken assertion,
      `build unit` red.

### Task 6: the pages, and the labels they are held to

- [ ] `site/content/using/case-python.md`: a section for the containerised python toolchain, with the
      transcripts, and table rows labelled `run` ONLY where a command was really driven on that product.
- [ ] `site/content/using/case-java.md`: the same for `build compile` / `build unit`, plus the sentence
      that the java profile carries no `analyse` and why.
- [ ] `tests/fixtures/case_*_manifest.yaml`: no change is expected (neither the java nor the python
      chapter's product drives the profile today), but the case-chapter suites compare fixture to
      profile entry by entry - re-run them and fix whatever they name.
- [ ] `site/content/using/releases.md`: name si#121 and si#122 in the 0.10.0 section. si#89's gate turns
      `main` red for a merged ticket nobody wrote down.

### Task 7: review

- [ ] Dispatch `python-reviewer` on the diff and act on what it finds.
- [ ] `./simplon.sh test all` + `./simplon.sh test typecheck-python` against the recorded baseline
      (3 failed / 2731 passed / 3 skipped and mypy clean over 84 files on `origin/main`, on this box;
      the three failures are `test_tasks_docs.py`'s and are a root-user artefact, not this branch's).
