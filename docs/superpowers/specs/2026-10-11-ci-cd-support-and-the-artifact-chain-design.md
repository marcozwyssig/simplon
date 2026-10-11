# ci / cd / support, and the artifact chain

**Status:** design, not built. **Date:** 2026-10-11. **Ticket:** si#344 (with si#346 for part D, after
si#371).

## The goal, in one sentence

A manifest says in its own structure which commands are **CI** (build, test, release), which are **CD**
(deploy, monitor, in an environment) and which **support** both, and every command says which
**artifact** it consumes and which it produces, so that the chain from source to deployment can be read,
checked and turned into a pipeline without anyone restating it.

The CLI does not change. `./simplon.sh build image` stays `./simplon.sh build image`. What changes is the
manifest's text, the checks the loader can make, and what the workflow generator can write.

## Decisions this spec is built on

All of them were taken by Marco through choice lists, and none of them is reopened here.

| # | Decision | Where |
|---|---|---|
| 1 | `ci`/`cd` are YAML structure only. The CLI does not change | si#344 body |
| 2 | `produces:`/`consumes:` are checked and generated, never run. `depends_on` still orders at run time, and nothing tracks freshness | si#344 body |
| 3 | The documentation site becomes `website:`. `cd.site:` is the location (central, branch office) | si#344 comment 6095971880 |
| 4 | A migration command (text splice), then a hard cut | same |
| 5 | `env_groups:` is deleted. `cd` is env-first | same |
| 6 | An artifact is name + path under `output:` + optional registry, in `artifacts:` | same |
| 7 | `images:` is folded into `artifacts:` as `kind: image` | 2026-10-11 |
| 8 | The migration command is `support manifest migrate`, **and** `simplon manifest migrate` on the package CLI | 2026-10-11 |
| 9 | `ci`/`cd` are a real tree level, transparent to the CLI | 2026-10-11 |
| 10 | The firn metamodel is in scope, including the `.firn` bridge, and covers the **whole manifest**, not only the pipeline | 2026-10-11 |
| 11 | Diagnoses change only in the cut, in both directions | 2026-10-11 |
| 12 | "Tested" is explicit: a test produces its own artifact (`kind: test-result`), and a release consumes the test results about what it publishes. That need not be a `test:image`: any test that writes a test result will do | 2026-10-11 |
| 13 | One spec, four plans, in the order A → B → C → D | 2026-10-11 |
| 14 | A command can have several inputs and several outputs. A release is an aggregate of leaves: it generates the release notes, puts the artifact into the registry and cuts a tag | 2026-10-11 |
| 15 | The release is one artifact, a `kind: release` bundle, and that is what a deploy consumes | 2026-10-11 |
| 16 | The release notes are generated from the merges and tickets since the previous tag | 2026-10-11 |

firn's metamodel advice (si#346, last comment, grounded in firn main a9e59dd5) supplies the vocabulary:
a **task** is a filter type with ports, a **command** is a filter instance (TaskCommand or
AggregateCommand), an **artifact** is the pipe as a typed value owned by its producer, ordering is
derived from `consumes`, and an aggregate's outputs are derived through a SelectorRelation.

## What this is NOT

- **Not a freshness engine.** Nothing decides that a step can be skipped because its output is newer than
  its input. `CommandSpec` refuses Make semantics on purpose, and that refusal stands (decision 2).
- **Not a CLI change.** No `ci build image`. The transparent level exists in the tree and nowhere on the
  command line.
- **Not the website simplification.** That comes last, after this has landed (memory
  `ci-cd-concept-2026-10-10`). This spec renames `site:` to `website:` and nothing more on the docs side.
- **Not the four Jinja templates.** Generating `launch.sh.j2`, `launch.cmd.j2`, `generic.clab.yml.j2` and
  `cli.py.j2` through firn stays on si#346. Part D builds the metamodel and the bridge they would stand
  on, and nothing else.
- **Not a `cd.site:` reader.** The key is reserved and modelled (part D), and no kernel body reads it in
  this spec. A deploy that takes a site is the next ticket, once a product has one to deploy to.

---

## Part A: the shape, the transparent level, the migration

### A.1 The manifest after the cut

```yaml
product: myctl
tasks:                     # the bodies, unchanged
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: kernel } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: kernel }, produces: { result: kernel-checked } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: kernel, evidence: kernel-checked } }
cd:
  default: dev
  environments: { dev: { backend: local } }
  site: {}                 # reserved: the location axis (central, branch-office, ...)
  deploy:
    commands: { ... }
  monitor:
    commands: { ... }
support:
  commands: { ... }
  groups: { ... }
artifacts:
  kernel: { kind: image, registry: ghcr.io/marcozwyssig, repository: simplon, dockerfile: ..., context: . }
  kernel-checked: { kind: test-result, path: build/test-results/kernel }
website:                   # was `site:`
  image: "hugomods/hugo:exts-0.148.2"
```

- **`ci:`** holds exactly the phase groups the catalogue places under it: `build`, `test`, `release`.
- **`cd:`** holds the phase groups `deploy` and `monitor`, plus three data keys: `default`,
  `environments` and `site`. A key under `cd:` is therefore a phase group if the catalogue declares it
  under `cd`, a data key if it is one of the three, and refused otherwise (diagnosis, naming both lists).
- **`support:`** is itself a group node with today's shape (`help`, `commands`, `groups`).
- **Every phase node** keeps today's group-node shape (`help`, `commands`, `groups`, ...). Only the
  wrapper changes: `groups: build:` becomes `ci: build:`.

### A.2 The catalogue declares the areas

`catalogue.yaml`'s `groups:` block becomes:

```yaml
groups:
  ci:
    transparent: true
    help: "Produce, verify and publish the artefacts."
    groups:
      build:   { help: "Produce the artefacts." }
      test:    { help: "Verify them." }
      release: { help: "Publish them." }
  cd:
    transparent: true
    env_first: true
    help: "Put them into an environment and watch them there."
    groups:
      deploy:  { help: "Put them into an environment." }
      monitor: { help: "Watch what is running there." }
  support:
    help: "Host preflight, environment introspection and host tooling."
    commands: { ... unchanged ... }
    groups:   { ... unchanged, plus `manifest` (A.5) ... }
```

- **`transparent: true`** is a new `TaxonomyNode` field. A transparent node is skipped when the CLI path is
  built: the internal path is `ci.build`, and the CLI path is `build`. Only the catalogue may declare it.
  A product writing `transparent:` is refused, the same way a product writing `taxonomy:` is refused
  today.
- **Collision.** If two transparent siblings would produce the same CLI path (`ci.x` and `cd.x`), the
  load fails with a diagnosis naming both internal paths. Today no catalogue does this. The check exists
  so the catalogue cannot do it either.
- **`env_first: true` on `cd`** is inherited by every descendant through the existing
  `group_requires_env`. That is decision 5: whatever stands under `cd:` takes an environment.
  `env_first:` written anywhere under `ci:` is refused. Measured over all eight reachable manifests, no
  manifest writes `env_first:` at all, so this costs nothing today.
- **The group lock** (`treeform.merge` rejects a path the catalogue does not declare) already refuses
  `ci: deploy:` and `cd: build:`. No new rule is needed. A test pins the message.

### A.3 si#34 learns the transparent level

`check_coordinate_placement(flat, platform_groups)` compares a coordinate's namespace with the first path
segment. After A.2 the first segment is `ci`, `cd` or `support`, and `build:image` would quietly become
a family. That is the failure si#344 measured.

The change is narrow:

- **The placement group** of a path is its **first non-transparent segment**: `ci.build.x` → `build`,
  and `support.git` → `support`.
- **`platform_groups`** is the set of first non-transparent nodes in the catalogue tree:
  `{build, test, release, deploy, monitor, support}`. That is the same six names as today, now computed
  from the tree instead of read off its top level.
- **The message** names the CLI path (`build image`), not the internal one, for the reason the function
  already gives: the reader has to find the key in the file they edit. It names the YAML location as
  `ci: build: commands: image:`.
- **See it red:** a test places `build:image` under `ci: test:` and expects the refusal. A second test
  fakes the old first-segment comparison and shows that the same manifest loads green under it. That is
  the failure this section exists to prevent.
- **The census:** `check_coordinate_placement` keeps its kind (expression rule, merged reach). Its return
  value, the count of placements ruled on, must be **equal** before and after the change over simplon's
  own manifest. A drop means the rule stopped applying to something.

### A.4 What moves, and who reads it

| Before | After | Kernel readers that change |
|---|---|---|
| `groups:` | `ci:` / `cd:` / `support:` | `orchestrator/manifest.py` (front end), `treeform` |
| `default:` | `cd: default:` | `environments.py`, `completiongen.environments_of`, `tasks/deploy.py`, `tasks/env.py` |
| `environments:` | `cd: environments:` | same |
| `env_groups:` | deleted | `manifest.py` rule 2, `treeform.check_env_groups`, `completiongen` (si#43 machinery) |
| `site:` (docs) | `website:` | `tasks/site.py` |
| `images:` | `artifacts:` with `kind: image` | part B |

Each reader moves to `context.section(document, "cd", "environments")` and the like, so that a bad outer
key is blamed by name (si#172). The refusal census walks these readers. The plan for part A must run
`tests/test_refusal_census.py` and classify every message that changes.

**`check_env_groups` and rule 2 are deleted, not adapted.** They guarded a key that no longer exists.
Their census entries go with them, which lowers the expression-rule count. That is the first time a part
of this spec deletes rules instead of adding them, and the census page should say so.

### A.5 The migration command

**One body, `support:migrate` (`simplon/tasks/migrate.py`), with two entry points:**

1. **`support manifest migrate`.** The catalogue places it in a new `support.manifest` subgroup. It
   passes the placement hurdle (si#39) on the argument that already placed `tasks:generate`: it reads no
   section that a product might lack, touches only the product's own root, and publishes nothing.
2. **`simplon manifest migrate [MANIFEST]`.** A second subcommand of `bootstrap.main` beside `init`.
   This one is needed because of the cut itself. Measured: both launcher routes exec
   `python -m <product>` (`launch.sh.j2:94`, `:264`, `:355`), and that module assembles the CLI from the
   manifest. Once `groups:` is refused, the product's CLI is never built, and `./cleon.sh support manifest
   migrate` cannot run. The package CLI loads no manifest.

**What it does, by text splice (si#110, the `toolchain scaffold` mechanism):**

- `groups: build/test/release:` → under `ci:`. `groups: deploy/monitor:` → under `cd:`. `groups:
  support:` → top-level `support:`.
- `default:` and `environments:` → under `cd:`.
- `env_groups:` → deleted. Measured values: agile-cockpit `[deploy]`, which is now the default, and
  netctl `[]`. Any value that names a group other than `deploy` or `monitor` is refused by name, because
  the new structure cannot say it.
- `site:` → `website:`.
- `images:` → `artifacts:` entries with `kind: image` (part B, B.4).
- Comments, flow style and key order survive.

**Before a byte is written,** the result is parsed back, lowered to the internal tree, and compared with
the lowering of the original. The command tree, the resolved tasks and every moved data section must be
identical. If they are not, nothing is written, and the difference is named.

**Its outcomes are three, and they stay three** (the house defect):

| Outcome | rc | Message |
|---|---|---|
| migrated | 0 | names each section it moved |
| already in the new form | 0 | "already in the ci/cd form - nothing to migrate", which is a different line, not the same green |
| cannot migrate | 1 | names the construct, and nothing is written |

### A.6 The diagnoses in the cut (decision 11)

Each of these is a **diagnosis**. Without it, the old key would be silently ignored, because
`_ManifestModel` has `extra="ignore"`:

| The manifest has | The message says |
|---|---|
| top-level `groups:` | the new form, with a three-line example, plus both migration commands |
| `env_groups:` | `cd` is env-first now; delete the key; migrate does it |
| top-level `default:` / `environments:` | they live under `cd:` |
| top-level `site:` with `image`/`base_url`/`theme` | it is `website:` now |
| `images:` | it is `artifacts:` with `kind: image` |
| no command under `ci:`, `cd:` or `support:` | "declares no commands under ci:, cd: or support:" replaces "manifest defines no groups" |

The migration line in these messages names **both routes**, because the reader may be on either:

```
  venv:      deploy/orchestrator/.venv/bin/simplon manifest migrate cleon.yaml
  container: docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/src" -w /src \
               ghcr.io/marcozwyssig/simplon:<pin> simplon manifest migrate cleon.yaml
```

The orchestrator directory and the pin are filled from what the product's launcher declares
(`LAUNCH_ORCH_DIR`, `LAUNCH_IMAGE_PIN`), so each message is a line the reader can copy. Each message text
is pinned by a test against the real output, because a quoted error text is a second source.

**The top-level `site:` diagnosis is conditional:** it fires only when the section carries one of the
docs keys. A `site:` without them is still refused, because after the cut the location belongs under
`cd:`, but with a different message. That keeps the two meanings of `site:` from sharing one diagnosis.

### A.7 The bill, measured over the eight reachable manifests

- **Every manifest's text** changes: the `groups:` wrapper, and the `default:`/`environments:` move in
  seven of them (simplon has no `environments:`).
- **`site:` → `website:`** in simplon, firn, cleon and biz-cockpit.
- **`env_groups:`** in agile-cockpit and netctl.
- **No typed command changes.** That is decision 1, and the part A plan holds it with a CLI-surface
  golden per manifest: the assembled command tree is byte-identical before and after migration, for all
  eight manifests fetched through the API.

---

## Part B: artifacts

### B.1 One section, every entry has a kind

```yaml
artifacts:
  <name>:
    kind: <kind>          # required
    path: <under output:> # where it lies once built; optional for kind image (B.3)
    registry: <host/ns>   # present once the artifact is published
    ...                   # kind-specific keys, unchanged from today
```

- **The name** is what `produces:`/`consumes:` refer to (part C).
- **`path:`** lies under the product's `output:` (si#314) and is what `upload-artifact` carries.
- **`registry:`** is decision 6: a build intermediate and a release artifact are the same kind of thing,
  and the second has been published.

### B.2 The kinds belong to the catalogue

`catalogue.yaml` gets a section `kinds:`:

```yaml
kinds:
  artifact:  {}                       # the root every kind refines
  image:     { refines: artifact }
  directory: { refines: artifact }    # release:artifact (cleon's p2 update site)
  site:      { refines: directory }   # docs:site's built website
  nuget:     { refines: artifact }
  maven:     { refines: artifact }
  conan:     { refines: artifact }
  test-result: { refines: artifact }  # what a test produces (decision 12, C.3)
  release-notes: { refines: artifact } # generated notes for one version (C.4)
  tag:       { refines: artifact }    # a cut tag: a value, no path (C.4)
  release:   { refines: artifact }    # the bundle a release aggregate stands for (C.4)
```

- **The set is measured.** These are the kinds that today's `artifacts:`/`images:` readers already
  distinguish by which task reads them: `release:artifact`, `release:nuget`, `release:maven`,
  `release:conan`, `build:image`/`test:image`/`release:image` and `docs:site`. Nothing is added in advance.
- **`test-result`, `release-notes`, `tag` and `release` are the kinds no reader distinguishes today.**
  They are added because decisions 12, 14 and 15 need them, not in advance (C.3, C.4).
- **A product cannot declare kinds.** The catalogue owns the vocabulary, which is the point of
  prescribing it (memory: "the terms have to be PRESCRIBED across products").
- **`kind:` naming an unknown kind** gets a diagnosis that lists the catalogue's kinds.

### B.3 `kind: image`

An image entry keeps every key `images:` entries carry today: `registry`, `repository`, `dockerfile`,
`context`, `platforms`, `contexts`, `build_contexts`, `name`, `tag`. `path:` is **optional** for an
image. When present, it is an OCI archive under `output:`, and only then can an image cross a job
boundary (C.6).

**netctl's bare strings** (`web: netctl:local`, ten of them) are not mappings. The migration rewrites each
as `{ kind: image, local: "netctl:local" }`. `local:` is the one new key: a locally tagged image that no
kernel task builds or publishes.

### B.4 What the fold costs, measured

- **Kernel:**
  - `tasks/image.py` (`SECTION = "images"`) reads `artifacts:` filtered to `kind: image`.
  - `deployment.SOURCE_SECTIONS` becomes `("artifacts",)`, and `deploy: source: { images: app }`
    becomes `{ artifacts: app }`. The migration rewrites that too, in biz-cockpit and firn.
  - `tasks/artifact.py`, `conan.py`, `nuget.py` and `maven.py` check that the named entry has their kind.
    A mismatch is a diagnosis.
- **cleon's `updatesite`:** `source:` becomes `path:` and it gains `kind: directory`. `tasks/artifact.py`
  reads `path:`, and `source:` is refused with the rename in the message.
- **Product code. This is the real bill, and it is not one line.** Measured on 2026-10-11 through GitHub
  code search, product code reads `images:` raw:
  - netctl: `deploy/provision/orchestrator/src/python/orchestrator/paths.py:60`. Ten names are read
    there, and the search returns about twenty more files that mention images.
  - biz-cockpit, agile-cockpit and firn each have an `orchestrator/paths.py` that the same search
    returns.

  After the fold, each of those reads `artifacts:` and filters by kind, or reads `local:` instead of a
  bare string. **Before part B ships, each of those four products names its own cost**, through its peer
  session (memory: peer sessions are the measurement). The spec does not guess the number.

---

## Part C: ports, produces/consumes, test results, the workflow generator

### C.1 Ports on tasks (filter types)

A catalogue task, or a product task, may declare ports:

```yaml
  build:image:
    impl: simplon.tasks.image:build
    output:
      image: { accepts: image, param: name }
  test:image:
    impl: simplon.tasks.image:test
    input:
      image:  { accepts: image, param: name }
    output:
      result: { accepts: test-result, param: results }
  release:image:
    impl: simplon.tasks.image:publish
    input:
      image:    { accepts: image, param: name }
      evidence: { accepts: test-result }
```

- **`accepts:`** names a kind. A port accepts that kind and every kind that refines it.
- **`param:`** is optional. It names the body parameter that receives the artifact's **name** at run
  time. This is the only way an artifact reaches a body. It is a binding, not a freshness check, so
  decision 2 holds.
- **A port without `param:`** is checked and generated only. That is the generic case:
  `toolchain:run` declares `input: { source: { accepts: artifact } }` and
  `output: { out: { accepts: artifact } }` and receives nothing.
- **Which catalogue tasks get ports** is measured from the tasks that today take a `name` selecting an
  `artifacts:`/`images:` entry, plus `docs:site` (output `site`) and `toolchain:run`. Every other task has
  no ports, and a command naming `produces:`/`consumes:` on it gets a diagnosis.

### C.2 Commands (filter instances)

```yaml
image: { task: "build:image", produces: { image: kernel } }
```

- **`produces: { <port>: <artifact> }`** and **`consumes: { <port>: <artifact> | [<artifact>, ...] }`**.
  This is the one form; there is no list shorthand (#33).
- **Several inputs and several outputs are the normal case, not an extension** (decision 14). A task has
  as many ports on each side as it needs, and a command binds each one. `release:image` consumes the
  image *and* its test results. A product's build step may produce a binary *and* a report.
- **`produces: { image: kernel }` replaces `with: { name: kernel }`.** Both on one command is a second
  source for one fact and is refused (expression rule, see C.7). The migration rewrites `with: name:`
  into the port binding wherever the task's port has `param: name`.
- **An aggregate (`depends_on`)** has no ports. Its outputs are derived as the union of its members'
  `produces` (firn: SelectorRelation `self.member.produces`), and nothing is stored. The one aggregate
  that names an output of its own is the release (C.4), and even its content is derived.

### C.3 Test results (decision 12)

Concept rule 2 says a test takes an artifact and produces one, and a release takes the *tested* one. The
artifact a test produces is **its own**: a test result, not a relabelled copy of what it tested.

- **A test result is an ordinary artifact**, declared in `artifacts:` with `kind: test-result` and a
  `path:` under `output:` (JUnit XML, Allure results, a verdict record, whatever the body writes). It has
  exactly one producer, like every artifact.
- **What a test result is ABOUT is derived, never declared:** it is about every artifact its producer
  consumes. A `subject:` key beside it would be a second source for what `consumes:` already says, and
  could disagree with it.
- **It is produced only under `ci: test:`.** A test result built anywhere else is not evidence of a test.
- **The body writes it.** A task whose output port accepts `test-result` declares `param:` on that port
  and receives the path to write to. A test result that is declared but never written would be
  "nothing to do" passing for "tested", which is the house defect, so a producer that exits 0 without
  writing its path is a failed step (rc 1, naming the path). Measured in the plan for C: which test
  tasks already write results (`test:gate` writes Allure results through `results_from:`; `test:image`
  writes nothing today and gains a small verdict record: argv, platform, rc, expected rc).
- **The release rule:** a command under `ci: release:` that consumes an artifact X must also consume
  **every** test result about X that the manifest produces, and **at least one** must exist. "At least
  one" makes an untested release impossible. "Every" makes it impossible to release past a failing test
  by leaving its result out. Its port for this is `evidence: { accepts: test-result }`, and it has no
  `param:`: the body does not read the results, it is ordered after them and the pipeline carries them.
- **No test needs to be a `test:image`.** Any test task whose producer consumes X counts: a `test:gate`,
  a `toolchain:run` test, a product's own suite. What does not count is a test of something X was merely
  built from: the source passing its unit tests says nothing about the image built from it, so "about"
  is direct, not transitive.

**What it costs, measured over the eight manifests:**

| Manifest | release of an image/artifact | tests on it | Change |
|---|---|---|---|
| firn | `release push-image` (firn) | 6 × `test:image` on `firn` | six `test-result` entries (one per test, one producer each), and `push-image` consumes all six as evidence |
| simplon | `release image` (kernel) | none | **add one test that consumes `kernel` and writes a test result**, e.g. `test:image` running `simplon --help` in the image, rc 0. Which task is simplon's choice |
| agile-cockpit | `release image` (app) | none | **add one test on `app` that writes a test result.** Its cost is named by its peer session before this ships |
| biz-cockpit | `release release` = aggregate over `build`, `publish` | measured in the plan for C | to be listed from the resolved tasks behind `publish` |
| cleon, asbundle, netctl, swi | no `release:image`/`release:artifact` placed under these names | — | measured again from the resolved tree in the plan for C, because a product task can wrap a catalogue body |

The rule binds the kernel with the product: simplon's own `release image` is refused until simplon tests
its image. That is intended. A step never run in its own house rots unseen.

### C.4 The release: one aggregate, several outputs, one bundle (decisions 14, 15, 16)

A release does three things: it **generates the release notes**, **puts the artifact into the
registry** and **cuts a tag**. Those are three leaves under one aggregate, because a command either runs
a body or plans others (`impl XOR depends_on`), and each of the three already fails differently today.
A tag that is cut while the push failed has to stay visible as exactly that.

```yaml
ci:
  release:
    commands:
      notes: { task: "release:notes", produces: { notes: kernel-notes } }
      image: { task: "release:image", consumes: { image: kernel, evidence: kernel-checked } }
      tag:   { task: "release:tag",   consumes: { notes: kernel-notes }, produces: { tag: kernel-tag } }
      all:
        depends_on: [notes, image, tag]
        produces: { release: kernel-release }
artifacts:
  kernel-notes:   { kind: release-notes, path: build/release/notes.md }
  kernel-tag:     { kind: tag }
  kernel-release: { kind: release }
```

- **`release:notes`** is a new catalogue task (decision 16). It writes the notes for the version being
  released, generated from the merges and the tickets they close since the previous tag, to its
  `release-notes` output. The reading half already exists: `tasks/releasenotes.py` (`test:release-notes`)
  walks exactly that range, merge by merge, to check a hand-written page. Generation reuses that walk,
  and it does not grow a second one.
- **The publish leaf** (`release:image`, `release:artifact`, `release:nuget`, `release:maven`,
  `release:conan`) consumes the artifact and its test results (C.3) and produces nothing new. A published
  artifact is the same artifact with its `registry:` (decision 6).
- **`release:tag`** consumes the notes and produces a `tag`. A `tag` has no `path:`, because its value is
  the tag name, and it is never uploaded.
- **The bundle.** The aggregate under `ci: release:` may name **exactly one** output of `kind: release`.
  It is the only aggregate that names an output, and the bundle's *content* is still derived and never
  stored: the notes and the tag its members produce, plus every artifact its publish leaves consumed,
  each with its `registry:`. That is firn's SelectorRelation, given a name so that a deploy can refer to
  it.
- **Order inside the aggregate** is still `depends_on` (decision 2). C.5 rule 8 refuses a list that runs
  `tag` before a publish leaf of the same aggregate. A tag for a release whose artifact never reached the
  registry would be a public statement that is false.
- **A deploy consumes the bundle:** `deploy: { consumes: { release: kernel-release } }`.
  `deployment.source` points at the `release` artifact, and the version selector (`1.4.0`, `latest`,
  `local`, si#235) chooses which release of it. That is firn's "Deploy consumes a Release".

**The hand-written releases page** (simplon's `releases:` section, with `test:release-notes` as its guard)
is not deleted by this spec. Generated notes name every ticket in their range by construction, which is
what the guard enforces on prose. A product with a `releases:` page keeps the guard, and the plan for C
measures which of the eight manifests have such a page before anything about it changes.

**What it costs:** simplon, agile-cockpit and firn place `release:tag` and `release:image` today as
separate commands, and none of them has an aggregate over them (measured, C.3 table). Each gains
`notes`, the aggregate and three `artifacts:` entries. The migration does not write these, because
nothing in today's manifest says which publish leaves belong to which release.

### C.5 Load-time rules

All of them run over the merged tree, before `resolve`:

1. **One producer per artifact.**
2. **No consumer without a producer**, unless the artifact has a `registry:`. An external input (si#343:
   a docker image built from a released jar) is a consumed artifact that this manifest does not produce
   and that can be fetched.
3. **Kind conformance:** each bound artifact's kind conforms to its port's `accepts:` through `refines`.
4. **Port names exist on the task.**
5. **No aggregate plans a consumer before its producer** when both are in its plan. The run-time order
   is still `depends_on` (decision 2). This rule only refuses a `depends_on` that contradicts the data.
6. **The release rule** (C.3): a release consuming X consumes every test result about X, and at least one
   exists. Test results are produced only under `ci: test:`.
7. **No `with:` on a parameter that a port binds** (C.2).
8. **The bundle:** only an aggregate under `ci: release:` names an output, and only one `kind: release`
   (C.4). A `release:tag` member must come after every publish member in `depends_on`.

### C.6 The workflow generator

`workflowgen.py` contains no `upload-artifact`/`download-artifact` today (measured, si#344). From the
derived edges:

- **Producer and consumer in different jobs:** the consumer's job gets `needs: [<producer job>]` plus a
  `download-artifact` step. The producer's job gets an `upload-artifact` step for the artifact's `path:`.
- **Producer and consumer in one job:** nothing is generated. The files are already there.
- **`kind: image` with no `path:` across a job boundary:** diagnosis, naming both jobs and the fix
  (give the image a `path:` so it is exported as an OCI archive, or put both commands in one job). An
  image in one job's docker daemon is not in the next job's unless the runner happens to be shared,
  which is exactly the kind of green that holds by accident.
- **`derive:` jobs** (si#267) use the same edges to order the derived steps.

Simplon's own CI is one job, so its generated `ci.yml` stays byte-identical. A test holds that too.

### C.7 Census classification

Each new refusal in parts A–C is entered in `tests/test_refusal_census.py` with its kind before the
plan that adds it is merged:

| Refusal | Kind | Reach |
|---|---|---|
| A.6 table (old keys) | diagnosis | — |
| unknown key under `cd:` | diagnosis | — |
| transparent CLI-path collision | diagnosis | merged (binds the catalogue) |
| `transparent:` written by a product | expression rule | platform/product seam |
| `env_first:` under `ci:` | expression rule | merged |
| unknown kind | diagnosis | — |
| artifact kind ≠ the task reading it (B.4) | diagnosis | — |
| C.5 rules 1, 2, 3, 4 | diagnosis | merged |
| C.5 rule 5 (aggregate contradicts data) | diagnosis | merged |
| C.5 rule 6 (release consumes every test result about X, at least one) | **expression rule** | merged, binds the kernel (simplon must add a test) |
| test result produced outside `ci: test:` | expression rule | merged |
| test producer exits 0 without writing its result path | diagnosis (run time) | — |
| C.5 rule 7 (`with:` beside a port binding) | expression rule | merged |
| C.5 rule 8: an aggregate output other than one `release` bundle under `ci: release:` | expression rule | merged |
| C.5 rule 8: tag ordered before a publish member | diagnosis | merged |
| image without `path:` across jobs | diagnosis | — |

`check_env_groups` and rule 2 leave the census (A.4).

---

## Part D: the manifest in firn

### D.1 Two M2 packages, owned by simplon

Decision 10 puts the **whole manifest** into firn, not only the pipeline.

- **`simplon.pipeline`** follows firn's sketch (si#346), with the additions above:
  - **ArtifactKind** has `refines`. `test-result` is one ArtifactKind among the others.
  - **Port**, **Task** (`body`, `input`, `output`), **Artifact** (`path`, `kind`, `registry`), plus
    **TestResult** extends Artifact, with `about` as a SelectorRelation over its producer's `consumes`
    (derived, never stored, as C.3 requires). **Release** extends Artifact, and its `notes`, `tag` and
    `published` are SelectorRelations over the producing aggregate's members (C.4).
  - **Command** is abstract. **TaskCommand** has `task`, `consumes` and `produces`.
    **AggregateCommand** has `member` and `produced` (SelectorRelation). **ReleaseCommand** extends it
    with `release` (composition of Release, 1..1), which is C.4's one named output.
  - **Area**, an Enum `ci | cd | support`, and **Group**. A Group belongs to an Area, and `transparent`
    is a property of an Area, not of a Group.
  - **Environment** has `next`, the promotion order, which is an association and not a list position.
    **Site**, **Registry**, and **Deploy** (extends TaskCommand, with `environment` 1..1 and `site`
    0..1). `site` stays 0..1 until a body reads it (see "What this is NOT").
- **`simplon.manifest`** imports `simplon.pipeline` and models every top-level section **the kernel
  reads**: `product`, `tasks`, `ci`/`cd`/`support`, `artifacts`, `website`, `suites`, `releases`,
  `tracker`, `workflows`, `generated`, `claude`, `nexus`, `carriers`, `deploy`, `lab_egress`,
  `instance`, `output`, and the rest.
  - **The list is not typed here,** because a typed list is wrong on the first day nobody checks it. The
    package covers exactly the sections the refusal census's derived reader population reads, and a test
    compares the two in both directions. A kernel reader with no class turns it red, and so does a class
    with no reader.
  - **Product-owned sections** (asbundle's `jdk:`, netctl's `topology:`, swi's `esxi:`, cleon's
    `build:`/`release:` data, ...) are not modelled. They are exported as one opaque `ProductData` entry
    per key, so the model never claims to understand what only the product reads.

### D.2 The bridge: `support manifest model`

- **The command:** a new catalogue task, `support:model`, placed under `support manifest` as `model`.
  It writes the **parsed and validated** manifest as an M1 `.firn` file. Its default location is
  `<output>/model/<product>.firn`, and `with: { output: ... }` overrides it.
- **simplon owns the parse and the validation.** firn gets no YAML importer, as firn advised.
- **It runs only after `manifest.load` has accepted the manifest.** A manifest the kernel refuses
  produces no model and passes on the refusal's rc, so "no model because it is broken" never reads as
  "no model because there is nothing to model".
- **Diagrams:** `firn diagram` over the output draws the chain.

### D.3 Checking it

- **The M2 packages live in this repository** under `model/`, with its own `firn.toml` at the top (firn
  expects the project at the mount root, si#371), and simplon places `test model: { task: "toolchain:run", with: { profile: firn,
  command: check } }` (si#371's done-when).
- **A drift gate in CI** regenerates `simplon.firn` from `simplon.yaml` and runs `firn check` over it.
  rc 0 is the only green. firn's exit codes are 0/1/2/3/70, and the gate compares against 0, never
  against 1.
- **None of firn's `.firn` sketch has been run through `firn check`** (firn says so itself). The plan for
  D starts by running it, and every parser disagreement goes to firn as a finding, not as a local patch.
- **Depends on si#371.** firn is paused until 2026-10-13.

---

## Order of work (decision 13)

| Plan | Content | Ships | Depends on |
|---|---|---|---|
| A | shape, transparent level, si#34, readers, migration (A.5), diagnoses (A.6), env_groups deleted | together with B in **one** kernel release, which is the cut | — |
| B | `artifacts:` + `kinds:`, `images:` folded, kind checks, migration extended | same release as A | A; the four products' named costs (B.4) |
| C | ports, produces/consumes, test results, the release aggregate and `release:notes`, load rules, workflowgen hand-off | the next release; additive except for the release rule | B; agile-cockpit's cost for its test |
| D | `simplon.pipeline` + `simplon.manifest`, `support manifest model`, drift gate | after C | si#371, firn back from pause |

A and B ship in one release because they share the cut. Two cuts would mean migrating every manifest
twice and refusing twice. C adds keys, so a migrated manifest without them still loads, with one
exception: the release rule refuses an untested release. That refusal is part of C's release
notes, and agile-cockpit is asked before C ships, not after.

## Testing, per CLAUDE.md

- **See it red, for every rule:** each refusal above has a test that loads a violating manifest and pins
  the real message. Each "keeps working" claim (CLI-surface golden, si#34 count, simplon's `ci.yml`) has
  a test whose broken variant goes red: an old si#34 comparison, a migration that drops a comment, a
  generator that forgets `needs:`.
- **The migration over all eight real manifests:** they are fetched through the API in the plan for A
  and kept as fixtures. For each one, `migrate` writes, the result loads, and the CLI-surface golden is
  identical.
- **The census:** `tests/test_refusal_census.py` is green with every new entry classified, and
  `with-what/rules.md` is regenerated, not edited.
