"""Unit tests for delivery.tasks.env (netctl#1280, epic #1274 slice S6): the environments listing,
driven purely by the `environments:` / `default:` / `env_var:` keys of the manifest, read straight
through delivery.context - no backend registry, no product import. AAA throughout.
"""
import pytest

from delivery import context
from delivery.tasks import env as env_cmd
from delivery.context import ProductContext

_ENVS = {
    "dev": {"backend": "local", "description": "Local development lab."},
    "uat": {"backend": "cloud", "description": "Stakeholder sign-off."},
}


def _register(monkeypatch, tmp_path, data):
    manifest_path = tmp_path / "sample.yaml"
    ctx = ProductContext("sample", tmp_path, manifest_path)
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: data)
    return ctx


# --- the active marker ----------------------------------------------------------------------------------


def test_environments_marks_the_env_named_by_the_active_environment_variable(monkeypatch, tmp_path, capsys):
    # arrange: env_var points at SAMPLE_ENV, which is set to the non-default environment
    data = {"environments": _ENVS, "default": "dev", "env_var": "SAMPLE_ENV"}
    _register(monkeypatch, tmp_path, data)
    monkeypatch.setenv("SAMPLE_ENV", "uat")

    # act
    env_cmd.environments()

    # assert: the header names uat as active and its line carries the marker
    out = capsys.readouterr().out
    assert "active: uat" in out
    assert "* uat" in out
    assert "  dev" in out


def test_environments_falls_back_to_default_when_the_active_variable_is_unset(monkeypatch, tmp_path, capsys):
    # arrange
    data = {"environments": _ENVS, "default": "dev", "env_var": "SAMPLE_ENV"}
    _register(monkeypatch, tmp_path, data)
    monkeypatch.delenv("SAMPLE_ENV", raising=False)

    # act
    env_cmd.environments()

    # assert
    out = capsys.readouterr().out
    assert "active: dev" in out
    assert "* dev" in out


def test_environments_falls_back_to_default_when_the_variable_names_an_unknown_environment(
        monkeypatch, tmp_path, capsys):
    # arrange: a stale/garbage value must not be trusted as the active environment
    data = {"environments": _ENVS, "default": "dev", "env_var": "SAMPLE_ENV"}
    _register(monkeypatch, tmp_path, data)
    monkeypatch.setenv("SAMPLE_ENV", "does-not-exist")

    # act
    env_cmd.environments()

    # assert
    out = capsys.readouterr().out
    assert "active: dev" in out


# --- env_var absent from the manifest --------------------------------------------------------------------


def test_environments_works_without_an_env_var_key_and_reports_the_default_as_active(
        monkeypatch, tmp_path, capsys):
    # arrange: a manifest that has not adopted env_var yet - must not KeyError or crash
    data = {"environments": _ENVS, "default": "dev"}
    _register(monkeypatch, tmp_path, data)
    monkeypatch.setenv("SAMPLE_ENV", "uat")  # even if this happens to be set, it names no env_var key

    # act
    env_cmd.environments()

    # assert: with no env_var to consult, default is the only sensible active environment
    out = capsys.readouterr().out
    assert "active: dev" in out
    assert "* dev" in out


# --- pure manifest-driven listing, no backend registry -----------------------------------------------


def test_environments_lists_every_declared_environment_with_its_backend_and_description(
        monkeypatch, tmp_path, capsys):
    # arrange: backend names here are made up (not a real registry entry) - the listing must not validate
    data = {"environments": {"dev": {"backend": "made-up-backend", "description": "whatever"}},
           "default": "dev"}
    _register(monkeypatch, tmp_path, data)

    # act
    env_cmd.environments()

    # assert: an unregistered backend name is printed as-is, never rejected
    out = capsys.readouterr().out
    assert "made-up-backend" in out
    assert "whatever" in out


def test_environments_rejects_a_manifest_with_no_environments_section(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, {})

    # act / assert
    with pytest.raises(ValueError, match="'environments' section is missing or empty"):
        env_cmd.environments()


def test_environments_rejects_a_default_that_names_no_declared_environment(monkeypatch, tmp_path):
    # arrange
    data = {"environments": _ENVS, "default": "staging"}
    _register(monkeypatch, tmp_path, data)

    # act / assert
    with pytest.raises(ValueError, match="'default' must name a declared environment"):
        env_cmd.environments()
