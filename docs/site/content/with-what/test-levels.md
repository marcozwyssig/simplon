---
title: "Test levels"
weight: 3
aliases:
  - "/building/test-levels/"
---

## Look it up

A **level** is one entry under `suites: gates:`, and this chapter is what the keys in it mean.

| key | on a gate | what it decides |
|---|---|---|
| `name` | required | the level's name, and what `with: { name: ... }` pins on the command |
| `suite` | one of three | a pytest directory the kernel runs itself |
| `impl` | one of three | [an opaque body](#an-impl-gate-is-opaque-and-says-so): your runner, your verdict |
| `command` | one of three | [a command in your own tree](#a-gate-may-name-a-command-in-your-own-tree) |
| `junit` | optional | where the runner left its JUnit XML, [relative to `reports`](#where-your-runner-put-its-results) |
| `results` | optional | [`clear` or `append`](#order-and-who-clears) - who empties the allure archive |
| `args` | optional | whether the gate forwards the caller's trailing arguments |
| `preamble` | optional | [a callable run before the suite](#hooks-precondition-preamble-and-the-one-rule-that-governs-them) |
| `announce` | optional | the line printed when the level starts |

Beside `gates:` the section takes `reports:` (where the whole report tree lives, default
`tests/reports`), `filtered_results:` (default `allure-results-filtered`, see [Exploratory runs are
quarantined](#exploratory-runs-are-quarantined)), `precondition:` and `report:`.

Three questions this chapter answers, if one of them is yours:

- *How do I attach a runner that is not pytest?* [`suite:` against `impl:`](#suite-against-impl---and-this-is-how-you-attach-gradle).
- *Why does my level report green when nothing ran?* [When a level does not exist](#when-a-level-does-not-exist).
- *What do I have to write to add one?* [Checklist for adding a level](#checklist-for-adding-a-level).

---

A gate is a command that instantiates a task - the [same model as everywhere
else](../../how/task-and-command/) - and the task is `test:gate`. What makes the test half of the loop worth its
own chapter is that one body backs *every* level a product has, and the differences between the levels
are data in a manifest section rather than code.

```yaml
groups:
  test:
    commands:
      unit:   { task: "test:gate", with: { name: "unit" },   help: "Run the unit suite." }
      system: { task: "test:gate", with: { name: "system" }, help: "Run the system suite, against the lab." }
      ui:     { task: "test:gate", with: { name: "ui" },     help: "Run the browser journeys." }
      all:    { task: "test:accept", help: "Every level in order, then the report." }
```

Four commands, two bodies. What each level actually *is* comes from the `suites:` section.

## The `suites:` section

```yaml
suites:
  reports: "test/reports"
  precondition: "orchestrator.health:cluster_ready"

  gates:
    - name: "unit"
      suite: "test/unit/python"
      junit: "junit-unit.xml"
      results: "clear"
    - name: "system"
      suite: "test/system/python"
      junit: "junit-system.xml"
      results: "append"
      args: true
      preamble: "orchestrator.lab:ready"
      announce: "system gate: the dataplane suite against the running lab"
    - name: "ui"
      impl: "orchestrator.journeys:run"

  report:
    merge: ["a/build/allure-results", "b/build/allure-results"]
    parent_suite: "Unit"
```

Every one of those keys is validated when the section is read, loudly and with the offending key named,
rather than surfacing minutes later as a pytest run against a path that does not exist. A missing section
is itself the first error:

> sample.yaml: the 'suites' section is missing or is not a mapping

`reports` is where the whole report tree lives. It may be declared and otherwise defaults to
`tests/reports` - beside the suite rather than under the product root, because the outputs of a test run
belong with the tests and a root directory called `reports/` says nothing about what produced it. The
example above declares it anyway, which is what a product whose outputs belong elsewhere does; an EMPTY
`reports:` is refused rather than read as a request for the default. `filtered_results` may be declared
and otherwise defaults to `allure-results-filtered`; what it is for is
[further down](#exploratory-runs-are-quarantined).

## `suite:` against `impl:` - and this is how you attach Gradle

Every gate declares **exactly one** of three keys, and the choice is the whole answer to "how do I run
something that is not pytest".

| | `suite:` | `impl:` | `command:` |
|---|---|---|---|
| what it names | a pytest root, relative to the product | a `module:function` the kernel calls | a command in your own tree, as you type it |
| who owns the argv | the kernel | you | your manifest, once, in that command |
| what the kernel does | makes the level's venv, clears or appends the shared results, runs pytest with the allure and junit flags, streams it | calls it, takes its return value as the exit code, and nothing else | runs it the way the CLI runs it - its `task:`'s body with its own `with:` pinned - and takes the exit code, and nothing else |

A `suite:` gate is the case where the kernel knows the runner. It builds the argv itself -
`<python> -m pytest --alluredir=<results> --junit-xml=<junit> <extra>` - runs it with the level's own
directory as the working directory so that its `conftest.py` loads, and writes into the shared results
tree that the report step later merges and renders.

An `impl:` gate is the case where it does not, and that is the seam a Gradle build, an npm suite, a
browser journey runner or a homegrown harness comes in through. **You do not teach the kernel Gradle.**
You write an ordinary task body that shells out to it and returns its exit code, and you declare a gate
that names that body:

```python
from simplon import context
from simplon.run import run


def integration() -> int:
    """Run the JVM integration suite through the project's Gradle wrapper."""
    root = context.current().root
    return run(["./gradlew", "--no-daemon", "integrationTest"], capture=False, cwd=str(root)).rc
```

```yaml
gates:
  - name: "integration"
    impl: "orchestrator.jvm:integration"
```

The kernel sequences that level with the others, honours the section-level precondition ahead of it, and
folds its return code into the run's verdict. What it does not do is pretend to understand it.

Declaring two of them, or none, is refused rather than guessed at:

> sample.yaml: 'suites.gates[0]' ('unit'): declare exactly one of 'suite' (a pytest root), 'impl' (a
> product-owned runner) or 'command' (a command in this product's own tree), not several and not none

### A gate may name a command in your own tree

`impl:` asks for a Python body, and a product whose test runner is a containerised toolchain has none to
offer. `ctest`, `dotnet test` and `gradle test` reach it through `toolchain:run`, which makes them
**commands**: declared once in the manifest with the image, the argv and the caches pinned, and typed as
`./cppdemo.sh build unit`. A gate names that command
([simplon#106](https://github.com/marcozwyssig/simplon/issues/106)):

```yaml
gates:
  - name: "unit"
    command: "build unit"          # what a person types, and what the gate reports on
    preamble: "build compile"      # the build that has to succeed first
    results: "clear"
```

The kernel resolves it the way the CLI does - the body the command's `task:` names, called with that
command's own `with:` pinned - so the image and the argv are stated **once** and the verdict is about the
command a person actually runs. Nothing is copied into the `suites:` section, so there is nothing there
to drift.

**And `preamble:` is why this is a gate kind rather than a convenience.** Measured on a C++ product:

```text
$ ./cppdemo.sh build compile        # a deliberate type error
error: cannot initialize a variable of type 'int' with an lvalue of type 'const char *'
rc 2
$ ./cppdemo.sh build unit           # ctest, over the binaries the failed compile did not replace
100% tests passed, 0 tests failed out of 3
rc 0
```

Three passing tests reported for a product that does not compile, and nothing could see the pair, because
neither half was a gate. Named as a gate's setup, the build runs first and a non-zero return code ends
the level **before the test command runs at all**:

> unit: setup failed (preamble 'build compile', rc 2) - 'build compile' failed, so 'build unit' never
> ran - which is what naming it here is for: a test command over the artefacts a failed build left
> standing reports the last good result and calls it green

That is the rule a pytest gate's preamble has always had, and it is the true sentence here too: the tests
did not run, so the run has learned nothing about the product. A gate's `precondition:` names a command
on a command gate as well - a product with no Python in it must not have to write a Python body in order
to reach a hook.

**The rc a command gate folds into its verdict is the container's own, and the tools disagree about it.**
The kernel interprets nothing, so what reaches the verdict is whatever the tool chose: a failing `ctest`
run exits **8**, `dotnet format --verify-no-changes` exits **2** on a formatting fault, `gradle test` and
`mypy` exit 1. Non-zero is the whole rule; anything comparing to `1` reads two of those four as a pass.

What is refused, and only when the gate actually runs, because deciding it needs the parsed manifest:

> 'suites.gates.unit.command': 'build ctest' is not a command in this product's tree (declared: build
> compile, build unit)

> 'suites.gates.unit.command': 'build all' plans other commands and runs no body of its own, so there is
> no single rc for a gate to report - name one of the commands it plans

> 'suites.gates.unit.command': 'build unit' pins imag with `with:`, which
> simplon.tasks.toolchain:run_toolchain does not take (it takes: argv, caches, env, extra, image,
> network, workdir)

That last one is the calling convention in a refusal, and it is the one `simplon.cli._bound` already
makes: a gate runs a command with what the manifest pinned and nothing else, so a `with:` key naming no
parameter is refused by name rather than arriving as a `TypeError` three frames down. A parameter the
body *requires* and no `with:` key pins is refused the same way, pointing at the block to edit -
`toolchain:run` has none, because every one of its parameters carries a default, so what an unpinned
`image:` gets instead is the toolchain's own diagnosis:

> build unit: no `image:` - a toolchain command names the image it runs in

**Read the first two words.** The message names the command a person types, not the coordinate behind
it, and that is what the gate hands the body: a `toolchain:run` command reads exactly one thing off a CLI
context, the path of the command it is running, and a gate knows that from the manifest. It hands over
that and nothing else ([simplon#136](https://github.com/marcozwyssig/simplon/issues/136)). A body
reaching for the rest of a Click context - `args`, `params`, `obj` - is asking a gate for a command line,
and a gate has none, so it is told so by name instead of being handed an invented empty one.

**The one command a gate may never name is the one that runs the gates:**

> 'suites.gates.unit.command': 'test accept' is the command that RUNS the gates, so a gate naming it
> would run itself until the interpreter stopped it - name the command whose rc this level is about
> instead

Until si#136 that loop was closed only as a side effect - `test:gate`'s body takes a CLI context, and
every context-taking body was refused - which also meant the kind could not reach `toolchain:run` at all,
and the case both the [C++](../../what/case-cpp/) and the [.NET](../../what/case-dotnet/) chapters rest
on did not run. The refusal now says what it is about.

### An `impl:` gate is opaque, and says so

Because the kernel only calls an `impl:` gate's runner for the return code, three keys make no sense on
one, and declaring them **fails** rather than being quietly dropped:

> sample.yaml: 'suites.gates[2]' ('ui'): an 'impl' gate cannot declare 'junit', 'args' - the kernel only
> calls its runner for the rc

A `command:` gate is opaque in the same way and shares two of those three. `preamble` is the key that
parts them: inert on an `impl:` gate, and the point of the kind on a `command:` one.

`results` used to be on that list, and taking it off is worth the sentence. The argument for refusing it
was real: an `impl:` gate carrying `results: clear` satisfied the "exactly one gate clears" rule below
while **nothing ever actually cleared**, because the clear hung on the pytest branch and an `impl:` gate
returns before it. A key accepted and inert is worse than one refused.

But the repair was on the wrong side. The clear could hang on nothing else, so a product whose only test
runner is its own could write no loadable `suites:` section at all - measured on a Java product with no
Python in it: both spellings refused, no report, and the way out was to ship a pytest gate holding
`assert True` purely to own the directory, at 29 MB of suite venv and an archive that counted four tests
where the product has three. So the inert half was fixed instead: an `impl:` gate honours the clear now,
and declaring it says exactly what it does - **this gate opens the run, and the run's results directory
starts empty**.

It still writes nothing into that directory. That is a different statement, and it stays pinned: a fix
that let the kernel invent a result for a runner it cannot see would have moved this defect rather than
removed it.

If your non-pytest runner produces results of its own - allure's or anything allure reads - name the
directory it wrote them into on the gate, with `results_from:`. That is the next section.

### Where your runner put its results

A gate may name the directory its own runner wrote results into
([simplon#133](https://github.com/marcozwyssig/simplon/issues/133)):

```yaml
gates:
  - name: "unit"
    command: "build unit"                # or impl:, or suite:
    results_from: "build/test-results"   # where THIS level's runner wrote
    results: "clear"
```

After the runner has run, the kernel merges that directory into this run's Allure results and renders it
with everything else. Nothing about the merge is new - `simplon.tasks.allure.merge_results` has been
technology-agnostic since it was written, and a product reached it by writing a task body in Python that
called it. **That was the gap: the capability was real, undeclared, and reachable only by writing the
Python the manifest exists to avoid.**

`results` and `results_from` are two different statements and it is worth reading them together once.
`results: clear` says *whose run this directory belongs to*; `results_from:` says *where this level's
results came from*. The first is about ownership, the second about a source, and a gate commonly carries
both.

**It is legal on every kind**, for the reason `results:` is: the mechanism does not vary - a directory is
merged and the contribution is checked - so there is nothing to refuse on one kind and allow on another.
A `suite:` gate rarely wants it, because the kernel already points `--alluredir` at the shared results
directory, but rarely wanting something is not the same as being unable to say it.

**What the report reads, measured rather than assumed.** Raw Allure `*-result.json`, JUnit XML and a
`dotnet test` TRX file all render out of ONE results directory, with no conversion and no second
directory. Driven on 2026-09-09 against the kernel's pinned `allure-docker-service:2.44.0`: two results
from `pytest --alluredir`, three from `ctest --output-junit` and one from `dotnet test --logger trx`,
merged together, rendered as `total: 6` across three suites. The image ships a `junit-xml`, an `xunit-xml`
and a `trx` plugin beside the Allure reader.

Two details from the same measurement, because they change what you should expect:

- **ctest names its suite `(empty)`.** `ctest --output-junit` writes `<testsuite name="(empty)">`, so its
  cases arrive under a suite of that name. `parent_suite:` cannot improve it - it acts on Allure raw
  results only, which is [what the merge will not do to your
  files](#what-the-merge-reports-and-what-it-will-not-do-to-your-files);
- **the .NET SDK image ships a TRX logger and no JUnit one.**
  `dotnet test --logger "trx;LogFileName=results.trx"` needs no `PackageReference` at all; `--logger
  junit` answers `Could not find a test logger with AssemblyQualifiedName, URI or FriendlyName 'junit'`
  and exits 1. So a .NET level reaches the report through TRX, or through a `JunitXml.TestLogger`
  reference it adds itself.

#### A level that contributed nothing is red

This is the half the key exists for. **An Allure report rendered with a level missing looks exactly like
one where the level passed**, so a gate that declared where its results land and produced none of them is
red, whatever its runner's exit code says:

> unit: failed (rc 1) - 'build/test-results' contributed no results to this run (nothing merged: 0 of 1
> declared source dirs present, missing: …/build/test-results) - and an Allure report rendered with a
> level missing looks exactly like one where that level passed, which is why an exit code of 0 is not
> enough here

The commonest way to meet it is not a broken runner. The kernel's own C++ profile runs
`ctest --test-dir build --output-on-failure`, which prints `100% tests passed, 0 tests failed out of 3`
and writes **no results file**: declare `results_from:` without adding `--output-junit` to the command and
you get exactly the line above. That pair is driven in `tests/test_suites_results_from_e2e.py`, with the
archive read back out of its own embedded data.

**And a file arriving is not the same as a level having run.** `ctest -L <a label nothing carries>`
exits **0**, prints `No tests were found!!!` and - asked for `--output-junit` - writes a perfectly
well-formed file with `tests="0"` in it. `dotnet test --filter` over a filter that matches nothing does
the same. A check that counted files would be green over that, so the kernel counts **test cases**:

> unit: failed (rc 1) - 'build/test-results' contributed no results to this run (merged 1 file from 1 of
> 1 declared source dirs: 1 copied unchanged, carrying no parentSuite; not one of the 1 file merged holds
> a test case - a runner whose selection matched nothing writes exactly this and exits 0) - …

It counts them in the shapes it demonstrably meets - the JUnit family, xunit's own XML, and TRX - and **a
format it cannot read counts as a contribution**. Allure reads more formats than this kernel knows about,
and calling a level empty because the kernel could not parse its evidence would be a false red invented
by the checker, which is the same defect pointing the other way.

**And the results have to be this run's.** Nothing on the kernel's side of the seam ever empties a
product's own results directory, so the merge is given the instant the gate's runner started and leaves
anything older where it is - si#70's rule, at gate scope. A runner that wrote nothing therefore does not
quietly contribute last week's results, and the line says which case it is:

> unit: failed (rc 1) - 'build/test-results' contributed no results to this run (nothing merged: 1 of 1
> declared source dirs present; 1 file older than this run left behind, as it is the previous run's
> (…/build/test-results/ctest.xml)) - …

Nothing is harvested for a gate that never ran its body - a failed `precondition`, a failed `preamble`, or
a runner that dropped the setup marker. In all three the run learned nothing about the product, and
merging whatever was lying in the directory would invent evidence.

`report.merge` is unchanged and still there: it is the section-level list of directories **other steps**
wrote, merged at the end. A directory a gate names in `results_from:` does not need repeating in it.

**And neither key may name the results directory itself.** `results_from:` means *where your runner
wrote*, not *where the results end up*, and pointing either key at the kernel's own results directory used
to end the step in a `shutil` traceback about copying a file onto itself. It is now refused by name, and a
gate that named it is red rather than green - because those files are already at the destination, so
nothing travelled and none of them is evidence this level produced:

> unit: failed (rc 1) - 'tests/reports/allure-results' contributed no results to this run (nothing
> merged: 0 of 1 declared source dirs present; 1 declared source dir is the destination itself and was not
> merged (…/tests/reports/allure-results) - those files are already at the destination, so nothing
> travelled and none of them counts as this merge's evidence. Name the directory the runner writes into,
> or drop the key) - …

### What the kernel says about your runner, and what only you can say

Opacity cuts both ways, and the second way is the one that produced a bug. Because the kernel sees a
return code and nothing else, a red `impl:` gate reports **the return code and says so**:

> unit: failed (rc 1) - the product's own runner returned this rc; the kernel did not run a suite here
> and cannot say whether one ran at all

It used to borrow the sentence written for a pytest gate - *the suite ran and reported failures* - and
that sentence was measured against a Gradle build with a deliberate compiler error
([simplon#65](https://github.com/marcozwyssig/simplon/issues/65)): nothing compiled, no test executed, no
JUnit XML was written, and the log line, the stamp and the archive's Environment widget all said the suite
had run and reported failures. *Not knowing* is a thing a record may say. It is not a licence to say
something else.

**Which leaves the half only you have.** From out there a compiler error and a failing assertion are the
same `rc 1`; from inside your runner they are not. So the setup marker is open to an `impl:` gate exactly
as it is to a pytest suite ([simplon#59](https://github.com/marcozwyssig/simplon/issues/59)): the kernel
puts a path in `SIMPLON_SETUP_FAILED` before it calls you, and a file written there names the stage that
broke. Write it only when you *know*, and the gate reports `setup-failed` with your word in it:

```python
import os
from simplon.tasks.testrun import SETUP_MARKER_ENV


def integration() -> int:
    """Run the JVM integration suite, and say when the build never reached it."""
    root = context.current().root
    results = root / "build" / "junit-xml"
    shutil.rmtree(results, ignore_errors=True)          # this run's evidence, not the last run's
    rc = run(["./gradlew", "--no-daemon", "integrationTest"], capture=False, cwd=str(root)).rc
    if rc != 0 and not list(results.glob("TEST-*.xml")):
        # gradle stopped before :test - a statement about this lab, not about the product
        with open(os.environ[SETUP_MARKER_ENV], "w", encoding="utf-8") as fh:
            fh.write("gradle build (:test never ran)\n")
    return rc
```

> unit: setup failed (gradle build (:test never ran), rc 1) - the suite never ran, so this says nothing
> about the product

The claim wins over your return code, including over a green one: a runner that reports a broken setup
and still returns `0` is a runner whose green means nothing. And a runner that writes nothing gets
`passed` or `failed` and **no invented stage** - the kernel does not guess a setup failure out of a
non-zero number, because a guessed one is the same false statement pointing the other way.

### The variable is a path, and it is always set

`SIMPLON_SETUP_FAILED` is exported before **every** gate the kernel calls, red or green, and removed
again afterwards. Its presence therefore says nothing: `[ -n "$SIMPLON_SETUP_FAILED" ]` is true on every
run of every gate, and a runner that reads it as a flag has read a question as an answer. What carries
the claim is the **file**. The kernel deletes it on the way in - so a marker left by an earlier run can
never be read as this one's verdict - and only a runner that writes it has said anything at all.

The name is the one part of this seam that reads like a boolean while holding a slot to write into. It
stays as it is: it is in a released version and on this page, and a rename would break a documented seam
to buy what this paragraph buys. **Write the file; do not test the variable.**

Which also means your runner need not be Python. The variable is inherited by whatever the gate spawns,
so a shell or a Gradle wrapper says the same thing the same way:

```bash
./gradlew --no-daemon integrationTest
rc=$?
if [ "$rc" -ne 0 ] && ! ls build/junit-xml/TEST-*.xml >/dev/null 2>&1; then
    printf 'gradle build (:test never ran)\n' > "$SIMPLON_SETUP_FAILED"
fi
exit "$rc"
```

**And a gate that writes nothing stays silent - the kernel does not offer this seam at run time.** The
sentence a red `impl:` gate prints already says what the kernel does not know; appending *and here is
how you could tell me* would put an advertisement in the log line, the stamp and the archive's
Environment widget, on every red run, for a reader who is usually a CI system. The place to find this is
a page, and this is the page.

## Order, and who clears

The `gates:` list is a list because **order is meaning**: the gates run in the order they are declared,
and that is the only place the order is stated.

Exactly one of them clears the shared results directory; the rest append into it. That is the whole of
the clear-versus-append rule, and it is held as data rather than as an `if` in the kernel, because which
level runs first is a statement about a product's own test tree.

Three ways to get it wrong, all three refused at load:

> sample.yaml: exactly one gate must declare results: clear (the first one to run); got ['unit', 'system']

Two clearing gates means the second silently deletes what the first wrote.

> sample.yaml: exactly one gate must declare results: clear (the first one to run); got none

No clearing gate means every run appends onto the last one, forever, and the archive stops describing a
run at all.

> sample.yaml: 'system' clears the shared results but is not the FIRST gate; a later clear deletes what
> the gates before it wrote

The clearing gate must be the one that runs first, for the same reason.

Note what "clear" clears: this run's results directory and the transient render directory, once, at the
start. It does not touch the archived HTML reports of previous runs - those are timestamped files and the
point of keeping them.

## Exploratory runs are quarantined

One gate may declare `args: true`, and that gate's command forwards whatever you type after it straight
to pytest:

```text
$ ./myctl.sh test system -k test_forwarding_survives_restart
```

That turns a twenty-minute gate into a one-minute answer, and it is the single most useful thing about
the test half of the loop. It is also, by definition, a **partial** run - so it must never touch the
canonical archive. Any run carrying extra arguments is redirected for its whole length into
`filtered_results`, gets its own junit file name and its own archive prefix, and leaves the last real
gate's archive exactly as it was. The kernel says so once, loudly, when it happens.

Consider what the two alternatives would have produced. Clearing the shared results and filling them with
one test's output leaves an archive that looks like a full gate and reports a single test. Appending
mixes two runs in one report. Both are green-looking artefacts describing something that did not happen.

At most one gate may take the arguments, and a second is refused:

> sample.yaml: at most one gate may declare args: true; got ['system', 'ui']

The reason is specific: both gates would receive the same `-k <expr>` verbatim, and an expression written
for one suite filters a different suite down to zero tests **while still reporting green**. A partial run
that does not look like one is the thing this whole section is built to prevent.

## Hooks: precondition, preamble, and the one rule that governs them

Three keys name a `module:function` the kernel resolves exactly the way it resolves a command's `impl:`
- except on a `command:` gate, where the gate's own two name a **command** instead, for the reason that
kind exists at all:

- `precondition` on the **section** - a fail-fast health verdict, run once before any suite work. A
  non-zero return aborts the run in seconds instead of wasting the whole collection, and nothing has been
  cleared, because nothing ran.
- `precondition` on a **gate** - the same, scoped to that level.
- `preamble` on a **gate** - the idempotent preparation that level needs (a converged inventory, a
  provisioned service, a settled forwarding plane). It runs inside the same keep-awake window as the suite
  itself, so a long convergence wait cannot idle-sleep the host out from under it.

{{< callout type="warning" >}}
**A hook must return an `int` on every path.** Including the path where it simply finishes.

This is not style. It is the difference between a gate that runs and a gate that reports success without
running.
{{< /callout >}}

Here is the whole chain, and every link in it is ordinary, defensible code.

A hook is a function a product wrote. An ordinary Python function that just does its work and reaches the
end of its body returns `None` - there is no `return` statement to notice missing, because falling off
the end of a function is not an error:

```python
def cluster_ready() -> None:
    """Wait until the cluster reports every node healthy."""
    wait_for(nodes_healthy, timeout=180)      # succeeded: no exception, no return
```

The kernel then asked the question every caller of a hook asks:

```python
rc = hook()
if rc != 0:
    return rc
```

`None != 0` is `True`. So a precondition that had just **succeeded** aborted its gate, and the gate
returned that `None` upward. The CLI's return-value coercion maps anything that is not an `int` to exit
0 - deliberately, because a body that returns a log line or a result object is a body written when the
return value could not matter, not a failure. The run therefore ended like this:

- the precondition passed;
- the suite never ran;
- the process exited **0**;
- and under `test:accept`, the report step then archived the *previous* run's results, because the gate
  that would have cleared them returned before it got that far.

**A test gate that skipped itself and called that a pass.** That is the one outcome a gate must never
produce, and every individual step on the way there was reasonable.

The fix is at the seam, not at the call sites. A hook is resolved through one function, so that function
now coerces what comes back into an exit code before anybody compares it to zero: a real `int` is the
verdict, and anything else - `None` included - counts as success rather than as an abort. It sits in the
one place because there are four call sites and they must not be able to drift apart; a hook is a hook
whether it is a section precondition, a gate precondition, a preamble or a gate's own `impl:`.

`bool` is excluded from "a real int" on purpose, and for the reason it is tempting: `return True` from
such a body means *success*, and `int(True)` is `1`, which is failure.

That coercion narrows the damage; it does not remove your obligation, and this is the part worth
carrying away:

- a hook that returns nothing on its **success** path is now merely sloppy - it reads as a pass, which is
  what it meant;
- a hook that returns nothing on a **failure** path reads as a pass too, and that one is still a gate
  reporting green over a broken precondition. No coercion anywhere can tell those two apart, because the
  information was never produced.

So: `return 0` when it is fine and a non-zero when it is not, on every branch, and annotate the function
`-> int` so a type checker can say something about it. A hook that raises instead is also fine - an
exception is loud and reaches the caller as a failure - but silence is not.

## Running them all: `test:accept`

`test:accept` chains every declared gate in order and then the report step, and returns a binary verdict
over all of them.

It does **not** fail fast. The point of the convenience is the full red/green picture and an archived
report either way, so a red level does not stop the ones after it - but a red level must surface as a
red exit code, and the summary names every level with its own return code so the one that failed is
visible without reading back through the log. The report step counts towards the verdict too: a run whose
archive silently failed to render is not a green run.

The one exception is the section-level `precondition`. An unhealthy environment aborts before any of it,
because collecting twenty minutes of failures against a cluster that is down tells you nothing you did
not already know.

## The report step

`test:report` runs no tests. It merges the result directories named in `report.merge` into this run's
results - tagging anything not already labelled with `parent_suite`, so a module's results group under one
heading - and renders the merged single-file HTML archive to a timestamped name.

Its verdict follows the [missing-tool rule](../rules/#a-missing-tool-is-not-a-failed-tool) exactly:

- **no render tool on the host at all** → a hint and green. The machine that runs the loop is not always
  the one that archives, and archiving must not itself be the reason a run is red.
- **a render tool that was there and failed** → red. That is not best-effort any more; it is a step that
  was asked to do something it can do and did not, and a run that silently ships no archive is
  indistinguishable from one that shipped a good one.

A typo in `report.merge` is caught at load rather than at merge time, because a missing directory is
deliberately *not* an error there - a standalone report still archives whatever is present - so a
stringified nonsense path would be skipped in silence:

> sample.yaml: 'suites.report.merge' holds a non-path entry: None

### What the merge reports, and what it will not do to your files

The merge says what it **did**, not that it was called
([simplon#64](https://github.com/marcozwyssig/simplon/issues/64)). It used to print
`per-module results merged (parentSuite=Java)` whatever had happened, and two different runs got that
identical sentence without having done what it claims:

> per-module results: merged 1 file from 1 of 1 declared source dirs: 1 copied unchanged, carrying no
> parentSuite; skipped 1 subdirectory allure would not read (…/build/test-results/test/binary)

> per-module results: nothing merged: 0 of 1 declared source dirs present, missing: …/build/junit-xml

Three things in that are worth reading off:

**`parent_suite` applies to allure raw results only.** Tagging means editing a `*-result.json`, so a JUnit
XML - or any other foreign format - is copied through untagged and reaches the report under whatever suite
its own format names. The line no longer claims otherwise.

**A declared source that is not there is a warning, not a failure.** Skipping it stays right - a standalone
report step archives what is present - but it is now named, because that is exactly the shape of a run
where a build stopped before writing anything.

**A subdirectory is skipped, and named.** Gradle's default `build/test-results/test/` holds `binary/`
beside the XML, and the merge used to hand every entry to `shutil.copy`, which raises `IsADirectoryError`
on a directory - so the standard layout of the most common non-pytest runner in existence crashed the
report step, and products worked around it by redirecting Gradle's report to a flat directory
([simplon#62](https://github.com/marcozwyssig/simplon/issues/62)). **That workaround is no longer needed.**
The choice between skipping, recursing and refusing was measured rather than argued: an allure results
directory is read *flat*, and a results dir holding `aaa-result.json` next to `sub/bbb-result.json` renders
`total: 1` with only the top-level suite. Recursing would copy bytes the renderer ignores; skipping is the
only one of the three that is true. If your runner writes attachments into a subdirectory, flatten them -
allure would not have read them there either.

## When a level does not exist

A command bound to `test:gate` whose pinned `name` matches no declared gate is a manifest typo, not a
runtime condition to limp along with, and the error lists what *is* declared:

> 'suites.gates' declares no gate 'sytem' (declared: unit, system, ui)

## A gate that is not a level: `test:release-notes`

Not every command under `test` is a suite. `test:release-notes` declares no gate, appears in no
`suites:` section and runs no runner. It asks one question about the repository - does the releases page
describe the releases the repository actually carries - and answers it out of `git tag`, `git log` and
the page's own `## X.Y.Z` headings. Its three values live in a
[`releases:` section](../../how/manifest/#releases---where-the-notes-live-and-from-when-they-are-complete), and
placing it is one line:

```yaml
groups:
  test:
    commands:
      release-notes: { task: "test:release-notes" }
```

**Why it is in `test` at all.** Its verdict is red or green and nothing else, which is what the phase
means, and `test:` is a group name, so [the placement rule](../../how/task-and-command/) puts it under `test` in
every product rather than leaving it to taste.

**Why it is not in `release`.** Folding it into `release:tag` was the obvious alternative - one command,
no bypass, exactly where the damage is. It is rejected because release notes are written *before* the
tag: the tag points at a tree that already carries them. A guard that only speaks when `release tag` is
typed speaks after every cheap chance to fix it has passed, and it would catch none of the pull requests
where the omission is actually made. The release being prepared has a measurable range already - it ends
at `HEAD` - so the same question is answerable on every push, and being answerable continuously is what
makes this a gate rather than a ceremony.

**It reports what it ruled on, green or red.** Every run prints the range each section answers for and
what `HEAD` resolved to:

```text
==> releases.md: 8 documented, 23 tagged, notes from 0.4.0, complete from 0.5.0
==> HEAD is eb671cc 'Merge pull request #137 from marcozwyssig/feat/129-init-reads-the-repository'
==>   v0.9.0     v0.8.0..v0.9.0  5 merges, 4 tickets, 4 named
==>   v0.10.0    v0.9.0..HEAD  11 merges, 12 tickets, 7 named
ERR the v0.10.0 section names 7 of the 12 tickets merged into v0.9.0..HEAD; missing: si#129, si#130
```

That second line is not decoration. The range is `<last tag>..HEAD` **of the state this run checked
out**, and a `pull_request` run checks out `refs/pull/N/merge` - your branch as merged with the base - so
a branch green on its own tip goes red the moment the base moves. Both readings are correct and neither
used to be said out loud, which is the only reason it read as a flaky gate.

**A run that ruled on nothing is red.** A floor above every release, a page whose headings stopped being
`## X.Y.Z`, a checkout with no tags - each leaves the gate with nothing to measure, and a green there is
a report that nobody looked. The tag-less checkout is diagnosed as the *checkout*: `actions/checkout`
fetches no tags unless you ask, so the message names `fetch-depth: 0` rather than blaming the page.

## Checklist for adding a level

1. Decide `suite:` or `impl:` - is this pytest, or is the runner yours?
2. Put it in `gates:` **in the position it should run in**. If it must run first, it is the one that
   carries `results: clear`, and the previous first gate stops carrying it.
3. A `suite:` gate needs its own `junit:` file name; an `impl:` gate must not declare one.
4. If the level's runner writes results of its own, name that directory with `results_from:` - and run it
   once with the results absent, because a level that contributes nothing must go red rather than render
   as a gap that looks like a pass.
5. Give it a `preamble:` if it needs the environment prepared, and a `precondition:` if it should abort
   early rather than fail slowly. Both return an `int` on every path.
6. Place the command: `{ task: "test:gate", with: { name: "<the gate name>" }, help: "..." }`.
7. Run it once on purpose against something broken, and check that the exit code is not 0. A gate is only
   worth having if it can go red.
