"""si#900: the firn runtime of `support install` is chosen by flag, remembered per host, and defaulted from the
release only when nothing was said before. AAA; the name states the behaviour under test."""
import re
from types import SimpleNamespace

import pytest

from simplon.adapters import firnrelease
from simplon.tasks import firneditor

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
