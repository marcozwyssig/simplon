"""Unit tests for delivery.tasks.claudeplugins (netctl#1286): the manifest's `claude` section as the one
declaration of a product's agent plugin set, and the pure derivation of what a machine is missing.

Nothing here shells out. `declared` and `plan` are pure, and the CLI answers are captured `--json` output
pasted in as fixtures, so the suite needs no `claude` binary and no network. Whether a PARTICULAR product's
manifest agrees with its `.claude/settings.json` is a product-side test - only the product knows where its
settings file lives. AAA throughout.
"""
import json

import pytest

from delivery.tasks import claudeplugins

# Captured verbatim from `claude plugin marketplace list --json` and `claude plugin list --json` on a
# configured machine, trimmed to the fields the module reads. The plugin listing KEEPS the duplicate the
# real CLI emits: one entry per scope, so a plugin enabled at user and project scope is listed twice.
_MARKETPLACES_JSON = json.dumps([
    {"name": "alexgreensh-token-optimizer", "source": "github", "repo": "alexgreensh/token-optimizer"},
    {"name": "claude-plugins-official", "source": "github", "repo": "anthropics/claude-plugins-official"},
])
_PLUGINS_JSON = json.dumps([
    {"id": "code-review@claude-plugins-official", "scope": "user", "enabled": True},
    {"id": "frontend-design@claude-plugins-official", "scope": "project", "enabled": True},
    {"id": "frontend-design@claude-plugins-official", "scope": "user", "enabled": True},
])

_SECTION = {
    "claude": {
        "marketplaces": {
            "claude-plugins-official": {"source": "github", "repo": "anthropics/claude-plugins-official"},
            "alexgreensh-token-optimizer": {"source": "github", "repo": "alexgreensh/token-optimizer"},
        },
        "plugins": ["superpowers@claude-plugins-official", "token-optimizer@alexgreensh-token-optimizer"],
    }
}


# --- the declaration ---------------------------------------------------------------------------------


def test_declared_reads_the_marketplaces_and_plugin_ids_from_the_manifest_section():
    # arrange / act
    markets, plugins = claudeplugins.declared(_SECTION)

    # assert: both come back in DECLARATION order, so the command's output reads like the manifest
    assert [(m.name, m.repo) for m in markets] == [
        ("claude-plugins-official", "anthropics/claude-plugins-official"),
        ("alexgreensh-token-optimizer", "alexgreensh/token-optimizer"),
    ]
    assert plugins == ("superpowers@claude-plugins-official", "token-optimizer@alexgreensh-token-optimizer")


def test_declared_labels_its_errors_with_the_source_the_caller_names():
    # arrange: `install` passes its manifest path, so the message points at a file on a multi-product host
    # act / assert
    with pytest.raises(ValueError, match="/tmp/other.yaml: the 'claude' section is missing"):
        claudeplugins.declared({}, source="/tmp/other.yaml")


def test_declared_rejects_a_marketplace_whose_repo_is_not_owner_slash_name():
    # arrange: a bare repo name would reach `claude plugin marketplace add` as a nonsense argument
    data = {"claude": {"marketplaces": {"broken": {"source": "github", "repo": "token-optimizer"}},
                       "plugins": ["x@broken"]}}

    # act / assert: the error names the offending key
    with pytest.raises(ValueError, match="claude.marketplaces.broken.*repo must be 'owner/name'"):
        claudeplugins.declared(data)


def test_declared_rejects_a_non_github_marketplace_source():
    # arrange
    data = {"claude": {"marketplaces": {"local": {"source": "path", "repo": "a/b"}},
                       "plugins": ["x@local"]}}

    # act / assert
    with pytest.raises(ValueError, match="only source 'github' is supported"):
        claudeplugins.declared(data)


def test_declared_rejects_a_plugin_id_naming_an_undeclared_marketplace():
    # arrange: a typo in the marketplace half of the id must fail here, not as an opaque CLI error later
    data = {"claude": {"marketplaces": {"official": {"source": "github", "repo": "a/b"}},
                       "plugins": ["superpowers@offical"]}}

    # act / assert
    with pytest.raises(ValueError, match="names undeclared marketplace 'offical'"):
        claudeplugins.declared(data)


def test_declared_rejects_a_plugin_id_without_a_marketplace():
    # arrange
    data = {"claude": {"marketplaces": {"official": {"source": "github", "repo": "a/b"}},
                       "plugins": ["superpowers"]}}

    # act / assert
    with pytest.raises(ValueError, match="must be 'name@marketplace'"):
        claudeplugins.declared(data)


def test_declared_rejects_a_missing_section_rather_than_installing_nothing():
    # arrange: a command that cheerfully installs nothing looks like success on a machine that has nothing
    # act / assert
    with pytest.raises(ValueError, match="the 'claude' section is missing"):
        claudeplugins.declared({"product": "demo"})


def test_declared_rejects_a_section_that_declares_no_plugins():
    # arrange
    data = {"claude": {"marketplaces": {"official": {"source": "github", "repo": "a/b"}}, "plugins": []}}

    # act / assert
    with pytest.raises(ValueError, match="'claude.plugins' declares none"):
        claudeplugins.declared(data)


# --- reading what the machine already has --------------------------------------------------------------


def test_installed_marketplace_names_reads_the_cli_json():
    # arrange / act
    names = claudeplugins.installed_marketplace_names(_MARKETPLACES_JSON)

    # assert
    assert names == ("alexgreensh-token-optimizer", "claude-plugins-official")


def test_installed_plugin_ids_dedups_the_same_plugin_listed_once_per_scope():
    # arrange / act: frontend-design appears twice in the real CLI output (project scope and user scope)
    ids = claudeplugins.installed_plugin_ids(_PLUGINS_JSON)

    # assert: this module only asks whether a plugin is there AT ALL, so the scope duplicate collapses
    assert ids == ("code-review@claude-plugins-official", "frontend-design@claude-plugins-official")


@pytest.mark.parametrize("payload", ["not json at all", '{"plugins": []}'])
def test_an_unreadable_cli_answer_fails_loudly_instead_of_looking_like_an_empty_machine(payload):
    # arrange: degrading to an empty list would turn a broken CLI into a full reinstall
    # act / assert
    with pytest.raises(ValueError):
        claudeplugins.installed_plugin_ids(payload)


# --- the plan ------------------------------------------------------------------------------------------


def test_plan_installs_only_what_is_missing_and_keeps_declaration_order():
    # arrange
    markets, plugins = claudeplugins.declared(_SECTION)

    # act: the official marketplace is registered and one of the two plugins is already there
    todo = claudeplugins.plan(markets, plugins,
                              installed_markets=["claude-plugins-official"],
                              installed_plugins=["superpowers@claude-plugins-official"])

    # assert
    assert [m.name for m in todo.add_marketplaces] == ["alexgreensh-token-optimizer"]
    assert todo.install_plugins == ("token-optimizer@alexgreensh-token-optimizer",)
    assert todo.present_plugins == ("superpowers@claude-plugins-official",)
    assert todo.is_complete is False


def test_plan_on_a_complete_machine_is_empty_so_a_rerun_changes_nothing():
    # arrange: idempotency is not a separate guard, it falls out of the set difference
    markets, plugins = claudeplugins.declared(_SECTION)

    # act
    todo = claudeplugins.plan(markets, plugins,
                              installed_markets=[m.name for m in markets],
                              installed_plugins=plugins)

    # assert
    assert todo.is_complete is True
    assert todo.add_marketplaces == ()
    assert todo.install_plugins == ()
    assert todo.present_plugins == plugins


def test_install_cmd_keeps_the_dry_run_payload_parameter():
    # arrange: the manifest resolves this callable directly and the generator introspects it, so the
    # PARAMETER has to survive even though its `--dry-run` / `-n` decls moved into manifest `params:`
    # (netctl#1444). The ANNOTATION is load-bearing: Typer reads a parameter's type from it, and an
    # unannotated `dry_run=False` renders as `--dry-run TEXT` rather than a boolean flag.
    import inspect

    # act
    signature = inspect.signature(claudeplugins.install_cmd)

    # assert
    assert list(signature.parameters) == ["dry_run"]
    assert signature.parameters["dry_run"].annotation == "bool"
    assert signature.parameters["dry_run"].default is False


def test_install_cmd_returns_an_exit_code_rather_than_raising_typer_exit():
    # arrange: the point of netctl#1444 - the body is callable from anything, not only a Click parser
    from pathlib import Path as _Path

    import delivery.tasks.claudeplugins as module

    # act
    source = _Path(module.__file__).read_text(encoding="utf-8")

    # assert
    assert "typer.Exit" not in source
    assert "\nimport typer" not in source
