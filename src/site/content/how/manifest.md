---
title: "The manifest"
weight: 4
aliases:
  - "/building/manifest/"
---

## The file, at a glance

The whole top level of a manifest, and where each part is explained:

```yaml
product: myctl            # the product's name
tasks:                    # the BODIES, each a module:function, declared once
ci:                       # the COMMAND TREE's integration half - build, test, release
cd:                       # the delivery half - deploy, monitor - and the environments they run in
support:                  # host preflight and tooling, beside the loop rather than in it
website:                  # ... and any other product data section a catalogue task reads
```

| what you want to do | where |
|---|---|
| add a command, or a sub-group | [The command tree](#the-command-tree) |
| point a command at a body | [`task:`, and what the command adds](#task-and-what-the-command-adds) |
| place the same body twice with different values | [Pinning values with `with:`](#pinning-values-with-with) |
| rename or re-help a command the catalogue placed | [Refining a platform command](#refining-a-platform-command-and-replacing-one) |
| make one command run several others | [Aggregates: `depends_on`](#aggregates-depends_on) |
| run steps side by side | [`parallel`](#parallel-the-one-key-that-suspends-list-order) |
| declare the environments a product deploys to | [Environments](#environments) |
| give a catalogue task its values | [Product data sections](#product-data-sections) |
| find out whether a name is already taken | [The names the kernel has claimed](#the-names-the-kernel-has-claimed) |
| move an old flat manifest onto the tree | [The flat form](#the-flat-form-and-how-to-leave-it) |

Two rules hold everywhere below, and most load errors are one of them: **a command never writes
`impl:`** - it names a `task:` and the body is declared once - and **the platform owns which groups
exist**, so a product adds to a group and never rewrites its `help:` or its `env_first:`.

---

One YAML file per product. It declares what commands exist, what they run, what they are called and
which of them take an environment - and the CLI is assembled from it, so there is no second place where
any of that is also true.

## The command tree

Groups are slots in the CI/CD loop; commands are the members of a group. The kernel's catalogue owns
which groups exist - `build`, `test` and `release` under `ci:`, `deploy` and `monitor` under `cd:`, and
`support` on its own - and a product fills them:

```yaml
product: myctl

ci:
  build:
    commands:
      wheel: { task: "pkg:wheel", help: "Build the wheel." }
support:
  groups:
    git:
      commands:
        commit: { task: "vcs:commit" }
```

`ci` and `cd` are **areas**, not groups: they say which half of the loop a phase belongs to, and they never
appear on the command line. The command above is `myctl build wheel`, exactly as it would be without them.

A group node a product writes has four keys: `help`, `env_first`, `groups` and `commands`. A fifth,
`transparent`, is the catalogue's alone - it is what makes `ci` and `cd` areas - and a product that writes
it is refused. Members live under
`commands:` rather than directly on the node, and that is not tidiness - without it `help:` would be a
group attribute in one place and a command called "help" in another.

**The platform owns the group shape.** A product may *add* commands and sub-groups to a group it
inherits. It may not rewrite that group's `help:` or its `env_first:`. Both are statements about what
the group *is*, and `env_first` in particular is load-bearing: a product quietly turning it off would
ungate every command underneath it. The group lock is not a check layered over the merge - it is the
merge. There is one tree, so there is no second way to bring a group into existence.

**A group you name is a promise.** Declare a group in your own tree and leave it without a single
command anywhere in its subtree, and the manifest fails to load, naming the group. A group only the
*catalogue* offers, that your tree never mentions, is simply dropped from the assembled CLI - see [the
rule](../../with-what/rules/#a-group-with-no-commands-does-not-appear) and why both halves are needed.

## `task:`, and what the command adds

Every command is an **instance** of a task: the task carries the body, the command carries the name, the
group and the values pinned for this placement. That model, its five refusals and the two name spaces the
colon tells apart are [a chapter of their own](../task-and-command/); what follows is only what the
*manifest file* looks like once you have it.

```yaml
tasks:
  wheel:
    impl: "orchestrator.cli:build_wheel"
    help: "Build the wheel."

ci:
  build:
    commands:
      wheel: { task: "wheel" }
```

A command never writes `impl:` itself. A bare `task:` value names a task this manifest declares; one with
a colon names a catalogue coordinate, whose body lives in the kernel.

## Pinning values with `with:`

The same body, placed twice, with different data:

```yaml
ci:
  test:
    commands:
      unit:   { task: "test:gate", with: { name: "unit" },   help: "Run the unit suite." }
      system: { task: "test:gate", with: { name: "system" }, help: "Run the system suite." }
```

A pinned parameter is removed from the generated signature and supplied at call time, so it is absent
from the command line entirely: `myctl test unit --name system` is not a command.

`params:` is the other half, and it is strictly about **presentation**: help text, the short flag, the
metavar, the order the declarations render in. The signature - name, type, default - is read off the
body. Declaring the type in YAML as well would state it twice and let the two drift, which is the exact
failure `impl:` on a command already has.

```yaml
prune-branches:
  task: "vcs:prune-branches"
  params:
    dry_run: { help: "preview only", short: "-n" }
    remote:  { help: "also delete merged branches on origin" }
```

## Binding artifacts: `produces:` and `consumes:`

A task that takes or gives an artifact has **ports**, listed with the kind each accepts on
[the kinds page](../../with-what/kinds/). A command binds each port to an `artifacts:` entry:

```yaml
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: kernel } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: kernel } }
artifacts:
  kernel: { kind: image, registry: ghcr.io/me, repository: kernel, dockerfile: Dockerfile, context: . }
```

A port with a parameter hands the artifact's name to it. This replaces `with: { name: kernel }`, which
still loads and is read as the same binding. `simplon manifest migrate` rewrites it, and writing both is
refused, because the two say one thing twice. A task of your own declares its ports beside its `impl:`:

```yaml
tasks:
  pack:
    impl: "orchestrator.cli:pack"
    input:  { site: { accepts: site } }
    output: { bundle: { accepts: directory, param: name } }
```

The loader holds every binding before anything runs:

- the port exists on the task, on the side the key binds;
- the artifact is declared, and its kind is the port's or refines it;
- something produces what a command consumes, or the artifact names a `registry:` it is fetched from;
- no aggregate plans two producers of one artifact, or a consumer before its producer - or beside it, in
  two branches of a `parallel: true` fan, where listing the producer first does not help.

Several commands may produce one artifact (an everyday single-platform build beside the release's
all-platform one); a plan picks one.

### A release consumes its test results, and names one bundle

A release is the chain the bindings draw: build produces the image, a test consumes it and produces a
`test-result`, the publish consumes the image and the result as its `evidence`, and an aggregate under
`ci: release:` names the bundle.

The evidence is **read before anything is published** (si#434). The load checks that every test result a
release needs is bound to it. At run time, the wrapper around every command body reads each bound record
before the body runs, and calls the body only when all of them are green. There are three refusals, each in
its own words:

- **not written:** "... has not been written - the test that produces it has not run here"
- **red:** "... is red: verdict 1 - its `runs` say which run failed"
- **no verdict:** "... holds no verdict - a release reads a JSON record with an integer `verdict` ..."

A record is the JSON that `test:image` writes, with an integer `verdict` (0 is green). Each of its runs
names the reference it tested and the daemon id that reference had, and a green record without them is
refused too:

- **no subject:** "... is green but does not name what it tested - every run needs its `reference` and `id`; ..."

`release:image` then compares the record with what it would push (si#439), so a green record left from an
earlier build no longer reads as green:

- **never tested:** "... was never tested: the evidence ran ..." - the record is about another tag
- **rebuilt since:** "... was rebuilt after it was tested: the test ran ..., and it is ... now"

This is simplon's own `simplon.yaml`:

```yaml
ci:
  test:
    commands:
      image:
        task: "test:image"
        consumes: { image: kernel }
        produces: { test-result: kernel-checked }
        with: { argv: "simplon --help", expect: "usage: simplon" }
  release:
    commands:
      notes: { task: "release:notes", produces: { release-notes: kernel-notes } }
      tag: { task: "release:tag", consumes: { release-notes: kernel-notes }, produces: { tag: kernel-tag } }
      push-image:
        task: "release:image"
        consumes:
          image: kernel
          evidence: [kernel-checked]
      all:
        depends_on: [notes, push-image, tag]
        passes: [tag]
        produces: { release: kernel-release }
        stop_on_failure: true
artifacts:
  kernel-checked: { kind: test-result, path: build/test/kernel-image.json }
  kernel-release: { kind: release }
```

Two rules hold the chain (the kinds page has [the ports](../../with-what/kinds/#ports)):

- **Rule 6.** A release command that consumes an artifact must bind every test result about it to `evidence`.
  A test result is about what its producer consumes, directly. With no such test the load refuses: "... and no
  test produces a result about it - add a command under `ci: test:` ...". With one left unbound it refuses:
  "... so no release goes past a test that ran". The four kinds a release produces about itself
  (`test-result`, `release-notes`, `tag`, `release`) need no evidence.
- **Rule 8.** Only an aggregate under `ci: release:` names an output, and it names exactly one, a
  `kind: release` artifact. The load refuses "... only an aggregate under `ci: release:` does" and "... a
  release aggregate names exactly one output", and it refuses a plan that lists `release:tag` before a publish
  ("... a tag cut before the push it announces ..."), because a public tag is false if the push fails. It
  also refuses a release aggregate without `stop_on_failure: true` ("... leaves `stop_on_failure` false"):
  the order holds at run time only if a failed member stops the plan.

`release all` **states** the release - its members, its bundle and their one safe order, checked at load -
and with `stop_on_failure` a failed leaf stops the plan. With [`passes: [tag]`](#passes-what-an-aggregate-hands-its-leaves)
it is also a release you can run: `./simplon.sh release all --tag v0.32.0` hands the tag to every member that
takes one. simplon's own `release.yml` is the first workflow derived from such an aggregate (si#491):
`release: release all` makes it the dispatch release, whose job runs the test leaves, the notes and the
tag in this order, so a red test leaves no tag behind. Typed in a checkout, `release all` still ends by
pushing the tag - and for simplon nothing then publishes it, because only the button does; if `main`
moves before the button is pressed, that version is refused there as taken. PyPI, the site and the image publish in product
jobs after it, and a publish that fails there is finished by rerunning that job.

## Refining a platform command, and replacing one

A command the catalogue already places can be refined in the product's own tree: change its `help:`, add
`params:`, pin a `with:`. Point it at a *different* `task:` and the loader stops, naming both bodies by
their real `module:function` and offering `override: true` as the explicit yes. That refusal has [its own
rule](../../with-what/rules/#a-name-collision-breaks-loudly), and the merge behaviour behind it is in [Task and
command](../task-and-command/#refinement-and-deliberate-replacement).

## Aggregates: `depends_on`

A command with no body, only a plan:

```yaml
all:
  help: "Build then deploy, end to end."
  depends_on: [build, up]
  stop_on_failure: false
```

`impl` and `depends_on` are mutually exclusive. A command is either a leaf with a body or an aggregate
that plans other commands - never both. The reason is mechanical: plan steps execute as subprocesses, so
an impl-bearing command that also carried dependencies would re-expand them in the child and break the
run-each-once guarantee.

The plan is a post-order depth-first walk over `depends_on`, deduplicated by name, so a command reached
along several paths appears exactly once. **List order is execution order** among siblings, and that is
how one step is made to run before another:

```yaml
docs:
  help: "Write the command reference, then build the website from it."
  depends_on: [reference, site]
```

`reference` writes the page that `site` reads. Nothing in the list says so except the order, and that is
deliberate: the same fact written twice - once as an order, once as an edge - is a second source that can
drift.

### `parallel`: the one key that suspends list order

Because position is the only statement of order, a command whose dependencies genuinely do *not* need
each other has to say so:

```yaml
images:
  help: "The five device images."
  depends_on: [sidecar, frr, vyos, ios, radius]
  parallel: true
```

Those five subtrees then run at the same time, and whatever follows `images` in its own parent's list
starts only when every one of them is done. That is the join, and it needs no new key: `depends_on`
already means "after", and `parallel` is the one place it stops meaning it.

**It is declared and not derived, and that was measured.** A dependency graph already states what must
come after what, so deriving parallelism from it - everything unconnected runs at once - looks like the
better answer. Over the six manifests simplon can reach, 541 pairs of planned steps have no edge between
them and **466 of those would break if they ran together**: the orders those manifests rely on are
written as list position, not as edges. Deriving would have run a website build before the page it
publishes, a packaging step before the thing it packages, and a gradle build inside an image that did not
exist yet.

Two things it does not change. A branch is still a chain - `parallel` applies to the dependencies of the
command that declares it, not to what is inside them - and `stop_on_failure` still decides what a failure
skips. A step already running when a sibling fails is left to finish rather than killed, because a killed
subprocess exits non-zero and that number cannot be told from the step having failed on its own; the
members of one fan are never skipped for each other, since the declaration says none of them needs
another; and the work after the join is skipped in the ordinary way.

The loader holds that declaration to the data. A fan whose branches consume what another branch produces
is refused at load (si#419), because its consumer may start before the artifact is written. That holds
even when the consumer's own branch lists the producer first: a command is planned once, at its first
place in the plan, so the producer runs in the other branch and the consumer's branch does not wait for it.
Plan the producer ahead of the fan instead.

How MANY run at once is the machine's answer rather than the manifest's, because the manifest travels
between machines and the number does not: `SIMPLON_MAX_PARALLEL` sets it, and the default is four or the
CPU count, whichever is smaller.

WHICH RUNNER draws the plan is the machine's answer too, and asking for the plain one is `--no-tui`. That
belongs with what a run looks like rather than with what a manifest declares: [Running a
command](../running/).

### `passes`: what an aggregate hands its leaves

Every leaf of a plan runs as its own subprocess, `./<product>.sh <group> <command>`, so an aggregate has no
way to give a leaf a value except on that leaf's command line. `passes:` names the parameters an aggregate
takes on its own command line and hands on:

```yaml
all:
  depends_on: [notes, push-image, tag]
  passes: [tag]
```

`./simplon.sh release all --tag v0.32.0` then runs `release notes --tag=v0.32.0`, `release push-image
--tag=v0.32.0` and `release tag -- v0.32.0`. Each leaf gets the value in its own form: `release tag` requires
its tag, so there it is a positional argument. A leaf whose body does not take the parameter gets nothing,
and so does a leaf that pins it with `with:`. The option is required on the aggregate where any leaf that
takes it requires it, so a missing `--tag` is refused before anything runs.

It is declared, not derived from the leaves' parameter names, because a shared name is not a shared
meaning. `name` is the notes file on one release leaf and the image on the next, and forwarding by name
would hand one value to both. Assembling the CLI refuses a passed name that no planned leaf takes
unpinned. The load refuses `passes:` on a leaf, because a leaf plans nothing to pass it to. A generated
CLI module refuses it too, because its dispatcher takes only a command name. A product with its own step
factory gives it an `args` keyword; `run_command` refuses a factory without one before anything runs.

Every `depends_on` entry must name a known, unambiguous command, and the graph must be acyclic. Both are
checked at load, not at run: a dependency naming a command that does not exist is a manifest error, and
it should not wait until the eleventh minute of a pipeline to say so.

`hidden: true` keeps a command out of every `--help` listing while leaving it fully invocable - which is
what a plan step named in a `depends_on` needs, since it must be a real command but need not clutter a
menu meant for a human.

## Environments

```yaml
cd:
  default: dev
  environments:
    dev:  { backend: local,    description: "Local development environment." }
    prod: { backend: exoscale, description: "Production." }
  deploy:
    commands:
      up: { task: "up" }
```

The environment matrix stands under `cd:`, beside the commands that run against it. What stands under
`cd:` takes an environment and nothing else does: the catalogue's `cd` node is env-first as a whole, so
`deploy` and `monitor` are gated the same way in every product and no manifest has to say it. A group
under `ci:` that declares `env_first:` is refused - a build, a test and a release run the same in every
environment. Everything not gated refuses the token. See [Environments](../../with-what/environments/) for
what the dispatch does with it.

## Product data sections

Beyond the command tree, a manifest carries the **data** its tasks read. This is the seam that makes a
catalogue task a promise to three products instead of a convenience for one: the mechanism is the
kernel's, the values are the product's, and the section is where they meet.

```yaml
website:
  image: "hugomods/hugo:exts-0.148.2"
  output: "build/website"
  base_url: "https://example.github.io/myctl/"
  theme: "github.com/imfing/hextra@v0.12.3"
  # source: "docs/site"   # omitted: that is the default
```

`image` and `output` are **required to be declared** rather than defaulted. A kernel that named the image
would be choosing a documentation generator on every product's behalf, and one that guessed `output`
would hand a recursive delete a directory nobody typed. A missing section fails at load, naming the key,
instead of as a container run against a directory that is not there.

**`source` defaults to `docs/site`** (si#183). `docs/` is the documentation root - architecture, specs,
plans and the site all belong in it - so a product that says nothing lands on the convention, and one
that names a path still gets exactly what it named. Omitting the key is the recommended way to write it.
Note the line the default does not cross: `source` is only ever read, `output` is handed to
`shutil.rmtree` before every build, and that is the whole reason one of them has a default and the other
never will.

Two of those values are refused unless they pin a version. `image: "hugomods/hugo"` means `:latest`,
which moves under the build; `theme: "...@latest"` fetches whatever is newest on the day it runs. A
build whose output depends on when it ran is not a build, and a documentation site is committed-to
prose - a generator change rewrites it wholesale. `source` and `output` must be plain relative paths
under the product root, for a blunter reason: `output` is handed to a recursive delete, and
`output: /var/tmp/x` would delete `/var/tmp/x`.

**It is a default and not a rule, and that was measured rather than preferred.** A `source:` outside
`docs/` REFUSED would turn away a product that has done nothing wrong. Measured over the same population
si#159 and si#172 used - every manifest this kernel can reach: its own, the five in
`simplon.cli.surface.CONSUMERS`, and secure-windows-images - three of those seven declare a `site:` section
and the three do not agree: cleon at `site`, biz-cockpit at `docs/website`, simplon at `docs/site` (until si#344 B1; it names `src/site` now, and the argument below was made at `docs/site`). Two of those three would
fail on their first run with a kernel that insisted - an expression rule with no measured cause, which
this platform declines to write ([the rules chapter](../../with-what/rules/) says why).

By that same count the default serves none of the three, because all three name the key. It is for the
**fourth**: the day your product gets a website, it writes four keys instead of five and lands on the
convention without having had to read this page. Simplon itself is the first consumer - its own manifest
leaves `source:` out, so the default is exercised by every `build docs` in the kernel's own repository
rather than only by a test.

{{< callout type="warning" >}}
**`docs:site` writes into your working tree, on purpose.** A theme declared as a Hugo module means the
build runs `hugo mod get <module>@<version>` before it builds, and that rewrites `go.mod` and refreshes
`go.sum` in the site directory. It is idempotent when the manifest pin and `go.mod` already agree - the
normal state - but the first build after you move the pin leaves a real diff.

A publishing job that asserts "working tree clean" after building the site will fail on it. That is the
mechanism working, not a fault: the manifest is the single place the theme version is declared, and
`hugo mod get` is what makes `go.mod` agree with it. Commit `go.mod` and `go.sum`; do not gate on a
clean tree after a site build.

It also writes `build/hugo-cache/`, which is Hugo's own cache kept between runs so that a second build
needs no network - the module it resolves and the theme's remote assets are both answered from it. That
path is the kernel's, not the manifest's: it is covered by the same `build/` rule a product's `clean`
and `.gitignore` already carry, and a CI job that wants offline builds is the one that should cache it.
{{< /callout >}}

### The names the kernel has claimed

A top-level key the kernel does not read is **the product's own**, and nothing here rules on it. That is
the design rather than a gap: the section is where a catalogue task's mechanism meets a product's values,
and a product that could not invent one would have to ask the kernel for permission to have data.
Measured over every manifest this kernel can reach, its own and those in other repositories, some top-level
keys are exactly that, and every one of them is read by a body in the product's own repository. Adding a key
nobody here has heard of is a supported thing to do. The one shape it may not have is an area's: a section
that carries `commands:` or `environments:` at any depth is refused as a misspelt `ci:`, `cd:` or `support:`
(si#388), because its commands would otherwise vanish without a word.

What was missing is the other half: **which names are already taken**. The product si#159 was reported
from builds three Windows Server *releases*, and it learned that `releases:` already means
`{page, from, complete_from}` to `test:release-notes` by reading `src/simplon/tasks/releasenotes.py`. A
reserved name that can only be found in the source is a trap with a delay on it, so every one is
published here: the sections a kernel reader reads, and `ci:` and `support:`, which only the
loader reads. `cd:` is both - the loader reads its commands, and the environment readers the matrix beside
them. `tests/test_manifest_top_level.py` holds this table to the kernel in both directions.

| key | read by | what it carries |
| --- | --- | --- |
| `artifacts:` | `release:artifact`, `build:nuget-pack`, `release:nuget`, `release:conan-*`, `build:maven-pack`, `release:maven`, `build:image`, `release:image`, `test:image` | one entry per artifact, each with its `kind:` (`image`, `directory`, `nuget`, `maven`, `conan`, ...) and that kind's keys - see [the kinds](../../with-what/kinds/) |
| `assets:` | `release:asset` | one entry per file attached to a GitHub release |
| `build:` | `build:cmake-files`, `build:dotnet-solution` | `targets:`, the dependency edges between build targets that a directory layout cannot show |
| `carriers:` | the environment selector | one entry per thing an environment is realised ON: its `proxmox:` node and kind, and the `portainer:` on it |
| `cd:` | the loader, the environment selector | the `deploy:` and `monitor:` commands, and the environment matrix beside them: `environments:` (name, backend, description) and `default:` (the environment a command targets when no env token is given) |
| `ci:` | the loader | the `build:`, `test:` and `release:` commands |
| `claude:` | `support:claude-plugins`, `support:install` | optional, and only what a product ADDS to simplon's plugin default (si#525): `plugins:` and the `marketplaces:` they need, `exclude:` for a default plugin it does not want, and `requires:`, executables its own plugins run. One missing from PATH makes the task fail (rc 1). An absent section means the default |
| `deploy:` | the deploy commands | `source:`, naming the `artifacts:` entry a deployment's versions are looked up in |
| `doctoolchain_version:` | `docs:render` | the pinned docToolchain image tag |
| `env_var:` | `support:environments` | the variable a product's env-first CLI publishes the active environment into |
| `generated:` | `test:generated` | one entry per committed generated file: its `path:` and the `by:` command that produces it |
| `instance:` | the multi-tenant lab | the env var naming the lab instance, and the product's id-length budget |
| `lab_egress:` | the lab egress helper | the host interface a lab reaches the outside through |
| `launcher:` | the launchers' renderer (`simplon init`), the container-route check, `toolchain:run` | `env: pass:`, the variable names forwarded by name into the kernel's container and onto every toolchain line |
| `layout:` | `build:toolchain`, `test:*`, `docs:acceptance` | where inside your tree a containerised command runs, and which directory holds the tests above the acceptance line |
| `nexus:` | the `nexus` commands | the proxy repositories, the compose file and the container this product runs |
| `output:` | every producing coordinate | the one directory this product's build writes into, as `<output>/<kind>/`. Defaults to `build` |
| `releases:` | `test:release-notes` | `page:`, `from:` and `complete_from:`, the three values that gate says what it measures against |
| `suites:` | `test:*` | the test-level taxonomy: the gates, their order, and which one clears the shared results |
| `support:` | the loader | the commands that support the five phases rather than being one, and their sub-groups |
| `tracker:` | `test:walk` | where a refused acceptance step becomes a bug ticket, and the product's own wording for it: `title:`, plus `kind:`, `repo:`, `labels:` and `preamble:` |
| `toolchains:` | `support:claude-plugins`, `support:install`, `support:toolchain` | the toolchains this product uses: `python`, `java`, `cpp`, `dotnet`, `firn`, `claude`, `gh`, `brew` (si#525, si#526). `support toolchain <name>` adds one; for `firn` that is `test model`, `build model` and `test manifest-model`, which validates this manifest, exported fresh, against the firn M2 simplon ships (si#522). `claude` turns on the Claude Code plugins (eight base plugins, plus one LSP plugin per language listed here). `gh` and `brew` make `support install` provision the GitHub CLI and Homebrew: brew first, then gh through brew, winget or GitHub's signed apt repository (with sudo where needed). Each says present, installed, skipped (container, CI, a platform Homebrew does not run on), no way to install it here, or failed; the last two fail the command. An unknown name is refused, and an absent list turns everything here off |
| `website:` | `docs:site` | the pinned Hugo image, where the sources live, where the site is built to |
| `workflows:` | `release:workflows` | one entry per generated CI file |

A key that is **mistyped** is therefore not the silent no-op it looks like. Most of the sections a
reader reads are named by the reader that wanted them, the moment that reader runs: `websiet:` instead
of `website:` answers `the 'website' section is missing or is not a mapping`, and every other reader
refuses the same way, naming the key it looked for. The ones that say nothing say nothing on purpose:

- **`build:`** - an absent section is the normal case. `build cmake-files` and `build dotnet-solution`
  render the build files from the SOURCES, and `build: targets:` only adds the edges the directories
  cannot show. A `build:` section that exists for some other reason and carries no `targets:` says the
  same thing, on purpose - two live manifests have one, and the next section is about them.
- **`env_var:`** - a product that selects its environment by token and `default:` alone has no such
  variable, and a listing must still work on a manifest that has not adopted the key.
- **`launcher:`** - an absent section is what every product in this family has. It arrived with si#467,
  and a product that says nothing forwards into the kernel's container exactly what it forwarded before.
  Same cost as `layout:`: `lanucher:` is silent too, and only a key mistyped *inside* a correctly spelled
  `launcher:` is refused.
- **`layout:`** - an absent section is what every product in this family has. It arrived with si#250 and
  its defaults are exactly what the kernel assumed before it existed, so a manifest that says nothing
  runs the line it ran yesterday. The cost is stated rather than left to be found: `layotu:` is silent
  too, and only a key mistyped *inside* a correctly spelled `layout:` is refused.
- **`output:`** - an absent key is the normal case and is what every manifest in this family has today.
  si#314 wrote down a convention rather than inventing one, so a manifest that says nothing writes where
  it wrote yesterday. Same cost as `layout:`, stated for the same reason: `otuput: build-out` is silent
  too, and the build lands in `build/`.

Each is driven in the test module above, so the silence is measured rather than assumed.

### Reading a section, yours or the kernel's

A product's own task body reads its own section through `simplon.manifest.context.section`, the same walk the
kernel's own readers use:

```python
from simplon.manifest import context

ctx = context.current()
packer, blame, got = context.section(ctx.manifest_data(), "build", "packer")
if blame:
    raise ValueError(f"{ctx.manifest_path}: `build: packer:` is not declared")
```

It walks a **path**, because `build:` is shared and a product that wants its own data under a phase has
to nest (the section above). It stops at the first step that is not a mapping and **names that step**:
`buidl: packer:` blames `build`, so a typo in the outer key never reports the inner one as absent.
`got` is what the blamed step held - `None` exactly when it is not declared at all, which is how a
reader tells "the product said nothing" from "the product said the wrong thing". A section declared and
empty is found, not blamed.

**It never raises, and that is deliberate.** Each reader above says something specific
when its section is missing, and si#159 measured that nearly all the sections it measured already refuse
by name and quote the key. An accessor that raised would replace those sentences with one. So it answers the
question and the reader keeps its own refusal - which is also what keeps every refusal countable where
it is written, in [the rules chapter](../../with-what/rules/)'s census.

### `build:` is shared, and `build: targets:` is the kernel's

`build` is the one name that is a **group** and a **top-level data section** at the same time: the
catalogue declares a `build` group, and `build:cmake-files` and `build:dotnet-solution` read their
`targets:` out of a top-level `build:` section. The kernel's own source used to carry a comment saying
the two could never meet. They already do (si#172).

Measured over the same seven manifests si#159 read, two products carry a top-level `build:` section of
their own and no `targets:` in it: cleon's holds `bundle:`, `ant:` and `site:`, and
secure-windows-images' holds `packer:` and `templates:`. Neither is doing anything wrong. The kernel
picked a name that was already taken, and one of those manifests had already written a comment to its
own authors explaining the collision and telling them not to add a `targets:` key.

**The rule, so nobody has to read the source for it again:**

- `build:` is **yours**. Declare it, put what you like in it, and nothing here refuses it. Refusing it
  is what si#159's measurement rules out - top-level keys across those manifests
  are read by product task bodies in repositories this kernel cannot see, so a rule over the top-level
  namespace refuses live products on its first run.
- The kernel reads exactly **one key** out of it, `targets:`, and rules on nothing else in there.
- An **absent** `targets:` means what an absent `build:` means: the source tree is the whole
  declaration. That is not a fallback, it is si#102's design - the directories say what the targets are,
  and `targets:` only adds the dependency edges they cannot show. Driven: a product carrying either of
  those two real sections and placing `build:cmake-files` writes exactly the files a product with no
  `build:` section writes.
- Inside `build:`, the word **`targets` is the kernel's**. If your own build vocabulary has targets -
  cleon's Ant block is one rename away, with `generate_targets:`, `compile_targets:` and
  `package_targets:` - call yours something else. A `targets:` of the wrong shape is refused by name and
  tells you to rename; it is not silent.

### `artifacts:` - what this product builds and hands over

Every entry is one artifact, named, with its **`kind:`** - one of the kinds the catalogue declares, listed
on [the kinds page](../../with-what/kinds/): `image`, `directory` (and `site`, which refines it), `nuget`,
`maven`, `conan`, ... A product cannot add a kind. A command binds one entry to its task's port
([`produces:` / `consumes:`](#binding-artifacts-produces-and-consumes)), and the port accepts an entry of its kind or of a kind that refines it - `release:artifact` reads a `directory`,
so a `site` too; an entry of any other kind is refused with both kinds named.

```yaml
artifacts:
  app:
    kind: image
    registry: ghcr.io/example
    repository: myctl
    dockerfile: Dockerfile
    context: .
  updatesite:
    kind: directory
    registry: ghcr.io/example
    repository: myctl-updatesite
    path: build-out/site        # where it lies once built
    media_type: application/vnd.example.updatesite.v1+zip
  web: { kind: image, local: "myctl-web:local" }   # built by your own script; no kernel task builds it
```

Each kind's keys and their shapes are checked when the manifest loads - a list where a list belongs, a
string or a number where a string does (`tag: 25` is the tag `25`) - and a key the kind does not take is
refused by name, with the nearest key it does take, because otherwise it would be ignored without a word.
What a task NEEDS it is told when it runs, all at once: `release:nuget` needs `registry`, `image` and
`path`; `build:nuget-pack` needs `image`, `project` and `path`; `build:nuget-config` only `registry`, so one entry
can serve both. The refusal of an unknown key
lists the keys the kind does take; your own code asks `simplon.manifest.artifactsection.is_a(kind, "image")` rather
than comparing `kind` to a string, so a kind that refines `image` is one too. Before si#344 B2 `path:` was called `source:`,
`images:` was a section of its own, and an entry needed no `kind:`; the loader refuses each of those by
name, and `simplon manifest migrate` rewrites all three (it derives a missing kind from the catalogue task
that reads the entry, and refuses by name when nothing does).

### `kind: image` - the container image

`build:image`, `test:image` and `release:image` read one `artifacts:` entry of
`kind: image`, bound per command - `produces: { image: app }` on the build, `consumes: { image: app }` on
the test and the release - because a product may build more than one:

```yaml
artifacts:
  app:
    kind: image
    registry: ghcr.io/example
    repository: myctl
    dockerfile: Dockerfile
    context: .
    tag: latest                 # optional; `--tag` overrides it
    build_args:                 # optional; yours, on top of the two the kernel derives
      PYTHON_VERSION: "3.12"
```

The first four are required, `registry` included even if you only ever build locally: the reference the
build tags is the reference the release pushes, and an unqualified name is one docker resolves against
Docker Hub. `dockerfile` and `context` must stay under the product root - `context: /` would stream your
whole filesystem to the daemon as a build context. A `local:` image -
one only your own code builds - needs none of them, and no kernel task builds or publishes it.

**`VERSION` and `REVISION` are passed on every build, and you do not declare them.** The kernel derives
them from *your* checkout - `git describe --tags --always --dirty` and `git rev-parse HEAD` - so the
image built on a laptop carries its provenance exactly as the one built in Actions does. Declare either
name in `build_args:` and yours wins; a Dockerfile that declares neither `ARG` ignores both at no cost.
The two are missing, with a warning, only when there is no checkout to ask - an exported tarball - and
your Dockerfile's own `ARG VERSION=dev` then stands rather than being overwritten with a placeholder.

{{< callout type="info" >}}
A shallow CI clone has no tags, so `git describe` falls back to the short commit. If you want the
release tag in the label, check out with `fetch-depth: 0`.
{{< /callout >}}

`release:image` asks the **registry** whether the tag arrived before it reports success. A push whose
result nobody reads is the same defect as a report nobody reads, and this project has shipped that twice.
The question goes through `oras` - the tool the kernel provisions anyway - and not through a docker
client, because `docker manifest inspect` answers out of `~/.docker/manifests/` and will confirm a tag
that only ever existed on your machine.

If `registry:` does not name `ghcr.io`, no GitHub token is minted for it. The push then uses whatever
credential your own `docker login <host>` stored, and a rejection says so instead of pointing at
`gh auth refresh`, which would mean nothing on someone else's registry.

#### Several platforms, and an image built from another one

Two optional keys turn one entry into a multi-platform image (si#347):

```yaml
artifacts:
  toolchain:                      # never published; only ever an input
    kind: image
    registry: ghcr.io
    repository: example/toolchain
    dockerfile: deploy/builder/Dockerfile
    context: .
    tag: "25"
  app:
    kind: image
    registry: ghcr.io
    repository: example/app
    dockerfile: Dockerfile        # starts `FROM ghcr.io/example/toolchain:25 AS build`
    context: .
    platforms: [linux/amd64, linux/arm64]
    contexts: [toolchain]
```

**`platforms:`** sends the build through `docker buildx bake` with a builder called `simplon` (created
with the docker-container driver the first time, and never made your current builder). `build:image`
loads each platform into the daemon under its own reference - `ghcr.io/example/app:1.0-linux-arm64` - and
tags the host's own platform under the plain reference too, so anything that runs the image by name still
does. `build:image` and `test:image` both take `platform:` to work on one declared platform only - pin
`platform: linux/amd64` with `with:` on the commands a developer and CI run every day, so they stay one
native build on a host with no emulator. `release:image` refuses until every declared platform has been
built: run `build image` without `platform:` before it. It then pushes **one manifest list**, fetches the
index from the registry and looks for every declared platform in it - a tag that resolves but lost a
platform is red - and holds each platform's manifest digest against the one the build recorded. The push
re-runs the bake; with the builder's cache warm that is an export of exactly the images the smoke ran,
and if the cache was pruned in between it is a second build, which this check turns red instead of
publishing images nothing ran. An entry without `platforms:` builds and pushes with exactly the argv it
always had.

**`contexts:`** names other `kind: image` entries of `artifacts:` that the Dockerfile starts `FROM`. The name the
`FROM` line uses is not typed again: it is the named image's own `registry/repository:tag` (its `tag:`,
or the derived `VERSION` when it declares none), so the two cannot drift apart. With `platforms:`, the
named image is built in the same bake, for the same platforms, with no tag and no output, so it is
supplied per platform and never pushed anywhere. Without `platforms:`, the plain `docker build` resolves
`FROM` in the daemon, so the named image has to be built first, and a build that would otherwise try to
pull it is refused with the command that builds it.

**Emulation is your host's business, and simplon says so rather than doing it.** Building arm64 on an
x86_64 runner needs QEMU registered in the kernel - a privileged, host-wide change that lasts until
reboot. simplon reads which platforms its builder can run, warns about any it cannot, and names the one
command that registers them:

```sh
docker run --privileged --rm tonistiigi/binfmt:qemu-v10.2.3 --install arm64
```

That registration **lasts until the host reboots**. On a runner that should keep building arm64 after a
restart, register the handlers persistently instead - the distribution's `qemu-user-static` (with
`binfmt-support` or systemd-binfmt), which re-registers them at boot. After either, `docker buildx rm
simplon` lets the builder be created again so it sees them.

It does not refuse, because a Dockerfile that cross-compiles (`FROM --platform=$BUILDPLATFORM`) needs no
emulator at all. buildx itself is required: the static docker CLI simplon can bootstrap carries no
plugins, so install `docker-buildx-plugin`, or use `docker/setup-buildx-action` in a workflow.

A **GitHub-hosted runner** is set up fresh for every job, so the generated workflow's job needs its own
`docker/setup-qemu-action` (and `docker/setup-buildx-action`) step before `build image`; simplon generates
neither.

#### A file from outside, fetched once and handed to the build

A Dockerfile that downloads an archive itself cannot build offline, and it downloads the archive again
whenever the builder's cache is pruned. A `kind: file` entry lets simplon do the download instead
(si#343). `build:fetch` checks the file's sha256 and leaves it under `path:`, and an image whose
`contexts:` names the entry is handed the file's directory as a build context under the entry's name:

```yaml
artifacts:
  gradle-dist:
    kind: file
    path: build/dist/gradle.zip     # git-ignored; the build context is build/dist
    url: https://services.gradle.org/distributions/gradle-{version}-bin.zip
    sha256: acd53f1edaf02f1a8ff99879f8a34b302661a057d9b063ae9e35b552f804d20a
    version_from: { file: gradle/libs.versions.toml, key: versions.gradle }
  toolchain:
    kind: image
    # ... registry, repository, dockerfile, context as above
    contexts: [gradle-dist]         # RUN --mount=type=bind,from=gradle-dist,source=/gradle.zip,...
```

```yaml
ci:
  build:
    commands:
      gradle: { task: "build:fetch", produces: { file: gradle-dist } }
      toolchain: { task: "build:image", produces: { image: toolchain } }
```

- **`version_from:`** is optional. It names a TOML file under the product root and a dotted key in it,
  and `{version}` in `url:` is replaced by that value, so the version is written in one place. A
  `{version}` without `version_from:` is refused, and so is a `version_from:` with no `{version}` in the
  url.
- **The sha256 belongs to one file.** When the version moves, the download arrives with another
  checksum. Nothing is stored, and the run is red and names both the checksum and where the version was
  read from.
- **A file already there with its checksum is not fetched again**, and the run says so. A file there with
  another checksum, such as the archive of an older version, is replaced.
- **`build:image` consumes the file without a `consumes:`.** The loader derives the binding from
  `contexts:`, so an aggregate that plans the image before the fetch is refused. So is an image whose
  file no command fetches. Writing `consumes: { file: ... }` on the image command is refused, because
  `contexts:` already says it.
- **A file context needs BuildKit** (`--build-context`), the builder that `docker build` uses since
  Docker 23 and the one the kernel image carries.

### `releases:` - where the notes live, and from when they are complete

`test:release-notes` reads this one. It is the smallest product-data section in the kernel, and that is
the point of it: the rule it feeds needs no product knowledge at all, so what a product owes it is three
values and nothing else.

```yaml
releases:
  page: "docs/site/content/when/releases.md"  # where the notes live, under the product root
  from: "0.4.0"                            # the first release that must have a section at all
  complete_from: "0.5.0"                   # the first section that must name every ticket in its range
```

The gate then answers four questions out of `git tag`, `git log` and the page's own `## X.Y.Z` headings:
is every release at or above `from` written up at all; does the page promise a version nobody can
install; does every merge in a documented range name a ticket in its subject; and does every section
from `complete_from` on name each of them.

**Nothing reads the prose.** What a change *meant* is knowledge no tool has. The whole claim is that a
number appears somewhere in the section, which is deliberately the weakest claim that catches the
failure this exists for - a release section that describes the pull request it was written in rather
than the release it names.

**The two floors, and why the second is a floor rather than a list.** `from` is where notes begin:
earlier releases have their tags and their commits, and writing them up now would mean reconstructing a
record from memory. `complete_from` is where *completeness* begins, and the gap between the two is the
excused set. An exemption list would be the thing that grows quietly, one entry at a time, each looking
justified on its own; a second floor can only ever be raised in public. A product that excuses nothing
writes the same number twice, and a `complete_from` *below* `from` is refused, because it would demand
completeness of a section the same manifest says may be absent.

**The spelling is the page's, not `git`'s.** `0.4.0`, three parts and no `v`. The tag carries the `v`
and the heading does not, so `from: "v0.4.0"` is refused rather than helpfully stripped - it would
otherwise be a floor that matches no section at all.

{{< callout type="warning" >}}
**The range is `<last tag>..HEAD` of the state being checked, and which state that is depends on the
event.** A `push` to your default branch has the merge that just landed as `HEAD`, so a pull request's
own ticket is in range from the second it merges. A `pull_request` run checks out `refs/pull/N/merge` -
your branch *as merged with the base* - so a branch green on its own tip goes red the moment the base
moves. Both are the gate working; neither used to be said. Every run now prints what `HEAD` resolved
to, and names GitHub's own merge in as many words when that is what it found.

**A pull request never has to name its own PR number.** GitHub's `Merge pull request #N from <branch>`
is a statement about the *act of merging*, not about the work, so the gate reads the commits that merge brought
in instead. The number the notes have to carry is the *ticket* number in your own commit subjects - one
you had before the branch existed. Without that rule a release-notes PR would demand a note about
itself, and a follow-up PR would bring its own number too: the regress has no floor.
{{< /callout >}}

**It is offered, not placed.** A product with no release notes never sees the command, and one that
declares this section places it in one line under `test`. A checkout with no tags is diagnosed as the
*checkout* - `actions/checkout` fetches no tags unless you ask - rather than blamed on the page, and a
run that ruled on nothing is red rather than green.

### `workflows:` - the CI files, generated from this same manifest

The manifest has always been meant to have **two outputs**. It assembles the command line, and - with
`support:workflows` - it writes the GitHub workflows that call it.

```yaml
workflows:
  ci:
    note: |
      Every push and every pull request, and it is the SAME command a developer types.
    on: [push, pull_request]
    jobs:
      self-build:
        runs-on: ubuntu-latest
        python: "3.12"
        steps:
          - command: test all
          - command: build wheel
```

The line that matters is `command: test all`. It is not a string that happens to look like a command -
it is **resolved against the command tree above** before anything is written, and what lands in the file
is `./myctl.sh test all`. Rename that command and generation fails, loudly, in the same commit. Today,
in a hand-written workflow, a renamed command leaves a `run:` line calling something that is gone, and
the first anybody hears of it is a red runner.

Everything the kernel cannot know stays yours and is carried through untouched, **at the level GitHub
puts it**:

| level | carried |
|---|---|
| workflow | `permissions:`, `concurrency:`, `defaults:`, `env:`, `run-name:` - and anything else GitHub adds |
| job | `permissions:`, `environment:`, `needs:`, `concurrency:`, `if:`, `strategy:`, `timeout-minutes:`, ... |
| step (beside `command:`) | `name:`, `if:`, `env:`, `id:`, `continue-on-error:`, `working-directory:`, ... |

The levels are not interchangeable, and getting them the wrong way round is the mistake this table
exists to prevent: `environment:` and `needs:` are a **job's**, `defaults:` and `run-name:` are a
**workflow's**. Neither list is enumerated in the kernel - the keys are simply passed through, because a
kernel that policed GitHub's schema would be wrong the week GitHub extends it.

A **step** is the exception, and deliberately: it has exactly one body, so a key that is neither a
modifier nor a body is refused rather than carried. Two bodies - `command:` beside `uses:` or `run:` -
are refused for the same reason.

**`flow:` on a workflow rolls a release out to your environments, in order.** The kernel writes one job
per stage:

```yaml
cd:
  environments:
    test: { backend: portainer, carrier: haus, stack: app-test, deploys: latest }
    prod: { backend: portainer, carrier: haus, stack: app-prod, deploys: "1.4.0" }

workflows:
  rollout:
    on: { release: { types: [published] } }
    runner: { kind: github-ubuntu }
    flow:
      - to: test
      - to: prod
        approval: true
```

**Two declarations, because they answer two questions.** The environment says **what** it receives, with
`deploys:` — `latest` for the newest published version, or a pinned tag. The flow says in **which order**
environments are reached and which stage a person releases. A staging instance wants the newest
publication and a production one wants a chosen tag, and that is true however the rollout is triggered;
putting the version in the flow as well would give one truth two homes.

What comes out is `deploy-test` and `deploy-prod`, the second with `needs: deploy-test` — chained rather
than merely ordered in the file, because **GitHub runs jobs in parallel unless told otherwise** and a
rollout whose order lived only in the emitted order would reach production and staging at once while
looking correct.

`approval: true` gates nothing here: it gives the job GitHub's own `environment:`, which is where an
account configures required reviewers, wait timers and the secrets that stage may see. Who may approve is
an account setting, and it is the only half that can be changed without a commit.

{{< callout type="warning" >}}
**The version is a literal, and that is a security property rather than a simplification.** It comes from
`deploys:` in your manifest, so the kernel writes `deploy up --version 1.4.0` with a value nobody outside
the repository chose. The obvious alternative — a `workflow_dispatch` input interpolated into the command
— is the classic Actions script injection, in a job holding deployment credentials, emitted by the
kernel on your behalf. A product that wants a person to choose the version at dispatch can still do it,
in a `jobs:` block of its own, where the hazard is visible in its own file.
{{< /callout >}}

**Your own jobs stand beside it.** A workflow may declare `flow:` and `jobs:` together — the generated
names are stable, so a notification job hangs `needs: deploy-prod` on one. And a step may now hand a
command a parameter:

```yaml
        - command: deploy up
          params: { version: "1.4.0" }
```

The parameter **name is checked against what the command declares**, which is si#40's join one level in:
a renamed parameter breaks generation instead of becoming a `run:` line that fails on a runner three
minutes into a job.

**A value chosen at dispatch reaches the command through the environment, never through the script**
(si#488). Name the variable instead of writing the value:

```yaml
    on:
      workflow_dispatch:
        inputs: { version: { required: true } }
    jobs:
      release:
        env: { RELEASE_VERSION: "${{ inputs.version }}" }
        steps:
          - command: release tag
            params: { tag: { env: RELEASE_VERSION } }
```

The step renders as `./<product>.sh release tag -- "$RELEASE_VERSION"`: GitHub writes nothing into the
script, the shell expands the variable, and the double quotes keep whatever a person typed one
argument. Writing `${{ inputs.version }}` into `params:` would put the input into the script itself,
which is the injection the callout above declines. A plain `$RELEASE_VERSION` value would not work
either: it is quoted like any literal and reaches the command as those characters.

The variable must be **set by an `env:`** of the step, its job or the workflow, or be one GitHub sets
itself (`GITHUB_*`, `RUNNER_*`, `CI`). A name set nowhere would expand to nothing and the command would
run as if no value were given, so generation refuses it. A `params:` value that is neither a scalar
nor `{ env: NAME }` is refused too: it used to reach the command as its Python text.

**`release:` on a workflow derives the whole dispatch release from a release aggregate** (si#490). The
product names the aggregate and the machine:

```yaml
workflows:
  release:
    release: release all
    runner: { kind: self-hosted-debian, labels: ghr-8 }
```

What the kernel writes:

- **The trigger.** `on: workflow_dispatch` with `version` (required) and `dry_run` (default **true**).
  There is no tag trigger: a release is started by a person who types the version.
- **`permissions:`** `contents: write` and `packages: write`. A product's own `permissions:` adds scopes,
  such as `id-token: write` for PyPI's Trusted Publishing, but it may not lower those two.
- **`concurrency:`** One release per version, never cancelled in progress.
- **One job, `release`.** It cuts the tag in the checkout, checks that `git describe` is the version, runs
  the aggregate's leaves **in the plan's own order**, and ends with a dry-run step that prints the notes.
  The order is what rule 8 already checked at load, so the workflow orders nothing itself.

The version reaches each leaf that takes `tag` unpinned as `"$RELEASE_VERSION"`, exactly as
`release all --tag v1.4.0` would hand it on the command line. Two task fields decide the rest. They are
declared on the task, so a catalogue task brings its own and a task of your own declares them:

- **`publishes: true`:** the task's act cannot be taken back, so a dry run skips its step;
- **`token: github`:** the task authenticates to GitHub, so its step's `env:`, and no other step's,
  carries the run's `GITHUB_TOKEN`. That is not yet isolation. The checkout every generated job starts
  with persists the job token in `.git/config`, where any step can read it, and `release:tag`'s push relies
  on it (si#507). A secret of your own goes in the workflow's `env:`, which every step of the job sees.
- **`token: app`** (si#534): the task writes to one repository the run's own token cannot reach, such as
  a Homebrew tap. The leaf binds it as `with: { repository: <owner>/<repo> }`, and the generator puts an
  `actions/create-github-app-token` step (pinned, v3.2.0) directly before the leaf's step, in the derived
  release job and in any job of your own. That step mints a token for that one repository with
  `contents: write`, under the leaf step's `if:`, so a dry run mints nothing. The leaf step alone reads it,
  as `GH_APP_TOKEN` in its `env:`. The app's two secrets are named after the repository: its name,
  every character outside `[A-Za-z0-9]` written as `_`, upper-cased, so `marcozwyssig/homebrew-tap` reads
  `HOMEBREW_TAP_CLIENT_ID` and `HOMEBREW_TAP_APP_KEY`. Refused at render: a leaf with no `repository` or
  one not shaped `<owner>/<repo>`, a name whose prefix GitHub would refuse as a secret name (it starts with
  a digit or with `GITHUB_`), a step whose `env:` is not a mapping or sets `GH_APP_TOKEN` itself, and an
  aggregate step whose plan holds such a
  leaf among others, because one `run:` line would hand the token to all of them. Run the leaf as its own
  step.

Refused beside `release:`:

- an `on:` (a second trigger would start a release with no version) and a `concurrency:`;
- `flow:` (each derives its own trigger);
- a job of your own called `release`;
- an `env:` that sets `RELEASE_VERSION`.

Refused at generation:

- an aggregate that passes no `tag`, or passes a second parameter a dispatch cannot fill;
- a leaf that is not `unattended: true`.

Your own jobs may stand beside it and `needs: release`.
[Cutting a release](../releasing/#a-dispatch-release-that-stopped-half-way) says how a run that stopped
half-way is finished.

**`derive:` on a step writes the pipeline the command tree already implies** (si#267). A step that
declares it is not one step but a placeholder for however many the named groups carry:

```yaml
    jobs:
      self-build:
        runner: { kind: self-hosted-debian, labels: ghr-8 }
        steps:
          - derive: [build, test]
```

Every **leaf** of each named group that may run with nobody watching becomes a step, in the order the
manifest declares it. Leaves rather than aggregates, because a GitHub job stops at its first red step -
emitting `test all` would collapse four verdicts into one and lose the order its members were written
in. An aggregate is skipped without comment, because nothing is missing from the file; a leaf that is
skipped **is named in the file**, with the reason, since a reader wondering where `test walk` went is
standing in the workflow and not in the kernel's source.

Which leaves may run is the `unattended:` flag from [task and command](../task-and-command/), declared
in the platform catalogue once for every product that imports the coordinate. A leaf that says nothing
is refused by name rather than guessed at.

**A derived step stands beside your own**, and that is the reason it is a step rather than a key on the
job. A product that wants the derived pipeline plus a Check Run reporter writes both and decides where
the seam falls:

```yaml
        steps:
          - uses: actions/setup-node@v4
          - derive: [build, test]
          - command: release image
```

A job-level `derive:` would have had to refuse `steps:` beside it — and that refusal would have been an
expression rule, forbidding something a product legitimately wants and sending it back to writing the
whole file by hand, which is the work this feature exists to remove.

**An artifact that crosses a job boundary is handed over** (si#344). Every job starts on a fresh machine, so
a file one job writes is not there for the next. When a command in one job `produces:` an artifact that a
command in another job of the same workflow `consumes:`, the generated file says so itself:

- the producing job archives the artifact's `path:` with `tar` after its last producing step and uploads it
  under the artifact's name;
- the consuming job gets `needs:` on the producing job (after any `needs:` you declared), and downloads and
  unpacks it before its first consuming step.

The archive keeps the path and the file modes, which `upload-artifact` alone does not. Producer and consumer
in one job hand nothing over, and a workflow with no such edge is written exactly as before. The archive is
kept a day. A producer written as a verbatim `run:` line is not seen: write it as a `command:`. On a Windows
runner the `tar` lines are not measured.

**What cannot be handed over is refused when the workflow is generated,** naming the workflow and the jobs
involved, and the artifact where one is the cause:

| The workflow would... | Refused because |
|---|---|
| consume an artifact that no job in it produces, and that has no `registry:` | nothing puts it there. A release whose evidence no job writes would be green with no test run |
| consume, in one job, before the step of that job that produces it | the order is yours; the data only checks it |
| consume an artifact that is produced in more than one job, or in a matrix job | one run uploads one artifact once |
| hand over an artifact with no `path:` | there is no file. An image stays in one job's docker daemon, so build and use it in one job |
| hand over an artifact whose name has anything but letters, digits, `.`, `_` and `-` | the name goes into a shell line and into `upload-artifact`, which rejects `" : < > | * ? \ /` |
| hand over an artifact whose `path:` is absolute or has a `..` segment | `tar` stores it somewhere else, so the consumer finds nothing where it looks |
| hand over from a job with an `if:` that the consuming job does not share | a skipped producer skips its consumer, and a skipped job is not red: the run would be green with nothing done |
| have jobs that need each other | GitHub refuses the file. If your own `needs:` form the loop, the message says so |

A hand-off between two workflows is not generated: give the artifact a `registry:` and let the body fetch it.

**`runner:` names a KIND of machine, and the kernel supplies what follows from it** (si#267). This is
the answer to a day that was spent twice: moving one repository's CI to a self-hosted runner meant
learning that `actions/setup-python` never installs Python, that a container job cannot be the thing that
provisions docker, and that `DELIVERY_DOCKER_BOOTSTRAP=1` exists — all of it already written down, in a
comment in another product's manifest.

```yaml
    jobs:
      self-build:
        runner: { kind: self-hosted-debian, labels: ghr-8 }
```

| kind | `runs-on:` | `setup-python` | environment |
|---|---|---|---|
| `github-ubuntu` (the default) | `ubuntu-latest` | yes | — |
| `self-hosted-debian` | yours to name | **no** | `DELIVERY_DOCKER_BOOTSTRAP: "1"` |

The **label stays yours**: `ghr-8` names one machine and no kernel can guess it, and
`[self-hosted, Linux, X64]` is not an answer — it describes every self-hosted Linux machine the account
will ever register, so the day a second one joins, the jobs are shared out with nothing saying so. A kind
that carries no label of its own therefore refuses until the job names the machine.

What the kind buys is the rest. A `python:` pin on a kind that cannot honour it is **refused at
generation**, because a pin that cannot be honoured reads as a guarantee and is a wish; the kind's own
environment is merged into the job's, and a variable the two set differently is refused rather than
resolved. The kind's one-line reason is written into the generated file, so a reader who finds
`runs-on: ghr-8` beside `DELIVERY_DOCKER_BOOTSTRAP: '1'` does not have to find the kernel to learn why
they belong together.

`runner:` and `runs-on:` answer the same question, so declaring both is refused. **Neither is
deprecated:** `runs-on:` is the whole of what a product needs when its machine has nothing to teach
anybody, and a new kind is added to the kernel's table once, for everybody, rather than described again
in each manifest.

**`runs-on:` may be a label, a list of labels, or GitHub's `group:`/`labels:` mapping** - all three of
GitHub's shapes, carried through as written. A list is the documented way to reach a self-hosted runner,
because one label is rarely enough once an account has more than one machine:

```yaml
    jobs:
      template:
        runs-on: [self-hosted, windows, vmware]
```

Until 0.16.0 the value was coerced with `str()`, so that list came out as the single label
`"['self-hosted', 'windows', 'vmware']"` - valid YAML, valid GitHub syntax, and a runner that cannot
exist, so the job queued for ever with no error anywhere (si#266). A value GitHub has no reading for at
all - a number, a bool, a list with something other than a label in it - is refused naming the line.

**Whether a tag publishes is your statement**, so a workflow that declares no `on:` is refused rather
than given a default. A step the kernel has no business modelling - `pypa/gh-action-pypi-publish`, an
upload, a shell script that reports something - is written out verbatim beside the resolved ones.

A command step keeps its modifiers, which is what lets it stay a command step:

```yaml
steps:
  - name: The system gate
    command: test system
  - name: Publish the report
    if: always()
    command: test report
```

Without that, every step carrying a `name:` or an `if:` would have had to be written as a verbatim
`run:` line - the hand-typed, unchecked string this section exists to abolish. Measured across six real
products: **34 of 41** command-invoking steps carry one of `name:`, `if:` or `env:`.

A command step that declares no `name:` shows its `run:` line in the Actions UI, and that line is
`./myctl.sh test all` - the same string you type in a checkout. The kernel does not invent a name for
it; say `name:` if you want different words.

Two things are the kernel's, and both are settings you should not have to remember. The checkout is
emitted with `fetch-depth: 0`, because `actions/checkout` defaults to a shallow clone that carries no
tags - so anything deriving a version from one gets a wrong answer *silently* rather than an error; and
`python:` becomes a `setup-python` step, or nothing at all if you declare none. A job that wants neither
says `checkout: false` and writes its own.

**Your comments survive.** `note:` may sit on the workflow, on a job or on a step, and is written out as
a comment in that position. That is a requirement rather than a nicety - a real workflow carries measured
values and the reasoning for absences, and a generator that dropped them would make the file worse than
the one it replaced.

{{< callout type="warning" >}}
**`on:` is a boolean in YAML 1.1.** `yaml.safe_load("on: [push]")` gives you a mapping keyed by `True`,
not by `"on"`. Write the trigger the natural way here - the loader reads both spellings - but if you ever
parse a workflow yourself, look under `True`, or you will search a section you never had and read the
miss as an answer.
{{< /callout >}}

#### `--check`, and the file nobody owns

`myctl support workflows --check` reports drift and **returns 1**, so one command is both a pre-commit
hook and a CI step. It also returns 1 for a file in `.github/workflows/` that **no entry names**. That
second case is the reason the section exists: a workflow nothing generates and nothing declares looks,
from the directory, exactly like one somebody maintains - and it keeps running long after it stopped
meaning anything.

There are two ways to answer it, and the second is a real answer rather than an escape hatch:

```yaml
workflows:
  release:
    handwritten: >-
      two-thirds prose and two multi-line shell scripts; declaring it would move that work
      rather than remove it
```

A declined workflow is never written to, and it is **named with its reason on every run** - because
"this one is hand-written" is easy to keep believing after it has stopped being true.

The declaration has to keep being true, too: if the file it names is **not there**, `--check` returns 1
and says so. A name with nothing behind it fails exactly the way a file nobody names does - by looking
accounted for.

Other sections work the same way: `suites:` is the test-level taxonomy a product's own test tree
defines, `cd: environments:` the deployment matrix, `nexus:` and `claude:` the data their respective tasks
read. A task that needs a section it does not find fails on its first line, which is why such tasks stay
*tasks* in the catalogue rather than being placed as commands for everybody.

### `output:` - the one directory a build writes into

```yaml
output: build        # the default; a product that needs another says so once
```

Everything the kernel's producing coordinates write lands under it, sorted by **kind**:

```
build/
  cpp/ dotnet/ java/ python/    what a compile produced
  docker/                       image.txt - the reference and the id of what `build:image` built
  docs/                         rendered documentation
  site/                         the built website
  logs/                         the step logs and the run transcript
```

The four language kinds are the kernel's own toolchain profiles, so a language it can build for is a
language it can say where the result went; a test holds that correspondence, and a fifth profile without
a kind turns it red.

**It is a default, not a rule.** A coordinate that names its own destination gets exactly what it named -
`site: output:` still wins over `<output>/site`, and a document written into the source tree because a
generator reads it from there is a legitimate thing to declare. That is measured rather than conceded:
over every manifest this kernel can reach, two producing coordinates write outside `build/` today, and
one of them is in this repository's own manifest.

**WHAT RESOLVES AGAINST IT, EXHAUSTIVELY** — because "not listed" and "not migrated" look the same to a
reader, and a report that quietly moved looks exactly like a report that does not exist:

| what | where it goes |
| --- | --- |
| the run transcript, and a step's own log | `<output>/logs/` — see below: not every run writes one |
| `build:image`'s pointer | `<output>/docker/image.txt` |
| `docs:site`, when the `website:` section names no `output:` | `<output>/site/` |
| the HOME a containerised run gets (si#319) | `<output>/home/` — honoured by a uid with no passwd entry; a container running as root takes that entry's home instead (si#325) |

**`<output>/logs/` is written by a run made of STEPS, not by every command.** Measured, because "on every
run" and "on a step run" are two different promises: the run transcript is written by the step pipeline -
the TUI and the headless runner - and by `test walk`; a step's own log is written when that step CRASHES,
or when an operator saves it from the TUI's palette. A gate invoked straight from the CLI (`test unit`)
runs the task body and no pipeline, so it writes neither, and a product that has only ever run gates
correctly finds no `logs/` directory at all. Reported by a consumer who upgraded, looked for it, and did
not find it.

**Nothing else moved, and `reports:` in particular did not.** A test run's outputs still fall back to
`tests/reports` beside the suite when `suites: reports:` names nothing — the rule 0.7.0 shipped, unchanged
here. A product that wrote down *"no `reports:`, the kernel's fallback is what we want"* keeps exactly
what it decided. The day that changes it will be a ticket with this table in it, not a side effect.

**`build/` is disposable, and that was already true.** A fetched tool binary, a step log and a rendered
site are all build outputs that `clean` removes - the kernel says so in `tools.py`, in `steplog.py` and
in the `.gitignore` it scaffolds. What si#314 changed is that a product's own artefacts now arrive there
at all, instead of sitting wherever each tool happened to default to.

**The one output that is not a file.** A container image lives in a daemon, not in a directory, so
`build:image` writes a POINTER: `<output>/docker/image.txt`, carrying the reference and the daemon's
image id. That is what a deployment redeems anyway. `docker save` was measured and rejected - about a
gigabyte per build for a toolchain image, written by something nobody reads.

### `layout:` - where your tree sits

The kernel **generates** against two facts about your directories, and before si#250 it guessed both.

```yaml
layout:
  build_root: kernel      # default: "" - the product root
  tests: tests            # default: tests
```

**`build_root:` is the question `workdir:` looks like it answers and does not.** `workdir:` is the path
your tree is *mounted* at inside the container - `toolchain:run` writes
`-v <product root>:<workdir> -w <workdir>` - so naming a subdirectory there relocates the whole tree
rather than descending into it. `build_root:` descends, and the mount stays the product root, which a
build that walks up to find its fixtures needs:

```text
without layout:            -v /home/dev/firn:/work -w /work        gradle assemble
build_root: kernel         -v /home/dev/firn:/work -w /work/kernel gradle assemble
```

That trap cost a real adoption: the Java profile scaffolds `gradle assemble`, the product's Gradle root
was one directory down, and the scaffolded command was silently wrong.

**`tests:` is the directory above the acceptance line** - where `test report` writes its merged report
and where `docs acceptance` reads scenarios. **The spelling the kernel writes is `tests`**, decided once
because both were in live use and nothing had chosen. A product whose root directory is `test/` says so
here in one line, instead of working around it in every command that touches a path.

**One more path question belongs to the command, not to `layout:`.** To lay a tree directory over a path
in the container, a `toolchain:run` command declares `mounts:`, and the kernel creates both ends as you
first. See [the toolchain section](../../with-what/phases/) (si#511).

**Nothing here is prescribed, and that is a measurement rather than a preference.** Across this family,
six products have six layouts - one is an Eclipse plugin tree, one has no `src/` at all. A kernel that
stated one layout and held products to it would refuse five of the six. So this section lets a product
*say* what the kernel was otherwise guessing; it never rules on a tree.

**An absent section is the normal case**, and its defaults are exactly what the kernel assumed before it
existed - so a manifest that says nothing runs the line it ran yesterday. The cost is stated rather than
left to be found: a section name mistyped as `layotu:` is silent, and only a key mistyped *inside* a
correctly spelled `layout:` is refused.

### `launcher:` - the variables that cross into the kernel's container

On the container route the launcher forwards a fixed set of variables into the kernel's container and
nothing else: `DELIVERY_*`, `CI`, `NO_COLOR`, `TERM`, `TZ`, `GITHUB_TOKEN`, `GH_TOKEN` and your product's own
`<PRODUCT>_*`. That is deliberate - forwarding the whole environment is how a secret reaches a place
nobody looked - and it leaves out a tool that reads its secret under its own fixed name. Name those here:

```yaml
launcher:
  env:
    pass: [VSCE_PAT]
```

**Each name crosses by name, never as a value.** The kernel's container line gets `-e VSCE_PAT`, and so
does every `toolchain:run` line, on either route. The value is on no command line and in no log. A name
your shell does not export stays unset on the far side: it is not forwarded as an empty string.

**The launcher carries its own copy, so re-render it after editing the list.** The launcher is bash and
builds the container line before any Python exists to read this file with - the reason the image pin is a
plain file. So `simplon init` writes the names into `<product>.sh` and `<product>.cmd`. After editing
the list, run this at the product root:

```sh
simplon init --dir . --launchers-only
```

A launcher you forgot to re-render is **refused, not silent**. The launcher also exports the list it was
rendered with (`DELIVERY_ENV_PASS`), and on the container route the kernel compares that with this
section. It refuses the run, naming the variables the launcher does not forward or still forwards, and
the command above. Without that check a missing variable would look exactly like one your host never
set. The venv route has no container and inherits your whole environment, so nothing is compared there.

What the section refuses at load, on either route:

- a name that is not an environment variable name (a letter or `_`, then letters, digits and `_`);
- a name the launcher sets on the kernel's container itself - `HOME`, `PYTHONPATH`, `PYTHONUSERBASE`,
  `DELIVERY_ROUTE`, `DELIVERY_HOST_ROOT`, `DELIVERY_MOUNT_ROOT`, `DELIVERY_ENV_PASS` and anything in
  `LAUNCH_*`. The list is read off the launcher templates, and forwarding your host's value over one of
  them would break the container;
- a key other than `env:`, or under it other than `pass:`, because a key the kernel ignored would forward
  nothing.

A name the launcher already forwards (`GH_TOKEN`, `<PRODUCT>_*`, a `DELIVERY_*` it does not set itself) is
accepted, and changes nothing.

### `carriers:` - what an environment is realised on

An environment says *where* it deploys with `backend:`. It says *onto what* by naming a **carrier** - and
a carrier is named once and pointed at many times, because one Portainer serves several applications and,
on the same instance, several environments.

**Both halves of a carrier are optional, and each absence is a statement.** `proxmox:` is the machine the
kernel makes; `portainer:` is what it installs on it. A carrier with only `proxmox:` is a machine created
and deliberately not configured (si#258). A carrier with only `portainer:` is a Portainer **somebody else
built** - it has been running for months, the kernel did not make it and will not, and all this manifest
needs is where it answers (si#280):

```yaml
carriers:
  theirs:
    portainer:
      url_from: PORTAINER
      insecure: true
```

`deploy carrier` refuses that one by name, because there is no machine for it to make, and it says so in
terms of the alternative rather than of a fault. A carrier declaring **neither** half is refused at load:
each absence says something, both at once say nothing that any command can act on.

```yaml
carriers:
  hausportainer:
    proxmox:
      endpoint: https://10.0.0.6:8006/
      token_from: PROXMOX       # a PREFIX -> PROXMOX_API_TOKEN; never the token itself
      insecure: true            # only for a self-signed certificate; the default verifies
      node: pve1
      kind: lxc                 # or vm - the choice is per environment
      template: local:vztmpl/debian-13-standard_amd64.tar.zst
      storage: local-lvm
      cores: 2                  # these three may be left out
      memory: 2048
      disk: 4
      ssh_key: "ssh-ed25519 AAAAC3Nz... you@host"
    portainer:
      url_from: PORTAINER       # a PREFIX, never a value
      endpoint: 1               # Portainer's own id; 1 is what a single-host install has
      insecure: true            # Portainer makes its own certificate on first start

cd:
  environments:
    test:
      backend: portainer
      carrier: hausportainer
      stack: myctl-test
      repository:
        url: github.com/you/myctl
        compose: deploy/docker-compose.yml   # default: docker-compose.yml at the root
    prod:
      backend: portainer
      carrier: hausportainer      # the SAME carrier
      stack: myctl-prod
      repository:
        url: github.com/you/myctl
        ref: release/2.x          # default: main; `refs/tags/v2.1.0` deploys a tag
        compose: deploy/docker-compose.yml
        credential_from: GIT      # a PREFIX -> GIT_USER, GIT_PASSWORD; omit it for a public repository
      required:                   # must have a value, or the deployment stops
        - COCKPIT_DATA_DIR
        - BACKUP_DIR
        - HTTP_BIND
      optional:                   # travels when set, absent when not
        - SMALLINVOICE_CLIENT_SECRET
        - APP_TITLE
```

**The sizes you leave out are the ones the community Proxmox helper script uses** - 2 cores, 2048 MB,
4 GB - read off `ct/docker.sh` rather than invented, so a carrier that says nothing gets what that tool
would have given it.

**Two secrets are read from the environment and neither has a field here.** `token_from: PROXMOX` means
`PROXMOX_API_TOKEN`; `url_from: PORTAINER` means `PORTAINER_URL`, `PORTAINER_TOKEN` and - because
Portainer needs an admin account *at start* or it locks itself after five minutes - `PORTAINER_PASSWORD`,
which must be at least twelve characters.

**`ssh_key:` is a PUBLIC key and belongs in the file.** It is not a secret, and putting it here is what
makes the carrier fully described by the manifest. The private half never appears.

**Two things the kernel sets and you cannot get wrong:** an unprivileged LXC will not start a Docker
daemon without `nesting` and `keyctl`, so they are not fields - they are what a carrier *is*, set on
every container the kernel creates. Whoever has set them by hand once has also forgotten them once.

**`insecure:` must be `true` or `false`, never a string.** Every non-empty string is truthy, so
`insecure: "no"` would mean the opposite of what it says. It is the one value here that is refused
rather than read leniently.

**A lower-case prefix is accepted.** `token_from: proxmox` reading `proxmox_API_TOKEN` is legal on every
platform the kernel runs on, and a rule against it was written and struck: it would have refused a
manifest that works.

**Why a section rather than more keys on each environment.** Written into the environments, the carrier
above would stand in the file twice - and the two could drift apart with nothing comparing them. Stated
once, they cannot.

**`carrier:` is not a second `backend:`.** They answer different questions and both are needed:
`backend:` says who deploys, `carrier:` says onto what. The backend stays what it has always been - the
one axis a product extends by registering an implementation.

**`repository:` is where Portainer pulls the compose document from, itself.** Which means Portainer needs
read access to it; the orchestrator does not. It is a block rather than a bare URL because the first real
consumer's compose document is not at the repository root, and `compose:` is the only place that can say
so. `credential_from:` names a PREFIX like every other credential here, and the credential is **sent with
every deployment** rather than stored in Portainer - so a stack somebody opens in the Portainer UI carries
no usable read access to your source.

**`backend: portainer` needs no product code.** It is one of the two backends the kernel ships, because
the whole chain under it is already the kernel's: `deploy carrier` builds the Portainer, `carriers:`
describes it, and this section points at it. A product that registers its own implementation under that
name still wins.

**`backend: devcontainer` is the other one, and it deploys the working tree into a container your
repository describes.**

```yaml
cd:
  environments:
    dev: { backend: devcontainer, description: "The development container." }
```

`deploy dev up local` brings up what `.devcontainer/devcontainer.json` describes; `deploy dev down`
removes it; `deploy dev status` says whether it is running. It is here for the same reason `portainer`
is - the chain under it is the kernel's, since Docker is a thing this kernel installs and checks - and it
needs no product code beyond the file the specification already defines.

**It names no editor, and that is the decision rather than an omission.** `devcontainer.json` is an
[open specification](https://containers.dev) with a reference CLI of its own, read by more than one
consumer; this backend drives that CLI and stops there. Which editor a person then attaches is theirs and
their product's, and a kernel that opened one would be coupling every product to it.

**It refuses a published version.** `local` is the only selector that means anything: a development
environment is the working tree, mounted. A tag names something in a registry, which is a deployment of a
different thing under the same verb.

**`portainer: insecure:` is the same value as the Proxmox one and is there for a measured reason.**
Portainer generates its own certificate on first start, so a carrier the kernel has just built answers
only with verification off. Give it a real certificate and leave this out.

{{< callout type="warning" >}}
**`deploy up` does not report success on a deployment that did not come up.** Portainer answers `200` to
accepting a stack, not to running one - a stack whose compose file does not exist is accepted and then
fails - so the deployment is read back until Portainer says it is up, and three outcomes are told apart:
it is up, it failed *(with Portainer's own sentence)*, or it is still deploying when the wait ran out.
{{< /callout >}}

**`required:` and `optional:` name the variables a deployment is given.** The values come from the
environment the deploy command runs in, on *every* deployment - not from a copy maintained by hand in
Portainer. Portainer stores them either way; the question is only whether its copy is an image something
refreshes or an original nobody does, and two masters of one set of values drift.

**Two lists, because "travels" and "may not be empty" are two statements.** A name in `required:` must
have a value when the deployment runs. A name in `optional:` travels when it has one and is left out when
it has not - and *left out*, not sent as an empty string, because to a document that writes `${X:-}` those
are the same today and the day they differ the kernel would have decided for it. A name in neither list
does not reach the deployment at all, so the two lists are the whole answer to "what goes over".

It was one list first, and the second one is not symmetry - it is a case one list could not say. A real
product writes `${SMALLINVOICE_CLIENT_SECRET:-}` where **empty means "not connected"**: the integration is
deliberately optional. In `required:` the product becomes uninstallable without a Smallinvoice account; in
neither list the secret never arrives and the integration is not optional but impossible. A name in *both*
lists is refused rather than ranked.

**An empty value fails the deployment.** It is the one place a consuming product asked for *more*
strictness than was offered, and the case is worth the refusal:

```yaml
# in the compose document
- "${COCKPIT_DATA_DIR:-${HOME}/.biz-cockpit}:/data"
```

A missing value does not make compose fail - it falls back, and the bind mount lands in the *carrier's*
`/root/.biz-cockpit` instead of `/srv/biz-cockpit/prod`. The container writes happily, the deployment
looks green, and the database sits outside everything the product's own `backup` knows about. An instance
that runs and is not backed up is this project's recurring defect exactly: green because nobody looks. So
every missing value is named, all of them at once - repairing eight variables one run at a time is the
kernel's work handed to an operator.

**A name that is not in the list does not reach the deployment**, which is what keeps the manifest
readable as the answer to "what goes over". And a manifest names variables here, never holds one:
`TOGGL_API_TOKEN=4c2b9f` is refused rather than read as a name with an equals sign in it.

**The version reaches the stack as `SIMPLON_VERSION`.** A compose document writes
`image: ghcr.io/acme/app:${SIMPLON_VERSION}`, so `deploy up --version 1.4.0` deploys 1.4.0 rather than
whatever the document happened to name. It is the kernel's variable and `required:` may not claim it -
two answers to one question, and nothing would print which had been used. `local` is refused here:
Portainer clones, and there is nothing on your machine for it to clone.

{{< callout type="warning" >}}
**No secret may be written here, and the section has no field for one.** `url_from: PORTAINER` names the
prefix, so the URL is read from `PORTAINER_URL` and the token from `PORTAINER_TOKEN`. A key this section
does not take is **refused, not ignored** - because a parser that skipped what it did not recognise would
let a `token: ghp_...` sit quietly in a committed file, which is a thing that has already happened once
in this family.
{{< /callout >}}

**An absent section is not a refusal.** A product that deploys nowhere yet has no carrier to describe,
and every field above defaults to empty. The section becomes required the moment an environment points at
one - and then a `carrier:` naming nothing declared is refused, and told which carriers exist.

**`portainer:` is optional, and leaving it out is a statement.** A carrier that declares only `proxmox:`
is a machine the kernel creates and does **not** configure:

```yaml
carriers:
  lab:
    proxmox:
      endpoint: https://10.0.0.6:8006/
      token_from: PROXMOX
      node: pve-2
      kind: vm
      template: local:vztmpl/debian-13-standard_amd64.tar.zst
      storage: local-zfs
      ssh_key: "ssh-ed25519 AAAAC3Nz... you@host"
```

`deploy carrier` then stops after the machine exists and says so - *"exists on pve-2 and nothing was
installed on it"*. What runs there is your own to deploy, through a backend you register. Until si#258
the `portainer:` block was required, which made *carrier* and *Portainer host* the same word: an
apt -> Docker -> Portainer playbook ran at the end of every run with no branch in it, so a product that
wanted a machine got a workload it never asked for - and on a machine without `apt`, a red run.

**`backend: portainer` pointed at such a carrier is refused by name**, because that backend has nowhere
to put its stack. The refusal names the carrier and both ways out.

### `deploy:` - which version a deployment is deploying

A deployment names its version, and it has three kinds of answer:

```text
./myctl.sh prod deploy up --version 1.4.0     this exact published version
./myctl.sh prod deploy up --version latest    the newest published version
./myctl.sh prod deploy up --version local     the current code base, built now
```

**Three values for three meanings**, rather than one value that sometimes means a lookup and sometimes a
build. `local` touches no registry at all - that is the point of it - while the other two resolve against
one, and a version the registry does not serve is refused *before* anything starts:

> ghcr.io/acme/demo-app does not serve '9.9.9', so nothing was deployed. Published versions are what
> `latest` resolves against; `local` deploys the current code base without needing one

Asking for nothing is refused too. "Whatever is newest" is a choice somebody makes, and a deployment that
made it silently would be exactly the accident this section exists to remove.

**The section points at an entry you already have**, rather than naming a registry a second time:

```yaml
artifacts:
  app: { kind: image, registry: ghcr.io/acme, repository: demo-app, dockerfile: Dockerfile }

deploy:
  source: { artifacts: app }
```

Everything about *where* comes from that entry, so there is one place a registry is written down. An
entry that cannot serve as a deployment source says so by name - one that is a bare string rather than a
mapping, or that carries no `registry:` - and the message lists the keys it does carry, because the next
question is what to add.

**The section is also the binding** (si#435). `deploy:up` has an input port, `source`, and the loader binds
it from `deploy: source:`, so the plan rules see a deploy as they see every other consumer: an aggregate
that runs `deploy up` before the build of its image is refused at load. A `consumes:` on a `deploy:up`
command is refused, because it would state the same fact a second time:

> command 'deploy up' binds `consumes: source`, and task 'deploy:up' takes that port from `deploy: source:`,
> which already names what is deployed - name it there, once

A deploy asks for no test result. That question belongs to the test levels, which have not been built yet
(si#450).

{{< callout type="info" >}}
**One source, many targets.** `dev|test|uat|prod` choose where a deployment goes, not where the artefact
comes from. Build once, deploy often - and a promotion is only provable if the number that went to test
is the number that goes to prod.
{{< /callout >}}

### `generated:` - the files that must be what their command produces

A generated file you commit carries one fact twice: the source it comes from, and the bytes in the tree.
They drift, and the drift is visible only to somebody who regenerates - which is exactly the person who
was not going to.

```yaml
generated:
  completion: { path: deploy/completions/myctl.bash, by: support completion }
  reference:  { path: docs/site/content/with-what/commands.md, by: docs reference }
```

`./myctl.sh test generated` runs each `by:` and fails if the file it produced is not the file that was
committed, naming which one and what to run. `by:` is the command a person would type, without the
launcher.

{{< callout type="warning" >}}
**It regenerates into your working tree.** That is what makes the comparison real - generating into a
temporary directory would compare two files your own command never produced side by side. A CI checkout
is disposable; on your own machine, expect the files to be rewritten.
{{< /callout >}}

**A file git does not track is a failure, not a pass.** The obvious implementation of this gate is
`git diff --exit-code`, and over an untracked path that exits 0 - so the artefact that was never
committed at all, which is this mistake in its most complete form, would come back green. Each entry is
checked for being tracked before anything is regenerated.

**And a regeneration that fails is not freshness either.** A command that could not run leaves the file
exactly as it was, so the diff is empty. The gate reads the return code, because "regenerated, and it
matched" and "did not regenerate, and nothing changed" are two different things.

**An API contract is one of these, and that is the whole of the answer** (si#240). A product that exports
its OpenAPI document and commits it has a generated file like any other - so the export is a `build`
command the `spec` entry of the python and java toolchain profiles scaffolds, and the *checking* is this
section:

```yaml
generated:
  contract: { path: api/rest/openapi.json, by: build spec }
```

Nothing about that is REST-specific, and nothing about it is a language's. The question had been asked
twice in this family before it was answered once: a Python product wrote `git diff --exit-code` over its
contract and called it its CI staleness gate, and this kernel wrote a suite for its own shell completion.
Both are the same six lines - and the first of them is the version that passes green over a contract
nobody ever committed.

### `tracker:` - where a refused step becomes a ticket

`test:walk` puts a person through the product's `.feature` files one step at a time. When they refuse a
step, that refusal is a bug report somebody has to write - so the kernel writes it, and this section is
what it needs to know:

```yaml
tracker:
  kind: github                 # the only one implemented; the default
  repo: ""                     # "owner/name", or "" for the checkout's own remote
  labels: ["bug"]
  title: "Acceptance refused: {scenario} ({version})"
  preamble: >
    A person walked the acceptance scenarios and refused this step. The verdict is a
    human judgement rather than a measurement.
```

**`title:` is the one key with no default**, on purpose: a kernel-invented title is the first thing a
maintainer reads and the last thing the kernel should be guessing. It may name `product`, `version`,
`revision`, `address`, `feature`, `scenario`, `step`, `step_number` and `step_total`; a field that is not
on that list is answered with the list.

**`preamble:` is the product's own wording**, put above the evidence the kernel writes underneath - the
step, the version, the revision, who walked it, when, and what they said.

A second walk that refuses the same step again **does not open a second ticket**. Each one carries a
`simplon-walk-id:` line in visible prose, and the search for it is what makes the walk idempotent - the
line is prose rather than an HTML comment so the person reading the ticket can see why, too.

{{< callout type="info" >}}
**Nothing here ever costs a refusal.** A section that is missing, incomplete or wrong - no `title:`, a
`kind:` this simplon cannot reach, a manifest that will not parse - is said out loud and names what it
wanted, and then the walk carries on: the refusals stay in the record and the run is still red. That is
why none of it raises. The sitting has a person's afternoon behind it, and a manifest typo must not throw
it away.
{{< /callout >}}

## The flat form, and how to leave it

You may meet an older spelling, in a manifest that predates the tree: a body written straight onto a
command, and catalogue tasks placed through an `import:` section plus a coordinate-keyed `tasks:` entry.

```yaml
groups:
  build:
    wheel: { impl: "orchestrator.cli:build_wheel", help: "Build the wheel." }

import:
  delivery: [docs]

tasks:
  docs:reference:
    group: build
```

**That form was abolished in 0.4.0.** A manifest written that way no longer loads, and the loader says
so by name rather than letting it die further down as a missing key on some node. Since si#344 it says so
second: the `groups:` key is refused first, with `simplon manifest migrate` as the way out, and the
migration moves each group under `ci:`, `cd:` or `support:` without reading what it holds - so the flat
groups are still flat afterwards, and this is the refusal that names them there:

```
this manifest is written in the flat command form, which no longer loads: the form was abolished in
0.4.0 and this kernel is past it.

What says so here: group(s) 'build' name commands directly, with `impl:` on them; task(s)
'docs:reference' are keyed by a platform coordinate; an `import:` section makes catalogue coordinates
available.

What it becomes:
  - a command is an INSTANCE of a task: declare the body once under `tasks:` and let the command point
    at it with `task:`, under `ci: build: commands:` (or the phase it belongs to), `cd: deploy:
    commands:` or `support: commands:`
  - a catalogue task keeps its body in the kernel - the command names the coordinate
    (`task: "<namespace>:<name>"`) and copies nothing
  - the catalogue's own commands arrive by merging its tree, so `import:` has nothing left to do -
    delete the section

This migration is documented at
  https://marcozwyssig.github.io/simplon/how/manifest/#the-flat-form-and-how-to-leave-it
and the shape it leads to at
  https://marcozwyssig.github.io/simplon/how/manifest/

Nothing here rewrites the file for you: the sections have to be edited by hand, which is also the only
way your comments survive the move.
```

The manifest above becomes:

```yaml
tasks:
  wheel: { impl: "orchestrator.cli:build_wheel", help: "Build the wheel." }

ci:
  build:
    commands:
      wheel: { task: "wheel" }
      reference: { task: "docs:reference" }
```

*(Until 0.11.0 the refusal also printed that block for you, rendered from your own manifest. The
renderer went in si#85: no manifest that installs this kernel had been on the flat form since 0.4.0, so
it was some 250 lines describing the manifest's shape a second time, where nobody reading was left to
notice it drifting - and si#56 had just found a property of it that was mis-documented from the day it
was written. This page is the source that is maintained.)*

Seven things to know while you convert:

- **An aggregate crosses unchanged.** A command with `depends_on:` and no `impl:` was never a body, so
  there is nothing to move out of it.
- **A shared body becomes one task.** Two commands that spelled out the same `impl:` are one template
  with two placements - which is the point of the form. Do not carry the duplication across.
- **A name collision needs two task names.** `build build` and `deploy build` are two different bodies
  under one command name. That is legal in the tree and impossible in one flat `tasks:` block, so one of
  the two bodies has to be declared under a different task name; the commands keep the names they had.
- **A name the catalogue places needs `override: true`.** `support install` is your body under a name
  the platform already uses, so the merge demands you say you mean it. Where your placement names the
  platform's *own* body, it is a refinement and needs no key.
- **A `tasks:` entry with `group:` keeps its body and loses the key.** Its body is already where the
  tree form wants it; what makes it flat is that it places its own command. Delete `group:`, and add the
  command under its group's `commands:` - in `ci:`, `cd:` or `support:` - pointing at the task with
  `task:`. Leaving the key behind is
  the one case where a manifest fixed by eye is refused a second time.
- **A coordinate-shaped name with its own `impl:` is *your* body, not the platform's.** `docs:site:` with
  no `impl:` names the kernel's task and copies nothing; `docs:site:` carrying an `impl:` was never a
  placement of the platform's body at all - it is yours under a name that looks like theirs. Keep the
  `impl:`, rename the task to a bare name, and point the command at that.
- **Your comments are yours to carry.** Nothing rewrites the file for you any more, which is the one
  respect in which this is easier than it was: a generated block was correct YAML carrying none of the
  reasoning the file it replaced carried, and a consumer whose manifest held forty lines of it kept them
  only because somebody looked.

What no conversion can fix is an old manifest that says something the tree form does not allow at all -
a group the platform's tree does not declare, a coordinate placed outside the group its namespace names,
a name that is an aggregate for you and a task-backed command in the catalogue. Those are refusals of
your manifest rather than of its spelling, and each names its own way out.

What you lose is the `import:` section, and you lose nothing with it: the catalogue's own commands
arrive by merging its tree, and any other coordinate is named directly by the command that wants it.
