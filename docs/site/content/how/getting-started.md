---
title: "Getting started"
weight: 1
aliases:
  - "/using/getting-started/"
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

### The name is a default, not a decree

Inside a git repository that is already named after the product, the name is **optional** and there is
nothing left to type:

    simplon init

It is read from the repository: the `origin` remote's repository name, or the working tree's root
directory name when there is no remote yet. The remote wins because it is the half that survives a clone
into a differently named folder, and the run prints which of the two it used.

The argument still wins whenever it is given, and that is the point of having one. A repository can be
called `tooling`, or hold two products at once; a directory is named for where it sits, not for what it
is.

A repository whose name cannot *be* a product name is refused rather than repaired. `Ops Tools` and
`my.ctl` would become a launcher filename, a manifest filename, a package path and a `<PRODUCT>_ENV`
variable, so a quietly mangled one is wrong in four places at once - the message names the argument that
fixes it. In a plain directory with no `.git` there is nothing to read, and `init` says so rather than
failing further down.

{{< callout type="warning" >}}
**The name also decides the directory.** With the name *given* and no `--dir`, the skeleton lands in a
**new `./myctl/` subdirectory** - pass `--dir .` whenever the repository *is* the product. With the name
*read from the repository*, the repository already is the product, so the skeleton lands at its **root**.
`--dir` overrides both.
{{< /callout >}}

### What it writes

    myctl.sh                                               the entry point (bash)
    myctl.cmd                                              the same entry point for cmd.exe
    myctl.yaml                                             the starter manifest
    .gitignore                                             what the kernel writes into your tree
    deploy/provision/orchestrator/requirements.txt         the host-venv deps, kernel pinned by version
    deploy/provision/orchestrator/src/python/orchestrator/
        __init__.py                                        the product package
        __main__.py                                        `python -m orchestrator` entry
        cli.py                                             the composition root
        paths.py                                           the product-context wiring
        environments.py                                    the environment provider

Ten files, and only two of them are yours to edit day to day: `myctl.yaml` and `cli.py`.

The block - the directory holding `.venv`, `requirements.txt` and `src/python/` - is a parameter, not a
decree. `deploy/provision/orchestrator` is the default because it is where every product that adopted
Simplon put it by hand: their own structure rules reserve the repository root. A product that owns its
root moves the whole block back up to it:

    simplon init myctl --dir . --orch-dir orchestrator

The value must be a plain relative path under the target; an absolute one, or one containing `..`, is
refused rather than scaffolded somewhere unexpected. Both launchers derive their virtual environment,
their requirements file and their `PYTHONPATH` from that single variable, so the block moves in one
piece and nothing needs a hand-edit. The Python package stays `orchestrator` under any layout - it is an
identifier resolved on `PYTHONPATH`, not a location.

Pass the same flag on a later refresh, and note that `--force` overwrites the launchers: a hand-edit
does not survive one.

### The `.gitignore`, and what it does not claim

The kernel writes into your tree, so `init` writes the rules for what it writes. Without them the first
`build deps` followed by `git status` offers you an 80 MB commit: the python profile installs pytest and
mypy into the bind mount, because a `--user` container may write nothing else. And it arrives earlier
than that - the launcher puts your orchestrator package on `PYTHONPATH` and the kernel imports it, so
`./myctl.sh help` leaves a `__pycache__/` behind before you own a single command.

The block is **appended once and never rewritten**. If your repository already has a `.gitignore` - which
it usually does, since `init` lands at the repository root - your file keeps every byte and the block goes
at the end; if the block's marker line is already there, the file is not touched at all, and `--force`
does not change that. So edit it, reorder it, delete half of it: the next `init` leaves your version
alone. The trade is that a stale block is never refreshed, which is the right way round for a file you
own rather than the kernel.

What it carries, and why each line is shaped the way it is:

    /.simplon-toolchain/    the python profile's user base (80 MB)
    /build/                 every build output the kernel names: logs, the run transcript, the fetched
                            tool binaries, the hugo cache, docToolchain, dotnet's home, the nupkgs
    /.gradle/               gradle's project-local state, written by `docs:render`
    /tests/reports/         a gate's allure run, its junit xml and its verdict stamp
    allure-results/         ... the two of those whose names hold wherever `reports:` points
    allure-report/
    .venv/                  the launcher's host venv, and a test gate's
    __pycache__/            python's, wherever the kernel imported something

The first four are anchored to the product root with a leading `/` because that is the only place the
kernel writes them - and because `build/` without it would also hide a target directory named `build`,
into which `build cmake-files` generates a `CMakeLists.txt` that is meant to be **committed**.

The last three cannot be anchored, and `.venv/` is the one to know about: unanchored, that single line
covers the launcher's venv wherever `--orch-dir` puts it **and** a test gate's `suite:` venv, on any host
python. It is there because a venv self-ignores only from CPython 3.13 on, where `EnvBuilder` gained
`scm_ignore_files` - measured, `python:3.12.14` writes no `.gitignore` into a fresh venv and
`python:3.13.15` writes one holding `*`. The block was first written without that line, passed on a 3.13
developer machine and failed in CI on 3.12; CI was right, because `myctl.sh` is written to survive a bare
host and pins no host python at all.

Three things are deliberately absent:

- **`.pytest_cache` and `.mypy_cache`.** Both tools write their own `.gitignore` holding `*` into the
  directory they create, so git already cannot see them - unlike a venv, unconditionally. A rule here
  would read as though it were doing work git was already doing.
- **What the kernel generates to be committed**: the CMake files, the solution and its projects,
  `nuget.config`, `deploy/completions/myctl.bash`, `.github/workflows/*.yml` and the generated CLI
  module. They land among your sources and carry a `DO NOT EDIT` header, not an ignore rule.
- **Paths only your manifest knows.** `docs:site` writes to the `output` you declare and reads the
  `source` you declare, where hugo leaves a `resources/` cache; `docs:reference` writes the page you name.
  None of those keys has a default - the kernel refuses the section rather than guessing - so a scaffolder
  running before any of them exists cannot write their lines either. Those are yours.

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
[14:48:58] ==> myctl: build (placeholder) - wire me up in deploy/provision/orchestrator/src/python/orchestrator/cli.py
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
    echo "source $PWD/deploy/completions/myctl.bash" >> ~/.bashrc

That writes `deploy/completions/myctl.bash` - the whole command tree as a shell function - and the second line
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

**`deploy/provision/orchestrator/src/python/orchestrator/cli.py`** - the callables the manifest's
`tasks:` block points its `impl:` at. Replace
`build`/`check`/`up`/`down`/`status` with your own; keep them as module-level functions, because that is
what `"orchestrator.cli:build"` means - import this module, get the attribute named after the colon.

Everything else - the sub-application per group, the flat aliases, the help panels, the option types and
defaults, the environment gate - is assembled from the manifest by the kernel. That is why the next
chapter is about the manifest and not about a plugin API.

Ready for real work? [Worked examples](../../what/examples/) walks eight jobs end to end. If you are the person
who has to *build* the product rather than run it, go to [Building on
Simplon](../manifest/).
