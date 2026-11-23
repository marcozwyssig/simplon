# si#860: variant keys on a command (cadence, platforms, python cells, time limit, emulation) - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CI leaf says under its `ci:` key when it runs (`cadence:`), on which hosted platforms (`platforms:`), under which extra Python versions (`python:`), how long it may take (`timeout_minutes:`) and which platforms it needs emulated (`emulates:`); `support github workflows` derives the matching workflows and jobs with no `workflows:` entry.

**Architecture:** `simplon.manifest.load` reads the new keys into a `CiVariant` value on `TaskCommand`. `simplon.tasks.cipipeline` partitions the selected leaves by cadence (one workflow per cadence), and inside each workflow puts a `platforms:` leaf in its own matrix job and adds a matrix job for a `python:` leaf beside its run in the main job. Platform cells are model instances (`workflow.firn`, generated into `simplon.model.workflowschema`) like the runner kinds of #857. Rendering stays `workflowgen`'s; cross-job artifacts go through the existing `handoff.plan`.

**Tech Stack:** Python 3.12+, pydantic (manifest load), firn model + templates (`./simplon.sh build model`), pytest, mypy.

**Spec:** `docs/superpowers/specs/2026-11-22-derived-workflows-design.md`, section 5.5 and section 7 step 6 (decision D8), plus the decisions below. Builds on the #858 plan `docs/superpowers/plans/2026-11-22-si858-derived-ci.md` and its code (`src/simplon/tasks/cipipeline.py`).

## Decisions this plan carries (Marco, 2026-11-23, two choice lists)

Measured first (8 reachable manifests and their hand-written workflow files, 2026-11-23):
- `{input:}`'s only user is biz-cockpit `publish.yml`, which dispatches the `release` aggregate (not a `ci build`/`ci test` leaf), with a default "tag ref, else the sha" a plain input cannot say. A derived CI leaf has no `params:` place.
- cleon `ci.yml` and asbundle `build-matrix.yml` carry the same five cells: `ubuntu-24.04` (x86_64), `ubuntu-24.04-arm` (aarch64), `macos-15-intel` (x86_64), `macos-15` (arm64), `windows-2025` (amd64, `shell: cmd`, entry `<product>.cmd`), an architecture assertion per cell, and a per-cell timeout as a cost cap. Both run only on a tag or by dispatch, never per push.
- agile-cockpit `systemtests-nightly.yml`: `cron: "17 2 * * *"` (off the full hour on purpose) plus dispatch, `timeout-minutes: 75`, `test report` and its upload after the gate, concurrency without cancel.
- Time limits written by hand today: netctl lab 95 min (#860 comment), agile-cockpit nightly 75, firn release 120/240. No manifest carries `ci:` on a command.

Decided:
1. **`{input:}` leaves #860** for spec step 8 (#862, release and pages without `workflows:`), where its one user stands. Spec 5.5 is corrected in Task 6.
2. **`platforms:` takes kernel cell names**: `linux-x64`, `linux-arm64`, `macos-x64`, `macos-arm64`, `windows-x64`. The kernel holds each cell's runner label, shell, launcher and expected architecture. An unknown name is refused with the list (diagnosis).
3. **`cadence:` takes `nightly`, `manual` or a cron string**: `nightly` -> `.github/workflows/ci-nightly.yml` (kernel cron `17 2 * * *`, plus dispatch); `manual` -> `.github/workflows/ci-manual.yml` (dispatch only); a cron string -> `.github/workflows/ci-scheduled.yml`, one main job per cron string. A leaf with no `cadence:` stays in `ci.yml`, per push.
4. **`ci: { timeout_minutes: N }`** on the leaf: a step's `timeout-minutes` in a shared job, the job's `timeout-minutes` in a leaf's own job (matrix); the same value for every cell.
5. **`python:` adds cells**: the leaf still runs in its main job, and once more per listed version in a matrix job on `github-ubuntu` with `setup-python`.
6. **`platforms:` replaces**: the leaf runs only in its cells, never in the main job (spec 5.2 "no double run").
7. **`emulates:` is built here** (`ci: { emulates: [linux/arm64] }`), so #863 can delete simplon's hand-written `suite-python-3-14`. A job holding such a leaf registers the emulation before its leaves (the `QEMU_ACTION` + `labhost.BINFMT_IMAGE` pair the release already uses); on a runner kind with `can_emulate = false` it registers nothing and the file names the gap (spec 5.4; routing is #722's).

My calls (no choice list; the executor posts them with the decisions in Task 0, Marco may overrule):
- `platforms:` and `python:` on one leaf are refused (a cross product nobody measured needs). `emulates:` on a `platforms:` leaf is refused (macOS and Windows cells have no binfmt). Both are expression rules with a measured cost of zero manifests; each reopens when a product asks.
- `skip:` beside any other `ci:` key is refused (diagnosis: the leaf does not run, so the other key does nothing).
- A cadence workflow is built like `ci.yml`: preparation steps, its leaves, the `after_all` leaves (the report) and the report upload, cleanup; `concurrency: { group: <file stem>, cancel-in-progress: false }`.
- A cell job carries no report: its result is its job's colour. The job note says so. (Reopens with #450's test results per cell.)

## Global Constraints

- Branch `si860-variant-keys` off `main` in a worktree. Every commit carries the identity env from the memory `git-identity-needs-env-per-commit`, message via `git commit -F-` with a quoted heredoc, subject `feat(si#860): ...` / `test(si#860): ...` / `docs(si#860): ...`, and the session's attribution lines.
- Tests: `deploy/orchestrator/.venv/bin/python -m pytest src/tests/<file> -q` (memory `running-the-suite-on-this-machine`; 3 `test_tasks_docs` failures are pre-existing). `./simplon.sh test typecheck-python` before every push. `test_wheel` fails inside a worktree (environment); run it in the main checkout.
- After any `.firn` / `.firnt` edit: `./simplon.sh build model`, commit the regenerated files with the change, then `./simplon.sh test generated`.
- Every new refusal gets a census entry in `src/tests/test_refusal_census.py` (kind and reach). Census fragments are literal message text: keep each fragment unique to its message.
- Literal keys only when reading a manifest section (`spec.ci`, `raw.get("cadence")`), never an imported constant (si#435).
- No em dash. English in code, docs, commits. PR body ends with the attribution block and `Closes #860`.
- No counts typed into prose; point at the test that computes them.

## Review Focus

1. **A python or platform cell leaf that consumes an artifact a main-job leaf produces.** Expected: the cell job gets `needs:` and a download through `handoff.plan`, or, if `handoff.plan` refuses a matrix consumer, the derivation refuses earlier naming both leaves. Never a cell that fails on a missing file. Test in Task 4.
2. **Every leaf of `ci build`/`ci test` carries a `cadence:`.** Expected: `ci.yml` has nothing to run and the existing `_nothing_to_run` refusal fires, now also naming the cadence workflows the leaves went to, so the product learns the push path verifies nothing. Test in Task 3.
3. **`python: [3.10]` written unquoted.** YAML reads `3.1`. Expected: refused, saying to quote it. Test in Task 2.
4. **A producer with `cadence: nightly` whose consumer has no cadence.** Expected: refused by `_refuse_consumers_of_absent_producers` with the cadence as the reason (the push run has no producer). Test in Task 3.
5. **Two leaves with the same cron string, and two with different ones.** Expected: same cron -> one job in `ci-scheduled.yml`; different -> one job each, each gated on its own `github.event.schedule`, both run on dispatch. Test in Task 3.

---

### Task 0: Post the decisions

**Files:** none in the repository.

- [ ] **Step 1:** Post on #860 (via `--body-file`): the measurement above, the seven decisions and my calls. Reply to Marco's netctl comment there: decision 4 answers it.
- [ ] **Step 2:** Comment on #862: `{input: <name>}` moved there from #860, with biz-cockpit's measured case (dispatches `release`, default tag-ref-else-sha) as its first user.

### Task 1: Platform cells and a step time limit in the model

**Files:**
- Modify: `src/firn/model/simplon/workflow/workflow.firn` (class `Platform`; `Step.timeout_minutes`)
- Modify: `src/firn/model/simplon/workflow/runners.firn` (five `Platform` instances)
- Regenerate: `src/simplon/model/workflowschema.py` (and whatever `build model` rewrites)
- Test: `src/tests/test_cipipeline.py`

**Interfaces:**
- Produces: `workflowschema.Platform(label: str, arch: str, shell: str, windows: bool)`; `workflowschema.PLATFORMS: Mapping[str, Platform]` keyed by cell name, generated the way `RUNNER_KINDS` is; `workflowschema.Step.timeout_minutes: int | None = None`.

- [ ] **Step 1: Failing test** `test_platform_cells_are_the_measured_five`: `PLATFORMS` keys are `linux-x64, linux-arm64, macos-x64, macos-arm64, windows-x64`; labels `ubuntu-24.04, ubuntu-24.04-arm, macos-15-intel, macos-15, windows-2025`; `arch` (what `uname -m` prints in bash) `x86_64, aarch64, x86_64, arm64, x86_64`; `shell` `bash` except `windows-x64` -> `cmd`; `windows` true only for `windows-x64`.
- [ ] **Step 2:** Run it; FAIL on the missing name.
- [ ] **Step 3:** Add `Platform` (attributes `label`, `arch`, `shell`: StringLiteral 1..1; `windows`: BooleanLiteral 1..1) and `Step.timeout_minutes` (IntegerLiteral 0..1) to `workflow.firn`; the five instances to `runners.firn`; extend the template that emits `RUNNER_KINDS` to emit `PLATFORMS`. `./simplon.sh build model`.
- [ ] **Step 4:** Test passes; `./simplon.sh test model` and `test generated` (after commit) green; simplon's rendered workflows unchanged (`./simplon.sh support github workflows --check`).
- [ ] **Step 5:** Commit.

### Task 2: The `ci:` keys on a command

**Files:**
- Modify: `src/simplon/model/command.py` (`CiVariant`, `TaskCommand.ci`)
- Modify: `src/simplon/manifest/load.py:1031-1072` (`_ci_skip` reads the known keys), `_command`
- Modify: `src/tests/test_refusal_census.py`
- Test: `src/tests/test_manifest_ci_keys.py` (new) or the file holding the #858 `_ci_skip` tests (`grep -l "_ci_skip\|ci: skip" src/tests`), whichever exists

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class CiVariant:
      cadence: str = ""                 # "", "nightly", "manual" or a five-field cron string
      platforms: tuple[str, ...] = ()   # keys of workflowschema.PLATFORMS, in the order written
      python: tuple[str, ...] = ()      # version strings, in the order written
      timeout_minutes: int | None = None
      emulates: tuple[str, ...] = ()    # buildx platform spelling, e.g. "linux/arm64"
  ```
  `TaskCommand.ci: CiVariant = CiVariant()` beside `ci_skip` (which stays).
- `_ci_skip(spec, where, ci_leaf) -> str` keeps its name and census entries; a new `_ci_variant(spec, where) -> CiVariant` reads the rest, called only after `_ci_skip` accepted the key.

Refusals (fragment, kind):
- unknown key: the existing message lists every key read now (`skip, cadence, platforms, python, timeout_minutes, emulates`): DIAGNOSIS, census fragment updated.
- `skip:` beside another key, "the leaf does not run in CI, so": DIAGNOSIS.
- `cadence:` not `nightly`/`manual` and not five whitespace-separated fields: DIAGNOSIS.
- `platforms:` empty, a duplicate, or a name not in `PLATFORMS` (message lists them): DIAGNOSIS.
- `python:` empty, a duplicate, or a non-string entry ("3.10 unquoted reads as 3.1: quote the version"): DIAGNOSIS.
- `timeout_minutes:` not a positive int (bool refused): DIAGNOSIS.
- `emulates:` not a non-empty list of `<os>/<arch>[/<variant>]`: DIAGNOSIS; reuse `workflowgen._emulates`'s pattern, one source for the spelling.
- `platforms:` with `python:`: EXPRESSION; `platforms:` with `emulates:`: EXPRESSION (my calls above; census docstring records cost zero over the eight manifests and the reopening trigger).

- [ ] **Step 1: Failing tests**, one per behaviour: each key parsed into `CiVariant` (`ci: { cadence: nightly, python: ["3.14"], timeout_minutes: 30, emulates: [linux/arm64] }` -> exactly those values); `python: [3.10]` refused with "quote"; `platforms: [linux-x64, solaris]` refused naming `solaris` and listing the five; `skip` + `cadence` refused; `platforms` + `python` refused; `cadence: "17 2 * *"` (four fields) refused; `timeout_minutes: true` refused; a command with no `ci:` has `CiVariant()`.
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** Implement `CiVariant`, `_ci_variant`, the widened key set in `_ci_skip`; pass `ci=` in `_command` for a `TaskCommand` only (a `Deploy` and an aggregate are already refused by `_ci_skip`).
- [ ] **Step 4:** Tests pass; `test_refusal_census.py` green with the new entries (see each one red first by deleting its entry).
- [ ] **Step 5:** Commit.

### Task 3: One workflow per cadence

**Files:**
- Modify: `src/simplon/tasks/cipipeline.py` (`select`, `derive`, `to_workflow`, `workflows`)
- Test: `src/tests/test_cipipeline.py`

**Interfaces:**
- Consumes: `TaskCommand.ci.cadence` (Task 2).
- Produces:
  - `NIGHTLY_CRON = "17 2 * * *"`; `CADENCE_PATHS = {"": ".github/workflows/ci.yml", "nightly": ".github/workflows/ci-nightly.yml", "manual": ".github/workflows/ci-manual.yml"}`, every cron string -> `.github/workflows/ci-scheduled.yml`; workflow keys (`title`) `ci`, `ci-nightly`, `ci-manual`, `ci-scheduled`.
  - `derive_all(manifest, data) -> tuple[Derivation, ...]`: `ci.yml` first, then nightly, manual, scheduled, each only when it has a leaf. `derive(manifest, data)` stays as the push workflow's derivation (callers and tests of #858 keep working).
  - Triggers: push workflow unchanged; nightly `schedule` (cron `NIGHTLY_CRON`) + `dispatch`; manual `dispatch`; scheduled one `schedule` trigger per distinct cron + `dispatch`. Add `"schedule"` to `_TRIGGERS` rendering `{"schedule": [{"cron": c}, ...]}`.
  - In `ci-scheduled.yml` one main job per distinct cron, key `ci-1`, `ci-2` in first-written order, each `if: ${{ github.event_name == 'workflow_dispatch' || github.event.schedule == '<cron>' }}`.

- [ ] **Step 1: Failing tests:** `test_nightly_leaf_leaves_the_push_workflow` (a `cadence: nightly` leaf is absent from `ci.yml` and present in `ci-nightly.yml`, whose `on:` is `schedule: [{cron: "17 2 * * *"}]` plus `workflow_dispatch`); `test_manual_cadence_is_dispatch_only`; `test_cron_strings_share_one_file_one_job_each` (Review Focus 5); `test_cadence_workflow_carries_the_report_last` (an `after_all` leaf and the report upload in the cadence job too); `test_cadence_workflow_does_not_cancel_in_progress`; `test_consumer_of_a_nightly_producer_is_refused` (Review Focus 4: the message names the producer and "cadence: nightly"); `test_all_leaves_scheduled_refuses_the_push_workflow` (Review Focus 2: message names `ci-nightly.yml`); `test_skipped_and_cadence_notes` (the push file's "Left out" lists a cadence leaf with "runs in ci-nightly.yml").
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** Implement. Partition in `select` (a `Selection` per cadence key, or a `cadence` field on `Leaf`: builder's call, the tests fix the behaviour); the absent-producer check runs per workflow; `_derived_note` names the cadence. `workflows()` appends every derivation of `derive_all` and keeps `_reject_duplicate_paths` over all of them.
- [ ] **Step 4:** Tests pass; simplon's `support github workflows --check` unchanged (no leaf of simplon's has a cadence).
- [ ] **Step 5:** Commit.

### Task 4: Cell jobs for `python:` and `platforms:`

**Files:**
- Modify: `src/simplon/tasks/cipipeline.py`
- Modify (only if needed): `src/simplon/tasks/workflowgen.py` (a job's `defaults: run: shell:` and a per-cell launcher in the step line)
- Test: `src/tests/test_cipipeline.py`

**Interfaces:**
- Consumes: `CiVariant.python`, `CiVariant.platforms` (Task 2); `workflowschema.PLATFORMS`, `Matrix` (Task 1).
- Produces: per leaf with cells, one job in the leaf's cadence workflow, key `<leaf words, spaces as ->-python` or `-platforms` (e.g. `test-suite-python`); model `Job(matrix=Matrix(python=...) | Matrix(platform=...))`.
  - python job: runner `github-ubuntu` (always; decision 5), `strategy: { fail-fast: false, matrix: { python: [...] } }`, `setup-python` with `${{ matrix.python }}`, checkout, the one leaf. The leaf also stays in the main job.
  - platforms job: `strategy: { fail-fast: false, matrix: { include: [{cell, os, arch, shell, entry}, ...] } }` from `PLATFORMS`, `runs-on: ${{ matrix.os }}`, `defaults: run: shell: ${{ matrix.shell }}`, checkout, an architecture assertion step (`shell: bash`, `uname -m` against `${{ matrix.arch }}`, `::error::` and exit 1 on mismatch; measured reason: a cell that silently runs the wrong architecture looks complete), then the leaf as `${{ matrix.entry }} <words>` where `entry` is `./<product>.sh` or `<product>.cmd` for `windows`. The leaf is not in the main job.
  - Cross-job artifacts: build the `handoff.Run` list over every job of the workflow and let `handoff.plan` add `needs:`/upload/download.

- [ ] **Step 1: Failing tests:** `test_python_cells_add_a_job_and_keep_the_main_run`; `test_python_cell_runs_on_github_ubuntu_under_a_self_hosted_runner`; `test_platform_cells_replace_the_main_run`; `test_windows_cell_runs_the_cmd_launcher` (`include` row for `windows-x64` has `shell: cmd`, `entry: <product>.cmd`); `test_platform_job_asserts_the_architecture`; `test_cell_consumer_of_a_main_job_artifact` (Review Focus 1: either `needs: [ci]` and a download step in the cell job, or a refusal naming both leaves; first measure what `handoff.plan` does with a matrix consumer and record the answer in the test's docstring).
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** Implement. `to_workflow` handles more than one job (today it unpacks `(job,) =`). A cell job gets no preparation steps beyond checkout (a hosted machine: no disk preflight, no docker probe, as `workflowgen._disk_steps` already decides for `github-ubuntu`) and `support install` when the product declares `toolchains:`. The job note says a cell carries no report and the result is the job's colour.
- [ ] **Step 4:** Tests pass. Render a scratch manifest with each variant and run `actionlint` through the launcher if a member exists (`./simplon.sh help | grep -i lint`); otherwise parse the rendered YAML and assert the GitHub keys by hand in the tests.
- [ ] **Step 5:** Commit.

### Task 5: `timeout_minutes:` and `emulates:`

**Files:**
- Modify: `src/simplon/tasks/cipipeline.py`
- Test: `src/tests/test_cipipeline.py`

**Interfaces:**
- Consumes: `CiVariant.timeout_minutes`, `CiVariant.emulates`; `workflowgen.QEMU_ACTION`, `labhost.BINFMT_IMAGE`; `RunnerKind.can_emulate`.
- Produces: kernel step name `EMULATION = "emulation"`, step id `prepare_emulation` added to `PREPARE`, so leaves after it are gated on it like the other preparation steps.

- [ ] **Step 1: Failing tests:** `test_timeout_is_a_step_limit_in_a_shared_job` (`timeout-minutes: 95` on the leaf's step in `ci`); `test_timeout_is_the_job_limit_in_a_cell_job`; `test_emulation_registered_once_before_the_leaves` (two leaves with `emulates: [linux/arm64]` and `[linux/arm64, linux/arm/v7]` -> one step, platforms `linux/arm64,linux/arm/v7` in first-written order, `image: <BINFMT_IMAGE>`, after the preparation steps, before the first leaf); `test_emulation_in_the_python_cell_job` (the cell job of an `emulates:` leaf registers it too: that is simplon's `suite-python-3-14`); `test_no_emulation_on_a_kind_that_cannot` (`runner: { kind: self-hosted-container, ... }` if #722's kind exists on main, else a kind table patched in the test: no step, and the job note names the gap and #722).
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** Implement: `Step.timeout_minutes` in the model, written as `timeout-minutes` by `to_workflow`; the emulation step derived from the leaves of each job.
- [ ] **Step 4:** Tests pass; `./simplon.sh test typecheck-python` green.
- [ ] **Step 5:** Commit.

### Task 6: Docs and the spec's corrections

**Files:**
- Modify: `docs/superpowers/specs/2026-11-22-derived-workflows-design.md` (5.5, section 7 step 6, section 8 rows for dispatch input and Python cell), each change tagged `(corrected 2026-11-23, #860)` as #858 did
- Modify: the manifest reference page that documents `ci: { skip: }` (`grep -rln "ci: { skip" docs/ site/ src/simplon` to find it) for the new keys, with the cell table generated or pointed at, not typed
- Regenerate: `with-what/rules.md` (census page) through its build member

- [ ] **Step 1:** Spec: `{input:}` moves to step 8 (#862) with the measurement; cadence file names; platform cell names; `timeout_minutes:` and `emulates:` under `ci:`; the two expression rules with their reopening trigger (spec section 10 format).
- [ ] **Step 2:** Manifest docs for the five keys; one example per key.
- [ ] **Step 3:** Regenerate the census page; `./simplon.sh test suite` green apart from the known three.
- [ ] **Step 4:** Commit, push, open the PR (`Closes #860`), body lists the decisions and the measurement.

## Self-review notes

- Spec 5.5 D8 items: cadence (Task 3), platforms (Tasks 1, 4), python (Task 4), `{input:}` (moved, Tasks 0 and 6), `emulates:` on the command (Task 5), Marco's timeout comment (Task 5). `gate:`, `sources:`, `merge: auto` are #861.
- Not covered on purpose: a real run on hosted macOS/Windows cells. Unmeasured here (this host is x86_64 Linux, and a hosted run costs). The first product migration that writes `platforms:` (cleon or asbundle) is that measurement; the PR body says so.
