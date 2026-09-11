---
title: "Releases"
weight: 9
---

What each release changed, and what a product has to do about it.

Notes start at **0.4.0**. Earlier releases have their tags and their commits;
writing their notes now would mean reconstructing them from memory, and a
reconstructed record reads exactly like a real one. The [release
procedure](../releasing/) explains how a version comes into being.

Every section from **0.5.0** on names the number of every ticket merged into
that release, and `./simplon.sh test release-notes` measures it against the
merges in the release's own range, so a change cannot go out undescribed. That
command is the catalogue's `test:release-notes`, so the rule is the kernel's
and every product that keeps release notes can run it; what is simplon's own is
the `releases:` section in `simplon.yaml` naming this page and those two
numbers. The numbers below are issues and pull requests in [this
repository](https://github.com/marcozwyssig/simplon/issues). The 0.4.0 section
predates that rule: it describes its release in prose and names no numbers, and
it is the one section held only to existing.

## 0.11.0

**Three things a real run showed, and two that had quietly stopped being true.** The first three came
out of one screenshot and one sentence from the operator watching a build: none of them was a failure,
the run was correct and unreadable at the same time. The other two are a refusal that still offered work
it should no longer do, and a gate that had stopped covering what its name claims.

A minor rather than a patch: the state alphabet is a surface and one of its five characters changed,
what a refusal says is a surface, and so is what a gate covers.

### `simplon init` scaffolds a `.gitignore`, and three of its lines were never needed (si#155)

`simplon init` wrote nine files and none of them told git what to hide, so the first `build deps`
followed by `git status` offered an 80 MB commit: the python profile installs pytest and mypy into the
bind mount, because a `--user` container may write nothing else. Driving a scaffolded product through
`help`, `support toolchain python 3.12`, `build deps`, `build unit` and `build analyse` answers four
untracked entries - and the first of them arrives from `help`, before the product owns a command:
the launcher puts the orchestrator package on `PYTHONPATH` and the kernel imports it.

**The list came first, not the rule**, because the kernel writes files on both sides of that line.
si#102's `CMakeLists.txt`, `<product>.sln` and every `.csproj` carry a `DO NOT EDIT` header and are meant
to be COMMITTED, as are `nuget.config`, the generated completions, the generated workflows and the
generated CLI module. Those land among the sources and never under `build/`, which is why the block's
first four rules are anchored with a leading `/`: unanchored, `build/` would also hide a target
directory named `build` and with it a generated `CMakeLists.txt`. A test drives the real si#102
generators over a real tree and asserts git can still see all eight files they write.

**Two of the lines this repository has been telling products to add were never necessary, and it nearly
became three.** The 0.10.0 notes named `.simplon-toolchain`, `.mypy_cache` and `.pytest_cache` as "yours
to add"; only the first is, because pytest and mypy each drop a `.gitignore` holding `*` into the cache
they create and `git check-ignore -v` names that file as the rule.

A venv looked like the same case and is not. It writes the same self-ignoring file **only since CPython
3.13**, where `EnvBuilder` gained `scm_ignore_files` - `python:3.12.14` leaves a fresh venv with no
`.gitignore` at all, `python:3.13.15` writes one. The block was first shipped without a `.venv` rule, was
green on a 3.13 developer machine and red in CI on 3.12, and CI was the honest reading: the launcher is
written to survive a bare host and pins no host python. So `.venv/` is a rule, unanchored, which is the
one line that covers the launcher's venv wherever `--orch-dir` puts it and a gate's `suite:` venv as
well - and that, rather than an absence, is what makes one block right under both si#130 layouts.

**It appends, and it never rewrites.** si#129 put `init` at the repository root, so the `.gitignore` it
meets is usually somebody else's - refusing the whole scaffold over it would be wrong, and forcing over it
would be si#110 again, where a scaffolder round-tripped a manifest through a plain yaml loader and
forty-two comment lines did not come back. So the block is appended once, guarded by a marker line, and
existing bytes are never read for structure. Edit it, reorder it, delete half of it and the next `init`
leaves your version alone; `--force` does not reach it either. The cost is stated rather than hidden: a
stale block is never refreshed, which is the right way round for a file the product owns.

**The assertion is `git status --porcelain`, not a line in a file.** A pattern in the right file with the
wrong anchoring ignores nothing and no `in body` check can tell. So the proof is a scaffolded product,
committed, driven through the commands that write into it, with git asked what it can see - nothing - and
then asked again about the files si#102 generates to be committed, all of which it still can.

### The manifest publishes which top-level names are already taken (si#159)

`groups:` is refused when it names a group the platform's tree does not declare. Every other top-level key
is a product data section, and a report asked whether a typo in one of those names should be refused too,
since the section would simply not exist and the task reading it would behave as though the product had
opted out.

It is not refused, and the measurement is why. Every manifest this kernel can reach was read - its own
plus the six in other repositories - and of the seventy top-level keys in them, **none is read by nobody**.
Eleven are read by the product's own task bodies rather than by the kernel, and each was traced to the line
that reads it. A rule about unread keys would have a population of zero to protect and a sixteen per cent
false-positive rate by construction. An edit-distance rule does worse: `release:` sits one character from
the kernel's `releases:` and is a real, product-read section in two of the seven manifests, so the cheap
version of the check refuses two live products on its first run.

The premise did not survive either. A mistyped section is not silent: fourteen of the sixteen top-level
keys the kernel reads are named by the reader that wanted them, and `sietv:` instead of `site:` answers
`the 'site' section is missing or is not a mapping`. That is now driven rather than believed - every one of
the sixteen is exercised through a manifest on disk and a registered context, including the two whose
absence deliberately says nothing (`build:`, where no section is the normal case, and `env_var:`, which a
product selecting its environment by token alone never declares).

What was actually missing is on `building/manifest.md` now: **the sixteen names the kernel has claimed**,
with the task that reads each and what it carries. The product this was reported from builds three Windows
Server *releases* and learned that `releases:` was taken by reading `src/simplon/tasks/releasenotes.py`. A
reserved name findable only in the source is a trap with a delay on it. The table is held to the kernel in
both directions, and the modules that read a manifest are derived from the call sites rather than listed,
so a new reader cannot join without appearing there.

### `build:` is a group name and a section name at once, and the kernel says so now (si#172)

`src/simplon/tasks/buildfiles.py` reads `build:cmake-files`' and `build:dotnet-solution`' `targets:`
block out of a top-level `build:` section, and its own comment said that was safe because a command
group and a data section could never share a name. They already did. Measured over the same seven
manifests si#159 read, **two live products carry a top-level `build:` section of their own** - cleon's
holds `bundle:`, `ant:` and `site:`, secure-windows-images' holds `packer:` and `templates:` - and one
of them had written a comment to its own authors explaining the collision and telling them never to add
a `targets:` key. A product should not have to document the kernel's namespace in its own file.

What the collision costs was driven rather than argued, which is what decided the shape: both real
sections were put into a product that DOES place `build:cmake-files`, and the command was run. It wrote
the same three files as a product with no `build:` section at all, byte for byte. **There is no silent
empty model on this path**, and not by luck - si#102 made the source tree the declaration, so an absent
`targets:` withholds only the dependency edges a directory cannot show, which is exactly what the
normal case withholds. A tree that yields no target is still refused.

So the fix is a stated rule and not a new refusal. `build:` is the product's section, the kernel reads
exactly one key out of it, an absent `targets:` means the tree is the whole declaration, and inside
`build:` the word `targets` is the kernel's - cleon's Ant block is one rename from tripping it, with
`generate_targets:`, `compile_targets:` and `package_targets:`. Refusing a product's `build:` was ruled
out by si#159's own measurement (eleven of seventy top-level keys are read by product bodies in
repositories this kernel cannot see). Renaming the section is free today, since not one reachable
manifest declares `build: targets:`, and was still rejected: it moves the generators' input out of the
group that produces it, for a collision measured at zero cost.

Two refusals changed their wording, because both claimed a section the kernel shares: a `build:` that
cannot hold a key no longer says what the product's section "must hold", and a `targets:` of the wrong
shape now says whose name it is and which key to rename. The manifest page's `build:` row said
`support:toolchain`, which reads `groups: build: commands:` and never the data section - si#172's own
confusion, in the documentation written to end it - and the row is derived from the catalogue now.

### The running row stops reading as two arrows (si#162)

`STATE_ICON[RUNNING]` was `▶`, and `▶` is exactly what Textual's `Tree` puts in front of a collapsed
node. A running row with steps under it therefore rendered

```text
├── ▶ ▶ build.prep   13m51s…
```

- two identical arrows, two unrelated meanings, on precisely the rows that carry work. It is `↻` now.

The choice is a glyph nobody else draws, and the alphabet it was checked against was read out of the
pinned Textual rather than assumed: the two node icons, plus every guide variant in `Tree.LINES` -
`│ └─ ├─` by default, `┃ ┗━ ┣━` under a bold row style, which is reachable because a failed row IS bold.
The other four were held to the same list instead of being taken on trust, and the pane was rendered at
100, 40 and 24 columns to confirm a narrow terminal changes the guides not at all. A test now asserts
the whole table is disjoint from that alphabet, so the next glyph anybody adds cannot re-open the
collision quietly.

**Static, and that is a constraint rather than a preference.** The same table renders the headless rows
a CI log carries and the `run-transcript.log` somebody attaches to a ticket. A spinner would read better
in the tree and be wrong in both, so `STATE_ICON` keeps producing exactly one plain character - asserted
in each of those two artefacts, alongside the existing "no markup, no escape" checks.

### The pane comes back to the tail, and an aggregate stops being a snapshot (si#162)

*"When I change the view it loses its place. Above all you cannot see the latest state while something
is running."* Two separate defects under one sentence, and si#144's backlog was neither of them - the
lines were all there, all thirty-seven of them.

**Where the pane was POINTED was wrong.** Leaving a running step remembered a y offset; the step had
five lines at the time, so the offset was 0 and it was also the end. Coming back to thirty-seven lines,
`scroll_to(y=0)` is the top - the pane showed `line 1` while the step was at `line 65`. Worse than one
stale screen: the sticky bottom asks whether the reader is at the end before every write, so from that
moment it never caught up again. Being at the tail is a relationship to output that has not been written
yet, so it is now remembered as one and restored as one.

**And an aggregate's listing never moved.** With the cursor on a parent row while its child streamed,
the rendered pane was byte-identical over a second and a half in which the child produced thirty more
lines. Two causes at once - the listing said `(running)`, which cannot change, and nothing repainted it
between step boundaries, which is the one event a long step does not produce. A running child now
carries how long it has been running, and the same one-second beat that drives the row counters
repaints the pane when its text really changed. The root of a plan is somewhere you can watch a run
from.

Both were reproduced before they were touched, with a real child through the real stream reader and the
cursor moved deliberately, and both tests were seen red against 0.10.0 first.

### The flat-form refusal names the way out instead of printing it (si#85)

The renderer served a measured-empty population. All six manifests that install this kernel have been off
the flat form since 0.4.0, the seventh flat one does not install it at all, and si#56 had just found that
the renderer carried a property that had been mis-documented since the day it was written. That is the
shape of a second source nobody reads: correct-looking, unexercised, and drifting from the thing it
describes.

**The refusal itself survives, and the argument for it was never rebutted.** A population is not the set
of possible inputs, and a new consumer can arrive with an old manifest. Without the refusal that manifest
dies further down as a missing key on some node, which names neither the shape the file is in nor the
release that abolished it. Roughly forty lines buy that, and they stay.

What the message says now, in place of the block:

```
this manifest is written in the flat command form, which no longer loads: the form was abolished in
0.4.0 and this kernel is past it.

What says so here: group(s) 'build' name commands directly, with `impl:` on them; task(s)
'docs:reference' are keyed by a platform coordinate; an `import:` section makes catalogue coordinates
available.

What it becomes:
  - a command is an INSTANCE of a task: declare the body once under `tasks:` and let the command point
    at it with `task:`, under `groups: <group>: commands:`
  ...

The tree form is documented at https://marcozwyssig.github.io/simplon/building/manifest/ - "The command
tree" for the shape, and "The flat form, and how to leave it" for this migration in particular. Nothing
here rewrites the file for you: the sections have to be edited by hand, which is also the only way your
comments survive the move.
```

The detection is unchanged: the same four shapes are still found together, and the same manifest is still
refused before any other check can report a symptom of it instead.

**Nothing to do unless you have a flat manifest**, and if you do, [The
manifest](../../building/manifest/#the-flat-form-and-how-to-leave-it) is now where the migration is
written down. That page grew the worked example the renderer used to print, plus the seven things to know
while converting - including the one the renderer could never do for you, which is carry your comments
across.

### `test all` runs every test again (si#156)

si#89 moved the release-notes guard out of simplon's own pytest suite and into the catalogue coordinate
`test:release-notes`. That was right, and it had a side effect nobody stated: **the check left the local
gate.** `./simplon.sh test all` was the pytest suite, `test release-notes` was a command only `ci.yml`
invoked, and a developer running the gate this project tells them to run learned nothing about their
missing notes until after the push. A command named `all` whose help says "Run every test" was not every
test.

The pytest leaf is called **`test suite`** now, and `test all` is an impl-less **aggregate** over it and
`test release-notes`. Nothing was reimplemented: the aggregate reaches the same command `ci.yml` reaches,
so there is one implementation per verdict, invoked from two places rather than written in two. That is
the rule `typecheck-python` already carries in the manifest, and a pytest test that shelled out to the
guard would have broken it.

`stop_on_failure` stays at its default, and here that is the load-bearing half: both steps run, both
verdicts print, and the aggregate takes the worst rc, so a red suite cannot hide the notes verdict and a
missing section cannot hide the suite. The notes guard costs **0.34s** against the suite's 55s, so the
local gate is the same length it was.

`ci.yml` still names the four leaves rather than the aggregate. A GitHub job stops at its first failed
step, so putting the aggregate first would place the prose gate in front of the type gate and the wheel,
which is exactly what si#89 refused when it put that step last.

**What to do about it.** For simplon itself, nothing. For a product that has adopted the coordinate: the
mechanism is `depends_on`, which the kernel already had, so folding the guard into your own `test all` is
two manifest lines and no new coordinate. Give your pytest leaf a name of its own, then let `all` depend
on it and on `release-notes` - a command either instantiates a task or plans other commands, never both,
which is why the leaf has to be renamed rather than extended.

Two things worth knowing beyond the change itself. `release.yml` runs `test all`, so the release path now
checks the notes too, and a tag whose section nobody wrote stops the publish rather than following it.
And `tests/test_type_gate.py` gained an assertion: its rule "any job that runs the suite runs the gate"
was a single command string, and renaming the command in `ci.yml` left every assertion in that file green
while the rule matched no job there at all. It asks about the predicate as well as about the gate now.

### A Windows CI log gets the verdict instead of a traceback (si#161)

`run_headless` ends by printing the tree in the glyph vocabulary it shares with the TUI. On Windows a
stdout that is not a console defaults to the legacy code page, and four of the five glyphs have no
cp1252 encoding at all - `↻` since si#162 among them - so the runner raised `UnicodeEncodeError` **at
the moment it reported its verdict**, after every step had run and the exit code was already decided. A
green pipeline came out of CI as a traceback and a non-zero exit, on exactly the path a CI runner and a
piped run take.

The runner now asks the stream what it can carry and prints the ASCII twin of the same table when the
answer is "not this": `pend`, `run`, `ok`, `fail`, `skip`, padded so the labels still line up. **A
terminal that can draw the glyphs keeps getting them** - nothing is flattened for everyone because one
platform cannot encode a tick, and `errors="replace"` was refused outright, because `?` loses which
state the row was in and a verdict that reads `?` is worse than a crash that is at least visible. Each
fallback spelling is a prefix of the state's own word, which is the property the test asserts; "it is
ASCII" would be satisfied by `+` and `-` too, and neither says anything to a reader.

The decision sits at the one print that reaches a stream the kernel did not open, asked once per run.
Reconfiguring `sys.stdout` to UTF-8 at startup was the alternative, and it was rejected for its blast
radius: it changes the encoding of a stream the kernel does not own, for every other writer to it, to
fix one runner's five characters. **A product needs no change** - a composition root that already
reconfigures its streams keeps working and simply never reaches the fallback.

The run transcript is untouched: `steplog` writes it `encoding="utf-8"` by name, so the file a reader
attaches to a ticket keeps the glyphs whatever the console can show, and a test now says so. si#162's
disjointness assertion covers the second table too, per character, because its spellings are words.

### The type gate joins the local gate, and a step that could not fail leaves the release (si#163)

si#156 gave `test all` its name back over the release-notes guard and left the type gate out on purpose,
because folding it in changes what `tests/test_type_gate.py`'s central rule is *about*. It is in now:
`./simplon.sh test all` plans the pytest suite, then `test:typecheck-python`, then the notes guard.
Measured on this tree it costs 3.4 s the first time and 0.6 s with mypy's cache warm, against some 60 s
of suite - so the command this project tells a developer to run is every test again, at no price worth
naming.

**The rule is narrower rather than gone.** *Any job that runs the suite runs the gate* had two halves,
and the aggregate takes one away: a job spelling `test all` cannot miss the gate any more. The other half
is the shape `ci.yml` deliberately has - it names the **leaves**, because a GitHub job stops at its first
failed step and the prose gate has to come last - and a job built that way still owes the gate a step of
its own. So the question moved from *does this job name the gate* to *does it reach it*, answered by
expanding each step through the manifest plan instead of matching a table of spellings. A table would be
si#156's defect one level up: it would go on saying `test all` carries the gate on the day somebody edits
that `depends_on:`. A separate assertion holds that claim by itself, so the cause is named rather than
the symptom.

**And `release.yml` lost a step.** It runs `test all`, which now carries the gate, so the
`test typecheck-python` step behind it could only ever run when `test all` had already been green - which
means the gate inside it had already passed. A check that cannot fail is the shape this repository hunts,
so it went rather than stay looking like a guard. What stops a publish is unchanged: a type error stops
it, one step earlier in the file, with the same verdict and the same message.

**One thing si#163 expected and did not find.** The ticket noted that mypy's exit codes would collapse
into the aggregate's 0/1 the way pytest's did. They were collapsed already: `tasks/typecheck.py` ends a
failing run on `log.die`, which is `SystemExit(1)`, so mypy's 1 for findings and 2 for a usage error had
never reached a caller in the first place. There was nothing left for the aggregate to flatten.

Nothing to do for a consuming product: `test:typecheck-python` is unchanged and this is simplon's own
manifest. What is worth copying is the shape - if your `test all` is an aggregate, the gate belongs in
its `depends_on:`, and the assertion that it is there belongs beside it.

### A merge source that is the destination is refused by name (si#138)

`allure.merge_results` copied every non-result file with `shutil.copy(f, dst/base)`, so a product that
declared its own results directory as a merge source copied a file onto itself and got
`SameFileError: '.../ctest.xml' and '.../ctest.xml' are the same file` - a `shutil` traceback three
frames down, naming neither the manifest key nor the directory, out of the one module that names the
offending key in every other refusal. It is reachable through `report.merge:` and, since si#133, through
a gate's `results_from:`, and both are plausible misreadings of *the directory the results are in*.

**The crash was the smaller half.** Measured on 0.11.0's tree before the fix: a self-source holding
`*-result.json` never reached `shutil.copy` at all. It reached the tag-and-rewrite branch, which wrote
each file back over itself and counted it - so a gate whose own runner wrote nothing reported `merged 3
files from 1 of 1 declared source dirs: 3 tagged parentSuite=Unit` and passed, over three results an
earlier gate had left in the shared directory. That is precisely the green-over-nothing si#133 exists to
prevent, reached through si#133's own key.

**A fourth fate, not a fourth flavour of skip.** The three the merge already had - a missing source
counted, a subdirectory named, a stale file named - all describe the world at merge time, and each can be
right on the next run with nobody editing anything. A source that is the destination describes the
*declaration*: it is true on every run and only an edit fixes it. So it is refused by name, and it
contributes nothing at all - not a present source, not a case, not an uncountable file - which is what
keeps `Merge.contributed` from going green over somebody else's evidence. The line says which directory
and what to do:

```text
nothing merged: 0 of 1 declared source dirs present; 1 declared source dir is the destination itself and
was not merged (…/tests/reports/allure-results) - those files are already at the destination, so nothing
travelled and none of them counts as this merge's evidence. Name the directory the runner writes into,
or drop the key
```

It is **not** a load-time refusal, and that was measured rather than argued: the destination is not one
directory. `results_dir` answers `allure-results` for a canonical run and `allure-results-filtered` for
an exploratory one, so the same declared path is the destination on one run and an ordinary source on the
other. A rule at load time would have to forbid a manifest that works in order to catch a fact that is
only true at run time. It is not an exception either, for the reason si#62 already wrote down one case
across: the archive is not damaged by this, so raising would destroy a report that is otherwise complete.
The report step now renders as usual and warns.

**Nothing to do.** A product that declares a real source directory behaves exactly as before. A product
whose `report.merge:` or `results_from:` names its own results directory sees a warning instead of a
traceback, and a gate that named it goes red rather than green - point the key at the directory the
runner writes into, or drop it.

### The pane's scroll tests wait for the frame Textual defers the scroll to (si#169)

si#162's own guard,
`test_coming_back_to_a_running_step_lands_on_its_tail_and_goes_on_following_it`, turned five unrelated
pull requests red in the two days after it was written, and a rerun of one identical commit failed
again. **The property it guards is intact; the test was reading one frame too early, and so were three
of its four neighbours.**

Read out of the pinned Textual 8.2.8 rather than guessed: `Widget.scroll_to` and `Widget.scroll_end`
move nothing at the moment they are called. Both end in `call_after_refresh` unless `immediate=True`,
and the framework says in that branch why - the layout has to settle first or `max_scroll_y` is not
the real one, which is the very number si#162 was about. The screen drains those callbacks only after
a frame and refuses to drain them at all while a repaint is outstanding, which is the state a
cleared-and-rewritten pane is always in. A bare `await pilot.pause()` sleeps one `SLEEP_GRANULARITY`,
20 ms, and hands back, against a screen update timer at 1/60 s.

**Reproduced before anything was touched, and the reproduction is the useful part.** The full suite
went green 12 times of 12 on this machine and the module alone 30 of 30, which is what makes a flake
look rare and unfixable. Under four competing CPU hogs it is not rare: the ticket's test went red in 8
of 40 runs and again in 10 of 40, on the assertion the ticket quotes, and the same load found three of
the four neighbouring scroll tests flaky on unmodified main too. That is also what the CI runner is,
since it executes two suites at once.

**It is the test and not the runner, and that was measured rather than argued.** Under the same four
hogs the pane reached 61 of 61 between 3.0 and 11.1 ms after the read, every time, inside one 60 Hz
frame. Nobody watching a terminal sees that, and the one alternative inside the runner -
`scroll_end(immediate=True)` - is what Textual's own comment rules out, because the layout has to
settle before `max_scroll_y` means anything. Nothing in the runner changed.

**There were two races and not one of them twice.** Waiting on the deferred scroll still left three
neighbours red over 120 loaded runs, all three at their pane's *maximum* offset - the signature of the
app's own scroll landing after the test's. The cursor move only assigns a line number; the highlight is
posted and bubbles, and the pane is repainted on the app's own account by a step starting and by the
one-second aggregate tick. A test that scrolls the pane by hand now first drains what the app already
asked for, deterministically rather than by waiting.

**And two of the new waits were at first satisfied by the wrong pane**, which is the failure mode a
poll introduces and the reason both are recorded in the file. Being at the tail is trivially true of a
pane holding three lines, so waiting for the tail alone returned instantly with the *previous* step
still on screen; and the round trip's second wait was satisfied by a pane neither cursor move had
reached, going green 2 of 20 runs against a deliberately broken runner. Both waits now name the row the
pane has to be showing.

Not a longer sleep, not a retry, not a weaker assertion: every original assertion is unchanged and
every one was seen red. Five properties were broken in the runner in turn, and each test failed 20 of
20 loaded runs against its own - the round trip among them, which the row-naming wait took from 18 of
20 to 20 of 20. The two reads that assert a scroll did **not** move are deliberately left on a bare
pause, because a poll cannot wait for a negative; each was red in 10 of 10 idle and 20 of 20 loaded runs
against the regression it exists to catch, which is why neither grew a wait it cannot justify. All five then survived 150 loaded runs with nothing red.

## 0.10.0

**A C++ or a .NET product stops writing its build files by hand.** 0.9.0 gave every product one pinned
toolchain and one uniform way to run it over its tree; this release produces the files that toolchain
compiles. The two halves meet in the tree and nowhere else - two coordinates, no new subsystem.

A minor rather than a patch: two catalogue coordinates are a surface, not a repair.

### Two coordinates that write a product's build files (si#102)

`build:cmake-files` writes one `CMakeLists.txt` per source directory plus the root file that adds them.
`build:dotnet-solution` writes the `.sln` and one `.csproj` per project. Both are **declared, not
placed** - a product without the language never sees the command, and a product whose build outgrows the
shapes below keeps its hand-written files and declares neither. Nothing degrades; it does what every
product does today.

**The tree is the declaration, and the manifest is only the exception.** `src/<name>/` holding sources
is a library, one holding a `main.cpp` or a `Program.cs` is an executable, each `tests/<name>_test.cpp`
is one ctest case, and a directory under `tests/` is a test project. The one thing a directory cannot
show is what a target depends on:

```yaml
build:
  targets:
    net: { depends: [core], include: [vendor/asio/include] }
```

Guessing that from include paths was considered and refused - it reads a preprocessor approximately, and
an approximate answer in a build file fails at link time, in a message about symbols rather than about
the manifest. A `targets:` key naming no target is refused by name, with the targets that do exist
listed, because a typo there is otherwise silent and silently does nothing.

**What they write is committed, so it has to be deterministic.** Every list is sorted, and a solution's
GUIDs are derived with `uuid5` from the project's path relative to the product root rather than
generated: a `uuid4` would put a new GUID into the diff on every run and make the committed decision
unusable within a week. Each file carries a two-sentence `DO NOT EDIT` header, and the generator
overwrites without asking - deliberately the opposite of `support:toolchain`'s never-clobber rule,
because a manifest is a product's own statement and a `CMakeLists.txt` is a rendering of one. Reverting
a statement would be wrong; reverting a rendering is the point.

**Driven, not asserted, and that is why 0.9.0 exists at all.** `tests/test_buildfiles_e2e.py` generates
a real tree, runs `configure`, `compile` and `ctest` in the profile's own `silkeh/clang:19`, executes
the binary, and does the same for `dotnet build` in `mcr.microsoft.com/dotnet/sdk:9.0`. It earned its
place on the first run: the .NET half targeted `net8.0`, which BUILDS in a 9.0 SDK image because the
targeting pack is restored from NuGet, and then refuses to run - `You must install or update .NET to run
this application`, rc 150. It targets the framework the SDK image carries now.

One thing to know before adopting the CMake half: `add_subdirectory` puts a target's output under its
own directory, so an executable declared in `src/<name>/` lands at `build/src/<name>/<name>` and not at
`build/<name>`. A `deploy up` command that runs the binary has to name that path.

### A product can hand a package over, and a second one can take it (si#127, si#128)

Both languages could compile in 0.10.0's uniform build and neither could give the result to anybody.
Five coordinates close that, and they are two different answers because GitHub Packages gives two
different answers.

**NuGet is an ordinary registry.** `release:nuget` packs the declared project and pushes it to
`nuget.pkg.github.com/<owner>`; `build:nuget-config` writes the `nuget.config` a consumer restores
through, and `build:nuget-restore` runs that restore with the credential the feed wants. All three read
the manifest's existing `artifacts:` section - there is no new top-level key.

**The generated `nuget.config` is meant to be committed and holds no token.** What it holds is
`%GITHUB_TOKEN%`, which NuGet expands from the environment when it reads the file. The resolved token
reaches the container as a `--env-file` created 0600 and deleted in a `finally`, never as
`-e NAME=VALUE`, and never on a command line: measured, a push against a source that already carries
credentials needs no `--api-key` at all.

**Conan is not a registry there, and the docs say so in as many words.** GitHub Packages serves npm,
RubyGems, Maven, Gradle, NuGet and Docker/Container - and no Conan. So `release:conan` is a
**transport**: `conan cache save` writes an archive, the coordinate moves it into a registry as an
ordinary OCI artifact, and `build:conan-cache` pulls that exact tag back for the product's own
`conan cache restore`. No remote resolution, no version ranges, no graph solved remotely. Whether Conan
could do better by itself was measured rather than looked up: `conan remote add` in Conan 2.32.0 accepts
one remote type, `local-recipes-index`.

The whole loop was driven end to end rather than asserted over an argv - published, then resolved from a
second project, and for Conan restored into an empty cache and built against. [Handing a package
over](../handing-a-package-over/) is the chapter. Nothing to do: five declared coordinates, and a
product that declares none of them is unchanged.

### The help screen names the simplon that is answering (si#125)

`<product> --help` rendered byte for byte the same screen whether the kernel behind it was a released
wheel from PyPI, an editable checkout on the same machine, or a version pinned two releases ago. Both
facts existed the whole time - `simplon.__version__`, and `importlib.metadata` knows the distribution -
and neither was ever printed. The root app's epilog now carries one line under the command panels:

```text
assembled by simplon 0.9.0.post1.dev8+g4b69283dc.d20260909 (editable install, /tmp/wt-125/src/simplon)
assembled by simplon 0.9.0.post1.dev8+g4b69283dc.d20260909 (/tmp/wheelvenv/lib/python3.13/site-packages/simplon)
assembled by simplon 0.0.0.dev0+unknown (no installed distribution, /tmp/bare2/simplon)
```

It reads *assembled by* rather than a bare version because the line sits under the **product's** own
commands, where a number alone would be read as the product's. The editable marker comes from PEP 610
`direct_url.json`, which is what pip records for `pip install -e`, rather than from the shape of the
path. Every half degrades to a phrase instead of raising - a help screen that fails because the tool
could not introspect itself is worse than one that says *unknown* - and a product that declares its own
epilog keeps it, with the kernel's line below it. Top-level app only, and no `--version` flag comes with
it. Nothing to do.

### The C++ model can say what a target IS (si#131, si#132, si#134)

0.10.0's generator read a tree and wrote build files; it could not be told what it was looking at. A
directory one level down was invisible, a library was static because nothing said otherwise, an include
path was `PRIVATE` so no consumer inherited it, and a co-located unit test was compiled INTO the library
it tested. That last one shipped test code and its framework's symbols inside the artefact, and no run
said a word about it.

**A nested directory folds into its parent target.** The alternative - promoting it - has to invent a
name, and every invented name collides in the flat namespace that `depends:`, `add_subdirectory` and the
solution GUIDs already share. Folding invents nothing, matches what the .NET SDK's own glob does, and is
the only default a product can escape by moving the directory.

**The location names the test level.** `src/<target>/<name>_test.cpp` is a unit test and is lifted out
of its library; `tests/` holds system and acceptance tests. Levels are ctest LABELS, so `ctest -L unit`
really selects.

**A build type, and no new key for it.** `support:toolchain` already scaffolds the profile into the
product's manifest, so the argv IS the key - `RelWithDebInfo`, changeable where every other toolchain
decision is made. Nothing is written into the generated `CMakeLists.txt`, because a committed
`set(CMAKE_BUILD_TYPE ...)` would decide it for every consumer of that tree forever.

The proof is at the artefact, not at the generated text: `file` distinguishes the shared object from the
archive, `with debug_info` distinguishes a debug build from one without - and it is the only thing that
does, because a build with NO build type is already `not stripped` and `nm` still lists its symbols. The
archive is read to confirm it does not carry the test's object. Each of those was seen red first.

**Nothing to do**, unless a product already relied on a nested directory being ignored.

### A gate names where its results landed, and an empty level goes red (si#133)

`allure.merge_results` was always technology-agnostic, and a product could reach it only by writing an
`impl:` gate in Python. A gate now declares `results_from:`, naming the directory its own runner wrote
results into, and the kernel merges it after the runner ran.

**A level that contributed nothing is red.** That is the whole point: an Allure report rendered with a
level missing looks exactly like one where the level passed. The kernel counts TEST CASES rather than
files, because a runner whose selection matched nothing writes a file and exits 0 - `ctest -L
<nothing>` does exactly that, and so does `dotnet test --filter` matching nothing.

The counting table is closed and its default is open: a format the kernel cannot parse counts as a
contribution rather than as an absence. Allure reads more formats than this kernel will ever know, and
calling a level empty because the checker could not read its evidence is the same defect pointing the
other way.

Measured while building it: the pinned Allure image carries `junit-xml-plugin`, `xunit-xml-plugin` and
`trx-plugin`, and raw allure-results JSON mixes with JUnit XML and TRX in one directory. The .NET SDK
image ships the TRX logger and no JUnit logger.

**Nothing to do.** A gate that declares no `results_from:` behaves exactly as before.

### A command gate can finally name the command a C++ or a .NET level has (si#136)

si#106 gave a gate a `command:` key so that a product whose test runner is a containerised toolchain
gets a verdict instead of a bare exit code. It could not name a `toolchain:run` command - the one command
such a product actually has. `run_toolchain`'s first parameter is a `typer.Context`, a gate refused any
body that took one, and every test behind si#106 resolved to a context-free stub, so the feature was
green over a case it could not do while both case chapters described the shape.

**A gate is not a CLI invocation, so it hands such a body what it truthfully can and nothing else.** A
`GateContext` carries the path of the command the gate is running - which the manifest names, and which
is the only thing `run_toolchain` reads off a context, to say which command a broken `with:` block was
read from. A body reaching for the rest of a Click context (`args`, `params`, `obj`) is asking a gate for
a command line it does not have, and is told so by name rather than handed an invented empty one.

**The gate-names-itself loop is now refused as itself.** It used to ride on the context rule, which was a
different statement wearing its clothes - and measured, it did not even hold: a product body that takes
no context and calls `testrun.accept()` passed the check and recursed until the interpreter stopped it.
That indirect case is recorded rather than patched here; the direct one is refused by name, at resolve
time, before a clearing gate has emptied anything.

**Driven, not asserted.** `tests/test_suites_command_gate_e2e.py` compiles a real CMake project in
`silkeh/clang:19` and runs a real `ctest` through a real gate: green, red carrying ctest's own rc of
**8** rather than 1, and a tree that does not compile stopping at the preamble with the stale binaries
untouched. Two quoted refusals on `building/test-levels.md` were repaired on the way - one listed a
parameter set `run_toolchain` does not have and was unreachable for it anyway, the other named a
required-parameter refusal that body cannot produce - and `tests/test_test_levels_refusals.py` now builds
them from the code that raises them.

**Nothing to do**, unless a gate of yours relied on a context-taking command being refused.

### simplon init reads what the repository already knows (si#129, si#130)

The product name argument is now OPTIONAL and defaults to the `origin` remote's repository name, falling
back to the working tree's root directory name. The argument still wins. A name that cannot become a
launcher filename and a shell token - `Ops Tools`, `my.ctl` - is REFUSED with the command that fixes it,
never mangled into something that half works, and `init` outside a repository says so and names the
argument rather than tracebacking.

The orchestrator block's default is now `deploy/provision/orchestrator`, which is where every product
that exists already puts it. `orchestrator/` remains available as `--orch-dir orchestrator`.

**A credential leak fixed on the way.** The remote URL is quoted back to the user, and a URL is one of
the places a token routinely lives: GitLab CI writes
`https://gitlab-ci-token:<job token>@gitlab.com/...` into every job's checkout, so this would have
printed a live token into every CI log. The whole userinfo field is replaced with `***`; a rule that
tried to decide which halves of it are safe would be a rule that can be wrong.

**Before you bump:** a new scaffold lands in a different directory than it did in 0.10.0. Existing
products pass `--orch-dir` explicitly and are unaffected.

### The release-notes guard becomes a kernel gate (si#89, si#103)

Until now the rule that a release documents what it carries was simplon's own house rule, living in
simplon's own `tests/`. Every other product consuming this kernel could release undocumented and nothing
would say a word. It is now the catalogue coordinate `test:release-notes` - **declared, not placed**, so a
product opts in by naming it.

**It is a `test:` gate and not a `release:` step**, and the reason is when it can still help. Notes are
written BEFORE the tag; the tag points at a tree that already carries them. A guard speaking at
`release tag` speaks after every cheap chance to fix the omission has passed, and it would have caught
neither of the two cases that turned `main` red while this was being built - both of them pull requests,
days away from a tag. A prepared release's range already ends at `HEAD`, so the question is answerable on
every push.

**si#103 is settled by a distinction rather than by an exemption.** A subject GitHub composed is not a
statement about the work: `Merge pull request #N` carries the pull request's number, so the commits it
brought in are read instead. What a notes PR must name is its own TICKET number, which its author had
before the branch existed. What it never has to name is a number that did not exist when the notes were
written. The ticket's own proposed fix - `git log --no-merges` - would have broken the guard outright,
because the population IS merges and a ticket named only in a merge subject would vanish.

The floors are manifest data: a page path, a version the guard starts reading from, and a version it
holds to completeness. An exemption LIST was asked for and refused - a list is what grows quietly, while
the gap between two floors can only be widened in public.

Two defects found on the way, both older than the change. A checkout with no tags blamed the PAGE ("every
section documents a version that carries no tag") when the fault was `fetch-depth`. And
`test_the_page_states_the_floor_it_is_held_to` could not fail: it searched the whole page, and `## 0.4.0`
IS the string `0.4.0`, so the page satisfied the rule by carrying the very section the rule exists to
excuse.

**Nothing to do** unless you want it: declare `test:release-notes` in your manifest and give it the three
values.

### Downloads say what they are doing, and uploads stop being swallowed (si#142, si#143)

simplon downloaded the docker CLI tarball, the oras release asset and `get-pip.py` in silence. `fetch` is
one kernel function with a progress bar, public so a product uses it rather than writing a fourth. No new
dependency: the kernel declares no `rich` and imports nothing from it, and adding one to draw a bar would
be the wrong trade.

On a terminal it repaints in place; **into a pipe it writes plain lines with no `\r`, no erase sequence
and no bar cells**, because this runs in CI far more often than in a terminal. Without a `Content-Length`
it turns a spinner and claims no percentage it cannot know.

Three things came with it that the ticket did not ask for and that matter more than the bar:

- **A timeout.** `urlretrieve` has none, so a hung server hung the command forever with no output at all.
- **A short body is now an error.** A temporary name and a rename on success is NOT enough:
  `HTTPResponse.read(amt)` returns `b""` on a truncated body and raises nothing, so the download reported
  success and the rename happened. The next run then treated a half file as cached.
- **The scheme is refused on every hop.** urllib's redirect handler admits `http`, `ftp` and an empty
  scheme for intermediate hops and follows the whole chain before the caller sees anything, so
  `https -> http -> https` passed because it ended where it was supposed to. Reproduced with three real
  servers.

The upload half is deliberately NOT symmetric: simplon uploads no bytes itself - every upload shells out
to `oras`, `gh`, `docker` or `dotnet` - so a bar there would mean reimplementing authentication, chunking
and OCI manifests to draw over them. What was wrong is that `gh release upload` ran through `run.run`,
whose default captures, so its progress was swallowed. `run`'s documentation now carries the rule and its
counter-example: `gh release create`, four lines above, reads `"already exists"` out of its captured
output and must keep capturing.

**Nothing to do.**

### The Textual runner: a run you can follow, and one file you can quote (si#148)

Nine changes to the step runner. The three that matter most:

**The bottom bar follows the PROCESS, not the cursor.** It names what is running and for how long,
alongside the run's counts and elapsed time, wherever the operator has navigated. Until now the tree row
and the details pane both followed the cursor and nothing followed the process, so navigating away meant
losing sight of the run.

**`auto_scroll` was fighting the reader, measured.** `RichLog.write` calls `scroll_end` unconditionally
and never asks where the reader is, so a reader at line 10 was thrown to line 182 by a single emitted
line - following a running step by reading it was impossible. The pane now has a sticky bottom: the
position before a write decides the position after it.

**There is a run transcript**, `build/logs/run-transcript.log`: every step in order with its command, its
rc, its duration and the run's provenance header. A log per step existed; a log of the RUN did not, and
that is the thing somebody attaches to a ticket.

Also: state now carries COLOUR from the theme rather than a glyph alone - the glyphs stay, because a state
that is only a colour is invisible to a reader with colour vision deficiency, to a broken palette and to a
log file, and the shared label helper keeps producing markup-free text for the headless runner and the
transcript. Plus follow mode (`f`), next-failure (`n`), a `/` filter, remembered scroll positions, and
Textual's command palette, which is where the new actions are discoverable without a footer that has
become noise.

**Nothing to do.** The headless path is unchanged.

### Output arrives when it happens, not when a line ends (si#144)

A step's output used to reach the pane in bursts, or only once the step ended. The cause was measured
rather than guessed, and it is neither buffering nor a missing pty.

**A line only exists once the child writes its terminator, and these tools write output that has
none yet.** `run_stream` iterated lines. pytest writes one dot per test and completes the line every
seventy-two of them, so on `./simplon.sh test all` the child wrote **2865 times and the reader handed
over 126 times**, with a byte waiting up to **11.37 seconds** - the pane frozen for eleven seconds while
the child was writing every few milliseconds. It now reads chunks, splits on carriage return and
newline, and hands over the partial line it holds once the child has been quiet for 0.1s. The same step
afterwards: 191 segments, worst silence 6.93s, and the residual is pytest's own collecting, which no
reader can shorten. The 0.1s came off the latency curve - 0.05s buys 0.65s worst for 210 segments, 0.2s
gives 1.76s for 159.

**The carriage return was not the cause, and the first candidate was wrong.** `run_stream` passed
`text=True`, which turns on universal newlines, and `\r` was already a terminator for `readline`: a
`git clone --progress` writing 405 of them came out as 412 lines with nothing delayed. What a repaint
costs here is a bar becoming a page, which is a display question, not a latency one. The split is kept
explicitly, because dropping `text=True` for chunked reading would otherwise have lost it.

**Child-side block buffering is not present in this toolbox.** Measured on this machine, first byte out
of a plain pipe: `docker pull` 1.69s (its own first byte), `docker build` 0.25s, `curl --progress-bar`
0.13s, `git clone` 0.00s, `oras push` 0.00s, `containerlab` 0.11s, and simplon's own step child 0.68s.
Every one of them delivers as it writes. The only child that block-buffered was a Python child without
`-u`, and this kernel spawns none: `simplon.sh` execs `python -u -m <module>` and the step factory
builds `[sys.executable, "-u", ...]`. `stdbuf -oL` changed nothing about even that child, confirming
what it says on the tin - it sets libc STDIO's mode, and neither Python's `io` nor Go's `os.Stdout` is
libc stdio.

**A pty was rejected, with its price measured.** It fixes exactly one tool, `gh`, which writes **nothing
at all** to a pipe by its own terminal check. It costs everywhere else: the same `docker build` goes
from 822 bytes to 37196 - 45x - with 397 carriage returns, and `oras push` from 444 to 2774. Every one
of those bytes would land in the step log and in si#148's run transcript, which is the file somebody
attaches to a ticket. `gh`'s silence is a per-tool fact for a per-tool answer on the day a step needs
it.

**A row highlighted mid-run now shows what the step has already said.** `Outcome.output` is only built
after the action returns, so the details pane said `(running…)` however much the step had printed, and
whatever went by while another row was selected was gone. si#148's follow mode covers the operator who
touches nothing; this covers the one who navigates away and comes back. The backlog is the list the
streaming step already collects into, handed to the `Step` by reference - one buffer, not a second copy
of the step log kept for the pane.

**What a product sees change.** A step log gains lines the child did not end itself: 126 to 191 for
`test all`, and 21 to 22 for this repository's own `build.site`. None of them is markup - no escape
sequence and no carriage return enters a step log or the transcript that did not enter it before. The
`build.site` line is worth looking at, because it is a repair rather than a cost: hugo writes `collected
modules in 1469 ms` without a terminator, and on the old reader that text was GLUED to the front of the
next log line. The headless path is otherwise unchanged, and CI output stays complete.

### The design behind the language cluster, as a document (si#135)

`docs/superpowers/specs/2026-09-09-the-language-cluster-design.md` records the four decisions eight
tickets share - no new top-level manifest section, the location names the test level, a gate may name
where its results landed, and `simplon init` defaults rather than decrees - together with the
artefact-level proof each of the eight owes. Two of its own claims were disproved by the lanes that
built against it and are corrected in place, which is the document working rather than failing.

### The guard over the results cutoff stopped depending on the clock (si#86)

`_started()` - the instant a gate hands its merge, floored to the whole second - is what keeps si#70's
rule honest: a report takes only what this run wrote. The unit test guarding that rule MEASURED the wall
clock instead of setting it, comparing an instant this process read with the instant the kernel stamps a
file with. Those are two reads of CLOCK_REALTIME taken in different places, and they are not ordered
with respect to each other: measured at up to 7047 ns apart, the wrong way round, across a CPU migration
between them. The guard now stamps both files and picks the cutoff between them, and the floor that
protects the real callers is guarded where it lives.

Measured, and it refutes the ticket's own suspicion: one- or two-second mtime granularity would have
failed that assertion on every attempt rather than on one run in four, so it was never the cause.

The same shape was found and removed one module over, in si#133's own tests: a fixture written before
the run started is one second boundary away from being read as the previous run's, so it is written by
the run now, the way the other twenty-two tests in that file already do it.

**Nothing to do.** No behaviour changed - the only source change is a docstring.

### Before you bump

**The scaffolder no longer empties your manifest of its comments** (si#110). `support toolchain` read
the file with `yaml.safe_load` and wrote it back with `safe_dump`, so on a freshly scaffolded manifest
forty-two comment lines became zero and every flow mapping was expanded to block style. It splices its
commands into the text now, and everything you wrote survives. Nothing to do beyond bumping.

**The C++ `analyse` profile analyses something, and can go red** (si#111). `clang-tidy -p build` takes
its sources as positional arguments and named none, so the entry refused every run it was ever given.
It is `run-clang-tidy -p build -quiet -warnings-as-errors=*` now, which reads the compile database
`configure` already wrote and walks it. The last flag is what makes the command a check rather than a
report: clang-tidy reports its findings as warnings and exits 0 without it, so `analyse` was green on
every tree. Re-run `support toolchain cpp <version>` to pick the new argv up, or edit the one line in
your manifest - the scaffolder never overwrites a command you already have.

**The Python profile runs at all** (si#121). It named `python:3.12` and the two bare words `pytest` and
`mypy`, and the official image carries neither, so both commands exited **127** before the product was
looked at. A fatter image is not the repair: mypy over a tree whose imports are not installed reports
missing stubs rather than type errors, and no image on any registry carries a product's wheels. So the
profile installs its two tools itself, into a `PYTHONUSERBASE` inside the bind mount - the one directory
a `--user`-mapped container can write, since a named docker volume is created root-owned. There are
three commands now: `build deps` (pinned `pytest==9.1.1` and `mypy==2.3.1`, the only one that needs a
network), `build unit` and `build analyse`, the last two run through `python -m` because a `--user`
install puts its scripts somewhere that is not on `PATH`. `analyse` excludes
`deploy/provision/orchestrator/`: that tree is host-venv Python and `test:typecheck-python` is what
checks it, so a container that has neither the kernel nor typer could only report five import errors
about the scaffold and none about the product. The user base is 80 MB and lands in your tree beside
`.mypy_cache` and `.pytest_cache`; `simplon init` scaffolds no `.gitignore`, so those three lines are
yours to add.

**The Java `compile` compiles, and the Java `analyse` is gone on purpose** (si#122). `compile` was
`gradle build`, which depends on `check` and therefore ran the tests - so a broken assertion made the
*compile* red, and a gate whose `preamble:` is `build compile` reported `setup-failed` for a product
fault, which is the exact distinction the preamble exists to draw. It is
`gradle assemble testClasses` now, and neither `assemble` nor `build -x test` alone would have done:
both produce the identical task list, neither runs `compileTestJava`, and both are green over a test
source that does not compile. The profile also carries **no `analyse`**, which is now a stated decision
rather than an empty slot - `gradle check` on a stock `java` plugin is `test` under another name, and
`gradle check -x test` runs one task, no javac, and exits 0 over a raw type, an unused import, a dead
store and a certain NullPointerException. Java's checkers are Gradle plugins a product's own
`build.gradle` applies.

**Re-running `support toolchain` will not fix an existing manifest**, and that is the never-clobber rule
working rather than failing: a command you already have is kept and named. A product on the old entries
edits the argv itself - one line each for Java, and for Python the two commands plus the new `deps`
beside them.

## 0.9.0

**0.8.0 shipped a uniform build that no product could drive.** This is the release that can, and the
reason it took a second one is worth stating plainly: every test in 0.8.0 was a unit test with a stubbed
`run`, and the plan's own end-to-end step - "netctl's CI green with `build compile`" - was never
executed. Two people writing use case chapters drove it for real within a day and found four defects
between the design, the scaffolder and the loader.

A minor rather than a patch, because si#106 adds a gate kind: a manifest surface, not a repair.

### Before you bump

**`support toolchain` takes the version as a second argument** (si#105). It always needed one - every
profile's image is a `{version}` template - but the catalogue declared only `language`, and
`signatures.bindable` drops `**kwargs`, so it raised `KeyError: 'version'` for every language:

```
./<product>.sh support toolchain cpp 19
```

or pinned per command with `with: { version: "19" }`.

**The block the scaffolder writes now assembles** (si#105). It did not: the loader binds `with:` keys to
impl PARAMETERS, and `run_toolchain` took none of `image`/`workdir`/`argv`/`env`/`caches`. A manifest
that a product's own scaffolder writes and the product's own loader then refuses is the shape this
release exists to remove. If you scaffolded under 0.8.0, re-run `support toolchain` - nothing else to do.

**A command's tail reaches the tool again** (si#105). "Manifest first, caller appends" is what the design
promises and 0.8.0 did not deliver: `./x.sh build compile --verbose` answered `No such option`. It needed
both halves - a variadic positional AND `passthrough_args: true` - and neither works alone.

**No `instance:` section is needed unless a command declares caches** (si#105). It was resolved before
anything asked whether a cache existed, so a freshly scaffolded product died on its first command.
`simplon.yaml` itself has no such section.

### A command in the product's tree can back a gate (si#106)

`Gate` took `suite:` (a pytest root) or `impl:` (a product callable). A `toolchain:run` command is
neither, so a product whose test runner is a containerised toolchain got an exit code and NO verdict - no
`setup-failed`, no marker, no Allure archive.

Measured, and this is the failure that made it urgent rather than untidy: a C++ product's `build compile`
exited 2 on a type error, and `build unit` then reported **`100% tests passed, 0 tests failed out of 3`**
off stale binaries. A positively wrong green.

A gate may now name a command:

```yaml
suites:
  unit:
    command: "build unit"
    preamble: "build compile"
```

The kernel resolves it the way the CLI does - the body its `task:` names, with that command's own `with:`
pinned - and turns the rc into the same verdict vocabulary every other gate produces. The alternative,
making `toolchain:run` usable as an `impl:`, was rejected: a gate's `impl:` is called with no arguments,
so it would need a second copy of image, argv and caches inside `suites:`, beside the command the product
already declares. Two declarations of one build drift, and then the verdict is about a line nobody runs.

The cost is stated in the code: the command is resolved at gate-run time, so a typo is a run-time
refusal - but everything resolves BEFORE the results directory is cleared, so a typo can no longer cost
the last real run's archive.

### Two use case chapters, driven rather than described (si#108, si#109)

`case-cpp` and `case-dotnet` walk the whole loop with real products - CMake and ctest, `dotnet build` and
xUnit - scaffolded, wired to the kernel and run. Every command on those pages is resolved against the
tree their fixture manifests assemble, every quoted refusal is pinned against the code that builds it,
and every step carries `run`, `derived` or `does not exist yet` with the ticket where a decision is open.

They are the reason this release exists: writing them is what drove the kernel, and driving it is what
found si#105 and si#106.

## 0.8.0

One merge, and it adds a catalogue coordinate - which is why this is 0.8.0 and not 0.7.2. Nothing existing
changes; the count on the [rules page](../../building/rules/) moves from 25 to 26.

### Before you bump

**Nothing.** `support:ci-privileges` is DECLARED and not placed, so no product's CLI grows a command it
did not ask for. If you want it, place it like any other offered task:

```yaml
support:
  commands:
    ci-privileges: { task: "support:ci-privileges" }
```

### The uniform build: one task, four languages (si#95, si#99, si#100, si#101)

The largest thing in this release, and the shape it took is the argument for it.

**`toolchain:run`** runs a pinned image over the product tree, as the calling user, with named caches. It
is the half of a build that is identical in every language: Java, C++, .NET and Python differ in which
image runs and which argv it is handed, not in how a container is wired to a source tree. It is a
FAMILY rather than a placement, because a toolchain is needed by `build` AND `test` - ctest, dotnet test
and gradle test all belong under the latter.

**`support:toolchain`** writes a language's ready-made configuration into the product's manifest:

```
./<product>.sh support toolchain cpp 19
```

lands `configure`, `compile`, `unit` and `analyse`, each a `toolchain:run` command with a pinned
`silkeh/clang:19`. A product declares its parameters and receives the rest.

**Scaffolded, not resolved at run time**, and that is a safety property rather than a convenience. A
profile read while a build runs would let a kernel release change what that build does - the same class
as an unpinned image, one level up. Written into the manifest, the product owns what it runs from then
on, and this kernel's table can move without moving anybody's build.

**It never clobbers.** A command that already exists is left as it is and named. The edit was somebody's
decision, and the scaffolder cannot tell a deliberate one from a stale one.

Both coordinates are DECLARED and not placed, so nothing appears in a product's CLI until the product
asks for it.

### A gate may be backed by a command, so a containerised runner gets a verdict (si#106)

The uniform build above buys a product the COMMAND and, until this, lost the VERDICT. A gate took a
pytest root (`suite:`) or a product callable (`impl:`); a `toolchain:run` command is neither, so a
product whose test runner is `ctest`, `dotnet test` or `gradle test` got an exit code and nothing else -
no `setup-failed`, no setup marker, no allure results, no archive.

A gate may now name a command in the product's own tree, and its two hooks name commands too:

```yaml
gates:
  - name: "unit"
    command: "build unit"          # what a person types, and what the gate reports on
    preamble: "build compile"      # the build that has to succeed first
    results: "clear"
```

**The `preamble:` line is why this is a kind and not a convenience.** Measured on a C++ product:
`build compile` exited 2 on a type error, and `build unit` then reported `100% tests passed, 0 tests
failed out of 3` - ctest over the binaries the failed compile had not replaced. Three passing tests for a
product that does not compile, and nothing could see the pair, because neither half was a gate. Named as
a gate's setup, a non-zero build ends the level as `setup-failed` and the test command never runs.

The command is resolved the way the CLI resolves it - the body its `task:` names, with its own `with:`
pinned - so the image and the argv are declared once, in the command, and the verdict is about the
command a person actually types.

**What a product has to do about it: nothing.** `command:` is a third alternative beside `suite:` and
`impl:`, both of which mean exactly what they did. Two load-time refusals are worded differently (the
exactly-one-kind lock now offers three, and the opacity lock names the kind it is refusing), and no
refusal was added or removed. The [test levels chapter](../../building/test-levels/) carries the whole
of it.

### The release guard asked for notes about pull requests (si#97, si#98, si#103)

Two defects in this repository's own gate, found by trying to cut this release four times.

**The first was red on every pull request** and had been for as long as the rule existed.
`test_every_merge_in_a_documented_range_names_its_ticket` asks that every merge in a release range names
a ticket. CI runs `on: [push, pull_request]`, and the `pull_request` event checks out
`refs/pull/N/merge` - an ephemeral merge GitHub composes, whose subject is exactly
`Merge <40 hex> into <40 hex>`, with no ticket and no way for an author to add one. So every PR carried
one permanently red check that had nothing to do with its content.

**The second was a catch-22 and stopped this very release.** A pull request merged from the web interface
gets `Merge pull request #N from <branch>`, so the PR carrying the release notes named ITSELF - and no
notes can anticipate their own merge. A follow-up PR would have brought its own number too; the regress
had no floor.

Both rest on one distinction. An **authored** merge subject is a statement about the WORK; GitHub's
wording is a statement about the VORGANG. The guard now reads the first as written, and for the second
reads the commits that merge BROUGHT IN, which is where the author put the number. The unit stays the
merge; only the place the statement is looked for moves one level down. With a floor: several merges
from before the convention name nothing in their commits either, and dropping those would excuse work
rather than describe it, so the subject's number remains the fallback.

**What a product has to do about it:** name the ticket in the COMMIT, not only in the pull request
title. `docs(#42): ...` rather than `docs: ...`. That is this repository's own convention already, and
it is now the thing the guard reads.

A defect in this repository's own gate, and it had been red on every pull request for as long as the
rule existed. `test_every_merge_in_a_documented_range_names_its_ticket` asks that every merge in a
release range names a ticket in its subject. CI runs `on: [push, pull_request]`, and the `pull_request`
event checks out `refs/pull/N/merge` - an ephemeral merge GitHub composes, whose subject is exactly
`Merge <40 hex> into <40 hex>`, with no ticket and no way for an author to add one.

So every PR carried one permanently red check that had nothing to do with its content. The fix skips
that one subject and only that one: a full match on the machine format, so a real merge whose author
forgot the number is still caught, and one that prefixes GitHub's wording to disguise itself is not
excused.

### Also in this range: a design and its plan, and nothing built from either (si#95, si#96)

The spec for `toolchain:run` and the uniform build across Java, C++, .NET and Python landed in this
range as a document, and its implementation plan behind it. **Nothing in 0.8.0 implements either** -
they are in `docs/superpowers/specs/` and `docs/superpowers/plans/`, to be read and argued with before
code exists.

Both numbers are here because their MERGES are in the range, and this paragraph is what keeps them from
reading as shipped changes. Worth noting for si#89: neither number appears in a single authored commit
subject - they come only from GitHub's automatic `Merge pull request #NN` line, so the guard is asking
for notes about pull requests rather than about work.

### The CI privileges of a host, as a task that refuses unless it is root (si#92, si#93)

Every product that puts a CI agent on a host was writing the same six lines by hand, and one of them is
easy to leave out:

```sh
grep -q '^#includedir /etc/sudoers.d' /etc/sudoers || echo '#includedir /etc/sudoers.d' >> /etc/sudoers
```

Without it the drop-in in that directory is **inert**, and everything still looks right. Measured on three
CI hosts that answered `sudo: a password is required` while the file sat at exactly the expected path with
exactly the expected content. Nothing in those six lines is product knowledge - only the user name.

Three things it does that a copied snippet does not:

- **It refuses unless it is root, and says why.** This grants the privilege the kernel needs in order to
  be allowed to do anything, so it cannot take it from inside a job - si#87 drew the same line one level
  down. The refusal names the cure; "it did not work" would be useless.
- **It validates the sudoers file before it is in force.** A broken file in `/etc/sudoers.d` does not fail
  the command, it breaks `sudo` for everyone on the host - and the way back needs the privilege that just
  stopped working. So it is written beside the directory, checked with `visudo -cqf`, and only then moved.
- **It verifies as the USER, not as root.** Root can always sudo, so a check from here would pass on a
  host where the grant did nothing. It also says that an agent which is already running must be restarted,
  because a process inherits its groups at start - and it does not restart anything, because it does not
  know what the service is called.

**Why it is not placed**, while `support:install` beside it is: this one hands out `NOPASSWD: ALL`. A
command that changes who may become root on a machine has to be something a product asked for, not
something it received along with the kernel.

## 0.7.1

Seven merges, and they have one thing in common worth saying first: **six of the
seven were found while doing something else and reported instead of quietly
repaired.** Four came out of driving the Java use case (#26), one out of fixing
a neighbouring ticket, one out of a consumer's migration. That is the habit this
kernel is trying to keep, and this release is what a week of it looks like.

### Before you bump

**`parent_suite:` no longer passes silently where it does nothing** (#79).
`report.merge` accepted the key and tagged nothing when the source was JUnit XML
- only Allure raw results (`*-result.json`) were ever tagged. A Java product
therefore declared a key that had no effect, and nothing said so. If your
product sets `parent_suite:` on a JUnit-XML suite, you were not getting what you
wrote.

**`docs:render` no longer runs as root** (#78). In the usual CI order it made the
next Gradle run impossible: the render wrote root-owned files into the tree, and
the build after it could not touch them. The uid is now read off the TREE rather
than set, so the render writes as whoever owns what it is writing into.

**`SETUP_MARKER_ENV` is advertised** (#80). Since #59 a product-owned runner may
report that its SETUP fell over - the run then says `setup-failed` with
`ran = False` instead of `failed`, which is the honest distinction between "the
suite ran and was red" and "there never was a suite". It was reachable and
undocumented, so no product reached it by default.

### The docker group membership belongs to the install (#87)

`_grant_socket_access` did two things of very different durability under one
name: `usermod -aG docker` is durable but takes effect only in a NEW session,
while the `setfacl` / `chmod 666` on the socket is transient and gone when the
daemon recreates it. Because the ACL works instantly, nothing ever revealed that
the membership had not reached a long-lived caller at all - a process inherits
its groups at start, so a service already running never gets it. And the whole
block sat behind `if not _daemon_reachable()`, on the failure path, so on a host
whose socket happened to be permissive it never ran.

Measured on three CI hosts that ran green for months and then failed at three
unrelated moments with no commit in common: `getent group docker` answered
`docker:x:991:` - the group exists and is EMPTY. `get.docker.com` creates it and
puts nobody in it, so a freshly installed host locks out every non-root caller.

The membership is now established by `_install_engine`, the one moment privilege
is known to be present and the state is being created from scratch, and
`_grant_socket_access` still calls it so an older host gets it too. root is
skipped - it reaches the socket by being root.

**What a product still has to do itself**, because the kernel cannot: grant the
passwordless sudo (the seed privilege the kernel needs in order to be allowed to
do anything), and, if it provisions a long-lived service, set the membership
before that service starts. A job-time call never reaches an agent that is
already running.

### The refusal says what re-applying costs (#56)

Found by a consumer migrating to 0.4.0, and it is this project's own defect class
in a tool built against it. The refusal for an old-form manifest prints a
complete rewrite - correct, loaded in one pass since #42, and carrying **zero
comments**, because it is generated from the parsed manifest. Applied, the
migration is green and the reasoning is gone. The refusal now says how many
comment lines re-applying it would throw away, so the choice is made with the
price visible instead of after it.

### The group description reaches the generated reference (#77)

Found while fixing #75 and reported rather than repaired along the way. #75 got
the group description from `catalogue.yaml` onto the screen - `--help` says
*"Produce the artefacts."* instead of *"build commands."*. The generated command
reference still showed the old text: a third surface of the same taxonomy that
nobody had counted. The surfaces are counted now, and the description reaches all
of them.

### Named here, and deliberately not shipped: the notes guard itself (#89)

Cutting this very release ran the guard into its own gap. `tests/test_releases_page.py` stopped the tag
because the section described one of seven merges - which is exactly what it exists for, and it worked.
But it is a HOUSE rule: it lives in this repository's `tests/`, `src/simplon/` knows nothing of it, and
the catalogue places nothing, so **no other product has it**. A product on this kernel can tag, publish
and never write it down, silently.

si#89 records lifting the mechanism into the kernel as a placeable gate - the rule is product-free, and
only the page path, the floor and the exemption list are product data. **None of it is in 0.7.1.** The
number appears in this release's merge range because the notes commit referenced it, and this paragraph
is here so that the number does not read as a shipped change.

### The self-exemption was measured against a population that never saw the rule (#83)

The fourth wrongly chosen population in this repository, and it concerns a number
that has been quoted repeatedly. The struck rule `check_every_task_is_used` read
only `product_tasks` - so the exemption granted in #48 was justified against a
set the rule never examined. The reach of an expression rule is now MEASURED
rather than labelled, which is the same move this repository has made four times
and, on the evidence, will make again.

## 0.7.0

One merge, and both halves of it are the same observation: a value every product
answered the same way was being carried as if it were a decision.

### Before you bump

**The committed shell completion moves to `deploy/completions/`** (#84). It was
written into `completions/` at the product root — which is where a reader looks
for what the product *is*, and a directory holding one generated shell file is
not that. `deploy/` is where this kernel's other outputs already live.

The path is still **not configurable**, for the reason it never was: a knob here
would be a second place to look for one file, and an installation instruction has
to be able to name the path without asking.

Migration is two steps and a shell:

```bash
git mv completions/<product>.bash deploy/completions/<product>.bash
./<product>.sh support completion          # rewrites it in place, and prints the source line
```

Then re-source it — the line in your `~/.bashrc` names the old path and will
silently complete nothing after the move. `support completion --check` returns 1
until the file is where the kernel now writes it, so a product whose CI runs that
check finds out rather than losing TAB quietly.

It is deliberately **not** `deploy/<orchestrator block>/completions`, which was
the first proposal: the block does not sit at one path across products — this
repository and agile-cockpit keep it at `deploy/orchestrator`, cleon at
`deploy/provision/orchestrator` — so a constant naming it would be right in one
checkout and wrong in the next. `deploy/` is the part they share.

**`suites.reports:` is now optional and defaults to `tests/reports`** (#84). It
was required until every product had written the same line, which is the point at
which a universal answer has been masquerading as a per-product decision — and a
required key with only one sensible answer teaches people to copy it rather than
choose it. `tests/reports` sits beside the suite rather than under the product
root, because the outputs of a test run belong with the tests and a root
directory called `reports/` says nothing about what produced it.

**Nothing changes for a manifest that declares the key**: a declared value still
wins, and no existing product moves unless it deletes the line. An *empty*
`reports:` is still refused rather than read as a request for the default —
`""` is a statement, and reading a typo as a default is exactly the silence a
default must not buy.

## 0.6.0

Seven merges. The theme, if there is one, is ownership: a test run learns which
results are its own, an image declaration is checked against the tree it points
into, and two rules the kernel had been carrying were measured and one of them
struck.

### Before you bump

**A test run now owns its results directory, and your report may count fewer
tests than it used to** (si#70, si#69). `test report` merged whatever stood in
the declared merge sources, and those sources are the *product's* directories — a
Gradle build's JUnit XML, an npm reporter's output — which no `results: clear` on
either kind of gate has ever touched. Measured: a build that stopped in
`:compileJava` shipped an archive reading `{"failed":0,"passed":3,"total":3}`,
decoded from a file 66 seconds older than the run that shipped it. The step now
knows when the run began; files written before that are left where they are and
**named in the line**, with the reason. The same run now reports
`{"passed":0,"total":0}`. If your numbers drop after the bump, that is the defect
leaving, not arriving — and `test report` on its own, which has no run behind it,
still merges everything present, because that is its documented job.

Alongside it, `wrote_results` no longer infers ownership from the gate verdicts
(si#69): reaching the clearing step *is* the ownership, and deriving the same
fact a second way from the outcome had already been wrong once.

**`results: clear` is now accepted on an `impl:` gate** (si#61). 0.5.0 recorded
this as a measurement and left it: a product with no pytest anywhere in it could
not write a taxonomy that loads, and the way out was a pytest gate containing
`assert True`, a 29 MB suite venv, and an archive that counted four tests for a
product that has three. **No new key was invented.** `results` was refused on an
`impl:` gate because it was ineffective there, and the ineffective half is what
got repaired — the `impl:` branch now honours the clear. It is the one key that
means the same thing on both kinds of gate, because it is not a statement about
what a gate writes but about whose run the directory belongs to. Migration: none.
Both manifests carrying a `suites:` section open with a pytest gate, so nothing
changes for them, no refusal was added or removed, and the [rules
page](../../building/rules/) is untouched.

**`build:image` refuses a declaration that points at nothing, before it asks for
docker** (si#74). Both `dockerfile:` and `context:` are checked against the
product root, the message says *which* of the two moved, and it is asked before
`ensure_docker` — so "my manifest points into thin air" no longer gets "you have
no docker" for an answer on a machine without one. The finding came from a real
product whose Dockerfile had moved into `deploy/` with nothing in the kernel
noticing; the kernel's own test fixtures then turned out to carry the same defect,
three of them building an image with a context that never existed.

**A nested group with a namesake member is refused** (si#60). `support.git` with
a member called `git` and a sibling beside it does not assemble: the taxonomy
matches on the last segment while the assembly looks the spec up under the full
dotted path, and the result was `KeyError: 'support.git'` — a stack trace where a
diagnosis belongs. The refusal names both halves and both ways out: rename the
member, or move the group to the top level, where the two names are the same
string. The capability was deliberately *not* built: measured over this kernel's
manifest and the five in `surface.CONSUMERS`, zero of six declare such a group,
so what a product needs is to be told where the floor is.

**A task you declare and no command places now loads** (si#53).
`check_every_task_is_used` is gone. It was the one expression rule that exempted
the kernel from itself, and measuring the exemption is what ended it: it would
have refused 14 of the kernel's own 22 catalogue tasks, it was the only refusal
with no measured cause in ticket, commit or docstring, and across all six
reachable manifests it had never refused anything. A catalogue is an offer, and a
product may now write one too. **The price is recorded rather than implied:** a
product that moves a command onto a catalogue coordinate and leaves its own body
standing beside it now loses that body *silently* — the manifest loads, the
catalogue body runs, and the product's own is reachable from nowhere.

**The narrower diagnosis was then built** (si#81), and it draws the line
somewhere other than "used" and "unused". A catalogue coordinate is placeable by
any product, so unplaced there means *offered*; a manifest's own `tasks:` entry
is a bare name reachable only from commands in that same manifest, so unplaced
there means *unreachable*, with no second reading. Refused is the narrow case
only: a declaration no command instantiates **and** whose name a command has
already spent on a different body. A task nobody names still loads. What the
narrow form does not catch is recorded rather than implied — a move that renames
at the same time. Measured over all six reachable manifests: zero violations, and
zero for the broad form too, so the narrowness costs nothing today and only stops
it costing something later.

**Group help text changes** (si#75). `catalogue.yaml` has declared a description
per group since it was written and nothing ever rendered it; the CLI built
`"release commands. Environment-agnostic (no env)."` out of the group name
instead. Measured across the catalogue and all six manifests: eight group paths,
all eight carrying a `help:`, and 33 of 40 rendered sub-apps showing the invented
sentence.

```
before   build commands. Environment-agnostic (no env).
after    Produce the artefacts. Environment-agnostic (no env).
```

**Prepended, not replaced**, and that was decided against the real texts:
replacing takes from `deploy --help` the only line saying the group does not run
without an environment token, and no `help:` carries that half.

**`docs:site` writes `build/hugo-cache/`** (si#27) — the kernel's convention,
under the same `build/` your `clean` and `.gitignore` already cover.

### A site build no longer needs the network

si#27 asked for `hugo mod get` to be made conditional and called that the likely
answer. **The premise is refuted, and the measurement is why.** With the fetch
skipped entirely and no host-side cache, the build still dies at `git ls-remote`,
because the build resolves the theme module itself — and the condition would never
have touched FlexSearch and mermaid, which Hextra pulls through
`resources.GetRemote` while rendering. A persistent cache fixes both; the
condition fixes neither. So there is no condition: it bought 0.9 s and would have
paid with a build that, on a wrongly answered question, renders against the old
theme and says nothing.

The proof is a build with **no network**, not a faster one: every container run
with `--network none`, rc 0, 26 pages, diagram rendered. The same run against the
previous kernel exits 1 at `git ls-remote`. Three pages that said an offline build
was impossible now say what it costs instead — a fresh checkout, a `clean`, and a
moved pin each need the network once.

### Also

- **`verdict.exit_code` is applied only where its precondition is carried**
  (si#71). The 128+n translation belongs to a child process's wait status; it was
  being applied to every gate's rc, including an `impl:` gate's, which is a Python
  callable's return value and names no signal however negative it is. Harmless in
  every case measured — and a docstring and a use that said different things,
  which is how the next reader widens the wrong one.

### Documentation

**A complete Java use case** (si#26), the other half of the pair 0.5.0 opened:
[Delivering a Java product](../case-java/). Nine of its thirteen steps were
driven rather than derived, including `build docs` with docToolchain producing
HTML and PDF — the step the Python chapter says outright it never saw. Three are
derived and one does not exist. The three number series come out of the archive
rather than out of prose, and the interesting one is the third:

```
green             rc 0   passed 3, total 3    verdict passed
one test broken   rc 1   failed 1, passed 2   verdict failed
compiler error    rc 1   passed 0, total 0    verdict setup-failed
```

Three tests, not four — the difference si#61 made, in one number.

**The site's own numbers are counted and its links resolved** (si#66, si#67).
Three pages counted the examples and all three were wrong — eight sections
described as "seven", "Seven" and "six" — so the counts are built from the source
rather than typed, along with five other unchecked numbers. And there is a link
checker: 84 internal links across 17 pages, none of them dead, with every anchor
checked against the target page's headings. Hugo renders a dead relative link
without complaining, and a dead `menu.pageRef` builds rc 0 with no warning at all
— measured, which is why the checker exists.

### About these notes

The section above 0.4.0 used to be checked only for *existing*. si#82 measured
what that permitted — 0.5.0 described two of its fourteen changes and was green —
and `tests/test_releases_page.py` now holds each section against the merges in
its own range: every ticket number merged into a release has to appear in that
release's section. Not the wording, which no tool can derive; the completeness,
which it can.

## 0.5.0

Fourteen changes went into this tag. This section named two of them for the first
weeks of its life, because it was written from the pull request the tag was cut
through rather than from the range the tag covers — si#82 measured that gap, and
the twelve below come from `git log v0.4.0..v0.5.0` rather than from anybody's
memory of the release.

### Before you bump

**Four modules that 0.4.0 announced as moved are gone** (si#73). If your product
still imports one of the old paths, it now fails with `ModuleNotFoundError` rather
than warning. The fix is the right-hand column:

| Gone | Import instead |
|---|---|
| `simplon.allure` | `simplon.tasks.allure` |
| `simplon.vcs` | `simplon.tasks.gitops` |
| `simplon.images` | `simplon.imagenames` |
| `simplon.nexus` | `simplon.nexusproxy` |

Measured through the API on the day of the release rather than assumed: **one
product is affected, at three lines** — netctl, at
`orchestrator/tooling.py:32`, `orchestrator/guard.py:55` and
`test/.../test_nexus_manifest.py:20`. It is not, however, a product this
grace period ever reached: netctl pins `simplon==0.3.0`, where `images` and
`nexus` are the *real* modules and `imagenames`/`nexusproxy` do not exist yet.
Those three lines are part of whatever upgrade takes netctl past 0.3.0, and
they change in the same commit that lifts the pin.

Two further lines the record named turned out never to have been simplon's:
asbundle reads `from delivery import images` — a different kernel that ships a
module of the same name — and biz-cockpit had already migrated. See
[Surface](../../building/surface/) for why re-measuring beats remembering.

**A killed run is a fifth outcome, and it leaves a different exit code**
(si#55). A run a signal ended used to be reported as `failed` with `ran = True` —
"the suite ran and reported failures", said about a suite whose output was empty.
It has its own outcome now: `killed`, `ran = False`, carrying the signal's *name*
rather than a negative number, because SIGTERM tells a reader something and `-15`
does not. Two things a product may notice. `simplon.verdict.Verdict` has a fifth
member, so anything that enumerates the four gets one more. And the exit code
changed: `sys.exit(-15)` reached the shell as 241, two numbers for one event and
neither of them saying "ended by a signal", where a killed gate now exits
`128 + n` — 143 for SIGTERM, the number a shell already writes into `$?` for the
same child. Measured end to end, and applied narrowly: the translation is derived
from a child process's wait status only, never from an arbitrary return value.

**Every product gains a `support completion` command** (si#58). It is *placed*
rather than offered, so it appears in your CLI whether you asked for it or not.
It clears the bar `support install` is placed on — it reads no manifest section
beyond the command tree every manifest already carries, it publishes nothing, and
it writes only under the product's own root — and the argument that settles it is
what the thing is: a completion you have to know about in order to ask for it is a
completion nobody has, because pressing TAB is the thing that does not work yet.
It writes `deploy/completions/<product>.bash`, and `--check` reports drift and writes
nothing, which is what makes committing the file worth anything. Generated rather
than switched on: Typer's own `--install-completion` runs the program on every
TAB, measured here at 340–360 ms, against 0.16 ms for the generated function.

**A scaffolded file's line endings now follow the file, not the machine**
(si#57). `bootstrap.write` used the *scaffolding* host's `os.linesep`, so two
machines scaffolding the same product produced 74 bytes of difference, and a
product scaffolded on Linux handed Windows users an LF `.cmd` built from five
multi-line `if` blocks. The endings are now decided per file by its extension —
CRLF for `.cmd`, LF for everything else. Nothing under you changes on the bump:
`simplon init` still refuses to overwrite an existing file, so a product that
wants the corrected bytes re-scaffolds with `--force`. The two halves are not
equally well evidenced and the code says so: the shell half is reproduced here (a
CRLF shim does not launch on this host at all — the kernel reads `bash\r` as the
interpreter name), while the `cmd.exe` half is this repository's standing claim,
carried in its `.gitattributes`, with no Windows machine behind it.

**An `impl:` gate now says less about your product, and that is the fix**
(si#65, si#59). A gate that hands the work to the product's own runner used to
get the default explanation — "the suite ran and reported failures" — and it got
it unchanged where Gradle had stopped in `:compileJava`, with nothing compiled,
no test run and no XML written. All three records claimed a green 1/1 table. The
line now reads:

```
unit: failed (rc 1) - the product's own runner returned this rc; the kernel did
                      not run a suite here and cannot say whether one ran at all
```

If anything of yours matches on the old sentence, it is gone. What the kernel
does *not* do is invent a level it has no basis for: a runner that says nothing
still gets `passed`/`failed` and no third state. A runner that *can* say more now
has a way to, because the setup marker is no longer pytest-only by placement — a
Gradle build that knows `:test` never ran writes it, and the run reports
`setup-failed (gradle build (:test never ran), rc 1)` with `ran = False`.

**Your orchestrator did not move** (si#24). The kernel moved *its own* to
`deploy/orchestrator`, using the `--orch-dir` it has offered since 0.1.9 rather
than any new capability — the same movement as pinning its own images: the kernel
submitting to what it already sells. No product directory relocates and no default
changed; `simplon init` still scaffolds `orchestrator/`. What did change is the
launcher it writes: a shim whose orchestrator directory is missing now fails
loudly and names the path, where before `python3 -m venv` created the very
directory the launcher was looking for and pip failed afterwards without naming
one.

### New

**`release:asset` attaches declared files to a GitHub release** (si#72). The other
half of `release:artifact`: that one publishes a directory to a registry, where a
consuming pipeline pulls it with its own token; this one puts files on a release
page, where a person downloads them. A product declares an `assets:` section and
pins one with `with: { name: ... }`, the same shape `release:artifact` uses.

```yaml
assets:
  bundle:
    source: "build-out/product_*.zip"   # glob, relative to the product root
    repository: owner/name              # optional — gh resolves it from the remote
    title: "..."                        # optional, defaults to the tag
    notes: "..."                        # optional
```

It runs `gh`, so the kernel gained no GitHub client and no new dependency, and
the token comes from the two sources `githubpackages.token` already documents.
Two behaviours are worth knowing because they are decisions rather than
defaults: a `create` that fails because another matrix cell got there first is
read as success and the upload proceeds, while any other failure stops before
anything is attached; and `--notes` is always passed, because `gh` opens an
editor where it has a terminal and refuses where it does not.

Which of the two a product offers is a question about its audience — and about
what its licence lets it hand out. Neither is placed; both are offered.

**Workflows come out of the manifest** (si#40). The manifest's second output:
`support:workflows` renders a product's `.github/workflows/*.yml` from a
`workflows:` section, so a renamed command breaks generation instead of leaving a
workflow calling something that is gone, and `--check` reports drift and returns
1. It is *offered* rather than placed, because it reads a manifest section and a
product without one would get a command that dies on its first line:

```yaml
groups:
  support:
    commands:
      workflows: { task: "support:workflows", help: "Regenerate the CI workflows." }
```

Three decisions are worth knowing before you declare it. Unknown keys at workflow
and job level are **carried through** rather than refused — measured against
sixteen real workflows, refusing them would have made eleven of the sixteen
inexpressible without the kernel ever needing an opinion about one of those keys;
a *step* is the exception, because it has exactly one body. `command:` is that
body rather than the whole step, which is what makes 34 of 41 real steps
expressible at all. And `handwritten: "<why>"` is how a file declines to be
generated: a file in the directory that nothing names is reported with rc 1, and
so is a `handwritten:` entry whose file has since disappeared — a name with
nothing behind it fails the same way an unowned file does, by looking accounted
for.

### Fixed — five findings, every one of them from running a real Java product

si#26's Java half was driven rather than described, and the drive produced five
defects sitting in one seam. Two are the `impl:` gate sentence above (si#65,
si#59). The other three:

- **si#63** — an exception inside the report step left `test-verdict.json` saying
  `passed` while the run ended red. The durable record was the thing that lied,
  which is the worst place for this defect to sit.
- **si#64** — the merge line announced its *intention*: "per-module results merged
  (parentSuite=X)" was printed when JUnit XML meant nothing was tagged, and again
  when the source directory was not there at all, and both times it read the same.
- **si#62** — `report.merge` raised `IsADirectoryError` on Gradle's standard
  layout, at `test-results/test/binary`. Settled by measurement rather than
  argument: an allure results directory is read *flat* — `aaa-result.json` plus
  `sub/bbb-result.json` yields `total: 1` — so recursive copying was moving bytes
  the renderer ignores, and skipping is the only true answer.

The capability that was already there was not taken along with the fix: JUnit XML
still arrives on Gradle's default layout without the detour.

### Measured, and deliberately not fixed here

**A test taxonomy with no pytest anywhere in it did not load** (si#61). Measured
against a real Java product: both spellings of the `suites:` section were refused,
and the way out was to ship a pytest gate containing `assert True`, a 29 MB suite
venv, and an archive that counted four tests for a product that has three. The
finding was recorded rather than patched, and it was classified twice before it
was believed: it is *diagnosis*, not an expression rule — without a clearing gate
nothing ever empties the results directory, and a stale result file survives the
whole run. What was actually missing was a word, not a rule, and that word ships
in 0.6.0.

Filing it turned up the larger finding. The two refusals stood in **no population
at all**: the refusal census counted two modules, and `tasks/testrun.py` was not
one of them — sixteen load-time refusals outside a census whose entire purpose is
that the sum cannot grow quietly. All sixteen were classified: fifteen diagnosis,
one expression rule. See [Rules](../../building/rules/) for the live split.

### Documentation

**A complete Python use case** (si#26), from `simplon init` to a deployed local
host: [Delivering a Python product](../case-python/). Every step carries one of
three labels — `run`, `derived`, `does not exist yet` — and the ratio is stated
rather than implied: eleven of fourteen steps were driven here, two are derived,
and one does not exist and names the open ticket instead of inventing a step. The
chapter is held against the product by `tests/test_case_python_chapter.py`: the
commands against the assembled command tree, the coordinates against the
catalogue, the five outcomes against `simplon.verdict.Verdict`, and every version
it names against `git tag`.

## 0.4.0

Thirty commits since 0.3.0. Three of them change what an existing product must
do; the rest add capability or explain what was already there.

### Before you bump

Two of the products that install this kernel do not load against 0.4.0 as
they stand, measured through the API rather than assumed:

| product | what stops it |
|---|---|
| biz-cockpit | still on the flat manifest form |
| netctl | `support install` redeclares a `task:` without `override: true`; `monitor accept` places `test:accept`, and a phase-named coordinate belongs in its phase |

*(A sixth manifest is on the flat form too and is deliberately not listed:
its product does not install this kernel at all, so no version of it can stop
that manifest loading. Counting it here would repeat the mistake 0.4.0 fixed in
five module heads, which named a consumer that never was one — see
[Surface](../../building/surface/) for how that is measured now.)*

Every one of those refusals prints the fix, and for the flat form it prints the
whole rewritten manifest. But the work is real, so plan it before the bump
rather than during it.

### What a product has to change

**The flat manifest form is gone.** A manifest that writes `impl:` directly
under a command no longer loads. The refusal prints the rewrite — the whole
manifest, in the tree form, ready to paste — and that rewrite was proved by
using it: the kernel's own `simplon.yaml` was migrated with exactly the printed
output. One case still needs a hand: where the catalogue places the same name
(`support install`, `release tag`), the printed block lacks the `override: true`
the merge then asks for, and the second refusal names that fix.

**And it replaces the structure, not your comments.** The rewrite is generated
from the parsed manifest, so a comment explaining *why* something stands where
it does does not survive it. A consumer whose manifest carried forty lines of
reasoning used the output as a blueprint and rebuilt by hand rather than
pasting — otherwise the migration would have been green and the reasons gone.
If your manifest is uncommented, paste it; if it is not, read it.

**`release tag` disappears from every product.** It was placed; it is now
offered. A placed command has to be useful in *every* product, and a product
with no release workflow does not need one. Declare it yourself if you want it:

```yaml
groups:
  release:
    commands:
      tag: { task: "release:tag", help: "Cut and push the release tag." }
```

**`env_groups:` may no longer CONTRADICT the platform.** An entry is measured
against the merged node: one that *disagrees* — naming a group the catalogue
shapes the other way — is refused, with the same sentence `env_first:` gets in
the same position. One that *agrees* is harmless, probably redundant, and
**accepted**. The key used to validate and do nothing at all in the tree form;
now it says which of the two it is. One consumer found the contradicting case on
the day it landed.

*(This paragraph said "naming a group the catalogue already shapes is now
refused", which is wrong for the agreeing case and was corrected after a
consumer's migration measured it: `env_groups: [deploy]` beside a catalogue that
declares `deploy` env-first **loads**. A reader who trusted the old wording would
have deleted a working line for no reason — the note was stricter than the
kernel, which is the direction nobody checks.)*

### Four modules moved

`allure`, `vcs`, `images` and `nexus` were kernel-level modules that were really
a task's innards, and three of them collided by name with a task body. The old
import paths still work, announce the move on use, and are removed in the next
minor:

| old | new |
|---|---|
| `simplon.allure` | `simplon.tasks.allure` |
| `simplon.vcs` | `simplon.tasks.gitops` |
| `simplon.images` | `simplon.imagenames` |
| `simplon.nexus` | `simplon.nexusproxy` |

The warning is a `FutureWarning` rather than a `DeprecationWarning`, and the
reason is measured: Python's default filters drop a DeprecationWarning unless
the frame that triggered it is `__main__`, and a product's task body never is.
A warning nobody sees is not a warning.

**Check the call, not the import.** The warning fires when a name is *used*,
not when the module is imported — `from simplon import images` is silent even
under `-W error::FutureWarning`, and `images.image_ref(...)` is what speaks. A
consumer who verifies "does it still import?" after the bump sees nothing and
meets the warning later, in operation. Measured by a consumer during their
migration, not by us.

Which modules are library and which are internals is now declared rather than
guessed — see [Surface](../../building/surface/).

### New

- **`build:image` and `release:image`** build a container image and publish it.
  The push is read back from the registry afterwards, because `docker push` can
  exit 0 without the tag arriving. `VERSION` and `REVISION` come from the
  product's git checkout, so a locally built image carries the same provenance
  as one built in CI.
- **`release:tag`** cuts the release tag and pushes it — `git push origin <tag>`,
  never `--tags`. It refuses a tag on a commit `main` does not carry.
- **A gate says why it is red.** "The setup failed" and "the suite ran and found
  something" are both a non-zero exit code, and they now read differently in the
  report — for the person reading it a week later, not just the one watching the
  terminal.
- **A results directory keeps the verdict it finds.** Merging one no longer
  copies `environment.properties` over the top of it.

### Stricter, in the kernel's own house

- A coordinate that starts with a phase name belongs in that phase; anything
  else is a family a product places where it likes. Measured against every
  existing manifest before it became a rule: no violations.
- The kernel pinned the three container images it was using without a tag,
  after refusing an unpinned image in a product's manifest. A rule the kernel
  breaks itself is a rule nobody believes twice.
- `docs:site` now renders each Mermaid diagram during the build. Hugo emits a
  diagram block whether or not its syntax parses, so a green build proved
  nothing about it.

### Documentation

New chapters on [the five phases](../../building/phases/) with a diagram, and
on what the kernel means by running in Docker. The coordinate table lost the
sentence beside each entry: those sentences were paraphrases of the catalogue's
own `help:`, nothing compared the two, and by the time anybody looked several
had drifted. The reliable fix is not to guard the copy but not to keep one.
