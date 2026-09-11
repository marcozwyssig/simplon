---
title: "What Simplon is"
weight: 1
aliases:
  - "/using/why/"
---

Every product invents its own delivery commands. One repository builds with `make all`, the next with
`./build.sh --release`, the third with a GitHub workflow nobody can run at a terminal. The work behind
them is the same work - build it, verify it, publish it, put it somewhere, watch it - and the spelling is
different every time. That is paid for twice on every onboarding: once to learn the tool, and once to
learn this team's way of saying it.

**Simplon puts the same five verbs on every product, whatever it is written in.** A product declares its
commands in one YAML file; the kernel assembles the command line from that declaration and runs the
steps. Somebody who has worked on the Java product can operate the C++ one without being told anything.

## Einfach

One file and a command exists - with its help text, its options and its place in the tree. Nobody writes
an argument parser:

```yaml
build:
  commands:
    wheel: { task: "pkg:wheel", help: "Build the wheel." }
```

`simplon init` writes the launcher, and the launcher provisions its own virtual environment and installs
the pinned kernel on first use. A fresh clone plus that one script is the whole setup.

## Strukturiert

Six groups exist - `build`, `test`, `release`, `deploy`, `monitor`, and `support` for the machine itself
- and that is all there are. A seventh is not refused by a rule bolted on top; it has nowhere to land,
because a product's tree is merged onto the platform's:

> groups entry 'publish' names a group the platform's tree does not declare. The platform owns which
> groups exist, so that the same groups and the same general tasks are there in every product. Available
> here: build, deploy, monitor, release, support, test. Either put these commands in one of those, or
> declare the new group in the platform's `groups:` - once, for everybody.

So `test` means *verify* in every product, and `deploy prod up` reads the same to somebody who has never
seen that product before.

## Agnostisch

The vocabulary names no technology. pytest, Hugo, Docker, Gradle, .NET, clang, Allure, mypy, a package
registry: every one of them sits behind a **task**, named by a coordinate, and the kernel knows nothing
about the product it serves.

```yaml
docs:site:
  impl: simplon.tasks.site:build
  help: "Build the product's documentation website with Hugo, in Docker (HTML only)."
```

Swapping the tool behind `docs:site` is a kernel change. It is not a change to six manifests.

## Erweiterbar

A task written once is available to every product that names its coordinate, and a product adds its own
data sections freely. Measured over every manifest this kernel can reach - its own and six in other
repositories - there are **seventy top-level keys, eleven of them read by a product's own body in
another repository, and not one read by nobody**.

## What it is not

**Not a CI system.** It schedules nothing, has no server, and does not replace GitHub Actions or GitLab
CI. Those *call* it: `./myctl.sh test all` reads the same in a workflow file and in a terminal, and a
step that only exists inside a CI runner cannot be run by the person debugging it.

**Not a build system.** No dependency graph over files, no timestamps, no incremental rebuild. It puts a
name on the step and hands it to the toolchain. A command's `depends_on` is a plan - run these first,
once each - and idempotency is each command's own promise. If you need Make, use Make; Simplon will
happily call it.

**Not a framework you write your product against.** The product's own code imports Simplon in exactly
one file, the composition root, and that file's job is to hand over the manifest and the callables it
names.

## What it costs to run

An ordinary PyPI dependency and one YAML file. No server, no agent, no second inventory, nothing
vendored and no submodule to initialise.

---

Next: [Getting started](../../how/getting-started/) is the shortest path from nothing to a running
command. [A Python product, end to end](../../what/case-python/) is the loop on a real product. And the
argument behind all of the above - the sentence this design comes from, taken apart noun by noun, with
the three places a hand-written delivery script goes wrong - is [The design, noun by
noun](../the-design/).
