# Generating CMakeLists and Solution files - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two coordinates that write a product's `CMakeLists.txt` files, and its `.sln`/`.csproj` files, from its source tree.

**Architecture:** A pure reader turns a directory tree into a typed model; pure renderers turn that model into text; a thin task writes the text. Nothing that decides needs a filesystem twice, and nothing that renders needs one at all - the same split `tasks/image.py` and `tasks/toolchain.py` already use.

**Tech Stack:** Python 3.11+, pytest, mypy. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-generating-build-files-design.md`

## Global Constraints

- Generated files are COMMITTED, so the output must be byte-identical between runs. Sort everything; a directory listing is not an order.
- GUIDs come from `uuid.uuid5` over a fixed namespace and the project path relative to the product root. Never `uuid4`.
- Every generated file carries the two-sentence `DO NOT EDIT` header from the spec's section 3.
- The generator ALWAYS overwrites. This is deliberately not `support:toolchain`'s never-clobber rule; the spec says why.
- The tree is the declaration; `targets:` in the manifest carries only what a directory cannot show, which is dependencies.
- Both coordinates are DECLARED, not placed.
- A new coordinate turns the counted docs pages red. Task 6 is not optional.

**Before Task 1, read** `src/simplon/tasks/toolchain.py` and `src/simplon/tasks/image.py` in full. They are the shape this follows: a typed config, a validator that refuses by name, pure assembly, a thin executor. Do not invent a different one.

---

### Task 1: read the tree into a model

**Files:** Create `src/simplon/tasks/buildfiles.py`, `tests/test_buildfiles_tree.py`

**Interfaces produced:** `Target(name: str, kind: str, directory: Path, sources: list[Path], depends: list[str], include: list[str])` with `kind` in `{"library", "executable", "test"}`; `read_tree(root: Path, overrides: Mapping[str, Mapping]) -> list[Target]`

- [ ] **Step 1: Write the failing tests**

```python
"""si#102: the source tree read as the declaration it is."""
from pathlib import Path

from simplon.tasks import buildfiles


def _tree(tmp_path, *paths):
    for rel in paths:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// x\n")
    return tmp_path


def test_a_source_directory_without_a_main_is_a_library(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/core/a.cpp", "src/core/b.cpp")

    # act
    targets = buildfiles.read_tree(root, {})

    # assert
    assert [(t.name, t.kind) for t in targets] == [("core", "library")]


def test_a_directory_holding_main_is_an_executable(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/app/main.cpp")

    # act / assert
    assert [(t.name, t.kind) for t in buildfiles.read_tree(root, {})] == [("app", "executable")]


def test_a_test_directory_becomes_test_targets(tmp_path):
    # arrange
    root = _tree(tmp_path, "src/core/a.cpp", "tests/core_test.cpp")

    # act
    kinds = {t.name: t.kind for t in buildfiles.read_tree(root, {})}

    # assert
    assert kinds == {"core": "library", "core_test": "test"}


def test_sources_are_sorted_so_two_runs_agree(tmp_path):
    # arrange: a directory listing is not an order, and the output is committed
    root = _tree(tmp_path, "src/core/z.cpp", "src/core/a.cpp", "src/core/m.cpp")

    # act
    target = buildfiles.read_tree(root, {})[0]

    # assert
    assert [p.name for p in target.sources] == ["a.cpp", "m.cpp", "z.cpp"]


def test_a_dependency_the_tree_cannot_show_comes_from_the_manifest(tmp_path):
    # arrange: the ONE thing a directory does not say
    root = _tree(tmp_path, "src/core/a.cpp", "src/net/b.cpp")

    # act
    targets = {t.name: t for t in buildfiles.read_tree(root, {"net": {"depends": ["core"]}})}

    # assert
    assert targets["net"].depends == ["core"]
    assert targets["core"].depends == []


def test_a_dependency_is_never_invented(tmp_path):
    # arrange: guessing from include paths was rejected - it fails at link time, in a message about
    # symbols rather than about the manifest
    root = _tree(tmp_path, "src/core/a.cpp", "src/net/b.cpp")

    # act / assert
    assert all(t.depends == [] for t in buildfiles.read_tree(root, {}))


def test_an_override_naming_no_target_is_refused_by_name(tmp_path, monkeypatch):
    # arrange
    monkeypatch.setattr(buildfiles.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    root = _tree(tmp_path, "src/core/a.cpp")

    # act / assert: a typo in `targets:` is silent otherwise, and silently does nothing
    import pytest
    with pytest.raises(RuntimeError) as e:
        buildfiles.read_tree(root, {"nett": {"depends": ["core"]}})
    assert "nett" in str(e.value) and "core" in str(e.value)
```

- [ ] **Step 2: Run and watch every one fail**

`PYTHONPATH=src pytest -q tests/test_buildfiles_tree.py` - expect `cannot import name 'buildfiles'`.

- [ ] **Step 3: Implement `read_tree` and the dataclass**

Minimal, and sorted at every level. `src/<name>/` with any `.cpp`/`.cc`/`.cxx` is a target; the presence of `main.cpp` makes it an executable; `tests/*_test.cpp` each become a `test` target named after the file stem. Refuse an override key that names no target, listing the targets that exist.

- [ ] **Step 4: Run and watch them pass. Step 5: Commit.**

```bash
git add src/simplon/tasks/buildfiles.py tests/test_buildfiles_tree.py
git commit -m "feat(si#102): the source tree read as a declaration, and the one thing it cannot say"
```

---

### Task 2: render CMake, purely

**Files:** Modify `src/simplon/tasks/buildfiles.py`, create `tests/test_buildfiles_cmake.py`

**Interfaces produced:** `HEADER: str`; `render_cmake(targets: list[Target], directory: Path) -> str`; `cmake_files(targets: list[Target], root: Path) -> dict[Path, str]`

- [ ] **Step 1: Write the failing tests**

Assert, each as its own test: the root file carries `cmake_minimum_required`, `project(...)` and one `add_subdirectory` per target directory, sorted; a library directory's file carries `add_library(core ...)` with its sources sorted; an executable's carries `add_executable`; a target with `depends: [core]` carries `target_link_libraries(net PRIVATE core)`; a test target carries `add_test`; **every returned file starts with `HEADER`**; and rendering the same targets twice returns equal strings.

- [ ] **Step 2: Run, watch fail. Step 3: Implement. Step 4: Run, watch pass.**

Pure: `render_cmake` takes the model and returns text. It touches no filesystem, which is what lets every assertion above be a string comparison.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(si#102): CMake rendered from the model, purely and in a fixed order"
```

---

### Task 3: render the .NET solution, with derived GUIDs

**Files:** Modify `src/simplon/tasks/buildfiles.py`, create `tests/test_buildfiles_dotnet.py`

**Interfaces produced:** `project_guid(project_path: str) -> str`; `dotnet_files(targets: list[Target], root: Path, product: str) -> dict[Path, str]`

- [ ] **Step 1: Write the failing tests, and this one FIRST**

```python
def test_a_guid_is_derived_from_the_path_so_two_runs_agree():
    # arrange / act
    a = buildfiles.project_guid("src/Core/Core.csproj")
    b = buildfiles.project_guid("src/Core/Core.csproj")
    other = buildfiles.project_guid("src/Net/Net.csproj")

    # assert: uuid4 here would put a new GUID in the diff on every run, and the committed decision
    # (spec section 4) would be unusable within a week
    assert a == b
    assert a != other
    assert a == a.upper() and a.count("-") == 4
```

Then: a `.csproj` per target directory; one `.sln` naming every project, sorted; a `depends:` becoming a `ProjectReference`; the configuration matrix rows sorted; the header on every file; and generating twice byte-identical.

- [ ] **Step 2-4: red, implement, green.** `uuid.uuid5` over a namespace constant defined in the module and the path. Microsoft's project TYPE GUIDs are quoted as the fixed constants they are, with a comment saying so.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(si#102): the solution rendered with GUIDs derived from the path, never generated"
```

---

### Task 4: the two tasks, and the coordinates

**Files:** Modify `src/simplon/tasks/buildfiles.py`, `src/simplon/catalogue.yaml`, create `tests/test_buildfiles_write.py`

**Interfaces produced:** `cmake(...) -> int`, `dotnet(...) -> int`

- [ ] **Step 1: Write the failing tests**

Files land where the model says; a hand-edited file IS replaced (the opposite of si#101, and the spec says why); the run reports which files it wrote; the manifest's `build: targets:` block reaches `read_tree`; and a product whose tree yields no target is refused rather than writing an empty project.

- [ ] **Step 2-4: red, implement, green.**

Read how `run_toolchain` binds its `with:` keys to parameters before writing the signature - si#105 is the ticket where that went wrong, and the same mistake here costs the same day. Declare both coordinates in `tasks:` only.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(si#102): build:cmake-files and build:dotnet-solution write what the model says"
```

---

### Task 5: the end-to-end proof

**Files:** create `tests/test_buildfiles_e2e.py` (or a documented manual run if docker is unavailable in the suite)

- [ ] **Step 1: Drive it.** Scaffold a product with `simplon init` into a tmp directory, point its requirements at this checkout, write two source directories and a test, run `build cmake-files`, then run `build configure` and `build compile` through `toolchain:run`, and execute the binary.

- [ ] **Step 2: Paste the transcript into the commit and the PR.**

**This task is the reason 0.9.0 exists.** simplon 0.8.0 shipped a uniform build that no product could drive, because every test behind it stubbed `run`. A generator whose output does not compile is not tested, and no number of string assertions in Tasks 2 and 3 says otherwise.

- [ ] **Step 3: Commit**

```bash
git commit -m "test(si#102): the generated tree compiles, driven rather than asserted"
```

---

### Task 6: the documentation the coordinates ENFORCE

**Files:** `site/content/building/phases.md`, `site/content/building/rules.md`, `site/content/using/why.md`, `tests/test_phases_chapter.py`, and the two case chapters

- [ ] **Step 1: Run the suite and let the assertions name the numbers.** They will: the `build` count, the section list, the summary sentence, the catalogue size, the kinds-of-work table.

- [ ] **Step 2: Update the pages FIRST, the test's literal LAST.** Their messages say so, and it is not decoration.

- [ ] **Step 3: The two case chapters.** `case-cpp.md` and `case-dotnet.md` each carry a step labelled `does not exist yet` pointing at si#102. Those steps now exist - move them to `run`, and RUN them to get the output. Their suites assert the ratio sentence against their own tables.

- [ ] **Step 4: Commit**

```bash
git commit -m "docs(si#102): the pages carry the two coordinates, and the case chapters lose a gap"
```

---

### Task 7: the release notes

- [ ] Write the section BEFORE the tag, name every ticket in `git log --oneline <lasttag>..HEAD`, and remember that a merge GitHub composed is read from the commits it brought in - so name the ticket in the COMMIT, not only in the pull request title (si#103).

---

## Not in this plan

Per-configuration compiler flags, install rules, packaging, custom build steps, code generators, multi-targeting, NuGet package references beyond project references. The spec's section 5 lists them with the reason: each needs a product behind it, and the escape hatch for a product that outgrows the table is to not place the coordinate.
