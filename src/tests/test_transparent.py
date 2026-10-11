"""The transparent level (si#344, spec A.2): `ci` and `cd` are real nodes in the merged tree and absent
from every path the CLI is built from. AAA throughout."""
import pytest

from simplon.orchestrator.model import treeform

TREE = {
    "ci": {"transparent": True, "help": "CI", "groups": {
        "build": {"help": "Produce.", "commands": {"wheel": {"task": "wheel"}}},
        "test": {"help": "Verify."}}},
    "cd": {"transparent": True, "env_first": True, "groups": {
        "deploy": {"help": "Put.", "commands": {"up": {"task": "deploy:up"}}}}},
    "support": {"help": "Support.", "commands": {"install": {"task": "support:install"}}},
}


def test_transparent_nodes_are_folded_away_and_their_children_hoisted():
    # act
    elided, areas = treeform.elide_transparent(TREE)

    # assert
    assert list(elided) == ["build", "test", "deploy", "support"]
    assert elided["build"]["commands"] == {"wheel": {"task": "wheel"}}
    assert areas == {"build": "ci", "test": "ci", "deploy": "cd"}


def test_a_transparent_env_first_node_hands_env_first_to_every_child():
    # act
    elided, _ = treeform.elide_transparent(TREE)

    # assert
    assert elided["deploy"].get("env_first") is True
    assert "env_first" not in elided["build"]


def test_a_tree_with_no_transparent_node_is_returned_unchanged():
    # arrange
    tree = {"build": {"commands": {"x": {"task": "y"}}}}

    # act
    elided, areas = treeform.elide_transparent(tree)

    # assert
    assert elided == tree and areas == {}


def test_two_transparent_siblings_that_would_hoist_the_same_name_are_refused():
    # arrange
    tree = {"ci": {"transparent": True, "groups": {"x": {}}},
            "cd": {"transparent": True, "groups": {"x": {}}}}

    # act / assert
    with pytest.raises(ValueError) as caught:
        treeform.elide_transparent(tree)
    assert str(caught.value) == (
        "group 'x' is reached through two transparent nodes, 'ci.x' and 'cd.x', and both would be "
        "'x' on the command line. A transparent node is skipped when the CLI path is built, so its "
        "children's names must be unique across all of them - rename one in the platform's `groups:`")


def test_a_transparent_child_that_collides_with_a_visible_sibling_is_refused():
    # arrange
    tree = {"ci": {"transparent": True, "groups": {"support": {}}}, "support": {}}

    # act / assert
    with pytest.raises(ValueError, match="'ci.support' and 'support'"):
        treeform.elide_transparent(tree)


def test_platform_groups_is_the_first_visible_level():
    # act / assert
    assert treeform.platform_groups(TREE) == frozenset({"build", "test", "deploy", "support"})


def test_lower_accepts_the_transparent_key_and_keeps_it_on_the_shape():
    # act
    taxonomy, flat = treeform.lower({"ci": {"transparent": True, "groups": {"build": {}}}})

    # assert
    assert taxonomy["ci"]["transparent"] is True
    assert "ci.build" in flat
