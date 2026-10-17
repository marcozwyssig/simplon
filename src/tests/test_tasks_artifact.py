"""`release:artifact` - publishing a declared directory as an OCI artifact.

What is the product's is DATA: which registry, which package, which directory, which media type. The
mechanics - zip, log in, push - are the same everywhere, which is why they are here and not in three
products. AAA throughout; nothing pushes anything.
"""
import pytest

from simplon.manifest import context
from simplon.adapters import githubpackages
from simplon.manifest.context import ProductContext
from simplon.tasks import artifact

_MANIFEST = """
product: demo
artifacts:
  updatesite:
    kind: directory
    registry: ghcr.io/owner
    repository: demo-updatesite
    path: build-out/site
    media_type: application/vnd.demo.updatesite.v1+zip
  website:
    kind: directory
    registry: ghcr.io/owner
    repository: demo-website
    path: build-out/website
    media_type: application/vnd.demo.website.v1+zip
    tag: latest
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
        _MANIFEST.replace("    path: build-out/site",
                          "    path: build-out/site\n    archive: demo-updatesite"), encoding="utf-8")
    seen: list = []
    monkeypatch.setattr(githubpackages, "login", lambda registry, **kw: None)
    monkeypatch.setattr(githubpackages, "push_directory",
                        lambda ref, directory, media, **kw: seen.append(kw.get("archive_name")))

    artifact.publish(name="updatesite", tag="1")

    assert seen == ["demo-updatesite"]


def test_an_entry_of_another_kind_is_refused_by_the_kind_it_is(published, _product):
    # arrange
    (_product / "demo.yaml").write_text(
        _MANIFEST + "  app:\n    kind: image\n    registry: ghcr.io/owner\n", encoding="utf-8")

    # act
    with pytest.raises(ValueError) as caught:
        artifact.publish(name="app", tag="1")

    # assert
    assert str(caught.value) == (
        "demo.yaml: 'artifacts.app' is of kind 'image', and this task reads a 'directory' or a kind that "
        "refines it - name an entry of that kind, or change the entry's `kind:`")
    assert published == []


def test_a_site_entry_is_published_as_the_directory_it_refines(published, _product):
    # arrange
    new = _MANIFEST.replace("  updatesite:\n    kind: directory\n", "  updatesite:\n    kind: site\n")
    assert new != _MANIFEST  # the replace really made it a `site`, or this would pass on a `directory`
    (_product / "demo.yaml").write_text(new, encoding="utf-8")

    # act
    rc = artifact.publish(name="updatesite", tag="1")

    # assert
    assert rc == 0 and published[0][0] == "ghcr.io/owner/demo-updatesite:1"


def test_a_missing_key_is_named_with_everything_the_coordinate_needs(published, _product):
    # arrange
    new = _MANIFEST.replace("    media_type: application/vnd.demo.updatesite.v1+zip\n", "", 1)
    assert new != _MANIFEST
    (_product / "demo.yaml").write_text(new, encoding="utf-8")

    # act
    with pytest.raises(ValueError) as caught:
        artifact.publish(name="updatesite", tag="1")

    # assert
    assert str(caught.value) == ("demo.yaml: 'artifacts.updatesite' declares no `media_type:`, which "
                                 "release:artifact needs - it reads registry, repository, media_type, path")


def test_the_login_and_the_push_share_a_docker_config_that_ends_with_them(_product, monkeypatch, tmp_path):
    # arrange: si#443
    import os

    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "operator"))
    seen: list = []
    monkeypatch.setattr(githubpackages, "login", lambda registry, **kw: seen.append(os.environ["DOCKER_CONFIG"]))
    monkeypatch.setattr(githubpackages, "push_directory",
                        lambda *a, **kw: seen.append(os.environ["DOCKER_CONFIG"]))

    # act
    rc = artifact.publish(name="updatesite", tag="0.4.149")

    # assert
    assert rc == 0
    assert seen[0] == seen[1] != str(tmp_path / "operator")
    assert os.environ["DOCKER_CONFIG"] == str(tmp_path / "operator")
