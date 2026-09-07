---
title: "Getting started"
weight: 2
---

## Install

    pip install simplon

The runtime dependencies are declared as ranges rather than exact pins, on purpose: a published
package's pins become its consumers' pins, and exact versions belong in a product's own
`requirements.txt`.

One extra exists: `pip install simplon[typecheck]` adds mypy, which the `test:typecheck-python` gate
runs. A product that never declares that command does not need it, which is why it is an extra and not a
dependency.

## Scaffold a product

A fresh product has a chicken-and-egg problem: it has no virtual environment, so it has no Simplon to
write its launcher with. Break it once, by hand:

    pipx run simplon init myctl --dir .

or install Simplon into any environment and run `simplon init myctl --dir .` inside the product
repository. After that the generated launcher carries itself, and a later `simplon init` refreshes it.

{{< callout type="warning" >}}
Without `--dir .` the skeleton lands in a **new `./myctl/` subdirectory**, not at the repository root.
Pass `--dir .` whenever the repository *is* the product.
{{< /callout >}}

### What it writes

    myctl.sh                                     the entry point (bash)
    myctl.cmd                                    the same entry point for cmd.exe
    myctl.yaml                                   the starter manifest
    orchestrator/requirements.txt                the host-venv deps, kernel pinned by version
    orchestrator/src/python/orchestrator/
        __init__.py                              the product package
        __main__.py                              `python -m orchestrator` entry
        cli.py                                   the composition root
        paths.py                                 the product-context wiring
        environments.py                          the environment provider

Nine files, and only two of them are yours to edit day to day: `myctl.yaml` and `cli.py`.

The `orchestrator/` block - the directory holding `.venv`, `requirements.txt` and `src/python/` - is a
parameter, not a decree. A product whose own layout reserves the repository root moves the whole block:

    simplon init myctl --dir . --orch-dir deploy/provision/orchestrator

The value must be a plain relative path under the target; an absolute one, or one containing `..`, is
refused rather than scaffolded somewhere unexpected. Both launchers derive their virtual environment,
their requirements file and their `PYTHONPATH` from that single variable, so the block moves in one
piece and nothing needs a hand-edit. The Python package stays `orchestrator` under any layout - it is an
identifier resolved on `PYTHONPATH`, not a location.

Pass the same flag on a later refresh, and note that `--force` overwrites the launchers: a hand-edit
does not survive one.

### The starter manifest

Stripped of its comments, `myctl.yaml` is this:

```yaml
product: myctl

tasks:
  build:   { impl: "orchestrator.cli:build",   help: "Build the product artefacts (placeholder)." }
  check:   { impl: "orchestrator.cli:check",   help: "Verify the artefacts (placeholder)." }
  up:      { impl: "orchestrator.cli:up",      help: "Deploy the product to the target environment (placeholder)." }
  down:    { impl: "orchestrator.cli:down",    help: "Tear the deployment down (placeholder)." }
  status:  { impl: "orchestrator.cli:status",  help: "Report what is running in the target environment (placeholder)." }

groups:
  build:
    commands:
      build: { task: build }
  test:
    commands:
      check: { task: check }
  release:
    commands:
      tag: { task: "release:tag" }
  deploy:
    commands:
      up:   { task: up }
      down: { task: down }
      all:
        help: "Run build then deploy up end to end (the build->up dependency plan)."
        depends_on: [build, up]
        stop_on_failure: false
  monitor:
    commands:
      status: { task: status }
  support:
    commands:
      install: { task: "support:install" }

default: dev
environments:
  dev: { backend: local, description: "Local development environment (the default)." }
```

**All five phases of the loop are there, plus `support`** - `build`, `test`, `release`, `deploy`,
`monitor` - and that is on purpose. The groups are not this manifest's invention: the kernel's catalogue
declares them, every Simplon product hangs its commands off the same six, and a group name the catalogue
does not declare is refused at load. A scaffold that showed two of them would teach you two ribs of a
corset you are going to be wearing anyway. Each starts with one command so you can run it today; grow a
phase by adding to its `commands:` list.

Two sections, and the split is the model:

- **`tasks:`** holds the **bodies**, each written down once as a `module:function`.
- **`groups:`** holds the **placements**. A command is an *instance* of a task, so it names one with
  `task:` and never writes an `impl:` of its own. That is what lets the same body sit at two commands
  with different pinned values - `test unit` and `test system` over one `test:gate` - without being
  copied.

Six commands, and each is a live example of a different shape:

- **`build`** is a single-member group whose member shares the group's name. Simplon collapses that to
  one flat top-level command, so you type `myctl build`, not `myctl build build`.
- **`up`**, **`down`** and **`status`** sit in env-first groups. They take a target environment as the
  outer token: `myctl dev deploy up`. Which groups are env-first is the catalogue's statement, not a
  second list in your manifest.
- **`tag`** and **`install`** name a **catalogue coordinate** - `task: "release:tag"`, with a colon. The
  body lives in the kernel; the line only says where the command sits in your tree. A `task:` without a
  colon names one of your own tasks above.
- **`all`** names no task at all - only `depends_on: [build, up]`. That is an **aggregate**: the kernel
  plans its dependencies and runs each as a step. It is a working example rather than a dead
  placeholder, which matters, because the aggregate is the shape people get wrong first.

### The first run

    ./myctl.sh help

The launcher provisions its own virtual environment on first use and installs the pinned kernel from
PyPI. Nothing is vendored, and there is no submodule to initialise. On a bare host it goes further than
that: it checks that `python3` can actually *create* a virtual environment (Debian and Ubuntu ship one
that cannot, because `ensurepip` lives in a separate package) and installs the interpreter-matched
package where it can do so without a prompt. That is not politeness - it is what keeps an ephemeral CI
runner green, since such a runner heals itself on every job rather than depending on a manual install
that died with the last container.

What comes back is the assembled CLI, in two panels:

```text
╭─ CI / agnostic (no env) ─────────────────────────────────────────────────────╮
│ build    Build the product artefacts (placeholder).                          │
│ release  release commands. Environment-agnostic (no env).                    │
│ support  support commands. Environment-agnostic (no env).                    │
│ test     test commands. Environment-agnostic (no env).                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ CD / env-first (myctl <env> <group> <cmd>, default dev) ────────────────────╮
│ deploy   deploy commands. Env-first: `myctl <env> deploy <cmd>` (default dev)│
│ monitor  monitor commands. Env-first: `myctl <env> monitor <cmd>` (default   │
│          dev).                                                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

Nobody wrote those panels, and nobody listed the groups in them either. They are the catalogue's own
`env_first:` rendered: the groups that take an environment and the groups that refuse one, told apart in
the help because they are told apart in the dispatch. `support` has more under it than your manifest
asked for - `support git commit`, `support tasks catalogue` - because the catalogue places those in
every product; try `./myctl.sh support tasks catalogue` to see the whole coordinate space.

Now run something:

```text
$ ./myctl.sh build
[14:48:58] ==> myctl: build (placeholder) - wire me up in orchestrator/src/python/orchestrator/cli.py
```

And try to run it against an environment:

```text
$ ./myctl.sh dev build
[14:48:59] ERR 'build' is environment-agnostic and takes no env prefix; run './myctl.sh build'
$ echo $?
1
```

That refusal is worth a second look on day one. `build` produces an artefact; an artefact built "for
dev" is either a lie or a different artefact, and both are worth failing over. The manifest said which
groups take an environment, so the dispatch can say no - and it says no with the command you meant.

### Make TAB work

One more command on day one, and it is the one nobody thinks to look for:

    ./myctl.sh support completion
    echo "source $PWD/completions/myctl.bash" >> ~/.bashrc

That writes `completions/myctl.bash` - the whole command tree as a shell function - and the second line
is what makes it do anything: a generated completion nobody sources completes nothing. Open a new shell
and `./myctl.sh support git <TAB>` answers from the manifest. In zsh the same file works after
`autoload -U +X bashcompinit && bashcompinit`.

**Commit the file.** It is generated from `myctl.yaml`, so it is a second description of the command
tree, and a second description drifts: run `./myctl.sh support completion --check` in CI, which exits 1
when a command has been added and the completion does not know it.

Why a file rather than the completion Typer ships: Typer's runs the program on every TAB. Measured on
this kernel's own CLI, a start costs 340-360 ms and one call of the generated function costs 0.16 ms.
The file is registered on `myctl.sh` and that is deliberate - bash falls back to the part of a command
word after the final slash, so the same registration answers for `./myctl.sh` and for an absolute path.

## Growing it

Two files, and the division between them is the whole design:

**`myctl.yaml`** - what commands exist, what they are called, which group they live in, what their
options are named, which ones take an environment, what depends on what.

**`orchestrator/cli.py`** - the callables the manifest's `tasks:` block points its `impl:` at. Replace
`build`/`check`/`up`/`down`/`status` with your own; keep them as module-level functions, because that is
what `"orchestrator.cli:build"` means - import this module, get the attribute named after the colon.

Everything else - the sub-application per group, the flat aliases, the help panels, the option types and
defaults, the environment gate - is assembled from the manifest by the kernel. That is why the next
chapter is about the manifest and not about a plugin API.

Ready for real work? [Worked examples](../examples/) walks six jobs end to end. If you are the person
who has to *build* the product rather than run it, go to [Building on
Simplon](../../building/manifest/).
