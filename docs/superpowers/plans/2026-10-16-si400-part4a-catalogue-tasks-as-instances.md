# si#400 part 4a: every catalogue task is an instance in the model - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** All 54 catalogue tasks, not only the 18 with ports, are `CatalogueTask` instances in
`simplon.catalogue`. Every product command on a catalogue coordinate references that instance, and a task
without a `key` is firn's own E004.

**Architecture:** This is step 1 of "What goes, and in what order" in the part 4 spec, in the instance form
Marco fixed on 2026-10-16 (PR #462 closed, PR #464/#465 merged). It also builds the model half of
decision 4. No Python task class is generated yet (plan 4b), and the runtime is untouched (plan 4c). The
Python `Command` hierarchy (`TaskCommand`, `AggregateCommand`, `Deploy`, `ReleaseCommand`, mirroring
`pipeline.firn` 1:1) belongs to 4b/4c and is **not** in this plan.

**Tech Stack:** firn v0.1.0 (pinned image `ghcr.io/marcozwyssig/firn:v0.1.0`), `.firn` / `.firnt`,
Python 3 (`simplon.domain.manifestmodel`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-part-4-tasks-as-generated-classes-design.md` (revised
2026-10-16), with "Part 4, decided now" in `docs/superpowers/specs/2026-10-13-architecture-as-a-firn-model-design.md`.

## Global Constraints

- firn image exactly `ghcr.io/marcozwyssig/firn:v0.1.0`, run only through `./simplon.sh test model` /
  `./simplon.sh build model` (and the suite's `firnrun.firn_rc`), never a host firn.
- Python only through `deploy/orchestrator/.venv/bin/python`. The 3 `test_tasks_docs` failures are
  root-bound and pre-existing.
- `./simplon.sh test typecheck-python` before every push.
- Generated files (`src/simplon/domain/artifactschema.py`, `src/site/content/with-what/kinds.md`,
  `src/simplon/catalogue.yaml` outside its protected region, `src/firn/model/product/simplon/simplon.firn`)
  change only by `build model` / `support manifest model`. Commit them before `test generated` runs,
  because it compares against the git index.
- Commit messages through a quoted heredoc. Identity via `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env on every commit.
- English in code, docs and PR. The subject names `si#400`, and the PR body says `Closes` nothing (si#400 stays open).

## Measured before this plan (2026-10-16, firn v0.1.0, probe in the session scratchpad)

- **The `PORTS` loop keeps a portless task out with `if t.input or t.output { ... }`.** With one portless
  instance (`vcs:commit`) added, the generated `PORTS` was byte-identical to main's and `vcs:commit`
  appeared only in `BODIES`. With the condition replaced by `if true`, `"vcs:commit": (` appeared in `PORTS`
  (seen red). Only the id line's hash changes.
- **`key` with `subjectCardinality = 1..1` on `simplon.pipeline.Task`** keeps simplon's own project
  clean (rc 0), and an instance without it is `error[E004]: 'simplon.catalogue.nokey' has 0
  'simplon.pipeline.Task.key' where 1..1 is required`, rc 1. Decision 4 needs no kernel code. It is
  firn's diagnosis and holds the catalogue too.
- **`mangle(coordinate)` is injective over the 54 coordinates** (54 distinct names). The 18 existing
  instances are already named `mangle(key)` (`build_image`, `toolchain_run`, ...).
- **A coordinate (`:` in `task:`) always resolves from the catalogue** (`treeform._resolve_one`), so a
  product command on a catalogue coordinate can never mean a product body.
- **The demo fixture's four tasks write no `key`** (`src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn`),
  so they turn red under 1..1 and get their own keys.
- **The export counts per fixture after 4a** (product tasks placed / catalogue tasks placed): demo 0/13,
  agile-cockpit 3/20, asbundle 15/11, biz-cockpit 22/17, cleon 12/12, firn 4/25, netctl 52/18,
  simplon 3/30, swi 11/16. So the demo places **no** product task any more, and `test_the_export_drops_nothing`'s
  `assert impls and ...` would be red on it.

## Review Focus

1. **A catalogue task without ports must not enter `PORTS`.** `ports.py`, `migrate.py` and
   `manifestmodel.py` read `PORTS` as "the tasks that take or give an artifact". Pinned by the existing
   literal `test_the_ports_are_the_ones_measured_from_the_bodies`, which must stay untouched (Task 2).
2. **The export references `simplon.catalogue.<mangle(c)>`, so every instance must be named exactly
   that.** A misnamed instance passes every pure test and is red only where docker runs (E200). Pinned by
   a pure test that reads `tasks.firn` (Task 1).
3. **A product command on a portless catalogue task references the catalogue instance.** Before, the
   export re-declared it as a product `t_...` task, a second source of its body. Pinned in Task 3.
4. **"Drops nothing" counts product tasks by `task:` name, not by impl** (si#420: two tasks on one impl
   are two tasks), and the demo legitimately has none. Pinned in Task 3.
5. **The demo fixture and simplon's exported model check clean under `key 1..1`.** Otherwise
   `test_the_demo_checks_clean` and `test_simplons_own_firn_project_checks_clean` are red only where
   docker runs. Run both locally (Task 2 Step 7, Task 3 Step 7).

---

### Task 1: the model must carry every catalogue task, named as the export references it (red first)

**Files:**
- Modify: `src/tests/test_catalogue_ports.py`

**Interfaces:**
- Consumes: `artifactschema.BODIES: dict[str, str]`, `artifactschema.PORTS`, `catalogue.load().tasks`
  (coordinate -> mapping with `"impl"`), `manifestmodel.mangle(str) -> str`.
- Produces: two assertions that Task 2 turns green.

- [ ] **Step 1: Widen the body test.** In
  `test_every_modelled_task_is_a_catalogue_coordinate_with_the_body_the_catalogue_names`, rename it to
  `test_every_catalogue_task_is_modelled_with_the_body_the_catalogue_names` and replace
  `assert set(artifactschema.BODIES) == set(artifactschema.PORTS)` with:

```python
    # assert: since si#400 4a EVERY catalogue task is an instance in the model, not only those with ports;
    # the model and the hand-written catalogue stay two sources for one body until plan 4c
    assert set(artifactschema.BODIES) == set(tasks)
    assert set(artifactschema.PORTS) <= set(artifactschema.BODIES)
```

- [ ] **Step 2: Add the naming test** below it:

```python
def test_every_catalogue_instance_is_named_as_the_export_references_it():
    # arrange: manifestmodel writes `task = simplon.catalogue.<mangle(coordinate)>`; a misnamed instance
    # passes every pure test and is firn's E200 only where docker runs
    import re
    from pathlib import Path
    from simplon.domain.manifestmodel import mangle
    text = (Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "catalogue" / "tasks.firn").read_text()

    # act
    declared = dict(re.findall(
        r'^(\w+) typeOf simplon\.pipeline\.CatalogueTask \{\n  key = "([^"]+)"$', text, re.MULTILINE))

    # assert
    assert declared == {mangle(c): c for c in catalogue.load().tasks}
```

- [ ] **Step 3: Run both, see them red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_catalogue_ports.py -k "every_catalogue"`
Expected: 2 FAILED. `BODIES` has 18 keys and `tasks` 54, and `declared` holds 18 of 54.

- [ ] **Step 4: Do not commit alone.** The red tests go into Task 2's commit, so main stays green.

---

### Task 2: the 36 portless tasks join the catalogue, `key` becomes required

**Files:**
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (header comment, 36 instances appended)
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn` (`Task.key` 1..1, `CatalogueTask` comment)
- Modify: `src/firn/templates/schema.firnt` (`PORTS` loop guarded, `BODIES` comment)
- Modify: `src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn` (4 keys)
- Modify: `src/tests/test_firn_pipeline_e2e.py` (E004 seen red)
- Regenerated by `./simplon.sh build model`: `src/simplon/domain/artifactschema.py`
- Test: `src/tests/test_catalogue_ports.py`, `src/tests/test_firn_pipeline_e2e.py`

**Interfaces:**
- Consumes: Task 1's tests.
- Produces: `artifactschema.BODIES` with 54 keys, `PORTS` unchanged (18), and
  `simplon.catalogue.<mangle(c)>` for every catalogue coordinate `c`, which Task 3 references.

- [ ] **Step 1: Append the 36 instances** with this script. It reads `catalogue.yaml` in its own order and
  skips the coordinates already modelled, so the 18 hand-written instances with ports stay byte-identical:

```bash
deploy/orchestrator/.venv/bin/python - <<'EOF'
from pathlib import Path
from simplon.domain import catalogue
from simplon.domain.artifactschema import BODIES
from simplon.domain.manifestmodel import mangle
path = Path("src/firn/model/simplon/catalogue/tasks.firn")
lines = ["", "// si#400 4a: the catalogue's tasks that take or give no artifact, so they have no port. They are here",
         "// because the generated task classes (plan 4b) and every command's `task` need all of them."]
for coordinate, spec in catalogue.load().tasks.items():
    if coordinate not in BODIES:
        lines += [f"{mangle(coordinate)} typeOf simplon.pipeline.CatalogueTask {{",
                  f'  key = "{coordinate}"', f'  body = "{spec["impl"]}"', "}"]
path.write_text(path.read_text().rstrip("\n") + "\n" + "\n".join(lines) + "\n")
EOF
grep -c "typeOf simplon.pipeline.CatalogueTask" src/firn/model/simplon/catalogue/tasks.firn
```

Expected: `54`.

- [ ] **Step 2: Correct the file's header.** Its first line says "the catalogue's tasks that take or give an
  artifact, with their ports". Make it:

```firn
// simplon.catalogue (si#344 C.1, si#400 4a): every catalogue task, with its ports where it takes or gives an artifact.
```

  Also replace "`key` and `body` repeat catalogue.yaml's coordinate and impl until si#400 generates those from
  here" with "`key` and `body` repeat catalogue.yaml's coordinate and impl until si#400 plan 4c removes
  `impl:` there".

- [ ] **Step 3: Make `key` required.** In `pipeline.firn`, `Task`'s `property key` gets
  `subjectCardinality = 1..1` (was `0..1`), with this comment above `Task`:

```firn
// A task's `key` is its coordinate, and a task without one is firn's E004 (si#400 part 4, decision 4): two
// tasks on one coordinate, or one on none, could not be told apart. A diagnosis, and it binds the catalogue too.
```

  In the comment above `CatalogueTask`, replace "si#400 builds the base classes on this." with "Since si#400
  4a it holds all 54, ported or not."

- [ ] **Step 4: Guard the `PORTS` loop** in `schema.firnt`. Directly inside
  ``for t : `simplon.pipeline.CatalogueTask` {`` of the `PORTS` block, wrap the whole entry (from
  `|    "${t.key}": (` through `|    ),`) in

```firnt
      // a task with no port is no entry: PORTS answers "the tasks that take or give an artifact" (si#400 4a)
      if t.input or t.output {
        ...the entry, unchanged...
      }
```

  and change the `BODIES` comment line to
  `|#: Every catalogue task -> the body the model names. catalogue.yaml names it too until si#400 plan 4c.`

- [ ] **Step 5: Give the demo's tasks keys.** In `demo.firn`, add one line to each of the four tasks:
  `key = "build-image"`, `key = "test-image"`, `key = "publish-image"`, `key = "save-image"` (product task
  names, which carry no `:`, because a coordinate would be the catalogue's).

- [ ] **Step 6: See E004 red in the suite.** Add to `test_firn_pipeline_e2e.py`:

```python
@needs_docker
def test_a_task_without_a_key_is_refused_by_firn(demo):
    # arrange: si#400 part 4, decision 4 - the coordinate is required, and firn says so, not the kernel
    path = demo / "model" / "demo" / "demo.firn"
    path.write_text(path.read_text().replace('  key = "save-image"\n', "", 1))

    # act
    rc, out = firn_rc(demo, "check")

    # assert
    assert rc == 1
    assert "E004" in out and "simplon.pipeline.Task.key" in out
```

- [ ] **Step 7: Generate and run**

```bash
./simplon.sh build model
git diff --stat
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_catalogue_ports.py src/tests/test_firn_pipeline_e2e.py
./simplon.sh test model
```

Expected: the diff in `artifactschema.py` is the 36 new `BODIES` lines, the changed `BODIES` comment and the id
line, and **nothing inside `PORTS`**. All tests pass, including the literal `PORTS` test, which this task
does not touch. `test model` is rc 0.

- [ ] **Step 8: See the guard red.** Change `if t.input or t.output {` to `if true {`, run `./simplon.sh build model`
  and `pytest -q src/tests/test_catalogue_ports.py -k measured_from_the_bodies`. Expected: FAIL (36 empty
  entries in `PORTS`). Restore it, `build model` again, and check that `git diff src/simplon/domain/artifactschema.py` is
  back to Step 7's.

- [ ] **Step 9: Commit**

```bash
git add src/firn src/simplon/domain/artifactschema.py src/tests/test_catalogue_ports.py src/tests/test_firn_pipeline_e2e.py src/tests/fixtures/firn
GIT_AUTHOR_NAME=... GIT_AUTHOR_EMAIL=... GIT_COMMITTER_NAME=... GIT_COMMITTER_EMAIL=... git commit -F - <<'EOF'
feat(si#400): all 54 catalogue tasks are instances in the model, and a task needs its key

...body: the 36 portless tasks, PORTS unchanged (guard seen red), key 1..1 = firn E004 (seen red),
demo tasks keyed...

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

  (The identity comes from the memory note "Git identity needs env per commit".)

---

### Task 3: a command on any catalogue task references the catalogue instance

**Files:**
- Modify: `src/simplon/domain/manifestmodel.py` (import, docstring lines 40-45, the `spec.task in PORTS` branch)
- Modify: `src/tests/test_manifestmodel.py`
- Regenerated by `./simplon.sh support manifest model src/firn/model/product/simplon/simplon.firn`:
  `src/firn/model/product/simplon/simplon.firn`

**Interfaces:**
- Consumes: `artifactschema.BODIES` (54 keys, Task 2) and `simplon.catalogue.<mangle(c)>` (Task 2).
- Produces: an export in which `tasks ... typeOf simplon.pipeline.Task` appears only for a product's own
  tasks (no `:` in `key`). Plan 4b reads this.

- [ ] **Step 1: Write the failing tests** in `test_manifestmodel.py`, after
  `test_a_command_on_a_modelled_catalogue_task_references_it_and_declares_no_task_of_its_own`:

```python
def test_a_command_on_a_portless_catalogue_task_references_the_catalogue_instance():
    # arrange: vcs:push has no port, so before si#400 4a the export re-declared it as a product task
    text = DEMO.replace("      all:", '      push: { task: "vcs:push" }\n      all:')

    # act
    out = _export(text)

    # assert
    assert "task = simplon.catalogue.vcs_push" in _block(out, "command push typeOf simplon.pipeline.TaskCommand {")
    assert "simplon.tasks.vcs:push" not in out


def test_the_export_declares_no_task_on_a_catalogue_coordinate():
    # arrange: every reachable manifest; a product's own task never carries a `:` (treeform._resolve_one)
    for name in ["demo", *sorted(p.stem for p in FIXTURES.glob("*.yaml"))]:
        mf, text = _source(name)

        # act
        out = manifestmodel.export(mf, yaml.safe_load(text), name, manifestmodel.KERNEL_SECTIONS)

        # assert
        keys = re.findall(r'^\s+tasks \w+ typeOf simplon\.pipeline\.Task \{\n\s+key = "([^"]+)"', out, re.MULTILINE)
        assert [k for k in keys if ":" in k] == [], name


def test_the_export_counts_two_product_tasks_on_one_impl_as_two_tasks():
    # arrange: si#420 - one body, two declarations; "drops nothing" must count tasks, not impls
    text = DEMO.replace("cd:\n", "tasks:\n"
                        '  pack-a: { impl: "orchestrator.cli:pack", help: "A." }\n'
                        '  pack-b: { impl: "orchestrator.cli:pack", help: "B." }\n'
                        "cd:\n").replace("      all:", "      pa: { task: pack-a }\n      pb: { task: pack-b }\n"
                                         "      all:")

    # act
    out = _export(text)

    # assert
    assert _count(out, r"tasks \w+") == len(_placed_product_tasks(_load(text))) == 2
```

  Add the helper above `_count`:

```python
def _placed_product_tasks(mf: manifest_mod.Manifest) -> set[str]:
    """The product tasks a command places, keyed by the `task:` name, not by its impl (si#420)."""
    from simplon.domain.artifactschema import BODIES
    specs = [mf.spec_for(group, command) for group, members in mf.groups.items() for command in members]
    return {s.task for s in specs if not s.depends_on and s.task not in BODIES}
```

  In `test_the_export_drops_nothing`, replace

```python
    from simplon.domain.artifactschema import PORTS
    specs = [mf.spec_for(group, command) for group, members in mf.groups.items() for command in members]
    impls = {s.impl for s in specs if not s.depends_on and s.task not in PORTS}
```

  with

```python
    specs = [mf.spec_for(group, command) for group, members in mf.groups.items() for command in members]
    placed = _placed_product_tasks(mf)
```

  and `assert impls and _count(out, r"tasks \w+") == len(impls)` with

```python
    # since si#400 4a a command on a catalogue task references the catalogue's instance; the demo places none
    assert placed or name == "demo"
    assert _count(out, r"tasks \w+") == len(placed)
```

  Also update the comment in `test_a_command_runs_the_task_its_task_names_and_the_task_carries_the_impl`
  ("since si#344 C.2 a modelled catalogue task is referenced instead") to "since si#400 4a every catalogue
  task is referenced instead".

- [ ] **Step 2: Run them, see them red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_manifestmodel.py`
Expected: FAIL in `..._portless_catalogue_task_...`, `..._no_task_on_a_catalogue_coordinate`, and
`test_the_export_drops_nothing` for every fixture (the export still declares catalogue tasks).
`..._two_product_tasks_on_one_impl_as_two_tasks` passes already, because it pins a count that holds today.
To see it red, key `_placed_product_tasks` by `s.impl` for one run: it fails with `2 == 1`. Then restore it.

- [ ] **Step 3: Implement.** In `manifestmodel.py`, change the import `from simplon.domain.artifactschema import PORTS`
  to `from simplon.domain.artifactschema import BODIES`, and the branch

```python
            if spec.task in PORTS:
                # a catalogue task the model carries (si#344 C.1): referenced, never re-declared (C.2)
```

  to

```python
            if spec.task in BODIES:
                # a catalogue task: since si#400 4a the model carries all of them, ported or not, so it is
                # referenced and never re-declared (si#344 C.2)
```

  In the module docstring, change the bullet "a Task for a command on a catalogue task the model carries
  (`artifactschema.PORTS`): the command references `simplon.catalogue.<task>` instead, the one source of its
  ports (si#344 C.2)." to "no Task for a command on a catalogue task (`artifactschema.BODIES`, all of them
  since si#400 4a): the command references `simplon.catalogue.<task>` instead, the one source of its body and
  ports (si#344 C.2)." Then `grep -n PORTS src/simplon/domain/manifestmodel.py` must answer nothing.

- [ ] **Step 4: Run the tests**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_manifestmodel.py`
Expected: all pass.

- [ ] **Step 5: Regenerate simplon's own model**

```bash
./simplon.sh support manifest model src/firn/model/product/simplon/simplon.firn
git diff --stat src/firn/model/product/simplon/simplon.firn
grep -A1 'typeOf simplon.pipeline.Task {' src/firn/model/product/simplon/simplon.firn | grep 'key = ".*:'
```

Expected: the `t_<coordinate>` tasks are gone (`t_docs_reference`, `t_test_typecheck_python`, `t_vcs_commit`, ...),
their commands say `task = simplon.catalogue.<name>`, and the last `grep` prints nothing. The remaining
`tasks` blocks (`t_wheel`, `t_suite`, `t_region_guard`, ...) all have keys without `:`.

- [ ] **Step 6: Commit the generated file first**, then run `test generated` (it compares against the index):

```bash
git add src/simplon/domain/manifestmodel.py src/tests/test_manifestmodel.py src/firn/model/product/simplon/simplon.firn
./simplon.sh test generated
```

Expected: rc 0.

- [ ] **Step 7: Run the gates** (spec, "Gates")

```bash
./simplon.sh test model
./simplon.sh build model && git status --short     # tree clean afterwards
./simplon.sh test typecheck-python
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests
./simplon.sh build docs
```

Expected: `test model` rc 0 (simplon's exported model checks against the 54 instances), tree clean, typecheck
clean, the suite green except the 3 pre-existing `test_tasks_docs` failures, docs built. Also check that
`test_refusal_census` is green: this plan adds no Python raise, so no census entry is due.

- [ ] **Step 8: See the reference red.** Rename one instance in `tasks.firn` (`vcs_push` -> `vcs_pushx`), run
  `./simplon.sh test model` and `pytest -q src/tests/test_catalogue_ports.py -k named_as_the_export`.
  Expected: both red (`E200 cannot resolve 'simplon.catalogue.vcs_push'` from firn, the naming test from
  pytest). Restore it.

- [ ] **Step 9: Commit and open the PR**

```bash
GIT_AUTHOR_NAME=... git commit -F - <<'EOF'
feat(si#400): a command on any catalogue task references the catalogue's instance

...body: the export re-declared 36 catalogue tasks as product tasks; drops-nothing counts tasks by name...

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
git push -u origin si400-part4a-instances
gh pr create --title "si#400 part 4a: every catalogue task is an instance in the model" --body-file <file>
```

  The PR body names the measurements above, the two red checks per task, and "Plan 4b next: generated
  Python classes from these instances". It ends with the Claude Code attribution lines. After asking Marco
  to merge, push nothing more to the branch.

---

## What this plan does not do (on purpose)

- **No Python task classes** (`<pkg>/tasks/<name>.py`, protected region `run`, wrapper): plan 4b.
- **No runtime change**: `CommandSpec`, the `impl:` lookup and `signatures.py` stay (plan 4c), so
  `catalogue.yaml`'s `impl:` and the model's `body` remain two sources, held equal by
  `test_every_catalogue_task_is_modelled_with_the_body_the_catalogue_names`.
- **No Python `Command` hierarchy** (`TaskCommand`, `AggregateCommand`, `Deploy`, `ReleaseCommand`): plan 4b/4c.
  The part 4 spec does not name `Deploy` and `ReleaseCommand` yet. Plan 4b adds them to it.
- **No change for products.** Their `tasks:` entries and `impl:` are untouched. Only the export of their
  manifests to firn changes, and no product imports `simplon.pipeline` (spec, "The bill").
