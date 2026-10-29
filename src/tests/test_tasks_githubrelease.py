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
  shipped: { kind: release-assets, path: build/release/assets.json }
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


def _attach(tag="v1.0.0", files=("linux", "mac"), evidence=("proof",), assets="shipped") -> int:
    def run() -> int:
        return results.guarded(evidence, lambda: githubrelease.attach(tag, assets))
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
    assert githubrelease.attach("v1.0.0", "shipped") == 1
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
    assert bound.within({"files": ("linux", "mac")}, lambda: githubrelease.attach("v1.0.0", "shipped")) == 1
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


def test_attach_refuses_a_name_that_collides_with_a_sidecar(built, api, capsys):
    # the first file's sidecar `tool.sha256` would overwrite the second file, so it is refused before GitHub
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace("tool-{tag}-linux", "tool").replace(
        "tool-{tag}-mac", "tool.sha256"), encoding="utf-8")
    assert _attach() == 1
    _refused(api, capsys, "tool.sha256", "'linux'", "'mac'", "sidecar")


# --- attach: the draft, the uploads, the read-back, the record (si#553) ----------------------------------

DRAFT = 7
LINUX_NAME, MAC_NAME = "tool-v1.2.3-linux", "tool-v1.2.3-mac"


def _draft(api, tag="v1.2.3", rid=DRAFT, *, draft=True) -> None:
    api["releases"].append(githubstandin.release(rid, tag, draft=draft))


def _on_draft(api, rid=DRAFT) -> dict[str, bytes]:
    return {a["name"]: api["asset_bytes"][a["id"]] for a in api["assets"] if a["release_id"] == rid}


def _left(api, name: str, content: bytes = b"stale", rid=DRAFT) -> int:
    aid = max([a["id"] for a in api["assets"]], default=100) + 1
    api["assets"].append({"id": aid, "release_id": rid, "name": name, "size": len(content), "state": "uploaded",
                          "content_type": "", "browser_download_url": "https://github.example/x",
                          "digest": _sha(content)})
    api["asset_bytes"][aid] = content
    return aid


def _hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_attach_uploads_each_file_and_its_sidecar(built, api, capsys):
    _draft(api)
    assert _attach("v1.2.3") == 0
    assert _on_draft(api) == {
        LINUX_NAME: LINUX, f"{LINUX_NAME}.sha256": f"{_hex(LINUX)}  {LINUX_NAME}\n".encode(),
        MAC_NAME: MAC, f"{MAC_NAME}.sha256": f"{_hex(MAC)}  {MAC_NAME}\n".encode()}
    assert "attached 2 files" in _said(capsys)


def test_attach_replaces_an_asset_an_earlier_run_left(built, api):
    _draft(api)
    _left(api, LINUX_NAME, b"from an earlier run")
    _left(api, f"{LINUX_NAME}.sha256", b"old sidecar")
    assert _attach("v1.2.3") == 0
    assert _on_draft(api)[LINUX_NAME] == LINUX
    assert _on_draft(api)[f"{LINUX_NAME}.sha256"] == f"{_hex(LINUX)}  {LINUX_NAME}\n".encode()
    assert len([a for a in api["assets"] if a["name"] == LINUX_NAME]) == 1


def test_attach_removes_and_names_assets_it_did_not_upload(built, api, capsys):
    _draft(api)
    _left(api, "stray-binary", b"nobody tested me")
    _left(api, "other-release-asset", b"elsewhere", rid=99)
    assert _attach("v1.2.3") == 0
    assert "stray-binary" not in _on_draft(api) and len(_on_draft(api)) == 4
    assert [a["name"] for a in api["assets"] if a["release_id"] == 99] == ["other-release-asset"]
    assert "deleted the asset stray-binary" in _said(capsys)


def test_attach_refuses_without_a_draft(built, api, capsys):
    assert _attach("v1.2.3") == 1
    assert "no draft release for v1.2.3 to attach to" in _said(capsys)
    assert _writes(api) == [] and api["assets"] == []


def test_attach_refuses_a_published_release_and_uploads_nothing(built, api, capsys):
    _draft(api, draft=False)
    _left(api, "kept", b"published", rid=DRAFT)
    assert _attach("v1.2.3") == 1
    assert "already a published release" in _said(capsys)
    assert _writes(api) == [] and list(_on_draft(api)) == ["kept"]
    assert [r for r in api["requests"] if r[0] == "DELETE"] == []


def test_attach_is_red_when_github_reports_another_digest(built, api, capsys):
    _draft(api)
    api["asset_digest"] = "wrong"
    assert _attach("v1.2.3") == 1
    said = _said(capsys)
    assert LINUX_NAME in said and _hex(LINUX) in said and "re-run" in said and "another digest" in said
    assert not (built / "build" / "release" / "assets.json").exists()


def test_attach_is_red_when_github_reports_no_digest(built, api, capsys):
    _draft(api)
    api["asset_digest"] = "none"
    assert _attach("v1.2.3") == 1
    said = _said(capsys)
    assert LINUX_NAME in said and "no digest" in said and "re-run" in said
    assert not (built / "build" / "release" / "assets.json").exists()


def test_attach_writes_the_release_assets_record(built, api):
    _draft(api)
    assert _attach("v1.2.3") == 0
    base = "https://github.com/o/n/releases/download/v1.2.3/"
    record = json.loads((built / "build" / "release" / "assets.json").read_text(encoding="utf-8"))
    assert record == {"tag": "v1.2.3", "assets": [
        {"name": LINUX_NAME, "url_after_publish": base + LINUX_NAME, "sha256": _hex(LINUX),
         "sidecar": {"name": f"{LINUX_NAME}.sha256", "url_after_publish": base + f"{LINUX_NAME}.sha256",
                     "sha256": _hex(f"{_hex(LINUX)}  {LINUX_NAME}\n".encode())}},
        {"name": MAC_NAME, "url_after_publish": base + MAC_NAME, "sha256": _hex(MAC),
         "sidecar": {"name": f"{MAC_NAME}.sha256", "url_after_publish": base + f"{MAC_NAME}.sha256",
                     "sha256": _hex(f"{_hex(MAC)}  {MAC_NAME}\n".encode())}}]}


def test_attach_never_publishes(built, api):
    _draft(api)
    assert _attach("v1.2.3") == 0
    assert [r for r in api["requests"] if r[0] == "PATCH"] == []
    assert api["releases"][0]["draft"] is True


def test_attach_names_what_is_on_the_draft_when_an_upload_is_refused(built, api, capsys):
    _draft(api)
    _left(api, "stray", b"x")
    api["fail"][("POST", f"/uploads/repos/o/n/releases/{DRAFT}/assets")] = 500
    assert _attach("v1.2.3") == 1
    said = _said(capsys)
    assert LINUX_NAME in said and "stray" in said and "re-run" in said


def test_attach_refuses_a_record_artifact_without_a_path(built, api):
    (built / "sample.yaml").write_text(ATTACH_MANIFEST.replace(", path: build/release/assets.json", ""),
                                       encoding="utf-8")
    _draft(api)
    with pytest.raises(ValueError, match="path"):
        _attach("v1.2.3")
    assert api["requests"] == []


def test_attach_refuses_a_record_that_is_not_a_release_assets_artifact(built, api):
    _draft(api)
    with pytest.raises(ValueError, match="release-assets"):
        _attach("v1.2.3", assets="proof")
    assert api["requests"] == []


def test_attach_removes_an_earlier_record_before_it_asks_github(built, api):
    record = built / "build" / "release" / "assets.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}", encoding="utf-8")
    assert _attach("v1.2.3") == 1   # no draft
    assert not record.exists()


def test_attach_command_hands_the_bound_release_assets_name_to_the_body():
    # the catalogue declares no `params: assets:`, so the pin comes from the `release-assets` output port's
    # `param = "assets"` alone; the loader pins it, and the cli's wrapper calls the body with it
    import inspect

    from simplon.manifest import catalogue
    from simplon.manifest import load as manifest_mod
    text = ("product: demo\n"
            "ci:\n"
            "  build:\n    commands:\n"
            "      tool: { task: \"build:image-file\", consumes: { image: img }, produces: { file: linux } }\n"
            "  test:\n    commands:\n"
            "      tool: { task: \"test:file\", consumes: { file: linux }, produces: { test-result: proof } }\n"
            "  release:\n    commands:\n"
            "      attach:\n"
            "        task: \"release:github-attach\"\n"
            "        consumes: { files: [linux], evidence: [proof] }\n"
            "        produces: { release-assets: shipped }\n"
            "artifacts:\n"
            "  img: { kind: image, registry: ghcr.io/o, repository: k, dockerfile: Dockerfile, context: . }\n"
            "  linux: { kind: file, path: build/tool-linux, asset_name: \"tool-{tag}-linux\" }\n"
            "  proof: { kind: test-result, path: build/proof.json }\n"
            "  shipped: { kind: release-assets, path: build/release/assets.json }\n")
    spec = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml").spec_for(
        "release", "attach")
    assert spec.with_["assets"] == "shipped"
    assert spec.consumes["files"] == ("linux",)
    assert "assets" in inspect.signature(githubrelease.attach).parameters

    import dataclasses

    import typer

    from simplon import cli
    seen: dict[str, object] = {}

    def body(tag: str = "", assets: str = "") -> int:
        seen.update(tag=tag, assets=assets)
        return 0

    # no ports bound for the call itself: the wrapper's evidence and record checks need a product on disk
    wrapper = cli._bound(body, dataclasses.replace(spec, produces={}, consumes={}), where="release attach")
    with pytest.raises(typer.Exit) as left:
        wrapper(tag="v1.2.3")
    assert left.value.exit_code == 0 and seen == {"tag": "v1.2.3", "assets": "shipped"}


def test_attach_removes_an_earlier_record_when_a_check_before_github_refuses(built, api):
    record = built / "build" / "release" / "assets.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("{}", encoding="utf-8")
    (built / "build" / "tool-mac").write_bytes(b"changed after its test")
    assert _attach("v1.2.3") == 1
    assert not record.exists() and api["requests"] == []


def test_attach_names_the_stray_it_could_not_delete(built, api, capsys):
    _draft(api)
    _left(api, "stray-binary", b"x")
    api["fail"][("DELETE", "/repos/o/n/releases/assets/")] = 500
    assert _attach("v1.2.3") == 1
    said = _said(capsys)
    assert "refused to delete stray-binary" in said and "re-run" in said and LINUX_NAME in said
    assert f"refused {MAC_NAME}.sha256" not in said


def test_attach_says_nothing_was_changed_when_the_first_listing_fails(built, api, capsys):
    _draft(api)
    api["fail"][("GET", f"/repos/o/n/releases/{DRAFT}/assets")] = 500
    assert _attach("v1.2.3") == 1
    said = _said(capsys)
    assert "nothing on the draft v1.2.3 was changed" in said and "not publishable" not in said
    assert [r for r in api["requests"] if r[0] in ("POST", "DELETE")] == []
