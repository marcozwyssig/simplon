"""Unit tests for images - the pure container-image naming primitives (version tag + registry repo
string, the tagged reference). Moved here from netctl's tooling (netctl#730) and grown by platform#43;
no docker, no subprocess; AAA throughout."""
import pytest

from delivery import images


def test_image_version_prefers_env_override():
    # arrange / act / assert: an explicit IMAGE_VERSION wins over the gradle file
    assert images.image_version('version = "9.9.9"', env_override="1.2.3") == "1.2.3"


def test_image_version_reads_gradle_version():
    # arrange: a build.gradle.kts with a version line
    text = 'plugins { }\nversion = "0.4.2"\n'

    # act / assert
    assert images.image_version(text) == "0.4.2"


def test_image_version_falls_back_to_default_without_version_or_override():
    # arrange / act / assert: no version line, no override
    assert images.image_version("plugins { }\n") == "0.1.0"


def test_hub_repo_without_registry_is_namespace_name():
    # arrange / act / assert: plain Docker Hub form
    assert images.hub_repo("netctl", "acme") == "acme/netctl"


def test_hub_repo_with_registry_prefixes_it():
    # arrange / act / assert: a non-Hub registry (e.g. ghcr.io) is prefixed
    assert images.hub_repo("netctl", "acme", "ghcr.io") == "ghcr.io/acme/netctl"


# --- the tagged reference, and the push that must not go to the wrong place (platform#43) ------------

def test_a_registry_reads_the_same_however_the_variable_was_spelled():
    # arrange / act / assert: whitespace and a trailing slash are noise, not part of the address
    assert images.registry_prefix("  ghcr.io/acme/  ") == "ghcr.io/acme"
    assert images.registry_prefix("ghcr.io/acme") == "ghcr.io/acme"


def test_an_unset_registry_is_no_registry():
    # arrange / act / assert: unset, empty and whitespace-only all mean the same thing
    assert images.registry_prefix(None) == ""
    assert images.registry_prefix("") == ""
    assert images.registry_prefix("   ") == ""


def test_an_image_reference_without_a_registry_is_just_the_name_and_tag():
    # arrange / act / assert: the local build form
    assert images.image_ref("acme-backend", "1.4.0") == "acme-backend:1.4.0"


def test_an_image_reference_is_prefixed_with_the_registry_when_there_is_one():
    # arrange / act: a registry that already carries the namespace, as IMAGE_REGISTRY usually does
    ref = images.image_ref("acme-frontend", "2.0.1", "ghcr.io/acme")

    # assert: name and tag are the caller's, not a default
    assert ref == "ghcr.io/acme/acme-frontend:2.0.1"


def test_an_image_reference_ignores_a_trailing_slash_on_the_registry():
    # arrange / act / assert: one slash, never two
    assert images.image_ref("acme-backend", "1.4.0", "ghcr.io/acme/") == "ghcr.io/acme/acme-backend:1.4.0"


def test_a_push_requires_a_registry_and_names_the_variable_it_read(monkeypatch):
    # arrange: die is what a missing registry must reach, and it must say WHICH variable is missing
    def _boom(msg):
        raise SystemExit(msg)

    monkeypatch.setattr(images.log, "die", _boom)

    # act / assert: an unqualified push would silently target Docker Hub
    with pytest.raises(SystemExit, match="ACME_REGISTRY"):
        images.require_registry("  ", var="ACME_REGISTRY")


def test_a_push_with_a_registry_gets_it_back_normalised(monkeypatch):
    # arrange: any die here would be a failure
    monkeypatch.setattr(images.log, "die", lambda msg: (_ for _ in ()).throw(AssertionError(msg)))

    # act
    prefix = images.require_registry("ghcr.io/acme/")

    # assert
    assert prefix == "ghcr.io/acme"
