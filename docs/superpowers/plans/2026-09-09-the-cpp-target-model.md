# The C++ target model - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A C++ product can say what each of its targets IS - an application, a shared library or a
static one - can nest directories under `src/`, can put a unit test beside the unit it tests without
shipping it inside the library, and gets a build that carries debug symbols.

**Tickets:** si#131 (nested directories, target kind, exported includes), si#134 (a co-located unit test
is not part of the library, and `tests/` tells its two levels apart), si#132 (a build type).

**Spec:** `docs/superpowers/specs/2026-09-09-the-language-cluster-design.md`, sections 3, 6 and 7. The
tree-as-declaration rule it does not renegotiate is
`docs/superpowers/specs/2026-09-09-generating-build-files-design.md`, section 2.

**Architecture:** unchanged from si#102 and deliberately so. `read_tree` reads the tree once into a
typed model, the renderers turn that model into text and touch no filesystem, and the two task
functions write it. Everything below is a change to what the model CARRIES and what the CMake renderer
EMITS. No new module, no new coordinate, no new manifest section.

**Tech Stack:** Python 3.11+, pytest, mypy. No new dependency.

## Global Constraints

- **No new catalogue coordinate.** Declaring one turns seven counted docs guards red at once (design
  section 7) and belongs to Lane D. If this lane ever wants one, it stops and reports instead.
- **No new top-level manifest section** (design section 2). Target shape extends `build: targets:`,
  which si#102 already established as the manifest's one exception to the tree.
- **The tree is the declaration, the manifest is the exception.** Every rule below defaults from the
  tree; the manifest names only what a directory cannot show.
- **Generated files are COMMITTED**, so the output stays deterministic: everything sorted, no
  filesystem in a renderer, one trailing newline.
- **The build type is NEVER written into a generated file.** A checked-in
  `set(CMAKE_BUILD_TYPE ...)` decides it for every consumer of that tree forever (si#132).
- **A string assertion over generated CMake text is not evidence** (design section 6). Every claim this
  lane makes about an artefact is proven by building it and reading the file that came out.

**Before Task 1, read** `src/simplon/tasks/buildfiles.py` in full - it is the thing being changed - plus
the `cpp` entry in `src/simplon/tasks/profiles.py` and `tests/test_buildfiles_e2e.py`.

---

## The decisions this plan takes, before any code

si#131 and si#134 are one decision (design section 3), so they are taken together here rather than
discovered task by task.

### D1. A nested directory FOLDS INTO the target above it; it is not its own target

`src/net/tcp/` is not a target. Its sources belong to `net`, at any depth.

Three reasons, in the order they decided it:

1. **It invents no naming rule, which is what si#102 refused to do by accident.** Making a nested
   directory a target needs an answer to "what is it called", and every answer is a new rule: `tcp`
   collides with `src/util/tcp` in a flat namespace that `_unique`, `_overridden`, `depends:`,
   `add_subdirectory` and the `.csproj` GUID derivation all key on; `net_tcp` and `net.tcp` are
   inventions this design has no reason to prefer between. Folding needs no name at all.
2. **The .NET half already works this way and cannot be made to work the other way.** An SDK-style
   `.csproj` globs `**/*.cs` beneath itself - the generator emits no `<Compile>` items - so a directory
   under a project directory is ALREADY part of that project, whatever the model says. One target per
   `src/<name>/` with recursive sources is the rule that makes both halves read the same tree.
3. **The rejected default is unreachable; this one is not.** A product that wants `src/net/tcp` to be
   its own library writes `src/tcp/` and says so. Under "nested is a target" a product that wants
   folding has no way to ask for it at all.

**The consequence, and it is refused rather than discovered.** A `main.cpp` below a target's root -
`src/net/tools/main.cpp` - would be folded into the library, and a static archive carrying a stray
`main` is silent: the linker pulls an archive member only to resolve an undefined symbol, and `main` is
already defined by whoever links it, so nothing ever says a word. That is the same defect class as
si#134 one directory over, so it is refused by name with the fix in the message.

**No manifest override promotes a nested directory.** si#131 asks for one; it is not built, because the
key it would need (`targets: { "net/tcp": ... }`) names something the model has no name for, and the
product can already say the same thing by moving the directory. This is stated as a decision, not an
omission: the trigger that reopens it is a product that cannot move the directory.

### D2. A target's KIND is `static`, `shared`, `executable` or `test`

The tree derives it: a `main.cpp`/`Program.cs` at the target root makes an executable, otherwise a
static library. The manifest overrides it per target with `kind:`, which is the shape the design's
section 2 blesses.

`add_library(<name> STATIC ...)` and `add_library(<name> SHARED ...)` are written EXPLICITLY. A bare
`add_library` follows `BUILD_SHARED_LIBS`, which nobody sets, which is why every library is static
today and why no product can have both (si#131).

`kind:` on a test target is refused: where a test sits is what makes it a test, and a manifest turning
one into a library would silently drop its `add_test`.

**Windows is named, not solved.** A `SHARED` target here gets no `-fvisibility=hidden`, no
`__declspec(dllexport)` and no generated export header, so it links on Linux and does not link on
Windows. The kernel ships no Windows toolchain, and the design's section 8 already says this is the
boundary rather than an oversight.

**`kind: shared` says nothing to the .NET half**, where a class library is a class library. It renders
the same `.csproj` as `static` and that is correct rather than a gap.

### D3. A library EXPORTS its own directory; an executable and a test keep their includes private

One sentence, one rule:

- a library target gets `target_include_directories(<name> PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}" ...)`,
  so anything that links it finds the headers that sit beside its sources;
- an executable or a test gets `PRIVATE`, because nothing links them and `PUBLIC` there is noise.

The manifest's `include:` paths ride the same visibility, so a product states a path once and its
consumers inherit it exactly when inheriting means something.

**How far the export goes: usable WITHIN the generated project, and no further.** No
`install(TARGETS ... EXPORT ...)`, no generated package config, no `find_package`. The design's section
8 leaves this to this plan, so: an export set with no importer is code written for a consumer that does
not exist, and the consumer that will exist is si#128's registry, in a lane that is not this one.

The consequence is named rather than left to be found: because the exported path is a bare source-tree
directory and not `$<BUILD_INTERFACE:...>`, `install(TARGETS)` will refuse this target the day somebody
adds it - "INTERFACE_INCLUDE_DIRECTORIES property contains path ... which is prefixed in the source
directory". Wrapping it now would cost nothing and buy nothing inside the project, so it is left, and
si#128 is the ticket that wraps it.

### D4. The location names the level, and the level is a ctest label

| where the file sits | level |
|---|---|
| `src/<target>/**/<name>_test.<ext>` | `unit` |
| `tests/system/...` | `system` |
| `tests/acceptance/...` | `acceptance` |
| `tests/<name>_test.<ext>`, `tests/<dir>/` | none - the shape si#102 shipped, kept |

A level reaches the build as `set_tests_properties(<name> PROPERTIES LABELS "<level>")`, so
`ctest -L unit` really selects the unit tests. That is what makes the level a fact about the build
rather than a fact about a path, and it is what si#133 will read.

**`_test` stays the recognition rule, and `test_` is deliberately NOT added.** Two spellings would mean
`test_helpers.cpp` - a helper every C++ project has - becomes a test target with no `main`. One
spelling, on the docs page as well as in the constant.

**A `tests/` directory that is not a level directory keeps its meaning.** `tests/Calculator.Tests/` is
still one target: that is the .NET test-project shape, and a level directory may hold one too
(`tests/system/Foo.Tests/`), so the rule is uniform rather than C++-only.

**A `_test` file directly in `tests/` is level-less and stays legal.** It is the shape si#102 shipped
and cppdemo runs; refusing it now would break a product to make a rule tidy.

### D5. A co-located unit test is not expressible in .NET, and the generator says so

The C++ answer is clean: the test file is lifted out of the library's source list into its own
executable, in the same directory, linking the library beside it - and it needs no `depends:` and no
`include:` entry, because the tree already shows both.

The .NET answer is that there is no answer. A second `.csproj` in the library's own directory is not a
shape MSBuild has, and the SDK's `**/*.cs` glob would compile the test into the library regardless of
what the model says - which means the si#134 defect is not fixable there by generating anything. So
`build:dotnet-solution` REFUSES a co-located `_test` source and names the move that fixes it. Saying
that plainly is what the design's section 8 asks for; generating something that builds and is wrong is
what it forbids.

### D6. The build type is a word in the argv the profile writes into the product's manifest

si#132 offers "a manifest key under `build:`, an argument on `build configure`, or both". It is neither
of the first two exactly, and the reason is that `support:toolchain` already solved it: the profile is
scaffolded INTO the product's manifest and from that moment the product owns what it runs. So
`cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo` in the `cpp` profile's `configure` IS the
manifest key - a line a reviewer reads, a one-word diff to change - and it needs no new word anywhere.

- **The default is `RelWithDebInfo`.** `Debug` gives symbols and no optimisation; `Release` gives
  optimisation and, with a single-config generator and no explicit `-g`, nothing to read a stack trace
  with. A CI build is the run whose artefact ships AND whose failure has to be explicable, and
  `RelWithDebInfo` is the only one of the three that is both.
- **A caller can still override it, and that is measured rather than assumed**: si#105 gave
  `toolchain:run` a variadic tail with `passthrough_args: true`, and
  `cmake ... -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_BUILD_TYPE=Debug` leaves
  `CMAKE_BUILD_TYPE:STRING=Debug` in the cache - measured in `silkeh/clang:19` on 2026-09-09.
- **`compile` needs no change and the two commands cannot disagree.** `CMAKE_BUILD_TYPE` is a
  single-config generator's knob and `silkeh/clang:19` produces Unix Makefiles, so the type is fixed at
  configure time and `cmake --build build -j` carries no `--config`. Ninja Multi-Config and the Visual
  Studio generators IGNORE `CMAKE_BUILD_TYPE` and take `--config` on the build step instead; the kernel
  ships neither, and this is named here so it is a known boundary rather than a green run with the
  wrong artefact.
- **The `dotnet` profile is deliberately NOT changed.** si#132 is a C++ ticket - `dotnet build` already
  defaults to a configuration that emits a PDB - and naming one explicitly would move every artefact
  path on a chapter this lane does not own. Named as a non-change, not skipped.

### D7. What proves each of these, and it is never a string

Design section 6, made concrete. All four run inside `silkeh/clang:19`, over a tree this repository's
own generator wrote:

| claim | the evidence |
|---|---|
| a `SHARED` target is a shared object | `file build/src/plugin/libplugin.so` says `ELF ... shared object` |
| a `STATIC` target is an archive | `file build/src/calculator/libcalculator.a` says `current ar archive` |
| includes are exported | `e2edemo` declares `depends:` and NO `include:`, links two libraries, and compiles |
| the build carries debug symbols | `file` on the binary says `with debug_info` - NOT `not stripped`, which is true of a build with no debug info at all (measured) |
| the library does not carry the unit test | `nm build/src/calculator/libcalculator.a` shows neither `T main` nor the test's own symbol |
| a level really selects | `ctest -L unit` reports `1 test`, and the label summary is read - `ctest -L nosuchlabel` exits **0** saying `No tests were found!!!` (measured), so an rc alone proves nothing |

---

### Task 1: the drive that goes red first

**Files:** `tests/test_buildfiles_e2e.py`

This task writes NO implementation. It extends the container drive to the tree the rest of the plan is
about and records what the CURRENT generator does with it, because those transcripts are the evidence
that the checks can fail.

- [ ] **Step 1: grow the C++ product in `CPP_SOURCES`**

Add to the existing tree, keeping it as small as the claim allows:

```
src/calculator/calculator.h          the library's header, beside its sources
src/calculator/calculator.cpp
src/calculator/detail/mul.cpp        NESTED - folds into `calculator` (D1)
src/calculator/calculator_test.cpp   CO-LOCATED unit test (D5), defines a marker symbol and a main
src/plugin/plugin.h                  a second library, declared `kind: shared` (D2)
src/plugin/plugin.cpp
src/e2edemo/main.cpp                 links both libraries and repeats NO include path (D3)
tests/system/smoke_test.cpp          a system-level test (D4)
tests/calculator_test.cpp            REMOVED - the unit test now sits beside its unit
```

`CPP_TARGETS` becomes the whole of what the tree cannot say, and its shortness is the assertion:

```yaml
plugin:     { kind: shared }
e2edemo:    { depends: [calculator, plugin] }
smoke_test: { depends: [calculator] }
```

No `include:` anywhere. If the export works, nothing needs one.

- [ ] **Step 2: extend the drive with the artefact-level assertions**

In `test_the_generated_cmake_tree_configures_compiles_tests_and_runs`, after the four steps, add a
fifth `_in_image` call that runs `file` and `nm` over the produced tree and assert on ITS output:
`shared object` for the `.so`, `current ar archive` for the `.a`, `with debug_info` on the executable,
and the absence of the test's marker symbol and of `T main` from the archive. Add `ctest -L unit` and
`ctest -L system` runs and assert on the label summary rather than on the exit code.

- [ ] **Step 3: run it and record the red**

```bash
cd tests && ../deploy/orchestrator/.venv/bin/python -m pytest -q test_buildfiles_e2e.py
```

**Verify:** it fails, and the failure names a real defect rather than a typo. Expected, in order: the
nested `mul.cpp` is not compiled by anything, so the link fails on an undefined symbol (si#131.1). Note
each red in the commit message - this is the "seen it fail" half of the proof standard, and the plan is
not done until every one of them has been observed once.

---

### Task 2: the model reads a nested tree, and lifts the unit tests out of it

**Files:** `src/simplon/tasks/buildfiles.py`, `tests/test_buildfiles_tree.py`

**Interfaces produced:** `Target` gains `level: str | None`; `kind` becomes
`"static" | "shared" | "executable" | "test"`; `read_tree` unchanged in signature.

- [ ] **Step 1: write the failing tests** in `tests/test_buildfiles_tree.py` (AAA, target-named):

  - a nested directory's sources belong to the target above it, and no target is named after it
  - a target root with no `main` is `static`; one with `main.cpp` is `executable`
  - a `main.cpp` BELOW the target root is refused, naming the file and the move that fixes it
  - `src/<t>/<n>_test.cpp` is a target of kind `test` and level `unit`, and is NOT in `<t>`'s sources
  - that test target's `depends` carries `<t>` without the manifest saying so
  - a `src/<t>/` holding only tests produces the tests and no library, and the tests depend on nothing
  - `tests/system/x_test.cpp` is level `system`; `tests/acceptance/y_test.cpp` is level `acceptance`
  - `tests/<n>_test.cpp` and `tests/<dir>/` keep today's shape and carry no level

- [ ] **Step 2: implement**

`_sources` grows a recursive variant for a target's own tree; `_library_targets` splits the recursive
listing into the target's sources and its co-located tests; `_test_targets` learns the two level
directories. `SOURCE_SUFFIXES`, `MAIN_FILES` and `TEST_SUFFIX` stay where they are.

- [ ] **Step 3: verify**

```bash
cd tests && ../deploy/orchestrator/.venv/bin/python -m pytest -q test_buildfiles_tree.py
```

**Verify:** green, and the docstrings say WHY (D1, D4, D5) rather than what.

---

### Task 3: the manifest says what the tree cannot - `kind:`

**Files:** `src/simplon/tasks/buildfiles.py`, `tests/test_buildfiles_tree.py`

- [ ] **Step 1: write the failing tests**

  - `targets: { plugin: { kind: shared } }` makes the model's kind `shared`
  - a `kind:` that is not one of the three is refused by name, listing the three
  - `kind:` on a test target is refused, saying that the location decides
  - a manifest `depends:` on a co-located test ADDS to the derived link rather than replacing it
  - a target whose manifest block carries no `depends:` keeps the one the tree derived

- [ ] **Step 2: implement** in `_overridden`: read `kind` through a small validator beside `_names`,
  and merge `depends` instead of overwriting it.

- [ ] **Step 3: verify** the tree suite is green.

---

### Task 4: the CMake renderer emits the kind, the export and the label

**Files:** `src/simplon/tasks/buildfiles.py`, `tests/test_buildfiles_cmake.py`

- [ ] **Step 1: write the failing tests**

  - a static library renders `add_library(core STATIC a.cpp b.cpp)`
  - a shared library renders `add_library(plugin SHARED plugin.cpp)`
  - a library renders `target_include_directories(<n> PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")`, with the
    manifest's paths after it on the same line
  - an executable and a test keep `PRIVATE`, and emit no line at all with no `include:`
  - a levelled test renders `set_tests_properties(<n> PROPERTIES LABELS "unit")`; a level-less one
    renders no such line
  - a folded source renders relative to the target root (`detail/mul.cpp`)

The existing string assertions that name `add_library(core ...)` and `PRIVATE` on a library move with
the rule rather than being deleted.

- [ ] **Step 2: implement** in `_render_target`.

- [ ] **Step 3: verify**

```bash
cd tests && ../deploy/orchestrator/.venv/bin/python -m pytest -q test_buildfiles_cmake.py test_buildfiles_write.py
```

---

### Task 5: the .NET half refuses what it cannot express

**Files:** `src/simplon/tasks/buildfiles.py`, `tests/test_buildfiles_dotnet.py`

- [ ] **Step 1: write the failing test** - `dotnet_files` over a model holding a co-located unit test
  refuses, names the file, and names the move (`tests/<Name>.Tests/`). And the existing .NET assertions
  stay green: `static` and `shared` both render a class library.

- [ ] **Step 2: implement** the refusal beside `_referenced`, which is the same shape and the same seam.

- [ ] **Step 3: verify** the .NET suite is green.

---

### Task 6: the build type (si#132)

**Files:** `src/simplon/tasks/profiles.py`, `tests/test_profiles.py`,
`tests/fixtures/case_cpp_manifest.yaml`

- [ ] **Step 1: write the failing test** in `tests/test_profiles.py`: the `cpp` profile's `configure`
  argv names `-DCMAKE_BUILD_TYPE=`, and the value is one of the three CMake types that carry `-g`.

- [ ] **Step 2: implement** - the argv, plus the comment block that records D6's four measurements.

- [ ] **Step 3: keep the chapter's fixture in step.** `case_cpp_manifest.yaml` is compared with the
  profile entry by entry by `test_case_cpp_chapter.py`, so its `configure` argv changes with it.

- [ ] **Step 4: verify**

```bash
cd tests && ../deploy/orchestrator/.venv/bin/python -m pytest -q test_profiles.py test_case_cpp_chapter.py
```

---

### Task 7: the drive goes green, and every check has been seen red

**Files:** `tests/test_buildfiles_e2e.py`

- [ ] **Step 1: run the drive**

```bash
cd tests && ../deploy/orchestrator/.venv/bin/python -m pytest -q test_buildfiles_e2e.py
```

- [ ] **Step 2: prove the debug-symbol check can fail**, which nothing above does: drop the
  `-DCMAKE_BUILD_TYPE=` from the profile in the working tree, re-run, confirm the `with debug_info`
  assertion is the one that goes red, and put it back. Record the transcript.

- [ ] **Step 3: prove the archive check can fail** the same way, against the pre-fix generator. This is
  Task 1's red, re-read: without it the assertion is a check that cannot fail, which is this
  repository's own recurring defect.

**Verify:** every row of D7's table has been seen both red and green.

---

### Task 8: the whole suite, the type gate, and the chapter

**Files:** `site/content/using/case-cpp.md`, plus whatever the counted guards name

- [ ] **Step 1:**

```bash
./simplon.sh test all
./simplon.sh test typecheck-python
```

against the baseline measured on `origin/main` before this branch existed. No new failure, and every
counted guard satisfied rather than weakened.

- [ ] **Step 2: update `case-cpp.md`** - the profile's `configure` row, and one "Since this walk"
  callout in the shape the chapter already uses for si#105, si#111 and si#102, carrying: the folding
  rule, the three kinds, the export, the co-located unit test and the level directories, the build
  type, and the two things that are named rather than solved (Windows visibility, and the .NET
  co-location refusal). The honesty table's rows are cppdemo's driven walk and do not grow: the ratio
  sentence is computed from that table and adding an undriven row would make the page claim a run.

- [ ] **Step 3: dispatch `python-reviewer`** on the diff, and act on what it finds.
