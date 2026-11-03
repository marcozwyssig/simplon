# si#487: `release:check <tag>` - the dispatch release's first member

Ticket: si#487, the last open part of si#463 (decision D3 and its pattern, si#463 comment 6231282127).
Decided by Marco on 2026-11-03, by choice list, against main d03b89f. Sibling designs:
`2026-10-17-si490-workflows-release-key-design.md` (the derived release job) and
`2026-10-18-si491-simplon-own-release-design.md` (simplon as its first user).

## Intent

A release started from the button has one thing standing between a mistyped version and a public tag plus a
PyPI upload: simplon's own product command `release-version` (`simplon.yaml:46`, "until `release:check`
(si#487)"), which checks the spelling only, plus the verbatim shell step "Cut the tag in this checkout",
which refuses a tag that exists at another commit. Neither is the kernel's, so no other product gets them,
and neither checks where the run was started, whether origin could be asked, or whether HEAD already
carries another version.

`release:check` is the kernel task that does all of it, fails closed, and says for every refusal what went
wrong and what the way out is. It is the first member of every release aggregate a `workflows: release:`
names, so it runs on the button and in a local `release all` alike.

## Decisions (Marco, 2026-11-03)

1. **Build without cleon's answer.** cleon#80 (asked 2026-10-17) is unanswered. The pattern reaches only a
   product that declares `workflows: release:`, and cleon does not. A comment goes on cleon#80 **when the PR
   merges**: the check shipped, it binds only with `workflows: release:`, the question stays open for the day
   cleon wants the flow.
2. **"Published?" is not the check's question.** A tag origin carries at THIS commit is a resumable release
   and is green. Whether its GitHub Release is already published is `release:github-unpublished`'s answer
   (si#486), and only a product that keeps GitHub Releases has that member. This deviates from the ticket
   text ("asked through the shared adapter GET") on purpose: simplon keeps no GitHub Releases, so an
   always-asked GET would answer "no release, so unfinished" on every run, which is a "nothing to do" read
   as "passed". It would also ask GitHub twice in a product that does keep them.
3. **The check is the aggregate's first member**, written by the product, not emitted by the generator. A
   local `release all` therefore checks the pattern and HEAD as well. A load-time rule holds it there.
4. **The generator lifts that first member in front of the cut.** The derived job today runs "Cut the tag in
   this checkout" and "The build will be stamped with the version" before any member
   (`tasks/workflowgen.py:1089`). Left there, a malformed version or a second version tag at HEAD would fail
   in shell with the shell's message, and the check would never speak.
5. **Without `GITHUB_REF`, "from main" is skipped and says so.** Not red (a local `release all` stays
   possible, and simplon's hand route is exactly that), not silent (a check that did not run is not a pass).
   The fetch check still requires origin's default branch to carry HEAD.
6. **The pattern is fixed** (si#463, 2026-10-17): `v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)`,
   no manifest key.

## What `release:check <tag>` does

A body in `src/simplon/tasks/` over `gitops`. It returns 0 or 1. Each check runs in this order and the first
red one ends the run, because a later check's message would be about a state the earlier one already
condemned.

| # | Check | Red when | Message says (substance; exact text is pinned by tests) |
|---|---|---|---|
| 1 | no tag | `tag` empty | which release? `release check vX.Y.Z` |
| 2 | pattern | `tag` does not match the fixed pattern | the version is spelled `vX.Y.Z` (no leading zeros, no suffix); nothing was cut |
| 3 | from main | `GITHUB_REF` set and not `refs/heads/<default>` | start the release from `<default>`; names the ref it was started from |
|   |  | `GITHUB_REF` unset | not red: logs that the branch the run was started from is not checked outside Actions |
| 4 | fetch | fetching origin's default branch fails | origin could not be fetched, so "origin/<default> carries this commit" has no answer; nothing is released on it |
| 5 | carried | `origin/<default>` missing, or does not carry HEAD | merge first and release what `<default>` carries (the advice `release:tag` already gives for off-main) |
| 6 | other version at HEAD | HEAD carries a tag matching the pattern other than `tag` | `git describe` would stamp the build with that one; names it |
| 7 | remote tag | `remote_tag_commit(tag)` is `None` | origin could not be asked whether `tag` exists; not read as "no such tag" |
|   |  | it names another commit | `tag` is taken at `<commit>`; choose the next version |
|   |  | it names HEAD | green: an unfinished release this run may finish (logged as such) |
|   |  | `""` | green: a new version |

Notes on the table:

- **Default branch** is `gitops.default_branch()`, the one `release:tag` uses.
- **The fetch** is the existing `gitops.fetch_branches()`: `git fetch --quiet --no-tags origin`, every branch,
  no tags (`gitops.py:476`). Any failure of it is red here, and the row-4 message says "origin could not be
  fetched", not "the default branch" (my call after the builder check: no new refspec fetch, which would be
  a second fetch path beside `release:tag`'s). In `release:tag` (`tasks/release.py:75`) it stays a warning: that guard can only refuse too much
  on a stale ref, whereas here the check is the claim that origin was read.
- **Local tags are not asked.** A local `tag` at another commit, absent from origin, is `release:tag`'s
  "moved" case and the cut step's refusal; the check speaks only about origin, which is where "taken" lives.
- **Check 6** reads the tags pointing at HEAD (`git tag --points-at HEAD`) and filters them with the same
  pattern. A non-version tag at HEAD (e.g. `iol-17.18.02`) is not this check's business.
- **No GitHub API call.** The task needs no token and declares no `token:`.

## Placement and the load rule

**Catalogue.** `release:check` in `src/simplon/catalogue.yaml`, in the release section beside `release:tag`,
`unattended: true`, one param `tag` (help and metavar as `release:tag`'s), no ports. It does not publish, so
it is added to `PUBLISH_READS` (`src/tests/test_catalogue_publishes_and_token.py:27`, today `release:notes` and
`release:github-unpublished`). Rendering of `tag`: the same as `release:tag`'s (my call; the check-1 message
names the command the way it renders). **Offered, not placed**, like the `github-*` tasks: a product without the dispatch flow has no
use for a fixed `vX.Y.Z`. The firn catalogue model (`src/firn/model/simplon/catalogue/tasks.firn`),
`artifactschema.BODIES` and the generated task class (`./simplon.sh build model`) follow, as for every
catalogue task.

**The rule (expression, merged reach).** A release aggregate that a `workflows: <name>: release:` names must
have, as **the first leaf of its plan**, a member whose task is `release:check`. "First leaf of the plan" is
read by the same helper the generator uses to lift it (`_leaves` / `plan_for`, depth-first), so the rule and
the lift cannot disagree on a nested aggregate (my call, after the builder check). The way out is in the
message: add `check: { task: "release:check" }` and put it first.

**Where it raises (Marco, 2026-11-03, after the builder check):** at manifest load, in `manifest/ports.py`
beside rule 8 (`_check_bundles`), which already resolves release aggregates against the merged catalogue.
Measured by the builder check: neither `workflowgen._release_key` (`workflowgen.py:416`, sees only the raw
workflow body, no `Manifest`) nor `_release` (`:1059`, reached only from `render` at `:1328`, i.e. only by
`support workflows` and `test generated`) both runs at load and sees the aggregate. In ports every command goes
red on a violating manifest. ports then reads the `workflows:` section (which workflow names which aggregate):
it either joins the census walk or is named in `READS_INLINE` with the reason, as the census's own rule
demands. A census entry (EXPRESSION, REACH_MERGED) comes with the refusal.

- Measured 2026-11-03 over the eight reachable product manifests plus smcctl's: **only `simplon.yaml`
  declares `workflows: release:`** (firn's `release` workflow is hand-written, without the key). The rule
  refuses no manifest other than simplon's, which this change fixes in the same commit. firn meets it at
  firn#1040, where its migration writes the member anyway.
- What it forbids: a dispatch release with no check, or with the check later than first. Nobody can want the
  second. The first is the whole point of si#463 D3.

**The generator.** `_release` emits, in order: the checkout, **the first member's step** (the check),
"Cut the tag in this checkout", "The build will be stamped with the version", the remaining members, the
dry-run tail. Not `if:`-guarded on a dry run (it publishes nothing). It gets the version as every other
taker does, `--tag "$RELEASE_VERSION"`.

## simplon itself

- `simplon.yaml`: the `version: { task: release-version }` member becomes `check: { task: "release:check" }`,
  first in `all.depends_on`; `all`'s `help:` and the comment at `simplon.yaml:46` follow.
- **`release-version` is deleted** (my call: a second source that cannot drift needs no rule): its entry in
  `simplon.yaml`, `orchestrator/cli.py:release_version` and the pattern beside it, and
  `src/tests/test_own_release_version.py`. That test's one measurement worth keeping, *every tag simplon has
  released matches the pattern*, moves to the new task's tests against `release:check`'s pattern.
- `.github/workflows/release.yml` is regenerated (`support workflows`); `test generated` holds it.

## Docstrings that would become false

- `gitops.tag_verdict` and `tasks/release.py`'s module docstring: "a pre-flight `ls-remote` is forbidden"
  (#32 acceptance 3, "the push IS the claim"). Add that `release:check` asks origin to tell "unfinished" from
  "taken", which claims no free number: the push stays the claim.
- `tasks/release.py`: "the kernel must not guess a tag convention" holds for `release:tag`. Reword: the
  dispatch flow fixes `vX.Y.Z` in `release:check`, which only a product with `workflows: release:` meets.
- `tasks/githubrelease.py:26` and the catalogue comment above `release:github-unpublished` name
  `release:check` as future; make them present.
- `workflowgen._release`'s docstring: add the lifted first member.

## Docs

- `src/site/content/with-what/phases.md`: the new coordinate.
- `src/site/content/how/releasing.md`: the check as the run's first step, and the half-release cases it now
  shortens (si#490 spec, "Half-release cases": "the page says plainly which of these `release:check` will
  shorten") - a new dispatch on a taken version, a dispatch from a branch, an unreachable origin.
- `with-what/rules.md`'s count is computed by the census; nothing typed.
- Release notes: an entry in the next unreleased section (si#487), including that `workflows: release:`
  now requires the member (a product bump that declares the key goes red until it adds it).

## Tests (each seen red first)

- Every row of the table: its refusal with the message pinned, against a real temporary git repository with
  a bare origin (the existing `gitops`/`release:tag` test fixtures), not a stub of git.
- A re-run: `tag` on origin at HEAD, green.
- A fetch failure (origin unreachable), red. An `ls-remote` failure, red (not "no such tag").
- `GITHUB_REF` unset: green on an otherwise good repository, and the skip is in the log.
- Every tag simplon has released matches the pattern (moved from `test_own_release_version.py`).
- The load rule: a release aggregate without the member, and with it second, refused; census entry present.
- The generator: the check step precedes the cut; golden updated.

## Non-goals

- No GitHub API question in the check (decision 2).
- No change to `release:tag`'s fetch warning, its "moved" handling, or the verbatim cut/stamp shell. The cut's
  own "exists at another commit" refusal stays; after the check it can only fire on a local leftover, and
  removing it is not this ticket.
- No version-pattern manifest key.
- No release cut by this ticket (Marco, 2026-10-29: the release comes when a consumer needs it).

## Left to the builder

- The module name for the body (`tasks/release.py` beside `release:tag`, or its own module).
- Whether checks 4 and 5 share `release:tag`'s helper text for the off-main advice.
