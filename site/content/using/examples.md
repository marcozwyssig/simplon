---
title: "Worked examples"
weight: 3
---

The [command reference](../commands/) is complete and generated, which means it can tell you what every
command takes and still not tell you which one you want. This chapter is the other half: eight jobs that
actually come up, done end to end, with the reasoning about *why that command and not the neighbouring
one*.

## 1. Set up a machine you have just been given

A fresh laptop or a fresh runner has none of the tooling the kernel leans on. There are two commands,
and they are two commands on purpose.

```text
$ ./myctl.sh support doctor
$ ./myctl.sh support install
```

`support doctor` reports; `support install` changes the machine. Run the first, read it, then run the
second - not because reporting is safer, but because a machine that is nearly right and a machine that
is entirely wrong want different next steps, and only the report can tell you which one you have.

`support install` is idempotent, so running it on a machine that is already provisioned costs a probe
per tool and changes nothing. It provisions **tools**, and deliberately not credentials. A GitHub token
missing its package scopes fails a publish exactly as hard as a missing `oras` binary, but the fix is a
browser window and a human clicking "authorise":

```text
$ ./myctl.sh support git auth-scopes
```

That is a separate command because one of them touches a machine and the other asks a person for
something. Bundling them would mean a CI runner's unattended provisioning step blocks forever on a
consent screen.

{{< callout type="info" >}}
The gates self-provision anyway - `oras` is installed the moment a package operation needs one, so a
build never stops for it. `support install` exists for the case where that is the wrong behaviour: an
install that happens as a side effect of a build is an install nobody chose, at the least convenient
moment, over a network that may be the very reason you are building offline.
{{< /callout >}}

## 2. Run the tests, and then run *fewer* tests

```text
$ ./myctl.sh test all
```

That is the whole suite, and on a real product it is minutes, not seconds. What you usually want next -
after it goes red - is one test, now.

Suites are declared per level, and a level that declares `args: true` forwards whatever you put after
the command straight to pytest:

```text
$ ./myctl.sh test system -k test_forwarding_survives_restart
```

Twenty-four minutes becomes about sixty seconds, and that is the entire reason the passthrough exists.

There is a consequence built into it that is worth knowing before you go looking for the report. A run
carrying extra arguments is **partial by definition**, so it is quarantined into its own results
directory and rendered under its own archive prefix. The canonical archive of the last full gate is left
exactly as it was. If filtered runs wrote into the shared results, you would end up with an archive that
looks like a complete gate and reports a single test - which is worse than having no archive at all,
because it answers.

So: filtered runs to find the problem, one unfiltered run to prove it fixed.

## 3. Read what a step actually printed

Aggregates run their steps in a terminal UI: the plan as a tree on the left, the highlighted row's
details on the right.

**What the run is doing, without pressing anything.** The bar along the bottom follows the PROCESS, not
your cursor. It names the step that is running right now and how long it has been running, beside the
run's own counts and clock:

```text
▶ build.compile  1m12s…  ·  3 ok · 1 running · 5 pending  ·  run 2m48s
```

That is the line that answers "is this compiling or has it hung", and it goes on answering it while you
read something else entirely. The running row carries the same counter in the tree, spelled `1m12s…` -
the trailing character is the difference between a step that TOOK twelve seconds and one that has taken
twelve so far. When the run ends the bar carries the verdict, which is the last thing you read before
pressing `q`.

State is a glyph AND a colour: `✓` green, `✗` red and bold, `▶` amber, `⊘` dimmed, `·` dim and
uncoloured. The glyph is never dropped, so a broken terminal palette or a saved log loses nothing. If
the colours are unreadable on your terminal, `ctrl+p` opens the command palette and its **Theme** entry
picks another one; the rows follow it.

**Moving around.** The cursor follows each step as it starts, and stops the moment you navigate by hand -
`f` asks for it back and goes straight to whatever is running now. On a finished run, `n` walks the
failures and wraps, and `/` filters the tree to the rows matching a substring plus the rows that carry
them (`/` again clears it). Everything in the footer is also in the command palette on `ctrl+p`, with a
sentence each, which is where to look rather than at a key you would have to remember.

The details pane keeps your place: scroll up in a long step's output, look somewhere else, come back, and
you are where you were. While a step is running, the pane follows the tail only if you are AT the tail -
scroll up and the lines keep arriving below you instead of dragging you down with them.

**Getting the text out.** A terminal UI takes the mouse, so your terminal's own selection stops working
and the output is visible and unreachable at the same time. Three ways out, in order of how much you had
to know in advance:

**You planned ahead:** redirect the whole command. Works, sidesteps the UI entirely, and requires you to
have known before the run that you would want the text.

**You are in the UI right now:** `c` copies the focused step's output, `s` writes it to a file.

**You did not plan ahead and the UI is already closed:** every step's output is on disk anyway.

```text
$ ls build/logs/
build.compile.log   test.unit.log   deploy.up.log   run-transcript.log
```

One file per step, in `build/logs/`, overwritten each run rather than appended - the interesting run is
the last one, and a file holding four of them makes finding the right one your job. It lives under
`build/` because a step log is a build output, and `clean` should take it with everything else.

**And one file for the RUN**, which is the one you attach to a ticket. `run-transcript.log` holds every
step in the order it ran with its exact command, its rc and its duration, then why each failure failed
and where the whole of its output is, under a header that says which run this was:

```text
=== simplon run transcript: bringup ===
started:      2026-09-10 14:03:09
environment:  prod
instance:     dev
tooling:      assembled by simplon 0.9.0 (/opt/myctl/.venv/lib/python3.12/site-packages/simplon)

✓ build.install  rc 0  2.0s
    $ build.install - Install host prereqs.
✗ build.compile  rc 1  1.4s
    $ build.compile - Compile the artefacts.
⊘ deploy.up  (skipped: build.prep stopped on a failure)
    $ deploy.up - Deploy up.
```

That last header line is what turns a pasted excerpt into evidence: it is the same provenance the
top-level `--help` prints, so an excerpt says which simplon produced it rather than leaving everyone to
assume it was theirs. The transcript is written on BOTH runners - the terminal UI and the plain one CI
falls back to - because the run that most needs attaching to a ticket is a red CI run.

## 4. Cut a release

Simplon's own repository is the honest example here, because it builds itself with itself:

```text
$ ./simplon.sh test all
$ ./simplon.sh test typecheck-python
$ ./simplon.sh build wheel
$ ./simplon.sh release tag v0.1.13
```

Tests first, and not as ceremony: the release workflow runs them again, and a tag whose tests fail is a
tag you now have to delete from a public remote. Finding out locally costs thirty seconds.

That last line used to be `git tag v0.1.13 && git push --tags`, typed by hand, and it was the only step
of the loop simplon did not hold. Two things changed with it becoming a command. It pushes **one** tag
by name rather than every local tag the machine happens to carry, and it refuses to cut a tag on a
commit `main` does not carry - which nothing stopped anyone from doing, and which would have published a
feature branch to PyPI under a release number. [Cutting a release](../releasing/) is the whole
story, including what the guard deliberately does *not* check.

The type gate is on that list for a reason worth stating. It is the kernel's own
`test:typecheck-python`, placed on the kernel - and until recently it was not, so `mypy` was something you
ran by hand or not at all. What that cost was a real bug hiding among findings everybody had agreed to
read as noise from a local Python version. It was not the Python version; the pipeline was simply never
asked. The gate pins the language level to the `requires-python` floor, so it answers the same on your
machine as in CI, which is the property that makes running it locally worth anything.

**Notice what is not in that list: editing a version number.** There is nowhere to edit one.
`pyproject.toml` declares its version `dynamic` and setuptools-scm reads it off the tag, so typing
`git tag v0.1.13` *is* how 0.1.13 gets chosen. Between tags the kernel calls itself
`0.1.12.post1.dev4+g1234abc` - the release it descends from, and how far past it you are.

That is worth more than the saved keystrokes. A number kept by hand can be chosen twice: two people
working at once each pick the next one, and neither finds out until one of them is in review. A tag
cannot - it is one name on one remote, so whoever pushes first has it and the second push is refused on
the spot.

The tag is what publishes. The workflow builds the wheel and pushes it to PyPI through Trusted
Publishing, so every published version points at a named commit and there is no path from a dirty
working tree to a release - a dirty tree would carry a `+local` segment that PyPI refuses outright. If
you need to know what a release *contains*, the tag is the answer, not the branch.

And *this website* is published by the same tag, which is the part people learn the hard way: merging a
documentation fix to `main` does not put it on the site. Nothing fails to say so - the page simply stays
as it was until the next release is cut.

## 5. Deploy to one environment - and find out you cannot

```text
$ ./myctl.sh dev deploy up
```

The environment is the **outer** token, before the group. That is not decoration: `deploy up` without a
target is meaningless, so the target is part of naming the command rather than an option on it. A group
that does not take an environment refuses one, loudly:

```text
$ ./myctl.sh dev build
[14:48:59] ERR 'build' is environment-agnostic and takes no env prefix; run './myctl.sh build'
```

Read that as a statement about artefacts, not about syntax. An artefact built "for dev" is either
identical to the one you would have built anyway - in which case the token was noise - or it is a
different artefact, in which case you have just made the thing you tested and the thing you ship two
different things. Both are worth an exit code.

Leave the token off and the default environment applies (`default:` in the manifest). Which means the
following two commands are the same command:

```text
$ ./myctl.sh deploy up
$ ./myctl.sh dev deploy up
```

Type the second one in anything anyone else will read. The default is a convenience for your own
terminal, not documentation.

To see the matrix, if the product places the command:

```text
$ ./myctl.sh support environments
```

## 6. Run the whole pipeline as one command

An aggregate is a command with no body of its own - only a list of what must happen first:

```yaml
all: { help: "Build then deploy, end to end.", depends_on: [build, up] }
```

```text
$ ./myctl.sh dev deploy all
```

The kernel resolves the dependencies transitively, deduplicates by name, and runs each unique command
exactly once per invocation, in dependency order. A command reached along two paths runs once, not
twice.

Two things about aggregates are worth knowing before you rely on one:

**There is no freshness tracking.** This is a plan, not a build system. Nothing checks timestamps and
nothing is skipped because it "looks done". Idempotency is each command's own promise, and if `build` is
expensive and unconditional then the aggregate is expensive and unconditional too.

**`stop_on_failure` is scoped to a subtree, not to the run.** Declared on an aggregate, it makes a
failure skip the rest of *that command's* subtree rather than the rest of everything. A failing bring-up
aborts its own phases while the `test all` that planned it carries on to the next gate. That is what a
flag declared per aggregate has to mean - and it is why the default is off: run every step, take the
worst return code, and see the whole picture once instead of one failure at a time.

If a long pipeline keeps getting interrupted by the host going to sleep, that is `keep_awake: true` on
the aggregate. It is declared there rather than on each leaf so the inhibitor also spans the *gaps*
between steps, which is where an idle timer actually fires.

## 7. Ship a container image

Two commands along two of the five verbs, and they stay two:

```text
$ ./myctl.sh build image           # docker build, with VERSION and REVISION derived from git
$ ./myctl.sh release image         # docker login, docker push, and then ASK THE REGISTRY
```

Both read one entry of the manifest's [`images:` section](../../building/manifest/#images---the-container-image).
A product that builds an image only to run a smoke test against it is then never one typo away from
publishing it; a product that wants both in one step declares an aggregate over them, which is where an
ordering belongs.

The last step of `release image` is the one worth knowing about. It does not trust `docker push`'s exit
code: it asks the registry whether the tag is really there, and goes red when the answer is no or when
the question could not be asked. It asks through `oras` rather than a docker client on purpose - a
docker client can answer from a local cache, and a check that can answer from your own machine is not a
check. Unlike the documentation build, a missing Docker here is a **failure**, not a hint - the image is
the whole point of the run.

## 8. Publish the documentation

Three documentation commands, three different outputs, and choosing wrongly wastes an afternoon:

| You want | Command | What comes out |
|---|---|---|
| Architecture documentation for people working **on** the system | `docs:render` | HTML **and PDF**, from AsciiDoc through docToolchain |
| A product website for people working **with** it | `docs:site` | HTML only, from Markdown through Hugo |
| The command reference | `docs:reference` | One Markdown page, read off the assembled CLI |

They are not three candidates for one job, and a product may want all three. The PDF is the point of the
first one - it is what gets handed over, filed and reviewed - and Hugo does not produce one, which is
why the website did not simply absorb it.

This site is built by the last two:

```text
$ ./simplon.sh build docs
```

That is an aggregate over `build reference` and `build site`, in that order, and the order is a
`depends_on` edge in the manifest rather than a convention in a script. It has to be: the site's
`content/using/commands.md` is written by the first step and read by the second, so a wrong order
produces a site with a stale reference on it - and, the first time round, no reference at all. Both
steps run in Docker, which is a decision with [its own rule](../../building/rules/#a-container-that-writes-into-a-mount-runs-as---user).

If Docker is not installed on your machine, that run is a hint and a zero exit code, not a failure. The
machine that runs the loop is not always the machine that publishes the page - and that distinction has
[a chapter of its own](../../building/rules/#a-missing-tool-is-not-a-failed-tool).
