# si#511 toolchain mounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `toolchain:run` bind-mounts tree paths (`mounts:`, and a `Toolchain.mounts` field), creating every mount point as the caller first, over one public helper `adapters.hostpath.mount_argv` that `test:image` shares (si#495).

**Architecture:** The helper is pure: it validates, translates and spells one `-v`. `toolchain.declared` parses `mounts:` into `Mount` values, `docker_argv` (still pure) places them after the cache volumes, and `toolchain.invocation` makes the mount points exist, owned by the caller, before the line runs. `tasks.image._mount_argv` delegates to the helper and keeps its own messages.

**Tech Stack:** Python 3.12, pytest, docker CLI.

**Spec:** `docs/superpowers/specs/2026-10-18-si511-toolchain-mounts-design.md`

## Global Constraints

- Python: `deploy/orchestrator/.venv/bin/python`; the suite serially via `./simplon.sh test suite` (about 3-5 min); docs only via `./simplon.sh build docs`.
- An empty `mounts` changes the `docker_argv` line by not one byte.
- Entry form: `<source>:<target>` or `<source>:<target>:ro`; anything else after the target is refused.
- Refusals in `toolchain` are `log.die(...)` then `raise SystemExit(1)`, naming `where`, and they are run time, so there is no census entry. `mount_argv` raises `ValueError`.
- A mount source outside the tree (absolute or climbing) is never accepted. No root-owned directory is left in the tree. Every source goes through `hostpath.translate`.
- Commits: quoted heredoc, env identity `Marco Zwyssig <marco@zwyssig.info>` for author and committer, and the trailer lines from the session.

## Review Focus

1. A target spelled with a trailing slash or `..` (`/work/`, `/work/src/../`) must still count as the workdir or its ancestor and be refused. Normalise with `posixpath.normpath` before comparing (Task 2 test).
2. A source that is a FILE, not a directory, under `must_exist=False`: `invocation` must not `mkdir` over it. Refuse it with the mount message (Task 3 test).
3. Two entries with the same target: docker refuses `Duplicate mount point` at run time, after the kernel has already created directories. Refuse it in `declared` (Task 2 test).
4. A Windows-style source (`C:\x`, or `src\node_modules`) must be refused, not split on the drive colon. `validate_relative_dir` already refuses `\` (Task 2 test).
5. A target under the workdir whose host counterpart's parent is root-owned: refused before any `mkdir`, with no traceback (Task 3 test).

---

### Task 1: `hostpath.mount_argv`, and `test:image` on top of it

**Files:**
- Modify: `src/simplon/adapters/hostpath.py` (add `mount_argv`)
- Modify: `src/simplon/tasks/image.py:770-794` (`_mount_argv` delegates)
- Test: `src/tests/test_hostpath.py`; `src/tests/test_tasks_image.py` (unchanged, must stay green)

**Interfaces:**
- Produces: `mount_argv(root: Path, source: str, target: str, *, readonly: bool = False, must_exist: bool = True) -> list[str]`. Returns `["-v", f"{translate(root / source)}:{target}" + (":ro" if readonly else "")]`. It raises `ValueError` when the target is not absolute, when the source is absolute, climbs (`..`) or holds `\`, and, under `must_exist=True`, when `root / source` is not a directory. A source of `.` means the root.

- [ ] **Step 1: Write the failing tests** in `test_hostpath.py`:
  - `test_mount_argv_spells_one_translated_bind`: `tmp_path/"a"` exists; `mount_argv(tmp_path, "a", "/x")` → `["-v", f"{hostpath.translate(tmp_path/'a')}:/x"]`.
  - `test_mount_argv_keeps_readonly`: ends with `":/x:ro"`.
  - `test_mount_argv_allows_the_root_as_dot`: `"."` → the source is `translate(tmp_path)`.
  - `test_mount_argv_refuses_what_leaves_the_tree`, parametrized over `"/etc"`, `"../sib"`, `"a/../../x"`, `"a\\b"`: `pytest.raises(ValueError)`.
  - `test_mount_argv_refuses_a_relative_target`: `target="x"` → ValueError.
  - `test_mount_argv_refuses_a_missing_source_only_when_asked`: `"nope"` raises with the default, and returns a line with `must_exist=False`.
- [ ] **Step 2: Run** `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_hostpath.py -k mount_argv`. Expected: FAIL, `AttributeError: ... no attribute 'mount_argv'`.
- [ ] **Step 3: Implement `mount_argv`.** For the source rule, reuse `manifest.layout.validate_relative_dir` (layering allows adapters to use manifest), with `"."`/`"./"` short-circuited to the root the way `image._inside_the_product` does. The docstring states the contract: arguments, `ValueError`, the si#201 translation, `must_exist`, and that it creates nothing.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Make `image._mount_argv` delegate.** Keep its partition, its `_inside_the_product` call and its three `log.error` messages exactly. Replace only the final `["-v", ...]` with `hostpath.mount_argv(root, inside, target)`, converting a `ValueError` to `log.error(str(e)); return None`.
- [ ] **Step 6: Run** `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_tasks_image.py src/tests/test_hostpath.py src/tests/test_hostpath_mounts.py`. Expected: PASS, with no test edited in `test_tasks_image.py`.
- [ ] **Step 7: Commit** `feat(si#495): adapters.hostpath.mount_argv - one public bind-mount helper, and test:image on it`.

### Task 2: `mounts:` parsed, and placed in the line

**Files:**
- Modify: `src/simplon/tasks/toolchain.py` (`Mount`, the `Toolchain.mounts` field, `_mounts`, `declared`, `docker_argv`, `run_toolchain`, `invocation` signature)
- Modify: `src/simplon/catalogue.yaml:854-877` (`toolchain:run` `params:` gains `mounts`)
- Test: `src/tests/test_toolchain.py`

**Interfaces:**
- Consumes: `hostpath.mount_argv(..., must_exist=False)` from Task 1.
- Produces:
  - `@dataclass(frozen=True) class Mount: source: str; target: str; readonly: bool = False`.
  - `Toolchain.mounts: list[Mount] = field(default_factory=list)`, added LAST so positional construction keeps its meaning.
  - `run_toolchain(..., mounts: list[str] | None = None, ...)` and `invocation(..., mounts: object = None, ...)`. Add these as keywords, with `run_toolchain`'s new parameter placed before `extra`.

- [ ] **Step 1: Write the failing tests** in `test_toolchain.py`, using `_cfg(mounts=[...])`:
  - `test_no_mounts_leaves_the_line_byte_for_byte`: `docker_argv(_cfg())` equals `docker_argv(_cfg(mounts=[]))`, and the line contains no `-v` other than the tree's.
  - `test_a_mount_sits_after_the_caches_and_before_the_image`: with a cache and `["build/nm:/work/src/frontend/node_modules"]`, the index of the mount's `-v` is greater than the cache's and less than `line.index(cfg.image)`. The value is `f"{hostpath.translate(Path('/repo')/'build/nm')}:/work/src/frontend/node_modules"`.
  - `test_a_readonly_mount_keeps_ro`: `"fixtures:/data:ro"` → the value ends with `":/data:ro"`.
  - `test_a_bad_mount_is_refused_by_name`, parametrized over `"nocolon"`, `"src:rel"`, `"/abs:/x"`, `"../sib:/x"`, `"src\\nm:/x"`, `"src:/x:rw"`, `"src:/work"`, `"src:/work/"`, `"src:/"`, `"src:/work/a/.."`: with `log.die` monkeypatched to `_boom`, `pytest.raises(RuntimeError)`, and the message contains `"build.compile"` and the entry. Pin the exact text of one entry against the real message once it is written.
  - `test_two_mounts_on_one_target_are_refused`.
  - `test_mounts_must_be_a_list_of_strings`: `mounts="a:/b"` and `mounts=[{"a": 1}]` are refused.
  - `test_a_toolchain_built_positionally_still_means_what_it_did`: `toolchain.Toolchain("img:1", ["x"], "/work", {}, [], "")` has `mounts == []`.
- [ ] **Step 2: Run** `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_toolchain.py`. Expected: the new tests FAIL (unexpected keyword or missing attribute), and the old ones pass.
- [ ] **Step 3: Implement.**
  - `_mounts(raw: object, where: str, workdir: str) -> list[Mount]`, beside `_caches`. A target is compared after `posixpath.normpath`, and is refused when it equals the workdir or is an ancestor of it.
  - `declared` passes `body.get("mounts")` and the workdir.
  - `docker_argv` appends `hostpath.mount_argv(root, m.source, m.target, readonly=m.readonly, must_exist=False)` for each mount, after `*volumes`.
  - `run_toolchain` and `invocation` thread `mounts` into the `declared` body.
  - The catalogue's `mounts:` help reads: "bind mounts `<path under the tree>:<absolute container path>[:ro]`; each path is created as the calling user before the run".
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Run** `./simplon.sh test generated`. If it names stale files (the catalogue feeds generated classes, the firn model, completions and the command reference), regenerate with the command it prints, `./simplon.sh build model` for the task classes, and `./simplon.sh support manifest model src/firn/model/product/simplon/simplon.firn` for the firn model. Then re-run. Expected: OK. The staleness gate passes only after the commit, so check it again after Step 6.
- [ ] **Step 6: Commit** `feat(si#511): mounts: on toolchain:run - parsed, refused by name, placed before the image`.

### Task 3: mount points exist, owned by the caller, before the run

**Files:**
- Modify: `src/simplon/tasks/toolchain.py` (`invocation`, plus a new `_prepare_mounts`)
- Test: `src/tests/test_toolchain.py`, and a docker e2e test in `src/tests/test_toolchain_mounts_e2e.py` (new; `needs_docker` as in `test_toolchain_firn_e2e.py`)

**Interfaces:**
- Consumes: `Toolchain.mounts` from Task 2.
- Produces: `_prepare_mounts(cfg: Toolchain, root: Path) -> str`, which returns a fault message or `""`. It creates `root/source`, and `root/<target relative to workdir>` when the normalised target lies under `cfg.workdir`. `invocation` calls it after `outputs.ensure_home()` and before `docker.ownership_fault`. A non-empty result goes to `log.error` and returns `None`, the same path an ownership fault takes.

- [ ] **Step 1: Write the failing tests** with real directories in `tmp_path`:
  - `test_the_source_and_the_inner_target_are_created_before_the_run`: mount `build/nm:/work/src/frontend/node_modules` → both `tmp_path/"build/nm"` and `tmp_path/"src/frontend/node_modules"` are directories afterwards, owned by `os.getuid()`.
  - `test_a_target_outside_the_workdir_creates_nothing_on_the_host`: `build/nm:/cache/nm` → only `build/nm` is created, and no `cache` directory appears.
  - `test_a_source_that_is_a_file_is_refused`: `tmp_path/"build/nm"` is a file → the result names it, and nothing is created.
  - `test_a_path_owned_by_someone_else_is_refused_before_any_mkdir`: skip unless root (`os.geteuid() == 0`). `os.chown` a pre-made `tmp_path/"src"` to 4242, mount `x:/work/src/frontend/node_modules` → the result names `src` and uid 4242, and `tmp_path/"x"` was NOT created, because the check comes first.
  - `test_invocation_returns_none_on_a_mount_fault`: through `invocation` with the context set as in `test_the_refusal_names_the_command_the_block_was_read_from`.
  - e2e `test_a_non_root_container_writes_through_a_mount_and_leaves_no_root_owned_dir`: `docker_argv` with `--user` of the caller (or 4242 when root, with the tree chowned to it), `busybox:1.37` (pinned by digest as other e2e tests pin), argv `["sh", "-c", "touch /work/src/frontend/node_modules/ok"]`, after `_prepare_mounts`. It asserts rc 0, that `tmp_path/"build/nm/ok"` exists, and that `os.walk(tmp_path)` finds no entry with `st_uid == 0` unless the test runs as root.
- [ ] **Step 2: Run** `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_toolchain.py src/tests/test_toolchain_mounts_e2e.py`. Expected: the new tests FAIL (no `_prepare_mounts`), and the e2e test FAILS on `Permission denied` or a root-owned dir.
- [ ] **Step 3: Implement `_prepare_mounts`.** For each path to create, take the path, or its nearest existing ancestor when it is missing (but never above `root`). Refuse when that ancestor is not owned by `os.getuid()` (skip the check where `os.getuid` is absent), or when the path exists and is not a directory. Do all the checks first, then the `mkdir(parents=True, exist_ok=True)` calls. Message: `f"{where}: mount '{entry}' needs {rel} owned by uid {uid}; it is owned by uid {owner}. Remove it or chown it (it takes a root shell), then run this again."`. Pin the real text in the test once it is written.
- [ ] **Step 4: Run** the same command. Expected: PASS. See the e2e test fail first by commenting out the `_prepare_mounts` call, then restore it.
- [ ] **Step 5: Commit** `feat(si#511): mount points exist before the run, owned by the caller, or the run is refused`.

### Task 4: docs, then the whole suite

**Files:**
- Modify: `src/site/content/with-what/phases.md` § toolchain (545-630): a `mounts:` paragraph after `caches:`, covering the key, the entry form, the creation rule with the measured docker behaviour (root:root 755), and `mounts:` as the working alternative to `caches:` for a non-root uid.
- Modify: `src/site/content/how/manifest.md` near line 1266: one sentence plus a pointer.

- [ ] **Step 1:** Write both docs edits. Quote no error text that is not pinned against its real message.
- [ ] **Step 2: Run** `./simplon.sh build docs`. Expected: `OK docs`.
- [ ] **Step 3: Run** `./simplon.sh test suite` serially, with the output to a file. Expected: all green. A failure in `test_launch_container_lifecycle_e2e` on a docker daemon error is si#503: rerun that file alone and report it, never hide it.
- [ ] **Step 4: Run** `./simplon.sh test generated` and `./simplon.sh test typecheck-python`. Expected: OK.
- [ ] **Step 5: Commit** `docs(si#511): mounts: on the toolchain page and the manifest page`.

## After the tasks

A final whole-branch review on the most capable model. Then push, and open the PR with `Closes #511` and `Closes #495`. In the PR body, say that the refusals are run time and so not in the census. After the release, tell biz-cockpit (si#511) and firn (si#495).
