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
import typer
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
    # `is` on the raw impl no longer holds: assemble WRAPS a leaf so the manifest's params:/with: apply
    # and the body's return value becomes the exit code (netctl#1444). `functools.wraps` keeps the
    # binding provable, and the flat alias must still be the SAME wrapper as the grouped registration -
    # two wrappers would mean two callbacks that could drift.
    assert alias.callback.__wrapped__ is sys.modules["demo_impls"].up
    assert alias.callback is _group_command(assembled, "deploy", "up").callback


def test_a_single_member_flat_group_is_one_visible_top_level_command_not_a_sub_app(assembled):
    # arrange
    flat = _flat(assembled)
    groups = _groups(assembled)

    # assert: 'build' is a VISIBLE flat command and has no sub-app.
    assert "build" not in groups
    assert flat["build"].hidden is False
    assert flat["build"].callback.__wrapped__ is sys.modules["demo_impls"].build


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
    assert flat["diff"].callback.__wrapped__ is sys.modules["gd_impls"].diff
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
    assert flat["lint"].callback.__wrapped__ is sys.modules["hidden_impls"].lint
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


# --- one impl bound to several commands (netctl#1406) ---------------------------------------------------


_SHARED_MANIFEST = """
product: demo
groups:
  test:
    system: { impl: "demo_impls:unit", help: "SYSTEM gate: the system suite against the running lab." }
    smoke:  { impl: "demo_impls:unit", help: "SMOKE gate: the fastest reachability check." }
    lint:   { impl: "demo_impls:lint", help: "Lint the sources." }
env_groups: []
"""


@pytest.fixture
def shared_impl_app():
    """A manifest where TWO commands point at the SAME impl - the shape a kernel suite runner produces,
    one callback backing every declared test level and identifying itself by the name it was invoked as."""
    sys.modules["demo_impls"] = _impls_module()
    try:
        import typer

        app = typer.Typer(add_completion=False, no_args_is_help=True, help="demo root")
        cli.assemble(app, manifest.load(_SHARED_MANIFEST), product="demo")
        yield app
    finally:
        del sys.modules["demo_impls"]


def _group_command(app, group, name):
    sub = next(g.typer_instance for g in app.registered_groups if g.name == group)
    return next(c for c in sub.registered_commands if c.name == name)


def test_assemble_takes_help_from_the_manifest_for_commands_sharing_one_impl(shared_impl_app):
    # arrange: both commands resolve to the same callable, so its single docstring cannot describe both
    system = _group_command(shared_impl_app, "test", "system")
    smoke = _group_command(shared_impl_app, "test", "smoke")

    # act
    rendered = (get_command(shared_impl_app).commands["test"].commands["system"].get_short_help_str(200),
                get_command(shared_impl_app).commands["test"].commands["smoke"].get_short_help_str(200))

    # assert: each renders its OWN manifest help, not the shared docstring
    # Two commands sharing one impl now get their OWN wrapper each, and that is the stronger property:
    # a wrapper carries that command's `params:` and its `with:` pins, so sharing one would make #1406's
    # `gate(name="system")` next to `gate(name="smoke")` impossible. What must be shared is the BODY.
    assert system.callback is not smoke.callback
    assert system.callback.__wrapped__ is smoke.callback.__wrapped__
    assert rendered[0].startswith("SYSTEM gate")
    assert rendered[1].startswith("SMOKE gate")


def test_assemble_leaves_an_unshared_impls_help_to_its_docstring(shared_impl_app):
    # arrange / act: a command whose impl only IT uses must be untouched by the rule above
    lint = _group_command(shared_impl_app, "test", "lint")

    # assert: no help override was applied, so Typer still reads the callback's own docstring
    assert lint.help is None


# --- assemble(skip=...): the hybrid while the migration runs (netctl#1444) ----------------------------

_HYBRID = """
groups:
  test:
    unit:   { impl: "delivery.test_impls:nullary", help: "One gate." }
    report: { impl: "delivery.test_impls:no_context", help: "Merge the results." }
  git:
    commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
env_groups: []
"""


def test_a_skipped_group_is_not_registered_at_all():
    # arrange: the product's generated module already owns `test`, so this assembly must leave it alone -
    # both registering it would have two add_typer calls under one name and one would win silently
    mf = manifest.load(_HYBRID)
    app = typer.Typer(add_completion=False)

    # act
    cli.assemble(app, mf, product="sample",
                 skip=frozenset({("test", "unit"), ("test", "report")}))

    # assert: `git` is here, `test` is not, and neither are the skipped flat aliases
    root = get_command(app)
    ctx = click.Context(root)
    assert root.get_command(ctx, "git") is not None
    assert root.get_command(ctx, "test") is None
    assert root.get_command(ctx, "unit") is None
    assert root.get_command(ctx, "commit") is not None


def test_skipping_a_group_only_in_part_is_rejected():
    # arrange: half a group would make both mechanisms register a sub-app under one name; Click keeps one
    # and the other's members vanish with nothing raised
    mf = manifest.load(_HYBRID)

    # act / assert
    with pytest.raises(ValueError, match="in part"):
        cli.assemble(typer.Typer(add_completion=False), mf, product="sample",
                     skip=frozenset({("test", "unit")}))


def test_skipping_a_group_the_manifest_does_not_declare_is_rejected():
    # arrange: a stale entry would silently protect nothing
    mf = manifest.load(_HYBRID)

    # act / assert
    with pytest.raises(ValueError, match="tset"):
        cli.assemble(typer.Typer(add_completion=False), mf, product="sample",
                     skip=frozenset({("tset", "unit")}))


def test_skipping_nothing_is_the_default_and_assembles_everything():
    # arrange / act
    app = typer.Typer(add_completion=False)
    cli.assemble(app, manifest.load(_HYBRID), product="sample")

    # assert
    root = get_command(app)
    assert root.get_command(click.Context(root), "test") is not None


# --- what assemble owes a framework-free body (netctl#1444) -------------------------------------------

_RC_MANIFEST = """
product: demo
groups:
  code:
    ok:    { impl: "rc_impls:ok",     help: "Succeed." }
    fail:  { impl: "rc_impls:fail",   help: "Fail with 3." }
    chatty: { impl: "rc_impls:chatty", help: "Return something that is not an exit code." }
env_groups: []
"""


@pytest.fixture
def rc_app():
    mod = types.ModuleType("rc_impls")
    mod.ok = lambda: None
    mod.fail = lambda: 3
    mod.chatty = lambda: "done"
    for name in ("ok", "fail", "chatty"):
        getattr(mod, name).__name__ = name
    sys.modules["rc_impls"] = mod
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True)
        cli.assemble(app, manifest.load(_RC_MANIFEST), product="demo")
        yield app
    finally:
        sys.modules.pop("rc_impls", None)


def test_a_body_that_returns_an_exit_code_exits_with_it(rc_app):
    # arrange: Click DISCARDS a callback's return value in standalone mode - only a raised typer.Exit sets
    # the code. A framework-free body (`return rc`) bound raw therefore produced a CLI that always exited
    # 0 however it failed, which is what this coupling exists to stop.
    runner = CliRunner()

    # act
    result = runner.invoke(rc_app, ["code", "fail"])

    # assert
    assert result.exit_code == 3


def test_a_body_that_returns_none_exits_zero(rc_app):
    # arrange / act
    result = CliRunner().invoke(rc_app, ["code", "ok"])

    # assert
    assert result.exit_code == 0


def test_a_body_returning_something_that_is_not_an_exit_code_is_ignored_rather_than_fatal(rc_app):
    # arrange: assemble binds whatever body a product ALREADY wrote, and Click has always thrown those
    # values away - so a body returning a log line is not a defect, it is one written when the return
    # value could not matter. Raising on it would turn a working CLI into a crashing one on upgrade.
    # act
    result = CliRunner().invoke(rc_app, ["code", "chatty"])

    # assert
    assert result.exit_code == 0


_PRESENTED_MANIFEST = """
product: demo
groups:
  code:
    commit:
      impl: "pres_impls:commit"
      help: "Commit."
      params:
        message: { help: "commit message", argument: true }
        dry_run: { help: "preview only", short: "-n" }
    pin:
      impl: "pres_impls:pin"
      help: "Pin a site."
      with: { site: "be" }
env_groups: []
"""


@pytest.fixture
def presented_app():
    mod = types.ModuleType("pres_impls")

    def commit(message: str = "", dry_run: bool = False):
        return 0

    def pin(site: str):
        return 0

    mod.commit, mod.pin = commit, pin
    sys.modules["pres_impls"] = mod
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True)
        cli.assemble(app, manifest.load(_PRESENTED_MANIFEST), product="demo")
        yield app
    finally:
        sys.modules.pop("pres_impls", None)


def test_assemble_applies_the_manifests_params_block(presented_app):
    # arrange: the whole point of making bodies framework-free is that ONE body serves both mechanisms.
    # Until netctl#1444 assemble bound the raw body, so everything the `params:` block carries - help,
    # short flags, positional-ness - was silently absent on this path while the generated module had it.
    cmd = get_command(presented_app).commands["code"].commands["commit"]

    # act
    by_name = {p.name: p for p in cmd.params}

    # assert
    assert isinstance(by_name["message"], click.Argument)
    assert by_name["dry_run"].opts == ["--dry-run"] and by_name["dry_run"].secondary_opts == ["-n"] or \
           by_name["dry_run"].opts == ["--dry-run", "-n"]
    assert by_name["dry_run"].help == "preview only"


def test_a_pinned_parameter_is_absent_from_the_command_line(presented_app):
    # arrange: `with:` FIXES a parameter, so it is not a command-line parameter at all - the same rule the
    # generated module follows. A required parameter pinned this way must not resurface as an argument.
    cmd = get_command(presented_app).commands["code"].commands["pin"]

    # act / assert
    assert [p.name for p in cmd.params] == []


def test_a_with_key_naming_no_parameter_of_the_impl_is_rejected():
    # arrange: a silently ignored pin is the failure this check exists for
    text = _PRESENTED_MANIFEST.replace('with: { site: "be" }', 'with: { sight: "be" }')
    mod = types.ModuleType("pres_impls")
    mod.commit = lambda message="", dry_run=False: 0
    mod.pin = lambda site: 0
    sys.modules["pres_impls"] = mod
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True)

        # act / assert
        with pytest.raises(ValueError, match="sight"):
            cli.assemble(app, manifest.load(text), product="demo")
    finally:
        sys.modules.pop("pres_impls", None)


_NESTED_MANIFEST = """
product: demo
taxonomy:
  support:
    help: "Host upkeep."
    groups:
      git: { help: "Version control." }
groups:
  support:
    doctor: { impl: "demo_impls:lint", help: "Check the host." }
  support.git:
    push: { impl: "demo_impls:up", help: "Push." }
env_groups: []
"""


def test_a_nested_group_hangs_from_its_parent_not_from_the_root():
    # arrange: assemble used to call add_typer(name="support.git") on the ROOT, producing one shell token
    # containing a dot - invokable only as `demo support.git push`, which no help text ever claimed
    # (netctl#1444). The generated module always nested; this is the two mechanisms agreeing again.
    sys.modules["demo_impls"] = _impls_module()
    try:
        app = typer.Typer(add_completion=False, no_args_is_help=True)
        cli.assemble(app, manifest.load(_NESTED_MANIFEST), product="demo")
        root = get_command(app)
        ctx = click.Context(root)

        # act
        support = root.get_command(ctx, "support")

        # assert
        assert [n for n in root.list_commands(ctx) if "." in n] == []
        assert "git" in support.list_commands(click.Context(support))
        assert support.get_command(click.Context(support), "git").get_short_help_str(60).startswith("git")
    finally:
        sys.modules.pop("demo_impls", None)
