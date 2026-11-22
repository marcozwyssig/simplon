# si#857 Workflow vocabulary as a firn model: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Workflow, Job, Step, Matrix, Trigger, Runner, RunnerKind and WorkflowException exist as classes of a firn metamodel; the runner kinds are model instances; a firn template generates the Python the kernel uses, and `simplon.manifest.runners.TABLE` is built from it.

**Architecture:** A new metamodel package `simplon.workflow` beside `simplon.pipeline`, plus a file of RunnerKind instances. A new whole-module template `WorkflowSchema` writes `src/simplon/model/workflowschema.py`: the runner kinds as data and one frozen dataclass per metamodel class, its fields read reflectively off the class's properties (the way `taskkeys.firnt` reads `CatalogueTask`'s). `runners.py` loses its hand-typed table and builds it from the generated data. Nothing renders differently: simplon's workflows stay byte-identical.

**Tech Stack:** firn (pinned image, through `./simplon.sh build model` / `test model`), Python 3, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-derived-workflows-design.md`, section 4 and decision D5. Ticket #857.

## Global Constraints

- Every command goes through the launcher: `./simplon.sh build model` (regenerate), `./simplon.sh test model` (firn validate), `./simplon.sh test generated` (staleness), `./simplon.sh test suite` (full suite; run it, CI's PYTHONPATH differs from a bare pytest, #846).
- Generated files are regenerated, never hand-edited, and committed with the change that caused them.
- English in code, comments, commits; never the em dash (U+2014).
- A firn name has no `-`: model names use `_`, the kernel's spelling uses `-` (`self_hosted_debian` -> `self-hosted-debian`), as `kinds.firn` already does.
- The runner kinds are exactly today's two, `github-ubuntu` and `self-hosted-debian`, with today's values. `self-hosted-container` is #722, not this plan.
- simplon's `.github/workflows/ci.yml` and `release.yml` must be byte-identical before and after: `./simplon.sh support github workflows --check` green with no regeneration.
- Commits set `GIT_AUTHOR_*`/`GIT_COMMITTER_*` on the command (git config is blocked on this machine).

## Review Focus

1. **A selector that answers nothing.** firn writes a module with an empty `RUNNER_KINDS` (or no dataclasses) and exits 0. Expected: the suite is red, not every runner lookup failing later. Pinned in Task 2 (`test_runner_kinds_are_exactly_the_two_measured_kinds`, `test_every_metamodel_class_has_a_generated_dataclass`).
2. **Prose with quotes and backticks in `why`.** The generated Python string must hold the text exactly. Pinned in Task 2 by comparing every `why` against the literal expected text.
3. **Order of `env` and `labels`.** A dict or tuple generated in a different order renders a different workflow. Pinned in Task 3 by `support github workflows --check` and the existing golden `src/tests/fixtures/workflows/release.golden.yml`.
4. **An empty label list** (`self-hosted-debian`). Must stay `()`, so `runners.resolve` keeps refusing a self-hosted job without product labels. Pinned in Task 3 by the existing `src/tests/test_runners.py`.
5. **firn keeping a stale file** (W300/W301) after a template rename. `build model` already refuses it; Task 2 step 6 states the expected clean output.

---

### Task 1: The metamodel and the runner kinds as instances

**Files:**
- Create: `src/firn/model/simplon/workflow/workflow.firn` (package `simplon.workflow`, the classes)
- Create: `src/firn/model/simplon/workflow/runners.firn` (package `simplon.workflow.runners`, the two RunnerKind instances)

**Interfaces:**
- Produces: the classes below, by these exact names, for Task 2's template. Property names are camelCase in the model; the generated Python turns them into snake_case.

| Class | Properties (kind, range, cardinality) |
|---|---|
| `RunnerKind` (allowRoot) | `labels` Attribute StringLiteral 0..N; `setupPython` Attribute BooleanLiteral 1..1; `diskPersists` Attribute BooleanLiteral 1..1; `canEmulate` Attribute BooleanLiteral 1..1; `why` Attribute StringLiteral 1..1; `env` Composition `RunnerEnv` 0..N |
| `RunnerEnv` | `envName` Attribute StringLiteral 1..1; `envValue` Attribute StringLiteral 1..1 |
| `Runner` | `kind` Association `RunnerKind` 1..1; `labels` Attribute StringLiteral 0..N |
| `Trigger` | `event` Attribute StringLiteral 1..1 (one of `pull_request`, `push_main`, `dispatch`, `schedule`); `cron` Attribute StringLiteral 0..1; `input` Attribute StringLiteral 0..N |
| `Matrix` | `platform` Attribute StringLiteral 0..N; `python` Attribute StringLiteral 0..N |
| `Step` | `command` Association `simplon.pipeline.TaskCommand` 0..1; `kernelStep` Attribute StringLiteral 0..1 |
| `Job` | `runner` Composition `Runner` 1..1; `step` Composition `Step` 1..N; `needs` Association `Job` 0..N; `matrix` Composition `Matrix` 0..1; `condition` Attribute StringLiteral 0..1 |
| `Workflow` (allowRoot) | `path` Attribute StringLiteral 1..1; `title` Attribute StringLiteral 1..1; `trigger` Composition `Trigger` 0..N; `job` Composition `Job` 1..N |
| `WorkflowException` (allowRoot) | `path` Attribute StringLiteral 1..1; `reason` Attribute StringLiteral 1..1 |

Deviations from the spec's section 4 list, on purpose: `Workflow.title` instead of `name` (every firn resource already has a `name`); no `permissions`/`concurrency` on `Workflow`, because both are kernel constants today (si#719) and nothing would read them from the model yet. `event` is a string rather than an enum so the template needs no enum handling; the four values go in the class comment. If the pinned firn offers an integer literal, `Job` also gets `timeoutMinutes` (0..1); if not, leave it out and say so in the commit message (si#720's default stays in workflowgen).

Instances, in `runners.firn`, values copied from `src/simplon/manifest/runners.py` `TABLE` exactly (the `why` strings character for character; the long comment above `TABLE` moves here as firn comments):
- `github_ubuntu`: labels `"ubuntu-latest"`, setupPython true, diskPersists false, canEmulate true, no env.
- `self_hosted_debian`: no labels, setupPython false, diskPersists true, canEmulate true, env `DELIVERY_DOCKER_BOOTSTRAP` = `"1"`.

- [ ] **Step 1: Write the two files.** Follow `pipeline.firn`'s form: every Association/Composition carries `objectCardinality`; reuse `firn.core.NamedResource` as the base.
- [ ] **Step 2: Validate.** Run `./simplon.sh test model`. Expected: green.
- [ ] **Step 3: See it red.** Point `Job.step`'s range at a misspelt class (`simplon.workflow.Stepp`), run `./simplon.sh test model`, expect a firn model error naming it. Revert.
- [ ] **Step 4: Measure the template reach** before Task 2 builds on it. In a throwaway template, print for `firn.core.Class`[.fullName() == "simplon.workflow.Job"] each property's `name`, its kind (Attribute/Composition/Association), its range's name and its `objectCardinality`/`subjectCardinality`. Run `./simplon.sh build model`, read the output, delete the throwaway. Record what firn answers in the commit message. **If firn cannot answer range or cardinality in a template, stop here and report to the maintainer.** Do not hand-type the dataclass fields: D5 requires them generated.
- [ ] **Step 5: Commit** both model files: `feat(si#857): workflow vocabulary and runner kinds in the firn model`.

### Task 2: The WorkflowSchema template and its generated module

**Files:**
- Create: `src/firn/templates/workflowschema.firnt` (template `WorkflowSchema`, file `model/workflowschema.py`, whole module, no protected region)
- Modify: `src/firn.toml`, `[target.simplon].templates`, append `"WorkflowSchema"`
- Modify: `src/firn/model/simplon/components/components.firn`, add `module m_model_workflowschema` with `path = "model.workflowschema"` to the `model` component
- Generated: `src/simplon/model/workflowschema.py`, `src/tests/generated/architecture.py`
- Test: `src/tests/test_generated_workflowschema.py`

**Interfaces:**
- Consumes: Task 1's classes and instances.
- Produces, in `simplon.model.workflowschema`:
  - `class RunnerKindData(NamedTuple)`: `labels: tuple[str, ...]`, `setup_python: bool`, `disk_persists: bool`, `can_emulate: bool`, `why: str`, `env: tuple[tuple[str, str], ...]` (pairs, model order).
  - `RUNNER_KINDS: dict[str, RunnerKindData]`, keyed by the kernel spelling (`github-ubuntu`, `self-hosted-debian`), in model order.
  - One `@dataclass(frozen=True)` per metamodel class of `simplon.workflow`, same class name. Field per property, snake_case, by this mapping: StringLiteral/BooleanLiteral 1..1 -> `str` / `bool` (no default); 0..1 -> `str = ""`; 0..N -> `tuple[str, ...] = ()`; Association/Composition to X 1..1 -> `"X"`; 0..1 -> `"X | None" = None`; 1..N or 0..N -> `tuple["X", ...] = ()`. A range outside `simplon.workflow` (Step.command -> TaskCommand) is typed `object`. Fields without a default come first, in model order, then the defaulted ones in model order.

- [ ] **Step 1: Write the failing tests** in `src/tests/test_generated_workflowschema.py` (AAA, names state the behaviour):
  - `test_runner_kinds_are_exactly_the_two_measured_kinds`: `tuple(workflowschema.RUNNER_KINDS) == ("github-ubuntu", "self-hosted-debian")`.
  - `test_each_runner_kind_carries_todays_values`: for each kind, `RUNNER_KINDS[k]` equals a literal `RunnerKindData(...)` written in the test with today's values from `runners.TABLE` (the `why` strings copied character for character; `env=(("DELIVERY_DOCKER_BOOTSTRAP", "1"),)` for `self-hosted-debian`, `()` for `github-ubuntu`; `can_emulate=True` for both). Literal, not `runners.TABLE`, so the test still means something after Task 3.
  - `test_every_metamodel_class_has_a_generated_dataclass`: the class names found by `re.findall(r"^(\w+) typeOf firn\.core\.Class", workflow.firn, re.M)` (assert non-empty) equal the frozen dataclasses defined in the module.
  - `test_job_fields_follow_the_model`: `[f.name for f in dataclasses.fields(workflowschema.Job)] == ["runner", "step", "needs", "matrix", "condition"]` (plus `timeout_minutes` last if Task 1 added it); `Job.__dataclass_params__.frozen` is true.
- [ ] **Step 2: Run** `./simplon.sh test suite` (or pytest on the file through the launcher's venv). Expected: FAIL, `ModuleNotFoundError: simplon.model.workflowschema`.
- [ ] **Step 3: Write the template** by the mapping above, using `taskkeys.firnt`'s reflective selector form for the dataclass fields and `schema.firnt`'s instance loop for `RUNNER_KINDS`. Header comment as in `schema.firnt`: generated from which model files, by `./simplon.sh build model`, do not edit, how to restore if empty.
- [ ] **Step 4: Register and place.** Append `"WorkflowSchema"` to `src/firn.toml`; add the module to `components.firn`.
- [ ] **Step 5: Regenerate** with `./simplon.sh build model`. Expected: rc 0, no W300/W301, the two generated files written.
- [ ] **Step 6: Run** the new test file and `src/tests/test_architecture.py`. Expected: PASS.
- [ ] **Step 7: See it red.** Change `self_hosted_debian`'s `setupPython` to true in `runners.firn`, `build model`, run the test: `test_each_runner_kind_carries_todays_values` fails. Revert and regenerate.
- [ ] **Step 8: Commit** the template, `firn.toml`, `components.firn`, both generated files and the test: `feat(si#857): WorkflowSchema generates the workflow vocabulary and runner kinds`.

### Task 3: runners.py builds its table from the generated kinds

**Files:**
- Modify: `src/simplon/manifest/runners.py` (`TABLE` and the comment above it)

**Interfaces:**
- Consumes: `workflowschema.RUNNER_KINDS`, `RunnerKindData`.
- Produces: unchanged public surface. `runners.TABLE: Mapping[str, Runner]`, `Runner`, `resolve`, `kinds()`, `DEFAULT`, `BOOTSTRAP` keep their names, types and values. `Runner.env` stays a `Mapping[str, str]` built with `dict(data.env)`.

- [ ] **Step 1: Replace the hand-typed `TABLE`** with one built from `workflowschema.RUNNER_KINDS`: `Runner(kind=k, labels=d.labels, setup_python=d.setup_python, env=dict(d.env), why=d.why, disk_persists=d.disk_persists)`. `can_emulate` is not read yet (#722 reads it). Replace the long comment with one line pointing at `src/firn/model/simplon/workflow/runners.firn`, where the measurements now live.
- [ ] **Step 2: Check byte identity.** Run `./simplon.sh support github workflows --check`. Expected: both workflows agree, rc 0. Then `./simplon.sh test generated`. Expected: all generated files current.
- [ ] **Step 3: Run the full suite** with `./simplon.sh test suite`. Expected: green, including `test_runners.py`, `test_runner_choice.py`, `test_workflowgen.py`, `test_release_workflow.py`. Also run `./simplon.sh test typecheck-python`.
- [ ] **Step 4: See it red.** Swap the order of the two instances in `runners.firn`, regenerate, and run `test_generated_workflowschema.py`: `test_runner_kinds_are_exactly_the_two_measured_kinds` fails. Revert and regenerate.
- [ ] **Step 5: Commit**: `refactor(si#857): runners.TABLE comes from the firn model`.

### Task 4: Record where the selectors run

**Files:**
- Modify: `docs/superpowers/specs/2026-11-22-derived-workflows-design.md`, the "Builder's call" paragraph of section 4

- [ ] **Step 1: Replace the paragraph with the decision.** The selectors (which leaves, which jobs) run in Python over the generated classes, inside `support github workflows`. Running them in firn over the exported manifest model would put docker and the firn image on every generation and every `--check`, including a pre-commit hook. Reopens when firn can be evaluated in-process without a container, or when the manifest becomes the firn model (#456).
- [ ] **Step 2: Comment the same decision on #857** (through `--body-file`), then open the PR with `Closes #857` in the body.
- [ ] **Step 3: Commit**: `docs(si#857): the derivation's selectors run in Python over the generated classes`.
