---
title: "A Python product, end to end"
weight: 5
---

Everything else on this half of the site shows one part at a time: how to get a command line, what to
type for a job that comes up, how a release is cut. This chapter is the loop itself - one Python
product, followed through all five verbs in the order they happen, with the manifest lines that make
each command exist and the tickets where a step does not.

It follows **two** products, because one is not enough to cover the five. Both are real and both are
Python:

- **simplon** - this kernel, scaffolded on itself. It builds a **wheel** and publishes it to **PyPI**,
  and the tag it is published under is the version.
- **agile-cockpit** - a private sibling product. It builds a **container image** and publishes it to
  **GHCR**, runs a system gate against a real GitLab instance, and deploys to the local host.

Between them, four of the five verbs are covered by work somebody really did. The fifth is `deploy`,
and that is not an oversight in the writing - it is the state of the kernel, and the table below says
so in the same column as everything else.

## The labels, and why they are on the page

A documentation page describing a pipeline nobody has driven is worse than no page: the reader follows
it, hits a command that does not exist, and concludes they misread the site. So every step in the table
below carries one of exactly three labels, and the evidence column says where to check it.

{{< callout type="info" >}}
**run** - somebody executed it. The evidence names who, where and when.

**derived** - read out of a manifest, a task body or a workflow file, and not executed for this page.
It is a statement about what is declared, not about what was observed.

**does not exist yet** - the step is named because leaving it out would make the loop look complete.
Every such row carries the ticket where the decision is still open.
{{< /callout >}}

| # | Step | Command | Label | Evidence |
|---|---|---|---|---|
| 1 | Generate the CI workflow from the manifest | `./simplon.sh support workflows --check` | run | this checkout, 2026-09-07; output below |
| 2 | Generate the shell completion from the manifest | `./simplon.sh support completion --check` | run | this checkout, 2026-09-07; output below |
| 3 | Build the wheel, version derived from the tag | `./simplon.sh build wheel` | run | this checkout, 2026-09-07; transcript below |
| 4 | Build the container image | `./agile-cockpit.sh build` (`build:image`) | run | agile-cockpit CI, every push; green 2026-09-06 |
| 5 | Run every unit suite | `./simplon.sh test all` | run | this checkout, 2026-09-07, green |
| 6 | Run the type gate | `./simplon.sh test typecheck-python` | run | this checkout, 2026-09-07, green |
| 7 | Run a system gate against a real service | `./agile-cockpit.sh test system` (`test:gate`) | run | agile-cockpit nightly workflow, 2026-09-07 02:36 UTC, green |
| 8 | Refuse a tag on a commit `main` does not carry | `./simplon.sh release tag v9.9.9` | run | this checkout, on a throwaway commit, 2026-09-07; refused before `create_tag`, `git tag -l 'v9*'` empty afterwards |
| 9 | Tag, then workflow, then PyPI | `./simplon.sh release tag v0.4.0` | run | simplon's release workflow, 2026-09-06 19:21 UTC; PyPI carries 0.4.0 |
| 10 | Push the image and read it back off the registry | `./agile-cockpit.sh release image` (`release:image`) | run | agile-cockpit CI on master, 2026-09-06 |
| 11 | Deploy to the local host | `./agile-cockpit.sh dev deploy up` | derived | read from the product's own task body: `docker run -d` against the image `build:image` tagged |
| 12 | Deploy past the local host - Proxmox, Portainer, a cloud | - | does not exist yet | [simplon#5](https://github.com/marcozwyssig/simplon/issues/5) |
| 13 | Build the documentation website | `./simplon.sh build docs` | run | this checkout, 2026-09-07; transcript below |
| 14 | Render the architecture documentation to HTML and PDF | `docs:render` | derived | the coordinate is in the catalogue; simplon places no command for it, so nothing here has run it |

Of the 14 steps above, 11 are **run**, 2 are **derived** and 1 **does not exist yet**. That ratio is
the point of the chapter rather than a happy accident: a Python product is the case where almost
everything can really be driven, because the kernel is itself one and publishes itself. A chapter full
of *derived* would have been a worse result than a shorter one full of *run*.

## Before the loop: the two things a product does once

Both write a file out of the manifest, and for both the interesting half is `--check`, which writes
nothing and returns 1 on drift - a pre-commit hook and a CI step in one command.

```text
$ ./simplon.sh support completion --check
[07:15:18]  OK deploy/completions/simplon.bash agrees with simplon.yaml

$ ./simplon.sh support workflows --check
[07:15:19]  OK .github/workflows/ci.yml agrees with simplon.yaml
[07:15:19] ==> .github/workflows/release.yml is declared hand-written: two-thirds prose and two multi-line shell scripts (the on-main report of si#23, the wheel-is-the-tag check of si#3); declaring it would move that work rather than remove it
```

Read the second line of that second output carefully, because it is the shape this project keeps
insisting on. `release.yml` is **not** generated - and the check does not stay silent about it. A file
it simply ignored would be a file nobody is accountable for; a file it *names* as declared
hand-written, with the reason, is accounted for. That distinction is the difference between "nothing to
do" and "nothing to say", and it is the defect this kernel hunts.

What each of those files contains, and how to declare them, is not repeated here:
[`workflows:` in the manifest](../../building/manifest/#workflows---the-ci-files-generated-from-this-same-manifest)
and [Make TAB work](../getting-started/#make-tab-work).

## build

Two products, two artefacts, and the kernel knows both shapes.

```text
$ git describe --tags
v0.4.0-21-g8d76a4d

$ ./simplon.sh build wheel
Successfully built simplon-0.4.0.post1.dev21+g8d76a4d30-py3-none-any.whl
```

Nothing chose that number. `pyproject.toml` declares `dynamic = ["version"]` and carries no `version =`
line at all; setuptools-scm derives it from `git describe` under the `no-guess-dev` scheme, which is
what turns the distance in that first line into the `.post1.dev` segment of the second. The trailing
`+g` segment names the commit, and
PyPI refuses a local segment outright - so there is no path from a working tree to a published release
that does not go through a tag.

The other artefact is a container image, and it is the same idea one layer out: `build:image` derives
`VERSION` and `REVISION` from git and writes them into the OCI labels, so the image that survives a
build carries its own provenance instead of being told what it is. Both halves of that -
`build:image` and `release:image` - are [worked through in the examples](../examples/#7-ship-a-container-image).

## test

Both products place their levels the same way, and the levels differ by data rather than by code: what
a level *is*, which one clears the results and how a non-pytest runner attaches are all in
[Test levels](../../building/test-levels/). agile-cockpit is the interesting one to look at, because
its `system` level runs against a real GitLab instance and therefore runs nightly rather than on push -
which is a statement its manifest makes, not one the kernel imposes.

What belongs here instead is what comes back. A gate does not answer yes or no - it answers with one of
**five** outcomes, and only two of them are statements about the product at all:

| outcome | `ran` | what it means |
|---|---|---|
| `passed` | yes | the suite ran and found nothing |
| `failed` | yes | the suite ran and found something |
| `setup-failed` | no | the preparation fell over, so the suite never started. This says nothing about the product |
| `not-run` | no | a precondition refused before anything was cleared, so the last real run's archive is untouched |
| `killed` | no | a signal ended the run. It did not report; it was shot |

The last one is the newest, and it exists because of the sentence it replaced. A run a signal ended used
to arrive as `failed`, and the record then said *the suite ran and reported failures* about a run whose
output was empty - a claim about a product where none had been made. It was measured three times in one
day on one product, with three different causes ([simplon#55](https://github.com/marcozwyssig/simplon/issues/55)),
and the false sentence was identical every time. The
fix widened the range rather than reinterpreting the ambiguous value: `killed` is its own outcome,
`ran` is `False`, and the message names the signal, because `SIGTERM` tells a reader that something
asked the run to stop and `-15` tells them nothing.

That is worth carrying past this page. **An outcome that cannot tell "nothing to do" from "failed" is a
bug**, and the three outcomes with `ran == False` are the whole of what that rule cost to build.

## release

The tag is the version, the push is the claim, and nothing local decides either. That argument, the
guard, and what the guard deliberately does *not* check are in [Cutting a release](../releasing/) and
are not repeated here.

What this chapter can add is that the guard was run against a live branch while the chapter was being
written, and it refused: `HEAD` on a working branch is not an ancestor of `origin/main`, so no tag was
cut and nothing was pushed. That is the ordinary case, not a staged one - it is what the command does
every time somebody types it before merging.

The other half is the record that the loop closes. `v0.4.0` was cut, its workflow ran, and PyPI carries
`0.4.0`. Two different products publish two different things through the same verb: simplon publishes a
wheel to PyPI, agile-cockpit publishes an image to GHCR under a moving `latest` and an immutable
`sha-<7>`, and `release:image` finishes by asking the registry whether the tag is really there rather
than trusting a push's exit code.

## deploy

**This is where the loop stops being complete, and the page says so rather than filling the gap with a
plausible-looking step.**

What exists is local. agile-cockpit's `deploy up` is a `docker run -d` against the image its own
`build:image` produced, on the machine you typed it on, with a named volume and a port. That is the
entire deploy story today, and it is honest work - but it is one host, and the host is yours.

Row 11 says *derived* rather than *run*, and the distinction is the reason the column exists: that
sentence was read out of the product's task body, not observed. Starting a container in somebody
else's checkout to be able to write *run* here would have been a run staged for the documentation, and
a staged run is the thing the label is supposed to rule out.

What does not exist is everything past that host. `deploy` is one of the two ribs the catalogue draws
empty on purpose: it carries the group name, the env-first gate and **no tasks at all**. Proxmox,
Portainer and a cloud account are not implemented, not stubbed and not planned in code -
[simplon#5](https://github.com/marcozwyssig/simplon/issues/5) is where the decision is open, and
[the two empty ribs](../../building/phases/#the-two-empty-ribs) is why leaving them empty is the
expensive choice rather than the lazy one.

So: a Python product can be built, tested, released and documented by this kernel today, and it can be
deployed to the machine in front of you. Beyond that, you write it yourself.

## docs

```text
$ ./simplon.sh build docs
[07:15:35] ==> build.reference - Write the product's command reference as Markdown, read off its BUILT command line.
  [07:15:36]  OK command reference -> site/content/using/commands.md
[07:15:36] ==> build.site - Build the product's documentation website with Hugo, in Docker (HTML only).
  [07:15:36] ==> fetching the pinned theme module github.com/imfing/hextra@v0.12.3
  [07:15:38] ==> building the site with hugo in hugomods/hugo:exts-0.148.2: site/ -> build/website/
  [07:15:44]  OK site built -> build/website/
[07:15:44]  OK docs: all 2 steps passed
```

One aggregate, two steps, and the order between them is a `depends_on` edge rather than a convention -
the first writes the command reference the second publishes. Which of the three documentation commands
produces what is [a table in the examples](../examples/#8-publish-the-documentation).

{{< callout type="info" >}}
**That third line used to mean the build needed the network.** `hugo mod get` runs before *every*
build, and hugo resolves the theme module again while building; with nothing kept on the host, both
went out to fetch it on every run and the step ended at `git ls-remote` without a network. A pinned
build that cannot run offline is reproducible and still not repeatable - it failed in a train and it
failed during a GitHub outage.

Hugo's cache now lives in `build/hugo-cache/` and outlives the container. Measured on this checkout:
the run above, repeated with every container cut off from the network, publishes the same site and
exits 0, where the same run against the previous kernel died on that third line. The fetch is still
made on every build rather than put behind a "have they drifted?" condition - with the cache warm it
costs under a second and no network, and a condition that answered wrongly would render against the
theme it already had and say nothing.
[simplon#27](https://github.com/marcozwyssig/simplon/issues/27) carries the measurements, including
the one that decided it: skipping the fetch alone does *not* make the build offline, because the build
resolves the module itself.
{{< /callout >}}

The AsciiDoc side - `docs:render`, the one that produces a PDF - is in the catalogue and simplon places
no command for it, which is why row 14 above says *derived* and not *run*. This page has not seen it
work.

## What this chapter does not repeat

Each of these is told once, elsewhere, and told properly:

- what a gate is, how a level is declared, and how a non-pytest runner attaches -
  [Test levels](../../building/test-levels/)
- why the tag is the version and what the release guard refuses - [Cutting a release](../releasing/)
- the jobs of the day, taken one at a time rather than as a loop - [Worked examples](../examples/)
- why `deploy` and `monitor` are empty - [The five phases](../../building/phases/)
- getting a product to exist in the first place - [Getting started](../getting-started/)
