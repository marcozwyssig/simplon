# si#788: every product's workflows derived by the kernel, the product writes nothing

Status: design, decided by Marco on 2026-11-22 (choice lists in the session that wrote this file).
Milestone: P2 M9 "Workflows derived, not written". Blocks #786 and #789.

## 1. Intent

Marco, 2026-11-19: "Die Idee ist, dass das Produkt nichts machen muss und alles automatisch aus dem
Simplon Kernel mit firn generiert wird." Every product's CI and release workflows are built the same
way, from information the manifest already carries, and every piece of work runs once.

Today the kernel derives everything *around* a job (trigger si#787, checkout si#3/si#622, the orphan
reaper si#756, the release job si#490 with permissions si#719, time limit si#720 and secrets si#836, the
artifact hand-off between jobs si#344 C.4). The jobs and the steps are still written by every product
under `workflows:`, and four products write their workflow files entirely by hand. #788's body holds
the survey of 2026-11-19 and the products' own reasons; this spec answers each reason as data, not as
steps.

## 2. Goals, non-goals, anti-goals

Goals:

- A product with no `workflows:` section gets a complete CI workflow and, when it declares a release,
  a complete release workflow. (corrected 2026-11-22, #858) For the CI the switch is `workflows: ci:`:
  a product with no such entry gets the derived ci.yml beside whatever else it declares, and a product
  that declares other workflows and has no leaf a machine may run gets no ci.yml and one log line. Adding a command to `ci build` or `ci test` puts it in CI with no
  second edit.
- Every case in #788's "Why the hand-written files exist" is expressible as a key on a command, on a
  runner or on the product. None of them needs a step.
- The workflow vocabulary (workflow, job, step, runner, trigger) is a firn model first; the generator
  consumes classes generated from it.
- No verdict runs twice in one run, and a release does not rebuild what CI built (the promotion
  itself is #789).

Non-goals:

- Merge queue. Reopen when post-merge runs are measured to cost more than a per-repository setting
  (#788 "Not decided").
- Retiring the YAML manifest (#456). Only the workflow vocabulary moves into the model here.
- Platforms other than GitHub Actions.
- Iterating firn projects in dependency order: that is firn's command (decision D6), not the kernel's.

Anti-goals (a result that works and is still a failure):

- A derivation that needs a product-written escape hatch for the common case. If a migrating product
  needs `run:` or `uses:`, the derivation is missing a datum and the migration stops until it has one.
- A new leaf that silently does not run in CI. Opt-in would reopen si#8 (green for months because mypy
  never ran); the derivation is opt-out.
- A derived workflow that hides why a leaf is absent. Every skipped leaf is named in the rendered file
  with its reason, as `derive:` already does.
- A kernel exemption: simplon migrates first and holds no `workflows:` the products may not.

## 3. Decisions (Marco, 2026-11-22)

| # | Question | Decision |
|---|----------|----------|
| D1 | What runs in CI | Every `unattended` leaf under `ci build` and `ci test`, the rule of `derive:` (si#267). Aggregates are skipped. |
| D2 | Opt-out | A new key on the command, `ci: { skip: "<reason>" }`. `unattended` keeps meaning "needs no human". |
| D3 | Job split | One job per runner need; a cut only where an artifact crosses it. The order is manifest order with port edges as the only extra precedence (amended 2026-11-22, see 5.2). |
| D4 | The machine | A top-level manifest key `runner: {kind, labels}`. Absent: `github-ubuntu`. |
| D5 | Model | Model first: Workflow, Job, Step, Runner, Trigger become classes in `pipeline.firn`; workflowgen consumes the generated classes. This slice of P3 M5 is pulled into P2 M9. |
| D6 | firn projects in dependency order | firn's own command (`--all`, ordered by `firn.toml [dependencies]`, parallel where independent). The kernel calls one command. |
| D7 | Product's own pytest suite | A new catalogue task `test:unit`: pytest over product-named paths in a kernel-provisioned venv, placed under `ci test`. |
| D8 | Schedule, dispatch input, OS matrix | Keys on the command: `cadence:`, `platforms:`, parameter values `{input: <name>}`. |
| D9 | Heavy lab gate, foreign repositories | Data keys: `ci: { gate: {paths, label} }` on the command; `sources:` on the product. (corrected 2026-11-23, #861: the gate sits on an aggregate, `ci: { gate: {paths, label, env} }`, see 5.5.) |
| D10 | Runner facts (empty `DOCKER_CONFIG`, no binfmt) | A new runner kind `self-hosted-container` carries them. |
| D11 | Migration order | simplon first, then cleon-firn, firn, secure-windows-images, biz-cockpit, agile-cockpit, cleon, asbundle, netctl. |
| D12 | simplon's release jobs beyond `release`, `docs`, `pages` (`publish`, `homebrew-tap`, `image`) | Counted `exception:` entries with the reason "waits on #789" until #789 lands; simplon's CI migrates at once. |
| D13 | Leaves D1 adds to simplon's CI (`build reference`, `build acceptance`, `build site`, `build model`, `build homebrew-formula`, `test image`, `test homebrew-formula`, as of 2026-11-22; (corrected 2026-11-22, #858) the first three were written `docs ...`, and simplon's commands are `build ...`) | Default: they run. simplon's migration ticket measures each on ghr-8; one not worth its price gets `ci: { skip: }` with the measured reason. |
| D14 | Default branch (`main` is a constant, cleon and agile-cockpit use `master`) | Those products rename `master` to `main` in their migration ticket. No new datum, no API call at generation time. |

Earlier decisions this spec builds on and does not reopen: triggers are PR plus push to `main` plus
dispatch (si#787, #794); a product-written `on:` is decided here (section 6.3); build once, release
promotes (#789).

## 4. The model (D5)

`src/firn/model/simplon/pipeline/pipeline.firn` gains a `simplon.workflow` package (or a sibling file
`workflow/workflow.firn`; builder's call) with these classes. Names are the vocabulary; attribute
lists are the minimum the derivation reads.

- **RunnerKind** (instances: `github-ubuntu`, `self-hosted-debian`, `self-hosted-container`):
  `labels` (default labels, may be empty), `setupPython`, `diskPersists`, `env` (table), `canEmulate`,
  `why`. The table in `src/simplon/manifest/runners.py` becomes model instances; `runners.py` becomes
  generated data plus the resolve logic.
- **Runner**: a RunnerKind plus product labels. The product's `runner:` key (D4) is one Runner.
- **Trigger**: `pullRequest`, `pushMain`, `dispatch` (with Inputs), `schedule` (cron). The CI default
  is the first three (si#787).
- **Workflow**: `path`, `name`, Triggers, Jobs, `permissions`, `concurrency`. Derived, never declared,
  except as an Exception (section 6.3).
- **Job**: a Runner, an ordered list of Steps, `needs` (Jobs), an optional Matrix, `timeoutMinutes`,
  `if`.
- **Step**: exactly one TaskCommand with bound parameters, or a kernel step (checkout, reaper, docker
  probe, disk preflight, upload, download, app-token mint). Kernel steps are instances the kernel owns;
  a product cannot name one.
- **Matrix**: cells from `platforms:` and Python versions (D8).
- **Exception**: a product-written workflow that names its reason (section 6.3).

Selectors derive, they are not stored: a Job's Steps are the TaskCommands placed under `ci build` /
`ci test` that are unattended, not skipped and need this Job's Runner; a Workflow's Jobs are those
groups cut at artifact crossings (section 5.2).

Generated output: a template (`Workflow.firnt`, builder's naming) generates the Python classes into
`src/simplon/` the way `ArtifactSchema` does today. workflowgen fills instances of them from the loaded
manifest and renders YAML from them. The rendered text format (notes as comments, the YAML 1.1 `on:`
trap) stays workflowgen's job.

Decided in #857 (2026-11-22): the selectors (which leaves, which jobs, which order) run in Python over the
generated classes, inside `support github workflows`. Running them in firn over the exported manifest model
(si#522 `test manifest-model` exports one) would put docker and the firn image on every generation and every
`--check`, including a pre-commit hook. The vocabulary is the model's (D5); the evaluation is the kernel's.
Reopens when firn can be evaluated in-process without a container, or when the manifest becomes the firn
model (#456). #857 also measured what the generated classes rest on: a firn template reads each property's
kind, range and cardinality, so the dataclass fields are generated, not typed.

## 5. The CI workflow

### 5.1 What runs (D1, D2)

The set is every TaskCommand leaf placed in a group whose area is `ci` and whose phase is `build` or
`test`, with `unattended: true`, minus the leaves that carry `ci: { skip: "<reason>" }`.

- Aggregates are skipped: the leaves they plan are in the set by themselves.
- A leaf with `unattended` unset is refused today by `derive:`; the same diagnosis holds.
- `ci: { skip: ... }` without a reason is refused. Census kind: expression rule (it forbids the bare
  `ci: false` spelling, which would have worked). Measured cost before shipping: zero manifests carry a
  `ci:` key on a command today; the builder re-measures over every reachable manifest
  (`reachable-manifests` memory: eight) before the ticket merges.
- (corrected 2026-11-22, #858) `ci:` on an aggregate, or on a command that is not a leaf under `ci
  build` or `ci test` (a cd, support or `ci release` command, a Deploy), is refused. Census kind:
  diagnosis (no derived CI selects the command, so the key would do nothing).
- (corrected 2026-11-23, #861) On an aggregate under `ci build` or `ci test`, `ci:` holds `gate:`, with
  `cadence:` and `timeout_minutes:` beside it (section 5.5); any other key there, or `cadence:` or
  `timeout_minutes:` without `gate:`, is refused as before, a diagnosis.
- Every skipped leaf is named in the rendered file as a comment with its reason.
- `test:gate` and other leaves that need a running lab are the expected users of `skip`, or of
  `gate:` (section 5.5).

### 5.2 Order and job split (D3)

1. **Order** inside the set is manifest order, with one extra precedence: a consumer after its producer
   (a stable topological sort). Amended 2026-11-22 (Marco, on #448's measurement): ports imply 36 of 1540 ordered leaf
   pairs across every reachable plan (netctl 0 of 1001, though its `web-jar`, `aot` and image steps really
   depend on each other), so an order from artifacts alone is measured out; ports only complete list order.
   #858 does this sort itself; #448 is not a prerequisite and stays in P5 M6.

   (corrected 2026-11-22, #858) This item also said the order "keeps simplon's 'release-notes last'
   without a key, because it is last in the manifest". Measured on simplon's manifest with
   `workflows.ci` deleted, it does not: manifest order is the loaded manifest's order, the platform's
   group order (`build`, then `test`, then nested groups such as `test.x` in catalogue order) and inside
   a group the order the YAML writes, so every `build` leaf runs before every `test` leaf and `test
   release-notes` is not the last leaf. It need not be: every leaf runs unless the run is cancelled or a
   preparation step went red (below), so no verdict hides another and "last" buys nothing. Only an
   `after_all` leaf, the report, is placed last.
2. **Runner need**: a leaf runs on the product's Runner (D4) unless its task needs something that
   Runner cannot give. The first such need the derivation knows is `platforms:` (D8). A leaf on a
   different Runner is a different Job.
3. **Cut**: two Jobs are split only by Runner need or by matrix. Inside one Runner, the set is one Job,
   in order. Where an artifact crosses a Job boundary, the existing `handoff.plan` adds `needs:`, the
   upload after the producer and the download before the consumer.
4. **No double run**: a leaf is in exactly one Job. firn's `test all` in both `build` and
   `container-route` (measured 24 of 41 min, #788 comment) cannot be expressed any more; if the two
   routes are two verdicts, they are two leaves.

A red step must not hide the verdicts after it. A Job stops at its first failed step, so every leaf
step after the first gets `if: ${{ !cancelled() }}` and the Job is red if any step was. Builder's call
how the failure is collected; the requirement is that a run answers *what went wrong* for every leaf,
not only the first (CLAUDE.md "usable"). (corrected 2026-11-22, #858) How: each leaf is its own
step and GitHub marks the Job red when any step was, so nothing more collects the failure. The
preparation steps (the docker probe, the disk preflight, `support install`, each where the product
places it) carry the ids `prepare_docker`, `prepare_disk` and `prepare_install` and no condition; the
first leaf has none either, since GitHub's default already waits on every step before it; every later
leaf runs `if: ${{ !cancelled() && steps.<id>.outcome == 'success' ... }}` over each preparation step
present, so one red leaf hides none of the others while after one red preparation the leaves are
skipped instead of every one red for the same cause; the `after_all` report and its upload still run and
say what they found. A leaf that consumes what another leaf produces also waits for that producer: the
producer carries a step id from its command words (`leaf_build_handoff_canary`), and the consumer adds
`steps.<that id>.outcome == 'success'`, so a red producer leaves its consumer skipped, not a second red
step for one cause (final review, #858). An `after_all` leaf and the report upload run `if: always()`.

### 5.3 Report steps

`test report` and its upload run `if: always()` today because they archive the gates' verdict. My
call: a catalogue task attribute (working name `after_all: true`, set on `test:report`) places the leaf
after every other leaf in its Job with `if: always()`. Not derived from `test-result` ports: no
catalogue task consumes `test-result` today and simplon's `test suite` writes an Allure directory, so
port-based derivation would be a catalogue change every consumer sees. Reopens when the report task
declares the port (#448 is the natural moment).

### 5.3a The hand-off canary

simplon's `handoff-canary-write` / `handoff-canary-check` exist to prove an artifact really crosses a
job boundary on a real runner. Under D3 they share ghr-8 and would collapse into one Job. My call:
they stay as one counted `exception:` with that reason. Reopens (and the canary retires) once a
derived workflow of simplon crosses a job boundary on every push, for example a `python:` cell
consuming a CI artifact.

### 5.4 The machine (D4, D10)

Top-level `runner: {kind, labels}`, resolved by the existing `runners.resolve`. Absent means
`github-ubuntu`. The kind table grows one kind:

- **self-hosted-container**: a runner that is itself a container (firn's, LXC). `env` sets
  `DOCKER_CONFIG` to an empty per-job directory so a stale ghcr login cannot break an anonymous pull
  (firn#957, firn#1039); `canEmulate = false`, so an arm64 build there is either routed to a native
  arm64 runner the product names, or rendered as a named gap. This closes #722 as part of this
  milestone.

### 5.5 Variants as data (D8, D9)

All on the command, under the one `ci:` key so a reader finds them together:

- `ci: { cadence: nightly }` (or a cron string): the leaf leaves the push workflow and goes into a
  derived scheduled workflow (`ci-nightly.yml`). agile-cockpit's nightly compose-around-a-suite becomes
  a leaf whose task brings the compose up and down (an existing `test:` task or the D7 task's
  sibling; builder measures which). `cadence: manual` puts it in a dispatch-only workflow.
- `ci: { platforms: [linux, macos, windows] }`: matrix cells on GitHub-hosted runners for that leaf
  (cleon, asbundle, #686). `python: ["3.14"]` adds Python cells the same way and replaces simplon's
  hand-written `suite-python-3-14` job. My call: a Python cell is a runner need; when the product's
  runner kind has `setupPython = false` (self-hosted kinds), the cell runs on `github-ubuntu`. The arm64
  emulation that job registers today belongs to the leaf that needs it (`emulates:` on the command),
  not to the cell.

  (corrected 2026-11-23, #860) What was built, beyond the text above:

  - **Cadence files.** `nightly` goes to `.github/workflows/ci-nightly.yml`, triggered by the kernel's
    cron `17 2 * * *` (off the full hour, as agile-cockpit's hand-written nightly is) and by dispatch;
    `manual` to `ci-manual.yml`, dispatch only; a cron string to `ci-scheduled.yml`, one job per distinct
    cron, each gated on its own schedule and all of them run on a dispatch. A leaf with no `cadence:`
    stays in `ci.yml`, per push. A cadence file is built like `ci.yml` (preparation, its leaves, the
    `after_all` leaves without a cadence of their own and the report upload, cleanup), and carries
    `concurrency: { group: <file stem>, cancel-in-progress: false }`. Each file exists only while a leaf
    carries its cadence. This answers section 9's "file names beyond `ci.yml`" for the CI half.
  - **Platform cells are kernel names**, not runner labels: `linux-x64`, `linux-arm64`, `macos-x64`,
    `macos-arm64`, `windows-x64` (measured on cleon `ci.yml` and asbundle `build-matrix.yml`). The
    kernel holds each cell's runner label, shell, launcher and the architecture `uname -m` prints there,
    as `simplon.workflow.Platform` instances in `runners.firn`; an unknown name is refused with the list.
    `platforms:` replaces the leaf's run in the main job (5.2's "no double run"); each cell checks its
    architecture first, a bash cell `exec`s the launcher, the Windows cell runs `<product>.cmd` in `cmd`.
  - **`python:` adds cells**: the leaf still runs in the main job, and once more per version in a matrix
    job on `github-ubuntu` with `setup-python`, whatever the product's `runner:` is.
  - **A cell job carries no report**: its result is its job's colour, one per cell, `fail-fast` off. It
    reopens with #450's test results per cell. A run whose every leaf is a platform leaf has no main job,
    so its `after_all` leaves do not run there, and the first cell job's note says so.
  - **`timeout_minutes:` and `emulates:` sit under `ci:`** with the other variant keys:
    `ci: { timeout_minutes: N }` is the leaf's step's `timeout-minutes` in a shared job and the job's in a
    leaf's own (cell) job, the same for every cell; `ci: { emulates: [linux/arm64] }` registers emulation
    once per job before its leaves, with the release's action and binfmt pin, and on a kind with
    `canEmulate = false` registers nothing and names the gap in the job's note (5.4; routing is #722's).
  - **Unmeasured: the hand-off unpack on Windows.** A Windows cell that downloads a hand-off unpacks it in
    `cmd` with Windows' tar from a `D:` path; nobody has run that on a Windows runner, so it is recorded in
    the generated file rather than refused. The first product migration that writes `platforms:` with a
    Windows cell and a hand-off is that measurement.
  - Two expression rules, in section 10: `platforms:` with `python:`, and `platforms:` with `emulates:`.
- A parameter value `{input: <name>}` (next to the existing `{env: NAME}`, si#488): the workflow that
  holds the leaf gets a `workflow_dispatch` input of that name (biz-cockpit publish: input to tag).
  (corrected 2026-11-23, #860) Not built in #860: it moves to step 8 (#862). Measured over the eight
  reachable manifests and their workflow files on 2026-11-23, its only user is biz-cockpit
  `publish.yml`, which dispatches the `release` aggregate, not a `ci build` or `ci test` leaf, with a
  default ("the tag ref, else the sha") a plain input cannot say; a derived CI leaf has no `params:`
  place for it to stand in.
- `ci: { gate: { paths: [...], label: <name> } }`: the leaf runs only when a changed path matches or
  the PR carries the label. Derived as a decide job in front of the leaf's Job (netctl's 75 min lab,
  #691). The decide job also fixes netctl's double trigger (`opened` and `labeled`): it is one job with
  one verdict per head SHA, and the heavy Job is cancelled-in-progress by concurrency.

  (corrected 2026-11-23, #861) What was built, which differs from the bullet above:

  - **The gate sits on an aggregate**, not on a leaf: `ci: { gate: { paths, label, env } }` with
    `cadence:` and `timeout_minutes:` beside it. Its plan leaves run in the gate's own file and not also
    in `ci.yml`; an `after_all` member stays in every run it ends. A leaf is gated by wrapping it in an
    aggregate.
  - **No cancel.** "Cancelled-in-progress" is wrong: the gated job's concurrency is
    `cancel-in-progress: false` (netctl#513), and its group carries the verdict, so a skipped job never
    shares a group with a real run.
  - **The decide table**, one verdict per event and never from earlier runs: dispatch and schedule run;
    `opened` runs when a changed path matches; `synchronize` and `reopened` when a path matches or the
    pull request carries the label; `labeled` when the label just added is the gate's and no path matches.
    Every verdict writes a `why`.
  - **Its own file**: `.github/workflows/ci-<aggregate words, dashed>.yml`, derived unless `workflows:`
    declares that stem. `paths:` are the `*`/`**` subset of GitHub's filter syntax, translated into one
    ERE at derive time; a glob with `!`, `?`, `+` or `[...]`, which GitHub reads otherwise, is refused.
  - **Not built here:** `sources:` is #873 and `merge: auto` is #874.

On the product:

- `sources: [{repo, path, secret?}]`: further checkouts the derived checkout step performs after the
  product's own, a private submodule or a second repository (netctl's submodule with a PAT, cleon-firn's
  import reading `../cleon`). `secret` names a secret through the si#833 secrets module, so it is
  masked and checked before the run.
- `merge: auto` (netctl, #691): a derived auto-merge workflow on green CI. My call; #788 lists it as a
  hand-written reason and it is a product-level datum.

### 5.6 The product's own pytest suite (D7)

New catalogue task `test:unit`, placed under `ci test`:

- Parameters: `paths` (one or more test directories), `requirements` (a requirements file or the
  project's own extras; builder's call, measured against cleon-firn, cleon and asbundle).
- The kernel provisions a venv (the launcher's mechanism), installs pytest and the named requirements,
  runs pytest, and produces `test-result` like the other test tasks so the report picks it up.
- simplon's own `test suite` stays a product task until simplon has a reason to move it; nothing in
  this spec forces it. #848 (suites in a kernel-owned container) is the later home for both.

## 6. The release and other workflows

### 6.1 Release

A product that declares a ReleaseCommand gets the release workflow it gets today from
`workflows.release: { release: <group> <name> }`, without the `workflows:` entry. `emulates:` and
`timeout_minutes:` move to the ReleaseCommand. What the release job runs is #789's question: it
promotes what CI built for the same commit. This spec only fixes the boundary: CI's artifacts are
published by the same hand-off mechanism (section 5.2), so #789 has a named artifact per commit to
promote, and firn's hand-declared `builder` job (stamped by `git describe`) becomes a CI leaf whose
image is promoted, not rebuilt.

### 6.2 Pages, rollout

- Pages (si#851): a product with a `site:` section gets the `docs` and `pages` jobs derived in its
  release workflow. Today simplon writes them by hand under `workflows.release.jobs`.
- Rollout: #786 (a rollout starting after a kernel-derived release) is unblocked by this spec and keeps
  its own design.

### 6.3 What `workflows:` may still say

After the migration, a `workflows:` entry may only be an Exception:

```yaml
workflows:
  lab:
    exception: "<why no datum expresses this yet, with the ticket that will>"
    # ... the hand-written workflow, carried verbatim as today
```

- An entry with jobs, steps or `on:` and no `exception:` is refused. Census kind: expression rule.
  It forbids what every product with a `workflows:` section writes today, so it ships **last**, after
  the migration tickets, measured over every reachable manifest; the fix cost per product is the
  migration itself.
- `handwritten:` (a file the kernel does not render) becomes the same thing and is folded into
  `exception:`. Builder's call whether to keep the old word for one release; CLAUDE.md says a retired
  word fails loudly, so no silent alias.
- The census (`tests/test_refusal_census.py`) counts every Exception in the reachable manifests, so
  the sum is visible on `with-what/rules.md`.
- A product-written `on:` is part of an Exception, never a CI override (the "named exception" #794
  deferred here). Measured 2026-11-20: biz-cockpit's and swi's `on:` are the default or the double-run
  defect; firn's is the default minus dispatch. None needs the exception.

## 7. Delivery

Each step is a ticket in P2 M9 (unless noted) and lands with a verification.

1. **Model** (D5): workflow classes in the firn model, template, generated Python; runner kinds as
   instances. Verify: `test model` green, generated classes used by workflowgen, simplon's rendered
   workflows byte-identical before and after.
2. *(Struck 2026-11-22: #448 is no longer a prerequisite; #858 sorts its leaves, see 5.2.)*
3. **Derivation core**: D1, D2, D3, D4, sections 5.1 to 5.3. A product with no `workflows: ci:` gets
   `ci.yml`. Verify: simplon's manifest with its `workflows.ci` deleted renders a CI workflow running
   every unattended leaf, the D13 leaves among them, in manifest order completed by ports, the report
   last; every skipped leaf is named with its reason; `support workflows --check` green.
   (corrected 2026-11-22, #858) The switch is `workflows: ci:`, not the whole section: this said "a
   product with no `workflows:`", and a product that declares other workflows gets the derived ci.yml
   beside them, or none, with one log line, when it has no leaf a machine may run. The verification said
   "today's leaves in today's order plus the D13 leaves"; today's order puts the prose gate last by hand,
   and manifest order does not (5.2 item 1).
4. **Runner kind** `self-hosted-container` (D10, closes #722).
5. **`test:unit`** (D7).
6. **Variant keys** (D8): `cadence`, `platforms`, `python`, `{input:}`.
   (corrected 2026-11-23, #860) Built in #860: `cadence`, `platforms`, `python`, and `timeout_minutes`
   and `emulates` under the same `ci:` (5.5). `{input:}` moved to step 8 (#862), where its one user
   stands.
7. **Gate and sources** (D9), `merge: auto` (closes #691's generation half).
8. **Release and pages without `workflows:`** (section 6.1, 6.2). Then #789 and #786.
9. **Migration**, one ticket per product, in the D11 order. simplon first: delete `workflows:` except
   the Exceptions this spec names (D12, 5.3a); measure the D13 leaves. cleon and agile-cockpit rename
   `master` to `main` (D14). Each product ticket ends with the product's manifest carrying no step
   outside a named Exception.

**When the derivation switches on** (my call): only when the product runs `support workflows`. The
kernel bump that ships steps 3 to 8 changes nothing in a product that does not run it, which is
exactly the four fully hand-written products today, so the D11 order holds. Where a derived file would
land on a path that holds a file without the generated header, generation refuses and names the file
(diagnosis: without it a hand-written file would be overwritten silently). A product's migration ticket
is the moment it starts running the verb. (corrected 2026-11-22, #858) This refusal is not in the
refusal census: it is decided by a file on disk, not by the manifest.
10. **The rule** (section 6.3), last, with its census entry.

Outside the kernel: a ticket at firn for `--all` in dependency order (D6), raised by message to the
firn session, not built here. cleon-firn's step 4 waits on it; its steps 1 to 3 do not.

## 8. Mapping: every reason in #788 to its datum

| Reason (product) | Datum |
|---|---|
| CI steps written per job (all generated products) | 5.1, 5.2 |
| `checkout: false` + hand-written reaper (firn) | already derived (si#756, si#622); deleted on migration |
| Step-level `DOCKER_CONFIG` (firn) | runner kind `self-hosted-container` (5.4) |
| No `emulates:` on a container runner (firn, #722) | `canEmulate` on the kind (5.4) |
| Builder job stamped by `git describe` (firn) | a CI leaf, promoted by #789 (6.1) |
| `test all` twice (firn) | not expressible; one leaf one Job (5.2) |
| Dispatch input to tag, `packages: write` (biz-cockpit publish) | `{input:}` (5.5); `publishes:` leaf permissions already derived (si#719). (corrected 2026-11-23, #860) `{input:}` is step 8's (#862): the dispatch is of the `release` aggregate, not a CI leaf |
| OS matrix with a plan job (cleon, asbundle, #686) | `ci: platforms:` (5.5). (corrected 2026-11-23, #860) Kernel cell names. Both products run the matrix on a tag or by dispatch: `cadence: manual` covers the dispatch, and no tag trigger is derived |
| Product's own pytest (cleon, asbundle, cleon-firn) | `test:unit` (5.6) |
| Pages deploy (cleon, simplon) | derived from `site:` (6.2) |
| Nightly compose around a suite (agile-cockpit) | `ci: cadence:` (5.5) |
| Decide job, paths + label, lab double trigger (netctl) | `ci: gate:` (5.5) |
| Auto-merge (netctl, #691) | `merge: auto` (5.5) |
| Private submodule PAT (netctl), cross-repo input (cleon-firn) | `sources:` (5.5) |
| firn projects in dependency order (cleon-firn) | firn's `--all` (D6) |
| Python version cell (simplon `suite-python-3-14`) | `ci: python:` (5.5). (corrected 2026-11-23, #860) With `ci: emulates:` for the arm64 emulation that job registers; deleting the hand-written job is #863 |
| netctl has no `support workflows` member | the verb is the kernel's; derivation needs no member (section 9) |

## 9. Left to the builder

- Whether `support workflows` must be named by a product at all, or is reachable from the kernel's
  catalogue for every product. The goal says a product that must name a command is doing something;
  the builder checks whether the catalogue already places it and closes the gap if not.
- The exact file names of derived workflows beyond `ci.yml` and `release.yml`. (corrected 2026-11-23,
  #860) Decided for the CI half: `ci-nightly.yml`, `ci-manual.yml`, `ci-scheduled.yml` (5.5).
- How failures of non-first steps are collected into the job's verdict (5.2).
- Where the selectors are evaluated (section 4).

## 10. Rejected alternatives, with what reopens them

- **A named aggregate as the CI source.** Rejected: a job stops at its first red step, so an aggregate
  puts one gate in front of the others (simplon.yaml's `workflows.ci` note). Reopens if aggregates get
  continue-on-failure semantics in one step.
- **Opt-in `ci: true` per command.** Rejected: reopens si#8. Not reopened.
- **One job per leaf.** Rejected: every job pays checkout, reaper and toolchain (firn: `build toolchain`
  7 to 10 s per job, measured) plus a hand-off per artifact. Reopens if a product has more runners than
  one and the leaves are measured to be independent and long.
- **Python first, model in P3 M5.** Rejected by Marco (D5).
- **The kernel reads `firn.toml` to fan out projects.** Rejected (D6). Reopens if a second product needs
  a kernel-side fan-out that is not firn's.
- **Unreasoned `ci: false`.** Rejected: an opt-out with no reason is the absence nobody can read back.
- **`platforms:` and `python:` on one leaf** (corrected 2026-11-23, #860). Rejected: a cross product of
  cells and interpreter versions no product has asked for, and nobody measured what it costs a runner
  bill; a cell runs on its platform's own interpreter. An expression rule: over the eight reachable
  manifests on 2026-11-23 it refuses nothing (none writes `ci:` on a command). Reopens when a product
  asks for that cross product on one leaf.
- **`platforms:` and `emulates:` on one leaf** (corrected 2026-11-23, #860). Rejected: a macOS or
  Windows cell has no binfmt to register an emulator with, and a native `linux-arm64` cell makes
  emulating arm64 pointless. An expression rule with the same measured cost, zero. Reopens when a
  product asks to emulate inside a platform cell.
- **`gate:` on a leaf** (corrected 2026-11-23, #861). Rejected: a single-leaf gate is an aggregate of one,
  and the aggregate is where the gate's members, file and concurrency already live. An expression rule:
  `depends_on: [<leaf>]` says the same thing, and the refusal names that form. What it costs: zero: #860's
  2026-11-23 measurement found no `ci:` on any command in the reachable manifests, and `gate:` is new in
  #861. Reopens when a product asks to gate a leaf without naming an aggregate for it.
- **`stop_on_failure` read by a gated job** (corrected 2026-11-23, #861, Marco's decision 6). Rejected: a
  Deploy member prepares and the verifying members keep `!cancelled()`, which is netctl's `lab.yml`
  (`if: always() && steps.up.outcome == 'success'`); a local `test lab` keeps running after a red `up`,
  and the gated job stops there. Reopens if a product asks for local and CI to agree.
- **A teardown Deploy in plain order** (corrected 2026-11-23, #861 final review). Rejected: a Deploy member
  is a plain step in order, so one placed last is skipped after a red verifying member. A teardown is a Deploy
  with `after_all: true`, which runs after the members with `if: always()` and prepares nothing; a command
  named twice in one plan runs once, so a pre-clean `down` and a final teardown are two commands. Reopens
  when a product needs a teardown that is not `after_all`.
