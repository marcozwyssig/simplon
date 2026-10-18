# si#491 simplon's own dispatch release: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** simplon cuts its releases from the `workflow_dispatch` button. `.github/workflows/release.yml`
is generated from `simplon.yaml` by `workflows: release: release: release all`, and no longer written by hand.

**Architecture:** This change is to the manifest and its tests only. The kernel is not touched.
- `release all` gains the four test leaves, ahead of `notes` and `tag`, and drops `push-image`.
- `workflows: release:` loses `handwritten:` and declares the `release:` key plus three product jobs:
  - `publish` (needs `release`), then `docs` and `image` (both need `publish`).
  - Each product job cuts the tag locally first, with a verbatim copy of `workflowgen.RELEASE_CUT`.
  - Each product job skips its publishing steps on a dry run.
- The tests that read `release.yml` now hold the generated file.

**Tech Stack:** Python 3.12, pytest, PyYAML, GitHub Actions, simplon workflowgen (si#490).

**Spec:** `docs/superpowers/specs/2026-10-18-si491-simplon-own-release-design.md` (decisions on si#491
comments 6246271640 and the follow-up).

## Global Constraints

- Python is `deploy/orchestrator/.venv/bin/python`. The suite runs serially (no `-n`), in about 3 minutes.
- `release.yml` keeps its path `.github/workflows/release.yml`.
- The `publish` job keeps `environment: pypi` and `permissions: id-token: write`. This is untestable
  here: PyPI's trusted publisher is configured by filename and environment on PyPI's side.
- `docs` keeps:
  - `environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }`;
  - `permissions: { pages: write, id-token: write }`;
  - `concurrency: { group: pages, cancel-in-progress: false }`.
- `image` keeps permissions contents/packages/pull-requests/actions: write and the qemu step with
  `image: tonistiigi/binfmt:qemu-v10.2.3`, `platforms: arm64`.
- No `${{ inputs.` inside any `run:` script. A product job sets `env: RELEASE_VERSION: ${{ inputs.version }}`
  at job level, and scripts read `$RELEASE_VERSION`. No `GITHUB_REF_NAME` remains in `release.yml`.
- Every publishing step carries `if: ${{ !inputs.dry_run }}`, and only those steps do:
  `pypa/gh-action-pypi-publish`, `actions/deploy-pages`, `release push-image` and the pin-PR script.
  `upload-pages-artifact` runs on a dry run: it uploads into the run, not to Pages.
- Product jobs declare `python: "3.12"`.
- Commits use a heredoc message, carry the env git identity (Marco Zwyssig <marco@zwyssig.info>), and
  end with the Co-Authored-By and Claude-Session trailers.
- The derived file is written by `./simplon.sh support workflows`, never by hand.
  `./simplon.sh support workflows --check` must be clean.

## Review Focus

- A dry run must publish nothing. Look for any step reaching PyPI, Pages, ghcr or `git push`/`gh pr`
  that lacks `!inputs.dry_run`, including a step a future edit adds. The test asserts over every step
  of every product job, not over a named list alone.
- On a real run the local cut in a product job must be a no-op. The fetched tag sits at HEAD, and
  `RELEASE_CUT` deletes and re-creates it at the same commit. A job on a commit other than the tagged
  one must refuse, not re-point. `RELEASE_CUT` already does this, and the copy test keeps the copy equal.
- The pin script must name `$RELEASE_VERSION`, never `main`. A leftover `GITHUB_REF_NAME` would open
  `pin/kernel-image-main`.
- `release all` run locally now runs the suite. Its `help:` must say so, or a person typing it is
  surprised by 3 minutes of tests.
- The docs must stop telling anyone to cut *simplon's* release with `release tag vX`. Pages describing
  a product's release (`myctl`, case records) stay as they are.

---

### Task 1: The generated release workflow

**Files:**
- Modify: `simplon.yaml` (`ci: release: commands: all`; `workflows: release:`)
- Regenerate: `.github/workflows/release.yml`
- Modify: `src/tests/test_release_workflow.py`, `src/tests/test_own_image.py:353-397`,
  `src/tests/test_own_workflows.py:90-130`
- Check: `src/tests/test_type_gate.py`, `src/tests/test_version_source.py`, and any test the suite turns
  red on `release all`'s members (`test_command.py:76`, `test_product_manifest.py:209`)

**Interfaces:**
- Consumes: `workflowgen.RELEASE_CUT` (str), `workflowgen.RELEASE_ENV == "RELEASE_VERSION"`, and the
  `release:` key and job rendering from si#490.
- Produces: job names `release`, `publish`, `docs` and `image` in `release.yml`, which Task 2's docs name.

- [ ] **Step 1: Write the failing tests.**

  In `test_release_workflow.py`:
  - Replace `test_the_release_is_triggered_by_a_tag_and_by_nothing_else` with
    `test_the_release_is_started_from_the_button_and_by_nothing_else`. It asserts
    `set(workflow[True]) == {"workflow_dispatch"}` and
    `set(workflow[True]["workflow_dispatch"]["inputs"]) == {"version", "dry_run"}`.
  - Delete the on-main fixture and the four on-main tests (`test_the_workflow_says_whether_the_tag_is_on_main`
    and the three after it).
  - Change `test_the_version_that_was_built_is_asserted_against_the_tag` to read `$RELEASE_VERSION`
    instead of `GITHUB_REF_NAME`.
  - Add these tests:
    - `test_the_release_job_runs_the_gate_before_the_tag`. The `run:` lines of `jobs.release`, in order,
      contain `./simplon.sh test suite`, `test typecheck-python`, `test generated` and
      `test release-notes`, each before `./simplon.sh release tag`.
    - `test_every_product_job_cuts_the_tag_locally_first`. For each of `publish`, `docs` and `image`,
      the first step after `actions/checkout` and `setup-python` has `run == workflowgen.RELEASE_CUT`.
    - `test_a_dry_run_publishes_nothing`. Walk every step of every job except `release` (that job's
      guards are si#490's). A step is publishing if its `uses` starts with `pypa/gh-action-pypi-publish`
      or `actions/deploy-pages`, or its `run` contains `release push-image`, `git push` or
      `gh pr create`. Assert every publishing step has `if == "${{ !inputs.dry_run }}"`. Assert the set
      of guarded steps is exactly those, so a guard on a build step also turns the test red.
    - `test_no_script_reads_an_input_or_the_ref_name`. No `run` contains `${{ inputs.` or
      `GITHUB_REF_NAME`.
    - `test_the_release_path_carries_no_test_archive_yet`. No step uses `actions/upload-artifact`, and
      the docstring names si#509 and si#248.
  - Change the module fixture `publish_job` to `workflow["jobs"]["publish"]`, as today.

  In `test_own_image.py`, `test_every_release_publishes_the_image_after_the_wheel_and_ci_never_does`
  keeps `needs == "publish"`. Add the assertion
  `job["steps"][i]["if"] == "${{ !inputs.dry_run }}"` for the `release push-image` step.

  In `test_own_workflows.py`, `test_the_ci_workflow_is_the_generated_one` becomes
  `test_both_workflows_are_generated`, which asserts
  `generated == [".github/workflows/ci.yml", ".github/workflows/release.yml"]`. Delete
  `test_the_release_workflow_is_declared_hand_written_with_its_reason`, and say why in the commit
  message.

- [ ] **Step 2: Run them and watch them fail.**

  Run: `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_release_workflow.py src/tests/test_own_image.py src/tests/test_own_workflows.py -q`
  Expected: the new and changed tests FAIL against the hand-written file (trigger `push`,
  `GITHUB_REF_NAME`, no `release` job, release.yml declined). Keep the list of red tests in the ledger.

- [ ] **Step 3: Change `simplon.yaml`.**

  1. `ci: release: commands: all`:
     - `depends_on: [suite, typecheck-python, generated, release-notes, notes, tag]`;
     - `help: "The release: the tests, the type gate, the staleness gate and the notes guard, then the notes, then the tag."`;
     - rewrite the block comment above `notes`. Drop the sentence "simplon's real release still starts
       with `./simplon.sh release tag vX` ... Changing that is open (si#344)". In its place, say that
       the button runs this aggregate (si#491) and that `push-image` left it for the `image` job after
       `publish` (decision 1).
  2. The `push-image` comment says it runs in `release.yml`'s `image` job after `publish`, and only
     when the dispatch is not a dry run.
  3. Replace `workflows: release:`'s `handwritten:` and its comment block with:
     - `name: release`, `release: release all`, `runs-on: ubuntu-latest`, and a `note:` carrying the
       button and decisions 1 to 6 in two short paragraphs;
     - `jobs:` with `publish`, `docs` and `image`. Each job has `runs-on: ubuntu-latest`,
       `python: "3.12"` and `env: { RELEASE_VERSION: "${{ inputs.version }}" }`, then this first step:
       `{ name: "Cut the tag in this checkout", run: <RELEASE_CUT verbatim, as a YAML block scalar> }`,
       with a `note:` saying why (decision 5).
     - `publish`: `needs: release`, `environment: pypi`, `permissions: { id-token: write }`. Steps:
       - `command: build wheel`;
       - the si#3 check, verbatim from today's file with `${GITHUB_REF_NAME#v}` changed to
         `${RELEASE_VERSION#v}` and `tag ${GITHUB_REF_NAME}` changed to `tag ${RELEASE_VERSION}`. Its
         `note:` is today's comment, condensed to what it still says;
       - `uses: pypa/gh-action-pypi-publish@release/v1` with `if: ${{ !inputs.dry_run }}`.
     - `docs`: `needs: publish`, plus the environment, permissions and concurrency from Global
       Constraints. Steps:
       - `uses: actions/configure-pages@v5` with `enablement: true`;
       - `command: build docs`;
       - `uses: actions/upload-pages-artifact@v3` with `path: build/site`;
       - `{ id: deployment, uses: actions/deploy-pages@v4, if: ${{ !inputs.dry_run }} }`.
     - `image`: `needs: publish` and the four permissions. Steps:
       - qemu, as in Global Constraints;
       - `command: build image`, `params: { tag: { env: RELEASE_VERSION } }`;
       - `command: test image`, with the same param;
       - `command: release push-image`, with the same param, plus
         `env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }` and the dry-run `if`;
       - the pin-PR script, verbatim from today with every `${GITHUB_REF_NAME}` changed to
         `${RELEASE_VERSION}`, plus its `env: GH_TOKEN` and the dry-run `if`.

     Check the exact spelling of a param value and a job-level `env:` against si#490's fixtures
     (`test_workflowgen.py` around line 2386) before writing.
  4. Run `./simplon.sh support workflows`, then `git diff --stat .github/workflows`.

- [ ] **Step 4: Run the three files.**

  Run: same command as Step 2.
  Expected: PASS. If a kept test fails because its assumption moved (the job set, a `needs`), rule on it
  in the ledger. Never loosen a test to fit.

- [ ] **Step 5: Run the gates.**

  Run, writing the output to the workspace:
  - `./simplon.sh support workflows --check`;
  - `./simplon.sh test generated`;
  - `deploy/orchestrator/.venv/bin/python -m pytest src/tests -q`.

  Expected:
  - `--check` reports no drift;
  - the suite is green except the 3 known root-bound `test_tasks_docs` failures, if they still appear;
  - `test_type_gate.py` still counts `release.yml` among the verifying files.

  If actionlint is available (`docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.7 .github/workflows/release.yml`),
  it reports nothing.

- [ ] **Step 6: Commit.**

  Stage `simplon.yaml`, `.github/workflows/release.yml` and the three test files. The message is
  `feat(si#491): simplon's release.yml is generated - the button, the gate before the tag, the dry run in every job`.

### Task 2: The docs describe the button

**Files:**
- Modify: `README.md` § Releasing (around line 186), `src/site/content/how/manifest.md:249`,
  `src/site/content/how/releasing.md` (only where it speaks of simplon itself),
  `src/site/content/what/examples.md:166` (read the context first: change it only if it tells a reader
  how simplon is released *now*)
- Do not touch: the `case-*.md` pages. They are dated run records.

**Interfaces:**
- Consumes: job names `release`, `publish`, `docs` and `image` from Task 1.

- [ ] **Step 1: Write the failing test.**

  Add `test_the_readme_releases_from_the_button` to `src/tests/test_release_workflow.py`. It asserts:
  - the README's `## Releasing` section contains `workflow_dispatch` and `dry_run`;
  - the section contains neither `./simplon.sh release tag v` nor `git push origin v`.

- [ ] **Step 2: Run it and watch it fail.** Expected: FAIL on `./simplon.sh release tag v0.1.13`.

- [ ] **Step 3: Rewrite the prose.**
  - **README:** Actions → release → Run workflow, with `version` and `dry_run` (default true).
    - Rehearse first, then run for real.
    - The tag IS the version: keep the setuptools-scm paragraph, but the tag is now cut by the
      run, not typed.
    - Off-main is refused, so a hotfix is merged first.
    - When a publish job fails after the tag, rerun that job. Never cut a second tag.
    - The release path no longer archives its test report (si#509).
  - **manifest.md:249:** delete "simplon itself still releases with `./simplon.sh release tag vX`".
    In its place, say that simplon's own `release.yml` is the first workflow derived this way.
  - **releasing.md:** wherever it describes simplon's own route, use the same facts.

- [ ] **Step 4: Run the test and the site build.**

  Run:
  - `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_release_workflow.py src/tests/test_site_counts.py -q`
    (use the real name of the site-count test file if this one differs);
  - `./simplon.sh build docs`.

  Expected: PASS, and the site builds.

- [ ] **Step 5: Commit.** The message is `docs(si#491): simplon is released from the button`.

## After the tasks

Do a whole-branch review and one fix pass. Then:
- open a PR with `Closes #491`, naming the Allure loss and si#509;
- before asking for the merge, try `gh workflow run release.yml --ref si491-own-release -f version=<next> -f dry_run=true`.
  GitHub may refuse it, because `main`'s `release.yml` has no `workflow_dispatch` yet. Either way,
  record the result. If it ran, its result is acceptance 1. If not, run the dry run right after the
  merge.

Acceptance 2 (the real cut) is Marco's.
