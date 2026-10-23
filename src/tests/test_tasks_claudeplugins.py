"""Unit tests for simplon.tasks.claudeplugins (netctl#1286): the manifest's `claude` section as the one
declaration of a product's agent plugin set, and the pure derivation of what a machine is missing.

Nothing here shells out. `declared` and `plan` are pure, and the CLI answers are captured `--json` output
pasted in as fixtures, so the suite needs no `claude` binary and no network. Whether a PARTICULAR product's
manifest agrees with its `.claude/settings.json` is a product-side test - only the product knows where its
settings file lives. AAA throughout.
"""
import json

import pytest

from simplon.tasks import claudeplugins

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
    with pytest.raises(ValueError, match="/tmp/other.yaml: the 'claude' section is not a mapping"):
        claudeplugins.declared({"claude": 5}, source="/tmp/other.yaml")


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


def test_declared_reads_a_missing_section_as_no_additions():
    # arrange: si#525 - simplon owns the default, so a product with nothing to add writes nothing
    # act / assert
    assert claudeplugins.declared({"product": "demo"}) == ((), ())


def test_declared_reads_an_empty_section_as_no_additions():
    # act / assert: the smcctl case - before si#525 the only way in was copying simplon's whole list
    assert claudeplugins.declared({"claude": {}}) == ((), ())


def test_declared_rejects_a_section_that_is_not_a_mapping():
    # act / assert
    with pytest.raises(ValueError, match="the 'claude' section is not a mapping"):
        claudeplugins.declared({"claude": ["superpowers@claude-plugins-official"]})


def test_a_product_plugin_may_name_a_default_marketplace_without_declaring_it():
    # act
    markets, plugins = claudeplugins.declared({"claude": {"plugins": ["kotlin-lsp@claude-plugins-official"]}})

    # assert: the default's marketplaces are known to every product, and only its own are declared
    assert markets == ()
    assert plugins == ("kotlin-lsp@claude-plugins-official",)


# --- the effective set: simplon's default, the product's additions, its exclusions (si#525) ---------

_OFFICIAL = "claude-plugins-official"


def test_no_claude_toolchain_is_off():
    assert claudeplugins.effective({"toolchains": ["python"]}) is None


def test_claude_alone_is_the_base_set():
    # act
    eff = claudeplugins.effective({"toolchains": ["claude"]})

    # assert
    assert eff.plugins == claudeplugins.BASE_PLUGINS
    assert eff.plugins == (f"superpowers@{_OFFICIAL}", f"feature-dev@{_OFFICIAL}", f"code-review@{_OFFICIAL}",
                           f"code-simplifier@{_OFFICIAL}", f"security-guidance@{_OFFICIAL}",
                           f"github@{_OFFICIAL}", f"frontend-design@{_OFFICIAL}",
                           "token-optimizer@alexgreensh-token-optimizer")
    assert set(eff.origin.values()) == {"default"}
    assert {m.name for m in eff.markets} == {_OFFICIAL, "alexgreensh-token-optimizer"}
    assert eff.requires == ("node",)


def test_empty_section_is_the_default():
    assert claudeplugins.effective({"toolchains": ["claude"], "claude": {}}).plugins == claudeplugins.BASE_PLUGINS


@pytest.mark.parametrize("language, plugin, binary", [
    ("python", "pyright-lsp", "pyright-langserver"), ("java", "jdtls-lsp", "jdtls"),
    ("cpp", "clangd-lsp", "clangd"), ("dotnet", "csharp-lsp", "csharp-ls")])
def test_language_adds_its_set_and_requires(language, plugin, binary):
    # act
    eff = claudeplugins.effective({"toolchains": ["claude", language]})

    # assert
    assert eff.plugins[-1] == f"{plugin}@{_OFFICIAL}"
    assert eff.origin[f"{plugin}@{_OFFICIAL}"] == f"toolchain {language}"
    assert binary in eff.requires


def test_a_language_without_claude_brings_nothing():
    assert claudeplugins.effective({"toolchains": ["python", "gh"]}) is None


def test_product_additions_and_their_marketplace():
    # arrange
    data = {"toolchains": ["claude"],
            "claude": {"marketplaces": {"acme": {"source": "github", "repo": "acme/plugins"}},
                       "plugins": ["x@acme"], "requires": ["acmectl"]}}

    # act
    eff = claudeplugins.effective(data)

    # assert
    assert eff.plugins[-1] == "x@acme"
    assert eff.origin["x@acme"] == "product"
    assert "acme" in {m.name for m in eff.markets}
    assert eff.requires == ("node", "acmectl")


def test_a_product_plugin_naming_an_undeclared_marketplace_is_still_refused():
    with pytest.raises(ValueError, match="names undeclared marketplace 'acme'"):
        claudeplugins.effective({"toolchains": ["claude"], "claude": {"plugins": ["x@acme"]}})


def test_a_product_restating_a_default_plugin_keeps_its_default_origin():
    # act
    eff = claudeplugins.effective({"toolchains": ["claude"], "claude": {"plugins": [f"github@{_OFFICIAL}"]}})

    # assert: one entry, not two, and the dry run still says where it really comes from
    assert eff.plugins == claudeplugins.BASE_PLUGINS
    assert eff.origin[f"github@{_OFFICIAL}"] == "default"


def test_exclude_removes_and_takes_requires_with_it():
    # arrange: Review Focus 2 - the exclusion wins over the product's own toolchain
    data = {"toolchains": ["claude", "python"], "claude": {"exclude": [f"pyright-lsp@{_OFFICIAL}"]}}

    # act
    eff = claudeplugins.effective(data)

    # assert
    assert f"pyright-lsp@{_OFFICIAL}" not in eff.plugins
    assert "pyright-langserver" not in eff.requires


def test_excluding_token_optimizer_drops_node_and_its_marketplace():
    # act
    eff = claudeplugins.effective({"toolchains": ["claude"],
                                   "claude": {"exclude": ["token-optimizer@alexgreensh-token-optimizer"]}})

    # assert: a marketplace nothing installs from is not registered
    assert "node" not in eff.requires
    assert {m.name for m in eff.markets} == {_OFFICIAL}


def test_exclude_of_nothing_is_refused():
    with pytest.raises(ValueError, match=f"excludes 'nope@{_OFFICIAL}', which is not in the default"):
        claudeplugins.effective({"toolchains": ["claude"], "claude": {"exclude": [f"nope@{_OFFICIAL}"]}})


def test_exclude_not_a_list_is_refused():
    with pytest.raises(ValueError, match="'claude.exclude' must be a list"):
        claudeplugins.effective({"toolchains": ["claude"], "claude": {"exclude": f"github@{_OFFICIAL}"}})


def test_excluding_everything_is_refused():
    with pytest.raises(ValueError, match="the effective plugin set is empty"):
        claudeplugins.effective({"toolchains": ["claude"],
                                 "claude": {"exclude": list(claudeplugins.BASE_PLUGINS)}})


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

    import simplon.tasks.claudeplugins as module

    # act
    source = _Path(module.__file__).read_text(encoding="utf-8")

    # assert
    assert "typer.Exit" not in source
    assert "\nimport typer" not in source


# --- si#292: a marketplace can say WHICH ---------------------------------------------------------------


def _one_market(**extra):
    return {"claude": {"marketplaces": {"m": {"source": "github", "repo": "o/r", **extra}},
                       "plugins": ["p@m"]}}


def test_a_marketplace_may_name_the_ref_it_is_fetched_at():
    """si#292. Six of the eight manifests this family can reach named the same third-party marketplace
    and none of them could say a version - an expressiveness gap in a section that reads as a
    declaration of what a product is developed with."""
    markets, _ = claudeplugins.declared(_one_market(ref="v1.2.3"))

    assert markets[0].ref == "v1.2.3"


def test_a_marketplace_without_a_ref_is_unchanged():
    """Every manifest written before si#292 keeps its meaning: no ref is the repository's default
    branch, which is what they have been getting."""
    markets, _ = claudeplugins.declared(_one_market())

    assert markets[0].ref == ""


def test_the_ref_reaches_the_command_in_the_spelling_the_cli_takes():
    """`owner/repo#ref` is the CLI's spelling and it is assembled in ONE place, so the manifest names the
    two halves separately and nothing has to know both."""
    pinned = claudeplugins.Marketplace(name="m", repo="o/r", ref="v1.2.3")
    plain = claudeplugins.Marketplace(name="m", repo="o/r")

    assert claudeplugins._source_of(pinned) == "o/r#v1.2.3"
    assert claudeplugins._source_of(plain) == "o/r"


def test_a_ref_that_carries_the_cli_separator_is_refused():
    """Refused rather than stripped: a value silently edited before use is one the manifest no longer
    describes, and `repo: o/r` with `ref: '#v1'` would otherwise reach the CLI as `o/r##v1`."""
    with pytest.raises(ValueError) as exc:
        claudeplugins.declared(_one_market(ref="#v1.2.3"))

    assert "ref" in str(exc.value) and "#" in str(exc.value)


# --- si#396: a plugin set can be complete on a machine that cannot run it -------------------------------


def _with_requires(value):
    return {"claude": {**_SECTION["claude"], "requires": value}}


def test_required_reads_the_executables_the_manifest_names():
    """si#396. token-optimizer's status line is `node …/statusline.js`; with no `node` on PATH, Claude
    Code shows a blank status line and says nothing. The product names what its plugins run."""
    assert claudeplugins.required(_with_requires(["node", "jq"])) == ("node", "jq")


def test_required_is_optional_and_a_section_without_it_requires_nothing():
    """Every manifest written before si#396 keeps its meaning."""
    assert claudeplugins.required(_SECTION) == ()


@pytest.mark.parametrize("value", ["node", {"node": True}, 3])
def test_required_that_is_not_a_list_is_refused(value):
    """`requires: node` is the likely slip, and iterating it would check `n`, `o`, `d`, `e`."""
    with pytest.raises(ValueError, match=r"m.yaml: 'claude.requires' must be a list of executable names"):
        claudeplugins.required(_with_requires(value), source="m.yaml")


@pytest.mark.parametrize("entry", ["", "  ", None, 7, ["node"]])
def test_a_required_entry_that_is_not_a_name_is_refused(entry):
    with pytest.raises(ValueError, match=r"'claude.requires': .* is not an executable name"):
        claudeplugins.required(_with_requires(["node", entry]))


def test_missing_names_the_executables_not_on_path_in_declaration_order():
    on_path = {"jq": "/usr/bin/jq"}

    assert claudeplugins.missing(("node", "jq", "rg"), which=on_path.get) == ("node", "rg")


def _machine(monkeypatch, tmp_path, *, requires, on_path):
    """`install` against a stubbed machine: every declared plugin is installed, and `which` answers only
    for `claude` and the names in `on_path`. Returns the log lines, by level."""
    import types

    from simplon.kernel.run import Result as RunResult

    data = _with_requires(requires)
    ctx = types.SimpleNamespace(manifest_data=lambda: data, manifest_path=tmp_path / "m.yaml")
    monkeypatch.setattr(claudeplugins.context, "current", lambda: ctx)
    monkeypatch.setattr(claudeplugins.shutil, "which",
                        lambda name: f"/bin/{name}" if name in ("claude", *on_path) else None)
    answers = {
        ("claude", "plugin", "marketplace", "list", "--json"): _MARKETPLACES_JSON,
        ("claude", "plugin", "list", "--json"): json.dumps(
            [{"id": p, "scope": "user"} for p in _SECTION["claude"]["plugins"]]),
    }
    monkeypatch.setattr(claudeplugins, "run",
                        lambda argv, **_: RunResult(rc=0, out=answers[tuple(argv)], err=""))
    lines: list[tuple[str, str]] = []
    for level in ("info", "ok", "warn"):
        monkeypatch.setattr(claudeplugins.log, level, lambda msg, _l=level: lines.append((_l, msg)))
    return lines


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_complete_plugin_set_on_a_machine_missing_a_required_tool_is_not_nothing_to_do(
        monkeypatch, tmp_path, dry_run):
    """The defect si#396 was filed for: "all 9 declared plugins are installed; nothing to do" while a
    plugin could not run. The dry run answers the same, because it is the question "is this machine
    ready"."""
    lines = _machine(monkeypatch, tmp_path, requires=["node", "jq"], on_path=["jq"])

    rc = claudeplugins.install(dry_run=dry_run)

    assert rc == 1
    assert not any("nothing to do" in msg for _, msg in lines)
    assert any(level == "warn" and "`node`" in msg and "not on PATH" in msg for level, msg in lines)
    assert not any("`jq`" in msg for _, msg in lines)


def test_a_complete_plugin_set_with_every_required_tool_present_is_still_nothing_to_do(
        monkeypatch, tmp_path):
    lines = _machine(monkeypatch, tmp_path, requires=["node"], on_path=["node"])

    assert claudeplugins.install() == 0
    assert any(level == "ok" and "nothing to do" in msg for level, msg in lines)
