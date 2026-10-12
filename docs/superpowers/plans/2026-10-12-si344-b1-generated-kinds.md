# Part B1: the kinds, generated from the model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `firn gen` writes the artifact-kind vocabulary from simplon's firn model into the kernel's own
`catalogue.yaml` (as a `kinds:` section beside a protected hand-written region) and into a reference
page of the website, and the catalogue loader reads it — with no product noticing anything.

**Architecture:** The firn project root moves from `src/firn/` up to `src/`, so `firn gen` may write into
`src/simplon/` and into the website, which moves from `docs/site/` to `src/site/`. Two firn targets:
`simplon` (writes `catalogue.yaml`, whose 804 hand-written lines live in one protected region) and `site`
(writes `with-what/kinds.md`). `Catalogue` gains a `kinds` field. Every silent-loss path firn v0.1.0 has
(measured: firn#966, two region findings reported 2026-10-12) gets a guard test on simplon's side.

**Tech Stack:** Python 3.11+, PyYAML, pytest; firn v0.1.0 in `ghcr.io/marcozwyssig/firn:v0.1.0` (`.firnt`
templates); Hugo `hugomods/hugo:exts-0.148.2` with the hextra theme.

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md` — part B.2
(the kinds belong to the catalogue), decision 17 (B is generated from the model), part D (the model).
This plan is **B1**, the additive half. **B2** (cut 2: required `kind:` on every artifact, the `images:`
fold, the migration, readers checking kinds, the duplicate-key diagnosis) is a separate plan, written once
netctl, biz-cockpit and agile-cockpit have named their B.4 costs.

**Decisions this plan rests on (Marco, 2026-10-12, by choice list):**
- `firn gen` writes straight into `src/simplon/`; `firn.toml` moves up to `src/`.
- firn's id line stays on (`file_id` is never set to false).
- The kinds go into `catalogue.yaml` itself, which becomes a generated file whose hand-written part is one
  protected region (spec B.2 kept literally).
- The website moves under `src/` (`src/site/`), so firn can write its reference page.
- Two plans: B1 now, B2 after the product costs.

**Measured before writing this plan** (throwaway spikes; reports in the session scratchpad,
`gen/spike-report.md` and `gen/regions-report.md`):
- A `.firnt` template can emit YAML, Python and Markdown (`language html` — `markdown` is E200). Output is
  byte-stable across runs and `--force`.
- Protected region markers in YAML: `# Begin Protected Region [handwritten]` and
  `# End Protected Region  [handwritten]` (TWO spaces after `End`). Wrapping the existing file in them by
  hand and then running `gen` keeps all 804 lines byte-identical (`cmp` empty).
- `gen` over an existing file WITHOUT markers overwrites it silently (rc 0, every line lost).
- Deleting either marker and running `gen` silently wipes the region (819 → 17 lines, rc 0).
- A `kinds` selector that answers nothing leaves `kinds:` empty with rc 0; the region survives as long as
  the `file` block is outside any `for`.
- The wiped file still loads: `catalogue.loads` returns 0 tasks and raises nothing.
- Two targets in one project → no `.firn-cache` at all; one target → `.firn-cache/` beside `firn.toml`.
  **Correction (Task 5, measured): refuted.** With two targets `src/.firn-cache` is still written (`build.bin`,
  `inputs.hash`); the ignore line stays.
- A target with `path = "."` is refused (E105: it overlaps the model folder). Two targets are the way.
- `firn check` does not evaluate templates (rc 0 over a template that fails at `gen`).
- Generated files are written with mode 0600.
- The front matter of a generated Markdown page is its first bytes; the id line is a trailing
  `<!-- ... -->` comment.

## Global Constraints

- **Run the suite** from `src/tests` with `../../deploy/orchestrator/.venv/bin/python -m pytest -q`. There is no `-n`.
- **Gates, all rc 0 before a task is done:** the full suite, `./simplon.sh test typecheck-python`,
  `./simplon.sh test generated` (it diffs against the INDEX, so commit first), and `./simplon.sh test model`.
- **Commits** carry Marco's identity through env vars on every commit:
  `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info"`.
  Pass the message through a quoted heredoc (`git commit -F - <<'EOF'`). It ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG`.
  Never `git config`, never `--amend`, never a force-push.
- **CLAUDE.md house rules:** measure, do not assume; see every new assertion red (break the property, watch
  it fail, restore); report findings rather than patching them away; counts are computed, never typed. The
  hunted defect is an outcome that cannot tell "nothing to do" from "failed".
- **firn image pin:** `ghcr.io/marcozwyssig/firn:v0.1.0`, unchanged. Docker tests use `src/tests/firnrun.py`
  (`firn_rc(project, *argv, cwd="")`) and skip the way the existing firn e2e tests skip.
- **firn names** have no `-` (firn#962). The model spells `test_result` and `release_notes`; every
  generated output spells the kernel's form, `test-result` and `release-notes`, via `.replace("_", "-")`.
- **A model class in a template is named back-quoted and in full:** `` `simplon.pipeline.ArtifactKind` ``.
  The bare name is E302-ambiguous with the M1 package `product.simplon`.
- **Never run `firn gen` against a file without its region markers.** The markers are committed before the
  first `gen` touches the file.
- **Each `file` block in a template stands outside every `for`**, so a selector that answers nothing can
  empty a section but never drop the file or its region.
- **`DEFAULT_SOURCE = "docs/site"` in `src/simplon/tasks/site.py` does not change.** It is every
  product's default (si#183). simplon now names its own `source:` instead.
- **The historical release notes are not rewritten.** `releases.md` mentions `docs/site` in past entries;
  those describe what was true then.
- **Product manifests under `src/tests/fixtures/` are not touched.** Their `docs/site` is the product's own.

## Review Focus

1. **A region marker deleted or reworded by hand.** firn wipes 804 lines with rc 0. Expected: red in the
   suite, before any `gen` runs. Pinned in Task 3 (marker-pair test, task-count test).
2. **A `kinds` selector that answers nothing** (a typo, or firn#963's unchecked selectors). Expected: red,
   not an empty `kinds:`. Pinned in Task 3 (every model kind appears) and Task 4 (`kinds:` present but
   empty is a diagnosis).
3. **A catalogue that has silently lost its tasks still loads.** Expected: a refusal naming the file. Pinned
   in Task 4 (`catalogue.loads` refuses zero tasks).
4. **firn's 0600 file mode reaching the wheel.** A root-installed package whose `catalogue.yaml` only root
   can read breaks every non-root user. Expected: the wheel's `catalogue.yaml` is world-readable. Measured
   and pinned in Task 3.
5. **The generated page breaks the site build or renders the id comment as text.** Expected: Hugo builds,
   and the page lists every kind. Measured in Task 5.

---

## File Structure

- `src/site/` (moved from `docs/site/`) — the Hugo website. Only its location changes.
- `src/firn.toml` (moved from `src/firn/firn.toml`) — the firn project root, with two targets.
- `src/firn/templates/catalogue.firnt` — new. Writes `src/simplon/catalogue.yaml`.
- `src/firn/templates/docs.firnt` — new. Writes `src/site/content/with-what/kinds.md`.
- `src/simplon/catalogue.yaml` — becomes generated: a `kinds:` section, then the protected region.
- `src/simplon/catalogue.py` — `Catalogue.kinds`; `loads` reads and checks it, and refuses zero tasks.
- `simplon.yaml` — `website: source:`, the paths into the site, `cwd: src` for both model commands,
  `generated:` entries for the two firn outputs.
- `pyproject.toml` — `exclude` gains `site*`.
- `.gitignore` — paths follow the moves.
- Tests: `src/tests/test_generated_catalogue.py` (new), `src/tests/test_catalogue.py`, the firn e2e tests,
  the site tests that name `docs/site`.

---

### Task 1: The website moves to `src/site/`

**Files:**
- Move: `docs/site/` → `src/site/` (`git mv`)
- Modify: `simplon.yaml` (lines 49-68, 94-100, 338, 357-359, 362-369, 435, 485 as measured on main
  ef3c75c), `.gitignore:25-35`, `src/site/go.mod:13` (the module path), `pyproject.toml`
  (`[tool.setuptools.packages.find] exclude`)
- Modify, path strings only: `src/tests/sitepages.py`, `src/tests/test_product_manifest.py:63-69`,
  `src/tests/test_tasks_acceptance.py:71-93`, `tests/acceptance/generated-documents.feature:16-34`,
  `src/simplon/tasks/acceptance.py:742`, plus every other hit of
  `git grep -n "docs/site" -- ':!src/tests/fixtures' ':!docs/superpowers' ':!src/site/content/when/releases.md'`
  that names simplon's own site
- Test: existing site tests; `src/tests/test_wheel.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the website at `src/site/`, so `src/site/content/with-what/` exists for Task 5. simplon.yaml
  declares `website: source: src/site`.

- [ ] **Step 1: Measure the population before moving anything**

Run: `git grep -n "docs/site" -- ':!src/tests/fixtures' ':!docs/superpowers' > /tmp/before.txt; wc -l /tmp/before.txt`
Sort each hit into: (a) simplon's own site path → moves; (b) the kernel DEFAULT (`site.py:90`, its
docstring, and tests asserting the default for a manifest with no `source:`) → stays; (c) historical
release-note prose → stays. Write the three lists into the task report. A hit you cannot place in one of
them is a finding for the report, not something to guess.

- [ ] **Step 2: Write the failing tests**

In `src/tests/test_product_manifest.py`, the test at lines ~60-69 asserts that simplon's manifest leaves
`source:` out and lands on the `docs/site` default. Replace it with a test that pins the new statement:

```python
def test_simplon_names_its_own_site_source_and_the_default_is_unchanged():
    # arrange: simplon's site moved under src/ (si#344 B1) so firn can write into it. The DEFAULT stays
    # `docs/site`, because it is every product's (si#183); simplon now names its path instead.
    from simplon.tasks import site
    data = yaml.safe_load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # act
    declared = data["website"].get("source")

    # assert
    assert declared == "src/site"
    assert site.DEFAULT_SOURCE == "docs/site"
    assert (ROOT / declared / "hugo.yaml").is_file()
```

Use whatever `ROOT`/`yaml` imports the module already has. Keep a separate test that a manifest with no
`source:` still resolves to `docs/site`, if `test_tasks_site.py:213` does not already pin it (it does
today; leave it).

In `src/tests/test_wheel.py`, no new test: `test_the_wheel_installs_nothing_beside_simplon` already turns
red if `src/site/` ships.

- [ ] **Step 3: Run the tests and see them fail**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_product_manifest.py -k site`
Expected: FAIL (`source` is absent today).

- [ ] **Step 4: Move and repoint**

```bash
git mv docs/site src/site
```

Then:
- In `simplon.yaml`: add `source: "src/site"` under `website:`, with a comment that says why simplon names
  it now (firn writes into the site; the default stays `docs/site` for every other product), and that
  simplon is therefore no longer the first consumer of the default. Remove or rewrite the comment at line
  ~338 that says it is. Repoint `output: docs/site/content/with-what/commands.md` and
  `.../acceptance.md` and `page: "docs/site/content/when/releases.md"` to `src/site/...`. Rewrite the
  comments that name `docs/site` as simplon's site.
- `.gitignore`: every `docs/site/...` line becomes `src/site/...`.
- `src/site/go.mod:13`: `module github.com/marcozwyssig/simplon/src/site`. Then check whether `go.sum` or
  `hugo.yaml` names the module path, and change it there too if they do.
- `pyproject.toml`: `exclude = ["tests*", "firn*", "site*"]`, with one comment line: the site moved under
  `src/` in si#344 B1, and `test_wheel.py` holds the property.
- Every list (a) hit from Step 1.

- [ ] **Step 5: Run the tests, the wheel test and the website build**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q`
Expected: all pass. If `test_wheel.py` goes red naming `site`, the exclude is missing or wrong.

Then build the site the way CI does and check it actually renders. Find the command placed on `docs:site`
in simplon.yaml (`./simplon.sh build site` or similar; measure, don't guess). Run it and record its rc and
the page count Hugo reports. Expected: rc 0, and the same page count as on main before the move. Build main
once first to get that number. A changed count is a finding.

- [ ] **Step 6: Gates and commit**

Run the four gates. `test generated` will regenerate the CI workflow; if it differs, regenerate with
`./simplon.sh support workflows` and commit that too. Then:

```bash
git add -A src/site docs simplon.yaml .gitignore pyproject.toml src/tests tests src/simplon
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
refactor(si#344): simplon's website moves to src/site

firn may only write below its project root, and the kinds reference page
is generated (B1). The kernel's default stays docs/site for every other
product; simplon now names its own source.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: The firn project root moves to `src/`

**Files:**
- Move: `src/firn/firn.toml` → `src/firn.toml`
- Modify: `simplon.yaml` (`build model` and `test model`: `cwd: src/firn` → `cwd: src`, plus their
  comments), `.gitignore:45-48`
- Modify: `src/tests/test_firn_pipeline_e2e.py`, `src/tests/test_manifestmodel_e2e.py`,
  `src/tests/test_toolchain_firn_e2e.py` (project root and `cwd`), and `src/simplon/manifestmodel.py`'s
  comment if it names `src/firn/` as the project
- Test: those three e2e files

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a firn project whose root is `src/`, `model = ["firn/model"]`,
  `templates = ["firn/templates"]`, and a single target `[target.gen] path = "firn/gen"` until Task 3
  replaces it.

- [ ] **Step 1: Write the new `src/firn.toml`**

```toml
# simplon's own firn project (si#371): the delivery pipeline as a model firn can check and generate from
# (si#344, si#346). Its root is src/ rather than src/firn/ since si#344 B1, because firn writes only
# below its root and the generated kinds land in src/simplon/ and src/site/. `./simplon.sh test model`
# runs `firn check` here and `./simplon.sh build model` runs `firn gen`, both in the pinned firn image.
name = "simplon"
model = ["firn/model"]
templates = ["firn/templates"]

# Until a template exists: a target that cannot touch anything simplon commits.
[target.gen]
path = "firn/gen"
```

Then `git rm src/firn/firn.toml` and `mkdir -p src/firn/templates` (git keeps no empty folder; Task 3 adds
the first template. If firn refuses a missing template folder, measure that and put a `.gitkeep` there).

- [ ] **Step 2: Repoint the commands and the ignore file**

`simplon.yaml`: in both `model:` commands, `cwd: src`, and comments saying "Started in src/, where
firn.toml is." `.gitignore`: `src/.firn-cache/` and `src/firn/gen/`, with the comment updated.

- [ ] **Step 3: Repoint the e2e tests and see them red first**

Run the three e2e files BEFORE editing them:
`cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_firn_pipeline_e2e.py test_manifestmodel_e2e.py test_toolchain_firn_e2e.py`
Expected: FAIL (they start firn in `src/firn`, which has no `firn.toml` any more). Record which fail and
how. If none fails, the tests did not depend on the project root, and that is a finding for the report.

Then edit them. Where a test copies `src/firn` into `tmp_path`, it now copies `src/firn.toml` and
`src/firn/` into `tmp_path` (the same relative layout), and runs firn with `cwd=""`, the copy's root.
Where a test points `cwd` at `src/firn`, it becomes `src`. Every `ignore=` that skips `.firn-cache` and
`gen` keeps doing so at the new paths.

- [ ] **Step 4: Run and see them green; run the gates**

Run the three files, then the four gates. `./simplon.sh test model` must answer rc 0 from the new root;
`./simplon.sh build model` must answer rc 0 and write nothing outside `src/firn/gen/`
(`git status --porcelain` empty).

- [ ] **Step 5: Commit**

```bash
git add -A src/firn.toml src/firn simplon.yaml .gitignore src/tests src/simplon/manifestmodel.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
refactor(si#344): the firn project root moves up to src/

firn writes only below the folder holding firn.toml, and B1 generates into
src/simplon/ and src/site/. Model and templates stay under src/firn/.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: `catalogue.yaml` becomes generated, its hand-written part a protected region

**Files:**
- Modify: `src/simplon/catalogue.yaml` (markers first, in a commit of their own; then the generated part)
- Create: `src/firn/templates/catalogue.firnt`
- Modify: `src/firn.toml` (target `simplon` replaces `gen`), `simplon.yaml` (`build model` comment;
  `generated:` entry), `.gitignore` (`src/firn/gen/` goes; `src/.firn-cache/` stays, since one target
  means a cache)
- Create: `src/tests/test_generated_catalogue.py`
- Test: `src/tests/test_wheel.py` (file mode)

**Interfaces:**
- Consumes: Task 2's project root `src/`.
- Produces: `src/simplon/catalogue.yaml` opening with a generated `kinds:` mapping,
  `<kind>: {}` or `<kind>: { refines: <kind> }` with kernel spellings (`test-result`, `release-notes`),
  then `# Begin Protected Region [handwritten]`, the 804 hand-written lines, then
  `# End Protected Region  [handwritten]`, then firn's id line. Task 4 reads the `kinds:` mapping.

- [ ] **Step 1: Seed the markers by hand, and prove nothing moved**

```bash
cp src/simplon/catalogue.yaml /tmp/catalogue.orig
{ echo '# Begin Protected Region [handwritten]'; cat /tmp/catalogue.orig; echo '# End Protected Region  [handwritten]'; } > src/simplon/catalogue.yaml
awk '/^# Begin Protected Region \[handwritten\]$/{f=1;next} /^# End Protected Region  \[handwritten\]$/{f=0} f' src/simplon/catalogue.yaml | cmp - /tmp/catalogue.orig && echo IDENTICAL
```

Expected: `IDENTICAL`. Run the full suite (the markers are YAML comments; nothing may change) and commit
this alone, so the adoption is one reviewable diff of two added lines:

```bash
git add src/simplon/catalogue.yaml
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
chore(si#344): catalogue.yaml's hand-written content becomes one protected region

Two comment lines, nothing else. They must be in the file before firn's
first gen touches it: firn v0.1.0 overwrites an unmarked file with rc 0.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

- [ ] **Step 2: Write the failing guard tests**

Create `src/tests/test_generated_catalogue.py`:

```python
"""si#344 B1: the kernel's catalogue is written by firn, and firn v0.1.0 loses data with rc 0.

Measured on v0.1.0, 2026-10-12: a deleted region marker wipes the hand-written region (819 -> 17 lines,
rc 0), and a `kinds` selector that answers nothing writes an empty `kinds:` (rc 0). Neither is visible to
firn, so both are visible here. These run on the committed file, without docker, so they hold in every
environment the suite runs in.

AAA; the name states the behaviour under test.
"""
import re
from pathlib import Path

import yaml

from simplon import catalogue

CATALOGUE = Path(catalogue.__file__).resolve().parent / "catalogue.yaml"
KINDS_MODEL = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "vocabulary" / "kinds.firn"
BEGIN = "# Begin Protected Region [handwritten]"
END = "# End Protected Region  [handwritten]"


def _lines() -> list[str]:
    return CATALOGUE.read_text(encoding="utf-8").splitlines()


def test_the_hand_written_region_is_marked_exactly_once_and_in_order():
    # arrange / act
    lines = _lines()

    # assert: a lost marker makes the next `firn gen` discard everything between them, silently
    assert lines.count(BEGIN) == 1, "the Begin marker is missing or doubled"
    assert lines.count(END) == 1, "the End marker is missing or doubled"
    assert lines.index(BEGIN) < lines.index(END)


def test_the_region_carries_the_task_tree():
    # arrange
    lines = _lines()
    region = "\n".join(lines[lines.index(BEGIN) + 1:lines.index(END)])

    # act
    data = yaml.safe_load(region) or {}

    # assert: the region is where the tasks and groups live - not merely non-empty
    assert set(data) >= {"groups", "tasks"}, sorted(data)
    assert data["tasks"], "the region holds no tasks"


def test_every_kind_in_the_model_is_in_the_generated_section():
    # arrange: the kernel's spelling of a firn name (firn#962: a firn name has no `-`)
    model = re.findall(r"^(\w+) typeOf simplon\.pipeline\.ArtifactKind", KINDS_MODEL.read_text(), re.M)
    expected = {name.replace("_", "-") for name in model}

    # act
    kinds = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")).get("kinds") or {}

    # assert: an empty selector writes `kinds:` with rc 0, so the set must be compared, not just present
    assert len(model) > 0, "the model regex found no kinds - this test would pass over nothing"
    assert set(kinds) == expected


def test_the_generated_section_says_where_to_edit():
    # arrange
    lines = _lines()

    # act
    head = "\n".join(lines[:lines.index(BEGIN)])

    # assert: an edit outside the region is overwritten by the next gen without warning (firn#921)
    assert "kinds.firn" in head and "protected region" in head.lower()
```

- [ ] **Step 3: Run them and see which fail, and why**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_generated_catalogue.py`
Expected: the marker and region tests PASS (Step 1 put the markers in); the kinds test and the header test
FAIL (no `kinds:` yet). Then see the passing two red as well: delete the End marker in the working tree,
run, watch the first test fail; restore with `git checkout src/simplon/catalogue.yaml`. Do the same for
the region test by deleting the `tasks:` key line inside the region. Record both in the report.

- [ ] **Step 4: Write the template and the target**

`src/firn/templates/catalogue.firnt`:

```
template Catalogue {

  // The kernel's catalogue (src/simplon/catalogue.yaml). The `kinds:` section is generated from
  // simplon.vocabulary (spec B.2); everything else is hand-written and lives in the protected region.
  // The `file` block stands outside every `for`, so a selector that answers nothing can empty `kinds:`
  // but never drop the file or its region.
  file "catalogue.yaml" language yaml {
    |# GENERATED from src/firn/model/simplon/vocabulary/kinds.firn by `./simplon.sh build model`.
    |# Edit only inside the protected region below: firn rewrites everything outside it on every run.
    |kinds:
    for k : `simplon.pipeline.ArtifactKind` {
      if k.refines {
        |  ${k.name.replace("_", "-")}: { refines: <<for r : k.refines sep ", ">>${r.name.replace("_", "-")}<<end>> }
      }
      if not k.refines {
        |  ${k.name.replace("_", "-")}: {}
      }
    }
    |
    protected "handwritten" {
    |# (the hand-written catalogue: groups and tasks)
    }
  }
}
```

`src/firn.toml`: replace `[target.gen]` with

```toml
# The kernel's catalogue. Its hand-written part is one protected region, which firn keeps.
[target.simplon]
path = "simplon"
templates = ["Catalogue"]
```

Check `src/firn.toml`'s top comment still says what is true.

Note on `refines`: the model declares it `0..N`. Every kind refines at most one today. If the YAML a
kind with two parents would get (`{ refines: a, b }`) matters, it is Task 4's diagnosis that catches it,
not the template.

- [ ] **Step 5: Generate and inspect**

Run: `./simplon.sh build model; echo rc=$?` then `git diff --stat src/simplon/catalogue.yaml` and
`git diff src/simplon/catalogue.yaml | head -40`.
Expected: rc 0. The diff is ONLY added lines above the Begin marker plus the id line at the end. Prove it:

```bash
git diff -U0 src/simplon/catalogue.yaml | grep '^-[^-]' && echo "LINES REMOVED - STOP" || echo "insert-only"
```

Then run Step 1's `awk | cmp` against `/tmp/catalogue.orig` again. Expected: `IDENTICAL`. If either
check fails, stop and report; do not repair by hand.

Measure the file mode: `stat -c %a src/simplon/catalogue.yaml`. Record it (the spike measured 0600).

- [ ] **Step 6: Pin the wheel's file mode**

Add to `src/tests/test_wheel.py`:

```python
def test_the_catalogue_in_the_wheel_is_readable_by_everyone(wheel):
    """firn writes its output 0600 (measured on v0.1.0). A wheel that carries that mode installs a
    catalogue only its installer can read, and every other user's first command fails to load it."""
    # arrange
    info = zipfile.ZipFile(wheel).getinfo("simplon/catalogue.yaml")

    # act
    mode = (info.external_attr >> 16) & 0o777

    # assert
    assert mode & 0o044 == 0o044, oct(mode)
```

Run it. If it is RED with the 0600 from Step 5, that is the defect the Review Focus names: report the
measured mode, then make it green by changing the mode where it is set. Order of preference: (1) the
`build model` placement gets a step after `gen` that sets 0644 on the two generated files, if
`toolchain:run` or an existing kernel task can do that; (2) failing that, stop and report, because the fix
then belongs in the kernel and is a controller decision. If it is GREEN with 0600 on disk, find out why
(setuptools may normalise modes) and record that; the test stays as the guard either way. Then see it red:
`chmod 600` the file, rebuild, watch it fail (if setuptools normalises, record that it cannot go red
locally and why).

- [ ] **Step 7: Register the outputs and run everything**

`simplon.yaml` `generated:`:

```yaml
  # The kernel's catalogue (si#344 B1): its `kinds:` section is generated by firn from
  # src/firn/model/simplon/vocabulary/kinds.firn; the rest is a protected region firn keeps.
  catalogue:
    path: src/simplon/catalogue.yaml
    by: build model
```

Rewrite the `build model` comment: it now writes the catalogue's `kinds:`.

Run: the full suite and the four gates. `test generated` regenerates the catalogue through `build model`
and diffs it against the index, so commit first, then run it.

- [ ] **Step 8: Commit**

```bash
git add src/simplon/catalogue.yaml src/firn src/firn.toml simplon.yaml .gitignore src/tests
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#344): firn writes the catalogue's kinds from the model

catalogue.yaml opens with a generated kinds: section (spec B.2); its
hand-written part is the protected region seeded in the previous commit.
Guards for what firn v0.1.0 loses silently: the marker pair, the task
tree inside the region, and every model kind in the section.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 4: The catalogue loader reads the kinds

**Files:**
- Modify: `src/simplon/catalogue.py` (the `Catalogue` NamedTuple and `loads`)
- Test: `src/tests/test_catalogue.py`

**Interfaces:**
- Consumes: Task 3's `kinds:` mapping in `catalogue.yaml`.
- Produces: `Catalogue.kinds: dict[str, str]`, each kind mapped to the one kind it refines, `""` for the
  root. B2's kind checks and Task 5's page test read it.

- [ ] **Step 1: Write the failing tests**

Append to `src/tests/test_catalogue.py` (use its existing import of `catalogue` and `pytest`):

```python
def test_the_kernels_catalogue_offers_the_model_kinds_each_reaching_artifact():
    # arrange / act
    kinds = catalogue.load().kinds

    # assert: one root, and every refines chain ends there (spec B.2)
    assert [k for k, parent in kinds.items() if not parent] == ["artifact"]
    for kind in kinds:
        seen, at = set(), kind
        while kinds[at]:
            assert at not in seen
            seen.add(at)
            at = kinds[at]
        assert at == "artifact"
    assert kinds["site"] == "directory" and kinds["test-result"] == "artifact"


def test_a_catalogue_without_kinds_still_loads_with_none():
    # arrange: every stub catalogue the suite builds through loads() carries no kinds
    text = "tasks:\n  a:b: { impl: m:f }\n"

    # act / assert
    assert catalogue.loads(text).kinds == {}


@pytest.mark.parametrize("text, fragment", [
    ("kinds:\ntasks:\n  a:b: { impl: m:f }\n", "'kinds' is declared but empty"),
    ("kinds: [image]\ntasks:\n  a:b: { impl: m:f }\n", "'kinds' must be a mapping"),
    ("kinds:\n  artifact: {}\n  image: { refines: nope }\ntasks:\n  a:b: { impl: m:f }\n",
     "kind 'image' refines 'nope', which the catalogue does not declare"),
    ("kinds:\n  artifact: {}\n  image: { refines: [artifact, artifact] }\ntasks:\n  a:b: { impl: m:f }\n",
     "kind 'image' must refine exactly one kind"),
    ("kinds:\n  a: { refines: b }\n  b: { refines: a }\ntasks:\n  a:b: { impl: m:f }\n",
     "refines in a circle"),
    ("kinds:\n  artifact: {}\n  other: {}\ntasks:\n  a:b: { impl: m:f }\n",
     "exactly one root kind"),
])
def test_a_broken_kinds_section_is_refused_with_the_place(text, fragment):
    # act / assert
    with pytest.raises(ValueError, match=re.escape(fragment)):
        catalogue.loads(text)


def test_a_catalogue_that_lost_its_tasks_is_refused():
    # arrange: what firn v0.1.0 leaves when a region marker goes missing (measured 2026-10-12)
    text = "kinds:\n  artifact: {}\n"

    # act / assert: before, this loaded as a catalogue offering nothing
    with pytest.raises(ValueError, match="declares no tasks"):
        catalogue.loads(text)
```

Add `import re` if the module lacks it.

Before writing the last test, measure: does any existing test or product path call
`catalogue.loads` with a text that has NO tasks on purpose? `grep -rn "loads(" src/tests src/simplon`.
If one does, the zero-tasks refusal is a rule with a cost, and you stop and report the callers instead of
changing them.

- [ ] **Step 2: Run them and see them fail**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_catalogue.py`
Expected: FAIL — `Catalogue` has no `kinds`, and nothing refuses.

- [ ] **Step 3: Implement**

In `src/simplon/catalogue.py`, add the field after `groups` (a default keeps every existing
`Catalogue(...)` construction valid):

```python
    # The artifact kinds (spec B.2): each kind mapped to the one kind it refines, "" for the root. The
    # section is GENERATED from simplon's firn model (si#344 B1); a product cannot declare kinds.
    kinds: dict[str, str] = {}
```

In `loads`, after the `groups` check:

```python
    kinds = _kinds(data)
```

then `if not out: raise ValueError("catalogue declares no tasks - a catalogue that offers nothing is a broken file, not an empty platform")`
after the task loop, and `kinds=kinds` in the `return`. Add:

```python
def _kinds(data: dict) -> dict[str, str]:
    """The `kinds:` section as {kind: parent}. Absent is a catalogue without kinds (every stub the suite
    builds); present-but-empty is what firn writes when its selector answers nothing, so it is refused."""
    if "kinds" not in data:
        return {}
    raw = data["kinds"]
    if raw is None or raw == {}:
        raise ValueError("catalogue 'kinds' is declared but empty")
    if not isinstance(raw, dict):
        raise ValueError("catalogue 'kinds' must be a mapping of kind name to its declaration")
    out: dict[str, str] = {}
    for kind, spec in raw.items():
        parent = (spec or {}).get("refines", "")
        if not isinstance(parent, str):
            raise ValueError(f"catalogue kind '{kind}' must refine exactly one kind, got {parent!r}")
        out[str(kind)] = parent
    for kind, parent in out.items():
        if parent and parent not in out:
            raise ValueError(f"catalogue kind '{kind}' refines '{parent}', which the catalogue does not declare")
    # The circle first: a circle has no root either, and "no root" would send the reader to the wrong line.
    for kind in out:
        seen, at = set(), kind
        while out[at]:
            if at in seen:
                raise ValueError(f"catalogue kinds refines in a circle through '{kind}'")
            seen.add(at)
            at = out[at]
    roots = [kind for kind, parent in out.items() if not parent]
    if len(roots) != 1:
        raise ValueError(f"catalogue kinds need exactly one root kind, found {roots}")
    return out
```

Check the messages against the test fragments; the test fragments are the second source, so one of the
two changes until they agree, and you say which.

Note: the circle case has no root either. The code above checks the circle first so that message is the
one the reader gets; keep that order.

- [ ] **Step 4: Run them green, see each red**

Run `test_catalogue.py`. Then for each refusal, break its `raise` (comment it out), watch its parameter
fail, restore. Then run the full suite: the census (`test_refusal_census.py`) decides whether these
refusals are in its population. If it goes red, classify each as `DIAGNOSIS` in `CENSUS`, update the counts
on `src/site/content/with-what/rules.md` by hand to what the census computes, and say so in the report. If
it stays green, say that too, and why (the catalogue is not reached from the two manifest seams).

- [ ] **Step 5: Gates and commit**

```bash
git add src/simplon/catalogue.py src/tests src/site
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#344): the catalogue loader reads the kinds, and refuses an empty catalogue

Catalogue.kinds maps each kind to the one it refines. A declared-but-empty
kinds: and a catalogue with no tasks are refused: both are what firn
v0.1.0 leaves behind with rc 0 when it loses data.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 5: The kinds reference page, generated into the website

**Files:**
- Create: `src/firn/templates/docs.firnt`
- Modify: `src/firn.toml` (second target), `.gitignore` (`src/.firn-cache/` goes: two targets write no
  cache, measured), `simplon.yaml` (`generated:` entry, `build model` comment)
- Create: `src/site/content/with-what/kinds.md` (generated, committed)
- Test: `src/tests/test_generated_catalogue.py` (append)

**Interfaces:**
- Consumes: Task 1's `src/site/`, Task 3's project and template folder, Task 4's `Catalogue.kinds`.
- Produces: `src/site/content/with-what/kinds.md`.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_generated_catalogue.py`:

```python
PAGE = Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "kinds.md"


def test_the_reference_page_lists_every_kind_the_catalogue_offers_and_what_it_refines():
    # arrange
    kinds = catalogue.load().kinds
    text = PAGE.read_text(encoding="utf-8")

    # act
    rows = dict(re.findall(r"^\| `([\w-]+)` \| `?([\w-]*)`? \|", text, re.M))

    # assert: the page and the loader read the same model, so they agree or one of them is stale
    assert text.startswith("---\n"), "Hugo needs the front matter as the first bytes"
    assert rows == {k: v for k, v in kinds.items()}
```

- [ ] **Step 2: Run it and see it fail**

Expected: FAIL (`kinds.md` does not exist).

- [ ] **Step 3: Write the template and the target**

`src/firn/templates/docs.firnt`:

```
template Docs {

  // The kinds reference page of the website (spec B.2). `language html`: firn has no markdown language
  // (E200 on v0.1.0), and html gives the id line as an html comment. A line starting with `|` in the
  // output needs `||`, because the first `|` is the template's output marker.
  file "kinds.md" language html {
    |---
    |title: "Artifact kinds"
    |weight: 6
    |---
    |
    |GENERATED from `src/firn/model/simplon/vocabulary/kinds.firn` by `./simplon.sh build model`.
    |
    |An artifact names its kind; a port accepts a kind and every kind that refines it.
    |
    || Kind | Refines |
    ||---|---|
    for k : `simplon.pipeline.ArtifactKind` {
      if k.refines {
        || `${k.name.replace("_", "-")}` | <<for r : k.refines sep ", ">>`${r.name.replace("_", "-")}`<<end>> |
      }
      if not k.refines {
        || `${k.name.replace("_", "-")}` |  |
      }
    }
  }
}
```

Before choosing `weight: 6`, read the `weight:` of every page in `src/site/content/with-what/` and pick
the next free one after `rules.md` (5). Say what you chose.

`src/firn.toml`, add:

```toml
# The kinds reference page of the website.
[target.site]
path = "site/content/with-what"
templates = ["Docs"]
```

- [ ] **Step 4: Generate, inspect, build the site**

Run `./simplon.sh build model; echo rc=$?`. Expected: rc 0; `kinds.md` exists; `git status` shows no
other file changed except `catalogue.yaml`'s id line if it changes with the target set (measure it).
Confirm `src/.firn-cache` is gone after this run (two targets); if it remains, keep the ignore line and
say so.

Then build the website (the command found in Task 1, Step 5) and check the built page: the table renders,
and the id comment is not visible text. Find the page in the build output and grep for `Generated by firn`;
expected: either absent or inside `<!-- -->`. Record the result.

- [ ] **Step 5: Register, see red, run everything**

`simplon.yaml` `generated:`:

```yaml
  # The kinds reference page (si#344 B1), generated by firn beside the catalogue's kinds.
  kinds-page:
    path: src/site/content/with-what/kinds.md
    by: build model
```

See the page test red: change one `refines` in `kinds.firn` (for example `site` refines `artifact`), run
`./simplon.sh build model`, and the test should still be GREEN, because page and catalogue move together.
That is correct: it shows the page follows the model. Then edit `kinds.md` by hand to drop one row and
watch the page test go RED. Restore both with `git checkout`.

Run the full suite and the four gates.

- [ ] **Step 6: Commit**

```bash
git add src/firn src/firn.toml src/site/content/with-what/kinds.md simplon.yaml .gitignore src/tests
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#344): the website's kinds reference page is generated from the model

One model, three readers: the catalogue's kinds:, Catalogue.kinds, and
this page. test generated holds the page against the model, and a test
holds it against the loader.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 6: The spec and the docs say what was built

**Files:**
- Modify: `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md` (B.2, D.3,
  and the order-of-work table)
- Modify: whatever page under `src/site/content/` describes the catalogue file or the firn project
  location, if any (`grep -rn "src/firn/firn.toml\|catalogue.yaml" src/site/content`, excluding
  `releases.md`)

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: text only.

- [ ] **Step 1: Update the spec**

- **B.2:** the kinds section is now generated by firn into `catalogue.yaml`, and the hand-written part is a
  protected region. List the measured firn v0.1.0 hazards (unmarked file overwritten; lost marker wipes the
  region; empty selector writes an empty section; 0600) and the guard each one has, by test name.
- **D.3:** the project root is `src/`, there are two targets, and the website is at `src/site/`.
- **The order table:** B is split into B1 (this plan, additive, ships in the next release) and B2 (cut 2,
  waits for the B.4 costs).

- [ ] **Step 2: Run the suite (site-page tests read some of this text), then commit**

```bash
git add docs src/site
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
docs(si#344): the spec says what B1 built, and what firn's hazards cost

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```
