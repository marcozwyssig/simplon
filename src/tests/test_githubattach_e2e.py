"""`release:github-attach` against a REAL throwaway draft release (si#553).

OPT-IN, and NOT RUN IN CI: this writes to a real repository. It is skipped unless
`SIMPLON_E2E_GITHUB_REPO=marcozwyssig/simplon` is set and a GitHub token is available (`GITHUB_TOKEN`, else
`gh auth token`). Marco allowed throwaway drafts on marcozwyssig/simplon for this test on 2026-10-29; the
repository is checked by name, so the variable cannot point the test at another one.

Only DRAFT releases tagged `v0.0.0-si553-<uuid8>` are created, and never a tag: a draft needs no tag on origin
and is never published here. The fixture deletes its draft in a `finally` and then asserts that no release
with that tag and no remote tag remains, so a run that cannot clean up is red rather than quiet.

    SIMPLON_E2E_GITHUB_REPO=marcozwyssig/simplon deploy/orchestrator/.venv/bin/python -m pytest \\
        tests/test_githubattach_e2e.py -q

GitHub's release LISTING lags a create by several seconds (measured: a draft `create_git_release` answered was
missing from `get_releases()`), and `_one_draft` reads that listing, so a production pipeline with no time
between `draft` and `attach` inherits the lag and may be told there is no draft. Recorded for the maintainer;
`attach` is not changed. This test waits for the listing, and tears down by the created release's id.

The stand-in server of `test_tasks_githubrelease.py` confirms only what was written into it; this is the
measurement against GitHub's own digests, name rules and asset listing.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import requests

from github.Repository import Repository

from simplon.adapters import github
from simplon.manifest import bound, context, results
from simplon.tasks import gitops, githubrelease

REPO = "marcozwyssig/simplon"


def _token() -> str:
    """`GITHUB_TOKEN`, else `gh auth token` with a time limit: this runs at collection, and the kernel's own
    `githubpackages.token()` puts none on `gh`, so a hung `gh` would hang every collection of the suite."""
    held = os.environ.get("GITHUB_TOKEN", "").strip()
    if held:
        return held
    try:
        shown = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return shown.stdout.strip() if shown.returncode == 0 else ""


pytestmark = pytest.mark.skipif(
    os.environ.get("SIMPLON_E2E_GITHUB_REPO") != REPO or not _token(),
    reason=f"opt-in: writes to the real repository {REPO}; set SIMPLON_E2E_GITHUB_REPO={REPO} and a token")

MANIFEST = """product: sample
artifacts:
  notes: { kind: release-notes, path: build/release/notes.md }
  a: { kind: file, path: build/tool-a, asset_name: "si553-{tag}-a" }
  b: { kind: file, path: build/tool-b, asset_name: "si553-{tag}-b" }
  proof: { kind: test-result, path: build/proof.json }
  shipped: { kind: release-assets, path: build/release/assets.json }
"""
A, B = b"si553 e2e a\n", b"si553 e2e b\n"


def _hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_record(root: Path, a: bytes = A, b: bytes = B) -> None:
    runs = [{"reference": "build/tool-a", "id": "sha256:" + _hex(a)},
            {"reference": "build/tool-b", "id": "sha256:" + _hex(b)}]
    (root / "build" / "proof.json").write_text(json.dumps({"verdict": 0, "runs": runs}), encoding="utf-8")


def _remote_tags(pattern: str) -> str:
    return subprocess.run(["git", "ls-remote", "--tags", "origin", pattern], check=True, capture_output=True,
                          text=True, cwd=Path(__file__).resolve().parent).stdout.strip()


def _listed(repo, tag: str, *, present: bool) -> list:
    """The releases for `tag` once GitHub's LISTING agrees with what was just done. Measured: a draft that
    `create_git_release` answered is missing from `get_releases()` for several seconds, and a deleted one
    lingers there. A run in CI sits minutes between `draft` and `attach`, so this waiting is the test's, not
    the task's."""
    found: list = []
    for _ in range(30):
        found = github.releases_for(repo, tag)
        if bool(found) == present:
            return found
        time.sleep(2)
    return found


@pytest.fixture
def real(tmp_path, monkeypatch):
    """A product with two files and a green record for each, and a real draft release for a unique tag."""
    root = tmp_path
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "start"], check=True)
    (root / "sample.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "build" / "release").mkdir(parents=True)
    (root / "build" / "release" / "notes.md").write_text("## si553 e2e\n\nthrowaway draft\n", encoding="utf-8")
    (root / "build" / "tool-a").write_bytes(A)
    (root / "build" / "tool-b").write_bytes(B)
    _write_record(root)
    monkeypatch.setattr(context, "_current", context.ProductContext("sample", root, root / "sample.yaml"))
    gitops.configure(root)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("GITHUB_TOKEN", _token())
    # the tmp product's own commit does not exist on GitHub, and a draft's target must: point it at main's head
    head = subprocess.run(["git", "ls-remote", "origin", "refs/heads/main"], check=True, capture_output=True,
                          text=True, cwd=Path(__file__).resolve().parent).stdout.split()[0]
    monkeypatch.setattr(gitops, "head_commit", lambda: head)
    tag = f"v0.0.0-si553-{uuid.uuid4().hex[:8]}"
    repo = github.repository()
    # The id of every release this test's create call answered, so teardown does not depend on the listing
    # (which lags a create): it deletes by id, and only what was created here.
    created: list[int] = []
    make = Repository.create_git_release

    def remembered(self, *args, **kwargs):
        made = make(self, *args, **kwargs)
        created.append(made.id)
        return made

    monkeypatch.setattr(Repository, "create_git_release", remembered)
    try:
        assert bound.within({}, lambda: githubrelease.draft("notes", tag)) == 0
        assert _listed(repo, tag, present=True), f"the draft {tag} never appeared in the release listing"
        yield root, tag, repo
    finally:
        _teardown(repo, tag, created)


def _teardown(repo, tag: str, created: list[int]) -> None:
    """Delete this test's draft(s) by id, then check nothing remains; every step runs whatever the others did,
    and a failure names the tag and id so a leftover can be removed by hand."""
    failures: list[str] = []
    for rid in created:
        try:
            release = repo.get_release(rid)
            if release.tag_name != tag or not release.draft:
                failures.append(f"release {rid} is not this test's draft {tag}: not deleted")
                continue
            release.delete_release()
        except (github.GithubException, requests.exceptions.RequestException) as error:
            failures.append(f"could not delete the draft {tag} (release id {rid}): {error}; delete it by hand")
    if not created:
        failures.append(f"no create call was seen for {tag}; check by hand: "
                        f"gh api repos/{REPO}/releases --paginate -q '.[]|select(.tag_name==\"{tag}\")|.id'")
    try:
        if _listed(repo, tag, present=False):
            failures.append(f"the draft {tag} (ids {created}) is still listed after its delete")
    except (github.Unanswered, github.GithubException, requests.exceptions.RequestException) as error:
        failures.append(f"could not list the releases to check {tag} is gone: {error}")
    try:
        if _remote_tags(tag):
            failures.append(f"origin carries the tag {tag}")
    except (subprocess.CalledProcessError, OSError) as error:
        failures.append(f"could not ask origin whether it carries {tag}: {error}")
    assert not failures, "; ".join(failures)


def _attach(tag: str) -> int:
    return bound.within({"files": ("a", "b")}, lambda: results.guarded(
        ("proof",), lambda: githubrelease.attach(tag, "shipped")))


def _draft_assets(repo, tag: str) -> dict:
    (release,) = _listed(repo, tag, present=True)
    assert release.draft
    return {a.name: a for a in github.assets(release)}


def test_attach_puts_both_files_and_sidecars_on_a_real_draft(real):
    root, tag, repo = real
    assert _attach(tag) == 0
    held = _draft_assets(repo, tag)
    a, b = f"si553-{tag}-a", f"si553-{tag}-b"
    assert sorted(held) == sorted([a, b, a + ".sha256", b + ".sha256"])
    assert held[a].digest == "sha256:" + _hex(A)
    assert held[b].digest == "sha256:" + _hex(B)
    for name, raw in ((a, A), (b, B)):
        side = f"{_hex(raw)}  {name}\n".encode()
        assert held[name + ".sha256"].digest == "sha256:" + _hex(side)


def test_a_rerun_replaces_and_a_foreign_asset_is_removed(real, tmp_path_factory):
    root, tag, repo = real
    assert _attach(tag) == 0
    (release,) = _listed(repo, tag, present=True)
    foreign = tmp_path_factory.mktemp("foreign") / "foreign"
    foreign.write_bytes(b"nobody tested this\n")
    github.upload(release, foreign, "si553-foreign")
    assert "si553-foreign" in _draft_assets(repo, tag)
    assert _attach(tag) == 0
    held = _draft_assets(repo, tag)
    assert "si553-foreign" not in held
    assert len(held) == 4


def test_the_record_names_the_after_publish_urls(real):
    root, tag, repo = real
    assert _attach(tag) == 0
    record = json.loads((root / "build" / "release" / "assets.json").read_text(encoding="utf-8"))
    base = f"https://github.com/{REPO}/releases/download/{tag}/"
    assert record["tag"] == tag
    assert [a["url_after_publish"] for a in record["assets"]] == [base + f"si553-{tag}-a", base + f"si553-{tag}-b"]
    assert record["assets"][0]["sidecar"]["url_after_publish"] == base + f"si553-{tag}-a.sha256"
    held = _draft_assets(repo, tag)
    for entry in record["assets"]:
        assert held[entry["name"]].digest == "sha256:" + entry["sha256"]
        assert held[entry["sidecar"]["name"]].digest == "sha256:" + entry["sidecar"]["sha256"]


def test_a_file_changed_after_its_record_uploads_nothing(real, capsys):
    root, tag, repo = real
    (root / "build" / "tool-a").write_bytes(b"changed after the test\n")
    assert _attach(tag) == 1
    out = capsys.readouterr()
    assert "the file changed after its test" in out.out + out.err
    assert _draft_assets(repo, tag) == {}
