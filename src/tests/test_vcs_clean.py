"""`vcs:clean` (si#714): put a checkout back to a fresh clone's state, preview by default.

Every test here runs against a REAL git repository under `tmp_path`; nothing is monkeypatched but the
product context that points the task at it. What the task promises is a claim about what `git clean`
does to a real tree - which files go, which nested repository survives, what a failing git says - and a
stub of `run()` could only confirm the wording it was written with.

The repository is isolated from the developer's own git configuration the way `test_release_tag` does
it, and GIT_CEILING_DIRECTORIES keeps the not-a-repository case from discovering whatever repository
the temporary directory happens to sit inside.

AAA throughout.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplon.manifest import context
from simplon.manifest.context import ProductContext
from simplon.tasks import vcs


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture
def isolated_git(tmp_path, monkeypatch) -> Path:
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    for name, value in (("GIT_CONFIG_GLOBAL", str(empty)), ("GIT_CONFIG_SYSTEM", str(empty)),
                        ("GIT_CEILING_DIRECTORIES", str(tmp_path)),
                        ("GIT_AUTHOR_NAME", "Test"), ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
                        ("GIT_COMMITTER_NAME", "Test"), ("GIT_COMMITTER_EMAIL", "test@example.invalid")):
        monkeypatch.setenv(name, value)
    return tmp_path


def _point_at(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(context, "_current", ProductContext("sample", root, root / "sample.yaml"))


@pytest.fixture
def repo(isolated_git, monkeypatch) -> Path:
    """A committed checkout with an ignore rule, and the task pointed at it."""
    work = isolated_git / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    (work / "tracked.txt").write_text("kept", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "init")
    _point_at(monkeypatch, work)
    return work


def _dirty(work: Path) -> None:
    """One untracked file, one ignored file and one ignored directory with content."""
    (work / "untracked.txt").write_text("u", encoding="utf-8")
    (work / "debug.log").write_text("i", encoding="utf-8")
    (work / "build" / "out").mkdir(parents=True)
    (work / "build" / "out" / "artefact").write_text("a", encoding="utf-8")


def test_the_preview_lists_what_would_go_and_removes_nothing(repo, capsys):
    # arrange
    _dirty(repo)

    # act
    rc = vcs.clean()

    # assert: every entry named, the count given, and every file still on disk
    out = capsys.readouterr().out
    assert rc == 0
    for entry in ("untracked.txt", "debug.log", "build/"):
        assert entry in out
    assert "3 entries" in out
    assert "--force" in out
    assert (repo / "untracked.txt").exists()
    assert (repo / "debug.log").exists()
    assert (repo / "build" / "out" / "artefact").exists()


def test_force_removes_untracked_and_ignored_files_and_lists_them(repo, capsys):
    # arrange
    _dirty(repo)

    # act
    rc = vcs.clean(force=True)

    # assert: untracked and ignored both gone, tracked content untouched, and the removal reported
    out = capsys.readouterr().out
    assert rc == 0
    assert not (repo / "untracked.txt").exists()
    assert not (repo / "debug.log").exists()
    assert not (repo / "build").exists()
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "kept"
    assert (repo / ".gitignore").exists()
    for entry in ("untracked.txt", "debug.log", "build/"):
        assert entry in out
    assert "removed 3 entries" in out


def test_a_nested_repository_survives_force_and_is_reported_as_skipped(repo, capsys):
    # arrange: a nested repository at the top (git skips it silently) and one deeper down (git names it),
    # and a worktree of the checkout itself, the shape `.claude/worktrees/agent-*` has
    _dirty(repo)
    subprocess.run(["git", "init", "-q", str(repo / "nested")], check=True)
    (repo / "nested" / "inside").write_text("n", encoding="utf-8")
    (repo / "deep" / "inner").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo / "deep" / "inner" / "repo")], check=True)
    (repo / "deep" / "loose").write_text("l", encoding="utf-8")
    _git(repo, "worktree", "add", "-q", str(repo / "wt"))

    # act: the preview first, then the removal
    preview_rc = vcs.clean()
    preview = capsys.readouterr().out
    rc = vcs.clean(force=True)
    out = capsys.readouterr().out

    # assert: every nested repository named as skipped in both runs, and still there afterwards
    assert (preview_rc, rc) == (0, 0)
    for text in (preview, out):
        for skipped in ("nested/", "deep/inner/repo", "wt/"):
            assert f"skipped (nested repository): {skipped}" in text
    assert (repo / "nested" / "inside").exists()
    assert (repo / "deep" / "inner" / "repo" / ".git").exists()
    assert (repo / "wt" / "tracked.txt").exists()
    assert not (repo / "deep" / "loose").exists()
    assert not (repo / "untracked.txt").exists()


def test_a_clean_checkout_says_nothing_to_remove(repo, capsys):
    # arrange: nothing untracked, nothing ignored

    # act
    preview_rc = vcs.clean()
    preview = capsys.readouterr().out
    rc = vcs.clean(force=True)
    out = capsys.readouterr().out

    # assert: its own line, rc 0, and not a preview of zero entries
    assert (preview_rc, rc) == (0, 0)
    for text in (preview, out):
        assert "nothing to remove" in text
        assert "--force" not in text
    assert (repo / "tracked.txt").exists()


@pytest.mark.parametrize("force", [False, True])
def test_a_failing_git_is_rc_1_with_gits_own_message(isolated_git, monkeypatch, capsys, force):
    # arrange: a directory that is not a repository
    plain = isolated_git / "plain"
    plain.mkdir()
    (plain / "file").write_text("f", encoding="utf-8")
    _point_at(monkeypatch, plain)

    # act
    rc = vcs.clean(force=force)

    # assert: a failure, never a silent 0, git's words on stderr, and nothing touched
    err = capsys.readouterr().err
    assert rc == 1
    assert "not a git repository" in err
    assert (plain / "file").exists()
