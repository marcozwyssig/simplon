---
title: "Releases"
weight: 1
aliases:
  - "/using/releases/"
---

What each release changed, and what a product has to do about it.

Notes start at **0.4.0**. Earlier releases have their tags and their commits;
writing their notes now would mean reconstructing them from memory, and a
reconstructed record reads exactly like a real one. The [release
procedure](../../how/releasing/) explains how a version comes into being.

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

## 0.22.0

### `simplon.interact` takes the container prefix, and no longer knows a product (si#312)

The module carried `_PREFIX = "clab-netctl-"` — one product's name, and not even that product's general
case: it is the spelling of that product's **reserved** instance. A multi-tenant orchestrator therefore
got correct answers for exactly one of its N labs and silent ones for the rest. Measured on netctl at
0.21.0: an instance with **zero containers** streamed another instance's live log, a listing printed
`a1-client-be` where it meant `client-be`, and — the finding that decided it — `connect` opened a shell in
**another instance's controller** while the operator had named their own. Two mis-read; the third
mis-acted.

**The kernel now derives no container name of its own.** It holds no product name, no reserved instance id
and no default prefix; a preset value would be the same defect by a detour, answering for whoever happens
to match it. The caller resolved the instance, so the caller passes the prefix. The test
`test_the_module_names_no_product_and_no_reserved_instance` holds that: neither spelling may reappear in
the module, in code or in prose.

**This is a breaking change to a LIBRARY module**, and it breaks loudly — a missing argument is a
`TypeError` at the call, never a wrong container. For the one measured consumer it is one argument at four
call sites, and the value is already in the process beside them (netctl passes `paths.CONTAINER_PREFIX`,
which the `docker ps` filters two lines above already use).

| before | after |
|---|---|
| `normalize_container(name)` | `normalize_container(name, prefix)` |
| `strip_prefix(text)` | `strip_prefix(text, prefix)` |
| `resolve_connect_target(name, devices, site_names)` | `resolve_connect_target(name, devices, site_controllers, prefix)` |

`parse_logs_args` is unchanged; it never touched a prefix.

`resolve_connect_target` is the one whose change is not just an argument. It used to build a site's
controller as `<product>-<site>` itself — a **second** product name in the module, which the first
sentence of this note forbids. It now takes a site → controller-container map, which the caller has and
the kernel does not.

### A command that presupposes an instance refuses when it is not there (si#312)

`require_instance_present(prefix, container_names)` raises `InstanceNotPresent` unless some name belongs to
that prefix's instance. It exists because *"the instance is not there"* and *"the instance is there and
quiet"* were one outcome, which is this project's recurring defect at this seam.

**The line is not read versus write** — it is *does this command create the instance, or presuppose it?*
A bring-up starts from zero containers, so zero is its ordinary beginning. The wording is netctl's and is
better than the one this ticket opened with. The same refusal closes a second, long-known defect of theirs
(netctl#1040): a tear-down from a linked worktree removes its own, usually empty, instance and **reports
success** while the main lab keeps running — *"it looks like a verification and is none"*.

It **raises** rather than returning a verdict, because a returned verdict can be ignored, and a command
that carried on regardless is the thing it guards against. Belonging is `startswith` rather than the
substring match `docker ps --filter name=` performs. One limit is stated in the docstring rather than
hidden: where a product collapses a reserved instance id away, that instance's prefix is a prefix of every
sibling's, so a sibling's containers satisfy the check for the collapsed one — the kernel does not hold
the collapse rule and cannot see it, and a caller that needs the distinction filters before calling.

### `strip_prefix` drops the first occurrence, not every one (si#312)

It was `str.replace`, which empties **every** occurrence: a prefix appearing again in a status column or
an image name corrupted the rest of the line. Both this ticket and netctl#1914 called the repair "a prefix
strip"; **it cannot be one**, and that was measured rather than argued — what the callers hand over is a
`docker ps --format '  {{.Names}}\t{{.Status}}'` LINE, indented and with a second column, so the name does
not sit at position 0 and `removeprefix` would be a no-op on every real input. The function drops the
first occurrence and leaves the rest of the line exactly as docker wrote it.

## 0.21.0

### `rc:` — a system level can say that the image REFUSES (si#303)

`test:image` shipped with `rc != 0` always red, so a product could say *the image answers* and not
*the image rejects a broken input* — the other half of what a system level wants to say about a shipped
artefact. The consumer who asked has had the fixture for months and could not use it.

```yaml
    image-refuses: { task: "test:image", with: { name: app, argv: "check", rc: 2 } }
```

**An expectation, not a tolerance**, and that is the whole of why it takes a value: `rc: 2` means
"exactly 2, and 0 would then be red". A tolerance widens what counts as green; an expectation moves it,
and only the second is still a gate. The wording is the consumer's (firn) and is better than the one the
ticket opened with.

A refusal that does not happen returns **1 and not the container's own 0** — handing that back would
report the failure as green, which is the defect this task exists against, at its own last seam. Every
manifest written before this keeps its meaning, and the ordinary message does not grow a clause about an
expectation nobody stated.

### A marketplace can say WHICH (si#292)

Measured over the eight manifests this family can reach: **six name the same third-party marketplace and
none could say a version.** The `claude:` section reads as a declaration of what a product is developed
with and could not express the one thing that makes a dependency declaration mean anything.

```yaml
claude:
  marketplaces:
    theirs: { source: github, repo: owner/repo, ref: v1.2.3 }
```

**`ref` is a branch or a tag and not a digest**, and saying so is half the point of having it. Claude
Code's *marketplace* sources take `ref` and explicitly not `sha`; a *plugin* source inside a marketplace
takes both. So the strongest pin available here is a name somebody upstream can move: it stops the silent
redraw on every fetch, and does not stop the owner of that repository from moving the tag. Both halves
belong in the sentence, because "pinned" is otherwise read as the stronger thing.

The `#` of the CLI's `owner/repo#ref` is assembled in one place and **refused in the manifest**: a value
silently edited before use is one the manifest no longer describes. One new refusal, diagnosis; the
census moves 199 → 200.

#### What this kernel does not do, said rather than left

simplon declares `claude: marketplaces:` and ships **no `.claude/settings.json`** — the scripted half
without the native one, in a module whose own invariant is *two files, one truth*. The manifest says so
now, and says why: these plugins are a developer convenience here and not part of any delivery path.
Growing a settings.json so an invariant would hold would be serving the rule rather than meeting it.

#### A correction from the way there

The premise this ticket ran on for a day was mine and was wrong. I read `known_marketplaces.json`, found
no `ref` in it, and concluded the native half *could not carry one* — so a manifest-side pin would be
half a pin, and half would be worse than a stated absence. It holds none because nobody declared one. I
measured the artefact instead of reading the contract, which is the same failure as searching a problem's
vocabulary instead of a solution's, one step earlier.

### A development environment the repository describes (si#308)

`deploy <env> up` has always resolved an environment to a backend, Docker is something this kernel
installs and checks, and `devcontainer.json` is an open specification with a reference CLI of its own.
What was missing between them was the thirty lines that read a file a repository already carries.

```yaml
environments:
  dev: { backend: devcontainer, description: "The development container." }
```

`deploy dev up local` brings up what `.devcontainer/devcontainer.json` describes, `deploy dev down`
removes it, and `deploy dev status` says whether it is running. **No product code**, for the reason
`portainer` needs none: the chain underneath is the kernel's.

**It names no editor**, and that is the decision rather than an omission. The specification is read by
more than one consumer — JetBrains Gateway, DevPod and Codespaces among them — so this backend drives the
CLI and stops there. Which editor a person attaches is theirs and their product's, and a kernel that
opened one would couple every product to it.

Two refusals are worth knowing before you meet them. A **published version** is refused: a development
environment is the working tree, so `local` is the only selector that means anything, and a tag names a
deployment of a different thing under the same verb. A repository with **no specification file** is
refused naming the path and https://containers.dev, rather than starting something it guessed.

**A teardown finds its containers by the label the CLI writes**, not by a name this kernel invents — so a
container somebody started from an editor is found by `down` too.


### The run finishing after the screen is gone (si#306)

si#265 repaired `#status` and left `#steps` with the same edge. It surfaced where it is most expensive:
**the v0.20.0 publish job**, with the tag already cut and pushed.

```text
FAILED test_walk_tui.py::test_a_refusal_stops_that_scenario_and_the_next_one_is_still_walked
textual.css.query.NoMatches: No nodes match '#steps' on Screen(id='_default')
```

`releasing.md` has a name for that state - **cut but not published**, which is neither "nothing happened"
nor "released" - and a re-run was needed to finish a release that had already been announced as done.

#### The measurement first, because the obvious repair is wrong

`_tree()` has **eleven** call sites. A blanket early return would make a real mount failure quiet in ten
places to fix one, which is the trade si#265 refused in its own words: *the repair is NOT
`except NoMatches: pass`*. So each caller was classified before anything was written:

| caller | reached from |
|---|---|
| `on_mount`, `_mount_tree`, `_cursor_row`, `_move_cursor_to`, `action_next_failure`, `action_filter`, `on_input_submitted`, `_repaint_everything` | mount, or a key the operator pressed - a screen exists by construction |
| **`_on_done`** | `call_from_thread` out of a `@work(thread=True)` worker |

**One.** It arrives when the run ends rather than when the app chooses, including after teardown - which
is exactly the pair si#265 measured for the bar, and the same worker.

#### The bar answers for the tree

`_on_done` returns early when `self._bar is None`. That is deliberate rather than indirect: si#265 made
`_bar` the one reference this app drops in `on_unmount`, so it is the app's marker for *there is a screen
right now*. A second marker for the tree would be a second source for one fact, and the two would
disagree the day only one of them is dropped.

Its `_repaint_status()` already no-ops on its own; what follows does not - it moves a cursor and renders
a pane. Nothing to focus is not a failure: the run is over and its verdict is already in the subtitle.

#### Two assertions, and the second one had to be rebuilt twice

The first says a handover after teardown raises nothing. The second says the feature still works with a
screen - without it the guard could become an early return that switched auto-focus off.

That second one was **green with the whole branch cut out**, twice. It first asserted `_expected_row`,
which other paths set during a run, so it measured the app having been used. Reading the tree cursor
instead was still green, because the fixture ends on its failure and the cursor is already sitting
there - `_on_done`'s move is a no-op for that pipeline. It needed a pipeline whose failure is **not
last**, and only then does removing the branch turn it red.

## 0.20.0

### The docstring claimed a write nothing exercises (si#303)

`test:image` shipped in 0.19.0 saying its mount

> proves the image can read **and write** a bind mount as the invoking user

**It proves reading.** `mount:` takes a product-relative directory, so the only thing a product can bind
is a directory of its own checkout, and a command that wrote into it would leave the tree dirty. The
second product to adopt the task hit that on its first use: it proves its image's runtime stage with a
read-only check and records in its own notes that the write path stays unproven.

The sentence now claims reading, says why the other half is missing, and names what would close it - a
scratch mount, copied into a temporary directory before the run. No behaviour changed.

**It was found and repaired by the consumer who wrote it**, within a day of its own release. A claim
nothing exercises is this repository's own defect class in prose, and prose is where it is hardest to
see: nothing goes red.

#### What si#303 still carries

Two extensions, neither urgent and neither built:

* **the scratch mount**, which would make the removed half true;
* **`rc:`**, so a system test can say *"the image rejects a broken model with code 2"* - today every
  non-zero rc is red, so a refusal cannot be asserted at all. The consumer has had the fixture for months
  and cannot use it, and supplied the constraint the design would need: **default 0, and an expectation
  rather than a tolerance** - `rc: 2` means "exactly 2, and 0 would then be red". A tolerance widens what
  counts as green; an expectation moves it, and only the second is still a gate.

## 0.19.0

### `test:image` — the third verb over an image (si#301)

`build:image` produces and `release:image` publishes. **Nothing ran what was produced**, and the
catalogue's own comment over `build:image` had been saying what that costs while offering no verb for it:
*"a product that builds an image only to run a smoke test against it must not be one typo away from
pushing it"*.

So a product could build an image, push it, and never once execute the **runtime stage of its own
Dockerfile** — the directives that copy a binary into a base and set an entrypoint, which is the half no
unit test reaches.

`test:image` builds nothing and pulls nothing. It runs what the daemon already holds, under the reference
the build would have produced, **resolving the tag the way `build` and `release` resolve it** so the three
verbs cannot end up naming three references. An image the daemon does not hold is a refusal that names
`build image` — not a quiet pull of whatever the registry happens to have.

```yaml
test:
  commands:
    image: { task: "test:image", with: { name: app, argv: "--version", expect: "1.4.0" } }
```

**The mount is what makes it a test about a workspace rather than about `--version`.**
`<directory under the product>:<absolute path in the container>` binds a fixture, and the run then proves
the runtime stage against real input. The host half goes through `simplon.hostpath`, because si#201's
finding applies here exactly as it applies to `toolchain:run`: an untranslated mount source makes the
daemon create an **empty directory on the host** and mount that, with rc 0 and no message.

Four refusals, each with a test that fails without it: an image the daemon does not hold, a mount that is
not `<dir>:<absolute>`, a mount that leaves the product or is not a directory, and output that does not
contain what the caller said it must. **The container's own return code travels** rather than being
flattened to 1 — a smoke test that reported `1` for every kind of failure would be the third verb
repeating the defect the first two exist without.

The catalogue grows to 43 coordinates and the `test` namespace to 8, which the phases page, the design
page and the rules page all carry as numbers **read back out of `catalogue.yaml` by the suite** rather
than typed.

### What a gate assures that an aggregate does not (si#290)

si#283 normed the test levels, and si#290 measured how far that norm reaches: **four of eight products in
this family declare no `suites: gates:` at all**, so `_gate` never runs for them and nothing rules on
what they call their levels.

The interesting half came from a consumer, and it is a distinction this repository had folded away: those
four did not **decline** the section, they **never met the question**. Their words when asked what
declaring it would cost:

> no resistance, just work with no visible benefit - our `ci` runs everything it should run, and a
> `suites:` section would first have to show what it additionally assures.

**Nobody had named the benefit.** So the chapter names it, measured out of the code rather than argued:

| | |
|---|---|
| a gate | `PASSED` `FAILED` `SETUP_FAILED` `NOT_RUN` `KILLED` |
| an aggregate step | a return code: `PASSED` or `FAILED` |

The three a gate can say and a return code cannot are exactly the **"nothing to do"** cases this project
separates from "failed": a precondition that said no and cleared nothing, a preamble that failed so the
suite never ran, and a suite ended by a **signal** - which reported nothing, making "the suite ran and
found failures" a statement about the product that nobody made. `SETUP_FAILED` is not hypothetical; that
rc used to be computed and dropped, so a lab that failed to converge ran the suite anyway.

The chapter ends where the honest answer is: **if none of your levels can fail to start, an aggregate is
genuinely enough** - and that sentence is now on the page instead of being something each product works
out alone.

No kernel code. `test_test_levels.py` reads the page back against the `Verdict` enum, and requires each
of the three to have a row that **explains** it - the first draft of that assertion asserted presence
alone and stayed green when a verdict was struck from the table, because the name still stood in a code
block above it.


### The backend gate is gone from the CLI, because it ruled on commands the kernel does not run (si#298)

Two repairs in one week ended in a check that could not fail, and the measurement that found it came from
a consumer noticing the gate no longer closed for any of their environments. It was not their case.

```
Provider.registry()          parses the matrix against  self._valid
Provider.require_drivable()  accepted                   drivable + self._valid
```

`current()` returns an environment out of `registry()`, and `parse_data` refuses any backend outside
`self._valid`. So `env.backend` was in `self._valid` **by construction**, and the gate added that same
set to what it accepted. si#288 asked the wrong question and broke `backend: local`; si#293 answered the
right one and made the gate unreachable. *A new assertion that has never failed is not yet an assertion*
- and one left in place reads as protection.

**The tests that guarded it asserted an impossible state.** Their helper overrode `current()` to return
an environment whose backend need not be in `valid_backends`, which `registry()` cannot produce. They
were seen red against the mutation; the mutation was real and the input was not.

#### What the measurement said

Over all eight manifests and repositories this family can reach:

| | |
|---|---|
| products calling `simplon.backend.register` | **1** - and only since this week, forced by si#288 |
| products resolving a command to a `deploy:*` task | **1** - the same one |
| products with their OWN commands in an env-first group | 5 |

netctl does not register: it has its own `REGISTRY` and its own `resolve()`, satisfying the kernel's
Protocol and handing the kernel nothing. `backend.py`'s docstring said it was *"the only consumer"*,
which is true of the Protocol and reads as if it were true of `register()`.

So the gate asked a question about the **kernel's dispatch** and applied it to **every command in an
env-first group** - which for five of eight products are their own `up`, `down` and `install`. Both
failures are that mismatch from either end.

The check now sits where the kernel actually resolves a backend to an instance: `tasks.deploy`.
`require_drivable` is gone, and so is the protocol entry - nothing called it.

#### The refusal a person meets now names the cause

Also the consumer's, and it needed the same move. A kernel deploy command against an unregistered `local`
produced:

> environment 'dev': backend must be 'portainer', got 'local'

That names a **requirement** where the cause is a **missing registration**, and sends the reader to the
`environments:` section while what is missing is a `backend.register` call in the composition root. Their
words: *it sends you to the wrong neighbour*. `backend.resolve` always had the sentence that fits and
could not be reached, because `tasks.deploy` re-parsed the matrix against the drivable set first.

`parse_data`'s `valid_backends` now **defaults to what the document itself declares**, so a caller does
not re-validate a matrix against a different set than the one it was loaded against - which is si#294,
the consumer's other finding, closed by the same line.

#### One copy of a function I wrote twice in a day

`declared_backends` lived in `workflowgen` and in `tasks.deploy`, written hours apart for the same
question. It is in `environments` once now. The refusal census found it: pulling the document apart in
`tasks.deploy` made that module a manifest reader in its own right, and si#61's guard said so.

## 0.18.0

### `backend: local` was refused by the gate that 0.17.0 shipped (si#293)

**A regression, and the shape of it is worth the space.** si#288 replaced *"is this backend local"* with
*"can this backend be driven"* and read the answer out of a set the KERNEL computes. The kernel ships
`portainer` and nothing else - `local` is the name a product's **own** backend answers to, which is why
the old gate skipped it entirely.

So every environment-bound command against a `local` environment died, for any product that had not
registered a backend:

```text
ERR environment 'dev' has backend 'local', which nothing here can drive -
    this run resolves portainer.
```

**That is what `simplon init` scaffolds.** `bootstrap.py` writes `dev: { backend: local }` and registers
nothing. A consumer measured four dead commands - `up`, `down`, `status`, `backup` - on a product whose
own suite was green.

The gate now resolves against what the kernel ships, what the product registered, **and what the
product's own provider declares valid**. A tag in `valid_backends` is one the product has claimed; a
claimed tag nobody implemented is still refused, by `backend.resolve` at dispatch, where it names the
right file. #11's protection is unchanged and arrives earlier than this gate: a matrix naming a tag the
product did not declare valid is refused by `parse_data` first.

#### The second half, which is why this is not a special case for `local`

The consumer measured it: `Provider.valid_backends` is hand-written and `drivable_backends()` is derived,
and the two could disagree - **one matrix valid to the parser and undrivable to the gate, out of the same
file**, with nowhere anybody could read them against each other. The gate is that place now.

#### Why neither side's tests caught it

This kernel **declares no `environments:` section at all**, so no assertion over its own matrix could have
existed. The consumer's CI is environment-agnostic and never touches a `dev` command; their suite was
69/69 green. It became visible when a person typed `up`.

What went in is their repair rather than ours, and their argument for it: assert the **outcome** - every
`backend:` a matrix names is in the set the gate resolves against - not the handle. A test on
`backend.register` would have died with any rename and would not have caught their fourth environment.

### A release rolls out to your environments, from the manifest (si#296)

`workflows:` could describe a CI run and could not describe a deployment. Measured before anything was
built: `deploy up` **requires** a version selector, a `command:` step could pass **no parameter at all**,
and an env-first command has no spelling in a step (`command: prod deploy up` resolves to a group
`prod.deploy` no manifest has). So a rollout was expressible only as a hand-typed `run:` line - the
unchecked string si#40 exists to abolish, for the command with the largest consequences.

```yaml
environments:
  test: { ..., deploys: latest }
  prod: { ..., deploys: "1.4.0" }

workflows:
  rollout:
    on: { release: { types: [published] } }
    runner: { kind: github-ubuntu }
    flow:
      - to: test
      - to: prod
        approval: true
```

**Two declarations, because they answer two questions.** The environment says *what* it receives; the
flow says in *which order* and which stage a person releases. A staging instance wants the newest
publication and a production one a chosen tag, whatever triggers the rollout - so the version is not in
the flow, and the order is not in the matrix.

Out comes `deploy-test` and `deploy-prod`, the second with `needs: deploy-test`. **Chained rather than
ordered in the file**: GitHub runs jobs in parallel unless told otherwise, so a rollout whose order lived
only in the emitted order would reach production and staging at once and look correct.

`approval: true` gives the job GitHub's own `environment:`, which is where an account configures required
reviewers, wait timers and the secrets that stage may see - the only half that can be changed without a
commit.

#### The version is a literal, and that decided the design

It comes from `deploys:`, so the kernel writes `deploy up --version 1.4.0` with a value nobody outside
the repository chose. The alternative that was offered and rejected was a `workflow_dispatch` input
interpolated into the command - the classic Actions script injection, in a job holding deployment
credentials, **emitted by the kernel on a product's behalf**. A test holds it: nothing the kernel writes
into a `run:` line may contain a GitHub expression.

#### A step can hand a command a parameter

`params: { version: "1.4.0" }`, with the **name checked against what the command declares** - si#40's
join one level in. A renamed parameter breaks generation instead of becoming a `run:` line that fails on
a runner three minutes into a job.

#### Two refusals were written and struck

Both were expression rules by CLAUDE.md's first question, and deleting was cheaper than justifying:

* **`deploys: local`** reads as obviously wrong for a pipeline and is something a product with a
  locally-building backend might legitimately mean. The case it *is* wrong for already refuses in
  `PortainerBackend.deploy`, with more context than a second refusal would have had.
* **`flow:` beside `jobs:`** would have forbidden a rollout plus a product's own notification job -
  si#267's lesson repeated. The generated names are stable, so a product hangs `needs:` on one.

Six new refusals, all **diagnosis**; the census moves 193 → 199 with no new expression rule.

#### What this kernel cannot do with it

**simplon declares no `environments:` section at all**, so it cannot run this against itself - the thing
this repository otherwise insists on. The feature is driven against a fixture product instead: ten
assertions, five of them seen red by breaking the property each protects. That is weaker than dogfooding,
and it is said here rather than left to be discovered.


### The four groups a product reaches for, and where each one goes (si#286)

A product adopting the kernel tends to want the same four groups beyond the six the taxonomy declares -
`dev`, `contract`, `lint`, `ci` - and the group lock refuses them. It refuses without saying where they
belong, so each adopting product has worked it out again.

Measured over all eight manifests this family can reach, before deciding anything:

| name | where it actually lives today | as a group |
|---|---|---|
| `dev` | `environments:`, in five products | never |
| `ci` | `workflows:`, in three | never |
| `lint`, `contract` | one product's own `test` commands (`lint`, `check-contract`) | never |

**No product that has adopted declares a group outside the six.** All four resolve into the three groups
that already exist, and one product had resolved three of them before the question was asked. Its reason
is the one the new table is built on: *they verify, so they belong in the group that verifies - a group of
their own would only repeat the name.*

So the taxonomy is complete and what was missing was the map. It is on [task and
command](../../how/task-and-command/#the-four-names-a-product-reaches-for-and-where-each-one-goes), with
the one entry that genuinely depends on the product spelled out: `contract` is `test` when it checks a
contract and `build` when it generates from a schema, and only that product knows which.

**No kernel code changed**, and deliberately: the four names are a product's vocabulary, not the
platform's, and pinning them into a refusal would carry somebody else's words in this kernel until they
changed them.

## 0.17.0

### Two defects that made `backend: portainer` unusable (si#287, si#288)

Both reported by biz-cockpit while wiring their first production deployment against 0.16.0, and both
confirmed at the source before anything was written. Together they meant the backend 0.16.0 shipped could
not be reached, and would not have carried its values if it had been.

#### `optional:` was validated and never handed over (si#287)

```python
envs[str(name)] = Environment(str(name), backend, ...,
                              required=required)          # and not optional
```

`Environment.optional` fell back to its default `()`. `portainer.stack_values` iterates
`(*required, *optional)`, so **no optional value had ever reached a deployment** since the feature
shipped.

What it would have cost the consumer, in their words: `prod` coming up without its Smallinvoice, Toggl
and Graph credentials - cleanly with 409 rather than with fakes, so no data damage, but *an instance that
can do nothing and does not say why*.

**Why a release went out with it.** Nothing in the suite read `Environment.optional`. The list was
validated, it took part in the "a name may not be in both lists" refusal, and it appeared in every
message that counted it - so at every point where somebody looked, it looked processed. Validation was
never what was missing; arrival was.

The repair is one argument. What is worth more is the assertion beside it: it reads the value at
`stack_values`, on the **far side** of the seam, because the same test written against `parse_data`'s
validation passes on the broken code.

#### The CD gate asked whether a backend was local, not whether it could be driven (si#288)

```python
if verdict == "gate-backend" and not asking_help and not environments.is_local(env):
    environments.require_backend(environments.LOCAL)
```

`gate-backend` covers every env-first group, so for any non-local environment **every** command in
`deploy` and `monitor` died - `deploy up` included. The feature this kernel released was unreachable
through the CLI this kernel assembles, and every product adopting it needed a `Provider` subclass to get
past its own kernel.

The gate was older than the backend it blocked. #11 put it there when `local` was the only backend
anybody had implemented, and its purpose was sound. What changed is that "is this backend local" and "can
this backend be driven" stopped being one question.

`Provider.require_drivable` asks the second one, against the same set `deploy up` resolves against
(`tasks.deploy.drivable_backends`, public now for exactly this reason) - so the gate and the dispatch
cannot disagree. It refuses precisely what #11 meant to refuse, and the refusal names what this run *can*
drive and how to add one, which is in no document because the set is assembled at run time.

**Nothing for a product to do.** `simplon init` writes a real `Provider`, so a scaffolded product
inherits the method; `is_local` and `require_backend` stay on the protocol because a product's own body
still calls them when it only works against one backend.

### The unit suite moved to `src/tests`, so the kernel keeps its own placement (si#283)

The taxonomy si#283 shipped says `unit` and `integration` live under `src`, beside the code they judge,
and `system` and `acceptance` under `tests`. simplon's own unit suite was in `tests/`, and the page had to
carry a callout saying so.

It does not any more. 164 files moved; `tests/` keeps the acceptance level and the run's artefacts, which
is what the taxonomy says belongs there. *None exempts the kernel* is a measured claim on the rules page,
and this is it paid for rather than asserted.

**Nothing for a product to do.** The kernel's defaults did not move - `tests/reports`, `tests/acceptance`
and the layout's `tests` are what every product still gets, because they are about where OUTPUTS and the
acceptance level go, not about where a unit suite lives. Where a product puts its unit tests it says in
its own gate.

#### Three things the move found, and every Python product laid out this way will meet the first two

**The wheel shipped the tests.** Under `src/`, setuptools' `packages.find` treats a directory as a
package: the first build after the move carried `tests` as a **top-level package**, which on installation
would land that name on a consumer's import path and shadow their own. `pyproject.toml` excludes it now,
with the measurement in a comment beside it.

**The type gate swept the suite in** - 382 errors in 64 files. `files = src` had never excluded the tests
by a decision; it excluded them by their living somewhere else, which is not the same thing and stopped
being true the day the directory moved. `mypy.ini` says it now, and its "NOT COVERED BY PATH" note - which
already explained *why* the suite is not typed - was carrying a number that had gone stale too: 1300+
tests, against 3858.

**Fifteen tests computed the product root themselves**, in ten files, while thirty-eight imported the one
anchor from `conftest`. All fifteen broke on the move, and three more hard-coded `tests/fixtures` into a
path spelled out from the root. That is the second source this repository hunts, inside its own suite, and
the move is what made it visible: a duplicated constant costs nothing until the thing it duplicates moves.
They read `conftest.ROOT` and a new `conftest.FIXTURES` now, and the one file that had anchored relative
to itself needed no change at all.


### The test levels are a taxonomy now, not three examples (si#283)

`with-what/test-levels.md` defined a level precisely - *"one entry under `suites: gates:`"* - and then
taught the mechanism with three example names. The kernel checked a gate's name against the product's own
manifest and nothing else, so two products could spell one level differently and a third could put a way
of *reaching* the product where a level goes. That page taught `ui` as a level for months, because there
was no list to check it against.

There are four, and the page states them as a taxonomy rather than as a report:

| level | what a failure in it means | where it lives |
|---|---|---|
| `unit` | one piece is wrong on its own | `src` |
| `integration` | two pieces disagree where they meet | `src` |
| `system` | the assembled product misbehaves against real infrastructure | `tests` |
| `acceptance` | the product does not do what somebody asked it for | `tests` |

**A suite of a level is that level, a `-`, and a name of your own** - `acceptance-ui`,
`acceptance-dataplane`, `unit-java`. Without that rule the norm would warn on every consumer that runs
more than one runner at a level, which is most of them.

**A gate off the set gets a warning, never a refusal.** A norm that broke an existing manifest on upgrade
is not shippable. The message names the set and deliberately does **not** guess at what was meant: a "did
you mean" over four words is a spelling correction pretending to be a taxonomy.

#### What the measurement changed about the ticket

Measured over all **eight** manifests this family can reach, before the set was written:

| name | products | in the set |
|---|---|---|
| `unit` | agile-cockpit, simplon, secure-windows-images | yes |
| `system` | agile-cockpit, netctl, secure-windows-images | yes |
| `acceptance-dataplane`, `acceptance-ui` | netctl | yes, as suites |
| `delivery` | agile-cockpit | **no** |
| `artefact` | secure-windows-images | **no** |
| `integration` | nobody | yes, and unused |

Two real declarations fall outside the set. That is the #34/#48 shape again - the smaller population
would have shown none - and it is why the refusal is a warning.

**And it dissolved the ticket's second question.** si#283 asked where `component` and `boot` sit, because
this page named them among netctl's levels. They are not levels, because they are not gates: netctl's
manifest declares `system`, `acceptance-dataplane` and `acceptance-ui`, and the six prefixes the page
quoted were its **Gradle source sets**. The one taxonomy the documentation had was a report about
directory names - which is the sharper version of the ticket's own complaint.

#### The placement is stated and not enforced, because this kernel breaks it

`unit` belongs under `src`. simplon's own `unit` gate runs the pytest suite under `tests/`. The page says
so in a callout rather than the kernel checking it, because *"none exempts the kernel"* is a measured
claim on the rules page and an unexamined exemption is what si#53 struck a rule for. Moving 3800 tests is
not a manifest line; the measurement is on si#283 and the decision is somebody's to make out loud.

### A Portainer on a machine the kernel did not make is a carrier too (si#280)

Raised by biz-cockpit while wiring `backend: portainer` against a Portainer that had been running for
months. They were blocked on the last piece and the obstacle was ours: `backend: portainer` needs a
`carrier:`, and every carrier needed a `proxmox:` block with a `node:` and a `kind:`.

**Nothing on the deploy path ever read that block.** Every reader of `carrier.proxmox` in the kernel:

```
src/simplon/tasks/carrier.py:132,137,141,198,442,444,445,446,447,448
```

One file, and it is `deploy:carrier` - the command that *makes* the machine. `PortainerTarget.from_carrier`
reads `carrier.name` and `carrier.portainer` and nothing else. So a product bringing its own machine had
to declare a block no code on its path consulted, and the two values without defaults had no true answer
to give. A value that never has an effect is the one that is wrong a year later and tells nobody.

**This is si#258's own argument arriving from the other side.** That ticket struck the refusal on a
carrier with no `portainer:`, and the reason is in the code: the section *"was written as though a carrier
and a Portainer host were the same thing"*. A machine with nothing on it is a complete statement. The
mirror of that sentence is that a Portainer on a machine somebody else built is a complete statement too -
and until now it could not be said. si#258 named the conflation and removed half of it.

```yaml
carriers:
  theirs:
    portainer:
      url_from: PORTAINER
      insecure: true
```

`deploy carrier` refuses that carrier by name, in terms of the alternative rather than of a fault: the
reader is there by accident, not by mistake. A carrier declaring **neither** half is refused at load -
each absence is a statement, both at once state nothing any command can act on.

#### The count goes up while the refusals go down

The census moves **192 → 193**, and that is not a slip. The requirement this ticket removes was never a
`raise` of its own: a carrier naming only `portainer:` fell into *"so no host is named"*, a refusal
written for a block that is present and incomplete. Nothing was deleted; a new one was added for the
carrier that says nothing. **Strictly fewer manifests are refused than before, and the number is one
higher** - which is the clearest demonstration this repository has yet produced that the count is a
tripwire against growth nobody noticed, and not a measure of how much a product may say.

No expression rule was added or removed; every carrier refusal is diagnosis.

#### What is not measured

The population is one. `carriers:` shipped in 0.16.0 and no other consumer has reached the section. The
asymmetry is a property of this code rather than of anybody's manifest, but the size of the want is a
single product, and that is written on the ticket too.

## 0.16.0

### The pipeline is derived from the command tree (si#267)

The generator **serialised**: a product wrote every job, every step and every `runs-on`, and the kernel
contributed a checkout and an interpreter. Measured across this family, two of seven repositories used it
at all; the other five hand-wrote between 47 and 283 lines each, and none of them is different from the
others for a reason anybody chose.

A step may now say where its steps come from instead of listing them:

```yaml
    steps:
      - derive: [build, test]
```

Every **leaf** of each named group that may run with nobody watching becomes a step, in the order the
manifest declares it. Leaves rather than aggregates: a GitHub job stops at its first red step, so
emitting `test all` would collapse four verdicts into one and lose the order its members were written in
- a reason this repository's own manifest had written down years before the derivation existed.

**The bit that makes it possible is `unattended:`, and it lives in the catalogue.** It asks one thing:
may a pipeline run this command with nobody at the keyboard? It is a fact about the *body* rather than
about a product - `test:walk` asks a person to answer each acceptance scenario, and it asks that of
everybody who imports the coordinate - so it is declared once, for all of them, which is the same
argument the coordinate space itself runs on.

The population was measured rather than judged: every catalogue body was walked transitively for a
construct that asks a person, and **one of forty-two** reaches any. That ratio is the case for deriving
at all; a kernel that had to be told about each command individually would be a template with holes.

**Three states, not two.** Leaving the key out means *nobody has said*, and a derivation may not guess:
read as false it drops a gate and the pipeline goes green for the wrong reason, read as true it puts a
command that wants a person on a runner. An undeclared leaf is named and refused. It is also the one
flag on a spec that is not coerced - every other is `bool(value)`, and `bool(None)` is `False`, which
would have destroyed the third state at the loader's own door.

#### A correction, and the rule it came from

The note filed on this ticket said a derived pipeline would **hang** on `test walk`. It would not:
`walk` checks for a terminal and refuses with a message. The repair is the same and the cost is
different - a red cross rather than a stuck job - and the difference is worth the correction, because a
red cross that means nothing is how people learn to stop reading them.

#### The refusal that was built and then removed

The first draft put `derive:` on the **job** and refused `steps:` beside it, since which one wins would
otherwise depend on read order. That refusal did not survive CLAUDE.md's own questions: a product wanting
the derived pipeline *plus* a Check Run reporter of its own was saying something the kernel could have
honoured, and what it would have done instead is write the whole file by hand - the work this ticket
exists to remove. So the rule was deleted rather than justified, by moving the derivation onto a step,
where a product places it among its own and the order stays the product's.

Four new refusals, all **diagnosis**; the census moves 188 → 192 with **no** new expression rule.

#### What this repository does with it, measured

Derived over simplon's own manifest, `[build, test]` yields ten steps. Its CI runs seven of them; the
three it adds are `build reference`, `build acceptance` and `build site`. All ten were run by hand on
this machine before the test was written - all ten exit 0 and leave the tree clean - so the derived
pipeline here is correct, not merely plausible.

simplon's own CI stays hand-written all the same, and the reason is in its manifest rather than in this
decision: its step order is argued there, chiefly that the prose gate goes **last** so a release section
still to be written cannot hide a red suite, and a derivation follows declaration order instead. That
difference is now held by a test rather than by anybody's memory: if the derivation starts emitting what
the CI runs, or the CI starts running what is derived, it says so.

### A runner is named by its KIND, and the kernel carries what follows from it (si#267)

Raised by the owner after moving this repository's CI to a self-hosted runner took a full day, and every
hour of it was spent rediscovering something another product in this family already knew:

> *Wenn man Simplon verwendet, dann sollte alles gleich sein. Das ist ja der Vorteil von Simplon.*

A product had to know, on its own, that `actions/setup-python` **never installs Python** — it unpacks
prebuilt archives, and its manifest carries Ubuntu 22.04/24.04/26.04 and RHEL 9/10 and nothing else; that
a **container job cannot be the thing that provisions docker**, because it needs docker on the runner in
order to start at all; and that `DELIVERY_DOCKER_BOOTSTRAP=1` exists. None of it was in the kernel. All of
it was in a comment in netctl's manifest, learned there once and here a second time.

`simplon.runners` carries it once, for everybody — the same answer the catalogue already gives to the
same question about commands. A job names a kind:

```yaml
    jobs:
      self-build:
        runner: { kind: self-hosted-debian, labels: ghr-8 }
```

| kind | `runs-on:` | `setup-python` | environment |
|---|---|---|---|
| `github-ubuntu` (the default) | `ubuntu-latest` | yes | — |
| `self-hosted-debian` | yours to name | **no** | `DELIVERY_DOCKER_BOOTSTRAP: "1"` |

**The label stays the product's.** `ghr-8` names one machine and no kernel can guess it, and
`[self-hosted, Linux, X64]` is not an answer — it describes every self-hosted Linux machine the account
will ever register, so the day a second one joins, the jobs are shared out with nothing saying so. A kind
carrying no label of its own refuses until the job names the machine.

What the kind buys is everything else. A `python:` pin on a kind that cannot honour it is refused **at
generation**, because a pin that cannot be honoured reads as a guarantee and is a wish. The kind's
environment is merged into the job's, and a variable the two set differently is refused rather than
resolved, with the escape named in the refusal. And the kind's one-line reason is written into the
generated file, so a reader who finds `runs-on: ghr-8` beside `DELIVERY_DOCKER_BOOTSTRAP: '1'` does not
have to find the kernel to learn why they belong together.

**Measured on this repository's own CI:** `simplon.yaml` now names the kind instead of spelling out the
three consequences, and the generated `ci.yml` is identical but for the line the kind added explaining
itself. Twelve manifest lines of hard-won comment became one declaration and a kernel table.

`runs-on:` is not deprecated and is not going to be — it is the whole of what a product needs when its
machine has nothing to teach anybody. Ten refusals join the census: eight diagnosis, and two expression
rules for saying a fact twice.

**The other half of si#267 is not in this release.** The ticket also asks whether the kernel should
*derive* a pipeline from the command tree. Measured against this repository's own manifest, a plain
derivation over the leaves of `build` and `test` would emit `test walk` — the acceptance walk, which waits
for a person — so it would produce a pipeline that hangs rather than one that works from the start. What
is missing is one bit the tree does not carry: whether a command can run with nobody watching. That is a
decision, not an oversight, and it is recorded on the ticket.


### `runs-on:` keeps its type, so a list of labels stays a list (si#266)

Filed by `secure-windows-images`, whose Windows template build needs one specific machine with VMware
Workstation while its unit gates want any Linux runner — so `[self-hosted, windows, vmware]` is the
natural thing to write, and it was exactly the input that broke.

`_job` coerced the value with `str()`:

```text
runs-on: [self-hosted, windows, vmware]   ->   runs-on: '[''self-hosted'', ''windows'', ''vmware'']'
```

Valid YAML, valid GitHub syntax, and it selects a runner whose single label is that literal text. Nothing
refuses it and nothing warns: the workflow generates, commits, reviews and runs, and the job then waits
for a runner that cannot exist. `str()` on a value whose **type** carries meaning is the same defect
`context.section` was given a `blame` for.

The rendering half needed no work at all — `_scalar` delegates to `yaml.safe_dump` in flow style rather
than guessing, so a tuple was always going to come out as `[self-hosted, windows, vmware]`. All that was
missing was letting the value through intact.

All three of GitHub's shapes are now carried: a label, a list of labels, and the `group:`/`labels:`
mapping. The mapping is accepted rather than refused deliberately — refusing a shape the platform
documents would be an expression rule bought for nothing, since the renderer already handles it. What is
refused is a value GitHub has no reading for in any shape — a number, a bool, a list with something other
than a label in it — which is diagnosis, and two entries the census now carries.

### A command that succeeded and said nothing has not answered (si#274)

Two unrelated tests failed on the self-hosted runner within one hour, both green on a re-run of the same
commit and both green on every developer machine. They look like two flakes. They are one defect: **in
each, a `git` command exited 0 and printed nothing, and the nothing was used as an answer.**

```python
found = Path(toplevel.out.strip())            # image.py, from `rev-parse --show-toplevel`
if found.resolve() != Path(root).resolve():
```

`Path("")` **is** `PosixPath('.')`, and `.resolve()` is the working directory — so an empty answer became
"the current directory", which is never the product root, so `provenance` reported the tree as living
inside somebody else's checkout and returned nothing. The warning said it out loud without anyone
noticing: *"the nearest one is `.`"*. The image would then have been built with no `VERSION`/`REVISION`
**and the run would have stayed green**; it is only visible because a test asks.

The second: `tickets_of` reads the commits a web merge brought in and falls back to the merge subject when
they name nothing. An empty read is indistinguishable from "they named nothing", so a merge whose author
had written si#92 was reported as {94} — the pull request's own number. A release note about the wrong
number, green.

**`Result.answered` is the seam.** `ok` asks whether the command succeeded; `answered` asks whether it
said anything, and a caller that goes on to use `out` as a value needs the second question. Three places
ask it now:

* `rev-parse --show-toplevel`, where an empty answer blames the tool instead of the tree;
* `describe` and `rev-parse HEAD`, which had never been seen to fire — an empty `describe` would stamp
  `VERSION=""`, a label that is present, empty and wrong, which a reader cannot tell from a build that
  declined to say;
* the `<sha>^1..<sha>^2` read, which has an answer **by construction**: the merge exists, so its second
  parent brought at least one commit.

It is a per-call question and not a rule, deliberately. `log --merges` over a range carrying none
legitimately prints nothing, and so does `git tag` in a checkout with no tags — refusing those would turn
two ordinary states into a broken tool.

**Why git answered nothing is still open.** It has only been seen on one machine, where every push starts two
workflow runs seconds apart on the same host — but one of the two failures had no concurrent job, so shared
state cannot be the whole of it. That half needs the runner, and it is si#277. This half converts a
wrong answer into a loud one, which is the difference between a defect that costs a re-run and one that
ships an unlabelled image.


### A repaint with no screen is an ordinary moment, not a missing widget (si#265)

`test_a_resumed_walk_asks_only_the_steps_nobody_answered` failed on one run of a commit and passed on two
others of the **same** commit, with nothing in that commit touching the TUI:

```text
textual.css.query.NoMatches: No nodes match '#status' on Screen(id='_default')
```

A check that gives two verdicts on one commit is not measuring its subject — it is measuring how the
scheduler happened to interleave. That is si#261's fault one layer along: there the verdict was decided by
who started the run, here by when a frame finished. And the expensive half is not the red cross; it is
that every red run of this kind teaches whoever sees it that a red CI might mean nothing.

`_repaint_status` looked the bar up on every call — and it has three callers, two of which are clocks: a
once-a-second `set_interval` and the worker thread's handovers. Both reach it in moments the app did not
choose, including the two stretches where there is no screen at all: before `on_mount`, and after the app
has been torn down, which is where `run_test()` found it.

**The repair is not `except NoMatches: pass`.** That swallows the other case too — a mounted screen that
really has no status line — and trades a loud flake for a silent one. The two states get different code:

* the bar is found **once**, in `on_mount`, where `compose` has just yielded it, so a screen without one
  raises there naming the selector;
* every later repaint writes to the widget that lookup found, and when there is no screen the reference is
  `None` and there is simply nothing to repaint.

`on_unmount` drops the reference rather than letting a late tick write into a detached widget — that write
raises nothing and changes nothing, which is exactly the silent half of the pair this ticket is about.

Four checks, three of them seen red against the old shape, and the once-flaky file run five times over.

### The notes guard could only ever fail after the merge, and asked for the wrong spelling (si#270)

Two defects in one gate, found because `main` went red on three consecutive merges and none of them had
broken anything. Measured over the last 40 pushes to `main`: **6 red, and 5 of the 6 were this gate** —
each for a different number, so nothing accumulated and every repair looked like a one-off.

**It could not fail on the branch.** `merges_in` walks `git log --merges`, and a branch's own commits are
not merges, so on a `pull_request` run they sat inside the range unread. A pull request's ticket entered
the range the instant a merge commit for it existed and not one second earlier — which is why si#263 and
si#264's notes were written from si#261's branch, and si#261's from #262's, and why a docs repair ended
up inside a chore about a runner.

The information was there the whole time, and the module already knew how to read it: `tickets_of` reads
`^1..^2` for exactly this. Measured over every merge since v0.12.0 — **36 of 41: the number the gate
demands is already named in a commit subject on the branch, before any merge commit exists.** Those 36
now fail where they cost a push. `branch_tickets` reads two parents of GitHub's own merge and of nothing
else, so a released range and an authored merge are the populations they always were.

**And it asked for a ticket that does not exist.** When a merge's commits name no number, the gate fell
back to the subject GitHub composed — `Merge pull request #262 from …` — and demanded a section naming
`si#262`. On GitHub a number is an issue or a pull request and never both, so a heading `(si#262)` sends
its reader to a merge rather than to the reason for it. Measured over the whole page: **14 of 109 section
headings name a pull request rather than a ticket**, one of them headed *"The release guard asked for
notes about pull requests"*. si#103 repaired the half that reads one level down and left the fallback
standing.

The demand has not weakened — the merge is work the release carries and still has to be described. Only
the spelling asked for is true now:

```text
ERR the v0.16.0 section names 7 of the 8 changes merged into v0.15.0..HEAD; missing: #262 (pull request).
    A `#N` there is a PULL REQUEST and not a ticket - write it in that spelling, because `si#N` would
    assert an issue of that number and there is none
```

The fourteen headings already on the page are left as they are. Rewriting them would mean inventing
tickets that were never filed, and a release note is a record of what happened.

### The CI job runs on a self-hosted runner (#262)

Named `#262` and not `si#262` because there was no ticket: this is the first change judged under the rule
above, and it is a pull request. `ci.yml`'s job moves to `ghr-8`, addressed by a label of its own rather
than by `[self-hosted, Linux, X64]`, which would describe any self-hosted Linux machine this account ever
registers. `release.yml` stays on `ubuntu-latest` — it publishes to PyPI and GHCR and moving it is a trust
decision, not a chore.

**No `python:`.** `actions/setup-python` never installs Python; it unpacks prebuilt archives, and its
manifest carries Ubuntu 22.04/24.04/26.04 and RHEL 9/10 and nothing else. This runner is Debian, so no pin
could have been honoured. Stated rather than buried: nothing now says which Python version CI tests on,
and a pin that cannot be honoured is worse than none. `DELIVERY_DOCKER_BOOTSTRAP=1` opts into the shape
`simplon.docker` was written for, because a container job needs docker on the runner in order to start
and so cannot be the thing that puts it there.

### Five checks that reported who started the run, not what the code did (si#261)

Three checks in `tests/test_tasks_docs.py` had been red on every developer machine that runs as root and
green on `ubuntu-latest`, and the difference was carried from session to session as a footnote
("pre-existing, root-bound"). Moving CI to a self-hosted runner made the footnote a failure.

Two facts were arriving ambiently: `docker.user_args` reads `os.getuid()`, and `_unwritable` asks
`os.access(..., W_OK)`, which answers **yes** to root whatever the mode says. So `assert "0:0" not in argv`
was really `assert os.getuid() != 0` — an assertion about the machine wearing the costume of one about the
code, which no amount of correct behaviour could make pass.

**It was five checks, not three, and the second pair is the worse half.** Two more *passed* as root for
the wrong reason, and that only showed when this file was finally run as a normal user:
`test_render_falls_back_to_root_*` expect `--user 0:0`, and as root the fallback never fired — `os.access`
had called the blocked tree writable — so `0:0` came out because the *caller* was root. The assertion was
right and the path to it was not. A check that is red tells you something; a check that is green for a
reason nobody intended tells you nothing and looks fine.

`_as(monkeypatch, uid, gid, unwritable=[...])` now pins both facts per test and delegates to the real
`os.access` for every path it was not given, so the pin is a statement about those paths rather than a
second, cruder filesystem underneath. `conftest.py` already does exactly this for two other ambient facts.

The point is not that they pass as root. It is that both cases became assertable on either machine, which
made two checks possible that could not be written before: a caller who **is** root gets a container that
runs as root, and the warning names the caller the render decided on rather than whoever started the
suite. Measured on both identities — 21 passed as root and 21 as `nobody`; broken deliberately, the same
four failed under each.

### A docker that is present and cannot be run is a third state (si#263)

Found by moving this repository's own CI to a self-hosted runner. On that machine a file named `docker`
sits on `PATH` that `shutil.which` accepts — it checks the permission bits, and they are set — and that
cannot be executed: `PermissionError: [Errno 13] Permission denied: 'docker'`, the signature of a binary
on a `noexec` mount.

**`ensure_docker` came apart in a traceback.** `_daemon_reachable()` probed with a bare
`run(["docker", "version"]).ok`, so the error propagated out of the one function in that module whose
entire stated purpose is to *die naming the fixes* — naming none of them. A third state that crashes the
function whose job is to classify states is this project's recurring defect wearing the module's own
clothes. It answers "not reachable" now, and `ensure_docker` says the rest out loud as it always meant to.

It is written against `OSError` rather than `PermissionError`: a wrong-architecture binary and a broken
interpreter reach the same place, and pinning the one subclass that happened to be measured would be a
guard fitted to the accident.

**Three e2e suites carried the same guard, word for word**, whose job is to decide whether to *skip* — and
which failed at import instead, taking every test in the file with it. It lives once in `conftest.py` now.

*Absent* and *present but unusable* are the same answer to "can I run a container". They are not the same
answer to "is something wrong with this machine", which is why the kernel still says so.

### `support ci-privileges` is placed, because simplon now provisions a CI host (si#264)

The command has existed since si#92 and was declared in the catalogue and placed **nowhere** — it grants
`NOPASSWD: ALL` and a docker group, which is *"a change nobody wants appearing in a CLI they did not ask
for it in"*. A product that provisions CI hosts places it deliberately.

Simplon now does, so it places it:

```text
$ ./simplon.sh support ci-privileges nosuchuser
ERR  no such user on this host: 'nosuchuser' - nothing was written
```

**It does not fix a runner that executes as root**, and the placement says so where a reader will find it,
because the two look like one problem. For root a docker *group* is not the obstacle. The order is: a
normal user first, then these privileges, then a service restart — a group is inherited at process start,
and the command deliberately does not know what the service is called.

### A carrier says what runs on it, instead of the kernel deciding (si#258)

The ticket asked whether a **hypervisor** is a carrier. The answer is no - an ESXi host that an artefact
is imported into, asserted against and torn down is a test target, not what an environment is *realised
on*, which is what `carriers:` means. What the ticket found on the way there is the part worth fixing.

**`portainer:` was required on every carrier**, so *carrier* and *Portainer host* were the same word - and
`deploy carrier` proved it by running an apt -> Docker -> Portainer playbook at the end of every run with
no branch in it. A product that wanted a machine got a workload it had never asked for, and on a machine
without `apt`, a red run rather than a useless one.

A carrier may now declare `proxmox:` alone. `deploy carrier` then stops when the machine exists and
reports that as its own outcome:

```text
OK  carrier 'lab' exists on pve-2 and nothing was installed on it - it declares no `portainer:`,
    so what runs on it is this product's own to deploy
```

Created-and-not-configured is a third outcome beside created-and-configured and failed, and it is said
rather than inferred from a log that stops early. `backend: portainer` pointed at such a carrier is
refused by name, and the admin-password check - which exists so a Portainer cannot lock itself - is no
longer asked of a carrier that has no Portainer to lock.

**It cost no manifest anything.** Measured over the GitHub API: not one repository in this family
declares a `carriers:` section, this kernel's own included.

### The kernel stopped guessing where your tree is (si#250)

The kernel *generates* against two facts about a product's directories, and it had never stated either.
Now the product says them:

```yaml
layout:
  build_root: kernel      # default: "" - the product root
  tests: tests            # default: tests
```

**The trap it removes cost a real adoption.** The Java profile scaffolds `gradle assemble`, and
`toolchain:run` writes `-v <product root>:<workdir> -w <workdir>` - so `workdir:` is the path the tree is
*mounted* at, not a path inside it. A product whose Gradle root was one directory down got a command that
looked right and built the wrong thing, and naming the subdirectory in `workdir:` does not fix it: that
relocates the whole tree instead of descending into it. `build_root:` descends, and the mount stays the
product root, which a build that walks up to find its fixtures needs:

```text
without layout:            -v /home/dev/firn:/work -w /work        gradle assemble
build_root: kernel         -v /home/dev/firn:/work -w /work/kernel gradle assemble
```

**`tests:` replaces two defaults that were layout statements made in passing** - `tests/reports` in the
suite taxonomy and `tests/acceptance` as a task's parameter default. Both now come from the section, and
both answer the same thing they always did for a manifest that says nothing.

**One spelling was chosen: `tests`.** Both were in live use - three products and the kernel's own ignore
block at `tests/`, netctl's root at `test/` - and nothing had ever decided. netctl is not refused; it says
so in one line instead of working around it per command.

**Nothing here rules on a tree, and that is a measurement rather than a preference.** Across this family,
six products have six layouts: one is an Eclipse plugin tree, one has no `src/` at all. A kernel that
stated one layout and held products to it would refuse five of the six, and two could not comply. So the
section lets a product *say* what the kernel was guessing.

**`simplon init` now writes a `tests/` directory with a README in it**, saying what belongs there and how
to move it - which is the file the product that filed this ticket had written by hand. A directory with a
README beats a convention nobody reads. Eleven scaffolded files instead of ten.

### The values a deployment must be given (si#5)

`required:` names the variables a deployment is handed, and every one of them must have a value. They are
read out of the environment the deploy command runs in, on *every* deployment.

```yaml
  prod:
    backend: portainer
    stack: bc-prod
    required:                 # must have a value, or the deployment stops
      - COCKPIT_DATA_DIR
      - BACKUP_DIR
      - HTTP_BIND
    optional:                 # travels when set, absent when not
      - SMALLINVOICE_CLIENT_SECRET
      - APP_TITLE
```

**Why not once into Portainer, by hand.** Portainer stores the stack's environment either way. The only
question is whether its copy is an *image* that every deployment refreshes or an *original* that nobody
does - and two masters of one set of values drift, after which the instance runs on values written down
nowhere. The consuming product put it that way, and it is the better formulation of a rule this kernel
already had: a manifest names a variable, never a value.

**An empty value fails the deployment**, and this is the one place a consumer asked for *more* strictness
than was offered. Their document writes `${COCKPIT_DATA_DIR:-${HOME}/.biz-cockpit}:/data`. A missing value
does not make compose fail - it falls back, and the bind mount lands in the *carrier's* `/root` instead of
`/srv/biz-cockpit/prod`. The container writes happily, the deployment is green, and the database sits
outside everything their `backup` knows about. An instance that runs and is not backed up is this
project's recurring defect exactly: green because nobody looks.

Every missing value is named at once. Repairing eight variables one run at a time is the kernel's work
handed to an operator:

```text
environment 'prod' requires 3 value(s) and 1 of them is not set: BACKUP_DIR. They are exported where the
deploy command runs; a value that is missing would let the deployed document fall back to its own
default, which is how an instance ends up running somewhere nobody is looking
```

**There are two lists because "travels" and "may not be empty" are two statements**, and the first form
had quietly made them one. It took a real product to show it: theirs writes
`${SMALLINVOICE_CLIENT_SECRET:-}`, where *empty means "not connected"* and the integration is deliberately
optional. In `required:` that product becomes uninstallable without a Smallinvoice account - undoing the
very ticket that made the integration optional. In neither list the secret never reaches the stack, so the
integration is not optional but impossible. An `optional:` name with no value is left **out** of the
payload rather than sent as an empty string: to a document writing `${X:-}` those are the same today, and
the day they differ the kernel would have chosen for it. A name in both lists is refused rather than
ranked.

**The lists are named after what they enforce, not after what they hold** - the consumer's request, and the
right one: the rule is "this variable must have a value", which is a statement about obligation and not
about a datatype. A secret can join the same list without it being renamed.

**`SIMPLON_VERSION` may not be in it.** The kernel sets it from the version being deployed, and a second
answer to that question would make `--version` mean whatever happened to be exported - with nothing
printing which of the two had been used. That refusal is counted as an **expression rule** rather than
diagnosis, because the honest answer to the sorting question is that the refused manifest would have
deployed perfectly well; the exported value would simply have been ignored.

### `backend: portainer` deploys, and the 200 that did not mean deployed (si#5)

A product writes four lines and the kernel deploys it - no backend class, no registration. The chain
under it was already the kernel's: `deploy carrier` builds the Portainer, `carriers:` describes it,
`environments:` points at it. What was missing was the far end.

```yaml
environments:
  prod:
    backend: portainer
    carrier: hausportainer
    stack: myctl-prod
    repository:
      url: github.com/you/myctl
      compose: deploy/docker-compose.yml
      credential_from: GIT      # a PREFIX; omit it for a public repository
```

**Portainer clones the repository itself**, rather than being handed a compose document somebody's
orchestrator assembled. What ran is then a commit, and the stack can be redeployed from Portainer with no
orchestrator running at all. Creating and redeploying are two different calls with different bodies, and
the second deliberately re-sends none of the description: Portainer already holds it, and sending it twice
would put a second copy of it where nothing compares it with the manifest.

**The credential travels with every deployment and is never stored.** So a stack somebody opens in the
Portainer UI carries no usable read access to your source.

**The find, and it was found by driving the real API rather than a double.** `POST .../repository` answers
`200` for *accepting* the stack, not for running it. A repository whose compose file does not exist is
accepted with a 200 and then fails - and the first draft of this returned "created" and would have exited
`0` over a deployment that pulled nothing. That is the defect this project hunts, one seam before the
operator. The deployment is now read back until Portainer stops working on it, and three outcomes are told
apart rather than folded into two:

```text
stack myctl-prod was created from github.com/you/myctl (main), and Portainer could not bring it up:
failed to deploy a stack: failed to create compose project: failed to load the compose file :
open /data/compose/7/docker-compose.yml: no such file or directory
```

Still deploying when the wait runs out is the third, and it is neither of the others: a slow image pull is
not a failure, and an operator told the wait ended knows to look rather than to deploy again. The status
numbers behind that are measured, not read off a document - a stack sat in "deploying" for roughly twenty
seconds while one image pulled, and came up afterwards.

**`SIMPLON_VERSION` is what reaches the stack**, so `deploy up --version 1.4.0` deploys 1.4.0 rather than
whatever the compose document happened to name. It is one variable and it is the kernel's own; passing a
*product's* environment values through is a slice of its own. `local` is refused: Portainer clones, and
there is nothing on this machine for it to clone.

**Two smaller things the measurement forced.** `repository:` is a block rather than the bare URL the
vocabulary shipped with, because the first real consumer's compose document is not at the repository root
and a string cannot say so - widened before the vocabulary was ever released, so no manifest had to be
migrated. And `portainer:` took an `insecure:` of its own: Portainer generates its own certificate on
first start, so a carrier the kernel had just built was unreachable without it.

### The carrier's Portainer is usable when the command finishes (si#5)

Two gaps, both measured against a real carrier the day after it was built, and both of which left
`deploy carrier` delivering something nobody could use.

**A Portainer with no admin account locks itself after five minutes.**

```text
the Portainer instance timed out for security purposes, to re-enable your Portainer instance,
you will need to restart Portainer
```

`/api/users/admin/init` then answers 403, because 2.45 wants a setup token it prints into its own log.
Parsing a log for a token is fragile; starting Portainer already initialised is not. It is started with
`--admin-password-file` now, and `/api/users/admin/check` answers 204 from the first second.

The password is read from the environment off the same prefix the carrier's `url_from:` names -
`url_from: PORTAINER` means `PORTAINER_PASSWORD`. **It is required**, and short ones are refused before
anything runs: Portainer will not start on fewer than twelve characters, and one that never starts never
initialises.

**A fresh Portainer manages nothing.** `GET /api/endpoints` comes back empty while a carrier declares
`endpoint: 1` - so that number was a promise nobody kept, and the first stack deployment would have
failed against an environment that did not exist. The local Docker environment is created now, once.

**A carrier built before this release is repaired rather than left alone.** A play that acted only on a
*missing* container would leave every existing Portainer locked forever. This one notices how the
container was started and rebuilds it - driven by putting the trap back by hand and watching the command
take it down and replace it.

**Nothing to do** beyond exporting the password before the next `deploy carrier`.

### `deploy carrier` makes the thing an environment stands on (si#5)

The second slice: the vocabulary of 0.16.0's first entry now has a command behind it. One `deploy
carrier` reads the `carriers:` section an environment points at, makes the machine on Proxmox, and puts
Portainer on it.

```text
$ ./myctl.sh prod deploy carrier
==> carrier 'hausportainer' for environment 'prod' on pve-2 (lxc)
    ...
    "msg": "Portainer 2.45.0 on 10.0.0.124:9443"
```

**Two tools, each in a pinned container, each doing the half it is good at.** Pulumi describes a goal and
keeps state; Ansible describes steps and keeps none. Neither is installed on your machine - the same
arrangement `docs:render` uses.

**It is its own command and not a preamble to `deploy up`**: two verbs, two verdicts. And it sits under
`deploy` rather than `support`, because setting a carrier up needs the environment and `deploy` is
already environment-first.

**Run it twice.** Measured on a real cluster: `3 unchanged` from Pulumi, `changed=0` from Ansible, one
container on the machine.

### Three facts in it that each cost a measurement

Worth reading before you change any of them, because each is a line that looks like tidying up.

**`nesting` and not `keyctl`.** The design this came from named both as preconditions for Docker in an
unprivileged container. Proxmox refuses every feature flag except `nesting` to an **API token** - HTTP
403, *"only allowed for root@pam"* - even a root token made with `--privsep 0`. And Docker does not need
it: Debian 13, kernel 7.0, overlay2, cgroup v2, `docker run hello-world` green with nesting alone.

**A public key and never a password.** Pulumi encrypts only values that are *marked* secret. The provider
marks its own `apiToken` and `password`; the container resource marks nothing. So a container created
with a root password would put that password in clear text into the state file - which is the file you
are asked to commit. Measured on a real run: the API token appears **zero** times in clear, the public
key once, which is correct because it is public.

**Your carrier's storage is checked before anything runs.** `/nodes/<node>/storage` lists storages the
node cannot actually use - one defined for a *different* node comes back with `enabled: 0, active: 0`.
Creating a container on it fails with an HTTP 500 three minutes in. The kernel asks first, and tells you
which storages that node really offers for containers.

**Nothing to do.** A product that declares no `carriers:` section has no new command and no new
requirement.

### An environment can say what it stands on (si#5)

The first slice of the deployment-provider work, and it is the vocabulary rather than a provider. A new
`carriers:` section names what an environment is realised on; environments point at it:

```yaml
carriers:
  hausportainer:
    proxmox: { node: pve1, kind: lxc }
    portainer: { url_from: PORTAINER, endpoint: 1 }

environments:
  test: { backend: portainer, carrier: hausportainer, stack: myctl-test, repository: github.com/you/myctl }
  prod: { backend: portainer, carrier: hausportainer, stack: myctl-prod, repository: github.com/you/myctl }
```

**One carrier, many environments** - which is the shape both waiting consumers described: a Portainer
serves several applications and, on one instance, several environments. Writing the chain into each
environment instead would put the carrier in the file two or three times, and two environments on the
same Portainer could drift apart with nothing comparing them.

**No secret may be written there, and the section has no field for one.** `url_from: PORTAINER` names the
prefix; the URL and the token are read from `PORTAINER_URL` and `PORTAINER_TOKEN`. A key the section does
not take is **refused rather than ignored** - because a parser that skipped what it did not recognise
would let a `token: ghp_...` sit quietly in a committed file, which has happened once in this family
already. That one refusal is counted as an **expression rule**: a manifest carrying a stray `token:`
would have worked, so refusing it costs flexibility and is billed as such.

**Nothing to do.** Every field defaults to empty and an absent `carriers:` section is not a refusal - the
six products this kernel can reach declare `backend: local` and nothing else, and none of them has a line
to change.

### The kernel renders a report of its own suite (si#248)

The catalogue has carried `test:report` since long before this release, `with-what/test-levels.md`
describes the Allure report at length - and `simplon.yaml` placed none of it. Measured on 2026-09-14:
`test:gate`, `test:accept`, `test:report` and `docs:acceptance`, all offered, none placed. The two
workflows ran the suite, the type gate, the staleness gate, the wheel, the image and the notes guard, and
rendered nothing.

That is the shape si#8 found in the type gate: a capability shipped to every other product and never
adopted at home. It is adopted now, in both workflows, with the archive uploaded as a run artefact:

```yaml
suites:
  gates:
    - name: unit
      command: test suite
      results: clear
      results_from: tests/allure-results
  report:
    merge: [tests/allure-results]
```

**A `command:` gate, not a `suite:` one**, because this suite runs from inside `tests/` so its conftest
applies - si#106's kind exists exactly so a product keeps the runner it has.

**The report is a CI artefact and not a page on this site**, which was a decision rather than a default:
a published report is the last green run frozen in public, including while `main` is red.

**And both steps carry `if: always()`.** A GitHub job stops at its first failed step, so without it the
archive would exist for exactly the runs nobody needs it for.

### What the first draft shipped, and the one line that fixed it

Worth reading if you adopt this, because the failure is silent. The first draft declared only the gate's
`results_from:` and ran `test suite` then `test report` - which is what both workflows do. The report
step arrives there with no gate run behind it, so it merged nothing, rendered a **2.5 MB Allure archive
of zero tests**, and printed `OK` beside it.

`report: merge:` is the line that was missing. `results_from:` is merged when the KERNEL runs that gate;
`merge:` is what a standalone report step reads. Declaring both is not redundancy - the two routes to the
archive are real, and a product may take either.

**Nothing to do.** A product that declares no `suites:` section is unaffected, and `simplon[report]` is
an optional extra: nothing is added to what a consumer must install.

## 0.15.0

### The notes were written before the tag, and had to name themselves (si#246)

The [release procedure](../../how/releasing/) says the notes go in before the tag, because the tag points
at a tree that already carries them. This time they went in as a pull request of their own, after the
work they describe had already merged - and `test:release-notes` immediately refused the section it had
passed a minute earlier:

```text
ERR the v0.15.0 section names 2 of the 3 tickets merged into v0.14.0..HEAD; missing: si#246
```

**The gate was right and the commit was wrong.** A merge GitHub's button composed is read one level down,
at the commits it brought in - precisely so that a notes PR cannot name itself. That commit's subject
named no ticket at all, so the only number left was the pull request's own, and the rule fell back to it.

**The fallback stays, and that is measured rather than assumed.** Removing it would silently excuse
fourteen merges in older ranges whose only ticket source is their pull request's number - #1, #7, #9,
#10, #11, #25, #36, #72, #73, #84, #95, #96, #195 and #207 - and two of those are already section
headings on this page, for exactly this reason. A rule that drops work from the record to make a present
run pass is the opposite of what this gate is for.

So the section names it, the way 0.13.0 names si#195 and si#207. What it costs a reader is one heading;
what it buys is that no change went out undescribed - which is the whole claim the page makes.

**Nothing to do.**

### The API contract, in the Python and the Java profile (si#240)

`support toolchain python` and `support toolchain java` now write a `spec` command as well. An OpenAPI
document is a **build** output, so it is scaffolded like every other language command rather than given a
catalogue coordinate:

```yaml
build:
  commands:
    spec:
      task: "toolchain:run"
      with:
        image: python:3.12
        workdir: /src
        network: none
        argv:
        - python
        - -c
        - |
          import importlib, json, pathlib, sys
          module, _, attribute = sys.argv[1].partition(":")
          target = getattr(importlib.import_module(module), attribute)
          app = target if hasattr(target, "openapi") else target()
          pathlib.Path(sys.argv[2]).write_text(json.dumps(app.openapi(), indent=2) + "\n")
        - app.main:create_app
        - api/rest/openapi.json
```

Two positional arguments and both are yours: the app - spelled the way uvicorn spells it - and where the
contract is committed. A factory and a module-level app object both work.

**The two languages do not cost the same, and the profile says which.** The Python export calls
`app.openapi()` on an app in memory and runs with `network: none`. The Java entry is
`gradle generateOpenApiDocs`, and the `springdoc-openapi` Gradle plugin **starts your application**,
reads `/v3/api-docs` and stops it again - so it needs the network, and the document it writes carries
`"servers": [{"url": "http://localhost:8080"}]`, because that is where it was read from.

**Without the prerequisite, each goes red rather than quiet.** A Java tree with no plugin answers
`Task 'generateOpenApiDocs' not found`, BUILD FAILED, rc 1; a Python export pointed at the wrong module
exits 1 and **writes no file at all**, so a broken export can never hand the staleness gate a
half-written contract to report as a stale one.

**Then commit it and let `test:generated` rule on it** - the same section, the same gate, the same six
lines as for a shell completion:

```yaml
generated:
  contract: { path: api/rest/openapi.json, by: build spec }
```

**Nothing to do.** A product that does not run `support toolchain` again keeps the commands it has.

### Why there is no Maven task and no PyPI task (si#234)

The catalogue publishes a .NET package and a C++ one and nothing for Python or Java, which reads as a gap.
It was measured over the six products that install this kernel - their manifests, their build files and
all fifteen of their CI workflows - and **not one of them publishes a language package**: no wheel, no
jar, no nupkg, no Conan package. The two tasks that do exist are placed by nobody.

**The parity was already there, in the direction nobody was looking.** Every product publishes through
`release:image`, `release:artifact` or `release:asset`, and none of the three knows what language built
what it moves. The asymmetry runs the other way: two languages have two *extra* tasks nothing uses.

The reasoning is now on the site rather than in a ticket:
[Handing a package over](../../what/handing-a-package-over/#why-there-is-no-maven-task-and-no-pypi-task).

**Nothing to do.** No coordinate was added or removed.

### Scaffolded commands keep their line breaks

A multi-line value used to be written into your manifest as a folded single-quoted scalar - one blank
line between every program line. It is a literal `|` block now. Nothing that was scaffolded before this
release can move: the export program above is the first multi-line value the profile table has ever had.

## 0.14.0

### One contract, two languages (si#239)

A new chapter: [One contract, two languages](../../what/one-contract-two-products/). A product whose
interface has two sides - a Python service and a Java client over one `.proto` - driven from a single
launcher.

```text
$ ./greeter.sh build proto     ->  both stub sets, as one plan with two steps
$ ./greeter.sh test wire       ->  REPLY: hello the java client, from the python service
```

**Nothing in it was run by hand.** The service is a container and so is the client, and both are started
by the command rather than by the reader - this repository's own rule about CI steps, applied to a
documentation page: a step that exists only in a transcript cannot be run by the person reading it.

**The first draft needed two products and had to end by admitting a gap**: the `.proto` was copied into
both trees, one contract and two files with nothing keeping them equal - the second-source shape removed
everywhere else in this repository. One launcher over one tree removes it rather than describing it, and
the chapter says so where the admission used to be.

It also records what the scaffolder does here: a second language **keeps** the first one's `proto`
command, because scaffolding never overwrites. One tree with two languages therefore declares
`proto-python` and `proto-java` itself and plans them under one `proto` - so what a person types stays
one command however many languages the contract has.

**Nothing to do.**

### gRPC and Protobuf, in all four toolchains (si#238)

`support toolchain <language>` now writes a `proto` command too, in every one of the four profiles:

```yaml
build:
  commands:
    proto:
      task: "toolchain:run"
      with:
        image: namely/protoc-all:1.51_2
        workdir: /defs
        argv: ["-d", "proto", "-l", "python", "-o", "build/proto/python"]
```

**No new catalogue coordinate.** gRPC arrives the way every other language tool here arrives - as a
ready-made command the scaffolder splices into your manifest, which you then own. That was the decision
and it is why none of the counted guards moved: a coordinate would have turned about twenty of them red,
and this needed none.

**One image serves all four languages, measured rather than assumed.** `namely/protoc-all` generated real
stubs for each from one `.proto`: `greeter_pb2.py` + `greeter_pb2_grpc.py`, `GreeterOuterClass.java` +
`GreeterGrpc.java`, `greeter.pb.h/.cc` + `greeter.grpc.pb.h/.cc`, `Greeter.cs` + `GreeterGrpc.cs`. The
four profiles name that image with a different `-l`.

**It is the first command that brings its own image**, because a language SDK carries neither `protoc`
nor its plugin. That needed no change: the scaffolder has always written `{"image": profile, **body}`, so
a body that names an image wins. The capability was there and unused, and `test_profiles` now proves the
override through the real toolchain gate instead of by reading the table.

**Stubs go to `build/proto/`, regenerated every run.** Generated code is not source: nothing in the tree
can go stale, no diff ever shows generated lines, and `depends_on` can plan generation before the build.

Two questions were deliberately left: whether `.proto` files should be named in a manifest section rather
than found under `proto/` by convention, and whether a breaking-change check becomes a `test` half. Both
are cheaper to answer against a product that has placed this than in the abstract.

**Nothing to do.** A product that has already scaffolded keeps its commands untouched - the scaffolder
never overwrites - and gets `proto` by running `support toolchain <language>` again.

### A committed generated file has to be what its command produces (si#240)

`./myctl.sh test generated` regenerates every file a `generated:` section declares and fails if what came
out is not what was committed, naming the file and the command that refreshes it.

```yaml
generated:
  completion: { path: deploy/completions/myctl.bash, by: support completion }
  reference:  { path: docs/site/content/with-what/commands.md, by: docs reference }
```

**The question had been invented twice already, and it has drawn blood here.** biz-cockpit wrote
`verify_spec` over its OpenAPI contract and called it its CI staleness gate; this repository wrote
`test_own_completion.py` over its shell completion. And `6ddecaf` is the gap between them: a command was
added to `simplon.yaml` without regenerating the completion, and `main` stood red - with an uncompletable
command - until somebody noticed.

**The obvious implementation had this repository's own recurring defect in it.** `git diff --exit-code`
over a path git does not track exits **0**, so an artefact that was never committed at all - the mistake
in its most complete form - would have passed green. Every entry is checked for being tracked first. The
same shape one step later is why the regenerating command's exit code is read: a command that could not
run leaves the file alone, the diff is empty, and "regenerated and matched" would be indistinguishable
from "did not regenerate".

**Where this came from, and what is deliberately not in it.** The ticket asked for REST/OpenAPI support.
Reading the one product that does it showed two halves: an export that is three lines of the product's
own app factory in a container, and a verify that is not product-specific at all. Only the second is
here. A scaffolded `spec` command would have to guess an argv - biz-cockpit's runs its own factory
against a temp database - and a starting point nobody runs is worse than none.

**simplon rules on itself**, and the gate is proved against the run that caused it. `simplon.yaml`
declares the two files this repository really commits - the shell completion and `ci.yml`, both carrying
*"GENERATED ... do not edit"* at the top, a promise nothing checked until now. `0794e24` changed the
manifest by twenty lines and touched no completion; `git show --name-only` on it lists one file. The
gate, running in CI on that push, would have been red on the spot.

It also caught a mistake while being wired up, which is the sort of thing it is for: the first draft of
the section said `by: release workflows` and the command is `support workflows`. A wrong `by:` regenerates
nothing and would report freshness - except that the gate reads the command's return code, so it said so.

**Nothing to do.** A product that declares no `generated:` section is unaffected.

### The deploy family, and the rib that is no longer empty (si#235)

`deploy` was the one group of the six the catalogue contributed nothing to. It now offers two tasks, and
they are the same for every product:

```text
./myctl.sh prod deploy up --version 1.4.0
./myctl.sh prod deploy down --version 1.4.0
```

**One shape, and the axis is what the product IS.** A `deploy: kind:` says `client` or `server`. A CLIENT
application is installed into a directory on this machine, one directory per version, so a rollback is a
second `up` rather than a re-fetch. A SERVER is brought up on a target through the backend the product
registers - `simplon.backend` has always been the seam for that and gained only a REGISTRATION, because a
catalogue task is called with manifest-pinned parameters and cannot be handed a registry as an argument.

**Out of scope, said once so nobody waits for it:** distributing a client application to a FLEET of
machines - an SCCM, an MDM, a software deployment server. `client` means installing a version *here*.

**The page's own argument changed, and it was withdrawn rather than repaired.** `with-what/phases.md`
said the empty ribs were *exactly* the env-first pair, and its test said so "where it can stop being
true". It stopped. What survives is the implication that carried it - an empty rib is always env-first -
and `monitor` is the one left. What `deploy` gained is the VERSION half; the provider half, the thing
three products would otherwise write three times, is still open as
[simplon#5](https://github.com/marcozwyssig/simplon/issues/5).

**Four refusals were pulled into the census without a rule being written.** `environments.parse_data` has
always refused a matrix that is not a mapping, is empty, names an unimplemented backend or defaults to an
environment it does not declare - and until a deploy task handed it the manifest document, nothing walked
there from a manifest seam, so nothing counted them. The count moved 116 -> 123 for that reason and for
three new ones, and the sum growing in the open is exactly what the census exists for.

**What a product has to do.** Nothing, unless it wants these commands. A product that does declares
`deploy: kind:` and `source:`, and - for a server - registers its backends with
`simplon.backend.register({...})`. Its own `deploy up` keeps working untouched until it places the task.

### A deployment can say which version it is deploying (si#235)

Thirty-two deploy commands across the five products this kernel can reach, and not one of them could
say. What went up was decided by `IMAGE_VERSION` if it happened to be exported, and by whatever the
product's build file said otherwise - an environment variable no manifest mentions and no command
documents. A deployment now names its version, and there are three kinds of answer:

```text
--version 1.4.0     this exact published version
--version latest    the newest published version
--version local     the current code base, built now
```

**Three values for three meanings**, which is the design rather than a convenience. One value that
silently meant two of them - `latest` quietly becoming a build when nothing is published - is the defect
this repository keeps finding, and the resolution its own rules prescribe is to widen the range until
each meaning has its own value. `local` touches no registry at all; a version the registry does not serve
is refused before anything starts; and asking for nothing is refused rather than defaulted, because
"whatever is newest" is a choice somebody makes.

**The section points at an entry you already have.** `images:` and `artifacts:` carry the registry and
the repository already, so `deploy: source: { images: app }` names one of them instead of writing a
registry down twice. Where the entry cannot serve - a bare string rather than a mapping, or no
`registry:` at all, both shapes measured in real manifests - it is refused by name, with the keys it does
carry in the message.

This is the **eighteenth** top-level section, and its eight refusals are all diagnosis; the census on
[Rules](../../with-what/rules/) carries them.

**Still to come on this ticket:** the catalogue's own `deploy` tasks. The vocabulary and the lookup
landed first because everything else rests on them, and because the kernel already owns the machinery -
`compose`, `portainer`, `backend`, `docker`, `healthgate` and `waits` are all on the library surface
already. What is not yet measured is how much of those 32 commands is really the same work.

**Nothing to do.** A product that declares no `deploy:` section is unaffected.

### The four claims are in English (si#232)

`why/why.md` answers "what is this" with four claims, and all four headings were still German. They
read **Simple**, **Modular**, **Agnostic** and **Evolve**. The one link that pointed at the renamed anchor moved with them; the si#186 note below keeps
the old spellings, because it describes the page as it was in 0.11.0.

**This is the class si#213 said no check would close, arriving on schedule.** That ticket withdrew the
claim that the site is English-only rather than buy a dictionary to lint against, and said why: the first
word a list does not carry is another one like it. These four have no umlaut and are not function words, so
both earlier sweeps answered honestly about what they were asked. Three of them are near-cognates of the
English word that replaces them, which is presumably how they survived two readings by people who knew
they were looking for German.

**No check is being built for it either**, and the reasoning is unchanged by a fourth instance: a reader
is what finds these. What the fourth instance buys is the count, and the count is now on the record.

**Nothing to do.** The old URL and every other anchor are unchanged.

## 0.13.0

**A word that was not a level, and three quotes nothing could check.** `with-what/test-levels.md`
taught the test levels with an example whose third level was `ui`, sitting beside `unit` and `system`.
UI is not a level; it is one kind of acceptance test, and the products spell it that way already.
Renaming it was the easy half. The hard half was that three of the page's five occurrences were quoted
REFUSALS, hand-typed, so a rename would have left three messages on the page that the code cannot
produce.

### The site is in one language (si#195)

`with-what/rules.md` stated the missing-tool rule twice - a German aphorism with its English translation
underneath. The device was deliberate; on a site written in English it still cost a reader a sentence to
skip before reaching the one they could read, so the translation became the quote.

**What was measured, and what it does not say.** Every page was swept for umlauts (zero hits) and for a
list of German function words that cannot be English (one hit, on that line). That is a statement about
those two patterns and not about the site. This note first read that the aphorism was *the only
non-English prose on the site*; it was not, and si#213 found a German noun twice, carrying neither an
umlaut nor a place on the list. The claim is withdrawn rather than re-measured, because no word
list closes this class: the next German noun without an umlaut escapes it the same way. Reading the prose
is the check, and it is a human one.

**Nothing to do.**

### `ui` is a suite of the `acceptance` level, not a level beside it (si#196)

The page's third level is `acceptance` now, and the pedagogy is untouched: it is still the level that
shows how a non-pytest runner attaches, through `impl:` rather than `suite:`. What the page gained is a
paragraph saying why the word matters - netctl, the consumer carrying the most levels of any, spells
them `acceptance-ui` and `acceptance-dataplane` beside `unit-java`, `component-db`, `integration-java`,
`boot-java` and `unit-typescript`, so a gate called `ui` puts a way of REACHING the product where the
level goes.

The three quoted refusals are DERIVED now rather than retyped, and that is the part that outlives this
rename. `tests/test_test_levels_refusals.py` already did this for the page's `command:` gate messages
(si#136, after two of them turned out to be unproducible as written); these three were about the
`suites:` section itself and were out of its scope. They are produced by lifting the page's own example
manifest out of the page - parsed from the yaml block under its own heading, not copied into the test -
and driving it through `testrun.declared`, once unmutated to prove the printed block loads at all and
then three times with one key changed. Each of the three was seen red against the old wording before it
was seen green against the new. A fourth test asserts the unmutated block is one the kernel accepts, so
the three refusals are about the mutation rather than about a defect the page shipped.

The neighbouring fixtures moved with it. `tests/test_verdict.py`, `tests/test_suites_impl_only.py` and
`tests/test_tasks_testrun.py` each used `ui` as a level name in a fixture; those are internal and the
ticket left them optional, and they were renamed anyway - a fixture is what the next reader copies. The
`product.tooling:ui` impl refs in the same files were left alone: they name a product's callable, not a
level.

### What a Gherkin acceptance suite already does, measured rather than designed (si#197)

si#197 asks for acceptance scenarios that read as Gherkin and can be run automatically or by a person.
Before designing anything, the automatic half was DRIVEN, because `test:gate` runs pytest and
`pytest-bdd` is an ordinary pytest plugin. It works today, with no kernel change at all: a product that
puts `pytest-bdd` in its suite's own `requirements.txt` and its `.feature` files beside that suite gets
Gherkin execution through the gate it already declares, and the run reports `passed` / `failed (rc 1)`
like any other level.

One thing decides whether the archive is worth having, and it is a choice inside the product's
requirements rather than anything the kernel can make. With `allure-pytest`, an Allure result carries the
pytest function name (`test_the_gateway_refuses_a_page_nobody_published`), `steps: []`, and the scenario
sentence only inside a `description` prefixed with an absolute path. With **`allure-pytest-bdd`**, the
result's `name` is the scenario sentence verbatim, its `fullName` is `<feature file>:<scenario>`, every
Given / When / Then is an Allure step carrying its own status, the failing step is named with its
assertion, the `Feature:` line becomes a `feature` label and each Gherkin tag becomes a `tag` label. All
of it survives into the rendered single-file archive.

It was then driven a second time in a pinned container, because this platform's rule is that nothing
depends on what is installed on the machine. A containerised acceptance level cannot be a `suite:` gate -
that kind's runner is the kernel's own pytest in a host venv - so it is a `command:` gate naming a
`toolchain:run` command, with `results_from:` harvesting what the container wrote, and that reaches the
archive with the scenario and its steps intact. Three things came out of getting it to run:
`toolchain:run` mounts the product ROOT at `workdir:`, so pointing `workdir:` at a subdirectory hides the
tree rather than entering it; `network:` binds from a `with:` block although the body's own docstring says
a manifest cannot supply it; and an acceptance container given no network did not fail to connect - the
service name resolved through the host's upstream resolver to an address on the public internet, which
answered, and the scenario reported a defect in a product it had never reached. The full measurement is
in the pull request for si#196; the plan si#197 becomes is written against it.

### The two gates that stood on the host, decided against the measurement (si#202, si#203)

si#199's rule is that a product depends on no application installed on the system, and two gates did
not: `test:gate` builds a per-suite venv on the host with `pyvenv`, and `test:typecheck-python` runs
mypy in the host venv. They were answered in one pass because they stand behind one wall, si#121's
measurement that **no prebuilt image can carry a product's wheels**, and answering it twice is how two
answers appear.

**The proof was to remove Python from the host's PATH for the length of a run**, which named the
boundary better than any reading of the source could. `simplon.sh` itself is the boundary and si#199
already states it as one: without `python3` the launcher refuses on its own line, because the kernel IS
host Python until the launcher gets its container route. Past that line the two gates part company.

| with `python3` off PATH | outcome |
| --- | --- |
| `test typecheck-python` | **green.** `Success: no issues found in 87 source files`, rc 0 |
| `test:gate`, suite venv already built | **green.** `1 passed`, rc 0 |
| `test:gate`, suite venv absent | `FileNotFoundError: [Errno 2] No such file or directory: 'python3'` |

**`test:gate` stays pytest in a host venv, and the containerised suite is a `command:` gate.** That was
si#202's open question and the cheaper answer is also the more honest one: a containerised suite cannot
be a `suite:` gate at all, because that kind's runner is the kernel's own pytest, so it is a `command:`
gate naming a `toolchain:run` command with `results_from:` harvesting what the container wrote. si#197
drove exactly that, green, with the scenario and its Gherkin steps intact in the archive, and it needed
no kernel change. Making `test:gate` a second containerised runner would be a second way to one verdict,
which is the shape si#8 already cost this repository. It is also the answer for a suite that is Java or
.NET: `results_from:` has been how a non-pytest runner contributes since si#133.

What the host route owed its user was an honest refusal, and it gave none. **Two refusals are new**, both
from that run. A host with no `python3` is now told so by name, *before* the half-built venv it might
have reused is wiped, and the message names the container route rather than only `apt install
python3-venv`, because "install python3" is the wrong advice on the machine si#199 is about. And a
suite's dependency install that FAILS no longer hands back a venv without the suite's tools in it: with
a bad pin in a product's own `requirements.txt` the rc was dropped, `pip`'s reason went nowhere, pytest
was started out of that venv anyway, and the gate recorded `unit: failed (rc 1) - the suite ran and
reported failures`. The suite never ran, and the record named the product for the kernel's own silence.

**The one key that decides what a suite container can reach is now documented.** si#197 measured a false
verdict in it: an acceptance container started with no `network:` did not fail to connect - the service
name resolved through the host's upstream resolver to 185.199.109.153 (GitHub Pages), which answered
404, so the scenario reported a defect in a product it had never touched. A 404 made it a false red; a
**200 would have made it a false green**. `run_toolchain`'s docstring claimed a manifest cannot supply
`network:`; it always could, measured on a scaffolded product - pinned, `ip -o link` inside the container
lists 1 interface, left out, 2 - and the parameter rendered as a real `--network` option with no help
text at all. It carries help now, and the python profile's `unit` and `analyse` pin `none`, which si#121
had already measured green. `deps` keeps its network, because it is the one command that has to reach an
index. It is **not** made mandatory: `build compile` wants no statement about networking, and a refusal
there would fail `rules.md`'s own question.

**`test:typecheck-python` does not move into a container either, and it is the one that looked hardest.**
It was already off the host: the gate runs `sys.executable`, an absolute path to the interpreter the
kernel is running in, and runs mypy as a *module* of it, so nothing is looked up on PATH. It therefore
travels with the kernel - the day the launcher gets si#199's second route, this command is inside that
container, reading exactly the installed set the kernel runs against, which is the property
`tasks/typecheck.py` argues for. What a container of its own would have cost, measured on a real product
(this kernel, 87 source files) rather than estimated, because si#163's 3.4 seconds is the gate's own
runtime and not the number this turns on:

```text
mypy 1.18.2 + types-PyYAML into the bind mount            55 MB
   plus the product's own dependencies (-e .[typecheck])  108 MB, 9.0s
python -m mypy --config-file mypy.ini after that          3.7s, Success: no issues found in 87 source files
the same verdict from the host gate                       0.39s warm, 4.7s cold
```

and the editable install needed `SETUPTOOLS_SCM_PRETEND_VERSION` to run at all, because the mount is a
git worktree whose `.git` is a file pointing outside it.

**A missing installed set is refused now rather than reported as findings**, which was si#203's other
open question. The module already drew that line once, for a missing checker, and had not drawn it for
the missing *dependencies*, which is the same class one level in. Measured in that container with the
product's dependencies absent: **rc 1, 20 errors, 20 of 20 import resolution, not one about the
product** - si#121's five-of-five on a scaffold, at kernel scale. With one deliberate `return 42` added:
rc 1, 28 errors, 27 import resolution and 1 real. A reader holding only the exit code cannot tell those
from a clean tree with one type error, and `1` is what a CI step reads. So the run is classified: all
import faults is a setup refusal naming the modules and the interpreter, findings alone is the ordinary
red, and both prints the findings *and* says that the silence around everything the missing modules
touch was never a verdict. `--show-error-codes` is on the argv rather than left to the config, because a
product writing `hide_error_codes = True` would otherwise switch the classification off - measured
against mypy 1.18.2, the flag on the line wins.

**What a product has to do.** Nothing, unless one of the two new refusals is describing it. A product
whose `test typecheck-python` starts refusing was never checking the code it thought it was: install the
product's dependencies into the interpreter the gate runs in, or point it at the one that has them with
`with: { python: ... }`. A product that re-runs `support toolchain python` gets `network: none` on the
two commands that were already measured not to need one; a scaffolded manifest that is already in a tree
is untouched, because a profile is written once and then owned by the product.


### A document of every acceptance test, generated (si#204)

si#197's primary ask, split out: **a document listing all acceptance tests, so somebody can bring
evidence of what exactly is verified.** It is `docs:acceptance`, a fourth `docs:` coordinate, and it is
`docs:reference` one level over - the reference reads the ASSEMBLED command line and lists what can be
TYPED, this reads the product's own `.feature` files and lists what is VERIFIED. Same split inside the
module, same Hugo front matter, same do-not-edit banner, same `validate_relative_dir` on the output. The
ticket asked whether the two are nearly the same before anything was designed; they are, so nothing new
was invented for the second one. Simplon generates its own at `with-what/acceptance.md`, from
`tests/acceptance/`.

**The format was measured, not chosen, and the measurement corrected it twice.** si#204 says the format
is what si#205 will be built against, so pytest 9.1.1, pytest-bdd 8.1.0 and allure-pytest-bdd 2.16.0 were
driven over real feature files and the Allure results read back. Three of the five findings decide the
page:

- a scenario's address is `<feature file>:<scenario>`, which is the archive's own `fullName` - so a
  person's verdict (si#205) and a run's result join on one key rather than on a resemblance;
- **the feature file in that address is NOT its path in the repository.**
  `pytest_bdd.parser.FeatureParser` sets `rel_filename = basename(basedir) + "/" + filename`, so
  `tests/acceptance/one-verdict.feature` is `acceptance/one-verdict.feature` to the runner. The first
  version of the module had it root-relative and the second run of the measurement killed that. The page
  prints both spellings, because an address that is not a repository path has to say where the file is
  somewhere;
- **a Scenario Outline is one result per Examples row, with the placeholders substituted in the title.**
  A page listing the outline once would carry an address matching nothing that ever ran, so the page
  expands them. Background steps are prepended to every scenario's walk for the matching reason: the
  archive carries them that way, and a person who performed them once per scenario must produce evidence
  at the same granularity.

The reader is a keyword scan of the constructs pytest-bdd 8 executes, and **no Gherkin dependency was
added**. The reason is agreement rather than thrift: `gherkin-official` parses a grammar WIDER than
pytest-bdd executes, so the kernel would have had the deeper answer and every construct in the gap would
have reached the page and never run. What it cannot honour it refuses - a `Rule:`, a non-English
`# language:` header - and twenty refusals in all, each one because it would otherwise produce a
document describing something no run executes. Two came from driving the artefact rather than from
reasoning about it, and eight more from review. The first real feature file carried an outline whose
title held no placeholder, and the page came out with three rows on one identical address - that is
pytest-bdd's own naming, the archive collides the same way, so refusing here is the only place it is
visible at all. And a tag line above a `Background:` landed on the scenario after it, which is a label
and a selection criterion arriving on a scenario the runner never gave it to.

**The review found one that was not a wrong page but a wrong directory.** `source:` was never checked for
shape, and `root / source` DISCARDS root when source is absolute - so `/etc` or `../..` read feature
files from outside the product and baked them into a published page with no error at all. It goes
through the same `validate_relative_dir` `output` uses now. si#183's asymmetry is about whether the
kernel supplies a DEFAULT for a key; it was never about whether the value a manifest wrote has to be a
path under the product. Driven against a real run of this repository's
own nine scenarios, the reader reproduces all nine addresses and all nine step lists **byte for byte**,
and that transcript is pinned in the suite as a second source rather than trusted.

**The page carries the steps, not only the scenario names**, because a customer reads it to decide
whether their functionality is covered and a title is the author's summary of its own body. It also
states, in generated prose, the one requirement PR #198 found: the archive carries a step at all only
when the product's suite requirements name **`allure-pytest-bdd`**. With plain `allure-pytest` a result
has the mangled pytest function name and `steps: []`, so without the plugin there is no per-step evidence
on the automatic side either and si#205's manual mode has nothing to be comparable with.

**Where the scenarios live is si#183's asymmetry, unchanged.** `source` defaults to `tests/acceptance`
because it is only ever read; `output` gets no default because it is written. The one thing si#183 could
measure and this cannot is the value: it had three consumer manifests declaring a `site:` section, and
here the population is zero, so the default is a convention offered to the first product rather than
consumer agreement.

**What the page does not claim, and this is a real limit rather than a caveat.** It says what the
scenarios ARE, and it says so on its own face. Simplon's nine scenarios have no step definitions in this
release, so nothing in simplon's own gate executes them - the automatic half is a product's choice
(pytest-bdd in its suite requirements, PR #198) and simplon has not made it yet. The page is honest about
that because it never claims a verdict; the verdicts are si#205's and the archive's.

**Products need do nothing.** The coordinate is offered, not placed. A product that wants the page
declares one command, pins `output`, and writes `.feature` files.

### A person walks the acceptance scenarios, and refusing costs one key (si#205)

`test:walk` is the manual half of an acceptance test: somebody sits with the customer, the Textual runner
puts each Given / When / Then in front of them one at a time, and they answer it before seeing the next.
One source and two modes - the scenarios are the same `.feature` files `docs:acceptance` documents and a
product's pytest-bdd suite executes, and what a caller chooses by typing `test walk` instead of `test
suite` is who answers, never which scenarios exist. Both address a scenario as `<feature
file>:<scenario>`, si#204's measured format, so a person's verdict and an Allure result join on one key.

**A Gherkin scenario really is a `Pipeline` whose steps take their outcome from a person, and one part of
that mapping is load-bearing rather than convenient.** The tree, the status bar, the run transcript, the
failure report and the exit code all come for free, which is the easy half. The half that decides it is
`stop_on_failure` per SCENARIO: pytest-bdd stops a scenario at its first failing step and runs the next
scenario anyway, and `steps.abort_after` scopes a failure to the outermost ancestor whose flag is true -
so a plan whose scenario nodes carry the flag reproduces that rule with nothing written to enforce it. A
flat list would have had to choose between skipping everything after a refusal and asking a person a
question whose precondition has just been denied, and either is a manual mode answering a different
question than the automatic one. What the mapping costs is stated too: a `PlanNode` carries a
`CommandSpec`, so the walk builds specs no manifest ever wrote.

**A step nobody reached is a third state, and it turned out to be two.** A refused step makes the rest of
ITS scenario `SKIPPED` and the walk goes on to the next one; a walk the person stopped leaves everything
after it `PENDING`. `overall_rc` is 0 only when every step is OK, so neither reads as green, and the
transcript already prints the two differently. Nothing was added for either.

**Refusing costs exactly what accepting costs**, and that is an arrangement rather than a claim: `a` and
`r`, one unmodified key each, no default and no confirmation on either, and both at the FRONT of the
footer so a narrow terminal drops the navigation keys before it drops these two. A prompt whose yes is
Enter collects signatures.

**The record is the run transcript**, not a fourth artefact. si#148's header already carries when, where
and si#125's provenance line; a walk appends who answered (claimed, not verified), the product version
and revision it was answered against, the digest of the scenarios, the selection, one line per sitting,
and every scenario that was NOT selected, by address - because a record saying "passed" when twelve of
forty were walked is a false document. The limit that comes with reusing it is that `run-transcript.log`
is one file per checkout, overwritten by the next run: a customer keeps their record by taking it away.

**Resume has a rule rather than a file, and it is the si#177 shape.** The state lives beside the
transcript in `build/logs/acceptance-walk.json`, under the `build/` a `clean` removes, so si#155's list
gains no entry. It carries a run key of six parts - the product, its `git describe` version and its
revision (taken through `tasks.image.provenance`, so the record names the product by the same string its
image carries), the source directory, the selection, and a sha256 over the QUESTIONS rather than the file
bytes. Any of them moved and the resume is REFUSED, naming which moved and both ways out; continuing
would record Monday's twelve answers as verifications of a product rebuilt on Tuesday. An unusable state
file is a different case and is treated differently: the kernel then knows nothing, warns, and asks every
question again. What the rule still misses is written down - a change that leaves a dirty tree dirty
(`--dirty` is one bit), a rebuild during one sitting, and a product whose version cannot be derived at
all, which may be walked and may never be resumed.

**Products need do nothing**, and simplon's own limit from si#204 is unchanged: its nine scenarios still
have no step definitions, so `test suite` executes none of them and this release cannot compare the two
modes by running both inside this repository. The comparison in the pull request was driven against a
throwaway suite of step definitions pointed at these very files, which is the same way si#204 measured
the format.

### A refused step becomes a bug ticket (si#206)

A customer's no was a line in a run transcript that the next command in the same tree overwrites. It is
now also a ticket on the product's tracker, carrying the step they refused, their reason in their words,
the product version and revision it was refused against, the scenario address and the selection, who
said it and when.

**Manual mode only, and that is a decision rather than a first slice.** The symmetrical feature - the
automatic gate filing a ticket per red scenario - turns one broken build into forty tickets and a flaky
scenario into a new one every night, which is how a tracker stops being read. Nothing in the new module
is reachable from `test suite`; `test walk` is its only caller and it runs after a person has said no.

**One ticket per scenario per version, and the lookup has two levels because one is not enough.** The
identity is a sha256 over exactly the product, the `git describe` version and the scenario address,
written into the ticket body as `simplon-walk-id: <digest>`, and the tracker is searched for it before
anything is created. That search alone is not the whole lookup, and the reason is a number: GitHub's
issue search is an index rather than a read of the table, and an issue created here on 2026-09-12 was
invisible to a search for its own digest for the first four one-second polls and appeared at 5.97 s. One
sample and short, but not zero and not bounded. So the walk state keeps what it opened and is consulted
first - immediately consistent, local, no request - and the search is the level that survives a `clean`,
a second checkout or a colleague's machine. What the search returns is verified here as well: an issue is only
"already open" when its body really carries the marker line, because a fuzzy hit accepted as a duplicate
would file a customer's refusal against somebody else's bug and report success.

**A tracker that cannot be reached costs a ticket and never a refusal.** The order in `test walk` is the
requirement rather than a promise about it: the verdicts are written to the state before anybody is asked
to type a word, the words are written before the network is touched, and only then is the tracker tried.
A wrong token, an unreachable host, a missing `gh`, an answer that is not JSON or a `title:` the product
mis-spelled all come back as a `problem` with no url - the run says which refusal has no ticket and why,
in the record and on the terminal, and the next sitting picks up exactly what is missing. A lookup that
FAILED is also not a lookup that found nothing: nothing is created after one, because treating "I could
not ask" as "there is none" is how a broken token opens a duplicate every run.

**The kernel does not know which tracker a product uses.** The destination, the labels and the wording
arrive through a `tracker:` section, the way `releases:` and `claude:` do; `title:` is a format string
over the refusal's own fields and has no kernel fallback, because a kernel-invented title is the kernel
wording somebody else's bug. What is NOT general is the backend: `github` is the one kind implemented,
`kind:` is refused for anything else naming what exists, and `tracker.KINDS` is the named seam - a second
tracker is two functions in that mapping and no change at any call site.

**Where the reason is asked, and the principle it collided with.** si#205 decided that refusing must cost
exactly what accepting costs: one key, no default, no confirmation. A text field opening on `r` and not
on `a` breaks that, so the words are collected after the walk instead, once, for every refusal at a time
when the Textual app is down. The collision is recorded rather than bent around: what is lost is
immediacy, and what is kept is the property the manual mode exists for. A person who is asked and says
nothing is recorded as having said nothing, so the next sitting does not ask again, and the ticket says
"no reason was given" rather than leaving a blank that reads as no comment.

**The walk state format is 2.** It gained `reasons` and `tickets`, and the version moved rather than the
two keys being read as optional: two documents with one version number, differing in what they can carry,
is the ambiguity a version exists to remove. An interrupted walk started on format 1 starts again with a
warning naming the format, and the population of those is zero - si#205 and si#206 both landed before
either was released.

**Products need do nothing.** A product that declares no `tracker:` section walks exactly as before; a
walk with a refusal in it then says by name that there is nowhere to file it, in the record and on the
terminal, rather than passing over it.

### The plan for the open tickets, as a document (si#207)

A merge that ships no code and is named here because the notes name every ticket merged into the range,
not every ticket that changed behaviour.
`docs/superpowers/plans/2026-09-12-the-open-tickets.md` orders the eleven open tickets by which files two
branches would both rewrite rather than by subject, records the decisions already taken for the acceptance
cluster, and states the rule that only one lane at a time may declare a catalogue coordinate - because
that turns nine counted guards red at once. Nothing to do.
### A locked read says what is holding it, and the retry is declined out loud (si#193)

`checksum.sha256_of` reads a file, and on Windows it can meet a byte-range lock held by something that
is not simplon. The failure is observed rather than imagined: `secure-windows-images` records
"cannot access the file because another process has locked a portion of it" in its own troubleshooting
table, against a directory under a synchronisation client holding 5 GB ISOs while it uploads them.

**The retry was asked for and is declined, and that is the decision worth reading.** The reporting
product answers the condition with `RETRY_DELAYS = (5, 10, 20, 30, 30)`, and si#177 had already left it
out as speculative. Its own maintainer then put the reason better than the refusal did: the tuple has no
comment, no reference and nothing deriving it, in a codebase where 450 MB is decimal because a channel
rejects at 500 decimal. Ninety-five seconds over six attempts is a guess that has not failed yet, which
is not a measurement, and **nobody has timed how long a sync client actually holds a byte range on a
file that size**. Adopting it would have put the one unjustified number of that codebase into a kernel
where every other number carries its reason, inside a wait a caller cannot see, shorten or interrupt.

What is adopted instead needs no measurement to be worth having. `simplon.filelock` recognises the two
Windows error numbers that mean "another process is holding this file" and turns them into a sentence
naming the likely holder class, the directory to exclude, and the fact that no retry is coming. It is
keyed on `OSError.winerror`, never on `errno`: Windows reports both holds as `EACCES` and so does an
ordinary POSIX permission denial, so an errno-keyed version would tell somebody with a missing `r` bit
to go hunting a sync client. Off Windows the module is inert by construction.

One rule, two spellings, because the two call sites had already promised different things.
`checksum.sha256_of` raises `filelock.FileLockedError`, which subclasses `OSError` so that its standing
promise to raise what `stat` and `open` raise is narrowed rather than replaced. `fetch.download` raises
`DownloadError` and nothing else on purpose, so it grows no second class to catch and appends the same
sentence behind the URL and the operating system's own wording. si#155's `.simplon-toolchain` is a
different failure (an install into a held directory, not a read of a held file) and is untouched.

**Nothing to do.** No behaviour changes on Linux, and a product catching `OSError` around either call
keeps catching what it caught, with `errno`, `strerror` and `filename` still on it. Keeping those was a
review correction and it needed a second one: `OSError.__str__` does not print its argument, it rebuilds
its text out of exactly those three fields the moment they are set, so carrying them over printed
`[Errno 13] Permission denied` back over the explanation. `FileLockedError` therefore keeps the fields
and takes its text from the argument.

The proof is split and the split is stated, because this repository has no Windows runner and si#161
set the precedent for constructing the condition instead of acquiring the platform. Real: a byte-range
lock held by a second process here makes a conflicting request fail with `BlockingIOError`, errno 11
`EAGAIN`, measured - and two descriptors inside one process do not conflict at all, because POSIX record
locks are owned by the process. Constructed: that the failing operation is the READ and that it carries
`winerror`, neither of which Linux can produce. Two facts came out of building it that no design would
have supplied: a blocking `lockf` on a held range waits rather than fails, so the probe has to be
`LOCK_NB` or it passes for the wrong reason after thirty seconds; and `fetch.download` calls `_staging`
OUTSIDE its own `try`, so an `OSError` from `mkstemp` or from the destination `mkdir` escapes past a
docstring promising `DownloadError` and only `DownloadError`. That last one is reported, not patched -
it is a pre-existing gap on a path no hold in this ticket reaches.

### The last German word on the site (si#213)

si#195 removed a German aphorism and reported the site English-only. It was not: `how/manifest.md` and
`how/releasing.md` both carried the same German noun in the same italicised sentence about what a
GitHub merge subject states. The sweep that missed it looked for umlauts and for German function words, and this word
has neither - a measurement that answered honestly about what it asked and was asked the wrong question.
It reads *act of merging* now, in both places.

**The claim is what was withdrawn, and no check replaces it.** The choice was a dictionary to lint the
prose against, or an end to saying the sweep is exhaustive; the second is cheaper and more honest, and it
is the one taken. A dictionary would be a second source that needs bumping and it would still not close
the class - the first loanword or proper noun it does not carry is another one of these. So si#195's note now
says which two patterns were swept for instead of what the site is, and neither release ever committed a
sweep: both were measured by hand, once, and only the prose carried the claim. That is the honest shape -
a narrow check that says what it checked beats a broad one that is green for the wrong reason.

**Nothing to do.**

### simplon builds a container image of itself (si#200)

`build:image` and `release:image` have been in the catalogue since #31, declared and never placed here,
so the kernel that ships them built no image of its own. It does now: `./simplon.sh build image` builds
the wheel inside a `python:3.12-slim` layer and installs it, and `./simplon.sh release image` pushes that
image and reads the tag back out of the registry. ci.yml builds it on every push, which is what keeps a
Dockerfile nobody publishes weekly from rotting.

**What is in the image is the kernel and nothing of any product.** si#121 measured why no prebuilt image
can carry a product's wheels, so the product's tree arrives as a bind mount at `/src` instead. si#201's
launcher route inherits that boundary.

**The registry is Docker Hub, and the GitHub credential does not go there.**
`githubpackages.is_github_packages` was not widened - its docstring records a token that leaked into a
repository's history. The credential for any other registry is the one `docker login <host>` already
stored, the kernel reads no secret of its own for it, and a push with none is now REFUSED by name
instead of attempted and answered by docker's `denied: requested access to the resource is denied`,
which names no host, no account and no fix.

**The tag is the version, from one source.** The task already derived `VERSION` from the product's own
`git describe` and stamped it into the image; the tag now defaults to that same string rather than to a
constant somebody keeps in the manifest. A declared `tag:` or a `--tag` still wins, and a product that
states `build_args: { VERSION: ... }` moves the tag with it.

**Nothing to do**, unless you publish a container image: a `tag:` you already declare is unaffected, and
a push to a non-GitHub registry now needs the `docker login` it always silently needed.

### The launcher runs the kernel in a container, as a second route (si#201)

`./myctl.sh` has always been Python in a virtual environment on the host. It can now be a container
instead, running the image si#200 builds with your checkout bind-mounted at `/src`. `DELIVERY_ROUTE`
chooses - `venv`, `container`, or the default `auto`, which prefers the venv when there is a `python3`
and reaches for the image when there is not. **A host with a python behaves exactly as it did.**

**The hard problem is that a container which runs containers passes HOST paths, and getting it wrong is
silent.** Measured, with the tree at `/src` inside a kernel container holding the docker socket:
`docker run -v /src:/x busybox ls -la /x` printed an EMPTY directory, exited 0, and left a root-owned
`/src` behind on the host - the daemon resolved the path against the host, did not find it, and created
it. A gate handed an empty tree finds nothing to fail on. So every bind mount in the kernel now goes
through `simplon.hostpath.translate`, which rewrites a path onto the host side of the mount and REFUSES
by name when it cannot. The launcher declares the mount as the pair it is, `DELIVERY_HOST_ROOT` and
`DELIVERY_MOUNT_ROOT`; two other ways to obtain it were driven and rejected, and
`src/simplon/hostpath.py` carries both numbers - `docker inspect $(hostname)` works in 11 ms and dies
with `Error: No such object` under `--hostname`, and `/proc/self/mountinfo` reports a path relative to
the source filesystem's root, so a tree under a tmpfs `/tmp` comes back missing its `/tmp`.

**The docker client is in the image now, and oras still is not.** si#200 left both out and asked si#201
to decide with a number. Fetching the client at runtime costs 84 MB and 15.0 s on first use and needs
egress from a container whose premise is "bash and docker", and leaving it out changed four verdicts in
simplon's own gate; in the layer it is 44 MB. oras is reached by two release paths, provisions itself,
and changed no verdict, so it stays out. The version installed is
`simplon.docker.DOCKER_CLI_VERSION` and a test holds the two together.

**The two routes were diffed rather than asserted.** A scaffolded product's `build compile` - a real
`toolchain:run` that starts a sibling container and writes into the mount - came out identical on both
routes: same verdict, exit code 0, the artefact byte-for-byte, and the log identical bar the first run's
image pull. simplon's own `test all` produced the same file set on disk and identical
`test.typecheck-python` and `test.release-notes` logs.

**Three differences that are real, and are exceptions rather than footnotes.** On the container route
the kernel names paths as the container sees them, so a log line reads `/src/build/logs/...`. A linked
git worktree is refused up front: its `.git` is a file naming a directory outside the mount, so git in
the container sees no repository. And a container can hand a sibling only a path the daemon can resolve,
so a task that mounts something OUTSIDE your tree refuses - in simplon's own suite that is twelve e2e
tests which scaffold a fixture into pytest's temp directory and really run its gate.

**`simplon.cmd` got the same route and it is UNDRIVEN.** There is no Windows on the machine this was
built on. What is held is that both launchers declare the same contract - the same parameters, mount
destinations and environment names - and two places where the batch file cannot be the shell file are
named where they occur: cmd.exe cannot answer whether it has a terminal, so `-t` is opt-in through
`DELIVERY_CONTAINER_TTY` rather than guessed, and a wrong guess would break every piped run.

**The Windows container route reaches the CLI and refuses at the first task that mounts anything**, and
that is the largest of the undriven gaps rather than a bug to be found later. `%LAUNCH_ROOT%` is
`C:\...`, and the kernel reading it back runs in a LINUX container where nothing joins a drive-letter
path onto a POSIX one, so `simplon.hostpath` refuses it by name and says to use `DELIVERY_ROUTE=venv`.
What Docker Desktop's daemon accepts as a `-v` source from inside a Linux container is a measurement, and
there was no Windows to take it on.

**Nothing to do.** The container route is opt-in, and a checkout whose `deploy/image/image.pin` carries
no reference - which is every checkout today, because no simplon image is published yet - is told it has
no container route and that the venv one works.

### A malformed manifest refuses in a sentence (si#222)

Two stray characters pasted in front of the opening `#` of a product's `swi.yaml` made line 1 stop being a
comment, so the `product:` key further down started a second document. Every command in that product
disappeared at once, and what the CLI printed was eight frames of kernel internals ending in
`yaml.safe_load` - naming neither the file, nor the line, nor what was wrong, all three of which the
exception it swallowed was carrying. The report that arrived was that a section somebody had added "does
not appear"; the file had not parsed for some time and nothing said so.

`manifest.load` catches `yaml.YAMLError` now and refuses the way the rest of the kernel does:

```
/repo/swi.yaml is not valid YAML:
  line 3, column 8: mapping values are not allowed here
```

The parser's mark is reprinted rather than passed through, because `safe_load` is handed a STRING and its
`problem_mark.name` is `<unicode string>`, never the file. So `load` takes the file's name as an optional
argument - a name to print, not a path it reads - and `ProductContext.manifest`, the caller that has it,
passes it. A `load` driven directly with text still refuses with the mark, under the name "the manifest".
The one parse failure that carries no mark at all - a control character in the file, which is what half a
written file leaves behind - prints its position for the same reason: its own `str()` would have put the
placeholder back into the sentence, naming the file twice and agreeing with itself only once.

This is why it was worth catching specifically and not as one refusal among many: a section that is wrong
takes out one command, a document that does not parse takes out all of them, so there is no `--help` left
to consult and no `doctor` to run. It is counted in the census as diagnosis - a document that does not
parse could not have meant anything else - which is the 130th load-time refusal.

**Nothing to do.** The manifests that loaded before load unchanged.

### The container route can file a ticket now, and the rule that let it slip (si#225)

si#206 gave the manual walk a tracker: a customer's refusal becomes a bug ticket carrying the step, their
words and the version. On the container route it opened none. The kernel's own image carried `git` and
the docker client and no `gh`, so a walk driven there asked its questions, recorded its refusals, printed
that no ticket was filed, and stopped - one of the "differences between two routes that are required to
be indistinguishable" si#200's own Dockerfile counts.

**What is worth reading here is why no gate found it.** si#200 decided what goes into that image by
measuring which verdicts a tool changes: the docker client moved four in a `test all` driven through both
routes, so it went in; oras moved none, so it stayed out. That rule is right. Its method could not see
this case, because `simplon.tracker` is unreachable from `test suite` BY DESIGN - the walk runs after a
person has said no, and si#206 refused to build an automatic gate that files tickets. So the difference
was real from the day si#206 landed and invisible to every run of everything.

`gh` is in the image now, pinned to one exact release. It costs 42,188,962 bytes - 40 MiB in the layer,
14 MiB on the wire - which is slightly LESS than the docker client already sitting beside it.

**Baking the tool in was only half of it, and the other half was quieter.** `simplon.sh` forwards a named
list of variables across the container boundary and nothing else, and `GH_TOKEN` was not on it. That is
the variable `gh` reads first, and the one si#206's own broken-tracker proof was driven with; only its
fallback `GITHUB_TOKEN` was crossing. With the tool present and the token stopping at the boundary, a
walk would have found `gh` on PATH, skipped the sentence that says the tool is missing, and failed with a
401 - a worse message than the one si#206 wrote, reached by fixing half the problem.

**Nothing asserted that list before.** It does now, in both places it is written: the kernel's own
launcher and the template every scaffolded product is rendered from, held against each other so a
capability cannot be kept for simplon and withheld from its products. The prose above the list is held
against the list too - it had already drifted one name short of the code beneath it.

**And a third layer under the second, which is the one worth reading twice.** With the tool in the image
and the variable crossing, the route still files nothing on a developer's machine - because `gh` on a
developer's machine is not authenticated by a variable at all. `gh auth login` writes a token to
`~/.config/gh/hosts.yml`, the launcher mounts `~/.gitconfig` and nothing else of a home directory, and
that is deliberate: forwarding a whole home is how a credential reaches a place nobody looked. So CI,
where the token IS a variable, works; a person running the same command does not.

That one is **not** repaired by mounting the credential, and the decision is written down rather than
implied. What the container route says instead is the one thing `gh` cannot know. Measured inside the
image, `gh` already answers `To get started with GitHub CLI, please run: gh auth login` and
`Alternatively, populate the GH_TOKEN environment variable...` - it names the variable itself, so the
kernel repeats none of it. What it adds is where: `gh auth login` cannot help on this route, because the
host's login stays on the host and a container's home is discarded when the command ends. A wrong token
gets no such sentence - a 401 means GH_TOKEN crossed and was refused, and telling that reader to export
it is advice for a problem they do not have.

The sentence printed when `gh` is missing no longer explains the container route, and the removal is the
change rather than an omission: it was true when si#206 wrote it and si#225 made it false, and a message
that names a cause which no longer exists sends its reader to look in the wrong place.

**Driven through the container route, four sittings over one scenario**, which is the proof si#206 was
held to and could not produce for this route. With no credential: the walk asked, recorded the refusal and
the reason, and said why no ticket was filed. With `GH_TOKEN`: it opened
[#227](https://github.com/marcozwyssig/simplon/issues/227) without asking a single question again, because
the answer and the words were already in the record. After a `clean` with the walk state deleted and the
same step refused again: the search found that ticket from inside the container and opened nothing. And
read back off the tracker with `gh api` - the product's title, the product's label, and the kernel's
evidence block naming the step, the version, the revision, who, when and what they said.
`gh issue list --search "<digest> in:body" --state all` returns exactly one issue after all of it. #227 is
closed as "not planned" with a comment saying it was this proof; it is still readable.

**Nothing to do.** A product that declares no `tracker:` section is unaffected, and one that does now
files from either route.

### Which runner runs, and who chose it (si#223)

A pipeline is either drawn in the Textual runner or walked headless, and until now that choice was made
by two accidents and announced by nobody. `--no-tui` is the first way to ask for headless ON PURPOSE:
`./myctl.sh --no-tui build all` sets `SIMPLON_NO_TUI=1`, which is what a workflow can export directly and
what actually travels, because every planned step is a `./myctl.sh <leaf>` subprocess that no flag on the
parent process reaches. Redirection still works exactly as before; it is no longer the only lever.

**The ticket asked for a `kind:` in the manifest and it was declined, which is the larger half of this
entry.** The proposal was to declare each task a RunTask or a StatusTask - one that acts, one that prints
- and a consumer really does make that distinction by hand, in a docstring, for fourteen of its sixteen
commands. What the measurement found is that the distinction is decided by a branch INSIDE a body: one
task is placed twice, once with `check: false` and once with `check: true`, and the body reports or acts
on that pin. A `kind:` beside it could never be a second source anything could CHECK - only one that can
drift, with `kind: status` and `check: false` declaring a command that reports and building one that
acts. So `steps.dispatch` is the declaration instead: a command that reaches it renders, and one that
never reaches it cannot render a pipeline it never built. The cost is stated rather than hidden - nothing
can now say BEFORE a run which commands render, so no help listing or generated document can carry it.

**A broken Textual install was indistinguishable from a CI run.** The construction of the app sat behind
`except Exception`, so a half-installed Textual, an incompatible version and a fault in the app itself all
arrived where a deliberate redirection arrives: a clean-looking headless run, exit code and all. That is
this repository's recurring defect - an outcome that cannot tell "chosen" from "failed" - sitting in the
mechanism that chooses. Only `ImportError` falls back now, because a kernel without Textual installed is
a configuration that is supported on purpose; everything else is a break and reads as one.

**Nothing to do**, unless a product was relying on a broken Textual quietly becoming a headless run - in
which case it now says so, and `SIMPLON_NO_TUI=1` is the way to ask for what it was getting by accident.

### The runner gets a chapter, and `tracker:` stops being one table row (si#230)

Before this release was cut, the site was measured against the sixteen tickets in it: for each one, does
a reader who wants to USE the thing find it on a page, or only here? Most held. Two did not.

**There is a chapter about running a command now** — [Running a
command](../../how/running/). The tree on the left, the step's output on the right, the seven keys, where
the per-step logs and the run transcript land, what the flat log looks like and how to ask for it. The
most visible surface of the whole tool had been described in `tui.py`'s module head and in five sections
of this page, which is the one place somebody looking for it does not read.

That chapter is also where `--no-tui` now lives. si#223 had put it in the manifest chapter, inside the
paragraph about `parallel:`, because the neighbouring `SIMPLON_MAX_PARALLEL` happened to be explained
there — and nobody asking how to turn the UI off opens the manifest chapter.

**`tracker:` has a section of its own** beside `releases:` and `workflows:`, with the example, the nine
placeholders `title:` may use, why a second walk does not open a second ticket, and what happens when the
section is missing. It had been one cell in a table since si#206 shipped it.

One claim was withdrawn while measuring, and it is the more useful half. The container route (si#200,
si#201) read as a third gap and is not one: **Two routes, one CLI** explains it properly, it is simply
filed under the scaffold chapter where somebody asking "how do I run this on a host with no python" will
not look. A cross-reference was the whole fix. Absence from a *search* and absence from the *site* are
two different findings, and only one of them is worth a chapter.

**Nothing to do.** No command, flag or manifest key changed.

## 0.12.0

**The site shows before it argues.** Every page on this site opened with the reasoning for the thing
before the thing, and the maintainer's verdict after reading it end to end was that it is still too
complicated. The house style that produces that - prose argues WHY - is right in the source and wrong on
a web page, so the correction is a move rather than a deletion: **no measured fact, quoted refusal or
worked example was dropped**, each one gained a short form above it or a page of its own behind a link.

### One accessor for a data section, and it refuses nothing (si#175)

`ProductContext.manifest_data()` handed back the raw mapping and stopped there, so every reader wrote
the same two lines - fetch the section, check it is a mapping - and `tasks/buildfiles.py` wrote eighteen,
because `build: targets:` is a PATH and a typo in the outer key must not report the inner one as absent.
`simplon.context.section(document, *path)` is that walk, once. It stops at the first step that is not a
mapping and names THAT step, hands back what the step held so a reader can print `got {type}`, and treats
a section declared and empty as found rather than missing.

**It raises nothing, and that is the design rather than an omission.** The nine kernel readers that fetch
a data section say nine different things when it is not there - `labegress` names the manifest and the
section, `nexusproxy` says "missing or is not a mapping", `tasks/site.py` adds what to declare instead,
`tasks/buildfiles.py` says nothing at all because an absent `build:` is the normal case - and si#159
measured that fourteen of the sixteen sections the kernel reads already refuse by name and quote the key.
An accessor that raised would have replaced fourteen good sentences with one. So it answers and the
caller refuses: all nine migrated readers produce a **byte-identical** message, driven with the section
missing and with it malformed, before and after.

Keeping the raise at the reader is also what keeps the refusal census honest. `tests/test_refusal_census.py`
counts raise sites and pins each message against the literal at its own site; moving nine raises into one
parameterised one would have collapsed nine entries into a message the census could no longer read. The
population is unchanged at 129 refusals across ten modules, and the census learned the accessor's name so
that a module reading a section through it is still counted as an inline reader rather than as one covered
by a callee - the second half of si#61's property, held by a new test.

What si#175 asked for and did not get is `required=`. The two sites that would use it disagree about what
present means: `labegress` treats a key that is blank after `str(...).strip()` as absent, `labinstance`
treats `max_id_len: 0` as present and refuses it a line later with a sentence about integers. One keyword
would have served three of one site's six lines and two of the other's three. That is si#159's own
finding at a smaller size - the measured population does not support the rule.

Products need do nothing. `manifest_data()` is unchanged, and the accessor is additive. One narrow
behaviour note: the shared shape test is `isinstance(..., Mapping)`, where `labegress`, `labinstance`
and `tasks/releasenotes.py` used to ask for a `dict`, so a `MappingProxyType` or an `OrderedDict` at
one of those three section keys is now accepted. `manifest_data()` is `yaml.safe_load`, which yields
plain dicts and nothing else, so the production path cannot reach that difference at all - only a test
that hands a reader a literal can.

### A step that blew up now has a verdict, and a body that prints can be a step (si#182, si#174)

**A step whose `action` or `stream` raised stayed `RUNNING` for ever.** `Step.run` set the rc, the
`ended_at` and the state only after the call returned, so a raise skipped all three - and then took the
run with it. Headless, the exception left `run_plan` and `run_headless`, so the run died before the
retraced tree, before `failure_report` and before the transcript. Losing that file is the worst of it:
the artefact exists precisely for the run that went wrong, and it was written for every run except that
one. Under the TUI, Textual catches a worker's exception, so `_on_done` was simply never reached and the
operator watched a row on `↻` with a timer counting upwards for ever, with nothing on the screen saying
the run had ended.

**What a raise MEANS was the decision, not where to put the `try`.** The ticket offered a reserved rc or
a sixth `StepState`, and this repository had already argued both down for the neighbouring case:
`simplon.verdict`'s module docstring rejects a widened rc, because an rc is one bit of judgement and a
private convention would have to be learned by CI, by a shell and by `simplon.cli._rc`; and it rejects a
new state, because `SKIPPED` already holds the neighbouring meaning and a crashed step was ENTERED, did
work and did not pass. FAILED is its fate. So the step is FAILED with rc 1, deliberately as red as any
other red step, and **the distinction lives in what gets written**: `Step.crash` holds the traceback,
`failure_report` says *"why `probe.crashes` crashed (it raised, so it has no exit code of its own)"*
instead of naming an exit code the step never produced, the transcript prints `crashed` where it would
print `rc 1`, and `steplog` keeps the whole traceback in a file the report names - because the report
shows ten lines and a traceback is longer, and *"the lines above are all of it"* would be a claim that
the evidence does not exist. Nothing is swallowed: the exception is recorded in five places where it
previously reached one, and `KeyboardInterrupt` and `SystemExit` still end the run, because neither is a
body blowing up. A sixth state was measured at eleven places over three files, every one of them a
chance for a product's five-state renderer to meet a state it does not map.

`run_headless` and the TUI's worker each grew a `finally`, so the tree, the report and the transcript are
written for a run that ended by raising as well - which is now Ctrl-C, `sys.exit` and a fault in a
runner's own hook. The tree print inside that `finally` is guarded, because an exception raised there
REPLACES the one already travelling: si#161 measured a `UnicodeEncodeError` on that very loop, and it
would have swapped the operator's Ctrl-C for the fault in the code reporting it.

**`steps.capturing(label, work)` turns a body that PRINTS into a step.** Measured on the installed
package first: no `redirect_stdout` and no `StringIO` anywhere in it, so a product with a few thousand
lines of command bodies ported from elsewhere - all of which report by printing - had to rewrite every
body, re-launch each as a subprocess, or go without. Completed lines reach the pane live, the accumulated
text is the Outcome, and the three ways a body reports all become an rc: it returns (0), it calls
`sys.exit(...)` (CPython's own rule, and a string message becomes a line of the step), or it raises -
which is a FAILED step and never an escaping exception, because one item blowing up must not take the
rest down. That last one is why the two tickets shipped together: the exception is left to `Step.run`,
which is now the thing that has a contract for it.

**The naive version is wrong in three ways, and si#147 made two of them likely.** `sys.stdout` is
process-global, so a per-step `contextlib.redirect_stdout` is not a per-step anything. Measured with two
threads each redirecting round three prints, 50 ms apart: five of the six lines landed in the wrong
step's writer, an unrelated thread's output was swallowed by whichever step happened to be capturing,
and - the fault that outlives the run - `redirect_stdout` restores what IT saved on entry, so
interleaved enter and exit left `sys.stdout` pointing at a finished step's buffer for the rest of the
process. So there is ONE router installed for as long as any capture is running, and it routes by
thread: two capturing branches of a fan do not see each other, an uncaptured thread keeps printing to
the terminal, and the restore happens once, from a counter under a lock. The alternative - one lock held
for the length of each capturing step - is four lines and correct, and it silently serialises a fan the
manifest declared parallel.

The third way is a hang rather than a mix-up: the headless runner's emit PRINTS, so delivering a line
with the redirect still in force feeds it back into the writer that produced it - `maximum recursion
depth exceeded` on the first line of the first step. The TUI's emit appends to a widget, so an
interactive run is fine and the fault waits for the first piped or CI run.

**Rich reaches the capture only half way, and that was measured rather than assumed** (rich 15.0.0).
`Console.file` is a property that reads `sys.stdout` at every access when no `file=` was passed, so a
console built at a product's module import does write into the step, and `Console.is_terminal` follows
the capture too. `Console._color_system` does not: it is detected once in `__init__`, and rich renders a
style whenever it is truthy, so a console built while stdout really was a terminal went on emitting
`\x1b[1;31m...` into what was about to become a step log and a run transcript - the plain-text artefact
si#144 spent its whole argument on. Captured lines therefore have their escape sequences removed;
`run_stream` still does not, and that is not an inconsistency, because there the bytes come from a
foreign child and si#144 chose a pipe over a pty so they would not be created in the first place. The
one console the capture cannot reach at all is `Console(file=sys.stdout)`, which pins the handle at
construction - a product-side spelling to avoid, and worth naming because the failure is silent: the
step's pane is simply empty.

Half lines are handed over on a `flush()` and at the end of the step, including on the path where the
body raised, so the line it fell over on sits beside the traceback. The break rule is
`simplon.run.LINE_BREAK` - published from `run_stream`'s own `_BREAK`, so an in-process step and a
subprocess step disagree about nothing.

**Sixteen deliberate breakages** confirmed each property can actually go red. One survived: the test
that a captured thread is told it is not a terminal passed with `isatty` deleted outright, because
pytest's own stdout already answers False. It is driven under a stream that claims to be a terminal now,
and finding that is what found the Rich colour caching above.

A review then found the same shape twice more. The half-line flush at the end of a step runs while a
raising body's exception is already travelling, so a fault in that courtesy would have become the
recorded traceback - `__context__` keeps the body's, but the ten-line tail would no longer show it. The
body's exception wins now, and a fault in the flush is dropped. And the test for two capturing steps
running side by side used a sleep to encourage the interleaving, which cannot fail falsely but can
quietly stop exercising the race at all on a fast runner; it uses a barrier, so all three branches are
provably inside their capture at once.

### A dropped download can be resumed, and `human_bytes` can be adopted (si#176, si#178)

Two changes to `simplon.fetch`, both asked for by a product that measured the kernel against its own
copy rather than reading the docs.

**`fetch.download(..., resume=True)` keeps what arrived.** A transfer that dies mid-body used to
discard the bytes, which is the right trade for the three artefacts the kernel itself fetches and the
wrong one at five gigabytes over a link that is sometimes a VPN. With `resume=True` those bytes stay in
`<dest>.part`, and the next call with the same URL and destination continues from there.

It is **opt-in**, and that is not timidity: it changes the promise si#142 made. Without it a failed
download still leaves the destination directory exactly as it found it, which is what the docker
bundle, the oras archive and `get-pip.py` all want.

A resume is also the one change that could reopen the hole si#142 closed, because appending to bytes
nobody vouched for produces a file of exactly the right length made of two different objects, and no
length check can see that. So it resumes only what it can prove:

- a sidecar beside the partial file records the URL and the object version (`ETag`, else
  `Last-Modified`) those bytes came from. No sidecar, a different URL, or no validator at all means the
  bytes are discarded before a socket is opened;
- the request carries `If-Range` beside the `Range`, so whether those bytes are still current is decided
  by the only party that can decide it;
- **anything that is not a `206` confirming the exact offset asked for truncates the partial file and
  downloads the whole object again.** That covers a server with no range support (a fresh download, in
  the same call) and the case that quietly corrupts a file: a server that ignores `Range` and sends the
  whole body with no hint that it did. A `206` whose `Content-Range` names a different offset is refused
  outright, because where those bytes belong is exactly what a resume may not guess.

A `416` (a stale partial file longer than the object) asks once more for the whole thing, so it cannot
wedge the download forever. There is no retry loop: how many attempts and how long between them is the
caller's policy, and a partial file that survives the call is what makes calling again cheap.

**`human_bytes` now writes `KB` and a thousands separator.** `kB` is the strictly correct spelling and
it changed anyway: the function exists to be the only one, three products had written their own, and the
one publishing fact sheets beside every medium it ships could not adopt this copy without every number
on them changing shape. The scale does **not** move - it stays decimal, and si#178 carries the best
argument for that: a 1024-based helper called 450'000'000 bytes `429.2 MB`, comfortably under a cap it
was in fact sitting on, and that confusion cost a publish.

One thing si#178 asks for that this cannot give: the separator reaches less far than the ticket's
examples imply. Every unit but the largest hands over at the next 1000, so `KB` and `MB` carry three
digits, and the bare-byte step stops at `999 B` - `11,240,000,000 B` is `11.2 GB` here and always was.
The separator appears in `GB`, which is where a run of 5 GB media adds up to `5,000.0 GB`.

**What to do.** If you print `fetch.human_bytes` output into logs or documents, `kB` is now `KB` and
figures at or above 1000 GB carry a comma. Nothing else changes unless you pass `resume=True`.

### The kernel can hash a file, and the cache beside it has a rule worth reading (si#177)

Every `sha256` in this package was an image digest - `docker.py`, `labhost.py`, `clabrender.py`,
`tasks/allure.py`, `tasks/site.py` all pin or compare a registry reference. None of them hashed a file.
So the first product to pin **media** by hash wrote its own, and `simplon.checksum` is that function
lifted into the kernel, with the part that actually needed deciding done differently.

```python
from simplon import checksum

digest = checksum.sha256_of(path, cache=checksum.cache_dir(root))
```

`cache=None` is a plain hash. With a cache directory the digest is written to a sidecar, because a
command whose whole job is to report what is present should not read five gigabytes to answer: driven on
a real 2 GiB image, 0.674 s to hash it against 0.075 ms to answer from the sidecar.

**A cache that can be wrong is worse than no cache**, and a checksum is the one place where being wrong
is silent - the caller gets a hex string either way. So the invalidation rule is three conditions, not
the usual two: the size is unchanged, `st_mtime_ns` is unchanged, **and** the sidecar's stat was taken at
least a second after the mtime it records. The third one is what survives a write inside the same second,
which is what a sync client, `touch -d`, `unzip` and `tar` all produce by stamping whole seconds, and
which si#86 and si#169 both were in one week. It is git's answer to its own racily-clean index entries;
it costs exactly one extra hash for a file hashed the moment it was written, and heals itself on the call
after.

It cannot see a rewrite that restores **both** size and mtime, and it says so in its own head rather than
leaving that to be found. Everything else recomputes: an unreadable sidecar, a malformed one, one written
by a version that spelled the record differently, one naming another path. Nothing trusts a record it
could not fully check, and a sidecar that cannot be written is not an error - the caller asked for a
digest and gets one.

**Where the sidecars go is part of the answer.** They live in `build/checksums/`, under the `/build/`
that is already the first anchored line of the `.gitignore` block si#155 scaffolds, so nothing is added
to the list of what the kernel writes into a product tree - a `.sha256` beside the media would have been.
`tests/test_checksum.py` asserts that through `git check-ignore` on a real scaffold rather than against
the text of the block.

**Nothing to do.** A new module on the library surface; no command, manifest key or existing signature
changes.

### A size in binary units, and a phase heading that was declined (si#192)

A consuming product on 0.11.0 measured its own console module against the kernel and found two functions
with nowhere to go. One of them is here; the other is not, and the ticket said in as many words that
"declined, and here is why" would be a good answer.

**`fetch.human_bytes_binary(n)` is the 1024-based twin.** `human_bytes` sits beside a `Content-Length`
and stays decimal for the reasons si#178 argued; what was missing is the other scale, for a size a file
manager reports. Two names rather than `human_bytes(n, binary=True)`, because a flag is read once at the
call site and never again by anyone reading the log.

```
450'000'000 bytes   human_bytes         450.0 MB
                    human_bytes_binary  429.2 MiB
```

**The unit is the half si#192 did not ask for, and it is the half that mattered.** The ticket's own
worked example renders the binary figure as `429.2 MB`, which is the exact string that cost that product
a failed publish: a true division wearing the other scale's unit, reading as comfortably under a cap it
was in fact sitting on. A distinct name keeps the pair apart where it is CALLED. Only a distinct unit
keeps them apart where the mistake was actually made, which is in a log, where the reader has one string
and no call site to consult. So the binary function writes `KiB`, `MiB`, `GiB`, and a test drives every
count in a range to assert the two functions never share a unit token once a scale applies. Below 1000
the two produce the same string, which is honest: `947 B` is the same count of the same bytes either
way. The threshold is the decimal function's first scale rather than this one's - from 1000 to 1023 the
two part company on the unit (`1.0 KB` against `1000 B`) instead of agreeing. The format otherwise mirrors `human_bytes` exactly, separator included, because a pair a reader has
to learn twice is a pair that gets misread.

**`log.step()` is declined, and the premise it rests on is not true.** The ticket asks for a phase
heading on the grounds that `==>` "belongs to the runner and a product's own body cannot reach it". It
is `log.info`. The headless runner heads every step with a plain `log.info` call, `log` is on the
library surface, and a product body calling it produces the same line the runner does. Measured under
the runner, with a real body:

```
[08:57:14] ==> probe.loginfo - the kernel's info line     <- the runner's entry line
  [08:57:14] ==> Setup                                    <- log.info, from inside the body
```

Three more measurements say why a second spelling would be worse than none.

*The word is taken twice over.* A `step` in this kernel is a `Step`: a row in the tree, an rc, a
duration, a `build/logs/<step>.log` and a line in the run transcript. And `phase` is the name of the
five delivery groups. A `log.step()` producing none of those would be named after all of them.

*si#174 moved where a body's output goes.* Since a step's body is captured into that step's pane, a
heading printed from a body no longer heads a phase of the run; it subdivides one step. Driven both
ways with the ticket's own five phases: printed inside one body they are five lines of text under a tree
with one row, one duration, one rc and one log file. Declared as five steps they are five rows, five
durations, five rcs and five log files, and the runner prints `==> Setup` for each of them anyway. A
phase in Simplon is a step, and a printed heading is a second phase structure the runner cannot see.

*si#190 discards the style.* The product's heading is `style="bold cyan"`, and captured lines have their
escape sequences stripped, so it arrives as plain text in the pane, in the step log and in the
transcript. The kernel could not offer the styled version regardless: `rich` is not a declared
dependency.

So a product that wants a heading inside a step body writes `print()` and `log.info("Setup")`, in the
kernel's own alphabet, timestamped, telling nothing apart from the runner's line except the two-space
indent that already separates every body line from its step. What a product wanting a heading for a
PHASE writes is a step. `tests/test_orchestrator_capturing.py` pins the whole entry line, clock included,
so this answer cannot quietly stop being true - the first version of that test pinned the `==>` marker
alone and stayed green against a runner rewritten to `print(f"==> {title}")`.

**What to do.** Nothing. `human_bytes_binary` is additive and no existing signature moves.

### The `why` chapter is a page, not an essay (si#186)

`why/why.md` was 3992 words and opened by announcing how it would take itself apart noun by noun. It is
now a short page carrying four claims - **Simple**, **Modular**, **Agnostic**, **Evolve** - with one
piece of evidence each rather than an adjective, plus the three things Simplon is explicitly **not** (not
a CI server, not a build system, not a framework you write against) and what it costs to run. The
noun-by-noun argument moved intact to [The design, noun by noun](../../why/the-design/), and
`test_why_chapter.py` moved with it: the same assertions over the same prose, against the file the prose
now lives in.

The old URL is unchanged, so no bookmark and no alias moved.

### The four worked cases start with what you type (si#186)

Each of `case-python`, `case-java`, `case-cpp` and `case-dotnet` now opens with **the command sequence a
reader can type**, in the order of the five verbs, with the support commands as hints beside the step
they help with. The dated evidence tables - every row labelled `run`, `derived` or `does not exist yet`
with the ticket or transcript behind it - are unchanged and sit directly below. **No row was relabelled;
moving a table is not re-verifying it.**

### `getting-started` is four commands (si#186)

The shortest path from nothing to a running command is now four numbered steps. The ignore block, the
starter manifest read line by line, shell completion and the product-name rules moved to [What `init`
wrote](../../how/what-init-wrote/), which is offered from the same section.

### The lookup chapters answer before they justify (si#186)

`with-what/rules.md` opens with the six rules in a table, one line each, linked to their own section.
`with-what/test-levels.md` opens with every key a gate takes and what it decides.
`with-what/phases.md` and `how/manifest.md` each open with a jump list for the question a reader
actually arrived with. The word counts barely move; what moves is how long it takes to find one fact.

### The site is in one language (no ticket)

`with-what/rules.md` stated the missing-tool rule twice: once as a German aphorism, once as its English
translation underneath. It was the only non-English prose on the site, measured by sweeping every page
for German function words and for umlauts. The English line stays and the German one goes, so a reader
never meets a sentence they have to skip.

**Nothing to do.**

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

What was actually missing is on `how/manifest.md` now: **the sixteen names the kernel has claimed**,
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

The tree form is documented at https://marcozwyssig.github.io/simplon/how/manifest/ - "The command
tree" for the shape, and "The flat form, and how to leave it" for this migration in particular. Nothing
here rewrites the file for you: the sections have to be edited by hand, which is also the only way your
comments survive the move.
```

The detection is unchanged: the same four shapes are still found together, and the same manifest is still
refused before any other check can report a symptom of it instead.

**Nothing to do unless you have a flat manifest**, and if you do, [The
manifest](../../how/manifest/#the-flat-form-and-how-to-leave-it) is now where the migration is
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

### Steps that do not have to wait for each other can say so (si#147)

Every step of a plan ran after the one before it. An aggregate whose dependencies are genuinely
independent - five device images, four test levels - therefore cost their sum, and the manifest had no
way to say otherwise. `parallel: true` on an aggregate is that way: its dependencies run at the same
time, and whatever follows it in its own parent's list starts when all of them are done. That is the
join, and it needs no new key - `depends_on` already means "after", and this is the one place it stops
meaning it. Measured on a four-step plan of real subprocesses: **3.67s sequential, 1.81s with the flag**,
the fan costing what its slowest member costs instead of what all three cost.

**Declared and not derived, which was the first question and it was settled by counting rather than by
preference.** A dependency graph already states what must come after what, so deriving parallelism from
it - run everything that has no edge between it - needs no new key at all and would have been the better
answer. Across the six manifests this kernel can reach, 541 pairs of planned steps have no edge between
them, and **466 of those would break if they ran together**. The reason is uniform: an aggregate's
dependencies are a LIST, and the order between siblings is stated by their position in it and nowhere
else. Simplon's own manifest says so in prose - *"Siblings execute in list order, so [reference, site] IS
the edge"* - asbundle's build chain says *"in the order listed"*, and the kernel's own idiom for chaining
two steps under the impl-XOR-`depends_on` lock produces exactly such a pair on every chained build. A
derived executor would have published a website before writing the page it publishes, and run a compiler
inside an image that did not exist yet, in four products at once. So the flag is opt-in and its default
is precisely the behaviour every existing manifest already has.

**Three decisions that come with it, each stated rather than discovered.** A step already running when a
sibling fails is left to finish: a killed subprocess exits non-zero and that number cannot be told from
the step having failed on its own, which is this project's recurring defect manufactured on purpose. The
members of one fan are never skipped for each other either - `parallel:` is the declaration that none of
them needs another, so a failure in one does not make another's work doomed - while the work after the
join is skipped by `stop_on_failure` exactly as before. And the exit code is not "the last one wins":
it was already derived from every step's final state, so two simultaneous failures are two entries in the
report and one return code.

**How many run at once is the machine's answer, not the manifest's.** A manifest travels between machines
and a container count does not: `SIMPLON_MAX_PARALLEL` sets the bound, and the default is four or the CPU
count, whichever is smaller. Four because the work in a fan is whole subprocesses that each already use
every core they can find, so the number is about how many daemons and caches are in flight rather than
about CPUs.

**Two defects a code review found, both of them the same shape as the one this feature refuses.** A fan
in which two branches raise at the same time re-raised one and dropped the other with no trace anywhere;
an exception carries one cause, so the ones that are not raised are logged. And a raise in the MIDDLE of
a fan used to swallow the output of the branches after it - the flusher stopped at the hole the crashed
step left, so a step that had run to completion and captured its output contributed nothing to the log.
The buffering that makes a fan readable would have destroyed exactly the evidence a crash needs. A fan
now flushes what it has when it ends, and names the hole rather than skipping over it. The remaining
half - a step that raises is left in `RUNNING` for ever, and the run then loses its tree, its failure
report and its transcript - is older than this change and is tracked as si#182.

**The output was the half expected to hurt, and only one of the two runners felt it.** In the TUI it
needed nothing: si#144 had already put each step's own lines in `Step.live`, so a second stream is a
second backlog and the pane shows the highlighted one. si#148's status bar had been built plural on
purpose and already names two running steps and counts the rest. What did change there is following -
it stops at a fan rather than dragging the cursor between eight rows that started in the same second,
and `f` still goes to a running step on demand. A CI log is one file, so the headless runner buffers a
fan's steps and prints each block whole, in plan order, whichever branch won the race: the same bytes a
sequential run produced, in the same sequence, arriving later. Nothing outside a fan is buffered at all.

### The site is divided by the question you arrive with, not by who you are (si#170)

Eighteen pages sat in two sections named after an AUDIENCE - "Using Simplon" and "Building on Simplon" -
so somebody who wanted to know why any of this exists first had to decide which of the two they were.
That is a question about the reader, and the reader is the one person who cannot answer it yet. The
division is now by question: **Why** it exists, **What** it looks like, **How** you work with it, **With
what** you look things up, and **When** each version went out.

**"How" is wider than installation, and that is a decision rather than drift.** The obvious reading -
how means install - leaves `Writing a task`, `The manifest` and `Task and command` nowhere honest to go.
They explain, so filing them under lookup is a lie about what the page does, and they are not
installation either. So How is "how you work with it", and With what keeps only the pages you open at a
heading and close again.

**The labels are English because the site is.** The five questions were picked in German, where they all
begin with the same letter - Warum, Was, Wie, Womit, Wann - and that is a property of the language, not
of the structure. The structure is the five questions and it survives translation; a navigation entry a
reader has to translate first is not doing the one job a label has.

**Every published URL that moved still answers.** `aliases:` in each page's front matter emits a
redirect from the old path, so the eighteen chapters keep their old addresses, and the two old section
roots land on the front page, which is where the five questions are now offered. Nothing you have
bookmarked or linked into goes to a 404, including the links into these notes.

**One place in the kernel prints a site address, and it moved.** The flat-form refusal (si#85) sends a
product whose manifest just failed to load to the chapter that documents the tree form, by its full
published address; it now names `how/manifest/`. A sweep of `src/` for hard-coded site URLs found that
one and nothing else. The README's pointer to the release procedure moved with it.

**What a product has to do: nothing.** No command, no manifest key and no task changed. What did change
beside the pages is where simplon's own manifest writes the generated command reference - it is
`docs/site/content/with-what/commands.md` now - and that is simplon's own product data, not a kernel
default.

The guards moved differently from the pages. Twelve suites used to spell a chapter's section into a path
of their own, so one re-division made twelve unrelated suites red for the same reason and each had to be
told the new answer separately. They ask `sitepages` for a page by its FILE name now, which is the part
a re-division does not touch. Two of them lost half an assertion and say so in place rather than
quietly: a `weight:` orders within a section, and a chapter and the pages it defers to no longer always
share one.

### The site lives under `docs/`, and a product that says nothing lands there (si#183)

`docs/` is the documentation root, and simplon's own site was not in it: the Hugo sources sat at `site/`
in the repository root while `docs/` held only `superpowers/specs` and `superpowers/plans`, so one
repository answered "where is the documentation" in two places. The sources are at `docs/site/` now -
`content/`, `hugo.yaml`, and the `go.mod` / `go.sum` that hold the pinned theme version. The published
site is unchanged: `base_url` did not move and every URL it serves is the one it served before, because
only the source directory changed.

**What a product has to do: nothing, and that is not a figure of speech.** `site: source:` now DEFAULTS
to `docs/site` instead of being required, so a manifest that names a path keeps exactly what it named and
a manifest that says nothing lands on the convention. Nothing is refused that was accepted before.

The refusal was considered and dropped, and the census is why. Measured over the same population si#159
and si#172 used - every manifest this kernel can reach: simplon's own, the five in
`simplon.surface.CONSUMERS`, and secure-windows-images:

| product | `site:` section | `source:` |
| --- | --- | --- |
| simplon | yes | `docs/site`, now by default and absent from the manifest |
| cleon | yes | `site` |
| biz-cockpit | yes | `docs/website` |
| agile-cockpit | no | - |
| asbundle | no | - |
| netctl | no | - |
| secure-windows-images | no | - |

Three of seven declare a site, and the three disagree. A kernel that insisted on `docs/` would have
refused two products that have done nothing wrong, on their first run with a new kernel - the expression
rule si#53, si#85 and si#159 each declined to write, and the one kind of refusal the census asks a reason
for.

**So who is a default for, if all three existing products name the key?** The fourth. A product that gets
a website from here on writes four keys instead of five and lands on the convention without having read
about it, which is the only moment a convention is cheap to adopt. Simplon is its first consumer rather
than a product that happens to agree with it: its own `site:` section carries no `source:` line, so every
`build docs` in this repository exercises the default.

**`site: output:` deliberately does not get one, and the asymmetry is the point.** By consumer agreement
it has the better case - two of the three declare `build/website` and only cleon differs - but `output`
is handed to `shutil.rmtree` before every build. A default there would recursively delete a directory the
product never typed, the first time somebody forgot a key. `source` is only ever read. The kernel may
assume where to look; it may not assume what to delete.

What moved beside the directory is every path that named it: the manifest's `site: source:`, the
`docs:reference` output and the `releases: page:`, four `.gitignore` lines, seven places in the suite
that spelled the content tree out for themselves, and the module path in `go.mod`. The link checker
walks every page and every fragment after the move, which is what says the move did not break the site
rather than that it looked fine.

**`tests/sitepages.py` calls itself the one place the site's shape is described, and it was not.** Six
other test modules carried the path again, in four spellings the same sweep does not catch at once:
`ROOT / "site" / "content"`, `Path(__file__).parents[1] / "site" / "content"`, `ROOT / "site" /
"hugo.yaml"` and `root / "site"` inside a list comprehension. Two of the six went red and named
themselves - one through its own vacuity guard, *"no page links into this chapter any more"*. The sixth
went GREEN and stopped covering anything: `test_surface.py`'s si#51 assertion reads every page of this
site for a repository named as a consumer that is not one, and `Path.rglob` over a directory that is no
longer there yields nothing and raises nothing, so the check kept passing over 25 pages it had stopped
opening. Measured by planting one of the names its own census has measured NOT to use this kernel into
`why.md`: green before the path was repaired, red after, naming the file. That is the defect this
repository calls a verdict that cannot fail, and a rename is how it arrives.

It then went red on these very notes, which had named that repository as the example. Both halves are
the guard working.


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
over](../../what/handing-a-package-over/) is the chapter. Nothing to do: five declared coordinates, and a
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
untouched. Two quoted refusals on `with-what/test-levels.md` were repaired on the way - one listed a
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
changes; the count on the [rules page](../../with-what/rules/) moves from 25 to 26.

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
refusal was added or removed. The [test levels chapter](../../with-what/test-levels/) carries the whole
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
wording is a statement about the ACT OF MERGING. The guard now reads the first as written, and for the second
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
page](../../with-what/rules/) is untouched.

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
[Delivering a Java product](../../what/case-java/). Nine of its thirteen steps were
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
[Surface](../../with-what/surface/) for why re-measuring beats remembering.

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
one expression rule. See [Rules](../../with-what/rules/) for the live split.

### Documentation

**A complete Python use case** (si#26), from `simplon init` to a deployed local
host: [Delivering a Python product](../../what/case-python/). Every step carries one of
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
[Surface](../../with-what/surface/) for how that is measured now.)*

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
guessed — see [Surface](../../with-what/surface/).

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

New chapters on [the five phases](../../with-what/phases/) with a diagram, and
on what the kernel means by running in Docker. The coordinate table lost the
sentence beside each entry: those sentences were paraphrases of the catalogue's
own `help:`, nothing compared the two, and by the time anybody looked several
had drifted. The reliable fix is not to guard the copy but not to keep one.
