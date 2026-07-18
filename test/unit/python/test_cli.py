"""Unit tests for the Typer binding layer (delivery.cli.assemble): the manifest -> Typer wiring exercised
on a SYNTHETIC manifest so the assembly is validated independently of any product's command set. Covers
the sub-app-per-group shape, the hidden flat back-compat aliases, the single-member flat-group collapse,
the ambiguous-name no-alias rule, the passthrough context settings, and the product-named CD panel.

The impls are a hermetic in-memory module registered in sys.modules, so `manifest.resolve_impl` resolves
each `module:function` ref to a real, identity-checkable callable without touching the filesystem or any
product. AAA throughout.
"""
import sys
import types

import click
import pytest
from typer.main import get_command
from typer.testing import CliRunner

from delivery import cli
from delivery.orchestrator import manifest


def _impls_module():
    """A throwaway module exposing the callables the synthetic manifest's impl refs point at, so identity
    of the registered callback can be asserted."""
    mod = types.ModuleType("demo_impls")
    for fn_name in ("fmt", "lint", "build", "unit", "test_all", "up", "deploy_all"):
        def make(n):
            def _fn():
                return n
            _fn.__name__ = n
            return _fn
        setattr(mod, fn_name, make(fn_name))
    return mod


_MANIFEST = """
product: demo
groups:
  code:   [fmt, lint]
  build:  [build]
  test:   [unit, all]
  deploy: [up, all]
env_groups: [deploy]
commands:
  fmt:        { impl: "demo_impls:fmt",        help: "Format the sources." }
  lint:       { impl: "demo_impls:lint",       help: "Lint the sources." }
  build:      { impl: "demo_impls:build",      help: "Build the artefacts." }
  unit:       { impl: "demo_impls:unit",       help: "Unit gate.", passthrough_args: true }
  test.all:   { impl: "demo_impls:test_all",   help: "Every test stage." }
  up:         { impl: "demo_impls:up",         help: "Deploy up." }
  deploy.all: { impl: "demo_impls:deploy_all", help: "Full bring-up." }
"""


@pytest.fixture
def assembled():
    """Register the impls module, load the manifest, and assemble a fresh Typer app under product 'demo'."""
    sys.modules["demo_impls"] = _impls_module()
    try:
        import typer

        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
        cli.assemble(app, manifest.load(_MANIFEST), product="demo")
        yield app
    finally:
        del sys.modules["demo_impls"]


def _flat(app):
    """Map of top-level flat command name -> its CommandInfo (the app-level registrations)."""
    return {c.name: c for c in app.registered_commands}


def _groups(app):
    """Map of sub-app group name -> its TyperInfo (the app-level group registrations)."""
    return {g.name: g for g in app.registered_groups}


def test_a_non_flat_group_becomes_a_sub_app(assembled):
    # arrange / act
    groups = _groups(assembled)

    # assert: code, test and deploy are sub-apps; the single-member 'build' group is NOT (it collapses).
    assert set(groups) == {"code", "test", "deploy"}


def test_a_grouped_command_gets_a_hidden_flat_back_compat_alias_on_the_same_callback(assembled):
    # arrange
    flat = _flat(assembled)

    # act: the deploy group's 'up' also registers as a hidden top-level alias.
    alias = flat["up"]

    # assert: hidden, and bound to the exact same callable resolved from the manifest impl.
    assert alias.hidden is True
    assert alias.callback is sys.modules["demo_impls"].up


def test_a_single_member_flat_group_is_one_visible_top_level_command_not_a_sub_app(assembled):
    # arrange
    flat = _flat(assembled)
    groups = _groups(assembled)

    # assert: 'build' is a VISIBLE flat command and has no sub-app.
    assert "build" not in groups
    assert flat["build"].hidden is False
    assert flat["build"].callback is sys.modules["demo_impls"].build


def test_a_name_owned_by_several_groups_gets_no_flat_alias(assembled):
    # arrange
    flat = _flat(assembled)

    # assert: 'all' lives in both test and deploy, so it has NO flat top-level form; only its group members
    # exist under each sub-app.
    assert "all" not in flat
    test_members = {c.name for c in _groups(assembled)["test"].typer_instance.registered_commands}
    deploy_members = {c.name for c in _groups(assembled)["deploy"].typer_instance.registered_commands}
    assert "all" in test_members and "all" in deploy_members


def test_a_passthrough_command_carries_the_forwarding_context_settings(assembled):
    # arrange: 'unit' is declared passthrough_args, registered under the test sub-app.
    unit = next(c for c in _groups(assembled)["test"].typer_instance.registered_commands if c.name == "unit")

    # assert: it forwards unknown trailing args to its underlying tool.
    assert unit.context_settings == {"allow_extra_args": True, "ignore_unknown_options": True}


def test_the_cd_panel_reads_in_the_product_voice(assembled):
    # arrange
    groups = _groups(assembled)

    # act / assert: the env-first deploy group is panelled with the product name, the agnostic code group is
    # on the generic CI panel.
    assert groups["deploy"].rich_help_panel == "CD / env-first (demo <env> <group> <cmd>, default dev)"
    assert groups["code"].rich_help_panel == "CI / agnostic (no env)"


def test_the_assembled_app_compiles_to_a_click_tree_with_the_expected_top_level_nodes(assembled):
    # arrange / act: compile the Typer app to its Click command tree (what the user actually invokes).
    root = get_command(assembled)
    ctx = click.Context(root, info_name="demo")
    names = set(root.list_commands(ctx))

    # assert: the three sub-apps, the collapsed flat 'build', and the hidden flat aliases are all present;
    # the ambiguous 'all' is absent as a flat node.
    assert {"code", "test", "deploy", "build", "up", "fmt", "lint"} <= names
    assert "all" not in names


# --- group-default-command (#592 D4): a multi-member group named after one of its members ---------------

_GD_MANIFEST = """
product: demo
groups:
  build:   [build, diff, docs]
  package: [package]
env_groups: []
commands:
  build:   { impl: "gd_impls:build",   help: "Build the images." }
  diff:    { impl: "gd_impls:diff",    help: "Show the schema diff." }
  docs:    { impl: "gd_impls:docs",    help: "Render the docs." }
  package: { impl: "gd_impls:package", help: "Package the images." }
"""


def _gd_impls_module(calls: list[str]):
    """Impls that RECORD their invocation, so a bare group token running its namesake member's callback is
    observable end-to-end (via CliRunner), not just by structural introspection."""
    mod = types.ModuleType("gd_impls")
    for fn_name in ("build", "diff", "docs", "package"):
        def make(n):
            def _fn():
                calls.append(n)
            _fn.__name__ = n
            return _fn
        setattr(mod, fn_name, make(fn_name))
    return mod


@pytest.fixture
def gd_assembled():
    """Assemble a demo app whose `build` group is the group-default shape (build/diff/docs), recording
    every impl invocation in `calls`."""
    import typer

    calls: list[str] = []
    sys.modules["gd_impls"] = _gd_impls_module(calls)
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
        cli.assemble(app, manifest.load(_GD_MANIFEST), product="demo")
        yield app, calls
    finally:
        del sys.modules["gd_impls"]


def test_a_group_default_group_is_registered_as_a_sub_app(gd_assembled):
    # arrange
    app, _ = gd_assembled

    # act / assert: unlike the single-member flat collapse, a group-default group IS a sub-app (so its
    # siblings are reachable as subcommands); the single-member `package` still collapses to a flat command
    groups = _groups(app)
    assert "build" in groups
    assert "package" not in groups


def test_a_bare_group_default_token_runs_the_namesake_member_not_group_help(gd_assembled):
    # arrange
    app, calls = gd_assembled

    # act: invoke the bare group token with no subcommand
    result = CliRunner().invoke(app, ["build"])

    # assert: the namesake `build` member ran as the default action (it did NOT fall through to group help)
    assert result.exit_code == 0, result.output
    assert calls == ["build"]


def test_a_group_default_sibling_dispatches_as_a_subcommand(gd_assembled):
    # arrange
    app, calls = gd_assembled

    # act: `demo build diff` runs the sibling, not the namesake default
    result = CliRunner().invoke(app, ["build", "diff"])

    # assert
    assert result.exit_code == 0, result.output
    assert calls == ["diff"]


def test_a_group_default_sibling_keeps_its_hidden_flat_back_compat_alias(gd_assembled):
    # arrange
    app, calls = gd_assembled
    flat = _flat(app)

    # assert: `diff` is registered as a HIDDEN top-level flat alias on the same callback...
    assert flat["diff"].hidden is True
    assert flat["diff"].callback is sys.modules["gd_impls"].diff
    # ...and invoking it runs the sibling
    result = CliRunner().invoke(app, ["diff"])
    assert result.exit_code == 0, result.output
    assert calls == ["diff"]


def test_a_group_default_namesake_is_neither_a_subcommand_nor_a_separate_flat_command(gd_assembled):
    # arrange
    app, _ = gd_assembled
    flat = _flat(app)

    # assert: the namesake `build` is the group's DEFAULT action only - not a top-level flat command, and
    # not registered as a `build build` subcommand (its siblings are the only subcommands)
    assert "build" not in flat
    build_sub = {c.name for c in _groups(app)["build"].typer_instance.registered_commands}
    assert build_sub == {"diff", "docs"}
