"""simplon's own `build wheel` is reproducible (si#537, fix round 1).

A rerun of release.yml's `publish` job rebuilds the wheel in a fresh checkout, and `skip-existing` passes
the PyPI upload the first attempt made. `build homebrew-formula --source pypi` then refuses unless PyPI's
sha256 equals the local wheel's - so the rebuilt wheel must be byte-identical, and the zip entries' mtimes
come from the files unless SOURCE_DATE_EPOCH says otherwise. Measured by the task review: two builds from
copies with different mtimes gave different digests, and the same digest with SOURCE_DATE_EPOCH set.

AAA; the name states the behaviour under test.
"""
import subprocess
import sys

import pytest

from conftest import ROOT  # noqa: E402 - the one product-root anchor (si#283)

sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
from orchestrator import cli  # noqa: E402 - the product's own module, only reachable from here


@pytest.fixture
def spawned(monkeypatch):
    """What `build_wheel` hands its build subprocess, with no build run; git still answers."""
    calls = []
    real = subprocess.run

    def run(argv, **kwargs):
        if argv[0] != sys.executable:
            return real(argv, **kwargs)
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(cli.subprocess, "run", run)
    return calls


def _head_time() -> str:
    return subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_the_wheel_is_built_at_the_head_commits_time_when_no_epoch_is_set(monkeypatch, spawned):
    # Arrange
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    expected = _head_time()

    # Act
    rc = cli.build_wheel()

    # Assert
    assert rc == 0 and len(spawned) == 1
    argv, kwargs = spawned[0]
    assert argv[1:] == ["-m", "build", "--wheel"] and kwargs["env"]["SOURCE_DATE_EPOCH"] == expected


def test_a_preset_epoch_is_kept(monkeypatch, spawned):
    # Arrange
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1761000000")

    # Act
    rc = cli.build_wheel()

    # Assert
    assert rc == 0 and len(spawned) == 1 and spawned[0][1]["env"]["SOURCE_DATE_EPOCH"] == "1761000000"


def test_without_a_commit_time_nothing_is_built(monkeypatch, spawned, capsys):
    # Arrange: git cannot answer
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    monkeypatch.setattr(cli, "_head_commit_time", lambda: None)

    # Act
    rc = cli.build_wheel()

    # Assert
    assert rc == 1 and spawned == []
    assert "SOURCE_DATE_EPOCH" in capsys.readouterr().err
