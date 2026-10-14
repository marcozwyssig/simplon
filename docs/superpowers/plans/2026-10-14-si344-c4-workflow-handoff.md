# si#344 C.4 — an artifact that crosses a job boundary is handed over, and one that cannot be is refused

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `support workflows` reads the `produces:`/`consumes:` edges of the commands each job runs. When a producer and its consumer run in different jobs of one workflow, the generated file gets `needs:`, an upload after the producing step and a download before the consuming step. When a hand-off cannot work, generation refuses and names the jobs. A file with no such edge stays byte for byte what it is today.

**Architecture:** A new module `src/simplon/tasks/handoff.py` holds the pure computation `plan(workflow, runs, artifacts) -> {job: Handoff}`, with every diagnosis. It knows nothing about YAML or GitHub. `workflowgen.render` builds the `Run`s from the expanded steps of every job (the rollout's generated jobs and the product's own), calls `handoff.plan` once per workflow, and `_render_job` writes the steps and merges `needs:`. The files cross as a tar archive in `${{ runner.temp }}`, not as a bare `path:`. The reasons are in "Decided in this plan".

**Tech Stack:** Python 3, PyYAML, pytest, GitHub Actions (`actions/upload-artifact@v4`, `actions/download-artifact@v4`), `tar`.

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md`, Part C.6 (and C.7's row "image without `path:` across jobs"). Decisions taken after the spec:
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6161492956: C measured; C does not wait for product adoption.
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6162459829: rule 1 is per plan.
- C.3 merged as #421 (eb3091f, 2026-10-14). Its open items (si#344 comment 6167823392) are **not** in C.4.
- Decided 2026-10-14 in this planning session (choice list, Marco); Task 0 records them on si#344:
  1. **A consumer whose producer runs in no job of the same workflow** is refused, unless the artifact has a `registry:` (then the body fetches it, as rule 2 already allows). This is rule 2 at workflow scope. The measured case: in the frozen firn fixture, with the release rule answered, `release push-image` consumes `firn-checked` in the release workflow, and no job there produces it. The push does not read its evidence, so the release would be green with no test run.
  2. **Inside one job, a step that consumes an artifact before the step that produces it** is refused, the same way rule 5 refuses an aggregate. This also covers `derive:` blocks (spec C.6's last bullet). The manifest's order stands, so decision 2 holds: order is declared, the data only checks it.
  3. **An artifact produced in more than one job and consumed in a job that does not produce it** is refused. GitHub refuses two uploads under one name in one run.
  4. **An artifact without `path:` that crosses a job boundary** is refused, whatever its kind. Spec C.6 names only `kind: image`.

## Decided in this plan (rulings; each is in Task 0's comment so Marco can overturn it)

- **A matrix job counts as several producers.** A job with a `strategy:` key runs once per matrix entry, so it uploads under one name more than once: decision 3's reason, so decision 3's refusal. A matrix job may *consume* freely.
- **The files cross as a tar archive.** The upload step does not take the artifact's `path:` directly, for two documented reasons:
  - `upload-artifact` drops file permissions (its README, "Permission Loss", recommends exactly this tar).
  - It roots a single path at the directory itself or at the file's parent, so the download location would depend on whether `path:` is a file or a directory. The generator cannot know that: `directory` is a directory, `test-result` a file, `artifact` either.

  So the producing job runs `tar -cf "${{ runner.temp }}/simplon-handoff-<artifact>.tar" <path>` and uploads that one file. The consuming job downloads it into `${{ runner.temp }}` and runs `tar -xf` in the workspace. The archive keeps the path relative to the product root and the mode bits. Task 2 measures this with the generated command lines on this machine. What it cannot measure here is GitHub's own upload and download of one file; that rests on the README.
- **`if-no-files-found: error` on every upload.** Its default is `warn`: a producer that wrote nothing would upload nothing and stay green. In practice the tar step already fails on a missing path; this second guard costs one line.
- **The upload goes after the last step in the job that produces the artifact; the download before the first step that consumes it.** A step that is an aggregate counts as producing or consuming whatever its planned leaves do.
- **The diagnoses run when the workflow is rendered, not when the manifest loads,** like `derive`'s and `resolve_command`'s. So they are not in the load-time census (spec C.7's row says "—"). Task 2 runs the census test to confirm it stays green; if it goes red, the commit adds `DIAGNOSIS` entries.
- **The fix the spec names for a pathless image is not offered.** Spec C.6: "give the image a `path:` so it is exported as an OCI archive". `build:image` exports nothing to a path (measured: `tasks/image.py` has no export), so the message names only the fix that exists: run producer and consumer in one job. Task 0 records this as a finding.

## Scope: what is C.4 and what is not

| Plan | Content |
|---|---|
| C.1 (merged, #417) | ports on catalogue tasks |
| C.2 (merged, #418) | `produces:`/`consumes:`, rules 1-5 and 7 |
| C.3 (merged, #421) | nuget/maven split, test results, rule 6, `release:notes`, the release aggregate, rule 8 |
| **C.4 (this)** | workflowgen: `needs:`, upload, download, and the hand-off diagnoses |

**Not in C.4:**
- **Hand-off between workflows.** Not generated. It is refused (decision 1) unless the artifact has a `registry:`.
- **Hand-written workflows** (`handwritten:`, such as simplon's `release.yml`). Untouched: the generator never reads them.
- **si#344's open C.3 items** (tag passing through aggregates, simplon's release order, the maven metadata PUT, `Release.published`, the deploy port).
- **Exporting an image to a `path:`.** No body does it, and C.4 does not add one.

## Global Constraints

- **Branch and PR:** branch `si344-c4-workflow-artifacts` from `main` at eb3091f (already created). The PR is in milestone "M3 - ci / cd / support"; its body says "Part of #344 (C.4 of four plans)" and does **not** say `Closes #344`, since si#344 still carries open items. Never merge; Marco merges.
- **Commits:** set the identity env on every commit; `git config` and `--amend` are blocked:
  `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'`
  The message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
  ```
- **Python:** always `./deploy/orchestrator/.venv/bin/python`. `PY` below means that path.
  - Tests: `PY -m pytest src/tests -q -p no:cacheprovider` (about 2 min). Redirect the full run to a file and read its tail. Three `test_tasks_docs` failures are root-bound and pre-existing; any other failure is yours.
  - mypy: `PY -m mypy --config-file mypy.ini src/simplon`.
- **Generated files are never edited by hand.** `.github/workflows/ci.yml` is written by `./simplon.sh support workflows`. **It must not change in this plan** (spec C.6: simplon's own CI is one job). `src/tests/test_own_workflows.py` is the drift gate.
- **CLAUDE.md:**
  - See every new assertion red: break the property, run the test, watch it fail, restore. Write down in the commit which break turned it red.
  - Report findings, do not patch them away.
  - A quoted error text is a second source. Every refusal a test asserts is matched on a fragment of the real message.
  - A new `raise` on the load path gets a census entry in the same commit (`src/tests/test_refusal_census.py` `CENSUS`). The census test says whether a raise is on that path; do not guess.
- **No invented step names.** `workflowgen` writes no `name:` the product did not declare (its docstring on `_render_job`). The kernel's own steps carry a `note:` comment instead, as the checkout does.

## Review Focus

1. **A file that does not change when nothing crosses.** simplon's `ci.yml`, and every workflow with one job or no edge, must render byte-identical. A hand-off computation that adds `needs: []` or an empty `with:` breaks that without failing anything obvious. Pinned in Task 2 (`test_simplons_own_ci_renders_byte_identical_and_hands_nothing_over`), and by `test_own_workflows.py`.
2. **The product's own `needs:`.** A job may already declare `needs: build` (a string) or a list. The generated value keeps the product's entries first, in their order, adds only what is missing, and stays a string when there is one entry. Pinned in Task 2 (`test_a_declared_needs_is_kept_first_and_not_repeated`).
3. **A cycle through the hand-off.** Two jobs that each consume what the other produces would get `needs:` on each other, and GitHub refuses such a file with an error far from the cause. Refused by name, together with the product's own `needs:`. Pinned in Task 1 (`test_jobs_that_need_each_other_through_their_artifacts_are_refused`).
4. **A producer that writes nothing.** The tar step fails on a missing path, and the upload has `if-no-files-found: error`. Pinned in Task 2 (`test_the_handoff_lines_fail_on_a_path_that_was_not_written`), measured with real `tar`.
5. **Mode bits and the relative path survive the trip.** An executable built in one job must still be executable in the next, under the same relative path. Pinned in Task 2 (`test_the_handoff_lines_restore_the_path_and_its_mode`), measured with real `tar`.

## The measurement this plan stands on (2026-10-14)

All eight manifests were fetched again through the API. Each one was loaded with the kernel at eb3091f; a product still in `groups:` form was loaded after `migrate_text`. Then every leaf each job runs was listed (aggregates expanded through `plan_for`, `derive:` through `derive`), and the edges between jobs were listed.

| manifest | generated workflows | jobs | edges across jobs |
|---|---|---|---|
| simplon | `ci` (`release` hand-written) | `self-build` | none: `kernel` is produced and nothing consumes it there |
| firn | `ci`, `release` | `build`, `system`, `regression`; `image` | none in the frozen fixture's `ci`: `toolchain` is built in all three jobs, and every consumer runs in the job that builds it. The live firn.yaml does not load: rule 6 refuses `release push-image`, which is firn's C.3 bill |
| biz-cockpit | `ci` (`publish` hand-written) | `gate` | none |
| swi | `ci` | `check` | none |
| agile-cockpit, asbundle, cleon, netctl | no `workflows:` section | — | — |

- **No live file changes.** None of the eight uses `derive:`, and none has a matrix job producing an artifact.
- **One case is refused by the new rules,** in the frozen firn fixture with the release rule answered in memory (`realmanifests.answer_release_rule`): the release workflow's `image` job runs `release push-image`, and no job there produces `firn-checked` (decision 1). It is a fixture, not a live file. firn's real answer to rule 6 will bind the tests its release job already runs.

The script that measured this is in Task 3, so the measurement can be rerun before the PR.

## File Structure

- **Create** `src/simplon/tasks/handoff.py`: `Run`, `Handoff`, `plan`, `_acyclic`. The edge computation and its five diagnoses; no YAML, no GitHub.
- **Modify** `src/simplon/tasks/workflowgen.py`:
  - constants `UPLOAD_ACTION`, `DOWNLOAD_ACTION`, `HANDOFF_ARCHIVE`, `HANDOFF_NOTE`;
  - `_expanded` (the `derive:` expansion, moved out of `_render_job`), `_leaves`, `_runs`, `_send`, `_receive`, `_with_needs`;
  - `render` gains `artifacts=`, computes the hand-off and passes each job's to `_render_job`; `write`/`check` gain `artifacts=`.
- **Modify** `src/simplon/tasks/workflows.py`: pass `artifacts=artifactsection.declared(ctx.manifest_data())`.
- **Modify** `src/site/content/how/manifest.md`: a section in the `workflows:` part on what crosses a job boundary.
- **Tests:**
  - `src/tests/test_handoff.py` (new, Task 1): `plan` and its diagnoses.
  - `src/tests/test_workflow_handoff.py` (new, Task 2): rendering, `needs:` merge, simplon byte-identical, and real `tar`.

---

### Task 0: Record the planning decisions on si#344

**Files:** none in the repository.

- [ ] **Step 1: Post the decisions**

```bash
cat > /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c4-decisions.md <<'EOF'
## C.4: decided before the plan (choice list, Marco, 2026-10-14)

C.4 is the workflow generator (spec C.6): when a producer and its consumer run in different jobs of one generated workflow, the consumer's job gets `needs:` and a download, and the producer's job an upload.

**Measured (all eight manifests, fetched 2026-10-14, loaded at eb3091f):** no generated workflow hands an artifact across a job boundary today. simplon's `ci` is one job; firn's `ci` builds `toolchain` in each of its three jobs and consumes it only where it builds it; biz-cockpit's and swi's are one job each; four products have no `workflows:` section. None uses `derive:`. **C.4 changes no live file.**

Decided:
1. **A consumer whose producer runs in no job of the same workflow is refused**, unless the artifact has a `registry:`. This is rule 2 at workflow scope. Found while measuring: in the frozen firn fixture, with rule 6 answered, `release push-image` consumes `firn-checked` in the release workflow, and no job there produces it. The push does not read its evidence, so the release would be green with no test run.
2. **A step that consumes an artifact before the step in the same job that produces it is refused**, as rule 5 refuses an aggregate. This covers `derive:` too. The manifest's order stands; nothing is reordered.
3. **An artifact produced in more than one job and consumed in a job that does not produce it is refused.** GitHub refuses two uploads under one name in one run.
4. **An artifact without `path:` across a job boundary is refused, whatever its kind**, not only `kind: image`.

Ruled while planning (say so if any of these is wrong):
- A job with `strategy:` counts as several producers (point 3's reason): it uploads once per matrix entry.
- The files cross as a tar archive in `${{ runner.temp }}`, not as a bare `path:`. `upload-artifact` drops file permissions (its README recommends tar), and its root for a single path depends on whether the path is a file or a directory, which the generator cannot know. GitHub's own upload and download of one file is not measured from this machine.
- `if-no-files-found: error` on every upload (the default `warn` would let a producer that wrote nothing stay green).
- The diagnoses run when a workflow is rendered, not when the manifest loads, like `derive`'s. They are outside the load-time census.

**Finding against spec C.6:** its fix for a pathless image ("give the image a `path:` so it is exported as an OCI archive") does not exist. `build:image` exports nothing to a path. The diagnosis therefore names the fix that exists: run producer and consumer in one job.
EOF
gh issue comment 344 --repo marcozwyssig/simplon --body-file /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c4-decisions.md
```

Expected: a comment URL.

---

### Task 1: `handoff.plan`: the edges between jobs, and the five diagnoses

**Files:**
- Create: `src/simplon/tasks/handoff.py`
- Test: `src/tests/test_handoff.py`

**Interfaces:**
- Consumes: `simplon.domain.manifest.CommandSpec` (`.produces`, `.consumes`: `dict[str, tuple[str, ...]]`); `simplon.domain.artifactsection.Declared(kind, registry, path)`.
- Produces (Task 2 relies on these exact names):
  - `Run(job: str, steps: tuple[tuple[tuple[str, CommandSpec], ...], ...], matrix: bool = False, needs: tuple[str, ...] = ())`. `steps[i]` holds the `(command path, spec)` of every leaf step `i` runs; `needs` is what the product declared.
  - `Handoff(needs: tuple[str, ...] = (), uploads: Mapping[int, tuple[str, ...]] = {}, downloads: Mapping[int, tuple[str, ...]] = {})`. `uploads[i]`: the artifacts to upload **after** step `i`; `downloads[i]`: those to download **before** step `i`; `needs`: only the jobs the hand-off adds.
  - `plan(workflow: str, runs: Sequence[Run], artifacts: Mapping[str, artifactsection.Declared]) -> dict[str, Handoff]`, one entry for every run.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_handoff.py`:

```python
"""si#344 C.4: which artifacts cross from one job to another, and which cannot (spec C.6).

AAA; the name states the behaviour under test. The specs come from a loaded manifest, so the edges are the ones
the loader binds, not hand-built tuples.
"""
import pytest

from simplon.domain import artifactsection, catalogue, manifest
from simplon.tasks import handoff

import yaml

TEXT = """
product: demo
tasks:
  copy:
    impl: "simplon.test_impls:nullary"
    help: "Copy one directory into another."
    input:  { source: { accepts: directory } }
    output: { target: { accepts: directory } }
  seed:
    impl: "simplon.test_impls:nullary"
    help: "Write a directory."
    output: { target: { accepts: directory } }
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
  left: { kind: directory, path: build/left }
  right: { kind: directory, path: build/right }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
      left: { task: "seed", produces: { target: left } }
      right: { task: "copy", consumes: { source: left }, produces: { target: right } }
      back: { task: "copy", consumes: { source: right }, produces: { target: left } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      push-image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""

LOADED = manifest.load(TEXT, catalogue=catalogue.load(), manifest_path="demo.yaml")
ARTIFACTS = artifactsection.declared(yaml.safe_load(TEXT))


def _leaf(path):
    group, name = path.rsplit(" ", 1)
    return (path, LOADED.spec_for(group, name))


def _run(job, *steps, matrix=False, needs=()):
    """A job whose step i runs the one leaf `steps[i]`."""
    return handoff.Run(job, tuple((_leaf(step),) for step in steps), matrix=matrix, needs=needs)


def test_a_result_made_in_one_job_and_consumed_in_another_is_handed_over():
    # arrange
    runs = [_run("test", "build image", "test image"), _run("release", "build image", "release push-image")]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out["test"] == handoff.Handoff(uploads={1: ("app-checked",)})
    assert out["release"] == handoff.Handoff(needs=("test",), downloads={1: ("app-checked",)})


def test_producer_and_consumer_in_one_job_hand_nothing_over():
    # arrange
    runs = [_run("all", "build image", "test image", "release push-image")]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out == {"all": handoff.Handoff()}


def test_the_upload_follows_the_last_producing_step_and_the_download_precedes_the_first_consumer():
    # arrange: job a writes `left` twice (seed at step 0, back at step 2 - back consumes `right`, which
    # a also makes, at step 1); job b reads `left` at steps 1 and 2
    runs = [handoff.Run("a", ((_leaf("build left"),), (_leaf("build right"),), (_leaf("build back"),))),
            handoff.Run("b", ((_leaf("build image"),), (_leaf("build right"),), (_leaf("build right"),)))]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out["a"] == handoff.Handoff(uploads={2: ("left",)})
    assert out["b"] == handoff.Handoff(needs=("a",), downloads={1: ("left",)})  # b makes `right` itself


def test_a_consumer_whose_producer_runs_in_no_job_of_the_workflow_is_refused():
    # arrange: the release job runs the push, and no job runs the test that writes its evidence
    runs = [_run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match="no job in this workflow produces it"):
        handoff.plan("release", runs, ARTIFACTS)


def test_a_consumed_artifact_with_a_registry_and_no_producer_in_the_workflow_is_fetched():
    # arrange: `app` has a registry; the test job does not build it
    runs = [_run("test", "test image")]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out == {"test": handoff.Handoff()}


def test_a_step_consuming_before_the_step_that_produces_it_in_the_same_job_is_refused():
    # arrange
    runs = [_run("all", "test image", "build image")]

    # act / assert
    with pytest.raises(ValueError, match="runs 'test image' .step 1. before 'build image' .step 2."):
        handoff.plan("ci", runs, ARTIFACTS)


def test_an_artifact_made_in_two_jobs_and_consumed_in_a_third_is_refused():
    # arrange
    runs = [_run("t1", "build image", "test image"), _run("t2", "build image", "test image"),
            _run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match="is produced in more than one job: 't1', 't2'"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_an_artifact_made_in_a_matrix_job_and_consumed_elsewhere_is_refused():
    # arrange
    runs = [_run("test", "build image", "test image", matrix=True),
            _run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match="runs once per matrix entry"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_a_matrix_job_may_consume_what_another_job_hands_over():
    # arrange
    runs = [_run("test", "build image", "test image"),
            _run("release", "build image", "release push-image", matrix=True)]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out["release"].needs == ("test",)


def test_an_artifact_without_a_path_across_a_job_boundary_is_refused_whatever_its_kind():
    # arrange: `app` is built in one job and tested in another, and an image has no file to hand over
    runs = [_run("build", "build image"), _run("test", "test image")]

    # act / assert
    with pytest.raises(ValueError, match="declares no `path:`, so there is no file to hand over"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_jobs_that_need_each_other_through_their_artifacts_are_refused():
    # arrange: a seeds `left` and copies `right` back into it; b copies `left` into `right`
    runs = [_run("a", "build left", "build back"), _run("b", "build right")]

    # act / assert
    with pytest.raises(ValueError, match="need each other: a -> b -> a"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_a_cycle_through_a_declared_needs_is_refused_too():
    # arrange: b needs a by hand-off; a declares `needs: b` itself
    runs = [_run("a", "build left", needs=("b",)), _run("b", "build right")]

    # act / assert
    with pytest.raises(ValueError, match="need each other"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_a_declared_needs_is_not_repeated_in_the_added_ones():
    # arrange
    runs = [_run("test", "build image", "test image"),
            _run("release", "build image", "release push-image", needs=("test",))]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert: the hand-off still downloads, and adds no second `test`
    assert out["release"] == handoff.Handoff(downloads={1: ("app-checked",)})
```


- [ ] **Step 2: Run the tests to verify they fail**

Run: `PY -m pytest src/tests/test_handoff.py -q -p no:cacheprovider`
Expected: collection error, `ImportError: cannot import name 'handoff' from 'simplon.tasks'`.

- [ ] **Step 3: Write the implementation**

Create `src/simplon/tasks/handoff.py`:

```python
"""Handing an artifact from one job to the next (si#344 C.4, spec C.6).

A generated workflow runs commands in jobs, and GitHub gives every job a fresh machine. An artifact one job
produces is therefore not on the disk of the next job, however the manifest orders the two commands. The
`produces:`/`consumes:` edges already say which artifact goes from which command to which; this module reads
them per job and says what has to cross: the consumer's job needs the producer's job, the producer's job uploads
after its last producing step, the consumer's job downloads before its first consuming step.

Producer and consumer in one job hand nothing over: the files are already there.

WHAT IS REFUSED, and every one is a diagnosis: the workflow it would have written does not work, or works by
accident.
- A consumer whose producer runs in no job of this workflow, for an artifact with no `registry:`: nothing would
  put it there. A release's evidence is the sharp case, because the push does not read it and would be green
  with no test run (decided 2026-10-14, si#344).
- A step consuming before the step of its own job that produces it: rule 5, one job wide. The order is the
  manifest's and is not changed here.
- An artifact produced in more than one job, or in a matrix job, and consumed in a job that does not produce
  it: GitHub refuses a second upload under one name in one run, and which one to take would be a guess.
- An artifact with no `path:` that crosses: there is no file to hand over. An image lives in one job's docker
  daemon, and the next job's daemon has it only when the runner happens to be shared.
- Jobs that need each other: GitHub refuses the file, far from the cause.

This module knows nothing about YAML or GitHub's steps; `workflowgen` writes them.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from simplon.domain.artifactsection import Declared
    from simplon.domain.manifest import CommandSpec


class Run(NamedTuple):
    """One job as the hand-off sees it. `steps[i]` holds the (command path, spec) of every leaf step `i` runs -
    one for a leaf, the plan for an aggregate, none for a verbatim step. `matrix` is true for a job with a
    `strategy:`, which runs once per entry. `needs` is what the product declared."""

    job: str
    steps: "tuple[tuple[tuple[str, CommandSpec], ...], ...]"
    matrix: bool = False
    needs: tuple[str, ...] = ()


class Handoff(NamedTuple):
    """What one job gains: the jobs it must wait for (only those the hand-off adds), the artifacts it uploads
    AFTER step i, and those it downloads BEFORE step i."""

    needs: tuple[str, ...] = ()
    uploads: Mapping[int, tuple[str, ...]] = {}
    downloads: Mapping[int, tuple[str, ...]] = {}


def _bound(sides: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(artifact for names in sides.values() for artifact in names)


def plan(workflow: str, runs: Sequence[Run], artifacts: Mapping[str, "Declared"]) -> dict[str, Handoff]:
    """Every job's hand-off, or a ValueError naming the workflow, the job and the artifact."""
    first: dict[str, dict[str, tuple[int, str]]] = {}
    last: dict[str, dict[str, int]] = {}
    for run in runs:
        for at, leaves in enumerate(run.steps):
            for path, spec in leaves:
                for artifact in _bound(spec.produces):
                    first.setdefault(artifact, {}).setdefault(run.job, (at, path))
                    last.setdefault(artifact, {})[run.job] = at
    matrix = {run.job: run.matrix for run in runs}
    needs: dict[str, list[str]] = {run.job: [] for run in runs}
    uploads: dict[str, dict[int, list[str]]] = {run.job: {} for run in runs}
    downloads: dict[str, dict[int, list[str]]] = {run.job: {} for run in runs}
    for run in runs:
        fetched: set[str] = set()
        for at, leaves in enumerate(run.steps):
            for path, spec in leaves:
                for artifact in _bound(spec.consumes):
                    where = f"workflow '{workflow}', job '{run.job}'"
                    makers = last.get(artifact, {})
                    if run.job in makers:
                        made_at, maker = first[artifact][run.job]
                        if made_at > at:
                            raise ValueError(
                                f"{where} runs '{path}' (step {at + 1}) before '{maker}' (step {made_at + 1}), and "
                                f"'{path}' consumes '{artifact}', which '{maker}' produces - put '{maker}' first")
                        continue
                    declared = artifacts.get(artifact)
                    if not makers:
                        if declared is not None and declared.registry:
                            continue
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}', and no job in this workflow produces it - "
                            f"run its producer in a job here, or give '{artifact}' a `registry:` it is fetched from")
                    if len(makers) > 1:
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}', which is produced in more than one job: "
                            f"{', '.join(repr(job) for job in makers)} - one run uploads an artifact once, so "
                            f"produce it in one job, or run '{path}' in a job that produces it itself")
                    (source, after), = makers.items()
                    if matrix[source]:
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}', which job '{source}' produces, and '{source}' "
                            f"runs once per matrix entry - one run uploads an artifact once, so produce it in a "
                            f"job without `strategy:`, or run '{path}' in '{source}'")
                    if declared is None or not declared.path:
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}' from job '{source}', and '{artifact}' declares "
                            f"no `path:`, so there is no file to hand over - run its producer and '{path}' in one job")
                    if artifact not in fetched:
                        fetched.add(artifact)
                        downloads[run.job].setdefault(at, []).append(artifact)
                    if artifact not in uploads[source].get(after, []):
                        uploads[source].setdefault(after, []).append(artifact)
                    if source not in needs[run.job] and source not in run.needs:
                        needs[run.job].append(source)
    _acyclic(workflow, {run.job: (*run.needs, *needs[run.job]) for run in runs})
    return {run.job: Handoff(tuple(needs[run.job]),
                             {at: tuple(names) for at, names in uploads[run.job].items()},
                             {at: tuple(names) for at, names in downloads[run.job].items()})
            for run in runs}


def _acyclic(workflow: str, needs: Mapping[str, tuple[str, ...]]) -> None:
    """Refuse jobs that wait for each other, through the hand-off or the product's own `needs:`."""
    done: set[str] = set()

    def visit(job: str, trail: tuple[str, ...]) -> None:
        if job in done:
            return
        if job in trail:
            loop = (*trail[trail.index(job):], job)
            raise ValueError(
                f"workflow '{workflow}': jobs need each other: {' -> '.join(loop)} - an artifact one of them "
                f"consumes is produced by a job that waits for it; move a producer or a consumer so the jobs form "
                f"a chain")
        for other in needs.get(job, ()):
            visit(other, (*trail, job))
        done.add(job)

    for job in needs:
        visit(job, ())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PY -m pytest src/tests/test_handoff.py -q -p no:cacheprovider`
Expected: 13 passed. If the cycle test's message lists the loop from `b` (`b -> a -> b`), the walk started elsewhere: `needs` is iterated in run order, so it starts at `a`. Fix the code, not the test.

- [ ] **Step 5: See each refusal red**

For each of the five `raise`s, replace the `raise ValueError(` with `pass  # ` on a copy (or comment the `if` body out), run its test, and watch it fail. Then also:
- Change `if artifact not in fetched` to `if True` and watch `test_the_upload_follows_..._first_consumer` fail (two downloads).
- Drop `and source not in run.needs` and watch `test_a_declared_needs_is_not_repeated_in_the_added_ones` fail.

Restore everything; the suite in Step 4 is green again.

- [ ] **Step 6: mypy, then commit**

Run: `PY -m mypy --config-file mypy.ini src/simplon`. Expected: `Success`.

```bash
git add src/simplon/tasks/handoff.py src/tests/test_handoff.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): the edges between a workflow's jobs say what has to be handed over

handoff.plan reads produces/consumes per job: a consumer in another job than its producer gets
`needs:` and a download, the producer an upload. Five diagnoses, decided 2026-10-14: no producer in
the workflow (unless the artifact has a registry), a consumer before its producer in one job, several
producing jobs or a matrix producer, no `path:` across jobs, and jobs that need each other.

Seen red: each raise disabled in turn; a second download per artifact; a declared `needs:` repeated.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: `workflowgen` writes the hand-off

**Files:**
- Modify: `src/simplon/tasks/workflowgen.py`: constants near `CHECKOUT_ACTION` (line 89); `render` (line 953); `_render_job` (line 1049); `write` (line 1271); `check` (line 1292).
- Modify: `src/simplon/tasks/workflows.py`: the `write` call (line 48) and the `check` call (line 64).
- Test: `src/tests/test_workflow_handoff.py` (new)

**Interfaces:**
- Consumes: `handoff.Run`, `handoff.Handoff`, `handoff.plan` (Task 1); `artifactsection.declared(document) -> dict[str, Declared]`.
- Produces: `render(workflow, *, manifest, product, source, environments=None, artifacts=None)`, `write(..., artifacts=None)`, `check(..., artifacts=None)`. With `artifacts=None`, `render` reads the declarations from `context.current().manifest_data()`, but **only** when a job runs a command that binds a port, as `_rollout` does for the matrix.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_workflow_handoff.py`:

```python
"""si#344 C.4: what the generated workflow says when an artifact crosses a job boundary (spec C.6).

AAA; the name states the behaviour under test. The tar lines are run for real: they are what crosses, and a
claim about them that was never executed is not yet a claim.
"""
import os
import stat
import subprocess
import textwrap

import pytest
import yaml

from simplon.domain import artifactsection, catalogue as catalogue_mod, manifest as manifest_mod
from simplon.tasks import workflowgen

from conftest import ROOT

TEXT = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      push-image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""

LOADED = manifest_mod.load(TEXT, catalogue=catalogue_mod.load(), manifest_path="demo.yaml")
ARTIFACTS = artifactsection.declared(yaml.safe_load(TEXT))

SPLIT = """
workflows:
  ci:
    on: [push]
    jobs:
      test:
        runs-on: ubuntu-latest
        steps:
          - command: build image
          - command: test image
      release:
        runs-on: ubuntu-latest
        steps:
          - command: build image
          - command: release push-image
"""


def _render(body, key="ci"):
    picked = next(w for w in workflowgen.parse(yaml.safe_load(textwrap.dedent(body))) if w.key == key)
    return workflowgen.render(picked, manifest=LOADED, product="demo", source="demo.yaml", artifacts=ARTIFACTS)


def _steps(doc, job):
    return doc["jobs"][job]["steps"]


def test_the_producing_job_archives_and_uploads_after_its_producing_step():
    # act
    doc = yaml.safe_load(_render(SPLIT))

    # assert: checkout, build image, test image, tar, upload
    steps = _steps(doc, "test")
    assert steps[2]["run"] == "./demo.sh test image"
    assert steps[3]["run"] == 'tar -cf "${{ runner.temp }}/simplon-handoff-app-checked.tar" build/test/app.json'
    assert steps[4] == {"uses": "actions/upload-artifact@v4",
                        "with": {"name": "app-checked",
                                 "path": "${{ runner.temp }}/simplon-handoff-app-checked.tar",
                                 "if-no-files-found": "error"}}


def test_the_consuming_job_needs_the_producer_and_downloads_before_its_consuming_step():
    # act
    doc = yaml.safe_load(_render(SPLIT))

    # assert: checkout, build image, download, untar, push
    job = doc["jobs"]["release"]
    assert job["needs"] == "test"
    steps = job["steps"]
    assert steps[2] == {"uses": "actions/download-artifact@v4",
                        "with": {"name": "app-checked", "path": "${{ runner.temp }}"}}
    assert steps[3]["run"] == 'tar -xf "${{ runner.temp }}/simplon-handoff-app-checked.tar"'
    assert steps[4]["run"] == "./demo.sh release push-image"


def test_the_file_says_why_the_kernel_wrote_the_handoff_steps():
    # act
    text = _render(SPLIT)

    # assert
    assert "upload-artifact drops file permissions" in text


def test_a_declared_needs_is_kept_first_and_not_repeated():
    # arrange: `release` already waits for a `lint` job of its own, and for `test`
    body = SPLIT.replace("      release:\n        runs-on: ubuntu-latest\n",
                         "      release:\n        runs-on: ubuntu-latest\n        needs: [lint, test]\n") + """\
      lint:
        runs-on: ubuntu-latest
        steps:
          - run: echo lint
"""

    # act
    doc = yaml.safe_load(_render(body))

    # assert
    assert doc["jobs"]["release"]["needs"] == ["lint", "test"]


def test_a_declared_needs_string_becomes_a_list_when_the_handoff_adds_a_job():
    # arrange
    body = SPLIT.replace("      release:\n        runs-on: ubuntu-latest\n",
                         "      release:\n        runs-on: ubuntu-latest\n        needs: lint\n") + """\
      lint:
        runs-on: ubuntu-latest
        steps:
          - run: echo lint
"""

    # act
    doc = yaml.safe_load(_render(body))

    # assert
    assert doc["jobs"]["release"]["needs"] == ["lint", "test"]


def test_a_workflow_with_no_edge_across_jobs_renders_as_it_did():
    # arrange: one job runs the whole chain
    body = """
    workflows:
      ci:
        on: [push]
        jobs:
          all:
            runs-on: ubuntu-latest
            steps:
              - command: build image
              - command: test image
              - command: release push-image
    """

    # act
    text = _render(body)

    # assert
    assert "upload-artifact" not in text and "download-artifact" not in text
    assert "needs" not in yaml.safe_load(text)["jobs"]["all"]


def test_an_aggregate_step_hands_over_what_its_leaves_produce():
    # arrange: an aggregate over the test leaf, run in the test job
    text = TEXT.replace("  test:\n    commands:\n",
                        "  test:\n    commands:\n      all: { depends_on: [check], help: \"Every test.\" }\n"
                        ).replace("      image: { task: \"test:image\"", "      check: { task: \"test:image\"")
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="demo.yaml")
    body = SPLIT.replace("- command: test image", "- command: test all")
    picked = next(w for w in workflowgen.parse(yaml.safe_load(textwrap.dedent(body))) if w.key == "ci")

    # act
    doc = yaml.safe_load(workflowgen.render(picked, manifest=loaded, product="demo", source="demo.yaml",
                                            artifacts=artifactsection.declared(yaml.safe_load(text))))

    # assert
    assert doc["jobs"]["test"]["steps"][4]["with"]["name"] == "app-checked"


def test_a_refusal_stops_generation_and_names_the_workflow():
    # arrange: the release job runs the push and nothing writes its evidence
    body = """
    workflows:
      release:
        on: [push]
        jobs:
          image:
            runs-on: ubuntu-latest
            steps:
              - command: build image
              - command: release push-image
    """

    # act / assert
    with pytest.raises(ValueError, match="workflow 'release', job 'image': 'release push-image' consumes "
                                         "'app-checked', and no job in this workflow produces it"):
        _render(body, key="release")


def test_simplons_own_ci_renders_byte_identical_and_hands_nothing_over():
    # arrange
    text = (ROOT / "simplon.yaml").read_text(encoding="utf-8")
    loaded = manifest_mod.load(text, catalogue=catalogue_mod.load(), manifest_path="simplon.yaml")
    data = yaml.safe_load(text)
    ci = next(w for w in workflowgen.parse(data) if w.key == "ci")

    # act
    rendered = workflowgen.render(ci, manifest=loaded, product="simplon", source="simplon.yaml",
                                  artifacts=artifactsection.declared(data))

    # assert
    assert rendered == (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "download-artifact" not in rendered


def _lines(doc):
    """The tar lines the generator wrote, with `${{ runner.temp }}` replaced the way the runner replaces it."""
    pack = _steps(doc, "test")[3]["run"]
    unpack = _steps(doc, "release")[3]["run"]
    return pack, unpack


def _sh(line, cwd, temp):
    return subprocess.run(["bash", "-c", line.replace("${{ runner.temp }}", str(temp))], cwd=cwd,
                          capture_output=True, text=True)


def test_the_handoff_lines_restore_the_path_and_its_mode(tmp_path):
    # arrange: the producing job's checkout holds the result, executable, under its relative path
    pack, unpack = _lines(yaml.safe_load(_render(SPLIT)))
    producer, consumer, temp = tmp_path / "producer", tmp_path / "consumer", tmp_path / "temp"
    for d in (producer, consumer, temp):
        d.mkdir()
    made = producer / "build" / "test" / "app.json"
    made.parent.mkdir(parents=True)
    made.write_text('{"rc": 0}\n', encoding="utf-8")
    made.chmod(0o755)

    # act: pack in the producer, unpack in a fresh consumer checkout
    packed = _sh(pack, producer, temp)
    unpacked = _sh(unpack, consumer, temp)

    # assert
    assert packed.returncode == 0 and unpacked.returncode == 0, packed.stderr + unpacked.stderr
    got = consumer / "build" / "test" / "app.json"
    assert got.read_text(encoding="utf-8") == '{"rc": 0}\n'
    assert stat.S_IMODE(os.stat(got).st_mode) == 0o755


def test_the_handoff_lines_fail_on_a_path_that_was_not_written(tmp_path):
    # arrange: the producer exited 0 and wrote nothing
    pack, _ = _lines(yaml.safe_load(_render(SPLIT)))
    temp = tmp_path / "temp"
    temp.mkdir()

    # act
    packed = _sh(pack, tmp_path, temp)

    # assert
    assert packed.returncode != 0
    assert "build/test/app.json" in packed.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PY -m pytest src/tests/test_workflow_handoff.py -q -p no:cacheprovider`
Expected: every test fails with `TypeError: render() got an unexpected keyword argument 'artifacts'`.

- [ ] **Step 3: Constants**

In `src/simplon/tasks/workflowgen.py`, after `SETUP_PYTHON_ACTION` (line 90), add:

```python
#: si#344 C.4: the two actions an artifact crosses a job boundary with. Pinned like the checkout.
UPLOAD_ACTION = "actions/upload-artifact@v4"
DOWNLOAD_ACTION = "actions/download-artifact@v4"

#: The one file that crosses, in the runner's temp directory, never in the product's tree.
HANDOFF_ARCHIVE = "${{{{ runner.temp }}}}/simplon-handoff-{artifact}.tar"

HANDOFF_NOTE = """si#344 C.4: '{artifact}' is produced in one job of this workflow and consumed in another, and every
job starts on a fresh machine. So the kernel writes its hand-off: an archive after the producing step, uploaded
and downloaded under the artifact's name, unpacked before the consuming step. The consuming job `needs:` this one.

An archive and not the bare path: upload-artifact drops file permissions (its README says so and recommends
tar), and where it roots one path depends on whether the path is a file or a directory. The archive keeps the
path relative to the checkout and the mode bits, so the next job finds exactly what this one wrote."""
```

`HANDOFF_ARCHIVE.format(artifact="x")` gives `${{ runner.temp }}/simplon-handoff-x.tar`. The doubled braces exist so that `.format` leaves GitHub's expression alone.

- [ ] **Step 4: Expansion, leaves, runs, and the hand-off steps**

In `_render_job`, cut the `derive:` loop (the block that starts at `steps: list[Step] = []` and ends after `steps.extend(rest)`). Put it in a function of its own, above `_render_job`:

```python
def _expanded(job: Job, manifest: Manifest, where: str) -> list[Step]:
    """The job's steps with every `derive:` placeholder replaced by the steps its groups imply.

    The derivation happens HERE and not at parse time, because it needs the manifest - the same seam a
    `command:` step is already resolved at. A derived step expands into the steps its groups imply and
    carries its own note into the first of them, so the file says where that block came from and what
    it left out, standing exactly where the product put it.
    """
    steps: list[Step] = []
    for index, step in enumerate(job.steps):
        if not step.derive:
            steps.append(step)
            continue
        result = derive(manifest, step.derive, where=f"{where}, step {index + 1}")
        head, rest = result.steps[0], result.steps[1:]
        note = "\n\n".join(part for part in (step.note.strip(), result.note) if part)
        steps.append(head._replace(note=note))
        steps.extend(rest)
    return steps


def _leaves(manifest: Manifest, step: Step, where: str) -> "tuple[tuple[str, CommandSpec], ...]":
    """The leaf commands a step runs, with their specs: itself for a leaf, its plan for an aggregate, none for a
    verbatim step. An aggregate's plan names each leaf by a bare name exactly one group owns (#519)."""
    if not step.command:
        return ()
    group, name = resolve_command(manifest, step.command, where=where)
    spec = manifest.commands[group][name]
    if not spec.depends_on:
        return ((f"{group.replace('.', ' ')} {name}", spec),)
    out: list[tuple[str, CommandSpec]] = []
    for leaf in manifest.plan_for(name, group=group):
        owner = next(g for g, members in manifest.commands.items() if leaf in members)
        member = manifest.commands[owner][leaf]
        if not member.depends_on:
            out.append((f"{owner.replace('.', ' ')} {leaf}", member))
    return tuple(out)


def _declared_needs(extras: Mapping[str, object]) -> tuple[str, ...]:
    value = extras.get("needs")
    if value is None:
        return ()
    return (str(value),) if isinstance(value, str) else tuple(str(v) for v in value)  # type: ignore[union-attr]


def _with_needs(extras: Mapping[str, object], added: Sequence[str]) -> Mapping[str, object]:
    """The job's own `needs:` first, in its order, then what the hand-off adds; a string while it is one."""
    if not added:
        return extras
    merged = [*_declared_needs(extras), *added]
    return {**extras, "needs": merged[0] if len(merged) == 1 else merged}


def _send(artifact: str, path: str) -> tuple[Step, Step]:
    archive = HANDOFF_ARCHIVE.format(artifact=artifact)
    return (Step(verbatim={"run": f'tar -cf "{archive}" {shlex.quote(path)}'},
                 note=HANDOFF_NOTE.format(artifact=artifact)),
            Step(verbatim={"uses": UPLOAD_ACTION,
                           "with": {"name": artifact, "path": archive, "if-no-files-found": "error"}}))


def _receive(artifact: str) -> tuple[Step, Step]:
    archive = HANDOFF_ARCHIVE.format(artifact=artifact)
    return (Step(verbatim={"uses": DOWNLOAD_ACTION, "with": {"name": artifact, "path": "${{ runner.temp }}"}},
                 note=HANDOFF_NOTE.format(artifact=artifact)),
            Step(verbatim={"run": f'tar -xf "{archive}"'}))
```

Add `from simplon.tasks import handoff`, `from simplon.domain import artifactsection` and `CommandSpec` to the imports (`from simplon.domain.manifest import CommandSpec, Manifest`).

- [ ] **Step 5: `render` computes the hand-off once per workflow**

Replace the job loop in `render`:

```python
    for job in (*_rollout(workflow, environments), *workflow.jobs):
        lines += _render_job(job, manifest=manifest, product=product, workflow=workflow.key)
```

with:

```python
    jobs = (*_rollout(workflow, environments), *workflow.jobs)
    expanded = {job.name: _expanded(job, manifest, f"workflow '{workflow.key}', job '{job.name}'") for job in jobs}
    runs = [handoff.Run(job.name,
                        tuple(_leaves(manifest, step, f"workflow '{workflow.key}', job '{job.name}', step {at + 1}")
                              for at, step in enumerate(expanded[job.name])),
                        matrix="strategy" in job.extras, needs=_declared_needs(job.extras))
            for job in jobs]
    binds = any(spec.produces or spec.consumes for run in runs for leaves in run.steps for _, spec in leaves)
    if binds and artifacts is None:
        # Read only when a job binds a port, for `_rollout`'s reason: an ordinary workflow must not need a
        # registered ProductContext to render.
        artifacts = artifactsection.declared(context.current().manifest_data())
    handoffs = handoff.plan(workflow.key, runs, artifacts or {})
    for job in jobs:
        lines += _render_job(job, expanded=expanded[job.name], crossing=handoffs[job.name],
                             artifacts=artifacts or {}, manifest=manifest, product=product, workflow=workflow.key)
```

Add `artifacts: "Mapping[str, artifactsection.Declared] | None" = None` to `render`'s signature, after `environments`. Add the same keyword to `write` and `check`, and pass it through to their `render` calls.

- [ ] **Step 6: `_render_job` writes the steps and the `needs:`**

Change the signature to:

```python
def _render_job(job: Job, *, expanded: Sequence[Step], crossing: "handoff.Handoff",
                artifacts: "Mapping[str, artifactsection.Declared]", manifest: Manifest, product: str,
                workflow: str) -> list[str]:
```

Keep `where = ...` as the first line. Where the cut `derive:` loop stood, build the job's steps from `expanded` and the hand-off; the rest of the function keeps using `steps` as before:

```python
    steps: list[Step] = []
    for at, step in enumerate(expanded):
        for artifact in crossing.downloads.get(at, ()):
            steps.extend(_receive(artifact))
        steps.append(step)
        for artifact in crossing.uploads.get(at, ()):
            steps.extend(_send(artifact, artifacts[artifact].path))
```

Replace `for key, value in job.extras.items():` with `for key, value in _with_needs(job.extras, crossing.needs).items():`.

**A product's typo in `command:` is now caught by `_leaves` in `render`,** before `_render_job`, so its message numbers the step in the expanded list. The old count, from `_render_job`, included the disk preflight when the runner has one, which is not a step the product wrote. No test pins the number (`grep 'step [0-9]'` over `test_workflowgen.py` and `test_tasks_workflows.py` finds none). Keep the new count, and say so in the commit.

- [ ] **Step 7: `workflows.py` passes the declarations**

In `src/simplon/tasks/workflows.py`, at both calls (`workflowgen.write` line 48, `workflowgen.check` line 64), add `artifacts=artifactsection.declared(ctx.manifest_data())`, and import `artifactsection` from `simplon.domain`.

- [ ] **Step 8: Run the new tests, then the old ones**

Run: `PY -m pytest src/tests/test_workflow_handoff.py src/tests/test_handoff.py src/tests/test_workflowgen.py src/tests/test_own_workflows.py src/tests/test_tasks_workflows.py src/tests/test_release_workflow.py -q -p no:cacheprovider`
Expected: all pass. `test_own_workflows.py` passing means simplon's `ci.yml` did not move. Also run `./simplon.sh support workflows --check`: expected rc 0, and `git status --short .github` empty.

- [ ] **Step 9: See it red**

- Remove `"if-no-files-found": "error"` from `_send`: `test_the_producing_job_archives_...` fails.
- Make `_with_needs` return `{**extras, "needs": list(added)}`: both `needs` tests fail.
- In `_send`, use `tar -cf ... -C <parent> <basename>` instead: `test_the_handoff_lines_restore_the_path_and_its_mode` fails (the file lands at the root).
- In `render`, hand `handoff.plan` `{}` instead of the declarations: the first two tests fail (the hand-off is refused for want of a `path:`).
- Make `_with_needs` add `needs: []` when nothing is added (return `{**extras, "needs": [...]}` unconditionally): `test_simplons_own_ci_renders_byte_identical_...` and `test_own_workflows.py` fail.

Restore everything.

- [ ] **Step 10: The census**

Run: `PY -m pytest src/tests/test_refusal_census.py -q -p no:cacheprovider`.
Expected: green. The five raises are in `handoff.plan` and `handoff._acyclic`, reached from `render`, the same way `derive`'s and `resolve_command`'s are, and those are not in the load-time population. **If it goes red,** the test names each raise. Add each one to `CENSUS` as `DIAGNOSIS` with the key it prints, and update the counts on `src/site/content/with-what/rules.md` to the numbers `test_the_page_prints_the_census_count_for_each_kind` prints. Write in the commit which outcome it was.

- [ ] **Step 11: mypy and the full suite, then commit**

Run: `PY -m mypy --config-file mypy.ini src/simplon` (expected `Success`), then the full suite into a file. Expected: green except the three known `test_tasks_docs` failures.

```bash
git add src/simplon/tasks/workflowgen.py src/simplon/tasks/workflows.py src/tests/test_workflow_handoff.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): a generated workflow hands an artifact from the job that makes it to the job that reads it

render computes handoff.plan over every job's expanded steps. The producing job archives the path
with tar into runner.temp and uploads it (if-no-files-found: error); the consuming job needs it,
downloads and unpacks before its first consuming step. The product's own `needs:` stays first.
simplon's ci.yml is byte-identical: it is one job.

The tar lines are run in the tests: path and mode survive, a path nobody wrote fails the pack.
Seen red: <list the breaks from Step 9>. Census: <green, render-time / or the entries added>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: The page, and the measurement rerun

**Files:**
- Modify: `src/site/content/how/manifest.md`: in the `### \`workflows:\`` section, after the `derive:` subsection (the paragraph that ends at about line 875, before the `--check` paragraph at about line 966; find it by the text "A job-level `derive:` would have had to refuse").

- [ ] **Step 1: Write the section**

Insert, as its own paragraphs:

```markdown
**An artifact that crosses a job boundary is handed over** (si#344). Every job starts on a fresh machine, so
a file one job writes is not there for the next. When a command in one job `produces:` an artifact that a
command in another job of the same workflow `consumes:`, the generated file says so itself:

- the producing job archives the artifact's `path:` with `tar` after its last producing step and uploads it
  under the artifact's name;
- the consuming job gets `needs:` on the producing job (after any `needs:` you declared), and downloads and
  unpacks it before its first consuming step.

The archive keeps the path and the file modes, which `upload-artifact` alone does not. Producer and consumer
in one job hand nothing over, and a workflow with no such edge is written exactly as before.

**What cannot be handed over is refused when the workflow is generated,** naming the workflow, the job and
the artifact:

| The workflow would... | Refused because |
|---|---|
| consume an artifact that no job in it produces, and that has no `registry:` | nothing puts it there. A release whose evidence no job writes would be green with no test run |
| consume, in one job, before the step of that job that produces it | the order is yours; the data only checks it |
| consume from an artifact produced in two jobs, or in a matrix job | one run uploads one artifact once |
| hand over an artifact with no `path:` | there is no file. An image stays in one job's docker daemon, so build and use it in one job |
| make two jobs need each other | GitHub refuses the file |

A hand-off between two workflows is not generated: give the artifact a `registry:` and let the body fetch it.
```

- [ ] **Step 2: Build the site**

Run: `./simplon.sh build docs` (Hugo runs only through this command; never a host `hugo`).
Expected: rc 0. Then run `PY -m pytest src/tests -q -p no:cacheprovider -k "docs or site or pages"` and check that it is green apart from the three known `test_tasks_docs` failures.

- [ ] **Step 3: Rerun the measurement**

```bash
D=/tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c4-manifests; mkdir -p $D
for rf in cleon:cleon.yaml biz-cockpit:biz-cockpit.yaml asbundle:asbundle.yaml agile-cockpit:agile-cockpit.yaml secure-windows-images:swi.yaml netctl:netctl.yaml firn:firn.yaml simplon:simplon.yaml; do
  gh api repos/marcozwyssig/${rf%%:*}/contents/${rf#*:} --jq .content | tr -d '\n' | base64 -d > $D/${rf#*:}
done
cat > $D/../c4-render.py <<'EOF'
import sys, pathlib, yaml
sys.path.insert(0, "src/tests")
import realmanifests
from simplon.domain import artifactsection, catalogue, manifest
from simplon.tasks import workflowgen
from simplon.tasks.migrate import migrate_text
for p in sorted(pathlib.Path(sys.argv[1]).glob("*.yaml")):
    raw = p.read_text()
    data = yaml.safe_load(raw)
    if "workflows" not in data:
        print(p.name, "no workflows:"); continue
    text = raw if ("ci" in data or "cd" in data) else migrate_text(raw).text
    try:
        loaded = manifest.load(text, catalogue=catalogue.load(), manifest_path=p.name)
    except ValueError as e:
        print(p.name, "does not load:", str(e)[:120]); continue
    doc = yaml.safe_load(text)
    for w in workflowgen.parse(doc):
        if not w.generated:
            continue
        try:
            out = workflowgen.render(w, manifest=loaded, product=p.stem, source=p.name,
                                     artifacts=artifactsection.declared(doc), environments=doc)
            print(p.name, w.key, "hand-off steps:", out.count("simplon-handoff-"))
        except ValueError as e:
            print(p.name, w.key, "REFUSED:", e)
EOF
./deploy/orchestrator/.venv/bin/python $D/../c4-render.py $D
```

Expected, as on 2026-10-14: `hand-off steps: 0` for biz-cockpit `ci`, simplon `ci`, swi `ci`; firn "does not load" (rule 6, firn's C.3 bill); four products with "no workflows:". **If any live file shows hand-off steps or is refused, stop and report it to Marco before the PR**: that product's file would change at its next bump.

- [ ] **Step 4: Commit**

```bash
git add src/site/content/how/manifest.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
docs(si#344): the manifest page says what crosses a job boundary and what is refused

Measured again before the PR over the eight live manifests: <the output of Task 3 Step 3>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```
