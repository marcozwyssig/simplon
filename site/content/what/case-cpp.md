---
title: "A C++ product, end to end"
weight: 7
---

The [Python chapter](../case-python/) walks one delivery loop with the kernel's own language underneath
it. The [Java chapter](../case-java/) walks the same loop with no Python in the product at all - and its
product still writes a build body of its own, a Python function ending in a `docker run`, because when it
was written there was nothing else to write.

This one is the same loop again with **no task body at all**. cppdemo's manifest has no `tasks:` block:
every command in it is an instance of a catalogue coordinate, and the four that build the product are the
*same* coordinate, `toolchain:run`, differing only in the argv they hand a pinned `silkeh/clang:19`.

That is the before/after this chapter exists for, and it is worth stating plainly rather than implying
it:

| | what the product writes for its build |
|---|---|
| javademo (Java, si#26) | `impl: "orchestrator.gradle:build"` plus a Python module that assembles a `docker run` |
| cppdemo (C++, this chapter) | an image reference and an argv, four times, in YAML |

**The second half of the chapter is why that is not yet the whole story.** Driving cppdemo was the first
time the si#95 path was walked end to end by a product, and it does not survive the walk: the ready-made
configuration cannot be asked for, the shape it writes does not assemble, and the command it produces
cannot report a verdict. Every one of those has a ticket and a row in the table below. Nothing on this
page is a plan.

The product was scaffolded for this chapter and driven on one machine on 2026-09-09, against the kernel
in this checkout rather than a released wheel. That is not a detail: `simplon init` pinned
`simplon==0.7.1` in the product's own requirements, which is the newest release it knew of and predates
`toolchain:run` entirely, so the first thing a C++ product has to change is the pin. It is about as
small as a C++ product gets:

```text
cppdemo.yaml                           the manifest - and there is no `tasks:` block in it
CMakeLists.txt                         the CMake project, three targets
src/calculator.h  src/calculator.cpp   three functions
src/main.cpp                           what `deploy up` runs
tests/calculator_test.cpp              three ctest cases
orchestrator/src/python/orchestrator/  five .py files - five scaffolded, zero written here
```

**Zero lines of product code outside C++ and YAML.** The five Python files are the scaffold's adapter -
the manifest path, the environment provider, the composition root - and this product added nothing to
them and named none of their placeholder bodies.

## The labels, and why they are on the page

Same rule as the other two cases, for the same reason: a page describing a pipeline nobody has driven is
worse than no page, because the reader concludes they misread the site rather than that the site is
inventing.

{{< callout type="info" >}}
**run** - somebody executed it. The evidence names where and when.

**derived** - read out of a manifest, a task body or the catalogue, and not executed for this page. It is
a statement about what is declared, not about what was observed.

**does not exist yet** - the step is named because leaving it out would make the loop look complete.
Every such row carries the ticket where the decision is still open.
{{< /callout >}}

| # | Step | Command | Label | Evidence |
|---|---|---|---|---|
| 1 | Scaffold the product | `simplon init cppdemo` | run | this checkout, 2026-09-09; five Python files and a CLI that runs before there is anything to run |
| 2 | Ask the kernel for the C++ configuration | `./cppdemo.sh support toolchain cpp` | does not exist yet | rc 1, a traceback: the profile is real and the command cannot carry its one parameter, [simplon#105](https://github.com/marcozwyssig/simplon/issues/105) |
| 3 | Write the profile's four commands into the manifest | `support:toolchain` | run | 2026-09-09 06:35:32, rc 0, four commands written - and what it wrote does not assemble, [simplon#105](https://github.com/marcozwyssig/simplon/issues/105) |
| 4 | Generate the build system, in Docker | `./cppdemo.sh build configure` | run | 2026-09-09 06:41:07, rc 0; transcript below |
| 5 | Compile in the pinned toolchain image | `./cppdemo.sh build compile` | run | 2026-09-09 06:41:07, rc 0; transcript below |
| 6 | Run the ctest suite in the same image | `./cppdemo.sh build unit` | run | 2026-09-09 06:41:08, rc 0, three of three |
| 7 | A failing C++ test arrives red | `./cppdemo.sh build unit` | run | 2026-09-09 06:41:38, rc 8; transcript below |
| 8 | A tree that does not compile reports a full green suite | `./cppdemo.sh build unit` | run | 2026-09-09 06:41:47, compile rc 2 and unit rc 0; table below |
| 9 | Static analysis over the compile database | `./cppdemo.sh build analyse` | run | 2026-09-09, rc 1: the profile's argv named no input file; fixed and re-driven the same day, [simplon#111](https://github.com/marcozwyssig/simplon/issues/111) |
| 10 | Append an argument to the pinned argv | `./cppdemo.sh build analyse src/calculator.cpp` | does not exist yet | rc 2, refused by the command line before docker was asked, [simplon#105](https://github.com/marcozwyssig/simplon/issues/105) |
| 11 | A verdict and an Allure archive for the ctest run | `test:accept` | derived | a gate names a command since [simplon#106](https://github.com/marcozwyssig/simplon/issues/106) and really reaches a `toolchain:run` one since [simplon#136](https://github.com/marcozwyssig/simplon/issues/136), which drove a `ctest` through one green and red; cppdemo declares no `suites:` section, so nothing was run on this product |
| 12 | Refuse a toolchain reference that is not pinned | `./cppdemo.sh build configure` | run | 2026-09-09 06:45:25, rc 1; message below |
| 13 | Cut the release tag | `./cppdemo.sh release tag v0.1.0` | run | 2026-09-09 06:41:28, rc 1; refused, nothing cut |
| 14 | Publish the binary or a container image | `release:artifact`, `release:image` | derived | they read an `artifacts:` and an `images:` section, and cppdemo declares neither |
| 15 | Deploy to the local host | `./cppdemo.sh dev deploy up` | run | 2026-09-09 06:41:18, rc 0; output below |
| 16 | Deploy past the local host - Proxmox, Portainer, a cloud | - | does not exist yet | [simplon#5](https://github.com/marcozwyssig/simplon/issues/5) |
| 17 | Render the documentation | `docs:render`, `docs:site` | derived | neither reads anything C++; the Java chapter drove `docs:render` and cppdemo declares no `site:` section |

Of the 17 steps above, 11 are **run**, 3 are **derived** and 3 **does not exist yet**.

Three open rows is two more than the Java chapter carries, and that is the honest shape of a capability
one week old: the toolchain itself does everything it promises, and the path from "I have a C++ product"
to "I have those commands" is not joined up yet. Row 11 was the fourth until
[simplon#136](https://github.com/marcozwyssig/simplon/issues/136), and how it stopped being one is worth
the sentence: the key it needs had existed since simplon#106 and could not name the kind of command this
product has, because every test behind that key used a Python stub. It is *derived* rather than *run* for
the ordinary reason the other two are - this product declares no `suites:` section, so nobody ran it
here.

## What the kernel carries for C++

`simplon.tasks.profiles` is a table, and that is a design decision rather than an implementation detail:
the kernel learns no CMake and no MSBuild, it learns to run a pinned image over a product tree as the
calling user. What it carries per language is argv and paths, nothing callable. There are four profiles -
`cpp`, `java`, `dotnet` and `python` - and the C++ one carries four commands:

| command | what it runs in `silkeh/clang:19` |
|---|---|
| `configure` | `cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo` |
| `compile` | `cmake --build build -j` |
| `unit` | `ctest --test-dir build --output-on-failure` |
| `analyse` | `run-clang-tidy -p build -quiet -warnings-as-errors=*` |

Those are the four cppdemo runs, unedited. The manifest entry for one of them is the whole of what the
product writes about compiling C++:

```yaml
      compile:
        task: "toolchain:run"
        help: "Compile the product in the containerised toolchain."
        with:
          body:
            image: "silkeh/clang:19"
            workdir: /src
            argv: ["cmake", "--build", "build", "-j"]
          where: "build compile"
          extra: []
```

Compiler and version are manifest data, so moving to clang 20 is a one-line diff in a file a reviewer
reads, not an edit to a script. And the same coordinate is filed under a different group further down,
which is what makes `toolchain:run` a *family* rather than a placement - the binary this product ships is
run by the same task that compiled it:

```yaml
      up:
        task: "toolchain:run"
        help: "Run the compiled binary on this host (si#5: there is no further target)."
        with:
          body:
            image: "silkeh/clang:19"
            workdir: /src
            argv: ["./build/cppdemo"]
          where: "deploy up"
          extra: []
```

### The three things between that table and a running command

The design says a product declares `{ language: cpp, version: "19" }`, runs one command and receives the
four. Driven, that path stops three times, and the shape above is what is left after going around all
three. They are one ticket, [simplon#105](https://github.com/marcozwyssig/simplon/issues/105), because
they are one story.

**The version cannot be asked for.** Every profile's image is a template, and the catalogue declares
exactly one parameter for the scaffolder - the language. `simplon.signatures.bindable` drops `**kwargs`,
so there is no second value to pass and no manifest key that carries one:

```text
$ ./cppdemo.sh support toolchain cpp
KeyError: 'version'
```

Pinning it in the manifest is refused rather than ignored, which is at least loud:
`support toolchain: `with:`/`params:` name parameter(s) the impl does not take: version`.

**The block the scaffolder writes does not assemble.** Called with the version it cannot receive, the
scaffolder does its job and writes four commands in the design's own shape:

```text
      compile:
        task: toolchain:run
        with:
          image: silkeh/clang:19
          workdir: /src
          argv:
          - cmake
          - --build
          - build
          - -j
```

That manifest LOADS. It does not ASSEMBLE, because `toolchain:run`'s body takes `body`, `where`, `extra`
and `network`, and `image`/`workdir`/`argv` are the keys inside the first of those:

```text
build configure: `with:`/`params:` name parameter(s) the impl does not take: argv, image, workdir
```

So the failure arrives at the first command anybody types afterwards, not at the scaffold - and the
nesting in the manifest block above is what a product has to write by hand until that is decided.

{{< callout type="warning" >}}
**And the scaffolder empties the manifest of its comments.** It reads the file with `yaml.safe_load` and
writes it back with `yaml.safe_dump`, so on the manifest `simplon init` had just written, forty-two
comment lines became zero and every flow mapping was expanded to block style. The argument for
scaffolding rather than resolving at run time is that the product then reads its own build in its own
file; a writer that keeps the data and drops the prose collects that argument and spends it.
[simplon#110](https://github.com/marcozwyssig/simplon/issues/110) is where the two ways out are weighed.
{{< /callout >}}

**And the toolchain asks for a lab instance it does not use.** `run_toolchain` resolves the instance id
before it looks at whether the command declares a cache volume at all, so a product with no caches still
needs the section, and `simplon init` writes none:

```yaml
instance:
  env_var: CPPDEMO_INSTANCE
  default: dev
  max_id_len: 2
```

{{< callout type="info" >}}
**Since this walk: [simplon#105](https://github.com/marcozwyssig/simplon/issues/105) is closed.** All
three faces above were fixed on 2026-09-09 and driven end to end on a throwaway product the same day:
`support toolchain cpp 19` takes the version as a declared parameter, `toolchain:run` takes the
manifest's keys - `image`, `workdir`, `argv`, `env`, `caches` - as its own parameters, so the flat block
the scaffolder writes assembles unchanged, and the lab instance is resolved only where a cache volume
needs one. The caller's argv reaches the tool again too (`build compile --verbose`).

The transcripts and the table above are left standing as the record of what cppdemo met on the date they
were measured - which is what makes this chapter evidence rather than documentation. What a product
writes TODAY is the block without `body:`, `where:` and `extra:`; the nesting below is the workaround
that was necessary before the fix.
{{< /callout >}}

## build

One command, one container, and the kernel does not know what CMake is.

```text
$ ./cppdemo.sh build configure
-- The CXX compiler identification is Clang 19.1.7
-- Configuring done
-- Generating done
-- Build files have been written to: /src/build

$ ./cppdemo.sh build compile
[ 16%] Building CXX object CMakeFiles/calculator.dir/src/calculator.cpp.o
[ 33%] Linking CXX static library libcalculator.a
[100%] Linking CXX executable cppdemo
[100%] Built target cppdemo
```

What stands behind both is one assembled argv, and it is worth reading once because every product on this
kernel gets the same one:

```text
docker run --rm --user 0:0 -v /tmp/cppdemo:/src -w /src silkeh/clang:19 cmake --build build -j
```

`--user` is there from the first line, and that is not tidiness. netctl's hand-written gradle invocation
does not carry it, and on 2026-09-08 that left a repo-root `build/` owned by root, after which every CI
run on a freshly cleared runner died at the next step that had to create a directory (netctl#1778). A
product that declares its build here inherits the right answer instead of copying the wrong one - which
is also why the Java chapter's `GRADLE_USER_HOME` callout has no counterpart on this page.

The image goes through the kernel's one image gate, with the toolchain's own hint on the end of it.
Written as `silkeh/clang:latest` and run, that manifest line answers:

```text
[06:45:25] ERR build configure: 'image' must pin a version, not the moving tag 'latest' (got 'silkeh/clang:latest') - a build whose output depends on when it ran is not a build; a toolchain must name its version
```

`docker.pinned_image` is the gate the kernel puts its own images through - the Hugo image a `site:`
section declares, the docToolchain tag `docs:render` reads. The difference from the Java chapter is
where the product stands relative to it: javademo *chose* to call the gate from its own task body, and
cppdemo cannot avoid it, because the image reference is a manifest key the kernel reads. The rule reaches
the declaration, so nobody has to remember to keep it.

### The argument the caller cannot add

The design's other half is that the manifest pins the argv and the caller appends: `build compile` is a
CI step by name, and a person at a terminal keeps the tool's whole vocabulary behind it. `toolchain.argv`
implements it, and no command line reaches it. `extra` is a required parameter of the body, so it has to
be pinned in the manifest, and a pinned parameter leaves the command line entirely; `toolchain:run` also
carries no `passthrough_args`, which is the mechanism that would have let the tail through:

```text
$ ./cppdemo.sh build analyse src/calculator.cpp
Got unexpected extra argument (src/calculator.cpp)
```

That is row 10, and it is what made row 9 a refusal rather than a pass: `clang-tidy -p build` names no
source file, so the profile's `analyse` entry could not analyse anything, and the mechanism that was
supposed to complete it was the one that was missing.

{{< callout type="info" >}}
**Since this walk: [simplon#111](https://github.com/marcozwyssig/simplon/issues/111) is closed, and the
argv in the table above is what the kernel carries today.** `run-clang-tidy` ships in the same image,
reads the compile database `configure` already wrote and analyses everything the project really compiles -
re-driven on a scaffolded product on 2026-09-09, **three files out of three, rc 0**.

Two words go with it, and both are measurements rather than taste. `-quiet` drops the several-hundred-line
dump of every enabled check the driver prints ahead of the run. `-warnings-as-errors=*` is what makes the
command a check at all: on a deliberate null dereference the driver **prints**
`clang-analyzer-core.NullDereference` and **still exits 0**, because clang-tidy reports its findings as
warnings - so without the flag `analyse` is green on every tree, and a gate naming it is green forever.
With it, that tree is rc 1 and a clean one is still rc 0.

Row 10 is closed too, by si#105: `toolchain:run` now declares the variadic tail and
`passthrough_args: true`, so `./cppdemo.sh build analyse <anything>` reaches the tool. The appending rule
is no longer what `analyse` depends on, which is the point of the driver.
{{< /callout >}}

### The file the product still wrote by hand

Read the tree listing at the top of this chapter again. Every line of cppdemo's build is manifest data
except one: `CMakeLists.txt`, three targets, written by a person. Nothing on this page labelled that a
gap, because when the walk was taken there was nothing else to write - which is exactly the shape the
chapter is about, one file lower down.

{{< callout type="info" >}}
**Since this walk: `build:cmake-files` writes that file.**
[simplon#102](https://github.com/marcozwyssig/simplon/issues/102) reads the tree as the declaration it
already is - `src/<name>/` holding sources is a library, one holding a `main.cpp` is an executable, and
each `tests/<name>_test.cpp` is one ctest case - and writes one `CMakeLists.txt` per directory plus the
root file that adds them. The one thing a directory cannot show is what a target depends on, and an
optional `build:` section carrying `targets: { cppdemo: { depends: [calculator], include: [src/calculator] } }`
is the whole of that exception. Guessing it from include paths was refused in the design: it reads a
preprocessor approximately, and an approximate answer fails at link time, in a message about symbols
rather than about the manifest.

Driven end to end on a throwaway product on 2026-09-09, in this same `silkeh/clang:19`: four files
written, `configure` rc 0, `compile` rc 0, ctest 1 of 1 passed, and the binary printed its line.

Two things a product adopting it has to know, and both are consequences rather than caveats. The
generated files are **committed** and each carries a `DO NOT EDIT` header, because the generator
overwrites without asking - deliberately the opposite of `support:toolchain`'s never-clobber rule, since
a manifest is a product's own statement and a `CMakeLists.txt` is a rendering of one. And the output
layout moves: `add_subdirectory` puts a target's binary under its own directory, so an executable
declared in `src/cppdemo/` lands at `build/src/cppdemo/cppdemo` and not at the `build/cppdemo` that row
15's `deploy up` argv above names.

The table and the transcripts above are left standing as the record of what cppdemo met on the date they
were measured.
{{< /callout >}}

{{< callout type="info" >}}
**Since this walk, again: a target can say what it IS.** Driving the generator produced its own next
three tickets, and two of them were one decision.
[simplon#131](https://github.com/marcozwyssig/simplon/issues/131) asked whether a nested directory under
`src/` is its own target, and [simplon#134](https://github.com/marcozwyssig/simplon/issues/134) asked
where a unit test belongs - and the second answer depends on the first, so they were taken together.

**A nested directory folds into the target above it.** `src/net/tcp/socket.cpp` is a source of `net`, at
any depth, and there is no target called `tcp`. The other answer needs a name for it, and every name is
an invention - `tcp` collides with `src/util/tcp` in the one namespace CMake, the solution and the
`depends:` key all share. This one needs none, it is what the .NET SDK's `**/*.cs` glob already does
whatever a solution file says, and it is the only one of the two a product can escape: a directory that
wants to be its own library is written as `src/<name>/`. A `main` BELOW a target's root is refused rather
than folded, because a static archive carrying a stray `main` is invisible - the linker gives up an
archive member only to resolve an undefined symbol, and whoever links it defined `main` already.

**A unit test sits beside its unit, and it is not part of it.** `src/<target>/<name>_test.<ext>` is a
unit test; `tests/` holds what is about the assembled product. That is a rule about meaning - a reader
has to be able to tell a level from a path without opening the file - and the thing it replaced was not
a missing feature. Every source directly in a directory went into that directory's target, so
`src/net/net_test.cpp` was compiled INTO `libnet.a`: the test's code and its `main` shipped inside the
artefact and nothing in any run said a word. A co-located test names neither a dependency nor an include
path, because sitting inside the library's directory already says both. `_test` is the one spelling;
`test_<name>` is deliberately not a second one, or `test_helpers.cpp` becomes a test target with no
`main`.

**`tests/system/` and `tests/acceptance/` name a level, and a level is a ctest label.** So
`ctest --test-dir build -L unit` really selects the unit tests, and a test directly in `tests/` keeps the
meaning it had and carries no level. Worth knowing before writing a gate around it:
`ctest -L <a-label-nothing-carries>` exits **0** and prints `No tests were found!!!`, so a check that
reads the exit code is green for a level that contributed nothing.

**A library can be shared, and its headers can be found.** `add_library` was written bare, so every
target followed `BUILD_SHARED_LIBS` - which nobody sets, so every library was static and no product could
have both. `targets: { plugin: { kind: shared } }` is the one word a directory of sources cannot say
about itself; `static` and `executable` are the other two, and the kind is written into the generated
file rather than left implied. Include directories were `PRIVATE`, which means used to compile the target
and inherited by nothing, so a library's headers could not be found by the target one directory over. A
library now exports the directory its sources sit in, and an executable and a test keep theirs private
because nothing links either. The export is usable **within the generated project** and no further -
there is no `install(TARGETS ... EXPORT ...)` and no package config, because an export set with no
importer is written for a consumer that does not exist, and the consumer that will exist is
[simplon#128](https://github.com/marcozwyssig/simplon/issues/128).

**And [simplon#132](https://github.com/marcozwyssig/simplon/issues/132): the build had no debug symbols
at all.** Nothing set `CMAKE_BUILD_TYPE`, and with a single-config generator an empty one means no
optimisation and no `-g`. It is said in the profile's `configure` argv and NOT in the generated
`CMakeLists.txt`, because a build type belongs to the run: a committed `set(CMAKE_BUILD_TYPE ...)` would
decide it for every consumer of that tree forever. `RelWithDebInfo` is the default because a CI build is
the one run whose artefact ships and whose failure has to be explicable, and
`./cppdemo.sh build configure -DCMAKE_BUILD_TYPE=Debug` still wins - measured, the last `-D` is the one
in the cache.

Two things are named rather than solved. A `SHARED` target gets no `-fvisibility=hidden` and no generated
export header, so it links on Linux and not on Windows, and the kernel ships no Windows toolchain. And a
co-located unit test is REFUSED on the .NET side: an SDK-style project compiles every `.cs` beneath
itself, so the file is part of the library whatever the solution says, and a second project in one
directory is not a shape MSBuild has. Saying so beats generating something that builds and is wrong.

**Driven end to end in this same `silkeh/clang:19`, and read off the artefacts rather than off the
generated text** - which is the point, because `add_library(plugin SHARED ...)` appears in the file
whether or not a shared object came out:

```text
$ file build/src/plugin/libplugin.so build/src/calculator/libcalculator.a build/src/e2edemo/e2edemo
build/src/plugin/libplugin.so:        ELF 64-bit LSB shared object, x86-64 ... with debug_info, not stripped
build/src/calculator/libcalculator.a: current ar archive
build/src/e2edemo/e2edemo:            ELF 64-bit LSB pie executable, x86-64 ... with debug_info, not stripped

$ nm build/src/calculator/libcalculator.a
calculator.cpp.o:
0000000000000000 T _ZN4demo3addEii

mul.cpp.o:
0000000000000000 T _ZN4demo3mulEii
```

Read the second command twice. The nested `detail/mul.cpp` is in the archive and the co-located
`calculator_test.cpp` is not, and neither of those two facts is visible in any `CMakeLists.txt`. The
executable links two libraries and its manifest names no include path at all.

`with debug_info` is the phrase that matters and `not stripped` is not: a build with no build type at all
is **also** `not stripped`, so an assertion on the second word would have been green on exactly the tree
simplon#132 was opened about.
{{< /callout >}}

## test

The suite runs, and it runs in the image the compile ran in - which is the one rule the design states
about static analysis and testing, and the reason it states it: a checker that cannot see the
dependencies it is checking against degrades into a blanket exception, and a test binary is no different
from a checker in that respect.

```text
$ ./cppdemo.sh build unit
    Start 1: adds
1/3 Test #1: adds .............................   Passed    0.00 sec
    Start 2: multiplies
2/3 Test #2: multiplies .......................   Passed    0.00 sec
    Start 3: divides
3/3 Test #3: divides ..........................   Passed    0.00 sec

100% tests passed, 0 tests failed out of 3
```

Break one assertion in `demo::mul` and it arrives red, with ctest's own accounting of what failed:

```text
2/3 Test #2: multiplies .......................***Failed    0.00 sec
multiplies: expected 20, got 9

67% tests passed, 1 tests failed out of 3

The following tests FAILED:
	  2 - multiplies (Failed)
```

{{< callout type="warning" >}}
**That run exits 8, not 1.** ctest reports its own error class in the exit code, and the kernel passes
the number through untouched - which is correct, and which quietly breaks any CI step that compares an
exit code to `1` rather than to `0`.
{{< /callout >}}

### The green that is not about the product

Three runs, one after another, on the same tree:

| run | `build compile` | `build unit` | what ctest said |
|---|---|---|---|
| green | `0` | `0` | `100% tests passed, 0 tests failed out of 3` |
| one assertion broken | `0` | `8` | `67% tests passed, 1 tests failed out of 3` |
| a type error in the tree | `2` | `0` | `100% tests passed, 0 tests failed out of 3` |

Read the third row. `build compile` failed on a `cannot initialize a variable of type 'int' with an
lvalue of type 'const char[11]'`, and `build unit` then ran the binaries the *previous* build left in
`build/` and reported every test passing. Nothing lied: ctest ran what was there, and what was there was
last week's answer.

The Java chapter has the same hazard and an answer for it. Its gate is an `impl:` - a callable the kernel
runs for a verdict - so the kernel exports a marker path in `SIMPLON_SETUP_FAILED` before it, the runner
writes the stage that broke into it, and the report comes out `setup-failed` and empty rather than
plausible. A `toolchain:run` command has no callable to point at - and it does not need one, because it
is a **command**, and a gate may name a command in the product's own tree
([simplon#106](https://github.com/marcozwyssig/simplon/issues/106)). A gate whose `command:` is the
ctest command above and whose `preamble:` is the compile stops on the third row *at the compile*: the
verdict is `setup-failed`, ctest is never asked about last week's binaries, and the archive says the
build fell over rather than that three tests passed. Nothing is copied out of the `build` commands - the
image, the argv and the caches stay declared once, where they already are.

**That pairing has since been driven rather than described** - a real `ctest` in `silkeh/clang:19`,
behind a real `command:` gate, green, red, and stopped at a failed compile
([simplon#136](https://github.com/marcozwyssig/simplon/issues/136), which is also what found that the key
could not name a `toolchain:run` command at all until then). What it has not been driven on is *this
product*: cppdemo declares no `suites:` section, which is why row 11 says *derived*.

**The three runs above were measured before that key existed**, and they are still exactly what the two
commands do when they are run bare. That is the point of the third row rather than an artefact of it: the
pairing is what a gate adds, and two commands nobody paired report the last good result.

`cppdemo` declares no `suites:` section, so what is above is what it does today; the block that closes
the gap is three keys in one section and no Python, which leaves the claim this chapter opens with
standing in the test phase as well as in the build.

What a gate is, what a level is and how a
[command backs one](../../building/test-levels/#a-gate-may-name-a-command-in-your-own-tree) are all in
[Test levels](../../building/test-levels/); the five outcomes a gate can report, and which two of them
are statements about the product, are in [the Python chapter's `test` section](../case-python/#test).

## release

The tag is the version and the guard is the kernel's, and neither of those has anything to do with the
language. `release:tag` is placed in cppdemo's manifest with one line and no body of its own, and it
behaves exactly as it does for a Python or a Java product - which the chapter can show, because it
refused: with no `origin/main` in the checkout the question "main carries this commit" has no answer, so
`./cppdemo.sh release tag v0.1.0` exited 1 and `git tag` afterwards listed nothing. What the guard checks,
and what it deliberately does not, is in [Cutting a release](../releasing/).

What gets published is the part that differs, and cppdemo declares none of it: `release:artifact` reads
an `artifacts:` section and `release:image` an `images:` one. Row 14 says *derived* for that reason and
not because anything is missing - a stripped ELF binary and a jar are the same kind of thing to the
kernel, which is the point.

## deploy

**Same answer as the other two chapters, and it is the state of the kernel rather than an omission here.**

What exists is the local host, and for this product it is one more instance of the same coordinate: the
binary runs in the image that compiled it, on the machine you typed the command on.

```text
$ ./cppdemo.sh dev deploy up
cppdemo: 2 + 3 = 5
```

There is a real difference from the Java chapter hiding in that line, and it is not in cppdemo's favour.
javademo runs its jar in a JRE image rather than the JDK that built it - what ships is the artefact, and
the thing that runs it is not the thing that made it. cppdemo runs its binary in the full clang image,
because the product declared the same image twice and nothing suggested otherwise. A C++ product that
cared would name a runtime image in the `deploy up` body, and the manifest is where that decision would
be visible.

What does not exist is everything past that host. `deploy` is one of the two ribs the catalogue draws
empty on purpose: the group name, the env-first gate, and no tasks at all.
[simplon#5](https://github.com/marcozwyssig/simplon/issues/5) is where that decision is open, and
[the two empty ribs](../../building/phases/#the-two-empty-ribs) is why leaving them empty is the
expensive choice rather than the lazy one.

## docs

Both documentation commands are language-agnostic, and this chapter drove neither. `docs:render` runs
docToolchain in Docker and produces HTML and PDF from AsciiDoc; the [Java chapter](../case-java/) drove
it and its transcript is there, including the ownership trap that makes the order of `build` and `docs`
matter on a fresh tree. `docs:site` reads a `site:` section cppdemo does not declare. Row 17 says
*derived* for both, and repeating a run that has nothing C++ about it would have been a third copy of
the same evidence.

## What this chapter does not repeat

Each of these is told once, elsewhere, and told properly:

- the same loop with the kernel's own language underneath it -
  [A Python product, end to end](../case-python/)
- the same loop with a hand-written build body - [A Java product, end to end](../case-java/)
- what a gate is, how a level is declared, and how a foreign runner attaches -
  [Test levels](../../building/test-levels/)
- why the tag is the version and what the release guard refuses - [Cutting a release](../releasing/)
- why `deploy` and `monitor` are empty - [The five phases](../../building/phases/)
- getting a product to exist in the first place - [Getting started](../getting-started/)
