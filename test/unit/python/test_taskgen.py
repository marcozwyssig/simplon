"""Unit tests for the CLI generator (delivery.taskgen, netctl#1434, retargeted to Typer in #1437):
signature introspection, `with:` binding, determinism, the drift gate, and the negative cases. Exercised
against REAL importable bodies (delivery.test_impls), because introspecting a mock would verify the mock.

Several tests import the RENDERED text and register it onto a Typer app. Asserting on the text says what
was written; asserting on the assembled Click tree says what Click made of it, and the tree is what
netctl's cli_surface golden compares. AAA throughout."""
import importlib.util

import click
import pytest
import typer
from click.testing import CliRunner
from typer.main import get_command

from delivery import taskgen
from delivery.orchestrator import manifest

_MANIFEST = """
groups:
  lab:
    seed: { impl: "delivery.test_impls:seed", help: "Seed the lab.", with: { sites: zh } }
"""


def _load(text=_MANIFEST):
    return manifest.load(text)


def _module(m, tmp_path, source="demo.yaml", product="sample", groups=None):
    """Render and import the generated module."""
    path = tmp_path / "_generated_cli.py"
    path.write_text(taskgen.render(m, source=source, product=product, groups=groups))
    spec = importlib.util.spec_from_file_location(f"_generated_cli_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assembled(m, tmp_path, source="demo.yaml", product="sample", groups=None):
    """Render, import and register the module onto a fresh root app; return the Click tree.

    Asserting on the TREE rather than only on the rendered text is deliberate: the text says what was
    written, the tree says what Click made of it, and the tree is what netctl's cli_surface golden
    compares.
    """
    module = _module(m, tmp_path, source, product, groups)
    app = typer.Typer(add_completion=False)
    module.register(app, aggregate=lambda name, group: 0)
    return get_command(app)


def _sub(cmd, name):
    return cmd.get_command(click.Context(cmd), name)



# --- render: the manifest is the model, the signature comes from the body ---------------------------

def test_the_rendered_module_declares_a_command_per_manifest_entry():
    # arrange / act
    text = taskgen.render(_load(), source="demo.yaml", product="sample")

    # assert: a plain function plus its registration under the manifest's name, carrying the body's
    # docstring as the help summary (see the docstring rule below)
    assert "def seed(" in text
    assert "_g_lab.command(name='seed', hidden=False)(seed)" in text
    assert "'Seed the lab and run the smoke test.'" in text


def test_the_generated_module_registers_onto_a_caller_supplied_app():
    # arrange: the product owns its ROOT app - its help blurb is its voice, and its own internal
    # commands live on it. The generated module only ADDS, which is what keeps netctl's
    # `wireguard-guard` and its `Internal` panel untouched by a regeneration.
    text = taskgen.render(_load(), source="demo.yaml", product="sample")

    # assert
    assert "def register(app: typer.Typer, *, aggregate: object = None) -> None:" in text
    assert "from invoke" not in text
    assert "@task" not in text


def test_the_signature_comes_from_the_body_not_from_the_manifest():
    # arrange: the manifest names neither `sites` nor `dry_run`
    text = taskgen.render(_load(), source="demo.yaml", product="sample")

    # assert: introspected and typed from the body - an UNANNOTATED default makes Typer read a bool as a
    # text option. `sites` is fixed by `with:`, so it is not on the command line at all (netctl#1442).
    assert "def seed(ctx: typer.Context, dry_run: bool = False)" in text
    assert "sites" not in text.split("def register")[0].split("def seed")[1].split(")")[0]


def test_the_wrapper_delegates_to_the_impl_by_keyword_and_raises_the_rc():
    # arrange / act
    text = taskgen.render(_load(), source="demo.yaml", product="sample")

    # assert: the body returns an int; the WRAPPER is what knows about process exit codes. The pinned
    # `sites` is passed as its LITERAL - it never reached the command line, so there is no variable in
    # scope to forward (netctl#1442).
    assert ("raise typer.Exit(_rc(delivery.test_impls.seed(ctx, sites='zh', dry_run=dry_run)))"
            in text)


def test_rendering_twice_is_byte_identical():
    # arrange: the drift gate compares TEXT, so a non-deterministic render makes it useless
    m = _load()

    # act / assert
    assert taskgen.render(m, source="demo.yaml", product="sample") == taskgen.render(m, source="demo.yaml", product="sample")


def test_the_rendered_module_imports_and_assembles_a_real_click_tree(tmp_path):
    # arrange / act: the point of committing generated code is that it IS code - so prove it runs
    root = _assembled(_load(), tmp_path)

    # assert: reachable as `lab seed`, with the introspected parameters on it - minus the one `with:`
    # pinned
    group = root.get_command(click.Context(root), "lab")
    leaf = group.get_command(click.Context(group), "seed")
    assert [p.name for p in leaf.params] == ["dry_run"]


def test_a_command_name_with_a_dash_becomes_a_legal_identifier(tmp_path):
    # arrange: `disk-guard` is not a Python name, but the TASK must keep the dashed name
    m = _load("""
groups:
  support:
    disk-guard: { impl: "delivery.test_impls:seed", help: "Guard the disk." }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "def disk_guard(" in text
    assert "command(name='disk-guard', hidden=False)(disk_guard)" in text


def test_a_variadic_body_renders_a_command_with_no_declared_parameters():
    # arrange: neither Click nor Typer binds *args to a parameter. Such a command is `passthrough_args`
    # and its raw tail reaches the body through `ctx.args`, which the per-command context settings allow.
    m = _load("""
groups:
  build:
    gradle: { impl: "delivery.test_impls:gradle", help: "Run gradle.", passthrough_args: true }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "def gradle(ctx: typer.Context) -> None:" in text
    assert "*args" not in text


def test_a_command_whose_impl_cannot_be_imported_fails_at_render():
    # arrange: a typo must fail HERE, not forty minutes into a deploy
    m = _load("""
groups:
  lab:
    seed: { impl: "delivery.nope:missing", help: "Seed the lab." }
""")

    # act / assert
    with pytest.raises(Exception):
        taskgen.render(m, source="demo.yaml", product="sample")


def test_an_impl_less_aggregate_is_rendered_and_dispatches_through_the_product():
    # arrange: a depends_on aggregate has no body to wrap, but it IS a real invocable command
    # (`netctl build`, `netctl test all`). Skipping it would delete it from the surface. It expands
    # through its dependency plan, which only the product can dispatch, so the wrapper calls the hook
    # `register(aggregate=...)` binds.
    m = _load("""
groups:
  build:
    build: { depends_on: [seed], help: "Build it." }
    seed:  { impl: "delivery.test_impls:seed", help: "Seed the lab." }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "def seed(" in text
    assert "def build() -> None:" in text
    assert "raise typer.Exit(_plan('build', 'build'))" in text


# --- the drift gate ----------------------------------------------------------------------------------

def test_check_returns_no_diff_when_the_file_matches_the_manifest(tmp_path):
    # arrange
    m = _load()
    target = tmp_path / "_generated.py"
    taskgen.write(m, target, source="demo.yaml", product="sample")

    # act / assert
    assert taskgen.check(m, target, source="demo.yaml", product="sample") is None


def test_check_returns_a_diff_when_the_manifest_moved_on(tmp_path):
    # arrange: the file was generated from an OLDER manifest
    target = tmp_path / "_generated.py"
    taskgen.write(_load(), target, source="demo.yaml", product="sample")
    moved = _load(_MANIFEST.replace("sites: zh", "sites: be"))

    # act
    diff = taskgen.check(moved, target, source="demo.yaml", product="sample")

    # assert: readable enough to act on without regenerating first
    assert diff is not None
    assert "sites='be'" in diff


def test_check_is_blind_to_a_help_change_the_generated_module_does_not_carry(tmp_path):
    # arrange: a non-shared impl takes its summary from the BODY's docstring, so editing the manifest's
    # `help:` legitimately does not move the generated file. Stating that here rather than leaving it
    # implied: `help:` still drives the plan/TUI labels and a shared impl's blurb, and a manifest whose
    # `help:` disagrees with its body's docstring is a real defect - one this gate cannot see, and one
    # that has to be caught by making the two agree.
    target = tmp_path / "_generated.py"
    taskgen.write(_load(), target, source="demo.yaml", product="sample")
    reworded = _load(_MANIFEST.replace("Seed the lab.", "Seed it and smoke-test it."))

    # act / assert
    assert taskgen.check(reworded, target, source="demo.yaml", product="sample") is None


def test_check_reports_a_missing_target_as_a_diff_rather_than_crashing(tmp_path):
    # arrange: a fresh checkout that never generated - the gate must SAY so, not raise
    # act
    diff = taskgen.check(_load(), tmp_path / "absent.py", source="demo.yaml", product="sample")

    # assert
    assert diff is not None


def test_write_is_idempotent_and_reports_whether_it_changed_anything(tmp_path):
    # arrange
    m = _load()
    target = tmp_path / "_generated.py"

    # act
    first = taskgen.write(m, target, source="demo.yaml", product="sample")
    second = taskgen.write(m, target, source="demo.yaml", product="sample")

    # assert
    assert first is True
    assert second is False


# --- what the review found: generated source must be safe, valid and honest -------------------------

def test_a_help_text_containing_triple_quotes_cannot_escape_the_docstring(tmp_path):
    # arrange: interpolating help into \"\"\"...\"\"\" let a manifest close the docstring and have the rest
    # of its text EXECUTED on import - arbitrary code execution from manifest content alone
    m = _load('''
groups:
  lab:
    seed:
      impl: "delivery.test_impls:seed"
      help: "Seed it.\\"\\"\\"\\nimport os\\nBREACH = os.getcwd()\\nx = \\"\\"\\""
''')

    # act
    path = tmp_path / "gen.py"
    path.write_text(taskgen.render(m, source="demo.yaml", product="sample"))
    spec = importlib.util.spec_from_file_location("gen_escape", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # assert: the payload stayed data
    assert not hasattr(module, "BREACH")


def test_a_command_name_containing_a_quote_cannot_escape_the_task_decorator():
    # arrange
    m = _load('''
groups:
  lab:
    'se"ed': { impl: "delivery.test_impls:seed", help: "Seed it." }
''')

    # act / assert: rejected as an illegal identifier rather than rendered into broken source
    with pytest.raises(ValueError, match="identifier"):
        taskgen.render(m, source="demo.yaml", product="sample")


def test_a_command_named_after_a_python_keyword_is_rejected():
    # arrange: `def import(c):` does not parse
    m = _load('''
groups:
  lab:
    import: { impl: "delivery.test_impls:seed", help: "Import it." }
''')

    # act / assert
    with pytest.raises(ValueError, match="identifier"):
        taskgen.render(m, source="demo.yaml", product="sample")


def test_a_with_value_yaml_typed_into_a_datetime_is_rejected():
    # arrange: an UNQUOTED date is a datetime.date to PyYAML. repr() of it is valid Python that needs an
    # import the generated module does not have, so the file failed only when imported - while the drift
    # gate stayed green, because the broken text rendered identically every time.
    m = _load('''
groups:
  lab:
    seed: { impl: "delivery.test_impls:seed", help: "Seed it.", with: { sites: 2026-01-01 } }
''')

    # act / assert
    with pytest.raises(ValueError, match="datetime|cannot be written"):
        taskgen.render(m, source="demo.yaml", product="sample")


def test_a_required_parameter_stays_required(tmp_path):
    # arrange: rendering it as =None turned a mandatory argument optional and moved the failure out of
    # the CLI parser into whatever the body does with None
    m = _load('''
groups:
  lab:
    pin: { impl: "delivery.test_impls:needs_site", help: "Pin a site." }
''')

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "def pin(ctx: typer.Context, site) -> None:" in text
    assert "site=None" not in text


def test_a_body_without_a_context_parameter_is_not_handed_one(tmp_path):
    # arrange: delivery.commands.vcs:commit takes its payload FIRST and no Context at all. Dropping
    # parameter 0 by position discarded the payload and passed a Context object in its place.
    m = _load('''
groups:
  git:
    commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
''')

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert: no context parameter at all, and the payload forwarded by keyword
    assert "def commit(message=None) -> None:" in text
    assert "no_context(message=message)" in text


def test_a_body_with_no_parameters_at_all_is_called_with_none(tmp_path):
    # arrange: delivery.commands.vcs:push takes nothing; `push(c)` raised TypeError at call time
    m = _load('''
groups:
  git:
    push: { impl: "delivery.test_impls:nullary", help: "Push." }
''')

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "def push() -> None:" in text
    assert "nullary()" in text


def test_binding_the_context_parameter_by_name_is_rejected():
    # arrange: the context IS a signature parameter, so validating against every name in the signature
    # accepted it - and the generator then discarded it silently. Binding it is the likeliest real typo
    # of all, so the fixture names the body's ACTUAL context parameter rather than a name it lacks.
    text = '''
groups:
  lab:
    seed: { impl: "delivery.test_impls:seed", help: "Seed it.", with: { ctx: nonsense } }
'''

    # act / assert
    with pytest.raises(ValueError, match="ctx"):
        manifest.load(text, validate_with=True)


# --- `params:` presentation in the rendered wrapper (netctl#1437) -------------------------------------

def test_a_param_declaring_a_short_flag_renders_an_explicit_typer_option():
    # arrange
    m = _load("""
groups:
  git:
    prune-branches:
      impl: "delivery.test_impls:pruner"
      help: "Delete merged branches."
      params:
        dry_run: { help: "preview only", short: "-n" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert ('dry_run: bool = typer.Option(False, "--dry-run", "-n", help=\'preview only\')' in text)


def test_a_param_declaring_short_first_puts_the_short_decl_before_the_long_one():
    # arrange: Click renders the decls in DECLARATION order, so this is what a user reads in `--help`.
    # netctl's surface uses both orders - `--watch -w` on one command, `-f --follow` on the next - so the
    # order is not a house style the generator may pick (netctl#1444).
    m = _load("""
groups:
  monitor:
    logs:
      impl: "delivery.test_impls:pruner"
      help: "Show logs."
      params:
        dry_run: { help: "follow the log", short: "-f", short_first: true }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert 'dry_run: bool = typer.Option(False, "-f", "--dry-run", help=\'follow the log\')' in text


def test_a_param_without_short_first_keeps_the_long_decl_in_front():
    # arrange: the default, and the shape every other declared parameter in netctl's surface has
    m = _load("""
groups:
  monitor:
    logs:
      impl: "delivery.test_impls:pruner"
      help: "Show logs."
      params:
        dry_run: { help: "follow the log", short: "-f" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert 'dry_run: bool = typer.Option(False, "--dry-run", "-f", help=\'follow the log\')' in text


def test_a_param_declaring_only_help_still_names_its_long_decl():
    # arrange: naming the long decl is what SUPPRESSES the `--no-x` secondary Typer derives for a bare
    # bool, and not one parameter in netctl's whole surface carries one. A bool that wanted the secondary
    # stays out of `params:` entirely - which is consistent, since `params:` is where a command departs
    # from the derivation.
    m = _load("""
groups:
  git:
    prune-branches:
      impl: "delivery.test_impls:pruner"
      help: "Delete merged branches."
      params:
        dry_run: { help: "preview only" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert 'dry_run: bool = typer.Option(False, "--dry-run", help=\'preview only\')' in text


def test_an_undeclared_param_is_left_to_typers_own_derivation():
    # arrange: emitting an explicit decl for EVERY parameter would suppress the `--no-remote` secondary
    # Typer derives for a bare bool, which is a working flag disappearing from the surface.
    m = _load("""
groups:
  git:
    prune-branches:
      impl: "delivery.test_impls:pruner"
      help: "Delete merged branches."
      params:
        dry_run: { help: "preview only" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "remote: bool = False" in text
    assert '"--remote"' not in text


def test_a_param_declaring_a_metavar_carries_it_into_the_rendered_argument():
    # arrange: the metavar names the placeholder Click prints in the usage line, so
    # `[up|down|status|repos|cleanup]` is the difference between an argument that lists its members and a
    # bare `[MEMBER]`. netctl's CLI-surface golden does not capture it, so nothing else would notice a
    # body losing it on the way into generated source (netctl#1444).
    m = _load("""
groups:
  support:
    nexus:
      impl: "delivery.test_impls:member_dispatch"
      help: "Drive the proxy."
      params:
        member: { help: "the group member to run; omit to list them", argument: true,
                  metavar: "[up|down|status|repos|cleanup]" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert: an optional POSITIONAL - `typer.Option` would have made it `--member`, a different command
    # line - carrying both the metavar and the help.
    assert ("member: str | None = typer.Argument(None, "
            "metavar='[up|down|status|repos|cleanup]', "
            "help='the group member to run; omit to list them')") in text


def test_a_param_declaring_only_a_metavar_is_declared_enough_to_leave_typers_derivation():
    # arrange: a metavar alone must count as a declaration. Treating it as "nothing declared" would render
    # `member: str | None = None` and drop the metavar without a word - the exact silent loss this key
    # exists to prevent.
    m = _load("""
groups:
  support:
    nexus:
      impl: "delivery.test_impls:member_dispatch"
      help: "Drive the proxy."
      params:
        member: { argument: true, metavar: "[up|down]" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "member: str | None = typer.Argument(None, metavar='[up|down]')" in text


def test_a_declared_required_parameter_renders_a_typer_argument():
    # arrange: a required parameter has no default to carry, and `typer.Option(...)` with an Ellipsis
    # default would render it as a required OPTION - a different command line.
    m = _load("""
groups:
  lab:
    pin:
      impl: "delivery.test_impls:needs_site"
      help: "Pin a site."
      params:
        site: { help: "site name (e.g. be)" }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")

    # assert
    assert "site=typer.Argument(..., help='site name (e.g. be)')" in text


def test_every_parameter_is_annotated_from_the_body(tmp_path):
    # arrange: this is the one that bites. Typer infers a parameter's TYPE from its annotation, and an
    # unannotated `dry_run=False` becomes a text option - `--dry-run TEXT` instead of a boolean flag -
    # while every string assertion about decls and help still passes.
    m = _load("""
groups:
  git:
    prune-branches: { impl: "delivery.test_impls:pruner", help: "Delete merged branches." }
    other:          { impl: "delivery.test_impls:nullary", help: "Other." }
""")

    # act
    root = _assembled(m, tmp_path)
    group = root.get_command(click.Context(root), "git")
    leaf = group.get_command(click.Context(group), "prune-branches")

    # assert
    assert [(p.name, p.type.name, p.is_flag) for p in leaf.params] == [
        ("dry_run", "boolean", True), ("remote", "boolean", True)]


# --- the registration shapes delivery.cli.assemble performs (netctl#1437) -----------------------------

_SHAPES = """
groups:
  build:
    build: { depends_on: [diff], help: "Build it." }
    diff:  { impl: "delivery.test_impls:nullary", help: "Diff it." }
  test:
    all:      { impl: "delivery.test_impls:nullary", help: "Every gate." }
    unit:     { impl: "delivery.test_impls:nullary", help: "One gate." }
    internal: { impl: "delivery.test_impls:nullary", help: "A plan step.", hidden: true }
  deploy:
    all:    { impl: "delivery.test_impls:nullary", help: "Every step." }
    gradle: { impl: "delivery.test_impls:gradle", help: "Run gradle.", passthrough_args: true }
  package:
    package: { impl: "delivery.test_impls:nullary", help: "Package it." }
env_groups: [deploy]
"""


def test_a_grouped_command_also_registers_a_hidden_flat_alias(tmp_path):
    # arrange / act
    root = _assembled(_load(_SHAPES), tmp_path)

    # assert: reachable as `test unit` AND as the bare `unit`, the second one hidden - the #147
    # back-compat pattern, so `./netctl.sh unit-java` keeps working
    assert _sub(_sub(root, "test"), "unit") is not None
    assert _sub(root, "unit").hidden is True


def test_an_ambiguous_leaf_gets_no_flat_alias(tmp_path):
    # arrange: `all` is owned by both test and deploy - a bare `all` must fail as unknown rather than
    # silently pick one owner
    root = _assembled(_load(_SHAPES), tmp_path)

    # act / assert
    assert _sub(_sub(root, "test"), "all") is not None
    assert _sub(_sub(root, "deploy"), "all") is not None
    assert _sub(root, "all") is None


def test_two_groups_owning_one_name_get_two_distinct_functions(tmp_path):
    # arrange: two `def all(...)` in one module would silently shadow each other and `test all` would
    # run the deploy plan. The COMMAND names stay `all`; only the identifiers differ.
    text = taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample")

    # act / assert
    assert "def test_all() -> None:" in text
    assert "def deploy_all() -> None:" in text
    assert "_g_test.command(name='all'" in text and "(test_all)" in text
    assert "_g_deploy.command(name='all'" in text and "(deploy_all)" in text


def test_a_collapsed_single_member_flat_group_is_one_visible_top_level_command(tmp_path):
    # arrange: `package` is its own only member, so a sub-app would collide with the command; a bare
    # `<product> package` must RUN it rather than print group help
    root = _assembled(_load(_SHAPES), tmp_path)

    # act
    cmd = _sub(root, "package")

    # assert
    assert not isinstance(cmd, click.Group)
    assert cmd.hidden is False


def test_a_group_default_namesake_runs_on_the_bare_group_token(tmp_path):
    # arrange: `<product> build` runs the pipeline, `<product> build diff` dispatches the sibling, and
    # `<product> build --help` still lists them
    root = _assembled(_load(_SHAPES), tmp_path)

    # act
    group = _sub(root, "build")

    # assert: a group whose callback fires with no subcommand, and the namesake is NOT a subcommand
    assert isinstance(group, click.Group)
    assert group.invoke_without_command is True
    assert _sub(group, "build") is None
    assert _sub(group, "diff") is not None


def test_a_hidden_command_stays_invocable_but_leaves_its_group_listing(tmp_path):
    # arrange: a plan step named by a depends_on entry must be a real command yet need not clutter a
    # --help meant for a human
    root = _assembled(_load(_SHAPES), tmp_path)

    # act
    inside = _sub(_sub(root, "test"), "internal")

    # assert
    assert inside is not None and inside.hidden is True


def test_a_passthrough_command_carries_the_context_settings_and_its_neighbour_does_not(tmp_path):
    # arrange
    root = _assembled(_load(_SHAPES), tmp_path)

    # act
    loose = _sub(_sub(root, "deploy"), "gradle")
    tight = _sub(_sub(root, "test"), "unit")

    # assert
    assert loose.context_settings == {"allow_extra_args": True, "ignore_unknown_options": True}
    assert tight.context_settings == {}


def test_an_env_first_group_is_listed_under_the_cd_panel_named_after_the_product(tmp_path):
    # arrange / act: the panel is user-visible and pinned by netctl's golden; the product token in it is
    # why `render` takes a product name rather than hardcoding one
    root = _assembled(_load(_SHAPES), tmp_path, product="sample")

    # assert
    assert _sub(root, "deploy").rich_help_panel == \
        "CD / env-first (sample <env> <group> <cmd>, default dev)"
    assert _sub(root, "test").rich_help_panel == "CI / agnostic (no env)"


def test_a_manifest_with_an_aggregate_and_no_dispatcher_fails_at_register(tmp_path):
    # arrange: the reflective assembly failed at ASSEMBLY time for this, not at first invocation
    path = tmp_path / "_gen.py"
    path.write_text(taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample"))
    spec = importlib.util.spec_from_file_location("_gen_noagg", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # act / assert
    with pytest.raises(ValueError, match="aggregate"):
        module.register(typer.Typer(add_completion=False))


def test_a_nested_group_registers_beneath_its_parent(tmp_path):
    # arrange: `support git commit` is the first intended use of nesting (Plan 5); the capability ships
    # here and is exercised there, so shipping and exercising stay separable in the golden diff.
    m = _load("""
taxonomy:
  support:
    help: "Host and tooling upkeep."
    groups:
      git: { help: "Version control verbs." }
groups:
  support.git:
    commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
env_groups: []
""")

    # act
    root = _assembled(m, tmp_path)

    # assert: reachable at depth 2, and the flat alias survives at that depth
    assert _sub(_sub(_sub(root, "support"), "git"), "commit") is not None
    assert _sub(root, "commit").hidden is True


# --- where a command's help summary comes from (netctl#1437) ------------------------------------------

def test_the_help_summary_comes_from_the_body_docstring(tmp_path):
    # arrange: the reflective assembly bound the BODY as the callback, so Typer read the docstring off
    # it. Preferring the manifest everywhere would read as the more principled rule and would silently
    # reword four netctl commands whose help: and docstring have drifted apart.
    m = _load("""
groups:
  lab:
    seed:  { impl: "delivery.test_impls:seed", help: "A DIFFERENT summary." }
    other: { impl: "delivery.test_impls:nullary", help: "Other." }
""")

    # act
    group = _sub(_assembled(m, tmp_path), "lab")

    # assert
    assert _sub(group, "seed").get_short_help_str(limit=250) == "Seed the lab and run the smoke test."


def test_an_impl_shared_by_several_commands_takes_each_summary_from_the_manifest(tmp_path):
    # arrange: one body has ONE docstring, so all of them would render the same blurb (netctl#1406,
    # where one kernel suite-runner backs every declared test level)
    m = _load("""
groups:
  test:
    system:     { impl: "delivery.test_impls:nullary", help: "The SYSTEM gate." }
    acceptance: { impl: "delivery.test_impls:nullary", help: "The ACCEPTANCE gate." }
""")

    # act
    group = _sub(_assembled(m, tmp_path), "test")

    # assert
    assert _sub(group, "system").get_short_help_str(limit=250) == "The SYSTEM gate."
    assert _sub(group, "acceptance").get_short_help_str(limit=250) == "The ACCEPTANCE gate."


def test_an_aggregate_takes_its_summary_from_the_manifest_because_it_has_no_body(tmp_path):
    # arrange
    m = _load("""
groups:
  build:
    build: { depends_on: [diff], help: "Build the images." }
    diff:  { impl: "delivery.test_impls:nullary", help: "Diff it." }
""")

    # act
    root = _assembled(m, tmp_path)

    # assert
    assert _sub(root, "build").get_short_help_str(limit=250) == "Build the images."


# --- collisions the generator must refuse rather than resolve (netctl#1440) ---------------------------

def test_a_qualified_name_colliding_with_a_literal_command_name_is_rejected():
    # arrange: `test all` and `deploy all` are ambiguous, so both are qualified - and `test_all` is then
    # the identifier of a command literally NAMED test_all in a third group, which is unambiguous by its
    # bare name and therefore NOT qualified. Two `def test_all` in one module: Python binds the second
    # over the first and `test all` dispatches the wrong body.
    m = _load("""
groups:
  test:
    all: { impl: "delivery.test_impls:nullary", help: "Every test." }
  deploy:
    all: { impl: "delivery.test_impls:no_context", help: "Every deploy step." }
  misc:
    test_all: { impl: "delivery.test_impls:seed", help: "Something else entirely." }
env_groups: [deploy]
""")

    # act / assert: named, both culprits, rather than silently shadowed
    with pytest.raises(ValueError) as exc:
        taskgen.render(m, source="demo.yaml", product="sample")
    assert "test all" in str(exc.value) and "misc test_all" in str(exc.value)


def test_two_dashed_names_rendering_one_identifier_are_rejected():
    # arrange: `disk-guard` and `disk_guard` are different COMMANDS and one Python name
    m = _load("""
groups:
  support:
    disk-guard: { impl: "delivery.test_impls:nullary", help: "Guard the disk." }
    disk_guard: { impl: "delivery.test_impls:no_context", help: "Guard it differently." }
""")

    # act / assert
    with pytest.raises(ValueError, match="shadow"):
        taskgen.render(m, source="demo.yaml", product="sample")


def test_registering_a_second_dispatcher_onto_one_module_is_rejected(tmp_path):
    # arrange: the dispatcher is MODULE state, so a second register() would rebind it under the commands
    # the first call already registered - they would start dispatching through the new one
    path = tmp_path / "_gen.py"
    path.write_text(taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample"))
    spec = importlib.util.spec_from_file_location("_gen_twice", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.register(typer.Typer(add_completion=False), aggregate=lambda name, group: 0)

    # act / assert
    with pytest.raises(ValueError, match="different aggregate dispatcher"):
        module.register(typer.Typer(add_completion=False), aggregate=lambda name, group: 1)


def test_registering_the_same_dispatcher_twice_is_allowed(tmp_path):
    # arrange: idempotence is not the failure - rebinding to something ELSE is
    path = tmp_path / "_gen.py"
    path.write_text(taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample"))
    spec = importlib.util.spec_from_file_location("_gen_same", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dispatcher = lambda name, group: 0

    # act / assert: no raise
    module.register(typer.Typer(add_completion=False), aggregate=dispatcher)
    module.register(typer.Typer(add_completion=False), aggregate=dispatcher)


def test_an_aggregate_invoked_before_register_says_so(tmp_path):
    # arrange: `_aggregate(...)` on None was a TypeError about NoneType, which names neither the command
    # nor the missing call
    path = tmp_path / "_gen.py"
    path.write_text(taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample"))
    spec = importlib.util.spec_from_file_location("_gen_unbound", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # act / assert
    with pytest.raises(RuntimeError, match="no dispatcher is bound"):
        module.build()


# --- `with:` pins (netctl#1442) -----------------------------------------------------------------------

def test_a_with_override_on_a_required_parameter_does_not_give_it_a_default(tmp_path):
    # arrange: the defect. Substituting the value as a DEFAULT turned a mandatory argument into an
    # optional one and moved the failure out of the CLI parser into whatever the body does with a value
    # nobody passed - the exact failure the required-parameter branch exists to prevent, reached through
    # the branch above it.
    m = _load("""
groups:
  lab:
    pin:   { impl: "delivery.test_impls:needs_site", help: "Pin a site.", with: { site: be } }
    other: { impl: "delivery.test_impls:nullary", help: "Other." }
""")

    # act
    text = taskgen.render(m, source="demo.yaml", product="sample")
    root = _assembled(m, tmp_path)

    # assert: no default, because no parameter - and the body still receives the value
    assert "def pin(ctx: typer.Context) -> None:" in text
    assert "needs_site(ctx, site='be')" in text
    leaf = _sub(_sub(root, "lab"), "pin")
    assert [p.name for p in leaf.params] == []


def test_a_pinned_parameter_cannot_be_set_from_the_command_line(tmp_path):
    # arrange: this is what "pins" has to mean to be worth the name - the suite runner's gate name is the
    # motivating case, and a user redirecting it would run one suite under another's identity
    m = _load("""
groups:
  lab:
    pin:   { impl: "delivery.test_impls:needs_site", help: "Pin a site.", with: { site: be } }
    other: { impl: "delivery.test_impls:nullary", help: "Other." }
""")
    root = _assembled(m, tmp_path)

    # act
    result = CliRunner().invoke(root, ["lab", "pin", "--site", "zh"])

    # assert
    assert result.exit_code != 0


def test_an_optional_parameter_is_pinned_by_with_too_rather_than_merely_redefaulted(tmp_path):
    # arrange: one rule for one key. "sets the default" for an optional parameter and "pins" for a
    # required one is a distinction a reader has to open the body to predict.
    m = _load("""
groups:
  lab:
    seed:  { impl: "delivery.test_impls:seed", help: "Seed.", with: { sites: zh } }
    other: { impl: "delivery.test_impls:nullary", help: "Other." }
""")

    # act
    leaf = _sub(_sub(_assembled(m, tmp_path), "lab"), "seed")

    # assert: `dry_run` stays settable, `sites` is gone
    assert [p.name for p in leaf.params] == ["dry_run"]


def test_describing_a_pinned_parameter_in_params_is_rejected():
    # arrange: a pinned parameter has no command line to appear on, so help text for it would be written
    # and never shown
    m = _load("""
groups:
  lab:
    pin:
      impl: "delivery.test_impls:needs_site"
      help: "Pin a site."
      with: { site: be }
      params:
        site: { help: "which site" }
""")

    # act / assert
    with pytest.raises(ValueError, match="pinned"):
        taskgen.render(m, source="demo.yaml", product="sample")


# --- a partial render, and the hybrid it enables (netctl#1444) ----------------------------------------

def test_rendering_a_subset_of_groups_covers_only_those(tmp_path):
    # arrange: how a product migrates off the reflective assembly without one all-or-nothing PR
    m = _load(_SHAPES)

    # act
    root = _assembled(m, tmp_path, groups=frozenset({"test"}))

    # assert: the chosen group and its flat aliases, nothing else
    assert _sub(root, "test") is not None
    assert _sub(root, "deploy") is None
    assert _sub(root, "unit").hidden is True


def test_the_generated_module_names_what_it_covers(tmp_path):
    # arrange: the product hands COVERED to the reflective assembly rather than restating the list
    m = _load(_SHAPES)

    # act
    module = _module(m, tmp_path, groups=frozenset({"test"}))

    # assert
    assert module.COVERED == frozenset({("test", "all"), ("test", "unit"), ("test", "internal")})


def test_covering_everything_is_the_default():
    # arrange / act
    full = taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample")

    # assert
    assert '("deploy", "gradle")' in full and '("test", "unit")' in full


def test_generating_a_group_the_manifest_does_not_declare_is_rejected():
    # arrange: a typo in the migration list would otherwise generate nothing and read as "not migrated yet"
    # act / assert
    with pytest.raises(ValueError, match="tset"):
        taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample",
                       groups=frozenset({"tset"}))


def test_a_nested_group_pulls_its_ancestor_into_the_render(tmp_path):
    # arrange: `support.git` cannot be registered without a `support` sub-app to hang from, and asking a
    # product to list both would be bookkeeping the generator can do
    m = _load("""
taxonomy:
  support:
    help: "Host and tooling upkeep."
    groups:
      git: { help: "Version control verbs." }
groups:
  support.git:
    commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
  test:
    unit: { impl: "delivery.test_impls:nullary", help: "One gate." }
env_groups: []
""")

    # act
    root = _assembled(m, tmp_path, groups=frozenset({"support.git"}))

    # assert
    assert _sub(_sub(_sub(root, "support"), "git"), "commit") is not None
    assert _sub(root, "test") is None


# --- unrenderable(): which bodies still hold the migration back ---------------------------------------

def test_unrenderable_names_the_commands_whose_bodies_cannot_be_written():
    # arrange: a body carrying a typer.Option default, as the unmigrated kernel bodies do
    import typer as _typer

    def legacy(dry_run: bool = _typer.Option(False, "--dry-run")):
        """A body that still has Typer in it."""

    import delivery.test_impls as impls
    impls.legacy = legacy
    try:
        m = _load("""
groups:
  git:
    legacy: { impl: "delivery.test_impls:legacy", help: "Legacy." }
    push:   { impl: "delivery.test_impls:nullary", help: "Push." }
""")

        # act
        blocked = taskgen.unrenderable(m)

        # assert: named, with the reason, and the clean neighbour absent
        assert set(blocked) == {("git", "legacy")}
        assert "OptionInfo" in blocked[("git", "legacy")]
    finally:
        del impls.legacy


def test_unrenderable_is_empty_for_a_fully_migrated_manifest():
    # arrange / act / assert
    assert taskgen.unrenderable(_load(_SHAPES)) == {}


# --- import order (netctl#1446) -----------------------------------------------------------------------

def test_the_impl_imports_come_after_register_so_either_import_order_works():
    # arrange: the product's CLI module imports THIS one and calls register() from its own body, while
    # this one imports the product's CLI module back for its impls. Whichever is imported first, the
    # other's body runs to completion inside it - so `register` must be DEFINED by then, or importing
    # this module first raises AttributeError on `register`.
    text = taskgen.render(_load(_SHAPES), source="demo.yaml", product="sample")

    # act
    lines = text.splitlines()
    register_at = next(i for i, line in enumerate(lines) if line.startswith("def register("))
    imports_at = [i for i, line in enumerate(lines)
                  if line.startswith("import delivery.test_impls")]

    # assert
    assert imports_at, "the impl import is missing entirely"
    assert min(imports_at) > register_at


def test_rendering_no_groups_at_all_still_runs_the_manifest_wide_clash_check():
    # arrange: `unrenderable()` reports per COMMAND, so a manifest-wide identifier clash is invisible to
    # it. This is how a product asserts none is hiding behind an empty report - render nothing, and the
    # check that belongs to no single command still runs.
    m = _load("""
groups:
  test:
    all: { impl: "delivery.test_impls:nullary", help: "Every test." }
  deploy:
    all: { impl: "delivery.test_impls:no_context", help: "Every deploy step." }
  misc:
    test_all: { impl: "delivery.test_impls:seed", help: "Something else." }
env_groups: [deploy]
""")

    # act / assert: nothing is rendered and the clash is still found
    assert taskgen.unrenderable(m) == {}
    with pytest.raises(ValueError, match="shadow"):
        taskgen.render(m, source="demo.yaml", product="sample", groups=frozenset())
