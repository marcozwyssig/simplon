"""si#486: `release:github-unpublished`, `-draft` and `-publish`, against a local stand-in of the API."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import githubstandin
from simplon.manifest import bound, context, results
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


# --- the final review's fix pass ------------------------------------------------------------------------

def test_draft_checks_the_answer_is_still_a_draft(api, capsys):
    # arrange: GitHub answers the reuse with a release that is no longer a draft
    api["releases"].append(githubstandin.release(7, "v1.0.0", draft=True))
    api["force_public"] = True

    # act / assert: a release made public before the build is red, and said
    assert githubrelease.draft("notes", "v1.0.0") == 1
    assert "not a draft" in _said(capsys)


def test_reuse_and_publish_keep_a_prerelease_a_prerelease(api, monkeypatch):
    # arrange: a draft somebody marked as a pre-release by hand
    _origin_has(monkeypatch, "a" * 40)
    api["releases"].append({**githubstandin.release(7, "v2.0.0-rc1", draft=True), "prerelease": True})

    # act
    assert githubrelease.draft("notes", "v2.0.0-rc1") == 0
    assert githubrelease.publish("v2.0.0-rc1") == 0

    # assert: neither PATCH turned it into a full release
    patches = [body for method, _, body in api["requests"] if method == "PATCH"]
    assert len(patches) == 2 and all(body.get("prerelease") is True for body in patches)


# --- attach: every refusal before GitHub is asked (si#553) ----------------------------------------------

ATTACH_MANIFEST = """product: sample
artifacts:
  linux: { kind: file, path: build/tool-linux, asset_name: "tool-{tag}-linux" }
  mac: { kind: file, path: build/tool-mac, asset_name: "tool-{tag}-mac" }
  proof: { kind: test-result, path: build/proof.json }
"""
LINUX, MAC = b"linux bytes", b"mac bytes"


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _record(root: Path, runs: list, verdict: int = 0) -> None:
    (root / "build" / "proof.json").write_text(json.dumps({"verdict": verdict, "runs": runs}), encoding="utf-8")


def _both_tested(root: Path) -> None:
    _record(root, [{"reference": "build/tool-linux", "id": _sha(LINUX)},
                   {"reference": "build/tool-mac", "id": _sha(MAC)}])


@pytest.fixture
def built(api, product, monkeypatch):
    """Two built files, a manifest that declares them, and a green record naming both."""
    (product / "sample.yaml").write_text(ATTACH_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", product, product / "sample.yaml"))
    (product / "build").mkdir(exist_ok=True)
    (product / "build" / "tool-linux").write_bytes(LINUX)
    (product / "build" / "tool-mac").write_bytes(MAC)
    _both_tested(product)
    return product


def _attach(tag="v1.0.0", files=("linux", "mac"), evidence=("proof",)) -> int:
    def run() -> int:
        return results.guarded(evidence, lambda: githubrelease.attach(tag))
    return bound.within({"files": files} if files is not None else {}, run)


def _refused(api, capsys, *phrases) -> None:
    said = _said(capsys)
    for phrase in phrases:
        assert phrase in said, said
    assert api["requests"] == []


def test_attach_refuses_without_a_tag(built):
    with pytest.raises(ValueError, match="which release"):
        _attach(tag="")


def test_attach_refuses_an_invalid_tag(built):
    with pytest.raises(ValueError, match="not a tag git would accept"):
        _attach(tag="a b")


@pytest.mark.parametrize("files", [None, ()])
def test_attach_refuses_bound_to_no_files(built, api, capsys, files):
    assert _attach(files=files) == 1
    _refused(api, capsys, "bound to no files", "consumes: { files: [...] }")


def test_attach_refuses_called_outside_a_command(built, api, capsys):
    assert githubrelease.attach("v1.0.0") == 1
    _refused(api, capsys, "bound to no files")


def test_attach_refuses_an_entry_with_no_asset_name(built, api, capsys):
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace(', asset_name: "tool-{tag}-mac"', ""),
                                       encoding="utf-8")
    assert _attach() == 1
    _refused(api, capsys, "'mac'", "no `asset_name`")


@pytest.mark.parametrize("name", [".hidden", "a/b", "tool linux", "tool\u00e4", "tool*", "tool~1", "a:b"])
def test_attach_refuses_an_asset_name_github_would_rewrite(built, api, capsys, name):
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace("tool-{tag}-mac", name), encoding="utf-8")
    assert _attach() == 1
    _refused(api, capsys, "'mac'", "GitHub would store another name", "release-assets")


def test_attach_refuses_an_empty_asset_name_in_the_schema(built, api, capsys):
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace("tool-{tag}-mac", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="'asset_name' must be a non-empty string"):
        _attach()
    assert api["requests"] == []


def test_attach_checks_the_name_after_the_tag_is_expanded(built, api, capsys):
    # `{tag}` is only a placeholder: a tag with a character GitHub rewrites makes the expanded name wrong
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace("tool-{tag}-mac", "{tag}"), encoding="utf-8")
    assert _attach(tag="v1.0.0#rc") == 1
    _refused(api, capsys, "'mac'", "GitHub would store another name", "v1.0.0#rc")


def test_attach_refuses_two_entries_with_the_same_expanded_name(built, api, capsys):
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace("tool-{tag}-mac", "tool-{tag}-linux"),
                                       encoding="utf-8")
    assert _attach() == 1
    _refused(api, capsys, "tool-v1.0.0-linux", "'linux'", "'mac'")


def test_attach_refuses_a_bound_file_missing_on_disk(built, api, capsys):
    (built / "build" / "tool-mac").unlink()
    assert _attach() == 1
    _refused(api, capsys, "'mac'", "build/tool-mac", "run the command that produces it first")


def test_attach_refuses_when_no_evidence_is_bound(built, api, capsys):
    assert bound.within({"files": ("linux", "mac")}, lambda: githubrelease.attach("v1.0.0")) == 1
    _refused(api, capsys, "no evidence bound", "`evidence`")


def test_attach_refuses_a_file_no_subject_names(built, api, capsys):
    _record(built, [{"reference": "build/tool-linux", "id": _sha(LINUX)}])
    assert _attach() == 1
    _refused(api, capsys, "build/tool-mac", "no test names it")


def test_attach_refuses_a_file_changed_after_its_test(built, api, capsys):
    (built / "build" / "tool-mac").write_bytes(b"changed")
    assert _attach() == 1
    _refused(api, capsys, "build/tool-mac", _sha(MAC), _sha(b"changed"), "changed after its test")


def test_attach_refuses_a_red_record_before_reading_the_files(built, api, capsys):
    _record(built, [{"reference": "build/tool-linux", "id": _sha(LINUX)}], verdict=1)
    assert _attach() == 1
    _refused(api, capsys, "is red")


def test_attach_that_passes_every_check_is_not_yet_implemented_and_never_green(built, api):
    # the guard against `return 0`: a green run that attached nothing (Task 4 replaces the raise)
    with pytest.raises(NotImplementedError, match="si#553 Task 4"):
        _attach()
    assert api["requests"] == []
