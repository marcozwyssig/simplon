# `simplon init` reads the repository - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `simplon init` with no arguments at all scaffolds the repository it is standing in, under the
block path every real product uses.

**Tickets:** si#129 (the product name defaults to the repository's name), si#130 (the orchestrator block
defaults to `deploy/provision/orchestrator`).

**Spec:** `docs/superpowers/specs/2026-09-09-the-language-cluster-design.md`, section 5. This is Lane C.

**Architecture:** Both tickets change what ONE function writes and where, so they are one lane by
construction: `src/simplon/bootstrap.py`, the two launcher templates it renders, and the pages that
describe the result. Nothing else in the kernel is touched, and no catalogue coordinate is added.

**Tech Stack:** Python 3.11+, pytest, mypy. No new dependency: git is reached through
`simplon.run.run`, the repository's one subprocess seam.

## Global Constraints

- **A default, never a decree.** si#102 is the fresh counter-example: its generator derived a CMake
  target from `root.name` and got the product name wrong, because a directory is named for where it
  sits and not for what it is. A repository can be `tooling`, or a monorepo holding two products. Both
  defaults must stay fully overridable, and the override must be the same one it was.
- **A derived name is never repaired.** `my.ctl` and `Ops Tools` are refused with the fix in the
  message. Lowercasing, or turning a dot into a hyphen, produces a product whose launcher, manifest and
  `<PRODUCT>_ENV` variable are named after something nobody chose.
- **No new catalogue coordinate.** Lane D owns that space, and seven counted docs guards go red the
  moment one appears here.
- **Every counted guard is satisfied, never weakened.** The pages that show `orchestrator/` at the
  target root stop being true on the day the default moves, and they are what a first-time reader reads
  first.
- **See it red.** Every assertion below is watched failing for the right reason before the code that
  makes it pass exists.
- **A string assertion over a rendered template is not evidence that a scaffold works.** Task 6 drives
  real scaffolds and RUNS the launchers that land there.

**Before Task 1, read** `src/simplon/bootstrap.py` in full, plus `src/simplon/templates/launch.sh.j2`
and `launch.cmd.j2`. The block dir already threads through everything from one variable; the work is to
change what it defaults to, not to re-plumb it.

**Baseline, measured on `origin/main` (`7ab6fe2`) before a line was changed:**

- `./simplon.sh test all` -> `3 failed, 2560 passed, 3 skipped in 41.05s`. The three failures are
  `test_tasks_docs.py`'s uid checks; this container runs as root, which is the condition they assert
  against. They are pre-existing and unrelated to this lane.
- `./simplon.sh test typecheck-python` -> `Success: no issues found in 82 source files`.

---

### Task 1: the block dir defaults to where products actually put it (si#130)

**Files:** `src/simplon/bootstrap.py`, `tests/test_init_orch_dir.py`

**Interfaces produced:** `bootstrap.DEFAULT_ORCH_DIR = "deploy/provision/orchestrator"` (public, because
the docs guard in Task 5 and the tests both have to name it rather than retype it)

- [ ] **Step 1: Write the failing tests.** In `tests/test_init_orch_dir.py`, replace the two
  backwards-compatibility tests (`test_the_default_is_byte_identical_to_passing_it_explicitly`,
  `test_the_default_still_writes_the_root_level_block`) with tests over the new default, and add the
  one that keeps the FLAG honest.

  The second point is the one that matters and is easy to miss: today the module's "the parameter moves
  the block" tests all pass `NESTED = "deploy/provision/orchestrator"`. The moment that string becomes
  the default, every one of them is a check that cannot fail - it would pass with the parameter deleted.
  So the flag's own evidence moves to `SHORT = "orchestrator"`, the old default, which is now the
  alternative a product owning its repository root passes.

```python
#: The default since si#130: where every real product puts the block. It is the value the two
#: separator/depth tests below need anyway, so they keep using it - what they must NOT be is the only
#: evidence that `--orch-dir` does anything, which is why SHORT exists.
NESTED = bootstrap.DEFAULT_ORCH_DIR

#: The old default, and now the alternative: a product that owns its repository root passes this. It is
#: what proves the parameter still moves the block, because it is not what the default would produce.
SHORT = "orchestrator"


def test_the_default_block_dir_is_the_one_products_actually_use():
    # arrange / act
    rendered = bootstrap.render("democtl")

    # assert: no flag at all lands the block where netctl, biz-cockpit and the kernel all put it
    assert f"{NESTED}/requirements.txt" in rendered
    assert "orchestrator/requirements.txt" not in rendered


def test_the_short_form_is_still_reachable_and_still_moves_the_whole_block(tmp_path):
    # arrange / act: the mirror image of the old default - a product that owns its repo root
    written = bootstrap.write("democtl", tmp_path, orch_dir=SHORT)

    # assert
    on_disk = {p.relative_to(tmp_path).as_posix() for p in written}
    assert f"{SHORT}/requirements.txt" in on_disk
    assert not (tmp_path / "deploy").exists(), "the new default was written anyway"
    assert f'LAUNCH_ORCH_DIR="$ROOT/{SHORT}"' in (tmp_path / "democtl.sh").read_text()
    assert 'set "LAUNCH_ORCH_DIR=%LAUNCH_ROOT%\\orchestrator"' in (tmp_path / "democtl.cmd").read_text()


def test_the_default_renders_windows_separators_it_never_had_to_before(tmp_path):
    # arrange / act: the one thing si#130 names as unexercised - the cmd template backslash-converts the
    # path, and until now the DEFAULT was a single segment with no separator in it at all
    bootstrap.write("democtl", tmp_path)
    cmd = (tmp_path / "democtl.cmd").read_text()

    # assert
    assert 'set "LAUNCH_ORCH_DIR=%LAUNCH_ROOT%\\deploy\\provision\\orchestrator"' in cmd
    assert "/provision/" not in cmd, "a POSIX separator survived into the cmd shim"
```

- [ ] **Step 2: Watch them fail.** `test_the_default_block_dir_is_the_one_products_actually_use` must
  fail on `'deploy/provision/orchestrator/requirements.txt' in rendered`, not on an import error.
- [ ] **Step 3: Implement.** Rename `_ORCH_DIR` to `DEFAULT_ORCH_DIR` and give it the new value.
  Update its block comment (it currently argues why `orchestrator` is the default), the module
  docstring's line 33 paragraph, `validate_orch_dir`'s hint (the two examples swap roles), the
  `--orch-dir` help text, and the three signature defaults.
- [ ] **Step 4: Verify.** `pytest tests/test_init_orch_dir.py -q` green.
- [ ] **Step 5: Repair the tests the moved default broke, one at a time,** each seen failing first:
  `tests/test_bootstrap.py` (`_EXPECTED_FILES` and four hardcoded `tmp_path / "orchestrator"` paths),
  `tests/test_init_contract.py` (the requirements path), `tests/test_launch_cmd.py` (the LF-only set),
  `tests/test_wheel.py` (`_GENERATE_CLI` and `_MYPY_INI`, which spell `orchestrator/src/python` into a
  scaffolded product from outside). `tests/test_own_orch_block.py`'s docstring claims "the DEFAULT is
  untouched"; that sentence is now false and is corrected in place.
- [ ] **Step 6: Commit.**

**Verify:** `./simplon.sh test all` shows only the three pre-existing root-uid failures.

---

### Task 2: read the repository's name, and refuse rather than repair (si#129, the pure half)

**Files:** `src/simplon/bootstrap.py`, `tests/test_init_default_name.py` (new)

**Interfaces produced:**

```python
@dataclass(frozen=True)
class RepositoryDefault:
    name: str     # validated: a legal product slug
    source: str   # where it was read from, for the note the CLI prints
    root: Path    # the repository's working-tree root - the scaffold target a defaulted name implies

def repository_name_from_url(url: str) -> str: ...
def repository_default(start: Path) -> RepositoryDefault: ...   # raises ValueError with the fix
```

**The four decisions, each with its reason, because si#129 leaves all four open:**

1. **Which name: the `origin` remote's, falling back to the working tree's root directory.** The two
   disagree whenever somebody clones into a different folder, and the remote is the one that survives
   that: `git clone .../netctl.git myproject` makes the directory an accident of one machine while the
   remote still carries the name the product is published under. A linked git worktree is the same case
   from the other side - its basename is `agent-3f2a`, and the product is still netctl. The fallback is
   the working tree root (`git rev-parse --show-toplevel`), not `Path.cwd()`, so running from a
   subdirectory reads the repository rather than the subdirectory.
2. **Validation refuses; it never repairs.** `repository_name_from_url` parses a URL - it drops a
   trailing `/` and a trailing `.git`, which are parts of the URL and not of the name - and stops
   there. Everything after that goes through the existing `validate_product_name`, so `Ops Tools` and
   `my.ctl` are refused with the argument named as the fix. Lowercasing `Ops Tools` to `ops-tools` would
   name a launcher, a manifest, a package directory and a `OPS_TOOLS_ENV` variable after a string nobody
   chose, and it would do it silently.
3. **Outside a repository it says what it wants.** `git rev-parse` failing, and git not being on PATH at
   all, are two causes with one fix; the message names the cause and then the argument.
4. **`--dir` is decided by the same omission.** See Task 3 - the interaction is stated there because
   that is where it is implemented, but the reason belongs with the name: reading the name from the
   repository IS the statement that the repository is the product, and scaffolding a product into a
   subdirectory of itself contradicts the fact just used to name it.

- [ ] **Step 1: Write the failing tests** in `tests/test_init_default_name.py`. A real `git init` per
  case - not a stub - because what is under test is what git answers.

```python
def _repo(tmp_path, *, origin: str | None = None) -> Path: ...   # git init, optional remote add


@pytest.mark.parametrize(("url", "expected"), [
    ("https://github.com/acme/netctl.git", "netctl"),
    ("https://github.com/acme/netctl", "netctl"),
    ("https://github.com/acme/netctl/", "netctl"),
    ("git@github.com:acme/netctl.git", "netctl"),
    ("ssh://git@host:2222/acme/netctl.git", "netctl"),
    ("/srv/git/netctl.git", "netctl"),
])
def test_the_repository_name_is_parsed_out_of_every_url_shape_git_accepts(url, expected): ...

def test_the_origin_remote_wins_over_the_directory_it_was_cloned_into(tmp_path): ...
def test_a_repository_with_no_remote_falls_back_to_its_working_tree_root(tmp_path): ...
def test_the_name_is_read_from_the_repository_root_not_from_the_subdirectory_you_stand_in(tmp_path): ...
def test_a_repository_whose_name_is_not_a_legal_product_name_is_refused_with_the_argument_named(tmp_path): ...
def test_a_plain_directory_with_no_git_says_what_it_wants_and_names_the_argument(tmp_path): ...
```

  The refusal tests pin the message, because a refusal whose text is not held is a refusal that can
  quietly stop naming the fix: `"Ops Tools"` and `"simplon init <product>"` both have to be in it.

- [ ] **Step 2: Watch them fail** - `AttributeError: module 'simplon.bootstrap' has no attribute
  'repository_default'`, which is the right reason for a test written before its function.
- [ ] **Step 3: Implement** `RepositoryDefault`, `repository_name_from_url` and `repository_default`.
  git is reached through `simplon.run.run` (the house's one subprocess seam); `OSError` from a missing
  git binary is caught and turned into the same ValueError with its own cause named.
- [ ] **Step 4: Verify.** `pytest tests/test_init_default_name.py -q` green, and
  `./simplon.sh test typecheck-python` still clean - `bootstrap` is inside `mypy.ini`'s `files`.
- [ ] **Step 5: Commit.**

---

### Task 3: the argument becomes optional, and says what it decided (si#129, the CLI half)

**Files:** `src/simplon/bootstrap.py`, `tests/test_init_default_name.py`

**The `--dir` interaction, stated rather than discovered:**

| name | `--dir` | target |
|---|---|---|
| given | given | `--dir` (unchanged) |
| given | absent | `./<name>/` (unchanged) |
| **defaulted** | given | `--dir` |
| **defaulted** | absent | **the repository root** |

The last row is the only new behaviour, and it is not a second default falling out of the first by
accident. `./<repo-name>/` inside the repository the name was just read from is a directory nobody
wants: it would put the launcher one level below the manifest marker its own `paths.py` walks up to.
The name is always read from the repository the command RUNS in, never from `--dir`, so there is one
rule rather than two - and the run prints which repository it read and where the skeleton is going, so
neither half is silent.

- [ ] **Step 1: Write the failing tests.**

```python
def test_init_with_no_arguments_at_all_scaffolds_the_repository_it_stands_in(tmp_path, monkeypatch): ...
def test_the_argument_still_wins_over_the_repository(tmp_path, monkeypatch): ...
def test_an_explicit_name_still_lands_in_its_own_subdirectory(tmp_path, monkeypatch): ...
def test_a_defaulted_name_with_an_explicit_dir_uses_the_dir(tmp_path, monkeypatch): ...
def test_a_defaulted_run_says_which_name_it_read_and_where_it_is_writing(tmp_path, capsys): ...
def test_init_outside_a_repository_exits_2_with_the_fix_and_no_traceback(tmp_path, capsys): ...
def test_a_bare_simplon_with_no_argv_still_names_the_subcommand(capsys): ...
```

  The last one is a regression guard rather than a new behaviour: `main` currently prints "nothing to
  do" for an empty argv, and the whole point of si#129 is that `simplon init` with nothing after it is
  now a legal command. `simplon` bare is still not one, and the two must not be confused.

- [ ] **Step 2: Watch them fail** - argparse currently exits 2 with `the following arguments are
  required: product`.
- [ ] **Step 3: Implement.** `nargs="?"`, `default=None`, the branch above, and the note on stderr.
- [ ] **Step 4: Verify.** Full `pytest -q`.
- [ ] **Step 5: Commit.**

---

### Task 4: check the Windows render rather than assuming it

**Files:** none expected

si#130 names one thing as never exercised: "the Windows launcher template backslash-converts the path,
and a two-segment default has never been rendered there". Two things have to be said about that.

- [ ] **Step 1:** Render `launch.cmd.j2` at the new default and read the bytes, not an assertion about
  them - the `LAUNCH_ORCH_DIR`, `VENV`, `REQ`, `STAMP`, `VPY`, `VPIP`, `PYTHONPATH` and the missing-block
  diagnostic all derive from the one variable, and the `set "X=%Y%\..."` quoting has to survive a value
  with separators in it.
- [ ] **Step 2:** Record the finding in the PR either way. The expectation going in is that si#130 is
  wrong on this point: the default is THREE segments, not two, and
  `test_the_cmd_shim_spells_the_chosen_dir_with_windows_separators` has been rendering exactly
  `deploy/provision/orchestrator` through that template since si#4. If that is what the render shows,
  say so plainly instead of writing a test that pretends to have found something.

---

### Task 5: the pages show what `init` actually does

**Files:** `site/content/using/getting-started.md`, `README.md`,
`tests/test_getting_started_scaffold.py` (new)

si#130's own words: the documentation is not wrong, it just "leads with a shape nobody runs, so a reader
learns the layout twice". Both pages carry the same two claims - the tree under "What it writes", and
the paragraph that calls the block "a parameter, not a decree" while showing the long form as the
exception.

- [ ] **Step 1: Write the failing guard** in a NEW file rather than in `test_site_counts.py`. The new
  file is deliberate: Lane D edits the counted-coordinate guards in that module, and a lane that adds a
  test to a file another lane is rewriting buys a conflict for nothing.

```python
def test_the_page_lists_exactly_the_files_a_scaffold_writes(): ...
def test_the_page_counts_them_with_the_number_the_scaffold_produces(): ...
def test_no_page_still_shows_the_block_at_the_target_root(): ...
```

  The third is the one with teeth: `getting-started.md` and `README.md` are swept for
  `orchestrator/requirements.txt` and `orchestrator/src/python` not prefixed by the default's parent -
  the same sweep `test_own_orch_block.py` runs over this repository's own configuration, pointed at the
  two pages that describe somebody else's.

- [ ] **Step 2: Watch it fail** on the un-updated pages, naming the stale lines.
- [ ] **Step 3: Edit both pages.**
  - the tree, and the `orchestrator/src/python/orchestrator/cli.py` the sample `build` output prints;
  - the flag's paragraph, flipped: the long form is what `init` writes, and the SHORT form is what a
    product owning its repository root passes. This is si#130's open question, and the answer is yes -
    the mirror image is the honest text once the default moves, and leaving it as it stands would be
    the "learns the layout twice" defect pointing the other way;
  - a short paragraph for si#129: the argument is optional, what it defaults to, and the `--dir`
    interaction from Task 3's table. `--dir .` stays in the shown command, because the page teaches the
    explicit form first and the reader who is NOT in a repository named after the product needs it.
- [ ] **Step 4: Verify.** The new guard green, `./simplon.sh test all` at the baseline.
- [ ] **Step 5: Commit.**

---

### Task 6: drive it, and run what lands

**Files:** none - this is evidence, and it goes in the PR body

Design section 6: an assertion about a variable is not evidence that a scaffold works. The failure this
guards against is exact and cheap to imagine: a generated `myctl.sh` whose venv path lost a segment
fails at its first invocation, and every string assertion about the template still passes.

- [ ] **Step 1:** A real git repository, `git init` + `git remote add origin
  https://github.com/acme/labctl.git`, no arguments at all: `simplon init`. Confirm the name came from
  the remote, the skeleton landed at the repository ROOT, and the block is under
  `deploy/provision/orchestrator`.
- [ ] **Step 2:** RUN `./labctl.sh help` from that repository. It provisions its own venv, installs
  `simplon==<released pin>` from PyPI and execs `python -m orchestrator`. Capture the transcript.
- [ ] **Step 3:** RUN `./labctl.sh build` and `./labctl.sh dev build` - the second must be the refusal,
  rc 1, because it exercises the assembled dispatch rather than just the import.
- [ ] **Step 4:** A repository with NO remote, cloned into a differently named directory, to take the
  fallback in a case where the two answers actually differ.
- [ ] **Step 5:** A plain directory with no `.git`: confirm rc 2, the message, the named argument, and
  that nothing was written.
- [ ] **Step 6:** A repository whose name is not a legal slug, by clone into `Ops Tools`: confirm the
  refusal names both the bad name and the argument.
- [ ] **Step 7:** The argument still winning: `simplon init otherctl` inside the `labctl` repository
  lands in `./otherctl/`, and its launcher runs from there too.
- [ ] **Step 8:** The short form: `simplon init myctl --dir . --orch-dir orchestrator` in a fresh
  repository, and run ITS launcher - the alternative the documentation now offers has to work, or the
  page is offering something nobody tried.

---

### Task 7: review and land

- [ ] **Step 1:** `./simplon.sh test all` and `./simplon.sh test typecheck-python`, compared against the
  baseline recorded above rather than against a number quoted from memory.
- [ ] **Step 2:** Dispatch `python-reviewer` on the diff; act on what it finds.
- [ ] **Step 3:** One PR against `main`, no labels, not merged.
