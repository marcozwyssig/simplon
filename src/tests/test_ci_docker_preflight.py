"""Unit tests for `support:ci-docker-preflight` (si#623): a job's first step runs a container from where the
kernel uses docker, and a refusal names who asked, what the socket is, which gid `--group-add` handed over,
and the way out.

Docker is a stub on PATH (`dockerstub`): a real process, so the body's real `run`, exit code and output are
what is tested. The socket is a real file under tmp_path named through DOCKER_HOST, so its uid, gid and mode
are read by a real `stat`. What the stub cannot show is a real daemon refusing a real socket: that is
`test_the_probe_runs_a_real_container_on_this_host` for the green half, and the PR's reproduction for the
red half (the kernel image, `--user` and a `--group-add` that does not match). AAA throughout.
"""
from __future__ import annotations

import os

import pytest

from conftest import docker_is_usable
from dockerstub import docker_on_path
from simplon.adapters import docker
from simplon.tasks import dockerpreflight

#: What the daemon answered on ghr-8 on 2026-11-11 (run 42979640016), verbatim.
_DENIED = "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DELIVERY_ROUTE", raising=False)


def _out(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _refusing_docker(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(docker_on_path(tmp_path, f"echo '{_DENIED}' >&2\nexit 1\n")))


def _socket(tmp_path, monkeypatch, mode: int):
    """A real file at a real mode, named as the socket through DOCKER_HOST."""
    sock = tmp_path / "docker.sock"
    sock.touch()
    sock.chmod(mode)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")
    return sock


def _as(monkeypatch, uid: int, gid: int, groups: list[int]) -> None:
    """This process as somebody else: the suite runs as root here, and root is never refused a socket."""
    monkeypatch.setattr(docker.os, "getuid", lambda: uid)
    monkeypatch.setattr(docker.os, "getgid", lambda: gid)
    monkeypatch.setattr(docker.os, "getgroups", lambda: groups)
    real = os.access
    # Only the socket is refused: `shutil.which` asks `os.access` too, and must still find the stub.
    monkeypatch.setattr(docker.os, "access", lambda p, m: False if str(p).endswith(".sock") else real(p, m))


def test_a_refused_socket_in_the_kernel_container_names_who_what_the_gid_and_the_way_out(
        tmp_path, monkeypatch, capsys):
    # arrange: the shape measured on ghr-8 - the kernel container, a non-root user, a group-add that is
    # not the socket's gid
    _refusing_docker(tmp_path, monkeypatch)
    sock = _socket(tmp_path, monkeypatch, 0o660)
    monkeypatch.setenv("DELIVERY_ROUTE", "inside")
    _as(monkeypatch, 5000, 5000, [5000, 4242])
    found = sock.stat()

    # act
    rc = dockerpreflight.ci_preflight()

    # assert
    out = _out(capsys)
    assert rc == 1
    assert _DENIED in out
    assert "uid 5000" in out and "groups 4242, 5000" in out
    assert f"{sock} uid {found.st_uid}, gid {found.st_gid}, mode 0660" in out
    assert "--group-add: 4242" in out
    assert f"gid {found.st_gid} is not among" in out


def test_a_socket_no_group_may_write_names_the_mode_not_the_group(tmp_path, monkeypatch, capsys):
    # arrange: a socket at 0600 - no group membership and no --group-add can reach it, so naming the group
    # would send the operator after the wrong cure
    _refusing_docker(tmp_path, monkeypatch)
    sock = _socket(tmp_path, monkeypatch, 0o600)
    monkeypatch.setenv("DELIVERY_ROUTE", "inside")
    _as(monkeypatch, 5000, 5000, [5000, sock.stat().st_gid])

    # act
    rc = dockerpreflight.ci_preflight()

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "mode 0600" in out and "no group membership and no --group-add" in out


def test_on_the_host_route_the_way_out_is_the_docker_group_and_no_group_add_is_claimed(
        tmp_path, monkeypatch, capsys):
    # arrange: the venv route - the kernel runs on the host as the runner's user, nothing was group-added
    _refusing_docker(tmp_path, monkeypatch)
    _socket(tmp_path, monkeypatch, 0o660)
    _as(monkeypatch, 5000, 5000, [5000])

    # act
    rc = dockerpreflight.ci_preflight()

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "--group-add: none" in out and "on the host" in out
    assert "support ci-privileges <user>" in out


def test_a_missing_socket_says_so(tmp_path, monkeypatch, capsys):
    # arrange
    _refusing_docker(tmp_path, monkeypatch)
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/absent.sock")

    # act
    rc = dockerpreflight.ci_preflight()

    # assert
    assert rc == 1
    assert "NOT MOUNTED" in _out(capsys)


def test_green_only_from_a_container_that_ran(tmp_path, monkeypatch, capsys):
    # arrange: a docker that records what it was asked - presence is not capability, so `docker version`
    # answering must not be what turns this green
    asked = tmp_path / "argv"
    monkeypatch.setenv("PATH", str(docker_on_path(tmp_path, f'echo "$@" > {asked}\nexit 0\n')))

    # act
    rc = dockerpreflight.ci_preflight()

    # assert
    assert rc == 0
    assert asked.read_text().split() == ["run", "--rm", "--network", "none", dockerpreflight.PROBE_IMAGE, "true"]


def test_the_probe_image_is_pinned_by_digest():
    assert "@sha256:" in dockerpreflight.PROBE_IMAGE


def test_no_docker_on_path_is_red(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))

    assert dockerpreflight.ci_preflight() == 1
    assert "no `docker` on PATH" in _out(capsys)


def test_a_probe_that_hangs_is_red_with_a_verdict(tmp_path, monkeypatch, capsys):
    # arrange: a run that hangs is neither green nor red
    monkeypatch.setenv("PATH", str(docker_on_path(tmp_path, "exec /bin/sleep 5\n")))
    monkeypatch.setattr(dockerpreflight, "PROBE_TIMEOUT_S", 0.5)

    # act
    rc = dockerpreflight.ci_preflight()

    # assert
    assert rc == 1
    assert "did not finish within" in _out(capsys)


@pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run the probe against")
def test_the_probe_runs_a_real_container_on_this_host(capsys):
    # arrange / act
    rc = dockerpreflight.ci_preflight()

    # assert
    assert rc == 0, _out(capsys)
