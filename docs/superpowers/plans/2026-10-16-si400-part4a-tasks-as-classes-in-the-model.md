# si#400 part 4a: tasks as classes in the model - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every task, the catalogue's 54 and each product's, is a firn **class** whose metaclass carries
its coordinate and body, with its ports as typed properties. A command still is a `TaskCommand`, whose
`task` now names a class.

**Architecture:** This is spec step 1, plus the model half of decision 4. No Python task class is
generated yet (plan 4b), and the runtime is untouched (plan 4c). Commands become instances of their task
class in a later plan, because `TestResult.about` and `Release.published` are derived over
`TaskCommand.produces`/`consumes` today. Moving them is its own step (one source at a time).

**Tech Stack:** firn v0.1.0 (pinned image `ghcr.io/marcozwyssig/firn:v0.1.0`), `.firn` / `.firnt`,
Python 3 (`simplon.domain.manifestmodel`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-part-4-tasks-as-generated-classes-design.md` (and "Part 4,
decided now" in `docs/superpowers/specs/2026-10-13-architecture-as-a-firn-model-design.md`).

## Global Constraints

- firn image exactly `ghcr.io/marcozwyssig/firn:v0.1.0`; firn only through `./simplon.sh test model` /
  `./simplon.sh build model`, never a host firn.
- Python only through `deploy/orchestrator/.venv/bin/python`; 3 `test_tasks_docs` failures are
  root-bound and pre-existing.
- `./simplon.sh test typecheck-python` before every push.
- The generated files (`src/simplon/domain/artifactschema.py`, `src/site/content/with-what/kinds.md`,
  `src/simplon/catalogue.yaml` outside its protected region) are only ever changed by `build model`, and
  committed before `test generated` runs (it compares against the index).
- Commit messages through a quoted heredoc; identity via `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env.
- English in code, docs and PR; the subject names `si#400`.

## Measured before this plan (2026-10-16, firn v0.1.0, probes in the session scratchpad)

Each line is something a task below relies on.

- `TaskCommand.task` with `range = <metaclass>` accepts a **class** (`task = probe.BuildImage`), and a
  non-task class there is `E003 ... is not within the range 'probe.TaskType'`.
- A port declared as `property image typeOf probe.OutputPort { range = firn.core.StringLiteral
  subjectCardinality = 0..N accepts = ... param = "name" needs = ... }`, where `OutputPort extends Port
  extends firn.core.Attribute`, checks clean. The template reads it with ``t.property:`probe.OutputPort` ``,
  then `p.accepts.name`, `p.param`, `p.needs`.
- ``t.property:`probe.Port` `` also answers the `InputPort`/`OutputPort` subtypes.
  ``if not t.property:`probe.Port`.isEmpty()`` tells a task with ports from one without.
- ``for t : `probe.CatalogueTaskType` `` (a metaclass extending `TaskType`) answers only the catalogue's
  classes. ``for t : `probe.TaskType` `` answers both.
- `key` with `subjectCardinality = 1..1` on the metaclass: a task class without it is
  `E004 'probe.Wheel' has 0 'probe.TaskType.key' where 1..1 is required`. **Decision 4 is firn's own
  diagnosis.** It needs no kernel code, and it binds the catalogue too (no exemption).
- ``t.-task`` (reverse navigation) answers the commands that name the class.

## Review Focus

1. **A catalogue task with no ports must not enter `PORTS`.** `ports.py`, `manifest.py`, `migrate.py`
   and `manifestmodel.py` read `PORTS` as "the tasks that take or give an artifact". Pinned in Task 2,
   Step 1 (the literal `PORTS` test stays byte-identical).
2. **A product command on a portless catalogue task now references the catalogue class.** Before, it was
   re-declared as a product `t_...` task, so the export loses a duplicate. Pinned in Task 3, Step 1.
3. **Two product task names that map to one class name** (`nuget-config` and `nuget_config`) must stay a
   loud `ModelExportError`, not a silent merge. Pinned in Task 3, Step 1.
4. **The demo fixture and simplon's own exported model** must check clean. Otherwise
   `test_the_demo_checks_clean` and `test_simplons_own_firn_project_checks_clean` go red only where docker
   runs. Run both locally (Task 2 Step 6, Task 3 Step 6).
5. **`artifactschema.BODIES` covers all 54 coordinates**, so the "two sources for one body" test holds
   the whole catalogue, not 18. Pinned in Task 1.

---

### Task 1: `BODIES` must cover the whole catalogue (red first)

**Files:**
- Modify: `src/tests/test_catalogue_ports.py` (`test_every_modelled_task_is_a_catalogue_coordinate_with_the_body_the_catalogue_names`)

**Interfaces:**
- Consumes: `artifactschema.BODIES: dict[str, str]`, `artifactschema.PORTS`, `catalogue.load().tasks`
  (coordinate -> mapping with `"impl"`).
- Produces: the assertion that Task 2 turns green.

- [ ] **Step 1: Change the assertion**

Replace the line `assert set(artifactschema.BODIES) == set(artifactschema.PORTS)` with:

```python
    # assert: since si#400 4a EVERY catalogue task is a class in the model, not only those with ports;
    # the model and the hand-written catalogue stay two sources for one body until plan 4c
    assert set(artifactschema.BODIES) == set(tasks)
    assert set(artifactschema.PORTS) <= set(artifactschema.BODIES)
```

and rename the test to
`test_every_catalogue_task_is_modelled_with_the_body_the_catalogue_names`.

- [ ] **Step 2: Run it, see it red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_catalogue_ports.py -k every_catalogue_task`
Expected: FAIL. `BODIES` has 18 keys and `tasks` has 54.

- [ ] **Step 3: Do not commit alone.** The red test travels with Task 2 (one commit, so main stays green).

---

### Task 2: the metamodel and the catalogue as classes

**Files:**
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn` (`Task`, `CatalogueTask`, `Port`, `TaskCommand.task`)
- Modify: `src/firn/model/simplon/manifest/manifest.firn:151-155` (delete `Product.tasks`)
- Rewrite: `src/firn/model/simplon/catalogue/tasks.firn` (18 instances become 54 classes)
- Modify: `src/firn/templates/schema.firnt:61-90`, `src/firn/templates/docs.firnt:40-56`
- Modify: `src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn` (4 tasks)
- Regenerated by `build model`: `src/simplon/domain/artifactschema.py`, `src/site/content/with-what/kinds.md`
- Test: `src/tests/test_catalogue_ports.py`, `src/tests/test_firn_pipeline_e2e.py`

**Interfaces:**
- Produces (firn): `simplon.pipeline.TaskType` (metaclass: `key` 1..1, `body` 0..1),
  `simplon.pipeline.CatalogueTaskType extends TaskType`, abstract `simplon.pipeline.Task`,
  `simplon.pipeline.Port extends firn.core.Attribute` (`accepts` 1..1, `param` 0..1, `needs` 0..N),
  `InputPort`/`OutputPort extends Port`, `TaskCommand.task` with `range = simplon.pipeline.TaskType`.
  Catalogue classes are named by `class_name(coordinate)` (Task 3): `build:nuget-config` ->
  `simplon.catalogue.BuildNugetConfig`.
- Produces (Python, generated): `artifactschema.BODIES` with 54 keys; `PORTS` unchanged.

- [ ] **Step 1: Write the metamodel.** In `pipeline.firn`, replace `Task` and `CatalogueTask` with:

```firn
// si#400 4a: a task is a CLASS. Its coordinate and its body are values on the class, so they live one storey
// up, on its metaclass (firn docs/03 §8.4). A task class without `key` is firn's E004 - decision 4 of the
// part 4 spec, a diagnosis, and it holds the catalogue too.
TaskType typeOf firn.core.Class extends firn.core.Class {
  property key typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 1..1
  }
  property body typeOf firn.core.Attribute {
    range = firn.core.StringLiteral
    subjectCardinality = 0..1
  }
}

// The PLATFORM's tasks: their own metaclass, so a template over the catalogue does not gather the
// product tasks that `support manifest model` writes into the same firn project (si#344 C.1's reason).
CatalogueTaskType typeOf firn.core.Class extends simplon.pipeline.TaskType {}

Task typeOf firn.core.Class extends firn.core.NamedResource {
  modifier = firn.core.InheritanceModifier.Abstract
}
```

Replace `Port`'s head `Port typeOf firn.core.Class extends firn.core.NamedResource {` with
`Port typeOf firn.core.Class extends firn.core.Attribute {`. Keep its `accepts`/`param`/`needs` bodies,
and fix the doubled `subjectCardinality` on `needs` to the single `subjectCardinality = 0..N`. After
`Port`, add:

```firn
// A port is a PROPERTY of its task class (si#400 4a); its direction is its type, no longer the
// composition (`input`/`output`) it sat in. Its value is the bound entry's NAME, which is what a body
// receives today through `param`.
InputPort typeOf firn.core.Class extends simplon.pipeline.Port {}
OutputPort typeOf firn.core.Class extends simplon.pipeline.Port {}
```

In `TaskCommand`, change `task`'s `range = simplon.pipeline.Task` to `range = simplon.pipeline.TaskType`.
In `manifest.firn`, delete the `property tasks` block (lines 151-155): a class cannot be composed, so
product task classes stand at the root of the product's package (Task 3). Update the comment at the head
of `pipeline.firn` ("a Task is a filter type ...") to say "a Task is a class, its ports its properties".

- [ ] **Step 2: Rewrite `tasks.firn`.** Each instance
`<snake> typeOf simplon.pipeline.CatalogueTask { key, body, input/output <port> typeOf simplon.pipeline.Port { accepts, param?, needs* } }`
becomes, mechanically:

```firn
BuildImage typeOf simplon.pipeline.CatalogueTaskType extends simplon.pipeline.Task {
  key = "build:image"
  body = "simplon.tasks.image:build"
  property image typeOf simplon.pipeline.OutputPort {
    range = firn.core.StringLiteral
    subjectCardinality = 0..N
    accepts = simplon.vocabulary.image
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.image.f_repository
    needs = simplon.vocabulary.image.f_dockerfile
    needs = simplon.vocabulary.image.f_context
  }
  // si#343 (decided 2026-10-15): ... (keep every comment where it stood)
  property file typeOf simplon.pipeline.InputPort {
    range = firn.core.StringLiteral
    subjectCardinality = 0..N
    accepts = simplon.vocabulary.file
  }
}
```

Keep the order of the ports exactly (the `PORTS` literal is ordered inputs first; the template, Step 3,
emits inputs before outputs either way). Then append one class per catalogue coordinate that has no port,
with only `key` and `body`. List them with:

```bash
deploy/orchestrator/.venv/bin/python - <<'EOF'
from simplon.domain import artifactschema, catalogue
from simplon.domain.manifestmodel import class_name   # Task 3 adds it; until then inline the rule below
for c, t in catalogue.load().tasks.items():
    if c not in artifactschema.PORTS:
        print(f'{class_name(c)} typeOf simplon.pipeline.CatalogueTaskType extends simplon.pipeline.Task {{\n'
              f'  key = "{c}"\n  body = "{t["impl"]}"\n}}')
EOF
```

The rule `class_name` implements: split the coordinate on `:`, `-` and `_`, capitalise each part, join
them (`support:ci-disk-cleanup` -> `SupportCiDiskCleanup`), and put `T` in front of a leading digit.
Change the file's head comment: "`key` and `body` repeat catalogue.yaml's coordinate and impl until si#400
4c". Expected count: `grep -c 'typeOf simplon.pipeline.CatalogueTaskType' tasks.firn` = 54.

- [ ] **Step 3: Move the two templates.** In `schema.firnt` (both loops) and `docs.firnt`, replace

```
for t : `simplon.pipeline.CatalogueTask` {
  ...
  for p : t.input {
  ...
  for p : t.output {
```

with

```
for t : `simplon.pipeline.CatalogueTaskType` {
  ...
  for p : t.property:`simplon.pipeline.InputPort` {
  ...
  for p : t.property:`simplon.pipeline.OutputPort` {
```

In `schema.firnt`'s `PORTS` loop (and in `docs.firnt`'s table), wrap the per-task body in
``if not t.property:`simplon.pipeline.Port`.isEmpty() { ... }``, so a portless task stays out of `PORTS`.
The `BODIES` loop is **not** wrapped, so it answers all 54. Change the `BODIES` comment to "Each catalogue
task -> the body the model names. catalogue.yaml names it too until si#400 4c."

- [ ] **Step 4: Move the demo fixture.** In `src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn`,
each `X typeOf simplon.pipeline.Task {` becomes `X typeOf simplon.pipeline.TaskType extends
simplon.pipeline.Task {` with a `key = "<x>"` line (the fixture's own coordinate, for example `key =
"build:image"` for `BuildImage`). Their ports move the same way as in Step 2.

- [ ] **Step 5: Generate and run.**

```bash
./simplon.sh build model && git status --short
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_catalogue_ports.py
```

Expected: `artifactschema.py` shows a `BODIES` with 54 entries and an unchanged `PORTS`. `kinds.md`
is unchanged or shows only the moved table, and if its port table changed, the diff must be empty: read it.
All of `test_catalogue_ports.py` passes, including Task 1's test. `test model` is still red, because
`src/firn/model/product/simplon/simplon.firn` writes `typeOf simplon.pipeline.Task` instances. Task 3
repairs it, and Tasks 2 and 3 are committed together.

- [ ] **Step 6: The demo e2e.**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_firn_pipeline_e2e.py -k demo`
Expected: PASS (the selector relations still answer what the fixture says).

---

### Task 3: products' tasks as classes in the export

**Files:**
- Modify: `src/simplon/domain/manifestmodel.py` (`mangle` beside a new `class_name`; `command()` lines
  ~197-205; `task_lines()` ~216-229; the module docstring's "a Task for a command on a catalogue task"
  paragraph near line 43)
- Regenerated: `src/firn/model/product/simplon/simplon.firn` (by `./simplon.sh support manifest model`,
  the command that wrote it; confirm its name in `simplon.yaml` before running)
- Test: `src/tests/test_manifestmodel.py` (lines 95, 387-389, 443, 462-463, plus new tests)

**Interfaces:**
- Consumes: `artifactschema.BODIES` (54 coordinates, Task 2), `artifactschema.PORTS`.
- Produces: `manifestmodel.class_name(name: str) -> str`. The export writes a product task as
  `<ClassName> typeOf simplon.pipeline.TaskType extends simplon.pipeline.Task { key body ports }` at the
  ROOT of the product's file (outside the `Product` block), and a command as
  `task = simplon.catalogue.<ClassName>` for every catalogue coordinate, or `task = <package>.<ClassName>`.

- [ ] **Step 1: Write the failing tests** in `test_manifestmodel.py`:

```python
def test_a_command_on_a_portless_catalogue_task_references_the_catalogue_class():
    # arrange: vcs:push has no port, so before si#400 4a the export re-declared it as a product task
    text = DEMO.replace("      all:", "      push: { task: vcs:push }\n      all:")

    # act
    out = _export(text)

    # assert
    assert "task = simplon.catalogue.VcsPush" in _block(out, "command push typeOf simplon.pipeline.TaskCommand {")
    assert "VcsPush typeOf" not in out


def test_a_product_task_is_a_class_at_the_root_of_the_products_package():
    # arrange
    text = DEMO.replace("cd:\n", 'tasks:\n  wheel: { impl: "orchestrator.cli:build_wheel", help: "Build." }\n'
                        "cd:\n").replace("      all:", "      wheel: { task: wheel }\n      all:")

    # act
    out = _export(text)

    # assert
    task = _block(out, "Wheel typeOf simplon.pipeline.TaskType extends simplon.pipeline.Task {")
    assert 'key = "wheel"' in task and 'body = "orchestrator.cli:build_wheel"' in task
    assert "task = product.demo.Wheel" in _block(out, "command wheel typeOf simplon.pipeline.TaskCommand {")


@pytest.mark.parametrize("name, expected", [
    ("build:image", "BuildImage"), ("support:ci-disk-cleanup", "SupportCiDiskCleanup"),
    ("pack_a", "PackA"), ("7zip", "T7zip"),
])
def test_class_name_capitalises_each_part_of_a_coordinate(name, expected):
    assert manifestmodel.class_name(name) == expected


def test_two_product_tasks_that_map_to_one_class_name_are_refused():
    # arrange
    text = DEMO.replace("cd:\n", 'tasks:\n  pack-a: { impl: "m:a", help: "A." }\n'
                        '  pack_a: { impl: "m:b", help: "B." }\ncd:\n').replace(
        "      all:", "      a: { task: pack-a }\n      b: { task: pack_a }\n      all:")

    # act / assert
    with pytest.raises(manifestmodel.ModelExportError, match="PackA"):
        _export(text)
```

Before writing them, read the product package name off an existing assertion (`product.demo.demo` is
the Product instance, so the package is `product.demo`). If `_export` writes another package, use that.
Change the existing expectations: line 95's block head becomes the `Wheel typeOf ...` form above, and
`task = product.demo.demo.t_wheel` becomes `task = product.demo.Wheel`. Lines 443 and 462-463 move the
same way (`PackA`/`PackB` heads). Line 389's `s.task not in PORTS` becomes `s.task not in BODIES`
(import `BODIES` beside `PORTS`).

- [ ] **Step 2: Run them, see them red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_manifestmodel.py`
Expected: FAIL on `class_name` (AttributeError) and on the block heads.

- [ ] **Step 3: Implement.** In `manifestmodel.py`, beside `mangle`:

```python
_PARTS = re.compile(r"[:\-_]+")


def class_name(name: str) -> str:
    """A task's coordinate or a product task's name as a firn CLASS name (si#400 4a): every part between
    `:`, `-` and `_` capitalised and joined, `T` in front of a leading digit. PascalCase also keeps a
    class clear of firn's keywords, which are all lower case."""
    out = "".join(part[:1].upper() + part[1:] for part in _PARTS.split(name) if part)
    out = _NOT_NAME.sub("_", out)
    return f"T{out}" if out[:1].isdigit() else out
```

In `command()`, replace the `if spec.task in PORTS:` branch with:

```python
            if spec.task in BODIES:
                # a catalogue task: every one is a class in the model since si#400 4a, referenced, never
                # re-declared (C.2)
                body.append(f"task = simplon.catalogue.{class_name(spec.task)}")
            else:
                if spec.task not in self.tasks:
                    self.tasks[spec.task] = (self.task_class(spec.task), spec.impl, spec.ports)
                body.append(f"task = {self.package}.{self.tasks[spec.task][0]}")
```

`self.task_class(task)` returns `class_name(task)` and records it in a dict of class names already given.
A second task with the same class name raises `ModelExportError(f"tasks '{first}' and '{task}' are both
the class '{name}'")`. `self.package` is the product's package (the part of `self.root` before its last
`.`). Name it the way the class already does, if it has one.

`task_lines()` writes each task as:

```python
            body = [f"key = {_q(task)}", f"body = {_q(impl)}"]
            for port in ports:
                kind = "InputPort" if port.direction == "input" else "OutputPort"
                fields = ["range = firn.core.StringLiteral", "subjectCardinality = 0..N",
                          f"accepts = simplon.vocabulary.{mangle(port.accepts)}"]
                if port.param:
                    fields.append(f"param = {_q(port.param)}")
                body += _block(f"property {mangle(port.name)} typeOf simplon.pipeline.{kind}", fields)
            lines += _block(f"{name} typeOf simplon.pipeline.TaskType extends simplon.pipeline.Task", body)
```

The caller that places `task_lines()` inside the `Product` block now places it **after** that block
closes, at the file's root. Find it with `grep -n 'task_lines()' src/simplon/domain/manifestmodel.py`.
Import `BODIES` from `artifactschema` beside `PORTS`, and keep `PORTS` only where the module still means
"has ports". Update the docstring near line 43 to match.

- [ ] **Step 4: Run the tests**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_manifestmodel.py src/tests/test_firn_manifest_coverage.py`
Expected: PASS.

- [ ] **Step 5: Re-export simplon's own model.** Run the export that wrote
`src/firn/model/product/simplon/simplon.firn` (its header names the command), then:

```bash
grep -c 'typeOf simplon.pipeline.Task {' src/firn/model/product/simplon/simplon.firn   # expect 0
./simplon.sh test model; echo rc=$?                                                    # expect 0
```

- [ ] **Step 6: Gates, then commit Tasks 1-3 together**

```bash
./simplon.sh build model && git status --short       # only the files this plan names
git add -A src/firn src/simplon src/site src/tests
./simplon.sh test generated
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests -x -p no:cacheprovider 2>&1 | tail -5
./simplon.sh test typecheck-python
```

Expected: `test model` rc 0, `test generated` green after staging, the suite green apart from the 3
known `test_tasks_docs` failures, typecheck clean. Then commit:

```bash
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" \
GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#400): tasks are classes in the model - the catalogue's 54 and every product's

(body: what moved, the measurements this relies on, Co-Authored-By and Claude-Session lines)
EOF
```

---

### Task 4: see decision 4 red, and the census

**Files:**
- Test: `src/tests/test_firn_pipeline_e2e.py` (new test)
- Check: `src/tests/test_refusal_census.py`

**Interfaces:**
- Consumes: `firn_rc(root, *argv, cwd=None) -> tuple[int, str]` and the `demo` fixture (both in
  `test_firn_pipeline_e2e.py`).

- [ ] **Step 1: Write the test**

```python
@needs_docker
def test_a_task_class_without_a_coordinate_is_refused(demo):
    # arrange: decision 4 of the part 4 spec - every concrete task class writes its own key
    model = demo / "model" / "demo" / "demo.firn"
    model.write_text(model.read_text().replace('  key = "build:image"\n', "", 1))

    # act
    rc, out = firn_rc(demo, "check")

    # assert
    assert rc == 1
    assert "E004" in out and "simplon.pipeline.TaskType.key" in out
```

- [ ] **Step 2: Run it, then see it red the other way.** Run it, expect PASS. Then set the metaclass's
`key` to `subjectCardinality = 0..1` in `pipeline.firn`, run it again, and expect FAIL (rc 0). Restore
the cardinality.

- [ ] **Step 3: The census.** Run `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_refusal_census.py`.
The new refusal is firn's, not the kernel's, so no census entry should be due. If the suite is red,
classify the entry it asks for as a **diagnosis** (CLAUDE.md, kind 1), with a comment naming si#400
decision 4.

- [ ] **Step 4: Commit**, the same identity and heredoc form, subject
`test(si#400): a task class without a coordinate is firn's E004, seen red`.

---

### Task 5: the PR

- [ ] Push the branch `si400-part4a-tasks-as-classes` and open the PR with `--body-file`. Do not write
  "Closes #400": the ticket stays open for 4b (generated Python classes, protected regions, the W300/W301
  guard) and 4c (the runtime, `CommandSpec` and the `impl:` lookup).
- [ ] The PR body names the bill. Re-running `support manifest model` writes each product's tasks
  differently now, so every product whose peer session exports its model sees a new shape. As of
  2026-10-15 no product imports `simplon.pipeline`, so nothing outside simplon breaks.

## What the next plans hold (not this one)

- **4b:** the `Tasks` template over ``CatalogueTaskType`.inBuild()``, one file per class
  (`src/simplon/tasks/<snake>.py`, 54 names measured collision-free against the existing modules), a
  `run = staticmethod(<body>)` wrapper in each protected region (measured: `signatures.bindable` sees the
  same parameters through `cls().run`), the W300/W301 guard reading `gen --format=json`, and the generated
  import of an out-of-build base class.
- **4c:** `resolve_ref` answers a `Task` subclass with `cls().run`, `taskgen._call` renders
  `Cls().run(...)`, and catalogue.yaml's `impl:` lines name the classes until they are generated.
- **Later:** commands as instances (moves `TestResult.about` and `Release.published` onto ports), kinds
  as classes, the library jar in the wheel, the products.
