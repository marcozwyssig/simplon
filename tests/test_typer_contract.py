"""The Typer behaviours the CLI generator depends on (netctl#1437).

Each assertion here is a DECISION the generator makes, so a Typer/Click version bump that changes one
must fail HERE rather than inside a rendered module, where the symptom would appear far from its cause.

Replaces test_invoke_contract.py. Invoke was measured during design and rejected: its task listing is a
flat dotted list with no panels, no group blurbs and no CI/CD split, and it derives short flags of its
own - so netctl's help display would have had to be rebuilt by hand (design section 0).

AAA throughout.
"""
import click
import typer
from typer.main import get_command
from typer.testing import CliRunner


def _app() -> typer.Typer:
    """One command carrying every feature the generator emits for an ordinary leaf, plus a sibling.

    The sibling is load-bearing rather than decoration: Typer collapses a SINGLE-command app into a bare
    command instead of a group (pinned below), and every shape the generator emits assumes a group.
    """
    app = typer.Typer(add_completion=False)

    @app.command(name="prune-branches", rich_help_panel="CI / agnostic (no env)")
    def prune_branches(dry_run: bool = typer.Option(False, "--dry-run", "-n", help="preview only")):
        """Delete local branches already merged into main."""
        raise typer.Exit(3 if dry_run else 0)

    @app.command(name="push")
    def push():
        """Push."""

    return app


def _leaf(app: typer.Typer, name: str) -> click.Command:
    root = get_command(app)
    return root.get_command(click.Context(root), name)


def test_a_single_command_app_collapses_into_a_bare_command_rather_than_a_group():
    # arrange: a Typer quirk with teeth. The generator always registers at least one sub-app onto the
    # product's root, so the root is a group in practice - but a test or a product that ends up with
    # exactly ONE command gets a different tree, and `root.get_command` then does not exist at all.
    one, two = typer.Typer(add_completion=False), typer.Typer(add_completion=False)

    @one.command(name="only")
    def only():
        """The only one."""

    @two.command(name="first")
    def first():
        """First."""

    @two.command(name="second")
    def second():
        """Second."""

    # act / assert
    assert not isinstance(get_command(one), click.Group)
    assert isinstance(get_command(two), click.Group)


def test_a_generated_command_carries_its_panel_onto_the_click_object():
    # arrange: the panel is what splits the root listing into CI / CD / Internal, and netctl's
    # cli_surface golden reads it off the Click object rather than off rendered text
    app = _app()

    # act
    cmd = _leaf(app, "prune-branches")

    # assert
    assert cmd.rich_help_panel == "CI / agnostic (no env)"


def test_a_generated_option_keeps_its_help_and_its_short_flag():
    # arrange
    app = _app()

    # act
    option = next(p for p in _leaf(app, "prune-branches").params if p.name == "dry_run")

    # assert: both are user-visible and both are pinned by the netctl golden
    assert option.help == "preview only"
    assert sorted(option.opts) == ["--dry-run", "-n"]


def test_an_undeclared_bool_keeps_its_negative_secondary_flag():
    # arrange: this is WHY the generator leaves a parameter alone when the manifest declares no
    # presentation for it - naming any decl explicitly suppresses the `--no-x` Typer derives, which
    # would silently delete a working flag from the surface.
    app = typer.Typer(add_completion=False)

    @app.command(name="prune")
    def prune(remote: bool = False):
        """Prune."""

    @app.command(name="push")
    def push():
        """Push."""

    # act
    option = next(p for p in _leaf(app, "prune").params if p.name == "remote")

    # assert
    assert option.secondary_opts == ["--no-remote"]


def test_typer_exit_carries_the_body_rc_to_the_process():
    # arrange: `raise typer.Exit(rc)` is the generated wrapper's return path
    runner = CliRunner()

    # act
    result = runner.invoke(_app(), ["prune-branches", "--dry-run"])

    # assert
    assert result.exit_code == 3


def test_registering_by_call_is_equivalent_to_decorating():
    # arrange: the generated module defines plain functions and registers them inside `register(app)`,
    # because the product owns the root app. That is only sound if the call form binds identically.
    def body(dry_run: bool = typer.Option(False, "--dry-run", help="preview only")):
        """Delete local branches already merged into main."""

    app = typer.Typer(add_completion=False)

    @app.command(name="push")
    def push():
        """Push."""

    # act
    app.command(name="prune-branches")(body)

    # assert
    cmd = _leaf(app, "prune-branches")
    assert cmd.get_short_help_str(limit=250) == "Delete local branches already merged into main."
    assert next(p for p in cmd.params if p.name == "dry_run").help == "preview only"


def test_a_passthrough_command_accepts_an_unknown_trailing_flag_and_its_neighbour_does_not():
    # arrange: the context settings are PER COMMAND, which is the property that matters - it is why
    # passthrough_args needs no facade bypass and why an unknown flag stays an error everywhere else.
    app = typer.Typer(add_completion=False)

    @app.command(name="gradle", context_settings={"allow_extra_args": True,
                                                  "ignore_unknown_options": True})
    def gradle(ctx: typer.Context):
        """Run gradle."""
        typer.echo(" ".join(ctx.args))

    @app.command(name="strict")
    def strict():
        """Takes no flags."""

    runner = CliRunner()

    # act
    loose = runner.invoke(app, ["gradle", ":web:bootTest", "--rerun-tasks"])
    tight = runner.invoke(app, ["strict", "--rerun-tasks"])

    # assert: the tail arrives verbatim on the passthrough command, and is still an error next door
    assert loose.exit_code == 0
    assert ":web:bootTest --rerun-tasks" in loose.stdout
    assert tight.exit_code != 0


def test_a_context_parameter_is_not_a_command_line_parameter():
    # arrange: the generated wrapper declares `ctx: typer.Context` for a body that wants one. If Typer
    # treated it as a parameter it would appear as a required argument on every such command.
    app = typer.Typer(add_completion=False)

    @app.command(name="accept")
    def accept(ctx: typer.Context, verbose: bool = False):
        """Accept."""

    @app.command(name="push")
    def push():
        """Push."""

    # act
    names = [p.name for p in _leaf(app, "accept").params]

    # assert
    assert names == ["verbose"]


def test_a_sub_app_nests_inside_another_sub_app():
    # arrange: `support git commit` is the first intended use of nesting; the generator relies on
    # add_typer composing to arbitrary depth rather than only one level.
    app, support, git = (typer.Typer(add_completion=False) for _ in range(3))

    @git.command(name="commit")
    def commit():
        """Commit."""

    support.add_typer(git, name="git")
    app.add_typer(support, name="support")

    # act
    root = get_command(app)
    sup = root.get_command(click.Context(root), "support")
    nested = sup.get_command(click.Context(sup), "git")

    # assert
    assert nested.get_command(click.Context(nested), "commit") is not None
