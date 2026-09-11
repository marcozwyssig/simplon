---
title: "The manifest"
weight: 3
aliases:
  - "/building/manifest/"
---

One YAML file per product. It declares what commands exist, what they run, what they are called and
which of them take an environment - and the CLI is assembled from it, so there is no second place where
any of that is also true.

## The command tree

Groups are slots in the CI/CD loop; commands are the members of a group. The kernel's catalogue owns
which groups exist - `build`, `test`, `release`, `deploy`, `monitor`, `support` - and a product fills
them:

```yaml
product: myctl

groups:
  build:
    commands:
      wheel: { task: "pkg:wheel", help: "Build the wheel." }
  support:
    groups:
      git:
        commands:
          commit: { task: "vcs:commit" }
```

A group node has exactly four keys: `help`, `env_first`, `groups` and `commands`. Members live under
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

groups:
  build:
    commands:
      wheel: { task: "wheel" }
```

A command never writes `impl:` itself. A bare `task:` value names a task this manifest declares; one with
a colon names a catalogue coordinate, whose body lives in the kernel.

## Pinning values with `with:`

The same body, placed twice, with different data:

```yaml
groups:
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

How MANY run at once is the machine's answer rather than the manifest's, because the manifest travels
between machines and the number does not: `SIMPLON_MAX_PARALLEL` sets it, and the default is four or the
CPU count, whichever is smaller.

Every `depends_on` entry must name a known, unambiguous command, and the graph must be acyclic. Both are
checked at load, not at run: a dependency naming a command that does not exist is a manifest error, and
it should not wait until the eleventh minute of a pipeline to say so.

`hidden: true` keeps a command out of every `--help` listing while leaving it fully invocable - which is
what a plan step named in a `depends_on` needs, since it must be a real command but need not clutter a
menu meant for a human.

## Environments

```yaml
env_groups: [deploy, monitor]

default: dev
environments:
  dev:  { backend: local,    description: "Local development environment." }
  prod: { backend: exoscale, description: "Production." }
```

A group's env gate is normally the **catalogue's** statement, not yours: `deploy` and `monitor` carry
`env_first: true` on their nodes there, so every product gates them the same way and no manifest has to
say it twice. `env_groups:` is the flat spelling of the same statement, and it is held to the same rule:
listing a group the catalogue already gates is a harmless restatement, listing one the catalogue
declares **not** env-first is refused exactly as `env_first: true` on that group's node is. It is the
manifest's own statement only for a **top-level group no catalogue owns**. Everything not gated refuses
the token. See [Environments](../../with-what/environments/) for what the dispatch does with it.

## Product data sections

Beyond the command tree, a manifest carries the **data** its tasks read. This is the seam that makes a
catalogue task a promise to three products instead of a convenience for one: the mechanism is the
kernel's, the values are the product's, and the section is where they meet.

```yaml
site:
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
`simplon.surface.CONSUMERS`, and secure-windows-images - three of those seven declare a `site:` section
and the three do not agree: cleon at `site`, biz-cockpit at `docs/website`, simplon at `docs/site`. Two of those three would
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
Measured over every manifest this kernel can reach, its own and the six in other repositories, eleven of
the seventy top-level keys are exactly that, and every one of them is read by a body in the product's own
repository. Adding a key nobody here has heard of is a supported thing to do.

What was missing is the other half: **which names are already taken**. The product si#159 was reported
from builds three Windows Server *releases*, and it learned that `releases:` already means
`{page, from, complete_from}` to `test:release-notes` by reading `src/simplon/tasks/releasenotes.py`. A
reserved name that can only be found in the source is a trap with a delay on it, so the sixteen are
published here and `tests/test_manifest_top_level.py` holds this table to the kernel in both directions.

| key | read by | what it carries |
| --- | --- | --- |
| `artifacts:` | `release:artifact`, `release:nuget-*`, `release:conan-*` | one entry per published artefact: registry, repository, source directory, media type |
| `assets:` | `release:asset` | one entry per file attached to a GitHub release |
| `build:` | `build:cmake-files`, `build:dotnet-solution` | `targets:`, the dependency edges between build targets that a directory layout cannot show |
| `claude:` | `support:claude-plugins` | the marketplaces and plugin ids an agent host installs |
| `default:` | the environment selector | the environment a command targets when no env token is given |
| `doctoolchain_version:` | `docs:render` | the pinned docToolchain image tag |
| `env_var:` | `support:environments` | the variable a product's env-first CLI publishes the active environment into |
| `environments:` | the environment selector | the environment matrix: name, backend, description |
| `images:` | `build:image`, `release:image` | one entry per container image: registry, repository, Dockerfile, context |
| `instance:` | the multi-tenant lab | the env var naming the lab instance, and the product's id-length budget |
| `lab_egress:` | the lab egress helper | the host interface a lab reaches the outside through |
| `nexus:` | the `nexus` commands | the proxy repositories, the compose file and the container this product runs |
| `releases:` | `test:release-notes` | `page:`, `from:` and `complete_from:`, the three values that gate says what it measures against |
| `site:` | `docs:site` | the pinned Hugo image, where the sources live, where the site is built to |
| `suites:` | `test:*` | the test-level taxonomy: the gates, their order, and which one clears the shared results |
| `workflows:` | `release:workflows` | one entry per generated CI file |

A key that is **mistyped** is therefore not the silent no-op it looks like. Fourteen of the sixteen are
named by the reader that wanted them, the moment that reader runs: `sietv:` instead of `site:` answers
`the 'site' section is missing or is not a mapping`, and every other reader refuses the same way, naming
the key it looked for. The two that say nothing say nothing on purpose:

- **`build:`** - an absent section is the normal case. `build cmake-files` and `build dotnet-solution`
  render the build files from the SOURCES, and `build: targets:` only adds the edges the directories
  cannot show. A `build:` section that exists for some other reason and carries no `targets:` says the
  same thing, on purpose - two live manifests have one, and the next section is about them.
- **`env_var:`** - a product that selects its environment by token and `default:` alone has no such
  variable, and a listing must still work on a manifest that has not adopted the key.

Both are driven in the test module above, so the silence is measured rather than assumed.

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
  is what si#159's measurement rules out - eleven of the seventy top-level keys across those manifests
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

### `images:` - the container image

`build:image` and `release:image` read one entry of this section, pinned per command with
`with: { name: ... }`, because a product may build more than one:

```yaml
images:
  app:
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
whole filesystem to the daemon as a build context.

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
is a statement about the *vorgang*, not about the work, so the gate reads the commits that merge brought
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
defines, `environments:` the deployment matrix, `nexus:` and `claude:` the data their respective tasks
read. A task that needs a section it does not find fails on its first line, which is why such tasks stay
*tasks* in the catalogue rather than being placed as commands for everybody.

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
so by name rather than letting it die further down as a missing key on some node:

```
this manifest is written in the flat command form, which no longer loads: the form was abolished in
0.4.0 and this kernel is past it.

What says so here: group(s) 'build' name commands directly, with `impl:` on them; task(s)
'docs:reference' are keyed by a platform coordinate; an `import:` section makes catalogue coordinates
available.

What it becomes:
  - a command is an INSTANCE of a task: declare the body once under `tasks:` and let the command point
    at it with `task:`, under `groups: <group>: commands:`
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

groups:
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
  command under `groups: <group>: commands:` pointing at the task with `task:`. Leaving the key behind is
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
