# si#344 C.2 — commands bind ports with `produces:`/`consumes:`, and the load rules hold the bindings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command binds its task's ports with `produces: { <port>: <artifact> }` and `consumes: { <port>: <artifact> }`, a product task may declare its own ports, and the loader holds every binding to the artifacts and the plans (spec C.5 rules 1-5 and 7). `simplon manifest migrate` rewrites the old `with: { name: X }`, and `support manifest model` references the catalogue's tasks instead of re-declaring them.

**Architecture:** There is one new module, `src/simplon/domain/ports.py`. It reads a task's ports, reads a command's bindings, and checks rules 1, 2, 3 and 5 on the loaded manifest. `treeform._resolve_one` calls it while it resolves a command, writes the binding into `with:` for a port that has a `param:`, and enforces rule 7 there. Rule 7 is the one expression rule; it sits in a tree module, so the census's reach measurement already covers it. `CommandSpec` carries the result as `task`, `produces`, `consumes` and `ports`. The migration gets a fourth pass, `_bind`. The manifest model exports the bindings, and the metamodel's `produces` becomes an Association.

**Tech Stack:** Python 3, pydantic, pytest, firn v0.1.0 (`ghcr.io/marcozwyssig/firn:v0.1.0`, run by `./simplon.sh build model` and `./simplon.sh test model`).

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md`, Parts C.2, C.5 and C.7. Decisions taken after the spec:
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6161492956 (C measured; C does not wait for products).
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6162459829 (C.2 measured and decided by Marco, 2026-10-14):
  1. **`with: { name: X }` alone stays valid.** On a parameter that a port binds, it is read as that port's binding. Rule 7 refuses only a port binding together with `with:` on that port's parameter.
  2. **Rule 1 is one producer per artifact *per plan*.** Several commands may produce one artifact: firn has three `build:image` commands for `firn`. No aggregate's plan may hold two of them. In the metamodel, `produces` becomes an Association.

## Scope: what is C.2 and what is not

| Plan | Content |
|---|---|
| C.1 (merged, PR #417) | ports on the catalogue tasks, modelled and generated |
| **C.2 (this)** | `produces:`/`consumes:`; product `input:`/`output:`; load rules 1-5 and 7; the `_bind` migration pass; the manifest model references catalogue tasks and exports bindings |
| C.3 | test results, `evidence`, the release rule (6), the release aggregate, `release:notes`, rule 8 |
| C.4 | workflowgen `upload-artifact`/`download-artifact` from the edges, and which producer an edge across jobs means |

**Not in C.2:**
- **Rule 6** (the release rule): that is C.3.
- **A refusal of `with: name` alone**: by decision 1, that is a later cut.
- **An aggregate's derived outputs** (`AggregateCommand.produced`): the metamodel already derives them, and C.2 adds nothing there.

## Global Constraints

- **Branch and PR:** branch `si344-c2-bindings` from `main`. The PR is in milestone "M3 - ci / cd / support" and its body says "Part of #344 (C.2 of four plans)". Do **not** write `Closes #344`. Never merge; Marco merges.
- **Commits:** set the identity env on every commit; `git config` and `--amend` are blocked:
  `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'`
  The message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
  ```
- **Python:** always `./deploy/orchestrator/.venv/bin/python`.
  - `PY` below means `./deploy/orchestrator/.venv/bin/python`.
  - Tests: `PY -m pytest src/tests -q -p no:cacheprovider` (about 2 min). Redirect the full run to a file and read its tail.
  - mypy: `PY -m mypy --config-file mypy.ini src/simplon`.
- **Generated files are never edited by hand.** These are:
  - `src/simplon/catalogue.yaml` outside its protected region;
  - `src/simplon/domain/artifactschema.py`;
  - `src/site/content/with-what/kinds.md`;
  - `src/firn/model/product/simplon/simplon.firn`;
  - `src/site/content/with-what/commands.md`.

  Edit the source, then regenerate. `./simplon.sh test generated` compares against the git **index**, so stage the regenerated files first. Both `./simplon.sh test generated` and `./simplon.sh test model` must be green before any commit that touches `src/firn/`, `simplon.yaml` or a generated file.
- **firn v0.1.0 loses output with rc 0** (firn#966). After every `./simplon.sh build model`, run `git status --short src/simplon src/site` and read each generated diff. If `artifactschema.py` is gone or empty, run `git checkout -- src/simplon/domain/artifactschema.py` and fix the template.
- **CLAUDE.md:**
  - See every new assertion red: break the property, run the test, watch it fail, restore. Write down in the commit which break turned it red.
  - Report findings, do not patch them away.
  - **Every new `raise` on the load path gets a census entry in the same commit**, in `src/tests/test_refusal_census.py` `CENSUS`. An expression rule also gets a `REACH` entry. The census's counts on `src/site/content/with-what/rules.md` are held by `test_the_page_prints_the_census_count_for_each_kind` and `test_the_page_prints_the_reach_of_the_expression_rules`, so each task that adds a refusal updates those two tables to the numbers the census computes. Edit only the numbers.
  - A census key is `(module, function, fragment)`, and the fragment is a piece of the message's **literal** text. `test_every_census_key_names_exactly_one_refusal` fails when a fragment matches zero refusals or two.
- **Kinds:** every rule asks the catalogue's kinds: `getattr(catalogue, "kinds", {}) or artifactsection.REFINES`, the same fallback `artifactsection.check` uses in `manifest.load`.
- **Port names are the catalogue's** (C.1): `image`, `directory`, `conan`, `nuget`, `maven`, `site`, `source`, `out`. `simplon.domain.artifactschema.PORTS` is the one source; nothing in this plan restates it.

## The measurement this plan stands on (2026-10-14, the eight manifests fetched through the API)

| manifest | form | `with: name` on a port task |
|---|---|---|
| simplon | `ci:`/`cd:` | `build image` → `kernel` (block `with:`); `release image` → `kernel` (block) |
| firn | `ci:`/`cd:` | `build toolchain` → `toolchain`; `build image`, `build release-image`, `build image-arm64` → `firn` (flow, two with `platform:`); six `test:image` → `firn` (three `with: &anchor` blocks, three `{ <<: *anchor, platform: ... }`); `release push-image` → `firn` |
| agile-cockpit | `groups:` (old) | `build build` → `app`, `release image` → `app` (flow) |
| the other five | `groups:` (old) | none |

No aggregate in firn plans two of the three `firn` producers; `plan_for` was walked for every aggregate. The frozen fixtures in `src/tests/fixtures/manifests/` are the same eight in the pre-A form, and `test_migrate.py` migrates and loads all of them. **That suite is the measurement of every new rule over every reachable manifest.** A real manifest that a new rule refuses turns it red; that is a finding to report to Marco, not a stub to edit.

## File Structure

- **Create** `src/simplon/domain/ports.py`. It holds:
  - `of(ref, product_tasks)`: a task's ports;
  - `declared(task, spec)`: a product task's `input:`/`output:` (Task 2);
  - `bindings(where, ref, spec, ports)`: a command's `produces:`/`consumes:`;
  - `check(manifest, declared, kinds)`: rules 1, 2, 3 and 5 (Task 3).
- **Modify** `src/simplon/domain/treeform.py`:
  - `_resolve_one`: bind, rule 7, `with: name` read as the binding;
  - `TASK_KEYS` and `check_task`: product ports (Task 2).
- **Modify** `src/simplon/domain/manifest.py`:
  - `CommandSpec` and `_CommandSpecModel` gain `task`, `produces`, `consumes` and `ports`;
  - `load` builds them and calls `ports.check` (Task 3).
- **Modify** `src/simplon/domain/artifactsection.py`: `declared(document)`, each entry's kind and whether it names a registry (Task 3).
- **Modify** `src/simplon/tasks/migrate.py`: the `_bind` pass (Task 4).
- **Modify** `simplon.yaml`: migrated by its own command (Task 4).
- **Modify** `src/simplon/domain/manifestmodel.py` and `src/firn/model/simplon/pipeline/pipeline.firn` (Task 5).
- **Regenerate** `src/firn/model/product/simplon/simplon.firn` (Task 5).
- **Modify** these pages:
  - `src/site/content/how/manifest.md`;
  - `src/site/content/how/task-and-command.md`;
  - `src/firn/templates/docs.firnt`, then regenerate `kinds.md`;
  - `src/site/content/with-what/rules.md` (numbers only).
- **Tests:**
  - create `src/tests/test_port_bindings.py` (Tasks 1-3);
  - extend `src/tests/test_migrate.py` (Task 4), `src/tests/test_manifestmodel.py` (Task 5) and `src/tests/test_catalogue_ports.py` (Task 6);
  - extend `src/tests/test_refusal_census.py` (Tasks 1-3).

---

### Task 1: A command binds a catalogue task's ports

**Files:**
- Create: `src/simplon/domain/ports.py`
- Modify: `src/simplon/domain/treeform.py` (`_resolve_one`, lines 590-646)
- Modify: `src/simplon/domain/manifest.py` (`CommandSpec` lines 43-125, `_CommandSpecModel` lines 373-391, the `CommandSpec(...)` construction in `load` around line 937)
- Modify: `src/tests/test_treeform.py` (two exact-equality asserts, see Step 6)
- Modify: `src/tests/test_refusal_census.py`, `src/site/content/with-what/rules.md`
- Test: `src/tests/test_port_bindings.py` (new)

**Interfaces:**
- Produces, in `simplon.domain.ports`:
  - `SIDE: dict[str, str] = {"output": "produces", "input": "consumes"}`;
  - `of(ref: str, product_tasks: Mapping[str, object]) -> tuple[Port, ...]`, where `Port` is `simplon.domain.artifactschema.Port`;
  - `bindings(where: str, ref: str, spec: Mapping[str, object], ports: tuple[Port, ...]) -> dict[str, dict[str, tuple[str, ...]]]`, which returns `{"produces": {port: (artifact, ...)}, "consumes": {...}}`.
- Produces, on `simplon.domain.manifest.CommandSpec`, four new trailing fields with defaults:
  - `task: str = ""`: the `task:` the command named, a coordinate or a product task name;
  - `produces: dict[str, tuple[str, ...]] = {}`;
  - `consumes: dict[str, tuple[str, ...]] = {}`;
  - `ports: tuple[Port, ...] = ()`.
- Produces, in `treeform.resolve`'s output: every resolved leaf carries `"task": ref`; `"produces"`/`"consumes"` appear only when non-empty; a port with `param:` adds `{param: artifact}` to `"with"`.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_port_bindings.py`:

```python
"""si#344 C.2: a command binds its task's ports with `produces:` and `consumes:`; the loader holds every
binding to the task's ports, to the artifacts and to the plans (spec C.5 rules 1-5 and 7).

Decided 2026-10-14 (si#344): `with: { name: X }` alone, on the parameter a port binds, is read as that
port's binding; rule 1 is one producer per artifact PER PLAN.

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.domain import catalogue
from simplon.domain import manifest as manifest_mod

ARTIFACTS = """\
artifacts:
  kernel: { kind: image, registry: ghcr.io/o, repository: k, dockerfile: Dockerfile, context: . }
  local: { kind: image, dockerfile: Dockerfile, context: . }
  docs: { kind: directory, registry: ghcr.io/o, repository: d, media_type: text/html, path: build/site }
"""


def _load(commands: str, *, tasks: str = "", artifacts: str = ARTIFACTS) -> manifest_mod.Manifest:
    text = f"product: demo\n{tasks}ci:\n{commands}{artifacts}"
    return manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")


def _refusal(commands: str, *, tasks: str = "", artifacts: str = ARTIFACTS) -> str:
    with pytest.raises(ValueError) as caught:
        _load(commands, tasks=tasks, artifacts=artifacts)
    return str(caught.value)


def test_produces_binds_the_output_port_and_hands_the_name_to_its_parameter():
    # act
    spec = _load("  build:\n    commands:\n"
                 '      image: { task: "build:image", produces: { image: kernel } }\n').spec_for("build", "image")

    # assert: the body still receives `name`, which is how an artifact reaches it (spec C.1)
    assert spec.produces == {"image": ("kernel",)}
    assert spec.consumes == {}
    assert spec.with_ == {"name": "kernel"}
    assert spec.task == "build:image"
    assert [p.name for p in spec.ports] == ["image"]


def test_consumes_binds_the_input_port():
    # act
    m = _load("  build:\n    commands:\n"
              '      image: { task: "build:image", produces: { image: kernel } }\n'
              "  release:\n    commands:\n"
              '      image: { task: "release:image", consumes: { image: kernel } }\n')

    # assert
    assert m.spec_for("release", "image").consumes == {"image": ("kernel",)}
    assert m.spec_for("release", "image").with_ == {"name": "kernel"}


def test_with_name_alone_is_read_as_the_binding():
    # act: the form simplon and firn write today (decided 2026-10-14)
    spec = _load("  build:\n    commands:\n"
                 '      image: { task: "build:image", with: { name: kernel, platform: linux/amd64 } }\n'
                 ).spec_for("build", "image")

    # assert
    assert spec.produces == {"image": ("kernel",)}
    assert spec.with_ == {"name": "kernel", "platform": "linux/amd64"}


def test_with_name_that_is_not_a_string_is_left_as_it_was():
    # act: `name: 25` was never a binding the loader could read; the run-time reader rules on it as before
    spec = _load("  build:\n    commands:\n"
                 '      image: { task: "build:image", with: { name: 25 } }\n', artifacts="").spec_for("build", "image")

    # assert
    assert spec.produces == {}
    assert spec.with_ == {"name": 25}


def test_a_task_without_ports_binds_nothing_and_says_which_ports_it_has():
    # act
    message = _refusal("  build:\n    commands:\n"
                       '      wheel: { task: "build:nuget-config", produces: { nuget: kernel } }\n')

    # assert: rule 4, and the direction is part of the port's name
    assert message == ("command 'build wheel' binds `produces: nuget`, and task 'build:nuget-config' has no "
                       "output port 'nuget' - its output ports: none")


def test_a_port_name_the_task_does_not_have_is_refused_with_the_ones_it_has():
    # act
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { img: kernel } }\n')

    # assert
    assert message == ("command 'build image' binds `produces: img`, and task 'build:image' has no output "
                       "port 'img' - its output ports: image")


def test_a_binding_that_is_not_a_mapping_is_refused():
    # act
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: [kernel] }\n')

    # assert
    assert message.startswith("command 'build image' declares `produces:` as list, not a mapping. "
                              "`produces:` binds a port to an artifact")


@pytest.mark.parametrize("value", ["''", "7", "{ a: b }"])
def test_a_binding_to_something_that_is_not_an_artifact_name_is_refused(value):
    # act
    message = _refusal("  build:\n    commands:\n"
                       f'      image: {{ task: "build:image", produces: {{ image: {value} }} }}\n')

    # assert
    assert "command 'build image' binds port 'image' to" in message
    assert "names an artifact" in message


def test_a_list_on_a_port_that_hands_one_name_to_its_parameter_is_refused():
    # act
    message = _refusal("  release:\n    commands:\n"
                       '      image: { task: "release:image", consumes: { image: [kernel, local] } }\n')

    # assert
    assert message == ("command 'release image' binds port 'image' to a list, and that port hands ONE "
                       "artifact's name to `name` - bind one artifact")


def test_a_binding_beside_with_on_the_parameter_it_binds_is_refused():
    # act: rule 7, the one expression rule here - both say the same fact
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: kernel }, with: { name: kernel } }\n')

    # assert
    assert message == ("command 'build image' binds a port and also pins name with `with:`. The binding "
                       "hands the artifact's name to that parameter - drop it from `with:`")


def test_a_binding_on_a_parameter_the_command_presents_with_params_is_refused():
    # act: the bound parameter is off the command line, so its presentation renders nowhere
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: kernel },'
                       ' params: { name: { help: "x" } } }\n')

    # assert
    assert "pins name with `with:` and also declares `params:` for it" in message
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_port_bindings.py -q -p no:cacheprovider`
Expected: most tests FAIL. `CommandSpec` has no `produces` (AttributeError), and `produces:` is ignored today, so no refusal is raised ("DID NOT RAISE"). `test_with_name_that_is_not_a_string_is_left_as_it_was` fails on `spec.produces`.

- [ ] **Step 3: Create `ports.py`**

```python
"""Port bindings (si#344 C.2): a command binds its task's ports with `produces:` and `consumes:`.

A port is `artifactschema.Port`. A catalogue task's ports come from the model (`PORTS`, generated, si#344
C.1); a product task's come from its own `input:`/`output:`. A port with a `param:` hands the bound
artifact's NAME to that body parameter - the only way an artifact reaches a body (spec C.1) - so the
loader writes the binding into the command's `with:`. A port without one is checked and modelled only.

`with: { name: X }` alone, on the parameter a port binds, is read as that port's binding (decided
2026-10-14, si#344): the rules see an unmigrated manifest too, and `simplon manifest migrate` rewrites it.
"""
from __future__ import annotations

from collections.abc import Mapping

from simplon.domain.artifactschema import PORTS, Port

#: The command key that binds each direction's ports.
SIDE = {"output": "produces", "input": "consumes"}


def of(ref: str, product_tasks: Mapping[str, object]) -> tuple[Port, ...]:
    """The ports of the task a command's `task:` names: the model's for a coordinate. A product task has
    none until it may declare them."""
    if ":" in ref:
        return PORTS.get(ref, ())
    return ()


def bindings(where: str, ref: str, spec: Mapping[str, object],
             ports: tuple[Port, ...]) -> dict[str, dict[str, tuple[str, ...]]]:
    """The command's `produces:` and `consumes:` as {key: {port: (artifact, ...)}}, each port one of
    `ports` on the side its key binds (rule 4)."""
    out: dict[str, dict[str, tuple[str, ...]]] = {"produces": {}, "consumes": {}}
    for direction, key in SIDE.items():
        raw = spec.get(key)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"command '{where}' declares `{key}:` as {type(raw).__name__}, not a mapping. `{key}:` binds "
                f"a port to an artifact: `{key}: {{ <port>: <artifact> }}`")
        offered = {p.name: p for p in ports if p.direction == direction}
        for name, value in raw.items():
            port = offered.get(str(name))
            if port is None:
                raise ValueError(
                    f"command '{where}' binds `{key}: {name}`, and task '{ref}' has no {direction} port "
                    f"'{name}' - its {direction} ports: {', '.join(sorted(offered)) or 'none'}")
            out[key][port.name] = _artifacts(where, key, port, value)
    return out


def _artifacts(where: str, key: str, port: Port, value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if key == "consumes" and isinstance(value, list) and value \
            and all(isinstance(item, str) and item.strip() for item in value):
        if port.param:
            raise ValueError(
                f"command '{where}' binds port '{port.name}' to a list, and that port hands ONE artifact's "
                f"name to `{port.param}` - bind one artifact")
        return tuple(item.strip() for item in value)
    raise ValueError(
        f"command '{where}' binds port '{port.name}' to {value!r}: `{key}:` names an artifact"
        + (", or a list of them on a port without `param:`" if key == "consumes" else ""))
```

- [ ] **Step 4: Bind in `treeform._resolve_one`**

Add `from simplon.domain import artifactsection, ports` (replacing the single `artifactsection` import). In `_resolve_one`, after `template = dict((source or {})[ref])` and `check_task(ref, template)`, replace everything from `out = {"impl": template["impl"], **spec}` to the end of the function with:

```python
    task_ports = ports.of(ref, product_tasks)
    bound = ports.bindings(where, ref, spec, task_ports)
    # Rule 7 (spec C.5, si#344 C.2): a binding hands the artifact's name to its port's parameter, so `with:`
    # on that same parameter is a second source for one fact.
    twice = sorted(p.param for p in task_ports
                   if p.param and p.name in bound[ports.SIDE[p.direction]] and p.param in (with_ or {}))
    if twice:
        raise ValueError(
            f"command '{where}' binds a port and also pins {', '.join(twice)} with `with:`. The binding "
            f"hands the artifact's name to that parameter - drop it from `with:`")
    # `with: { name: X }` alone is read as the binding (decided 2026-10-14, si#344)
    for p in task_ports:
        side = bound[ports.SIDE[p.direction]]
        if p.param and p.name not in side and isinstance((with_ or {}).get(p.param), str):
            side[p.name] = (str((with_ or {})[p.param]),)
    by_binding = {p.param: bound[ports.SIDE[p.direction]][p.name][0] for p in task_ports
                  if p.param and p.name in bound[ports.SIDE[p.direction]]}

    out = {"impl": template["impl"], **spec, "task": ref}
    out.pop("produces", None)
    out.pop("consumes", None)
    for key, side in bound.items():
        if side:
            out[key] = side
    for key in INHERITED:
        if key not in out and key in template:
            out[key] = template[key]
    # (keep the existing comment block about `with:` and `params:` here, unchanged)
    own = spec.get("params") or {}
    pinned_values = {**(with_ or {}), **by_binding}
    pinned = sorted(set(pinned_values) & set(own))
    if pinned:
        raise ValueError(
            f"command '{where}' pins {', '.join(pinned)} with `with:` and also declares `params:` for "
            f"it. A pinned parameter is off the command line, so its presentation renders nowhere - "
            f"drop the `params:` entry, or drop the pin if the user should still be able to set it")
    if by_binding:
        out["with"] = pinned_values
    params = {key: value for key, value in {**(template.get("params") or {}), **own}.items()
              if key not in pinned_values}
    if params:
        out["params"] = params
    return out
```

- [ ] **Step 5: Carry it on `CommandSpec`**

In `manifest.py`, add `from simplon.domain import ports` beside the other domain imports, and `from simplon.domain.artifactschema import Port`. Append to `CommandSpec`, after `params`:

```python
    # si#344 C.2: the `task:` this command named (a coordinate, or a product task's bare name; "" for an
    # aggregate), the artifacts it binds to its task's ports, and those ports.
    task: str = ""
    produces: dict[str, tuple[str, ...]] = {}
    consumes: dict[str, tuple[str, ...]] = {}
    ports: tuple[Port, ...] = ()
```

Append to `_CommandSpecModel`, after `unattended`:

```python
    task: str = ""
    produces: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    consumes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
```

In `load`, add these to the `CommandSpec(...)` call, after `with_=spec.with_,`:

```python
                                  task=spec.task, produces=spec.produces, consumes=spec.consumes,
                                  ports=ports.of(spec.task, product_tasks) if spec.task else (),
```

- [ ] **Step 6: Run the new tests and the tree tests**

Run: `PY -m pytest src/tests/test_port_bindings.py src/tests/test_treeform.py -q -p no:cacheprovider`
Expected: `test_port_bindings.py` all PASS. In `test_treeform.py`, exactly `test_a_coordinate_resolves_against_the_catalogue` and `test_a_bare_name_resolves_against_the_product_and_the_command_keeps_its_own_help` FAIL, because the resolved dict now carries `"task"`. Update both asserts to add `"task": "vcs:push"` and `"task": "lab-image"`, and in the first one change the comment `and \`task\` is gone` to `and \`task\` is kept: the model and the port rules read it (si#344 C.2)`. Ledger the change as a ruling. Rerun: PASS.

- [ ] **Step 7: See the rules red**

Break each property in turn, run `test_port_bindings.py`, and confirm the named test fails. Restore after each break:
- In `ports.bindings`, comment out the `if port is None: raise` → `test_a_port_name_the_task_does_not_have...` fails with a KeyError/AttributeError.
- In `_resolve_one`, comment out the rule 7 `raise` → `test_a_binding_beside_with_on_the_parameter_it_binds_is_refused` fails with "DID NOT RAISE".
- Delete the "read as the binding" loop → `test_with_name_alone_is_read_as_the_binding` fails.

- [ ] **Step 8: Census entries, and the page's numbers**

Run: `PY -m pytest src/tests/test_refusal_census.py -q -p no:cacheprovider`
Expected: FAIL in `test_every_load_time_refusal_is_classified`, naming the new raises in `ports.bindings` (four) and `treeform._resolve_one` (one).

Add a `# --- ports.py (si#344 C.2) ---` block to `CENSUS`:

```python
    # --- ports.py (si#344 C.2) ------------------------------------------------------------------------
    # A binding the task cannot take: no working meaning, so all four are diagnosis. Rule 4 (port names exist
    # on the task) is the second; the spec files it under C.5 as a merged-reach diagnosis.
    ("ports", "bindings", "binds a port to an artifact"): DIAGNOSIS,
    ("ports", "bindings", "has no"): DIAGNOSIS,
    ("ports", "_artifacts", "hands ONE artifact's name"): DIAGNOSIS,
    ("ports", "_artifacts", "names an artifact"): DIAGNOSIS,
```

Under the treeform block, add:

```python
    # si#344 C.2 rule 7: a port binding and `with:` on the parameter it binds say one fact twice. When the two
    # agree the manifest would have worked, so it is an expression rule (spec C.7); it binds the kernel too.
    ("treeform", "_resolve_one", "binds a port and also pins"): EXPRESSION,
```

and in `REACH`: `("treeform", "_resolve_one", "binds a port and also pins"): REACH_MERGED,`.

Rerun the census suite. `test_the_page_prints_the_census_count_for_each_kind` and `test_the_page_prints_the_reach_of_the_expression_rules` now fail with the computed numbers. Edit only the numbers in the two tables of `src/site/content/with-what/rules.md` (`| diagnosis |`, `| expression rule |`, `| **all load-time refusals** |`, `| the kernel is held to it too |`) to match. Rerun: PASS. If `test_every_merged_reach_expression_rule_ruled_on_the_kernels_own_declarations` fails, that is a finding: stop and ledger it.

- [ ] **Step 9: Full suite, mypy, commit**

Run the full suite into a file and read its tail, then run mypy.
Expected: all pass except the known flaky `test_container_lifecycle_e2e` (rerun once if it fails), and mypy is clean. A real-manifest test in `test_migrate.py` that turns red is a finding: report it, do not edit the fixture.

```bash
git add src/simplon/domain/ports.py src/simplon/domain/treeform.py src/simplon/domain/manifest.py \
  src/tests/test_port_bindings.py src/tests/test_treeform.py src/tests/test_refusal_census.py \
  src/site/content/with-what/rules.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): a command binds its task's ports with produces: and consumes:

C.2 Task 1. A binding on a port with `param:` is written into `with:`, so the body receives
the artifact's name as before. `with: { name: X }` alone is read as the binding (decided
2026-10-14). Rule 7 refuses a binding beside `with:` on the same parameter (expression rule,
merged reach); rule 4 and three shape diagnoses are in ports.bindings.

Seen red: <which break turned which test red>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: A product task declares its own ports

**Files:**
- Modify: `src/simplon/domain/ports.py` (`declared`, and `of` for a bare name)
- Modify: `src/simplon/domain/treeform.py` (`TASK_KEYS` line 543, `check_task` lines 547-571)
- Modify: `src/site/content/how/task-and-command.md` (lines 49-53 and the quoted message at lines 105-106)
- Modify: `src/tests/test_refusal_census.py`, `src/site/content/with-what/rules.md`
- Test: `src/tests/test_port_bindings.py`

**Interfaces:**
- Consumes: `ports.of`, `ports.bindings` and `CommandSpec.ports` (Task 1).
- Produces: `ports.declared(task: str, spec: Mapping[str, object]) -> tuple[Port, ...]`, inputs first, `needs=()`. `TASK_KEYS` becomes `("impl", "help", "passthrough_args", "params", "unattended", "input", "output")`.

- [ ] **Step 1: Write the failing tests** (append to `test_port_bindings.py`)

```python
PRODUCT_TASK = """\
tasks:
  pack:
    impl: "orchestrator.cli:pack"
    help: "Pack the site."
    input:
      site: { accepts: site }
    output:
      bundle: { accepts: directory, param: name }
"""


def test_a_product_task_declares_ports_and_its_command_binds_them():
    # act
    spec = _load("  build:\n    commands:\n"
                 "      pack: { task: pack, consumes: { site: web }, produces: { bundle: docs } }\n",
                 tasks=PRODUCT_TASK,
                 artifacts=ARTIFACTS + "  web: { kind: site, path: build/site }\n").spec_for("build", "pack")

    # assert: the port with `param:` hands the name over; the one without is checked only
    assert [(p.name, p.direction, p.accepts, p.param) for p in spec.ports] == [
        ("site", "input", "site", ""), ("bundle", "output", "directory", "name")]
    assert spec.consumes == {"site": ("web",)}
    assert spec.produces == {"bundle": ("docs",)}
    assert spec.with_ == {"name": "docs"}


@pytest.mark.parametrize("ports,fragment", [
    ("    output: [bundle]\n", "declares `output:` as list, not a mapping of port name to port"),
    ("    output:\n      bundle: directory\n", "port 'bundle' is not a mapping: it takes `accepts:`"),
    ("    output:\n      bundle: { accepts: directory, kind: x }\n", "port 'bundle' declares unknown key `kind:`"),
    ("    output:\n      bundle: { param: name }\n", "port 'bundle' declares no `accepts:`"),
    ("    output:\n      bundle: { accepts: directory, param: 3 }\n", "`param:` is the name of a body parameter"),
    ("    input:\n      bundle: { accepts: site }\n    output:\n      bundle: { accepts: directory }\n",
     "declares port 'bundle' as an input and an output"),
])
def test_a_port_declaration_the_loader_cannot_read_is_refused(ports, fragment):
    # arrange
    tasks = ('tasks:\n  pack:\n    impl: "orchestrator.cli:pack"\n    help: "Pack."\n' + ports)

    # act
    message = _refusal("  build:\n    commands:\n      pack: { task: pack }\n", tasks=tasks)

    # assert
    assert message.startswith("task 'pack' ")
    assert fragment in message
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_port_bindings.py -q -p no:cacheprovider -k "product_task or port_declaration"`
Expected: FAIL. `check_task` refuses `input:`/`output:` with "declares unknown key `input:`" (or `output:`), so every case's message differs from the expected one.

- [ ] **Step 3: Implement `declared` and widen `of`**

In `ports.py`:

```python
#: What a port declaration takes.
_PORT_KEYS = ("accepts", "param")


def declared(task: str, spec: Mapping[str, object]) -> tuple[Port, ...]:
    """A product task's own `input:` and `output:` (si#344 C.2) as Ports, inputs first. The shape only:
    which kinds exist is the catalogue's, and `check` holds `accepts:` to it."""
    out: list[Port] = []
    seen: dict[str, str] = {}
    for direction in ("input", "output"):
        raw = spec.get(direction)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"task '{task}' declares `{direction}:` as {type(raw).__name__}, not a mapping of port name to "
                f"port: `{direction}: {{ <port>: {{ accepts: <kind>, param: <parameter> }} }}`")
        for key, body in raw.items():
            name = str(key)
            if not isinstance(body, Mapping):
                raise ValueError(
                    f"task '{task}' port '{name}' is not a mapping: it takes `accepts:` and optionally `param:`")
            unknown = sorted(str(k) for k in body if k not in _PORT_KEYS)
            if unknown:
                raise ValueError(
                    f"task '{task}' port '{name}' declares unknown key `{unknown[0]}:` - a port takes "
                    f"{', '.join(_PORT_KEYS)}")
            accepts, param = body.get("accepts"), body.get("param", "")
            if not isinstance(accepts, str) or not accepts.strip():
                raise ValueError(
                    f"task '{task}' port '{name}' declares no `accepts:` - name the kind of artifact it takes")
            if not isinstance(param, str):
                raise ValueError(
                    f"task '{task}' port '{name}': `param:` is the name of a body parameter, written as text")
            if name in seen:
                raise ValueError(
                    f"task '{task}' declares port '{name}' as an {seen[name]} and an {direction}: a port name "
                    f"says which port a command binds, so it names one")
            seen[name] = direction
            out.append(Port(name, direction, accepts.strip(), param.strip(), ()))
    return tuple(out)
```

Change `of` to read a product task's ports:

```python
def of(ref: str, product_tasks: Mapping[str, object]) -> tuple[Port, ...]:
    """The ports of the task a command's `task:` names: the model's for a coordinate, the task's own
    `input:`/`output:` for a product task."""
    if ":" in ref:
        return PORTS.get(ref, ())
    spec = product_tasks.get(ref)
    return declared(ref, spec) if isinstance(spec, Mapping) else ()
```

In `treeform.py`, set `TASK_KEYS = ("impl", "help", "passthrough_args", "params", "unattended", "input", "output")`, and at the end of `check_task` add `ports.declared(name, spec)`. The shape is checked where every other task key is.

- [ ] **Step 4: Run them to verify they pass**

Run: `PY -m pytest src/tests/test_port_bindings.py src/tests/test_treeform.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: See it red**

Comment out the duplicate-name `raise`, run the parametrised test, and see its last case fail. Restore.

- [ ] **Step 6: The page quotes the message, so update it**

In `src/site/content/how/task-and-command.md`:
- Line 49: "A task takes exactly five keys:" → "A task takes exactly seven keys:".
- The `text` block below it: `impl   help   passthrough_args   params   unattended   input   output`.
- The quoted refusal at lines 105-106 → `> task 'wheel' declares unknown key \`group:\`. A task takes impl, help, passthrough_args, params,\n> unattended, input, output - check the spelling.`
- After the second `text` block (the command keys), add `produces` and `consumes` to the command key list.
- Line 102: "Anything outside the five" → "Anything outside the seven".

Then confirm the quote against the real message: `PY -c "from simplon.domain import treeform; treeform.check_task('wheel', {'impl': 'a:b', 'group': 1})"`. Its text must equal the quote, line break aside.

- [ ] **Step 7: Census, page numbers, full suite, mypy, commit**

Add to the ports block of `CENSUS` (six diagnoses):

```python
    # A product task's port declaration the loader cannot read (si#344 C.2): diagnosis, each one.
    ("ports", "declared", "not a mapping of port name to port"): DIAGNOSIS,
    ("ports", "declared", "is not a mapping: it takes"): DIAGNOSIS,
    ("ports", "declared", "a port takes"): DIAGNOSIS,
    ("ports", "declared", "declares no `accepts:`"): DIAGNOSIS,
    ("ports", "declared", "is the name of a body parameter"): DIAGNOSIS,
    ("ports", "declared", "a port name says which port"): DIAGNOSIS,
```

Update the numbers in `rules.md` to what the census computes. Run the census suite, then the full suite and mypy.

```bash
git add src/simplon/domain/ports.py src/simplon/domain/treeform.py src/tests/test_port_bindings.py \
  src/tests/test_refusal_census.py src/site/content/with-what/rules.md src/site/content/how/task-and-command.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): a product task declares its own input: and output: ports

C.2 Task 2. Six shape diagnoses in ports.declared, checked where every other task key is.
Which kinds exist is the catalogue's; Task 3 holds `accepts:` to it.

Seen red: <which break>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: The load rules hold every binding to the artifacts and the plans

**Files:**
- Modify: `src/simplon/domain/ports.py` (`check`, `_check_plan`)
- Modify: `src/simplon/domain/artifactsection.py` (`declared`)
- Modify: `src/simplon/domain/manifest.py` (`load`: the call before `return`)
- Modify: `src/tests/test_refusal_census.py`, `src/site/content/with-what/rules.md`
- Test: `src/tests/test_port_bindings.py`

**Interfaces:**
- Consumes: `CommandSpec.task/produces/consumes/ports` (Task 1); product ports (Task 2).
- Produces:
  - `artifactsection.declared(document: Mapping[str, object]) -> dict[str, tuple[str, bool]]`: entry name → (its kind, whether it names a `registry:`);
  - `ports.check(manifest: Manifest, declared: Mapping[str, tuple[str, bool]], kinds: Mapping[str, str]) -> None`.

**Why `artifactsection.declared` and not a read in `ports`:** `artifactsection` is already the census's reader of `artifacts:`. If `ports` took the document, it would become a second reader that the census has to account for. Handing it a plain mapping keeps one reader.

- [ ] **Step 1: Write the failing tests** (append to `test_port_bindings.py`)

```python
BUILD = '  build:\n    commands:\n      image: { task: "build:image", produces: { image: local } }\n'


def test_an_artifact_no_entry_declares_is_refused():
    # act: rule 3 cannot hold a kind it does not know
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: ghost } }\n')

    # assert
    assert message == ("command 'build image' binds 'ghost' to port 'image', and `artifacts:` declares no "
                       "'ghost' - declare it there with its `kind:`")


def test_an_artifact_of_a_kind_the_port_does_not_accept_is_refused():
    # act: rule 3, kind conformance through `refines`
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: docs } }\n')

    # assert
    assert message == ("command 'build image' binds 'docs', a `directory`, to port 'image', which accepts "
                       "`image` and the kinds that refine it")


def test_a_port_that_accepts_the_root_kind_takes_every_kind():
    # act: `toolchain:run`'s ports accept `artifact`, which every kind refines
    m = _load(BUILD + '      tool: { task: "toolchain:run", consumes: { source: [local, docs] } }\n')

    # assert
    assert m.spec_for("build", "tool").consumes == {"source": ("local", "docs")}


def test_a_product_port_accepting_a_kind_the_catalogue_lacks_is_refused():
    # arrange
    tasks = 'tasks:\n  pack:\n    impl: "orchestrator.cli:pack"\n    help: "Pack."\n' \
            "    output:\n      bundle: { accepts: tarball }\n"

    # act
    message = _refusal("  build:\n    commands:\n      pack: { task: pack }\n", tasks=tasks)

    # assert
    assert message.startswith("command 'build pack': port 'bundle' of task 'pack' accepts 'tarball', which is "
                              "no kind the catalogue declares - it declares: artifact")


def test_a_consumer_with_no_producer_and_no_registry_is_refused():
    # act: rule 2
    message = _refusal("  release:\n    commands:\n"
                       '      image: { task: "release:image", consumes: { image: local } }\n')

    # assert
    assert message == ("command 'release image' consumes 'local', and no command produces it - produce it "
                       "with a command, or give it a `registry:` it is fetched from")


def test_a_consumer_of_an_artifact_with_a_registry_needs_no_producer():
    # act: rule 2's exception, an external input (si#343)
    m = _load("  release:\n    commands:\n"
              '      image: { task: "release:image", consumes: { image: kernel } }\n')

    # assert
    assert m.spec_for("release", "image").consumes == {"image": ("kernel",)}


def test_several_producers_of_one_artifact_load_when_no_plan_holds_two():
    # act: firn's three `build:image` for one image (decided 2026-10-14)
    m = _load("  build:\n    commands:\n"
              '      image: { task: "build:image", with: { name: kernel, platform: linux/amd64 } }\n'
              '      image-all: { task: "build:image", with: { name: kernel } }\n')

    # assert
    assert m.spec_for("build", "image-all").produces == {"image": ("kernel",)}


def test_a_plan_holding_two_producers_of_one_artifact_is_refused():
    # act: rule 1, per plan
    message = _refusal("  build:\n    commands:\n"
                       '      image: { task: "build:image", produces: { image: kernel } }\n'
                       '      image-all: { task: "build:image", produces: { image: kernel } }\n'
                       '      all: { depends_on: [image, image-all], help: "Everything." }\n')

    # assert
    assert message == ("aggregate 'build all' plans two producers of 'kernel': 'image' and 'image-all' - one "
                       "plan builds an artifact once, so plan one of them")


def test_a_plan_that_consumes_before_it_produces_is_refused():
    # act: rule 5 - the run order is `depends_on`, and this one contradicts the data
    message = _refusal("  build:\n    commands:\n"
                       '      make: { task: "build:image", produces: { image: local } }\n'
                       "  release:\n    commands:\n"
                       '      push: { task: "release:image", consumes: { image: local } }\n'
                       '      all: { depends_on: [push, make], help: "Release." }\n')

    # assert
    assert message == ("aggregate 'release all' plans 'push' before 'make', and 'push' consumes 'local', which "
                       "'make' produces - list 'make' first in `depends_on`")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_port_bindings.py -q -p no:cacheprovider`
Expected: the refusal tests FAIL with "DID NOT RAISE". The load tests PASS already. They are guards for the exceptions, and Step 5 sees each of them red.

- [ ] **Step 3: Implement**

In `artifactsection.py`, after `check`:

```python
def declared(document: Mapping[str, object]) -> dict[str, tuple[str, bool]]:
    """Each `artifacts:` entry -> (its kind, whether it names a `registry:`), for the port rules (si#344
    C.2). `check` has refused an entry without a kind before this is asked."""
    section = document.get(SECTION)
    if not isinstance(section, Mapping):
        return {}
    return {str(name): (str(body["kind"]), bool(body.get("registry")))
            for name, body in section.items() if isinstance(body, Mapping) and "kind" in body}
```

In `ports.py`, add `from typing import TYPE_CHECKING`, `from simplon.domain import artifactsection` and, under `if TYPE_CHECKING:`, `from simplon.domain.manifest import Manifest`. Then:

```python
def check(manifest: "Manifest", declared: Mapping[str, tuple[str, bool]], kinds: Mapping[str, str]) -> None:
    """Load rules 1, 2, 3 and 5 (spec C.5, si#344 C.2) over the loaded manifest. All four are diagnosis."""
    producers: dict[str, list[str]] = {}
    consumers: list[tuple[str, str]] = []
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            where = f"{group} {name}"
            for port in spec.ports:
                if port.accepts not in kinds:
                    raise ValueError(
                        f"command '{where}': port '{port.name}' of task '{spec.task}' accepts '{port.accepts}', "
                        f"which is no kind the catalogue declares - it declares: {', '.join(kinds)}")
            for key, side in (("produces", spec.produces), ("consumes", spec.consumes)):
                for port_name, artifacts in side.items():
                    port = next(p for p in spec.ports if p.name == port_name)
                    for artifact in artifacts:
                        if artifact not in declared:
                            raise ValueError(
                                f"command '{where}' binds '{artifact}' to port '{port_name}', and `artifacts:` "
                                f"declares no '{artifact}' - declare it there with its `kind:`")
                        kind = declared[artifact][0]
                        if not artifactsection.accepts(kinds, port.accepts, kind):
                            raise ValueError(
                                f"command '{where}' binds '{artifact}', a `{kind}`, to port '{port_name}', which "
                                f"accepts `{port.accepts}` and the kinds that refine it")
                        if key == "produces":
                            producers.setdefault(artifact, []).append(where)
                        else:
                            consumers.append((where, artifact))
    for where, artifact in consumers:
        if artifact not in producers and not declared[artifact][1]:
            raise ValueError(
                f"command '{where}' consumes '{artifact}', and no command produces it - produce it with a "
                f"command, or give it a `registry:` it is fetched from")
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            if spec.depends_on:
                _check_plan(manifest, f"{group} {name}", manifest.plan_for(name, group=group))


def _check_plan(manifest: "Manifest", aggregate: str, plan: tuple[str, ...]) -> None:
    """Rule 1 per plan (decided 2026-10-14) and rule 5: one producer of an artifact in a plan, planned
    before every consumer of it there."""
    made: dict[str, tuple[int, str]] = {}
    for at, step in enumerate(plan):
        spec = manifest.spec_by_name(step)
        for artifact in (a for names in (spec.produces if spec else {}).values() for a in names):
            if artifact in made:
                raise ValueError(
                    f"aggregate '{aggregate}' plans two producers of '{artifact}': '{made[artifact][1]}' and "
                    f"'{step}' - one plan builds an artifact once, so plan one of them")
            made[artifact] = (at, step)
    for at, step in enumerate(plan):
        spec = manifest.spec_by_name(step)
        for artifact in (a for names in (spec.consumes if spec else {}).values() for a in names):
            if artifact in made and made[artifact][0] > at:
                producer = made[artifact][1]
                raise ValueError(
                    f"aggregate '{aggregate}' plans '{step}' before '{producer}', and '{step}' consumes "
                    f"'{artifact}', which '{producer}' produces - list '{producer}' first in `depends_on`")
```

In `manifest.load`, replace the final `return Manifest(...)` with:

```python
    loaded = Manifest(groups=groups, env_groups=env_groups, commands=commands, tree=tree,
                      generate=generate, areas=areas)
    ports.check(loaded, artifactsection.declared(data),
                getattr(catalogue, "kinds", {}) or artifactsection.REFINES)
    return loaded
```

- [ ] **Step 4: Run them to verify they pass**

Run: `PY -m pytest src/tests/test_port_bindings.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: See each guard red**

Break one property at a time, run the test file, and restore after each:
- Change `if artifact in made:` to `if False:` → the rule 1 test fails.
- Replace the consumer loop's `raise` with `pass` → the rule 2 test fails.
- Make `_check_plan` raise on any second producer **across** plans as well, by moving `made` to module scope → `test_several_producers_of_one_artifact_load_when_no_plan_holds_two` fails. That proves the per-plan decision is pinned.
- Drop `or not declared[...]` from the rule 2 condition → `test_a_consumer_of_an_artifact_with_a_registry_needs_no_producer` fails.

- [ ] **Step 6: Census and the full suite. This step is the measurement over the eight manifests.**

Add to the ports block of `CENSUS`:

```python
    # C.5 rules 1, 2, 3 and 5 (si#344 C.2), all diagnosis, merged (spec C.7). Rule 1 is per plan (decided
    # 2026-10-14): firn's three producers of one image are a working product, and refusing them would have been
    # an expression rule nobody measured.
    ("ports", "check", "no kind the catalogue declares"): DIAGNOSIS,
    ("ports", "check", "declare it there with its"): DIAGNOSIS,
    ("ports", "check", "and the kinds that refine it"): DIAGNOSIS,
    ("ports", "check", "and no command produces it"): DIAGNOSIS,
    ("ports", "_check_plan", "plans two producers of"): DIAGNOSIS,
    ("ports", "_check_plan", "first in `depends_on`"): DIAGNOSIS,
```

Each fragment lies inside one literal part of its f-string; `test_every_census_key_names_exactly_one_refusal` confirms it.

Update the numbers in `rules.md`. Run the full suite into a file. **Read every failure:**
- A unit-test stub that binds an artifact with `with: { name: ... }` on a port task but declares no `artifacts:` entry is now refused by rule 3. That is the intended new diagnosis. Fix the stub by declaring the artifact, and ledger it as `Ruling: <test> stub declares its artifact - rule 3 refuses an undeclared one at load since C.2`. Expected candidates, measured by grep: `test_tasks_image.py`, `test_own_image.py`, `test_tasks_nuget_config.py`, `test_cut.py`, `test_coordinate_placement.py`, `test_catalogue.py`.
- A real manifest in `test_migrate.py`, `test_manifestmodel.py` or `test_manifestmodel_e2e.py` (the eight fixtures) that is refused is a **finding**. Stop, ledger it with the message, and report it. Do not edit a fixture.

Then run mypy.

- [ ] **Step 7: Commit**

```bash
git add src/simplon/domain/ports.py src/simplon/domain/artifactsection.py src/simplon/domain/manifest.py \
  src/tests/ src/site/content/with-what/rules.md
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): the load rules hold every binding to the artifacts and the plans

C.2 Task 3: spec C.5 rules 1 (one producer per artifact per plan, decided 2026-10-14), 2, 3
and 5, all diagnosis. The eight reachable manifests, migrated, load under them (test_migrate).

Seen red: <which break>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 4: `simplon manifest migrate` rewrites `with: name` into the port binding

**Files:**
- Modify: `src/simplon/tasks/migrate.py`:
  - the module docstring ("THREE PASSES" becomes "FOUR PASSES", with a paragraph on `_bind`);
  - `_bind` and its helpers, after `_fold`;
  - `migrate_text`'s pass tuple.
- Modify: `simplon.yaml` (by running the command)
- Test: `src/tests/test_migrate.py`

**Interfaces:**
- Consumes: `artifactschema.PORTS`. It must not import `simplon.domain.manifest`, which `test_importing_the_migration_does_not_import_the_manifest_loader` holds.
- Produces: `_bind(text: str) -> Migration`, run after `_fold` in `migrate_text`.

- [ ] **Step 1: Write the failing tests** (append to `test_migrate.py`)

```python
def _commands(body: str) -> str:
    return ("product: p\nci:\n  build:\n    commands:\n" + body
            + "artifacts:\n  k: { kind: image, registry: r, repository: k, dockerfile: D, context: . }\n")


def test_a_block_with_holding_only_name_becomes_the_binding_and_keeps_its_comments():
    # arrange
    text = _commands('      image:\n        task: "build:image"\n        with:   # pinned\n'
                     "          name: k   # the kernel\n")

    # act
    result = migrate_text(text)

    # assert
    assert result.status == "migrated", result.reason
    assert ('        produces:   # pinned\n          image: k   # the kernel\n') in result.text
    assert "with:" not in result.text


def test_a_block_with_holding_more_keeps_the_rest_under_with():
    # arrange
    text = _commands('      image:\n        task: "build:image"\n        with:\n          name: k\n'
                     "          platform: linux/amd64\n")

    # act
    result = migrate_text(text)

    # assert
    assert ("        produces:\n          image: k\n        with:\n          platform: linux/amd64\n"
            in result.text)


@pytest.mark.parametrize("written,expected", [
    ("with: { name: k }", "produces: { image: k }"),
    ("with: { name: k, platform: linux/arm64 }   # arm",
     "produces: { image: k }\n        with: { platform: linux/arm64 }   # arm"),
])
def test_a_flow_with_becomes_the_binding(written, expected):
    # arrange
    text = _commands(f'      image:\n        task: "build:image"\n        {written}\n')

    # act
    result = migrate_text(text)

    # assert
    assert f"        {expected}\n" in result.text


def test_an_input_port_becomes_consumes():
    # arrange
    text = _commands('      image:\n        task: "release:image"\n        with: { name: k }\n')

    # act / assert
    assert "        consumes: { image: k }\n" in migrate_text(text).text


@pytest.mark.parametrize("command", [
    '      image:\n        task: "build:image"\n        with: &pinned\n          name: k\n',
    '      image: { task: "build:image", with: { name: k } }\n',
    '      gate:\n        task: "test:gate"\n        with: { name: unit }\n',
])
def test_what_the_pass_cannot_rewrite_safely_or_need_not_is_left_as_written(command):
    # arrange: an anchor others may merge, a one-line command, and a task whose `name` is no port
    text = _commands(command)

    # act
    result = migrate_text(text)

    # assert: the loader reads the first two as the same binding (decided 2026-10-14)
    assert (result.status, result.text) == ("current", text)


def test_the_binding_pass_runs_twice_as_current():
    # arrange
    once = migrate_text(_commands('      image:\n        task: "build:image"\n        with: { name: k }\n'))

    # act / assert
    assert migrate_text(once.text).status == "current"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_migrate.py -q -p no:cacheprovider -k "binding or block_with or flow_with or input_port or left_as_written"`
Expected: the rewrite tests FAIL with status "current". The "left as written" cases PASS. They are guards, seen red in Step 5.

- [ ] **Step 3: Implement `_bind`**

Add `from simplon.domain.artifactschema import PORTS` to the imports. After `_fold`:

```python
#: Each catalogue coordinate whose port binds `name` -> (that port, the command key that binds it).
_BINDS_NAME = {coordinate: (p.name, "produces" if p.direction == "output" else "consumes")
               for coordinate, ports in PORTS.items() for p in ports if p.param == "name"}
_TASK_LINE = re.compile(r"""^(?P<indent> *)task:\s*(?P<q>["']?)(?P<coordinate>[^"'\s#]+)(?P=q)\s*(?:#.*)?$""")
_WITH_FLOW = re.compile(r"^(?P<indent> *)with:\s*\{(?P<body>[^{}&*<]*)\}(?P<comment>\s+#.*)?$")
_WITH_BLOCK = re.compile(r"^(?P<indent> *)with:(?P<comment>\s+#.*)?$")
_NAME_LINE = re.compile(r"^(?P<indent> *)name:\s*(?P<value>[^\s#&*|>][^#]*?)(?P<comment>\s+#.*)?$")


def _bound(node: object) -> object:
    """The document as the loader reads it since si#344 C.2: on a coordinate in `_BINDS_NAME`, a string
    `with: name` IS that port's binding. The oracle `_bind`'s splice is held to."""
    if isinstance(node, list):
        return [_bound(value) for value in node]
    if not isinstance(node, dict):
        return node
    out = {key: _bound(value) for key, value in node.items()}
    task, pinned = out.get("task"), out.get("with")
    if isinstance(task, str) and task in _BINDS_NAME and isinstance(pinned, dict) \
            and isinstance(pinned.get("name"), str):
        port, key = _BINDS_NAME[task]
        out[key] = {port: pinned["name"], **(out.get(key) or {})}
        rest = {k: v for k, v in pinned.items() if k != "name"}
        if rest:
            out["with"] = rest
        else:
            out.pop("with")
    return out


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _span(lines: list[str], at: int, width: int) -> tuple[int, int]:
    """[first, last) of the mapping the key on line `at`, `width` spaces in, stands in."""
    def inside(line: str) -> bool:
        return not line.strip() or line.lstrip().startswith("#") or _indent(line) >= width
    first, last = at, at + 1
    while first > 0 and inside(lines[first - 1]):
        first -= 1
    while last < len(lines) and inside(lines[last]):
        last += 1
    return first, last


def _flow(match: re.Match, port: str, key: str) -> list[str] | None:
    indent, body, comment = match["indent"], match["body"], match["comment"] or ""
    items = [item.strip() for item in body.split(",") if item.strip()]
    named = [item for item in items if re.match(r"name\s*:", item)]
    if len(named) != 1:
        return None
    rest = [item for item in items if item not in named]
    value = named[0].split(":", 1)[1].strip()
    # the split is trusted only if it parses back to what the line said (a comma inside a value would not)
    if yaml.safe_load("{" + ", ".join(rest) + "}") != {k: v for k, v in yaml.safe_load("{" + body + "}").items()
                                                       if k != "name"}:
        return None
    if not rest:
        return [f"{indent}{key}: {{ {port}: {value} }}{comment}"]
    return [f"{indent}{key}: {{ {port}: {value} }}", f"{indent}with: {{ {', '.join(rest)} }}{comment}"]


def _block(lines: list[str], at: int, match: re.Match, port: str, key: str) -> tuple[int, list[str]] | None:
    """The `with:` block on line `at`, rewritten: (the line after it, its new lines), or None."""
    width = len(match["indent"])
    end = at + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > width):
        end += 1
    body = lines[at + 1:end]
    keys = [line for line in body if line.strip() and not line.lstrip().startswith("#")]
    if not keys:
        return None
    child = _indent(keys[0])
    names = [n for n, line in enumerate(body) if _indent(line) == child and _NAME_LINE.match(line)]
    own = [line for line in keys if _indent(line) == child]
    if len(names) != 1 or any(line.lstrip().startswith("<<") for line in own):
        return None
    found = _NAME_LINE.match(body[names[0]])
    assert found is not None
    binding = f"{' ' * child}{port}: {found['value']}{found['comment'] or ''}"
    if len(own) == 1:
        return end, [f"{match['indent']}{key}:{match['comment'] or ''}",
                     *(binding if n == names[0] else line for n, line in enumerate(body))]
    return end, [f"{match['indent']}{key}:", binding, lines[at],
                 *(line for n, line in enumerate(body) if n != names[0])]


def _bind(text: str) -> Migration:
    """Pass 3 (si#344 C.2): `with: { name: X }` on a coordinate whose port binds `name` becomes that port's
    binding - `produces: { image: X }` on `build:image`, `consumes: { image: X }` on `release:image`. Only a
    `task:` on its own line whose sibling `with:` carries no anchor, alias or merge key is rewritten; the
    rest stays as written, which the loader reads as the same binding (decided 2026-10-14), so leaving it
    is never wrong - only older."""
    old, reason = _parse(text)
    if reason:
        return Migration("refused", text, (), reason)
    if not isinstance(old, dict):
        return Migration("current", text)
    lines = text.splitlines()
    edits: list[tuple[int, int, list[str], str]] = []
    for number, line in enumerate(lines):
        task = _TASK_LINE.match(line)
        if not task or task["coordinate"] not in _BINDS_NAME:
            continue
        port, key = _BINDS_NAME[task["coordinate"]]
        width = len(task["indent"])
        first, last = _span(lines, number, width)
        for at in range(first, last):
            if _indent(lines[at]) != width:
                continue
            flow, block = _WITH_FLOW.match(lines[at]), _WITH_BLOCK.match(lines[at])
            new = _flow(flow, port, key) if flow else None
            end = at + 1
            if block:
                rewritten = _block(lines, at, block, port, key)
                if rewritten:
                    end, new = rewritten
            if new:
                edits.append((at, end, new, f"line {at + 1}: {task['coordinate']} binds its `{port}` port with "
                                            f"`{key}:` instead of `with: name`"))
    if not edits:
        return Migration("current", text)
    out = list(lines)
    removed: list[str] = []
    added: list[str] = []
    for start, end, new, _ in sorted(edits, reverse=True):
        removed += out[start:end]
        added += new
        out[start:end] = new
    new_text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    parsed, reason = _parse(new_text)
    if reason:
        return Migration("refused", text, (), f"the bound text does not parse back: {reason}")
    if _bound(parsed) != _bound(old):
        return Migration("refused", text, (), "the bound text does not read back as the same bindings: "
                         + _first_difference(_bound(old), _bound(parsed)))
    lost, extra = _accounting(lines, out, removed, added)
    if lost or extra:
        return Migration("refused", text, (), f"binding changed a line it should not have: {lost or extra}")
    return Migration("migrated", new_text, tuple(move for *_, move in sorted(edits)))
```

In `migrate_text`, change the pass tuple to `(_dedupe, lambda t: _shape(t, unknown_groups_into=unknown_groups_into), _fold, _bind)`, and change "THREE PASSES" in the module docstring to "FOUR PASSES". Add one sentence: "`_bind` is si#344 C.2: `with: { name: X }` on a port task becomes `produces:`/`consumes:`; what it cannot rewrite safely stays, and the loader reads it as the same binding."

- [ ] **Step 4: Run them, and every migration test**

Run: `PY -m pytest src/tests/test_migrate.py src/tests/test_manifestmodel.py -q -p no:cacheprovider`
Expected: PASS, including:
- the eight real manifests migrate;
- each is current on a second run;
- the CLI-surface goldens are identical. A binding changes no command line, and that test is the proof.

If a golden differs, that is a finding: stop.

- [ ] **Step 5: See it red**

Each break below must turn a test red; restore after each.
- In `_flow`, return the binding without `with:` for the rest. Expected: `_bound` differs, the result is "refused", and `test_a_flow_with_becomes_the_binding[...arm64]` fails.
- Drop the `<<` guard in `_block`. Expected: the anchored case is no longer "current", or the result is refused.

- [ ] **Step 6: Migrate simplon's own manifest by its own command**

Run: `./simplon.sh support manifest migrate`
Expected: rc 0, "migrated to the current form (2 change(s))", and two moves, `build:image` and `release:image`. Read `git diff simplon.yaml`. The output must show `produces:` / `image: kernel` under `ci build image` and `consumes:` / `image: kernel` under `ci release image`, with nothing else changed.

Then: `git add simplon.yaml && ./simplon.sh test generated`
Expected: green. A binding changes neither the CLI reference nor the completion. The product model is rebuilt in Task 5; if `test generated` reports `src/firn/model/product/simplon/simplon.firn` stale here, ledger it and regenerate it in Task 5.

- [ ] **Step 7: Full suite, mypy, commit**

```bash
git add src/simplon/tasks/migrate.py src/tests/test_migrate.py simplon.yaml
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): manifest migrate rewrites with: name into the port binding; simplon migrated

C.2 Task 4. A fourth pass, `_bind`, held to an oracle that reads both texts the way the
loader does. An anchored, merged or one-line `with:` stays as written; the loader reads it
as the same binding (decided 2026-10-14). simplon.yaml migrated by its own command.

Seen red: <which break>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 5: The manifest model references the catalogue's tasks and carries the bindings

**Files:**
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn`:
  - the header comment, lines 3-7;
  - `TaskCommand.produces`, lines 147-151.
- Modify: `src/simplon/domain/manifestmodel.py` (`_Export.command`, `_Export.task_lines`, the module docstring)
- Regenerate: `src/firn/model/product/simplon/simplon.firn`
- Test: `src/tests/test_manifestmodel.py`

**Interfaces:**
- Consumes: `CommandSpec.task/produces/consumes/ports` (Task 1); `artifactschema.PORTS`. The catalogue instance names are `mangle(coordinate)` in package `simplon.catalogue`, measured: `build_image`, `build_nuget_config`, `toolchain_run`, ...
- Produces:
  - A `TaskCommand` on a coordinate in `PORTS` writes `task = simplon.catalogue.<mangle(coordinate)>` and declares no `t_` task.
  - Every binding is written as `produces = <root>.a_<mangle(artifact)>` or `consumes = <root>.a_<mangle(artifact)>`.
  - A product `t_` task carries its ports as `input <port> typeOf simplon.pipeline.Port { accepts = simplon.vocabulary.<kind> ... }`.

- [ ] **Step 1: Write the failing tests** (append to `test_manifestmodel.py`)

```python
BOUND = DEMO.replace('image: { task: "build:image" }',
                     'image: { task: "build:image", produces: { image: kernel } }')


def test_a_command_on_a_modelled_catalogue_task_references_it_and_declares_no_task_of_its_own():
    # act
    out = _export(BOUND)

    # assert: si#344 C.2 - the catalogue task is the one source of its ports
    command = _block(out, "command image typeOf simplon.pipeline.TaskCommand {")
    assert "task = simplon.catalogue.build_image" in command
    assert "t_simplon_tasks_image_build" not in out


def test_a_binding_is_exported_as_a_reference_to_the_artifact():
    # act
    out = _export(BOUND)

    # assert
    assert "produces = product.demo.demo.a_kernel" in _block(
        out, "command image typeOf simplon.pipeline.TaskCommand {")


def test_a_product_tasks_ports_are_exported_on_its_task():
    # arrange
    text = BOUND.replace("cd:\n", 'tasks:\n  pack:\n    impl: "orchestrator.cli:pack"\n    help: "Pack."\n'
                         "    output:\n      bundle: { accepts: directory, param: name }\n"
                         "cd:\n").replace("      all:", "      pack: { task: pack }\n      all:")

    # act
    out = _export(text)

    # assert
    task = _block(out, "tasks t_orchestrator_cli_pack typeOf simplon.pipeline.Task {")
    assert "output bundle typeOf simplon.pipeline.Port {" in task
    assert "accepts = simplon.vocabulary.directory" in task and 'param = "name"' in task
```

In `test_the_export_drops_nothing`, change `impls` to the impls of commands whose task is **not** in `PORTS`, and add the two binding counts:

```python
    from simplon.domain.artifactschema import PORTS
    specs = [mf.spec_for(group, command) for group, members in mf.groups.items() for command in members]
    impls = {s.impl for s in specs if not s.depends_on and s.task not in PORTS}
    ...
    assert _count(out, r"tasks \w+") == len(impls)
    assert len(re.findall(r"^\s+produces = ", out, re.MULTILINE)) == sum(
        len(names) for s in specs for names in s.produces.values())
    assert len(re.findall(r"^\s+consumes = ", out, re.MULTILINE)) == sum(
        len(names) for s in specs for names in s.consumes.values())
```

Drop the `assert impls and` guard only if a fixture has no non-catalogue task. Measure that, do not guess, and ledger the result.

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_manifestmodel.py -q -p no:cacheprovider`
Expected: the three new tests FAIL, and `test_the_export_drops_nothing` FAILS for every fixture that has a port task (simplon, firn, agile-cockpit at least).

- [ ] **Step 3: The metamodel: `produces` becomes an Association**

In `pipeline.firn`:
- Lines 3-5: replace "OWNS what it produces and REFERENCES what it consumes, so every artifact has exactly one producer by construction" with "REFERENCES what it produces and what it consumes: the Product owns every artifact, and several commands may produce one, but no plan holds two of them (si#344 C.2, decided 2026-10-14)".
- `TaskCommand.produces`: `typeOf firn.core.Association`, `objectCardinality = 0..N`.

- [ ] **Step 4: The export**

In `manifestmodel.py`, add `from simplon.domain.artifactschema import PORTS`. In `_Export.__init__`, change `self.tasks` to `dict[str, tuple[str, tuple]]` (impl → (firn name, ports)). In `command`, change the leaf branch to:

```python
        else:
            if spec.task in PORTS:
                # a catalogue task the model carries (si#344 C.1): referenced, never re-declared (C.2)
                body.append(f"task = simplon.catalogue.{mangle(spec.task)}")
            else:
                if spec.impl not in self.tasks:
                    self.tasks[spec.impl] = (self.names(spec.impl, "t_"), spec.ports)
                body.append(f"task = {self.root}.{self.tasks[spec.impl][0]}")
            for key, side in (("produces", spec.produces), ("consumes", spec.consumes)):
                body += [f"{key} = {self.root}.a_{mangle(artifact)}" for names in side.values() for artifact in names]
            kind = "TaskCommand"
```

`task_lines` becomes:

```python
    def task_lines(self) -> list[str]:
        lines: list[str] = []
        for impl, (name, ports) in self.tasks.items():
            body = [f"key = {_q(impl)}", f"body = {_q(impl)}"]
            for port in ports:
                fields = [f"accepts = simplon.vocabulary.{mangle(port.accepts)}"]
                if port.param:
                    fields.append(f"param = {_q(port.param)}")
                body += _block(f"{port.direction} {mangle(port.name)} typeOf simplon.pipeline.Port", fields)
            lines += _block(f"tasks {name} typeOf simplon.pipeline.Task", body)
        return lines
```

In the module docstring's "What is NOT exported" list, add: "a command on a catalogue task the model carries (`artifactschema.PORTS`) declares no `t_` task: it references `simplon.catalogue.<task>` (si#344 C.2)".

- [ ] **Step 5: Run the tests, regenerate, and run the gates**

Run: `PY -m pytest src/tests/test_manifestmodel.py -q -p no:cacheprovider`
Expected: PASS.

Run: `./simplon.sh support manifest model src/firn/model/product/simplon/simplon.firn`, then `git diff --stat src/firn/model/product/` and read it. Expected:
- the `t_simplon_tasks_image_build` and `t_simplon_tasks_image_release` tasks are gone;
- `task = simplon.catalogue.build_image` / `simplon.catalogue.release_image`;
- `produces`/`consumes = product.simplon.simplon.a_kernel`;
- the same for `docs:site` and `toolchain:run` (catalogue references, no binding).

Then: `git add -A src/firn && ./simplon.sh test model && ./simplon.sh test generated`
Expected: both green. firn rc 0 is the only green. A red `test model` is firn refusing the reference or the cardinality: read its error and ledger it. If it is a firn parser limit, that is a finding for firn, not a local patch.

Run: `PY -m pytest src/tests/test_manifestmodel_e2e.py -q -p no:cacheprovider` (needs docker).
Expected: all eight PASS.

- [ ] **Step 6: See it red**

Revert `produces` to `firn.core.Composition` with `objectCardinality = 0..1` in `pipeline.firn`, run `./simplon.sh test model`, and expect red. A Product composition and a command composition on one artifact give two owners. Ledger firn's exact error; this is the measurement behind decision 2 in the model. If it stays green, ledger that as a finding: firn v0.1.0 does not enforce Composition's object cardinality across two properties. Restore.

- [ ] **Step 7: Full suite, mypy, commit**

```bash
git add src/firn src/simplon/domain/manifestmodel.py src/tests/test_manifestmodel.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): the manifest model references the catalogue's tasks and carries the bindings

C.2 Task 5. A command on a modelled catalogue task points at simplon.catalogue.<task> instead
of re-declaring a product Task; bindings are references to the Product's artifacts, so
TaskCommand.produces is an Association (several producers, one per plan - decided 2026-10-14).

Seen red: <what firn said with produces as a 0..1 Composition>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 6: The pages say how to bind, and the PR

**Files:**
- Modify: `src/firn/templates/docs.firnt` (lines 33-34), then regenerate `src/site/content/with-what/kinds.md`
- Modify: `src/site/content/how/manifest.md` (a new section after "## Pinning values with `with:`", before "## Refining a platform command")
- Modify: `src/tests/test_catalogue_ports.py` (`test_the_kinds_page_does_not_offer_ports_a_manifest_cannot_bind_yet`)

- [ ] **Step 1: Turn the page test around (it fails first)**

Rename the test to `test_the_kinds_page_says_how_a_command_binds_a_port` and replace its assert:

```python
    # assert: since si#344 C.2 a command binds a port; the page says how, and no longer that it cannot
    assert "A manifest cannot bind a port yet" not in ports
    assert "`produces: { <port>: <artifact> }`" in ports
    assert "`consumes: { <port>: <artifact> }`" in ports
```

Run: `PY -m pytest src/tests/test_catalogue_ports.py -q -p no:cacheprovider`
Expected: FAIL. The page still says it cannot.

- [ ] **Step 2: The template**

In `docs.firnt`, replace the two lines starting `|A manifest cannot bind a port yet` with:

```
    |A command binds a port with `produces: { <port>: <artifact> }` on an output and
    |`consumes: { <port>: <artifact> }` on an input. The artifact is an `artifacts:` entry whose kind the port accepts.
    |A port that binds a parameter hands the artifact's name to it; `with: { name: ... }` on that parameter is read as
    |the same binding, and `simplon manifest migrate` rewrites it into the port's.
```

Run: `./simplon.sh build model`, then `git status --short src/simplon src/site` and read the `kinds.md` diff. Only the paragraph should change; `artifactschema.py` and `catalogue.yaml` must be unchanged. Then: `git add -A src/firn src/site && ./simplon.sh test generated && ./simplon.sh test model`
Expected: green. Rerun the page test: PASS.

- [ ] **Step 3: The manifest page**

In `src/site/content/how/manifest.md`, insert before `## Refining a platform command, and replacing one`:

````markdown
## Binding artifacts: `produces:` and `consumes:`

A task that takes or gives an artifact has **ports**, listed with the kind each accepts on
[the kinds page](../../with-what/kinds/). A command binds each port to an `artifacts:` entry:

```yaml
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: kernel } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: kernel } }
artifacts:
  kernel: { kind: image, registry: ghcr.io/me, repository: kernel, dockerfile: Dockerfile, context: . }
```

A port with a parameter hands the artifact's name to it. This replaces `with: { name: kernel }`, which
still loads and is read as the same binding. `simplon manifest migrate` rewrites it, and writing both is
refused, because the two say one thing twice. A task of your own declares its ports beside its `impl:`:

```yaml
tasks:
  pack:
    impl: "orchestrator.cli:pack"
    input:  { site: { accepts: site } }
    output: { bundle: { accepts: directory, param: name } }
```

The loader holds every binding before anything runs:

- the port exists on the task, on the side the key binds;
- the artifact is declared, and its kind is the port's or refines it;
- something produces what a command consumes, or the artifact names a `registry:` it is fetched from;
- no aggregate plans two producers of one artifact, or a consumer before its producer.

Several commands may produce one artifact (an everyday single-platform build beside the release's
all-platform one); a plan picks one.
````

Run the docs-site tests: `PY -m pytest src/tests -q -p no:cacheprovider -k "site or docs or page or chapter"`. The 3 pre-existing root-bound `test_tasks_docs` failures stay as they were; note them, do not chase them.

- [ ] **Step 4: Full suite, mypy, gates, commit**

```bash
git add src/firn/templates/docs.firnt src/site src/tests/test_catalogue_ports.py
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
docs(si#344): the pages say how a command binds a port

C.2 Task 6. The kinds page (generated) and how/manifest.md: produces:/consumes:, a product
task's own ports, and the four load-time checks.

Seen red: the kinds page test, before the template changed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

- [ ] **Step 5: Push and open the PR**

Write the body to `/tmp/claude-0/-root-git-simplon/36693d3e-3ebc-423e-8e38-fca86fd4d6be/scratchpad/si344-c2-pr.md`, in English. It contains:
- the two decisions of 2026-10-14 with the issue link;
- the new refusals with their kinds: 16 diagnosis and 1 expression rule (rule 7, merged reach), or the numbers the census really computed;
- what the migration rewrites and what it leaves (with the firn anchors as the measured case);
- what was seen red;
- the suite, mypy and gate results;
- "Part of #344 (C.2 of four plans)".

It ends with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
```

```bash
git push -u origin si344-c2-bindings
gh pr create --base main --milestone "M3 - ci / cd / support" \
  --title "feat(si#344): C.2 - commands bind ports with produces:/consumes:, and the load rules hold them" \
  --body-file /tmp/claude-0/-root-git-simplon/36693d3e-3ebc-423e-8e38-fca86fd4d6be/scratchpad/si344-c2-pr.md
```

Do not merge; Marco merges. After the PR is open, tell firn (the peer session, `firn (cai-3) [ae9506]`) in English:
- what `produces:`/`consumes:` are;
- that its `with: name` keeps loading;
- that `manifest migrate` rewrites four of its ten commands and leaves the six anchored `test:image` commands as they are.

---

## Review Focus

1. **A command's own `params:` for a parameter a binding fills.** Expected: it is refused like a `with:` pin is, and not dropped silently. Pinned by `test_a_binding_on_a_parameter_the_command_presents_with_params_is_refused` (Task 1). The message still says "with `with:`" for a `produces:` binding. Check that wording against what a person reads.
2. **An unmigrated manifest whose `with: { name: X }` names an artifact `artifacts:` lacks.** It was a run-time refusal; it is now a load-time refusal (rule 3). That is intended, and it reaches every product that loads, so the eight-manifest run in Task 3 Step 6 is the check. Pinned by `test_an_artifact_no_entry_declares_is_refused`.
3. **`with: name` that is not a string** (`name: 25`). Expected: it loads exactly as before, is not read as a binding, and the run-time reader rules on it. Pinned by `test_with_name_that_is_not_a_string_is_left_as_it_was` (Task 1).
4. **The migration and YAML anchors or merge keys** (firn's six `test:image`). Expected: they stay byte for byte, and the loader reads them as the same binding. Pinned by `test_what_the_pass_cannot_rewrite_safely_or_need_not_is_left_as_written` (Task 4). The firn fixture in `test_a_migrated_real_manifest_is_current_on_the_second_run` is the real case.
5. **Rule 1 per plan versus across plans.** Expected: several producers load, and two in one plan are refused. Pinned in both directions by Task 3, and Step 5 breaks it on purpose. Which producer an edge across jobs means is C.4's, and is not decided here.
