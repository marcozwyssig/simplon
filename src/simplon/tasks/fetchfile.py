"""`build:fetch` - download a declared file, check its sha256, and leave it under the product root (si#343).

WHY THIS IS THE KERNEL'S. firn's toolchain image needs Gradle, a 130 MB archive from outside its signed
package repository, and Marco decided on firn#547 that simplon downloads and stores it, in a place git
ignores, and the image build takes it from there. A Dockerfile that downloads it itself (firn#770's `FROM
scratch` + `ADD --checksum`) caches well - measured 4.5 s against 29 s - but cannot build offline, and
fetches it again after every builder-cache prune. `simplon.adapters.fetch.download` and
`simplon.adapters.checksum.sha256_of` already did both halves as library functions; what was missing is a
coordinate a manifest can name without a task body of its own, which firn's adr/0008 rules out.

WHAT A PRODUCT STATES, ONCE. A `kind: file` entry in `artifacts:` carries the `url`, its `sha256` and the
`path` the file lives at. An image whose `contexts:` names the entry gets the file's directory as a
`--build-context` under the entry's name (`tasks.image`), so the path is written in one place and the
Dockerfile reads `--mount=type=bind,from=<name>,source=/<file name>`.

THE VERSION MAY LIVE ELSEWHERE, AND THEN IT IS READ, NOT RESTATED. `version_from: {file, key}` names a TOML
file under the product root and a dotted key in it (firn: `gradle/libs.versions.toml`, `versions.gradle`),
and `{version}` in the url is replaced by that value. The sha256 cannot follow a version - it is the
statement about one particular archive - so a moved version with an old sha256 fails closed, and the message
names both, rather than downloading something nobody checked.

"NOTHING TO DO" AND "FAILED" ARE TWO ANSWERS. A file that is already there with the declared checksum is
rc 0 and says so; a download that fails, or arrives with another checksum, is rc 1 and leaves NOTHING under
`path` - the bytes land beside it under a staging name and are renamed into place only once they match.
A file under `path` with the wrong checksum (the previous version's archive) is replaced, and the run says
that too.
"""
from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from simplon.adapters import checksum
from simplon.adapters import fetch as transfer
from simplon.manifest import artifactsection, context
from simplon.model import artifactschema
from simplon.manifest.layout import validate_relative_dir
from simplon.kernel import log

#: The manifest section this task reads.
SECTION = "artifacts"

#: The kind this task reads; its keys, their shapes and what `build:fetch` needs are the generated schema's.
ENTRY = artifactschema.FileEntry

#: What `url` writes where the version read through `version_from` goes.
VERSION = "{version}"

#: The two keys `version_from:` takes.
VERSION_FROM_KEYS = ("file", "key")

#: The suffix the bytes carry until their checksum is known.
STAGING = ".unverified"


@dataclass(frozen=True)
class File:
    """A declared `kind: file` entry, validated: `path` relative to the product root, `sha256` lower case."""

    path: str
    url: str
    sha256: str
    version_file: str = ""
    version_key: str = ""


def declared(section: Mapping[str, object], name: str, source: str) -> File:
    """The file `name` declares, validated LOUDLY - everything that can be judged without the product tree."""
    if name not in section:
        raise ValueError(f"{source}: no artifact '{name}' in the `{SECTION}:` section; declared are: "
                         f"{', '.join(sorted(str(k) for k in section)) or '(none)'}")
    entry = artifactsection.entry(section, name, ENTRY, source, "build:fetch")
    where = f"{source}: '{SECTION}.{name}'"
    # `or ""` is for the type checker: `build:fetch` NEEDS all three, and `entry` refused the entry otherwise.
    path = validate_relative_dir(entry.path or "", f"{where}: 'path'",
                                 "give the file's path under the product root, e.g. 'build/dist/gradle.zip'",
                                 inside="the product root")
    sha256 = (entry.sha256 or "").strip().lower()
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError(f"{where}: 'sha256' is {entry.sha256!r}, not 64 hexadecimal characters - give the "
                         f"checksum the publisher states for this exact file")
    url = (entry.url or "").strip()
    version_from = entry.version_from
    if version_from is None:
        if VERSION in url:
            raise ValueError(f"{where}: the url writes {VERSION} and the entry declares no `version_from:` - "
                             f"name the TOML file and key the version is read from, or write the version "
                             f"into the url")
        return File(path, url, sha256)
    unknown = sorted(set(version_from) - set(VERSION_FROM_KEYS))
    missing = [key for key in VERSION_FROM_KEYS if not str(version_from.get(key, "")).strip()]
    if unknown or missing:
        raise ValueError(f"{where}: `version_from:` takes exactly {{ file: <TOML file>, key: <dotted key> }}"
                         + (f"; it declares {', '.join(unknown)}" if unknown else "")
                         + (f"; it lacks {', '.join(missing)}" if missing else ""))
    if VERSION not in url:
        raise ValueError(f"{where}: `version_from:` reads a version and the url does not write {VERSION}, so "
                         f"the version would reach nothing - put {VERSION} where the url names it")
    version_file = validate_relative_dir(version_from["file"], f"{where}: 'version_from.file'",
                                         "give the TOML file's path under the product root",
                                         inside="the product root")
    return File(path, url, sha256, version_file, version_from["key"].strip())


def version_of(spec: File, root: Path, where: str) -> str:
    """The version `version_from` names, read out of the product tree."""
    toml = root / spec.version_file
    try:
        document: object = tomllib.loads(toml.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{where}: `version_from.file` is {spec.version_file}, and no file under the product "
                         f"root answers to it") from None
    except tomllib.TOMLDecodeError as fault:
        raise ValueError(f"{where}: {spec.version_file} is not TOML ({fault})") from None
    for part in spec.version_key.split("."):
        if not isinstance(document, Mapping) or part not in document:
            raise ValueError(f"{where}: {spec.version_file} has no key '{spec.version_key}'")
        document = document[part]
    if not isinstance(document, str) or not document.strip():
        raise ValueError(f"{where}: '{spec.version_key}' in {spec.version_file} is {document!r}, not a version "
                         f"written as text")
    return document.strip()


def fetch(name: str = "") -> int:
    """Leave the file `name` declares under its `path`, with its declared sha256.

    `name` is normally pinned per command with `with: { name: ... }`, the shape `build:image` uses.
    """
    if not name:
        raise ValueError(f"which file? pin one with `with: {{ name: ... }}` from the `{SECTION}:` section, or "
                         f"pass --name")
    ctx = context.current()
    section = ctx.manifest_data().get(SECTION)
    source = ctx.manifest_path.name
    spec = declared(section if isinstance(section, Mapping) else {}, name, source)
    where = f"{source}: '{SECTION}.{name}'"
    root = ctx.root
    version = version_of(spec, root, where) if spec.version_file else ""
    url = spec.url.replace(VERSION, version) if version else spec.url
    dest = root / spec.path
    if dest.is_file():
        if checksum.sha256_of(dest) == spec.sha256:
            log.ok(f"{spec.path} is already there with the declared sha256; nothing to fetch")
            return 0
        log.info(f"{spec.path} is there with another sha256 - an older download, or another file; it is "
                 f"replaced")
    staged = dest.with_name(dest.name + STAGING)
    try:
        transfer.download(url, staged, label=dest.name)
    except transfer.DownloadError as failure:
        log.error(f"{name}: {failure}")
        return 1
    found = checksum.sha256_of(staged)
    if found != spec.sha256:
        staged.unlink(missing_ok=True)
        log.error(f"{name}: {url} sent a file with sha256 {found}, and `{SECTION}.{name}.sha256` declares "
                  f"{spec.sha256}. Nothing was stored."
                  + (f"\n  the url's version {version} is read from '{spec.version_key}' in "
                     f"{spec.version_file}: a new version needs the sha256 of its own file" if version else ""))
        return 1
    os.replace(staged, dest)
    log.ok(f"fetched {spec.path} from {url}; sha256 verified")
    return 0
