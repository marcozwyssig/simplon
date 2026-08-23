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


def _assembled(m, tmp_path, source="demo.yaml"):
    """Render, import and register the module onto a fresh root app; return the Click tree."""
    path = tmp_path / "_generated_cli.py"
    path.write_text(taskgen.render(m, source=source))
    spec = importlib.util.spec_from_file_location("_generated_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = typer.Typer(add_completion=False)
    module.register(app)
    return get_command(app)


# --- render: the manifest is the model, the signature comes from the body ---------------------------

def test_the_rendered_module_declares_a_command_per_manifest_entry():
    # arrange / act
    text = taskgen.render(_load(), source="demo.yaml")

    # assert: a plain function plus its registration under the manifest's name, carrying its help
    assert "def seed(" in text
    assert "lab.command(name='seed')(seed)" in text
    assert "Seed the lab." in text


def test_the_generated_module_registers_onto_a_caller_supplied_app():
    # arrange: the product owns its ROOT app - its help blurb is its voice, and its own internal
    # commands live on it. The generated module only ADDS, which is what keeps netctl's
    # `wireguard-guard` and its `Internal` panel untouched by a regeneration.
    text = taskgen.render(_load(), source="demo.yaml")

    # assert
    assert "def register(app: typer.Typer) -> None:" in text
    assert "from invoke" not in text
    assert "@task" not in text


def test_the_signature_comes_from_the_body_not_from_the_manifest():
    # arrange: the manifest names neither `sites` nor `dry_run`
    text = taskgen.render(_load(), source="demo.yaml")

    # assert: introspected, with the `with:` override applied to `sites` only
    assert "sites='zh'" in text
    assert "dry_run=False" in text


def test_the_wrapper_delegates_to_the_impl_by_keyword_and_raises_the_rc():
    # arrange / act
    text = taskgen.render(_load(), source="demo.yaml")

    # assert: the body returns an int; the WRAPPER is what knows about process exit codes
    assert ("raise typer.Exit(_rc(delivery.test_impls.seed(ctx, sites=sites, dry_run=dry_run)))"
            in text)


def test_rendering_twice_is_byte_identical():
    # arrange: the drift gate compares TEXT, so a non-deterministic render makes it useless
    m = _load()

    # act / assert
    assert taskgen.render(m, source="demo.yaml") == taskgen.render(m, source="demo.yaml")


def test_the_rendered_module_imports_and_assembles_a_real_click_tree(tmp_path):
    # arrange / act: the point of committing generated code is that it IS code - so prove it runs
    root = _assembled(_load(), tmp_path)

    # assert: reachable as `lab seed`, with the introspected parameters on it
    group = root.get_command(click.Context(root), "lab")
    leaf = group.get_command(click.Context(group), "seed")
    assert [p.name for p in leaf.params] == ["sites", "dry_run"]


def test_a_command_name_with_a_dash_becomes_a_legal_identifier(tmp_path):
    # arrange: `disk-guard` is not a Python name, but the TASK must keep the dashed name
    m = _load("""
groups:
  support:
    disk-guard: { impl: "delivery.test_impls:seed", help: "Guard the disk." }
""")

    # act
    text = taskgen.render(m, source="demo.yaml")

    # assert
    assert "def disk_guard(" in text
    assert "command(name='disk-guard')(disk_guard)" in text


def test_a_variadic_body_renders_a_command_with_no_declared_parameters():
    # arrange: neither Click nor Typer binds *args to a parameter. Such a command is `passthrough_args`
    # and its raw tail reaches the body through `ctx.args`, which the per-command context settings allow.
    m = _load("""
groups:
  build:
    gradle: { impl: "delivery.test_impls:gradle", help: "Run gradle.", passthrough_args: true }
""")

    # act
    text = taskgen.render(m, source="demo.yaml")

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
        taskgen.render(m, source="demo.yaml")


def test_an_impl_less_aggregate_command_is_not_rendered_as_a_task():
    # arrange: a depends_on aggregate is a PLAN, and a plan step runs as a subprocess - it has no body
    # to wrap, so rendering one would invent a task that cannot work
    m = _load("""
groups:
  build:
    build: { depends_on: [seed], help: "Build it." }
    seed:  { impl: "delivery.test_impls:seed", help: "Seed the lab." }
""")

    # act
    text = taskgen.render(m, source="demo.yaml")

    # assert
    assert "def seed(" in text
    assert "def build(" not in text


# --- the drift gate ----------------------------------------------------------------------------------

def test_check_returns_no_diff_when_the_file_matches_the_manifest(tmp_path):
    # arrange
    m = _load()
    target = tmp_path / "_generated.py"
    taskgen.write(m, target, source="demo.yaml")

    # act / assert
    assert taskgen.check(m, target, source="demo.yaml") is None


def test_check_returns_a_diff_when_the_manifest_moved_on(tmp_path):
    # arrange: the file was generated from an OLDER manifest
    target = tmp_path / "_generated.py"
    taskgen.write(_load(), target, source="demo.yaml")
    moved = _load(_MANIFEST.replace("Seed the lab.", "Seed it and smoke-test it."))

    # act
    diff = taskgen.check(moved, target, source="demo.yaml")

    # assert: readable enough to act on without regenerating first
    assert diff is not None
    assert "Seed it and smoke-test it." in diff


def test_check_reports_a_missing_target_as_a_diff_rather_than_crashing(tmp_path):
    # arrange: a fresh checkout that never generated - the gate must SAY so, not raise
    # act
    diff = taskgen.check(_load(), tmp_path / "absent.py", source="demo.yaml")

    # assert
    assert diff is not None


def test_write_is_idempotent_and_reports_whether_it_changed_anything(tmp_path):
    # arrange
    m = _load()
    target = tmp_path / "_generated.py"

    # act
    first = taskgen.write(m, target, source="demo.yaml")
    second = taskgen.write(m, target, source="demo.yaml")

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
    path.write_text(taskgen.render(m, source="demo.yaml"))
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
        taskgen.render(m, source="demo.yaml")


def test_a_command_named_after_a_python_keyword_is_rejected():
    # arrange: `def import(c):` does not parse
    m = _load('''
groups:
  lab:
    import: { impl: "delivery.test_impls:seed", help: "Import it." }
''')

    # act / assert
    with pytest.raises(ValueError, match="identifier"):
        taskgen.render(m, source="demo.yaml")


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
        taskgen.render(m, source="demo.yaml")


def test_a_required_parameter_stays_required(tmp_path):
    # arrange: rendering it as =None turned a mandatory argument optional and moved the failure out of
    # the CLI parser into whatever the body does with None
    m = _load('''
groups:
  lab:
    pin: { impl: "delivery.test_impls:needs_site", help: "Pin a site." }
''')

    # act
    text = taskgen.render(m, source="demo.yaml")

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
    text = taskgen.render(m, source="demo.yaml")

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
    text = taskgen.render(m, source="demo.yaml")

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
