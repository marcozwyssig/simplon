"""A docker that is PRESENT and cannot be run is a third state, and it used to crash both halves.

FOUND ON A REAL RUNNER, not reasoned about. On ghr-8 (2026-09-16) a file named `docker` sat on PATH that
`shutil.which` accepted - it checks the permission bits, and they were set - and that could not be
executed: `PermissionError: [Errno 13] Permission denied: 'docker'`, the signature of a binary on a
`noexec` mount.

Two things met it and neither survived. The kernel's own `ensure_docker`, whose entire stated purpose is
to "die naming the fixes", came apart in a bare traceback that named none of them. And three e2e suites
carried the same copied guard - `shutil.which(...) is not None and run(...).ok` - whose job is to decide
whether to SKIP, and which crashed the module instead.

Both are this repository's recurring defect: a value that cannot tell two states apart, here one state
short. Absent and unusable are the same answer to "can I run a container"; they are not the same answer
to "is something wrong with this machine", which is why the kernel still says so out loud.

AAA throughout.
"""
from __future__ import annotations

import pytest

import conftest
from simplon import docker


class _Unexecutable:
    """A `docker` that is on PATH and cannot be exec'd, which is what a noexec mount produces."""

    def __init__(self, path: str = "/mnt/noexec/docker") -> None:
        self.path = path

    def which(self, _name: str) -> str:
        return self.path

    def run(self, _argv, **_kw):
        raise PermissionError(13, "Permission denied", "docker")


def test_the_kernel_answers_not_reachable_instead_of_raising(monkeypatch) -> None:
    """The half that matters in production: `ensure_docker` classifies, and a probe that throws takes
    the classifier with it."""
    # arrange
    broken = _Unexecutable()
    monkeypatch.setattr(docker, "run", broken.run)

    # act
    reachable = docker._daemon_reachable()

    # assert
    assert reachable is False


def test_the_suites_guard_answers_no_instead_of_crashing_the_module(monkeypatch) -> None:
    """The half that decides whether three e2e suites run at all. A guard that raises does not skip -
    it fails, and it fails at import, so everything in the file goes with it."""
    # arrange
    broken = _Unexecutable()
    monkeypatch.setattr("shutil.which", broken.which)
    monkeypatch.setattr("simplon.run.run", broken.run)

    # act / assert
    assert conftest.docker_is_usable() is False


def test_an_absent_docker_is_still_no(monkeypatch) -> None:
    """The state that always worked, kept: the repair must not have swapped one blind spot for another."""
    # arrange
    monkeypatch.setattr("shutil.which", lambda _n: None)

    # act / assert
    assert conftest.docker_is_usable() is False


def test_a_working_docker_is_still_yes(monkeypatch) -> None:
    """And the ordinary case, because a guard that answers no to everything would make all three e2e
    suites skip forever and nothing would say so."""
    # arrange
    class _Ok:
        ok = True

    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("simplon.run.run", lambda *_a, **_k: _Ok())

    # act / assert
    assert conftest.docker_is_usable() is True


@pytest.mark.parametrize("error", [PermissionError(13, "Permission denied"), OSError("exec format error")])
def test_every_way_the_exec_can_fail_answers_no(monkeypatch, error) -> None:
    """`noexec` is the one that was measured; a wrong-architecture binary and a broken interpreter reach
    the same place. The guard is written against OSError rather than against the one subclass that
    happened to be seen."""
    # arrange
    def raising(*_a, **_k):
        raise error

    monkeypatch.setattr(docker, "run", raising)

    # act / assert
    assert docker._daemon_reachable() is False
