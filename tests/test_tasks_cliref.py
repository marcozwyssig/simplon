"""Unit tests for simplon.tasks.cliref (#2): the command reference generated from the BUILT Typer app.

The apps here are assembled the way a product's own composition root assembles one - `simplon.cli.assemble`
over a loaded manifest, then `typer.main.get_command` - so what the generator walks is a real Click tree
with real sub-apps, real hidden flat aliases and real parameter objects, not a stand-in for one. That is
the whole point of the module under test: a reference read off the CATALOGUE would describe the intent, and
these tests are what pin it to the result.

The two measured acceptances of the plan live here:
  - `test_the_reference_documents_exactly_the_commands_the_app_offers` counts the app's commands with a
    walk written INDEPENDENTLY of the generator's, and compares it to the entries in the rendered page;
  - `test_a_command_newly_placed_in_the_catalogue_appears_with_no_hand_editing` places a command in the
    CATALOGUE alone, regenerates, and asserts it is documented - nothing else edited.

AAA throughout.
"""
import enum
import sys
import types

import click
import pytest
import typer
import yaml
from click.testing import CliRunner
from typer.main import get_command

from simplon import catalogue as catalogue_mod
from simplon import cli, context
from simplon.context import ProductContext
from simplon.orchestrator import manifest
from simplon.tasks import cliref


# --- fixtures: a catalogue and a product manifest that exercise every shape the walker must handle ------

_CATALOGUE = """
groups:
  build:   { help: "Produce the artefacts." }
  deploy:  { help: "Put them into an environment.", env_first: true }
  support:
    help: "Host preflight and tooling."
    groups:
      git:
        help: "Version-control helpers."
        commands:
          commit:
            task: "vcs:commit"
            params:
              message: { help: "commit message", argument: true }
          prune-branches:
            task: "vcs:prune-branches"
            params:
              dry_run: { help: "preview only", short: "-n" }
tasks:
  vcs:commit:
    impl: "cliref_impls:commit"
    help: "git add -A + git commit -m."
  vcs:prune-branches:
    impl: "cliref_impls:prune_branches"
    help: "Delete merged local branches."
  vcs:push:
    impl: "cliref_impls:push"
    help: "git pull --rebase then push."
  docs:site:
    impl: "cliref_impls:site"
    help: "Build the product website."
"""

_MANIFEST = """
product: sample
default: dev
groups:
  build:
    commands:
      wheel: { task: "wheel" }
  deploy:
    commands:
      up: { task: "up" }
tasks:
  wheel:
    impl: "cliref_impls:wheel"
    help: "Build the wheel."
  up:
    impl: "cliref_impls:up"
    help: "Bring the environment up."
"""


def _impls():
    """The bodies the manifests' coordinates resolve to. Their SIGNATURES are the payload: the parameter
    table under each command is read off the Click objects Typer derives from exactly these."""
    mod = types.ModuleType("cliref_impls")

    def commit(message: list[str] | None = None) -> int:
        """Commit everything.

        A second paragraph, so the summary line and the full help can be told apart.
        """
        return 0

    def prune_branches(dry_run: bool = False, remote: bool = False) -> int:
        """Delete merged local branches."""
        return 0

    def push() -> int:
        """Push."""
        return 0

    def site() -> int:
        """Build the website."""
        return 0

    def wheel(target: str, clean: bool = False) -> int:
        """Build the wheel."""
        return 0

    def up() -> int:
        """Bring it up."""
        return 0

    for fn in (commit, prune_branches, push, site, wheel, up):
        setattr(mod, fn.__name__, fn)
    return mod


@pytest.fixture
def impls():
    sys.modules["cliref_impls"] = _impls()
    try:
        yield
    finally:
        del sys.modules["cliref_impls"]


def _built(manifest_text=_MANIFEST, catalogue_text=_CATALOGUE, product="sample"):
    """A product's manifest, loaded against a catalogue and ASSEMBLED - the root Click command plus the
    manifest, which is what the task itself holds at the moment it renders."""
    mf = manifest.load(manifest_text, catalogue=catalogue_mod.loads(catalogue_text))
    app = typer.Typer(add_completion=False, no_args_is_help=True, help=f"{product} root")
    cli.assemble(app, mf, product=product)
    return get_command(app), mf


def _entries(root, mf):
    return cliref.entries(root, env_first=mf.taxonomy().group_requires_env)


def _page(root, mf, product="sample", unplaced=()):
    return cliref.render(_entries(root, mf), product=product, title=f"{product} commands",
                         unplaced_tasks=unplaced)


def _visible_commands(root):
    """Every command the app offers a human, walked INDEPENDENTLY of the generator.

    Deliberately a second implementation of the same rule rather than a call into the module under test:
    an acceptance that both sides compute the same way measures nothing. Hidden is skipped (the flat
    back-compat aliases and any `hidden: true` command), a group that runs without a subcommand counts as
    a command of its own, and a leaf counts once.
    """
    found = []

    def walk(cmd, path):
        for name, sub in cmd.commands.items():
            if sub.hidden:
                continue
            here = (*path, name)
            if isinstance(sub, click.Group):
                if sub.invoke_without_command:
                    found.append(here)
                walk(sub, here)
            else:
                found.append(here)

    walk(root, ())
    return found


# --- the walk over the Click tree -----------------------------------------------------------------------


def test_the_walk_reaches_every_group_and_leaf_of_the_assembled_tree(impls):
    # arrange
    root, mf = _built()

    # act
    paths = [entry.path for entry in _entries(root, mf)]

    # assert: the product's two commands plus the two the catalogue placed under support.git
    assert paths == [("build", "wheel"), ("deploy", "up"),
                     ("support", "git", "commit"), ("support", "git", "prune-branches")]


def test_a_hidden_flat_alias_is_documented_as_a_second_spelling_and_not_as_a_second_command(impls):
    # arrange: assemble registers every grouped command a second time as a hidden top-level alias
    root, mf = _built()

    # act
    commit = next(e for e in _entries(root, mf) if e.path[-1] == "commit")

    # assert
    assert commit.alias == "commit"
    assert [e.path for e in _entries(root, mf)].count(("support", "git", "commit")) == 1


def test_a_command_the_manifest_hides_stays_out_of_the_reference(impls):
    # arrange: `hidden: true` is a declaration that the command is not part of the surface
    text = _MANIFEST.replace('up: { task: "up" }', 'up: { task: "up", hidden: true }')

    # act
    root, mf = _built(manifest_text=text)

    # assert
    assert [e.path for e in _entries(root, mf)] == [("build", "wheel"),
                                                    ("support", "git", "commit"),
                                                    ("support", "git", "prune-branches")]


def test_a_group_that_runs_without_a_subcommand_is_documented_as_a_command_too(impls):
    # arrange: a multi-member group whose name is one of its members runs that member on the bare token
    text = """
product: sample
groups:
  build:
    build: { impl: "cliref_impls:wheel", help: "Run the build pipeline." }
    docs:  { impl: "cliref_impls:site",  help: "Render the docs." }
"""
    root, mf = _built(manifest_text=text, catalogue_text="tasks: {}\n")

    # act
    paths = [entry.path for entry in _entries(root, mf)]

    # assert: the bare `sample build` is a command a user can type, so it is an entry
    assert ("build",) in paths
    assert ("build", "docs") in paths


def test_the_env_first_distinction_comes_from_the_taxonomy_and_not_from_a_help_panel(impls):
    # arrange
    root, mf = _built()

    # act
    by_path = {entry.path: entry for entry in _entries(root, mf)}

    # assert
    assert by_path[("deploy", "up")].env_first is True
    assert by_path[("build", "wheel")].env_first is False
    assert by_path[("support", "git", "commit")].env_first is False


# --- the shapes that have no group token -----------------------------------------------------------------

_FLAT = """
product: sample
groups:
  package:
    package: { impl: "cliref_impls:wheel", help: "Package the artefacts." }
  build:
    wheel: { impl: "cliref_impls:up", help: "Build the wheel." }
env_groups: [package]
"""


def test_a_single_member_group_that_collapses_is_never_described_as_a_group(impls):
    # arrange: `is_flat_command_group` - a first-class, documented manifest shape. `sample package` IS the
    # command; there is no `sample package <command>` to type, and claiming one is a lie on the page.
    root, mf = _built(manifest_text=_FLAT, catalogue_text="tasks: {}\n")
    assert mf.taxonomy().is_flat_command_group("package")

    # act
    found = _entries(root, mf)
    page = cliref.render(found, product="sample", title="t")
    package = next(e for e in found if e.path == ("package",))

    # assert
    assert package.top_level is True
    assert "sample package <command>" not in page
    assert "sample <env> package <command>" not in page
    assert cliref.TOP_LEVEL_HEADING in page
    # it is still env-first, and the usage line is where that has to show
    assert "sample <env> package" in page


def test_a_command_the_product_registers_on_the_root_itself_is_documented_as_one(impls):
    # arrange: the seam `simplon.cli.assemble` documents - and the reason the source here is the RUNNING
    # app. It is not a group either, so it must not be described as one.
    mf = manifest.load(_MANIFEST, catalogue=catalogue_mod.loads(_CATALOGUE))
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="sample root")

    @app.command(name="probe")
    def probe():
        """A command no manifest knows about."""

    cli.assemble(app, mf, product="sample")
    root = get_command(app)

    # act
    found = cliref.entries(root, env_first=mf.taxonomy().group_requires_env)
    page = cliref.render(found, product="sample", title="t")

    # assert
    assert ("probe",) in [e.path for e in found]
    assert "sample probe <command>" not in page
    assert "`sample probe`" in page


def test_a_grouped_command_still_gets_the_group_shape_it_really_has(impls):
    # arrange: the fix must not flatten the case that WAS right
    root, mf = _built()

    # act
    page = _page(root, mf)

    # assert
    assert "sample support git <command>" in page
    assert "sample <env> deploy <command>" in page


# --- the parameters, read off the Click objects ----------------------------------------------------------


def test_a_parameter_carries_its_declarations_type_default_and_help(impls):
    # arrange
    root, mf = _built()

    # act
    prune = next(e for e in _entries(root, mf) if e.path[-1] == "prune-branches")
    by_name = {p.name: p for p in prune.params}

    # assert: the declared one keeps its short flag and its help; the undeclared bool keeps Typer's
    # `--no-` secondary, which is part of what a user can type
    assert by_name["dry_run"].decls == ("--dry-run", "-n")
    assert by_name["dry_run"].help == "preview only"
    assert by_name["dry_run"].type_name == "flag"
    assert by_name["dry_run"].default is False
    assert "--no-remote" in by_name["remote"].decls


def test_a_required_argument_is_documented_as_a_positional_with_no_default(impls):
    # arrange
    root, mf = _built()

    # act
    wheel = next(e for e in _entries(root, mf) if e.path[-1] == "wheel")
    target = next(p for p in wheel.params if p.name == "target")

    # assert
    assert target.is_argument is True
    assert target.required is True
    assert target.decls == ()
    assert target.metavar == "TARGET"


def test_a_variadic_argument_is_documented_as_repeatable(impls):
    # arrange
    root, mf = _built()

    # act
    commit = next(e for e in _entries(root, mf) if e.path[-1] == "commit")
    message = next(p for p in commit.params if p.name == "message")

    # assert
    assert message.variadic is True
    assert message.metavar == "MESSAGE..."


def test_a_computed_default_is_named_rather_than_printed(impls):
    # arrange: Click lets a default be a callable evaluated at parse time. Its repr carries a memory
    # address, so printing it would put a different page on disk on every run.
    root, mf = _built()
    param = cliref.Param(name="when", decls=("--when",), metavar="WHEN", type_name="text",
                         required=False, default=lambda: "now", variadic=False, is_argument=False)
    entry = cliref.Entry(path=("build", "wheel"), group="build", summary="s", help="h",
                         env_first=False, params=(param,))

    # act
    page = cliref.render([entry], product="sample", title="t")

    # assert
    assert "computed" in page
    assert "0x" not in page


def test_the_help_option_is_not_a_documented_parameter(impls):
    # arrange: Click adds `--help` to every command; it is the framework's, not the command's
    root, mf = _built()

    # act
    names = {p.name for entry in _entries(root, mf) for p in entry.params}

    # assert
    assert "help" not in names


class _Level(str, enum.Enum):
    info = "info"
    debug = "debug"


def _direct_app():
    """A Typer app built the way a product's own module would build one, for the parameter shapes a
    manifest cannot express: a REQUIRED option and an enum that Click turns into a Choice. Two commands,
    because Typer collapses a one-command app into a bare command rather than a group."""
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="direct")

    @app.command(name="publish")
    def publish(channel: str = typer.Option(..., "--channel", help="where it goes"),
                level: _Level = typer.Option(_Level.info, "--level", help="how loud")):
        """Publish it."""

    @app.command(name="idle")
    def idle():
        """Do nothing."""

    return get_command(app)


def test_a_required_option_is_not_shown_as_optional_in_the_usage_line():
    # arrange: the table says "required"; a usage line bracketing it would contradict the table
    root = _direct_app()

    # act
    entry = next(e for e in cliref.entries(root) if e.path == ("publish",))
    usage = cliref._usage(entry, "direct")

    # assert
    assert "--channel CHANNEL" in usage
    assert "[--channel" not in usage


def test_a_choice_option_shows_the_values_it_accepts():
    # arrange: without this the page would print a placeholder and drop the only thing that matters
    root = _direct_app()

    # act
    entry = next(e for e in cliref.entries(root) if e.path == ("publish",))
    level = next(p for p in entry.params if p.name == "level")

    # assert
    assert level.metavar == "[info|debug]"


def test_the_front_matter_stays_valid_yaml_when_the_title_carries_quotes():
    # arrange: the title comes from a manifest, so it is not the kernel's to trust
    entry = cliref.Entry(path=("x",), group="x", summary="s", help="h", env_first=False, params=())

    # act
    title = 'it\'s a "reference"'
    page = cliref.render([entry], product="p", title=title)

    # assert
    front = yaml.safe_load(page.split("---", 2)[1])
    assert front["title"] == title


# --- the rendered page ------------------------------------------------------------------------------------


def test_the_page_is_markdown_with_hugo_front_matter_and_no_asciidoc(impls):
    # arrange
    root, mf = _built()

    # act
    page = _page(root, mf)

    # assert
    assert page.startswith("---\ntitle: ")
    assert "\n## " in page and "\n### " in page
    for residue in ("\n= ", "\n== ", "[source,", "____", "ifdef::"):
        assert residue not in page


def test_the_usage_line_shows_the_env_token_exactly_for_an_env_first_command(impls):
    # arrange
    root, mf = _built()

    # act
    page = _page(root, mf)

    # assert
    assert "sample <env> deploy up" in page
    assert "sample build wheel TARGET" in page
    assert "sample <env> build wheel" not in page


def test_the_page_names_the_second_spelling_of_a_command_that_has_one(impls):
    # arrange
    root, mf = _built()

    # act
    page = _page(root, mf)

    # assert
    assert "`sample commit`" in page


def test_the_unplaced_section_claims_no_more_than_the_catalogue_supports(impls):
    # arrange: the catalogue itself says `support:nexus` reads a `nexus:` section, `test:gate` needs a
    # running lab, and so on - "placed here, each would be a command that dies on its first line". A page
    # promising that adopting one is a manifest line contradicts the source of truth in the same repo.
    root, mf = _built()

    # act
    page = _page(root, mf, unplaced=cliref.unplaced(mf, catalogue_mod.loads(_CATALOGUE)))
    section = page.split(cliref.UNPLACED_HEADING)[1]

    # assert
    assert "not a port" not in section
    assert "product data of their own" in section
    # and it says what the list IS, since a flat-form manifest must import a namespace before placing
    assert "not what this manifest imports" in section


def test_the_page_lists_the_platform_tasks_this_product_has_not_placed(impls):
    # arrange: `docs:site` is a catalogue task no command instantiates - it appears in no group at all
    root, mf = _built()

    # act
    page = _page(root, mf, unplaced=cliref.unplaced(mf, catalogue_mod.loads(_CATALOGUE)))

    # assert
    assert "docs:site" in page
    assert "vcs:commit" not in page.split(cliref.UNPLACED_HEADING)[1]


def test_the_reference_documents_exactly_the_commands_the_app_offers(impls):
    # arrange: the plan's first acceptance, measured rather than estimated
    root, mf = _built()
    known = _visible_commands(root)

    # act
    page = _page(root, mf)
    documented = [line for line in page.splitlines() if line.startswith("### ")]

    # assert
    assert len(documented) == len(known) == 4
    assert f"documents {len(known)} commands" in page


def test_a_command_newly_placed_in_the_catalogue_appears_with_no_hand_editing(impls):
    # arrange: the plan's second acceptance. NOTHING but the catalogue changes - not the product manifest,
    # and certainly not the page.
    before = _page(*_built())
    grown = _CATALOGUE.replace("          prune-branches:",
                               "          push: { task: \"vcs:push\" }\n          prune-branches:")

    # act
    root, mf = _built(catalogue_text=grown)
    after = cliref.render(_entries(root, mf), product="sample", title="sample commands")

    # assert
    assert "sample support git push" not in before
    assert "sample support git push" in after
    assert after.count("\n### ") == before.count("\n### ") + 1
    assert "documents 5 commands" in after


# --- the task entry point ----------------------------------------------------------------------------------


def test_the_task_refuses_to_run_outside_the_cli_it_is_meant_to_describe():
    # arrange / act / assert: no Click invocation is in progress, so there is no built app to read
    with pytest.raises(RuntimeError, match="running CLI"):
        cliref.root_command()


def test_the_task_reads_the_root_of_the_app_that_is_running(impls):
    # arrange
    root, _ = _built()
    seen = {}

    @click.command()
    def leaf():
        seen["root"] = cliref.root_command()

    root.add_command(leaf, "probe")

    # act
    CliRunner().invoke(root, ["probe"])

    # assert
    assert seen["root"] is root


def test_the_task_writes_the_page_where_the_manifest_pinned_it(monkeypatch, tmp_path, impls):
    # arrange
    root, mf = _built()
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest", lambda self: mf)
    monkeypatch.setattr(cliref, "root_command", lambda: root)

    # act
    rc = cliref.reference("site/content/reference/commands.md")

    # assert
    assert rc == 0
    page = (tmp_path / "site/content/reference/commands.md").read_text(encoding="utf-8")
    assert "sample build wheel" in page


def test_an_output_path_that_leaves_the_product_root_is_refused(monkeypatch, tmp_path, impls):
    # arrange: the same rule `docs:site` applies to its own paths (simplon.bootstrap.validate_relative_dir)
    root, mf = _built()
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest", lambda self: mf)
    monkeypatch.setattr(cliref, "root_command", lambda: root)

    # act / assert
    with pytest.raises(ValueError, match="relative"):
        cliref.reference("/etc/commands.md")
