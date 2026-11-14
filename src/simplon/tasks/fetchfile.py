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

THE URL IS PART OF "ALREADY THERE" (si#493). The sha256 alone cannot see a moved version: the old archive
still matches the old sha256 while the url now names another file, and this module answered "nothing to
fetch" and built the old archive under the new version. So every file this task leaves - under `path` and
in the download cache - carries a record beside it, `<file>.url`, naming the url its bytes were verified
against, and a file counts as there only when its sha256 AND its record match the declaration. Otherwise
the url is fetched and the checksum rules on what it serves now: a moved version with an old sha256 fails
there, and a mirror move serving the same bytes passes. A file with no record (one an earlier kernel left,
or one put there by hand) is not a match - it costs one download, where trusting it is the defect.
BuildKit's layer key does not see the record: a `--build-context` directory gaining `gradle.zip.url` beside
a bind-mounted `gradle.zip` left the layer CACHED (measured 2026-11-11, buildx 0.38.1), and changing the
archive itself rebuilt it.

"NOTHING TO DO" AND "FAILED" ARE TWO ANSWERS. A file that is already there with the declared checksum and
url is rc 0 and says so; a download that fails, or arrives with another checksum, is rc 1 and leaves NOTHING under
`path` - the bytes land beside it under a staging name and are renamed into place only once they match.
A file under `path` with the wrong checksum (the previous version's archive) is replaced, and the run says
that too.

A DOWNLOAD CACHE, OUTSIDE THE TREE (si#600). The file under `path` is gone after every `clean`, every
fresh checkout and every CI job, and each of those fetched the archive again. firn bridged it with a
cache of its own (`FIRN_DIST_CACHE`, firn#1240); Marco decided on si#600 that the kernel carries one for
every product, with no manifest key. It lives at `DELIVERY_DIST_CACHE` (`off` turns it off), else
`$RUNNER_TOOL_CACHE/simplon/dist` on a CI runner, else `${XDG_CACHE_HOME:-$HOME/.cache}/simplon/dist`,
keyed `<sha256>/<file name>` - the checksum is the key because it is the one statement about the bytes.
A hit is copied beside `path`, verified AGAIN on the copy, and renamed into place; a miss downloads as
before and then copies the verified file into the cache under a unique `.partial` name. EVERY CACHE
FAULT IS A WARNING AND A MISS, never the verdict: an unreadable entry, a wrong checksum in the cache (it
is removed and replaced), a cache that cannot be written. Only the fetch decides the exit code, and the
four outcomes are four different lines - "from the download cache", "fetched ...; stored in the download
cache", "fetched ...; cache not written: <reason>", "fetched ...; the download cache is off". The
launcher mounts the host's cache into the kernel's container on the container route, at a fixed path
it names through the same variable.
"""
from __future__ import annotations

import os
import shutil
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

#: The suffix of the record beside a fetched file and beside a cache entry: the url its bytes were
#: verified against (si#493).
SOURCE = ".url"

#: The variable naming the download cache directory, and the value that turns the cache off (si#600).
CACHE_ENV = "DELIVERY_DIST_CACHE"
CACHE_OFF = "off"


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


def cache_dir(environ: Mapping[str, str] | None = None) -> Path | None:
    """The download cache directory the environment names, or None when it says `off` (si#600).

    The chain is the launcher's too (`launch.sh.j2` resolves the host side with the same four names), so
    the two cannot pick different directories for one caller.
    """
    env = os.environ if environ is None else environ
    named = env.get(CACHE_ENV, "").strip()
    if named == CACHE_OFF:
        return None
    if named:
        return Path(named)
    runner = env.get("RUNNER_TOOL_CACHE", "").strip()
    if runner:
        return Path(runner) / "simplon" / "dist"
    base = env.get("XDG_CACHE_HOME", "").strip() or str(Path(env.get("HOME", "").strip() or Path.home()) / ".cache")
    return Path(base) / "simplon" / "dist"


def _source(path: Path) -> Path:
    """Where the url `path`'s bytes were verified against is recorded (si#493)."""
    return path.with_name(path.name + SOURCE)


def _fetched_from(path: Path) -> str:
    """The url recorded beside `path`, or "" when there is no readable record - which matches no url."""
    try:
        return _source(path).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def _record(path: Path, url: str) -> None:
    _source(path).write_text(f"{url}\n", encoding="utf-8")


def _restore(cached: Path, spec: File, dest: Path, url: str) -> bool:
    """Put the cached copy under `path` if it is the declared file; False, with a warning, if it is not.
    A cache entry recorded for another url, or for none, is a miss and no fault (si#493)."""
    if not cached.is_file():
        return False
    recorded = _fetched_from(cached)
    if recorded != url:
        log.info(f"the download cache holds {cached} for {recorded or 'no recorded url'}, not {url}; the url "
                 f"is fetched so the checksum rules on what it serves now")
        return False
    copy: Path | None = None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # The mode a plain `open()` gives, as `transfer.download` gives a fetched file (si#497): BuildKit's
        # layer cache key includes the file mode (firn, si#600), so a restore and a download must not
        # differ, and neither may be 0600 - another uid sharing the checkout builds the image from it.
        handle, copy = transfer.unique_file(dest.parent, f"{dest.name}.", ".cached")
        os.close(handle)
        shutil.copyfile(cached, copy)
        # Verified on the COPY, not on the cache: the bytes that are renamed into place are the bytes
        # that were checked, whatever happens to the cache entry in between.
        found = checksum.sha256_of(copy)
        if found != spec.sha256:
            copy.unlink(missing_ok=True)
            log.warn(f"the download cache holds {cached} with sha256 {found}, not the declared "
                     f"{spec.sha256}; it is removed and the file is fetched instead")
            cached.unlink(missing_ok=True)
            return False
        os.replace(copy, dest)
        _record(dest, url)
    except OSError as fault:
        if copy is not None:
            copy.unlink(missing_ok=True)
        log.warn(f"the download cache entry {cached} could not be read ({fault}); the file is fetched instead")
        return False
    log.ok(f"{spec.path} restored from the download cache {cached}; sha256 verified, nothing downloaded")
    return True


def _store(dest: Path, cached: Path, url: str) -> str:
    """Copy the verified file into the cache; the reason it could not be, or "" when it was."""
    partial: Path | None = None
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        # The umask's mode, as the restore and the download give (si#669): `mkstemp` would make the entry
        # 0600 whatever the umask, and another uid sharing the cache could not read it back.
        handle, partial = transfer.unique_file(cached.parent, f"{cached.name}.", ".partial")
        os.close(handle)
        shutil.copyfile(dest, partial)
        os.replace(partial, cached)
        _record(cached, url)
    except OSError as fault:
        if partial is not None:
            partial.unlink(missing_ok=True)
        return str(fault)
    return ""


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
        recorded = _fetched_from(dest)
        if checksum.sha256_of(dest) != spec.sha256:
            log.info(f"{spec.path} is there with another sha256 - an older download, or another file; it is "
                     f"replaced")
        elif recorded == url:
            log.ok(f"{spec.path} is already there with the declared sha256 from {url}; nothing to fetch")
            return 0
        else:
            log.info(f"{spec.path} has the declared sha256 and was verified against "
                     f"{recorded or 'no recorded url'}, not {url}; the url is fetched so the checksum rules on "
                     f"what it serves now")
    cache = cache_dir()
    cached = cache / spec.sha256 / dest.name if cache is not None else None
    if cached is not None and _restore(cached, spec, dest, url):
        return 0
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
    _record(dest, url)
    fetched = f"fetched {spec.path} from {url}; sha256 verified"
    if cached is None:
        log.ok(f"{fetched}; the download cache is off ({CACHE_ENV}={CACHE_OFF})")
        return 0
    reason = _store(dest, cached, url)
    if reason:
        log.warn(f"{fetched}; cache not written: {reason}")
    else:
        log.ok(f"{fetched}; stored in the download cache {cached}")
    return 0
