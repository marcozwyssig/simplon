"""Unit tests for the generic CommandTaxonomy env-gate engine (platformcore.clitaxonomy): the reverse
index, group/flat-command resolution, env-requirement, and the verdict - exercised on a SYNTHETIC taxonomy
so the engine is validated independently of any product's command set. AAA throughout."""
from platformcore.clitaxonomy import CommandTaxonomy


def _tax() -> CommandTaxonomy:
    return CommandTaxonomy(
        groups={"code": ("diff", "lint"), "build": ("build",), "deploy": ("up", "down")},
        env_groups=frozenset({"deploy"}),
    )


def test_command_group_is_the_reverse_index_of_groups():
    # arrange / act
    tax = _tax()

    # assert: every command maps back to its owning group
    assert tax.command_group == {"diff": "code", "lint": "code", "build": "build", "up": "deploy", "down": "deploy"}


def test_resolve_group_returns_group_token_flat_command_or_none():
    # arrange
    tax = _tax()

    # act / assert: a group name resolves to itself; a member to its group; unknown/None to None
    assert tax.resolve_group("deploy") == "deploy"
    assert tax.resolve_group("up") == "deploy"
    assert tax.resolve_group("diff") == "code"
    assert tax.resolve_group("frobnicate") is None
    assert tax.resolve_group(None) is None


def test_group_requires_env_only_for_env_groups():
    # arrange / act / assert
    tax = _tax()
    assert tax.group_requires_env("deploy") is True
    assert tax.group_requires_env("code") is False
    assert tax.group_requires_env("build") is False


def test_is_flat_command_group_only_for_same_named_single_member():
    # arrange / act / assert: build has one member sharing its name; code/deploy have many
    tax = _tax()
    assert tax.is_flat_command_group("build") is True
    assert tax.is_flat_command_group("code") is False
    assert tax.is_flat_command_group("deploy") is False


def _tax_with_duplicate() -> CommandTaxonomy:
    """`all` is owned by BOTH test (agnostic) and deploy (env-first) - the #519 shape."""
    return CommandTaxonomy(
        groups={"test": ("unit", "all"), "deploy": ("up", "all")},
        env_groups=frozenset({"deploy"}),
    )


def test_a_name_owned_by_several_groups_is_ambiguous_and_lists_all_owners():
    # arrange / act
    tax = _tax_with_duplicate()

    # assert: the multi-owner index carries both groups, in declaration order
    assert tax.command_groups["all"] == ("test", "deploy")
    assert tax.is_ambiguous("all") is True
    assert tax.is_ambiguous("unit") is False


def test_an_ambiguous_name_has_no_flat_reverse_index_entry():
    # arrange / act
    tax = _tax_with_duplicate()

    # assert: unique names keep their reverse mapping; the ambiguous one is absent (no flat command)
    assert tax.command_group == {"unit": "test", "up": "deploy"}
    assert tax.resolve_group("all") is None


def test_env_verdict_treats_an_ambiguous_flat_token_as_unknown():
    # arrange
    tax = _tax_with_duplicate()

    # act / assert: bare `all` resolves to no group, so the gate has nothing to decide ("ok" - the CLI
    # then fails it as an unknown command because no flat alias is registered for an ambiguous name)
    assert tax.env_verdict("all", env_explicit=False) == "ok"
    assert tax.env_verdict("all", env_explicit=True) == "ok"


def test_env_verdict_rejects_explicit_env_on_agnostic_gates_cd_and_is_ok_otherwise():
    # arrange
    tax = _tax()

    # act / assert: explicit env on an agnostic group is rejected
    assert tax.env_verdict("build", env_explicit=True) == "reject-env"
    # a CD group is gated whether or not the env was explicit
    assert tax.env_verdict("deploy", env_explicit=False) == "gate-backend"
    assert tax.env_verdict("up", env_explicit=True) == "gate-backend"
    # agnostic without env, and unknown/None tokens, are ok (passthrough)
    assert tax.env_verdict("build", env_explicit=False) == "ok"
    assert tax.env_verdict("frobnicate", env_explicit=True) == "ok"
    assert tax.env_verdict(None, env_explicit=False) == "ok"
