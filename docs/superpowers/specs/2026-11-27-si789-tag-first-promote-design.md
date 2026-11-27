# si#789: tag first, then promote

Status: design, decided by Marco on 2026-11-26 (shape, comment on #789) and 2026-11-27 (choice lists in
the session that wrote this file). Milestone M1 "Workflows derived, not written", lane L2. Absorbs #721.
Written against main at 0ae728b (after #904/si#862).

## 1. Intent

A release rebuilds nothing. Today `release.yml` re-runs the tests `ci.yml` already ran green on the same
commit, and rebuilds the wheel and the image that CI built and discarded. Both artifacts carry their
version in their bytes (setuptools-scm in the wheel; `VERSION` from `git describe` in the image, its
`org.opencontainers.image.version` label and the wheel inside it), so an artifact built on an untagged
commit is a dev version and cannot be promoted. Hence Marco's decision: the tag comes first, CI builds and
tests the release's artifacts on the tag with the real version, and the publish jobs promote exactly those.

## 2. Goals, non-goals, anti-goals

Goals:

- One release button, one run: gate, notes, tag push, the producers on the tag (both platforms), promotion.
- The promotion jobs build nothing they publish; they download what the run's producer jobs built.
- A commit without a green `ci.yml` run on `main` gets no tag. Refused with one sentence naming the commit
  and the run to look at (or that there is none).
- A failing image test leaves no published release (#721's acceptance).
- The CI-on-tag jobs and the gate are derived by the kernel through firn for every product.

Non-goals:

- Changing `ci.yml` for pull requests and `main`: it stays fast and amd64-only (`ci: params:`).
- Promotion across runs (finding another run's artifacts by API). The run promotes what it built itself.
- Deriving the promotion jobs (Marco 2026-11-27): `publish`, `image` and `homebrew-tap` stay simplon's D12
  exceptions in `workflows: release: jobs:`, rewritten to download instead of build. Deriving promotion for
  every product's release commands (maven, nuget, conan, GitHub draft) is its own ticket, measured over
  every reachable manifest; #864 (counted `exception:`) is unaffected.
- firn (Marco 2026-11-27): simplon only. firn follows via #893. Before the merge, firn's manifest is run
  through the new generation to see whether the kernel bump breaks its release; a break is reported on
  #893, not fixed here.

Anti-goals (a failure even if it works):

- A promoted artifact stamped with a version other than the tag. The existing guards (`RELEASE_STAMP`, "the
  wheel that was built must be the tag") stay and move to where the build now happens.
- A promotion job that silently rebuilds when an artifact is missing. A missing artifact is a red job naming
  it, never a fallback build.
- Evidence from one platform presented as evidence from two: `kernel-checked` is kept only from a build that
  covered every platform the release publishes.
- Deleting a public tag.

## 3. Constraints

- The tag is public before anything is published. This inverts si#491's "a red test leaves no tag". The
  green-on-main gate (4.2) makes the inversion small: only the tag run itself can still go red.
- `workflow_dispatch` inputs reach commands only through `env:` (si#488), never as `${{ inputs.* }}` in a
  run line.
- `release:tag` refuses a commit `main` does not carry; that stays.
- Generated files are regenerated and committed with the change (`support github workflows --check`).

## 4. The design

### 4.1 Run shape

```
release  ->  producers on the tag (derived)  ->  publish -> image / homebrew-tap / docs -> pages
check+gate,   build wheel, build image,           download, promote; docs and the formula
notes, tag    test image; both platforms;         render from what PyPI now serves (4.5)
              upload artifacts to this run
```

### 4.2 The `release` job and the `release all` aggregate

The aggregate loses its test members (Marco 2026-11-27): `release all` becomes `check`, `notes`, `tag`,
for every product and also when typed in a checkout. Aggregate and derived job stay one plan (si#491).

`release:check` gains the gate: a successful `ci.yml` run triggered by `push` on `main` whose head is
exactly the commit being released. Refused otherwise, naming the commit and the run (its URL and
conclusion), or saying no such run exists. It runs on a dry run too. When it cannot look (no token, API
unreachable) it refuses with that reason: "could not look" is never "no run" and never "green" (my call).

`test release-notes` leaves the aggregate with the other tests; whether the notes guard is needed after
`release notes` writes in this job is the builder's to check against what the guard reads (6).

### 4.3 Producers on the tag: derived jobs in `release.yml`

Not `workflow_call` of `ci.yml` (Marco 2026-11-27). The kernel derives jobs into `release.yml` from the
same firn model as `ci.yml`, selected and parameterised for the release:

- **Selection** (Marco 2026-11-27): only the leaves whose artifact a release command consumes, plus the
  tests that produce the `evidence:` those release commands consume. For simplon: `build wheel`,
  `build image`, `test image`. The suite, the type gate and the model tests do not run again: the green
  `main` run is that evidence. This selection rule is new kernel logic and gets its census entry.
- **No `ci: params:`**: the release's parameters apply, so the image builds and is tested on every platform
  the release publishes, and `kernel-checked` is kept.
- **Machine** (my call): the release command's `ci: { runner, emulates }` (simplon: `github-ubuntu`,
  `emulates: [linux/arm64]`), not the CI default (ghr-8 is LXC and cannot register emulation, #722).
- **Checkout of the tag.** On a real run the job checks out the pushed tag and verifies it names `HEAD` (the
  existing "the tag is on origin at this commit" step). On a dry run nothing is pushed: the job checks out
  the commit and cuts the tag locally with the existing `RELEASE_CUT`, then `RELEASE_STAMP`, so the
  rehearsal also builds with the real version.

Each producer uploads the `path:` artifacts the release consumes to the run (the #862 mechanism, now from
this run instead of `push`/`workflow_dispatch` runs of `ci.yml`). The `ci.yml` 90-day upload from #862 then
has no consumer and is removed (builder to confirm nothing else reads it).

### 4.4 Promotion

`publish`, `image`, `homebrew-tap` (simplon's D12 jobs) `needs:` the producer jobs and download their
artifacts instead of running `build wheel`, `build image`, `test image`. How the multi-arch image crosses
from its producer to `image` (registry push by sha under a non-release tag, or an OCI archive artifact) is
the builder's to measure and choose (6).

A dry run runs everything up to, not including, the pushing steps, exactly as today.

### 4.5 Two builds that stay after publish (my call)

- **Homebrew formula:** `build homebrew-formula --source pypi` needs the sha256 PyPI serves, so it runs after
  the upload. It renders from the published wheel and promotes nothing the run built. Taking the sha from
  the local wheel instead would rely on byte identity with what PyPI got, which si#537 says does not hold
  across a rerun.
- **docs:** the derived `docs` job keeps running `build docs` after `publish`: the site describes the
  version PyPI now serves. The `website:` derivation from si#862 is unchanged.

### 4.6 A red tag run

Same rule as a failed publish today: rerun the failed job, never cut a second tag. A real defect gets the
next patch version; the red tag stays. The workflow header and the refusal texts say so.

### 4.7 #862's `{input: tag}` dispatch

Falls away for the release path: the run promotes only what it built. If a tag-input dispatch remains for
another use, it is refused when the tag's commit has no green `main` CI, with the sentence of 4.2.

## 5. Approaches considered

1. **One run, producers embedded** (picked, Marco 2026-11-27). Artifacts come from the same run; no run
   lookup; the dry run keeps its place.
2. Tag push triggers `ci.yml`, publish separate (`workflow_run` or a second button), finding the green tag
   run by API. Rejected: two triggers, a run lookup, and the dry run has no natural place.
3. Tag push runs the whole release (`on: push: tags`). Rejected: pushing a tag publishes, and the dry run
   loses its place.

Sub-decisions, all Marco 2026-11-27:

- Derived jobs in `release.yml` over `workflow_call` of `ci.yml`: the latter puts the platform behind a
  condition in `ci.yml` and moves artifacts across the called-workflow boundary.
- Green `main` CI before the tag over "only the tag run counts": without it a red tag is common and the
  refusal becomes a skipped job, not a sentence.
- Producers and their tests only, over the whole CI model on the tag: the whole model repeats the
  duplication this ticket removes and barely moves wall time.
- The aggregate loses its tests, over "the derivation skips them": the latter is a new expression of "job
  differs from aggregate". Reopens if a product needs `release all` typed locally to run its tests.
- Promotion jobs stay hand-written now, over deriving them: deriving needs every product's release paths
  measured. Reopens as its own ticket.

## 6. Left to the builder

- How the multi-arch image crosses from its producer to `image` (registry by sha vs OCI archive), measured.
- Whether the release-notes guard is still needed after `release notes` in the `release` job.
- How `release:check` finds the green run (GitHub API via the run's token), within 4.2's rule on "could not
  look".
- Census entries and `with-what/rules.md` for every new refusal, including the selection rule.
- Running firn's manifest through the new generation before merge, reporting on #893.

## 7. Acceptance

- A dry-run release on a commit with green `main` CI runs no `build wheel`, `build image`, `test image` in
  the promotion jobs; their logs show downloads and promotion only. Named exceptions: the formula rendered
  from PyPI and `docs` (4.5).
- Seen red first: a release on a commit with no green `main` CI is refused with the sentence of 4.2.
- Seen red first: a promotion job whose artifact is missing fails naming it and builds nothing.
- A failing image test on the tag leaves no published release.
- Wall time before and after on simplon. Before, v0.51.0 (run 45889937811): 23 min 24 s. firn's
  before-measurement is taken now and recorded on #893, which carries its after.
