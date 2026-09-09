---
title: "A .NET product, end to end"
weight: 8
---

The [Java chapter](../case-java/) walks one delivery loop over a toolchain the kernel has never met, and
its product pays for that with a task body: `impl: orchestrator.gradle:build`, a function that ends in a
`docker run`, written by hand because there was nothing else to write. This one walks the same loop with
**no task body for the build at all**. `compile`, `unit` and `analyse` are `toolchain:run` commands: a
pinned `mcr.microsoft.com/dotnet/sdk:9.0`, one argv each, and the argv are the kernel's rather than the
product's.

That is the second half of the uniform-build design, and putting it beside the first is what makes the
claim checkable: **the same five verbs, and a product that declares data where the other one declares a
function.**

It is also the chapter with the most **does not exist yet** rows on this site, and that is not an
accident of scheduling. Driving a .NET product end to end on 2026-09-09 found four ways in which the
design, the scaffolder and the loader disagree about `toolchain:run`, and one more about what a gate is
allowed to name. Every one of them is on this page with its ticket rather than smoothed over.

The product is `dotnetdemo`, scaffolded for this chapter and driven on one machine on 2026-09-09:

```text
dotnetdemo.yaml                                the manifest - four lines of build, and no body behind them
DotnetDemo.sln                                 the product's own, and Simplon does not write it
src/DotnetDemo/DotnetDemo.csproj               ditto
src/DotnetDemo/Calculator.cs                   two methods
src/DotnetDemo/Program.cs                      what `deploy up` runs
tests/DotnetDemo.Tests/CalculatorTests.cs      three [Fact] methods
orchestrator/src/python/orchestrator/          six .py files - five scaffolded, one written here
```

The one module written here is the deployment body. Nothing in `orchestrator/` knows what `dotnet` is.

## The labels, and why they are on the page

Same rule as the two chapters before it, for the same reason: a page describing a pipeline nobody has
driven is worse than no page, because the reader concludes they misread the site rather than that the
site is inventing.

{{< callout type="info" >}}
**run** - somebody executed it. The evidence names where and when.

**derived** - read out of a manifest, a task body or the catalogue, and not executed for this page. It
is a statement about what is declared, not about what was observed.

**does not exist yet** - the step is named because leaving it out would make the loop look complete.
Every such row carries the ticket where the decision is still open.
{{< /callout >}}

| # | Step | Command | Label | Evidence |
|---|---|---|---|---|
| 1 | Scaffold the product | `simplon init dotnetdemo` | run | this checkout, 2026-09-09; five Python files and a CLI that runs before there is anything to run |
| 2 | Bring the solution and the project files | - | does not exist yet | [simplon#107](https://github.com/marcozwyssig/simplon/issues/107); the design puts them out of scope, and `dotnet new sln` inside the same image wrote them |
| 3 | Write the toolchain configuration into the manifest | `./dotnetdemo.sh support toolchain dotnet` | does not exist yet | [simplon#105](https://github.com/marcozwyssig/simplon/issues/105); 2026-09-09 06:41:33, rc 1, and the traceback is below |
| 4 | Compile in the pinned SDK image | `./dotnetdemo.sh build compile` | run | 2026-09-09 06:37, rc 0 in 23 s; transcript below |
| 5 | Refuse a toolchain image that is not pinned | `./dotnetdemo.sh build compile` | run | 2026-09-09 06:40:51, rc 1; message below |
| 6 | Refuse the `with:` block the design and the scaffolder write | `./dotnetdemo.sh build compile` | run | 2026-09-09, rc 1; message below |
| 7 | Append a flag of your own to the pinned argv | `./dotnetdemo.sh build compile` | does not exist yet | [simplon#105](https://github.com/marcozwyssig/simplon/issues/105); 2026-09-09, rc 2, `No such option: -v` |
| 8 | Run the unit tests in the same image | `./dotnetdemo.sh build unit` | run | 2026-09-09 06:38:26, rc 0; three passed |
| 9 | A failing xUnit test arrives red | `./dotnetdemo.sh build unit` | run | 2026-09-09 06:39:10, rc 1; transcript below |
| 10 | A type error in the product arrives with the same rc | `./dotnetdemo.sh build unit` | run | 2026-09-09 06:39:39, rc 1; transcript below |
| 11 | Turn that rc into a verdict and an Allure archive | `test:accept`, `test:report` | does not exist yet | [simplon#106](https://github.com/marcozwyssig/simplon/issues/106); a gate takes `suite:` or `impl:`, and a toolchain command is neither |
| 12 | Analyse where the compile ran | `./dotnetdemo.sh build analyse` | run | 2026-09-09 06:38:38, rc 0; and 06:40:00, rc 2 on two stray spaces |
| 13 | Cut the release tag | `./dotnetdemo.sh release tag v0.1.0` | run | 2026-09-09 06:40:21, rc 1; refused, nothing cut |
| 14 | Publish the build output to a registry | `release:artifact`, `release:asset` | derived | they read an `artifacts:` and an `assets:` section, and dotnetdemo declares neither |
| 15 | Build and push a container image | `build:image`, `release:image` | derived | both read an `images:` section, and dotnetdemo declares none |
| 16 | Deploy to the local host | `./dotnetdemo.sh dev deploy up` | run | 2026-09-09 06:40:06, rc 0; output below |
| 17 | Deploy past the local host - Proxmox, Portainer, a cloud | - | does not exist yet | [simplon#5](https://github.com/marcozwyssig/simplon/issues/5) |
| 18 | Render the architecture documentation to HTML and PDF | `docs:render` | derived | it reads a pinned docToolchain tag, and dotnetdemo declares none |
| 19 | Build a documentation website with Hugo | `docs:site` | derived | it reads a `site:` section, and dotnetdemo declares none |

Of the 19 steps above, 10 are **run**, 4 are **derived** and 5 **does not exist yet**.

The four *derived* rows are the same shape as in the Java chapter and it is worth saying once: each of
those tasks reads a manifest section this product does not have. They are **offered and not placed** -
the catalogue carries the body, and a product declares the command the day it has something for it to
read.

The five *does not exist yet* rows are not that shape at all, and they are the reason to read on. Rows 3
and 7 are one ticket - [simplon#105](https://github.com/marcozwyssig/simplon/issues/105) - and so is row
6, which is *run* rather than open because the refusal it names really happened. That one finding has
four faces, the `build` section below walks all of them, and it is what this chapter was written to
produce.

## build

One declaration, one container, and the kernel does not know what `dotnet` is:

```text
$ ./dotnetdemo.sh build compile
  Determining projects to restore...
  Restored /src/src/DotnetDemo/DotnetDemo.csproj (in 36 ms).
  Restored /src/tests/DotnetDemo.Tests/DotnetDemo.Tests.csproj (in 20.55 sec).
  DotnetDemo -> /src/src/DotnetDemo/bin/Debug/net9.0/DotnetDemo.dll
  DotnetDemo.Tests -> /src/tests/DotnetDemo.Tests/bin/Debug/net9.0/DotnetDemo.Tests.dll

Build succeeded.
    0 Warning(s)
    0 Error(s)

Time Elapsed 00:00:22.64
```

The declaration behind it names no callable at all:

```yaml
      compile:
        task: "toolchain:run"
        help: "Compile in the containerised toolchain."
        with:
          body:
            image: "mcr.microsoft.com/dotnet/sdk:9.0"
            workdir: /src
            argv: ["dotnet", "build"]
          where: "build compile"
          extra: []
```

Compare that with the Java product's line - `impl: "orchestrator.gradle:build"`, plus the function it
points at, plus that function's own `docker run`, plus the test surface all of it needs. Here the image
and the argv are data, and what turns them into a process is `simplon.tasks.toolchain`, which every
product shares. What comes out is one line:

    docker run --rm --user <uid>:<gid> -v <product root>:/src -w /src \
        mcr.microsoft.com/dotnet/sdk:9.0 dotnet build

The argv at the end is the only part of that line the product had a say in, and the three decisions in
front of it are the kernel's - the ones a hand-written body gets wrong. The mount is the product root at
the declared workdir. The **`--user` is the calling uid and gid**, from the
first line rather than after the first CI run that left a root-owned `bin/` behind. And the image goes
through `simplon.docker.pinned_image`, which is the same gate the kernel puts its own images through -
written as `:latest` and run, that line answers:

```text
[06:40:51] ERR build compile: 'image' must pin a version, not the moving tag 'latest' (got 'mcr.microsoft.com/dotnet/sdk:latest') - a build whose output depends on when it ran is not a build; a toolchain must name its version
```

The tail of that sentence is the toolchain's own: the general gate offers an example tag, and here the
diagnosis is that a *toolchain* must name its version.

### The three argv are not this product's

This is the part that distinguishes the chapter from a product that merely happens to use containers.
`compile`, `unit` and `analyse` are the kernel's `dotnet` profile - a table of argv and paths in
`simplon.tasks.profiles`, one entry per language - and the product's contribution is the version that
fills the image template. Swapping 9.0 for 10.0 is a one-line diff rather than an edit to a script.

The profile is **data, and inert after it is written out**. That is a safety property rather than a
convenience: a profile read while a build ran would let a kernel release change how a product compiles,
which is the unpinned-image defect one level up. Written into the manifest, the product owns what it
runs, the kernel's table can move without moving anybody's build, and a wrong entry is fixed by editing
a manifest instead of by waiting for a release.

### What the design writes, and what the loader accepts

{{< callout type="warning" >}}
**The `with:` block above is not the one the design writes, and not the one the scaffolder writes.** Both
of those put the toolchain's keys directly under `with:`:

```text
        with:
          image: "mcr.microsoft.com/dotnet/sdk:9.0"
          workdir: /src
          argv: ["dotnet", "build"]
```

`manifest.load` accepts that. The binder does not, because `toolchain:run`'s body takes `body`, `where`,
`extra` and `network`, and nothing named `image`:

```text
ValueError: build compile: `with:`/`params:` name parameter(s) the impl does not take: argv, image, workdir
```

So `support toolchain <language>` writes a manifest that does not assemble, and the shape shown above -
the toolchain nested under `body:`, with `where:` and `extra:` pinned beside it - is the only one that
runs today.

Pinning `extra` has a price the design's own argv rule cannot survive. A pinned parameter leaves the
command line entirely, so *manifest first, caller appends* becomes *manifest only*:

```text
$ ./dotnetdemo.sh build compile -v
No such option: -v            (rc 2)
```

[simplon#105](https://github.com/marcozwyssig/simplon/issues/105) carries all four faces of this,
including the last one: `toolchain:run` resolves the lab instance for its cache-volume names **before**
it looks at whether the command declares a cache at all, so a freshly scaffolded product dies on

```text
ValueError: simplon: manifest .../dotnetdemo.yaml is missing the 'instance' section
```

with no cache anywhere in sight. `dotnetdemo` therefore carries a section nothing told it to write:

```yaml
instance:
  env_var: DOTNETDEMO_INSTANCE
  default: dev
  max_id_len: 2
```
{{< /callout >}}

### And the command that was supposed to write all of it

Row 3 is the one that should have made this section unnecessary. `support:toolchain` exists, is declared
in the catalogue, is placed in this product's manifest, and takes exactly one parameter: the language.
Every profile's image is a template with a `{version}` in it, and there is no second parameter to fill
it:

```text
$ ./dotnetdemo.sh support toolchain dotnet
  File ".../simplon/tasks/profiles.py", line 93, in profile
KeyError: 'version'
```

It is not a .NET quirk: all four profiles carry the same template, so the command raises for every
language it offers. `dotnetdemo`'s manifest was therefore written by hand - to the letter of what the
scaffolder would have produced, which is why the page can still claim the argv are the kernel's.

## test

**There is no `test` group in this product, and that is the honest headline of the section.**

Two separate things put it there. The first is placement: `support toolchain` writes all three commands
under `build`, while the design's own command table promises `test unit` and `test analyse`. The
placement is the scaffolder's, so it is kept here rather than corrected on the page - `toolchain:run` is
a family and free to be filed anywhere, so both are legal and only one of them is what a product gets.

The second is the one that matters. Run the tests:

```text
$ ./dotnetdemo.sh build unit
Starting test execution, please wait...
A total of 1 test files matched the specified pattern.

Passed!  - Failed: 0, Passed: 3, Skipped: 0, Total: 3, Duration: 5 ms - DotnetDemo.Tests.dll (net9.0)
```

Break one assertion in `Calculator.Mul`, and it arrives red:

```text
[xUnit.net 00:00:00.08]     DotnetDemo.Tests.CalculatorTests.Multiplies [FAIL]
  Failed DotnetDemo.Tests.CalculatorTests.Multiplies [4 ms]
  Error Message:
   Assert.Equal() Failure: Values differ
Expected: 6
Actual:   5

Failed!  - Failed: 1, Passed: 2, Skipped: 0, Total: 3, Duration: 6 ms - DotnetDemo.Tests.dll (net9.0)
```

Now put a type error in the product instead, so the build never reaches a test:

```text
/src/src/DotnetDemo/Broken.cs(5,35): error CS0029: Cannot implicitly convert type 'string' to 'int' [/src/src/DotnetDemo/DotnetDemo.csproj]
```

| run | rc | what came out |
|---|---|---|
| green | 0 | `Failed: 0, Passed: 3, Skipped: 0, Total: 3` |
| one assertion broken | 1 | `Failed: 1, Passed: 2, Skipped: 0, Total: 3` |
| a type error in the product | 1 | no test ran at all: `error CS0029`, and the run says nothing else |

**Read the rc column.** The two failures are indistinguishable from outside, and nothing in the run
above can tell them apart - because nothing in it is a *gate*. `build unit` is a command: it runs
`dotnet test` in the pinned SDK image and hands back a number, and a number is all a caller gets. No
verdict vocabulary (the five outcomes are [the Python chapter's table](../case-python/#test)), no
`setup-failed` and no setup marker to reach it with, no Allure results, no merge, no archive.

The Java product paid one task body and got all three -
[an `impl:` gate is opaque, and says so](../../building/test-levels/#an-impl-gate-is-opaque-and-says-so)
is where that trade is written down. **This product pays nothing and gets the same, by naming the
command it already has** ([simplon#106](https://github.com/marcozwyssig/simplon/issues/106)). A gate
declares `command:` - a command in this product's own tree, `build unit` as it is typed - and
`preamble:` for the build that has to succeed first, and the third row above then stops at the compile
as `setup-failed` instead of arriving as the same `rc 1` the second row carries. The gate resolves that
command the way the CLI does, the body its `task:` names with its own `with:` pinned, so the image and
the argv stay declared once and the verdict is about the line a person runs.

**This product declares no `suites:` section**, and the runs above are what it does without one: the
measurement is what two commands do when nobody pairs them. Closing it costs one manifest section and no
Python, so the design's claim that a product writes no body of its own reaches the test phase too -
[Test levels](../../building/test-levels/#a-gate-may-name-a-command-in-your-own-tree) carries the block
and the rules.

### analyse, and the one rule it obeys

```text
$ ./dotnetdemo.sh build analyse
(rc 0, and nothing at all on stdout)
```

Two stray spaces in front of a method, and:

```text
/src/src/DotnetDemo/Program.cs(5,5): error WHITESPACE: Fix whitespace formatting. Delete 2 characters. [/src/src/DotnetDemo/DotnetDemo.csproj]
```

rc 2 rather than 1, which is `dotnet format`'s own answer and passes through untouched - the kernel
returns what the container returned and interprets nothing.

The rule the command does obey is that it names the **same image** as `compile`. That is not tidiness: a
checker that cannot see what the compiler saw is analysing a program nobody builds, and the same holds
for Roslyn analyzers, `clang-tidy` and mypy alike. Here it is a property of the manifest, so it is
readable rather than promised.

## The solution file, which Simplon does not write

Row 2 is the open question this chapter is asked to name rather than gloss. Generating `.sln` and
`.csproj` is explicitly out of scope in the design, and the reason given is that a solution file is a
format with GUIDs and configuration matrices - inventing conventions for it without a product to measure
against is how a generator ages faster than it helps.

Measured on this product, so the cost is a number rather than an adjective: `DotnetDemo.sln` for two
projects is 54 lines, carries five distinct GUIDs (three project identities and two project *type*
identities), and 24 rows of configuration matrix - six per project, because `dotnet new sln` writes
Debug and Release across Any CPU, x64 and x86 whether or not anything targets them.

So `dotnetdemo` brings its own, written by `dotnet new sln` inside the same pinned SDK image the build
runs in, and the kernel only runs the toolchain over what it finds. That works, and it leaves a specific
gap: the kernel scaffolds a product, is about to scaffold its toolchain configuration, and the one file
the toolchain compiles over is the thing the product has to obtain elsewhere.
[simplon#107](https://github.com/marcozwyssig/simplon/issues/107) is where that is open, with the three
candidate homes for it and the trigger that decides between them.

## release

The tag is the version and the guard is the kernel's, and neither has anything to do with the language.
`release:tag` is placed in dotnetdemo's manifest with one line and no `impl:` of its own, and it behaves
exactly as it does for a Python or a Java product - which the chapter can show, because it refused:

```text
$ ./dotnetdemo.sh release tag v0.1.0
[06:40:21]   ! could not fetch from origin, so origin/main may be out of date. The guard below reads
              what is here; a stale ref can only make it refuse too much, never too little
[06:40:21] ERR there is no origin/main here, so the question 'main carries this commit' has no answer
              - and nothing was cut.
```

`git tag` afterwards lists nothing. What the guard checks, and what it deliberately does not, is in
[Cutting a release](../releasing/).

What differs for a .NET product is what gets published, not how. A NuGet package, a self-contained
publish directory and a container image are three different answers, and all three reach the registry
through the kernel's existing tasks - which read manifest sections dotnetdemo does not declare. Rows 14
and 15 say *derived* for that reason and not because anything is missing.

## deploy

**Same answer as the two chapters before it, and it is the state of the kernel rather than an omission
here.**

What exists is the local host, and this is the one place dotnetdemo writes a body of its own:

```text
$ ./dotnetdemo.sh dev deploy up
[06:40:06] ==> running src/DotnetDemo/bin/Debug/net9.0/DotnetDemo.dll in mcr.microsoft.com/dotnet/runtime:9.0 on this host
dotnetdemo: 2 + 3 = 5
```

The runtime image is not the SDK the build ran in - what ships is the app, and the thing that runs it is
not the thing that made it - and its reference goes through the same pin gate as the toolchain's. That
is the seam working in the direction people forget: nothing forces a product's own image string through
`simplon.docker.pinned_image`, and calling it anyway buys the kernel's argument about what a reference
may say.

What does not exist is everything past that host. `deploy` is one of the two ribs the catalogue draws
empty on purpose: the group name, the env-first gate, and no tasks at all.
[simplon#5](https://github.com/marcozwyssig/simplon/issues/5) is where that decision is open, and
[the two empty ribs](../../building/phases/#the-two-empty-ribs) is why leaving them empty is the
expensive choice rather than the lazy one.

## docs

Both documentation commands are *derived* here, and for the ordinary reason: `docs:render` needs a
pinned docToolchain tag and a config file in the checkout, `docs:site` needs a `site:` section, and
dotnetdemo declares none of them. The Java chapter has driven the first of the two and shows what comes
out - including the ownership trap that bites when it runs before the build.

## What this chapter does not repeat

Each of these is told once, elsewhere, and told properly:

- the same loop with a hand-written build body under it - [A Java product, end to end](../case-java/)
- the same loop in the kernel's own language - [A Python product, end to end](../case-python/)
- what a gate is, how a level is declared, and how a non-pytest runner attaches -
  [Test levels](../../building/test-levels/)
- why the tag is the version and what the release guard refuses - [Cutting a release](../releasing/)
- why `deploy` and `monitor` are empty - [The five phases](../../building/phases/)
- getting a product to exist in the first place - [Getting started](../getting-started/)
