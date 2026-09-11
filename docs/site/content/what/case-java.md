---
title: "A Java product, end to end"
weight: 3
aliases:
  - "/using/case-java/"
---

## The commands, in order

This chapter is the delivery loop on a product with **no Python in it at all** - one Gradle project,
three JUnit tests. Here is what a person types, in order:

```text
./javademo.sh build jar             compile and package, with gradle inside a pinned container
./javademo.sh test unit             the JUnit suite, and a verdict the kernel can read
./javademo.sh test accept           every level in order, then the merged report
./javademo.sh build docs            the architecture documentation, HTML and PDF
./javademo.sh release tag v0.1.0    tag it; refused unless the tree is clean
./javademo.sh dev deploy up         env-first: the environment is the outer token
```

Two support commands sit beside those steps. `./javademo.sh support install` is the host preflight, run
once on a new machine. `./javademo.sh test report` renders the archive on its own, which is what you
want after a red run rather than a second full sweep.

Everything under this heading is the table below read as a sequence; the table is what says which rows
were really run, and when.

## The product, and what it proves

The [Python chapter](../case-python/) walks one delivery loop with the kernel's own language underneath
it. This one walks the same loop with **no Python in the product at all** - one Gradle project, three
JUnit tests, and an orchestrator whose only job is to hand a container an argument list and read one
integer back.

That is the claim the positioning rests on: Simplon is the piece between a CI/CD process and the
technologies under it. Two chapters side by side are what turns that from a design intention into
something a reader can check - **the same five verbs, the same commands, and a toolchain that shares
nothing with the first one.**

The product is `javademo`, scaffolded for this chapter and driven on one machine on 2026-09-08. It is
about as small as a Java product gets:

```text
javademo.yaml                          the manifest - one gate, and it is not pytest
build.gradle  settings.gradle          the Gradle project
src/main/java/demo/Calculator.java     two methods
src/main/java/demo/Main.java           what `deploy up` runs
src/test/java/demo/CalculatorTest.java three @Test methods
src/docs/manual.adoc                   what `build docs` renders
orchestrator/src/python/orchestrator/  seven .py files - five scaffolded, two written here
```

**Zero `.py` files outside `orchestrator/`.** That was not possible until this week, and the section on
`test` below says what changed.

## The labels, and why they are on the page

Same rule as the Python chapter, for the same reason: a page describing a pipeline nobody has driven is
worse than no page, because the reader concludes they misread the site rather than that the site is
inventing.

{{< callout type="info" >}}
**run** - somebody executed it. The evidence names where and when.

**derived** - read out of a manifest, a task body or the catalogue, and not executed for this page. It
is a statement about what is declared, not about what was observed.

**does not exist yet** - the step is named because leaving it out would make the loop look complete.
Every such row carries the ticket where the decision is still open.
{{< /callout >}}

| # | Step | Command | Label | Evidence |
|---|---|---|---|---|
| 1 | Scaffold the product | `simplon init javademo` | run | this checkout, 2026-09-08; five Python files and a CLI that runs before there is anything to run |
| 2 | Compile and jar with Gradle, in Docker | `./javademo.sh build jar` | run | 2026-09-08 06:25, rc 0; transcript below |
| 3 | Refuse a toolchain reference that is not pinned | `./javademo.sh test unit` | run | 2026-09-08, rc 1; message below |
| 4 | Run the Java gate and merge its JUnit XML | `./javademo.sh test accept` | run | 2026-09-08 06:27:48, rc 0; archive below |
| 5 | A failing Java test arrives red | `./javademo.sh test accept` | run | 2026-09-08 06:27:19, rc 1; archive below |
| 6 | A build that never reached the tests arrives as `setup-failed` | `./javademo.sh test accept` | run | 2026-09-08 06:27:34, rc 1; archive below |
| 7 | Cut the release tag | `./javademo.sh release tag v0.1.0` | run | 2026-09-08, rc 1; refused, nothing cut |
| 8 | Publish the jar itself to a registry | `release:artifact` | derived | the coordinate is in the catalogue; it reads an `artifacts:` section, and javademo declares none |
| 9 | Build and push a container image | `build:image`, `release:image` | derived | both read an `images:` section, and javademo declares none |
| 10 | Deploy to the local host | `./javademo.sh dev deploy up` | run | 2026-09-08 06:25:34, rc 0; output below |
| 11 | Deploy past the local host - Proxmox, Portainer, a cloud | - | does not exist yet | [simplon#5](https://github.com/marcozwyssig/simplon/issues/5) |
| 12 | Render the architecture documentation to HTML and PDF | `./javademo.sh build docs` | run | 2026-09-08 06:26:21, rc 0; transcript below |
| 13 | Build a documentation website with Hugo | `docs:site` | derived | it reads a `site:` section, and javademo declares none |

Of the 13 steps above, 9 are **run**, 3 are **derived** and 1 **does not exist yet**.

The three *derived* rows are the same shape and it is worth saying once rather than three times: each of
those tasks reads a manifest section this product does not have. They are **offered and not placed** -
the catalogue carries the body, and a product declares the command the day it has something for it to
read. Nothing about them is Java-specific, and nothing about them is broken; javademo simply ships a jar
to a host rather than an image to a registry.

## build

One command, one container, and the kernel does not know what Gradle is.

```text
$ ./javademo.sh build jar
> Task :compileJava
> Task :jar
> Task :build

BUILD SUCCESSFUL in 9s
```

The manifest line behind it names a callable, not a tool:

```yaml
tasks:
  build:   { impl: "orchestrator.gradle:build", help: "Compile and jar the product (gradle, in Docker)." }
groups:
  build:
    commands:
      jar:  { task: build }
      docs: { task: "docs:render", help: "Render the architecture documentation to HTML and PDF." }
```

and the callable is a short function that ends in a `docker run`. What is worth reading in it is its
first constant:

```python
IMAGE = docker.pinned_image("gradle:8.14.3-jdk21", "orchestrator.gradle")
```

`simplon.docker.pinned_image` is the gate the kernel puts its **own** images through - the Hugo image a
`site:` section declares, the docToolchain tag `docs:render` reads, the mermaid renderer the diagram
check runs. Nothing forces a product's own reference through it: the rule reaches the manifest keys the
kernel reads, and this string is javademo's. Calling it anyway is the seam working in the direction
people forget - the product picks the toolchain and inherits the kernel's argument about what a
toolchain reference may say. Written as `gradle:latest` and run, that line answers:

```text
ValueError: orchestrator.gradle: 'image' must pin a version, not the moving tag 'latest'
(got 'gradle:latest') - a build whose output depends on when it ran is not a build;
pin it as '<image>:<tag>' (e.g. 'hugomods/hugo:exts-0.148.2'), or by digest
```

{{< callout type="warning" >}}
**`GRADLE_USER_HOME` has to be a directory the caller owns, and the failure gives you nothing to go on.**
The obvious way to keep a Gradle cache across runs is a named docker volume. Measured: a named volume is
created root-owned, `--user <uid>:<gid>` cannot write into it, and Gradle dies unpacking
`libnative-platform.so` before it runs a single task - **rc 1 in 0.8 s**, with `Could not initialize
native services` and no mention of permissions anywhere in its output.

A bind mount under the product root, created by the orchestrator with the caller's own uid, is the whole
fix. This is the same rule the kernel writes down for its own containers -
[a container that writes into a mount runs as `--user`](../../with-what/rules/#a-container-that-writes-into-a-mount-runs-as---user) -
one step further out, where the mount is a cache rather than an output.
{{< /callout >}}

### The kernel's own java profile, which this product deliberately does not use

javademo writes its own `orchestrator.gradle` body, and the chapter is built on that: the kernel does
not know what Gradle is. A product that would rather not write one asks for the ready-made configuration
instead - `support toolchain java 25` - and gets `toolchain:run` commands scaffolded into its manifest.
**Two of that profile's decisions were wrong until si#122, and both were wrong in a way only a driven
run shows.**

`compile` was `gradle build`. `build` depends on `check`, so it ran the tests, and a broken assertion
made the *compile* red - which destroys the one distinction a gate's `preamble:` exists to draw. The
`test` section below shows that distinction working on this product:
[a build that never reached the tests](#a-build-that-never-reached-the-tests) arrives as `setup-failed`,
and `setup-failed` is a statement about the BUILD. On the old profile a failing assertion arrived
wearing that word. The repair is not the obvious one either. Measured in `gradle:jdk25` (Gradle 9.7.1) on 2026-09-10, over a
tree whose **test source does not compile**:

```text
$ gradle assemble --no-daemon --console=plain
> Task :compileJava   > Task :classes   > Task :jar   > Task :assemble
BUILD SUCCESSFUL in 2s
rc 0
```

`assemble` never runs `compileTestJava`, so it trades one wrong verdict for another - and
`gradle build -x test` produces the identical task list, because Gradle's `-x` drops the excluded task's
exclusive dependencies too. `assemble testClasses` is the pair that means what the two commands are
called: on that same tree it is rc 1 with
`error: incompatible types: String cannot be converted to int`, and on a tree whose *assertion* is
broken it is rc 0 while `gradle test` is rc 1.

**And the profile carries no `analyse` at all, on purpose.** The other three languages have one - C++
has clang-tidy, .NET has `dotnet format`, Python has mypy - and Java's slot stays empty because the
kernel has nothing true to put in it. `gradle check` on a stock `java` plugin is `test` under another
name (`--dry-run` lists `compileJava classes compileTestJava testClasses test check`), and the obvious
repair is worse:

```text
$ gradle clean check -x test --no-daemon --console=plain      # a raw type, an unused import,
> Task :clean                                                 # a dead store and a certain NPE
> Task :check
BUILD SUCCESSFUL in 2s
rc 0
```

One task, no javac at all, rc 0 over four deliberate defects. That is exactly the shape
[simplon#111](https://github.com/marcozwyssig/simplon/issues/111) measured for clang-tidy without
`-warnings-as-errors=*`: a command that cannot go red, and a gate naming it green forever. SpotBugs,
PMD, Checkstyle and ErrorProne are all Gradle plugins the product's own `build.gradle` applies, so a
Java product that wants one declares a `build analyse` command of its own. **A missing command with a
reason beats a command that cannot fail** - which is the same rule the `deploy` section below applies to
a whole phase.

## test

This is the seam the chapter exists for, so it is the longest section - and even so, most of it is
elsewhere. What a level is, which one clears the results directory, how a non-pytest runner attaches and
what the merge step will and will not do to your files are all in
[Test levels](../../with-what/test-levels/#suite-against-impl---and-this-is-how-you-attach-gradle).

What belongs **here** is the whole taxonomy of a Java product, which fits in nine lines:

```yaml
suites:
  reports: "build/reports"
  gates:
    - name: "unit"
      impl: "orchestrator.gradle:test"
      results: "clear"
  report:
    parent_suite: "Java"
    merge: ["build/junit-xml"]
```

**Until this week that section would not load.** The clear used to hang on the pytest branch, so
`results: clear` on an `impl:` gate was accepted and inert - and refusing it, which is what the kernel
did next, left a product whose only runner is its own with no loadable taxonomy at all. The way out was
to ship a pytest gate holding `assert True` purely to own the directory: 29 MB of suite venv, and an
archive that counted four tests where the product has three. The inert half was fixed instead
([simplon#61](https://github.com/marcozwyssig/simplon/issues/61)), and the sentence the key now makes is
exact: *this gate opens the run, and the run's results directory starts empty*. It still writes nothing
into that directory, which is a different statement and stays pinned.

So the run below is the first thing in this repository that a Java product could do at all.

```text
$ ./javademo.sh test accept
[06:27:37] ==> accept: running the lab-based suites (unit + report)
> Task :test

BUILD SUCCESSFUL in 9s
[06:27:48]  OK per-module results: merged 1 file from 1 of 1 declared source dirs: 1 copied unchanged, carrying no parentSuite
[06:27:48]  OK allure results written to build/reports/allure-results
[06:27:48] ==> no local allure CLI; rendering the allure HTML report via docker (single-file)
[06:27:48]  OK allure HTML report: build/reports/allure-20260908-062748.html
```

### How JUnit XML gets into the report, and the word that does nothing

`report.merge` is a list of directories other steps already wrote. Gradle is told to put its JUnit XML in
a flat `build/junit-xml/`, the report step copies what it finds there into the shared Allure results, and
Allure's own JUnit reader does the rest.

Read that merge line again, because it is the honest half:

> merged 1 file from 1 of 1 declared source dirs: **1 copied unchanged, carrying no parentSuite**

`parent_suite: "Java"` is declared right above `merge:` in the taxonomy - and it did not apply. Tagging a
result with a parent suite means editing an Allure result JSON; a JUnit XML is not one, so it goes through
the copy branch untouched and reaches the report under whatever suite its own format names
(`demo.CalculatorTest`). The line says so in as many words. It used to say `per-module results merged
(parentSuite=Java)` for this exact case, which was a sentence about an intention rather than a result -
[what the merge reports](../../with-what/test-levels/#what-the-merge-reports-and-what-it-will-not-do-to-your-files)
is where that was taken apart.

So: **`parent_suite:` is for merged Allure results, not for foreign formats.** Nothing warns you, because
nothing is wrong - it is simply a key that does not reach the files a Java product actually has.

### A red Java test arrives red

Same command, one assertion broken in `Calculator.mul`:

```text
CalculatorTest > multiplies() FAILED
    org.opentest4j.AssertionFailedError at CalculatorTest.java:8
3 tests completed, 1 failed

[06:27:22]   ! accept is RED (unit failed (rc 1) - the product's own runner returned this rc; the
              kernel did not run a suite here and cannot say whether one ran at all, report passed)
```

Read what the kernel does **not** say there. It does not say the suite ran and reported failures, because
it did not run one - it called a Python callable and got a number. The sentence it uses instead is the
`impl:` gate's own, and [why it is that sentence](../../with-what/test-levels/#what-the-kernel-says-about-your-runner-and-what-only-you-can-say)
is a measured story on the test levels page.

### A build that never reached the tests

And this is the half only the product has. From outside, a compiler error and a failing assertion are the
same `rc 1`. From inside the runner they are not, because the runner knows that `:test` writes XML and
that its absence after a non-zero rc means the task never ran. The kernel offers a marker file for exactly
that and guesses nothing without one - the kernel exports a path in `SIMPLON_SETUP_FAILED` before every
gate, and a file written there names the stage that broke:

```python
from simplon.tasks.testrun import SETUP_MARKER_ENV

rc = _gradle("test")
if rc != 0 and not list(results.glob("TEST-*.xml")):
    with open(os.environ[SETUP_MARKER_ENV], "w", encoding="utf-8") as fh:
        fh.write("gradle build (:test never ran)\n")
return rc
```

The variable is set for every gate and holds a path, so its presence says nothing - what carries the
claim is the file. [The seam, and why the name stays as it
is](../../with-what/test-levels/#the-variable-is-a-path-and-it-is-always-set), on the test levels page.

With a deliberate type error in `src/main/java/demo/Broken.java`:

```text
/work/src/main/java/demo/Broken.java:5: error: incompatible types: String cannot be converted to int

[06:27:34]   ! per-module results: nothing merged: 0 of 1 declared source dirs present,
              missing: build/junit-xml
[06:27:36]   ! accept is RED (unit setup failed (gradle build (:test never ran), rc 1) - the suite
              never ran, so this says nothing about the product, report passed)
```

Three sentences, and none of them is about the product. The merge says nothing was merged **and why**; the
gate says the suite never ran and whose word that is; the archive that comes out is empty rather than
plausible.

### The numbers, read out of the archive

Three runs, one after another, and this is what came out of each report:

| run | rc | `widgets/summary.json` | `verdict` |
|---|---|---|---|
| green | 0 | `{"failed":0,"broken":0,"skipped":0,"passed":3,"unknown":0,"total":3}` | `passed` |
| one assertion broken | 1 | `{"failed":1,"broken":0,"skipped":0,"passed":2,"unknown":0,"total":3}` | `failed` |
| compiler error | 1 | `{"failed":0,"broken":0,"skipped":0,"passed":0,"unknown":0,"total":0}` | `setup-failed` |

Three, not four: there is no pytest gate in this product padding the count with its own `assert True`.

{{< callout type="warning" >}}
**Do not `grep` that report.** The archive is a single 2.6 MB HTML file with every data file embedded as
`d('<path>','<base64>')`, so `grep -c CalculatorTest` answers **0** on the green report above - which has
three of them - and **0** on the empty one. A search that cannot tell a full archive from an empty one is
not evidence about either, and reading it that way has already produced one wrong measurement here.
Decode the payloads and read `widgets/summary.json`.

The related question is worth measuring rather than assuming: **are those numbers this run's?** They are
now. A report used to be able to show an *earlier* run's results, because a runner that wrote nothing left
the previous run's XML lying in the merge source directory and the merge picked it up
([simplon#70](https://github.com/marcozwyssig/simplon/issues/70)). Checked on the three runs above: each
archive's own `time.start` falls inside its own run's window, and the compiler-error run reports `total: 0`
where the run before it reported `total: 3`.
{{< /callout >}}

## release

The tag is the version and the guard is the kernel's, and neither of those has anything to do with the
language. `release:tag` is placed in javademo's manifest with one line and no `impl:` of its own, and it
behaves exactly as it does for a Python product - which the chapter can show, because it refused:

```text
$ ./javademo.sh release tag v0.1.0
[06:25:33]   ! could not fetch from origin, so origin/main may be out of date. The guard below reads
              what is here; a stale ref can only make it refuse too much, never too little
[06:25:33] ERR there is no origin/main here, so the question 'main carries this commit' has no answer
              - and nothing was cut. Add the remote and push main first, or point origin/HEAD at the
              branch releases really are cut from (`git remote set-head origin -a`)
```

`git tag` afterwards lists nothing. What the guard checks, and what it deliberately does not, is in
[Cutting a release](../../how/releasing/).

**What is different for a Java product is what gets published, not how.** A wheel goes to PyPI because
`pyproject.toml` says so; a jar goes wherever your build tells it to. The kernel's two publishing tasks -
`release:artifact` for a directory a pipeline pulls, `release:asset` for files a person clicks - are the
same for both, and both read a manifest section javademo does not declare. Rows 8 and 9 say *derived* for that
reason and not because anything is missing.

## deploy

**Same answer as the Python chapter, and it is the state of the kernel rather than an omission here.**

What exists is the local host. javademo's `deploy up` runs the jar its own `build jar` produced, in a JRE
container on the machine you typed it on:

```text
$ ./javademo.sh dev deploy up
[06:25:34] ==> running build/libs/javademo.jar in eclipse-temurin:25-jre on this host
javademo: 2 + 3 = 5
```

One task body, one `docker run`, and that is the whole deploy story. The runtime image is a JRE and not
the JDK the build ran in - what ships is the jar, and the thing that runs it is not the thing that made
it - and it goes through the same pin gate as the build image.

What does not exist is everything past that host. `deploy` is one of the two ribs the catalogue draws
empty on purpose: the group name, the env-first gate, and no tasks at all.
[simplon#5](https://github.com/marcozwyssig/simplon/issues/5) is where that decision is open, and
[the two empty ribs](../../with-what/phases/#the-two-empty-ribs) is why leaving them empty is the expensive
choice rather than the lazy one.

## docs

`docs:render` is the AsciiDoc side - docToolchain in Docker, HTML and PDF out. The Python chapter labels
it *derived* and says in as many words that the page has not seen it work. **This one has:**

```text
$ ./javademo.sh build docs
[06:25:35] ==> rendering docs via docToolchain (generateHTML + generatePDF) in Docker -> build/docToolchain/
> Task :generateHTML
Converting /project/src/docs/manual.adoc
> Task :generatePDF
Converting /project/src/docs/manual.adoc

BUILD SUCCESSFUL in 45s
[06:26:21]  OK docs rendered -> build/docToolchain/ (html5/ + pdf/)
```

Two files come out - `build/docToolchain/html5/manual.html` and `build/docToolchain/pdf/manual.pdf` - and
the product declared exactly two things to get them: `doctoolchain_version: "v3.5.0"` in the manifest, and
a `docToolchainConfig.groovy` naming its input. The version key goes through the same pin gate as
everything else on this page.

{{< callout type="warning" >}}
**Order matters here, and on a fresh checkout it bites.** `docs:render` runs its container as root, on
purpose and for a documented reason. Gradle, in this product, runs as the caller. On a tree where
docToolchain went first, `build/` and `.gradle/` are then root-owned and the next Gradle run dies:

```text
> Could not open file hash cache (/work/.gradle/8.14.3/fileHashes).
   > Cannot create directory '/work/.gradle/8.14.3/fileHashes'.
```

Measured both ways on this machine: on a fresh tree, `build docs` then `build jar` gives **rc 1**; with
`build jar` run first, so that `build/` and `.gradle/` already belong to the caller, the sequence
`build jar` -> `test accept` -> `build docs` -> `test accept` gives **rc 0** four times. The failure at
least names the path it could not create, which is more than most of this class of problem manages - but
a Java product that runs both in CI has to put the build first, and nothing tells it so.
{{< /callout >}}

The Hugo side, `docs:site`, is the other documentation command and reads a `site:` section javademo does
not declare - row 13, *derived*. Which of the documentation commands produces what is
[a table in the examples](../examples/#8-publish-the-documentation).

## What this chapter does not repeat

Each of these is told once, elsewhere, and told properly:

- the same loop with a Python product underneath it - [A Python product, end to end](../case-python/)
- what a gate is, how a level is declared, and how a non-pytest runner attaches -
  [Test levels](../../with-what/test-levels/)
- the five outcomes a gate can report, and which two of them are statements about the product -
  [the Python chapter's `test` section](../case-python/#test)
- why the tag is the version and what the release guard refuses - [Cutting a release](../../how/releasing/)
- why `deploy` and `monitor` are empty - [The five phases](../../with-what/phases/)
- getting a product to exist in the first place - [Getting started](../../how/getting-started/)
