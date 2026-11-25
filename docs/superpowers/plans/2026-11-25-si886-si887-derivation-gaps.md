# si#886 + si#887: two gaps in the derived CI - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The derived CI never runs a `generated:` producer in front of `test:generated` (#886), and never derives a leaf whose task needs a parameter nothing binds (#887).

**Architecture:** Both are decisions in the derivation (`src/simplon/tasks/cipipeline.py`, where leaves are selected and "Left out" is written). #886 leaves the producer out with a named reason. #887 needs to know which task parameters are required: that is new vocabulary, so it is modelled in firn first (`TaskParam.required` in `src/firn/model/simplon/pipeline/pipeline.firn`), set on the catalogue tasks that need it (`src/firn/model/simplon/catalogue/tasks.firn`), regenerated, and read by the derivation.

**Tech Stack:** Python 3.12, firn, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-derived-workflows-design.md` (5.1, 5.2); tickets si#886, si#887 (with the comment on #887 from si#859's final review).

## Global Constraints

- Everything generated goes through firn: new vocabulary is modelled in `.firn`, generated with `./simplon.sh build model`, never hand-edited; `./simplon.sh test generated` green.
- #886 (Marco, 2026-11-25): when the product has a `test:generated` leaf, the derivation leaves out every leaf that is the `by:` of a `generated:` entry, and names it under "Left out" with the reason. simplon's `ci: { skip: }` on `build model` is removed in the same change.
- #887 (ticket): a derived leaf whose task has a required parameter bound neither by the command's `with:` nor by `ci: { params: }` is refused at generation, naming the command, the parameter and the two ways out (`ci: { params: }`, `ci: { skip: }`). Census kind: diagnosis, with its census entry.
- Measured 2026-11-25 over the nine reachable manifests: #886 hits simplon (`build model` before `test generated`) and biz-cockpit (`build export-spec` before `check-contract`, a `test:generated` command). No other product has a `generated:` producer under `ci build`.
- Suite: `deploy/orchestrator/.venv/bin/python -m pytest -q --no-header -p no:cacheprovider <paths>` (no `-n`). No em dash (U+2014); no counts typed into prose; English.

## Review Focus

- A `generated:` entry whose `by:` names a command outside `ci build` (simplon's `support ...` entries): untouched.
- A product with a `generated:` producer and no `test:generated` leaf: the producer still runs (nothing is blinded).
- A required parameter bound through the command's own `with:`: no refusal.
- A leaf the product already skips (`ci: { skip: }`) or that the derivation already leaves out: no refusal for its parameters.
- `test:unit` declared without `with:` (si#859 note on #887): refused.

---

### Task 1: #886, the generated producer leaves the derived CI

**Files:**
- Modify: `src/simplon/tasks/cipipeline.py` (leaf selection, the "Left out" reasons)
- Modify: `simplon.yaml` (remove `ci: { skip: }` from `build model` and its comment's claim; regenerate `.github/workflows/ci.yml`)
- Modify: `src/site/content/how/manifest.md` (the derived CI section: which leaves are left out and why)
- Test: `src/tests/test_cipipeline.py`, `src/tests/test_own_workflows.py`

- [ ] **Step 1: Failing tests:** (a) a synthetic manifest with `generated: { x: { path: ..., by: build x } }`, a `build x` leaf and a `test:generated` leaf: the derived ci.yml does not run `build x` and its "Left out" names it with a reason naming `test:generated` and #886; (b) the same without a `test:generated` leaf: `build x` runs; (c) a `generated:` `by:` outside `ci build`: no effect; (d) `test_own_workflows.py`: simplon's ci.yml still leaves `build model` out, now by the derivation (the manifest carries no `skip` for it).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; remove simplon's `skip`; regenerate (`./simplon.sh support github workflows`, `--check`, `./simplon.sh test generated`).
- [ ] **Step 4:** Docs; full suite.
- [ ] **Step 5:** Commit `fix(si#886): the derived CI leaves a generated: producer out when test:generated would compare its output with itself`.

### Task 2: #887, a required parameter nothing binds is refused at generation

**Files:**
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn` (`TaskParam`: property `required`, boolean, default false, with a comment citing #887)
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (`required = true` on the params a task cannot run without: at least `build:homebrew-formula` `source`, `test:homebrew-formula` `online`, `test:unit` `paths` and `requirements`; walk every catalogue task body and list in the report which params you marked and why, and which you considered and left)
- Regenerate with `./simplon.sh build model`
- Modify: `src/simplon/tasks/cipipeline.py` (the check), `src/tests/test_refusal_census.py` (entry), `src/site/content/with-what/rules.md` if the census page counts follow, `src/site/content/how/manifest.md`
- Test: `src/tests/test_cipipeline.py`

- [ ] **Step 1: Measure first:** over the nine reachable manifests (fetch each through `gh api repos/marcozwyssig/<repo>/contents/<manifest> --jq .content | tr -d "\n" | base64 -d`; manifests: cleon-firn.yaml, firn.yaml, swi.yaml (secure-windows-images), biz-cockpit.yaml, agile-cockpit.yaml, cleon.yaml, asbundle.yaml, netctl.yaml at the repo root; simplon.yaml is local), list every derived leaf the new refusal would hit. Put the table in the report. If a product other than simplon would be refused, the refusal still ships (it is a diagnosis: those leaves fail on every push today), and the report names them so their migration tickets can carry the fix.
- [ ] **Step 2: Failing tests:** (a) a leaf of a task with a required param and no binding: refused at generation naming command, parameter and both ways out; (b) bound by `with:`: renders; (c) bound by `ci: { params: }`: renders; (d) skipped with `ci: { skip: }`: no refusal; (e) `test:unit` without `with:`: refused.
- [ ] **Step 3:** Model, regenerate, implement, census entry (diagnosis).
- [ ] **Step 4:** Docs; full suite.
- [ ] **Step 5:** Commit `feat(si#887): a derived leaf whose task needs a parameter nothing binds is refused at generation`.
