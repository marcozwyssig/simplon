# si#862: Release and pages derived with no `workflows:` entry - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A product with a ReleaseCommand gets release.yml derived from that command, with `docs` and `pages` jobs when its `website:` says so, and its derived ci.yml keeps the artifacts a release consumes for #789 to promote.

**Architecture:** The release moves off `workflowgen`'s own dataclasses onto the firn workflow model first (new module `src/simplon/tasks/releasepipeline.py`, the release counterpart of `cipipeline.py`: derive a `workflowschema.Workflow`, convert it to the renderer's `workflowgen.Workflow`), proven by a byte-identical release.yml. Then the machine, emulation and time limit move to `ci:` on the ReleaseCommand, `workflows.release.release:` is retired loudly, and `workflows: release:` carries only extra jobs that land beside the derived `release` job. `website: { pages: release, by: <command> }` adds the si#851 `docs`/`pages` pair. ci.yml uploads each `path:` artifact a release step consumes. simplon migrates last.

**Tech Stack:** Python 3.12, firn (`.firn` model, `workflowschema.firnt` template), pytest, GitHub Actions; generation through `./simplon.sh support github workflows`.

**Spec:** `docs/superpowers/specs/2026-11-22-derived-workflows-design.md` (D12, sections 6.1-6.3, 7 step 8). Ticket si#862 and its 2026-11-25 decision comment (binding). Measurement: `/tmp/claude-0/-root-git-simplon/f6f1f3c0-cc0f-4e52-8c5d-8780bc7b8fe4/scratchpad/si862-measure.md` (main at a985296; file:line evidence; copy what you need into the PR, the scratchpad is not durable). The spec says `site:`; the code's section is `website:` (`src/simplon/tasks/site.py`, `SECTION`), and this plan uses `website:`.

## Global Constraints

- Decided (Marco, 2026-11-25, choice list on #862):
  - **Q1:** `workflows.release.release:` is retired loudly. `workflows: release:` carries only extra jobs (publish, homebrew-tap, image; firn's builder), which land in release.yml beside the derived `release` job. No separate file: PyPI Trusted Publishing is bound to the file name release.yml.
  - **Q2:** `ci: { emulates:, timeout_minutes:, runner: }` on the ReleaseCommand, as for CI leaves. simplon sets the release runner to `github-ubuntu`. Without that override, `emulates:` on ghr-8 is refused at generation (#722).
  - **Q3:** an explicit switch in `website:` turns on the derived docs and pages jobs: `pages: release`. The docs command is named in the data: `by: "<group> <name>"`, as `generated:` does.
  - **Q7:** CI uploads only the `path:` artifacts a release step consumes, under their manifest names, kept for 90 days, from push and dispatch runs only.
  - **Defaults taken:** the docs job waits for `release` and for every declared release job while the D12 exceptions stand; `{input: tag}` is handed to #789 and #895 (not built here); model first.
- Everything generated goes through firn: new workflow vocabulary is modelled in `src/firn/model/simplon/workflow/workflow.firn`, generated with `./simplon.sh build model` into `src/simplon/model/workflowschema.py`, never hand-edited; `./simplon.sh test generated` green. Derived jobs are model instances converted by one function per file kind (the `cipipeline.to_workflow` pattern), never `workflowgen.Job`s assembled by hand outside that converter.
- Every new refusal says its kind in its docstring and has a census entry in `src/tests/test_refusal_census.py`; see each new one red. A retired word fails loudly; no alias.
- Nothing changes for a product until it runs `support workflows` (spec 7, "When the derivation switches on"); the one load-time change (Task 3, the si#487 rule) is measured over every reachable manifest before it ships.
- Suite: `deploy/orchestrator/.venv/bin/python -m pytest -q --no-header -p no:cacheprovider <paths>` (no `-n`). The root-bound `test_tasks_docs` failures the memory names are pre-existing.
- No em dash (U+2014); no counts typed into prose (compute or point at where it is computed); English artefacts.
- Commits: `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F- <<'EOF'`, trailers `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG`. No push, PR, dispatch or merge without Marco's word.

## Decisions this plan takes (the inputs did not settle them; each reopens on the trigger named)

1. **`CiRelease` is Python only**, in `src/simplon/model/command.py` beside `CiVariant` and `CiGate`, which are not modelled in `pipeline.firn` either (measured: no `emulates`/`timeout_minutes` under `src/firn/model` outside the workflow package). Reopens when the command `ci:` vocabulary is modelled in firn.
2. **The pages job runs on `github-ubuntu` whatever the release runner**, takes no checkout and starts no container (so no si#756 reap step: it holds `pages: write` and `id-token: write`, si#874's reason). A self-hosted kind would add launcher preflight steps that need the checkout the job does not take. The docs job runs on the release job's machine. Reopens when a product cannot use GitHub-hosted runners.
3. **Two ReleaseCommands are refused at generation** (expression rule: both would write release.yml). Measured: no reachable manifest holds two. Reopens when one does.
4. **A release-consumed artifact that the derived ci.yml cannot upload once** (produced only in a platform/python cell, a gate file or a cadence file) is named in ci.yml's note as not uploaded, with the reason; not refused, CI still verifies it. One that also crosses a job boundary inside ci.yml is refused at generation (diagnosis: the hand-off upload already holds that name in the run, so the promotion upload would be red).
5. **The si#487 rule (`release:check` first) holds every ReleaseCommand**, not the aggregate a `workflows: release:` names (that key is retired). Same population on the reachable manifests (simplon, firn); re-measured in Task 3.
6. **The retired keys are diagnoses**: once nothing reads `release:`, `emulates:`, `timeout_minutes:` or a workflow-level machine under `workflows: release:`, each would be ignored silently.
7. **`by:` must plan a `docs:site` leaf** (diagnosis): otherwise the upload publishes a directory nothing built. Measured: simplon's `build site` is a leaf and `build docs` the aggregate that also writes the generated pages; the docs job must name the aggregate.
8. **Measuring on GitHub needs main**: `release:check` refuses a run not started from the default branch (`src/simplon/tasks/release.py`, `GITHUB_REF`), so the dry-run release is dispatched from main after the merge, and the CI uploads are read off the push-to-main run that merge starts. No extra ci.yml dispatch.

## What each product sees

- **simplon:** migrates in Task 6.
- **firn:** declares a ReleaseCommand and `workflows.release` with `release:`, `timeout_minutes: 120`, `runs-on: firn`, a workflow `env:` and a `builder` job. Its next `support workflows` (and its `--check`/`test generated` gate) after the kernel bump is refused, naming each key's new place. Its migration (#893) moves the machine to `ci: { runner: { kind: <its kind>, labels: firn } }` on `ci release all` (the kind supplies the env), drops `timeout_minutes:` (equal to the default) and keeps `builder` as an extra job. The kernel bump PR must carry that move or firn holds its pin. firn has `website:` and no Pages: without `pages:` it gets no docs/pages jobs.
- **biz-cockpit:** no ReleaseCommand, so no release.yml is derived; `website:` without `pages:` derives nothing; its `{input: tag}` waits on #789/#895.
- **cleon:** no ReleaseCommand, old top-level `site:`, its own push-triggered pages.yml: untouched. `pages: push` is the reopening trigger for a second switch value.
- **Everyone else:** nothing. The load-time si#487 change binds only ReleaseCommand holders (Task 3 measures).

## Review Focus

- A dry run of the derived pair: `docs` uploads, `pages` runs `configure-pages` and skips `deploy-pages`, both green (Task 4, assert the `if:` on the deploy step and none on the upload; Task 6 measures on GitHub).
- A ReleaseCommand with no `workflows: release:` entry at all: release.yml holds the `release` job, and `docs` (if switched on) needs `release` only (Task 3 and Task 4 tests).
- A pull request run of ci.yml uploads nothing for #789 (Task 5 asserts `github.event_name != 'pull_request'` in each promotion step's `if:`; Task 6 reads the PR run).
- `workflows: release: { handwritten: "..." }` switches the derived release.yml off; a ReleaseCommand `ci:` key or `website: pages:` then shapes nothing and is refused with that reason (Task 3, Task 4 tests).
- firn's manifest as it stands: the refusal names `release:`, `timeout_minutes:` and `runs-on:` with each new place, and no workflow-level `runs-on:` under `workflows: release:` is dropped silently (Task 3 test over a copy of firn's entry).

---

### Task 1: The release vocabulary in the firn model; release.yml rendered from it, byte-identical

**Files:**
- Modify: `src/firn/model/simplon/workflow/workflow.firn`; regenerate `src/simplon/model/workflowschema.py` with `./simplon.sh build model` (adjust `src/firn/templates/workflowschema.firnt` only if a new class needs a rendering rule it lacks)
- Create: `src/simplon/tasks/releasepipeline.py`
- Modify: `src/simplon/tasks/workflowgen.py` (`render` stops calling `_release`; `_release`'s step logic moves to `releasepipeline`; `_RELEASE_TRIGGER` becomes model data), `src/simplon/tasks/cipipeline.py` (`_on` renders dispatch inputs; `workflows` hands a declared release entry to `releasepipeline`)
- Test: `src/tests/test_releasepipeline.py` (new), `src/tests/test_generated_workflowschema.py`, `src/tests/test_release_workflow.py`

**Interfaces:**
- Model, added to `workflow.firn` (each property with a comment citing si#862 and what reads it):
  - `DispatchInput` (class): `input_name` 1..1, `description` 1..1, `input_type` 1..1 (strings), `required` boolean 1..1, `default_value` string 0..1. `Trigger.dispatch_input` composition 0..N replaces the unused `Trigger.input` string list (prove unused with the suite and `./simplon.sh test typecheck-python`, not grep).
  - `Job.permission` composition `Permission` 0..N (job-level scopes, si#719); `Job.environment` composition `DeployEnvironment` 0..1 (`environment_name` 1..1, `url` 0..1); `Job.no_checkout` boolean 0..1.
  - `Step.condition` string 0..1, `Step.env` composition `RunnerEnv` 0..N (an expression is a string value), `Step.step_id` string 0..1.
- `releasepipeline.derive(manifest: Manifest, data: Mapping[str, object], entry: workflowgen.Workflow) -> workflowschema.Workflow`: path, title, one `dispatch` trigger with the `version` and `dry_run` inputs (values from today's `_RELEASE_TRIGGER`), the workflow permissions, one job `release`: kernel steps (names as module constants: `PASS_SECRETS_CHECK`, `EMULATION`, `PROVISION`, `RELEASE_CUT`, `RELEASE_STAMP`, `DRY_RUN_TAIL`, `REPORT`), command steps for the plan's leaves with `condition`/`env`/params as `_release` sets them today, `permission`, `timeout_minutes`, `env` (`RELEASE_VERSION` + runner env). Every refusal `_release` raises today moves with it, same text (census keys move from `("workflowgen", "_release", ...)` to `("releasepipeline", ...)`).
- `releasepipeline.to_workflow(model: workflowschema.Workflow, manifest: Manifest, data: Mapping[str, object], entry: workflowgen.Workflow, *, product: str) -> workflowgen.Workflow`: the renderer's workflow, `release` set (render's app-secrets insertion keys on it), `derived=True`, jobs = the converted `release` job then `entry.jobs`. Concurrency `_RELEASE_CONCURRENCY` is the converter's (renderer decides per file kind).
- Interim, deleted in Task 3: the release job's machine comes from `entry.rollout_runs_on`/`rollout_runner`/`rollout_env`, because simplon's `runs-on: ubuntu-latest` names no kind the model's `Runner` could hold.
- `cipipeline.workflows`: a declared workflow with `.release` is replaced by `releasepipeline.to_workflow(releasepipeline.derive(...), ...)`.

- [ ] **Step 1: Failing tests.** `test_releasepipeline.py`: (a) `test_the_release_is_a_model_instance`: `derive` over simplon's loaded manifest returns a `workflowschema.Workflow` whose single trigger has inputs `version` (string, required) and `dry_run` (boolean, required, default `"true"`) and whose job `release` has permissions `contents: write`, `packages: write` and `timeout_minutes == workflowgen.RELEASE_TIMEOUT_MINUTES`; (b) `test_the_old_path_is_gone`: `not hasattr(workflowgen, "_release")` and `not hasattr(workflowgen, "_RELEASE_TRIGGER")`. `test_release_workflow.py`: `test_release_yml_renders_byte_identical_from_the_model`: the text `workflows.assemble` renders for `release.yml` equals `git show a985296:.github/workflows/release.yml` (read through `subprocess`, so the pin survives later regenerations of the file until Task 6 replaces the base with its own commit). Carry every existing synthetic `release:` test in `test_workflowgen*.py` and `test_release_bundle.py` unchanged: they must pass through the new path.
- [ ] **Step 2:** Run them; expect FAIL (`derive` not defined).
- [ ] **Step 3:** Model the vocabulary; `./simplon.sh build model`; `./simplon.sh test generated` green.
- [ ] **Step 4:** Implement `releasepipeline.derive`/`to_workflow`, `_on` with inputs; delete `_release` and `_RELEASE_TRIGGER` from `workflowgen`. Move census entries.
- [ ] **Step 5:** `./simplon.sh support github workflows --check` reports no drift; full suite green. Measure firn: fetch `firn.yaml` and its `.github/workflows/release.yml` (`gh api repos/marcozwyssig/firn/contents/<path> --jq .content | tr -d "\n" | base64 -d`), render firn's release.yml with main's kernel and with this branch's in a scratch directory; report the diff (expected empty) or why firn's manifest does not load against this catalogue.
- [ ] **Step 6:** Commit `refactor(si#862): the release workflow is derived through the firn workflow model, release.yml byte-identical`.

### Task 2: `ci: { emulates:, timeout_minutes:, runner: }` on a ReleaseCommand

**Files:**
- Modify: `src/simplon/model/command.py` (`CiRelease`, `ReleaseCommand.ci`), `src/simplon/manifest/load.py` (`_ci_skip`, new `_ci_release`, `_command`)
- Modify: `src/tests/test_refusal_census.py`
- Test: `src/tests/test_ci_skip.py`, `src/tests/test_release_bundle.py`

**Interfaces:**
- `@dataclass(frozen=True) class CiRelease: emulates: tuple[str, ...] = (); timeout_minutes: int | None = None; runner: "runners.Runner | None" = None; labels: tuple[str, ...] = ()` (runner and labels as `runners.resolve` returns them; None when unwritten).
- `ReleaseCommand.ci: CiRelease = field(default_factory=CiRelease)`.
- `_ci_skip(spec, where, ci_leaf, release: bool = False)`: on a release aggregate the held keys are `emulates`, `timeout_minutes`, `runner`; any other key, `ci: {}` and a non-mapping are diagnoses naming those three. On any other aggregate the existing message also says that `runner:`/`emulates:` belong on the release aggregate.
- `_ci_release(spec, where) -> CiRelease`, reusing `_ci_emulates`, `_ci_timeout` and `runners.resolve(value, f"'{where}' ci:")`.

- [ ] **Step 1: Failing tests:** (a) `release all` with `ci: { emulates: [linux/arm64], timeout_minutes: 90, runner: github-ubuntu }` loads to a `ReleaseCommand` whose `ci` holds those values; (b) `runner: { kind: self-hosted-container, labels: ghr-8 }` resolves kind and labels; (c) `ci: { skip: x }` and `ci: { gate: ... }` on a release aggregate are refused naming the three keys; (d) `ci: { runner: github-ubuntu }` on a non-release aggregate is refused, naming the release aggregate as the place; (e) a bad value of each key gives the existing reader's message.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; census entries (diagnosis) for each new message; see each red by breaking it once.
- [ ] **Step 4:** Full suite. Commit `feat(si#862): a ReleaseCommand carries its release job's machine, emulation and time limit under ci:`.

### Task 3: release.yml derived from the ReleaseCommand; `workflows.release.release:` retired; `workflows: release:` holds extra jobs

**Files:**
- Modify: `src/simplon/tasks/releasepipeline.py`, `src/simplon/tasks/cipipeline.py` (`workflows`, its docstring's switch rule), `src/simplon/tasks/workflowgen.py` (`_workflow`, `_release_key`, `_emulates`, `_release_timeout`, `_OWN_WORKFLOW_KEYS`)
- Modify: `src/simplon/manifest/load.py` (`_release_workflows` -> `_release_commands`), `src/simplon/manifest/ports.py` (`_check_release_first`)
- Modify: `src/tests/test_refusal_census.py`, every synthetic manifest in `src/tests` that writes `release:` under `workflows:` (find them by loading, not by grep alone: the suite goes red on each)
- Modify: `src/site/content/how/manifest.md` (`workflows:` section), `src/site/content/when/releases.md` (the si#490 paragraph and the si#487 rule), `src/site/content/with-what/rules.md` (the si#487 sentence)
- Test: `src/tests/test_releasepipeline.py`, `src/tests/test_workflowgen.py`, `src/tests/test_release_rule.py`

**Interfaces:**
- `releasepipeline.release_commands(manifest: Manifest) -> tuple[tuple[str, ReleaseCommand], ...]` (command words, spec), in manifest order.
- `releasepipeline.derive(manifest, data, entry: workflowgen.Workflow | None) -> workflowschema.Workflow`: the release aggregate is the one ReleaseCommand; the machine is `ci.runner` or else `cipipeline.runner_of(data)`, always a kind now (the interim pass-through of Task 1 is deleted); `emulates` and `timeout_minutes` from `ci` (default `RELEASE_TIMEOUT_MINUTES`); `workflowgen._refuse_emulates_where_it_cannot_register` is called with that runner (census key unchanged). `entry` is the declared `workflows: release:` entry or None; its `jobs`, `permissions`, `env` and `note` are carried as today.
- `cipipeline.workflows`: one ReleaseCommand and no `workflows: release: { handwritten: }` -> the derived release.yml, the declared `release` entry folded into it (not emitted on its own). Handwritten -> no derived release.yml, and a ReleaseCommand `ci:` key is refused as shaping nothing (diagnosis). No ReleaseCommand -> a `workflows: release:` entry is an ordinary declared workflow.
- `workflowgen._workflow`, under any key: `release:`, `emulates:`, `timeout_minutes:` refused; under the key `release` also a workflow-level `runs-on:`, `runs_on:`, `runner:`. One message per key, naming the new place (`ci: { runner: }`/`emulates:`/`timeout_minutes:` on the ReleaseCommand under `ci release`; "the release is derived into release.yml from the ReleaseCommand; `workflows: release:` adds jobs beside it"). Kind: diagnosis (nothing reads them any more). The `on:`, `concurrency:`, `flow:`, job-named-`release` and `RELEASE_VERSION` refusals stay, worded for the derived release.
- `load._release_commands(manifest) -> dict[str, str]` and `ports._check_release_first` name the aggregate, not a workflow key; census entry text and key updated (still expression rule, merged reach).

- [ ] **Step 1: Measure first:** over the reachable manifests (fetch as Task 1; names in memory `reachable-manifests-are-named-per-product`), list each ReleaseCommand, whether its plan starts with `release:check`, and each `workflows:` entry that writes a retired key. Put the table in the report. Expected from the 2026-11-25 measurement: simplon and firn only, both checked first.
- [ ] **Step 2: Failing tests:** (a) a ReleaseCommand and no `workflows:` derives `release.yml` with the dispatch inputs and the `release` job on the product runner; (b) with `workflows: release: { jobs: { extra: { needs: release, steps: [...] } } }` the file holds `release` then `extra`; (c) each retired key, under `release` and under another key, refused with its own message (one parametrised test, the firn-shaped entry `{release: ci release all, timeout_minutes: 120, runs-on: firn, env: {...}, jobs: {builder: ...}}` among the cases); (d) `emulates:` on a ReleaseCommand whose effective runner is `self-hosted-container` refused naming #722; with `ci: { runner: github-ubuntu }` it renders the QEMU step; (e) two ReleaseCommands refused naming both; (f) `handwritten:` under `release` derives no release.yml, and `ci: { runner: }` on the ReleaseCommand is then refused; (g) a ReleaseCommand whose plan does not start with `release:check` refused at load naming the aggregate.
- [ ] **Step 3:** Run; expect FAIL.
- [ ] **Step 4:** Implement; move synthetic fixtures to the new form, each test keeping what it protects; census entries (the retired-key diagnoses, the two-ReleaseCommands expression rule with its reopening trigger, the handwritten diagnosis), each seen red. simplon's own manifest still writes the old form: its `--check` is refused from this commit until Task 6, so `test_own_workflows.py` and `test_release_workflow.py` are red in between; say so in the commit body, or (better) land Task 6's manifest move of the three keys in this commit and leave only docs/pages and the notes to Task 6. Choose the second when the diff stays reviewable.
- [ ] **Step 5:** Docs: `how/manifest.md` states the switch rule for `release` (handwritten switches off; jobs add) and the three `ci:` keys; `when/releases.md` and `with-what/rules.md` lose `workflows: <key>: release:` as a current form. Full suite; `./simplon.sh test generated`.
- [ ] **Step 6:** Commit `feat(si#862): release.yml is derived from the ReleaseCommand; workflows.release.release: is retired and the entry adds jobs`.

### Task 4: `docs` and `pages` derived from `website: { pages: release, by: }`

**Files:**
- Modify: `src/simplon/tasks/site.py` (reader), `src/simplon/tasks/releasepipeline.py` (two jobs), `src/simplon/tasks/workflowgen.py` (constants: `RELEASE_ON_ORIGIN`, the three Pages action pins), `src/tests/test_refusal_census.py`
- Modify: `src/site/content/how/manifest.md` (`website:` keys)
- Test: `src/tests/test_releasepipeline.py`, `src/tests/test_tasks_site.py`

**Interfaces:**
- `site.Pages(NamedTuple): on: str; by: str`; `site.pages(data: Mapping[str, object]) -> site.Pages | None` (None when `website:` or `pages:` is absent). Diagnoses: `pages:` other than `release` (name the one value, and that cleon's per-push deploy is the reopening trigger); `pages:` without `by:` and `by:` without `pages:`; `by:` not `<group> <name>`.
- At derivation (`releasepipeline`), diagnoses: `pages: release` with no ReleaseCommand or a handwritten release; `by:` resolving to no command (`workflowgen.resolve_command`); `by:` not unattended (`workflowgen.require_unattended`); `by:`'s plan holds no `docs:site` leaf; a declared release job named `docs` or `pages` ("rename yours", as for `release`).
- Model jobs, converted by `to_workflow`:
  - `docs`: the release job's runner; `needs` = `release` plus every declared release job, in declared order; `env` `RELEASE_VERSION: ${{ inputs.version }}`; permission `contents: read`; steps: `RELEASE_CUT` with condition `${{ inputs.dry_run }}`, `RELEASE_ON_ORIGIN` (the "tag is on origin at this commit" script, verbatim from simplon.yaml today) with `${{ !inputs.dry_run }}`, the `by:` command, then `actions/upload-pages-artifact@v3` with `path: <site.declared(data).output>` as the LAST step, no condition.
  - `pages`: `github-ubuntu`, `no_checkout`, `starts_no_container`, `needs: docs`, permissions `pages: write` and `id-token: write`, environment `github-pages` with url `${{ steps.deployment.outputs.page_url }}`, concurrency `pages`; steps `actions/configure-pages@v5` (`enablement: true`) and `actions/deploy-pages@v4` with `step_id` `deployment` and condition `${{ !inputs.dry_run }}`.
  - Notes (generated prose): the upload is last so no later step can turn the job red after the artifact exists (si#851); the deploy has its own job because `deploy-pages` listed the artifacts one second after the upload and found none (runs 44901604309, 44938156739); "Re-run failed jobs" reruns `pages` alone; a full rerun needs the run's `github-pages` artifacts deleted first; docs waits for every declared release job so the site never documents a version nobody can install (D12, until #789).

- [ ] **Step 1: Failing tests:** (a) `pages: release, by: build docs` over a synthetic manifest with a ReleaseCommand and declared jobs `publish`, `image`: release.yml has `docs` with `needs: [release, publish, image]`, its last step the upload with the declared output path, and `pages` as specified; (b) without declared jobs, `docs` needs `release` only; (c) `website:` without `pages:` (firn's and biz-cockpit's shape) derives neither job; (d) the deploy step's `if:` is `${{ !inputs.dry_run }}` and the upload has none; (e) each diagnosis above, red with its message; (f) the docs job's cut and origin scripts equal `workflowgen.RELEASE_CUT` and `RELEASE_ON_ORIGIN`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; census entries (all diagnoses), each seen red.
- [ ] **Step 4:** Docs paragraph for `pages:`/`by:`; full suite. Commit `feat(si#862): website: pages: release derives the docs and pages jobs with si#851's boundary`.

### Task 5: ci.yml uploads the `path:` artifacts a release step consumes (#789's hand-off)

**Files:**
- Modify: `src/firn/model/simplon/workflow/workflow.firn` (`Step.artifact`, string 0..1, the artifact a kernel step names), regenerate
- Modify: `src/simplon/tasks/releasepipeline.py` (`consumed`), `src/simplon/tasks/cipipeline.py` (`_job`, `_to_job`, `_leaf_ids`, the job note), `src/tests/test_refusal_census.py`
- Modify: `src/site/content/how/manifest.md` (derived CI section: what is uploaded, for how long, from which runs)
- Test: `src/tests/test_cipipeline.py`

**Interfaces:**
- `releasepipeline.consumed(manifest: Manifest, data: Mapping[str, object]) -> tuple[str, ...]`: the artifacts with a `path:` that a leaf release.yml runs consumes (the ReleaseCommand's plan, every command step of the declared release jobs, the docs `by:` plan), in manifest order; () without a derived release.
- Kernel step `PROMOTE_UPLOAD = "promote-upload"` with `artifact`, placed in ci.yml's main job after the last leaf and before `REPORT_UPLOAD`, one per consumed artifact a leaf of that job produces. Rendered as `actions/upload-artifact@v4` with `name: <artifact>`, `path: <declared path>`, `if-no-files-found: error`, `retention-days: 90`, and `if: ${{ !cancelled() && steps.<producer id>.outcome == 'success' && github.event_name != 'pull_request' }}` (the producer gets its id through `_leaf_ids`).
- Not uploaded, named in ci.yml's note with the reason (Decision 4): a consumed artifact produced only in a cell, a gate file or a cadence file. Refused at generation (diagnosis): one that also crosses a job boundary inside ci.yml.

- [ ] **Step 1: Failing tests:** (a) a synthetic manifest where `build x` (ci build) produces `x` with `path:` and a release member consumes it: ci.yml's main job uploads `x` after the last leaf with exactly the `with:` and `if:` above; (b) an artifact no release step consumes is not uploaded; (c) an image artifact (no `path:`) is not uploaded; (d) a pull request is excluded by the expression, push and dispatch are not; (e) cell-only producer: not uploaded, named in the note; (f) crossing inside ci.yml: refused naming the artifact and both jobs; (g) simplon's own: the set `consumed` returns equals what ci.yml uploads (computed, not typed).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Model `Step.artifact`, regenerate, implement; census entry (diagnosis) seen red.
- [ ] **Step 4:** Docs; full suite; regenerate simplon's ci.yml (`./simplon.sh support github workflows`), `--check` and `./simplon.sh test generated` green.
- [ ] **Step 5:** Commit `feat(si#862): ci.yml keeps each path: artifact a release consumes for 90 days, from push and dispatch runs`.

### Task 6: simplon's release.yml derived; measured on GitHub

**Files:**
- Modify: `simplon.yaml` (`ci:` on `release all`, `website:` gains `pages:`/`by:`, `workflows.release` loses its derived keys and the `docs`/`pages` jobs)
- Regenerate: `.github/workflows/release.yml`, `.github/workflows/ci.yml`
- Modify: `src/tests/test_release_workflow.py`, `src/tests/test_own_workflows.py`

The manifest edit, exactly:
- `release all`: `ci: { runner: github-ubuntu, emulates: [linux/arm64] }`, comment: si#570 (the suite's linux/arm64 e2e, si#552), and why not ghr-8 (`self-hosted-container` cannot register emulation, #722). No `timeout_minutes:` (today's 120 is the default).
- `website:`: `pages: release` and `by: build docs`, comment: si#851, and why the aggregate (it writes the reference and acceptance pages before `build site`).
- `workflows.release`: delete `release:`, `emulates:`, `runs-on:` and the `docs` and `pages` jobs; rewrite the entry's `note:` and its leading comment for "the release job, docs and pages are derived; these jobs are added". `publish`, `homebrew-tap` and `image` stay, each note gaining one line: "D12: an exception that waits on #789 (build once, release promotes); #864 makes it a counted `exception:`".

- [ ] **Step 1: Rewrite the failing tests:** `test_a_release_that_changes_no_documentation_still_rebuilds_the_site` asserts the derived `docs` job (needs `release`, `publish`, `homebrew-tap`, `image`; runs `build docs`; uploads `build/site` last); the test holding the cut copies equal keeps `publish` and `image`; `test_release_yml_renders_byte_identical_from_the_model` is replaced by `test_simplons_release_yml_is_derived`: no `release:` key under `workflows.release` in simplon.yaml and the rendered `release` job equals the Task 5 commit's `release` job except for the lines Step 4 explains.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Manifest edit; `./simplon.sh support github workflows`; `--check`; `./simplon.sh test generated`; full suite.
- [ ] **Step 4: Measure the diff** `git diff <Task 5 commit> -- .github/workflows/release.yml .github/workflows/ci.yml` and explain every changed line in the PR body (expected kinds: `runs-on` now from a kind with its note; `docs` needs the three jobs and has no `setup-python` 3.12; `pages` has no reap step; generated notes; ci.yml's promotion uploads). A change no step of this plan predicts is a finding: stop and report it.
- [ ] **Step 5:** Commit `feat(si#862): simplon's release, docs and pages are derived; publish, homebrew-tap and image stay as D12 exceptions`.
- [ ] **Step 6 (Marco's word): push and open the PR** (`Closes #862`). Read the PR's ci.yml run: every promotion upload step is skipped (`gh run view <id> --json jobs --jq '.jobs[].steps[] | [.name,.conclusion] | @tsv'`).
- [ ] **Step 7 (Marco's word, after Marco merges): read the push-to-main run** `gh api repos/marcozwyssig/simplon/actions/runs/<id>/artifacts --jq '.artifacts[] | [.name,.expires_at] | @tsv'`: the names equal `releasepipeline.consumed` over simplon's manifest, each expiring about 90 days out.
- [ ] **Step 8 (Marco's word): one dry-run release from main** `gh workflow run release.yml -R marcozwyssig/simplon --ref main -f version=<next unreleased vX.Y.Z> -f dry_run=true`. Green verdict only from that run: `release` green, `docs` uploads `github-pages`, `pages` runs `configure-pages` and skips `deploy-pages`. Post the run link and the step table on #862. A red step is a finding with its log, not a retry.

## Self-review

- Spec 6.1: Tasks 1-3 (release without the entry, keys on the ReleaseCommand), Task 5 (named artifact per commit for #789). 6.2: Task 4 (explicit switch per Q3, not the bare section). 6.3: untouched (#864); the D12 jobs carry their note in Task 6. 7 step 8: Tasks 1-6. `{input: tag}` is out by decision.
- Type names used across tasks: `releasepipeline.derive`/`to_workflow`/`release_commands`/`consumed`, `CiRelease`, `site.Pages`/`site.pages`, `PROMOTE_UPLOAD`, `RELEASE_ON_ORIGIN`, model `DispatchInput`, `DeployEnvironment`, `Job.permission`/`environment`/`no_checkout`, `Step.condition`/`env`/`step_id`/`artifact`.
- Unrelated, mention only: `docker/setup-qemu-action@v3` in simplon's `image` job is a tag, not a SHA; a jobs-only declared workflow's workflow-level `runs-on:` is in `_OWN_WORKFLOW_KEYS` and appears to be dropped without a word (read, not run: measure before filing).
