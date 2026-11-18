"""simplon's own orchestrator bodies reach their tools through the kernel's one subprocess seam (si#670 item 6).

`deploy/orchestrator/src/python/orchestrator/cli.py` carried its own `subprocess.run` calls next to
`simplon.kernel.run.run`, and the two copies had drifted: `_head_commit_time` caught `OSError`, so git
missing from PATH was a sentence, while `_canary_line` did not, so the same machine gave a traceback from
`handoff-canary`. Through `run()` a child that never starts is a Result (si#653) for both.

AAA; the name states the behaviour under test.
"""
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import ROOT  # noqa: E402 - the one product-root anchor (si#283)

sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
from orchestrator import cli  # noqa: E402 - the product's own module, only reachable from here


@pytest.fixture
def no_git(monkeypatch, tmp_path):
    """A PATH on which git cannot be found; the interpreter is absolute and still starts."""
    monkeypatch.setenv("PATH", str(tmp_path))


def test_the_canary_without_git_on_path_says_so_rather_than_raising(no_git, capsys):
    # Act
    line = cli._canary_line()

    # Assert
    assert line is None
    assert "git could not name HEAD" in capsys.readouterr().err


def test_the_canary_with_git_names_head():
    # Act
    line = cli._canary_line()

    # Assert
    assert line is not None and line.startswith("simplon hand-off canary: commit ")


def test_the_commit_time_without_git_on_path_is_no_answer(no_git):
    # Act / Assert
    assert cli._head_commit_time() is None


def test_the_suite_streams_through_the_kernels_run(monkeypatch):
    # Arrange: a call past the seam would run the whole suite again, so it fails instead
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(rc=3)

    def bypass(*args, **kwargs):
        raise AssertionError("a body called subprocess.run instead of the kernel's run")

    monkeypatch.setattr(cli, "run", run, raising=False)
    monkeypatch.setattr(subprocess, "run", bypass)

    # Act
    rc = cli.test_suite()

    # Assert: the child's rc is the verdict, its output is not captured, it runs from the tests directory
    assert rc == 3 and len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:3] == [sys.executable, "-m", "pytest"]
    assert kwargs["capture"] is False and kwargs["cwd"] == str(ROOT / "src" / "tests")
