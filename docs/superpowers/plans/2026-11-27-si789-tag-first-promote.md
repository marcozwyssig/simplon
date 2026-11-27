# si#789 Tag First, Then Promote: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** release.yml gates on green `main` CI, pushes the tag, builds and tests the release's artifacts once on the tag, and the publish jobs promote them without rebuilding.

**Architecture:** `release:check` gains a GitHub Actions lookup. `release all` loses its test members. `releasepipeline.derive` adds one derived `artifacts` job (the release's producers and the tests whose evidence a release step consumes, on the release machine, without `ci: params:`). The same-run hand-off (`handoff.plan`) carries the path artifacts to simplon's D12 jobs, which stop building. The #862 90-day upload in ci.yml goes.

**Tech Stack:** Python 3.12, PyGithub (`src/simplon/adapters/github.py`), firn workflow model, GitHub Actions, docker buildx bake.

**Spec:** `docs/superpowers/specs/2026-11-27-si789-tag-first-promote-design.md`

## Global Constraints

- Never write the em dash (U+2014). Technical text in English.
- `workflow_dispatch` inputs reach commands only through `env:` (si#488).
- "Could not look" is never "no run" and never "green" (spec 4.2). It refuses, naming the reason.
- A missing artifact in a promotion job is a red job naming it, never a fallback build.
- Generated files (`.github/workflows/*.yml`, `src/simplon/catalogue.yaml`) are regenerated with `./simplon.sh support github workflows` / the firn generation, never hand-edited, and committed with the change.
- Every new load-time `raise ValueError` gets a `CENSUS` entry in `src/tests/test_refusal_census.py` (and `REACH` if EXPRESSION), and the counts on `src/site/content/with-what/rules.md` follow.
- Suite: `deploy/orchestrator/.venv/bin/python -m pytest src/tests -q`. Three `test_tasks_docs` failures are root-bound and pre-existing.
- Every new assertion is seen red once (break the property, watch it fail, restore).
- Git identity on every commit via `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env; messages `feat(si#789): ...` with the session trailers.

## Review Focus

1. A release run against a commit whose `main` CI is still running (not completed): refused as "not green yet", naming the run, not "no run". Test in Task 2.
2. Several `ci.yml` push runs on the same sha (rerun after a flake): the newest completed attempt decides; one green attempt is enough. Test in Task 2.
3. A dry run where the producer job cuts the tag locally: wheel and image are stamped `X.Y.Z`, not `.devN`. Test in Task 4 (rendered steps) and the acceptance dry run (Task 8).
4. A product with a release but no artifact its release steps consume: no `artifacts` job, nothing else changes. Test in Task 4.
5. A rerun of only a failed promotion job after the producers succeeded: its download still finds this run's artifacts (same run, retention covers it). Checked in the Task 8 dry run by rerunning one job.

---

### Task 1: Measure how the multi-arch image crosses jobs (spike, no product code)

The image lives only in the producing job's buildx builder (`image._build_platforms`, `src/simplon/tasks/image.py:1683`). `release push-image` on another machine would rebuild. Measure on github-ubuntu with arm64 emulation:

- **A. OCI archive artifact:** bake with an extra `type=oci,dest=build/image/kernel.oci.tar` output, upload, download in a second job, `docker buildx imagetools create`/`oras` push from the archive. Record: archive size, upload+download time, whether the pushed index digest equals the producer's digests from the bake metadata.
- **B. Candidate tag in the registry:** the producer pushes `ghcr.io/marcozwyssig/simplon:candidate-<sha>` (dry run too), `image` retags by digest with `docker buildx imagetools create --tag <version> <candidate>@<digest>`. Record: time, and what a dry run leaves in ghcr.

- [ ] **Step 1:** Run both on a scratch branch with a throwaway workflow (not committed to main). Record numbers in a comment on #789.
- [ ] **Step 2: Decision rule.** Pick A if its digests match and total transfer is under the 4 min 34 s the `image` job costs today. Pick B only if A fails that. If neither holds, stop and bring both measurements to Marco before Task 5.

**Produces:** the chosen crossing (A or B), named in the #789 comment. Task 4 and Task 5 implement it.

---

### Task 2: `release:check` refuses a commit without green `main` CI

**Files:**
- Modify: `src/simplon/tasks/release.py` (`check(tag: str) -> int`, line 56)
- Modify: `src/simplon/adapters/github.py` (new function beside `published`, line 133)
- Modify: `src/firn/model/simplon/catalogue/tasks.firn:1481-1503` (the comment "It asks GitHub's API nothing" and the help text), then regenerate `src/simplon/catalogue.yaml`
- Modify: `src/simplon/tasks/releasepipeline.py:87` `_RELEASE_PERMISSIONS` gains `"actions": "read"`
- Test: `src/tests/test_release.py` (create the test functions there or in the existing release-check test module; find it with `grep -rn "def test.*check" src/tests/test_release*.py`)

**Interfaces:**
- Produces: `github.main_ci_verdict(sha: str, branch: str, workflow: str = "ci.yml") -> CiVerdict` and
  `class CiVerdict(NamedTuple): state: Literal["green", "red", "running", "none"]; url: str; conclusion: str`.
  Raises `github.Unanswered` when the API cannot be asked (no token, network, 4xx/5xx). Query: `repos/{owner}/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&branch={branch}&event=push`. The newest completed attempt per run decides; any green run gives `green`.

- [ ] **Step 1: Write the failing tests** (inject the lookup: `check` takes the verdict through a module-level seam `release._ci_verdict = github.main_ci_verdict` that tests monkeypatch):
  - `test_check_refuses_a_commit_with_no_main_ci_run`: verdict `none`, then `check("v1.2.3") == 1`. The log names the sha and says no `ci.yml` push run exists on `main` for it.
  - `test_check_refuses_a_red_main_run_naming_it`: verdict `red`, url `https://github.com/o/r/actions/runs/7`, then rc 1. The log contains the url and `failure`.
  - `test_check_refuses_a_main_run_still_running`: verdict `running`, then rc 1. The log says it is not finished, with the url (Review Focus 1).
  - `test_check_refuses_when_it_cannot_look`: the seam raises `github.Unanswered("no token")`, then rc 1. The log says it could not look and why, and does NOT say "no run" (assert `"no " + "ci.yml" not in log`).
  - `test_check_passes_on_green`: verdict `green`, and the other checks are stubbed as today's tests do, then rc 0.
  - `test_main_ci_verdict_newest_attempt_decides` (adapter, against a recorded API payload): two runs, one failure and one success, give `green`; only `in_progress` gives `running` (Review Focus 2).
- [ ] **Step 2:** Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_release.py -q -k "check"`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement `main_ci_verdict` in `github.py` with `_asked(...)` and `githubpackages.token()`. In `check`, call it after the "origin carries HEAD" check (step 5 of today's order), with `gitops.remote_default_branch()` as the branch. One `log.error` sentence per state; return 1 on all but `green`.
- [ ] **Step 4:** Run the same command. Expected: PASS.
- [ ] **Step 5: Real instance.** Run `GITHUB_TOKEN=$(gh auth token) deploy/orchestrator/.venv/bin/python -c "from simplon.adapters import github; print(github.main_ci_verdict('<sha of origin/main>', 'main'))"` against this repository. Expected: `green` with a real run URL. Then run it with a sha that has no run (any feature-branch commit). Expected: `none`.
- [ ] **Step 6:** Regenerate the catalogue and workflows. Then run `./simplon.sh test generated`. Expected: clean. `release.yml`'s `release` job now shows `actions: read`.
- [ ] **Step 7:** Commit.

---

### Task 3: `release all` loses its test members

**Files:**
- Modify: `simplon.yaml:445-512` (the `release: all:` entry: `depends_on: [check, notes, tag]`, `help:`, and the comments at 445-452 that describe the four test leaves). Also the `workflows: release:` entry note at 899-912.
- Modify: the release.yml header text in `src/simplon/tasks/workflowgen.py` (the block that renders "The derived `release` job runs `release all`: the tests, ..."). It now says: gate on green `main` CI, notes, tag. Then the producers on the tag. Then promotion. Add the rule from spec 4.6: a red tag run is rerun, never retagged, and a real defect gets the next patch version.
- Test: `src/tests/test_release_workflow.py`, `src/tests/test_own_workflows.py`

`test release-notes` leaves with the other tests. The green `main` run ran it on the committed notes page, and `release notes` in this job writes only the GitHub release text (artifact `kernel-notes`).

- [ ] **Step 1: Turn the tests that encode the old order into the new claim:**
  - `test_the_release_job_runs_the_gate_before_the_tag` (`test_release_workflow.py:506`) becomes `test_the_release_job_runs_no_test_leaf`. No step of the `release` job runs `test suite`, `test typecheck-python`, `test generated` or `test release-notes`, and the order is check, notes, tag.
  - `test_the_release_job_archives_the_tests_that_gated_it` (756): delete. Its premise ends, and the REPORT step disappears because no `test:report` leaf remains. Assert in the renamed test above that the `release` job has no report upload.
  - `test_the_release_job_can_run_linux_arm64_before_the_suite` (`test_own_workflows.py:407`): move this claim to the `artifacts` job in Task 4. Delete it here.
- [ ] **Step 2:** Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_release_workflow.py src/tests/test_own_workflows.py -q`. Expected: the renamed test FAILS (the suite is still in the job).
- [ ] **Step 3:** Edit `simplon.yaml` and the header text. Regenerate the workflows.
- [ ] **Step 4:** Run the same command. Expected: PASS, except `test_simplons_release_yml_is_derived` (it compares `release` with the fixture). Update `src/tests/fixtures/workflows/release-handwritten-site.yml`'s `release` job to the regenerated one, after reading the diff line by line: only the four test steps, the report step and the header may differ.
- [ ] **Step 5:** Commit.

---

### Task 4: Derive the `artifacts` job (producers on the tag)

**Files:**
- Modify: `src/simplon/tasks/releasepipeline.py` (`derive`, line 231; `to_workflow`, line 465; `_to_job`, line 483; `consumed`, line 330)
- Test: `src/tests/test_releasepipeline.py`, `src/tests/test_release_workflow.py`

**Interfaces:**
- Consumes: `releasepipeline.consumed(manifest, data)`; `workflowgen._leaves`; `runner_of(spec.ci)`; the kernel steps `RELEASE_CUT` (condition `_DRY_RUN`), `RELEASE_ON_ORIGIN` (condition `_NOT_DRY_RUN`), `RELEASE_STAMP`; PROVISION; EMULATION.
- Produces:
  - `ARTIFACTS_JOB = "artifacts"` (module constant).
  - `producers_on_tag(manifest, data) -> tuple[workflowgen.Leaf, ...]`. Selection: every ci-area `build`/`test` TaskCommand that produces an artifact some release-workflow step consumes (registry images included, unlike `consumed`'s path filter), plus every test producing a `test-result` such a step consumes. Not selected: an artifact a step of the release workflow itself produces (the aggregate, the `workflows: release:` jobs, `website: by:`). That keeps `kernel-notes`, `simplon-formula` and `simplon-formula-checked` out. Ordered as `cipipeline.order`.
  - The `artifacts` job: `needs: release`; the release command's machine and emulation; time limit = the release's; steps PROVISION, EMULATION if declared, cut (dry run) / on-origin (real run), stamp, then each selected leaf with the release's parameters (no `ci: params:`; the `tag` param bound to `RELEASE_VERSION` as in the `release` job). For an image, add the crossing chosen in Task 1.
  - Order in the file: `release, artifacts, *entry.jobs, *website`.

- [ ] **Step 1: Write the failing tests** in `test_releasepipeline.py`:
  - `test_simplons_producers_on_tag_are_wheel_image_and_its_test`: `[l.spec.command for l in producers_on_tag(...)]` on simplon's manifest equals `["build wheel", "build image", "test image"]`.
  - `test_the_artifacts_job_builds_without_ci_params`: the rendered `build image` step carries no `--platform`.
  - `test_the_artifacts_job_runs_where_the_release_runs`: `runs-on` is `ubuntu-latest`, and a QEMU step for `linux/arm64` comes before `build image`.
  - `test_the_artifacts_job_cuts_on_a_rehearsal_and_requires_the_tag_on_a_real_run`: the cut step has `if: ${{ inputs.dry_run }}`, the on-origin step has `if: ${{ !inputs.dry_run }}`, and the stamp step comes before the first leaf (Review Focus 3).
  - `test_a_release_consuming_nothing_built_gets_no_artifacts_job`: a minimal manifest with a release and no consumed artifact renders no `artifacts` job (Review Focus 4).
  - `test_an_artifact_the_release_workflow_produces_is_not_rebuilt`: `build homebrew-formula` is not selected.
- [ ] **Step 2:** Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_releasepipeline.py -q -k "artifacts or producers"`. Expected: FAIL.
- [ ] **Step 3:** Implement `producers_on_tag` and the job in `derive`/`to_workflow`/`_to_job`. Reuse the `release` job's leaf loop for param binding and secrets instead of copying it. If the selection needs a refusal (for example a consumed artifact with no ci producer and no release-workflow producer), raise with a sentence naming the artifact and the consuming step, and add the census entry (DIAGNOSIS).
- [ ] **Step 4:** Run the same command. Expected: PASS. Then run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_workflowgen.py -q -k golden`. If the demo release in `release.golden.yml` changes, read the diff and regenerate the golden only if every change is the `artifacts` job.
- [ ] **Step 5:** Commit.

---

### Task 5: simplon's D12 jobs promote instead of build

**Files:**
- Modify: `simplon.yaml:913-1131` (`publish`, `image`; `homebrew-tap` unchanged), the D12 notes ("waits on #789" goes; the reason becomes "promotion is not derived yet, see the follow-up ticket")
- Test: `src/tests/test_release_workflow.py`

Changes:
- `publish`: remove `command: build wheel`. `dist` now arrives by hand-off from `artifacts` (handoff.plan adds `needs: artifacts` and the download). Keep "The wheel that was built must be the tag", and the PyPI step, `build homebrew-formula`, `test homebrew-formula` (spec 4.5).
- `image`: remove `build image` and `test image`. Bring the image in by the Task 1 crossing. Keep `release push-image`, the pin steps and the `gh workflow run`. `kernel-checked` arrives by hand-off.

- [ ] **Step 1: Write the failing tests:**
  - `test_no_promotion_job_builds_what_artifacts_built`: in release.yml, `publish` and `image` run no `build wheel`, `build image` or `test image`.
  - `test_publish_downloads_dist_from_artifacts`: `publish.needs` contains `artifacts`, and a `download-artifact` step names `dist`.
  - `test_push_image_consumes_the_evidence_the_artifacts_job_produced`: `image` downloads `kernel-checked`, and `needs` contains `artifacts`.
  - Update `test_the_release_tests_the_image_between_building_and_publishing_it` (774): the order is now `artifacts`(build image, test image), then `image`(push-image).
  - `test_a_missing_artifact_fails_naming_it` (see red): the rendered download step has no `continue-on-error`, and the cross-job download in `workflowgen._receive` fails the job when the artifact is absent. Assert on the rendered step. Then break it (set `continue-on-error: true` in a copy) and watch the test fail.
- [ ] **Step 2:** Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_release_workflow.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Edit `simplon.yaml`. Regenerate the workflows. Update `PRODUCT_JOBS` (line 474) if `image` no longer needs the cut (it does if the crossing pushes from a checkout, so keep it unless Task 1 chose a checkout-free path). Update the fixture's `publish`/`image` jobs after reading the diff.
- [ ] **Step 4:** Run the same command, then the full suite. Expected: PASS, except the three known `test_tasks_docs`.
- [ ] **Step 5:** Commit.

---

### Task 6: Remove ci.yml's 90-day promotion upload (#862)

Nothing reads it (measured: no `download-artifact`, `gh run download` or API fetch of another run anywhere outside worktrees).

**Files:**
- Modify: `src/simplon/tasks/cipipeline.py`: remove `PROMOTE_UPLOAD`, `PROMOTE_RETENTION_DAYS`, `_PROMOTED_EVENTS`, `PROMOTE_NOTE`, `_NARROWER`, `PROMOTE_UNKEPT`, `Promotion`, `_promotion`, `_refuse_promoted_crossings`, `_refuse_promoted_report_name`, `_unkept_note` and their uses (around 1079-1080, 1122, 1470, 1497-1507, 1587)
- Modify: `src/tests/test_cipipeline.py:1887-2110` (delete the promotion tests), `src/tests/test_workflow_handoff.py:222-224` (upload count without `kept`), `src/tests/test_own_report.py:48` (drop the `_PROMOTED_EVENTS` exclusion)
- Modify: `src/tests/test_refusal_census.py:1355,1357` (remove both entries), `src/site/content/with-what/rules.md` (counts, and the paragraph at line 250 rewritten: #789 removed the two diagnoses #862 added, and why)
- Modify: `src/site/content/how/manifest.md:1568-1579` (replace "ci.yml keeps what the release consumes" with the `artifacts` job: what it selects, where it runs, the dry-run cut)
- Regenerate: `.github/workflows/ci.yml` (the note at 50-60 and the upload at 205-215 go)

- [ ] **Step 1:** Delete the promotion tests. Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_refusal_census.py -q`. Expected: FAIL (`test_every_census_key_names_exactly_one_refusal` still finds the two refusals in code). This red is the census proving the population.
- [ ] **Step 2:** Remove the code. Regenerate. Fix the census and rules.md.
- [ ] **Step 3:** Run the full suite, `./simplon.sh test generated`, `./simplon.sh test typecheck-python`. Expected: PASS (known three excepted). Run `deploy/orchestrator/.venv/bin/python -c "import simplon.tasks.releasepipeline as r; print(r.consumed)"`. If nothing outside tests uses `consumed` any more, `producers_on_tag` should have absorbed it. Prove it with the suite after removal, not with grep.
- [ ] **Step 4:** Commit.

---

### Task 7: firn before-measurement and firn's manifest through the new generation

- [ ] **Step 1:** `gh run list --repo marcozwyssig/firn --workflow release.yml --status success -L 3 --json databaseId,createdAt,updatedAt`, then `gh run view <id> --repo marcozwyssig/firn --json jobs` for per-job times of the newest. Post the total and per-job times on #893 as "before (#789)".
- [ ] **Step 2:** Fetch firn's manifest (see memory `reachable-manifests-are-named-per-product`). Run this branch's `support github workflows --check` logic against it in a scratch copy of firn (a scratch clone, never firn's checkout). Record whether generation succeeds and how firn's release.yml changes. Post the result on #893. A break is reported there, not fixed here.

---

### Task 8: Acceptance on the real system

After merge (`release:check` refuses a start that is not on `main`):

- [ ] **Step 1: Red first.** Dispatch release.yml with `dry_run: true` on a version, at a moment when `main`'s head has no completed green `ci.yml` run (right after a merge, while CI runs). Expected: `release check` refuses with the "not finished" sentence and the run URL.
- [ ] **Step 2:** Once CI is green, dispatch the dry run again. Expected: `artifacts` builds wheel and image (both platforms) stamped with the version. `publish` and `image` logs show downloads and promotion steps skipped by the dry run, and no `build wheel` / `build image` / `test image`.
- [ ] **Step 3:** Rerun only `publish` from the Actions UI. Expected: its download of `dist` still succeeds (Review Focus 5).
- [ ] **Step 4:** At the next real release, record the wall time (total and per job) on #789 against the before of 23 min 24 s (run 45889937811).
