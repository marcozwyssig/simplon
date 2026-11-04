"""Unit tests for `support:docker-preflight` (si#564): docker found from the active context, and with
`editor: devcontainer` the one VS Code setting that makes the Dev Containers extension find it.

Docker is a stub on PATH (`dockerstub`): a real process, so the body's real `run`/`subprocess` calls,
exit codes and output are what is tested. No host in CI has Colima, and the extension is not run here:
what it does is read from its code (0.471.0, si#564's first comment). The stub answers `context inspect`
differently when DOCKER_HOST or DOCKER_CONTEXT is set, which is how "what the terminal sees" and "what
VS Code sees" are told apart. AAA throughout.
"""
from __future__ import annotations

import pytest

from simplon.tasks import dockerpreflight

from dockerstub import docker_on_path


def _docker(tmp_path, monkeypatch, *, terminal: str = "", editor: str = "colima|unix:///c.sock",
            version_rc: int = 0, version_err: str = "", inspect_rc: int = 0) -> None:
    """A docker whose `context inspect` prints `editor` without overrides and `terminal` (when given)
    with DOCKER_HOST/DOCKER_CONTEXT set."""
    terminal = terminal or editor
    script = f"""
case "$1" in
  version) [ {version_rc} -eq 0 ] || {{ echo '{version_err}' >&2; exit {version_rc}; }}; echo 29.5.2 ;;
  context) [ {inspect_rc} -eq 0 ] || exit {inspect_rc}
           if [ -n "$DOCKER_HOST$DOCKER_CONTEXT" ]; then echo '{terminal}'; else echo '{editor}'; fi ;;
  *) exit 0 ;;
esac
"""
    monkeypatch.setenv("PATH", str(docker_on_path(tmp_path, script)))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)


def _out(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_no_docker_on_path_is_red(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))

    assert dockerpreflight.preflight() == 1
    assert "install docker" in _out(capsys)


def test_a_daemon_that_does_not_answer_is_red_with_its_own_lines(tmp_path, monkeypatch, capsys):
    # arrange
    _docker(tmp_path, monkeypatch, version_rc=1, version_err="Cannot connect to the Docker daemon at x")

    # act
    rc = dockerpreflight.preflight()

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "Cannot connect to the Docker daemon at x" in out and "docker context ls" in out


def test_docker_answers_is_green_and_names_context_and_endpoint(tmp_path, monkeypatch, capsys):
    _docker(tmp_path, monkeypatch)

    assert dockerpreflight.preflight() == 0
    out = _out(capsys)
    assert "colima" in out and "unix:///c.sock" in out and "29.5.2" in out


def test_a_context_docker_cannot_name_warns_and_stays_green(tmp_path, monkeypatch, capsys):
    # arrange: the daemon answers, `context inspect` does not
    _docker(tmp_path, monkeypatch, inspect_rc=1)

    # act
    rc = dockerpreflight.preflight(editor="devcontainer")

    # assert: never read as "default", and no advice built on a guess
    out = _out(capsys)
    assert rc == 0
    assert "could not" in out and "docker.context" not in out


def test_without_editor_nothing_is_said_about_the_editor(tmp_path, monkeypatch, capsys):
    _docker(tmp_path, monkeypatch)

    dockerpreflight.preflight()

    out = _out(capsys)
    assert "docker.context" not in out and "Dev Containers" not in out


def test_editor_on_a_non_default_context_names_the_setting(tmp_path, monkeypatch, capsys):
    _docker(tmp_path, monkeypatch, editor="colima|unix:///c.sock")

    assert dockerpreflight.preflight(editor="devcontainer") == 0
    assert '"docker.context": "colima"' in _out(capsys)


def test_editor_on_default_with_its_socket_is_quiet_ok(tmp_path, monkeypatch, capsys):
    # arrange: the default context, and its socket exists
    sock = tmp_path / "docker.sock"
    sock.touch()
    _docker(tmp_path, monkeypatch, editor=f"default|unix://{sock}")

    # act
    rc = dockerpreflight.preflight(editor="devcontainer")

    # assert
    out = _out(capsys)
    assert rc == 0
    assert "docker.context" not in out and "docker.host" not in out


def test_editor_on_default_without_its_socket_names_a_context_that_answers(tmp_path, monkeypatch, capsys):
    # arrange: VS Code would see `default` with nothing behind it; the terminal sees colima
    monkeypatch.setenv("DOCKER_CONTEXT", "colima")
    _docker(tmp_path, monkeypatch, terminal="colima|unix:///c.sock",
            editor=f"default|unix://{tmp_path}/missing.sock")

    # act
    rc = dockerpreflight.preflight(editor="devcontainer")

    # assert
    out = _out(capsys)
    assert rc == 0
    assert '"docker.context": "colima"' in out


def test_editor_on_default_without_its_socket_names_the_host_when_no_context_has_a_name(
        tmp_path, monkeypatch, capsys):
    # arrange: DOCKER_HOST in the shell is the only way the terminal reaches docker
    sock = tmp_path / "real.sock"
    sock.touch()
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")
    _docker(tmp_path, monkeypatch, terminal=f"default|unix://{sock}",
            editor=f"default|unix://{tmp_path}/missing.sock")

    # act
    rc = dockerpreflight.preflight(editor="devcontainer")

    # assert
    out = _out(capsys)
    assert rc == 0
    assert f'"docker.host": "unix://{sock}"' in out


def test_editor_sees_what_vscode_sees_not_the_shell(tmp_path, monkeypatch, capsys):
    """The builder check's measurement, as a test: with DOCKER_HOST exported, the terminal says `default`
    and answers, while VS Code from the Dock sees neither."""
    # arrange
    sock = tmp_path / "real.sock"
    sock.touch()
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")
    _docker(tmp_path, monkeypatch, terminal=f"default|unix://{sock}",
            editor=f"default|unix://{tmp_path}/missing.sock")

    # act
    dockerpreflight.preflight(editor="devcontainer")

    # assert: the verdict is about the socket VS Code would use, not the one the terminal reaches
    out = _out(capsys)
    assert "DOCKER_HOST" in out and "VS Code" in out
    assert f"{tmp_path}/missing.sock" in out


def test_an_unknown_editor_is_refused_with_the_known_values(tmp_path, monkeypatch, capsys):
    _docker(tmp_path, monkeypatch)

    assert dockerpreflight.preflight(editor="vim") == 1
    out = _out(capsys)
    assert "'vim'" in out and "devcontainer" in out


def test_windows_is_not_checked_and_says_so(tmp_path, monkeypatch, capsys):
    _docker(tmp_path, monkeypatch)
    monkeypatch.setattr(dockerpreflight.os, "name", "nt")

    assert dockerpreflight.preflight(editor="devcontainer") == 0
    out = _out(capsys)
    assert "not checked" in out and "docker.context" not in out


@pytest.mark.parametrize("scenario", [
    dict(),
    dict(version_rc=1, version_err="Cannot connect"),
    dict(inspect_rc=1),
    dict(editor="default|unix:///nowhere/docker.sock"),
    dict(editor="colima|unix:///c.sock"),
])
def test_no_message_says_sudo_or_ln(tmp_path, monkeypatch, capsys, scenario):
    _docker(tmp_path, monkeypatch, **scenario)

    dockerpreflight.preflight(editor="devcontainer")

    out = _out(capsys)
    assert "sudo" not in out and "ln -s" not in out
