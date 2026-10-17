# si#490: `workflows: <key>: release: <aggregate>` - workflowgen derives the dispatch release

Part of si#463 (decisions D2, D4 and D5 in comment 6231282127). Decided by Marco on 2026-10-17
(si#490 comment 6234934085, plus two choice lists after the builder check: the token and the dry run). Measured on main 98bf07c.

## Intent

firn wrote its release workflow by hand as verbatim steps in `firn.yaml` (`workflows: release:`, branch
`chore/1039-simplon-0.32`, its generated `.github/workflows/release.yml` read in full for this spec). It
carries the dispatch trigger, the inputs, the permissions, the concurrency, a local cut, a stamping check,
the draft, the build and its checks, the tag push, the image push, the publish and a dry-run tail. Every
product releasing through GitHub would write the same 390 lines. The kernel now owns the pieces (si#486
coordinates, si#488 `params: { env: }`, si#489's ordering rule), so the workflow can be derived from one
key.

**The design rests on one measurement.** Since si#489, `manifest.plan_for(<aggregate>)` already returns a
release aggregate's leaves in an order rule 8 accepts. The leaves are the notes, any draft, the
members, the tag and the publishes, with every publish member and the tag before `release:github-publish`.
Rule 8 does not demand that the publish is the *last* leaf, and workflowgen does not add that demand. The workflow therefore needs
**no ordering of its own**. It renders the aggregate's plan as steps and adds only what a plan cannot
say: the trigger, the local cut, the stamping check, the dry-run conditions and the tail.

## Goals

- A workflow-level key `release: <group> <name>` beside `flow:`, naming a release aggregate (a
  `ReleaseCommand`). The product writes no trigger and no step for its release.
- **Desugaring, not a new renderer.** `release:` expands into a `Workflow` with `on:`, extras
  (`permissions`, `concurrency`) and one `Job` of ordinary `Step`s. workflowgen's existing job renderer
  writes it, as `_rollout` already expands `flow:` into jobs. The checkout, the runner table, the bootstrap
  and the notes-as-comments come for free and stay the same in every workflow.
- A golden test on a fixture manifest. The rendered file parses as YAML, passes `actionlint` when it is on
  PATH, and has no `${{ inputs.` inside any `run:` script.

## Non-goals

- `release:check` (si#487, waiting on cleon#80). The flow is built without it. When it lands, it becomes
  the job's first step after the checkout: one generator line plus a golden update. Until then a
  dispatch with a malformed version fails at `release:notes` or the stamping check, not at a dedicated
  validation step. This gap is stated here and on si#490.
- simplon's own release (si#491). simplon's `workflows: release:` stays `handwritten:`.
- A `push: tags:` trigger. D2: a release is started by dispatch only.

## Anti-goals

- **No `${{ inputs.* }}` in any `run:` line.** The version reaches scripts only through the job's
  `env: RELEASE_VERSION` and commands only through `EnvValue("RELEASE_VERSION")` (si#488). `dry_run`
  appears only in `if:` expressions.
- **No list of "publishing tasks" typed into workflowgen.** Which steps are skipped on a dry run is
  derived, see "Dry run".
- No second ordering rule. If the plan's order is wrong, rule 8 refuses at load, and workflowgen
  trusts the plan.

## The key, decided

```yaml
workflows:
  release:
    release: release all          # <group> <name> of a release aggregate
    runner: { kind: self-hosted-debian, labels: ghr-8 }   # the job's machine, as for flow:
    note: ...                     # optional, as today
    jobs: { ... }                 # optional, allowed beside it (decision 3)
```

| Product writes | Result | Kind |
|---|---|---|
| `release:` and `on:` | refused: the trigger is derived from `release:` | **expression rule**, reach merged (decision 1) |
| `release:` and `flow:` | refused: one workflow is a rollout or a release, not both | diagnosis (the two derive two different triggers) |
| `release:` and `permissions:` or `concurrency:` | refused: derived from `release:` | expression rule, reach merged. *My call*, same reason as `on:`: a product-written value would silently replace a key the dispatch flow depends on (`contents: write` for the tag, no cancel in progress). |
| `release:` naming a command the manifest lacks, or one that is not a release aggregate | refused, naming the command | diagnosis |
| `release:` and `jobs:` | allowed. The derived job is named `release`, so a product job can `needs: release`. A product job named `release` is refused (diagnosis, the name is taken) | |
| `release:` in a `handwritten:` workflow | refused like `jobs:` today | diagnosis (extends the existing stray list) |
| an aggregate whose `passes:` does not carry `tag` | refused: the version would reach no command | diagnosis (otherwise the version input is silently ignored) |
| a plan leaf with `unattended:` not `true` | refused, naming the leaf | diagnosis. `derive()` today refuses `None` and *skips* `false`, and a skipped release member is green for the wrong reason |

The aggregate is **not** required to contain `release:tag`, `release:image` or `release:github-*`. *My
call*, guarding against rule creep: the plan renders whatever the aggregate holds, rule 8 already orders
it, and a release without a GitHub Release is still a release. Measured: no reachable manifest declares
`release:` under `workflows:` today, so no new refusal refuses anything.

The sentence "the kernel does not invent one" (the `on:` refusal in `_workflow`, and its echo on
`how/manifest.md`) is amended. A workflow with `release:` derives its trigger, and every other workflow
still has to write its own.

## What is derived

1. **Trigger.** `on: workflow_dispatch` with `inputs.version` (string, required, description
   `'The version to release, exactly as its tag will be: vX.Y.Z'`) and `inputs.dry_run` (boolean,
   required, **default true**, description `'Rehearse: build and check everything, publish nothing'`).
   The texts are firn's.
2. **Extras.** `permissions: { contents: write, packages: write }` and
   `concurrency: { group: '${{ github.workflow }}-${{ inputs.version }}', cancel-in-progress: false }`.
3. **One job, `release`,** on the workflow's `runner:`. Its `env:` holds
   `RELEASE_VERSION: ${{ inputs.version }}` merged with the runner table's env, which `_with_runner_env`
   already computes. The checkout keeps `fetch-depth: 0`, which the kernel already emits.
4. **Steps, in order:**
   1. *Cut the tag in this checkout:* `git tag -d "$RELEASE_VERSION" >/dev/null 2>&1 || true`, then
      `git tag "$RELEASE_VERSION"`. The delete comes from firn's validation step. Measured by the builder
      check: `fetch-depth: 0` fetches every tag, so on a re-run after the tag push a plain `git tag` fails
      with rc 128 and the run never reaches `release:tag`'s resume path. Deleting the local copy and
      cutting at HEAD hands that decision to `release:tag`, which compares origin's tag with HEAD:
      resume when equal, the "moved" refusal when not (gitops.py).
   2. *The build will be stamped with the version:* `git describe --tags --always --dirty` must equal
      `$RELEASE_VERSION`, else `::error::` and exit 1 (firn's script).
   3. One command step per leaf of `manifest.plan_for(<aggregate>)`, in that order. Each leaf's task
      that the aggregate **passes** (`AggregateCommand.passes`, si#433), and `tag` is required there (see
      the table), gets `params: { tag: EnvValue("RELEASE_VERSION") }`. It is not bound by parameter name:
      `test:image`, `build:image` and the pack tasks also declare a `tag` with another meaning, and
      `passes:` already exists to say what an aggregate hands its leaves.
      **The token (decision of 2026-10-17):** a new catalogue field, `token: github`, on every task that
      reads `githubpackages.token()`. Measured candidates: `release:image`, `release:asset`,
      `release:github-unpublished` / `-draft` / `-publish`, and the nuget/maven publish tasks. The builder
      greps for every caller of `token()` and makes the field cover exactly that set, with a test that
      holds the two together. Only those steps get `env: { GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }} }`, and
      the build and the tests never see it. A product task under `tasks:` may declare the field too. Measured
      first: today the kernel gives no step a token. firn and simplon's own release.yml write it by hand
      on each step, and the comment at `adapters/githubpackages.py:14` saying "Actions injects
      `GITHUB_TOKEN`" is wrong (it falls back to `gh auth token`) and is corrected. Other secrets (firn's
      `VSCE_PAT`) go in a workflow-level `env:`, which is carried through as an extra.
   4. *What a release would have published (dry run),* `if: ${{ inputs.dry_run }}`. It prints a line
      saying nothing was published, then `cat`s the release-notes file when the plan contains a
      `release:notes` leaf, using its produced artifact's declared `path:`. Without such a leaf it prints
      only the line.

The local cut comes first rather than after the notes. *My call*: the notes read the previous tag, not
this one, so cutting first changes nothing for them. `release:github-draft` sets `target_commitish` from
HEAD either way.

## Dry run

**Decision of 2026-10-17:** a new catalogue field, `publishes: true`, on every task whose act cannot be
taken back: `release:tag`, `release:image`, `release:asset`, `release:github-draft`,
`release:github-publish`, and the nuget/maven publish tasks. A product task under `tasks:` may declare
it too. A leaf whose task has it gets `if: ${{ !inputs.dry_run }}`, and every other leaf runs on a dry
run (the notes, the build, the checks, `release:github-unpublished`).

Measured by the builder check: the earlier derivation (evidence port, plus tag, plus github-*) let
`release:asset`, which has no ports and can create a public Release, run on a rehearsal. The cost of a field,
stated: a publishing task that forgets it runs on a dry run. The builder therefore adds a test that every
catalogue task under `release:` either carries `publishes: true` or is named in a short list of known
reads (`release:notes`, `release:github-unpublished`, `release:check` when it lands), so a new release task has to say
which it is. Rule 8's `publishes` set (evidence ports) is left as it is. It answers a different question
(what needs evidence), and the two need not agree.

Both new fields are task data beside `unattended:`. Measured while planning: `unattended:` lives in the
hand-written part of `catalogue.yaml` and in `treeform.TASK_KEYS`/`INHERITED`, not in the firn model
(which carries key, body and ports). So a command inherits both from its task and may override them,
exactly as `unattended`. (This corrects an earlier draft of this paragraph, which placed them in the model.)

## Half-release cases (docs section `how/releasing`, source firn docs/07 §7)

Each case, how it is finished, and the fact that a re-run is safe: the draft is reused, the tag on
origin at the same commit is resumed, and the publish happens once.

- **Tag pushed, `release:image` failed:** re-run.
- **Image pushed, the publish failed:** re-run (the image is rebuilt and re-pushed), or run only the
  publish command by hand.
- **The default branch moved after the tag push:** re-run the same run (it finishes on its own commit).
  A new dispatch is refused because the tag is at another commit. Alternatively, delete the tag and the
  draft.
- **A check fails only after the tag push:** the re-run fails the same way. Delete the tag and the
  draft, or take the next version.
- **Cancelled between the tag push and the publish:** re-run.
- **An abandoned draft:** not public. Delete it by hand.

The page says plainly which of these `release:check` (si#487) will shorten.

## Census

Each new load-time refusal, including a malformed `publishes:`/`token:` on a product task, gets a `CENSUS` entry: the kind as in the table above, and for each expression
rule a `REACH` (merged). The published count on `with-what/rules.md` moves accordingly and is computed,
not typed.

## Acceptance

- Golden: a fixture manifest with a release aggregate (notes, draft, an image member with evidence, tag,
  publish), plus one product job with `needs: release`. The rendered file is compared byte for byte.
- The rendered file `yaml.safe_load`s. Under it, `True` is the `on:` key, and the test says so.
- `actionlint`, when on PATH (skip otherwise, as other workflow tests do).
- No `${{ inputs.` inside any `run:` value, asserted over the whole file.
- Each refusal in the table: a test that was seen red first, with the message pinned.
- On a dry run, every `publishes: true` leaf is skipped and no other leaf is (golden). Only `token: github` leaves carry `GITHUB_TOKEN` (golden).
- A real bash run of steps 1–2 against a temporary git repo: fresh, with the tag already present at HEAD (re-run), and with an unequal describe.
- `support workflows --check` stays green on simplon's own manifest (its release stays handwritten).
- The release notes at the next cut carry the key.
