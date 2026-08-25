"""The new-form command tree, lowered to the flat form the manifest model validates (netctl#1469).

AAA throughout. Every rejection has a negative test, because a rule that only ever runs on valid input
is a rule nobody has seen work.
"""
import pytest

from delivery.orchestrator.model import treeform


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


def test_a_non_mapping_group_node_in_lower_is_rejected():
    # arrange: a manifest typo that turns a group node into a scalar
    tree = {"build": "not-a-mapping"}

    # act / assert
    with pytest.raises(ValueError, match="is not a mapping"):
        treeform.lower(tree)


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


def test_a_non_mapping_group_node_in_merge_is_rejected():
    # arrange: a manifest typo that turns a group node into a scalar
    product = {"build": ["not", "a", "mapping"]}

    # act / assert
    with pytest.raises(ValueError, match="is not a mapping"):
        treeform.merge(KERNEL, product)


def test_an_unknown_key_on_a_group_node_in_merge_is_rejected():
    # arrange: a typo'd `helo:` would otherwise be copied through silently and render nowhere
    product = {"build": {"helo": "typo"}}

    # act / assert
    with pytest.raises(ValueError, match="unknown key"):
        treeform.merge(KERNEL, product)


CATALOGUE_TASKS = {"vcs:push": {"impl": "delivery.tasks.vcs:push", "help": "push it.",
                                "params": {"remote": {"help": "the remote"}}}}
PRODUCT_TASKS = {"lab-image": {"impl": "orchestrator.tooling:lab_image", "help": "build an image."}}


def test_a_coordinate_resolves_against_the_catalogue():
    # arrange
    flat = {"support.git": {"push": {"task": "vcs:push"}}}

    # act
    resolved = treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)

    # assert: impl and the template's help and params come along, and `task` is gone
    assert resolved["support.git"]["push"] == {
        "impl": "delivery.tasks.vcs:push", "help": "push it.",
        "params": {"remote": {"help": "the remote"}}}


def test_a_bare_name_resolves_against_the_product_and_the_command_keeps_its_own_help():
    # arrange: the instance's own wording wins over the template's (spec 3.7)
    flat = {"build": {"frr-image": {"task": "lab-image", "with": {"key": "frr"},
                                    "help": "Build the FRR lab node image."}}}

    # act
    resolved = treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)

    # assert
    assert resolved["build"]["frr-image"] == {
        "impl": "orchestrator.tooling:lab_image", "help": "Build the FRR lab node image.",
        "with": {"key": "frr"}}


def test_two_commands_may_instantiate_one_task():
    # arrange: the case netctl#1406 recorded as unmigratable - one coordinate, two commands
    flat = {"test": {"system": {"task": "gate", "with": {"name": "system"}},
                     "acceptance": {"task": "gate", "with": {"name": "acceptance"}}}}
    tasks = {"gate": {"impl": "delivery.tasks.testrun:gate", "help": "run a suite."}}

    # act
    resolved = treeform.resolve(flat, tasks, {})

    # assert
    assert resolved["test"]["system"]["with"] == {"name": "system"}
    assert resolved["test"]["acceptance"]["with"] == {"name": "acceptance"}
    assert {c["impl"] for c in resolved["test"].values()} == {"delivery.tasks.testrun:gate"}


def test_a_command_naming_a_task_that_does_not_exist_is_rejected():
    # arrange
    flat = {"build": {"frr-image": {"task": "lab-imag"}}}

    # act / assert
    with pytest.raises(ValueError, match="names no task"):
        treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)


def test_a_command_with_both_a_task_and_depends_on_is_rejected():
    # arrange
    flat = {"build": {"web-image": {"task": "lab-image", "depends_on": ["aot"]}}}

    # act / assert
    with pytest.raises(ValueError, match="both `task:` and `depends_on:`"):
        treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)


def test_a_command_with_neither_a_task_nor_depends_on_is_rejected():
    # arrange
    flat = {"build": {"web-image": {"help": "a command that runs nothing."}}}

    # act / assert
    with pytest.raises(ValueError, match="neither `task:` nor `depends_on:`"):
        treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)


def test_an_impl_inside_a_group_is_rejected():
    # arrange: the old form's leaf, written where a command now goes. Rejecting it is what makes the
    # migration a ratchet instead of two forms living side by side forever.
    flat = {"build": {"frr-image": {"impl": "orchestrator.cli:frr_image_cmd", "help": "h."}}}

    # act / assert
    with pytest.raises(ValueError, match="declares `impl:`"):
        treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)


def test_a_params_entry_for_a_pinned_parameter_is_rejected():
    # arrange: `with:` takes the parameter off the command line, so describing its presentation is a
    # declaration that renders nowhere - the failure this model exists to stop
    flat = {"test": {"system": {"task": "gate", "with": {"name": "system"},
                                "params": {"name": {"help": "the suite"}}}}}
    tasks = {"gate": {"impl": "delivery.tasks.testrun:gate", "help": "run a suite."}}

    # act / assert
    with pytest.raises(ValueError, match="pins .* with `with:`"):
        treeform.resolve(flat, tasks, {})


def test_a_block_whose_nodes_carry_node_keys_is_new_form():
    # arrange
    new = {"build": {"help": "Produce.", "commands": {"web-image": {"task": "img"}}}}

    # act / assert
    assert treeform.is_new_form(new) is True


def test_the_old_group_to_member_block_is_not_new_form():
    # arrange: the shape netctl.yaml carries today
    old = {"build": {"web-image": {"impl": "orchestrator.cli:web_image_cmd", "help": "h."}}}

    # act / assert
    assert treeform.is_new_form(old) is False


def test_an_empty_block_is_not_new_form():
    # arrange / act / assert: no nodes means nothing to detect, and the old path is the safe default
    assert treeform.is_new_form({}) is False


def test_an_import_section_in_a_new_form_manifest_is_rejected():
    # arrange: `import:` is the OLD form's way of making coordinates available. Left in a new-form
    # manifest it would be quietly ignored, which is how a product ends up believing it imported
    # something. Loud beats ignored.
    with pytest.raises(ValueError, match="`import:` has no meaning"):
        treeform.check_no_stale_import({"import": {"delivery": ["vcs"]}})


def test_a_new_form_manifest_without_an_import_section_passes_the_check():
    # arrange / act / assert: no exception
    treeform.check_no_stale_import({"product": "demo", "groups": {}})


def test_a_product_task_no_command_instantiates_is_rejected():
    # arrange: a template nobody uses is a dead declaration
    flat = {"build": {"frr-image": {"task": "lab-image"}}}
    tasks = {"lab-image": {"impl": "a:b", "help": "h."}, "orphan": {"impl": "c:d", "help": "h."}}

    # act / assert
    with pytest.raises(ValueError, match="no command instantiates"):
        treeform.check_every_task_is_used(flat, tasks)


def test_every_instantiated_product_task_passes_the_check():
    # arrange
    flat = {"build": {"frr-image": {"task": "lab-image"}, "web-image": {"depends_on": ["aot"]}}}
    tasks = {"lab-image": {"impl": "a:b", "help": "h."}}

    # act / assert: no exception
    treeform.check_every_task_is_used(flat, tasks)
