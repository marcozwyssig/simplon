---
title: "Releases"
weight: 6
---

What each release changed, and what a product has to do about it.

Notes start at **0.4.0**. Earlier releases have their tags and their commits;
writing their notes now would mean reconstructing them from memory, and a
reconstructed record reads exactly like a real one. The [release
procedure](../releasing/) explains how a version comes into being.

## 0.5.0

Two changes, and they pull in opposite directions: one adds a way to hand
something over, the other takes four import paths away.

### Before you bump

**Four modules that 0.4.0 announced as moved are gone.** If your product still
imports one of the old paths, it now fails with `ModuleNotFoundError` rather
than warning. The fix is the right-hand column:

| Gone | Import instead |
|---|---|
| `simplon.allure` | `simplon.tasks.allure` |
| `simplon.vcs` | `simplon.tasks.gitops` |
| `simplon.images` | `simplon.imagenames` |
| `simplon.nexus` | `simplon.nexusproxy` |

Measured through the API on the day of the release rather than assumed: **one
product is affected, at three lines** — netctl, at
`orchestrator/tooling.py:32`, `orchestrator/guard.py:55` and
`test/.../test_nexus_manifest.py:20`. It is not, however, a product this
grace period ever reached: netctl pins `simplon==0.3.0`, where `images` and
`nexus` are the *real* modules and `imagenames`/`nexusproxy` do not exist yet.
Those three lines are part of whatever upgrade takes netctl past 0.3.0, and
they change in the same commit that lifts the pin.

Two further lines the record named turned out never to have been simplon's:
asbundle reads `from delivery import images` — a different kernel that ships a
module of the same name — and biz-cockpit had already migrated. See
[Surface](../../building/surface/) for why re-measuring beats remembering.

### New

**`release:asset` attaches declared files to a GitHub release.** The other half
of `release:artifact`: that one publishes a directory to a registry, where a
consuming pipeline pulls it with its own token; this one puts files on a release
page, where a person downloads them. A product declares an `assets:` section and
pins one with `with: { name: ... }`, the same shape `release:artifact` uses.

```yaml
assets:
  bundle:
    source: "build-out/product_*.zip"   # glob, relative to the product root
    repository: owner/name              # optional — gh resolves it from the remote
    title: "..."                        # optional, defaults to the tag
    notes: "..."                        # optional
```

It runs `gh`, so the kernel gained no GitHub client and no new dependency, and
the token comes from the two sources `githubpackages.token` already documents.
Two behaviours are worth knowing because they are decisions rather than
defaults: a `create` that fails because another matrix cell got there first is
read as success and the upload proceeds, while any other failure stops before
anything is attached; and `--notes` is always passed, because `gh` opens an
editor where it has a terminal and refuses where it does not.

Which of the two a product offers is a question about its audience — and about
what its licence lets it hand out. Neither is placed; both are offered.

## 0.4.0

Thirty commits since 0.3.0. Three of them change what an existing product must
do; the rest add capability or explain what was already there.

### Before you bump

Two of the products that install this kernel do not load against 0.4.0 as
they stand, measured through the API rather than assumed:

| product | what stops it |
|---|---|
| biz-cockpit | still on the flat manifest form |
| netctl | `support install` redeclares a `task:` without `override: true`; `monitor accept` places `test:accept`, and a phase-named coordinate belongs in its phase |

*(A sixth manifest is on the flat form too and is deliberately not listed:
its product does not install this kernel at all, so no version of it can stop
that manifest loading. Counting it here would repeat the mistake 0.4.0 fixed in
five module heads, which named a consumer that never was one — see
[Surface](../../building/surface/) for how that is measured now.)*

Every one of those refusals prints the fix, and for the flat form it prints the
whole rewritten manifest. But the work is real, so plan it before the bump
rather than during it.

### What a product has to change

**The flat manifest form is gone.** A manifest that writes `impl:` directly
under a command no longer loads. The refusal prints the rewrite — the whole
manifest, in the tree form, ready to paste — and that rewrite was proved by
using it: the kernel's own `simplon.yaml` was migrated with exactly the printed
output. One case still needs a hand: where the catalogue places the same name
(`support install`, `release tag`), the printed block lacks the `override: true`
the merge then asks for, and the second refusal names that fix.

**And it replaces the structure, not your comments.** The rewrite is generated
from the parsed manifest, so a comment explaining *why* something stands where
it does does not survive it. A consumer whose manifest carried forty lines of
reasoning used the output as a blueprint and rebuilt by hand rather than
pasting — otherwise the migration would have been green and the reasons gone.
If your manifest is uncommented, paste it; if it is not, read it.

**`release tag` disappears from every product.** It was placed; it is now
offered. A placed command has to be useful in *every* product, and a product
with no release workflow does not need one. Declare it yourself if you want it:

```yaml
groups:
  release:
    commands:
      tag: { task: "release:tag", help: "Cut and push the release tag." }
```

**`env_groups:` may no longer contradict the platform.** Naming a group the
catalogue already shapes — `deploy`, which the catalogue declares
`env_first: true` — is now refused, with the same sentence `env_first:` gets in
the same position. The key used to validate and do nothing at all in the tree
form, so a line like that was already having no effect; now it says so. One
consumer found exactly this on the day it landed.

### Four modules moved

`allure`, `vcs`, `images` and `nexus` were kernel-level modules that were really
a task's innards, and three of them collided by name with a task body. The old
import paths still work, announce the move on use, and are removed in the next
minor:

| old | new |
|---|---|
| `simplon.allure` | `simplon.tasks.allure` |
| `simplon.vcs` | `simplon.tasks.gitops` |
| `simplon.images` | `simplon.imagenames` |
| `simplon.nexus` | `simplon.nexusproxy` |

The warning is a `FutureWarning` rather than a `DeprecationWarning`, and the
reason is measured: Python's default filters drop a DeprecationWarning unless
the frame that triggered it is `__main__`, and a product's task body never is.
A warning nobody sees is not a warning.

**Check the call, not the import.** The warning fires when a name is *used*,
not when the module is imported — `from simplon import images` is silent even
under `-W error::FutureWarning`, and `images.image_ref(...)` is what speaks. A
consumer who verifies "does it still import?" after the bump sees nothing and
meets the warning later, in operation. Measured by a consumer during their
migration, not by us.

Which modules are library and which are internals is now declared rather than
guessed — see [Surface](../../building/surface/).

### New

- **`build:image` and `release:image`** build a container image and publish it.
  The push is read back from the registry afterwards, because `docker push` can
  exit 0 without the tag arriving. `VERSION` and `REVISION` come from the
  product's git checkout, so a locally built image carries the same provenance
  as one built in CI.
- **`release:tag`** cuts the release tag and pushes it — `git push origin <tag>`,
  never `--tags`. It refuses a tag on a commit `main` does not carry.
- **A gate says why it is red.** "The setup failed" and "the suite ran and found
  something" are both a non-zero exit code, and they now read differently in the
  report — for the person reading it a week later, not just the one watching the
  terminal.
- **A results directory keeps the verdict it finds.** Merging one no longer
  copies `environment.properties` over the top of it.

### Stricter, in the kernel's own house

- A coordinate that starts with a phase name belongs in that phase; anything
  else is a family a product places where it likes. Measured against every
  existing manifest before it became a rule: no violations.
- The kernel pinned the three container images it was using without a tag,
  after refusing an unpinned image in a product's manifest. A rule the kernel
  breaks itself is a rule nobody believes twice.
- `docs:site` now renders each Mermaid diagram during the build. Hugo emits a
  diagram block whether or not its syntax parses, so a green build proved
  nothing about it.

### Documentation

New chapters on [the five phases](../../building/phases/) with a diagram, and
on what the kernel means by running in Docker. The coordinate table lost the
sentence beside each entry: those sentences were paraphrases of the catalogue's
own `help:`, nothing compared the two, and by the time anybody looked several
had drifted. The reliable fix is not to guard the copy but not to keep one.
