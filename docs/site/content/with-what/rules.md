---
title: "The rules"
weight: 5
aliases:
  - "/building/rules/"
---

## The six, at a glance

| the rule | what it means in one line |
|---|---|
| [A missing tool is not a failed tool](#a-missing-tool-is-not-a-failed-tool) | A step that shells out has three outcomes, not two, and "not installed" is its own verdict. |
| [A container that writes into a mount runs as `--user`](#a-container-that-writes-into-a-mount-runs-as---user) | Whatever uid the image runs as is the uid that ends up owning your files. Pass `--user uid:gid`, always. |
| [The catalogue travels inside the package](#the-catalogue-travels-inside-the-package) | A package resolves its own data as package data, never by counting directory levels up to a repository root. |
| [A group with no commands does not appear](#a-group-with-no-commands-does-not-appear) | Your own empty group is a load error; a catalogue group you never mention is dropped silently. Who promised decides. |
| [A name collision breaks loudly](#a-name-collision-breaks-loudly) | Two different bodies on one command name stops the load and names both. `override: true` is the explicit yes. |
| [A step runs `sys.executable`, not `python`](#a-step-runs-sysexecutable-not-python) | A planned step is spawned with the interpreter that is running, by absolute path. |

Each of the six below carries the **mechanism** that forces it and a closing check you can run in
ten minutes. [What a rule costs, and how many there are](#what-a-rule-costs-and-how-many-there-are) is
the arithmetic behind the number six.

---

Everything else on this site can be derived. The command reference is read off the assembled
application; the manifest's shape is in the loader; the environment gate is in the dispatch. This
chapter cannot be derived from anything, and that is exactly why it exists.

These are the rules the kernel is designed by. Each one is here with the **mechanism** that forces it -
what happens, in what arrangement, and what the program does about it - because a rule without its
mechanism is an opinion, and an opinion is the first thing somebody argues away at four in the
afternoon.

Each rule ends with a way to check whether your own code has the same shape. That is the point of
writing them down: not that these six things happened, but that you can find out in ten minutes whether
the seventh is sitting in your own tree.

---

## What a rule costs, and how many there are

Before the six, the thing they are all a means to.

Simplon exists to give a delivery pipeline **clear structure**, **extensibility** and **reusability**.
Those three are the point; every rule below is a means, and a means that costs more flexibility than it
buys is a bad one. The risk is not any single rule - each one arrives with a measured cause and looks
obviously right on its own. The risk is the **sum**, because nobody ever measures a sum.

So it is measured here, and the measurement is the reason this section exists.

### Not every refusal costs anything

Three kinds, and lumping them together is what makes a count frightening for no reason.

1. **Diagnosis.** The manifest is broken, inert, or says something that renders nowhere, and the refusal
   says where. It takes nothing away - without it the failure would be silent, which is the defect this
   kernel spends most of its time hunting. *Example:* a coordinate the catalogue does not carry.
2. **Self-binding.** The kernel subjects itself to a rule it imposes. Costs a product nothing.
   *Example:* the placement rule below checks over the **merged** tree, so the catalogue's own placements
   are ruled on beside the product's.
3. **Expression rule.** A product may no longer say something it could have said - the refused manifest
   would have produced a working product, just a different one. **Only this kind costs flexibility.**
   *Example:* a phase name in a coordinate *is* the placement, so `build:image` cannot sit under
   `release`.

The question that sorts a refusal is therefore not how strict it feels but: *would the refused manifest
have produced a working product?* If no, it is diagnosis. If yes, it is an expression rule and it owes
an argument.

### The count

| kind | today | what it costs a product |
| --- | --- | --- |
| diagnosis | 108 | nothing - the declaration had no working meaning |
| expression rule | 22 | something it could otherwise have said |
| **all load-time refusals** | **130** | |

A **load-time refusal** is one raised on the way from the manifest to a decision, with no tool consulted
in between. Refusals that happen later - a task whose tool is missing, a build the daemon rejected - are a
different population with a different cost, and are not counted here.

{{< callout type="info" >}}
**None of these three numbers is typed.** They are computed by walking out from the two places a manifest
enters the kernel - `manifest.load(text)` and `ProductContext.manifest_data()` - and compared with this
table by `tests/test_refusal_census.py`, which is also what makes a new refusal impossible to add quietly:
an unclassified one has no census entry, and the suite goes red naming it until somebody says which kind
it is. A number typed onto a page is wrong on the first day nobody checks it, and this repository has
proved that twice.
{{< /callout >}}

**The total nearly doubled without a single new rule being written, and that is the most useful thing on
this page.** The census began as a list of modules, and a list is right only for as long as somebody
remembers it. It was first found short by one module - the `suites:` section is refused in the task module
that reads it, sixteen refusals outside a census whose entire purpose is that the sum cannot grow quietly.
The repair at the time was to add that module to the list. The list was then found short by six more.

So the population is no longer listed. It is derived from the two seams above and everything the kernel
reaches from them, and the derivation agrees three separate times with a number somebody had measured by
hand - the loader's two modules exactly, and the `suites:` sixteen exactly. What it added, on the day it
landed, was six modules: the ones that refuse a product's `nexus:`, `claude:`, `images:`, `site:` and
`workflows:` sections, plus the image pin - and the sentence this section used to carry named that pin as
its example of a refusal that is *not* load-time. It is decided on a string in the manifest with nothing
running.

Most of what came in is diagnosis; the few that cost a product something hold the kernel to them as well,
and the table below carries the live split rather than a sentence about it. The lesson is not about any
one of them: **a count that is computed rather than typed is still only a count of what you pointed it
at**, and the fix for that is to stop pointing it by hand.

### How far an expression rule reaches

Self-binding is not a third bucket of refusals; it is how far an expression rule reaches. Split that way:

| reach | count | meaning |
| --- | --- | --- |
| the kernel is held to it too | 16 | the same check rules on the catalogue's own declarations - over the merged tree, or over a product-owned section the kernel would go through unchanged |
| a statement about the platform/product seam | 6 | the rule *is* the asymmetry - the platform owns which groups exist, and "the kernel too" means nothing |
| the kernel exempts itself | 0 | there is no longer a rule the kernel declines to apply to itself |

**That last row used to say one, and how it got to zero is the point of measuring it.** The rule was
`check_every_task_is_used`: a product could not declare a task no command instantiated, while the kernel's
own catalogue does exactly that - its `tasks:` is an **offer**, because a task needing product data must
not become a baseline command that dies on its first line. It was the only one of the expression rules with
no measured cause in ticket, commit or docstring, and across every reachable manifest - this kernel's own
and the five products that install it - it had refused nothing, ever. So it was struck.

**A number that used to stand here has been withdrawn, and withdrawing it is worth more than it was.** The
exemption was also published with a *size* - the rule would have refused *14 of the kernel's own 22*
catalogue tasks - and that number was quoted here, in the working agreements, and in the commit that struck
the rule. It does not survive reading the rule's signature: `check_every_task_is_used(flat, product_tasks)`
was called with the merged tree and the **product's** `tasks:` block, and the catalogue's coordinates were
never handed to it at all. The count was right and the set was wrong. That has now happened four times in
this repository, every time to a number that was correctly computed, so the lesson is worth stating as a
rule of its own: **a number about a set is two questions, not one.** Is the count right, and is it the set
being talked about? The second one is the one that keeps going missing.

**What replaces it is a measurement rather than a label.** The reach column above was hand-written, and a
hand-written word beside a rule is exactly the kind of thing that was wrong. So the kernel's own manifest is
now loaded against the real catalogue with every rule-bearing function on the merge path recorded, and each
rule is asked what it was actually handed. The catalogue holds **38** coordinates and its own tree places
**9** of them; those 9 are the platform's half - in the merged tree because the catalogue put them there,
not because this product asked - and all 9 reach every rule the table calls *held to it too*. Exactly two
functions never see them, `check_no_old_form` (which rules on the product's document alone; it was shown
the catalogue until si#85, for the rewrite it no longer prints) and the one that enforces which groups
exist, and every rule in both is a seam statement. A rule labelled *held to it too* that was handed only the product's
half is now red - which is the shape the struck rule had, and nothing would have caught it.

The row stays, at zero, and the suite goes red if it ever leaves zero without an argument. A
self-exemption is not automatically wrong; an unexamined one is - and neither is a *measured* one, if the
measurement was taken over a set the rule never saw.

**Striking it cost something, and the price was paid rather than argued away.** A product that moves a
command onto a catalogue coordinate and leaves its own `tasks:` entry standing beside the new placement
loses that body *silently*: the manifest loads, the catalogue's body runs under the name, and the half
still being maintained is reachable from nowhere. That was pinned as a characterisation - a test that
records the silence - and it is now a **diagnosis** instead, one that names only the case the old rule
was actually catching: a declared task whose name a command has already taken for a different body. A
declared task nobody names at all is still an offer and still loads, which is the difference between the
two rules and the reason the second one is not the first one under a new name. Measured over all six
reachable manifests before it was built: **zero** would be refused by either.

### Before you add the next one

An expression rule has to answer three questions before it is built - in the ticket, not afterwards.

- **Does it forbid something a product might legitimately want?** If so, which product, and what does it
  do instead? The bar is *zero violations across the existing manifests*, measured rather than assumed.
- **Is it diagnosis or expression rule?** Diagnosis needs no such justification. Most refusals are
  diagnosis, which is why the total is much less alarming than it looks.
- **Would deleting be cheaper than guarding?** A second source you do not have cannot drift, and it needs
  no rule to watch it.

The census, the three questions and the reasoning behind them are [#48](https://github.com/marcozwyssig/simplon/issues/48).

---

## A missing tool is not a failed tool

> A tool that is missing is not the same as a tool that failed.

A step that shells out has **three** outcomes, not two: the tool is not installed, the tool ran and
failed, the tool ran and worked. A step that collapses the first two into one has an answer that is
wrong half the time.

So: a step whose tool is not installed reports a **hint** and exits zero. A step whose tool is installed
and *fails* is loud - an error on stderr and a non-zero exit code.

**The shape that gets this wrong.** A function that returns `None` on any non-success and logs a
warning, wrapped by a command that returns zero either way. Read it and it looks careful. Run it, and a
run in which the tool died is byte-for-byte indistinguishable from a run in which it succeeded: exit code
0, no exception, the raw inputs still sitting there, and none of the output the step exists to produce. A
warning is the only trace, and anyone measuring the run by its exit code - which is every CI system -
learns nothing.

**Why a branch like that survives review and a full suite.** It is reached only by the callers who lack
the local tool: every caller with the binary installed takes the other branch and never enters it at all.
A branch that only some arrangements reach is untested in practice however green the suite is, and
"nobody has complained" is evidence about your callers, not about your code.

The rule keeps the original promise and adds the distinction it was missing:

- no tool at all → hint, exit 0. Not every machine that runs the loop is the one that archives, and
  archiving must not itself be the reason a run is red;
- a tool that ran and failed → `log.error` on stderr, non-zero exit code;
- the function still **never raises**. It returns an outcome object with two predicates - `ok` and
  `failed` - so a caller that ignores it is unaffected and a caller that cares can tell the two cases
  apart. An exception was considered and rejected: it would reach direct callers as an unhandled
  traceback, which is loud in the wrong way and in a place the caller cannot decide about.

The rule now shapes every kernel task that shells out. `docs:site` is the clearest case: no Docker on the
host is a hint and exit 0, because the machine that runs the loop is not always the one that publishes
the website; Docker present and no site produced is red. And note what that second case has to include -
a site generator exits 0 on an empty content tree, or on a `contentDir` pointing at nothing, so the task
wipes the destination before building and then checks that a home page exists afterwards. **A build that
produces nothing is not a green build, whatever the tool's exit code says.**

{{< callout type="info" >}}
**Check your own:** find every place you call an external binary and ask what distinguishes "not
installed" from "installed, exited 3". If the only difference in your code is the wording of a log line,
they are the same case to every caller you have, and one of them is wrong.
{{< /callout >}}

---

## A container that writes into a mount runs as `--user`

Any container that writes into a bind-mounted host directory is passed `--user uid:gid`. Not caution -
a mechanism, and it bites from both directions.

A bind mount hands the container the host's inodes. Whatever uid the image happens to run as is the uid
that ends up owning the output, and neither of the two possibilities is safe.

**Direction one: the image runs as a non-root uid that is not the caller's.** It cannot create anything
in the mounted directory at all. An image whose default user is uid 1000, run against a host account with
some other uid, mounting the host's report directory at `/work`, dies on its first write:

```text
java.nio.file.AccessDeniedException: /work/allure-report
```

The same run with `--user "$(id -u):$(id -g)"` succeeds and produces the archive. Which means the branch
is broken on every machine whose uid is not the image's - that is, on every account that is not the first
one created on its own system, and on most CI runners.

**Direction two: the image runs as root.** Not obvious from the first, and worse, because it *succeeds*.
The run writes its output owned by `0:0`; the caller's own `rm -rf build` then comes back:

```text
rm: cannot remove 'build/website/index.html': Permission denied
```

and a root-owned lock file is left behind in the **source** tree - enough that the *next* run fails with
`failed to acquire a build lock` even when that run passes `--user` correctly. One run without the flag
poisons the working tree for every run after it.

The reason `rm -rf` failed is worth stating precisely, because it is not about who owns the files:
unlinking an entry needs write permission on the **directory** that holds it, and the container created
those directories.

The rule lives in exactly one place, `docker.user_args()`, with both measurements in its docstring. It
started as a private helper beside one caller and moved the moment a second task needed the same argument
for the same reason - because a convention restated in two modules is a convention that will drift in one
of them. On a host with no uid concept it returns an empty list: there is no ownership on the mount to
get wrong.

{{< callout type="info" >}}
**Check your own:** for every image you bind-mount into, run `docker run --rm --entrypoint id <image>`.
`uid=0` is direction two and will leave you files you cannot delete; any other uid that is not yours is
direction one and will fail to write at all. Both are fixed by the same flag.
{{< /callout >}}

---

## The catalogue travels inside the package

The task catalogue ships **inside** the kernel's Python package, as package data, rather than sitting in
the repository and being found by walking up the tree.

A package that resolves a data file of its own by counting directory levels to a repository root has
bound itself to one arrangement. `parents[5]` - five levels up - is exactly correct while the package is
vendored inside that repository, and meaningless once it is installed: from `site-packages`, five levels
up is somewhere else entirely, the file is not there, and the read raises `FileNotFoundError`. The
package cannot read its own catalogue.

The interesting part is not the mistake, it is why a full suite says nothing about it. Every test reached
the code through a `sys.path` adjustment against the source tree - which is the normal, sensible way to
test a package you are developing. So every test ran in the arrangement where the path is right, and the
one arrangement in which the defect exists is the one arrangement nothing exercised. There is no amount
of coverage that fixes this, because the uncovered thing is not a line.

The fix moved the file next to the code that reads it, declared it as package data, and added the test
that had been missing: the only test in the repository that builds the wheel, installs it, and uses the
package the way a consumer does.

**The rule underneath it:** *a tool never used in its own house rots unseen.* It is why the kernel is a
product of itself - its own `simplon.yaml` declares its own build, test and support commands, assembled
by the very kernel that repository builds. When a commit breaks the assembly, it fails in the same round
rather than after a release.

{{< callout type="info" >}}
**Check your own:** `pip install` your wheel into an empty virtual environment, `cd` somewhere that is not
your checkout, and import it. Anything that resolves a path relative to `__file__` and then walks *up*
is a candidate; anything that walks up past the package directory is the defect.
{{< /callout >}}

---

## A group with no commands does not appear

Two questions that look like one, answered differently, and the difference is who made the promise.

- A group the **product's own tree** names and leaves empty is a **load error**, naming the group.
- A group only the **catalogue** offers, that the product's tree never mentions, is **silently dropped**
  from the assembled CLI.

What that prevents is a `--help` listing a sub-application for every platform group the product never
filled. `release` and `monitor` render as bare placeholders, a user reading the help sees two
capabilities the product does not have, and finds out by running one. The help text is the contract; a
menu entry that leads nowhere breaks it as surely as a wrong answer does.

Both halves are needed and neither alone is right. Dropping every empty group would swallow a real
mistake - a product that declares a group and forgets to put anything in it has announced something it
does not have. Erroring on every empty group would refuse to load any product that has not yet filled all
six of the platform's slots, which is every product on its first day.

Two details, both of which are easy to get wrong:

**Where the decision is made.** In `load()`, not in the merge. The merge only ever sees the new-form half
of a manifest that is still migrating, so pruning inside it drops a group that was filled through the
*old* form - which, from the merge's narrow view, looks identical to a group nobody filled at all. A
decision has to be made where all the information is, and the merge is not that place.

**What counts as empty.** The whole *subtree*, not the one path. A parent group can hold no direct
command of its own while a child group underneath it holds four; measured per path, the parent looks
empty, gets dropped, and its children have nowhere left to hang from.

The check is made against the **assembled application** rather than against the parsed manifest, because
the parsed manifest is not what a user types against: a group that was correctly dropped shows up as an
unregistered command, and everything the product does implement still works.

A second defect of the same shape sat next to it. A flat-form manifest could declare `import:`, make
catalogue coordinates available, reference none of them, and load perfectly clean having placed nothing at
all - no command, no warning, no error. That one is gone at the root: `import:` no longer exists, and a
manifest that still carries it is refused by name. **A mechanism that accepts something and does nothing
is the shape of both**, and it is worth looking for by name.

{{< callout type="info" >}}
**Check your own:** run your CLI's top-level `--help` and try every group it lists. Any entry that exists
in the listing and has nothing behind it is this defect, and it is the cheapest of the six to find.
{{< /callout >}}

---

## A name collision breaks loudly

When a catalogue-placed command and a product's own command land on the same name with *different*
bodies, the loader stops and names both bodies. It does not pick one.

The mechanism that makes this dangerous is a two-line merge: `{**inherited, **spec}`, the later
declaration winning. Nothing about that is unusual, and it is right for every key except the one that
names the body. When the two dictionaries name **different** bodies, the command still resolves, the help
text still reads plausibly, and the only proof of which body actually ran is what the host looks like
afterwards.

That is the failure mode worth naming: not an error, not a warning, not even a wrong answer - a
*plausible* answer, with the evidence for it outside the program.

The rejection names both bodies by their real `module:function` rather than only the coordinate they
share:

> command 'support install' redeclares `task:` from 'support:install' to 'install' - two different bodies
> placed under one name: the platform's is `simplon.tasks.hosttools:install`, the product's is
> `orchestrator.cli:install`. Which one runs is exactly the silent choice this loader refuses to make [...]

`install` and `install` read identically; `simplon.tasks.hosttools:install` and `orchestrator.cli:install`
do not. A human cannot act on the first pair and can act on the second, which is the entire job of the
message.

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

{{< callout type="info" >}}
**Check your own:** for any name that two configuration sources can both define, ask what the program
prints when they disagree. If the answer is "nothing, and then you look at the machine", the disagreement
is being resolved outside the program and you cannot review it.
{{< /callout >}}

---

## A step runs `sys.executable`, not `python`

A planned step is spawned with the interpreter that is currently running, by absolute path. Not
`python`, not `python3`, and - where it can be avoided - not the product's shell launcher either.

Two problems, one fix.

**`python` is whatever `PATH` says.** A step that starts through `python` rather than `sys.executable`
runs under a different interpreter than its parent process the moment `PATH` does not point at the same
virtual environment - which is the normal state on a machine with a system Python, a shell that was
opened before the environment existed, or a `PATH` a CI image sets for its own reasons. That does not
fail where it happens. It surfaces three steps later as a missing dependency, in a step that has nothing
to do with the cause, and the traceback names the innocent step.

**A shell launcher is a bootstrap being asked to do something it is not for.** The launcher's job is to
create the environment, install the requirements and exec the module. By the time a plan is running all
of that has already happened and the process *is* that environment's Python - so spawning each step
through the launcher repeats the whole bootstrap once per step, and forces the code to know which of
`myctl.sh` and `myctl.cmd` the current host can execute.

That second half is what made it worth a change rather than a note, because it is not a performance
argument. A POSIX launcher hard-coded into a step factory is not a slow choice on Windows, it is a file
the host cannot execute at all:

```text
WinError 193: %1 is not a valid Win32 application
```

and it fails on the first run that ever reaches that factory on that platform - which may be long after
the line was written, in a place nobody associates with it. The workaround is a per-platform ternary at
every call site, restated wherever a step is spawned, with the usual consequence for a convention stated
twice. With the interpreter already running, there is nothing to choose and nothing to restate.

One thing deliberately did **not** change: the identity stamp each step carries. It is what lets the
kernel verify that step *i* really is the step for plan leaf *i*, and losing it takes the plan tree with
it, and every subtree's `stop_on_failure` with that - so a gate chain would run on after a failure.
**Changing how a step is spawned must not change what it is.**

The launcher-based factory is still there, unchanged, for a product whose steps genuinely must redo the
bootstrap - a self-updating launcher, a requirements change mid-plan. That shape is rare, not wrong.

{{< callout type="info" >}}
**Check your own:** `grep` for `"python"` and `"python3"` as the first element of anything you spawn, and
for a hard-coded `.sh` or `.cmd`. Then print `sys.executable` in a parent and in a child and compare them.
If they differ, everything downstream is running somewhere you did not choose.
{{< /callout >}}

---

## What these have in common

Read them together and the same failure keeps appearing under different names.

**Four of the six are silence, not error.** A render that failed and reported success. A container that
wrote files nobody could delete. A package that could not find its own data in the one arrangement
nothing tested. A collision that resolved to a plausible answer with the evidence outside the program.
None of them threw. All of them looked fine.

So the working rule the kernel keeps applying is: **a mechanism that accepts something and does nothing
is a defect, even when nothing is on fire.** A section with no meaning left, like `import:`. An empty
group in a menu. A `with:`
that names a parameter the body does not take. A task key that is read by nobody. A gate whose hook
returns nothing. Each of those is now a load error or a warning, because a declaration that renders
nowhere is worse than one that fails.

And underneath that, the thing they actually share: **every one of the six lives in a branch that only
some arrangements reach.** A host without the local binary. An image whose default user happens not to be
yours. A package installed rather than vendored. A platform the code has never run on. A merge that only
happens when two declarations collide.

That is why none of them was found by reading the diff, and why none of them *could* be: in the
arrangement you are reading in, the code is correct. A test suite that always runs in one arrangement is
evidence about that arrangement, and a review is evidence about the reviewer's. The only thing that finds
these is putting the code in the other arrangement on purpose - which is a thing you can schedule, and is
cheaper than the alternative every time.
