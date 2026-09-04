"""Unit tests for delivery.environments.Provider - the stateful environments seam every adopting product
used to carry as a scaffolded copy. The precedence and the group/environment collision are what these
pin down, because that is where the copies had already drifted apart. AAA throughout.
"""
import pytest

from delivery import context, environments
from delivery.environments import Provider

_MANIFEST = """\
product: sample
groups:
  test:
    test: { impl: "sample.cli:test", help: "Run the suite." }
  deploy:
    up: { impl: "sample.cli:up", help: "Bring it up." }
env_groups: [deploy]
default: prod
environments:
  dev:  { backend: local, description: "Local." }
  test: { backend: local, description: "Trial." }
  prod: { backend: local, description: "Live." }
"""

_NO_ENVIRONMENTS = """\
product: sample
groups:
  code:
    lint: { impl: "sample.cli:lint", help: "Lint it." }
env_groups: []
"""


@pytest.fixture
def provider(monkeypatch, tmp_path):
    manifest = tmp_path / "sample.yaml"
    manifest.write_text(_MANIFEST)
    context.set_current(context.ProductContext(name="sample", root=tmp_path, manifest_path=manifest))
    monkeypatch.delenv("SAMPLE_ENV", raising=False)
    return Provider("SAMPLE_ENV", shim="./sample.sh")


def test_the_matrix_is_read_out_of_the_products_manifest(provider):
    # arrange: the fixture registered a manifest carrying three environments

    names = provider.names()

    assert names == ["dev", "test", "prod"]


def test_without_the_variable_the_manifest_default_is_the_target(provider):
    # arrange: the fixture cleared SAMPLE_ENV

    target = provider.default()

    assert target == "prod"


def test_the_exported_variable_selects_an_environment_the_cli_token_cannot_reach(provider, monkeypatch):
    # arrange: `test` is also a GROUP, so `./sample.sh test ...` runs the suite, not the instance
    monkeypatch.setenv("SAMPLE_ENV", "test")

    target = provider.default()

    assert target == "test"


def test_an_unknown_variable_value_falls_back_to_the_manifest_default(provider, monkeypatch):
    # arrange: a typo, or a variable left over from another product
    monkeypatch.setenv("SAMPLE_ENV", "staging")

    target = provider.default()

    assert target == "prod", "an unknown name must not become a target no command can act on"


def test_the_selected_target_and_the_active_environment_are_the_same_one(provider, monkeypatch):
    # arrange: the exact case the scaffolded copies disagreed on
    monkeypatch.setenv("SAMPLE_ENV", "dev")

    selected, active = provider.default(), provider.current()

    assert active.name == selected == "dev", (
        "default() drives the CLI's env-first selection and current() drives the commands; two answers "
        "means the CLI targets one environment while the command acts on another")


def test_a_manifest_without_environments_still_yields_a_runnable_local_one(monkeypatch, tmp_path):
    # arrange: a product that has not reached deployment yet
    manifest = tmp_path / "sample.yaml"
    manifest.write_text(_NO_ENVIRONMENTS)
    context.set_current(context.ProductContext(name="sample", root=tmp_path, manifest_path=manifest))
    monkeypatch.delenv("SAMPLE_ENV", raising=False)

    provider = Provider("SAMPLE_ENV", shim="./sample.sh")

    assert provider.names() == ["dev"]
    assert provider.is_local() is True


def test_an_environment_whose_backend_the_product_implements_passes_the_gate(provider):
    # arrange: every environment in the fixture manifest is local

    provider.require_backend()

    assert provider.is_local() is True


def test_an_environment_on_an_unimplemented_backend_dies_rather_than_mis_running(provider):
    # arrange: the product implements `local`, the caller demands a backend nothing declares

    with pytest.raises(SystemExit):
        provider.require_backend("cloud")


def test_a_hint_for_an_environment_shadowed_by_a_group_uses_the_variable(provider):
    # arrange: `test` names both an environment and a command group

    hint = provider.command_hint("test", "deploy down")

    assert hint == "SAMPLE_ENV=test ./sample.sh deploy down", (
        "the plain token form would run the GROUP, so an operator following this hint would tear down "
        "nothing and believe they had")


def test_a_hint_for_an_unshadowed_environment_uses_the_plain_token(provider):
    # arrange: `prod` collides with no group

    hint = provider.command_hint("prod", "deploy down")

    assert hint == "./sample.sh prod deploy down"


def test_the_provider_exposes_what_the_cli_seam_reads_off_it(provider):
    # arrange: delivery.cli.EnvironmentProvider is structural, so the attributes ARE the contract

    seam = (provider.ENV_VAR, provider.LOCAL)

    assert seam == ("SAMPLE_ENV", environments.LOCAL)
