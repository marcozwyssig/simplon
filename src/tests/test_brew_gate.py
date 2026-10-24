"""si#526: the brew gate, against fake `brew` and `bash` executables on a PATH each test owns.

What a fake confirms is only what is written into it: these tests prove what the gate DECIDES - which
outcome, which command, which environment - not that Homebrew's install.sh works. That was measured
against a real container (see `adapters/brew.py`, "Measured"). AAA throughout.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from simplon.adapters import brew, fetch, hostinstall, tools
from simplon.adapters.hostinstall import State


def _tool(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def host(tmp_path, monkeypatch):
    """An empty PATH and a Homebrew prefix inside tmp_path; nothing outside the test is reachable."""
    path_dir = tmp_path / "path"
    path_dir.mkdir()
    prefix = tmp_path / "prefix"
    monkeypatch.setenv("PATH", str(path_dir))
    monkeypatch.setattr(brew, "prefix", lambda system, machine: str(prefix))
    monkeypatch.setattr(tools, "prepend_to_path", lambda d: os.environ.__setitem__(
        "PATH", f"{d}{os.pathsep}{os.environ['PATH']}"))
    return path_dir, prefix


def _ensure(**kw):
    defaults = dict(env={}, container=False, system="Linux", machine="x86_64", euid=1000, interactive=False)
    defaults.update(kw)
    return brew.ensure(**defaults)


def test_windows_is_skipped_not_failed(host):
    # act
    outcome = _ensure(system="Windows", machine="AMD64")

    # assert
    assert outcome.state is State.SKIPPED and "Windows" in outcome.detail
    assert hostinstall.rc(outcome) == 0


def test_intel_mac_is_skipped(host):
    # act
    outcome = _ensure(system="Darwin", machine="x86_64")

    # assert
    assert outcome.state is State.SKIPPED and "Apple Silicon" in outcome.detail


def test_ci_is_skipped(host):
    # act
    outcome = _ensure(env={"CI": "true"})

    # assert
    assert outcome.state is State.SKIPPED and "CI=true" in outcome.detail


def test_brew_on_path_is_present(host):
    # arrange
    path_dir, _ = host
    _tool(path_dir, "brew", "echo Homebrew 7.0.9")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.PRESENT


def test_brew_at_the_prefix_but_off_path_is_present_and_put_on_path(host, capsys):
    # arrange
    _, prefix = host
    _tool(prefix / "bin", "brew", "echo Homebrew 7.0.9")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.PRESENT
    assert os.environ["PATH"].split(os.pathsep)[0] == str(prefix / "bin")
    out = capsys.readouterr()
    assert "shellenv" in out.out + out.err


def test_root_on_a_plain_host_has_no_route(host, monkeypatch, tmp_path):
    # arrange: no container marker, whatever machine runs the suite
    monkeypatch.setattr(brew, "ROOT_ALLOWED_MARKERS", (str(tmp_path / "no-dockerenv"),))

    # act
    outcome = _ensure(euid=0)

    # assert
    assert outcome.state is State.NO_ROUTE and "root" in outcome.detail


def _serve(monkeypatch, payload: bytes):
    def download(url, dest, **kw):
        assert url == brew.INSTALL_URL
        Path(dest).write_bytes(payload)
        return Path(dest)
    monkeypatch.setattr(fetch, "download", download)


def _pin_to(monkeypatch, payload: bytes):
    import hashlib
    monkeypatch.setattr(brew, "INSTALL_SHA256", hashlib.sha256(payload).hexdigest())


def test_a_script_with_the_wrong_sha256_is_never_run(host, monkeypatch, tmp_path):
    # arrange: bash would leave a marker if anything ran it
    path_dir, _ = host
    marker = tmp_path / "ran"
    _tool(path_dir, "bash", f"/usr/bin/touch {marker}")
    monkeypatch.setattr(brew, "BASH", str(path_dir / "bash"))
    _serve(monkeypatch, b"echo not the pinned script\n")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and brew.INSTALL_SHA256 in outcome.detail
    assert not marker.exists()


def test_noninteractive_install_sets_noninteractive(host, monkeypatch, tmp_path):
    # arrange: the fake bash records its environment and installs a working brew at the prefix
    path_dir, prefix = host
    seen = tmp_path / "env"
    _tool(path_dir, "bash", f'echo "NONINTERACTIVE=$NONINTERACTIVE" > {seen}; /bin/mkdir -p {prefix}/bin; '
                            f'printf "#!/bin/sh\\necho Homebrew\\n" > {prefix}/bin/brew; /bin/chmod +x {prefix}/bin/brew')
    monkeypatch.setattr(brew, "BASH", str(path_dir / "bash"))
    payload = b"#!/bin/bash\n"
    _serve(monkeypatch, payload)
    _pin_to(monkeypatch, payload)

    # act
    outcome = _ensure(interactive=False)

    # assert
    assert outcome.state is State.INSTALLED
    assert seen.read_text().strip() == "NONINTERACTIVE=1"


def test_interactive_install_does_not_set_noninteractive(host, monkeypatch, tmp_path):
    # arrange
    path_dir, prefix = host
    seen = tmp_path / "env"
    _tool(path_dir, "bash", f'echo "NONINTERACTIVE=$NONINTERACTIVE" > {seen}; /bin/mkdir -p {prefix}/bin; '
                            f'printf "#!/bin/sh\\necho Homebrew\\n" > {prefix}/bin/brew; /bin/chmod +x {prefix}/bin/brew')
    monkeypatch.setattr(brew, "BASH", str(path_dir / "bash"))
    monkeypatch.delenv("NONINTERACTIVE", raising=False)
    payload = b"#!/bin/bash\n"
    _serve(monkeypatch, payload)
    _pin_to(monkeypatch, payload)

    # act
    outcome = _ensure(interactive=True)

    # assert
    assert outcome.state is State.INSTALLED
    assert seen.read_text().strip() == "NONINTERACTIVE="


def test_root_inside_a_container_may_install(host, monkeypatch, tmp_path):
    # arrange: Homebrew's own installer lets root run where /.dockerenv exists
    marker = tmp_path / "dockerenv"
    marker.touch()
    monkeypatch.setattr(brew, "ROOT_ALLOWED_MARKERS", (str(marker),))
    path_dir, _ = host
    _tool(path_dir, "bash", "exit 1")
    monkeypatch.setattr(brew, "BASH", str(path_dir / "bash"))
    payload = b"#!/bin/bash\n"
    _serve(monkeypatch, payload)
    _pin_to(monkeypatch, payload)

    # act
    outcome = _ensure(euid=0)

    # assert: it got as far as running install.sh
    assert outcome.state is State.FAILED and "exited 1" in outcome.detail


def test_install_that_leaves_no_brew_is_failed(host, monkeypatch):
    # arrange: install.sh "succeeds" and leaves nothing behind
    path_dir, _ = host
    _tool(path_dir, "bash", "exit 0")
    monkeypatch.setattr(brew, "BASH", str(path_dir / "bash"))
    payload = b"#!/bin/bash\n"
    _serve(monkeypatch, payload)
    _pin_to(monkeypatch, payload)

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and "does not run" in outcome.detail


def test_a_failing_install_script_is_failed(host, monkeypatch):
    # arrange
    path_dir, _ = host
    _tool(path_dir, "bash", "exit 1")
    monkeypatch.setattr(brew, "BASH", str(path_dir / "bash"))
    payload = b"#!/bin/bash\n"
    _serve(monkeypatch, payload)
    _pin_to(monkeypatch, payload)

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and "exited 1" in outcome.detail


def test_a_failed_download_is_failed(host, monkeypatch):
    # arrange
    def refuse(url, dest, **kw):
        raise fetch.DownloadError("could not download: offline")
    monkeypatch.setattr(fetch, "download", refuse)

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and "offline" in outcome.detail


@pytest.mark.parametrize("system, machine, expected", [
    ("Darwin", "arm64", "/opt/homebrew"),
    ("Linux", "x86_64", "/home/linuxbrew/.linuxbrew"),
    ("Linux", "aarch64", "/home/linuxbrew/.linuxbrew"),
    ("Darwin", "x86_64", None),
    ("Windows", "AMD64", None),
])
def test_prefix(system, machine, expected):
    # act / assert
    assert brew.prefix(system, machine) == expected


def test_shellenv_line():
    # act / assert
    assert brew.shellenv_line("/opt/homebrew") == 'eval "$(/opt/homebrew/bin/brew shellenv)"'


def test_the_install_script_is_pinned_to_a_commit():
    # act / assert: never HEAD, never a branch
    assert brew.INSTALL_URL == ("https://raw.githubusercontent.com/Homebrew/install/"
                                "8ab1549dfa1189fd4d818a2116592d8f0ee06d8c/install.sh")
    assert brew.INSTALL_SHA256 == "5f333bbe53bc490e51e7ccb1df8779b3dd6ee73a1a7379efda216edb08ccb148"
