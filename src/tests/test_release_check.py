"""Unit tests for `release:check` (si#487, part of si#463 D3): the dispatch release refused before anything is cut.

Against REAL repositories - a work tree and a `--bare` origin - for the reason `test_release_tag.py` gives:
the states the check reads (a fetch that fails, a tag origin carries at another commit, a tag at HEAD) do
not exist in a mocked `run()`. The one patch is `remote_tag_commit` returning `None`, because a fetch that
works and an `ls-remote` that fails cannot both be produced against one bare repository.

AAA throughout; each test sets or clears `GITHUB_REF` itself, so the runner's own environment cannot leak in.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplon.manifest import context
from simplon.manifest.context import ProductContext
from simplon.tasks import gitops, release

from conftest import ROOT
from test_release_tag import Lab, _commit, _git, _sha, lab  # noqa: F401 - `lab` is a fixture


@pytest.fixture
def no_ref(monkeypatch):
    monkeypatch.delenv("GITHUB_REF", raising=False)


def _out(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


# --- the tag itself ------------------------------------------------------------------------------------

def test_an_empty_tag_is_refused_and_asks_which_release(lab, no_ref, capsys):
    # act
    rc = release.check("  ")

    # assert
    assert rc == 1
    assert "which release" in _out(capsys)


@pytest.mark.parametrize("tag", ["0.99.0", "v0.99", "v0.99.0-rc1", "V0.99.0", "v01.2.3", " v1.0.0",
                                 "v1.0.0\n", "v1.0.0; touch pwned", "-v0.99.0"])
def test_a_version_not_spelled_vxyz_is_refused(lab, no_ref, capsys, tag):
    # act
    rc = release.check(tag)

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "vX.Y.Z" in out and repr(tag) in out
    assert not (lab.work / "pwned").exists()


@pytest.mark.parametrize("tag", ["v0.0.0", "v1.4.0", "v10.20.30"])
def test_a_version_spelled_vxyz_passes_the_pattern(lab, no_ref, tag):
    assert release.check(tag) == 0


def test_every_tag_this_repository_carries_matches_the_pattern():
    """The population (moved from simplon's own `release version` test): a pattern that would have refused
    a real release is an expression rule over simplon itself, not a diagnosis. Over every tag, not a sample."""
    tags = subprocess.run(["git", "-C", str(ROOT), "tag", "--list"], capture_output=True, text=True,
                          check=True).stdout.split()

    assert tags, "no tags to measure against"
    assert [t for t in tags if not release.VERSION.fullmatch(t)] == []


# --- where the run was started -------------------------------------------------------------------------

@pytest.mark.parametrize("ref", ["refs/heads/feature", "refs/tags/v1.0.0", "refs/pull/7/merge"])
def test_a_run_started_from_anything_but_the_default_branch_is_refused(lab, monkeypatch, capsys, ref):
    # arrange
    monkeypatch.setenv("GITHUB_REF", ref)

    # act
    rc = release.check("v1.0.0")

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "start the release from main" in out and ref in out


def test_a_run_started_from_main_passes(lab, monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")

    assert release.check("v1.0.0") == 0


@pytest.fixture
def master_lab(tmp_path, monkeypatch) -> Lab:
    """`lab`, with `master` as the default branch and origin/HEAD pointing at it."""
    empty = tmp_path / "gitconfig"
    empty.write_text("", encoding="utf-8")
    for name, value in (("GIT_CONFIG_GLOBAL", str(empty)), ("GIT_CONFIG_SYSTEM", str(empty)),
                        ("GIT_AUTHOR_NAME", "Test"), ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
                        ("GIT_COMMITTER_NAME", "Test"), ("GIT_COMMITTER_EMAIL", "test@example.invalid")):
        monkeypatch.setenv(name, value)
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "master", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "master", str(work)], check=True)
    _commit(work, "one")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "master")
    _git(work, "remote", "set-head", "origin", "master")
    monkeypatch.setattr(context, "_current", ProductContext("sample", work, work / "sample.yaml"))
    return Lab(work, origin)


def test_the_default_branch_is_read_not_assumed(master_lab, monkeypatch, capsys):
    # arrange / act
    monkeypatch.setenv("GITHUB_REF", "refs/heads/master")
    on_master = release.check("v1.0.0")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    on_main = release.check("v1.0.0")

    # assert
    assert (on_master, on_main) == (0, 1)
    assert "start the release from master" in _out(capsys)


def test_without_github_ref_the_branch_is_not_checked_and_it_says_so(lab, no_ref, capsys):
    # act
    rc = release.check("v1.0.0")

    # assert: not red (a local `release all` stays possible) and not silent (a check that did not run is
    # not a pass)
    out = _out(capsys)
    assert rc == 0
    assert "GITHUB_REF" in out and "not checked" in out


# --- origin ---------------------------------------------------------------------------------------------

def test_a_failed_fetch_is_red(lab, no_ref, tmp_path, capsys):
    # arrange
    _git(lab.work, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    # act
    rc = release.check("v1.0.0")

    # assert
    assert rc == 1
    assert "could not be fetched" in _out(capsys)


def test_no_origin_remote_is_red_at_the_fetch(lab, no_ref, capsys):
    # arrange
    _git(lab.work, "remote", "remove", "origin")

    # act
    rc = release.check("v1.0.0")

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "could not be fetched" in out and "Traceback" not in out


def test_a_commit_the_default_branch_does_not_carry_is_refused(lab, no_ref, capsys):
    # arrange
    _git(lab.work, "checkout", "-q", "-b", "feature")
    _commit(lab.work, "two")

    # act
    rc = release.check("v1.0.0")

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "does not carry" in out and "merge" in out


# --- tags -----------------------------------------------------------------------------------------------

def test_another_version_tag_at_head_is_refused(lab, no_ref, capsys):
    # arrange
    _git(lab.work, "tag", "v0.9.0")

    # act
    rc = release.check("v1.0.0")

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "v0.9.0" in out and "git describe" in out


def test_the_tag_itself_and_a_non_version_tag_at_head_are_no_obstacle(lab, no_ref):
    # arrange: a re-run, with an input tag of another scheme on the same commit
    _git(lab.work, "tag", "v1.0.0")
    _git(lab.work, "tag", "iol-17.18.02")
    _git(lab.work, "push", "-q", "origin", "refs/tags/v1.0.0")

    # act / assert
    assert release.check("v1.0.0") == 0


def test_a_tag_origin_carries_at_another_commit_is_taken(lab, no_ref, capsys):
    # arrange
    first = _sha(lab.work)
    _git(lab.work, "tag", "v1.0.0")
    _git(lab.work, "push", "-q", "origin", "refs/tags/v1.0.0")
    _commit(lab.work, "two")
    _git(lab.work, "push", "-q", "origin", "main")
    _git(lab.work, "tag", "-d", "v1.0.0")

    # act
    rc = release.check("v1.0.0")

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "choose the next version" in out and first[:7] in out


def test_a_tag_origin_carries_at_this_commit_is_an_unfinished_release(lab, no_ref, capsys):
    # arrange
    _git(lab.work, "tag", "v1.0.0")
    _git(lab.work, "push", "-q", "origin", "refs/tags/v1.0.0")

    # act
    rc = release.check("v1.0.0")

    # assert
    assert rc == 0
    assert "unfinished" in _out(capsys)


def test_origin_that_cannot_be_asked_about_the_tag_is_red(lab, no_ref, monkeypatch, capsys):
    # arrange: the fetch works, the ls-remote does not
    monkeypatch.setattr(gitops, "remote_tag_commit", lambda name: None)

    # act
    rc = release.check("v1.0.0")

    # assert
    assert rc == 1
    assert "could not be asked" in _out(capsys)


def test_a_new_version_passes(lab, no_ref):
    assert release.check("v1.0.0") == 0


def test_the_first_red_check_ends_the_run(lab, monkeypatch, capsys):
    # arrange: two reasons to refuse; only the first is reported
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")

    # act
    rc = release.check("0.99.0")

    # assert
    out = _out(capsys)
    assert rc == 1
    assert "vX.Y.Z" in out and "start the release from" not in out


def test_a_refused_check_cuts_and_pushes_nothing(lab, no_ref):
    # arrange
    _git(lab.work, "tag", "v0.9.0")

    # act
    release.check("v1.0.0")

    # assert
    assert lab.local_tags() == ["v0.9.0"] and lab.remote_tags() == {}
