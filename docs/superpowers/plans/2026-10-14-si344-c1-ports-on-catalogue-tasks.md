# si#344 C.1 — the catalogue's tasks carry ports, modelled in firn and generated

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The kernel's catalogue tasks that take an artifact become `simplon.pipeline.Task` instances in simplon's firn model, each with its input and output ports. The model generates `PORTS` into `artifactschema.py`, and `READERS`/`NEEDS` are then derived from those ports instead of from the `KindReader` placeholder, which this plan deletes.

**Architecture:** This plan is additive. No manifest key changes and no new refusal is added. The ports are data the kernel generates and exposes. C.2 (a later plan) makes commands bind them with `produces:`/`consumes:`. `READERS` and `NEEDS` keep their exact values, and the existing tests in `test_generated_schema.py` are the regression net that proves it.

**Tech Stack:** firn v0.1.0 (`ghcr.io/marcozwyssig/firn:v0.1.0`, run by `./simplon.sh build model`), Python 3, pydantic, pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md`, Part C.1. Decisions taken after the spec: https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6161492956 (measurement) and the "Decided (choice list, Marco, 2026-10-14)" comment after it. In short, C.1 is built in M3, si#400 builds on it, and C does not wait for products to adopt cuts 1 and 2.

## Scope: what is C.1 and what is not

Part C is split into four plans. This is the first.

| Plan | Content |
|---|---|
| **C.1 (this)** | ports on the catalogue tasks, modelled and generated; `KindReader` replaced |
| C.2 | product tasks may declare `input:`/`output:`; commands bind `produces:`/`consumes:`; load rules 1-5 and 7; migration of `with: { name: }` into a port binding; `support manifest model` references catalogue tasks instead of re-declaring them |
| C.3 | test results (`test:image` writes a verdict record, its `result` output), `evidence` on publish leaves, the release rule, the release aggregate, `release:notes`, `release:tag` ports |
| C.4 | workflowgen: `upload-artifact`/`download-artifact` from the edges |

C.3's ports (`test:image`'s `result` output and the publish leaves' `evidence` input) are **not** declared here. A port with `param:` needs a body parameter of that name. `test:image` has no `results` parameter today, and a port the body cannot honour is a statement that is false.

## Global Constraints

- **Commits:** set the identity env on every commit; `git config` and `--amend` are blocked:
  `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'`
  The message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
  ```
- **Python:** always `./deploy/orchestrator/.venv/bin/python`.
  - Tests: `./deploy/orchestrator/.venv/bin/python -m pytest src/tests -q -p no:cacheprovider` (about 2 min).
  - mypy: `./deploy/orchestrator/.venv/bin/python -m mypy --config-file mypy.ini src/simplon`.
- **Generated files** (`src/simplon/catalogue.yaml` outside its protected region, `src/simplon/domain/artifactschema.py`, `src/site/content/with-what/kinds.md`) are **never edited by hand**. Edit the model or the template, then run `./simplon.sh build model`. Both `./simplon.sh test generated` and `./simplon.sh test model` must be green before every commit that touches `src/firn/`.
- **firn v0.1.0 loses output with rc 0** (firn#966): a selector that answers nothing deletes a generated file, and a template error leaves only the id line. After every `build model`, run `git status --short src/simplon src/site` and read the diff of each generated file. If `artifactschema.py` is gone or empty, restore it with `git checkout -- src/simplon/domain/artifactschema.py`, then fix the template.
- **CLAUDE.md:**
  - See every new assertion red: break the property, run the test, watch it fail, restore. Write down in the commit which break turned it red.
  - Report findings, do not patch them away.
  - A new refusal needs a census entry. This plan adds none; if you find yourself adding a `raise`, stop and say so.
- **Port names follow the kind they accept**, so a product can guess them: `image`, `directory`, `conan`, `nuget`, `maven`, `site`. The two generic ports are `source` and `out` on `toolchain:run`, as the spec writes them. This naming is the plan's choice, not the spec's (the spec only shows `image`), and it is flagged for review.

## The ports, decided from the bodies (measured 2026-10-14)

All ten coordinates that read one entry by name today have a `name: str = ""` parameter (read off the signatures in `src/simplon/tasks/`). The direction comes from what the body does with the entry:

| coordinate | body | direction | port | accepts | param | needs (unchanged from today's `KindReader`) |
|---|---|---|---|---|---|---|
| `build:image` | `image:build` | output | `image` | image | name | registry, repository, dockerfile, context |
| `test:image` | `image:smoke` | input | `image` | image | name | registry, repository, dockerfile, context |
| `release:image` | `image:release` | input | `image` | image | name | registry, repository, dockerfile, context |
| `release:artifact` | `artifact:publish` | input | `directory` | directory | name | registry, repository, media_type, path |
| `build:conan-cache` | `conan:fetch` | input | `conan` | conan | name | registry, repository, media_type, path |
| `release:conan` | `conan:publish` | input | `conan` | conan | name | registry, repository, media_type, path |
| `build:nuget-config` | `nuget:config` | input | `nuget` | nuget | name | registry |
| `build:nuget-restore` | `nuget:restore` | input | `nuget` | nuget | name | registry, image, project |
| `release:nuget` | `nuget:publish` | input | `nuget` | nuget | name | registry, image, project |
| `release:maven` | `maven:publish` | input | `maven` | maven | name | registry, image, group, modules |
| `docs:site` | `site:build` | output | `site` | site | — | — |
| `toolchain:run` | `toolchain:run_toolchain` | input + output | `source`, `out` | artifact | — | — |

Two judgement calls, both flagged for review:

- **`build:conan-cache` is an input.** It fetches a *published* cache. That is the spec's external input (C.5 rule 2: consumed, not produced here, fetchable because it has a `registry:`), not something this build produces.
- **`build:nuget-config` and `build:nuget-restore` are inputs.** They read where the package lives and what to restore, and they write `nuget.config` or the restored tree, which is not the package. Calling either a producer of the `nuget` artifact would give that artifact two producers once `release:nuget` is also bound, and C.5 rule 1 forbids that.

## File Structure

- **Modify** `src/firn/model/simplon/pipeline/pipeline.firn`:
  - `Port` gains `needs`;
  - a new class `CatalogueTask` extends `Task`;
  - `KindReader` is deleted (Task 2).
- **Create** `src/firn/model/simplon/catalogue/tasks.firn` (package `simplon.catalogue`): the twelve `CatalogueTask` instances above.
- **Modify** `src/firn/model/simplon/vocabulary/kinds.firn`: the ten `KindReader` instances are deleted (Task 2).
- **Modify** `src/firn/templates/schema.firnt`:
  - generate `Port`, `PORTS` and `BODIES`;
  - from Task 2, derive `READERS`/`NEEDS` from `PORTS`.
- **Modify** `src/firn/templates/docs.firnt`: a "Ports" table on the kinds page (Task 3).
- **Regenerated** by `./simplon.sh build model`: `src/simplon/domain/artifactschema.py` and `src/site/content/with-what/kinds.md`.
- **Create** `src/tests/test_catalogue_ports.py`: the ports, held to the catalogue and to the bodies.
- **Modify** `src/tests/test_generated_schema.py`: only the `KindReader` wording in docstrings and messages. Its assertions stay as they are; they are the regression net.

### Why `CatalogueTask` and not `Task`

The product models (`src/firn/model/product/*/`, written by `support manifest model`) declare `simplon.pipeline.Task` instances too, one per impl a product uses, and they sit in the same firn project. A template loop over `simplon.pipeline.Task` would therefore pull in product tasks, and `PORTS` would gain keys like `orchestrator.cli:build_wheel`. The subclass makes the platform's offer its own class. si#400 then builds on that class (C.2 makes product commands reference it).

---

### Task 1: The catalogue tasks and their ports, in the model and generated

**Files:**
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn` (the `Port` and `Task` classes, around lines 79-110)
- Create: `src/firn/model/simplon/catalogue/tasks.firn`
- Modify: `src/firn/templates/schema.firnt` (after the `NEEDS` block, around line 57)
- Regenerated: `src/simplon/domain/artifactschema.py`
- Test: `src/tests/test_catalogue_ports.py` (new)

**Interfaces:**
- Produces, in `simplon.domain.artifactschema`:
  - `class Port(NamedTuple)` with fields `name: str`, `direction: str` (`"input"` or `"output"`), `accepts: str` (a kind, kernel spelling: `test-result`, not `test_result`), `param: str` (`""` when the port has none) and `needs: tuple[str, ...]`;
  - `PORTS: dict[str, tuple[Port, ...]]`, catalogue coordinate to its ports, inputs first, in model order;
  - `BODIES: dict[str, str]`, catalogue coordinate to the body the model names (`module:function`, with `simplon.tasks.` written out).
- `READERS` and `NEEDS` are unchanged in this task.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_catalogue_ports.py`:

```python
"""si#344 C.1: the catalogue's tasks carry ports, modelled in firn and generated into artifactschema.

Every property is pinned on the committed generated module, without docker - firn v0.1.0 loses output
with rc 0 (firn#966), so the committed file is what has to be right.

AAA; the name states the behaviour under test.
"""
import importlib
import inspect

from simplon.domain import artifactschema, catalogue

P = artifactschema.Port
IMAGE_NEEDS = ("registry", "repository", "dockerfile", "context")
OCI_NEEDS = ("registry", "repository", "media_type", "path")


def test_the_ports_are_the_ones_measured_from_the_bodies():
    # assert: pinned as a literal - built from READERS on both sides, this could not see a wrong direction
    assert artifactschema.PORTS == {
        "build:image": (P("image", "output", "image", "name", IMAGE_NEEDS),),
        "test:image": (P("image", "input", "image", "name", IMAGE_NEEDS),),
        "release:image": (P("image", "input", "image", "name", IMAGE_NEEDS),),
        "release:artifact": (P("directory", "input", "directory", "name", OCI_NEEDS),),
        "build:conan-cache": (P("conan", "input", "conan", "name", OCI_NEEDS),),
        "release:conan": (P("conan", "input", "conan", "name", OCI_NEEDS),),
        "build:nuget-config": (P("nuget", "input", "nuget", "name", ("registry",)),),
        "build:nuget-restore": (P("nuget", "input", "nuget", "name", ("registry", "image", "project")),),
        "release:nuget": (P("nuget", "input", "nuget", "name", ("registry", "image", "project")),),
        "release:maven": (P("maven", "input", "maven", "name", ("registry", "image", "group", "modules")),),
        "docs:site": (P("site", "output", "site", "", ()),),
        "toolchain:run": (P("source", "input", "artifact", "", ()), P("out", "output", "artifact", "", ())),
    }


def test_every_modelled_task_is_a_catalogue_coordinate_with_the_body_the_catalogue_names():
    # arrange
    tasks = catalogue.load().tasks

    # act
    unknown = sorted(c for c in artifactschema.BODIES if c not in tasks)
    wrong = {c: (body, tasks[c]["impl"]) for c, body in artifactschema.BODIES.items()
             if c in tasks and tasks[c]["impl"] != body}

    # assert: the model and the hand-written catalogue are two sources for one body until si#400
    assert set(artifactschema.BODIES) == set(artifactschema.PORTS)
    assert unknown == []
    assert wrong == {}


def test_a_port_that_binds_a_parameter_names_one_its_body_takes():
    # arrange
    tasks = catalogue.load().tasks

    # act: the body's real signature, imported - a `param:` the body lacks would bind nothing at run time
    missing = {}
    for coordinate, ports in artifactschema.PORTS.items():
        module, function = tasks[coordinate]["impl"].split(":")
        params = inspect.signature(getattr(importlib.import_module(module), function)).parameters
        lost = [p.param for p in ports if p.param and p.param not in params]
        if lost:
            missing[coordinate] = lost

    # assert
    assert any(p.param for ports in artifactschema.PORTS.values() for p in ports), "no port binds anything"
    assert missing == {}


def test_every_port_accepts_a_kind_and_needs_only_keys_that_kind_has():
    # act
    unknown = {(c, p.name): p.accepts for c, ports in artifactschema.PORTS.items() for p in ports
               if p.accepts not in artifactschema.REFINES}
    stray = {(c, p.name): [k for k in p.needs if k not in type(artifactschema.validate(p.accepts, {"kind": p.accepts})).SHAPES]
             for c, ports in artifactschema.PORTS.items() for p in ports}

    # assert
    assert unknown == {}
    assert stray == {key: [] for key in stray}
    assert {p.direction for ports in artifactschema.PORTS.values() for p in ports} == {"input", "output"}


def test_a_task_has_no_two_ports_of_one_name_on_one_side():
    # act
    doubled = {c: names for c, ports in artifactschema.PORTS.items()
               for names in [[p.name for p in ports]] if len(names) != len(set(names))}

    # assert: `consumes: { image: ... }` must name exactly one port
    assert doubled == {}
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_ports.py -q -p no:cacheprovider`
Expected: 5 failed, each with `AttributeError: module 'simplon.domain.artifactschema' has no attribute 'Port'` (or `PORTS`/`BODIES`).

- [ ] **Step 3: Extend the metamodel**

In `src/firn/model/simplon/pipeline/pipeline.firn`, replace the `Port` class with the version below. It gains `needs`, which moves from the reader to the port that does the reading:

```
// A task's port (spec C.1): the kind it accepts (and every kind refining it), the body parameter that
// receives the bound artifact's NAME at run time, if any, and the keys that port NEEDS on the entry it
// reads (si#344 B2's requiredness, which belongs to the reader: `build:nuget-config` needs a registry only,
// `release:nuget` an image and a project too). Since si#344 C.1 the port IS the reader; KindReader is gone.
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
  property needs typeOf firn.core.Association {
    range = simplon.pipeline.ArtifactField
    subjectCardinality = 0..N
    objectCardinality = 0..N
  }
}
```

Directly after the `Task` class, add:

```
// A task the PLATFORM offers (si#344 C.1): a catalogue coordinate in `key`, its body in `body`. Its own
// class, because every product model declares plain Tasks in the same firn project (`support manifest
// model`), and a template over `Task` would gather theirs too. si#400 builds the base classes on this.
CatalogueTask typeOf firn.core.Class extends simplon.pipeline.Task {
  allowRoot = true
}
```

Leave `KindReader` in place for now. Task 2 deletes it once nothing reads it.

- [ ] **Step 4: Write the twelve catalogue tasks**

Create `src/firn/model/simplon/catalogue/tasks.firn`:

```
// simplon.catalogue (si#344 C.1): the catalogue's tasks that take or give an artifact, with their ports.
// Measured from the bodies on 2026-10-14 (docs/superpowers/plans/2026-10-14-si344-c1-ports-on-catalogue-tasks.md):
// all ten readers by name take `name`; the direction is what the body does with the entry. A port is named
// after the kind it accepts, so a product can guess it; `toolchain:run`'s two are the spec's `source`/`out`.
// `key` and `body` repeat catalogue.yaml's coordinate and impl until si#400 generates those from here;
// src/tests/test_catalogue_ports.py holds the two to each other.
package simplon.catalogue

build_image typeOf simplon.pipeline.CatalogueTask {
  key = "build:image"
  body = "simplon.tasks.image:build"
  output image typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.image
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.image.f_repository
    needs = simplon.vocabulary.image.f_dockerfile
    needs = simplon.vocabulary.image.f_context
  }
}
test_image typeOf simplon.pipeline.CatalogueTask {
  key = "test:image"
  body = "simplon.tasks.image:smoke"
  input image typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.image
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.image.f_repository
    needs = simplon.vocabulary.image.f_dockerfile
    needs = simplon.vocabulary.image.f_context
  }
}
release_image typeOf simplon.pipeline.CatalogueTask {
  key = "release:image"
  body = "simplon.tasks.image:release"
  input image typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.image
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.image.f_repository
    needs = simplon.vocabulary.image.f_dockerfile
    needs = simplon.vocabulary.image.f_context
  }
}
release_artifact typeOf simplon.pipeline.CatalogueTask {
  key = "release:artifact"
  body = "simplon.tasks.artifact:publish"
  input directory typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.directory
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.directory.f_repository
    needs = simplon.vocabulary.directory.f_media_type
    needs = simplon.vocabulary.artifact.f_path
  }
}
build_conan_cache typeOf simplon.pipeline.CatalogueTask {
  key = "build:conan-cache"
  body = "simplon.tasks.conan:fetch"
  input conan typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.conan
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.conan.f_repository
    needs = simplon.vocabulary.conan.f_media_type
    needs = simplon.vocabulary.artifact.f_path
  }
}
release_conan typeOf simplon.pipeline.CatalogueTask {
  key = "release:conan"
  body = "simplon.tasks.conan:publish"
  input conan typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.conan
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.conan.f_repository
    needs = simplon.vocabulary.conan.f_media_type
    needs = simplon.vocabulary.artifact.f_path
  }
}
build_nuget_config typeOf simplon.pipeline.CatalogueTask {
  key = "build:nuget-config"
  body = "simplon.tasks.nuget:config"
  input nuget typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.nuget
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
  }
}
build_nuget_restore typeOf simplon.pipeline.CatalogueTask {
  key = "build:nuget-restore"
  body = "simplon.tasks.nuget:restore"
  input nuget typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.nuget
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.nuget.f_image
    needs = simplon.vocabulary.nuget.f_project
  }
}
release_nuget typeOf simplon.pipeline.CatalogueTask {
  key = "release:nuget"
  body = "simplon.tasks.nuget:publish"
  input nuget typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.nuget
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.nuget.f_image
    needs = simplon.vocabulary.nuget.f_project
  }
}
release_maven typeOf simplon.pipeline.CatalogueTask {
  key = "release:maven"
  body = "simplon.tasks.maven:publish"
  input maven typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.maven
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.maven.f_image
    needs = simplon.vocabulary.maven.f_group
    needs = simplon.vocabulary.maven.f_modules
  }
}
docs_site typeOf simplon.pipeline.CatalogueTask {
  key = "docs:site"
  body = "simplon.tasks.site:build"
  output site typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.site
  }
}
toolchain_run typeOf simplon.pipeline.CatalogueTask {
  key = "toolchain:run"
  body = "simplon.tasks.toolchain:run_toolchain"
  input source typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.artifact
  }
  output out typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.artifact
  }
}
```

Before going on, check the `needs` references against `kinds.firn`: each `simplon.vocabulary.<kind>.f_<key>` must be the field where that key is *declared*. Copy each from the matching `KindReader` instance in `kinds.firn`, lines 155-229, which already reference the right ones.

- [ ] **Step 5: Check the model**

Run: `./simplon.sh test model`
Expected: rc 0.
If firn names an error:
- a composition child written as `output image typeOf ...`: read how `src/firn/model/product/simplon/simplon.firn` writes a composition child (`command wheel typeOf ...`) and match it;
- a name firn reserves (`out`, `source`): rename the *firn resource* and keep the port's name in a `key` attribute. Report that as a finding, because it changes the `Port` class.

- [ ] **Step 6: Generate `Port`, `PORTS` and `BODIES`**

In `src/firn/templates/schema.firnt`, directly after the closing `|}` of the `NEEDS` block, add:

```
    |
    |
    |class Port(NamedTuple):
    |    """One port of a catalogue task (si#344 C.1): its name, `input` or `output`, the kind it accepts (and
    |    every kind refining it), the body parameter that receives the bound artifact's name ("" for none) and
    |    the keys it needs on the entry it reads."""
    |
    |    name: str
    |    direction: str
    |    accepts: str
    |    param: str
    |    needs: tuple[str, ...]
    |
    |
    |#: Each catalogue task that takes or gives an artifact -> its ports, inputs first.
    |PORTS: dict[str, tuple[Port, ...]] = {
    for t : `simplon.pipeline.CatalogueTask` {
      |    "${t.key}": (
      for p : t.input {
        if p.param {
          |        Port("${p.name}", "input", "${p.accepts.name.replace("_", "-")}", "${p.param}", (<<for f : p.needs>>"${f.key}", <<end>>)),
        }
        if not p.param {
          |        Port("${p.name}", "input", "${p.accepts.name.replace("_", "-")}", "", (<<for f : p.needs>>"${f.key}", <<end>>)),
        }
      }
      for p : t.output {
        if p.param {
          |        Port("${p.name}", "output", "${p.accepts.name.replace("_", "-")}", "${p.param}", (<<for f : p.needs>>"${f.key}", <<end>>)),
        }
        if not p.param {
          |        Port("${p.name}", "output", "${p.accepts.name.replace("_", "-")}", "", (<<for f : p.needs>>"${f.key}", <<end>>)),
        }
      }
      |    ),
    }
    |}
    |
    |#: Each of those tasks -> the body the model names. catalogue.yaml names it too until si#400 generates it.
    |BODIES: dict[str, str] = {
    for t : `simplon.pipeline.CatalogueTask` {
      |    "${t.key}": "${t.body}",
    }
    |}
```

Add `NamedTuple` to the typing import line in the same template:
`|from typing import ClassVar, NamedTuple, TypeAlias`

- [ ] **Step 7: Generate, and read what firn wrote**

```bash
./simplon.sh build model
git status --short src/simplon src/site
git diff --stat src/simplon/domain/artifactschema.py
sed -n '/^class Port/,/^BODIES/p' src/simplon/domain/artifactschema.py
```

Expected:
- `artifactschema.py` modified, nothing deleted;
- twelve `PORTS` entries;
- `()` for an empty `needs` tuple, `("registry",)` for a single one.

The template writes `"registry", ` with a trailing comma, so a single key is a valid one-element tuple. If firn rejected `if p.param` on an attribute (only `if k.refines`, an association, is used today), the build names it. In that case give every port an explicit `param` (`param = ""` for none), drop the `if`/`if not` pair, and record it in the commit message as measured.

- [ ] **Step 8: Run the tests to see them pass**

Run: `./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_ports.py src/tests/test_generated_schema.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 9: See each new assertion red**

Break one property at a time in the **model**, then `./simplon.sh build model`, run the test, watch it fail, and restore with `git checkout -- src/firn src/simplon/domain/artifactschema.py`. Do not break the generated file by hand; that would test the editor, not the chain.

1. Flip `test_image`'s port from `input` to `output`. Expected red: `test_the_ports_are_the_ones_measured_from_the_bodies`.
2. Set `release_maven`'s `body = "simplon.tasks.maven:publish_argv"`. Expected red: `test_every_modelled_task_is_a_catalogue_coordinate_with_the_body_the_catalogue_names`.
3. Set `build_nuget_config`'s `param = "names"`. Expected red: `test_a_port_that_binds_a_parameter_names_one_its_body_takes`, with `{'build:nuget-config': ['names']}`.
4. Give `docs_site`'s port `needs = simplon.vocabulary.image.f_dockerfile`. Expected red: `test_every_port_accepts_a_kind_and_needs_only_keys_that_kind_has`.
5. Add a second `input source` to `toolchain_run`. If firn itself refuses the duplicate name, that is the stronger guard: note it, and keep the test as the guard for a generated file somebody edits.

- [ ] **Step 10: Full suite, mypy, gates**

```bash
./deploy/orchestrator/.venv/bin/python -m pytest src/tests -q -p no:cacheprovider
./deploy/orchestrator/.venv/bin/python -m mypy --config-file mypy.ini src/simplon
./simplon.sh test generated
./simplon.sh test model
```

Expected:
- pytest: all passed. 4832 passed and 2 skipped on main at 500be88, plus the 5 new tests.
- mypy: no issues.
- Both gates: rc 0.

`test_architecture` may need nothing, because no module was added. If `test_refusal_census` moves, stop: this task adds no `raise`.

- [ ] **Step 11: Commit**

```bash
git add src/firn/model/simplon/pipeline/pipeline.firn src/firn/model/simplon/catalogue/tasks.firn \
        src/firn/templates/schema.firnt src/simplon/domain/artifactschema.py src/tests/test_catalogue_ports.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): the catalogue's artifact tasks are modelled with their ports, and generated

C.1, first half. Twelve CatalogueTask instances in simplon.catalogue, each with
the ports measured from its body; artifactschema gains Port, PORTS and BODIES.
READERS and NEEDS are unchanged (still from KindReader until the next commit).

Seen red, each by breaking the MODEL and regenerating: <list the five from Step 9>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: `READERS` and `NEEDS` come from the ports; `KindReader` is deleted

**Files:**
- Modify: `src/firn/templates/schema.firnt` (the `READERS` and `NEEDS` blocks, around lines 44-57)
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn` (delete `KindReader`)
- Modify: `src/firn/model/simplon/vocabulary/kinds.firn` (delete the ten `KindReader` instances and the comment above them, lines 152-229)
- Regenerated: `src/simplon/domain/artifactschema.py`
- Modify: `src/tests/test_generated_schema.py` (wording only)
- Test: `src/tests/test_catalogue_ports.py`

**Interfaces:**
- Consumes `artifactschema.Port` and `artifactschema.PORTS` from Task 1.
- Produces `READERS: dict[str, str]` and `NEEDS: dict[str, tuple[str, ...]]`, with the same names, types and values as today. They are now plain Python over `PORTS`, so the template needs no filter (firn v0.1.0 templates have no equality test):

```python
READERS: dict[str, str] = {c: p.accepts for c, ports in PORTS.items() for p in ports if p.param == "name"}
NEEDS: dict[str, tuple[str, ...]] = {c: p.needs for c, ports in PORTS.items() for p in ports if p.param == "name"}
```

Consumers do not change: `domain/artifactsection.py:39-40`, `tasks/migrate.py`, and the tests.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_catalogue_ports.py`:

```python
def test_the_model_has_no_second_source_for_what_a_reader_reads():
    # arrange: KindReader was B2's placeholder ("Part C's ports replace it"); once ports exist it is a
    # second statement of the same fact, and two statements drift
    from pathlib import Path
    model = Path(__file__).resolve().parents[1] / "firn" / "model"
    template = Path(__file__).resolve().parents[1] / "firn" / "templates" / "schema.firnt"

    # act
    mentions = sorted(str(p.relative_to(model)) for p in model.rglob("*.firn") if "KindReader" in p.read_text())

    # assert
    assert mentions == []
    assert "KindReader" not in template.read_text()
    assert artifactschema.READERS == {c: p.accepts for c, ports in artifactschema.PORTS.items()
                                      for p in ports if p.param == "name"}
```

- [ ] **Step 2: Run it to see it fail**

Run: `./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_ports.py -q -p no:cacheprovider -k second_source`
Expected: FAIL. `mentions` lists `simplon/pipeline/pipeline.firn` and `simplon/vocabulary/kinds.firn`.

- [ ] **Step 3: Derive the two dicts from `PORTS` in the template**

In `src/firn/templates/schema.firnt`, delete the two blocks that loop over `simplon.pipeline.KindReader` (the `READERS` block and the `NEEDS` block, with their `#:` comment lines). Directly after the closing `|}` of `BODIES` (from Task 1), add:

```
    |
    |#: The catalogue coordinate that reads ONE entry by name (`with: { name: ... }`) -> the kind it reads: its
    |#: port that binds `name`. `simplon manifest migrate` derives a kindless entry's kind from it.
    |READERS: dict[str, str] = {c: p.accepts for c, ports in PORTS.items() for p in ports if p.param == "name"}
    |
    |#: The catalogue coordinate -> the keys that port needs, in the order a reader is told about them.
    |NEEDS: dict[str, tuple[str, ...]] = {c: p.needs for c, ports in PORTS.items() for p in ports if p.param == "name"}
```

The two dicts now stand after `PORTS`, because they read it.

- [ ] **Step 4: Delete `KindReader` from the model**

- In `pipeline.firn`, delete the `KindReader` class and its four comment lines ("A catalogue coordinate that reads ONE `artifacts:` entry by name ... Part C's ports replace it.").
- In `kinds.firn`, delete from the comment "The catalogue coordinates that read ONE `artifacts:` entry by name" to the end of the last `release_maven typeOf simplon.pipeline.KindReader { ... }` block.
- Grep for leftovers: `grep -rn KindReader src/ docs/superpowers/specs`. Fix comments in `src/`, and report any mention in the spec rather than editing the spec.

- [ ] **Step 5: Generate and check**

```bash
./simplon.sh build model
git status --short src/simplon src/site
./simplon.sh test model
./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_ports.py src/tests/test_generated_schema.py src/tests/test_artifactsection.py src/tests/test_migrate.py -q -p no:cacheprovider
```

Expected:
- `artifactschema.py` modified, not deleted;
- `test model` rc 0;
- all passed.

The regression net is `test_generated_schema.py`: `len(READERS) == 10`, the `NEEDS` literal in `test_a_reader_needs_what_its_body_checked_before_si344_b2`, and `test_every_reader_in_the_model_is_a_coordinate_whose_body_reads_that_kind`. If any of them goes red, the derivation is wrong. Fix the derivation, never the expected values.

- [ ] **Step 6: See it red**

Put one `KindReader` line back in a comment of `kinds.firn` (`// KindReader`). Run `-k second_source`, expect it red, then restore. Then change `param = "name"` to `param = "ref"` on `release_image` in the model and run `./simplon.sh build model`. Expect both `test_generated_schema.py::test_every_reader_names_a_catalogue_coordinate_a_kind_and_needs_of_that_kind` (9 readers, not 10) and `test_a_port_that_binds_a_parameter_names_one_its_body_takes` to go red. Restore with `git checkout -- src/firn src/simplon/domain/artifactschema.py`.

- [ ] **Step 7: Wording in `test_generated_schema.py`**

Replace the word "reader" only where a docstring or message says *where it comes from*, for example "every reader in the model" becoming "every port that binds `name` in the model". Leave every assertion untouched. `grep -n "KindReader\|reader" src/tests/test_generated_schema.py` lists them.

- [ ] **Step 8: Full suite, mypy, gates, commit**

```bash
./deploy/orchestrator/.venv/bin/python -m pytest src/tests -q -p no:cacheprovider
./deploy/orchestrator/.venv/bin/python -m mypy --config-file mypy.ini src/simplon
./simplon.sh test generated && ./simplon.sh test model
git add src/firn src/simplon/domain/artifactschema.py src/tests/test_catalogue_ports.py src/tests/test_generated_schema.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
refactor(si#344): READERS and NEEDS are the ports that bind `name`; KindReader is gone

C.1, second half. B2's placeholder said "Part C's ports replace it", and they
do: the two dicts are derived from PORTS in the generated module, with the
same values - test_generated_schema's literals, unchanged, are the proof.

Seen red: <the two from Step 6>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: The ports on the kinds page

**Files:**
- Modify: `src/firn/templates/docs.firnt`
- Regenerated: `src/site/content/with-what/kinds.md`
- Test: `src/tests/test_catalogue_ports.py`

**Interfaces:**
- Consumes `artifactschema.PORTS`.
- Produces a "Ports" section on `with-what/kinds.md`: one table row per port, with columns `Task | Port | Direction | Accepts | Binds`.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_catalogue_ports.py`:

```python
def test_the_kinds_page_lists_every_port_the_module_has():
    # arrange
    import re
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "kinds.md").read_text()
    row = re.compile(r"^\| `([a-z-]+:[a-z-]+)` \| `([a-z-]+)` \| (input|output) \| `([a-z-]+)` \| (`[a-z_]+`|) \|$", re.M)

    # act
    listed = {(c, n, d, a, b.strip("`")) for c, n, d, a, b in row.findall(page)}
    expected = {(c, p.name, p.direction, p.accepts, p.param)
                for c, ports in artifactschema.PORTS.items() for p in ports}

    # assert: the page is a second rendering of one model, so it is held to the module both ways
    assert expected, "no ports - the comparison would mean nothing"
    assert listed == expected
```

- [ ] **Step 2: Run it to see it fail**

Run: `./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_ports.py -q -p no:cacheprovider -k kinds_page`
Expected: FAIL, `listed == set()`.

- [ ] **Step 3: Render the table**

In `src/firn/templates/docs.firnt`, before the closing `}` of the `file` block, add the following. A table row starts with `||`, because the first `|` is firn's output marker:

```
    |
    |## Ports
    |
    |A catalogue task takes and gives artifacts through its ports. A port accepts a kind and every kind that
    |refines it; a port that binds a parameter receives the bound artifact's name in it.
    |
    || Task | Port | Direction | Accepts | Binds |
    ||---|---|---|---|---|
    for t : `simplon.pipeline.CatalogueTask` {
      for p : t.input {
        if p.param {
          || `${t.key}` | `${p.name}` | input | `${p.accepts.name.replace("_", "-")}` | `${p.param}` |
        }
        if not p.param {
          || `${t.key}` | `${p.name}` | input | `${p.accepts.name.replace("_", "-")}` |  |
        }
      }
      for p : t.output {
        if p.param {
          || `${t.key}` | `${p.name}` | output | `${p.accepts.name.replace("_", "-")}` | `${p.param}` |
        }
        if not p.param {
          || `${t.key}` | `${p.name}` | output | `${p.accepts.name.replace("_", "-")}` |  |
        }
      }
    }
```

If Task 1, Step 7 measured that `if p.param` is unsupported and every port got an explicit `param = ""`, use one line per direction instead of the `if` pair. An empty `${p.param}` then renders as ``` `` ```, so adjust the regex's last group to accept ``` `` ``` and strip it to `""`.

- [ ] **Step 4: Generate, check, see it pass and red**

```bash
./simplon.sh build model
git diff src/site/content/with-what/kinds.md
./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_ports.py -q -p no:cacheprovider
```

Expected: twelve tasks and thirteen rows; all tests pass.

To see it red, delete the `for p : t.output { ... }` block from the template, `build model`, run the test, watch it go red (the four output ports are missing), then `git checkout -- src/firn src/site`.

Then run the tests that already read `kinds.md`:
`./deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_generated_catalogue.py src/tests/test_own_whole_files.py src/tests/test_own_make_readable.py -q -p no:cacheprovider`
Expected: passed.

- [ ] **Step 5: Full suite, mypy, gates, commit**

```bash
./deploy/orchestrator/.venv/bin/python -m pytest src/tests -q -p no:cacheprovider
./deploy/orchestrator/.venv/bin/python -m mypy --config-file mypy.ini src/simplon
./simplon.sh test generated && ./simplon.sh test model
git add src/firn/templates/docs.firnt src/site/content/with-what/kinds.md src/tests/test_catalogue_ports.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
docs(si#344): the kinds page lists every catalogue port, generated from the model

Seen red: the template without its output loop drops the four output ports.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 4: Pull request

- [ ] **Step 1: Push and open the PR**

```bash
git push -q -u origin si344-c1-ports
```

Write the body to `/tmp/claude-0/-root-git-simplon/36693d3e-3ebc-423e-8e38-fca86fd4d6be/scratchpad/si344-c1-pr.md`, in English. It contains:
- the ports table above;
- the two judgement calls and the port-naming rule, each flagged for review;
- what was seen red;
- the test, mypy and gate results;
- "Part of #344 (C.1 of four plans)". Do **not** write `Closes #344`: C.2-C.4 are still open.

It ends with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
```

```bash
gh pr create --base main --milestone "M3 - ci / cd / support" \
  --title "feat(si#344): C.1 - the catalogue's artifact tasks carry ports, modelled in firn" \
  --body-file /tmp/claude-0/-root-git-simplon/36693d3e-3ebc-423e-8e38-fca86fd4d6be/scratchpad/si344-c1-pr.md
```

Do not merge; Marco merges.

---

## Review Focus

1. **A port name a product will type is surface.** `consumes: { nuget: lib }` versus `consumes: { package: lib }` is decided here and lives in every C.2 manifest. Check the kind-named rule against the four products' vocabulary before C.2 ships. No test can pin a naming choice; the review is the check.
2. **firn's loop over `CatalogueTask` must not include product `Task`s.** Product models live in the same firn project. `test_every_modelled_task_is_a_catalogue_coordinate_with_the_body_the_catalogue_names` goes red on any product task that leaks in, because `orchestrator.cli:build_wheel` is no catalogue coordinate. That test is the guard, in Task 1.
3. **firn v0.1.0 deleting or emptying `artifactschema.py` with rc 0** when a new selector answers nothing. If that happens, every `./simplon.sh` command stops at import. The existing guards are `build model-whole` and `test_generated_schema.py::test_the_committed_module_is_whole_and_says_it_is_generated`. Task 1, Step 7 reads the diff after every build.
4. **The same body in two models.** `simplon.catalogue.release_image` (key `release:image`) and a product model's `t_simplon_tasks_image_release` (key `simplon.tasks.image:release`) both describe one body after this plan. That is accepted until C.2 makes `support manifest model` reference the catalogue task. Name it in the PR so nobody reads the product models as the source of ports.
5. **A port with `param:` whose body later loses that parameter.** It would bind nothing at run time, and the run would then do "nothing to do" when it should fail, which is the house defect. `test_a_port_that_binds_a_parameter_names_one_its_body_takes` imports each body and reads its real signature, in Task 1.
