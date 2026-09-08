# `toolchain:run` and the uniform build - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One kernel task that runs a pinned toolchain image over a product tree as the calling user, plus a scaffolder that writes a language's ready-made configuration into a product's manifest.

**Architecture:** Follows `tasks/image.py` exactly - a typed config, a `declared()` validator that turns a manifest body into it and refuses what it cannot accept, and a PURE argv assembler that runs nothing. The executor is thin. Language profiles are DATA, scaffolded into the product's manifest rather than resolved at run time, so a kernel bump can never change how a product builds.

**Tech Stack:** Python 3.11+, pytest, mypy (`test:typecheck-python`), the existing `simplon.docker`, `simplon.run`, `simplon.labinstance`.

**Spec:** `docs/superpowers/specs/2026-09-09-toolchain-run-and-the-uniform-build-design.md`

## Global Constraints

- The coordinate is a FAMILY: `toolchain:run`, never `build:toolchain`. si#34 would then forbid placing it under `test`, where `ctest` / `dotnet test` / `gradle test` belong.
- Every image goes through `docker.pinned_image(image, where, hint=...)`. No second check, no exception.
- Every container that writes into the bind mount gets `docker.user_args()`. This is the defect class `user_args`'s own docstring calls "LEARNED TWICE".
- Argv rule: the manifest's argv first, the caller's appended after it. An empty caller argv must produce byte-for-byte what the manifest declares.
- Cache volumes carry the instance suffix from `labinstance.resolve()`.
- Declared, NOT placed - in `tasks:` only. A product without a compiled toolchain must not receive these commands.
- Adding a coordinate turns the counted docs pages red. Task 6 is not optional and not a follow-up.
- Refusals are diagnoses: name the value, the key and the way out.

---

### Task 1: `Toolchain` config and its validator

**Files:**
- Create: `src/simplon/tasks/toolchain.py`
- Test: `tests/test_toolchain.py`

**Interfaces:**
- Consumes: `simplon.docker.pinned_image`, `simplon.log`
- Produces: `Toolchain(image: str, workdir: str, argv: list[str], env: dict[str,str], caches: list[Cache])`, `Cache(volume: str, path: str)`, `declared(body: Mapping, where: str) -> Toolchain`

- [ ] **Step 1: Write the failing tests**

```python
"""si#95: the toolchain declaration a product writes, and what the kernel refuses."""
import pytest

from simplon.tasks import toolchain


def _boom(msg, *a, **k):
    raise RuntimeError(msg)


def test_a_declaration_becomes_a_toolchain(monkeypatch):
    # arrange
    body = {"image": "gradle:jdk25", "workdir": "/work",
            "argv": ["gradle", "build"],
            "env": {"GRADLE_USER_HOME": "/home/gradle/.gradle"},
            "caches": [{"volume": "gradle-cache", "path": "/home/gradle/.gradle"}]}

    # act
    cfg = toolchain.declared(body, where="build.compile")

    # assert
    assert cfg.image == "gradle:jdk25"
    assert cfg.argv == ["gradle", "build"]
    assert cfg.caches == [toolchain.Cache(volume="gradle-cache", path="/home/gradle/.gradle")]


def test_an_unpinned_image_is_refused_by_the_one_gate(monkeypatch):
    # arrange: the refusal must come from pinned_image, not a second check written here
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle", "argv": ["gradle"]}, where="build.compile")
    assert "gradle" in str(e.value)


def test_a_declaration_without_argv_is_refused_by_name(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert: the message names the key and where it was missing
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle:jdk25"}, where="build.compile")
    assert "argv" in str(e.value) and "build.compile" in str(e.value)


def test_workdir_defaults_so_a_product_need_not_write_it():
    # arrange / act
    cfg = toolchain.declared({"image": "gcc:14", "argv": ["make"]}, where="build.compile")

    # assert: the spec's "the user has only their parameters" - /work is the kernel's answer
    assert cfg.workdir == "/work"
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain.py`
Expected: FAIL with `ImportError: cannot import name 'toolchain'`

- [ ] **Step 3: Write the minimal implementation**

```python
"""`toolchain:run` - one pinned image, over the product tree, as the calling user (si#95).

WHY A FAMILY AND NOT A PLACEMENT. si#34 makes a coordinate opening with a group name a placement, and a
containerised toolchain is needed by `build` AND `test` - ctest, dotnet test and gradle test all belong
under the latter. As a family it is free to be filed where the product needs it.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from simplon import docker, log


@dataclass(frozen=True)
class Cache:
    """A named volume mounted into the container, so a dependency graph survives the run."""

    volume: str
    path: str


@dataclass(frozen=True)
class Toolchain:
    image: str
    argv: list[str]
    workdir: str = "/work"
    env: dict[str, str] = field(default_factory=dict)
    caches: list[Cache] = field(default_factory=list)


def declared(body: Mapping[str, object], where: str) -> Toolchain:
    """Turn a command's `with:` body into a Toolchain, refusing what cannot be run.

    The image goes through `docker.pinned_image` rather than a check written here: one gate for every
    image in the kernel is the point of that function, and a second one drifts from it.
    """
    image = body.get("image")
    if not isinstance(image, str) or not image:
        log.die(f"{where}: no `image:` - a toolchain command names the image it runs in")
        raise SystemExit(1)
    argv = body.get("argv")
    if not isinstance(argv, Sequence) or isinstance(argv, str) or not argv:
        log.die(f"{where}: no `argv:` - a toolchain command names what to run inside the image")
        raise SystemExit(1)
    caches = [Cache(volume=str(c["volume"]), path=str(c["path"]))
              for c in body.get("caches", []) if isinstance(c, Mapping)]
    return Toolchain(
        image=docker.pinned_image(image, where, hint="a toolchain must name its version"),
        argv=[str(a) for a in argv],
        workdir=str(body.get("workdir", "/work")),
        env={str(k): str(v) for k, v in dict(body.get("env", {})).items()},
        caches=caches,
    )
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain.py`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add src/simplon/tasks/toolchain.py tests/test_toolchain.py
git commit -m "feat(#95): the toolchain declaration, and the three things it refuses"
```

---

### Task 2: the pure argv assembler

**Files:**
- Modify: `src/simplon/tasks/toolchain.py`
- Modify: `tests/test_toolchain.py`

**Interfaces:**
- Consumes: `Toolchain` from Task 1, `docker.user_args()`, `labinstance.resolve()`
- Produces: `argv(cfg: Toolchain, root: Path, product: str, instance: str, extra: list[str], network: str | None = None) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path


def _cfg(**kw):
    body = {"image": "gradle:jdk25", "argv": ["gradle", "build"]}
    body.update(kw)
    return toolchain.declared(body, where="build.compile")


def test_the_argv_mounts_the_tree_and_runs_as_the_caller(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", "1000:1000"])

    # act
    line = toolchain.argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])

    # assert: the bind mount, the workdir, and the uid that owns whatever the run writes
    assert "--user" in line and "1000:1000" in line
    assert "-v" in line and "/repo:/work" in line
    assert line[-2:] == ["gradle", "build"]


def test_the_caller_argv_is_APPENDED_to_the_manifest_argv(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    line = toolchain.argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev",
                          extra=["--rerun-tasks"])

    # assert: netctl#1091's promise - the full vocabulary survives - on top of a pinned default
    assert line[-3:] == ["gradle", "build", "--rerun-tasks"]


def test_an_empty_caller_argv_changes_nothing(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    a = toolchain.argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])
    b = toolchain.argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])

    # assert
    assert a == b and a[-2:] == ["gradle", "build"]


def test_cache_volumes_carry_the_product_and_the_instance(monkeypatch):
    # arrange: netctl#453's property, which only netctl knew by hand until now
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = _cfg(caches=[{"volume": "gradle-cache", "path": "/home/gradle/.gradle"}])

    # act
    dev = toolchain.argv(cfg, root=Path("/repo"), product="netctl", instance="dev", extra=[])
    a1 = toolchain.argv(cfg, root=Path("/repo"), product="netctl", instance="a1", extra=[])

    # assert
    assert "netctl-gradle-cache-dev:/home/gradle/.gradle" in dev
    assert "netctl-gradle-cache-a1:/home/gradle/.gradle" in a1


def test_env_reaches_the_container_and_nothing_else_does(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])
    cfg = _cfg(env={"GRADLE_USER_HOME": "/home/gradle/.gradle"})

    # act
    line = toolchain.argv(cfg, root=Path("/repo"), product="netctl", instance="dev", extra=[])

    # assert: no implicit inheritance - what the manifest names, and only that
    assert "GRADLE_USER_HOME=/home/gradle/.gradle" in line
    assert len([x for x in line if x == "-e"]) == 1


def test_the_network_appears_only_when_it_is_given(monkeypatch):
    # arrange: the one runtime value the manifest cannot supply (the spec's section 5)
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: [])

    # act
    without = toolchain.argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[])
    with_net = toolchain.argv(_cfg(), root=Path("/repo"), product="netctl", instance="dev", extra=[],
                              network="scratch-net")

    # assert
    assert "--network" not in without
    assert ["--network", "scratch-net"] == with_net[2:4]
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain.py -k argv or cache or env or network`
Expected: FAIL with `AttributeError: module 'simplon.tasks.toolchain' has no attribute 'argv'`

- [ ] **Step 3: Write the minimal implementation**

```python
def argv(cfg: Toolchain, root: Path, product: str, instance: str,
         extra: list[str], network: str | None = None) -> list[str]:
    """The full docker argv for one toolchain invocation. PURE: it assembles, it runs nothing.

    Pure for the reason `gradle_argv` is pure in netctl: the decisions here - which volume, whose uid,
    what order - are exactly what a test should be able to read without a docker daemon in the room.

    `extra` is APPENDED, never merged: the manifest pins what a CI step means, and a person at a terminal
    keeps the tool's whole vocabulary behind it.
    """
    volumes: list[str] = []
    for cache in cfg.caches:
        volumes += ["-v", f"{product}-{cache.volume}-{instance}:{cache.path}"]
    env: list[str] = []
    for key, value in cfg.env.items():
        env += ["-e", f"{key}={value}"]
    return ["docker", "run", "--rm",
            *(["--network", network] if network else []),
            *docker.user_args(),
            "-v", f"{root}:{cfg.workdir}", "-w", cfg.workdir,
            *volumes, *env,
            cfg.image, *cfg.argv, *extra]
```

Note: `--network` must be assembled BEFORE `user_args()` for the positional assertion in the test to hold; keep that order.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain.py`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/simplon/tasks/toolchain.py tests/test_toolchain.py
git commit -m "feat(#95): the toolchain argv, pure, with the caller's words appended"
```

---

### Task 3: the executor and the catalogue coordinate

**Files:**
- Modify: `src/simplon/tasks/toolchain.py`
- Modify: `src/simplon/catalogue.yaml`
- Modify: `tests/test_toolchain.py`

**Interfaces:**
- Consumes: `argv()` from Task 2, `simplon.run.run`, `simplon.context`
- Produces: `run_toolchain(...) -> int` bound as `simplon.tasks.toolchain:run_toolchain`

- [ ] **Step 1: Write the failing test**

```python
def test_the_executor_runs_the_assembled_line_and_returns_its_rc(monkeypatch):
    # arrange
    from simplon.run import Result
    seen = []
    monkeypatch.setattr(toolchain, "run",
                        lambda a, **kw: seen.append(list(a)) or Result(rc=3, out="", err=""))
    monkeypatch.setattr(toolchain, "argv", lambda *a, **k: ["docker", "run", "--rm", "img", "cmd"])

    # act
    rc = toolchain.run_toolchain({"image": "img:1", "argv": ["cmd"]}, where="build.compile", extra=[])

    # assert: thin - it executes what argv decided, and hands the real rc back
    assert seen == [["docker", "run", "--rm", "img", "cmd"]]
    assert rc == 3
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain.py -k executor`
Expected: FAIL with `has no attribute 'run_toolchain'`

- [ ] **Step 3: Implement, and declare the coordinate**

```python
def run_toolchain(body: Mapping[str, object], where: str, extra: list[str],
                  network: str | None = None) -> int:
    """Run one toolchain invocation. Thin: `declared` decides what is legal, `argv` decides the line."""
    cfg = declared(body, where)
    ctx = context.current()
    line = argv(cfg, root=ctx.root, product=ctx.name, instance=labinstance.resolve(),
                extra=extra, network=network)
    return run(line, capture=False).rc
```

In `src/simplon/catalogue.yaml`, under `tasks:`, add - declared, not placed:

```yaml
  # --- toolchain: a pinned image over the product tree (si#95) -----------------------------------------
  # A FAMILY, not a placement: si#34 would confine `build:toolchain` to `build`, and ctest / dotnet test /
  # gradle test belong under `test`. Declared and not placed, because a product with no compiled
  # toolchain should not receive the command with the kernel.
  toolchain:run:
    impl: simplon.tasks.toolchain:run_toolchain
    help: "Run a pinned toolchain image over the product tree, as the calling user."
```

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=src pytest -q tests/`
Expected: the toolchain tests PASS; the counted docs tests now FAIL - that is Task 6, and it is expected here.

- [ ] **Step 5: Commit**

```bash
git add src/simplon/tasks/toolchain.py src/simplon/catalogue.yaml tests/test_toolchain.py
git commit -m "feat(#95): toolchain:run is declared, as a family and not a placement"
```

---

### Task 4: language profiles, as data

**Files:**
- Create: `src/simplon/tasks/profiles.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PROFILES: dict[str, Profile]`, `Profile(image: str, commands: dict[str, dict])`, `profile(language: str, **params) -> Profile`

- [ ] **Step 1: Write the failing tests**

```python
"""si#95: the ready-made configurations. DATA, and inert after the scaffold."""
import pytest

from simplon.tasks import profiles, toolchain


def test_every_profile_declares_a_toolchain_the_kernel_accepts():
    # arrange: a broken profile must not be shippable - this is the whole assurance profiles need
    for language, prof in profiles.PROFILES.items():
        for name, body in prof.commands.items():
            # act / assert
            cfg = toolchain.declared({**body, "image": prof.image.format(version="1")},
                                     where=f"{language}.{name}")
            assert cfg.argv


def test_the_cpp_profile_compiles_tests_and_analyses():
    # arrange / act
    prof = profiles.profile("cpp", compiler="clang", version="19")

    # assert: the spec's table, as data
    assert prof.image == "silkeh/clang:19"
    assert prof.commands["compile"]["argv"][:2] == ["cmake", "--build"]
    assert "ctest" in prof.commands["unit"]["argv"]
    assert "clang-tidy" in prof.commands["analyse"]["argv"]


def test_an_unknown_language_is_refused_and_lists_what_exists(monkeypatch):
    # arrange
    monkeypatch.setattr(profiles.log, "die", lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))

    # act / assert
    with pytest.raises(RuntimeError) as e:
        profiles.profile("cobol")
    assert "cobol" in str(e.value) and "cpp" in str(e.value)
```

- [ ] **Step 2: Run and watch fail**

Run: `PYTHONPATH=src pytest -q tests/test_profiles.py`
Expected: FAIL with `cannot import name 'profiles'`

- [ ] **Step 3: Implement**

```python
"""The ready-made toolchain configurations (si#95): DATA, scaffolded, then inert.

WHY THE KERNEL MAY CARRY LANGUAGE KNOWLEDGE HERE, having refused it for modules. A profile is a table of
argv and paths, not behaviour, and `support:toolchain` writes it INTO the product's manifest. After that
the product owns what it runs: this table can change without moving anybody's build, and a wrong entry is
fixed by editing a manifest rather than by waiting for a kernel release.
"""
from __future__ import annotations

from dataclasses import dataclass

from simplon import log


@dataclass(frozen=True)
class Profile:
    image: str
    commands: dict[str, dict]


PROFILES: dict[str, Profile] = {
    "cpp": Profile(
        image="silkeh/clang:{version}",
        commands={
            "configure": {"workdir": "/src", "argv": ["cmake", "-S", ".", "-B", "build"]},
            "compile":   {"workdir": "/src", "argv": ["cmake", "--build", "build", "-j"]},
            "unit":      {"workdir": "/src", "argv": ["ctest", "--test-dir", "build", "--output-on-failure"]},
            "analyse":   {"workdir": "/src", "argv": ["clang-tidy", "-p", "build"]},
        }),
    "java": Profile(
        image="gradle:jdk{version}",
        commands={
            "compile": {"workdir": "/work", "argv": ["gradle", "build", "--no-daemon", "--console=plain"]},
            "unit":    {"workdir": "/work", "argv": ["gradle", "test", "--no-daemon", "--console=plain"]},
        }),
    "dotnet": Profile(
        image="mcr.microsoft.com/dotnet/sdk:{version}",
        commands={
            "compile": {"workdir": "/src", "argv": ["dotnet", "build"]},
            "unit":    {"workdir": "/src", "argv": ["dotnet", "test"]},
            "analyse": {"workdir": "/src", "argv": ["dotnet", "format", "--verify-no-changes"]},
        }),
    "python": Profile(
        image="python:{version}",
        commands={
            "unit":    {"workdir": "/src", "argv": ["pytest", "-q"]},
            "analyse": {"workdir": "/src", "argv": ["mypy", "."]},
        }),
}


def profile(language: str, **params: str) -> Profile:
    """The profile for a language, with its image resolved from the caller's parameters."""
    if language not in PROFILES:
        log.die(f"no toolchain profile for '{language}' - the kernel carries: "
                f"{', '.join(sorted(PROFILES))}")
        raise SystemExit(1)
    prof = PROFILES[language]
    return Profile(image=prof.image.format(**params), commands=prof.commands)
```

Note: `cpp`'s `compiler` parameter is accepted and unused in this first cut - the image string decides the compiler, and `compiler: gcc` selects a different profile key when a product asks for it. Record that in Task 6's page rather than growing the table now.

- [ ] **Step 4: Run and watch pass**

Run: `PYTHONPATH=src pytest -q tests/test_profiles.py`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add src/simplon/tasks/profiles.py tests/test_profiles.py
git commit -m "feat(#95): the language profiles, as data a test can refuse"
```

---

### Task 5: `support:toolchain` - the scaffolder

**Files:**
- Modify: `src/simplon/tasks/toolchain.py`
- Modify: `src/simplon/catalogue.yaml`
- Test: `tests/test_toolchain_scaffold.py`

**Interfaces:**
- Consumes: `profiles.profile()` from Task 4
- Produces: `scaffold(language: str, **params) -> int`

- [ ] **Step 1: Write the failing tests**

```python
"""si#95: writing a ready-made configuration into a product's manifest."""
import pytest

from simplon.tasks import toolchain


def test_scaffolding_writes_the_expanded_form_into_the_manifest(tmp_path, monkeypatch):
    # arrange
    manifest = tmp_path / "product.yaml"
    manifest.write_text("groups:\n  build:\n    commands: {}\n")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: manifest)

    # act
    toolchain.scaffold("cpp", version="19")

    # assert: the product reads its own build in its own file
    body = manifest.read_text()
    assert "toolchain:run" in body and "silkeh/clang:19" in body and "cmake" in body


def test_scaffolding_twice_changes_nothing_the_second_time(tmp_path, monkeypatch):
    # arrange
    manifest = tmp_path / "product.yaml"
    manifest.write_text("groups:\n  build:\n    commands: {}\n")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: manifest)
    toolchain.scaffold("cpp", version="19")
    once = manifest.read_text()

    # act
    toolchain.scaffold("cpp", version="19")

    # assert
    assert manifest.read_text() == once


def test_a_hand_edited_command_is_not_clobbered(tmp_path, monkeypatch, capsys):
    # arrange: a scaffolder that silently overwrites an edit is worse than none
    manifest = tmp_path / "product.yaml"
    manifest.write_text('groups:\n  build:\n    commands:\n      compile:\n'
                        '        task: "toolchain:run"\n        with: { image: "gcc:14", argv: ["make"] }\n')
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: manifest)

    # act
    toolchain.scaffold("cpp", version="19")

    # assert: the edit survives and the reader is told which command was left alone
    assert "gcc:14" in manifest.read_text()
    assert "compile" in capsys.readouterr().out
```

- [ ] **Step 2: Run and watch fail**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain_scaffold.py`
Expected: FAIL with `has no attribute 'scaffold'`

- [ ] **Step 3: Implement**

```python
def scaffold(language: str, **params: str) -> int:
    """Write a language's ready-made toolchain commands into THIS product's manifest (si#95).

    Scaffolded rather than resolved at run time, and that is the safety property: a profile read at run
    time would let a kernel bump change how a product builds - the same class as an unpinned image, one
    level up. Written into the manifest, the product owns what it runs from here on.

    Never clobbers: a command that already exists is left exactly as it is and NAMED, because a
    scaffolder that silently overwrites a hand-edited build is worse than no scaffolder.
    """
    prof = profiles.profile(language, **params)
    path = _manifest_path()
    data = yaml.safe_load(path.read_text()) or {}
    commands = data.setdefault("groups", {}).setdefault("build", {}).setdefault("commands", {})
    written, kept = [], []
    for name, body in prof.commands.items():
        if name in commands:
            kept.append(name)
            continue
        commands[name] = {"task": "toolchain:run", "with": {"image": prof.image, **body}}
        written.append(name)
    if written:
        path.write_text(yaml.safe_dump(data, sort_keys=False))
    log.ok(f"scaffolded {len(written)} command(s) for {language}: {', '.join(written) or 'none'}")
    for name in kept:
        log.info(f"kept your own `{name}` - scaffolding does not overwrite an edited command")
    return 0
```

In `catalogue.yaml`, beside `toolchain:run`:

```yaml
  support:toolchain:
    impl: simplon.tasks.toolchain:scaffold
    help: "Write a ready-made toolchain configuration for a language into this product's manifest."
    params:
      language: { help: "java | cpp | dotnet | python", argument: true }
```

- [ ] **Step 4: Run and watch pass**

Run: `PYTHONPATH=src pytest -q tests/test_toolchain_scaffold.py`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add src/simplon/tasks/toolchain.py src/simplon/catalogue.yaml tests/test_toolchain_scaffold.py
git commit -m "feat(#95): support:toolchain writes the ready-made configuration, and never clobbers"
```

---

### Task 6: the documentation the coordinates ENFORCE

**Files:**
- Modify: `site/content/building/phases.md`
- Modify: `site/content/building/rules.md`
- Modify: `site/content/using/why.md`
- Modify: `tests/test_phases_chapter.py` (its literal count, LAST)
- Create: `site/content/using/uniform-build.md`

- [ ] **Step 1: Run the suite to see exactly which pages are red**

Run: `PYTHONPATH=src pytest -q tests/test_phases_chapter.py tests/test_why_chapter.py tests/test_refusal_census.py`
Expected: FAIL. The assertions name the count and the missing coordinates - measured on 2026-09-08 with `support:ci-privileges`, seven tests went red at once.

- [ ] **Step 2: Update the pages, in this order**

1. `phases.md`: the overview table's count for `support` (+1) and for the new `toolchain` family row; the section list; the summary sentence ("Twenty-eight coordinates: ...") - read the numbers from the failure messages, never from memory.
2. `rules.md`: the catalogue size sentence.
3. `why.md`: the kinds-of-work table - `toolchain:run` and `support:toolchain` under "the machine and its services", because they drive docker.

- [ ] **Step 3: Update the test's own literal count LAST**

`tests/test_phases_chapter.py`: `assert len(listed) == N, "the count moved - update the page, then this number"` - the message states the order and it is not decoration.

- [ ] **Step 4: Write the page nothing counts**

Create `site/content/using/uniform-build.md`: the command table from the spec, what a product declares (`{ language: cpp, compiler: clang, version: "19" }`), what it gets, and the one-line scaffold path. A capability nobody can find is a capability nobody has.

- [ ] **Step 5: Run the whole suite**

Run: `PYTHONPATH=src pytest -q tests/`
Expected: PASS except the four failures and five errors that are identical on `main` without this change (wheel/py_typed need a build toolchain; the docs "run as the caller" tests fail on a root box by construction).

- [ ] **Step 6: Commit**

```bash
git add site/content tests/test_phases_chapter.py
git commit -m "docs(#95): the pages carry the two new coordinates, and then the count"
```

---

### Task 7: the release notes, which the release gate refuses to tag without

**Files:**
- Modify: `site/content/using/releases.md`

- [ ] **Step 1: Read the range**

Run: `git log --oneline <lasttag>..HEAD`
Every ticket number in those subjects must appear in the section - including numbers that only rode in on a merge subject.

- [ ] **Step 2: Write the section**

Under `## <next version>`: what a product has to do (nothing - both coordinates are declared, not placed), the command table, and the scaffold path.

- [ ] **Step 3: Verify the gate**

Run: `PYTHONPATH=src pytest -q tests/test_releases_page.py`
Expected: PASS, 8 tests. Notes BEFORE the tag - the tag has to carry them.

- [ ] **Step 4: Commit**

```bash
git add site/content/using/releases.md
git commit -m "docs(#95): the release notes for the uniform build"
```

---

## Not in this plan

- **Generating `CMakeLists.txt` / `.sln` / `.csproj`.** The spec's "What this is NOT". Separate coordinates, when a product needs them.
- **netctl's migration**, including whether its Python moves into a container. That is a plan in netctl's own repo, against a released kernel.
- **Generalising the artefact-mirror flags.** The spec's section 5 rejects it for the first cut, on the grounds that the part carrying the most special cases - "a dead proxy must never fail a gate" - should be generalised against a second case, not the first.
