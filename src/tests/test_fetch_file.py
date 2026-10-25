"""si#343: `build:fetch` leaves a declared `kind: file` under its path with its sha256, and `build:image` is
handed it as a `--build-context` through the image's own `contexts:`.

Decided 2026-10-15 (si#343): a `file` kind with `url`, `sha256` and an optional `version_from: {file, key}`;
the image's `contexts:` names it, and the loader derives `build:image`'s `file` port from there.

AAA; the name states the behaviour under test. Nothing touches the network: `fetch.download` is replaced by
a writer of known bytes.
"""
import hashlib
import re

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
    # arrange
    calls, _ = served
    (product / "build/dist").mkdir(parents=True)
    (product / "build/dist/plain.bin").write_bytes(ARCHIVE)

    # act
    rc = fetchfile.fetch(name="plain")

    # assert: nothing to do is rc 0 and says it, rather than looking like a download
    assert rc == 0
    assert calls == []
    assert "nothing to fetch" in capsys.readouterr().out


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
