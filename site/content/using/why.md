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

## The same five verbs over very different work

The vocabulary is fixed and the technologies are not. What makes that trade worth making is not visible
from either half on its own - it becomes visible when you ask what *kind of work* the tasks are.

Delivering a component is not one activity. Version control, testing, documentation, packaging, the
machine everything runs on: these are separate kinds of work, done with separate tools, frequently by
separate people, and no one of those toolchains has anything to say to the others. `pytest` knows
nothing about Hugo. `oras` knows nothing about `mypy`. A vocabulary that described them *technically*
would have to be six vocabularies, and nobody would be able to read across them.

The catalogue is where this can be checked rather than taken on trust. Every coordinate in it, grouped
by the kind of work instead of by the phase it runs in:

| the work | what the bodies shell out to | coordinates |
|---|---|---|
| version control | `git`, `gh` | `vcs:commit`, `vcs:push`, `vcs:prune-branches`, `vcs:submodules`, `vcs:auth-scopes`, `release:tag` |
| testing | pytest, mypy, Allure | `test:gate`, `test:accept`, `test:report`, `test:typecheck-python` |
| documentation | Hugo, docToolchain, the assembled command line itself | `docs:site`, `docs:render`, `docs:reference` |
| packaging and publishing | `docker`, `oras` | `build:image`, `release:image`, `release:artifact` |
| the machine and its services | `oras`, `docker compose`, the `claude` CLI | `support:install`, `support:nexus`, `support:claude-plugins`, `support:environments` |
| the manifest itself | nothing external | `tasks:generate`, `tasks:catalogue` |

Six kinds of work, and the middle column barely intersects. Every one of them is reached through
`build`, `test`, `release`, `deploy`, `monitor`, `support` and nothing else. That is the claim the fixed
verb list is worth making - not that five verbs are elegant, but that they are the only thing six
unrelated toolchains can all be addressed by at once. Take the list apart per team and you have not
gained expressiveness; you have lost the one word that meant the same thing in all six places.

The two ways of grouping cut the same coordinates differently, and the difference is the point rather
than an untidiness. `release:tag` is version-control work that happens in the release phase;
`docs:site` is documentation work that simplon files under `build` and another product could file under
`release`. Which half of a coordinate decides which is the placement-or-family rule, in [The five
phases](../../building/phases/#what-the-catalogue-offers-today).

{{< callout type="info" >}}
**A word this page does not use.** The goal this section comes from calls these *disciplines*. That
word is already spoken for here: [Writing a task](../../building/tasks/) uses "discipline" for
self-restraint - *the discipline that keeps the catalogue honest* - and so does the kernel's own source,
throughout. Two meanings of one word across one site is worse than a plainer word, so this page says
**kinds of work**, and "discipline" keeps meaning rigour.
{{< /callout >}}

The row that is *not* in the table is worth naming too. **Running things** - putting a component into an
environment and watching it there - is a kind of work like the others, and the catalogue carries nothing
for it at all. Not because it is not real work, but because its tools belong to the shared environment
rather than to the product, and who should own them is still open. Those are the two empty ribs, in
[The five phases](../../building/phases/#the-two-empty-ribs).

## Why the technology travels in a container

A task body shells out to a tool, which raises the question the section above walked past: *where does
the tool come from?* There are two answers, and the kernel does not give the same one everywhere.

The first is to provision the machine - install Hugo, install docToolchain, write the versions down
somewhere, and hope the next machine gets the same ones. The second is to **bring the tool with the
task**: name an image, run the tool inside it, and let the build depend on that image instead of on
whatever happens to be installed where it runs. The second is what the two documentation renders do,
and it is what those two catalogue entries mean when they say *in Docker*:

> Build the product's documentation website with Hugo, in Docker (HTML only).

> Render the project docs via docToolchain (generateHTML + generatePDF) in Docker.

**It collapses the tool question into one question.** Hextra, the theme this site is built with, is a
Hugo *module*, and building a Hugo module needs Hugo Extended, Go and Git together - three installations
on a developer's machine, three ways to be the wrong version, three unrelated error messages to learn to
recognise. In an image it is none of them. "Which of the three is missing, and in which version?"
becomes "is docker there?", and that second question has an answer a script can act on.

**Which is why the image reference is refused at load unless it names a version.** A container that
brings whatever a moving tag points at today has relocated the problem rather than solved it - the
machine no longer decides what the build uses, but the calendar does:

> simplon.yaml: 'site': 'image' must pin a version ('<image>:<tag>'), got 'hugomods/hugo' - an untagged
> image means ':latest', which moves under the build; pin it as '<image>:<tag>' (e.g.
> 'hugomods/hugo:exts-0.148.2'), or by digest

The theme module is refused on the same grounds - `@latest`, `@master` and a bare branch name are
all queries that resolve differently tomorrow. Both declarations, and the rest of the `site:`
section, are in [The manifest](../../building/manifest/#product-data-sections).

### What it costs

A page that only listed the upside would be recommending something it had not used.

- **The pin fixes the version, not the availability.** `docs:site` runs `hugo mod get <module>@<version>`
  before *every* build, and there is no host-side module cache for it to answer from, so the call ends
  at `git ls-remote`. A build with no network is therefore impossible today, even when nothing has moved
  since the last one - which is reproducible without being repeatable, and those are not the same
  property. Open as [simplon#27](https://github.com/marcozwyssig/simplon/issues/27).
- **A green build proves less about the output than it looks like.** Hugo emits a Mermaid block into the
  HTML whether or not the Mermaid parses, because the diagram is drawn in the reader's browser and not
  during the build. Measured: a one-character error in the source gives exit code 0, a full page count,
  and the broken text verbatim in the published page. Open as
  [simplon#45](https://github.com/marcozwyssig/simplon/issues/45).
- **A container that writes into your tree writes as somebody.** The uid the image happens to run as is
  the uid that ends up owning the output, and both directions of getting that wrong have been measured
  here. The rule and both measurements are in [A container that writes into a mount runs as
  `--user`](../../building/rules/#a-container-that-writes-into-a-mount-runs-as---user).
- **A container that is not there is not the same as one that failed.** No docker on the host is a hint
  and a zero exit code; docker present and no site produced is red. That distinction is a rule of its
  own: [A missing tool is not a failed tool](../../building/rules/#a-missing-tool-is-not-a-failed-tool).

### Where a container is the wrong answer

Not every tool belongs in one, and the catalogue says so out loud. The type gate's entry ends the other
way round:

> Type-check the product's Python sources with mypy, in the host venv (no Docker, no lab).

The reason is in what that tool has to see. mypy resolves the product's *installed* dependencies, and
without them every third-party import degrades into a blanket exception and the gate stops meaning
anything - so the interpreter it runs under has to be the one the product actually ships against. An
image would bring a Python of its own, which is precisely the wrong Python. The rule that comes out of
the pair: bring the tool in a container when the tool has no opinion about the product's installed set,
and use the product's own environment when it does.

Two more shapes are worth not confusing with either. `build:image` and `release:image` use docker
because the artefact *is* a container image - docker is the subject there, not the delivery vehicle -
and their verdict on a missing docker is the opposite of the site build's: they call the gate that
dies, because producing the image is the only thing they were asked to do. And `test:report` prefers a
local `allure` on the PATH, falls back to an image when there is none, and degrades to a hint when
there is neither: a container is one answer to "where does the tool come from", not the only one.

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
