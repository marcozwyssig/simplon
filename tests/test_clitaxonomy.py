"""Unit tests for the generic CommandTaxonomy env-gate engine (delivery.clitaxonomy): the reverse
index, group/flat-command resolution, env-requirement, and the verdict - exercised on a SYNTHETIC taxonomy
so the engine is validated independently of any product's command set. AAA throughout."""
import pytest

from delivery import clitaxonomy
from delivery.clitaxonomy import CommandTaxonomy, TaxonomyNode


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


def _tax_with_group_default() -> CommandTaxonomy:
    """`build` is a MULTI-member group that ALSO contains a `build` member (the #592 D4 shape): a
    discipline that gained sibling commands but keeps its bare group-token default action."""
    return CommandTaxonomy(
        groups={"build": ("build", "diff", "docs"), "package": ("package",), "test": ("unit", "lint")},
        env_groups=frozenset(),
    )


def test_is_group_default_command_only_for_a_multi_member_group_named_after_a_member():
    # arrange / act / assert: build has several members incl. one named `build`; package is single-member
    # (flat-collapse, not group-default); test is multi-member but named after NONE of its members
    tax = _tax_with_group_default()
    assert tax.is_group_default_command("build") is True
    assert tax.is_group_default_command("package") is False
    assert tax.is_group_default_command("test") is False


def test_flat_collapse_and_group_default_are_mutually_exclusive():
    # arrange / act / assert: a single-member same-named group collapses (flat); a multi-member same-named
    # group is group-default - never both, so the assembly picks exactly one wiring per group
    tax = _tax_with_group_default()
    assert tax.is_flat_command_group("build") is False and tax.is_group_default_command("build") is True
    assert tax.is_flat_command_group("package") is True and tax.is_group_default_command("package") is False


def test_a_group_default_groups_namesake_member_is_unambiguous_and_resolves_to_the_group():
    # arrange / act / assert: the namesake `build` is owned by only the build group, so it keeps a flat
    # reverse mapping and its bare token resolves to the group (the env-gate still treats it agnostically)
    tax = _tax_with_group_default()
    assert tax.is_ambiguous("build") is False
    assert tax.command_group["build"] == "build"
    assert tax.resolve_group("build") == "build"


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


# --- the tree (netctl#1431): the declared flat shape IS a tree of depth one -------------------------

def test_a_flat_declaration_becomes_a_depth_one_tree():
    # arrange
    groups = {"build": ("build", "gradle"), "deploy": ("up", "down")}

    # act
    tax = CommandTaxonomy(groups, frozenset({"deploy"}))

    # assert: one node per declared group, its commands verbatim, no children
    assert sorted(tax.tree) == ["build", "deploy"]
    assert tax.tree["build"].commands == ("build", "gradle")
    assert tax.tree["build"].groups == {}
    assert tax.tree["deploy"].env_first is True
    assert tax.tree["build"].env_first is False


def test_the_flat_groups_projection_survives_the_tree_rewrite():
    # arrange: delivery.cli:233 tests membership against `.groups`, so it must stay a mapping of
    # group name -> ordered command names
    groups = {"build": ("build", "gradle")}

    # act
    tax = CommandTaxonomy(groups, frozenset())

    # assert
    assert tax.groups == {"build": ("build", "gradle")}
    assert "build" in tax.groups


# --- nesting: a group holds groups, addressed by dotted path ----------------------------------------

def _nested() -> CommandTaxonomy:
    """The tree the design targets: git nested beneath support, deploy env-first."""
    return CommandTaxonomy.from_tree({
        "build": TaxonomyNode(name="build", commands=("build", "gradle")),
        "deploy": TaxonomyNode(name="deploy", commands=("up", "down"), env_first=True),
        "support": TaxonomyNode(name="support", commands=("nexus", "doctor"), groups={
            "git": TaxonomyNode(name="git", commands=("commit", "push")),
        }),
    })


def test_a_nested_group_resolves_by_its_dotted_path():
    # arrange
    tax = _nested()

    # act
    node = tax.resolve_path("support.git")

    # assert
    assert node is not None
    assert node.name == "git"
    assert node.commands == ("commit", "push")


def test_a_top_level_group_resolves_by_its_bare_name():
    # arrange / act / assert
    assert _nested().resolve_path("support").name == "support"


def test_an_unknown_path_resolves_to_none():
    # arrange
    tax = _nested()

    # act / assert: each negative case is a distinct way to be wrong
    assert tax.resolve_path("nope") is None
    assert tax.resolve_path("support.nope") is None
    assert tax.resolve_path("build.git") is None       # build has no children at all
    assert tax.resolve_path("") is None
    assert tax.resolve_path(None) is None


def test_the_flat_groups_projection_of_a_nested_tree_lists_only_the_top_level():
    # arrange / act / assert: delivery.cli:233 asks "is argv[1] a group token?", which is a
    # TOP-LEVEL question; a nested group is never a leading token.
    assert sorted(_nested().groups) == ["build", "deploy", "support"]


# --- env_first is declared on the subtree ROOT and inherited by every descendant ---------------------

def _env_nested() -> CommandTaxonomy:
    """deploy is env-first and has a child group, which must inherit the flag."""
    return CommandTaxonomy.from_tree({
        "build": TaxonomyNode(name="build", commands=("build",)),
        "deploy": TaxonomyNode(name="deploy", commands=("up",), env_first=True, groups={
            "rescue": TaxonomyNode(name="rescue", commands=("reset",)),
        }),
    })


def test_a_child_of_an_env_first_group_inherits_the_flag():
    # arrange: `rescue` never declares env_first itself
    tax = _env_nested()

    # act / assert
    assert tax.group_requires_env("deploy.rescue") is True


def test_a_child_of_an_agnostic_group_does_not_require_an_env():
    # arrange
    tax = CommandTaxonomy.from_tree({
        "support": TaxonomyNode(name="support", commands=("nexus",), groups={
            "git": TaxonomyNode(name="git", commands=("commit",)),
        }),
    })

    # act / assert
    assert tax.group_requires_env("support.git") is False


def test_an_unknown_path_requires_no_env():
    # arrange
    tax = _env_nested()

    # act / assert: an unknown token must reach the "ok" verdict, never a gate
    assert tax.group_requires_env("nope") is False
    assert tax.group_requires_env("deploy.nope") is False


def test_the_env_verdict_gates_a_nested_env_first_group():
    # arrange
    tax = _env_nested()

    # act / assert
    assert tax.env_verdict("deploy", env_explicit=False) == "gate-backend"
    assert tax.env_verdict("build", env_explicit=True) == "reject-env"
    assert tax.env_verdict("build", env_explicit=False) == "ok"
    assert tax.env_verdict(None, env_explicit=False) == "ok"


# --- a flat alias depends on the NAME, not on the depth ----------------------------------------------

def test_a_leaf_keeps_its_flat_alias_at_any_depth():
    # arrange: `commit` sits two levels down and is unique in the whole tree
    tax = _nested()

    # act / assert
    assert tax.is_ambiguous("commit") is False
    assert tax.resolve_group("commit") == "support.git"


def test_a_name_owned_by_two_subtrees_has_no_flat_form():
    # arrange: #519's case - `all` under test and under deploy
    tax = CommandTaxonomy.from_tree({
        "test": TaxonomyNode(name="test", commands=("all", "unit-java")),
        "deploy": TaxonomyNode(name="deploy", commands=("all", "up"), env_first=True),
    })

    # act / assert: ambiguous -> no flat alias, addressable only via its group token
    assert tax.is_ambiguous("all") is True
    assert tax.resolve_group("all") is None
    assert tax.is_ambiguous("unit-java") is False
    assert tax.resolve_group("unit-java") == "test"


def test_a_group_token_still_resolves_to_itself():
    # arrange / act / assert: a top-level group token beats any command lookup
    assert _nested().resolve_group("support") == "support"


def test_an_unknown_token_resolves_to_no_group():
    # arrange / act / assert
    assert _nested().resolve_group("nope") is None
    assert _nested().resolve_group(None) is None


def test_a_nested_leaf_that_collides_with_a_top_level_leaf_is_ambiguous():
    # arrange: the collision nesting makes newly possible - same name, different depths
    tax = CommandTaxonomy.from_tree({
        "build": TaxonomyNode(name="build", commands=("status",)),
        "support": TaxonomyNode(name="support", commands=(), groups={
            "git": TaxonomyNode(name="git", commands=("status",)),
        }),
    })

    # act / assert: neither gets the flat alias, because `netctl status` would be a coin toss
    assert tax.is_ambiguous("status") is True
    assert tax.resolve_group("status") is None


# --- merge: the catalogue takes the tree over one group at a time -----------------------------------

def test_a_catalogue_group_and_a_product_group_merge_into_one_tree():
    # arrange: the half-migrated state - build has moved, deploy has not
    catalogue = {"build": TaxonomyNode(name="build", commands=("build", "gradle"))}
    product = {"deploy": TaxonomyNode(name="deploy", commands=("up",), env_first=True)}

    # act
    merged = clitaxonomy.merge_trees(catalogue, product)

    # assert: both survive, neither is altered
    assert sorted(merged) == ["build", "deploy"]
    assert merged["build"].commands == ("build", "gradle")
    assert merged["deploy"].env_first is True


def test_a_group_declared_in_both_manifests_is_an_error():
    # arrange: the same group in both is a contradiction, not a precedence question
    catalogue = {"build": TaxonomyNode(name="build", commands=("build",))}
    product = {"build": TaxonomyNode(name="build", commands=("gradle",))}

    # act / assert: the message must NAME the group, so the fix is obvious from the failure alone
    with pytest.raises(ValueError, match="build"):
        clitaxonomy.merge_trees(catalogue, product)


def test_the_error_names_every_clashing_group_not_only_the_first():
    # arrange: a wave migration can clash on several groups at once; reporting one at a time
    # turns one fix into three rounds
    catalogue = {"build": TaxonomyNode(name="build"), "test": TaxonomyNode(name="test")}
    product = {"build": TaxonomyNode(name="build"), "test": TaxonomyNode(name="test")}

    # act / assert
    with pytest.raises(ValueError) as err:
        clitaxonomy.merge_trees(catalogue, product)
    assert "build" in str(err.value)
    assert "test" in str(err.value)


def test_an_empty_catalogue_leaves_the_product_tree_untouched():
    # arrange: this IS netctl's state throughout netctl#1431 - no catalogue exists yet
    product = {"deploy": TaxonomyNode(name="deploy", commands=("up",))}

    # act
    merged = clitaxonomy.merge_trees({}, product)

    # assert
    assert merged == product


# --- the two shape predicates must be path-aware, like group_requires_env -----------------------------

def test_a_nested_single_member_group_named_after_itself_is_a_flat_command_group():
    # arrange: the collapse rule, one level down - `support.doctor` holding only `doctor`
    tax = CommandTaxonomy.from_tree({
        "support": TaxonomyNode(name="support", commands=(), groups={
            "doctor": TaxonomyNode(name="doctor", commands=("doctor",)),
        }),
    })

    # act / assert
    assert tax.is_flat_command_group("support.doctor") is True
    assert tax.is_group_default_command("support.doctor") is False


def test_a_nested_multi_member_group_containing_its_own_name_has_a_default_command():
    # arrange
    tax = CommandTaxonomy.from_tree({
        "support": TaxonomyNode(name="support", commands=(), groups={
            "git": TaxonomyNode(name="git", commands=("git", "commit", "push")),
        }),
    })

    # act / assert: the two are mutually exclusive, at any depth
    assert tax.is_group_default_command("support.git") is True
    assert tax.is_flat_command_group("support.git") is False


def test_the_shape_predicates_answer_false_for_an_unknown_path():
    # arrange / act / assert: silently wrong is the failure mode these replace
    tax = _nested()
    assert tax.is_flat_command_group("nope") is False
    assert tax.is_group_default_command("support.nope") is False
