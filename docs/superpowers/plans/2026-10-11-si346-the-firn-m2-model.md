# The firn M2 model (si#344 part D, si#346) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** simplon's manifest becomes a firn model. There are three parts:
- the M2 packages `simplon.pipeline` and `simplon.manifest`;
- the kernel's own vocabulary as an M1 model;
- a bridge, `support manifest model`, that writes any validated manifest as an M1 `.firn` file.

A drift gate then checks simplon's own exported model with `firn check` in CI.

**Architecture:**
- **Where the models live.** All `.firn` files live in simplon's firn project at `src/firn/`, which si#371 created. Paths under `model/` follow the package names, as firn requires.
- **The bridge** is a pure Python function `simplon.manifestmodel.export(manifest, document, product) -> str`. It reads the validated `Manifest` and the raw document, and it never re-validates.
- **The command.** The catalogue task `support:model` wraps it, and the catalogue places it under `support manifest` beside `migrate`.
- **simplon's own export** is committed at `src/firn/model/product/simplon/simplon.firn`:
  - it is registered in `generated:`, so `test generated` catches drift;
  - `test model` (si#371) runs `firn check` over it with the M2.

**Tech Stack:**
- Python 3.12 and the kernel's own modules (`simplon.orchestrator.manifest`, `simplon.context`, `simplon.outputs`);
- firn v0.1.0 (`ghcr.io/marcozwyssig/firn:v0.1.0`) through `toolchain:run`;
- pytest, with docker-gated end-to-end tests that use `conftest.docker_is_usable`.

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md`, part D and decisions 10 and 17.

## Global Constraints

- **firn version and names.** firn is pinned at `ghcr.io/marcozwyssig/firn:v0.1.0`, and nothing in this plan names a moving tag. A firn name is `[A-Za-z_][A-Za-z0-9_]*` in ASCII (firn docs/03 §2). A name with `-` or `.` has to be mangled, and the original kept as a string.
- **Package directories.** The directory under a model folder must match the package name: package `simplon.pipeline` lives at `src/firn/model/simplon/pipeline/` (firn docs/03 §7).
- **Associations and selectors.**
  - Every `firn.core.Association` declares both `subjectCardinality` and `objectCardinality`. firn v0.1.0 refuses one without the other (E004, measured 2026-10-11).
  - `owner` in a selector is a function, `owner()`. `firn check` does **not** validate a SelectorRelation's selector: a misspelt property passes rc 0 and answers empty (measured 2026-10-11, reported to firn). Every SelectorRelation in this plan therefore has a docker test that asserts its **non-empty** expected value.
- **Two firn tickets lie on this plan's path.** firn will close both from its Wave 1 (from 2026-10-13); until then this plan works around them, and each workaround names its ticket in a comment, so it can be removed when the ticket ships:
  - **firn#963:** `SelectorRelation.selector` is a plain Attribute in `core.firn`, so neither E302 nor E012 checks it. The workaround is Task 1's non-empty-answer tests, which firn itself recommends.
  - **firn#962:** a name may contain `-`. The workaround is Task 5's `mangle`, with the original kept in `key`.
- **firn exit codes** are 0 clean, 1 model wrong, 2 usage, 3 no project and 70 internal. A gate compares against 0 and never against 1.
- **Spec D.1:** the bridge exports **after** `manifest.load` has accepted the manifest. A refused manifest produces no model and keeps the refusal's rc.
- **No YAML importer in firn.** simplon owns the parse and the validation (spec D.2).
- **Product-owned sections are never modelled.** Each is one opaque `ProductData` entry, holding its key only (spec D.1).
- **The CLI does not change**, except for the new placed command `support manifest model`.
- **Commits** are written by Marco's identity through env vars, and their messages go through a quoted heredoc.

## Review Focus

1. **A command, group, task or environment whose name is not a firn name.** Examples: `typecheck-python`, `release-notes`, a coordinate `build:image`. The expected behaviour is that it exports under a mangled name and keeps the original in `key`. Two originals that mangle to the same name are refused by name. Pinned in Task 5 (`test_names_that_mangle_alike_are_refused_naming_both`).
2. **A product with a section the kernel does not read** (asbundle `jdk:`, netctl `topology:`). The expected behaviour is a `ProductData` entry with the key and nothing else, so the model never claims to understand it. Pinned in Task 5 (`test_a_product_section_is_opaque_product_data`).
3. **A SelectorRelation that silently answers empty.** The expected behaviour is a red test, not a green check. Pinned in Task 1 (`test_every_selector_relation_answers_what_the_fixture_says`), and seen red with a misspelt selector.
4. **`support manifest model` on a product whose output directory does not exist yet.** The expected behaviour is that the directory is created, the file written, and the path printed. Pinned in Task 6 (`test_the_default_output_lands_under_the_output_root`).
5. **A kernel section added later with no class in `simplon.manifest`, or a class whose reader was deleted.** The expected behaviour is that the coverage test goes red in either direction. Pinned in Task 4 (`test_the_manifest_package_models_exactly_what_the_kernel_reads`), seen red both ways.

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/firn/model/simplon/pipeline/pipeline.firn` | M2: the pipeline vocabulary of spec D.1. Moved from `model/pipeline/`, then completed |
| `src/firn/model/simplon/vocabulary/kinds.firn` | M1: the kernel's ArtifactKinds (spec B.2) and nothing else |
| `src/firn/model/simplon/manifest/manifest.firn` | M2: `Product`, one class per kernel-read section, and `ProductData` |
| `src/firn/model/product/simplon/simplon.firn` | M1: simplon's own manifest, **generated** by `support manifest model` and committed |
| `src/firn/model/simplon/kernel/simplon.firn` | **deleted**: si#371's hand-written stand-in, replaced by the generated file |
| `src/tests/fixtures/firn/pipeline_demo/` | M1 fixture: a firn project that exercises every SelectorRelation |
| `src/simplon/manifestmodel.py` | the bridge: `export()`, `mangle()`, `ModelExportError` |
| `src/simplon/tasks/manifestmodel.py` | the catalogue body `support:model`: load, export, write |
| `src/simplon/catalogue.yaml` | `support:model` task, placed under `support manifest` |
| `simplon.yaml` | `generated:` entry `firn-model` |
| `src/tests/test_refusal_census.py` | `_sections_read()` derivation, plus a test that it covers every `SECTION` constant |
| `src/tests/test_firn_pipeline_e2e.py` | docker: `firn check` and the SelectorRelation answers |
| `src/tests/test_firn_manifest_coverage.py` | kernel-read sections ⇔ `Product` properties, both ways |
| `src/tests/test_manifestmodel.py` | the bridge, pure, with no docker |
| `src/tests/test_manifestmodel_e2e.py` | docker: every reachable manifest exports and checks rc 0 |
| `docs/site/content/with-what/phases.md` | `support manifest model` documented |
| `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md` | D.3 corrected to the measured facts |

---

### Task 1: `simplon.pipeline`, complete, and a fixture that makes every selector answer

**Files:**
- Move: `src/firn/model/pipeline/pipeline.firn` → `src/firn/model/simplon/pipeline/pipeline.firn`
- Create: `src/tests/fixtures/firn/pipeline_demo/firn.toml`
- Create: `src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn`
- Create: `src/tests/test_firn_pipeline_e2e.py`
- Modify: `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md` (D.3)

**Interfaces:**
- Consumes: `simplon.tasks.profiles.profile("firn", version="0.1.0")` and `simplon.tasks.toolchain.declared` / `docker_argv`, both from si#371.
- Produces: the M2 class names that Tasks 2, 4 and 5 write instances of:
  - `simplon.pipeline.{Area, ArtifactKind, Registry, Port, Task, Artifact, Command, TaskCommand, TestResult, AggregateCommand, Release, ReleaseCommand, Environment, Site, Deploy, Group}`;
  - the Area enum values `ci`, `cd` and `support`.
- Produces: the helper `firn_rc(project: Path, *argv: str, cwd: str = "") -> tuple[int, str]` in `src/tests/firnrun.py`. It returns rc and stdout and is shared by every docker test in this plan.

- [ ] **Step 1: Write the shared runner and the failing test**

`src/tests/firnrun.py`:

```python
"""Run the pinned firn image over a firn project, the way `toolchain:run` would (si#371)."""
from pathlib import Path

from simplon.run import run
from simplon.tasks import profiles, toolchain

FIRN = profiles.profile("firn", version="0.1.0")


def firn_rc(project: Path, *argv: str, cwd: str = "") -> tuple[int, str]:
    """(rc, stdout) of `firn <argv>` started in `project/<cwd>`, as the caller, with no network."""
    body = {"image": FIRN.image, "workdir": "/workspace", "argv": list(argv)}
    if cwd:
        body["cwd"] = cwd
    cfg = toolchain.declared(body, where="firn")
    line = toolchain.docker_argv(cfg, root=project, product="firn-test", instance="", extra=[],
                                 network="none")
    result = run(line, capture=True)
    return result.rc, result.stdout
```

Before writing it, check `simplon.run.run`'s result object for the attribute that holds captured stdout (`grep -n "class .*Result\|stdout" src/simplon/run.py`). If its name differs, use that name, and keep the `(rc, text)` return shape.

`src/tests/test_firn_pipeline_e2e.py`:

```python
"""si#346: simplon.pipeline checks, and every SelectorRelation answers what the fixture says.

`firn check` does not compile a SelectorRelation's selector (measured on v0.1.0, 2026-10-11): a misspelt
property passes rc 0 and answers EMPTY. The release rule reads `TestResult.about`, so an empty answer
would let an untested release through - the house defect, arriving through a model. Each relation is
therefore asked for its value over a fixture whose answer is known, and an empty answer is red.

AAA throughout.
"""
import shutil
from pathlib import Path

import pytest

from conftest import docker_is_usable
from firnrun import firn_rc

SRC_FIRN = Path(__file__).resolve().parents[1] / "firn"
DEMO = Path(__file__).resolve().parent / "fixtures" / "firn" / "pipeline_demo"

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")


@pytest.fixture
def demo(tmp_path):
    """The demo project with the real simplon.pipeline beside it, as one firn project."""
    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    shutil.copytree(SRC_FIRN / "model" / "simplon" / "pipeline", tmp_path / "model" / "simplon" / "pipeline")
    return tmp_path


@needs_docker
def test_simplons_own_firn_project_checks_clean():
    # arrange / act
    rc, _ = firn_rc(SRC_FIRN.parents[1], "check", cwd="src/firn")

    # assert
    assert rc == 0


@needs_docker
@pytest.mark.parametrize("selector, expected", [
    ("TestResult.about", ["demo.build.image.kernel"]),
    ("AggregateCommand.produced", ["demo.build.all.kernel_archive"]),
    ("Release.published", ["demo.build.image.kernel", "demo.test.image.checked"]),
])
def test_every_selector_relation_answers_what_the_fixture_says(demo, selector, expected):
    # arrange / act
    rc, out = firn_rc(demo, "query", selector)

    # assert: a value, not merely a clean exit - empty is exactly the failure firn does not report
    assert rc == 0
    assert sorted(out.split()) == sorted(expected)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_firn_pipeline_e2e.py`

Expected:
- FAIL, because the fixture directory does not exist;
- `test_simplons_own_firn_project_checks_clean` may already pass.

- [ ] **Step 3: Move and complete the M2, and write the fixture**

Run `git mv src/firn/model/pipeline/pipeline.firn src/firn/model/simplon/pipeline/pipeline.firn`, then replace its body after the head comment with the following. It was measured green with `firn check` on 2026-10-11, and its selectors were measured answering.

```
package simplon.pipeline

// ci | cd | support (spec D.1). Transparency is a property of the area, so it is not a key a group
// can carry.
enum Area { ci cd support }

ArtifactKind typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property refines typeOf firn.core.Association {
    range = simplon.pipeline.ArtifactKind
    subjectCardinality = 0..N
    objectCardinality = 0..N
  }
}

Registry typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property host typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
}

Port typeOf firn.core.Class extends firn.core.NamedResource {
  property accepts typeOf firn.core.Association {
    range = simplon.pipeline.ArtifactKind
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property param typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
}

Task typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
  property body typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
  property input typeOf firn.core.Composition {
    range = simplon.pipeline.Port
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
  property output typeOf firn.core.Composition {
    range = simplon.pipeline.Port
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
}

Artifact typeOf firn.core.Class extends firn.core.NamedResource {
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
  property path typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
  property kind typeOf firn.core.Association {
    range = simplon.pipeline.ArtifactKind
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property registry typeOf firn.core.Association {
    range = simplon.pipeline.Registry
    subjectCardinality = 0..1
    objectCardinality = 0..N
  }
}

Command typeOf firn.core.Class extends firn.core.NamedResource {
  modifier = firn.core.InheritanceModifier.Abstract
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
}

TaskCommand typeOf firn.core.Class extends simplon.pipeline.Command {
  property task typeOf firn.core.Association {
    range = simplon.pipeline.Task
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property consumes typeOf firn.core.Association {
    range = simplon.pipeline.Artifact
    subjectCardinality = 0..N
    objectCardinality = 0..N
  }
  property produces typeOf firn.core.Composition {
    range = simplon.pipeline.Artifact
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
}

// What a test result is ABOUT is derived from what its producer consumes, never declared (spec C.3).
TestResult typeOf firn.core.Class extends simplon.pipeline.Artifact {
  property about typeOf firn.core.SelectorRelation {
    range = simplon.pipeline.Artifact
    subjectCardinality = 0..N
    objectCardinality = 0..N
    selector = "self.owner().consumes"
  }
}

AggregateCommand typeOf firn.core.Class extends simplon.pipeline.Command {
  property member typeOf firn.core.Association {
    range = simplon.pipeline.Command
    subjectCardinality = 1..N
    objectCardinality = 0..N
  }
  property produced typeOf firn.core.SelectorRelation {
    range = simplon.pipeline.Artifact
    subjectCardinality = 0..N
    objectCardinality = 0..N
    selector = "self.member.produces"
  }
}

// The bundle a release aggregate names (spec C.4). Its content is derived from the members.
Release typeOf firn.core.Class extends simplon.pipeline.Artifact {
  property published typeOf firn.core.SelectorRelation {
    range = simplon.pipeline.Artifact
    subjectCardinality = 0..N
    objectCardinality = 0..N
    selector = "self.owner().member.consumes"
  }
}

ReleaseCommand typeOf firn.core.Class extends simplon.pipeline.AggregateCommand {
  property release typeOf firn.core.Composition {
    range = simplon.pipeline.Release
    subjectCardinality = 1..1
    objectCardinality = 0..1
  }
}

Environment typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
  property next typeOf firn.core.Association {
    range = simplon.pipeline.Environment
    subjectCardinality = 0..1
    objectCardinality = 0..1
  }
}

Site typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
}

// `site` stays 0..1 until a kernel body reads it (spec, "What this is NOT").
Deploy typeOf firn.core.Class extends simplon.pipeline.TaskCommand {
  property environment typeOf firn.core.Association {
    range = simplon.pipeline.Environment
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property site typeOf firn.core.Association {
    range = simplon.pipeline.Site
    subjectCardinality = 0..1
    objectCardinality = 0..N
  }
}

Group typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
  property area typeOf firn.core.Association {
    range = simplon.pipeline.Area
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property command typeOf firn.core.Composition {
    range = simplon.pipeline.Command
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
  property group typeOf firn.core.Composition {
    range = simplon.pipeline.Group
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
}
```

Edit the head comment, so it no longer says that AggregateCommand, Registry, Environment, Site and the areas are "not yet modelled". Then run `git rm src/firn/model/simplon/kernel/simplon.firn` only in Task 7, not here: until then it still checks against `Task`/`Group`.

**Check this before moving on:** `src/firn/model/simplon/kernel/simplon.firn` sets no `area` on its `build` group, and `area` is `1..1`. Add `area = simplon.pipeline.Area.ci` to it, or `firn check` reports a missing value.

`src/tests/fixtures/firn/pipeline_demo/firn.toml`:

```toml
name = "pipeline_demo"
model = ["model"]
templates = []
```

`src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn`. The kinds are named `kimage`, `kresult` and `kbundle`, because a kind called `release` beside a group called `release` in one package is the name clash measured on 2026-10-11 (E200 on the group's body):

```
package demo

kimage typeOf simplon.pipeline.ArtifactKind {
}
kresult typeOf simplon.pipeline.ArtifactKind {
}
kbundle typeOf simplon.pipeline.ArtifactKind {
}

BuildImage typeOf simplon.pipeline.Task {
  body = "simplon.tasks.image:build"
}
TestImage typeOf simplon.pipeline.Task {
  body = "simplon.tasks.image:test"
}
PublishImage typeOf simplon.pipeline.Task {
  body = "simplon.tasks.image:publish"
}
SaveImage typeOf simplon.pipeline.Task {
  body = "simplon.tasks.image:save"
}

build typeOf simplon.pipeline.Group {
  area = simplon.pipeline.Area.ci
  command image typeOf simplon.pipeline.TaskCommand {
    task = demo.BuildImage
    produces kernel typeOf simplon.pipeline.Artifact {
      kind = demo.kimage
    }
  }
  command save typeOf simplon.pipeline.TaskCommand {
    task = demo.SaveImage
    consumes = demo.build.image.kernel
    produces kernel_archive typeOf simplon.pipeline.Artifact {
      kind = demo.kimage
      path = "build/image/kernel.tar"
    }
  }
  command all typeOf simplon.pipeline.AggregateCommand {
    member = demo.build.save
  }
}

test typeOf simplon.pipeline.Group {
  area = simplon.pipeline.Area.ci
  command image typeOf simplon.pipeline.TaskCommand {
    task = demo.TestImage
    consumes = demo.build.image.kernel
    produces checked typeOf simplon.pipeline.TestResult {
      kind = demo.kresult
      path = "build/test/image.json"
    }
  }
}

release typeOf simplon.pipeline.Group {
  area = simplon.pipeline.Area.ci
  command image typeOf simplon.pipeline.TaskCommand {
    task = demo.PublishImage
    consumes = demo.build.image.kernel
    consumes = demo.test.image.checked
  }
  command all typeOf simplon.pipeline.ReleaseCommand {
    member = demo.release.image
    release bundle typeOf simplon.pipeline.Release {
      kind = demo.kbundle
    }
  }
}
```

The test's `demo` fixture copies `simplon/pipeline/` into the demo project, because firn has no cross-project reference without a `[dependencies]` entry. If a `[dependencies] simplon = { path = "..." }` in the demo's `firn.toml` is preferred, remember that firn refuses a path outside the project (E104). The copy is the measured route.

- [ ] **Step 4: Run it to see it pass**

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_firn_pipeline_e2e.py`

Expected: 4 passed. If `AggregateCommand.produced` answers more than `kernel_archive`, `firn query` lists every instance's value. A `ReleaseCommand` is an `AggregateCommand` too, and here it produces nothing, so the expected list stays `[kernel_archive]`. Assert what the query really answers, and say in the test comment why.

- [ ] **Step 5: See it red**

1. Change `selector = "self.owner().consumes"` to `"self.owner.consumes"`.
2. Run the test: `TestResult.about` must FAIL with an empty answer while `firn check` still passes.
3. Restore the selector, and record both runs in the commit message.

- [ ] **Step 6: Correct spec D.3 to the measured facts**

In the spec's D.3:
- "under `model/`, with its own `firn.toml` at the top" becomes "under `src/firn/` (si#371, Marco: firn under src), started there through `toolchain:run`'s `cwd:`".
- `test model: { task: "toolchain:run", with: { profile: firn, command: check } }` becomes "`test model`, written by `support toolchain firn 0.1.0` in its expanded form (profiles are scaffolded, si#95)".
- Add a bullet: "**`firn check` does not compile a SelectorRelation's selector** (measured on v0.1.0, reported to firn): every SelectorRelation has a test asserting its non-empty answer over a fixture."

- [ ] **Step 7: Commit**

```bash
git add src/firn src/tests/firnrun.py src/tests/test_firn_pipeline_e2e.py src/tests/fixtures/firn docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md
git commit -F - <<'EOF'
feat(si#346): simplon.pipeline complete, and every selector relation proven to answer
...body: what was moved, the selector finding, the red run...
EOF
```

---

### Task 2: the kernel's vocabulary, `simplon.vocabulary`

**Files:**
- Create: `src/firn/model/simplon/vocabulary/kinds.firn`
- Modify: `src/tests/test_firn_pipeline_e2e.py` (one more test)

**Interfaces:**
- Consumes: `simplon.pipeline.ArtifactKind` (Task 1).
- Produces: the resources `simplon.vocabulary.{artifact, image, directory, site, nuget, maven, conan, test_result, release_notes, tag, release}`. Task 5 exports `kind = simplon.vocabulary.image` and `kind = simplon.vocabulary.artifact` against these exact names.

- [ ] **Step 1: Write the failing test** (append to `test_firn_pipeline_e2e.py`)

```python
@needs_docker
def test_every_kind_refines_artifact_and_artifact_refines_nothing():
    # arrange / act: spec B.2 - one root, and every other kind reaches it
    rc, kinds = firn_rc(SRC_FIRN.parents[1], "query", "ArtifactKind", cwd="src/firn")
    _, refines = firn_rc(SRC_FIRN.parents[1], "query", "ArtifactKind.refines", cwd="src/firn")

    # assert
    assert rc == 0
    names = set(kinds.split())
    assert "simplon.vocabulary.artifact" in names
    assert set(refines.split()) <= names
    assert len(names) == 11
```

- [ ] **Step 2: Run it to see it fail.** Expected: FAIL, because `simplon.vocabulary.artifact` is not in the answer.

- [ ] **Step 3: Write the vocabulary**

```
// The kernel's artifact kinds (spec B.2), as M1 instances of simplon.pipeline.ArtifactKind. The catalogue
// owns this vocabulary and a product cannot add to it. `test_result` and `release_notes` are spelled with
// `_`, because a firn name has no `-`; the kernel's spelling (`test-result`) is what Task 5's mangling
// maps to these.
package simplon.vocabulary

artifact typeOf simplon.pipeline.ArtifactKind {
}
image typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
directory typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
site typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.directory
}
nuget typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
maven typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
conan typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
test_result typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
release_notes typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
tag typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
release typeOf simplon.pipeline.ArtifactKind {
  refines = simplon.vocabulary.artifact
}
```

- [ ] **Step 4: Run it to see it pass.** Expected: PASS. `test_simplons_own_firn_project_checks_clean` stays green.

- [ ] **Step 5: Commit** with message `feat(si#346): the kernel's artifact kinds as firn's M1 vocabulary`.

---

### Task 3: the census says which top-level sections the kernel reads

**Files:**
- Modify: `src/tests/test_refusal_census.py` (a derivation and two tests)

**Interfaces:**
- Consumes: the census's own `_kernel_modules()`, `_module(dotted)` (with `.tree` and `.funcs`), `_document_entries()`, `_inline_readers()` and `READS_INLINE`.
- Produces: `sections_read() -> frozenset[str]`, a **public** module function in `test_refusal_census.py`, which Task 4 imports. It returns the top-level manifest keys the kernel reads.

The census already finds **which modules** read the manifest. This derivation walks those same modules for **which keys** they read at the top level. Like the census, it is computed, never typed.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_sections_the_kernel_reads_include_every_declared_section_constant():
    """A module that names its section in a `SECTION` constant reads it, so the derivation must find it.

    This cross-check keeps `sections_read()` honest. It is a second route to the same answer, and the
    two routes have to agree.
    """
    constants: set[str] = set()
    for dotted in _kernel_modules():
        for node in _module(dotted).tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and "SECTION" in node.targets[0].id):
                value = node.value
                items = value.elts if isinstance(value, ast.Tuple) else [value]
                constants |= {item.value for item in items
                              if isinstance(item, ast.Constant) and isinstance(item.value, str)}

    assert constants and constants <= sections_read(), sorted(constants - sections_read())


def test_the_kernel_reads_its_command_tree_and_identity_sections():
    # the loader's own keys, read in `manifest.load` and `treeform`, not through a SECTION constant
    assert {"product", "tasks", "ci", "cd", "support"} <= sections_read()
```

- [ ] **Step 2: Run them to see them fail.** Expected: `NameError: sections_read`.

- [ ] **Step 3: Implement `sections_read()`**

Add the function near `_inline_readers()`. It walks these modules:
- every module in `_kernel_modules()` that the census already counts as touching the manifest: the modules of `_document_entries()`, plus `_inline_readers()`, plus `READS_INLINE`;
- `simplon.orchestrator.manifest` and `simplon.orchestrator.model.treeform`, the `manifest.load` seam.

In each module it records a string key `k` whenever one of these patterns appears:
- `X.get(k ...)` or `X[k]` or `k in X`, where `X` is a `Name` whose id is in `DOCUMENT_NAMES = {"data", "document", "doc", "raw", "mapping", "manifest_data"}`, or a call to `.manifest_data()`;
- `k` is a `str` constant, a `Name` bound at module level to a `str` constant, or a `Tuple` of them (`SOURCE_SECTIONS`).

```python
#: The parameter names this kernel binds a parsed manifest DOCUMENT to. Measured over the walked modules
#: on the day this was written; a module that binds it to another name reads nothing as far as this
#: derivation can see, and `test_the_sections_the_kernel_reads_include_every_declared_section_constant`
#: goes red if that hides a section.
DOCUMENT_NAMES = frozenset({"data", "document", "doc", "raw", "mapping", "manifest_data"})


def _constants(module) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for node in module.tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value
            items = value.elts if isinstance(value, ast.Tuple) else [value]
            strings = tuple(i.value for i in items if isinstance(i, ast.Constant) and isinstance(i.value, str))
            if strings and len(strings) == len(items):
                out[node.targets[0].id] = strings
    return out


def _is_document(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in DOCUMENT_NAMES
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == DOCUMENT_ACCESSOR)


def _keys(node: ast.AST, consts: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        return consts.get(node.id, ())
    return ()


def sections_read() -> frozenset[str]:
    """The top-level manifest keys this kernel reads, derived from the modules the census walks (si#346)."""
    modules = ({dotted for dotted, _ in _document_entries()} | set(_inline_readers()) | set(READS_INLINE)
               | {"simplon.orchestrator.manifest", "simplon.orchestrator.model.treeform"})
    out: set[str] = set()
    for dotted in sorted(modules):
        module = _module(dotted)
        consts = _constants(module)
        for node in ast.walk(module.tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and node.args and _is_document(node.func.value)):
                out.update(_keys(node.args[0], consts))
            elif isinstance(node, ast.Subscript) and _is_document(node.value):
                out.update(_keys(node.slice, consts))
            elif (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.In)
                  and _is_document(node.comparators[0])):
                out.update(_keys(node.left, consts))
    return frozenset(out)
```

- [ ] **Step 4: Run them, then read the answer.**

1. Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -c "from test_refusal_census import sections_read; print(sorted(sections_read()))"`.
2. Read the list against the `SECTION` constants (`grep -rn "SECTION\w* = " src/simplon`) and against `manifest.load`.
3. A key that is **not** top-level, for example a nested `name` read off a variable called `data` in a sub-parser, is a false positive. Either rename that local variable in the kernel to a name outside `DOCUMENT_NAMES`, or narrow the walk to the function that receives the whole document. Do **not** add an exclusion list: an exclusion list is a typed second source.
4. A section you know is read but that is missing, such as `cd`'s `environments`, which is read through `environments.matrix_section`, means a module binds the document to another name. Add that name to `DOCUMENT_NAMES` with the module named in the comment.

Expected: both tests PASS, and the printed list contains no nested key.

- [ ] **Step 5: See it red.** Delete `"document"` from `DOCUMENT_NAMES`. The constants test must go red, naming at least one section (for example `generated`). Then restore it.

- [ ] **Step 6: Commit** with message `test(si#346): the census derives which top-level sections the kernel reads`.

---

### Task 4: `simplon.manifest`, exactly the sections the kernel reads

**Files:**
- Create: `src/firn/model/simplon/manifest/manifest.firn`
- Create: `src/tests/test_firn_manifest_coverage.py`

**Interfaces:**
- Consumes: `sections_read()` (Task 3) and `simplon.pipeline.*` (Task 1).
- Produces:
  - the class `simplon.manifest.Product`. It is `allowRoot`, and it has one property per kernel-read section, named by `manifestmodel.mangle(section)`, for example `lab_egress` → `lab_egress` and `ci` → `ci`;
  - the class `simplon.manifest.KernelSection`, with a `key` attribute;
  - the class `simplon.manifest.ProductData`, with a `key` attribute.

  Task 5 writes instances of exactly these names.

**Ruling recorded for review:**
- **Command tree and artifacts are modelled in structure.** `ci`, `cd` and `support` are compositions of `simplon.pipeline.Group`, `tasks` a composition of `simplon.pipeline.Task`, and `artifacts`/`images` compositions of `simplon.pipeline.Artifact`. These are the sections parts B and C are generated from.
- **Every other kernel-read section is a `KernelSection`:** the kernel knows the key, and its inner structure is **not modelled yet**. Modelling the inside of every one of them (tracker, nexus, carriers, ...) would multiply this plan's size and serves no generation that is planned.
- **The test** holds the set of keys, not their depth. A section that B or C needs to generate from gets a real class when that plan needs it.

- [ ] **Step 1: Write the failing test**

```python
"""si#346 / spec D.1: `simplon.manifest` models exactly the top-level sections the kernel reads.

Both directions. A kernel reader with no property here, and a property here with no reader, are each
red, because a typed list is wrong on the first day nobody checks it, and this one is checked against
the census's derived population, not against a list.
"""
import re
from pathlib import Path

from simplon import manifestmodel
from test_refusal_census import sections_read

M2 = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "manifest" / "manifest.firn"


def _product_properties() -> set[str]:
    text = M2.read_text(encoding="utf-8")
    block = re.search(r"^Product typeOf .*?^\}", text, re.MULTILINE | re.DOTALL)
    assert block, "manifest.firn declares no Product class"
    return set(re.findall(r"^\s+property (\w+) typeOf", block.group(0), re.MULTILINE)) - {"key", "data"}


def test_the_manifest_package_models_exactly_what_the_kernel_reads():
    # arrange
    read = {manifestmodel.mangle(section) for section in sections_read()}

    # act
    modelled = _product_properties()

    # assert
    assert read - modelled == set(), f"read by the kernel, not modelled: {sorted(read - modelled)}"
    assert modelled - read == set(), f"modelled, read by nothing: {sorted(modelled - read)}"
```

This test imports `manifestmodel.mangle`, which is Task 5's. Write `mangle` now, as Task 5 Step 3 specifies it, in `src/simplon/manifestmodel.py`, with only that function and `ModelExportError`. Task 5 adds `export`.

- [ ] **Step 2: Run it to see it fail.** Expected: FAIL with "manifest.firn declares no Product class".

- [ ] **Step 3: Write `manifest.firn`**

```
// simplon.manifest (spec D.1): the manifest's top level, as far as the kernel reads it. Each property is
// one section `test_firn_manifest_coverage` derived from the census - add a reader and this file has to
// follow, delete one and it has to shrink. A section only a product reads is never here; it is a
// ProductData entry holding its key and nothing else.
package simplon.manifest

// A section the kernel reads and whose inside is not modelled yet. Parts B and C give a section a real
// class when they generate from it.
KernelSection typeOf firn.core.Class extends firn.core.NamedResource {
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
}

// A section only the product reads (asbundle's jdk:, netctl's topology:, ...). The model does not claim
// to understand it.
ProductData typeOf firn.core.Class extends firn.core.NamedResource {
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
}

Product typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property data typeOf firn.core.Composition {
    range = simplon.manifest.ProductData
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
  // ... one property per section in sorted(sections_read()), in this shape ...
}
```

Generate the per-section properties from the measured list; do not type them from memory. Print `sorted(manifestmodel.mangle(s) for s in sections_read())`, then write one property per name. The table below is fixed; every name it does not list gets the `KernelSection` shape.

| Section | Property type | range | subjectCardinality | objectCardinality |
|---|---|---|---|---|
| `ci`, `cd`, `support` | `Composition` | `simplon.pipeline.Group` | `0..N` | `0..1` |
| `tasks` | `Composition` | `simplon.pipeline.Task` | `0..N` | `0..1` |
| `artifacts`, `images` | `Composition` | `simplon.pipeline.Artifact` | `0..N` | `0..1` |
| `environments` (only if the census lists it at the top level) | `Composition` | `simplon.pipeline.Environment` | `0..N` | `0..1` |
| `product` | none: `product` is the `Product` resource's own `key`, so leave it out of the properties and remove it from `read` in the test with a comment saying so | — | — | — |
| every other section | `Composition` | `simplon.manifest.KernelSection` | `0..1` | `0..1` |

- [ ] **Step 4: Run the test and `firn check`.** Expected: the coverage test PASSES, and `test_simplons_own_firn_project_checks_clean` stays green.

- [ ] **Step 5: See it red in both directions.**
  1. Delete one `KernelSection` property: the test names the section under "read by the kernel, not modelled".
  2. Add `property nosuchsection` in the same shape: the test names it under "modelled, read by nothing".
  3. Restore the file.

- [ ] **Step 6: Commit** with message `feat(si#346): simplon.manifest models exactly the sections the census says the kernel reads`.

---

### Task 5: the bridge, `simplon.manifestmodel`

**Files:**
- Create or complete: `src/simplon/manifestmodel.py`
- Create: `src/tests/test_manifestmodel.py`
- Create: `src/tests/test_manifestmodel_e2e.py`

**Interfaces:**
- Consumes:
  - `simplon.orchestrator.manifest.Manifest`, with `.groups: dict[str, tuple[str, ...]]`, `.commands: dict[str, dict[str, CommandSpec]]`, `.areas: dict[str, str]` and `.area_of(group) -> str | None`;
  - `CommandSpec`, with `.impl: str` and `.depends_on: tuple[str, ...]`;
  - the class names from Tasks 1, 2 and 4.
- Produces:
  - `mangle(name: str) -> str`;
  - `class ModelExportError(ValueError)`;
  - `export(manifest: Manifest, document: Mapping[str, object], product: str, kernel_sections: frozenset[str]) -> str`. It returns the complete text of an M1 `.firn` file in package `product.<mangle(product)>`.

  Task 6 calls `export` with `kernel_sections` set to the kernel's section set. Task 6 gets that set from a module constant this task writes: `KERNEL_SECTIONS`, read off the `Product` properties of the packaged `manifest.firn`.

**What one export looks like**, for a product `demo` with `ci: build: { commands: { image: build:image, all: depends_on [image] } }`, a `cd:` matrix `environments: { dev: {}, prod: {} }`, an `images: kernel` entry and a product section `jdk:`:

```
// GENERATED by `support manifest model` from demo.yaml (si#346). Do not edit; regenerate.
package product.demo

demo typeOf simplon.manifest.Product {
  key = "demo"
  ci build typeOf simplon.pipeline.Group {
    key = "build"
    area = simplon.pipeline.Area.ci
    command image typeOf simplon.pipeline.TaskCommand {
      key = "image"
      task = product.demo.demo.t_simplon_tasks_image_build
    }
    command all typeOf simplon.pipeline.AggregateCommand {
      key = "all"
      member = product.demo.demo.build.image
    }
  }
  tasks t_simplon_tasks_image_build typeOf simplon.pipeline.Task {
    key = "simplon.tasks.image:build"
    body = "simplon.tasks.image:build"
  }
  cd dev typeOf ...
  images kernel typeOf simplon.pipeline.Artifact {
    key = "kernel"
    kind = simplon.vocabulary.image
  }
  data jdk typeOf simplon.manifest.ProductData {
    key = "jdk"
  }
}
```

The rules, each pinned by a test below:
1. **Names.** `mangle(n)`:
   - replaces every character outside `[A-Za-z0-9_]` with `_`;
   - prefixes `_` when the result starts with a digit;
   - turns `a-b` into `a_b` and `build:image` into `build_image`.

   The original name always goes in `key`.
2. **Tasks** are named `t_` + `mangle(impl)`, one per distinct `impl`, so a task can never share a name with a group. A command's `task` points at it.
3. **Groups** nest as `group` compositions, and `area` comes from `manifest.area_of`:
   - a top-level group under `support` is `Area.support`;
   - `area_of` returns `None` for `support`, so `None` maps to `support`;
   - the group goes under the Product property named by its area (`ci`, `cd` or `support`).
4. **Commands.** A command with a non-empty `depends_on` is an `AggregateCommand`, and its `member`s resolve each name in the same group first and then anywhere it is unique. Every other command is a `TaskCommand`. A name that resolves nowhere is a `ModelExportError`; this cannot happen after `load`, and the test proves the guard.
5. **Environments.** Each key of the `cd:` matrix's `environments` is an `Environment` under the Product's `cd`-area property `environments`. `next` follows declaration order.
6. **Artifacts.** Each `images:` entry is an `Artifact` with `kind = simplon.vocabulary.image`. Each `artifacts:` entry is one with `kind = simplon.vocabulary.artifact`. Kinds are part B's to refine.
7. **Product data.** Every top-level key that is not in `kernel_sections` becomes one `data <mangled> typeOf simplon.manifest.ProductData { key = "<original>" }`.
8. **Other kernel sections.** Every other kernel section that is present becomes `<section> <section> typeOf simplon.manifest.KernelSection { key = "<section>" }`.
9. **Collisions.** Two originals in one owner that mangle to the same name raise `ModelExportError` naming both originals and the mangled name. Collisions are children with the same owner and the same mangled name.
10. **Strings** are written with `"` and `\` escaped.

- [ ] **Step 1: Write the failing pure tests** in `src/tests/test_manifestmodel.py`

```python
"""si#346: the bridge from a validated manifest to an M1 `.firn` model. Pure: no docker, no firn.

AAA throughout.
"""
import pytest
import yaml

from simplon import catalogue, manifestmodel
from simplon.orchestrator import manifest as manifest_mod

DEMO = """\
product: demo
ci:
  build:
    commands:
      image: { task: "build:image" }
      typecheck-python: { task: "test:typecheck-python" }
      all: { depends_on: [image] }
cd:
  default: dev
  environments:
    dev: {}
    prod: {}
images:
  kernel: { registry: ghcr.io/x, repository: demo, dockerfile: Dockerfile, context: . }
jdk:
  version: 21
"""

KERNEL = frozenset({"product", "tasks", "ci", "cd", "support", "images", "artifacts"})


def _export(text: str = DEMO) -> str:
    mf = manifest_mod.load(text, catalogue=catalogue.load())
    return manifestmodel.export(mf, yaml.safe_load(text), "demo", KERNEL)


@pytest.mark.parametrize("raw, mangled", [
    ("typecheck-python", "typecheck_python"), ("build:image", "build_image"),
    ("simplon.tasks.image:build", "simplon_tasks_image_build"), ("7zip", "_7zip"), ("ok_1", "ok_1")])
def test_mangle_makes_a_firn_name(raw, mangled):
    assert manifestmodel.mangle(raw) == mangled


def test_the_export_is_one_product_in_its_own_package():
    out = _export()
    assert "package product.demo\n" in out
    assert 'demo typeOf simplon.manifest.Product {' in out


def test_a_name_that_is_not_a_firn_name_keeps_its_original_in_key():
    out = _export()
    assert "command typecheck_python typeOf simplon.pipeline.TaskCommand {" in out
    assert 'key = "typecheck-python"' in out


def test_an_aggregate_names_its_members_and_runs_no_task():
    out = _export()
    block = out.split("command all typeOf simplon.pipeline.AggregateCommand {", 1)[1].split("}", 1)[0]
    assert "member = product.demo.demo.build.image" in block
    assert "task =" not in block


def test_a_task_is_named_by_its_body_and_cannot_meet_a_group():
    out = _export()
    assert "tasks t_simplon_tasks_image_build typeOf simplon.pipeline.Task {" in out


def test_environments_follow_the_matrix_and_promote_in_order():
    out = _export()
    assert "environments dev typeOf simplon.pipeline.Environment {" in out
    assert "next = product.demo.demo.prod" in out


def test_an_image_is_an_artifact_of_the_image_kind():
    out = _export()
    assert "images kernel typeOf simplon.pipeline.Artifact {" in out
    assert "kind = simplon.vocabulary.image" in out


def test_a_product_section_is_opaque_product_data():
    out = _export()
    assert 'data jdk typeOf simplon.manifest.ProductData {' in out
    assert "21" not in out.split("data jdk", 1)[1].split("}", 1)[0]


def test_names_that_mangle_alike_are_refused_naming_both():
    text = DEMO.replace("      all: { depends_on: [image] }\n",
                        "      all: { depends_on: [image] }\n      typecheck_python: { task: \"build:image\" }\n")
    with pytest.raises(manifestmodel.ModelExportError) as e:
        _export(text)
    assert "typecheck-python" in str(e.value) and "typecheck_python" in str(e.value)
```

Before writing the expected strings, check the exact `impl` that `build:image` resolves to: `catalogue.load()`, then the merged spec's `impl`. The `t_…` name is `mangle` of that impl. Adjust the two expected strings to the measured impl. The impl may be `simplon.tasks.image:build`, but do not assume it.

- [ ] **Step 2: Run them to see them fail.** Expected: `AttributeError: module 'simplon.manifestmodel' has no attribute 'export'`, plus the mangle tests if Task 4 has not written `mangle` yet.

- [ ] **Step 3: Implement `src/simplon/manifestmodel.py`**

The module head says what it is, and what it is not: no validation and no YAML importer in firn (spec D.2).

```python
"""The manifest as a firn M1 model (si#346, spec D.2): a validated manifest in, `.firn` text out.

Run only on what `manifest.load` accepted - this module validates nothing, and a manifest the kernel
refused never reaches it (`tasks/manifestmodel.py` passes the refusal's rc on). firn gets no YAML
importer: simplon owns the parse and the validation, firn checks the shape of what it is handed.

Names. A firn name is [A-Za-z_][A-Za-z0-9_]* (firn docs/03 §2), and a manifest's are not: `typecheck-python`,
`build:image`. `mangle` maps one to the other and the original is kept in `key`, so nothing is lost. Two
originals one owner would mangle to the same name are refused by name: firn would merge them into one
resource, and a model that silently holds one command where the manifest has two is the defect this
kernel hunts.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from simplon.orchestrator.manifest import Manifest

_NOT_NAME = re.compile(r"[^A-Za-z0-9_]")
AREAS = ("ci", "cd", "support")


class ModelExportError(ValueError):
    """A manifest the bridge cannot write as a model without losing something."""


def mangle(name: str) -> str:
    """`name` as a firn name: every character outside [A-Za-z0-9_] becomes `_`, and a leading digit gets `_`."""
    out = _NOT_NAME.sub("_", name)
    return f"_{out}" if out[:1].isdigit() else out


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Names:
    """One owner's children: mangled name -> original, refusing two originals on one mangled name."""

    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.seen: dict[str, str] = {}

    def __call__(self, original: str, mangled: str | None = None) -> str:
        name = mangled or mangle(original)
        if name in self.seen and self.seen[name] != original:
            raise ModelExportError(
                f"{self.owner}: '{self.seen[name]}' and '{original}' are both '{name}' as a firn name, "
                f"and firn would merge them into one resource - rename one of them")
        self.seen[name] = original
        return name
```

Then write `export()` so that it emits exactly the shape in "What one export looks like", following rules 1 to 10:
- indent with two spaces;
- emit one `}` per opened block;
- emit groups in `manifest.groups` order, nesting by the dotted path: `build.docker` is `group docker` inside `build`;
- start the file with the GENERATED comment line.

Keep the function under about 120 lines by splitting it into `_group()`, `_command()`, `_tasks()`, `_environments()`, `_artifacts()` and `_sections()`. Each helper returns `list[str]`.

- [ ] **Step 4: Run the pure tests.** Expected: all PASS.

- [ ] **Step 5: Write the docker test over every reachable manifest** in `src/tests/test_manifestmodel_e2e.py`

```python
"""si#346: every reachable manifest, migrated, exports to a model firn accepts (rc 0, never "not 1").

The eight manifests are the frozen fixtures of si#344 plan A, in the old form; `migrate_text` brings each
to the current form first, exactly as a product will.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import docker_is_usable
from firnrun import firn_rc
from simplon import catalogue, manifestmodel
from simplon.orchestrator import manifest as manifest_mod
from simplon.tasks.migrate import migrate_text

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "manifests"
SRC_FIRN = Path(__file__).resolve().parents[1] / "firn"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.yaml"))

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")


@needs_docker
@pytest.mark.parametrize("name", NAMES)
def test_a_reachable_manifest_exports_to_a_model_firn_accepts(tmp_path, name):
    # arrange
    text = migrate_text((FIXTURES / f"{name}.yaml").read_text(encoding="utf-8")).text
    mf = manifest_mod.load(text, catalogue=catalogue.load())
    out = manifestmodel.export(mf, yaml.safe_load(text), name, manifestmodel.KERNEL_SECTIONS)
    shutil.copytree(SRC_FIRN, tmp_path / "firn")
    target = tmp_path / "firn" / "model" / "product" / manifestmodel.mangle(name)
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.firn").write_text(out, encoding="utf-8")

    # act
    rc, text_out = firn_rc(tmp_path, "check", cwd="firn")

    # assert
    assert rc == 0, text_out
    assert len(NAMES) == 8
```

Check the `Migration` type's field that holds the rewritten text in `simplon/tasks/migrate.py`, and use that field. `migrate_text` takes `unknown_groups_into=` for two of the fixtures. Copy whatever `test_migrate.py` passes per fixture rather than guessing.

`KERNEL_SECTIONS` reads the `Product` properties of the packaged `manifest.firn` once, at import:

```python
from importlib import resources  # noqa: E402 - at the top of the module in the real file

def _kernel_sections() -> frozenset[str]:
    ...
```

The kernel wheel does not ship `src/firn/`. So `KERNEL_SECTIONS` is **not** read from the `.firn` file at run time. Generate it instead, as a sorted tuple literal in `manifestmodel.py`: the property names of `Product` plus `product`, written by hand **once** in this step from the coverage test's list. Then extend `test_firn_manifest_coverage.py` with one assertion: `{mangle(s) for s in manifestmodel.KERNEL_SECTIONS} - {"product"} == _product_properties()`. The constant then has a test against the model, which has a test against the census. That chain is what keeps three copies honest. Write that assertion in this step.

- [ ] **Step 6: Run the docker test.** Expected: 8 passed.
  - A fixture that fails `firn check` is a finding. Read firn's message.
  - A name clash inside one owner that `_Names` did not catch, for example an environment and a group with the same name under one `cd` property, means the owner was drawn too wide. Fix the owner, not the test.

- [ ] **Step 7: See it red.** Make `mangle` return `name` unchanged. The pure tests and at least the fixtures with `-` in a command name go red (firn E113). Restore it.

- [ ] **Step 8: Commit** with message `feat(si#346): the bridge - a validated manifest as a firn M1 model, checked over all eight`.

---

### Task 6: `support manifest model`

**Files:**
- Create: `src/simplon/tasks/manifestmodel.py`
- Modify: `src/simplon/catalogue.yaml`, adding the `support:model` task and placing `model: { task: "support:model" }` under `support: manifest: commands:` beside `migrate`
- Test: `src/tests/test_manifestmodel_task.py`
- Regenerate: `deploy/completions/simplon.bash` (`./simplon.sh support completion`)

**Interfaces:**
- Consumes:
  - `manifestmodel.export` and `manifestmodel.KERNEL_SECTIONS` (Task 5);
  - `simplon.context.current()`, which returns a `ProductContext` with `.name`, `.manifest()` and `.manifest_data()`;
  - `simplon.outputs.root() -> Path`.
- Produces: the body `simplon.tasks.manifestmodel:model(output: str = "") -> int`, which Task 7 places through `generated:`.

- [ ] **Step 1: Write the failing tests**

```python
"""si#346 / spec D.2: `support manifest model` writes the validated manifest as a firn model."""
from pathlib import Path

from simplon import catalogue, context
from simplon.tasks import manifestmodel as task


def test_the_default_output_lands_under_the_output_root(tmp_path, monkeypatch, product_context):
    # arrange: an output directory that does not exist yet
    monkeypatch.setattr(task.outputs, "root", lambda: tmp_path / "build")

    # act
    rc = task.model()

    # assert
    written = tmp_path / "build" / "model" / f"{context.current().name}.firn"
    assert rc == 0 and written.is_file()
    assert written.read_text().startswith("// GENERATED by `support manifest model`")


def test_an_explicit_output_is_written_where_it_is_named(tmp_path, product_context):
    rc = task.model(output=str(tmp_path / "x" / "p.firn"))
    assert rc == 0 and (tmp_path / "x" / "p.firn").is_file()


def test_a_refused_manifest_writes_no_model_and_keeps_a_failing_rc(tmp_path, monkeypatch, product_context):
    # arrange: spec D.2 - "no model because it is broken" must never read as "nothing to model"
    def refuse():
        raise ValueError("the manifest is broken")
    monkeypatch.setattr(task.context.current(), "manifest", refuse, raising=False)

    # act
    rc = task.model(output=str(tmp_path / "p.firn"))

    # assert
    assert rc != 0 and not (tmp_path / "p.firn").exists()


def test_the_catalogue_places_it_beside_migrate():
    cat = catalogue.load()
    assert "support:model" in cat.tasks
```

`product_context` is a fixture. Find the existing one that registers a `ProductContext` over a temporary manifest (`grep -rn "set_current" src/tests/conftest.py src/tests/*.py | head`) and reuse it. If none fits, write one in this test file that writes the `DEMO` manifest from `test_manifestmodel.py` and calls `context.set_current(ProductContext(name="demo", root=tmp_path, manifest_path=...))`. `ProductContext` is frozen, so if `monkeypatch.setattr` on `.manifest` fails, patch `task._load` instead: the body loads through one small function, `_load()`, for exactly this seam. Adjust the catalogue assertion to the real attribute that holds the catalogue's tasks (`grep -n "def load" -A20 src/simplon/catalogue.py`).

- [ ] **Step 2: Run them to see them fail.** Expected: `ModuleNotFoundError: simplon.tasks.manifestmodel`.

- [ ] **Step 3: Implement the body and the catalogue entry**

```python
"""`support manifest model` (si#346, spec D.2): this product's validated manifest, written as a firn model."""
from __future__ import annotations

from pathlib import Path

from simplon import context, log, manifestmodel, outputs


def _load():
    ctx = context.current()
    return ctx.name, ctx.manifest(), ctx.manifest_data()


def model(output: str = "") -> int:
    """Write the model; rc 1 and no file when the manifest is refused or cannot be modelled."""
    try:
        name, mf, document = _load()
        text = manifestmodel.export(mf, document, name, manifestmodel.KERNEL_SECTIONS)
    except ValueError as exc:  # ModelExportError is a ValueError; so is every load refusal
        log.error(f"no model written: {exc}")
        return 1
    path = Path(output) if output else outputs.root() / "model" / f"{name}.firn"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log.ok(f"wrote the model of {name} to {path}")
    return 0
```

`catalogue.yaml`, beside `support:migrate`:

```yaml
  support:model:
    impl: simplon.tasks.manifestmodel:model
    help: "Write this product's validated manifest as a firn model (si#346)."
    unattended: true
    params:
      output: { help: "the .firn file to write (default: <output>/model/<product>.firn)", argument: true }
```

and under `support: manifest: commands:` add `model: { task: "support:model" }`.

- [ ] **Step 4: Run the tests and the touched gates.**
  - Run the task tests.
  - Run `test_refusal_census.py`: the body's `ValueError` catch adds no load-time refusal, but run it.
  - Run the CLI-surface goldens of si#344 (`grep -rln "golden" src/tests | head`). These goldens will now show one new command, `support manifest model`, in every manifest. Update them the way plan A updated them for `support manifest migrate`, by regenerating from the kernel rather than editing by hand. Check how `src/tests/fixtures/manifests/golden/README` or `test_migrate.py` regenerates them.
  - Run `./simplon.sh support completion` and `./simplon.sh test generated`.

  Expected: all green after the golden regeneration. The si#34 count in the census moves from 18 to 19, because `support:model` is a new catalogue placement. Update the count where the census pins it, with the reason in the comment.

- [ ] **Step 5: Commit** with message `feat(si#346): support manifest model - the validated manifest as a firn model`.

---

### Task 7: simplon models itself, and the drift gate

**Files:**
- Create (generated): `src/firn/model/product/simplon/simplon.firn`
- Delete: `src/firn/model/simplon/kernel/simplon.firn`
- Modify: `simplon.yaml` (the `generated:` entry)
- Modify: `docs/site/content/with-what/phases.md` (`support manifest model`)

**Interfaces:**
- Consumes: `./simplon.sh support manifest model <path>` (Task 6), `test generated` (si#240) and `test model` (si#371).

- [ ] **Step 1: Generate and register**

```bash
./simplon.sh support manifest model src/firn/model/product/simplon/simplon.firn
git rm src/firn/model/simplon/kernel/simplon.firn
```

`simplon.yaml`, under `generated:`:

```yaml
  # simplon's own manifest as a firn model (si#346). `test generated` regenerates it and fails on drift;
  # `test model` runs `firn check` over it with the M2 beside it, so a manifest change the model cannot
  # carry is red in CI rather than discovered when parts B and C generate from it.
  firn-model:
    path: src/firn/model/product/simplon/simplon.firn
    by: support manifest model src/firn/model/product/simplon/simplon.firn
```

Check that `generated.py` splits `by:` with `shlex` and passes the arguments through (`grep -n "shlex" src/simplon/tasks/generated.py`). If it does not take arguments, give `support:model` a pinned `with: { output: ... }` through a product command `model-self` under `support manifest`, and point `by:` at that command.

- [ ] **Step 2: Run the three gates.**

```bash
./simplon.sh test model; echo rc=$?
./simplon.sh test generated; echo rc=$?
```

Expected: both rc 0. `test generated` will report the new file as stale until it is committed. That is si#240's tracked-file check, so commit first and run again.

- [ ] **Step 3: See it red.**
  1. Add a command to `simplon.yaml` without regenerating: `test generated` must fail and name `firn-model`.
  2. Revert that.
  3. Hand-edit one `key = "..."` line in the generated file to a string with an unescaped `"`: `test model` must go rc 1.
  4. Revert that too.

- [ ] **Step 4: Document** in `phases.md`, under the support commands, next to `support manifest migrate`:
  - what `support manifest model` writes and where;
  - that it writes only after the manifest loads;
  - that product sections are `ProductData` with their key only;
  - that names are mangled with the original kept in `key`;
  - that simplon checks its own model in CI through `generated:` and `test model`.

- [ ] **Step 5: Full suite and gates**

```bash
cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q
cd ../.. && ./simplon.sh test typecheck-python && ./simplon.sh test generated && ./simplon.sh test model
```

Expected:
- the suite is all green apart from the 4 known skips;
- the derived-pipeline tests in `test_own_workflows.py` are unchanged, because no new build/test command was added;
- if they moved, read why before you edit them.

- [ ] **Step 6: Commit** with message `feat(si#346): simplon models itself, and CI checks the model on every push`.

---

## Self-Review

- **Spec coverage, part D.**
  - D.1 `simplon.pipeline`: Task 1 covers every listed class, including TestResult.about, Release, ReleaseCommand, Area, Environment.next, Site, Registry and Deploy.
  - The kinds are in Task 2.
  - D.1 `simplon.manifest` is Tasks 3 and 4, including the both-directions test and ProductData.
  - D.2 bridge and command are Tasks 5 and 6, including the "runs only after load" rc.
  - D.3 drift gate is Task 7. "Every parser disagreement goes to firn as a finding": the selector finding was sent on 2026-10-11 and is noted in the spec in Task 1.
  - `firn diagram` does not exist in v0.1.0, so the spec's D.2 bullet stays unbuilt. Task 1's spec edit should add that sentence to D.2.
- **Deliberately not here (decision 17):** generating B and C from the model; the kinds checks; ports on catalogue tasks; the release rule; the `images:` fold. Those are the next plans.
- **Type consistency:**
  - the `mangle`, `export`, `KERNEL_SECTIONS` and `ModelExportError` names are used identically in Tasks 4, 5 and 6;
  - `firn_rc(project, *argv, cwd=)` is identical in Tasks 1, 2 and 5;
  - the class names in Task 5's output match Task 1's and Task 4's declarations.
- **Known soft spots, flagged for review:**
  - Task 3's AST derivation may need one or two kernel locals renamed (Step 4 says how, without an exclusion list).
  - Task 4 models most sections as `KernelSection` (ruling above).
  - `KERNEL_SECTIONS` is one typed copy held by two tests (Task 5 Step 5).
