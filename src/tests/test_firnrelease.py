"""`simplon.adapters.firnrelease` - firn's private release: the pin, its assets, a checked download (si#900).

The GitHub and transfer seams are stubbed here: these tests pin how each answer is TOLD APART (no token,
an unreadable release, a missing asset, a wrong checksum), which a stub can confirm. Whether the real
release answers the way the stubs assume was measured against marcozwyssig/firn v0.19.0 itself (the si#900
Task 1 report): a stub confirms exactly the assumptions written into it.
"""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplon.adapters import fetch, firnrelease, github, githubpackages

FIRN = "ghcr.io/marcozwyssig/firn"


def _command(task, image):
    return {"task": task, "with": {"image": image}}


def _manifest(test_image, build_image):
    """The real shape: `ci: <phase group>: commands: <name>: {task, with: {image}}`."""
    return {"ci": {"test": {"commands": {"model": _command("test:model", test_image)}},
                   "build": {"commands": {
                       "model": _command("build:model", build_image),
                       "model-binary": _command("build:model-binary",
                                                "ghcr.io/marcozwyssig/firn-builder:v0.18.0")}}}}


# --- the pin ----------------------------------------------------------------------------------------


def test_pinned_tag_is_the_one_firn_image_tag():
    data = _manifest(f"{FIRN}:v0.19.0", f"{FIRN}:v0.19.0@sha256:" + "a" * 64)
    assert firnrelease.pinned_tag(data, "x.yaml") == "v0.19.0"


def test_pinned_tag_reads_a_support_command_too():
    data = {"support": {"commands": {"lint": _command("test:model", f"{FIRN}:v0.19.0")}}}
    assert firnrelease.pinned_tag(data, "x.yaml") == "v0.19.0"


def test_pinned_tag_refuses_two_tags_naming_both():
    data = _manifest(f"{FIRN}:v0.19.0", f"{FIRN}:v0.18.0")
    with pytest.raises(ValueError, match=r"v0\.18\.0.*v0\.19\.0|v0\.19\.0.*v0\.18\.0") as refused:
        firnrelease.pinned_tag(data, "x.yaml")
    said = str(refused.value)
    assert "x.yaml" in said and "test model" in said and "build model" in said


def test_pinned_tag_refuses_no_firn_image():
    data = {"ci": {"build": {"commands": {
        "model-binary": _command("build:model-binary", "ghcr.io/marcozwyssig/firn-builder:v0.18.0")}}}}
    with pytest.raises(ValueError, match="no command runs ghcr.io/marcozwyssig/firn"):
        firnrelease.pinned_tag(data, "x.yaml")


def test_pinned_tag_refuses_a_firn_image_with_no_tag():
    data = _manifest(f"{FIRN}@sha256:" + "a" * 64, f"{FIRN}:v0.19.0")
    with pytest.raises(ValueError, match="test model.*no tag"):
        firnrelease.pinned_tag(data, "x.yaml")


def test_pinned_tag_refuses_a_firn_command_whose_cwd_is_no_folder_name():
    # a refusal decided on the manifest alone, so it is on the path the census walks (no disk, no git)
    data = _manifest(f"{FIRN}:v0.19.0", f"{FIRN}:v0.19.0")
    data["ci"]["build"]["commands"]["model"]["with"]["cwd"] = ["src"]
    with pytest.raises(ValueError, match=r"build model.*cwd: \['src'\].*not a folder name"):
        firnrelease.pinned_tag(data, "x.yaml")


def test_pinned_tag_reads_a_null_cwd_as_the_mount_itself():
    # `cwd: null` is what toolchain._cwd reads as "the mount itself": the pin must not refuse what the build runs
    data = _manifest(f"{FIRN}:v0.19.0", f"{FIRN}:v0.19.0")
    data["ci"]["build"]["commands"]["model"]["with"]["cwd"] = None
    assert firnrelease.pinned_tag(data, "x.yaml") == "v0.19.0"


# --- the host binary --------------------------------------------------------------------------------


def test_host_binary_name_maps_machine():
    assert firnrelease.host_binary_name("v0.19.0", "Linux", "x86_64") == "firn-v0.19.0-linux-amd64"
    assert firnrelease.host_binary_name("v0.19.0", "Linux", "aarch64") == "firn-v0.19.0-linux-arm64"
    assert firnrelease.host_binary_name("v0.19.0", "Darwin", "arm64") == "firn-v0.19.0-darwin-arm64"
    assert firnrelease.host_binary_name("v0.19.0", "Linux", "riscv64") is None
    assert firnrelease.host_binary_name("v0.19.0", "Windows", "AMD64") is None


# --- reading the release ----------------------------------------------------------------------------


def _token(monkeypatch, value="t0ken"):
    monkeypatch.setattr(githubpackages, "token", lambda: value)


def test_read_without_token_is_no_token(monkeypatch):
    def none():
        raise githubpackages.PackageError("no GitHub token: GITHUB_TOKEN is not set")
    monkeypatch.setattr(githubpackages, "token", none)
    with pytest.raises(firnrelease.NoToken, match="no GitHub token"):
        firnrelease.read("v0.19.0")


def test_read_repository_404_is_unreadable_not_unpublished(monkeypatch):
    _token(monkeypatch)

    def refused(name, token):
        raise github.Unanswered(f"https://api.github.com answers 404 for the repository {name}")
    monkeypatch.setattr(github, "other", refused)
    with pytest.raises(firnrelease.ReleaseUnreadable) as caught:
        firnrelease.read("v0.19.0")
    said = str(caught.value)
    assert "not published" not in said and "v0.19.0" in said and "answers 404" in said


def test_read_missing_tag_is_unreadable_naming_the_tag(monkeypatch):
    _token(monkeypatch)
    monkeypatch.setattr(github, "other", lambda name, token: object())
    monkeypatch.setattr(github, "published", lambda repo, tag: None)
    with pytest.raises(firnrelease.ReleaseUnreadable, match="could not read release v0.19.0 of marcozwyssig/firn"):
        firnrelease.read("v0.19.0")


def test_read_a_failed_asset_list_is_unreadable_not_empty(monkeypatch):
    _token(monkeypatch)
    monkeypatch.setattr(github, "other", lambda name, token: object())
    monkeypatch.setattr(github, "published", lambda repo, tag: object())

    def failed(release):
        raise github.Unanswered("could not list the assets of release 7: 502")
    monkeypatch.setattr(github, "assets", failed)
    with pytest.raises(firnrelease.ReleaseUnreadable, match="v0.19.0.*could not list the assets"):
        firnrelease.read("v0.19.0")


def test_read_keys_the_assets_by_name(monkeypatch):
    _token(monkeypatch)
    vsix = SimpleNamespace(name="firn-v0.19.0.vsix", url="https://api.github.com/a/1")
    monkeypatch.setattr(github, "other", lambda name, token: object())
    monkeypatch.setattr(github, "published", lambda repo, tag: object())
    monkeypatch.setattr(github, "assets", lambda release: [vsix])
    release = firnrelease.read("v0.19.0")
    assert release.tag == "v0.19.0" and dict(release.assets) == {"firn-v0.19.0.vsix": vsix}


# --- the checked download ---------------------------------------------------------------------------

VSIX = "firn-v0.19.0.vsix"
BODY = b"a vsix, standing in"


def _asset(name):
    return SimpleNamespace(name=name, url=f"https://api.github.com/repos/marcozwyssig/firn/releases/assets/{name}")


def _release(*names):
    return firnrelease.Release(tag="v0.19.0", assets={n: _asset(n) for n in names})


def _served(monkeypatch, contents, seen=None):
    """`fetch.download` writing `contents[<asset name>]`, keyed off the asset URL the stub hands out."""
    def download(url, dest, *, label="", headers=None, **_):
        name = url.rsplit("/", 1)[-1]
        if seen is not None:
            seen.append((name, dict(headers or {})))
        Path(dest).write_bytes(contents[name])
        return Path(dest)
    monkeypatch.setattr(fetch, "download", download)


def test_fetch_checked_names_a_missing_asset_and_its_tag(tmp_path, monkeypatch):
    _token(monkeypatch)
    with pytest.raises(firnrelease.AssetMissing, match=r"v0\.19\.0.*firn-v0\.19\.0\.vsix"):
        firnrelease.fetch_checked(_release(), VSIX, tmp_path / VSIX)


def test_fetch_checked_refuses_a_missing_sha256_asset(tmp_path, monkeypatch):
    _token(monkeypatch)
    with pytest.raises(firnrelease.AssetMissing, match=r"firn-v0\.19\.0\.vsix\.sha256"):
        firnrelease.fetch_checked(_release(VSIX), VSIX, tmp_path / VSIX)
    assert list(tmp_path.iterdir()) == []


def test_fetch_checked_refuses_a_wrong_sha_and_leaves_no_file(tmp_path, monkeypatch):
    _token(monkeypatch)
    _served(monkeypatch, {VSIX: BODY, f"{VSIX}.sha256": f"{'0' * 64}  {VSIX}\n".encode()})
    with pytest.raises(firnrelease.ChecksumMismatch, match=hashlib.sha256(BODY).hexdigest()):
        firnrelease.fetch_checked(_release(VSIX, f"{VSIX}.sha256"), VSIX, tmp_path / VSIX)
    assert not (tmp_path / VSIX).exists()
    assert list(tmp_path.iterdir()) == []


def test_fetch_checked_refuses_a_sha256_asset_holding_no_digest(tmp_path, monkeypatch):
    _token(monkeypatch)
    _served(monkeypatch, {VSIX: BODY, f"{VSIX}.sha256": b"<html>not a digest</html>"})
    with pytest.raises(firnrelease.ChecksumMismatch, match=r"firn-v0\.19\.0\.vsix\.sha256"):
        firnrelease.fetch_checked(_release(VSIX, f"{VSIX}.sha256"), VSIX, tmp_path / VSIX)
    assert list(tmp_path.iterdir()) == []


def test_fetch_checked_writes_the_matching_file_through_the_api_url(tmp_path, monkeypatch):
    _token(monkeypatch, "t0ken")
    seen: list = []
    _served(monkeypatch, {VSIX: BODY, f"{VSIX}.sha256": f"{hashlib.sha256(BODY).hexdigest()}  {VSIX}\n".encode()},
            seen)
    got = firnrelease.fetch_checked(_release(VSIX, f"{VSIX}.sha256"), VSIX, tmp_path / VSIX)
    assert got == tmp_path / VSIX and got.read_bytes() == BODY
    assert list(tmp_path.iterdir()) == [got]
    assert {name for name, _ in seen} == {VSIX, f"{VSIX}.sha256"}
    for _, headers in seen:
        assert headers == {"Accept": "application/octet-stream", "Authorization": "token t0ken"}


def test_fetch_checked_a_failed_transfer_is_unreadable(tmp_path, monkeypatch):
    _token(monkeypatch)

    def broken(url, dest, **_):
        raise fetch.DownloadError(f"{url}: HTTP Error 502")
    monkeypatch.setattr(fetch, "download", broken)
    with pytest.raises(firnrelease.ReleaseUnreadable, match=r"v0\.19\.0.*HTTP Error 502"):
        firnrelease.fetch_checked(_release(VSIX, f"{VSIX}.sha256"), VSIX, tmp_path / VSIX)
    assert list(tmp_path.iterdir()) == []
