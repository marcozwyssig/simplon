"""`release:artifact` - publishing a declared directory as an OCI artifact.

What is the product's is DATA: which registry, which package, which directory, which media type. The
mechanics - zip, log in, push - are the same everywhere, which is why they are here and not in three
products. AAA throughout; nothing pushes anything.
"""
import pytest

from simplon import context, githubpackages
from simplon.context import ProductContext
from simplon.tasks import artifact

_MANIFEST = """
product: demo
artifacts:
  updatesite:
    registry: ghcr.io/owner
    repository: demo-updatesite
    source: build-out/site
    media_type: application/vnd.demo.updatesite.v1+zip
  website:
    registry: ghcr.io/owner
    repository: demo-website
    source: build-out/website
    media_type: application/vnd.demo.website.v1+zip
    tag: latest
groups: {}
env_groups: []
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    (tmp_path / "build-out" / "site").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def published(monkeypatch):
    calls: list = []
    monkeypatch.setattr(githubpackages, "login", lambda registry, **kw: None)
    monkeypatch.setattr(githubpackages, "push_directory",
                        lambda ref, directory, media, **kw: calls.append((ref, str(directory), media)))
    return calls


def test_a_declared_artifact_is_published_under_the_tag_it_was_given(published, _product):
    rc = artifact.publish(name="updatesite", tag="0.4.149")

    assert rc == 0
    assert published == [("ghcr.io/owner/demo-updatesite:0.4.149",
                          str(_product / "build-out" / "site"),
                          "application/vnd.demo.updatesite.v1+zip")]


def test_a_tag_declared_in_the_manifest_needs_no_argument(published, _product, monkeypatch):
    """A product whose artefact is always 'latest' should not have to pass it on every call."""
    (_product / "build-out" / "website").mkdir(parents=True)

    artifact.publish(name="website")

    assert published[0][0] == "ghcr.io/owner/demo-website:latest"


def test_without_a_tag_anywhere_it_says_both_places_one_could_be(published):
    """cleon's tag comes out of a generated jar at runtime and cannot be declared - so the message has
    to name the argument as well as the manifest key, or the reader concludes the task cannot do it."""
    with pytest.raises(ValueError, match="--tag"):
        artifact.publish(name="updatesite")


def test_an_undeclared_artifact_lists_the_ones_that_are(published):
    with pytest.raises(ValueError, match="updatesite, website"):
        artifact.publish(name="nope", tag="1")


def test_a_source_that_is_not_there_is_named_before_anything_is_pushed(published, _product):
    import shutil
    shutil.rmtree(_product / "build-out" / "site")

    with pytest.raises(ValueError, match="build-out/site"):
        artifact.publish(name="updatesite", tag="1")

    assert published == []


def test_a_declared_archive_name_reaches_the_publisher(_product, monkeypatch):
    """The manifest names the file, so a consumer pulling by hand sees what it holds - and a consumer
    reading the name is not coupled to the publisher's directory layout."""
    (_product / "demo.yaml").write_text(
        _MANIFEST.replace("    source: build-out/site",
                          "    source: build-out/site\n    archive: demo-updatesite"), encoding="utf-8")
    seen: list = []
    monkeypatch.setattr(githubpackages, "login", lambda registry, **kw: None)
    monkeypatch.setattr(githubpackages, "push_directory",
                        lambda ref, directory, media, **kw: seen.append(kw.get("archive_name")))

    artifact.publish(name="updatesite", tag="1")

    assert seen == ["demo-updatesite"]
