"""The transparent level (si#344, spec A.2): `ci` and `cd` are real nodes in the merged tree and absent
from every path the CLI is built from. AAA throughout."""
import textwrap

import pytest

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod
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


def test_a_transparent_node_that_declares_commands_is_refused_rather_than_dropped():
    """A transparent node is skipped when the CLI path is built, so a command on it has no path. Folding
    it away silently was the house defect - a command declared, loaded green, and run nowhere."""
    # arrange
    tree = {"ci": {"transparent": True, "commands": {"x": {"task": "y"}}, "groups": {"build": {}}}}

    # act / assert
    with pytest.raises(ValueError) as caught:
        treeform.elide_transparent(tree)
    assert str(caught.value) == (
        "group 'ci' is transparent and declares `commands:`. A transparent node is skipped when the CLI "
        "path is built, so a command on it would have no path - place it on one of its groups")


# --- the loader reads the area form (si#344, plan A Task 3) -------------------------------------------

NEW_FORM = textwrap.dedent("""\
    product: demo
    tasks:
      wheel: { impl: "pkg.mod:wheel", help: "Build the wheel.", unattended: true }
    ci:
      build:
        commands:
          wheel: { task: wheel }
    cd:
      default: dev
      environments: { dev: { backend: local } }
""")


def _load(text: str):
    return manifest_mod.load(text, catalogue=catalogue_mod.load())


def test_the_catalogues_top_level_is_the_three_areas():
    # act
    groups = catalogue_mod.load().groups

    # assert
    assert list(groups) == ["ci", "cd", "support"]
    assert groups["ci"]["transparent"] is True and groups["cd"]["transparent"] is True
    assert groups["cd"]["env_first"] is True
    assert list(groups["ci"]["groups"]) == ["build", "test", "release"]
    assert list(groups["cd"]["groups"]) == ["deploy", "monitor"]


def test_a_command_under_ci_build_is_build_on_the_command_line():
    # act
    mf = _load(NEW_FORM)

    # assert
    assert mf.groups["build"] == ("wheel",)
    assert mf.area_of("build") == "ci"
    assert mf.area_of("support.git") is None


def test_the_old_groups_form_is_refused_rather_than_read():
    # arrange: the same manifest, still written in the form si#344 replaced
    old = NEW_FORM.replace("ci:\n  build:", "groups:\n  build:")

    # act / assert: no second reading of it any more - the cut, by name (`test_cut.py` pins the text)
    with pytest.raises(ValueError, match="declares `groups:`, which si#344 replaced"):
        _load(old)


def test_everything_under_cd_is_env_first_and_nothing_under_ci_is():
    # act
    tax = _load(NEW_FORM).taxonomy()

    # assert
    assert tax.group_requires_env("deploy") and tax.group_requires_env("monitor")
    assert not tax.group_requires_env("build")


def test_a_catalogue_less_load_still_treats_ci_as_transparent():
    """Without a catalogue there is no platform tree to say `ci` is transparent; `AREA_SKELETON` says it,
    so the command is `build wheel` here too and not `ci build wheel`. (The body is declared under
    `tasks:` and named with `task:` - `impl:` on a command is refused in every load, catalogue or not.)"""
    # act
    mf = manifest_mod.load(NEW_FORM)

    # assert
    assert "build" in mf.groups and "ci.build" not in mf.groups


def test_the_skeleton_agrees_with_the_catalogue_on_the_areas():
    """`AREA_SKELETON` is a second statement of which areas are transparent, and it exists only so that
    a load without a catalogue reads `ci:` the way every product does. This holds it to the first."""
    # arrange
    cat = catalogue_mod.load().groups

    # act / assert
    for area, node in treeform.AREA_SKELETON.items():
        assert bool(node.get("transparent")) == bool(cat[area].get("transparent"))
        assert bool(node.get("env_first")) == bool(cat[area].get("env_first"))


# --- what a product may not say about the area shape (si#344, plan A Task 4) ---------------------------

def test_a_product_writing_transparent_is_refused():
    # arrange
    text = NEW_FORM.replace("  build:\n", "  build:\n    transparent: true\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`ci: build:` declares `transparent:`. Which nodes are transparent is the platform's statement "
        "(the catalogue's `groups:`), so that `ci` and `cd` are skipped on the command line in every "
        "product and nothing else is - remove the key")


def test_transparent_on_a_group_nested_under_support_names_where_it_is_written():
    # arrange: `support:` is a group node with no name of its own above it, so the location is built
    # from the area alone - without a stray `: ` where a name would have stood
    text = NEW_FORM + "support:\n  groups:\n    git:\n      transparent: true\n"

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value).startswith("`support: groups: git:` declares `transparent:`. ")


def test_env_first_under_ci_is_refused():
    # arrange
    text = NEW_FORM.replace("  build:\n", "  build:\n    env_first: true\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`ci: build:` declares `env_first:`. Nothing under `ci:` takes an environment - a build, a test "
        "and a release run the same in every environment; what takes one stands under `cd:`, which is "
        "env-first as a whole. Remove the key, or move the commands that need an environment under `cd:`")


def test_an_unknown_key_under_cd_names_both_lists():
    # arrange
    text = NEW_FORM.replace("  default: dev\n", "  default: dev\n  rollout: {}\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`cd: rollout:` is neither a phase group nor a data key. Under `cd:` stand the phase "
        "groups deploy, monitor and the data keys default, environments, site")


def test_an_area_that_is_not_a_mapping_is_refused():
    # arrange
    text = NEW_FORM.replace("ci:\n  build:\n    commands:\n      wheel: { task: wheel }\n", "ci: [build]\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`ci:` is not a mapping: found list instead. It maps each phase group (build, test, release) "
        "to its node - check the indentation under this key")


@pytest.mark.parametrize("area, first", [("ci", "build"), ("cd", "deploy")])
@pytest.mark.parametrize("with_catalogue", [True, False])
def test_commands_directly_under_an_area_are_refused(area, first, with_catalogue):
    # arrange
    text = NEW_FORM.replace(f"{area}:\n", f"{area}:\n  commands: {{}}\n")
    load = _load if with_catalogue else manifest_mod.load

    # act / assert
    with pytest.raises(ValueError) as caught:
        load(text)
    assert str(caught.value) == (
        f"`{area}: commands:` stands directly under the area. Commands belong to a phase group - "
        f"`{area}: {first}: commands:` - because the area itself is skipped on the command line")


# --- a refusal names the place the manifest WRITES a group (si#344, review round 1) ---------------------

def test_a_phase_group_that_is_not_a_mapping_is_named_where_it_is_written():
    # arrange
    text = NEW_FORM.replace("  build:\n    commands:\n      wheel: { task: wheel }\n", "  build: 3\n")

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value) == (
        "`ci: build:` is not a mapping: found int instead. A group node's value must be a mapping with "
        "its own keys (help, env_first, groups, commands) - check the indentation under this entry")


def test_an_unknown_key_on_a_nested_support_group_is_named_where_it_is_written():
    # arrange
    text = NEW_FORM + "support:\n  groups:\n    git:\n      bogus: 1\n"

    # act / assert
    with pytest.raises(ValueError) as caught:
        _load(text)
    assert str(caught.value).startswith("`support: groups: git:` declares unknown key 'bogus'. ")


def test_a_shadowed_task_declaration_names_the_command_and_its_place_as_written():
    # arrange: a `tasks: wheel` no command instantiates, beside a command `wheel` that runs another body
    text = textwrap.dedent("""\
        product: demo
        tasks:
          wheel: { impl: "pkg.mod:wheel", help: "Build the wheel." }
          other: { impl: "pkg.mod:other", help: "Something else." }
        support:
          groups:
            git:
              commands:
                wheel: { task: other }
    """)

    # act / assert: the command as the command line spells it, the place as the manifest writes it
    with pytest.raises(ValueError) as caught:
        _load(text)
    message = str(caught.value)
    assert "the command 'support git wheel' - the one that bears its name" in message
    assert "Either point `support: groups: git: commands: wheel:` at `task: wheel`" in message
