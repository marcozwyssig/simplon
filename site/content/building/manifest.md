---
title: "The manifest"
weight: 3
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
rule](../rules/#a-group-with-no-commands-does-not-appear) and why both halves are needed.

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
rule](../rules/#a-name-collision-breaks-loudly), and the merge behaviour behind it is in [Task and
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
the token. See [Environments](../environments/) for what the dispatch does with it.

## Product data sections

Beyond the command tree, a manifest carries the **data** its tasks read. This is the seam that makes a
catalogue task a promise to three products instead of a convenience for one: the mechanism is the
kernel's, the values are the product's, and the section is where they meet.

```yaml
site:
  image: "hugomods/hugo:exts-0.148.2"
  source: "site"
  output: "build/website"
  base_url: "https://example.github.io/myctl/"
  theme: "github.com/imfing/hextra@v0.12.3"
```

Every value is **required to be declared** rather than defaulted. A kernel that assumed `site/` and
`public/` would work for the product that happens to use those names and silently build nothing for the
next one; a kernel that named the image would be choosing a documentation generator on every product's
behalf. A missing section fails at load, naming the key, instead of as a container run against a
directory that is not there.

Two of those values are refused unless they pin a version. `image: "hugomods/hugo"` means `:latest`,
which moves under the build; `theme: "...@latest"` fetches whatever is newest on the day it runs. A
build whose output depends on when it ran is not a build, and a documentation site is committed-to
prose - a generator change rewrites it wholesale. `source` and `output` must be plain relative paths
under the product root, for a blunter reason: `output` is handed to a recursive delete, and
`output: /var/tmp/x` would delete `/var/tmp/x`.

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

**That form is gone.** A manifest written that way no longer loads.

It does not fail with "no longer supported", though, and that is the part worth knowing about: the
loader rewrites *your* sections, in *your* names, and prints the result. Feeding the manifest above to
the loader answers with

```
this manifest is written in the flat command form, which this kernel no longer loads: group(s) 'build'
name commands directly, with `impl:` on them; task(s) 'docs:reference' are keyed by a platform
coordinate; an `import:` section makes catalogue coordinates available. Rewrite those sections as:

    tasks:
      wheel: { impl: "orchestrator.cli:build_wheel", help: "Build the wheel." }

    groups:
      build:
        commands:
          wheel: { task: "wheel" }
          reference: { task: "docs:reference" }

  - a command is an INSTANCE of a task: the body is declared once under `tasks:` and the command points
    at it with `task:`
  - a catalogue task keeps its body in the kernel - the command names the coordinate
    (`task: "<namespace>:<name>"`) and copies nothing
  - the catalogue's own commands arrive by merging its tree, so `import:` has nothing left to do -
    delete the section
```

Paste that block over the sections it names and the manifest loads. The rewrite covers the whole of
`tasks:` and `groups:`, including any group you had already converted, so a half-migrated manifest does
not lose its converted half when you paste. Four things to know about what it does:

- **An aggregate crosses unchanged.** A command with `depends_on:` and no `impl:` was never a body, so
  there is nothing to move.
- **A shared body becomes one task.** Two commands that spelled out the same `impl:` come out as one
  template with two placements - which is the point of the form.
- **A name collision is qualified, not shadowed.** `build build` and `deploy build` are two different
  bodies under one command name; the rewrite renames the second task.
- **A name the catalogue places carries `override: true`.** `support install` is your body under a name
  the platform already uses, so the merge demands you say you mean it - and the rewrite says it for you.

So what it prints loads, as printed, in one round. What no rewrite can fix is an old manifest that says
something the tree form does not allow at all - a group the platform's tree does not declare, a
coordinate placed outside the group its namespace names, a name that is an aggregate for you and a
task-backed command in the catalogue. Those are refusals of your manifest rather than of the block, and
each names its own way out.

What you lose is the `import:` section, and you lose nothing with it: the catalogue's own commands
arrive by merging its tree, and any other coordinate is named directly by the command that wants it.
