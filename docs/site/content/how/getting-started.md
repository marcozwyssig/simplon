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


