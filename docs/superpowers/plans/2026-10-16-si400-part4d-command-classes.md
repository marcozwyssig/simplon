# si#400 part 4d: commands are objects of Command classes - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `CommandSpec` goes. Each command of a loaded manifest is an object of a class that mirrors
`simplon.pipeline` one to one: `TaskCommand`, `Deploy(TaskCommand)`, `AggregateCommand` and
`ReleaseCommand(AggregateCommand)`, all deriving `Command`. Each class carries only its own fields. The
base answers the other kind's fields with their empty value for one release window, with a deprecation
warning, so netctl's tests keep running.

**Architecture:** This follows Marco's choice list of 2026-10-16 (si#400 comment 6219416834).
- The classes are frozen dataclasses.
- `TaskCommand.task` holds the coordinate or name, and `task_class()` resolves it lazily.
- `ReleaseCommand.release` is the release bundle (today `produces: {release: ...}` on an aggregate).
- `Deploy` is a task command in an env-first group, with no field of its own yet.

The kernel reads only a command's own kind. The suite turns the compatibility warning into an error, so
every kernel read of the other kind is found mechanically.

**Tech Stack:** Python 3 dataclasses, pytest, mypy.

**Spec:** `docs/superpowers/specs/2026-10-15-part-4-tasks-as-generated-classes-design.md`, with si#400 comments 6219416834 and 6214912886.

## Global Constraints

- Python only through `deploy/orchestrator/.venv/bin/python`. Run `./simplon.sh test typecheck-python` before every push.
- Commits go through a quoted heredoc, with `GIT_AUTHOR_*`/`GIT_COMMITTER_*` = Marco Zwyssig <marco@zwyssig.info>.
  End each with the Co-Authored-By and Claude-Session lines.
- English in code, docs and PR. Subjects name `si#400`. The PR closes nothing.
- No count typed into prose. A new load-time refusal gets its census entry.
- **Measure before claiming**: the 4c count of imported modules was wrong once. Count with a meta-path hook, never with `PYTHONPROFILEIMPORTTIME` under `./simplon.sh`.

## Measured before this plan (2026-10-16)

- **Consumers.** netctl's `test_manifest_parity.py`, `test_bringup.py` and `test_manifest_flag_agreement.py`
  read `impl`, `depends_on`, `help`, `stop_on_failure` and `hidden` through `Manifest.spec_for` /
  `.commands` / `plan_tree_for`, and call `manifest.resolve_impl`. That includes `assert not spec.impl` on an
  aggregate and `spec.depends_on` on every command. No consumer constructs a `CommandSpec` (GitHub code
  search, owner marcozwyssig; firn's `CommandSpec` is picocli, unrelated).
- **Construction.** `manifest.py:965` (the one place a loaded manifest builds them) and `walk.py:607` (a
  walk's synthesized specs). `workflowgen.py:1099`'s `_replace` is on a `Step`, not on a spec.
- **The form.** A frozen dataclass whose base defines `__getattr__` for the other kind's field names answers
  them only when the instance lacks them. Measured: `TaskCommand.depends_on` gives `()` with a warning,
  `AggregateCommand.impl` gives `""` with a warning. A frozen assignment still raises, an unknown name still
  raises `AttributeError`, and `deepcopy` and `pickle` round-trip.
- **Per kind**, by the loader's own rules (`manifest.py` validators and the `CommandSpec` docstring):
  - **leaf only:** `passthrough_args`, `with_`, `params`, `task`, `consumes`, `ports`, `impl`, and
    `produces` for port bindings;
  - **aggregate only:** `depends_on`, `stop_on_failure`, `parallel`, `keep_awake`, `passes`, and
    `produces: {release: X}` (the release bundle, si#344 C.3);
  - **both:** `help`, `hidden`, `unattended` (accepted on both; `workflowgen` reads it on leaves).
- **The removal clock.** `kernel.moved.MOVED_DUE_AFTER = (0, 32)`, so the si#399 aliases go in 0.33.0.
  This compatibility gets its own `COMPAT_DUE_AFTER = (0, 33)`, so it goes in 0.34.0, one release after it
  ships. It is checked the way `test_surface` checks the aliases' deadline.

## Review Focus

1. **A kernel read of the other kind.** It is found by the suite with the compatibility warning as an error.
   A read the suite does not exercise is found by a grep in Task 2 Step 5.
2. **A walk's synthesized specs** (`walk.py`) must be the right class, because `PlanNode.is_leaf` decides
   leaf versus aggregate there. Pinned in Task 2.
3. **A release aggregate that names its bundle** must be a `ReleaseCommand` whose `release` is that name.
   Its port rules (`ports._check_bundles`) and the firn export (`manifestmodel`) must read `release`, not
   `produces["release"]`. Pinned in Task 3.
4. **An aggregate in an env-first group** stays an `AggregateCommand`. Only a TASK command in an env-first
   group is a `Deploy`. Pinned in Task 3.
5. **The compatibility must not outlive its date.** A test goes red once the checkout's version passes
   `COMPAT_DUE_AFTER`. Pinned in Task 1.

---

### Task 1: the Command classes

**Files:**
- Create: `src/simplon/domain/command.py`
- Create: `src/tests/test_command.py`
- Modify: `src/simplon/cli/surface.py` (classify `domain.command`) and `src/site/content/with-what/surface.md`
  if `test_surface` asks
- Modify: `src/firn/model/simplon/components/components.firn` (a `m_domain_command` module in the
  `domain` component)

**Interfaces:**
- Produces:
  - `Command(help: str = "", hidden: bool = False, unattended: bool | None = None)`
  - `TaskCommand(Command)` with `impl: str = ""`, `task: str = ""`, `passthrough_args: bool = False`,
    `with_: Mapping[str, object] = {}`, `params: Mapping[str, ParamPresentation] = {}`,
    `produces: Mapping[str, tuple[str, ...]] = {}`, `consumes: Mapping[str, tuple[str, ...]] = {}`,
    `ports: tuple[Port, ...] = ()`, and the method `task_class(self, *, where: str) -> type[Task]`
  - `Deploy(TaskCommand)`
  - `AggregateCommand(Command)` with `depends_on: tuple[str, ...] = ()`, `stop_on_failure: bool = False`,
    `parallel: bool = False`, `keep_awake: bool = False`, `passes: tuple[str, ...] = ()`
  - `ReleaseCommand(AggregateCommand)` with `release: str = ""`
  - `CompatWarning(DeprecationWarning)`, `COMPAT_DUE_AFTER = (0, 33)`
  - `ParamPresentation` moves here from `manifest.py`, and `manifest` re-exports it (it is LIBRARY).
  - Mutable defaults use `field(default_factory=...)` or `MappingProxyType`. Use what mypy accepts with
    frozen, and ledger it.

- [ ] **Step 1: Write the failing tests** in `src/tests/test_command.py`:

```python
"""si#400 4d: a command is an object of a Command class mirroring simplon.pipeline (TaskCommand, Deploy,
AggregateCommand, ReleaseCommand). AAA."""
import dataclasses
import pickle
import warnings

import pytest

from simplon.domain import command


def test_a_task_command_carries_its_own_fields_and_reads_the_aggregates_as_empty_with_a_warning():
    # arrange
    leaf = command.TaskCommand(help="h", impl="m:f", task="build:image")

    # act / assert: netctl's tests read `depends_on` on every command (measured) - one release window
    with pytest.warns(command.CompatWarning, match=r"TaskCommand\.depends_on"):
        assert leaf.depends_on == ()
    assert leaf.impl == "m:f"


def test_an_aggregate_reads_impl_as_empty_with_a_warning():
    # arrange: netctl asserts `not spec.impl` on an aggregate (measured)
    agg = command.AggregateCommand(help="h", depends_on=("a",))

    # act / assert
    with pytest.warns(command.CompatWarning, match=r"AggregateCommand\.impl"):
        assert agg.impl == ""


def test_an_unknown_field_is_still_an_attribute_error():
    # act / assert
    with pytest.raises(AttributeError):
        command.TaskCommand(help="h").nonsense


def test_a_command_is_frozen_and_round_trips():
    # arrange
    agg = command.ReleaseCommand(help="h", depends_on=("a",), release="bundle")

    # act / assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        agg.release = "other"
    assert pickle.loads(pickle.dumps(agg)) == agg


def test_the_hierarchy_mirrors_the_pipeline_model():
    # act / assert
    assert issubclass(command.Deploy, command.TaskCommand) and issubclass(command.TaskCommand, command.Command)
    assert issubclass(command.ReleaseCommand, command.AggregateCommand)
    assert issubclass(command.AggregateCommand, command.Command)
    assert not issubclass(command.AggregateCommand, command.TaskCommand)


def test_task_class_is_resolved_only_when_asked():
    # arrange: holding the name keeps manifest loading free of body imports (Marco's choice 2)
    leaf = command.TaskCommand(help="h", impl="simplon.tasks.vcs_push:VcsPush", task="vcs:push")

    # act
    cls = leaf.task_class(where="build push")

    # assert
    assert cls.KEY == "vcs:push"


def test_the_compatibility_is_gone_after_its_release():
    # arrange: the checkout's own version, as test_surface reads it for MOVED_DUE_AFTER
    from test_surface import _release_number

    # act / assert
    assert _release_number() <= command.COMPAT_DUE_AFTER, (
        f"the read compatibility on Command was due to go after {command.COMPAT_DUE_AFTER}: delete "
        f"`Command.__getattr__`, `_OTHER_KIND`, `CompatWarning` and these tests' compat cases")
```

  Check first that `test_surface._release_number` exists with that name and returns `(major, minor)`. If
  not, use what `test_surface` uses for `MOVED_DUE_AFTER`, and ledger it.

- [ ] **Step 2: Run, see red** (`ModuleNotFoundError: simplon.domain.command`).

- [ ] **Step 3: Implement `command.py`.** Keep a module docstring that names si#400 4d and the choice list.
  `_OTHER_KIND` maps each field name to its empty value for the kind that lacks it:
  `impl: ""`, `task: ""`, `passthrough_args: False`, `with_: {}`, `params: {}`, `produces: {}`, `consumes: {}`,
  `ports: ()`, `depends_on: ()`, `stop_on_failure: False`, `parallel: False`, `keep_awake: False`,
  `passes: ()`, `release: ""`. `Command.__getattr__(name)` returns it with
  `warnings.warn(f"{type(self).__name__}.{name} is not a field of a {type(self).__name__}; it reads as empty until simplon {major}.{minor + 1}.0 removes it - ask isinstance(command, TaskCommand) instead", CompatWarning, stacklevel=2)`,
  and raises `AttributeError(name)` for anything else. Dunder names must raise at once, because
  copy and pickle probe them. `task_class` returns `task.task_class(self.impl, self.task or where, where=where)`.

- [ ] **Step 4: Run** `test_command.py`, `test_surface.py` and `test_architecture.py`. Classify
  `domain.command` as LIBRARY in `surface.py`, because netctl reads these objects. Add the page line and the
  components entry as their tests ask, then `./simplon.sh build model`. Typecheck.

- [ ] **Step 5: Commit** as `feat(si#400): the Command classes - TaskCommand, Deploy, AggregateCommand, ReleaseCommand`.

---

### Task 2: the loader builds Command objects; CommandSpec goes; the kernel reads its own kind

**Files:**
- Modify: `src/simplon/domain/manifest.py` (the construction at ~965, the `CommandSpec` class deleted,
  `ParamPresentation` re-exported, `resolve_impl`), `src/simplon/kernel/plan.py` (`is_leaf`),
  `src/simplon/tasks/walk.py` (~607), and every module `grep -rln CommandSpec src/simplon` names
  (cli, workflowgen, catalogue, handoff, treeform at least)
- Modify: `pyproject.toml` (pytest `filterwarnings`: `error::simplon.domain.command.CompatWarning`)
- Test: the suite

**Interfaces:**
- Consumes: Task 1's classes.
- Produces: `Manifest.commands: dict[str, dict[str, Command]]`, and `spec_for` returns a `Command`.
  `PlanNode.spec: Command`, `PlanNode.is_leaf` = `isinstance(self.spec, TaskCommand)`.

- [ ] **Step 1: Make the compatibility an error in the suite.** Add to `pyproject.toml` `[tool.pytest.ini_options]`
  `filterwarnings = ["error::simplon.domain.command.CompatWarning"]`. Read the file first: if a
  `filterwarnings` list exists, append to it. In `test_command.py`, the two compatibility tests already use
  `pytest.warns`, which captures the warning before the filter turns it into an error. Run them to confirm.

- [ ] **Step 2: Build the right class at the construction site.** At `manifest.py:965`, replace
  `CommandSpec(...)` with a helper `_command(group, spec, ...)` that chooses:
  - with `depends_on`: a `ReleaseCommand(release=produces["release"][0], ...)` when
    `spec.produces.get("release")`, else an `AggregateCommand`;
  - without: a `Deploy` when the group is env-first (`group in env_groups`; read how `Manifest.env_groups`
    is computed and use the same value at that point), else a `TaskCommand`.

  Each gets only its own kind's fields. In `walk.py:607`, a leaf is a `TaskCommand(impl=..., help=...)` and an
  aggregate an `AggregateCommand(help=..., stop_on_failure=...)`. Delete `class CommandSpec`. Run
  `grep -rn "CommandSpec" src/simplon` and replace each use with `Command` (annotations) or the right
  subclass (isinstance).

- [ ] **Step 3: Run the suite, then fix each red by reading it.** Each `CompatWarning` error names a
  kernel read of the other kind, for example `spec.impl` asked of every command to tell a leaf from an
  aggregate. Replace it with `isinstance(spec, TaskCommand)` / `AggregateCommand`, or move the read inside
  the branch that already knows the kind. `plan.py:61`'s `is_leaf` becomes `isinstance(self.spec,
  TaskCommand)`. Ledger every module touched, and fix causes: never weaken the filter.

- [ ] **Step 4: See it red.** Remove one `isinstance` guard you added, for example in `plan.py`, and put
  `bool(self.spec.impl)` back. The suite fails with `CompatWarning`. Restore it.

- [ ] **Step 5: Find what the suite does not exercise.** Run
  `grep -rnE "\.(depends_on|stop_on_failure|parallel|keep_awake|passes)\b" src/simplon` and
  `grep -rnE "\.(impl|with_|params|passthrough_args|consumes|ports)\b" src/simplon`. For each hit on a
  command object, check that it sits where the kind is known (an isinstance branch, or a function only one
  kind reaches). Ledger the ones you read and the ones you changed.

- [ ] **Step 6: Typecheck and suite**, then commit as `refactor(si#400): the loader builds Command objects, CommandSpec goes`.

---

### Task 3: ReleaseCommand carries its bundle; Deploy is a task command in an env-first group

**Files:**
- Modify: `src/simplon/domain/ports.py` (`_check_bundles` and any `produces.get("release")`),
  `src/simplon/domain/manifestmodel.py` (the release aggregate's export), and anything `grep -rn
  "\"release\"" src/simplon | grep produces` names
- Test: `src/tests/test_command.py`

- [ ] **Step 1: Write the failing tests** in `test_command.py`:

```python
def test_a_release_aggregate_is_a_release_command_naming_its_bundle():
    # arrange: simplon's own manifest releases through `release all` with `produces: { release: kernel-release }`
    from conftest import ROOT
    from simplon.domain import catalogue, manifest
    mf = manifest.load((ROOT / "simplon.yaml").read_text(encoding="utf-8"), catalogue=catalogue.load())

    # act
    releases = {f"{g} {n}": c for g, cs in mf.commands.items() for n, c in cs.items()
                if isinstance(c, command.ReleaseCommand)}

    # assert
    assert releases and all(c.release for c in releases.values())


def test_a_task_command_in_an_env_first_group_is_a_deploy_and_an_aggregate_there_is_not():
    # arrange: a manifest with a `cd: deploy:` leaf and an aggregate beside it (read an existing test fixture
    # that has both - tests/test_manifest.py's env-first cases - and reuse its text)
    ...
```

  Write the second test's body from a real fixture with both forms. Find one with
  `grep -rn "cd:" src/tests/test_manifest.py | head`. Assert that the leaf is a `Deploy` and that the
  aggregate is an `AggregateCommand` and not a `Deploy`.

- [ ] **Step 2: Run, see red or green.** The construction from Task 2 may already satisfy both. If so, see
  them red by building every leaf as a `TaskCommand`, then restore.

- [ ] **Step 3: Readers of the bundle** read `release`. `grep -rn 'produces.get("release"\|produces\["release"\]' src/simplon`.
  Each hit on an aggregate becomes `isinstance(c, ReleaseCommand)` and `c.release`. Run the suite.

- [ ] **Step 4: Commit** as `feat(si#400): ReleaseCommand carries its bundle, Deploy is an env-first task command`.

---

### Task 4: prose, gates, PR, and a note for netctl

- [ ] **Step 1: Prose.** `grep -rn "CommandSpec" src docs/*.md`. Today `src/site/content/when/releases.md`
  names it. Rewrite each mention that is now false, and leave history in dated plan and spec files alone.
  The spec gets one dated line: "4d built 2026-10-16: commands are Command objects; read compat until 0.34.0".
- [ ] **Step 2: All gates**: `test generated` (commit first), `test model`, `build model` with a clean tree,
  `typecheck-python`, the suite (with the filter), `build docs`, and `build wheel` + `test_wheel.py`.
- [ ] **Step 3: Commit, push, PR.** The body lists the four decisions, the consumers measured, the red checks,
  and "netctl: its tests read through the compatibility, and see a CompatWarning; switch to isinstance
  before 0.34.0". After the merge and the next release, tell netctl's peer session the same, with the
  release number.

## What this plan does not do (on purpose)

- **No `environment`/`site` field on `Deploy`**: the environment arrives at run time (`--env`). It is added
  when a body reads one from the object.
- **No product change.** Products' manifests are untouched. Their tests read through the compatibility until 0.34.0.
- **`signatures.py` and `PORTS` stay** (4c's decisions).
