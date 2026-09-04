"""Unit tests for delivery.environments.parse - the pure environments.yml -> Registry parsing and
validation with product-supplied valid backends. No I/O; AAA throughout."""
import pytest

from delivery.environments import parse, parse_data

_BACKENDS = ("local", "cloud")
_OK = """
default: dev
environments:
  dev:  { backend: local, description: "Local lab." }
  test: { backend: cloud, description: "QA." }
  prod: { backend: cloud }
"""


def test_parse_reads_environments_their_backends_and_the_default():
    # arrange / act
    reg = parse(_OK, _BACKENDS)

    # assert: all three environments, their backends, and the default
    assert set(reg.environments) == {"dev", "test", "prod"}
    assert reg.environments["dev"].backend == "local"
    assert reg.environments["test"].backend == "cloud"
    assert reg.default == "dev"
    assert reg.environments["dev"].description == "Local lab."


def test_parse_defaults_missing_description_to_empty():
    # arrange: prod has no description
    reg = parse(_OK, _BACKENDS)

    # assert
    assert reg.environments["prod"].description == ""


def test_parse_rejects_a_backend_not_in_valid_backends():
    # arrange: a backend outside the product's valid set
    text = "default: dev\nenvironments:\n  dev: { backend: kubernetes }\n"

    # act / assert
    with pytest.raises(ValueError, match="backend"):
        parse(text, _BACKENDS)


def test_parse_rejects_a_default_that_is_not_a_defined_environment():
    # arrange: default points at a non-existent environment
    text = "default: staging\nenvironments:\n  dev: { backend: local }\n"

    # act / assert
    with pytest.raises(ValueError, match="default"):
        parse(text, _BACKENDS)


def test_parse_rejects_an_empty_environment_set():
    # arrange / act / assert
    with pytest.raises(ValueError, match="no environments"):
        parse("default: dev\nenvironments: {}\n", _BACKENDS)


def test_parse_data_builds_the_registry_from_an_already_parsed_mapping():
    # arrange: the one-manifest path hands parse_data an already-loaded dict, not text (no yaml round-trip)
    data = {"default": "dev",
            "environments": {"dev": {"backend": "local", "description": "Local lab."},
                             "prod": {"backend": "cloud"}}}

    # act
    reg = parse_data(data, _BACKENDS)

    # assert: same registry the text form yields, straight from the mapping
    assert set(reg.environments) == {"dev", "prod"}
    assert reg.environments["dev"].backend == "local"
    assert reg.default == "dev"


def test_parse_data_rejects_an_unknown_backend_from_a_mapping():
    # arrange: the same validation applies on the mapping path
    data = {"default": "dev", "environments": {"dev": {"backend": "kubernetes"}}}

    # act / assert
    with pytest.raises(ValueError, match="backend"):
        parse_data(data, _BACKENDS)
