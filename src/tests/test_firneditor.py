"""si#900: the firn runtime of `support install` is chosen by flag, remembered per host, and defaulted from the
release only when nothing was said before. AAA; the name states the behaviour under test."""
import json
import re
import subprocess
import shlex
from types import SimpleNamespace

import pytest

from simplon.adapters import firnrelease, hostinstall, tools
from simplon.adapters.hostinstall import State
from simplon.kernel import limits
from simplon.kernel.run import Result
from simplon.tasks import firneditor
from simplon.tasks.firneditor import Choice

TAG = "v0.19.0"
HOST_BINARY = f"firn-{TAG}-linux-amd64"


def _never():
    raise AssertionError("the release must not be read")


def _unreadable():
    raise firnrelease.ReleaseUnreadable("no release")


def _no_token():
    raise firnrelease.NoToken("no token")


def _release_with(*names):
    return firnrelease.Release(TAG, {name: SimpleNamespace(name=name) for name in names})


@pytest.fixture
def env(tmp_path):
    return {"XDG_CONFIG_HOME": str(tmp_path)}


@pytest.fixture(autouse=True)
def pinned_host(monkeypatch):
    monkeypatch.setattr(firnrelease, "host_binary_name", lambda tag, system=None, machine=None: f"firn-{tag}-linux-amd64")


def test_runtime_file_honours_xdg(tmp_path):
    assert firneditor.runtime_file({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "simplon" / "firn-runtime"


def test_runtime_file_falls_back_to_home_config(tmp_path):
    assert firneditor.runtime_file({"HOME": str(tmp_path)}) == tmp_path / ".config" / "simplon" / "firn-runtime"


def test_flag_wins_and_is_stored(env, tmp_path):
    assert firneditor.choose_runtime("docker", _never, env) == firneditor.Choice("docker", "flag")
    assert (tmp_path / "simplon" / "firn-runtime").read_text() == "docker\n"


def test_flag_replaces_a_stored_value(env):
    firneditor.choose_runtime("docker", _never, env)
    firneditor.choose_runtime("local", _never, env)
    assert firneditor.runtime_file(env).read_text() == "local\n"


def test_stored_value_is_used_without_reading_the_release(env):
    firneditor.choose_runtime("local", _never, env)
    assert firneditor.choose_runtime("", _never, env) == firneditor.Choice("local", "stored")


def test_default_local_when_the_release_has_this_hosts_binary(env):
    choice = firneditor.choose_runtime("", lambda: _release_with(HOST_BINARY), env)
    assert choice.runtime == "local" and choice.source.startswith("default (")
    assert not firneditor.runtime_file(env).exists()


def test_default_docker_when_no_binary_for_this_host(env):
    choice = firneditor.choose_runtime("", lambda: _release_with("firn-v0.19.0-darwin-arm64"), env)
    assert choice.runtime == "docker" and HOST_BINARY in choice.source
    assert not firneditor.runtime_file(env).exists()


def test_default_docker_when_firn_names_no_binary_for_the_host(env, monkeypatch):
    monkeypatch.setattr(firnrelease, "host_binary_name", lambda tag, system=None, machine=None: None)
    choice = firneditor.choose_runtime("", lambda: _release_with(HOST_BINARY), env)
    assert choice.runtime == "docker" and choice.source.startswith("default (")


def test_unreadable_release_gives_no_default(env):
    with pytest.raises(firnrelease.ReleaseUnreadable):
        firneditor.choose_runtime("", _unreadable, env)
    assert not firneditor.runtime_file(env).exists()


def test_missing_token_gives_no_default(env):
    with pytest.raises(firnrelease.NoToken):
        firneditor.choose_runtime("", _no_token, env)


@pytest.mark.parametrize("text", ["", "\n", "dockers\n", "local\nextra\n", "LOCAL\n", "local"])
def test_a_bad_stored_value_names_the_file(env, text):
    path = firneditor.runtime_file(env)
    path.parent.mkdir(parents=True)
    path.write_text(text)
    with pytest.raises(ValueError, match=re.escape(str(path))):
        firneditor.choose_runtime("", _never, env)


def test_a_bad_flag_names_the_two_values(env):
    with pytest.raises(ValueError, match="local.*docker"):
        firneditor.choose_runtime("podman", _never, env)
    assert not firneditor.runtime_file(env).exists()


def test_a_directory_at_the_runtime_path_is_not_nothing_stored(env):
    path = firneditor.runtime_file(env)
    path.mkdir(parents=True)
    with pytest.raises(ValueError, match=re.escape(str(path))):
        firneditor.choose_runtime("", _never, env)


def test_a_dangling_symlink_at_the_runtime_path_is_not_nothing_stored(env):
    path = firneditor.runtime_file(env)
    path.parent.mkdir(parents=True)
    path.symlink_to(path.parent / "missing")
    with pytest.raises(ValueError, match=re.escape(str(path))):
        firneditor.choose_runtime("", _never, env)


def test_a_file_that_is_not_utf8_names_the_file(env):
    path = firneditor.runtime_file(env)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match=re.escape(str(path))):
        firneditor.choose_runtime("", _never, env)


def test_no_binary_for_this_os_or_arch_says_so_and_that_docker_is_the_default(env, monkeypatch):
    monkeypatch.setattr(firnrelease, "host_binary_name", lambda tag, system=None, machine=None: None)
    choice = firneditor.choose_runtime("", lambda: _release_with(HOST_BINARY), env)
    assert "no firn binary exists for this OS and architecture" in choice.source and "docker" in choice.source


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    path = tmp_path / "bin"
    monkeypatch.setattr(tools, "bin_dir", lambda: path)
    return path


def test_docker_script_mounts_the_host_path_quoted(tmp_path):
    root = tmp_path / "my 'odd' tree"
    text = firneditor.docker_script(root, "ghcr.io/marcozwyssig/firn:v0.19.0", 1000, 1000)
    assert text.startswith("#!/bin/sh\n")
    argv = shlex.split(text.splitlines()[-1])
    assert argv[:4] == ["exec", "docker", "run", "-i"]
    assert argv[argv.index("-v") + 1] == f"{root}:{root}" and argv[argv.index("-w") + 1] == str(root)
    assert argv[-2:] == ["ghcr.io/marcozwyssig/firn:v0.19.0", "$@"] and "/workspace" not in text


def test_local_present_at_the_tag_is_nothing_to_do(tmp_path, bin_dir):
    bin_dir.mkdir()
    (bin_dir / HOST_BINARY).write_text("x")
    (bin_dir / HOST_BINARY).chmod(0o755)
    outcome, binary = firneditor.runtime_gate(Choice("local", "stored"), TAG, _never, tmp_path)
    assert outcome.state is State.PRESENT and binary == bin_dir / HOST_BINARY


def test_local_file_that_is_not_executable_is_fetched_again(tmp_path, bin_dir, monkeypatch):
    bin_dir.mkdir()
    (bin_dir / HOST_BINARY).write_text("old")
    (bin_dir / HOST_BINARY).chmod(0o644)
    monkeypatch.setattr(firnrelease, "fetch_checked", lambda r, n, dest: dest.write_text("new") or dest)
    outcome, binary = firneditor.runtime_gate(Choice("local", "stored"), TAG, lambda: _release_with(HOST_BINARY), tmp_path)
    assert outcome.state is State.INSTALLED and binary.read_text() == "new"


def test_local_downloads_checked_and_executable(tmp_path, bin_dir, monkeypatch):
    calls = []
    release = _release_with(HOST_BINARY)

    def fetch(rel, name, dest):
        calls.append((rel, name, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("bin")
        return dest

    monkeypatch.setattr(firnrelease, "fetch_checked", fetch)
    outcome, binary = firneditor.runtime_gate(Choice("local", "flag"), TAG, lambda: release, tmp_path)
    assert outcome.state is State.INSTALLED and binary == bin_dir / HOST_BINARY
    assert calls == [(release, HOST_BINARY, binary)] and binary.stat().st_mode & 0o111


def test_local_without_a_binary_for_this_host_fails_naming_it(tmp_path, bin_dir, monkeypatch):
    monkeypatch.setattr(firnrelease, "host_binary_name", lambda tag, system=None, machine=None: None)
    outcome, binary = firneditor.runtime_gate(Choice("local", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "no firn binary" in outcome.detail and binary is None


@pytest.mark.parametrize("exc", [firnrelease.NoToken("t"), firnrelease.ReleaseUnreadable("u"),
                                 firnrelease.AssetMissing("a"), firnrelease.ChecksumMismatch("c")])
def test_local_turns_each_release_exception_into_failed(tmp_path, bin_dir, monkeypatch, exc):
    def boom(*args):
        raise exc

    monkeypatch.setattr(firnrelease, "fetch_checked", boom)
    outcome, binary = firneditor.runtime_gate(Choice("local", "flag"), TAG, lambda: _release_with(HOST_BINARY), tmp_path)
    assert outcome.state is State.FAILED and outcome.detail == str(exc) and binary is None
    assert not (bin_dir / HOST_BINARY).exists()


def test_local_release_read_failure_is_failed(tmp_path, bin_dir):
    outcome, binary = firneditor.runtime_gate(Choice("local", "flag"), TAG, _unreadable, tmp_path)
    assert outcome.state is State.FAILED and outcome.detail == "no release" and binary is None


def test_docker_that_hangs_is_failed_not_absent(tmp_path, bin_dir, monkeypatch):
    def hang(tool, env=None):
        raise hostinstall.NoAnswer("docker --version gave no answer")

    monkeypatch.setattr(hostinstall, "runs", hang)
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "could not ask docker" in outcome.detail and binary is None


class _Docker:
    """A scripted docker: `answers` maps the subcommand (version, image inspect, pull) to a Result."""

    def __init__(self, **answers):
        self.answers = {"version": Result(0, "", ""), "inspect": Result(0, "", ""), "pull": Result(0, "", ""), **answers}
        self.calls = []

    def __call__(self, argv, **kwargs):
        key = {"version": "version", "image": "inspect", "pull": "pull"}[argv[1]]
        self.calls.append((key, argv, kwargs.get("timeout")))
        return self.answers[key]


@pytest.fixture
def docker(monkeypatch):
    fake = _Docker()
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: True)
    monkeypatch.setattr(firneditor, "run", fake)
    return fake


def test_docker_cli_absent_is_failed_naming_the_cli(tmp_path, bin_dir, monkeypatch):
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: False)
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "docker CLI" in outcome.detail and binary is None


def test_docker_daemon_down_is_failed_naming_the_daemon(tmp_path, bin_dir, docker):
    docker.answers["version"] = Result(1, "", "Cannot connect")
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "daemon" in outcome.detail and binary is None
    assert [c[0] for c in docker.calls] == ["version"]


def test_docker_image_missing_is_pulled_with_the_pull_limit(tmp_path, bin_dir, docker):
    docker.answers["inspect"] = Result(1, "", "No such image")
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.INSTALLED and binary is not None
    pulled = [c for c in docker.calls if c[0] == "pull"]
    assert pulled[0][1] == ["docker", "pull", f"{firnrelease.FIRN_IMAGE_REPOSITORY}:{TAG}"]
    assert pulled[0][2] == limits.DOCKER_PULL


def test_docker_pull_refused_is_failed_naming_the_pull(tmp_path, bin_dir, docker):
    docker.answers["inspect"] = Result(1, "", "No such image")
    docker.answers["pull"] = Result(1, "", "denied")
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "pull" in outcome.detail and "denied" in outcome.detail
    assert binary is None and not (bin_dir / "firn-docker").exists()


@pytest.mark.parametrize("hangs", ["version", "inspect", "pull"])
def test_docker_probe_that_hangs_is_could_not_ask(tmp_path, bin_dir, docker, hangs):
    docker.answers["inspect"] = Result(1, "", "No such image")
    docker.answers[hangs] = Result(-9, "", "timed out", timed_out=True)
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "could not ask docker" in outcome.detail and binary is None


def test_docker_root_with_a_colon_is_failed_naming_the_path(tmp_path, bin_dir, docker):
    root = tmp_path / "a:b"
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, root)
    assert outcome.state is State.FAILED and str(root) in outcome.detail and "colon" in outcome.detail
    assert binary is None and docker.calls == []


def test_docker_script_that_is_not_utf8_is_rewritten(tmp_path, bin_dir, docker):
    bin_dir.mkdir()
    (bin_dir / "firn-docker").write_bytes(b"\xff\xfe")
    outcome, path = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.INSTALLED and path.read_text().startswith("#!/bin/sh\n")


def test_docker_script_path_that_is_a_directory_is_failed_naming_it(tmp_path, bin_dir, docker):
    (bin_dir / "firn-docker").mkdir(parents=True)
    outcome, path = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and str(bin_dir / "firn-docker") in outcome.detail and path is None


def test_docker_rewrites_the_script_when_the_pin_changed(tmp_path, bin_dir, docker):
    first, path = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    again, same = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    moved, _ = firneditor.runtime_gate(Choice("docker", "flag"), "v0.20.0", _never, tmp_path)
    assert (first.state, again.state, moved.state) == (State.INSTALLED, State.PRESENT, State.INSTALLED)
    assert path == same == bin_dir / "firn-docker" and path.stat().st_mode & 0o777 == 0o755
    assert "firn:v0.20.0" in path.read_text()


# ---- the extension gate -------------------------------------------------------------------------------

VSIX = f"firn-{TAG}.vsix"


class _Code:
    """A scripted `code`: `listing` answers --list-extensions, `install` answers --install-extension."""

    def __init__(self, listing, install=Result(0, "", "")):
        self.listing, self.install, self.calls = listing, install, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return self.listing if "--list-extensions" in argv else self.install


@pytest.fixture
def code(monkeypatch):
    fake = _Code(Result(0, "ms-python.python@1.0.0\n", ""))
    monkeypatch.setattr(firneditor.shutil, "which", lambda name, path=None: "/usr/bin/code")
    monkeypatch.setattr(firneditor, "run", fake)
    return fake


def _vsix_release():
    return _release_with(VSIX, f"{VSIX}.sha256")


def _fetches(monkeypatch):
    got = []

    def fake(release, name, dest):
        got.append((name, dest))
        dest.write_text("vsix")
        return dest
    monkeypatch.setattr(firnrelease, "fetch_checked", fake)
    return got


def test_no_code_on_path_fails_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(firneditor.shutil, "which", lambda name, path=None: None)
    outcome = firneditor.extension_gate(TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "code" in outcome.detail and "PATH" in outcome.detail


def test_installed_at_the_tag_is_present(tmp_path, code):
    code.listing = Result(0, "a.b@1\nzwyssig.firn@0.19.0\n", "")
    outcome = firneditor.extension_gate(TAG, _never, tmp_path)
    assert outcome.state is State.PRESENT and "0.19.0" in outcome.detail
    assert len(code.calls) == 1 and code.calls[0][1]["timeout"] == hostinstall.VERSION_TIMEOUT_S


def test_other_version_installs_the_checked_vsix(tmp_path, code, monkeypatch):
    code.listing = Result(0, "zwyssig.firn@0.18.0\n", "")
    got = _fetches(monkeypatch)
    outcome = firneditor.extension_gate(TAG, _vsix_release, tmp_path)
    assert outcome.state is State.INSTALLED and "0.19.0" in outcome.detail
    assert got == [(VSIX, tmp_path / VSIX)]
    argv, kw = code.calls[-1]
    assert argv[1:] == ["--install-extension", str(tmp_path / VSIX), "--force"]
    assert kw["timeout"] == hostinstall.INSTALL_TIMEOUT_S


def test_not_installed_at_all_installs(tmp_path, code, monkeypatch):
    _fetches(monkeypatch)
    assert firneditor.extension_gate(TAG, _vsix_release, tmp_path).state is State.INSTALLED


def test_a_longer_version_with_the_tag_as_prefix_is_not_the_tag(tmp_path, code, monkeypatch):
    code.listing = Result(0, "zwyssig.firn@0.19.01\nzwyssig.firn-other@0.19.0\n", "")
    _fetches(monkeypatch)
    assert firneditor.extension_gate(TAG, _vsix_release, tmp_path).state is State.INSTALLED


@pytest.mark.parametrize("listing", [Result(1, "", "boom"), Result(-9, "", "slow", timed_out=True),
                                     Result(127, "", "nope", not_started="exec failed")])
def test_unanswering_code_is_could_not_ask_and_installs_nothing(tmp_path, code, listing):
    code.listing = listing
    outcome = firneditor.extension_gate(TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "could not ask code" in outcome.detail
    assert all("--install-extension" not in c[0] for c in code.calls)


def test_release_without_vsix_names_tag_and_asset(tmp_path, code):
    outcome = firneditor.extension_gate(TAG, lambda: _release_with(), tmp_path)
    assert outcome.state is State.FAILED and VSIX in outcome.detail and TAG in outcome.detail
    assert all("--install-extension" not in c[0] for c in code.calls)


@pytest.mark.parametrize("raising", [_no_token, _unreadable])
def test_unreadable_release_is_failed(tmp_path, code, raising):
    assert firneditor.extension_gate(TAG, raising, tmp_path).state is State.FAILED


def test_failed_install_is_failed_with_codes_words(tmp_path, code, monkeypatch):
    _fetches(monkeypatch)
    code.install = Result(1, "", "bad vsix")
    outcome = firneditor.extension_gate(TAG, _vsix_release, tmp_path)
    assert outcome.state is State.FAILED and "bad vsix" in outcome.detail


def test_install_that_hangs_is_failed_not_installed(tmp_path, code, monkeypatch):
    _fetches(monkeypatch)
    code.install = Result(-9, "", "timed out", timed_out=True)
    outcome = firneditor.extension_gate(TAG, _vsix_release, tmp_path)
    assert outcome.state is State.FAILED and "could not ask code" in outcome.detail


# --- the workspace gate -----------------------------------------------------------------------------------------

BINARY_REL = "build/tools/bin/firn-v0.19.0-linux-amd64"


def _manifest(*cwds):
    """The real shape: {phase: {group: {commands: {name: {task, with: {image, cwd}}}}}}."""
    commands = {}
    for i, cwd in enumerate(cwds):
        w = {"image": f"ghcr.io/marcozwyssig/firn:{TAG}"}
        if cwd is not None:
            w["cwd"] = cwd
        commands[f"model{i}"] = {"task": "x", "with": w}
    return {"ci": {"build": {"commands": commands}}}


def _git_init(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _gate(root, binary=None, data=None):
    return firneditor.workspace_gate(root, "p", binary or root / BINARY_REL, data or _manifest("src"))


def _project(root, rel, java=False):
    (root / rel).mkdir(parents=True, exist_ok=True)
    if java:
        (root / rel / "F.java").write_text("class F {}")


def test_folders_come_from_firn_workspace_toml(tmp_path):
    (tmp_path / "b/x").mkdir(parents=True)
    (tmp_path / "a/y").mkdir(parents=True)
    (tmp_path / "firn-workspace.toml").write_text('# c\nprojects = ["b/x", "a/y"]  # c\n')
    assert firneditor.projects(tmp_path, _manifest("src")) == ["b/x", "a/y"]


def test_without_firn_workspace_toml_the_model_cwd_is_the_folder(tmp_path):
    (tmp_path / "src").mkdir()
    assert firneditor.projects(tmp_path, _manifest("src")) == ["src"]
    assert firneditor.projects(tmp_path, _manifest(None)) == ["."]


def test_several_model_commands_give_one_folder_each_deduplicated(tmp_path):
    for d in ("src", "other"):
        (tmp_path / d).mkdir()
    assert firneditor.projects(tmp_path, _manifest("src", "other", "src")) == ["src", "other"]


@pytest.mark.parametrize("text", ["projects = [", "projects = 3", 'projects = ["a", 1]'])
def test_a_broken_firn_workspace_toml_names_the_file(tmp_path, text):
    (tmp_path / "firn-workspace.toml").write_text(text)
    with pytest.raises(ValueError, match="firn-workspace.toml"):
        firneditor.projects(tmp_path, _manifest("src"))


def test_a_listed_folder_that_does_not_exist_is_named(tmp_path):
    (tmp_path / "firn-workspace.toml").write_text('projects = ["src/firn/gone"]\n')
    with pytest.raises(ValueError, match="src/firn/gone"):
        firneditor.projects(tmp_path, _manifest("src"))


def test_workspace_json_carries_mode_and_relative_binary(tmp_path):
    _project(tmp_path, "src")
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text("/p.code-workspace\n")
    out = _gate(tmp_path)
    assert out.state is State.INSTALLED, out.detail
    ws = json.loads((tmp_path / "p.code-workspace").read_text())
    assert ws["folders"] == [{"path": "src"}]
    assert ws["settings"] == {"firn.mode": "stdio", "firn.binary": BINARY_REL}
    assert _gate(tmp_path).state is State.PRESENT


def test_not_git_ignored_fails_naming_the_line(tmp_path):
    _project(tmp_path, "src")
    _git_init(tmp_path)
    out = _gate(tmp_path)
    assert out.state is State.FAILED
    assert "/p.code-workspace" in out.detail
    assert (tmp_path / "p.code-workspace").is_file()


def test_not_a_git_repository_is_could_not_ask_git(tmp_path):
    _project(tmp_path, "src")
    out = _gate(tmp_path)
    assert out.state is State.FAILED
    assert "could not ask git" in out.detail


def test_java_projects_are_named_in_the_outcome(tmp_path):
    _project(tmp_path, "src/j", java=True)
    _project(tmp_path, "src/k")
    (tmp_path / "firn-workspace.toml").write_text('projects = ["src/j", "src/k"]\n')
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text("/p.code-workspace\n")
    out = _gate(tmp_path)
    assert out.state is State.INSTALLED
    assert "src/j" in out.detail and "firn#1460" in out.detail
    assert "src/k" not in out.detail


def test_java_files_under_build_do_not_count(tmp_path):
    _project(tmp_path, "a")
    (tmp_path / "a/build/gen").mkdir(parents=True)
    (tmp_path / "a/build/gen/F.java").write_text("x")
    assert firneditor.java_projects(tmp_path, ["a"]) == []
    (tmp_path / "a/src").mkdir()
    (tmp_path / "a/src/G.java").write_text("x")
    assert firneditor.java_projects(tmp_path, ["a"]) == ["a"]


def test_an_unreadable_project_folder_raises_not_none(tmp_path, monkeypatch):
    _project(tmp_path, "a")
    def walk(top, onerror=None, **kw):
        onerror(PermissionError(13, "denied", str(top)))
        return iter(())
    monkeypatch.setattr(firneditor.os, "walk", walk)
    with pytest.raises(OSError):
        firneditor.java_projects(tmp_path, ["a"])
    _git_init(tmp_path)
    out = _gate(tmp_path, data=_manifest("a"))
    assert out.state is State.FAILED
    assert "could not tell which projects carry Java functions" in out.detail
