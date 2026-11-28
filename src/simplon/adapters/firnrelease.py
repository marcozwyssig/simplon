"""firn's private GitHub Release, read by the kernel: which tag, which assets, and a checked download (si#900).

THE PIN IS THE MANIFEST'S. The tag is the one the product's commands already run firn's image at
(`ghcr.io/marcozwyssig/firn:<tag>`), so the editor a product installs and the model its build checks
cannot be two versions. `firn-builder` is another image and does not count.

THREE OUTCOMES, KEPT APART. No token (`NoToken`); a token, and the release could not be read with it
(`ReleaseUnreadable`, never worded "not published": the repository is private, so a 404 is as likely to be
a token that cannot see it as a release that is not there); the release read and the asset not on it
(`AssetMissing`, naming the tag and the asset). A checksum that does not match is a fourth
(`ChecksumMismatch`), and nothing is written under the destination for it. Each message is the sentence a
gate prints.

THE DOWNLOAD GOES THROUGH THE ASSET'S API URL. A private asset has no anonymous `browser_download_url`; the
API URL with `Accept: application/octet-stream` answers with a redirect to object storage, and the token
travels to the API only (`fetch.download(headers=...)` sends it unredirected).
"""
from __future__ import annotations

import os
import platform
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from simplon.adapters import checksum, fetch, github, githubpackages
from simplon.manifest import treeform

if TYPE_CHECKING:
    from github.GitReleaseAsset import GitReleaseAsset

FIRN_REPO = "marcozwyssig/firn"
#: The repository part of firn's image, never an image reference itself: the tag is the manifest's. Not named
#: `*_IMAGE`, because every such constant in the kernel is a pinned reference (test_image_pins.py).
FIRN_IMAGE_REPOSITORY = "ghcr.io/marcozwyssig/firn"

_SYSTEMS = {"linux": "linux", "darwin": "darwin"}
_MACHINES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
_DIGEST = re.compile(r"[0-9a-f]{64}")


class NoToken(Exception):
    """No GitHub token to read firn's private release with."""


class ReleaseUnreadable(Exception):
    """A token, and the release (or a transfer from it) could not be read with it."""


class AssetMissing(Exception):
    """The release was read and does not carry the asset asked for."""


class ChecksumMismatch(Exception):
    """The downloaded asset is not the one its `.sha256` asset names; nothing was written."""


@dataclass(frozen=True)
class Release:
    tag: str
    assets: Mapping[str, GitReleaseAsset]


def _firn_tag(image: str) -> str | None:
    """`<tag>` out of `ghcr.io/marcozwyssig/firn:<tag>[@sha256:...]`, "" for firn's image with no tag, and
    None for any other image."""
    named = image.split("@", 1)[0]
    repository, _, tag = named.rpartition(":")
    if "/" in tag or not repository:          # the colon was a registry port, or there was none
        repository, tag = named, ""
    return tag if repository == FIRN_IMAGE_REPOSITORY else None


def pinned_tag(data: Mapping[str, object], source: str) -> str:
    """The one tag of `ghcr.io/marcozwyssig/firn` the manifest's commands run, read off the raw document.

    None, or more than one, is a ValueError naming `source`, and for several the commands at each tag: the
    editor follows the model's firn, and two of them leave nothing to follow.
    """
    _, flat = treeform.lower(treeform.tree_from_areas(dict(data), {}))
    found: dict[str, list[str]] = {}
    for group, members in flat.items():
        for name, spec in (members or {}).items():
            if not isinstance(spec, Mapping) or not isinstance(spec.get("with"), Mapping):
                continue
            image = spec["with"].get("image")
            tag = _firn_tag(image) if isinstance(image, str) else None
            if tag is None:
                continue
            parts = group.split(".")
            where = " ".join([*(parts[1:] if parts[0] in ("ci", "cd") else parts), str(name)])
            if not tag:
                raise ValueError(f"{source}: command '{where}' runs {image}, which has no tag - the firn "
                                 f"release the editor comes from is named by the tag. Write "
                                 f"{FIRN_IMAGE_REPOSITORY}:<tag>@sha256:... to keep the digest")
            found.setdefault(tag, []).append(where)
    if not found:
        raise ValueError(f"{source}: no command runs {FIRN_IMAGE_REPOSITORY}:<tag>, so there is no firn version to "
                         f"install the editor for. A command with `with: image: {FIRN_IMAGE_REPOSITORY}:<tag>` "
                         f"(the model's build or test) names it")
    if len(found) > 1:
        each = "; ".join(f"{tag} ({', '.join(wheres)})" for tag, wheres in sorted(found.items()))
        raise ValueError(f"{source}: the commands run {FIRN_IMAGE_REPOSITORY} at more than one tag: {each}. The editor "
                         f"follows the model's firn, so every command has to run the same tag")
    return next(iter(found))


def host_binary_name(tag: str, system: str | None = None, machine: str | None = None) -> str | None:
    """`firn-<tag>-<os>-<arch>` for this host (or the one given), or None for a host firn names no
    binary for."""
    os_name = _SYSTEMS.get((system if system is not None else platform.system()).lower())
    arch = _MACHINES.get((machine if machine is not None else platform.machine()).lower())
    if os_name is None or arch is None:
        return None
    return f"firn-{tag}-{os_name}-{arch}"


def _token() -> str:
    try:
        return githubpackages.token()
    except githubpackages.PackageError as missing:
        raise NoToken(f"cannot read firn's release ({FIRN_REPO} is private): {missing}") from None


def read(tag: str) -> Release:
    """Release `tag` of firn and its assets by name."""
    token = _token()
    what = f"could not read release {tag} of {FIRN_REPO}"
    try:
        release = github.published(github.other(FIRN_REPO, token), tag)
        if release is None:
            raise ReleaseUnreadable(
                f"{what}: the token sees the repository and GitHub answers no published release for the tag. "
                f"Check that {tag} is released, or that the manifest's firn image names a released tag")
        return Release(tag=tag, assets={asset.name: asset for asset in github.assets(release)})
    except github.Unanswered as unanswered:
        raise ReleaseUnreadable(f"{what}: {unanswered}") from None


def _asset(release: Release, name: str) -> GitReleaseAsset:
    asset = release.assets.get(name)
    if asset is None:
        carried = ", ".join(sorted(release.assets)) or "nothing"
        raise AssetMissing(f"release {release.tag} of {FIRN_REPO} carries no {name} (it carries {carried})")
    return asset


def fetch_checked(release: Release, name: str, dest: Path) -> Path:
    """Asset `name` of `release` at `dest`, checked against the release's `<name>.sha256`, and `dest`.

    Both are downloaded into a directory beside `dest` and only a body whose sha256 matches is renamed onto
    `dest`; on any refusal nothing is left, not under `dest` and not beside it.
    """
    asset = _asset(release, name)
    sums = _asset(release, f"{name}.sha256")
    headers = {"Accept": "application/octet-stream", "Authorization": f"token {_token()}"}
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=f".{dest.name}.") as staging:
        try:
            said = fetch.download(sums.url, Path(staging) / sums.name, label=sums.name, headers=headers)
            body = fetch.download(asset.url, Path(staging) / name, label=name, headers=headers)
        except fetch.DownloadError as failed:
            raise ReleaseUnreadable(f"could not download from release {release.tag} of {FIRN_REPO}: {failed}"
                                    ) from None
        words = said.read_text(encoding="utf-8", errors="replace").split()
        expected = words[0].lower() if words else ""
        if not _DIGEST.fullmatch(expected):
            raise ChecksumMismatch(f"{sums.name} on release {release.tag} of {FIRN_REPO} holds no sha256, so "
                                   f"{name} cannot be checked; nothing was written to {dest}")
        got = checksum.sha256_of(body)
        if got != expected:
            raise ChecksumMismatch(f"{name} from release {release.tag} of {FIRN_REPO} has sha256 {got}, and "
                                   f"{sums.name} says {expected}; nothing was written to {dest}")
        os.replace(body, dest)
    return dest
