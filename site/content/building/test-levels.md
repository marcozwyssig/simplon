---
title: "Test levels"
weight: 6
---

A gate is a command that instantiates a task - the [same model as everywhere
else](../task-and-command/) - and the task is `test:gate`. What makes the test half of the loop worth its
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

What is refused, and only when the gate actually runs, because deciding it needs the parsed manifest:

> 'suites.gates.unit.command': 'build ctest' is not a command in this product's tree (declared: build
> compile, build unit)

> 'suites.gates.unit.command': 'build all' plans other commands and runs no body of its own, so there is
> no single rc for a gate to report - name one of the commands it plans

> 'suites.gates.unit.command': 'build unit' needs image, which its `with:` does not pin - a gate has no
> command line to supply them on, so pin them there

The last one is the whole calling convention in a refusal: a gate runs a command with what the manifest
pinned and nothing else, because there is no command line for anything to arrive on. A body that takes a
CLI context is refused for the harder version of the same reason - and that is also what stops a gate
naming the command it is invoked as.

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

If your non-pytest runner produces allure results of its own, hand them to the report step through
`report.merge` instead. That is what that list is for: result directories other steps already wrote,
copied in and tagged with a parent suite so the merged archive groups them.

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

## Checklist for adding a level

1. Decide `suite:` or `impl:` - is this pytest, or is the runner yours?
2. Put it in `gates:` **in the position it should run in**. If it must run first, it is the one that
   carries `results: clear`, and the previous first gate stops carrying it.
3. A `suite:` gate needs its own `junit:` file name; an `impl:` gate must not declare one.
4. Give it a `preamble:` if it needs the environment prepared, and a `precondition:` if it should abort
   early rather than fail slowly. Both return an `int` on every path.
5. Place the command: `{ task: "test:gate", with: { name: "<the gate name>" }, help: "..." }`.
6. Run it once on purpose against something broken, and check that the exit code is not 0. A gate is only
   worth having if it can go red.
