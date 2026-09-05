---
title: "The rules"
weight: 6
---

Everything else on this site can be derived. The command reference is read off the assembled
application; the manifest's shape is in the loader; the environment gate is in the dispatch. This
chapter cannot be derived from anything, and that is exactly why it exists.

These are the rules the kernel is designed by. Each one is here with the defect that forced it, because
a rule without its case is an opinion, and an opinion is the first thing somebody argues away at four in
the afternoon.

---

## A missing tool is not a failed tool

> Ein Werkzeug, das fehlt, ist nicht dasselbe wie ein Werkzeug, das gescheitert ist.
>
> *A tool that is missing is not the same as a tool that failed.*

A step whose tool is not installed reports a **hint** and exits zero. A step whose tool is installed and
*fails* is loud: an error on stderr and a non-zero exit code. Those are two different things, and a step
that collapses them into one has an answer that is wrong half the time.

The case that forced it was reported by a consumer connecting to the kernel for the first time
([simplon#6](https://github.com/marcozwyssig/simplon/issues/6)).

`render_report` archived Allure results, either through a local `allure` binary or through a container.
Its docstring justified never raising: *"a missing render tool leaves the raw results in place with a
hint, because archiving must not itself be the reason a run is red."* For a **missing** tool that is
right, and it stays right - not every machine that runs the loop is the one that archives.

But it returned `None` on *any* failure and warned, and the command around it returned zero either way.
So a run in which the container branch died looked exactly like a run in which it had succeeded: exit
code 0, no exception, nine raw result files sitting there - and no `allure-*.html` anywhere. A warning
was the only trace, and anyone measuring the run by its exit code, which is every CI system, learned
nothing.

**How long it stayed invisible: two releases.** Not because the defect was subtle, but because of who
could see it. The failure was in the *container* branch, and the two products already using the kernel
had a local `allure` binary - so they never entered that branch at all. The one consumer that would have
walked into it was the one that had not connected yet.

The fix keeps the original rule and adds the distinction it was missing:

- no render tool at all → hint, exit 0, exactly as before;
- a tool that ran and failed → `log.error` on stderr, non-zero exit code;
- the function still **never raises**. It returns an outcome object with two predicates - `ok` and
  `failed` - so a caller that ignores it is unaffected and a caller that cares can tell the two cases
  apart. An exception was considered and rejected: it would reach direct callers as an unhandled
  traceback, which is loud in the wrong way and in a place the caller cannot decide about.

The rule now shapes every kernel task that shells out to something. `docs:site` is the clearest case:
no Docker on the host is a hint and exit 0, because the machine that runs the loop is not always the one
that publishes the website. Docker present and no site produced is red. And note what that second case
has to include - Hugo exits 0 on an empty content tree or a `contentDir` pointing at nothing, so the
task wipes the destination before building and then checks that a home page exists. A build that
produces nothing is not a green build, whatever the tool's exit code says.

**The lesson underneath the rule:** the failure survived because the only consumer who could see it was
not there yet. Every branch that only some callers reach is a branch that is untested in practice, and
"nobody has complained" is evidence about your consumers, not about your code.

---

## A container that writes into a mount runs as `--user`

Any container that writes into a bind-mounted host directory is passed `--user uid:gid`. Not caution -
a measurement, and it has been measured from both directions.

**Direction one: an image running as a non-root uid that is not the caller's.** The same
[simplon#6](https://github.com/marcozwyssig/simplon/issues/6) report. `frankescobar/allure-docker-service`
runs as uid 1000; the kernel mounted the host's report directory at `/work` and let the container write
as its own uid. On a host whose uid is not 1000, Allure died with:

```text
java.nio.file.AccessDeniedException: /work/allure-report
```

Measured on host uid 5015237. The counter-check by hand with `--user "$(id -u):$(id -g)"` gave *"Report
successfully generated"*, exit 0, a 2.6 MB archive. So the container branch was broken on every machine
that is not the first account on its own system, and on most CI runners.

**Direction two: an image running as root.** Not obvious from the first, and it is worse, because it
*succeeds*. Measured while building this website: `hugomods/hugo` defaults to uid 0. A run without
`--user` wrote `build/website/index.html` owned by `0:0`, the caller's own `rm -rf build` came back
`Permission denied`, and a root-owned `.hugo_build.lock` was left behind in the **source** tree - enough
that the next run failed with `failed to acquire a build lock` even when *that* run passed `--user`
correctly.

One run without it poisons the working tree for the runs after it. And the reason `rm -rf` failed is
worth stating precisely, because it is not about who owns the files: unlinking an entry needs write
permission on the **directory** that holds it, and the container created those directories.

The rule lives in exactly one place, `docker.user_args()`, with both measurements in its docstring. It
started as a private helper in the Allure module and moved the moment a second task needed the same
argument for the same reason - because a convention restated in two modules is a convention that will
drift in one of them.

---

## The catalogue travels inside the package

The task catalogue ships **inside** the kernel's Python package, as package data, rather than sitting in
the repository and being found by walking up the tree.

The defect was found by a spike doing something nobody had done before: running the kernel the way a
consumer does.

`catalogue.py` resolved its own file with `parents[5]` - five directory levels up to the repository
root. That is precisely correct while the kernel is vendored inside a monorepo, and completely
meaningless once it is installed from PyPI: from `site-packages`, five levels up is somewhere else
entirely, and `load()` raised `FileNotFoundError`. The kernel could not read its own catalogue.

Nobody had noticed, because every test in the repository ran against the source tree via a `sys.path`
hack in `conftest.py`. There was no test that installed the wheel and used it as a consumer would - so
the one arrangement in which the defect existed was the one arrangement nothing exercised.

The fix moved `catalogue.yaml` next to the code that reads it, declared it as package data, and added
the test that had been missing: the only test in the repository that builds the wheel, installs it, and
uses the package the way a consumer would.

**The lesson underneath the rule:** *a tool never used in its own house rots unseen.* It is why the
kernel is a product of itself - its own `simplon.yaml` declares its own build, test and support
commands, assembled by the very kernel that repository builds. When a commit breaks the assembly, it
fails in the same round, not after a release.

---

## A group with no commands does not appear

Two questions that look like one, answered differently, and the difference is who made the promise.

- A group the **product's own tree** names and leaves empty is a **load error**, naming the group.
- A group only the **catalogue** offers, that the product's tree never mentions, is **silently dropped**
  from the assembled CLI.

The case: a product's `--help` rendered a sub-application for every catalogue group it had never filled.
`release` and `monitor` appeared in the listing as bare platform placeholders the product did not
implement. A user reading that help saw two capabilities the product did not have, and found out by
running one.

Both halves are needed and neither alone is right. Dropping every empty group would swallow a real
mistake - a product that declares a group and forgets to put anything in it has announced something it
does not have, and silence there is how you ship a menu entry that leads nowhere. Erroring on every
empty group would refuse to load any product that has not yet filled all six of the platform's slots,
which is every product on its first day.

Two details, both learned the hard way:

**Where the decision is made.** In `load()`, not in the merge. The merge only ever sees the new-form
half of a manifest that is still migrating, so pruning inside it broke a group filled through the *old*
form - which looked identically untouched from the merge's narrow view.

**What counts as empty.** The whole *subtree*, not the one path. `support` holds no direct command of
its own while `support.git` underneath it holds four; measured per path, the parent looks empty and gets
dropped, and its children have nowhere left to hang from.

Verified against a real product rather than a fixture: its actual entry point, run against a throwaway
environment holding the built wheel, reports `release` and `monitor` as unregistered commands while
everything it does implement still works.

A second defect of the same shape rode along in the same release. A flat-form manifest could declare
`import:`, make catalogue coordinates available, reference none of them, and load perfectly clean having
placed nothing at all - no command, no warning, no error. That is now a warning that names the likely
cause. *A mechanism that accepts something and does nothing is the shape of both defects,* and it is
worth looking for by name.

---

## A name collision breaks loudly

When a catalogue-placed command and a product's own command land on the same name with *different*
bodies, the loader stops and names both bodies. It does not pick one.

The case: a product redeclared `support install` with its own `task:`, where the catalogue's command
tree already placed one. The two bodies were the kernel's `oras` provisioning and the product's Colima
setup. The merge simply let the product's dictionary win, so the command resolved, the help text read
plausibly, and **the only proof of which body had actually run was what the host looked like
afterwards.**

That is the failure mode worth naming: not an error, not a warning, not even a wrong answer - a
*plausible* answer, with the evidence for it outside the program.

The rejection names both bodies by their real `module:function` rather than only the coordinate they
share, because `install` and `install` read identically while `simplon.tasks.hosttools:install` and
`orchestrator.host:colima` do not. A human cannot act on the first pair and can act on the second.

Refinement stays silent, because it is not a collision: pointing at the *same* task and changing the
help, the parameters or the pinned values is a product adjusting the platform's command, which is the
mechanism working. Deliberate replacement is available and has to be *said* - `override: true`, next to
the `task:` line - and an overriding node then stands alone rather than merging with the base's `help:`
and `params:`, because those describe the body that no longer runs.

This rule also decided where the command reference on this site comes from. The catalogue states the
**intent**; the assembled application is the **result**; between them lies this merge. A reference
generated from the catalogue would have described *both* colliding commands and said nothing about the
fact that only one of them runs. So the reference is read off the running application instead - and it
fails outright if the application does not assemble, which is a failure in the right place.

---

## A step runs `sys.executable`, not `python`

A planned step is spawned with the interpreter that is currently running, by absolute path. Not
`python`, not `python3`, and - where it can be avoided - not the product's shell launcher either.

Two problems, one fix.

**`python` is whatever `PATH` says.** It need not be the environment the caller was provisioned into,
and when it is not, the step runs under a different interpreter than its parent. That does not fail
where it happens. It surfaces three steps later as a missing dependency, in a step that has nothing to
do with the cause.

**A shell launcher is a bootstrap being asked to do something it is not for.** The launcher's job is to
create the environment, install the requirements and exec the module. By the time a plan is running all
of that has already happened and the process *is* that environment's Python - so spawning each step
through the launcher repeats the whole bootstrap once per step, and forces the product to know which of
`myctl.sh` and `myctl.cmd` the current host can execute.

That last part is what made it worth a change rather than a note. A product's Windows cell died on the
first run that ever reached it:

```text
WinError 193: %1 is not a valid Win32 application
```

because a POSIX launcher had been written into the step factory. A second product had hit the same thing
earlier and fixed it locally with a per-platform ternary. Two products, two ternaries, one question that
should not exist - and with the interpreter already running, there is nothing to choose.

One thing deliberately did **not** change: the identity stamp each step carries. It is what lets the
kernel verify that step *i* really is the step for plan leaf *i*, and losing it would take the plan tree
with it, and every subtree's `stop_on_failure` with that. **Changing how a step is spawned must not
change what it is.**

The launcher-based factory is still there, unchanged, for a product whose steps genuinely must redo the
bootstrap. That shape is rare, not wrong.

---

## What these have in common

Read them together and the same failure keeps appearing under different names.

**Four of the six are silence, not error.** A render that failed and reported success. A container that
wrote files nobody could delete. A catalogue that could not be found in the one arrangement nothing
tested. A collision that resolved to a plausible answer with the evidence outside the program. None of
them threw. All of them looked fine.

So the working rule the kernel keeps applying is: **a mechanism that accepts something and does nothing
is a defect, even when nothing is on fire.** An unused `import:`. An empty group in a menu. A `with:`
that names a parameter the body does not take. A task key that is read by nobody. Each of those is now a
load error or a warning, because a declaration that renders nowhere is worse than one that fails.

And underneath that, the reason these were found at all: every one of the six was found by *using* the
thing - a new consumer connecting for the first time, a spike running the kernel as a consumer does, a
Windows cell reaching a code path for the first time ever. Not one was found by reading the diff.
