---
title: "Cutting a release"
weight: 4
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

**It is not a secret, though.** A hand-pushed tag still triggers the release workflow - the trigger has
no branch filter - so the workflow asks the same question and *reports* the answer in the run log and
the run summary:

```text
::warning::v1.4.0 was cut from 1b3d99e, which origin/main (228f9e7) does not carry. This release is
going out anyway - 'release tag' refuses this case, so the tag was pushed by hand.
```

It reports and never blocks, and it runs before the publish step. That ordering is the point: a tag
cannot be taken back, but a publication can still be stopped by whoever is watching. An exception that
nobody ever hears about is not a loud exception - it is an unnoticed one.

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

In this repository - and in any product set up the same way - **both** the PyPI release **and** the
documentation website hang off the `v*` tag:

```yaml
on:
  push:
    tags: ["v*"]
```

Merging to `main` runs the CI workflow. It does **not** publish the package, and it does **not**
republish this website. If you edit a page, merge it, and then refresh the site expecting to see the
change, you will not see it - and nothing will have failed anywhere to tell you why. The site is
rebuilt when a release is cut, by design: it describes the version it was cut from, so between releases
it ages rather than describing something nobody can install yet.

So: documentation changes go out with the next release, and if a documentation fix is urgent, the way
to ship it is to cut a release.

## The whole sequence

```text
$ ./myctl.sh test all                  # the workflow runs these again; find out here instead
$ ./myctl.sh test typecheck-python
$ ./myctl.sh build wheel               # optional, but it fails faster than the workflow does
$ ./myctl.sh release tag v1.4.0        # the release
```

Notice what is not on that list: editing a version number. There is nowhere to edit one.
