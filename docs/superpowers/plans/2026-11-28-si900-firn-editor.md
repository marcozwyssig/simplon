# si#900 firn editor provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With `toolchains: [firn]`, `support install` installs firn's VS Code extension, provides a language server runtime (`local` binary or `docker` script) and writes `<product>.code-workspace`, all at the pinned firn version.

**Architecture:** A new adapter `simplon/adapters/firnrelease.py` owns every read of firn's private GitHub Release (pin, asset list, checked download). A new task module `simplon/tasks/firneditor.py` owns the three gates (extension, runtime, workspace) and the remembered runtime choice; `hosttools.install` calls it after the existing gates. The `firn_runtime` parameter enters through the firn catalogue model.

**Tech Stack:** Python 3.12, PyGithub (via `simplon.adapters.github`), `simplon.adapters.fetch`, pytest, firn (`./simplon.sh build model`).

**Spec:** `docs/superpowers/specs/2026-11-27-si900-firn-editor-design.md`

## Global Constraints

- The pin is the tag of the `ghcr.io/marcozwyssig/firn` image the manifest's commands run (`firn-builder` images do not count). One distinct tag; none or several is a diagnosis naming the commands and tags.
- firn's assets: `firn-<tag>.vsix`, `firn-<tag>-<os>-<arch>` (today `linux-amd64`, `linux-arm64`), each with `<name>.sha256`. Repository `marcozwyssig/firn`, private.
- Token: `githubpackages.token()` (environment first, then `gh auth token`). Three outcomes kept apart: no token; release unreadable with the token (never worded "not published"); release read but asset missing (names tag and asset).
- No silent runtime: when the release cannot be read and no flag or stored value decides, the runtime gate is red with that reason; it never falls to `docker`.
- Runtime values exactly `local` and `docker`. Stored in `${XDG_CONFIG_HOME:-~/.config}/simplon/firn-runtime`, one value for the host. A flag stores its value. Every run says the runtime and its source: `flag`, `stored`, or `default (<why>)`.
- Default: `local` when the release carries `firn-<tag>-<os>-<arch>` for this host, else `docker`.
- Docker route: stdio only. Script `build/tools/bin/firn-docker`: `exec docker run -i --rm -u <uid>:<gid> -v <root>:<root> -w <root> <image> "$@"`, every value `shlex.quote`d. Never mount at `/workspace`.
- Workspace `<product>.code-workspace` at the product root: `folders` from `firn-workspace.toml` `projects`, else the model commands' project folder (their `cwd`, default the root); `settings` `firn.mode = "stdio"`, `firn.binary` relative to the product root. Rewritten every run; not git-ignored is a FAILED gate naming the line `/<product>.code-workspace`.
- Container route and CI (`hostinstall.machine_skip_reason`): all three gates SKIPPED, no release read.
- Every new refusal gets a census entry; `with-what/rules.md` counts follow the census test, never typed.
- No em dash anywhere. Artefacts in English. Commits with `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env, ending with the Co-Authored-By and Claude-Session lines.

## Review Focus

1. A private asset download is answered with a redirect to GitHub's object storage; forwarding `Authorization` there gets a 400. Expect the download to work: the token goes as an unredirected header (Task 1 test).
2. A stored runtime file that is empty, has trailing junk or an unknown word: a diagnosis naming the file, not the default (Task 2 test).
3. A product root containing a space or a quote: the docker script still mounts exactly that path (Task 3 test).
4. `code` on PATH but `code --list-extensions --show-versions` fails or times out: FAILED "could not ask", never an install over it (Task 4 test).
5. `firn-workspace.toml` naming a folder that does not exist: the workspace gate FAILED naming it, not a silently shorter workspace (Task 5 test).

---

### Task 1: Reading firn's release

**Files:**
- Create: `src/simplon/adapters/firnrelease.py`
- Modify: `src/simplon/adapters/fetch.py` (`download` gains `headers`, `_request` sends them unredirected)
- Test: `src/tests/test_firnrelease.py`, `src/tests/test_fetch.py` (existing file if present, else new)

**Interfaces:**
- Produces:
  - `FIRN_REPO = "marcozwyssig/firn"`, `FIRN_IMAGE = "ghcr.io/marcozwyssig/firn"`
  - `class NoToken(Exception)`, `class ReleaseUnreadable(Exception)`, `class AssetMissing(Exception)`, `class ChecksumMismatch(Exception)`; each message is the sentence the gate prints.
  - `pinned_tag(data: Mapping[str, object], source: str) -> str` (raises `ValueError`)
  - `@dataclass(frozen=True) class Release: tag: str; assets: Mapping[str, GitReleaseAsset]`
  - `read(tag: str) -> Release` (raises `NoToken`, `ReleaseUnreadable`)
  - `host_binary_name(tag: str, system: str | None = None, machine: str | None = None) -> str | None`
  - `fetch_checked(release: Release, name: str, dest: Path) -> Path` (raises `AssetMissing`, `ChecksumMismatch`, `ReleaseUnreadable` for a failed transfer)
  - `fetch.download(..., headers: Mapping[str, str] | None = None)`

- [ ] **Step 1: Write the failing tests**

```python
def test_pinned_tag_is_the_one_firn_image_tag():
    data = {"commands": {"test": {"model": {"task": "test:model", "with": {"image": "ghcr.io/marcozwyssig/firn:v0.19.0"}}},
                         "build": {"model": {"task": "build:model", "with": {"image": "ghcr.io/marcozwyssig/firn:v0.19.0@sha256:" + "a" * 64}},
                                   "model-binary": {"task": "build:model-binary", "with": {"image": "ghcr.io/marcozwyssig/firn-builder:v0.18.0"}}}}}
    assert firnrelease.pinned_tag(data, "x.yaml") == "v0.19.0"

def test_pinned_tag_refuses_two_tags_naming_both():
    # test model on v0.19.0, build model on v0.18.0
    with pytest.raises(ValueError, match=r"v0\.18\.0.*v0\.19\.0|v0\.19\.0.*v0\.18\.0"): ...

def test_pinned_tag_refuses_no_firn_image():
    with pytest.raises(ValueError, match="no command runs ghcr.io/marcozwyssig/firn"): ...

def test_host_binary_name_maps_machine():
    assert firnrelease.host_binary_name("v0.19.0", "Linux", "x86_64") == "firn-v0.19.0-linux-amd64"
    assert firnrelease.host_binary_name("v0.19.0", "Linux", "aarch64") == "firn-v0.19.0-linux-arm64"
    assert firnrelease.host_binary_name("v0.19.0", "Darwin", "arm64") == "firn-v0.19.0-darwin-arm64"
    assert firnrelease.host_binary_name("v0.19.0", "Linux", "riscv64") is None

def test_read_without_token_is_no_token(monkeypatch):      # githubpackages.token raises PackageError
    with pytest.raises(firnrelease.NoToken): firnrelease.read("v0.19.0")

def test_read_repository_404_is_unreadable_not_unpublished(monkeypatch):   # github.other raises Unanswered
    with pytest.raises(firnrelease.ReleaseUnreadable) as caught: firnrelease.read("v0.19.0")
    assert "not published" not in str(caught.value) and "v0.19.0" in str(caught.value)

def test_read_missing_tag_is_unreadable_naming_the_tag(monkeypatch):      # github.published returns None
    with pytest.raises(firnrelease.ReleaseUnreadable, match="v0.19.0"): ...

def test_fetch_checked_names_a_missing_asset_and_its_tag(tmp_path):
    with pytest.raises(firnrelease.AssetMissing, match=r"v0\.19\.0.*firn-v0\.19\.0\.vsix"): ...

def test_fetch_checked_refuses_a_missing_sha256_asset(tmp_path):
    with pytest.raises(firnrelease.AssetMissing, match=r"firn-v0\.19\.0\.vsix\.sha256"): ...

def test_fetch_checked_refuses_a_wrong_sha_and_leaves_no_file(tmp_path):
    with pytest.raises(firnrelease.ChecksumMismatch): ...
    assert not (tmp_path / "firn-v0.19.0.vsix").exists()

def test_download_sends_headers_unredirected():                 # Review Focus 1
    request = fetch._request("https://api.github.com/x", 0, "", headers={"Authorization": "token t"})
    assert request.unredirected_hdrs.get("Authorization") == "token t"
    assert "Authorization" not in request.headers
```

- [ ] **Step 2: Run them, expect FAIL** (`deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_firnrelease.py src/tests/test_fetch.py -q`): module and parameter missing.

- [ ] **Step 3: Implement.** `pinned_tag` walks every command's `with: image:` (nested groups as the manifest nests them; reuse an existing walker if `manifest`/`profiles` has one), keeps images whose repository is exactly `FIRN_IMAGE`, strips a `@sha256:` digest, and takes the tag. `read` gets the token via `githubpackages.token()` (wrap `PackageError` in `NoToken`), the repository via `github.other(FIRN_REPO, token)` (wrap `Unanswered` in `ReleaseUnreadable`), the release via `github.published` (None means unreadable: "could not read release <tag> of marcozwyssig/firn"), assets via `github.assets`. `fetch_checked` downloads `<name>.sha256` and `<name>` through the asset's API URL (`asset.url`) with `Accept: application/octet-stream` and `Authorization: token <t>` as headers, compares with `checksum.sha256_of`, writes to `dest` only when it matches. `fetch._request` adds every given header with `add_unredirected_header`.

- [ ] **Step 4: Run the tests, expect PASS.**

- [ ] **Step 5: See it red once against the real release.** With a token, call `read("v0.19.0")` and `fetch_checked(..., "firn-v0.19.0.vsix", tmp)` from a scratch script; it must succeed. Then corrupt the expected sha in the script and confirm `ChecksumMismatch`. Record both outputs in the task report.

- [ ] **Step 6: Commit** `feat(si#900): read firn's private release: pin, assets, checked download`.

### Task 2: The remembered runtime choice

**Files:**
- Create: `src/simplon/tasks/firneditor.py`
- Test: `src/tests/test_firneditor.py`

**Interfaces:**
- Consumes: `firnrelease.Release`, `firnrelease.host_binary_name`, the exceptions of Task 1.
- Produces:
  - `RUNTIMES = ("local", "docker")`
  - `runtime_file(env: Mapping[str, str] | None = None) -> Path`
  - `@dataclass(frozen=True) class Choice: runtime: str; source: str` (`source` is `"flag"`, `"stored"` or `"default (<why>)"`)
  - `choose_runtime(flag: str, release_of: Callable[[], firnrelease.Release], env: Mapping[str, str] | None = None) -> Choice` (raises `ValueError` for an invalid flag or stored value; lets `NoToken`/`ReleaseUnreadable` through only when the default is needed)

- [ ] **Step 1: Write the failing tests**

```python
def test_runtime_file_honours_xdg(tmp_path):
    assert firneditor.runtime_file({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "simplon" / "firn-runtime"

def test_flag_wins_and_is_stored(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert firneditor.choose_runtime("docker", _never, env) == firneditor.Choice("docker", "flag")
    assert (tmp_path / "simplon" / "firn-runtime").read_text() == "docker\n"

def test_stored_value_is_used_without_reading_the_release(tmp_path):   # _never raises if called
    assert firneditor.choose_runtime("", _never, env).source == "stored"

def test_default_local_when_the_release_has_this_hosts_binary(tmp_path, monkeypatch):
    choice = firneditor.choose_runtime("", lambda: _release_with("firn-v0.19.0-linux-amd64"), env)
    assert choice.runtime == "local" and choice.source.startswith("default (")
    assert not runtime_file(env).exists()            # a default is not stored

def test_default_docker_when_no_binary_for_this_host(...):
    assert choice.runtime == "docker" and "firn-v0.19.0-linux-amd64" in choice.source

def test_unreadable_release_gives_no_default(...):
    with pytest.raises(firnrelease.ReleaseUnreadable): firneditor.choose_runtime("", _unreadable, env)

@pytest.mark.parametrize("text", ["", "\n", "dockers\n", "local\nextra\n", "LOCAL\n"])
def test_a_bad_stored_value_names_the_file(tmp_path, text):           # Review Focus 2
    with pytest.raises(ValueError, match=re.escape(str(runtime_file(env)))): ...

def test_a_bad_flag_names_the_two_values():
    with pytest.raises(ValueError, match="local.*docker"): firneditor.choose_runtime("podman", _never, env)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `runtime_file` and `choose_runtime` as the tests pin them. The stored file holds exactly one of `RUNTIMES` and a trailing newline; anything else is the `ValueError`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(si#900): the firn runtime, chosen by flag, remembered per host, defaulted from the release`.

### Task 3: The two runtimes

**Files:**
- Modify: `src/simplon/tasks/firneditor.py`
- Test: `src/tests/test_firneditor.py`

**Interfaces:**
- Consumes: `Choice`, `firnrelease.read`/`fetch_checked`/`host_binary_name`, `tools.bin_dir()`, `hostinstall.Outcome`/`State`.
- Produces:
  - `docker_script(root: Path, image: str, uid: int, gid: int) -> str` (the script text)
  - `runtime_gate(choice: Choice, tag: str, release_of: Callable[[], firnrelease.Release], root: Path) -> tuple[hostinstall.Outcome, Path | None]`; the path is the `firn.binary` target (absolute), None when the gate did not leave one.

- [ ] **Step 1: Write the failing tests**

```python
def test_docker_script_mounts_the_host_path_quoted(tmp_path):          # Review Focus 3
    root = tmp_path / "my 'odd' tree"
    text = firneditor.docker_script(root, "ghcr.io/marcozwyssig/firn:v0.19.0", 1000, 1000)
    assert text.startswith("#!/bin/sh\n")
    argv = shlex.split(text.splitlines()[-1])
    assert argv[:4] == ["exec", "docker", "run", "-i"]
    assert argv[argv.index("-v") + 1] == f"{root}:{root}" and argv[argv.index("-w") + 1] == str(root)
    assert argv[-2:] == ["ghcr.io/marcozwyssig/firn:v0.19.0", "$@"] and "/workspace" not in text

def test_local_present_at_the_tag_is_nothing_to_do(tmp_path):          # no release read
    outcome, binary = firneditor.runtime_gate(Choice("local", "stored"), "v0.19.0", _never, tmp_path)
    assert outcome.state is State.PRESENT and binary.name == "firn-v0.19.0-linux-amd64"

def test_local_downloads_checked_and_executable(tmp_path): ...          # State.INSTALLED, mode & 0o111

def test_local_without_a_binary_for_this_host_fails_naming_it(tmp_path): ...   # State.FAILED

def test_docker_without_a_running_docker_fails(tmp_path, monkeypatch):  # hostinstall.runs("docker") False
    assert outcome.state is State.FAILED and "docker" in outcome.detail

def test_docker_rewrites_the_script_when_the_pin_changed(tmp_path): ... # INSTALLED, then PRESENT on rerun
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Binary path: `tools.bin_dir() / host_binary_name(tag)`, mode 0755. Script path: `tools.bin_dir() / "firn-docker"`, mode 0755, written only when its text differs (PRESENT otherwise). Image: `f"{firnrelease.FIRN_IMAGE}:{tag}"`; uid/gid from `os.getuid()`/`os.getgid()`. Each exception of Task 1 becomes `Outcome(State.FAILED, str(exc))`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(si#900): the local and docker runtimes of the firn language server`.

### Task 4: The extension gate

**Files:**
- Modify: `src/simplon/tasks/firneditor.py`
- Test: `src/tests/test_firneditor.py`

**Interfaces:**
- Consumes: `firnrelease`, `hostinstall`, `simplon.kernel.run`.
- Produces: `extension_gate(tag: str, release_of: Callable[[], firnrelease.Release], scratch: Path) -> hostinstall.Outcome`; `EXTENSION_ID = "zwyssig.firn"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_code_on_path_fails_and_says_so(...):        # State.FAILED, "code" and "PATH" in detail
def test_installed_at_the_tag_is_present(...):          # list prints "zwyssig.firn@0.19.0"; release never read
def test_other_version_installs_the_checked_vsix(...):  # list prints "zwyssig.firn@0.18.0"; argv has --install-extension <path> --force
def test_unanswering_code_is_could_not_ask(...):        # Review Focus 4: list rc != 0 or timeout -> FAILED "could not ask", no install run
def test_release_without_vsix_names_tag_and_asset(...): # AssetMissing -> FAILED naming firn-v0.19.0.vsix
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Version compare: `tag.removeprefix("v")` against the `@<version>` of `EXTENSION_ID` in `code --list-extensions --show-versions`. Bound every `code` call with a timeout from `simplon.kernel.limits` (add one if none fits). The `.vsix` goes to `scratch` (a temp dir the caller removes).
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(si#900): install firn's VS Code extension at the pinned version`.

### Task 5: The workspace gate

**Files:**
- Modify: `src/simplon/tasks/firneditor.py`
- Test: `src/tests/test_firneditor.py`

**Interfaces:**
- Produces:
  - `projects(root: Path, data: Mapping[str, object]) -> list[str]` (relative POSIX paths; raises `ValueError` naming a listed folder that does not exist)
  - `java_projects(root: Path, projects: list[str]) -> list[str]`: a project counts when its folder holds a `*.java` file outside its `build/` (measured on cleon-firn: 18 of 53); a folder that cannot be walked raises `OSError`, never counts as "none".
  - `workspace_gate(root: Path, product: str, binary: Path, data: Mapping[str, object]) -> hostinstall.Outcome`

- [ ] **Step 1: Write the failing tests**

```python
def test_folders_come_from_firn_workspace_toml(tmp_path): ...      # order as listed
def test_without_firn_workspace_toml_the_model_cwd_is_the_folder(tmp_path): ...   # cwd "src" -> ["src"]; no cwd -> ["."]
def test_a_listed_folder_that_does_not_exist_is_named(tmp_path):   # Review Focus 5
    with pytest.raises(ValueError, match="src/firn/gone"): ...
def test_workspace_json_carries_mode_and_relative_binary(tmp_path):
    ws = json.loads((tmp_path / "p.code-workspace").read_text())
    assert ws["settings"] == {"firn.mode": "stdio", "firn.binary": "build/tools/bin/firn-v0.19.0-linux-amd64"}
def test_not_git_ignored_fails_naming_the_line(tmp_path): ...      # git init, no ignore -> FAILED, "/p.code-workspace" in detail
def test_java_projects_are_named_in_the_outcome(tmp_path): ...     # detail names the project and firn#1460
def test_java_files_under_build_do_not_count(tmp_path): ...
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Write with `json.dumps(..., indent=2) + "\n"`; INSTALLED when the text changed, PRESENT when equal. Ignore check: `git check-ignore -q <file>` in `root`; rc 1 is FAILED naming the line, rc 128 is FAILED "could not ask git". Java projects go in the outcome detail as "the editor uses the stock firn for: <list> (their own binary needs firn#1460)"; this is not a failure.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(si#900): write the product's firn code-workspace`.

### Task 6: Wiring, parameter, docs, census

**Files:**
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (`support_install` gains `params p_firn_runtime`, help updated), then regenerate with `./simplon.sh build model` (updates `src/simplon/catalogue.yaml`, `src/simplon/tasks/support_install.py`, and whatever else firn reports)
- Modify: `src/simplon/tasks/hosttools.py` (`install(firn_runtime: str = "") -> int` calls `firneditor.editor`)
- Modify: `src/simplon/tasks/firneditor.py` (`editor(container: bool, flag: str, declared: tuple[str, ...]) -> bool`)
- Modify: `.gitignore` (`/simplon.code-workspace`)
- Modify: the site page that lists `support install`'s gates (find it under `src/site/content/`), `src/site/content/with-what/rules.md` via the census test
- Test: `src/tests/test_tasks_hosttools.py`, `src/tests/test_refusal_census.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `support install --firn-runtime local|docker`.

- [ ] **Step 1: Write the failing tests** in `test_tasks_hosttools.py`:

```python
def test_firn_not_declared_says_nothing_and_reads_nothing(...)
def test_container_route_skips_all_three_firn_gates_without_reading(...)   # three SKIPPED lines, release_of never called
def test_ci_skips_all_three_firn_gates(...)
def test_a_failing_firn_gate_fails_install_but_every_gate_runs(...)
def test_the_run_names_runtime_and_source(...)                              # "firn runtime: docker (flag)"
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** `editor` reads the release at most once (memoised `release_of`), skips per `hostinstall.machine_skip_reason(os.environ, container, "editor tools")`, runs extension, runtime, workspace in that order, and runs the workspace gate only when the runtime gate left a binary path (otherwise reports the workspace as not written, naming why). The catalogue param: `key = "firn_runtime"`, help `"how the editor reaches firn's language server: local (the binary) or docker (the image); remembered per host"`. The task help drops "today oras".
- [ ] **Step 4: Regenerate and check:** `./simplon.sh build model`, then `./simplon.sh support github workflows --check` and the full suite (`deploy/orchestrator/.venv/bin/python -m pytest src/tests -q -x -n auto`; three `test_tasks_docs` failures are root-bound and pre-existing). Add census entries for every refusal the census test reports, with its kind (all diagnoses), and let it update `rules.md`.
- [ ] **Step 5: Commit** `feat(si#900): support install provisions the firn editor`.

### Task 7: Acceptance on real hosts

Not code; a measured report in the task report file and later on #900.

- [ ] **Step 1:** In a scratch clone of `marcozwyssig/cleon-firn`, run the branch's kernel `support install` (local route). Expect: extension FAILED with "no code on PATH" if `code` is absent (seen red), binary INSTALLED, workspace INSTALLED naming 18 Java projects. Second run: every gate PRESENT.
- [ ] **Step 2:** Drive the generated `firn.binary` with the LSP probe from the spec's spike (`initialize`, `didOpen` of a broken file, diagnostics with host URIs). Repeat with `--firn-runtime docker` through `build/tools/bin/firn-docker`.
- [ ] **Step 3:** Seen red: no token (`GITHUB_TOKEN=` and no gh login in a clean env), a pin whose release has no `.vsix` (`v0.18.0`), the workspace not git-ignored.
- [ ] **Step 4:** If `code` is not on this host, stop and ask Marco before installing VS Code; the extension install itself is then measured on a host that has it.
