# si#400 part 4b: a generated Python class per catalogue task, and the gen guard - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** firn generates one Python class per catalogue task (`class BuildImage(Task)`, its `KEY`, its
ports as `ClassVar[Port]` attributes, its body as a wrapper in a protected region), one file each. The
kernel's new `build:model` task runs `firn gen`, refuses W300/W301 with rc 1, and makes everything firn
wrote world-readable and whole. Its hand-typed file lists go.

**Architecture:** This is spec step 2, plus step 4, which Marco pulled forward on 2026-10-16 by choice list
because 54 more files would otherwise join two hand-typed lists. Nothing calls the classes at run time yet:
`CommandSpec`, the `impl:` lookup and `signatures.py` stay until plan 4c, which also builds the Python
`Command` hierarchy (`TaskCommand`, `AggregateCommand`, `Deploy`, `ReleaseCommand`, mirroring `pipeline.firn`).
Products are not touched (spec steps 5 and 6).

**Tech Stack:** firn v0.1.0 (pinned image `ghcr.io/marcozwyssig/firn:v0.1.0`), `.firnt`, Python 3, pytest,
mypy.

**Spec:** `docs/superpowers/specs/2026-10-15-part-4-tasks-as-generated-classes-design.md` (revised 2026-10-16).

## Global Constraints

- firn image stays exactly `ghcr.io/marcozwyssig/firn:v0.1.0`. The bump to v0.2.0 is si#410, a ticket of its
  own. firn runs only through the kernel (`toolchain`, `firnrun.firn_rc`), never as a host binary.
- Python only through `deploy/orchestrator/.venv/bin/python`. Run `./simplon.sh test typecheck-python`
  before every push.
- Generated files change only through `./simplon.sh build model` / `support manifest model`. Commit them
  before `test generated`, because it compares against the index.
- Commit messages go through a quoted heredoc, with `GIT_AUTHOR_*`/`GIT_COMMITTER_*` = Marco Zwyssig
  <marco@zwyssig.info> on every commit. Each one ends with the Co-Authored-By and Claude-Session lines.
- English in code, docs and PR. Subjects name `si#400`. The PR closes nothing.
- No count typed into prose. Write "every catalogue task", not "54".

## Measured before this plan (2026-10-16, probes in the session scratchpad)

- **A template writes one file per `CatalogueTask` instance** (`for t` around `file "tasks/${t.name}.py"
  language python`). On v0.1.0: 54 files written, rc 0. The class name has no firn built-in: snake to
  Pascal is `t.name.toFirstUpper()` followed by `.replace("_a", "A")` ... `.replace("_z", "Z")`, inside a
  template `function`. The probe got `BuildImage` and `SupportCiArm64`. `t.body.replace(":", " import ")`
  turns `simplon.tasks.image:build` into `simplon.tasks.image import build`.
- **mypy refuses an import in a class body** (`Unsupported class scoped import [misc]`). With the import
  in its own module-level region (`<name>.imports`) and `run = staticmethod(_body)` in `<name>.run`, mypy
  is clean, and `signatures.bindable(BuildImage().run) == signatures.bindable(build)` holds.
- **W301 reads the same in v0.1.0 and v0.2.0 JSON.** After renaming an instance, `gen --format=json`
  exits 0, lists `{"code": "W301", "message": "no template produces 'simplon/tasks/vcs_push.py' any more"}`
  in `diagnostics`, and lists the file in `files.kept`. The old file stays on disk with its old `KEY`.
  `files` has `written`, `unchanged`, `upToDate`, `deleted` and `kept`, with paths relative to the firn
  root (`src/`). On v0.1.0, stderr is empty under `--format=json`. W300 shows up in `diagnostics[].code`
  the same way (spec, measured 2026-10-15).
- **firn writes every file 0600, in v0.1.0 and v0.2.0 alike.** A `.py` in the wheel takes the builder's
  umask, not its mode on disk (`test_every_file_in_the_wheel_is_readable_by_everyone`). Package data such
  as `catalogue.yaml` keeps its mode.
- **`docker.run_container(line, name, capture=True)` returns `Result(rc, out, err)`.**
- **No snake file name collides with a hand module in `src/simplon/tasks/`** (measured for si#400 4a, 2026-10-16).

## Review Focus

1. **A file from a renamed or removed task, kept by W301, still defines a class with a live `KEY`.**
   `build:model` must be rc 1 and name the file. A tree that already carries such a file must also be red
   in the suite without docker. Pinned in Task 2 (stray-file test) and Task 3 (`verdict` on W301).
2. **firn's stdout is not JSON** (a crash, a usage error, a future format change). `build:model` must be
   rc 1 with what firn printed, never rc 0 on nothing parsed. Pinned in Task 3.
3. **firn reports no file at all, with rc 0** (an empty selector, firn#966). That is "nothing done", not
   success, so rc 1. Pinned in Task 3.
4. **A generated class whose wrapper has a different signature from its impl** would bind other CLI
   options in 4c. Pinned for every class in Task 2 (`bindable` and `takes_context` equal).
5. **A new generated file that was never committed** is untracked, and `git diff` does not see it, so
   `test generated` would be green over it. Pinned in Task 4.

---

### Task 1: the spec says what changed

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-part-4-tasks-as-generated-classes-design.md`

**Interfaces:** none (prose).

- [ ] **Step 1: Add a dated paragraph under the 2026-10-16 revision.** Text:

```markdown
**Revised again 2026-10-16 (Marco, by choice list, before plan 4b):** the ports are `ClassVar[Port]`
attributes holding the same `artifactschema.Port` values `PORTS` holds, generated from the same instance;
4c derives `PORTS` from the classes, and the second rendering goes. The gen guard (step 4) moves before the
runtime (step 3): firn writes every file 0600 and `build model`'s two hand-typed file lists would otherwise
grow by one entry per task, so the kernel's new `build:model` task reads `gen --format=json`, refuses
W300/W301, and sets 0644 on and checks the wholeness of every file firn reports. The import of the wrapped
body stands in a module-level protected region `<name>.imports`, not in the class: mypy refuses a
class-scoped import (measured). The Python `Command` hierarchy mirrors `pipeline.firn` one to one,
`Deploy(TaskCommand)` and `ReleaseCommand(AggregateCommand)` included, and is built in 4c.
```

- [ ] **Step 2: Correct "The shape in Python".** Replace the block's `image: Image  # output port; the type
  is the kind class` and the region lines with the measured shape:

```python
# simplon/tasks/build_image.py - GENERATED; edit only inside the protected regions
# Begin Protected Region [build_image.imports]
from simplon.tasks.image import build as _body
# End Protected Region  [build_image.imports]


class BuildImage(Task):
    KEY = "build:image"
    file: ClassVar[Port] = Port("file", "input", "file", "", ())
    image: ClassVar[Port] = Port("image", "output", "image", "name", ("registry", "repository", "dockerfile", "context"))

    # Begin Protected Region [build_image.run]
    run = staticmethod(_body)                 # the wrapper (decision 3)
    # End Protected Region  [build_image.run]
```

  Keep the `TaskCommand`/`AggregateCommand` lines below it. In "What goes, and in what order", add
  "(moved before step 3 on 2026-10-16, see above)" after step 4's title.

- [ ] **Step 3: Commit** together with this plan:

```bash
git add docs/superpowers
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
docs(si#400): plan 4b, and the spec follows Marco's 2026-10-16 choices

Ports are ClassVar[Port] attributes; the gen guard moves before the runtime; the wrapped
body's import stands in a module-level region (mypy refuses a class-scoped one, measured).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: the Task base class and one generated class per catalogue task

**Files:**
- Create: `src/simplon/domain/task.py`
- Create: `src/firn/templates/tasks.firnt`
- Modify: `src/firn.toml` (`[target.simplon]` templates)
- Create: `src/tests/test_task_classes.py`
- Generated by `./simplon.sh build model`: `src/simplon/tasks/<instance>.py`, one per catalogue task

**Interfaces:**
- Consumes: `simplon.catalogue.<name>` instances (4a), `artifactschema.Port`, `artifactschema.PORTS`,
  `catalogue.load().tasks[c]["impl"]`, `manifestmodel.mangle`, `signatures.bindable`, `signatures.takes_context`.
- Produces: `simplon.domain.task.Task` (`KEY: ClassVar[str]`). For every coordinate `c`, the module
  `simplon.tasks.<mangle(c)>` defines exactly one `Task` subclass, with `KEY == c`, a `Port` class
  attribute per port, and `run`. Task 3 adds `build:model` and gets its class from this template.

- [ ] **Step 1: Write the failing tests** in `src/tests/test_task_classes.py`:

```python
"""si#400 part 4b: one generated class per catalogue task, held to the catalogue it is generated from.

Pure: no docker. The classes are committed generated files (`build model`), so the committed files are
what has to be right, as test_catalogue_ports.py says of artifactschema.

AAA; the name states the behaviour under test.
"""
import importlib
import re
from pathlib import Path

import pytest

from simplon.domain import artifactschema, catalogue, signatures
from simplon.domain.manifestmodel import mangle
from simplon.domain.task import Task

TASKS = Path(__file__).resolve().parents[1] / "simplon" / "tasks"
COORDINATES = sorted(catalogue.load().tasks)


def _class_of(coordinate: str) -> type[Task]:
    module = importlib.import_module(f"simplon.tasks.{mangle(coordinate)}")
    found = [v for v in vars(module).values()
             if isinstance(v, type) and issubclass(v, Task) and v is not Task and v.__module__ == module.__name__]
    assert len(found) == 1, f"{module.__name__} defines {found}"
    return found[0]


def _impl(coordinate: str):
    module, function = catalogue.load().tasks[coordinate]["impl"].split(":")
    return getattr(importlib.import_module(module), function)


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_every_catalogue_task_has_one_generated_class_carrying_its_coordinate(coordinate):
    # act
    cls = _class_of(coordinate)

    # assert
    assert cls.KEY == coordinate


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_a_class_carries_the_ports_the_model_gives_its_task_inputs_first(coordinate):
    # act
    ports = tuple(v for v in vars(_class_of(coordinate)).values() if isinstance(v, artifactschema.Port))

    # assert: the same values PORTS holds, from the same instance (4c derives PORTS from these)
    assert ports == artifactschema.PORTS.get(coordinate, ())


@pytest.mark.parametrize("coordinate", COORDINATES)
def test_the_wrapper_binds_exactly_what_the_impl_binds(coordinate):
    # arrange: 4c runs cls().run where it runs the impl today; any difference changes the CLI it renders
    body, impl = _class_of(coordinate)().run, _impl(coordinate)

    # act / assert
    assert signatures.bindable(body) == signatures.bindable(impl)
    assert signatures.takes_context(body) == signatures.takes_context(impl)


def test_the_class_names_are_distinct():
    # act
    names = [_class_of(c).__name__ for c in COORDINATES]

    # assert
    assert len(set(names)) == len(names)


def test_no_generated_task_file_is_left_over_from_a_task_the_catalogue_no_longer_has():
    # arrange: firn KEEPS a file whose task was renamed or removed, with rc 0 (W301, measured), and that
    # file still defines a class with a live KEY - two classes on one coordinate
    ids = {p.name: re.search(r"id=\[Tasks:simplon\.catalogue\.(\w+),", p.read_text())
           for p in TASKS.glob("*.py")}

    # act
    generated = {name: m.group(1) for name, m in ids.items() if m}

    # assert
    assert generated, "no generated task file found - the template wrote nothing, or its id line changed"
    assert sorted(generated.values()) == sorted(mangle(c) for c in COORDINATES)
    assert all(name == f"{instance}.py" for name, instance in generated.items())


def test_every_generated_file_keeps_its_body_in_two_named_regions():
    # act
    missing = [c for c in COORDINATES
               for region in (f"[{mangle(c)}.imports]", f"[{mangle(c)}.run]")
               if f"Begin Protected Region {region}" not in (TASKS / f"{mangle(c)}.py").read_text()]

    # assert
    assert missing == []
```

- [ ] **Step 2: Run them, see them red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_task_classes.py`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'simplon.domain.task'`.

- [ ] **Step 3: Write the base class** `src/simplon/domain/task.py`:

```python
"""si#400 part 4: the base of every task class firn generates, one per task (`<package>/tasks/<name>.py`).

A task class carries its coordinate in `KEY`, its ports as `ClassVar[Port]` attributes, and its body as
`run`, which until a product moves the body into the method is the wrapper `run = staticmethod(<impl>)`
in the class's protected region (spec decision 3). Nothing runs these classes before plan 4c; the suite
holds each one to the catalogue it is generated from (tests/test_task_classes.py).
"""
from typing import ClassVar


class Task:
    """A task: an instance of `simplon.pipeline.Task` in the model, a class here."""

    KEY: ClassVar[str]
```

- [ ] **Step 4: Write the template** `src/firn/templates/tasks.firnt`. Write the `replace` chain for all 26
  letters out in full: `.replace("_a", "A").replace("_b", "B")` ... `.replace("_z", "Z")`. The probe generated
  it with a shell loop. Commit the literal text. The `if not` blocks are for the 36 tasks with no port, which
  must not import names they do not use.

```firnt
template Tasks {

  // A Python class name from an instance name: snake_case to PascalCase. firn has no built-in for it
  // (docs/04 §3.5), so each "_<letter>" is replaced; mangle() only writes [a-z0-9_] (si#400 4b, measured).
  function className(t) {
    |${t.name.toFirstUpper().replace("_a", "A")<...the other 25 letters...>.replace("_z", "Z")}
  }

  function port(p, direction) {
    if p.param {
      |    ${p.name}: ClassVar[Port] = Port("${p.name.replace("_", "-")}", "${direction}", "${p.accepts.name.replace("_", "-")}", "${p.param}", (<<for f : p.needs>>"${f.key}", <<end>>))
    }
    if not p.param {
      |    ${p.name}: ClassVar[Port] = Port("${p.name.replace("_", "-")}", "${direction}", "${p.accepts.name.replace("_", "-")}", "", (<<for f : p.needs>>"${f.key}", <<end>>))
    }
  }

  // One file per catalogue task (part 4, decision 5), its body in two protected regions: the import at
  // module level (mypy refuses a class-scoped one) and `run` in the class (decision 2). Their first content
  // is the wrapper over today's `impl:` (decision 3).
  for t : `simplon.pipeline.CatalogueTask` {
    file "tasks/${t.name}.py" language python {
      |"""GENERATED from simplon.catalogue.${t.name} by `./simplon.sh build model`: the task `${t.key}`.
      |
      |Edit only inside the protected regions; firn rewrites everything else on every run."""
      if t.input or t.output {
        |from typing import ClassVar
        |
        |from simplon.domain.artifactschema import Port
      }
      |from simplon.domain.task import Task
      |
      protected "${t.name}.imports" {
      |from ${t.body.replace(":", " import ")} as _body
      }
      |
      |
      |class ${@className(t)}(Task):
      |    KEY = "${t.key}"
      for p : t.input {
        |${@port(p, "input")}
      }
      for p : t.output {
        |${@port(p, "output")}
      }
      |
      protected "${t.name}.run" {
      |    run = staticmethod(_body)
      }
    }
  }
}
```

  Two things in it are unmeasured: the `port` function (a call to a function that holds an `if`), and the
  `${@port(...)}` line's indentation. If the output differs from the shape in the spec, rule on the
  smallest change (inline the two `if` blocks into each `for` instead of the function), and ledger it.

- [ ] **Step 5: Register the template.** In `src/firn.toml`, `[target.simplon]`, change
  `templates = ["Catalogue", "ArtifactSchema"]` to `templates = ["Catalogue", "ArtifactSchema", "Tasks"]`, and
  add to the comment above it: "and one class per catalogue task in `simplon/tasks/` (si#400 4b)".

- [ ] **Step 6: Generate and look at two files**

```bash
./simplon.sh build model
ls src/simplon/tasks/*.py | xargs grep -l "id=\[Tasks:" | wc -l
cat src/simplon/tasks/build_image.py src/simplon/tasks/vcs_push.py
```

Expected: `build model` rc 0. The count equals `len(catalogue.load().tasks)`. `build_image.py` matches the
spec's shape, two ports included. `vcs_push.py` has no `ClassVar`/`Port` import and no port lines.

- [ ] **Step 7: Run the tests and the type gate**

```bash
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_task_classes.py
./simplon.sh test typecheck-python
```

Expected: all pass. mypy reports "no issues". If an impl module cannot be imported for one coordinate, that
is a finding about that module. Report it, and do not skip it in the test.

- [ ] **Step 8: See three tests red.**
  (a) In `src/simplon/tasks/vcs_push.py`, change the region's `run = staticmethod(_body)` to
  `def run(self, x): pass`. The wrapper test fails for `vcs:push`. Restore with `git checkout`.
  (b) Copy `src/simplon/tasks/vcs_push.py` to `src/simplon/tasks/vcs_pushed.py`. The stray-file test fails.
  Delete the copy.
  (c) Delete the `for p : t.output` loop from the template and `build model`. The ports test fails for
  every task with an output. Restore it and `build model` again. `git status` shows only Task 2's files.

- [ ] **Step 9: Commit**

```bash
git add src/simplon/domain/task.py src/firn/templates/tasks.firnt src/firn.toml src/tests/test_task_classes.py src/simplon/tasks/
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#400): firn generates one Python class per catalogue task

<what: Task base, template, one file per task, ports as ClassVar[Port], body in two regions;
the three red checks of step 8>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 3: `build:model` runs `firn gen` and refuses what firn only warns about

**Files:**
- Modify: `src/simplon/tasks/toolchain.py` (extract the line-building half of `run_toolchain`)
- Create: `src/simplon/tasks/firngen.py`
- Modify: `src/simplon/catalogue.yaml` (inside the protected region: the `build:model` task, after `build:fetch`)
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (the `build_model` instance)
- Modify: `simplon.yaml` (`build model`, its leaves, the `make-readable`/`whole-files` tasks)
- Modify: `deploy/orchestrator/src/python/orchestrator/cli.py` (delete `make_readable`, `whole_files` and what only they use)
- Delete: `src/tests/test_own_make_readable.py`. Move `src/tests/test_own_whole_files.py`'s cases into the new test.
- Modify: `src/tests/test_own_workflows.py` (the derived step lists)
- Create: `src/tests/test_firngen.py`
- Generated: `src/simplon/tasks/build_model.py`, `src/simplon/domain/artifactschema.py` (BODIES), the CI
  workflow and the completion if `test generated` says so

**Interfaces:**
- Consumes: `toolchain.declared`, `toolchain.docker_argv`, `docker.run_container(line, name, capture=True) -> Result(rc, out, err)`.
- Produces: `toolchain.invocation(where: str, *, image: str, argv: list[str], workdir: str, env, caches, network, cwd, extra) -> tuple[list[str], str] | None`
  (the docker line and the container name, or None after the ownership fault has been logged);
  `firngen.generate(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None) -> int`;
  `firngen.verdict(rc: int, out: str, root: Path) -> int`, which is pure apart from `chmod`.

- [ ] **Step 1: Write the failing unit tests** in `src/tests/test_firngen.py`. Cover `verdict` with
  hand-written JSON in `tmp_path`, no docker:

```python
"""si#400 4b: `build:model` runs `firn gen --format=json` and turns what firn only warns about into rc 1.

firn v0.1.0 keeps a file with a protected region when no template produces it any more (W301) and appends
an orphaned region at the end of a file (W300), both with rc 0 (measured, part 4 spec); it writes every
file 0600; and an empty selector deletes a generated file with rc 0 (firn#966). `verdict` is where each of
those becomes an answer. AAA.
"""
import json
import stat

from simplon.tasks import firngen


def _out(written=(), unchanged=(), kept=(), codes=()):
    return json.dumps({"diagnostics": [{"code": c, "message": f"{c} message"} for c in codes],
                       "files": {"written": list(written), "unchanged": list(unchanged), "upToDate": [],
                                 "deleted": [], "kept": list(kept)}})


def _file(root, name, text="x = 1\n# Generated by firn, do not edit. id=[T:,1]\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)
    return path


def test_a_clean_run_is_rc_0_and_every_reported_file_is_world_readable(tmp_path):
    # arrange
    a, b = _file(tmp_path, "a.py"), _file(tmp_path, "d/b.yaml")

    # act
    rc = firngen.verdict(0, _out(written=["a.py"], unchanged=["d/b.yaml"]), tmp_path)

    # assert
    assert rc == 0
    assert stat.S_IMODE(a.stat().st_mode) == stat.S_IMODE(b.stat().st_mode) == 0o644


def test_a_kept_file_is_rc_1_naming_it(tmp_path, capsys):
    # arrange
    _file(tmp_path, "a.py")

    # act
    rc = firngen.verdict(0, _out(written=["a.py"], kept=["tasks/old.py"], codes=["W301"]), tmp_path)

    # assert
    assert rc == 1
    assert "tasks/old.py" in capsys.readouterr().err


def test_an_orphaned_region_is_rc_1(tmp_path, capsys):
    # arrange
    _file(tmp_path, "a.py")

    # act
    rc = firngen.verdict(0, _out(written=["a.py"], codes=["W300"]), tmp_path)

    # assert
    assert rc == 1
    assert "W300" in capsys.readouterr().err


def test_firns_own_failure_passes_through_with_what_it_said(tmp_path, capsys):
    # act
    rc = firngen.verdict(1, '{"diagnostics": [{"code": "E200", "message": "cannot resolve"}], "files": {}}', tmp_path)

    # assert
    assert rc == 1
    assert "E200" in capsys.readouterr().err


def test_output_that_is_not_json_is_rc_1_not_success(tmp_path, capsys):
    # act
    rc = firngen.verdict(0, "usage: firn gen ...", tmp_path)

    # assert
    assert rc == 1
    assert "usage: firn gen" in capsys.readouterr().err


def test_a_run_that_reports_no_file_is_rc_1(tmp_path):
    # act / assert: nothing generated is not "done" (firn#966)
    assert firngen.verdict(0, _out(), tmp_path) == 1


def test_a_file_holding_only_firns_id_line_is_rc_1(tmp_path, capsys):
    # arrange: what a template error leaves (si#344 B1)
    _file(tmp_path, "a.py", "# Generated by firn, do not edit. id=[T:,1]\n")

    # act
    rc = firngen.verdict(0, _out(written=["a.py"]), tmp_path)

    # assert
    assert rc == 1
    assert "a.py" in capsys.readouterr().err


def test_a_reported_file_that_is_not_there_is_rc_1(tmp_path):
    # act / assert
    assert firngen.verdict(0, _out(written=["gone.py"]), tmp_path) == 1
```

  Move `test_own_whole_files.py`'s remaining cases over (the markdown heading counts as content, an
  `<!-- -->` header does not), rewritten against `verdict`. Then delete that file.

- [ ] **Step 2: Run them, see them red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_firngen.py`
Expected: collection ERROR, `ImportError: cannot import name 'firngen'`.

- [ ] **Step 3: Extract the invocation from `run_toolchain`.** In `toolchain.py`, move everything from
  `cfg = declared(...)` through `line = docker_argv(...)` into

```python
def invocation(where: str, *, image: str, argv: list[str] | None, workdir: str, env: object, caches: object,
               network: str | None, cwd: str | None, extra: list[str]) -> tuple[list[str], str] | None:
    """The `docker run` line for one toolchain invocation and its container's name, or None when the
    output tree is not the caller's (the fault is logged). Shared by `run_toolchain` and `firngen.generate`."""
```

  Keep its comments. Return `None` where `run_toolchain` returned 1 after `log.error(fault)`. `run_toolchain`
  becomes `got = invocation(where, image=image, ...)`, then `if got is None: return 1`, then
  `return docker.run_container(*got).rc`. The suite must stay green here (`test_toolchain*`).

- [ ] **Step 4: Write `src/simplon/tasks/firngen.py`**

```python
"""`build:model` (si#400 4b): run `firn gen` over a product's firn project, and refuse what firn only warns about.

firn v0.1.0 answers rc 0 when it KEEPS a file no template produces any more (W301) and when it appends a
protected region a template no longer produces (W300) - measured in the part 4 spec. The kept file still
defines a task class with a live KEY, so after a rename two classes carry one coordinate: green, and wrong.
`gen --format=json` names both in `diagnostics[].code`, and this reads it (spec decision 6).

It also does what `build model` did by hand-typed lists until 4b: firn writes every file 0600, so each file
firn reports is made 0644, and a file holding nothing but firn's id line - what a template error or an
empty selector leaves (firn#966) - is refused. The list is firn's own report, so it cannot go stale.
"""
import json
import re
import sys
from pathlib import Path

import typer

from simplon.adapters import docker
from simplon.kernel import context
from simplon.tasks import toolchain

#: firn's id line in any comment syntax: `# ...` (yaml, python) or `<!-- ... -->` (html, markdown).
_ID_LINE = re.compile(r"Generated by firn\b.*\bid=\[.*\]")
#: firn's diagnostics that leave a file behind with rc 0 (docs/04 §2.5).
REFUSED = ("W300", "W301")


def generate(ctx: typer.Context, image: str = "", cwd: str | None = None, network: str | None = None) -> int:
    """Run `firn gen --format=json` in the pinned `image`, started in `cwd`, and rule on what it reports."""
    where = ctx.command_path or "build:model"
    got = toolchain.invocation(where, image=image, argv=["gen", "--format=json"], workdir="/workspace",
                               env=None, caches=None, network=network, cwd=cwd, extra=[])
    if got is None:
        return 1
    result = docker.run_container(*got, capture=True)
    if result.err.strip():
        print(result.err, file=sys.stderr, end="")
    return verdict(result.rc, result.out, context.current().root / (cwd or ""))


def _is_header_comment(line: str, suffix: str) -> bool:
    """A comment-only line: `<!-- ... -->` anywhere, `# ...` unless the file is markdown (a heading is content)."""
    text = line.strip()
    if text.startswith("<!--") and text.endswith("-->"):
        return True
    return text.startswith("#") and suffix != ".md"


def verdict(rc: int, out: str, root: Path) -> int:
    """0 only when firn succeeded, reported at least one file, refused nothing it only warns about, and every
    file it reported is there, holds more than its id line, and is now 0644. `root` is firn's project root."""
    try:
        report = json.loads(out)
        diagnostics, files = report["diagnostics"], report["files"]
    except (ValueError, KeyError, TypeError):
        print(f"build:model: firn's output is not its JSON report (rc {rc}), so nothing can be ruled on:\n{out}",
              file=sys.stderr)
        return 1
    for d in diagnostics:
        print(f"firn {d.get('code')}: {d.get('message')}", file=sys.stderr)
    if rc != 0:
        return rc
    bad = 0
    refused = [d for d in diagnostics if d.get("code") in REFUSED]
    for path in files.get("kept", []):
        print(f"build:model: firn kept {path}, which no template produces any more but which holds a protected "
              f"region. It still defines what it defined - move its region's content where it belongs, then "
              f"delete the file", file=sys.stderr)
    if refused:
        print(f"build:model: {', '.join(sorted({str(d.get('code')) for d in refused}))} - firn left a protected "
              f"region no template produces, with rc 0; see above", file=sys.stderr)
        bad = 1
    produced = [*files.get("written", []), *files.get("unchanged", []), *files.get("upToDate", [])]
    if not produced:
        print("build:model: firn reported no file at all - nothing was generated, which is not done (firn#966)",
              file=sys.stderr)
        return 1
    for name in produced:
        path = root / name
        if not path.is_file():
            print(f"build:model: firn reported {name}, and it is not there", file=sys.stderr)
            bad = 1
            continue
        content = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if all(_ID_LINE.search(line) or _is_header_comment(line, path.suffix) for line in content):
            print(f"build:model: {name} holds nothing but firn's id line and header comments - what a template "
                  f"error leaves; read firn's error above", file=sys.stderr)
            bad = 1
        path.chmod(0o644)
    return bad
```

  `files.get("kept")` alone makes nothing red: firn says W301 for each kept file, and that is what refuses.
  The message only names the file.

- [ ] **Step 5: Run the unit tests**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_firngen.py src/tests/test_toolchain*.py`
Expected: all pass.

- [ ] **Step 6: Offer it in the catalogue.** In `src/simplon/catalogue.yaml`'s protected region, after the
  `build:fetch` entry, add:

```yaml
  # `firn gen` over a product's firn project (si#400 4b): firn's own answer, plus rc 1 on what firn only
  # warns about (W300/W301 - a kept file still defines its task class), 0644 on every file it wrote, and rc 1
  # on a reported file holding only firn's id line. The list is firn's report, never a hand-typed one.
  build:model:
    impl: simplon.tasks.firngen:generate
    help: "Generate from this product's firn model, refusing a protected region firn kept or orphaned."
    params:
      image:   { help: "the pinned firn image" }
      cwd:     { help: "the directory under the root where firn.toml is (a plain relative path)" }
      network: { help: "the docker network firn runs on ('none' for no networking)" }
```

  Add the instance to `tasks.firn`, in the portless block from 4a:

```firn
build_model typeOf simplon.pipeline.CatalogueTask {
  key = "build:model"
  body = "simplon.tasks.firngen:generate"
}
```

- [ ] **Step 7: Use it in `simplon.yaml`.** `model-gen` becomes

```yaml
      model-gen:
        task: build:model
        with:
          image: ghcr.io/marcozwyssig/firn:v0.1.0
          cwd: src
          network: none
```

  Remove `model-whole` and `model-mode` from `build model`'s `depends_on` (it becomes
  `[model-guard, model-gen]`) and delete both commands. Delete the `make-readable` and `whole-files` entries
  under `tasks:`. Rewrite the aggregate's long comment, keeping the measured history. The two later steps'
  work now happens inside `build:model`, from firn's report. `model-guard` stays, because v0.1.0 has no
  W303, and W303 arrives with si#410. In `deploy/orchestrator/src/python/orchestrator/cli.py`, delete
  `make_readable`, `whole_files`, `_ANY_ID_LINE` and `_is_header_comment`, but only if nothing else uses
  them (`grep -n` first). `outside_region` and `_ID_LINE` are `region_guard`'s and stay.

- [ ] **Step 8: Generate, update the step lists, run**

```bash
./simplon.sh build model
stat -c '%a' src/simplon/catalogue.yaml src/simplon/tasks/build_model.py
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_own_workflows.py src/tests/test_task_classes.py src/tests/test_firngen.py src/tests/test_catalogue_ports.py
```

Expected: rc 0, both files `644`, `build_model.py` generated. `test_own_workflows` fails on its two literal
lists. In both, drop `"build model-whole"` and `"build model-mode"`, and in the first docstring add one
sentence: "si#400 4b folded `model-whole` and `model-mode` into `model-gen`, which runs `build:model`".
Then all pass.

- [ ] **Step 9: See it red against the real firn** (docker). Add to `test_firngen.py`:

```python
from conftest import docker_is_usable
from firnrun import FIRN
import pytest
import shutil

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")
SRC = __import__("pathlib").Path(__file__).resolve().parents[1]


@needs_docker
def test_a_renamed_task_is_refused_against_the_real_firn(tmp_path):
    # arrange: simplon's own project, generated once, then one catalogue instance renamed - firn keeps the
    # old class file with rc 0 (W301, measured)
    from firnrun import firn_rc
    project = tmp_path / "src"
    shutil.copytree(SRC / "firn", project / "firn")
    shutil.copy(SRC / "firn.toml", project / "firn.toml")
    shutil.copytree(SRC / "simplon", project / "simplon", ignore=shutil.ignore_patterns("__pycache__"))
    (project / "site" / "content" / "with-what").mkdir(parents=True)
    (project / "tests" / "generated").mkdir(parents=True)
    shutil.rmtree(project / "firn" / "model" / "product")   # its commands reference the instance by name
    tasks = project / "firn" / "model" / "simplon" / "catalogue" / "tasks.firn"
    tasks.write_text(tasks.read_text().replace("vcs_push typeOf", "vcs_pushed typeOf", 1))

    # act
    rc, out = firn_rc(tmp_path, "gen", "--format=json", cwd="src")

    # assert
    assert rc == 0                                         # firn alone calls it fine
    assert firngen.verdict(rc, out, project) == 1          # build:model does not
```

  Check `firnrun.FIRN` and `firn_rc`'s arguments before relying on them (they are named in
  `src/tests/firnrun.py:10-19`). Run it: it passes. Then replace `"W300", "W301"` with `"W300"` in
  `REFUSED`, and it fails. Restore it.

- [ ] **Step 10: Commit**

```bash
git add -A src/simplon src/firn src/tests simplon.yaml deploy/orchestrator
git status --short   # nothing unintended, no deleted file you did not mean
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#400): build:model runs firn gen and refuses what firn only warns about

<what: W300/W301 -> rc 1, 0644 and wholeness from firn's own report, model-whole and
model-mode and their hand-typed lists gone; seen red against the real firn>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 4: `test generated` covers the generated task classes, the untracked ones too

**Files:**
- Modify: `src/simplon/tasks/generated.py` (`check`: an untracked file under an entry's path is stale)
- Modify: `simplon.yaml` (`generated:` gets `task-classes`)
- Test: `src/tests/test_tasks_generated.py`

**Interfaces:**
- Consumes: `generated.check()`, `generated._tracked`, `generated._differs`.
- Produces: `generated._untracked(root: Path, path: str) -> list[str]`.

- [ ] **Step 1: Write the failing test.** Read `src/tests/test_tasks_generated.py` first and follow how it
  builds a git repository and an entry. Add a case: an entry whose `path` is a directory with one
  committed file and one new, untracked file under it. Its `by` command writes both. `check()` must be 1,
  and the log must name the untracked file. Add a second case: the same directory with both files
  committed must be 0.

- [ ] **Step 2: Run it, see it red**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_tasks_generated.py`
Expected: the untracked case FAILS (`check()` is 0, because `git diff` does not see an untracked file).

- [ ] **Step 3: Implement**

```python
def _untracked(root: Path, path: str) -> list[str]:
    """Files under `path` git does not track and does not ignore: a new generated file never committed.
    `git diff` cannot see one, so without this a directory entry is green over exactly that staleness."""
    listed = run.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "--", path])
    return [line for line in listed.out.splitlines() if line.strip()]
```

  In `check`, after `_regenerate` succeeds:

```python
        new = _untracked(root, entry.path)
        if new:
            log.error(f"{entry.name}: `{entry.by}` wrote {', '.join(new)}, which git does not track. Commit it "
                      f"(or, if no template should write it, find out why one does)")
            stale.append(entry.name)
            continue
```

- [ ] **Step 4: Run it**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_tasks_generated.py`
Expected: all pass.

- [ ] **Step 5: Declare the classes.** In `simplon.yaml`'s `generated:`, after `artifact-schema`:

```yaml
  # One class per catalogue task (si#400 4b), firn's whole output in this directory beside the hand-written
  # task modules: a directory entry, so a class for a new task is stale until committed.
  task-classes:
    path: src/simplon/tasks
    by: build model
```

- [ ] **Step 6: Gates, all of them** (spec, "Gates"). Commit the tree first, because `test generated`
  compares against the index:

```bash
git add src/simplon/tasks/generated.py src/tests/test_tasks_generated.py simplon.yaml
./simplon.sh test generated
./simplon.sh test model
./simplon.sh build model && git status --short
./simplon.sh test typecheck-python
deploy/orchestrator/.venv/bin/python -m pytest -q src/tests > <workspace>/suite.log 2>&1; tail -1 <workspace>/suite.log
./simplon.sh build docs
./simplon.sh build wheel && deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_wheel.py
```

Expected: every gate rc 0, the tree clean after `build model`, the suite green (the 3 root-bound
`test_tasks_docs` failures excepted, if they appear), and `test_wheel` green, which now covers the generated
modules too. If `test generated` regenerates the CI workflow or completion differently, commit what it
wrote and say so in the commit.

- [ ] **Step 7: Commit, push, PR**

```bash
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -F - <<'EOF'
feat(si#400): test generated holds the task classes, and an untracked generated file is stale

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
git push -u origin si400-part4b-task-classes
gh pr create --base main --title "si#400 part 4b: a generated class per catalogue task, and build:model" --body-file <file>
```

  The PR body names the measurements, each red check, Marco's two choices of 2026-10-16, and "Plan 4c next:
  the runtime runs these classes; Command classes; CommandSpec and impl: go". It ends with the Claude Code
  attribution lines. After asking Marco to merge, push nothing more.

---

## What this plan does not do (on purpose)

- **Nothing runs the classes**: `CommandSpec`, `impl:` and `signatures.py` stay (plan 4c), and with them two
  sources for a body, the class's wrapper and `catalogue.yaml`'s `impl:`. `test_the_wrapper_binds_exactly_what_the_impl_binds`
  and `test_catalogue_ports` hold the two together until then.
- **No `Command` classes**: plan 4c.
- **No product classes, no jar, no `-cp`**: spec steps 5 and 6. `build:model` is the command step 5 extends.
- **No firn bump**: si#410. `model-guard` stays until W303 replaces it there.
