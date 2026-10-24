"""si#535: `adapters.repofile` - one file committed to a branch of another repository, in three outcomes,
against the real-HTTP stand-in (never a mock of PyGithub: see the stand-in's docstring)."""
from __future__ import annotations

from pathlib import Path

import pytest

import githubstandin
from simplon.adapters import repofile
from simplon.adapters.repofile import State

CONTENTS = f"/repos/{githubstandin.REPO}/contents"


@pytest.fixture
def standin(monkeypatch):
    """A running stand-in, with `GITHUB_API_URL` pointed at it."""
    shared = githubstandin.state()
    base, stop = githubstandin.serve(shared)
    monkeypatch.setenv("GITHUB_API_URL", base)
    try:
        yield shared
    finally:
        stop()


def _write(content: bytes, *, branch: str = "main", path: str = "pkg/x.txt", token: str = "t"):
    return repofile.write(githubstandin.REPO, branch, path, content, "update x", token)


def _puts(shared: dict) -> list:
    return [r for r in shared["requests"] if r[0] == "PUT"]


def test_a_new_file_is_written_and_names_its_commit(standin):
    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.WRITTEN
    assert outcome.commit and outcome.commit in standin["commits"]
    assert outcome.reason == ""
    assert standin["files"][("main", "pkg/x.txt")] == b"new\n"


def test_a_changed_file_is_written_with_the_old_sha(standin):
    # arrange
    standin["files"][("main", "pkg/x.txt")] = b"old\n"

    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.WRITTEN
    [(_, _, body)] = _puts(standin)
    assert body["sha"] == githubstandin.blob_sha(b"old\n")
    assert body["branch"] == "main"
    assert standin["files"][("main", "pkg/x.txt")] == b"new\n"


def test_identical_content_is_already_current_and_sends_no_put(standin):
    # arrange
    standin["files"][("main", "pkg/x.txt")] = b"same\n"

    # act
    outcome = _write(b"same\n")

    # assert
    assert outcome.state is State.CURRENT
    assert outcome.commit == "" and outcome.reason == ""
    assert _puts(standin) == []


def test_a_trailing_newline_is_a_change(standin):
    # arrange
    standin["files"][("main", "pkg/x.txt")] = b"same"

    # act
    outcome = _write(b"same\n")

    # assert
    assert outcome.state is State.WRITTEN
    assert standin["files"][("main", "pkg/x.txt")] == b"same\n"


def test_a_forbidden_put_is_refused_with_its_status(standin):
    # arrange
    standin["fail"][("PUT", CONTENTS)] = 403

    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.REFUSED
    assert "HTTP 403" in outcome.reason
    assert "forced 403" in outcome.reason
    assert outcome.commit == ""


def test_a_moved_sha_is_refused_not_retried(standin):
    # arrange: another writer commits between our read and our PUT
    standin["files"][("main", "pkg/x.txt")] = b"old\n"
    standin["race"] = b"theirs\n"

    # act
    outcome = _write(b"ours\n")

    # assert
    assert outcome.state is State.REFUSED
    assert "HTTP 409" in outcome.reason
    assert len(_puts(standin)) == 1
    assert standin["files"][("main", "pkg/x.txt")] == b"theirs\n"


def test_an_unknown_branch_is_refused(standin):
    # arrange: the default branch holds the file, the named branch does not exist
    standin["files"][("main", "pkg/x.txt")] = b"old\n"

    # act
    outcome = _write(b"new\n", branch="nope")

    # assert
    assert outcome.state is State.REFUSED
    assert "HTTP 404" in outcome.reason
    assert "nope" in outcome.reason
    assert standin["files"] == {("main", "pkg/x.txt"): b"old\n"}
    assert standin["commits"] == {}


def test_a_directory_path_is_refused(standin):
    # arrange
    standin["files"][("main", "pkg/x.txt")] = b"x\n"

    # act
    outcome = _write(b"new\n", path="pkg")

    # assert
    assert outcome.state is State.REFUSED
    assert "directory" in outcome.reason
    assert _puts(standin) == []


@pytest.mark.parametrize("token", ["", "  \n"])
def test_an_empty_token_is_refused_before_any_request(standin, token):
    # act
    outcome = _write(b"new\n", token=token)

    # assert
    assert outcome.state is State.REFUSED
    assert "token" in outcome.reason
    assert githubstandin.REPO in outcome.reason
    assert standin["requests"] == []


def test_a_readback_that_differs_is_refused(standin):
    # arrange
    standin["corrupt_readback"] = True

    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.REFUSED
    assert "read back" in outcome.reason
    [commit] = standin["commits"]
    assert commit in outcome.reason


def test_a_file_github_will_not_inline_is_refused_before_any_put(standin):
    # arrange: over 1 MB, the contents API answers `encoding: "none"` and no content
    standin["files"][("main", "pkg/x.txt")] = b"old\n"
    standin["large"] = {"branch"}

    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.REFUSED
    assert "pkg/x.txt" in outcome.reason
    assert "none" in outcome.reason
    assert _puts(standin) == []


def test_a_readback_github_will_not_inline_is_refused_naming_the_commit(standin):
    # arrange
    standin["large"] = {"commit"}

    # act
    outcome = _write(b"new\n")

    # assert: the commit landed, and the verdict says which one
    assert outcome.state is State.REFUSED
    [commit] = standin["commits"]
    assert commit in outcome.reason
    assert "none" in outcome.reason


def test_a_failed_readback_is_refused_naming_the_commit(standin):
    # arrange
    standin["fail_readback"] = 502

    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.REFUSED
    [commit] = standin["commits"]
    assert f"read back failed at commit {commit}" in outcome.reason
    assert "HTTP 502" in outcome.reason


def test_an_unreachable_api_is_refused(monkeypatch):
    # arrange: a port nothing listens on
    shared = githubstandin.state()
    base, stop = githubstandin.serve(shared)
    stop()
    monkeypatch.setenv("GITHUB_API_URL", base)

    # act
    outcome = _write(b"new\n")

    # assert
    assert outcome.state is State.REFUSED
    assert "could not reach" in outcome.reason


def test_the_three_states_are_three_distinct_words():
    # act
    values = [s.value for s in State]

    # assert
    assert len(values) == 3
    assert len(set(values)) == 3
    assert all(v.strip() for v in values)


def test_the_adapter_names_no_package_manager():
    # act
    source = Path(repofile.__file__).read_text(encoding="utf-8").lower()

    # assert: a later package manager reuses it as is
    assert "brew" not in source
    assert "formula" not in source
