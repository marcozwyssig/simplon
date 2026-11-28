"""si#900: the firn runtime of `support install` is chosen by flag, remembered per host, and defaulted from the
release only when nothing was said before. AAA; the name states the behaviour under test."""
import re
import shlex
from types import SimpleNamespace

import pytest

from simplon.adapters import firnrelease, hostinstall, tools
from simplon.adapters.hostinstall import State
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


def test_docker_without_a_running_docker_fails(tmp_path, bin_dir, monkeypatch):
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: False)
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "docker" in outcome.detail and binary is None
    assert not (bin_dir / "firn-docker").exists()


def test_docker_that_hangs_is_failed_not_absent(tmp_path, bin_dir, monkeypatch):
    def hang(tool, env=None):
        raise hostinstall.NoAnswer("docker --version gave no answer")

    monkeypatch.setattr(hostinstall, "runs", hang)
    outcome, binary = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    assert outcome.state is State.FAILED and "could not ask docker" in outcome.detail and binary is None


def test_docker_rewrites_the_script_when_the_pin_changed(tmp_path, bin_dir, monkeypatch):
    monkeypatch.setattr(hostinstall, "runs", lambda tool, env=None: True)
    first, path = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    again, same = firneditor.runtime_gate(Choice("docker", "flag"), TAG, _never, tmp_path)
    moved, _ = firneditor.runtime_gate(Choice("docker", "flag"), "v0.20.0", _never, tmp_path)
    assert (first.state, again.state, moved.state) == (State.INSTALLED, State.PRESENT, State.INSTALLED)
    assert path == same == bin_dir / "firn-docker" and path.stat().st_mode & 0o777 == 0o755
    assert "firn:v0.20.0" in path.read_text()
