---
title: "Releases"
weight: 7
---

What each release changed, and what a product has to do about it.

Notes start at **0.4.0**. Earlier releases have their tags and their commits;
writing their notes now would mean reconstructing them from memory, and a
reconstructed record reads exactly like a real one. The [release
procedure](../releasing/) explains how a version comes into being.

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
catalogue body runs, and the product's own is reachable from nowhere. Two
assertions hold that loss as a characterisation, and the narrower diagnosis that
would find the case again without forbidding the offer is proposed and not built
(si#81).

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
It writes `completions/<product>.bash`, and `--check` reports drift and writes
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

**`env_groups:` may no longer contradict the platform.** Naming a group the
catalogue already shapes — `deploy`, which the catalogue declares
`env_first: true` — is now refused, with the same sentence `env_first:` gets in
the same position. The key used to validate and do nothing at all in the tree
form, so a line like that was already having no effect; now it says so. One
consumer found exactly this on the day it landed.

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
