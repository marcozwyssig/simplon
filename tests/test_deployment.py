"""WHICH VERSION A DEPLOYMENT IS DEPLOYING (si#235).

Thirty-two deploy commands across five products, and not one of them could say. The version that went up
was whatever `IMAGE_VERSION` happened to be, or whatever the tree happened to say - a side effect
standing in for a statement, which is the shape si#223 had just decided against for the runner.

THREE VALUES, THREE MEANINGS, and that is the decided vocabulary rather than a convenience:

    1.4.0     this exact published version   -> a lookup, verified before anything runs
    latest    the newest published version   -> a lookup, verified by existing
    local     the current code base          -> a build, and no registry is touched at all

One value that silently meant two of those - `latest` quietly becoming a build when nothing is published
- would be this repository's recurring defect. Three values for three meanings is the widening CLAUDE.md
prescribes for it, so the tests below pin the SEPARATION as hard as they pin each answer.

THE SECTION POINTS, IT DOES NOT RESTATE. `images:` and `artifacts:` already carry a registry and a
repository, so a `deploy:` section naming those again would be a second source for one fact. It names an
entry in a section that exists, and everything about WHERE comes from there.

AND THE ENTRY IT POINTS AT MAY NOT CARRY IT, which is measured rather than imagined. Over the five
reachable manifests that declare such a section: `registry` and `repository` are in three of them,
biz-cockpit's images carry `name` instead, and netctl's are bare strings rather than mappings at all. So
the reader refuses by name in each of those shapes instead of raising a KeyError two frames down.

AAA throughout.
"""
from __future__ import annotations

import pytest

from simplon import context, deployment
from simplon.context import ProductContext


def _product(tmp_path, monkeypatch, manifest: str) -> None:
    """Register a product whose manifest is `manifest`."""
    path = tmp_path / "demo.yaml"
    path.write_text(manifest, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, path))


_GOOD = """
images:
  app:
    registry: ghcr.io/acme
    repository: demo-app
    dockerfile: Dockerfile
deploy:
  source: { images: app }
"""


# --- the section, and the four shapes it refuses ------------------------------------------------------


def test_the_source_is_read_off_the_section_it_points_at(tmp_path, monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch, _GOOD)
    # Act
    source = deployment.declared()
    # Assert: nothing about WHERE was restated in the deploy section
    assert source.kind == "images" and source.name == "app"
    assert source.registry == "ghcr.io/acme" and source.repository == "demo-app"


def test_a_manifest_with_no_deploy_section_says_what_it_needs(tmp_path, monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch, "images:\n  app: { registry: r, repository: d }\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"`deploy:`"):
        deployment.declared()


def test_a_deploy_section_with_no_source_says_so(tmp_path, monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch, "deploy:\n  default: latest\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"source:"):
        deployment.declared()


def test_a_source_naming_a_section_the_manifest_does_not_declare_lists_the_ones_it_does(tmp_path,
                                                                                       monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch,
             "images:\n  app: { registry: r, repository: d }\ndeploy:\n  source: { artifacts: app }\n")
    # Act / Assert: the reader names what IS declared rather than only what is missing
    with pytest.raises(ValueError, match=r"artifacts.*images"):
        deployment.declared()


def test_a_source_naming_an_entry_the_section_does_not_carry_lists_the_entries(tmp_path, monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch,
             "images:\n  app: { registry: r, repository: d }\n  sidecar: {}\n"
             "deploy:\n  source: { images: web }\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"web.*app, sidecar"):
        deployment.declared()


def test_an_entry_that_is_not_a_mapping_is_refused_by_name(tmp_path, monkeypatch):
    """netctl's shape, measured: its `images:` entries are bare strings like `netctl:local`."""
    # Arrange
    _product(tmp_path, monkeypatch,
             "images:\n  web: netctl:local\ndeploy:\n  source: { images: web }\n")
    # Act / Assert
    with pytest.raises(ValueError, match=r"images: web"):
        deployment.declared()


def test_an_entry_without_a_registry_names_what_it_does_carry(tmp_path, monkeypatch):
    """biz-cockpit's shape, measured: `context`, `dockerfile` and `name` - and no registry anywhere."""
    # Arrange
    _product(tmp_path, monkeypatch,
             "images:\n  backend: { context: ., dockerfile: Dockerfile, name: bc-backend }\n"
             "deploy:\n  source: { images: backend }\n")
    # Act / Assert: the keys it has are in the message, so the reader can see what to add
    with pytest.raises(ValueError, match=r"registry.*context, dockerfile, name"):
        deployment.declared()


# --- the three values ---------------------------------------------------------------------------------


def test_local_touches_no_registry_at_all(tmp_path, monkeypatch):
    """The separation, and the half that is easy to lose: `local` is a BUILD, so there is nothing to look
    up and nothing that can fail because a registry is unreachable."""
    # Arrange
    _product(tmp_path, monkeypatch, _GOOD)
    monkeypatch.setattr(deployment, "_newest", lambda source: pytest.fail("latest was resolved"))
    monkeypatch.setattr(deployment, "_serves", lambda source, tag: pytest.fail("the registry was asked"))
    # Act
    version = deployment.resolve("local", deployment.declared())
    # Assert
    assert version.builds is True and version.tag == "" and version.selector == "local"


def test_latest_is_the_newest_published_tag(tmp_path, monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch, _GOOD)
    monkeypatch.setattr(deployment, "_newest", lambda source: "1.4.0")
    # Act
    version = deployment.resolve("latest", deployment.declared())
    # Assert: resolved to a concrete tag, and it is NOT a build
    assert version.tag == "1.4.0" and version.builds is False
    assert version.selector == "latest"


def test_a_named_version_the_registry_serves_resolves_to_itself(tmp_path, monkeypatch):
    # Arrange
    _product(tmp_path, monkeypatch, _GOOD)
    monkeypatch.setattr(deployment, "_serves", lambda source, tag: True)
    # Act
    version = deployment.resolve("1.4.0", deployment.declared())
    # Assert
    assert version.tag == "1.4.0" and version.builds is False


def test_a_named_version_the_registry_does_not_serve_is_refused_before_anything_runs(tmp_path,
                                                                                     monkeypatch):
    """The decided refusal. Without it the deployment dies somewhere in the middle with the underlying
    tool's error, which names neither the version nor the registry it was looked for in."""
    # Arrange
    _product(tmp_path, monkeypatch, _GOOD)
    monkeypatch.setattr(deployment, "_serves", lambda source, tag: False)
    # Act / Assert: the message carries both halves a reader needs to act - which version, and which
    # registry it was looked for in. Asserted independently, because the order they read best in is the
    # message's business and not this test's.
    with pytest.raises(ValueError) as refusal:
        deployment.resolve("9.9.9", deployment.declared())
    assert "9.9.9" in str(refusal.value)
    assert "ghcr.io/acme/demo-app" in str(refusal.value)


def test_asking_for_nothing_is_refused_rather_than_defaulted(tmp_path, monkeypatch):
    """An empty selector must not quietly become `latest`: "whatever is newest" is a choice somebody has
    to make, and a deployment that picked it silently is the side effect this ticket removes."""
    # Arrange
    _product(tmp_path, monkeypatch, _GOOD)
    # Act / Assert
    with pytest.raises(ValueError, match=r"latest.*local"):
        deployment.resolve("", deployment.declared())
