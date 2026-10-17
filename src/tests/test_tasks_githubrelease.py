"""si#486: `release:github-unpublished`, `-draft` and `-publish`, against a local stand-in of the API."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import githubstandin
from simplon.manifest import context
from simplon.tasks import gitops, githubrelease

NOTES = "## v1.0.0\n\n- a merge\n"
MANIFEST = "product: sample\nartifacts:\n  notes: { kind: release-notes, path: build/release/notes.md }\n"


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A one-commit repository with a notes artifact, registered as the process' product."""
    root = tmp_path
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "start"], check=True)
    (root / "sample.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "build" / "release").mkdir(parents=True)
    (root / "build" / "release" / "notes.md").write_text(NOTES, encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", root, root / "sample.yaml"))
    gitops.configure(root)
    return root


@pytest.fixture
def api(monkeypatch, product):
    shared = githubstandin.state()
    base, stop = githubstandin.serve(shared)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_API_URL", base)
    monkeypatch.setenv("GITHUB_REPOSITORY", githubstandin.REPO)
    try:
        yield shared
    finally:
        stop()


def _origin_has(monkeypatch, answer):
    monkeypatch.setattr(gitops, "remote_tag_commit", lambda name: answer)


def _said(capsys) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def _writes(api) -> list:
    return [r for r in api["requests"] if r[0] in ("POST", "PATCH")]


# --- unpublished ---------------------------------------------------------------------------------------

def test_unpublished_is_green_for_none_and_for_a_draft(api, capsys):
    assert githubrelease.unpublished("v1.0.0") == 0
    api["releases"].append(githubstandin.release(1, "v1.0.0", draft=True))
    assert githubrelease.unpublished("v1.0.0") == 0
    assert "no published release" in _said(capsys)


def test_unpublished_refuses_a_published_release(api, capsys):
    api["releases"].append(githubstandin.release(1, "v1.0.0", draft=False))
    assert githubrelease.unpublished("v1.0.0") == 1
    said = _said(capsys)
    assert "github.example/o/n/releases/tag/v1.0.0" in said and "never overwritten" in said


def test_unpublished_is_red_when_the_api_does_not_answer(api, capsys):
    api["fail"][("GET", "/repos/o/n/releases/tags")] = 500
    assert githubrelease.unpublished("v1.0.0") == 1
    api["fail"].clear()
    api["repo"] = None
    assert githubrelease.unpublished("v1.0.0") == 1
    assert "could not tell" in _said(capsys)


# --- draft ---------------------------------------------------------------------------------------------

def test_draft_is_created_at_head_with_the_notes_as_body(api, capsys):
    assert githubrelease.draft("notes", "v1.0.0") == 0
    [(method, _, body)] = _writes(api)
    assert method == "POST"
    assert body["tag_name"] == "v1.0.0" and body["name"] == "v1.0.0" and body["body"] == NOTES
    assert body["draft"] is True and body["target_commitish"] == gitops.head_commit()
    assert "created the draft release v1.0.0" in _said(capsys)


def test_draft_reuse_replaces_the_body_and_stays_a_draft(api, capsys):
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True, body="old"))
    assert githubrelease.draft("notes", "v1.0.0") == 0
    [(method, path, body)] = _writes(api)
    assert (method, path) == ("PATCH", "/repos/o/n/releases/7")
    assert body["draft"] is True, "a reuse without draft=True publishes the draft before the build"
    assert body["body"] == NOTES and len(api["releases"]) == 1
    assert "reused the draft release v1.0.0" in _said(capsys)


def test_draft_reuse_with_the_tag_already_on_origin(api, monkeypatch):
    _origin_has(monkeypatch, gitops.head_commit())
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True, body="old"))
    assert githubrelease.draft("notes", "v1.0.0") == 0
    assert api["releases"][0]["body"] == NOTES and api["releases"][0]["draft"] is True


def test_draft_refuses_a_published_release(api, capsys):
    api["releases"].append(githubstandin.release(1, "v1.0.0", draft=False))
    assert githubrelease.draft("notes", "v1.0.0") == 1
    assert _writes(api) == []
    assert "already a published release" in _said(capsys)


def test_draft_beside_a_published_release_counts_as_published(api):
    api["releases"] += [githubstandin.release(1, "v1.0.0", draft=True),
                        githubstandin.release(2, "v1.0.0", draft=False)]
    assert githubrelease.draft("notes", "v1.0.0") == 1
    assert _writes(api) == []


def test_draft_refuses_two_drafts_and_names_both(api, capsys):
    api["releases"] += [githubstandin.release(1, "v1.0.0", draft=True),
                        githubstandin.release(2, "v1.0.0", draft=True)]
    assert githubrelease.draft("notes", "v1.0.0") == 1
    assert _writes(api) == []
    said = _said(capsys)
    assert "untagged-1" in said and "untagged-2" in said


def test_draft_refuses_missing_and_empty_notes(api, product, capsys):
    notes = product / "build" / "release" / "notes.md"
    notes.write_text("  \n", encoding="utf-8")
    assert githubrelease.draft("notes", "v1.0.0") == 1
    notes.unlink()
    assert githubrelease.draft("notes", "v1.0.0") == 1
    said = _said(capsys)
    assert "release:notes" in said
    assert "previous" not in said, "si#477 made firn's 'once the tag exists it is the previous one' false"
    assert api["requests"] == [], "the notes are read before GitHub is asked anything"


# --- publish -------------------------------------------------------------------------------------------

def test_publish_turns_the_draft_public(api, monkeypatch, capsys):
    _origin_has(monkeypatch, "a" * 40)
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True, body=NOTES))
    assert githubrelease.publish("v1.0.0") == 0
    [(method, path, body)] = _writes(api)
    assert (method, path) == ("PATCH", "/repos/o/n/releases/7")
    assert body["draft"] is False and body["tag_name"] == "v1.0.0" and body["body"] == NOTES
    assert "published the GitHub Release v1.0.0" in _said(capsys)


def test_publish_checks_the_answer_not_the_status(api, monkeypatch, capsys):
    _origin_has(monkeypatch, "a" * 40)
    api["keep_draft"] = True
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True))
    assert githubrelease.publish("v1.0.0") == 1
    assert "stays a draft" in _said(capsys)


def test_publish_500_leaves_the_draft_and_says_a_rerun_finishes(api, monkeypatch, capsys):
    _origin_has(monkeypatch, "a" * 40)
    api["fail"][("PATCH", "/repos/o/n/releases/")] = 500
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True))
    assert githubrelease.publish("v1.0.0") == 1
    assert api["releases"][0]["draft"] is True
    assert "re-run" in _said(capsys)


@pytest.mark.parametrize("answer, words", [("", "default branch"), (None, "could not ask")])
def test_publish_refuses_without_the_tag_on_origin(api, monkeypatch, capsys, answer, words):
    _origin_has(monkeypatch, answer)
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True))
    assert githubrelease.publish("v1.0.0") == 1
    assert words in _said(capsys)
    assert api["requests"] == [], "origin is asked before GitHub"


def test_publish_refuses_when_there_is_no_draft(api, monkeypatch, capsys):
    _origin_has(monkeypatch, "a" * 40)
    assert githubrelease.publish("v1.0.0") == 1
    assert "release:github-draft" in _said(capsys)


def test_publish_on_an_already_published_release_is_rc_1(api, monkeypatch, capsys):
    _origin_has(monkeypatch, "a" * 40)
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=False))
    assert githubrelease.publish("v1.0.0") == 1
    assert _writes(api) == []
    assert "nothing was changed" in _said(capsys)


# --- usage ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tag", ["", "a..b"])
def test_an_invalid_tag_is_refused_before_any_request(api, tag):
    for call in (lambda: githubrelease.unpublished(tag), lambda: githubrelease.draft("notes", tag),
                 lambda: githubrelease.publish(tag)):
        with pytest.raises(ValueError):
            call()
    assert api["requests"] == []


def test_draft_without_an_artifact_is_refused_by_name(api):
    with pytest.raises(ValueError, match="which artifact"):
        githubrelease.draft("", "v1.0.0")
    with pytest.raises(ValueError, match="no artifact 'nope'"):
        githubrelease.draft("nope", "v1.0.0")
