---
title: "Worked examples"
weight: 3
---

The [command reference](../commands/) is complete and generated, which means it can tell you what every
command takes and still not tell you which one you want. This chapter is the other half: seven jobs that
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

Aggregates run their steps in a terminal UI, and a terminal UI takes the mouse. Your terminal's own
selection stops working, so the output is visible and unreachable at the same time. Three ways out, in
order of how much you had to know in advance:

**You planned ahead:** redirect the whole command. Works, sidesteps the UI entirely, and requires you to
have known before the run that you would want the text.

**You are in the UI right now:** `c` copies the focused step's output, `s` writes it to a file.

**You did not plan ahead and the UI is already closed:** every step's output is on disk anyway.

```text
$ ls build/logs/
build.compile.log   test.unit.log   deploy.up.log
```

One file per step, in `build/logs/`, overwritten each run rather than appended - the interesting run is
the last one, and a file holding four of them makes finding the right one your job. It lives under
`build/` because a step log is a build output, and `clean` should take it with everything else.

## 4. Cut a release

Simplon's own repository is the honest example here, because it builds itself with itself:

```text
$ ./simplon.sh test all
$ ./simplon.sh build wheel
$ git tag v0.1.13 && git push --tags
```

Tests first, and not as ceremony: the release workflow runs them again, and a tag whose tests fail is a
tag you now have to delete from a public remote. Finding out locally costs thirty seconds.

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

## 5. Deploy to one environment - and find out you cannot

```text
$ ./myctl.sh dev deploy up
```

The environment is the **outer** token, before the group. That is not decoration: `deploy up` without a
target is meaningless, so the target is part of naming the command rather than an option on it. A group
that does not take an environment refuses one, loudly:

```text
$ ./myctl.sh dev build
[14:48:59] ERR 'build' is environment-agnostic and takes no env prefix; run 'myctl build'
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

## 7. Publish the documentation

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
