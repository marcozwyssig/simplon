# si#863: Migrate simplon to derived workflows - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** simplon's `ci.yml` is derived by the kernel from its command tree; `workflows:` keeps only the release workflow (until #862/#789) and the hand-off canary.

**Architecture:** Delete `workflows.ci` from `simplon.yaml`. What its jobs said moves to data the kernel already reads (si#858, si#860): a top-level `runner:`, `ci: { python:, emulates: }` on two leaves, `ci: { skip: }` on the canary leaves. The canary keeps its job boundary as its own declared workflow `handoff-canary.yml` (spec 5.3a) until #864 gives it `exception:`. The tests that read `workflows.ci` out of the manifest read the workflows the verb assembles instead.

**Tech Stack:** Python 3.12, pytest, PyYAML, GitHub Actions; generation through `./simplon.sh support github workflows`.

**Spec:** `docs/superpowers/specs/2026-11-22-derived-workflows-design.md` (D1, D11, D12, D13, sections 5.3a, 5.4, 5.5, 7 step 9). Ticket: si#863.

## Global Constraints

- Generated files are regenerated through the launcher (`./simplon.sh support github workflows`), never edited by hand; the regenerated file is committed with the manifest change that caused it.
- `workflows.release` stays whole: docs and pages derivation is #862 (L2, open), release promotion is #789. Spec 7 step 9's "delete `workflows:` except the Exceptions" is only reachable for `ci` today. (Measured 2026-11-25: #862 OPEN.)
- `exception:` does not exist before #864. The canary workflow is a plain declared workflow until then.
- No branch protection on `main` (measured 2026-11-25: "Branch not protected", no rulesets), so renamed jobs block no merge.
- Suite command: `deploy/orchestrator/.venv/bin/python -m pytest -q --no-header -p no:cacheprovider <paths>` (`-n` is not installed).
- No em dash; no counts typed into prose; English artefacts.
- Commit identity per commit through env (Marco Zwyssig), `git commit -F-` with a quoted heredoc, trailers `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG`.

## Measured before writing (2026-11-25, worktree si863 off b1ef7b9)

- `workflows.ci` deleted, nothing else: the derived `ci.yml` runs every unattended leaf in one job `ci` **on `ubuntu-latest`**, the canary's writer and reader in that same job, no 3.14 run. Left out: `test walk` only.
- With the candidate keys of Task 2 (diff saved at `/tmp/claude-0/-root-git-simplon/f6f1f3c0-cc0f-4e52-8c5d-8780bc7b8fe4/scratchpad/si863-candidate.diff`): `ci` on `ghr-8` with docker and disk preflight, a QEMU registration step in the main job (new on ghr-8), and two hosted cell jobs `test-suite-python` and `test-typecheck-python-python`.
- Full suite over that candidate: the only failures are in tests that read simplon's own workflows: `test_own_workflows.py`, `test_own_image.py` (`KeyError: 'ci'`), `test_type_gate.py::test_everyWorkflowThatVerifiesThisTreeAlsoRunsTheGate`, `test_workflow_handoff.py::test_simplons_own_ci_renders_byte_identical_and_hands_over_only_the_canary`.
- `test_own_workflows._declared()` uses `workflowgen.parse` (declared entries only), while the verb uses `cipipeline.workflows(..., read=automerge.read_handwritten ...)`. So the gate called the derived `ci.yml` "named by nothing". Test defect, not kernel defect: the verb itself reported nothing unmanaged.

## Review Focus

- The derived `ci.yml` on a fresh checkout of ghr-8 where `docker` is reached only through the bootstrap: the main job must stay on `ghr-8`, not `ubuntu-latest` (Task 2 test asserts `runs-on`).
- The canary file and `ci.yml` both naming `build handoff-canary`: the canary must run exactly once per push, in its own workflow, and not in `ci.yml` (Task 2 asserts both).
- A future edit that drops `python:` from `test typecheck-python` but keeps it on `test suite`: the type gate rule must still go red (Task 3 sees it red).
- `support github workflows --check` and `test generated` must both know `handoff-canary.yml` (Task 2 adds the `generated:` entry and asserts it).
- The 3.14 cell registering QEMU before the suite: the arm64 e2e must not turn into "Exec format error" (PR #557) on the hosted cell (Task 2 asserts the order in the cell job).

---

### Task 1: The own-workflow gate reads what the verb assembles

**Files:**
- Modify: `src/simplon/tasks/workflows.py` (extract the assembly the verb does inline)
- Modify: `src/tests/test_own_workflows.py` (`_declared`, `_report`)
- Test: `src/tests/test_own_workflows.py`

**Interfaces:**
- Produces: `simplon.tasks.workflows.assemble(manifest, data: Mapping, *, product: str, root: Path) -> tuple[workflowgen.Workflow, ...]`, the exact call the verb makes today (`cipipeline.workflows(manifest, data, product=..., read=lambda workflow, role: automerge.read_handwritten(workflow, role, root=root))`). The verb calls it; nothing else changes in the verb.
- `_declared()` in `test_own_workflows.py` returns `workflows.assemble(_loaded(), <yaml data>, product=PRODUCT, root=ROOT)`.

- [ ] **Step 1: Write the failing test** `test_the_gate_assembles_the_workflows_the_verb_writes` in `test_own_workflows.py`: load simplon.yaml, delete `data["workflows"]["ci"]`, and assert that `ci.yml` is among the paths of `workflows.assemble(manifest_mod.load(yaml.safe_dump(data), catalogue=...), data, product=PRODUCT, root=ROOT)` and that `workflowgen.unmanaged(<that tuple>, ROOT) == ()`.
- [ ] **Step 2:** Run it; expect FAIL (`AttributeError: ... has no attribute 'assemble'`).
- [ ] **Step 3:** Implement `assemble`; make the verb and `_declared()` call it. Every existing test in the file keeps passing on main's manifest (it still declares `workflows.ci`).
- [ ] **Step 4:** Run `src/tests/test_own_workflows.py src/tests/test_workflows*.py`; expect PASS.
- [ ] **Step 5:** Commit: `fix(si#863): the own-workflow gate assembles the workflows the verb writes, derived ones included`.

### Task 2: Delete `workflows.ci`; the leaves and the canary carry what it said

**Files:**
- Modify: `simplon.yaml` (top-level `runner:`; `ci:` keys on `test suite`, `test typecheck-python`, both `handoff-canary` commands; `workflows.handoff-canary`; delete `workflows.ci`; `generated:` entry)
- Regenerate: `.github/workflows/ci.yml`, create `.github/workflows/handoff-canary.yml`
- Modify: `src/tests/test_own_workflows.py`, `src/tests/test_own_image.py`, `src/tests/test_workflow_handoff.py`

**Interfaces:**
- Consumes: `workflows.assemble` (Task 1).
- Produces: workflow keys `ci` (derived, job `ci`, cell jobs `test-suite-python`, `test-typecheck-python-python`) and `handoff-canary` (declared, jobs `handoff-canary-write`, `handoff-canary-check`). Task 3 reads the cell jobs.

The manifest edit, exactly (the candidate diff in the scratchpad, with these reasons):

- `runner: { kind: self-hosted-debian, labels: ghr-8 }` at top level, directly above `ci:`, with a comment carrying the reason `self-build`'s note gave (si#3: version from the git tag, so the job runs where the launcher provisions itself; full history is the kernel's own emission now).
- `suite: { task: suite, ci: { python: ["3.14"], emulates: [linux/arm64] } }`, comment: the formula's interpreter (si#537) and the arm64 e2e of `test:file` (si#552, PR #557).
- `typecheck-python: { task: "test:typecheck-python", ci: { python: ["3.14"] } }`, comment: si#8, the interpreter that runs the suite owes the type verdict.
- Both canary commands get `ci: { skip: "runs across a job boundary in handoff-canary.yml (si#639, spec 5.3a); one job would prove nothing" }`.
- `workflows.handoff-canary` with the two jobs and notes moved verbatim from `workflows.ci.jobs.handoff-canary-write/-check`, plus a `note:` naming #864 as the ticket that turns it into an `exception:`.
- `generated:` gains `canary-workflow: { path: .github/workflows/handoff-canary.yml, by: support github workflows }` beside `ci-workflow`.
- The `workflows.ci` block is deleted with its notes; a note whose reason is not restated by the kernel's generated prose or by a comment above goes into the comment of the leaf it argues for. The prose-gate-last ordering note is dropped: spec 5.2 item 1 replaced it with manifest order.

- [ ] **Step 1: Rewrite the failing tests first**, against the assembled workflows (Task 1), not `data["workflows"]["ci"]`:
  - `test_both_workflows_are_generated` -> `test_every_workflow_is_generated`: the generated paths are `{ci.yml, handoff-canary.yml, release.yml}`.
  - `test_the_generated_workflow_carries_the_prose_it_was_written_with`: asserts a note of `handoff-canary.yml` (`"The job hand-off canary (si#639)"`) and the `skip` reason in `ci.yml`.
  - `test_this_repository_runs_a_subset_of_those_and_the_difference_is_a_choice_not_a_defect` -> `test_ci_runs_every_unattended_leaf_but_the_canary`: the commands of job `ci` equal the derived leaves minus `build handoff-canary` and `test handoff-canary`, and `ci.yml` names both under "Left out" with the skip reason.
  - `test_ci_runs_the_suite_on_the_formulas_python`: job `test-suite-python` has `python-version` matrix `["3.14"]` and `runs-on: ubuntu-latest`.
  - `test_the_hosted_suite_job_can_run_linux_arm64_before_the_suite`: in `test-suite-python`, the `docker/setup-qemu-action` step with `image: <labhost.BINFMT_IMAGE>` precedes `./simplon.sh test suite`.
  - `test_the_handoff_canary_crosses_a_job_boundary_in_ci` -> `..._in_its_own_workflow`: `handoff-canary.yml` has the two jobs, the reader `needs:` the writer, and `ci.yml` runs neither command.
  - `test_simplon_without_its_ci_entry_derives_every_leaf_report_last`: now simplon itself has no `ci` entry; assert on the committed manifest directly, report last.
  - New: `test_ci_runs_on_ghr8`: job `ci` has `runs-on: ghr-8`.
  - `test_own_image.py` (`KeyError: 'ci'`) and `test_workflow_handoff.py::test_simplons_own_ci_renders_byte_identical_and_hands_over_only_the_canary`: read `ci.yml`/`handoff-canary.yml` from the assembled workflows; the hand-off assertion moves to `handoff-canary.yml`.
- [ ] **Step 2:** Run those files; expect the rewritten tests FAIL (manifest still declares `workflows.ci`).
- [ ] **Step 3:** Make the manifest edit above; run `./simplon.sh support github workflows`; expect "regenerated ... ci.yml, handoff-canary.yml".
- [ ] **Step 4:** Run `./simplon.sh support github workflows --check` (all agree, nothing unmanaged) and `./simplon.sh test generated`; then the full suite. Expected: only `test_type_gate.py::test_everyWorkflowThatVerifiesThisTreeAlsoRunsTheGate` red (Task 3's).
- [ ] **Step 5:** Commit manifest, both workflow files and tests: `feat(si#863): simplon's ci.yml is derived; the canary keeps its job boundary in a workflow of its own`. The suite is red on one known test between this commit and Task 3's; say so in the commit body.

### Task 3: The type gate is owed per interpreter, not per job

**Files:**
- Modify: `src/tests/test_type_gate.py` (`_jobs`, `test_everyWorkflowThatVerifiesThisTreeAlsoRunsTheGate`)

si#8's rule is "whichever workflow claims to have checked this tree owes the same verdict". Derived cells put each leaf in its own job (`<command words>-python`), so "same job" no longer holds for a hosted interpreter. Ruling: a job that runs the suite on interpreter V is gated when the same job reaches the gate, **or** the same workflow has a job that runs the gate on V. V is the job's `python-version` matrix value(s), or "the runner's own" for a job without `setup-python`.

- [ ] **Step 1:** Rewrite the test with that rule; keep its failure message's way out.
- [ ] **Step 2: See it red:** delete `ci: { python: ["3.14"] }` from `typecheck-python` in a scratch copy of the manifest (assemble from the edited data, not the file on disk); expect the test to name `ci.yml:test-suite-python`. Keep that as a second test, `test_a_suite_cell_without_its_type_gate_cell_is_red`.
- [ ] **Step 3:** Full suite; expect PASS except the root-bound `test_tasks_docs` failures the memory names (none appeared in the 2026-11-25 run).
- [ ] **Step 4:** Commit: `fix(si#863): the type gate is owed per interpreter a workflow runs the suite on`.

### Task 4: Measure the D13 leaves on ghr-8 (needs Marco's go to push)

D13: `build reference`, `build acceptance`, `build site`, `build model`, `build homebrew-formula`, `test image`, `test homebrew-formula` now run on every push. Measured on the real runner, not here.

- [ ] **Step 1:** Push the branch and open the PR (Marco's word). The PR run is the measurement.
- [ ] **Step 2:** Read each step's duration and conclusion of job `ci`: `gh run view <id> -R marcozwyssig/simplon --json jobs --jq '.jobs[] | select(.name=="ci") | .steps[] | [.name,.conclusion,.startedAt,.completedAt] | @tsv'`. Compare the job total with main's `self-build` (`gh run list --branch main --workflow ci --limit 3`, measured 2026-11-25: 15m32s for the whole run).
- [ ] **Step 3:** Post a table on #863 (leaf, duration, verdict) and propose, per leaf, keep or `ci: { skip: "<measured reason>" }` as a choice list to Marco. A skip lands as its own commit with the regenerated `ci.yml`.

## Decisions (Marco, 2026-11-25, by choice list)

1. **QEMU on ghr-8: yes.** `emulates: [linux/arm64]` stays on `test suite`; the main job on ghr-8 registers arm64 emulation too and runs the arm64 e2e there. No kernel change.
2. **Canary: its own declared workflow** `handoff-canary.yml` until #864 adds `exception:`.
3. **Execution: subagent-driven.**
