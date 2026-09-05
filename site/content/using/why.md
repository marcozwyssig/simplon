---
title: "Why Simplon exists"
weight: 1
---

Every software component that ships has the same five verbs behind it: build the artefacts, verify them,
publish them, put them into an environment, watch what is running there. Almost every component writes
those five verbs itself, and almost every one writes them a little differently.

That is not a tidiness complaint. It costs three concrete things.

## The three costs

**A command line nobody maintains.** The delivery script starts as `build.sh`, grows a `case` statement,
then a second script for tests, then a Makefile someone added because the `case` statement got long. By
the time it has options with defaults and a help text, it is an argument parser written by hand - and an
argument parser written by hand is a thing whose `--help` is a separate document from its behaviour. The
day they disagree, the help text is what a human read.

**A capability that lives in one repo.** Somebody solves rendering the architecture docs, or pushing a
stack to Portainer, or provisioning the host's tooling. It works. It is four hundred lines in one
product's `scripts/` directory, and the next product that needs it either copies those four hundred lines
or does without. Copies drift; the second copy is the one that never gets the fix.

**Nowhere to put "and be careful about X".** The uid a container writes as, the difference between a tool
that is missing and a tool that failed, the reason a step must use the interpreter that is running rather
than whatever `python` resolves to - these are learned once, expensively, and then live in a person's
head or a comment in one file. They are not the kind of knowledge a README carries, because they only
become interesting at the moment something is being built.

## What Simplon does instead

**A component declares its commands; Simplon assembles the command line.** One manifest names the groups,
the commands in them, what each one implements and what its options are called. Simplon builds the Typer
application from that: the sub-applications, the help texts, the option types and defaults, the
environment gating. There is no argument parser to maintain, because there is no argument parser - there
is a declaration, and the `--help` is generated from the same declaration the dispatch uses. They cannot
disagree.

**A capability is a task, and a task is in the catalogue.** The kernel carries a catalogue of task
*coordinates* - `docs:render`, `test:gate`, `vcs:commit`, `support:install`. A product imports a
namespace and places the coordinates it wants as commands in its own tree. The body lives once, in the
kernel; what the product supplies is data - the pinned image tag, where its sources are, which suite
level to run. The fix to the body reaches every product on the next version bump, and there is no second
copy to forget.

**The rules are written down, with the defect that forced each one.** They have [their own
chapter](../../building/rules/), and it is deliberately the part of this site that cannot be generated.

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

## Where it comes from

Simplon grew up inside a family of infrastructure products - `netctl`, `infractl`, and others - that all
had the same five verbs and three separately maintained versions of them. It was extracted into a kernel
so those products could share one. The family is where it is proven, not where it is limited: nothing in
the kernel knows what a network lab is.

The kernel is also a product of itself. `simplon.yaml` in its own repository declares its own build, test
and support commands, assembled by the very kernel that repository builds. That is not a demonstration -
it is a guard. A tool never used in its own house rots unseen, and it was a spike doing exactly that
which found the task catalogue being resolved by walking five directories up to a repository root: right
while the kernel was vendored, and silently wrong the moment it was installed from PyPI.
