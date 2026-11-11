"""`deploy/ci-hosts/runner-docker-check.sh` (si#624), run as a real process against this machine's docker.

What runs here is the `--self` half - the check ExecStartPre= makes - as this process and, where the suite
runs as root, as a uid without the socket's group. The timer half reads a systemd unit's main process
from /proc; it was measured with transient units on a developer host (the PR says how), not in this suite,
because a test that starts system units is a test that can leave them behind. AAA throughout.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import docker_is_usable
from simplon.tasks import imagefile

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "ci-hosts" / "runner-docker-check.sh"

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run the check against")


def _run(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*argv], capture_output=True, text=True, timeout=180,
                          env={**os.environ, **(env or {})})


def test_the_check_runs_the_kernels_own_pinned_image():
    # arrange: a second copy of a pin drifts unless something holds the two equal
    text = SCRIPT.read_text(encoding="utf-8")

    # act
    found = re.search(r'IMAGE="\$\{IMAGE:-([^}]+)\}"', text)

    # assert
    assert found and found.group(1) == imagefile.FILE_TEST_IMAGE


def test_a_docker_that_refuses_is_red_and_names_the_socket(tmp_path):
    # arrange: a docker on PATH that answers `version` and `info` and refuses to run anything, the way
    # ghr-8's did on 2026-11-11 - presence is not capability, so only `run` may decide
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text("#!/bin/sh\ncase \"$1\" in version|info) exit 0 ;; esac\n"
                                   "echo 'permission denied while trying to connect to the "
                                   "docker API at unix:///var/run/docker.sock' >&2\nexit 1\n")
    (bindir / "docker").chmod(0o755)
    sock = tmp_path / "docker.sock"
    sock.touch()

    # act
    done = _run("sh", str(SCRIPT), "--self",
                env={"PATH": f"{bindir}:{os.environ['PATH']}", "SOCKET": str(sock)})

    # assert
    assert done.returncode == 1
    assert "ALERT" in done.stdout and "permission denied" in done.stdout
    assert f"socket: {sock} uid" in done.stdout and "way out:" in done.stdout


def test_no_running_runner_is_red_not_a_quiet_green():
    # arrange / act: a pattern no unit matches - nothing was checked, which is not the same as healthy
    if shutil.which("systemctl") is None:
        pytest.skip("no systemctl here")
    done = _run("sh", str(SCRIPT), env={"PATTERN": "actions.runner.si624-no-such-unit-*.service"})

    # assert
    assert done.returncode == 1
    assert "no running unit matches" in done.stdout


@needs_docker
def test_green_only_from_a_container_that_ran():
    # arrange / act
    done = _run("sh", str(SCRIPT), "--self")

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith("ok ") and "ran a container" in done.stdout


@needs_docker
@pytest.mark.skipif(not hasattr(os, "getuid") or os.getuid() != 0 or shutil.which("setpriv") is None,
                    reason="needs root and setpriv to become a uid without the socket's group")
def test_a_user_without_the_sockets_group_is_refused_by_the_real_daemon():
    # arrange: uid 65534 with no supplementary group - what a runner looks like that lost the docker group.
    # The script goes in on stdin, because that uid may not be able to traverse the checkout.
    if not os.path.exists("/var/run/docker.sock"):
        pytest.skip("docker here is not on the default socket the script checks")
    if os.stat("/var/run/docker.sock").st_mode & 0o002:
        pytest.skip("this socket is world-writable, so no uid is refused it")

    # act
    done = subprocess.run(["setpriv", "--reuid", "65534", "--regid", "65534", "--clear-groups",
                           "sh", "-s", "--", "--self"], input=SCRIPT.read_text(encoding="utf-8"),
                          capture_output=True, text=True, timeout=180, env={**os.environ, "HOME": "/nonexistent"})

    # assert
    assert done.returncode == 1
    assert "permission denied" in done.stdout
    assert "socket: /var/run/docker.sock uid" in done.stdout
