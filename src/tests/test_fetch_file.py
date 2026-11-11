"""si#343: `build:fetch` leaves a declared `kind: file` under its path with its sha256, and `build:image` is
handed it as a `--build-context` through the image's own `contexts:`.

Decided 2026-10-15 (si#343): a `file` kind with `url`, `sha256` and an optional `version_from: {file, key}`;
the image's `contexts:` names it, and the loader derives `build:image`'s `file` port from there.

AAA; the name states the behaviour under test. Nothing touches the network: `fetch.download` is replaced by
a writer of known bytes.
"""
import hashlib
import re
import stat
from pathlib import Path

import pytest

from simplon.adapters import fetch as transfer
from simplon.manifest import catalogue, context
from simplon.manifest import load as manifest_mod
from simplon.manifest.context import ProductContext
from simplon.tasks import fetchfile

ARCHIVE = b"gradle 9.7.1, as served"
SHA = hashlib.sha256(ARCHIVE).hexdigest()

_MANIFEST = f"""
product: demo
artifacts:
  gradle-dist:
    kind: file
    path: build/dist/gradle.zip
    url: https://services.gradle.org/distributions/gradle-{{version}}-bin.zip
    sha256: {SHA}
    version_from: {{ file: gradle/libs.versions.toml, key: versions.gradle }}
  plain:
    kind: file
    path: build/dist/plain.bin
    url: https://example.org/plain.bin
    sha256: {SHA}
"""


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    """si#600: the download cache, pointed into the test's own directory so no run writes the caller's."""
    where = tmp_path / "cache"
    monkeypatch.setenv(fetchfile.CACHE_ENV, str(where))
    return where


@pytest.fixture
def product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    (tmp_path / "gradle").mkdir()
    (tmp_path / "gradle" / "libs.versions.toml").write_text('[versions]\ngradle = "9.7.1"\n', encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    return tmp_path


@pytest.fixture
def served(monkeypatch):
    """The download, replaced: it records the url and writes `body` where it was asked to."""
    calls: list[str] = []
    state = {"body": ARCHIVE}

    def download(url, dest, **kwargs):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(state["body"])
        return dest

    monkeypatch.setattr(transfer, "download", download)
    return calls, state


# --- the task -----------------------------------------------------------------------------------------

def test_a_declared_file_is_fetched_from_the_url_its_version_writes_and_stored_under_its_path(product, served):
    # arrange
    calls, _ = served

    # act
    rc = fetchfile.fetch(name="gradle-dist")

    # assert: the version came out of the TOML file, the bytes are in place, nothing is left staged
    assert rc == 0
    assert calls == ["https://services.gradle.org/distributions/gradle-9.7.1-bin.zip"]
    assert (product / "build/dist/gradle.zip").read_bytes() == ARCHIVE
    assert not (product / "build/dist/gradle.zip.unverified").exists()


def test_a_file_already_there_with_its_checksum_is_not_fetched_again_and_says_so(product, served, capsys):
    # arrange: fetched once, so the file is there with its checksum and the url it was verified against
    calls, _ = served
    assert fetchfile.fetch(name="plain") == 0
    calls.clear()
    capsys.readouterr()

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: nothing to do is rc 0 and says it, rather than looking like a download
    assert rc == 0
    assert calls == []
    assert "nothing to fetch" in capsys.readouterr().out


def test_a_file_with_its_checksum_and_no_recorded_url_is_fetched_again(product, served, capsys):
    # arrange (si#493): the bytes match, and nothing says which url they were verified against - a file an
    # earlier kernel left, or one put there by hand
    calls, _ = served
    (product / "build/dist").mkdir(parents=True)
    (product / "build/dist/plain.bin").write_bytes(ARCHIVE)

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: an absent record is no match - the url is fetched, and the record is written for next time
    assert rc == 0
    assert calls == ["https://example.org/plain.bin"]
    assert "no recorded url" in capsys.readouterr().out
    assert (product / "build/dist/plain.bin.url").read_text(encoding="utf-8") == "https://example.org/plain.bin\n"


def test_a_download_with_another_checksum_fails_and_stores_nothing(product, served, capsys):
    # arrange: the server sends other bytes - a moved version, or a tampered mirror
    _, state = served
    state["body"] = b"something else"

    # act
    rc = fetchfile.fetch(name="gradle-dist")

    # assert: red, and neither the final name nor the staging name holds the unchecked bytes
    assert rc == 1
    assert not (product / "build/dist/gradle.zip").exists()
    assert not (product / "build/dist/gradle.zip.unverified").exists()
    err = capsys.readouterr().err
    assert hashlib.sha256(b"something else").hexdigest() in err
    assert "a new version needs the sha256 of its own file" in err


def test_a_stale_file_under_the_path_is_replaced_by_the_verified_one(product, served):
    # arrange: the previous version's archive is still there
    (product / "build/dist").mkdir(parents=True)
    (product / "build/dist/plain.bin").write_bytes(b"the old archive")

    # act
    rc = fetchfile.fetch(name="plain")

    # assert
    assert rc == 0
    assert (product / "build/dist/plain.bin").read_bytes() == ARCHIVE


def _move_the_version(product, to="9.8.0"):
    (product / "gradle" / "libs.versions.toml").write_text(f'[versions]\ngradle = "{to}"\n', encoding="utf-8")


def test_a_moved_version_with_the_old_sha256_fails_closed_over_the_old_archive_in_the_tree(product, served,
                                                                                          capsys):
    # arrange (si#493): the old archive is fetched and stored, then the version moves and the sha256 does
    # not - the new url serves the new version's bytes, which the old sha256 does not describe
    calls, state = served
    assert fetchfile.fetch(name="gradle-dist") == 0
    _move_the_version(product)
    state["body"] = b"gradle 9.8.0, as served"

    # act
    rc = fetchfile.fetch(name="gradle-dist")

    # assert: red rather than "nothing to fetch", the moved url was asked, and the message names both
    assert rc == 1
    assert calls[-1] == "https://services.gradle.org/distributions/gradle-9.8.0-bin.zip"
    err = capsys.readouterr().err
    assert "9.8.0" in err
    assert SHA in err


def test_a_moved_version_with_the_old_sha256_fails_closed_over_the_old_archive_in_the_cache(product, served,
                                                                                           capsys):
    # arrange (si#493): as above, after a `clean` - the tree is empty, the cache holds the old archive
    # under the declared sha256
    calls, state = served
    assert fetchfile.fetch(name="gradle-dist") == 0
    (product / "build/dist/gradle.zip").unlink()
    _move_the_version(product)
    state["body"] = b"gradle 9.8.0, as served"

    # act
    rc = fetchfile.fetch(name="gradle-dist")

    # assert
    assert rc == 1
    assert calls[-1] == "https://services.gradle.org/distributions/gradle-9.8.0-bin.zip"
    err = capsys.readouterr().err
    assert "9.8.0" in err
    assert SHA in err


def test_a_moved_url_that_serves_the_same_bytes_is_fetched_again_and_stays_green(product, served):
    # arrange (si#493): a mirror move - another url, the same archive, so the checksum still holds
    calls, _ = served
    assert fetchfile.fetch(name="gradle-dist") == 0
    _move_the_version(product)

    # act
    rc = fetchfile.fetch(name="gradle-dist")

    # assert: the checksum is the judge, so the moved url is fetched and accepted
    assert rc == 0
    assert calls == ["https://services.gradle.org/distributions/gradle-9.7.1-bin.zip",
                     "https://services.gradle.org/distributions/gradle-9.8.0-bin.zip"]


def test_a_failed_download_is_red_and_names_the_file(product, monkeypatch, capsys):
    # arrange
    def broken(url, dest, **kwargs):
        raise transfer.DownloadError(f"could not download {url}: TimeoutError: timed out")
    monkeypatch.setattr(transfer, "download", broken)

    # act
    rc = fetchfile.fetch(name="plain")

    # assert
    assert rc == 1
    assert "plain: could not download https://example.org/plain.bin" in capsys.readouterr().err


def test_a_version_key_the_toml_file_does_not_hold_is_refused_by_name(product, served):
    # arrange
    (product / "gradle" / "libs.versions.toml").write_text('[versions]\nkotlin = "2.1"\n', encoding="utf-8")

    # act / assert
    with pytest.raises(ValueError, match="gradle/libs.versions.toml has no key 'versions.gradle'"):
        fetchfile.fetch(name="gradle-dist")


# --- the download cache (si#600) ----------------------------------------------------------------------

def _no_network(monkeypatch):
    """A download that fails, so a green run proves the bytes came from somewhere else."""
    def broken(url, dest, **kwargs):
        raise transfer.DownloadError(f"could not download {url}: the test has no network")
    monkeypatch.setattr(transfer, "download", broken)


def _cached(cache, body=ARCHIVE, name="plain.bin", url="https://example.org/plain.bin"):
    entry = cache / SHA / name
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes(body)
    if url:
        entry.with_name(name + fetchfile.SOURCE).write_text(f"{url}\n", encoding="utf-8")
    return entry


def test_a_file_in_the_cache_is_restored_without_a_download_and_says_so(product, cache, monkeypatch, capsys):
    # arrange
    _cached(cache)
    _no_network(monkeypatch)

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: green with no network, the bytes in place, nothing staged left beside them, and the line
    # says where they came from
    assert rc == 0
    assert (product / "build/dist/plain.bin").read_bytes() == ARCHIVE
    assert sorted(p.name for p in (product / "build/dist").iterdir()) == ["plain.bin", "plain.bin.url"]
    assert "from the download cache" in capsys.readouterr().out


def test_a_cache_entry_with_no_recorded_url_is_a_miss(product, served, cache, capsys):
    # arrange (si#493): an entry an earlier kernel stored, with no record of the url it came from
    calls, _ = served
    _cached(cache, url="")

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: downloaded, and the entry now carries the record
    assert rc == 0
    assert calls == ["https://example.org/plain.bin"]
    assert "no recorded url" in capsys.readouterr().out
    assert (cache / SHA / "plain.bin.url").read_text(encoding="utf-8") == "https://example.org/plain.bin\n"


def test_a_miss_downloads_and_leaves_the_file_in_the_cache_under_its_sha256(product, served, cache, capsys):
    # arrange
    calls, _ = served

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: one download, the cache holds the verified bytes under <sha256>/<file name>, no partial left
    assert rc == 0
    assert len(calls) == 1
    assert (cache / SHA / "plain.bin").read_bytes() == ARCHIVE
    assert sorted(p.name for p in (cache / SHA).iterdir()) == ["plain.bin", "plain.bin.url"]
    out = capsys.readouterr().out
    assert "fetched build/dist/plain.bin" in out
    assert "stored in the download cache" in out


def test_the_second_fetch_after_a_miss_needs_no_network(product, served, monkeypatch):
    # arrange: the first run fills the cache, then the tree loses the file and the network goes away
    assert fetchfile.fetch(name="plain") == 0
    (product / "build/dist/plain.bin").unlink()
    _no_network(monkeypatch)

    # act
    rc = fetchfile.fetch(name="plain")

    # assert
    assert rc == 0
    assert (product / "build/dist/plain.bin").read_bytes() == ARCHIVE


def test_a_cached_file_with_the_wrong_sha256_is_refused_replaced_and_treated_as_a_miss(product, served, cache,
                                                                                      capsys):
    # arrange: the cache holds other bytes under the declared checksum - a torn copy, or a tampered one
    calls, _ = served
    entry = _cached(cache, b"not what the checksum says")

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: downloaded, the tree holds the verified bytes, the cache entry now does too, and it was said
    assert rc == 0
    assert len(calls) == 1
    assert (product / "build/dist/plain.bin").read_bytes() == ARCHIVE
    assert entry.read_bytes() == ARCHIVE
    out = capsys.readouterr().out
    assert "the download cache holds" in out
    assert hashlib.sha256(b"not what the checksum says").hexdigest() in out


def test_a_cache_that_cannot_be_written_is_a_warning_and_the_fetch_stays_green(product, served, tmp_path,
                                                                               monkeypatch, capsys):
    # arrange: the cache path is a regular file, so no directory can be made under it - unwritable for
    # root as well, which a chmod would not be
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(fetchfile.CACHE_ENV, str(blocker))

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: only the fetch decides rc; the cache fault is its own line, distinguishable from a clean fetch
    assert rc == 0
    assert (product / "build/dist/plain.bin").read_bytes() == ARCHIVE
    out = capsys.readouterr().out
    assert "cache not written:" in out
    assert "stored in the download cache" not in out


def test_a_cache_entry_that_cannot_be_read_is_a_miss_not_a_failure(product, served, cache, monkeypatch, capsys):
    # arrange: the entry exists and copying it fails
    calls, _ = served
    _cached(cache)
    real = fetchfile.shutil.copyfile

    def failing(src, dst, *args, **kwargs):
        if str(src).startswith(str(cache)):
            raise PermissionError(13, "Permission denied", str(src))
        return real(src, dst, *args, **kwargs)
    monkeypatch.setattr(fetchfile.shutil, "copyfile", failing)

    # act
    rc = fetchfile.fetch(name="plain")

    # assert
    assert rc == 0
    assert len(calls) == 1
    assert (product / "build/dist/plain.bin").read_bytes() == ARCHIVE
    assert sorted(p.name for p in (product / "build/dist").iterdir()) == ["plain.bin", "plain.bin.url"]
    assert "could not be read" in capsys.readouterr().out


def test_off_touches_no_cache_anywhere_and_says_the_cache_is_off(product, served, tmp_path, monkeypatch, capsys):
    # arrange: every place the chain could otherwise resolve to is a directory this test can watch
    monkeypatch.setenv(fetchfile.CACHE_ENV, "off")
    monkeypatch.setenv("RUNNER_TOOL_CACHE", str(tmp_path / "runner"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    # act
    rc = fetchfile.fetch(name="plain")

    # assert
    assert rc == 0
    for name in ("runner", "xdg", "home", "cache", "off"):
        assert not (tmp_path / name).exists(), name
    assert not (product / "off").exists()
    out = capsys.readouterr().out
    assert "download cache is off" in out


def test_off_does_not_read_the_cache_either(product, cache, monkeypatch):
    # arrange: a valid entry sits where the chain would look, and the network is gone
    _cached(cache)
    monkeypatch.setenv(fetchfile.CACHE_ENV, "off")
    _no_network(monkeypatch)

    # act / assert: off means off - the run downloads, and here that fails
    assert fetchfile.fetch(name="plain") == 1


def test_a_restored_file_has_the_same_mode_as_a_fetched_one(product, served, monkeypatch):
    # arrange: BuildKit keys a layer on the file mode too (firn, si#600), so the two must not differ
    assert fetchfile.fetch(name="plain") == 0
    dest = product / "build/dist/plain.bin"
    fetched = stat.S_IMODE(dest.stat().st_mode)
    dest.unlink()
    _no_network(monkeypatch)

    # act
    assert fetchfile.fetch(name="plain") == 0
    restored = stat.S_IMODE(dest.stat().st_mode)

    # assert: equal, and the mode a real download produces (mkstemp's 0600, measured)
    assert fetched == restored == fetchfile.MODE == 0o600


@pytest.mark.parametrize("environ,expected", [
    ({"DELIVERY_DIST_CACHE": "/named", "RUNNER_TOOL_CACHE": "/runner", "XDG_CACHE_HOME": "/xdg", "HOME": "/h"},
     "/named"),
    ({"RUNNER_TOOL_CACHE": "/runner", "XDG_CACHE_HOME": "/xdg", "HOME": "/h"}, "/runner/simplon/dist"),
    ({"XDG_CACHE_HOME": "/xdg", "HOME": "/h"}, "/xdg/simplon/dist"),
    ({"HOME": "/h"}, "/h/.cache/simplon/dist"),
    ({"DELIVERY_DIST_CACHE": "", "RUNNER_TOOL_CACHE": "", "XDG_CACHE_HOME": "", "HOME": "/h"},
     "/h/.cache/simplon/dist"),
    ({"DELIVERY_DIST_CACHE": "off", "RUNNER_TOOL_CACHE": "/runner", "HOME": "/h"}, None),
])
def test_the_cache_location_follows_the_decided_chain(environ, expected):
    # act
    found = fetchfile.cache_dir(environ)

    # assert
    assert found == (None if expected is None else Path(expected))


# --- the declaration ----------------------------------------------------------------------------------

def _entry(**body) -> dict:
    return {"f": {"kind": "file", "path": "build/f.zip", "url": "https://e.org/f.zip", "sha256": SHA, **body}}


@pytest.mark.parametrize("body,fragment", [
    ({"sha256": "abc"}, "not 64 hexadecimal characters"),
    ({"url": "https://e.org/f-{version}.zip"}, "declares no `version_from:`"),
    ({"version_from": {"file": "v.toml", "key": "v"}}, "the url does not write {version}"),
    ({"url": "https://e.org/{version}", "version_from": {"file": "v.toml"}}, "it lacks key"),
    ({"url": "https://e.org/{version}", "version_from": {"file": "v.toml", "key": "v", "x": "y"}},
     "it declares x"),
    ({"path": "../outside.zip"}, "is not a directory name"),
])
def test_a_file_declaration_that_cannot_be_fetched_is_refused_by_name(body, fragment):
    # act / assert
    with pytest.raises(ValueError, match=re.escape(fragment)):
        fetchfile.declared(_entry(**body), "f", "demo.yaml")


def test_a_file_without_a_url_is_refused_naming_what_build_fetch_needs():
    # arrange
    section = _entry()
    del section["f"]["url"]

    # act / assert
    with pytest.raises(ValueError, match=re.escape("declares no `url:`, which build:fetch needs")):
        fetchfile.declared(section, "f", "demo.yaml")


def test_an_upper_case_checksum_is_read_as_the_same_checksum():
    # act
    spec = fetchfile.declared(_entry(sha256=SHA.upper()), "f", "demo.yaml")

    # assert
    assert spec.sha256 == SHA


# --- the port the image's `contexts:` binds -----------------------------------------------------------

ARTIFACTS = f"""\
artifacts:
  toolchain:
    kind: image
    registry: ghcr.io/o
    repository: t
    dockerfile: Dockerfile
    context: .
    contexts: [gradle-dist]
  gradle-dist: {{ kind: file, path: build/dist/gradle.zip, url: "https://e.org/g.zip", sha256: {SHA} }}
"""

FETCH = '      fetch: { task: "build:fetch", produces: { file: gradle-dist } }\n'
# The command is `toolchain-image`, not `toolchain`: since si#550 the kernel places `support toolchain`, and a
# bare `depends_on: [toolchain]` would be ambiguous between the two groups.
IMAGE = '      toolchain-image: { task: "build:image", produces: { image: toolchain } }\n'


def _load(commands: str) -> manifest_mod.Manifest:
    return manifest_mod.load(f"product: demo\nci:\n  build:\n    commands:\n{commands}{ARTIFACTS}",
                             catalogue=catalogue.load(), manifest_path="demo.yaml")


def test_an_image_consumes_the_files_its_contexts_name_without_saying_so_twice():
    # act
    spec = _load(FETCH + IMAGE).spec_for("build", "toolchain-image")

    # assert: the binding is derived from the entry, and the body still receives only the image's name
    assert spec.consumes == {"file": ("gradle-dist",)}
    assert spec.with_ == {"name": "toolchain"}


def test_consumes_on_the_derived_port_is_refused_as_a_second_statement():
    # arrange
    image = ('      toolchain-image: { task: "build:image", produces: { image: toolchain }, '
             'consumes: { file: gradle-dist } }\n')

    # act / assert
    with pytest.raises(ValueError, match="takes that port from the `contexts:`"):
        _load(FETCH + image)


def test_a_plan_that_builds_the_image_before_fetching_its_file_is_refused():
    # arrange
    plan = '      all: { help: both, depends_on: [toolchain-image, fetch] }\n'

    # act / assert: rule 5, reached through the derived binding
    with pytest.raises(ValueError, match="plans 'toolchain-image' before 'fetch'"):
        _load(FETCH + IMAGE + plan)


def test_a_plan_that_fetches_first_loads():
    # act
    manifest = _load(FETCH + IMAGE + '      all: { help: both, depends_on: [fetch, toolchain-image] }\n')

    # assert
    assert manifest.plan_for("all", group="build") == ("fetch", "toolchain-image")


def test_a_file_context_nobody_fetches_is_refused_at_load():
    # act / assert: the build would fail on a missing file; the loader says so first
    with pytest.raises(ValueError, match="consumes 'gradle-dist', and no command produces it"):
        _load(IMAGE)
