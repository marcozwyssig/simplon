---
title: "Cutting a release"
weight: 7
aliases:
  - "/using/releasing/"
---

A release is one command:

```text
$ ./myctl.sh release tag v1.4.0
```

That is the whole act. There is no version to edit first, no file to remember, and no second command to
push what the first one made. What follows is why each of those absences is deliberate, and what the
command refuses to do for you.

## The tag *is* the version

`pyproject.toml` declares its version `dynamic` and setuptools-scm derives it from the git tag. So
typing `v1.4.0` is not *recording* a decision made somewhere else - it **is** the decision. There is
nowhere else. Between releases the package calls itself something like
`1.4.0.post1.dev4+g1234abc`: the release it descends from, plus how far past it you are.

{{< callout type="warning" >}}
`release tag` takes the tag **exactly as it will exist** - `v1.4.0`, not `1.4.0`. The kernel does not
add the `v`. Which tags publish is your product's statement, made in your release workflow's trigger and
your setuptools-scm settings, and a kernel that decorated `1.4.0` into `v1.4.0` would be guessing at a
convention it cannot read. The only shape check is `git check-ref-format` - git's own rule.

**The price of that, stated plainly:** type `release tag 0.1.14` and the command will cut the tag, push
it, verify origin has it, and report success - because all four of those things really happened. What
will *not* happen is a release, because `tags: ["v*"]` never sees a tag called `0.1.14`. Nothing fails.
Nothing warns. You get a green command and no package.

This is the one trap in the whole flow, and it is the reason the success line says only that the tag is
on origin and explicitly *not* what any workflow will do with it: the command cannot read your triggers,
so it does not pretend to. If a release does not appear, **check the tag's spelling against your
workflow's trigger first.**
{{< /callout >}}

This is worth more than the saved keystrokes. A number kept by hand can be chosen twice: two people
working at once each pick the next one, and neither finds out until one of them is in review. That
happened three times in one day here, and cost two renumberings - and looking first would not have
helped, because the number the other person had reserved was in a branch nobody else could see.

A tag cannot be chosen twice. It is one name on one remote, so whoever pushes first has it and the
second push is refused on the spot, by git, in the terminal where the mistake is being made.

## `git push origin <tag>`, never `git push --tags`

The command pushes **the one tag it just cut**, by name.

`--tags` pushes *every* local tag. Not the release you are cutting: all of them, including the one
somebody made last month to try something out and never deleted. Measured in a scratch repository with
two stray tags beside a real one, `git push --dry-run --tags` offers all three to the remote.

In this repository the difference is currently invisible - 14 local tags, none of them missing from
origin, so `--tags` would push nothing extra today. That is a fact about today's tag list, not about the
flag. The command names one tag because naming one tag is the property you want; being harmless right
now is not.

## The guard: is this commit one `main` carries?

Before anything is cut, `release tag` asks one question:

> Is `HEAD` an ancestor of `origin/<default branch>`?

If not, it refuses - loudly, naming the commit, the branch you are on, and what `main` actually carries:

```text
ERR v1.4.0 was NOT cut: origin/main does not carry this commit.
ERR     the commit      1b3d99e (a feature nobody merged yet)
ERR     on branch       feature
ERR     origin/main     228f9e7 (the first commit)
ERR a release is built from the TAG, so the workflow would check this commit out and publish it
ERR under a release number - a branch on PyPI, and a website describing it.
ERR the way out is to merge it first and tag what main then carries:
ERR     git switch main && git pull && ./myctl.sh release tag v1.4.0
```

The gap it closes is a real one. setuptools-scm guarantees that a version names **one commit**; it does
not guarantee that the commit is one `main` carries. Without this check, a tag on a feature branch
publishes to PyPI without complaint - the release workflow checks out whatever the tag points at.

{{< callout type="warning" >}}
A squash merge **rewrites** the commit. After your branch is squash-merged, its tip is still not an
ancestor of `main` and will still be refused - correctly, because that commit is not what was merged.
Tag `main`'s head instead.
{{< /callout >}}

### What the guard does *not* check

Three things, each on purpose.

**It does not ask the remote whether the tag is free.** That is the remote's answer to give. A tag is
unique on the remote, whoever pushes first owns the number, and the loser finds out from `git push`
rather than from a reviewer. Asking beforehand would move that decision into the command, where it
would be raced anyway - the answer can go stale between the asking and the pushing - and where losing
would look like the tool's opinion rather than a fact about the world. **The push is the claim.**

**It does not check that the tests pass.** Run them first; the workflow will run them again, but a tag
whose tests fail is a tag you now have to delete from a public remote.

**It does not check the version number itself.** Nothing compares `v1.4.0` against anything, because
there is nothing to compare it against - that is the point of the section above. A *mistyped* number
(`v1.41.0` for `v1.4.0`) is caught by nobody: PyPI refuses a number reused, never one skipped. That is a
deliberate trade, not an oversight. It buys the property that a number cannot be claimed twice by two
people at once, and a typo is one person's slip, visible in the command they are typing, while a
collision is two people behaving correctly and producing a wrong result.

### And there is no flag to switch it off

If you genuinely need to tag something `main` does not carry, the two git commands still work and always
will:

```text
$ git tag v1.4.0 && git push origin v1.4.0
```

That is the escape hatch, and it is a better one than an option would be. A person typing raw git has
decided something. A `--force` flag gets set once, in a script, and is never looked at again.

**In a repository whose release starts from the button, there is no such hatch.** simplon's own
`release.yml` is derived from `release: release all` (si#491) and starts from `workflow_dispatch` and
nothing else, so a hand-pushed tag releases nothing, and the cut is `release tag` itself, inside the
run. The guard is then a refusal rather than a choice: a hotfix merges first. Until si#491 that same
workflow triggered on any `v*` tag and only *reported* an off-`main` one in its log; the report went
with the trigger, because nothing is left for it to report.

## If the push is refused

The interesting failure is the one where the tag was cut and the push did not land - somebody claimed
the number first, or the network dropped. The tag is then sitting in your repository, **cut but not
published**: not "nothing happened", and not "released".

The command says so, in those terms:

```text
ERR origin refused v1.4.0: it already carries that tag. Someone claimed the number first - a tag is
ERR unique on the remote, and being told by `git push` instead of by a reviewer is the point rather
ERR than a fault.
ERR THE TAG IS STILL HERE: v1.4.0 -> 036f361, cut by this run. Nothing was published.
ERR   that number is gone. Drop it and take the next one:
ERR       git tag -d v1.4.0 && ./myctl.sh release tag <the next one>
```

Run the command again on that same tag and it **resumes** - it pushes the tag that is already there,
rather than reading "tag already exists" as proof that the release went out:

```text
!   v1.4.0 is already cut here at 036f361. This run does not read that as a release that already
!   happened: it pushes the tag and then asks origin. If an earlier push did not land, this is that
!   push; if it did, origin simply reports it up to date.
```

It says it that way because the same state is reached by two roads. Re-running the command after a
release that went out perfectly well lands here too, and telling *that* caller their push had failed
would be inventing a failure. What is true on both roads is that the tag being here proves nothing; the
push and the read-back settle it.

### When the tag is already here because you *pulled* it

There is a second way a tag ends up in your repository on the wrong commit, and it is the ordinary one:
`git pull` fetches tags. Pull before cutting a release - which the refusal above tells you to do - and a
number somebody else claimed lands in your checkout as a local tag, looking exactly like a leftover of
your own.

The command tells the two apart by asking origin, and the two need opposite fixes:

```text
ERR v1.4.0 already exists here and names a different commit, so nothing was cut or pushed:
ERR     v1.4.0 is at   7bbcca6 (their work)
ERR     HEAD is at     2dd184c (mine)
ERR origin carries v1.4.0 at that same commit, so this is NOT a tag of yours left behind - it is
ERR the number, already claimed by someone else, fetched into this checkout by an ordinary git pull.
ERR   the number is gone; take the next one:
ERR       ./myctl.sh release tag <the next one>
ERR   (`git tag -d v1.4.0` would only delete your copy of their tag. The next fetch brings it back,
ERR   and origin still has it either way.)
```

If origin has *no* such tag, the same situation is your own leftover instead, and the advice is the
opposite one: decide which of your two commits is the release.

{{< callout type="info" >}}
Asking origin here is not the pre-flight check the command otherwise refuses to make. That one would
decide whether a *free* number may be claimed, replacing the push as the claim. Nothing is claimable in
this situation either way - the tag in your repository names the wrong commit, so there is nothing to
push that would mean what you meant. The refusal is already settled; origin is asked only to say which
of the two situations produced it.
{{< /callout >}}

### The outcomes

| What it found | What it does |
| --- | --- |
| `main` does not carry `HEAD` | Refuses. Nothing is cut. |
| The tag is here on another commit, **and origin has it there** | Refuses: the number is taken. Take the next one. |
| The tag is here on another commit, **and origin has no such tag** | Refuses: it is your own leftover. Decide which commit is the release. |
| The tag is here on another commit, **and origin cannot be asked** | Refuses, and says it cannot tell the two apart. |
| The tag is already here, on **this** commit | Pushes it and asks origin - whether an earlier push landed or not. |
| No such tag here | Cuts it, pushes it, then reads it back off the remote. |

That last step is not ceremony. `git push` exiting 0 is not proof that origin has the tag, so the
command asks the remote - `ls-remote`, which keeps no local cache - before it reports success.

## The tag is what publishes. A push to `main` is not.

This is the one that costs people an afternoon, so it gets its own heading.

In a product whose release workflow triggers on a tag, the PyPI release, the documentation website
**and** the container image all hang off the `v*` tag:

```yaml
on:
  push:
    tags: ["v*"]
```

In this repository they hang off the release run instead - the button, which cuts the tag itself - and
the consequence below is the same.

Merging to `main` runs the CI workflow. It does **not** publish the package, and it does **not**
republish this website. If you edit a page, merge it, and then refresh the site expecting to see the
change, you will not see it - and nothing will have failed anywhere to tell you why. The site is
rebuilt when a release is cut, by design: it describes the version it was cut from, so between releases
it ages rather than describing something nobody can install yet.

So: documentation changes go out with the next release, and if a documentation fix is urgent, the way
to ship it is to cut a release.

**The Homebrew formula follows PyPI, and only after it.** `brew install marcozwyssig/tap/simplon` installs
the kernel on macOS and Linux from the tap `marcozwyssig/homebrew-tap`. The `publish` job runs, in this
order: build the wheel, upload it to PyPI (`skip-existing: true`), `./simplon.sh build homebrew-formula`,
`./simplon.sh test homebrew-formula`, and `./simplon.sh release homebrew-tap`. The formula is generated, and
its URL and sha256 are PyPI's, so the tap has to come after the upload: a formula must never name a URL
that is not live. The flags differ by kind of run. A real run builds with `--source pypi` and tests with
`--online true`. A dry run builds with `--source local` and tests with `--online false`, and it stops
before `release homebrew-tap`.

A dry run therefore carries the placeholder URL `https://pypi.invalid/dry-run/<wheel>` in the formula, and
the test is `brew audit --strict` and `brew style` only. Nothing goes to PyPI or the tap. The build (for the
install closure) and the test both run in a pinned brew image; on a fresh runner the build is the step that
pulls it, and that pull dominates the cost: measured once in the si#449 round of 2026-10-18 at about 4.5
minutes per release.

The tap is a different repository, so the workflow's own token cannot write to it. `release homebrew-tap`
declares `token: app`, and the workflow derives a step before it that mints a GitHub App token for
`marcozwyssig/homebrew-tap` and nothing else. The App is created once by the maintainer: contents
read/write on `marcozwyssig/homebrew-tap` only, installed on that repository. Its Client ID and private key
are stored as the repository secrets `HOMEBREW_TAP_CLIENT_ID` and `HOMEBREW_TAP_APP_KEY` in `simplon`; the
`HOMEBREW_TAP` prefix comes from the repository name. A dry run skips the step and needs neither secret.

**Rerun the failed job, never a second tag, also when the formula step failed.** That holds as long as the
rerun builds with the same toolchain: `build wheel` sets `SOURCE_DATE_EPOCH` from HEAD's commit time, so
the same toolchain rebuilds identical bytes. `skip-existing` lets the upload pass what the first attempt
already made, and `build homebrew-formula --source pypi` refuses if PyPI serves different bytes than the
local wheel. The tap is only ever written from a formula whose digest matches what PyPI serves.

The toolchain is not pinned: `pyproject.toml`'s build requirements are lower bounds at most, and the
wheel's `WHEEL` file names the setuptools version that built it. A setuptools release between the attempt and the
rerun gives other bytes, and the rerun's refusal is then permanent (and safe: nothing reaches the tap).
The way out is by hand, from a checkout at the tag, rendering from PyPI's own wheel instead of a rebuild.
`dist/` must hold that one wheel and no other, and the token is a GitHub App token for the tap,
exported as `GH_APP_TOKEN`:

```text
$ rm -rf dist
$ pip download simplon==X.Y.Z --no-deps --only-binary :all: -d dist
$ ./simplon.sh build homebrew-formula --source pypi
$ ./simplon.sh test homebrew-formula --online true
$ export GH_APP_TOKEN=...                     # an App token for marcozwyssig/homebrew-tap
$ ./simplon.sh release homebrew-tap
```

**The container image follows the tag too, and its pin follows in a pull request.** After the wheel is
on PyPI, the release workflow builds `ghcr.io/marcozwyssig/simplon:vX.Y.Z`, pushes it with the run's own
token and reads it back. Then it opens a pull request that moves `deploy/image/image.pin` to that image.
Merge it: until you do, a machine with no python3 still runs the previous image. The tagged commit cannot
pin its own image, because the image does not exist yet when the tag is cut.

## A **minor** has a second question

Everything above is the same for `v1.4.1` and for `v1.5.0`. One thing is not.

A module that moves out of a published package leaves a **tombstone** at the old path — it still
imports, and it says on use where the thing went. That is a promise with a date in it: *removed at the
next minor*. The date is the only part nothing checks, and a transition period that nobody is reminded
of does not end by decision. It ends by being forgotten — one release at a time, each of which looks
like the cheap choice on its own.

So before you type a version whose **minor** changes, read `simplon.cli.surface`:

* `MOVED` — the old paths that are still standing, and where each one now lives.
* `MOVED_CONSUMERS` — who still imports them, measured down to the repository, file and line, so the
  cost of ending the period is a number rather than a worry.
* `MOVED_DUE_AFTER` — the release they were promised to survive.

The kernel's own test suite goes red once a version past that pair is built, and `release.yml` runs the
suite *before* the tag (si#491) — so a minor that still carries tombstones costs a red run, and neither a
tag number nor a publication. That is the backstop, not the plan: it fires at the last possible moment,
because the version cannot know what you are about to type. This heading is the first one.

{{< callout type="info" >}}
Re-measure `MOVED_CONSUMERS` before you delete anything. "Nobody uses it any more" is a claim about
other people's repositories, and the point of removing a tombstone is that the next import fails loudly
— which is the wrong way to find out you were wrong. And delete the *promise* with the module: the
migration table on [What you may import](../../with-what/surface/) describes something that no longer
exists the moment the files go.
{{< /callout >}}

## The notes are part of the release, and something checks

A release nobody wrote up is a release that happened silently, and nothing in a repository notices by
itself: the tag is there, the wheel is there, and the page simply does not mention it. `test:release-notes`
is the gate that notices. Declare where the notes live and from when they count, in a
[`releases:` section](../manifest/#releases---where-the-notes-live-and-from-when-they-are-complete),
place the command under `test`, and run it in CI beside the suite.

It reads nothing of your prose. What it holds you to is that each release at or above your floor has a
section, that the page promises no version nobody can install, and that from your completeness floor on
each section names the number of every ticket merged into its range.

**Write the notes before the tag.** That is not a preference, it is the mechanism: the tag points at a
tree, so the tree has to already carry them. The section for the release you are preparing is measured
against `<last tag>..HEAD`, which is exactly what the tag will point at, so it is checkable before there
is anything to check it against.

{{< callout type="warning" >}}
**Two things about the range surprise people once each, and both are the gate working.**

*A pull request is measured as merged, not as its tip.* The `pull_request` event checks out
`refs/pull/N/merge` - your branch merged with the base - so when the base gains a merge your branch does
not have, the range gains it too and your section is asked about it. Rebase or merge the base in, and
write the number. Every run prints what `HEAD` resolved to, so the two states are told apart on the spot.

*The default branch goes red the moment a pull request merges* if that pull request's own ticket is not
in the prepared section. The merge is in range from the second it lands, which is correct - the release
being prepared really does now carry it.

**You never have to name your own pull request number.** GitHub's `Merge pull request #N from <branch>`
is a statement about the *act of merging*, not about the work, so the gate reads the commits that merge brought
in instead. The number your notes have to carry is the ticket number in your own commit subjects - one
you had before the branch existed. Without that rule a release-notes pull request would demand a note
about itself, and the follow-up would bring its own number too: the regress has no floor.
{{< /callout >}}

## The whole sequence

```text
$ ./myctl.sh test all                  # the workflow runs these again; find out here instead
$ ./myctl.sh test typecheck-python
$ ./myctl.sh test release-notes        # the section for v1.4.0, against what v1.4.0 will carry
$ ./myctl.sh build wheel               # optional, but it fails faster than the workflow does
$ ./myctl.sh release tag v1.4.0        # the release
```

In a product that ships a Homebrew formula, the tasks `build:homebrew-formula`, `test:homebrew-formula`
and `release:homebrew-tap` follow the tag, in that order and after the PyPI upload. Nothing derives these
steps: the product's own publish job places them, under whatever command words its manifest gives them
(simplon's are above). They run in the release workflow, not from a checkout: the last one needs the App
token.

Notice what is not on that list: editing a version number. There is nowhere to edit one.

## A dispatch release that stopped half-way

A workflow declared with [`release:`](../manifest/) runs the release as one job, started by dispatch. It
publishes in steps (draft, tag, image, publish), and a run can stop between any two. **A re-run of the
same run is safe**, and that is the answer to most of the cases below. The draft an earlier attempt left
is reused. A tag already on origin at this commit is resumed rather than cut again. The release is
published once, at the end.

- **The tag was pushed, then `release:image` failed.** Re-run.
- **The image was pushed, then the publish failed.** Re-run: the image is rebuilt and pushed again,
  which costs a full release's runner time. Running only the publish command by hand avoids that.
- **The default branch moved after the tag was pushed.** Re-run the same run: it finishes on its own
  commit. A *new* dispatch is refused, because the tag is at another commit. Alternatively, delete the
  tag and the draft.
- **A check fails only after the tag was pushed** (flaky, or dependent on the environment). The re-run
  fails the same way. Delete the tag and the draft, or release the next version.
- **The run was cancelled between the tag push and the publish.** Re-run.
- **A draft was abandoned.** A draft is not public. Delete it by hand.

A **dry run** (the default) builds and checks everything and publishes nothing. Every step whose task
declares `publishes: true` is skipped, and the last step prints the notes the release would have carried.
A publishing task that forgot the field would run on a rehearsal, which is why the catalogue's own
release tasks are held to it by a test.

`release:check` (si#487) will refuse a malformed version or a commit `main` does not carry *before*
anything is built. Until it lands, an off-`main` commit goes red at `release tag`, before the tag is
pushed - but **a malformed version is not caught by anything the kernel derives**. Measured on simplon
(si#491): `0.99.0`, without the `v`, passed the cut, the stamping check and the notes guard, and would have
published. A product that cannot accept that puts its own check first in the aggregate, as simplon does
with `release version`.
