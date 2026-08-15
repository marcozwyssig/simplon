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
  code:
    fmt:  { impl: "demo_impls:fmt",  help: "Format the sources." }
    lint: { impl: "demo_impls:lint", help: "Lint the sources." }
  build:
    build: { impl: "demo_impls:build", help: "Build the artefacts." }
  test:
    unit: { impl: "demo_impls:unit",     help: "Unit gate.", passthrough_args: true }
    all:  { impl: "demo_impls:test_all", help: "Every test stage." }
  deploy:
    up:  { impl: "demo_impls:up",         help: "Deploy up." }
    all: { impl: "demo_impls:deploy_all", help: "Full bring-up." }
env_groups: [deploy]
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
  build:
    build: { impl: "gd_impls:build", help: "Build the images." }
    diff:  { impl: "gd_impls:diff",  help: "Show the schema diff." }
    docs:  { impl: "gd_impls:docs",  help: "Render the docs." }
  package:
    package: { impl: "gd_impls:package", help: "Package the images." }
env_groups: []
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


# --- hidden command (netctl#1277): a plan step need not clutter --help --------------------------------

_HIDDEN_MANIFEST = """
product: demo
groups:
  code:
    fmt:  { impl: "hidden_impls:fmt",  help: "Format the sources." }
    lint: { impl: "hidden_impls:lint", help: "Lint the sources.", hidden: true }
  package:
    package: { impl: "hidden_impls:package", help: "Package the artefacts.", hidden: true }
env_groups: []
"""


def _hidden_impls_module():
    mod = types.ModuleType("hidden_impls")
    for fn_name in ("fmt", "lint", "package"):
        def make(n):
            def _fn():
                return n
            _fn.__name__ = n
            return _fn
        setattr(mod, fn_name, make(fn_name))
    return mod


@pytest.fixture
def hidden_assembled():
    """Assemble a demo app whose `code` group has one hidden member (lint) beside a visible one (fmt), and
    whose single-member flat group `package` is itself hidden."""
    sys.modules["hidden_impls"] = _hidden_impls_module()
    try:
        import typer

        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
        cli.assemble(app, manifest.load(_HIDDEN_MANIFEST), product="demo")
        yield app
    finally:
        del sys.modules["hidden_impls"]


def test_a_hidden_grouped_command_is_absent_from_its_group_listing(hidden_assembled):
    # arrange: both members still REGISTER under the group (Typer needs the registration to dispatch the
    # name at all); `hidden` is what Click's listing/`--help` rendering reads to omit a command
    code_members = {c.name: c for c in _groups(hidden_assembled)["code"].typer_instance.registered_commands}

    # assert: fmt is listed, the hidden lint sibling is marked hidden - so it drops out of `code --help`
    assert code_members["fmt"].hidden is False
    assert code_members["lint"].hidden is True


def test_a_hidden_grouped_commands_help_text_omits_it_from_the_group_listing(hidden_assembled):
    # arrange / act: render the group's own --help, the actual listing a human reads
    result = CliRunner().invoke(hidden_assembled, ["code", "--help"])

    # assert: fmt is advertised, lint is not - even though both dispatch fine (checked elsewhere)
    assert result.exit_code == 0, result.output
    assert "fmt" in result.output
    assert "lint" not in result.output


def test_a_hidden_grouped_command_keeps_its_hidden_flat_alias_and_stays_invocable(hidden_assembled):
    # arrange
    flat = _flat(hidden_assembled)

    # assert: the flat alias was always hidden regardless, and dispatches the same callback
    assert flat["lint"].hidden is True
    assert flat["lint"].callback is sys.modules["hidden_impls"].lint
    result = CliRunner().invoke(hidden_assembled, ["lint"])
    assert result.exit_code == 0, result.output


def test_a_non_hidden_grouped_commands_flat_alias_is_unaffected_by_the_hidden_flag(hidden_assembled):
    # arrange
    flat = _flat(hidden_assembled)

    # assert: fmt's flat alias is the unrelated, unconditional #147 back-compat hiding - unchanged by
    # this feature (fmt's GROUP listing entry is asserted visible above)
    assert flat["fmt"].hidden is True


def test_a_hidden_single_member_flat_group_hides_its_one_and_only_registration(hidden_assembled):
    # arrange
    flat = _flat(hidden_assembled)
    groups = _groups(hidden_assembled)

    # assert: `package` has no sub-app (collapsed) and its one registration is hidden, yet still invocable
    assert "package" not in groups
    assert flat["package"].hidden is True
    result = CliRunner().invoke(hidden_assembled, ["package"])
    assert result.exit_code == 0, result.output


# --- impl-less aggregate binding (#896): assemble synthesizes the aggregate's callback -----------------
# `bringup` is an impl-less aggregate (deps, no impl); assemble binds it to a kernel-synthesized closure
# that expands the #895 dependency plan through run_command and exits with the pipeline's rc.

_AGG_MANIFEST = """
product: demo
groups:
  build:
    install: { impl: "agg_impls:install", help: "Install host prereqs." }
    build:   { impl: "agg_impls:build",   help: "Build the artefacts." }
  deploy:
    up:      { impl: "agg_impls:up",   help: "Deploy up." }
    seed:    { impl: "agg_impls:seed", help: "Seed." }
    bringup: { help: "Full bring-up.", depends_on: [build, up, seed] }
env_groups: [deploy]
"""


def _agg_impls_module():
    mod = types.ModuleType("agg_impls")
    for fn_name in ("install", "build", "up", "seed"):
        def make(n):
            def _fn():
                return n
            _fn.__name__ = n
            return _fn
        setattr(mod, fn_name, make(fn_name))
    return mod


@pytest.fixture
def agg_assembled(monkeypatch):
    """Assemble a demo app whose manifest declares the `bringup` aggregate, injecting a fake
    StepFactoryContext that records every planned command and succeeds - so invoking the aggregate is
    observable end-to-end without a subprocess or the TUI (dispatch is forced headless-free by the fake
    steps; the steps themselves are instant)."""
    import typer

    from delivery.orchestrator import product
    from delivery.orchestrator.steps import Outcome, Step, run_headless

    monkeypatch.setattr(product, "dispatch", run_headless)
    built: list[str] = []

    def step_factory(cmd: str) -> Step:
        built.append(cmd)
        return Step(label=cmd, action=lambda: Outcome(rc=0, output=""))

    step_ctx = product.StepFactoryContext("demo", step_factory)
    sys.modules["agg_impls"] = _agg_impls_module()
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
        cli.assemble(app, manifest.load(_AGG_MANIFEST), product="demo", step_context=step_ctx)
        yield app, built
    finally:
        del sys.modules["agg_impls"]


def test_an_impl_less_aggregate_registers_under_its_group_with_a_hidden_flat_alias(agg_assembled):
    # arrange
    app, _ = agg_assembled

    # assert: registration behaviour is unchanged - a subcommand of its group plus a hidden flat alias
    deploy_members = {c.name for c in _groups(app)["deploy"].typer_instance.registered_commands}
    assert "bringup" in deploy_members
    flat = _flat(app)
    assert flat["bringup"].hidden is True


def test_invoking_an_aggregate_runs_its_dependency_plan_and_exits_zero(agg_assembled):
    # arrange
    app, built = agg_assembled

    # act: the hidden flat alias dispatches the synthesized callback
    result = CliRunner().invoke(app, ["bringup"])

    # assert: the plan's leaves were built as steps in dependency order and the run exited 0
    assert result.exit_code == 0, result.output
    assert built == ["build", "up", "seed"]


def test_assemble_fails_loudly_when_an_aggregate_manifest_gets_no_step_context():
    # arrange: the same manifest, but the product forgot to inject its StepFactoryContext
    import typer

    sys.modules["agg_impls"] = _agg_impls_module()
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")

        # act / assert: assembly (not first invocation) rejects the unbindable aggregate
        with pytest.raises(ValueError, match="'deploy.bringup' is an impl-less aggregate"):
            cli.assemble(app, manifest.load(_AGG_MANIFEST), product="demo")
    finally:
        del sys.modules["agg_impls"]


def test_the_aggregates_help_line_is_its_synthesized_callbacks_docstring(agg_assembled):
    # arrange
    app, _ = agg_assembled

    # assert: Typer renders the spec's help from the closure docstring
    bringup = next(c for c in _groups(app)["deploy"].typer_instance.registered_commands
                   if c.name == "bringup")
    assert bringup.callback.__doc__ == "Full bring-up."
