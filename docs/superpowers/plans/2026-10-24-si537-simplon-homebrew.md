# si#537 simplon releases its own Homebrew formula Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** simplon's own release renders, audits and commits its formula after the PyPI upload. CI proves simplon on the Python the formula runs it on.

**Architecture:**
- These are manifest edits to `simplon.yaml`, plus generated workflows and docs. No kernel code changes.
- The three si#536 coordinates become simplon commands, and the product job `publish` runs them after its PyPI step.
- The wheel is built once in that job. No handoff.

**Tech Stack:** `simplon.yaml`, the generated `.github/workflows/{ci,release}.yml`, Hugo docs via `./simplon.sh build docs`.

**Spec:** `docs/superpowers/specs/2026-10-18-si449-homebrew-tap-design.md`, section E and both amendments of 2026-10-24.

**Depends on:** si#534, si#535 and si#536 merged.

## Global Constraints

- **simplon's `with:` for `build homebrew-formula`:**
  - `shape: python`;
  - `depends_on: [cryptography, libsodium, libyaml, pydantic, python@3.14]`;
  - `python: python@3.14`;
  - `env: {SODIUM_INSTALL: system}`;
  - `test: {args: ["--help"], expect: "usage:"}`. Measured: lowercase `usage:`, and `--version` exits 2.
- **`source` and `online` are never in `with:`.** They are step `params:`, in two steps each:
  - `if: ${{ inputs.dry_run }}` with `local`/`false`;
  - `if: ${{ !inputs.dry_run }}` with `pypi`/`true`.
- **`release homebrew-tap`:**
  - `with: { repository: marcozwyssig/homebrew-tap }`;
  - `if: ${{ !inputs.dry_run }}`;
  - after the PyPI step;
  - its evidence is the formula's test result.
- **The new commands are in no aggregate** (`build all`, `test all`, `release all`). A developer's `test all` must not pull the 3.2 GB brew image.
- **The secrets** are `HOMEBREW_TAP_CLIENT_ID` and `HOMEBREW_TAP_APP_KEY`. Marco creates them before the first real run; the plan does not.
- **The new CI job** is `runs-on: ubuntu-latest`, `python: "3.14"`. The ghr-8 job is unchanged.
- Generated files are regenerated with `./simplon.sh support workflows` and committed with the change. Then `git add -A` and `./simplon.sh test generated` (it diffs against the index).
- Suite: `deploy/orchestrator/.venv/bin/python -m pytest`. No em dash in anything written.

## Review Focus

- **A dry run where the PyPI step is skipped.** Every PyPI-reading step must be skipped too, or the dry run goes red on a version PyPI does not list. Pinned in Task 2: every `source: pypi`/`online: true` step carries `!inputs.dry_run`.
- **A rerun of `publish` after the tap commit succeeded.** "Rerun the failed job, never a second tag." Expected: the PyPI step already fails today on an existing file. That stays the behaviour, and the tap answers `already current` if it ever gets there. Stated in `how/releasing.md`. There is no test, because it needs a real release.
- **`test all` or `build all` on a laptop.** Expected: neither touches docker for Homebrew. Pinned in Task 2.
- **The 3.14 job on ubuntu-latest meets tests that assume ghr-8 (docker group, root).** Expected: the first run is measured. A failure that is the host's, not the code's, is recorded as a finding with its log, not silenced with a skip. Task 1.
- **The README tells someone to `brew install` before the first generated formula exists.** The tap already carries 0.36.0 (homebrew-tap#1), so the command works today. Stated, not tested.

---

### Task 1: CI on Python 3.14

**Files:**
- Modify: `simplon.yaml` (`workflows: ci: jobs:`, a new job beside `self-build` at ~725).
- Regenerate: `.github/workflows/ci.yml`.
- Modify: `src/tests/test_own_workflows.py`, if it pins the ci job list.

- [ ] **Step 1: Write the failing test** in `test_own_workflows.py`: `test_ci_runs_the_suite_on_the_formulas_python`. The generated ci.yml has a job with `runs-on: ubuntu-latest`, an `actions/setup-python` step with `python-version: "3.14"`, and a step running `./simplon.sh test suite`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Add the job `suite-python-3-14`. Its note says why: the formula runs simplon on `python@3.14`, because Homebrew's `cryptography` and `pydantic` exist only for 3.14/3.15. Its one step is `command: test suite`. Run `./simplon.sh support workflows`.
- [ ] **Step 4:** Run `test_own_workflows.py`, then `git add -A` and `./simplon.sh test generated`. Expected: green.
- [ ] **Step 5: Commit** `ci(si#537): the suite runs on Python 3.14, the formula's interpreter`. After the push, read the job's first run with `gh run view`. Record its verdict and duration in the PR. A red that is the host's is a finding, not a skip.

### Task 2: The formula commands and the publish job

**Files:**
- Modify: `simplon.yaml`:
  - `artifacts:` gains `dist` (`kind: directory`, `path: dist`), `simplon-formula` (`kind: homebrew-formula`, `path: build/homebrew/simplon.rb`) and `simplon-formula-checked` (`kind: test-result`, `path: build/test/homebrew-formula.json`);
  - `ci: build:` `wheel` gains `produces: { directory: dist }`, and a new `homebrew-formula` command (`task: "build:homebrew-formula"`, consumes `wheel: dist`, produces `formula: simplon-formula`, with simplon's `with:`);
  - `ci: test:` gains `homebrew-formula` (`task: "test:homebrew-formula"`, consumes `formula: simplon-formula` and `wheel: dist`, produces `test-result: simplon-formula-checked`);
  - `ci: release:` gains `homebrew-tap` (`task: "release:homebrew-tap"`, consumes `formula: simplon-formula`, `evidence: [simplon-formula-checked]`, `with: { repository: marcozwyssig/homebrew-tap }`);
  - `release all`'s `help:` gains one sentence: after PyPI the publish job renders, audits and commits the Homebrew formula, and the tap follows PyPI so the formula never names a URL that is not live;
  - the `publish` job gains the five steps after `pypa/gh-action-pypi-publish`, in the order build, test, release, with the `if:`/`params:` from Global Constraints.
- Regenerate: `.github/workflows/release.yml`, the shell completion, `CLAUDE.md` if `support claude-md` lists commands, and the firn model via `support manifest model`. `test generated` names what drifts.
- Modify: `src/tests/test_release_workflow.py`.

**Interfaces:**
- Consumes: si#536's coordinates, ports and params (`source`, `online`, `repository`, `branch`); si#534's derived token step.

- [ ] **Step 1: Write the failing tests** in `test_release_workflow.py`:
  - `test_the_tap_follows_pypi`: in `publish`, the index of the `release homebrew-tap` run line is greater than the index of the `pypa/gh-action-pypi-publish` step;
  - `test_a_dry_run_reads_nothing_from_pypi_and_commits_nothing`: every step whose run line has `--source pypi`, `--online true` or `release homebrew-tap` carries `if: ${{ !inputs.dry_run }}`, and the `local`/`false` steps carry `if: ${{ inputs.dry_run }}`;
  - `test_the_tap_step_has_its_app_token`: the step before `release homebrew-tap` uses `actions/create-github-app-token@bcd2ba...` with `secrets.HOMEBREW_TAP_CLIENT_ID` and `secrets.HOMEBREW_TAP_APP_KEY`;
  - `test_no_aggregate_runs_homebrew`: no plan of `build all`, `test all` or `release all` contains a homebrew leaf;
  - `test_the_release_path_carries_no_test_archive_yet` keeps passing unchanged (no handoff).
  - The exact flag spelling (`--source pypi`) is what `_parameters` renders. Read it from the generated file before writing the assertion.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Edit `simplon.yaml`. Run `./simplon.sh support workflows` and the other generators `test generated` names.
- [ ] **Step 4:** Run `test_release_workflow.py`, `test_own_workflows.py`, `test_workflowgen.py`, `test_refusal_census.py` and the full suite. Then `git add -A` and `./simplon.sh test generated`. Expected: green except the three known `test_tasks_docs` failures. Rules 6 and 8 load the manifest, so a refusal there shows up at this step, and its message is the fix.
- [ ] **Step 5: Local rehearsal of the dry-run path,** on this host through the launcher. Run `./simplon.sh build wheel`, then `./simplon.sh build homebrew-formula --source local`, then `./simplon.sh test homebrew-formula --online false`. Expected: rc 0, and `build/homebrew/simplon.rb` has the placeholder URL and the resources. Record durations in the PR.
- [ ] **Step 6: Commit** `feat(si#537): simplon renders, audits and commits its Homebrew formula after PyPI`.

### Task 3: The docs

**Files:**
- Modify: `README.md` ("## Using it", 14-24): `brew install marcozwyssig/tap/simplon` beside `pip install simplon`, for macOS and Linux.
- Modify: `src/site/content/how/releasing.md`, in "The tag is what publishes" (208-232) and "The whole sequence" (305):
  - the formula steps;
  - the order after PyPI and why;
  - the dry-run difference (placeholder URL, `--strict` only);
  - the measured 4.5-minute brew image pull;
  - the two secrets and the GitHub App Marco creates (contents read/write on `homebrew-tap` only);
  - the rerun rule.
- Modify: `README.md` "## Releasing" (185-231): one line naming the tap.

- [ ] **Step 1:** Write the paragraphs. Every command named in them is checked against `./simplon.sh help`.
- [ ] **Step 2:** Run `./simplon.sh build docs`. Expected: rc 0. Run `test_site_counts.py` and the docs tests. Expected: no new failure.
- [ ] **Step 3: Commit** `docs(si#537): brew install marcozwyssig/tap/simplon, and how the formula is released`.

### Task 4: Acceptance

- [ ] **Step 1:** Open the PR with `Closes #537` and `Closes #449`, unless A and F are still open in #449. In that case write `Part of #449` and say what remains.
- [ ] **Step 2:** After merge, ask Marco before dispatching a dry run `v0.N.0` from `main`. Expected:
  - the formula is generated with its resources;
  - `brew audit --strict` and `brew style` are green;
  - the sha256 matches the local wheel;
  - no PyPI upload and no tap commit happen.
  - Read it with `gh run view --log`, not from the summary.
- [ ] **Step 3:** At the next real cut, check that the tap's `Formula/simplon.rb` is at the new version. On a clean machine (a `ghcr.io/homebrew/brew` container counts for Linux), run `brew install marcozwyssig/tap/simplon` and `simplon --help`. Record the result in #537.
