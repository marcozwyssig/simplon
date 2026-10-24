"""si#526: the gh gate, against fake `brew`, `winget`, `sudo`, `install`, `dpkg` and `apt-get` executables on
a PATH each test owns.

The fakes record every argv, so what is asserted is what a child process was asked to do. What they cannot
show is that the real apt repository installs gh: that was measured in a `debian:trixie` container (see
`adapters/gh.py`, "Measured"). AAA throughout.
"""
from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from simplon.adapters import fetch, gh, hostinstall
from simplon.adapters.hostinstall import State

_WORKING_GH = '#!/bin/sh\necho "gh version 2.103.0"\n'


def _tool(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _make_gh(directory: Path) -> str:
    """Shell that makes a working fake gh appear in `directory`, for a fake installer to run."""
    target = directory / "gh"
    return f"printf '{_WORKING_GH}' > {target}; /bin/chmod +x {target}"


@pytest.fixture
def host(tmp_path, monkeypatch):
    path_dir = tmp_path / "path"
    path_dir.mkdir()
    monkeypatch.setenv("PATH", str(path_dir))
    calls = tmp_path / "calls.log"
    monkeypatch.setattr(gh, "KEYRING_PATH", str(tmp_path / "etc" / "keyring.gpg"))
    monkeypatch.setattr(gh, "LIST_PATH", str(tmp_path / "etc" / "github-cli.list"))
    return path_dir, calls


def _ensure(**kw):
    defaults = dict(env={}, container=False, system="Linux", euid=1000)
    defaults.update(kw)
    return gh.ensure(**defaults)


def _serve_keyring(monkeypatch, payload: bytes, pin: bool = True):
    def download(url, dest, **kw):
        assert url == gh.KEYRING_URL
        Path(dest).write_bytes(payload)
        return Path(dest)
    monkeypatch.setattr(fetch, "download", download)
    if pin:
        monkeypatch.setattr(gh, "KEYRING_SHA256", hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize("system, tools, expected", [
    ("Linux", {"brew", "apt-get", "dpkg"}, "brew"),
    ("Darwin", {"brew"}, "brew"),
    ("Windows", {"brew", "winget"}, "brew"),
    ("Windows", {"winget"}, "winget"),
    ("Linux", {"apt-get", "dpkg"}, "apt"),
    ("Linux", {"apt-get"}, ""),
    ("Linux", {"dnf"}, ""),
    ("Darwin", set(), ""),
    ("Linux", {"winget"}, ""),
])
def test_route_order(system, tools, expected):
    # act / assert
    assert gh.route(system, lambda tool: tool in tools) == expected


def test_gh_that_runs_is_present(host):
    # arrange
    path_dir, _ = host
    (path_dir / "gh").write_text(_WORKING_GH)
    (path_dir / "gh").chmod(0o755)

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.PRESENT


def test_a_gh_on_path_that_does_not_run_is_not_present(host):
    # arrange: a broken gh and no route to replace it
    path_dir, _ = host
    _tool(path_dir, "gh", "exit 1")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.NO_ROUTE


def test_no_route_names_the_manual_link(host):
    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.NO_ROUTE and "https://github.com/cli/cli#installation" in outcome.detail
    assert hostinstall.rc(outcome) == 1


def test_ci_is_skipped(host):
    # act
    outcome = _ensure(env={"GITHUB_ACTIONS": "true"})

    # assert
    assert outcome.state is State.SKIPPED


def test_brew_route_installs_through_brew(host):
    # arrange
    path_dir, calls = host
    _tool(path_dir, "brew", f'echo "brew $@" >> {calls}; {_make_gh(path_dir)}')

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.INSTALLED
    assert calls.read_text().splitlines() == ["brew install gh"]


def test_winget_route_uses_the_pinned_argv(host):
    # arrange
    path_dir, calls = host
    _tool(path_dir, "winget", f'echo "winget $@" >> {calls}; {_make_gh(path_dir)}')

    # act
    outcome = _ensure(system="Windows")

    # assert
    assert outcome.state is State.INSTALLED
    assert calls.read_text().splitlines() == [" ".join(gh.WINGET_ARGV)]


def test_winget_without_gh_on_this_path_asks_for_a_new_shell(host):
    # arrange: winget changes PATH for new shells only
    path_dir, _ = host
    _tool(path_dir, "winget", "exit 0")

    # act
    outcome = _ensure(system="Windows")

    # assert
    assert outcome.state is State.INSTALLED and "new shell" in outcome.detail


def _apt_host(path_dir: Path, calls: Path, *, sudo: bool = True, apt_body: str | None = None):
    if sudo:
        _tool(path_dir, "sudo", f'echo "sudo $@" >> {calls}; exec "$@"')
    _tool(path_dir, "install", f'echo "install $@" >> {calls}; /bin/mkdir -p "$(/usr/bin/dirname "$5")"; '
                               f'/bin/cp "$4" "$5"')
    _tool(path_dir, "dpkg", 'echo arm64')
    _tool(path_dir, "apt-get", apt_body if apt_body is not None else
          f'echo "apt-get $@" >> {calls}; if [ "$1" = install ]; then {_make_gh(path_dir)}; fi')


def test_apt_route_runs_the_official_steps_in_order(host, monkeypatch):
    # arrange
    path_dir, calls = host
    _apt_host(path_dir, calls)
    _serve_keyring(monkeypatch, b"keyring")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.INSTALLED
    lines = [line for line in calls.read_text().splitlines() if not line.startswith("sudo ")]
    assert [line.split()[0] for line in lines] == ["install", "install", "apt-get", "apt-get"]
    assert lines[0].endswith(gh.KEYRING_PATH) and lines[1].endswith(gh.LIST_PATH)
    assert lines[2:] == ["apt-get update", "apt-get install -y gh"]
    assert Path(gh.LIST_PATH).read_text() == (
        f"deb [arch=arm64 signed-by={gh.KEYRING_PATH}] https://cli.github.com/packages stable main\n")
    assert Path(gh.KEYRING_PATH).read_bytes() == b"keyring"
    assert all(line.startswith("sudo ") for line in calls.read_text().splitlines()[::2])


def test_apt_route_writes_nothing_on_a_keyring_mismatch(host, monkeypatch):
    # arrange: the served keyring is not the pinned one
    path_dir, calls = host
    _apt_host(path_dir, calls)
    _serve_keyring(monkeypatch, b"not the keyring", pin=False)

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and gh.KEYRING_SHA256 in outcome.detail
    assert not calls.exists()
    assert not Path(gh.KEYRING_PATH).exists()


def test_apt_as_root_runs_without_sudo(host, monkeypatch):
    # arrange
    path_dir, calls = host
    _apt_host(path_dir, calls, sudo=False)
    _serve_keyring(monkeypatch, b"keyring")

    # act
    outcome = _ensure(euid=0)

    # assert
    assert outcome.state is State.INSTALLED
    assert not any(line.startswith("sudo ") for line in calls.read_text().splitlines())


def test_apt_without_root_or_sudo_has_no_route(host, monkeypatch):
    # arrange
    path_dir, calls = host
    _apt_host(path_dir, calls, sudo=False)
    _serve_keyring(monkeypatch, b"keyring")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.NO_ROUTE and "sudo" in outcome.detail
    assert not calls.exists()


def test_a_failing_apt_step_stops_the_sequence(host, monkeypatch):
    # arrange: apt-get update fails
    path_dir, calls = host
    _apt_host(path_dir, calls, apt_body=f'echo "apt-get $@" >> {calls}; exit 100')
    _serve_keyring(monkeypatch, b"keyring")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and "exited 100" in outcome.detail
    assert [line for line in calls.read_text().splitlines() if line.startswith("apt-get")] == ["apt-get update"]


def test_an_install_that_leaves_no_working_gh_is_failed(host):
    # arrange
    path_dir, _ = host
    _tool(path_dir, "brew", "exit 0")

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and "does not run" in outcome.detail


def test_a_hanging_install_is_failed_not_waited_on(host, monkeypatch):
    # arrange
    path_dir, _ = host
    _tool(path_dir, "brew", "/bin/sleep 5")
    monkeypatch.setattr(hostinstall, "INSTALL_TIMEOUT_S", 0.2)

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.FAILED and "timed out" in outcome.detail


def test_the_keyring_is_pinned():
    # act / assert: the value cli/cli publishes in docs/install_linux.md, measured 2026-10-24
    assert gh.KEYRING_URL == "https://cli.github.com/packages/githubcli-archive-keyring.gpg"
    assert gh.KEYRING_SHA256 == "6084d5d7bd8e288441e0e94fc6275570895da18e6751f70f057485dc2d1a811b"


def test_a_gh_only_this_process_can_reach_says_so(host, monkeypatch):
    # arrange: final review - brew's bin was put on PATH by the brew gate, not by the person's shell, so
    # the next `release asset` would not find the gh it installs
    path_dir, calls = host
    _tool(path_dir, "brew", f'echo "brew $@" >> {calls}; {_make_gh(path_dir)}')
    monkeypatch.setattr(hostinstall, "INHERITED_PATH", str(path_dir.parent / "shell-path"))

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.INSTALLED
    assert "shellenv" in outcome.detail and str(path_dir) in outcome.detail


def test_a_present_gh_only_this_process_can_reach_says_so(host, monkeypatch):
    # arrange
    path_dir, _ = host
    (path_dir / "gh").write_text(_WORKING_GH)
    (path_dir / "gh").chmod(0o755)
    monkeypatch.setattr(hostinstall, "INHERITED_PATH", str(path_dir.parent / "shell-path"))

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.PRESENT and "shellenv" in outcome.detail


def test_a_gh_the_shell_reaches_needs_no_hint(host, monkeypatch):
    # arrange
    path_dir, _ = host
    (path_dir / "gh").write_text(_WORKING_GH)
    (path_dir / "gh").chmod(0o755)
    monkeypatch.setattr(hostinstall, "INHERITED_PATH", str(path_dir))

    # act
    outcome = _ensure()

    # assert
    assert outcome.state is State.PRESENT and outcome.detail == ""
