# The architecture as a firn model (si#390 part 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every module of `src/simplon/` belongs to one component in a firn model; firn generates the data for a hand-written test and a website page; the test is red on an unassigned module, an import against the layers that is not a named exception, and an exception no longer needed.

**Architecture:** A new M2 package `simplon.architecture` (Component, Module, Excluded, Exception) and an M1 package `simplon.components` with the six components, every module and the 14 exceptions. A new firn template file renders `src/tests/architecture.py` (data only, new firn target `tests`) and `src/site/content/with-what/architecture.md` (existing target `site`). `src/tests/test_architecture.py` reads every import with `ast` and holds the code to the data. Nothing in `src/simplon/` changes.

**Tech Stack:** firn v0.1.0 in its pinned image (only via `./simplon.sh test model` / `build model`), Python 3 `ast`, pytest, Hugo only via `./simplon.sh build docs`.

**Spec:** `docs/superpowers/specs/2026-10-13-architecture-as-a-firn-model-design.md` (ticket si#390; exceptions si#391-si#394).

## Global Constraints

- Layers: **kernel 0 < domain 1 < adapters 2 < tasks 3 < cli 4, ui 4**. An import is allowed inside a component or to a strictly lower layer; same layer, other component, is a violation (spec "The rule").
- An exception is one module edge with a reason and a ticket `si#<n>`; never a component edge.
- The generated data file is test code: `src/tests/architecture.py`. Nothing goes into `src/simplon/`, the wheel or `surface`.
- No module moves, no import in `src/simplon/` changes, no census change, nothing for a product to do.
- Counts are computed, never typed into a document (CLAUDE.md). The tests may assert design data (the component keys and layers), not module or exception counts.
- Every new assertion is seen red once (CLAUDE.md): break the property, run, see it fail, restore.
- firn only via `./simplon.sh test model` / `./simplon.sh build model`; Hugo only via `./simplon.sh build docs`. Never run `./simplon.sh` from a copy or worktree.
- Tests run from `src/tests` with `../../deploy/orchestrator/.venv/bin/python -m pytest -q`.
- Commits: identity by env (`GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info"`), message through a quoted heredoc, subject naming `si#390`, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG`. Never `git config`, `--amend` or force-push.
- A firn parser disagreement (a reserved name, a refused nested reference) is reported in the task report as a finding for firn, not patched around silently.

## Review Focus

1. **A relative import** (`from . import x`, `from ..tasks import image`) - must resolve to the right module, not be dropped. Test: `test_a_relative_import_is_resolved` (Task 2).
2. **`from simplon import __version__`** or another name that is not a module - must be ignored, not crash or invent a module. Test: `test_a_name_that_is_not_a_module_is_not_an_edge` (Task 2).
3. **An import inside a function body** - must count like a top-level one. Test: `test_an_import_inside_a_function_is_an_edge` (Task 2).
4. **A new module nobody assigned** - red naming the file. Test: `test_every_module_is_in_one_component_or_excluded` seen red (Task 2).
5. **firn#966: an empty selector deletes `architecture.py`, or a template error leaves only the id line** - `build model-whole` refuses it. Wired in Task 1, seen red in Task 1 Step 9.

---

## File structure

- Create `src/firn/model/simplon/architecture/architecture.firn` - M2: the four classes.
- Create `src/firn/model/simplon/components/components.firn` - M1: components, modules, exclusions, exceptions.
- Create `src/firn/templates/architecture.firnt` - templates `ArchitectureData` and `ArchitecturePage`.
- Modify `src/firn.toml` - new target `tests`; `ArchitecturePage` joins target `site`.
- Generated: `src/tests/architecture.py`, `src/site/content/with-what/architecture.md`.
- Modify `simplon.yaml` - `model-whole` / `model-mode` file lists; `generated:` entries; the `model` help text.
- Modify `src/tests/test_own_whole_files.py` - its `GENERATED` list.
- Create `src/tests/test_architecture.py` - the four checks and the resolver tests.
- Create `src/tests/test_architecture_page.py` - page and data agree.

---

### Task 1: The model, the data template, and the build wiring

**Files:**
- Create: `src/firn/model/simplon/architecture/architecture.firn`
- Create: `src/firn/model/simplon/components/components.firn`
- Create: `src/firn/templates/architecture.firnt` (template `ArchitectureData` only in this task)
- Modify: `src/firn.toml`
- Modify: `simplon.yaml` (`model-whole`, `model-mode`, `generated:`)
- Modify: `src/tests/test_own_whole_files.py:19`
- Generated: `src/tests/architecture.py`

**Interfaces:**
- Produces `src/tests/architecture.py` with exactly these names:
  - `COMPONENTS: dict[str, tuple[int, str]]` - component key -> (layer, summary)
  - `MODULES: dict[str, str]` - dotted path below `simplon` (e.g. `"orchestrator.steps"`, `"tasks.image"`, `"__init__"`) -> component key
  - `EXCLUDED: dict[str, str]` - dotted path -> reason
  - `EXCEPTIONS: tuple[tuple[str, str, str, str], ...]` - (importer path, imported path, reason, ticket)

- [ ] **Step 1: Write the M2 package**

`src/firn/model/simplon/architecture/architecture.firn`:

```
// simplon.architecture (si#390 part 1): simplon's own components, the module each holds, and the named
// exceptions to the layers. The M1 is simplon.components; src/tests/test_architecture.py holds the code to
// it. Every spelling a firn name cannot carry (a dotted path, a component key) is an attribute, as
// simplon.pipeline.ArtifactField carries `key`.
package simplon.architecture

// One component on one layer. An import may stay inside its component or go to a strictly lower layer.
// `layer` is an integer written as text (0-4); `summary` is one sentence, with no double quote in it,
// because the generated data file carries it in a Python string.
Component typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property layer typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property summary typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property module typeOf firn.core.Composition {
    range = simplon.architecture.Module
    subjectCardinality = 0..N
    objectCardinality = 0..1
  }
}

// One module below src/simplon/, by its dotted path ("orchestrator.steps", "tasks.image", "__init__").
Module typeOf firn.core.Class extends firn.core.NamedResource {
  property path typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
}

// A module that belongs to no component, and why.
Excluded typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property path typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property reason typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
}

// One import against the layers, allowed until its ticket resolves it. One module edge, never a
// component edge, so a new wrong import cannot pass behind an old one.
Exception typeOf firn.core.Class extends firn.core.NamedResource {
  allowRoot = true
  property importer typeOf firn.core.Association {
    range = simplon.architecture.Module
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property imported typeOf firn.core.Association {
    range = simplon.architecture.Module
    subjectCardinality = 1..1
    objectCardinality = 0..N
  }
  property reason typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property ticket typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
}
```

- [ ] **Step 2: Write the M1 package**

`src/firn/model/simplon/components/components.firn`, exactly as below. It was produced from the module files on 2026-10-13; if a module was added since, Task 2's completeness test names it and it is assigned there (report it).

```
// simplon's components (si#390 part 1), as M1 instances of simplon.architecture. Every module below
// src/simplon/ is in exactly one component or excluded with a reason; src/tests/test_architecture.py holds
// the model to the files and to every import. A module's firn name is `m_` and its path with `_` for `.`,
// because a firn name has no `.`; its spelling is `path`.
package simplon.components

kernel typeOf simplon.architecture.Component {
  key = "kernel"
  layer = "0"
  summary = "The base classes of tasks and commands (from part 4), and running a plan: steps, outcomes, the subprocess seam, the log."
  module m_orchestrator_steps typeOf simplon.architecture.Module {
    path = "orchestrator.steps"
  }
  module m_orchestrator_product typeOf simplon.architecture.Module {
    path = "orchestrator.product"
  }
  module m_run typeOf simplon.architecture.Module {
    path = "run"
  }
  module m_log typeOf simplon.architecture.Module {
    path = "log"
  }
  module m_verdict typeOf simplon.architecture.Module {
    path = "verdict"
  }
  module m_steplog typeOf simplon.architecture.Module {
    path = "steplog"
  }
  module m_waits typeOf simplon.architecture.Module {
    path = "waits"
  }
  module m_degraded typeOf simplon.architecture.Module {
    path = "degraded"
  }
  module m_filelock typeOf simplon.architecture.Module {
    path = "filelock"
  }
}
domain typeOf simplon.architecture.Component {
  key = "domain"
  layer = "1"
  summary = "Reading the configuration, validating it, and building the plan from it."
  module m_orchestrator_manifest typeOf simplon.architecture.Module {
    path = "orchestrator.manifest"
  }
  module m_orchestrator_model_treeform typeOf simplon.architecture.Module {
    path = "orchestrator.model.treeform"
  }
  module m_yamlkeys typeOf simplon.architecture.Module {
    path = "yamlkeys"
  }
  module m_artifactsection typeOf simplon.architecture.Module {
    path = "artifactsection"
  }
  module m_artifactschema typeOf simplon.architecture.Module {
    path = "artifactschema"
  }
  module m_environments typeOf simplon.architecture.Module {
    path = "environments"
  }
  module m_carrierspec typeOf simplon.architecture.Module {
    path = "carrierspec"
  }
  module m_layout typeOf simplon.architecture.Module {
    path = "layout"
  }
  module m_outputs typeOf simplon.architecture.Module {
    path = "outputs"
  }
  module m_deployment typeOf simplon.architecture.Module {
    path = "deployment"
  }
  module m_signatures typeOf simplon.architecture.Module {
    path = "signatures"
  }
  module m_context typeOf simplon.architecture.Module {
    path = "context"
  }
  module m_catalogue typeOf simplon.architecture.Module {
    path = "catalogue"
  }
  module m_runners typeOf simplon.architecture.Module {
    path = "runners"
  }
  module m_manifestmodel typeOf simplon.architecture.Module {
    path = "manifestmodel"
  }
  module m_clitaxonomy typeOf simplon.architecture.Module {
    path = "clitaxonomy"
  }
}
adapters typeOf simplon.architecture.Component {
  key = "adapters"
  layer = "2"
  summary = "The tools and platforms a task drives: docker, oras, a registry, a lab, a proxy."
  module m_awake typeOf simplon.architecture.Module {
    path = "awake"
  }
  module m_backend typeOf simplon.architecture.Module {
    path = "backend"
  }
  module m_checksum typeOf simplon.architecture.Module {
    path = "checksum"
  }
  module m_clablifecycle typeOf simplon.architecture.Module {
    path = "clablifecycle"
  }
  module m_clabrender typeOf simplon.architecture.Module {
    path = "clabrender"
  }
  module m_compose typeOf simplon.architecture.Module {
    path = "compose"
  }
  module m_credentials typeOf simplon.architecture.Module {
    path = "credentials"
  }
  module m_devcontainer typeOf simplon.architecture.Module {
    path = "devcontainer"
  }
  module m_disk typeOf simplon.architecture.Module {
    path = "disk"
  }
  module m_diskguard typeOf simplon.architecture.Module {
    path = "diskguard"
  }
  module m_docker typeOf simplon.architecture.Module {
    path = "docker"
  }
  module m_fetch typeOf simplon.architecture.Module {
    path = "fetch"
  }
  module m_githubpackages typeOf simplon.architecture.Module {
    path = "githubpackages"
  }
  module m_healthgate typeOf simplon.architecture.Module {
    path = "healthgate"
  }
  module m_host typeOf simplon.architecture.Module {
    path = "host"
  }
  module m_hostpath typeOf simplon.architecture.Module {
    path = "hostpath"
  }
  module m_imagenames typeOf simplon.architecture.Module {
    path = "imagenames"
  }
  module m_interact typeOf simplon.architecture.Module {
    path = "interact"
  }
  module m_labegress typeOf simplon.architecture.Module {
    path = "labegress"
  }
  module m_labhost typeOf simplon.architecture.Module {
    path = "labhost"
  }
  module m_labinstance typeOf simplon.architecture.Module {
    path = "labinstance"
  }
  module m_labnet typeOf simplon.architecture.Module {
    path = "labnet"
  }
  module m_linux typeOf simplon.architecture.Module {
    path = "linux"
  }
  module m_nexusproxy typeOf simplon.architecture.Module {
    path = "nexusproxy"
  }
  module m_oras typeOf simplon.architecture.Module {
    path = "oras"
  }
  module m_portainer typeOf simplon.architecture.Module {
    path = "portainer"
  }
  module m_ports typeOf simplon.architecture.Module {
    path = "ports"
  }
  module m_pyvenv typeOf simplon.architecture.Module {
    path = "pyvenv"
  }
  module m_tools typeOf simplon.architecture.Module {
    path = "tools"
  }
  module m_topology typeOf simplon.architecture.Module {
    path = "topology"
  }
  module m_tracker typeOf simplon.architecture.Module {
    path = "tracker"
  }
}
tasks typeOf simplon.architecture.Component {
  key = "tasks"
  layer = "3"
  summary = "The catalogue's task bodies, and the generators they call."
  module m_completiongen typeOf simplon.architecture.Module {
    path = "completiongen"
  }
  module m_taskgen typeOf simplon.architecture.Module {
    path = "taskgen"
  }
  module m_tasks_acceptance typeOf simplon.architecture.Module {
    path = "tasks.acceptance"
  }
  module m_tasks_allure typeOf simplon.architecture.Module {
    path = "tasks.allure"
  }
  module m_tasks_artifact typeOf simplon.architecture.Module {
    path = "tasks.artifact"
  }
  module m_tasks_asset typeOf simplon.architecture.Module {
    path = "tasks.asset"
  }
  module m_tasks_buildfiles typeOf simplon.architecture.Module {
    path = "tasks.buildfiles"
  }
  module m_tasks_carrier typeOf simplon.architecture.Module {
    path = "tasks.carrier"
  }
  module m_tasks_ciarm64 typeOf simplon.architecture.Module {
    path = "tasks.ciarm64"
  }
  module m_tasks_cidisk typeOf simplon.architecture.Module {
    path = "tasks.cidisk"
  }
  module m_tasks_ciprivileges typeOf simplon.architecture.Module {
    path = "tasks.ciprivileges"
  }
  module m_tasks_claudeplugins typeOf simplon.architecture.Module {
    path = "tasks.claudeplugins"
  }
  module m_tasks_cliref typeOf simplon.architecture.Module {
    path = "tasks.cliref"
  }
  module m_tasks_completion typeOf simplon.architecture.Module {
    path = "tasks.completion"
  }
  module m_tasks_conan typeOf simplon.architecture.Module {
    path = "tasks.conan"
  }
  module m_tasks_deploy typeOf simplon.architecture.Module {
    path = "tasks.deploy"
  }
  module m_tasks_docs typeOf simplon.architecture.Module {
    path = "tasks.docs"
  }
  module m_tasks_env typeOf simplon.architecture.Module {
    path = "tasks.env"
  }
  module m_tasks_generated typeOf simplon.architecture.Module {
    path = "tasks.generated"
  }
  module m_tasks_gitops typeOf simplon.architecture.Module {
    path = "tasks.gitops"
  }
  module m_tasks_hosttools typeOf simplon.architecture.Module {
    path = "tasks.hosttools"
  }
  module m_tasks_image typeOf simplon.architecture.Module {
    path = "tasks.image"
  }
  module m_tasks_manifestmodel typeOf simplon.architecture.Module {
    path = "tasks.manifestmodel"
  }
  module m_tasks_maven typeOf simplon.architecture.Module {
    path = "tasks.maven"
  }
  module m_tasks_migrate typeOf simplon.architecture.Module {
    path = "tasks.migrate"
  }
  module m_tasks_nexus typeOf simplon.architecture.Module {
    path = "tasks.nexus"
  }
  module m_tasks_nuget typeOf simplon.architecture.Module {
    path = "tasks.nuget"
  }
  module m_tasks_profiles typeOf simplon.architecture.Module {
    path = "tasks.profiles"
  }
  module m_tasks_proxmoxapi typeOf simplon.architecture.Module {
    path = "tasks.proxmoxapi"
  }
  module m_tasks_release typeOf simplon.architecture.Module {
    path = "tasks.release"
  }
  module m_tasks_releasenotes typeOf simplon.architecture.Module {
    path = "tasks.releasenotes"
  }
  module m_tasks_site typeOf simplon.architecture.Module {
    path = "tasks.site"
  }
  module m_tasks_tasks typeOf simplon.architecture.Module {
    path = "tasks.tasks"
  }
  module m_tasks_testrun typeOf simplon.architecture.Module {
    path = "tasks.testrun"
  }
  module m_tasks_toolchain typeOf simplon.architecture.Module {
    path = "tasks.toolchain"
  }
  module m_tasks_typecheck typeOf simplon.architecture.Module {
    path = "tasks.typecheck"
  }
  module m_tasks_vcs typeOf simplon.architecture.Module {
    path = "tasks.vcs"
  }
  module m_tasks_walk typeOf simplon.architecture.Module {
    path = "tasks.walk"
  }
  module m_tasks_workflows typeOf simplon.architecture.Module {
    path = "tasks.workflows"
  }
  module m_workflowgen typeOf simplon.architecture.Module {
    path = "workflowgen"
  }
}
cli typeOf simplon.architecture.Component {
  key = "cli"
  layer = "4"
  summary = "The command line: simplon and simplon init, and what a product may import."
  module m_cli typeOf simplon.architecture.Module {
    path = "cli"
  }
  module m_bootstrap typeOf simplon.architecture.Module {
    path = "bootstrap"
  }
  module m_surface typeOf simplon.architecture.Module {
    path = "surface"
  }
}
ui typeOf simplon.architecture.Component {
  key = "ui"
  layer = "4"
  summary = "Running a plan in front of a person."
  module m_orchestrator_tui typeOf simplon.architecture.Module {
    path = "orchestrator.tui"
  }
}
e_init typeOf simplon.architecture.Excluded {
  path = "__init__"
  reason = "The package itself; it imports no simplon module."
}
e_version typeOf simplon.architecture.Excluded {
  path = "_version"
  reason = "Written by setuptools-scm; it imports nothing."
}
e_orchestrator___init typeOf simplon.architecture.Excluded {
  path = "orchestrator.__init__"
  reason = "A package marker; it imports no simplon module."
}
e_orchestrator_model___init typeOf simplon.architecture.Excluded {
  path = "orchestrator.model.__init__"
  reason = "A package marker; it imports no simplon module."
}
e_tasks___init typeOf simplon.architecture.Excluded {
  path = "tasks.__init__"
  reason = "A package marker; it imports no simplon module."
}
e_test_impls typeOf simplon.architecture.Excluded {
  path = "test_impls"
  reason = "Bodies for the generator tests, not part of any component."
}
x_orchestrator_product__orchestrator_manifest typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_orchestrator_product
  imported = simplon.components.domain.m_orchestrator_manifest
  reason = "Imports `Manifest`."
  ticket = "si#391"
}
x_orchestrator_steps__orchestrator_manifest typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_orchestrator_steps
  imported = simplon.components.domain.m_orchestrator_manifest
  reason = "Imports `PlanNode`."
  ticket = "si#391"
}
x_steplog__context typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_steplog
  imported = simplon.components.domain.m_context
  reason = "Imports the module `context`."
  ticket = "si#391"
}
x_orchestrator_product__awake typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_orchestrator_product
  imported = simplon.components.adapters.m_awake
  reason = "Imports `keep_awake`."
  ticket = "si#391"
}
x_steplog__labinstance typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_steplog
  imported = simplon.components.adapters.m_labinstance
  reason = "Imports the module `labinstance`."
  ticket = "si#391"
}
x_orchestrator_steps__orchestrator_tui typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_orchestrator_steps
  imported = simplon.components.ui.m_orchestrator_tui
  reason = "Imports `run_pipeline`."
  ticket = "si#391"
}
x_steplog__cli typeOf simplon.architecture.Exception {
  importer = simplon.components.kernel.m_steplog
  imported = simplon.components.cli.m_cli
  reason = "Imports `provenance_line`."
  ticket = "si#391"
}
x_tasks_acceptance__bootstrap typeOf simplon.architecture.Exception {
  importer = simplon.components.tasks.m_tasks_acceptance
  imported = simplon.components.cli.m_bootstrap
  reason = "Imports `validate_relative_dir`."
  ticket = "si#392"
}
x_tasks_cliref__bootstrap typeOf simplon.architecture.Exception {
  importer = simplon.components.tasks.m_tasks_cliref
  imported = simplon.components.cli.m_bootstrap
  reason = "Imports `validate_relative_dir`."
  ticket = "si#392"
}
x_tasks_image__bootstrap typeOf simplon.architecture.Exception {
  importer = simplon.components.tasks.m_tasks_image
  imported = simplon.components.cli.m_bootstrap
  reason = "Imports `validate_relative_dir`."
  ticket = "si#392"
}
x_tasks_site__bootstrap typeOf simplon.architecture.Exception {
  importer = simplon.components.tasks.m_tasks_site
  imported = simplon.components.cli.m_bootstrap
  reason = "Imports `validate_relative_dir`."
  ticket = "si#392"
}
x_outputs__bootstrap typeOf simplon.architecture.Exception {
  importer = simplon.components.domain.m_outputs
  imported = simplon.components.cli.m_bootstrap
  reason = "Imports `validate_relative_dir`."
  ticket = "si#392"
}
x_deployment__tasks_image typeOf simplon.architecture.Exception {
  importer = simplon.components.domain.m_deployment
  imported = simplon.components.tasks.m_tasks_image
  reason = "Imports the module `tasks.image`."
  ticket = "si#393"
}
x_tasks_walk__orchestrator_tui typeOf simplon.architecture.Exception {
  importer = simplon.components.tasks.m_tasks_walk
  imported = simplon.components.ui.m_orchestrator_tui
  reason = "Imports `run_walk`."
  ticket = "si#394"
}
```

- [ ] **Step 3: Check the model**

Run: `./simplon.sh test model`
Expected: rc 0.

If firn refuses a name (`key`, `layer`, `module`, `Exception`, `importer`) or the nested reference `simplon.components.kernel.m_orchestrator_steps`: rename the property or class (`layer` -> `level`, `Exception` -> `LayerException`), or, for a refused nested reference, make `Module` `allowRoot = true` and move each module to the top level of `components.firn` with an added Association `component` (range `simplon.architecture.Component`, subjectCardinality 1..1, objectCardinality 0..N) - and adapt Step 4's template to `for m : \`simplon.architecture.Module\``. Record the exact firn error in the report as a finding for firn.

- [ ] **Step 4: Write the data template**

`src/firn/templates/architecture.firnt`:

```
template ArchitectureData {

  // src/tests/architecture.py (si#390 part 1): the components, every module's component, the exclusions
  // and the exceptions, as Python data for src/tests/test_architecture.py. A WHOLE file with no protected
  // region. The `file` block stands outside every `for`, so a selector that answers nothing leaves a file
  // with empty collections rather than no file - and `build model-whole` refuses a missing one.
  file "architecture.py" language python {
    |# GENERATED from src/firn/model/simplon/components/components.firn by `./simplon.sh build model`. Do not
    |# edit: firn rewrites the whole file on every run. Read by src/tests/test_architecture.py (si#390).
    |"""simplon's components, the module each one holds, and the named exceptions to the layers (si#390)."""
    |from __future__ import annotations
    |
    |#: Each component's layer and what it is for. An import stays in its component or goes to a lower layer.
    |COMPONENTS: dict[str, tuple[int, str]] = {
    for c : `simplon.architecture.Component` {
      |    "${c.key}": (${c.layer}, "${c.summary}"),
    }
    |}
    |
    |#: Every module below src/simplon/ that belongs to a component, by its dotted path.
    |MODULES: dict[str, str] = {
    for c : `simplon.architecture.Component` {
      for m : c.module {
        |    "${m.path}": "${c.key}",
      }
    }
    |}
    |
    |#: The modules that belong to no component, and why.
    |EXCLUDED: dict[str, str] = {
    for e : `simplon.architecture.Excluded` {
      |    "${e.path}": "${e.reason}",
    }
    |}
    |
    |#: (importer, imported, reason, ticket): each import against the layers, until its ticket resolves it.
    |EXCEPTIONS: tuple[tuple[str, str, str, str], ...] = (
    for x : `simplon.architecture.Exception` {
      |    ("<<for m : x.importer>>${m.path}<<end>>", "<<for m : x.imported>>${m.path}<<end>>", "${x.reason}", "${x.ticket}"),
    }
    |)
  }
}
```

- [ ] **Step 5: Add the target**

In `src/firn.toml`, after the `[target.simplon]` block, add:

```toml
# The architecture's data (si#390 part 1): test code, read by src/tests/test_architecture.py, never shipped.
[target.tests]
path = "tests"
templates = ["ArchitectureData"]
```

- [ ] **Step 6: Wire the guards**

In `simplon.yaml`, append `src/tests/architecture.py` to BOTH `model-whole: with: files:` and `model-mode: with: files:` (the lists must stay equal; `test_own_whole_files.py` holds them equal). Append the same path to `GENERATED` in `src/tests/test_own_whole_files.py:19`. Add to `generated:` after `artifact-schema:`:

```yaml
  # The architecture's data (si#390 part 1), generated WHOLE by firn into the tests: it has no protected
  # region, so a hand edit is lost on the next `build model` and is red here first.
  architecture-data:
    path: src/tests/architecture.py
    by: build model
```

- [ ] **Step 7: Generate**

Run: `./simplon.sh build model`
Expected: rc 0; `src/tests/architecture.py` exists; `git status --short` shows it new and nothing else changed by firn. Read it: four collections, every component of Step 2, one `MODULES` line per module, the exceptions with `si#391`-`si#394`.

- [ ] **Step 8: Write a smoke test of the data's design**

Append to a new file `src/tests/test_architecture.py`:

```python
"""si#390 part 1: every module of src/simplon/ belongs to one component, and imports go down the layers.

The data is generated by firn from src/firn/model/simplon/components/components.firn into
src/tests/architecture.py. This file reads every import of every module with `ast` - function-level and
relative imports included - and holds the code to that data in both directions.

Known limit: Python imports only. A body named by text (`impl: "module:function"` in the catalogue or a
manifest) is resolved at run time, and no layer applies to it.
"""
import architecture


def test_the_components_and_their_layers_are_the_ones_decided():
    # The design (spec decision 3), not a count.
    assert {key: layer for key, (layer, _) in architecture.COMPONENTS.items()} == {
        "kernel": 0, "domain": 1, "adapters": 2, "tasks": 3, "cli": 4, "ui": 4}
    assert all(summary.strip() for _, summary in architecture.COMPONENTS.values())
```

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_architecture.py test_own_whole_files.py`
Expected: PASS. Then change `"ui": 4` to `"ui": 3` in the test, see it FAIL, restore.

- [ ] **Step 9: See `build model-whole` red on the new file**

Replace the content of `src/tests/architecture.py` with only its id line (copy the last line of the file), run `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_own_whole_files.py::test_the_committed_generated_files_are_whole`, expect FAIL naming `src/tests/architecture.py`; then `git checkout -- src/tests/architecture.py` if committed, else `./simplon.sh build model`.

- [ ] **Step 10: Commit**

```bash
git add src/firn/model/simplon/architecture src/firn/model/simplon/components src/firn/templates/architecture.firnt src/firn.toml simplon.yaml src/tests/architecture.py src/tests/test_architecture.py src/tests/test_own_whole_files.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#390): simplon's components as a firn model, generated into the tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
./simplon.sh test generated
```
Expected: `test generated` rc 0 (it diffs against the index, so it runs after the commit).

---

### Task 2: The test that holds the code to the model

**Files:**
- Modify: `src/tests/test_architecture.py` (Task 1 created it)

**Interfaces:**
- Consumes `architecture.COMPONENTS`, `MODULES`, `EXCLUDED`, `EXCEPTIONS` (Task 1).
- Produces `modules_below(root: Path) -> set[str]`, `imports_of(root: Path, path: str, known: set[str]) -> set[str]`, `edges(root: Path) -> set[tuple[str, str]]`, `violates(importer: str, imported: str) -> bool` - module-level functions in `test_architecture.py`, used by its own tests only.

- [ ] **Step 1: Write the resolver and its tests**

Add to `src/tests/test_architecture.py` - the imports go to the top of the file beside Task 1's `import architecture` (one import block), the functions and tests below Task 1's test:

```python
import ast
import re
from pathlib import Path

import architecture

SRC = Path(__file__).resolve().parents[1] / "simplon"


def modules_below(root: Path) -> set[str]:
    """Every `.py` file below `root`, as its dotted path: `orchestrator/steps.py` -> `orchestrator.steps`."""
    return {".".join(p.relative_to(root).with_suffix("").parts) for p in root.rglob("*.py")}


def _resolve(name: str, known: set[str]) -> str | None:
    """The module a dotted name means: the longest prefix that is a module, or a package's `__init__`.
    None for a name that is no module (`__version__` imported from the package)."""
    parts = name.split(".") if name else []
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
        if f"{candidate}.__init__" in known:
            return f"{candidate}.__init__"
    return None


def imports_of(root: Path, path: str, known: set[str]) -> set[str]:
    """The modules below `root` that module `path` imports, anywhere in its body."""
    tree = ast.parse((root / (path.replace(".", "/") + ".py")).read_text(encoding="utf-8"))
    package = path.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name[len("simplon."):] for alias in node.names if alias.name.startswith("simplon.")]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package[: len(package) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            elif node.module == "simplon" or (node.module or "").startswith("simplon."):
                base = (node.module or "")[len("simplon"):].lstrip(".")
            else:
                continue
            names = [f"{base}.{alias.name}".lstrip(".") for alias in node.names]
        for name in names:
            target = _resolve(name, known)
            if target and target != path:
                found.add(target)
    return found


def edges(root: Path) -> set[tuple[str, str]]:
    known = modules_below(root)
    return {(path, target) for path in known for target in imports_of(root, path, known)}


def violates(importer: str, imported: str) -> bool:
    """True when the import goes against the layers: another component on the same or a higher layer."""
    a, b = architecture.MODULES[importer], architecture.MODULES[imported]
    return a != b and architecture.COMPONENTS[a][0] <= architecture.COMPONENTS[b][0]


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_relative_import_is_resolved(tmp_path):
    root = _package(tmp_path, {"__init__.py": "", "tasks/__init__.py": "", "run.py": "",
                               "tasks/image.py": "from .. import run\nfrom . import walk\n", "tasks/walk.py": ""})
    assert edges(root) >= {("tasks.image", "run"), ("tasks.image", "tasks.walk")}


def test_a_name_that_is_not_a_module_is_not_an_edge(tmp_path):
    # `__version__` is no module, so `_resolve` answers None and no edge is invented.
    root = _package(tmp_path, {"__init__.py": "__version__ = '1'\n", "cli.py": "from simplon import __version__\n"})
    assert edges(root) == set()


def test_an_import_inside_a_function_is_an_edge(tmp_path):
    root = _package(tmp_path, {"__init__.py": "", "run.py": "",
                               "steplog.py": "def f():\n    from simplon.run import x\n"})
    assert ("steplog", "run") in edges(root)


def test_the_walk_finds_the_imports_of_the_real_tree():
    # Non-vacuity: a resolver that found nothing would pass every check below.
    assert ("cli", "context") in edges(SRC)
```

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_architecture.py`
Expected: PASS. See each red once: change `node.level - 1` to `node.level` (relative test FAILS), restore; replace `ast.walk(tree)` with `tree.body` (function-level test FAILS), restore.

- [ ] **Step 2: Write the four checks**

Append:

```python
def test_every_module_is_in_one_component_or_excluded():
    files = modules_below(SRC)
    assigned, excluded = set(architecture.MODULES), set(architecture.EXCLUDED)
    assert not assigned & excluded, f"both assigned and excluded: {sorted(assigned & excluded)}"
    assert not files - assigned - excluded, (
        f"no component in src/firn/model/simplon/components/components.firn: {sorted(files - assigned - excluded)}")
    assert not (assigned | excluded) - files, f"in the model but not a file: {sorted((assigned | excluded) - files)}"


def _violations() -> set[tuple[str, str]]:
    return {(a, b) for a, b in edges(SRC)
            if a in architecture.MODULES and b in architecture.MODULES and violates(a, b)}


def test_every_import_goes_down_the_layers_or_is_a_named_exception():
    listed = {(importer, imported) for importer, imported, _, _ in architecture.EXCEPTIONS}
    unlisted = _violations() - listed
    assert not unlisted, (
        "imports against the layers (si#390); move the import, or name it as an exception with a ticket: "
        + ", ".join(f"{a} -> {b} ({architecture.MODULES[a]} -> {architecture.MODULES[b]})" for a, b in sorted(unlisted)))


def test_no_exception_outlives_its_import():
    listed = {(importer, imported) for importer, imported, _, _ in architecture.EXCEPTIONS}
    stale = listed - _violations()
    assert not stale, f"resolved - delete the exception from components.firn: {sorted(stale)}"


def test_every_exception_names_its_reason_and_its_ticket():
    seen: set[tuple[str, str]] = set()
    for importer, imported, reason, ticket in architecture.EXCEPTIONS:
        assert (importer, imported) not in seen, f"named twice: {importer} -> {imported}"
        seen.add((importer, imported))
        assert reason.strip(), f"{importer} -> {imported} has no reason"
        assert re.fullmatch(r"si#\d+", ticket), f"{importer} -> {imported} names no ticket: {ticket!r}"
```

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_architecture.py`
Expected: PASS. If `test_every_import_goes_down_the_layers_or_is_a_named_exception` or `test_no_exception_outlives_its_import` FAILS on the committed model, the spec's measured table and the real test disagree: STOP and report both sets; do not edit the model to make it pass.

- [ ] **Step 3: See each check red**

Edit `src/tests/architecture.py` by hand for each, run the test, see it FAIL with the message naming the case, then `git checkout -- src/tests/architecture.py`:
1. delete the line `"labnet": "adapters",` -> `test_every_module_is_in_one_component_or_excluded` FAILS naming `labnet`;
2. delete the `("tasks.walk", "orchestrator.tui", ...)` line -> the layers test FAILS naming `tasks.walk -> orchestrator.tui`;
3. add `("cli", "context", "x", "si#1"),` -> `test_no_exception_outlives_its_import` FAILS naming it;
4. change one ticket to `"later"` -> the reason/ticket test FAILS.

- [ ] **Step 4: Commit**

```bash
git add src/tests/test_architecture.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
test(si#390): every module has a component and every import goes down the layers or is named

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: The architecture page

**Files:**
- Modify: `src/firn/templates/architecture.firnt` (add `ArchitecturePage`)
- Modify: `src/firn.toml` (`[target.site]` templates)
- Modify: `simplon.yaml` (`model-whole`, `model-mode`, `generated:`, `model` help)
- Modify: `src/tests/test_own_whole_files.py:19`
- Create: `src/tests/test_architecture_page.py`
- Generated: `src/site/content/with-what/architecture.md`

**Interfaces:**
- Consumes `architecture.COMPONENTS`, `MODULES`, `EXCEPTIONS` (Task 1).

- [ ] **Step 1: Write the page test**

`src/tests/test_architecture_page.py`:

```python
"""si#390 part 1: the architecture page and the test data come from one model, so they agree."""
import re
from pathlib import Path

import architecture

PAGE = Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "architecture.md"


def test_the_page_lists_every_component_with_its_layer():
    text = PAGE.read_text(encoding="utf-8")
    rows = {key: int(layer) for layer, key in re.findall(r"^\| (\d) \| `([a-z]+)` \|", text, re.M)}
    assert text.startswith("---\n"), "Hugo needs the front matter as the first bytes"
    assert rows == {key: layer for key, (layer, _) in architecture.COMPONENTS.items()}


def test_the_page_names_every_module_under_its_component():
    text = PAGE.read_text(encoding="utf-8")
    for key in architecture.COMPONENTS:
        section = re.search(rf"^## {key}\n\n(.*)$", text, re.M)
        assert section, f"no section for {key}"
        listed = set(re.findall(r"`([\w.]+)`", section.group(1)))
        assert listed == {m for m, c in architecture.MODULES.items() if c == key}


def test_the_page_lists_every_exception_with_its_ticket():
    text = PAGE.read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `([\w.]+)` -> `([\w.]+)` \| .* \| (si#\d+) \|$", text, re.M))
    assert rows == {(a, b, t) for a, b, _, t in architecture.EXCEPTIONS}


def test_the_page_says_what_the_test_does_not_see():
    assert "resolved at run time" in PAGE.read_text(encoding="utf-8")
```

Run: `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_architecture_page.py`
Expected: FAIL (no page).

- [ ] **Step 2: Write the page template**

Append to `src/firn/templates/architecture.firnt`:

```
template ArchitecturePage {

  // src/site/content/with-what/architecture.md (si#390 part 1). `language html`: firn has no markdown
  // language (E200 on v0.1.0). A line starting with `|` in the output needs `||`.
  file "architecture.md" language html {
    |---
    |title: "Architecture"
    |weight: 7
    |---
    |
    |GENERATED from `src/firn/model/simplon/components/components.firn` by `./simplon.sh build model` (si#390).
    |
    |Every module of `src/simplon/` belongs to one component. An import may stay inside its component or go
    |to a component on a lower layer; two components on the same layer do not import each other. Any other
    |import is a named exception below, with the ticket that resolves it. `src/tests/test_architecture.py`
    |holds the code to this page.
    |
    |The test reads Python imports only. A body named by text - `impl: "module:function"` in the catalogue
    |or a manifest - is resolved at run time, and no layer applies to it.
    |
    || Layer | Component | What it is for |
    ||---|---|---|
    for c : `simplon.architecture.Component` {
      || ${c.layer} | `${c.key}` | ${c.summary} |
    }
    for c : `simplon.architecture.Component` {
      |
      |## ${c.key}
      |
      |<<for m : c.module sep ", ">>`${m.path}`<<end>>
    }
    |
    |## Exceptions
    |
    || Import | Why | Ticket |
    ||---|---|---|
    for x : `simplon.architecture.Exception` {
      || `<<for m : x.importer>>${m.path}<<end>>` -> `<<for m : x.imported>>${m.path}<<end>>` | ${x.reason} | ${x.ticket} |
    }
  }
}
```

(If Task 1 Step 3 moved modules to the top level, the per-component list iterates `for m : \`simplon.architecture.Module\`` with `if` on the component instead - whatever Task 1 recorded; the test above is the same either way.)

- [ ] **Step 3: Wire it**

`src/firn.toml`: `[target.site]` `templates = ["Docs", "ArchitecturePage"]`. `simplon.yaml`: append `src/site/content/with-what/architecture.md` to `model-whole` and `model-mode` files (equal lists); add to `generated:` after `architecture-data:`:

```yaml
  # The architecture page (si#390 part 1), generated by firn beside the kinds page.
  architecture-page:
    path: src/site/content/with-what/architecture.md
    by: build model
```

In the `model` command's `help:`, add "the architecture data and page" to what it generates. Append the page to `GENERATED` in `src/tests/test_own_whole_files.py`.

- [ ] **Step 4: Generate and test**

Run: `./simplon.sh build model` (rc 0), then `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q test_architecture_page.py test_own_whole_files.py`
Expected: PASS. See red: in the generated page change one exception's ticket, run, see `test_the_page_lists_every_exception_with_its_ticket` FAIL, regenerate.

- [ ] **Step 5: Build the site**

Run: `./simplon.sh build docs`
Expected: rc 0, the page renders (Hugo via docker only).

- [ ] **Step 6: Commit**

```bash
git add src/firn/templates/architecture.firnt src/firn.toml simplon.yaml src/tests/test_own_whole_files.py src/tests/test_architecture_page.py src/site/content/with-what/architecture.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
docs(si#390): the architecture page, generated from the same model as the test data

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
./simplon.sh test generated
```
Expected: rc 0.

---

### Task 4: Gates and the PR body

**Files:** none in the repo; `pr-body.md` in the plan workspace.

- [ ] **Step 1: Run every gate on the final commit**

- `cd src/tests && ../../deploy/orchestrator/.venv/bin/python -m pytest -q` - all pass (the 4 skips are pre-existing).
- `./simplon.sh test typecheck-python`, `./simplon.sh test model`, `./simplon.sh build model` (then `git status --short` empty), `./simplon.sh test generated`, `./simplon.sh build docs` - each rc 0.

- [ ] **Step 2: Write the PR body**

Title: `si#390 part 1: simplon's components as a firn model, and a test for the import direction`. Body: what changes (the model, the two generated files, the test, the page), the six components and layers, the exceptions with their tickets (from the generated data, not typed counts), the known limit (text references), the gates with rc, `Refs #390`, ending with the Claude Code line, a blank line, and the session URL.
