# si#564 support:docker-preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One context-aware docker socket resolver in the kernel. All three socket callers use it, each with its guard. A new `support:docker-preflight` task is green when docker answers, and with `editor: devcontainer` it warns with the one VS Code setting that makes the Dev Containers extension find it.

**Architecture:** `adapters/host.py` gains `context_endpoint()` (I/O, environment injectable). `docker_socket_path()` stays pure and gains an injected `endpoint`. `docker._socket_path()`, `Host.probe` and `labhost.ensure_colima_vm` pass the endpoint through their guards. The task body is a new module over the resolver. It is registered as every catalogue task is: `catalogue.yaml`, `tasks.firn`, then `./simplon.sh build model`.

**Tech Stack:** Python 3.12, pytest, the docker CLI (`docker context inspect`), firn model generation.

**Spec:** `docs/superpowers/specs/2026-11-03-si564-docker-preflight-design.md` (and si#564's first comment, which records the extension's code as measured).

## Global Constraints

- No `sudo`, no symlink, no write to editor configuration in any code path or message.
- A context docker cannot be asked about is "could not ask" (`None`), never "default".
- The editor check resolves with `DOCKER_HOST` and `DOCKER_CONTEXT` removed from the environment.
- macOS lab paths accept a context endpoint only when it is a Colima profile socket `~/.colima/<profile>/docker.sock`.
- `_grant_socket_access` chmods only `/var/run/docker.sock` or an explicit `unix://` `DOCKER_HOST`.
- `editor` is a plain string. `devcontainer` and absent are valid; anything else is refused at run time. No new manifest feature.
- No em dash (U+2014). Artefacts in English. Every new assertion is seen red first.
- Commits: env identity `Marco Zwyssig <marco@zwyssig.info>`, quoted heredoc, trailers `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG`.
- Test commands:
  - single files: `cd src && ../deploy/orchestrator/.venv/bin/python -m pytest <files> -q`;
  - gates: `./simplon.sh test typecheck-python`, `git add -A && ./simplon.sh test generated`, `./simplon.sh test release-notes`;
  - full: `./simplon.sh test suite`.

## Review Focus

1. **A daemon that answers on a context while `docker context inspect` fails** (an old CLI, or a broken `~/.docker/config.json`). Expected: green, with a warning that the context could not be named and no editor advice. The editor advice must never be derived from a guess.
2. **A Mac whose active context is `default`, with Docker Desktop answering while Colima is dead.** Expected: the lab probe pings the Colima socket and stays `UNREACHABLE`. It is not `SOCKET_ONLY`.
3. **A rootless docker on Linux** (`unix:///run/user/1000/docker.sock` named only by the context), with the daemon unreachable in bootstrap mode. Expected: the die message names that socket, and no `chmod 666` or `setfacl` runs on it.
4. **`DOCKER_HOST` exported in the shell** with the default context socket missing. Expected: the terminal part is green, and the editor part warns that VS Code does not see `DOCKER_HOST` and names a context or a host setting.
5. **A context endpoint that is tcp:// or ssh://.** Expected: `docker_socket_path` returns `""`, and no message prints a file path for it.

---

### Task 1: The resolver in `adapters/host.py`

**Files:**
- Modify: `src/simplon/adapters/host.py` (beside `docker_socket_path`, line ~71)
- Test: `src/tests/test_host.py` (beside the `docker_socket_path` tests, line ~171)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class DockerContext: name: str; endpoint: str` (endpoint as docker prints it, e.g. `unix:///x.sock`, `tcp://h:2375`).
  - `context_endpoint(environ: Mapping[str, str] | None = None) -> DockerContext | None`. It runs `docker context inspect --format '{{.Name}}|{{.Endpoints.docker.Host}}'` with `environ` as the full process environment (`os.environ` when None). It returns `None` when docker is not on PATH, exits non-zero, or prints no `|`-separated pair.
  - `docker_socket_path(*, darwin: bool, environ: dict | None = None, endpoint: str | None = None) -> str`. Order: a `unix://` DOCKER_HOST; a non-unix DOCKER_HOST gives `""`; then a `unix://` endpoint; a non-unix endpoint gives `""`; then Colima on darwin; then `DEFAULT_SOCKET`.
  - `is_colima_socket(path: str) -> bool`: True if `path`, after `expanduser`, matches `~/.colima/<profile>/docker.sock` for any profile.
  - `without_docker_overrides(environ: Mapping[str, str] | None = None) -> dict[str, str]`: a copy without `DOCKER_HOST` or `DOCKER_CONTEXT`.

- [ ] **Step 1: Write the failing tests** in `test_host.py`:
  - `test_docker_socket_path_takes_a_unix_endpoint_after_docker_host`: `endpoint="unix:///ctx.sock"`, `environ={}` → `"/ctx.sock"` (darwin True and False); with `environ={"DOCKER_HOST": "unix:///dh.sock"}` → `"/dh.sock"`.
  - `test_docker_socket_path_is_empty_for_a_non_unix_endpoint`: `endpoint="tcp://h:2375"` → `""`.
  - `test_docker_socket_path_without_endpoint_keeps_the_old_order`: `endpoint=None` → today's Colima/default values (reuse the existing expectations).
  - `test_is_colima_socket`: `~/.colima/default/docker.sock` and `~/.colima/work/docker.sock` → True; `/var/run/docker.sock`, `~/.docker/run/docker.sock`, `~/.colima/default/other.sock` → False.
  - `test_context_endpoint_reads_name_and_endpoint`: a `docker` script on a tmp PATH that prints `colima|unix:///c.sock` → `DockerContext("colima", "unix:///c.sock")`.
  - `test_context_endpoint_is_none_when_docker_cannot_say`: the script exits 1 → `None`; empty output → `None`; no docker on PATH → `None`.
  - `test_context_endpoint_runs_in_the_environment_it_is_given`: the script prints `$DOCKER_HOST`. Calling with `without_docker_overrides({"PATH": ..., "DOCKER_HOST": "unix:///x"})` → the script sees it unset.

  The stub is a real executable (`#!/bin/sh`) put on PATH through the passed environment, not a monkeypatched `run`.
- [ ] **Step 2: Run them.** `cd src && ../deploy/orchestrator/.venv/bin/python -m pytest tests/test_host.py -q`. Expected: FAIL (`endpoint` unexpected keyword / missing names).
- [ ] **Step 3: Implement** the five names above in `host.py`. `context_endpoint` uses `simplon.kernel.run.run` with the given environment if `run` accepts one; otherwise `subprocess.run(..., env=...)`, check `run`'s signature first. Update the module docstring line that says host.py is the only module that knows Colima (`labhost` starts the VM).
- [ ] **Step 4: Run them.** Same command. Expected: PASS, including every old `docker_socket_path` test.
- [ ] **Step 5: Commit** `feat(si#564): a docker socket resolver that asks the active context`.

### Task 2: The three callers and their guards

**Files:**
- Modify: `src/simplon/adapters/docker.py:445-475` (`_socket_path`, `_socket_state`), `:150-175` (`_grant_socket_access`), `:212-214`
- Modify: `src/simplon/adapters/host.py:161-176` (`Host.probe`)
- Modify: `src/simplon/adapters/labhost.py:290`
- Test: `src/tests/test_docker.py`, `src/tests/test_host.py`, `src/tests/test_labhost.py`

**Interfaces:**
- Consumes: Task 1's `context_endpoint`, `docker_socket_path(endpoint=)`, `is_colima_socket`.
- Produces:
  - `docker._socket_path() -> Path | None`, now context-aware. Without `DOCKER_HOST` it uses `context_endpoint()`, and `None` for a non-unix endpoint.
  - `docker._chmod_target() -> Path | None`. The path `_grant_socket_access` may touch: `/var/run/docker.sock`, or an explicit `unix://` DOCKER_HOST path. `None` otherwise.
  - `host.lab_socket_path(*, darwin: bool, environ=None) -> str`. On darwin it takes the context endpoint only if `is_colima_socket`. On Linux it takes any unix endpoint. With `None` it keeps the old order. `Host.probe` and `labhost` both call it.

- [ ] **Step 1: Write the failing tests.**
  - `test_docker.py::test_socket_state_names_the_socket_the_context_names`: no DOCKER_HOST, a stub docker printing `rootless|unix://<tmp>/docker.sock` on PATH, the file absent → `_socket_state()` names `<tmp>/docker.sock` and `NOT MOUNTED`.
  - `test_docker.py::test_a_socket_named_only_by_the_context_is_never_chmodded`: same stub, the socket exists and is unwritable. Record the argv of `run`, then call `_grant_socket_access(["sudo"])`. No `setfacl` or `chmod` argv names that path, and a warning or the returned state names it.
  - `test_docker.py::test_the_system_socket_and_an_explicit_docker_host_are_still_chmodded`: `_chmod_target()` gives `/var/run/docker.sock` without DOCKER_HOST (stub context `default|unix:///var/run/docker.sock`), and the DOCKER_HOST path when set.
  - `test_host.py::test_the_lab_ignores_a_non_colima_context_on_darwin`: stub context `desktop-linux|unix:///Users/x/.docker/run/docker.sock` → `lab_socket_path(darwin=True, environ=...)` is the Colima default socket.
  - `test_host.py::test_the_lab_takes_another_colima_profile_from_the_context`: stub `colima-work|unix://<home>/.colima/work/docker.sock` → that path.
  - `test_host.py::test_the_lab_without_a_context_keeps_the_old_order`: the stub exits 1 → the old value.
  - `test_labhost.py`: the existing `ensure_colima_vm` tests stay green. Add one where `socket_answers` is asked about `lab_socket_path` (monkeypatch `host_mod.lab_socket_path`, assert it is consulted).
- [ ] **Step 2: Run them.** `cd src && ../deploy/orchestrator/.venv/bin/python -m pytest tests/test_docker.py tests/test_host.py tests/test_labhost.py -q`. Expected: the new ones FAIL.
- [ ] **Step 3: Implement.**
  - `_socket_path` delegates to `host.docker_socket_path(darwin=False, endpoint=...)`, with the endpoint from `context_endpoint()`, and keeps its `Path | None` contract.
  - `_grant_socket_access` uses `_chmod_target()`. When the resolved socket differs from that target, it chmods nothing and `log.warn`s, naming the socket and saying why it is not touched.
  - `Host.probe` calls `lab_socket_path` only on the socket branch (after `docker ps` failed). `labhost:290` uses `lab_socket_path(darwin=True)`.
- [ ] **Step 4: Run them.** Same command. Expected: PASS, with all existing tests in the three files green.
- [ ] **Step 5: Commit** `feat(si#564): the bootstrap, the lab probe and labhost resolve through the context, each guarded`.

### Task 3: `support:docker-preflight`

**Files:**
- Modify: `src/simplon/catalogue.yaml` (support section, after `support:ci-disk-cleanup`)
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (beside `support_ci_disk_preflight`, line ~382)
- Create: `src/simplon/tasks/dockerpreflight.py`
- Generated: `./simplon.sh build model` (task class, `artifactschema.py`, architecture files, completions)
- Test: create `src/tests/test_docker_preflight.py`; update the pinned lists that go red (expected: `test_phases_chapter.py` 67→68, `test_coordinate_placement.py`, the `support` namespace list in `test_catalogue.py`, `PUBLISH_READS` in `test_catalogue_publishes_and_token.py`; find the rest with the suite, as si#487 did)

**Interfaces:**
- Consumes: `host.context_endpoint`, `host.without_docker_overrides`, `host.DockerContext`.
- Produces: `dockerpreflight.preflight(editor: str = "") -> int`, coordinate `support:docker-preflight`, `unattended: true`, param `editor` (help: "`devcontainer` also checks that VS Code's Dev Containers extension will find docker."; metavar `EDITOR`).

- [ ] **Step 1: Write the failing tests** in `test_docker_preflight.py`. Every test puts a stub `docker` script on PATH via `monkeypatch.setenv("PATH", ...)`. The stub answers `version` and `context inspect` from files the test writes. The module docstring says: "no host in CI has Colima; the stub is a real process, and what it cannot show is the extension itself."
  - `test_no_docker_on_path_is_red`: message has "install docker".
  - `test_a_daemon_that_does_not_answer_is_red_with_its_own_lines`: the stub `version` exits 1 with `Cannot connect` → rc 1, the line quoted, `docker context ls` named.
  - `test_docker_answers_is_green_and_names_context_and_endpoint`: rc 0, `colima` and the endpoint in the output.
  - `test_a_context_docker_cannot_name_warns_and_stays_green`: `context inspect` exits 1 → rc 0, "could not" in the output, no `docker.context` advice.
  - `test_without_editor_nothing_is_said_about_the_editor`: no `docker.context` or `Dev Containers` in the output.
  - `test_editor_on_a_non_default_context_names_the_setting`: `editor="devcontainer"`, context `colima` → rc 0, `"docker.context": "colima"` in the output.
  - `test_editor_on_default_with_its_socket_is_quiet_ok`: context `default`, the endpoint `unix://<tmp file that exists>` → rc 0, no warning.
  - `test_editor_on_default_without_its_socket_names_a_context_that_answers`: the editor view (no overrides) gives `default|unix://<missing>`, the terminal view gives `colima|...` → `"docker.context": "colima"`.
  - `test_editor_sees_what_vscode_sees_not_the_shell`: `DOCKER_HOST` is set in the test environment, and the stub echoes whether it saw `DOCKER_HOST`. The editor resolution runs without it, and the output says VS Code does not see `DOCKER_HOST`.
  - `test_an_unknown_editor_is_refused_with_the_known_values`: `editor="vim"` → rc 1, `devcontainer` named.
  - `test_no_message_says_sudo_or_ln`: over every scenario above, `sudo` and `ln -s` never appear.
  - `test_windows_is_not_checked_and_says_so`: monkeypatch `os.name` → "nt"; editor check skipped with "not checked".
- [ ] **Step 2: Run them.** `cd src && ../deploy/orchestrator/.venv/bin/python -m pytest tests/test_docker_preflight.py -q`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `dockerpreflight.preflight` following the spec's table, in order: check 1, check 2, check 3, then check 4. The module docstring carries the spec's "What the extension really does" facts in short, with the version (0.471.0) they were read from.
- [ ] **Step 4: Register.** Add the catalogue entry (with a comment citing si#564 and the extension facts) and the `tasks.firn` instance (`key = "support:docker-preflight"`, `body = "simplon.tasks.dockerpreflight:preflight"`). Then run `./simplon.sh build model`.
- [ ] **Step 5: Run.** The new file plus `tests/test_catalogue_ports.py tests/test_catalogue.py tests/test_refusal_census.py tests/test_phases_chapter.py tests/test_coordinate_placement.py`. Expected: the new tests PASS. Pinned counts fail with their numbers. Update each pin to the computed value, never a guessed one.
- [ ] **Step 6: Gates.** Run `./simplon.sh test typecheck-python` and `git add -A && ./simplon.sh test generated`. Expected: both OK.
- [ ] **Step 7: Commit** `feat(si#564): support:docker-preflight - docker found from the active context, the editor told one setting`.

### Task 4: Docs and the whole suite

**Files:**
- Modify: `src/site/content/with-what/phases.md` (the coordinate, and the computed count sentence)
- Modify: `src/site/content/when/releases.md` (0.37.0: a `### ` section for si#564)
- Modify: `src/site/content/with-what/rules.md` only if the census numbers moved (computed)

- [ ] **Step 1: Write the docs.**
  - The notes section says what the task does.
  - It gives the resolver's new order and the two guards.
  - It says firn moves `deploy preflight` to `support docker-preflight` at its bump.
  - It names `"docker.context"` as the way out for VS Code, read from the extension 0.471.0's code and not run on a Mac.
- [ ] **Step 2: Run** `./simplon.sh test release-notes` and `cd src && ../deploy/orchestrator/.venv/bin/python -m pytest tests/test_phases_chapter.py tests/test_tasks_docs.py -q`. Expected: OK (the 3 root-bound `test_tasks_docs` failures are pre-existing, see memory).
- [ ] **Step 3: Full suite.** `./simplon.sh test suite > <workspace>/suite.log 2>&1`, then read the tail. Expected: all pass except known flakes (si#503 container e2e: rerun alone).
- [ ] **Step 4: Commit** `docs(si#564): the docker preflight on the phases page and in the 0.37.0 notes`.
