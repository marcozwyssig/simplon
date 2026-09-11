---
title: "Getting started"
weight: 1
aliases:
  - "/using/getting-started/"
---

Four commands from an empty repository to a working delivery CLI. Everything else `init` wrote is on
[What `init` wrote](../what-init-wrote/).

## 1. Install

    pip install simplon

## 2. Scaffold

    pipx run simplon init myctl --dir .

Inside a git repository already named after the product the name is **optional** - plain
`simplon init` reads it from the `origin` remote's repository name, or from the working tree's root
directory when there is no remote yet.

{{< callout type="warning" >}}
**The name also decides the directory.** With the name *given* and no `--dir`, the skeleton lands in a
**new `./myctl/` subdirectory** - pass `--dir .` whenever the repository *is* the product. With the name
*read from the repository*, the repository already is the product, so the skeleton lands at its **root**.
`--dir` overrides both.
{{< /callout >}}

## 3. What landed


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

Ten files, and only two of them are yours to edit day to day: `myctl.yaml` and `cli.py`. The
orchestrator block is a parameter rather than a decree - a product that owns its repository root writes
`simplon init myctl --dir . --orch-dir orchestrator` instead, and [What `init`
wrote](../what-init-wrote/#the-orchestrator-block-is-a-parameter) says what moves with it.

## 4. Run it

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

## Where to go next

- [Worked examples](../../what/examples/) walks eight jobs end to end.
- [The manifest](../manifest/) is the file every command you add is declared in.
- [What `init` wrote](../what-init-wrote/) reads the rest of the scaffold - the ignore block, the starter
  manifest, shell completion, and the two files you go on editing.
