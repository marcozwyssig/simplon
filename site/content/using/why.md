---
title: "What Simplon is"
weight: 1
---

> **Simplon is the link between the CI/CD process and the technologies, and it brings structure and
> reusability.**

That sentence is the design, and it is a blueprint rather than a figure of speech. Every noun in it
names something you can point at: the process is a fixed set of groups, the technologies are what a task
body shells out to, the link is a resolution step in the loader with a name, and *structure* and
*reusability* are each a short list of things the loader refuses to do. This chapter takes it apart noun
by noun, and only then gets to the question the name of this page used to ask on its own - why not write
the five verbs yourself.

## The three nouns

### The CI/CD process is a closed vocabulary

Every component that ships has the same five verbs behind it: build the artefacts, verify them, publish
them, put them into an environment, watch what is running there. Simplon declares those five once, plus
a sixth for the machine itself, and they are the only groups there are:

```yaml
groups:
  build:   { help: "Produce the artefacts." }
  test:    { help: "Verify them." }
  release: { help: "Publish them." }
  deploy:  { help: "Put them into an environment.", env_first: true }
  monitor: { help: "Watch what is running there.", env_first: true }
  support: { help: "Host preflight, environment introspection and host tooling." }
```

A product fills those groups. It cannot invent a seventh, and the refusal is not a rule layered over the
merge - it *is* the merge. A product's tree is merged onto the platform's, so a path the platform does
not already declare has nowhere to land:

> groups entry 'publish' names a group the platform's tree does not declare. The platform owns which
> groups exist, so that the same groups and the same general tasks are there in every product. Available
> here: build, deploy, monitor, release, support, test. Either put these commands in one of those, or
> declare the new group in the platform's `groups:` - once, for everybody.

There is one tree, so there is no second way to bring a group into existence. That is what makes the
vocabulary hold: `test` means *verify* in every product that uses the kernel, and `deploy prod up` reads
the same to somebody who has never seen this particular product before.

### The technologies are behind a task, never in the vocabulary

Nothing above mentions pytest, Hugo, Docker, Allure, mypy, git or a package registry. Those live one
layer down, each behind a **task**: a body plus a coordinate that names it.

```yaml
docs:site:
  impl: simplon.tasks.site:build
  help: "Build the product's documentation website with Hugo, in Docker (HTML only)."
test:gate:
  impl: simplon.tasks.testrun:gate
  help: "Run a declared pytest suite against the running lab."
vcs:commit:
  impl: simplon.tasks.vcs:commit
  help: "git add -A + git commit -m."
```

A coordinate is deliberately **not** a module path. `docs:site` is a name in the catalogue's coordinate
space, and the body it points at can move inside the kernel without breaking a single product manifest.
The technology is an implementation detail of the body, which is why swapping one is a kernel change and
not a change to six manifests.

### The link is a named resolution step

Between the vocabulary and the technologies sits the manifest, and the linking is not a metaphor for
"gluing things together" - it is one function. `treeform.resolve` walks every command in the tree and
replaces its `task:` with the `impl:` the template names. On one side of that step there is a group path
and a command name; on the other there is a `module:function`. Nothing in between is inferred:

| what you wrote | what the step does |
|---|---|
| `task: "wheel"` — no colon | looks it up in **this manifest's** own `tasks:` |
| `task: "docs:site"` — a colon | looks it up in the **platform catalogue** |

One resolution rule, two sources, and the two name spaces cannot intersect - so nothing shadows anything
and there is no precedence to remember. A name that resolves in neither is a load error that lists what
*is* available, rather than a command that exists in the help and dies on invocation.

That is the whole of the link, and it is why the sentence at the top is a construction plan. You can
read the seam, test it, and put a breakpoint in it.

## What "structure" means here

Structure is not layout. It is a short list of things the loader **refuses** to do, and each refusal
removes one way for a command line to lie about itself.

- **A group you name is a promise.** Declare a group in your own tree and leave its whole subtree without
  a single command, and the manifest fails to load, naming the group. A group only the *catalogue*
  offers, which your tree never mentions, is dropped from the assembled CLI instead - a menu entry that
  leads nowhere is worse than no entry.
- **A command is an instance, never a body.** A command that writes `impl:` is refused with *"declare the
  body once under `tasks:` and point this command at it with `task:`"*. There is one place a body is
  declared, so there is one place to change it.
- **A collision breaks loudly.** Two different bodies under one command name is a load error that prints
  both by their real `module:function`, not a silent win for whichever dictionary was merged last.
- **The group's shape is the platform's.** A product may add commands and sub-groups to a group it
  inherits; it may not rewrite that group's `help:` or its `env_first:`. Turning `env_first` off quietly
  would ungate every command underneath it.
- **A declaration that renders nowhere fails.** A task key nobody reads, a `with:` pinning a parameter
  the body does not take, a parameter both pinned and given a `params:` entry it can no longer show - all
  of them are errors rather than silent no-ops.

The help text is generated from the same declaration the dispatch uses, so the two cannot disagree.
That is the practical shape of "structure": `--help` is not a document about the CLI, it is a rendering
of it.

## What "reusability" means here

The body lives once, in the kernel, under a coordinate. A **command** is a placement of it: the name, the
group, and the values pinned for this particular instance. So the same body can be placed several times,
in one product or in twenty:

```yaml
groups:
  test:
    commands:
      unit:   { task: "test:gate", with: { name: "unit" },   help: "Run the unit suite." }
      system: { task: "test:gate", with: { name: "system" }, help: "Run the system suite." }
```

Two commands, one body, and the difference between them is data. What a product supplies is exactly
that: the pinned image tag, where its sources are, which suite level to run. The mechanism is the
kernel's; the values are the product's; the manifest section where they meet is the seam that makes a
catalogue task a promise to several products rather than a convenience for one.

The consequence that matters is the one you feel on a bad day: the fix to a body reaches every product
on the next version bump, and **there is no second copy to forget.** The test for whether a body belongs
in the kernel at all is written down in [Writing a task](../../building/tasks/) - can it be written
without naming this product's directories, images or services?

## Why not just write the five verbs yourself

Almost every component does write them itself, and almost every one writes them a little differently.
That is not a tidiness complaint; it costs three concrete things.

**A command line nobody maintains.** The delivery script starts as `build.sh`, grows a `case` statement,
then a second script for tests, then a Makefile someone added because the `case` statement got long. By
the time it has options with defaults and a help text, it is an argument parser written by hand - and an
argument parser written by hand is a thing whose `--help` is a separate document from its behaviour. The
day they disagree, the help text is what a human read. Under Simplon there is no argument parser to
maintain, because there is no argument parser: there is a declaration, and the sub-applications, the
option types, the defaults and the help are all built from it.

**A capability that lives in one repo.** Somebody solves rendering the architecture docs, or pushing a
stack to Portainer, or provisioning the host's tooling. It works. It is four hundred lines in one
product's `scripts/` directory, and the next product that needs it either copies those four hundred lines
or does without. Copies drift; the second copy is the one that never gets the fix. A capability that is a
catalogue task has no second copy.

**Nowhere to put "and be careful about X".** The uid a container writes as, the difference between a tool
that is missing and a tool that failed, the reason a step must use the interpreter that is running rather
than whatever `python` resolves to - these are learned once, expensively, and then live in a person's
head or a comment in one file. They are not the kind of knowledge a README carries, because they only
become interesting at the moment something is being built. Here they are [rules with the failure that
forced each one](../../building/rules/), and the mechanism that enforces them is in the kernel rather
than in a person's memory.

## What it is not

Simplon is not a CI system. It does not schedule anything, it has no server, and it does not replace
GitHub Actions or GitLab CI. It is what those systems *call*: `./myctl.sh test all` reads the same in a
workflow file and in a terminal, which is the point. A step that only exists inside a CI runner cannot be
run by the person debugging it.

It is not a build system either. It has no dependency graph over files, no timestamps, no incremental
rebuild. A command's `depends_on` is a plan - run these first, once each - and idempotency is each
command's own promise. If you need Make, use Make; Simplon will happily call it.

And it is not a framework you write your product against. The product's own code does not import Simplon
to do its job. It imports it in exactly one file, the composition root, and that file's job is to hand
Simplon the manifest and the callables it names.

## The kernel is its own first product

`simplon.yaml` in the kernel's own repository declares its own build, test and support commands, and the
CLI that runs them is assembled by the very kernel that repository builds. That is not a demonstration.
It is a guard, and it exists because of a specific class of defect: the code path that only a *consumer*
walks is the one no test in the repository reaches.

The concrete shape of it is worth keeping in mind whenever a package reads a file of its own. Resolving
a data file by walking a fixed number of directory levels up to a repository root is exactly correct
while the package is vendored inside that repository, and meaningless once it is installed - from
`site-packages`, five levels up is somewhere else entirely, and the read raises `FileNotFoundError`. Every
test that reaches the source tree through a `sys.path` adjustment passes anyway, because none of them is
in the arrangement where the defect exists.

So the catalogue travels inside the package, and the kernel builds and tests itself with itself: when a
commit breaks the assembly, it fails in the same round instead of after a release. A tool never used in
its own house rots unseen.
