"""The new-form command tree, lowered to the flat form the manifest model validates (netctl#1469).

AAA throughout. Every rejection has a negative test, because a rule that only ever runs on valid input
is a rule nobody has seen work.
"""
import pytest

from delivery.orchestrator import treeform


def test_a_flat_group_lowers_to_a_taxonomy_entry_and_a_member_map():
    # arrange
    tree = {"build": {"help": "Produce the artefacts.",
                      "commands": {"web-image": {"task": "img", "help": "the image."}}}}

    # act
    taxonomy, flat = treeform.lower(tree)

    # assert
    assert taxonomy == {"build": {"help": "Produce the artefacts."}}
    assert flat == {"build": {"web-image": {"task": "img", "help": "the image."}}}


def test_a_nested_group_lowers_to_a_bare_taxonomy_child_and_a_dotted_member_key():
    # arrange: the shape that decides it - the taxonomy nests by BARE name, the flat map keys by DOTTED
    # path, and getting either backwards silently detaches the group from the env gate
    tree = {"support": {"help": "Host tooling.",
                        "groups": {"git": {"help": "VCS helpers.",
                                           "commands": {"push": {"task": "vcs:push"}}}}}}

    # act
    taxonomy, flat = treeform.lower(tree)

    # assert
    assert taxonomy == {"support": {"help": "Host tooling.",
                                    "groups": {"git": {"help": "VCS helpers."}}}}
    assert flat == {"support": {}, "support.git": {"push": {"task": "vcs:push"}}}


def test_env_first_survives_the_lowering():
    # arrange
    tree = {"deploy": {"help": "Deploy.", "env_first": True, "commands": {}}}

    # act
    taxonomy, _ = treeform.lower(tree)

    # assert
    assert taxonomy == {"deploy": {"help": "Deploy.", "env_first": True}}


KERNEL = {
    "build": {"help": "Produce the artefacts.", "commands": {}},
    "support": {"help": "Host tooling.",
                "groups": {"git": {"help": "VCS helpers.",
                                   "commands": {"push": {"task": "vcs:push", "help": "push it."}}}}},
}


def test_a_product_adds_a_command_to_a_platform_group():
    # arrange
    product = {"build": {"commands": {"web-image": {"task": "img"}}}}

    # act
    merged = treeform.merge(KERNEL, product)

    # assert
    assert merged["build"]["commands"] == {"web-image": {"task": "img"}}
    assert merged["support"]["groups"]["git"]["commands"]["push"]["help"] == "push it."


def test_a_product_refines_an_inherited_command_key_by_key():
    # arrange: netctl pinning `tasks generate`'s target is exactly this shape
    product = {"support": {"groups": {"git": {"commands": {"push": {"with": {"remote": "origin"}}}}}}}

    # act
    merged = treeform.merge(KERNEL, product)
    push = merged["support"]["groups"]["git"]["commands"]["push"]

    # assert: the refinement lands and the inherited keys survive it
    assert push == {"task": "vcs:push", "help": "push it.", "with": {"remote": "origin"}}


def test_a_group_the_platform_does_not_declare_is_rejected():
    # arrange: the whole point of the lock - a product may add tasks freely but never a group
    product = {"wildwest": {"commands": {"yeehaw": {"task": "x"}}}}

    # act / assert
    with pytest.raises(ValueError, match="the platform's tree does not declare"):
        treeform.merge(KERNEL, product)


def test_a_nested_group_the_platform_does_not_declare_is_rejected():
    # arrange: the same rule one level down, where a typo in a path used to disable an env gate
    product = {"support": {"groups": {"gti": {"commands": {"push": {"task": "vcs:push"}}}}}}

    # act / assert
    with pytest.raises(ValueError, match="the platform's tree does not declare"):
        treeform.merge(KERNEL, product)


def test_refining_a_task_backed_command_into_an_aggregate_is_rejected():
    # arrange: changing a command's KIND is not a refinement, it is a different command wearing the name
    product = {"support": {"groups": {"git": {"commands": {"push": {"depends_on": ["commit"]}}}}}}

    # act / assert
    with pytest.raises(ValueError, match="declared as one kind of command and refined as another"):
        treeform.merge(KERNEL, product)
