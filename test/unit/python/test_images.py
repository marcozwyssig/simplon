"""Unit tests for images - the pure container-image naming primitives (version tag + registry repo
string). Moved here from netctl's tooling (netctl#730); no docker, no subprocess; AAA throughout."""
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
