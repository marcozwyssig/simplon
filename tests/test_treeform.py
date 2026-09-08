"""The new-form command tree, lowered to the flat form the manifest model validates (netctl#1469).

AAA throughout. Every rejection has a negative test, because a rule that only ever runs on valid input
is a rule nobody has seen work.
"""
import textwrap

import pytest
import yaml

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest
from simplon.orchestrator.model import treeform


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


def test_an_unknown_key_on_a_group_node_in_lower_is_rejected():
    # arrange: the kernel's OWN tree, which only `lower` ever walks directly when a product has not
    # migrated - a `commmands:` typo here used to be copied through silently, dropping every baseline
    # command in every product with no gate ever seeing it
    tree = {"build": {"help": "Produce.", "commmands": {}}}

    # act / assert
    with pytest.raises(ValueError, match="unknown key"):
        treeform.lower(tree)


def test_a_product_overriding_env_first_on_a_platform_group_is_rejected():
    # arrange: switching the platform's env-first gate off from a product manifest would ungate every
    # descendant command silently
    product = {"support": {"env_first": False}}

    # act / assert
    with pytest.raises(ValueError, match="which the platform's node already sets"):
        treeform.merge(KERNEL, product)


def test_a_product_overriding_help_on_a_platform_group_is_rejected():
    # arrange: the same rule for `help:` - a group's own attributes are the platform's shape, not a
    # product's to rewrite
    product = {"build": {"help": "my own wording"}}

    # act / assert
    with pytest.raises(ValueError, match="which the platform's node already sets"):
        treeform.merge(KERNEL, product)


def test_a_kernel_only_group_the_product_never_touches_stays_in_the_merged_tree():
    # arrange: `release`/`monitor` in the real catalogue are exactly this shape - a bare `{help: ...}`
    # node with no commands, that a product simply never places anything into (defect 1, first half).
    # `merge` itself keeps it (see its docstring): whether it RENDERS is `load()`'s call, made with
    # `declared_paths` plus the OLD-form half of the manifest that `merge` never sees at all.
    kernel = {**KERNEL, "release": {"help": "Publish them."}}
    product = {"build": {"commands": {"web-image": {"task": "img"}}}}

    # act
    merged = treeform.merge(kernel, product)

    # assert
    assert merged["release"] == {"help": "Publish them."}
    assert "build" in merged and "support" in merged


def test_declared_paths_names_every_path_a_tree_declares_regardless_of_content():
    # arrange: the product's OWN (un-merged) tree - the set `load()` uses to tell "the product named
    # this and it is empty" (a load error, raised by `merge`) apart from "the product never named this"
    # (a silent drop, decided in `load()`)
    tree = {"build": {"commands": {"web-image": {"task": "img"}}},
           "support": {"groups": {"git": {"commands": {"push": {"task": "vcs:push"}}}}}}

    # act
    paths = treeform.declared_paths(tree)

    # assert: every level the tree names, bare and nested alike
    assert paths == {"build", "support", "support.git"}


def test_declared_paths_of_an_empty_tree_is_empty():
    # arrange / act / assert: nothing named, nothing declared - the safe default for a manifest with no
    # new-form groups at all
    assert treeform.declared_paths({}) == frozenset()


def test_a_product_declared_group_left_with_no_commands_is_rejected():
    # arrange: the SAME empty shape, but this time the PRODUCT names the group itself - an announcement
    # with nothing behind it, which is a load error rather than a silent drop (defect 1, second half)
    kernel = {**KERNEL, "release": {"help": "Publish them."}}
    product = {"release": {}}

    # act / assert
    with pytest.raises(ValueError, match="declares no commands"):
        treeform.merge(kernel, product)


def test_a_product_declared_nested_group_left_with_no_commands_is_rejected():
    # arrange: the same rule one level down - a product naming a subgroup it never fills
    kernel = {**KERNEL, "support": {**KERNEL["support"],
                                    "groups": {**KERNEL["support"]["groups"], "empty-sub": {}}}}
    product = {"support": {"groups": {"empty-sub": {}}}}

    # act / assert
    with pytest.raises(ValueError, match="support.empty-sub.*declares no commands"):
        treeform.merge(kernel, product)


def test_a_non_mapping_command_spec_in_merge_is_rejected():
    # arrange: a `task:` string written where the whole command mapping belongs - the realistic typo is
    # `commands: { push: "vcs:push" }` instead of `commands: { push: { task: "vcs:push" } }`
    product = {"build": {"commands": {"web-image": "vcs:push"}}}

    # act / assert
    with pytest.raises(ValueError, match="is not a mapping"):
        treeform.merge(KERNEL, product)


CATALOGUE_TASKS = {"vcs:push": {"impl": "simplon.tasks.vcs:push", "help": "push it.",
                                "params": {"remote": {"help": "the remote"}}}}
PRODUCT_TASKS = {"lab-image": {"impl": "orchestrator.tooling:lab_image", "help": "build an image."}}


def test_a_coordinate_resolves_against_the_catalogue():
    # arrange
    flat = {"support.git": {"push": {"task": "vcs:push"}}}

    # act
    resolved = treeform.resolve(flat, PRODUCT_TASKS, CATALOGUE_TASKS)

    # assert: impl and the template's help and params come along, and `task` is gone
    assert resolved["support.git"]["push"] == {
        "impl": "simplon.tasks.vcs:push", "help": "push it.",
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
    tasks = {"gate": {"impl": "simplon.tasks.testrun:gate", "help": "run a suite."}}

    # act
    resolved = treeform.resolve(flat, tasks, {})

    # assert
    assert resolved["test"]["system"]["with"] == {"name": "system"}
    assert resolved["test"]["acceptance"]["with"] == {"name": "acceptance"}
    assert {c["impl"] for c in resolved["test"].values()} == {"simplon.tasks.testrun:gate"}


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
    tasks = {"gate": {"impl": "simplon.tasks.testrun:gate", "help": "run a suite."}}

    # act / assert
    with pytest.raises(ValueError, match="pins .* with `with:`"):
        treeform.resolve(flat, tasks, {})


def test_a_command_pinning_a_parameter_the_template_declares_loads():
    # arrange: the design's own canonical `lab-image` shape (spec 3.7) - the TASK declares `key` and
    # `dockerfile`, and every command instantiating it pins both with `with:`. The earlier conflict check
    # intersected against the merged template+command map and rejected exactly this
    flat = {"build": {"frr-image": {"task": "lab-image", "with": {"key": "frr", "dockerfile": "Frr"}}}}
    tasks = {"lab-image": {"impl": "orchestrator.tooling:lab_image", "help": "build an image.",
                           "params": {"key": {"help": "the image key"},
                                      "dockerfile": {"help": "the Dockerfile"}}}}

    # act
    resolved = treeform.resolve(flat, tasks, {})

    # assert: both pinned keys are gone from `with:`'s target - no presentation renders for a value the
    # command line never shows
    assert resolved["build"]["frr-image"] == {
        "impl": "orchestrator.tooling:lab_image", "help": "build an image.",
        "with": {"key": "frr", "dockerfile": "Frr"}}


def test_one_command_pins_a_template_parameter_and_another_leaves_it_documented():
    # arrange: the mixed case the earlier check made unrepresentable - one instance pins `key`, another
    # leaves it on the command line and keeps the template's documentation for it
    flat = {"build": {"frr-image": {"task": "lab-image", "with": {"key": "frr"}},
                      "generic-image": {"task": "lab-image"}}}
    tasks = {"lab-image": {"impl": "orchestrator.tooling:lab_image", "help": "build an image.",
                           "params": {"key": {"help": "the image key"}}}}

    # act
    resolved = treeform.resolve(flat, tasks, {})

    # assert
    assert "params" not in resolved["build"]["frr-image"]
    assert resolved["build"]["generic-image"]["params"] == {"key": {"help": "the image key"}}


def test_a_command_params_entry_for_a_parameter_it_also_pins_itself_is_still_rejected():
    # arrange: the check narrows to the command's OWN `params:`, so a command declaring both for the SAME
    # key must still fail - only the template/command split changed, not this rule
    flat = {"build": {"frr-image": {"task": "lab-image", "with": {"key": "frr"},
                                    "params": {"key": {"help": "own wording"}}}}}
    tasks = {"lab-image": {"impl": "orchestrator.tooling:lab_image", "help": "build an image."}}

    # act / assert
    with pytest.raises(ValueError, match="pins .* with `with:`"):
        treeform.resolve(flat, tasks, {})


def test_a_non_mapping_with_block_is_rejected():
    # arrange: `with:` given as a list instead of a mapping - would otherwise compute a nonsense pin set
    # from the list's elements rather than failing where the mistake is
    flat = {"build": {"frr-image": {"task": "lab-image", "with": ["key", "frr"]}}}
    tasks = {"lab-image": {"impl": "orchestrator.tooling:lab_image", "help": "build an image."}}

    # act / assert
    with pytest.raises(ValueError, match="`with:` as list, not a mapping"):
        treeform.resolve(flat, tasks, {})


def test_a_block_with_both_forms_names_only_the_flat_group():
    # arrange: the shape a half-migrated product had for exactly as long as the migration took. Naming
    # only the flat half is the whole point - the message has to say WHICH group to rewrite, not that
    # the file is wrong somewhere.
    groups = {"build": {"commands": {"web-image": {"task": "img"}}},
              "test":  {"unit-java": {"impl": "orchestrator.cli:unit_java", "help": "h."}}}

    # act
    flat = treeform.old_form_groups(groups)

    # assert
    assert set(flat) == {"test"}


def test_a_wholly_flat_block_is_flat_throughout():
    # arrange
    groups = {"test": {"unit-java": {"impl": "a:b", "help": "h."}}}

    # act / assert
    assert set(treeform.old_form_groups(groups)) == {"test"}


def test_a_mixed_manifest_loads_both_halves(tmp_path):
    # arrange: the migration's central claim - a converted group and an unconverted one coexist
    catalogue = catalogue_mod.loads(textwrap.dedent("""
        tasks:
          vcs:push: { impl: simplon.tasks.vcs:push, help: "push it." }
        groups:
          build: { help: "Produce the artefacts." }
          test:  { help: "Verify them." }
    """))
    text = textwrap.dedent("""
        product: demo
        tasks:
          img: { impl: "demo.tooling:image", help: "Build an image." }
          unit-java: { impl: "demo.cli:unit_java", help: "Run the Java unit gate." }

        groups:
          build:
            commands:
              web-image: { task: "img", with: { key: "web" }, help: "Build the web image." }
          test:
            commands:
              unit-java: { task: "unit-java" }
    """)

    # act
    mf = manifest.load(text, catalogue=catalogue)

    # assert: both groups carry their member, and each resolved through its own path
    assert mf.commands["build"]["web-image"].impl == "demo.tooling:image"
    assert mf.commands["test"]["unit-java"].impl == "demo.cli:unit_java"


def test_a_catalogue_group_the_product_never_fills_does_not_render(tmp_path):
    # arrange: the agile-cockpit shape (defect 1) - a tree-form manifest that uses `build` and `test` but
    # never mentions `release`, exactly like the real catalogue's bare CI/CD groups
    catalogue = catalogue_mod.loads(textwrap.dedent("""
        tasks: {}
        groups:
          build:   { help: "Produce the artefacts." }
          test:    { help: "Verify them." }
          release: { help: "Publish them." }
    """))
    text = textwrap.dedent("""
        product: demo
        tasks:
          img: { impl: "demo.tooling:image", help: "Build an image." }
        groups:
          build:
            commands:
              web-image: { task: img, help: "Build the web image." }
          test:
            commands:
              unit: { task: img, help: "Run the unit gate." }
    """)

    # act
    mf = manifest.load(text, catalogue=catalogue)

    # assert: the untouched catalogue group is gone from the assembled surface, the used ones are not
    assert "release" not in mf.groups
    assert set(mf.groups) == {"build", "test"}


def test_a_catalogue_group_the_product_fills_old_form_still_renders_even_though_new_form_never_touches_it(
        tmp_path):
    # arrange: the exact regression the naive "prune inside merge()" fix produced - `test` looks
    # untouched from the NEW-form side (this manifest's `test:` is still old-form), but the product DOES
    # fill it, just through the other half of a still-migrating manifest. It must render, and the
    # catalogue's ownership check must still recognise it as a real group (not "unknown group 'test'")
    catalogue = catalogue_mod.loads(textwrap.dedent("""
        tasks: {}
        groups:
          build: { help: "Produce the artefacts." }
          test:  { help: "Verify them." }
    """))
    text = textwrap.dedent("""
        product: demo
        tasks:
          img: { impl: "demo.tooling:image", help: "Build an image." }
          unit-java: { impl: "demo.cli:unit_java", help: "Run the Java unit gate." }

        groups:
          build:
            commands:
              web-image: { task: "img", help: "Build the web image." }
          test:
            commands:
              unit-java: { task: "unit-java" }
    """)

    # act
    mf = manifest.load(text, catalogue=catalogue)

    # assert
    assert mf.groups["test"] == ("unit-java",)


def test_a_product_adding_to_a_group_the_platform_already_placed_a_command_in_keeps_both():
    # arrange: `merge` seeds its output from EVERY catalogue group, so `test` arrives already carrying
    # the platform's own `unit-py` - and this product adds `unit-java` beside it. Neither side may
    # vanish: with the flat form gone there is no second declaration of a group that could shadow the
    # first, and this pins the union rather than a winner.
    catalogue = catalogue_mod.loads(textwrap.dedent("""
        tasks:
          test:unit-py: { impl: "simplon.tasks.x:y", help: "run the python gate." }
        groups:
          build: { help: "Produce the artefacts." }
          test:  { help: "Verify them.", commands: { unit-py: { task: "test:unit-py", help: "run it." } } }
    """))
    text = textwrap.dedent("""
        product: demo
        tasks:
          img: { impl: "demo.tooling:image", help: "Build an image." }
          unit-java: { impl: "demo.cli:unit_java", help: "Run the Java unit gate." }

        groups:
          build:
            commands:
              web-image: { task: "img", help: "Build the web image." }
          test:
            commands:
              unit-java: { task: "unit-java" }
    """)

    # act
    mf = manifest.load(text, catalogue=catalogue)

    # assert
    assert set(mf.groups["test"]) == {"unit-py", "unit-java"}


# --- one command name, one or two bodies (netctl's silent oras-vs-Colima `support install`) ---------------

def _support_install_catalogue():
    """A minimal catalogue that PLACES `support install`, the way `simplon.catalogue.yaml` has since
    0.1.4 - just enough tree for the collision/refinement/override tests below."""
    return catalogue_mod.loads(textwrap.dedent("""
        tasks:
          support:install: { impl: "simplon.tasks.hosttools:install", help: "Provision oras." }
        groups:
          support:
            help: "Host tooling."
            commands:
              install: { task: "support:install" }
    """))


def test_a_product_command_that_points_a_placed_name_at_a_different_task_is_rejected():
    # arrange: netctl's own `support install` names a DIFFERENT body (its own Colima/containerlab
    # provisioning) than the one the catalogue already placed there (oras) - two bodies, one name, no
    # `override:` opt-in. Silently picking either would be exactly netctl's reported defect.
    catalogue = _support_install_catalogue()
    text = textwrap.dedent("""
        product: netctl
        tasks:
          install: { impl: "orchestrator.cli:install", help: "Provision Colima and containerlab." }
        groups:
          support:
            commands:
              install: { task: install, help: "Provision Colima and containerlab." }
    """)

    # act / assert: the message must name BOTH bodies by their real `module:function` - `install` and
    # `install` look identical, only `simplon.tasks.hosttools:install` and `orchestrator.cli:install` show
    # a human what they would be choosing between
    with pytest.raises(ValueError, match=(r"redeclares `task:`.*"
                                          r"simplon\.tasks\.hosttools:install.*"
                                          r"orchestrator\.cli:install.*"
                                          r"override: true")):
        manifest.load(text, catalogue=catalogue)


def test_a_product_refining_help_and_params_on_a_placed_command_stays_silent():
    # arrange: same `task:` the catalogue already placed - this is a REFINEMENT (its own help text),
    # not a second body, so it must keep resolving with no error and no `override:` needed.
    catalogue = _support_install_catalogue()
    text = textwrap.dedent("""
        product: netctl
        groups:
          support:
            commands:
              install: { task: "support:install", help: "Provision the host tools this product needs." }
    """)

    # act
    mf = manifest.load(text, catalogue=catalogue)

    # assert: the catalogue's body runs, under the product's own wording
    spec = mf.commands["support"]["install"]
    assert spec.impl == "simplon.tasks.hosttools:install"
    assert spec.help == "Provision the host tools this product needs."


def test_a_product_command_with_explicit_override_replaces_the_placed_task_silently():
    # arrange: the same collision as the rejection test above, but with the opt-in the error message
    # names - the product's body must now win, cleanly (not merged with the catalogue's own help/params).
    catalogue = _support_install_catalogue()
    text = textwrap.dedent("""
        product: netctl
        tasks:
          install: { impl: "orchestrator.cli:install", help: "Provision Colima and containerlab." }
        groups:
          support:
            commands:
              install: { task: install, override: true, help: "Provision Colima and containerlab." }
    """)

    # act
    mf = manifest.load(text, catalogue=catalogue)

    # assert
    spec = mf.commands["support"]["install"]
    assert spec.impl == "orchestrator.cli:install"
    assert spec.help == "Provision Colima and containerlab."


TASK_KEYS_OK = {"impl": "a:b", "help": "h.", "passthrough_args": True, "params": {"x": {"help": "y"}}}


def test_a_task_declaring_every_allowed_key_is_accepted():
    # arrange / act / assert: no exception
    treeform.check_task("lab-image", TASK_KEYS_OK)


def test_a_task_without_an_impl_is_rejected_by_name():
    # arrange: today this dies as a bare KeyError deep inside resolve()
    with pytest.raises(ValueError, match="declares no `impl:`"):
        treeform.check_task("lab-image", {"help": "h."})


def test_a_task_declaring_a_command_only_key_is_rejected():
    # arrange: `hidden` is a real _CommandSpecModel key and reads as plausible on a template, which is
    # exactly why silently dropping it is worse than refusing it
    with pytest.raises(ValueError, match="belongs on a command"):
        treeform.check_task("lab-image", {"impl": "a:b", "help": "h.", "hidden": True})


def test_a_task_declaring_an_unknown_key_is_rejected():
    # arrange
    with pytest.raises(ValueError, match="unknown key"):
        treeform.check_task("lab-image", {"impl": "a:b", "help": "h.", "helo": "typo"})


def test_a_node_carrying_node_keys_is_not_the_flat_form():
    # arrange
    tree = {"build": {"help": "Produce.", "commands": {"web-image": {"task": "img"}}}}

    # act / assert
    assert treeform.old_form_groups(tree) == {}


def test_a_group_to_member_block_is_the_flat_form():
    # arrange: the shape every product carried before the tree
    flat = {"build": {"web-image": {"impl": "orchestrator.cli:web_image_cmd", "help": "h."}}}

    # act / assert
    assert set(treeform.old_form_groups(flat)) == {"build"}


def test_an_empty_block_is_not_the_flat_form():
    # arrange / act / assert: no nodes means nothing to name, and a group declared with nothing in it is
    # `merge`'s error to report, by name - not this one's
    assert treeform.old_form_groups({}) == {}
    assert treeform.old_form_groups({"build": {}}) == {}


def test_an_import_section_is_rejected():
    # arrange: `import:` is the OLD form's way of making coordinates available. Left in a manifest it
    # would be quietly ignored, which is how a product ends up believing it imported something. Loud
    # beats ignored.
    with pytest.raises(ValueError, match="`import:` has nothing left to do"):
        treeform.check_no_old_form({"import": {"delivery": ["vcs"]}})


def test_a_tree_form_manifest_passes_the_flat_form_check():
    # arrange / act / assert: no exception
    treeform.check_no_old_form({"product": "demo", "groups": {}})
    treeform.check_no_old_form({"product": "demo",
                                "tasks": {"img": {"impl": "a:b", "help": "h."}},
                                "groups": {"build": {"commands": {"img": {"task": "img"}}}}})


def test_a_declared_task_no_command_places_is_accepted():
    """si#53 struck `check_every_task_is_used`, and this is the assertion the deletion is worth.

    The rule refused a `tasks:` entry no command instantiated. It was the ONE expression rule the kernel
    exempted itself from, because its own catalogue declares far more than it places - a task needing
    product data must not become a baseline command that dies on its first line - and si#48 measured the
    exemption at 14 of 22. Over every reachable manifest - this kernel's own and the five in
    `surface.CONSUMERS` - it had refused nothing, ever.

    What has to be true now is not "the function is gone" but that an ORPHAN TASK LOADS, which is the
    capability the rule took away. Asserted through `load()` rather than through the deleted helper,
    because a test that names the helper would pass by import error rather than by behaviour.
    """
    # arrange: a manifest declaring two tasks and placing exactly one of them
    from simplon.orchestrator import manifest as manifest_mod
    text = """
product: demo
tasks:
  placed: { impl: "simplon.tasks.docs:site", help: "Placed." }
  offered: { impl: "simplon.tasks.docs:site", help: "Declared and not placed - an offer." }
groups:
  build:
    commands:
      placed: { task: "placed", help: "The one command." }
"""

    # act
    loaded = manifest_mod.load(text)

    # assert: it loaded, and the unplaced task really was in the manifest that loaded
    assert loaded.commands["build"]["placed"].impl == "simplon.tasks.docs:site"
    assert "offered" not in loaded.commands.get("build", {})
    assert not hasattr(treeform, "check_every_task_is_used")


# --- the flat form is gone, and the refusal shows the way out (si#33) ----------------------------------
#
# Acceptance 4/5 of si#33: a manifest still written the old way must fail with a message that shows the
# REWRITE, not merely "no longer supported". Whoever has such a product has to be able to convert it
# without guessing at a shape nobody can read out of the code any more.
#
# The manifest below is not an illustration. It is simplon's OWN `simplon.yaml` as it stood at 0.3.0 -
# flat groups, `import:`, and coordinate-keyed `tasks:` entries all three - which is what makes these
# tests a measurement rather than a restatement of the renderer.

_REAL_OLD_MANIFEST = """
product: simplon
default: dev

groups:
  build:
    wheel:
      help: "Build the wheel."
      impl: "orchestrator.cli:build_wheel"
    docs:
      help: "Write the command reference, then build the website from it."
      depends_on: [reference, site]
  test:
    all:
      help: "Run every test."
      impl: "orchestrator.cli:test_all"
  support:
    doctor:
      help: "Check the tools and the environment."
      impl: "orchestrator.cli:doctor"

import:
  delivery: [docs, test, release]
tasks:
  docs:reference:
    group: build
    with:
      output: site/content/using/commands.md
      title: "Command reference"
  docs:site:
    group: build
  test:typecheck-python:
    group: test
  release:tag:
    group: release

site:
  image: "hugomods/hugo:exts-0.148.2"
  source: "site"
  output: "build/website"
  base_url: "https://marcozwyssig.github.io/simplon/"
  theme: "github.com/imfing/hextra@v0.12.3"
"""


def _rewritten(text: str) -> str:
    """`text` with its `tasks:`/`groups:`/`import:` sections replaced by the rewrite the refusal prints.

    Exactly the edit the message asks a human to make: keep everything else, paste the block over those
    sections. Done here through the parsed document so the test is doing the pasting rather than
    re-implementing the renderer.
    """
    data = yaml.safe_load(text)
    rest = {key: value for key, value in data.items() if key not in ("tasks", "groups", "import")}
    return yaml.safe_dump(rest, sort_keys=False) + "\n" + treeform.rewrite_of_old_form(data)


def test_a_real_old_manifest_is_refused_and_the_message_names_every_flat_section():
    # arrange: all three flat shapes at once, which is the realistic case - a product that wrote `impl:`
    # on a command also placed its catalogue tasks the old way. Reporting one per load would be three
    # guessing games instead of none.
    # act
    with pytest.raises(ValueError) as exc:
        manifest.load(_REAL_OLD_MANIFEST, catalogue=catalogue_mod.load())

    # assert
    message = str(exc.value)
    assert "no longer loads" in message
    assert "'build'" in message and "'test'" in message and "'support'" in message
    assert "keyed by a platform coordinate" in message
    assert "`import:`" in message


def test_the_refusal_shows_the_rewrite_and_not_only_that_the_form_is_gone():
    # arrange / act
    with pytest.raises(ValueError) as exc:
        manifest.load(_REAL_OLD_MANIFEST, catalogue=catalogue_mod.load())
    message = str(exc.value)

    # assert: the product's OWN names, in the shape they have to take - the body moved under `tasks:`,
    # the command pointing at it, and the catalogue coordinate named rather than copied
    assert 'wheel: { impl: "orchestrator.cli:build_wheel", help: "Build the wheel." }' in message
    assert 'wheel: { task: "wheel" }' in message
    assert 'site: { task: "docs:site" }' in message
    # the aggregate was never a body, so it crosses unchanged
    assert 'depends_on: ["reference", "site"]' in message


def test_the_rewrite_the_refusal_prints_is_itself_a_manifest_that_loads():
    """The whole claim, measured: a message that shows a rewrite nobody can load is a message that
    reads well and helps nobody. Pasting the block over the sections it names has to produce a manifest
    that assembles the SAME CLI - which is also what proves the rewrite lost nothing on the way."""
    # arrange
    rewritten = _rewritten(_REAL_OLD_MANIFEST)

    # act
    mf = manifest.load(rewritten, catalogue=catalogue_mod.load())

    # assert: every command the old manifest declared, in the group it declared it in
    assert set(mf.groups["build"]) == {"wheel", "docs", "reference", "site"}
    assert set(mf.groups["test"]) == {"all", "typecheck-python"}
    assert mf.groups["support"][-1] == "doctor"
    assert mf.groups["release"] == ("tag",)
    # the bodies survived the move from the command to the task
    assert mf.spec_for("build", "wheel").impl == "orchestrator.cli:build_wheel"
    assert mf.spec_for("build", "site").impl == "simplon.tasks.site:build"
    assert mf.spec_for("build", "docs").depends_on == ("reference", "site")
    # and so did the pinned values, which is where a rewrite would most easily lose something
    assert mf.spec_for("build", "reference").with_["output"] == "site/content/using/commands.md"


def test_two_commands_sharing_one_body_become_one_task_with_two_placements():
    # arrange: the flat form spelled a shared body twice, so a rewrite that copied it would carry the
    # duplication into the shape whose entire point is that a body is written down once
    data = {"groups": {"test": {
        "unit":   {"impl": "demo.gates:gate", "help": "Run a suite."},
        "system": {"impl": "demo.gates:gate", "help": "Run a suite."},
    }}}

    # act
    rewrite = treeform.rewrite_of_old_form(data)

    # assert: ONE task, two commands pointing at it
    assert rewrite.count('impl: "demo.gates:gate"') == 1
    assert 'unit: { task: "unit" }' in rewrite
    assert 'system: { task: "unit" }' in rewrite


def test_a_command_name_already_taken_by_a_different_body_is_qualified_rather_than_shadowed():
    # arrange: `build build` and `deploy build` are two different bodies under one command name, which
    # is legal in a tree and impossible in one flat `tasks:` block - so the rewrite has to rename one,
    # or it prints a block that does not load
    data = {"groups": {
        "build":  {"build": {"impl": "demo.cli:build", "help": "Build."}},
        "deploy": {"build": {"impl": "demo.cli:rebuild", "help": "Rebuild in place."}},
    }}

    # act
    rewrite = treeform.rewrite_of_old_form(data)

    # assert: both bodies survive under distinct task names, and both commands keep the name they had
    assert 'build: { impl: "demo.cli:build", help: "Build." }' in rewrite
    assert 'deploy-build: { impl: "demo.cli:rebuild", help: "Rebuild in place." }' in rewrite
    assert 'build: { task: "build" }' in rewrite
    assert 'build: { task: "deploy-build" }' in rewrite


def test_a_manifest_part_way_through_the_migration_gets_a_rewrite_of_the_whole_block():
    # arrange: one group converted, one not. A rewrite of only the flat half is a block that SILENTLY
    # DROPS the converted one the moment it is pasted over `groups:`.
    data = {"tasks": {"img": {"impl": "demo.tooling:image", "help": "Build an image."}},
            "groups": {"build": {"commands": {"web-image": {"task": "img"}}},
                       "test":  {"unit": {"impl": "demo.cli:unit", "help": "Run the unit gate."}}}}

    # act
    rewrite = treeform.rewrite_of_old_form(data)

    # assert: the already-converted group and its task come through untouched, beside the converted one
    assert 'img: { impl: "demo.tooling:image", help: "Build an image." }' in rewrite
    assert 'web-image: { task: "img" }' in rewrite
    assert 'unit: { task: "unit" }' in rewrite


# --- the printed rewrite loads where the catalogue places the same name (si#42) ------------------------
#
# The rewrite exists so nobody with an old manifest has to GUESS. A block that loads in three cases of
# four and asks for a second round in the fourth solves the task three quarters of the way - and the
# names it failed on were the commonest ones, `support install` above all, in the catalogue since 0.1.7.
#
# So every green below is the SHARPER probe: not "the printed text mentions override" but the printed
# text, pasted in and LOADED, with the product's own body proved to be the one that runs.

#: A catalogue that places `release tag`, which the SHIPPED one no longer does (si#39 unplaced it: a
#: command that publishes must not arrive in every product unasked). The review found `release tag` as
#: one of the three cases, so it is covered here against a catalogue that still places it - the rule is
#: about what a catalogue places, not about which names today's catalogue happens to hold.
_PLACES_RELEASE_TAG = """
groups:
  release:
    help: "Publish them."
    commands:
      tag: { task: "release:tag" }
tasks:
  release:tag: { impl: "simplon.tasks.release:tag", help: "Cut the tag." }
"""

_OLD_SUPPORT_INSTALL = """
groups:
  support:
    install: { impl: "orchestrator.cli:install", help: "install our stuff" }
"""

_OLD_RELEASE_TAG = """
groups:
  release:
    tag: { impl: "orchestrator.cli:tag", help: "cut our tag" }
"""

_OLD_FLAT_SUPPORT_GIT = """
groups:
  support.git:
    commit: { impl: "orchestrator.cli:commit", help: "commit it our way" }
"""


def _refused_rewrite(text: str, cat) -> str:
    """The rewrite the refusal prints for `text`, taken out of the refusal itself.

    Out of the MESSAGE rather than off `rewrite_of_old_form` directly, because the claim under test is
    about what a human is handed, and a test that called the renderer would prove the renderer agrees
    with itself while the loader printed something else.
    """
    with pytest.raises(ValueError) as exc:
        manifest.load(text, catalogue=cat)
    message = str(exc.value)
    body = message.split("Rewrite those sections as:\n\n", 1)[1].split("\n\n  - ", 1)[0]
    return textwrap.dedent(body)


def test_the_rewrite_carries_override_where_the_catalogue_places_the_same_name():
    # arrange: `support install` is the commonest case - the catalogue has placed it since 0.1.7
    cat = catalogue_mod.load()

    # act
    rewrite = _refused_rewrite(_OLD_SUPPORT_INSTALL, cat)

    # assert: next to the `task:`, which is where the merge's own refusal tells a reader to put it
    assert 'install: { task: "install", override: true }' in rewrite


def test_the_printed_rewrite_of_support_install_loads_without_a_second_round():
    # arrange
    cat = catalogue_mod.load()
    rewrite = _refused_rewrite(_OLD_SUPPORT_INSTALL, cat)

    # act
    mf = manifest.load(rewrite, catalogue=cat)

    # assert: it loads, and the body that runs is the PRODUCT's - an override that loaded while leaving
    # the platform's body in place would be the silent choice the merge refuses to make
    assert mf.spec_for("support", "install").impl == "orchestrator.cli:install"


def test_the_printed_rewrite_of_release_tag_loads_without_a_second_round():
    # arrange: against a catalogue that places `release tag` (see _PLACES_RELEASE_TAG)
    cat = catalogue_mod.loads(_PLACES_RELEASE_TAG)
    rewrite = _refused_rewrite(_OLD_RELEASE_TAG, cat)

    # act
    mf = manifest.load(rewrite, catalogue=cat)

    # assert
    assert 'tag: { task: "tag", override: true }' in rewrite
    assert mf.spec_for("release", "tag").impl == "orchestrator.cli:tag"


def test_the_printed_rewrite_of_a_flat_nested_group_loads_without_a_second_round():
    # arrange: the dotted flat key `support.git`, whose members the catalogue places one level down
    cat = catalogue_mod.load()
    rewrite = _refused_rewrite(_OLD_FLAT_SUPPORT_GIT, cat)

    # act
    mf = manifest.load(rewrite, catalogue=cat)

    # assert: the override reached the NESTED node, not the `support` level it was written flat under
    assert 'commit: { task: "commit", override: true }' in rewrite
    assert mf.spec_for("support.git", "commit").impl == "orchestrator.cli:commit"


def test_every_name_the_shipped_catalogue_places_rewrites_into_a_manifest_that_loads():
    """The three review cases are the ones that were MEASURED; this is the rule they are cases of.

    Derived from the catalogue rather than listed, so a command placed there tomorrow is covered the day
    it is placed instead of the day somebody remembers this file. The count is asserted for the reason
    si#34's placement count is: a loop over an empty set is as green as a loop over eight.
    """
    # arrange: one old-form manifest per placed name, each colliding with the catalogue's own body
    cat = catalogue_mod.load()
    placed = treeform.placed_commands(cat.groups)
    cases = {f"{'.'.join(path)} {command}": (path, command)
             for path, commands in placed.items() for command in commands}

    # act / assert
    for label, (path, command) in cases.items():
        text = yaml.safe_dump(
            {"groups": {".".join(path): {command: {"impl": f"orchestrator.cli:{command}",
                                                   "help": f"our own {command}"}}}},
            sort_keys=False)
        rewrite = _refused_rewrite(text, cat)
        mf = manifest.load(rewrite, catalogue=cat)
        assert mf.spec_for(".".join(path), command).impl == f"orchestrator.cli:{command}", label
    assert len(cases) >= 8


def test_a_name_the_catalogue_does_not_place_gets_no_override():
    # arrange: `release tag` against the SHIPPED catalogue, which does not place it (si#39). An
    # `override: true` printed where nothing is being overridden is a second kind of noise - it would
    # tell a reader the platform has a body here when it has none.
    cat = catalogue_mod.load()

    # act
    rewrite = _refused_rewrite(_OLD_RELEASE_TAG, cat)

    # assert
    assert 'tag: { task: "tag" }' in rewrite
    assert "override" not in rewrite
    assert manifest.load(rewrite, catalogue=cat).spec_for("release", "tag").impl == "orchestrator.cli:tag"


def test_a_placement_that_names_the_platforms_own_body_is_a_refinement_and_gets_no_override():
    # arrange: the old way of placing a PLATFORM task - a coordinate-keyed `tasks:` entry with `group:`.
    # It rewrites to the same `task:` the catalogue already places there, which is a refinement of the
    # platform's command and not a replacement of it.
    cat = catalogue_mod.load()
    text = """
tasks:
  support:install:
    group: support
"""

    # act
    rewrite = _refused_rewrite(text, cat)

    # assert
    assert 'install: { task: "support:install" }' in rewrite
    assert "override" not in rewrite
    assert manifest.load(rewrite, catalogue=cat).spec_for("support", "install").impl \
        == "simplon.tasks.hosttools:install"


# --- the rewrite is of the STRUCTURE, and the refusal says so (si#56) ----------------------------------
#
# Found on a consumer's 0.4.0 migration: the printed block is correct, loads in one round, and carries
# NOTHING of the roughly forty comment lines their manifest used to explain why things stood where they
# stood. Pasting it would have been green and the reasoning gone. They kept it only because they looked.
#
# It is the recurring defect in the one tool built against it - an outcome that cannot tell "migrated"
# from "migrated and lost the reasons" - so the fix is at the seam where somebody acts: the terminal
# message, which knows the manifest's own lines and can say which case this reader is in.
#
# The two manifests below are the SAME manifest. `_REAL_OLD_MANIFEST` is simplon's own `simplon.yaml` at
# 0.3.0 with its comments stripped; the one here restores them, shortened but in the places they really
# stood (`git show v0.3.0:simplon.yaml`). Same parse, same rewrite, and only one of them has anything to
# lose - which is the whole property under test.

_REAL_OLD_MANIFEST_COMMENTED = """
# Simplon builds and tests itself with itself. The very kernel built here
# assembles this CLI from this manifest -- if a commit breaks the assembly,
# it fails in the same round instead of after a release.
product: simplon
default: dev

# NOTE: no `commands:` nesting under each group. That shape is the loader's "new form", reserved for a
# command that INSTANTIATES a task declared under `tasks:`, so this stays the flat "old form".
groups:
  build:
    wheel:
      help: "Build the wheel."
      impl: "orchestrator.cli:build_wheel"
    # The documentation website, as ONE command, and an impl-less AGGREGATE rather than a leaf (#2,
    # task 3). `reference` WRITES the page `site` READS, so the order is not a preference - run them
    # the other way round and the published site carries the previous run's reference. Siblings execute
    # in list order, so [reference, site] IS the edge.
    docs:
      help: "Write the command reference, then build the website from it."
      depends_on: [reference, site]
  test:
    all:
      help: "Run every test."
      impl: "orchestrator.cli:test_all"
  support:
    doctor:
      help: "Check the tools and the environment."
      impl: "orchestrator.cli:doctor"

# Both documentation tasks are placed through `import:` + `tasks:` because this manifest is the flat old
# form throughout: that is the old form's way of instantiating a catalogue coordinate.
import:
  delivery: [docs, test, release]
tasks:
  # `output` is PINNED (#2, task 3): the Hugo project exists, so where the page belongs is no longer an
  # open question a caller answers on the command line.
  docs:reference:
    group: build
    with:
      output: site/content/using/commands.md
      title: "Command reference"
  docs:site:
    group: build
  test:typecheck-python:
    group: test
  release:tag:
    group: release

site:
  # Outside the sections the block replaces: this one survives a paste and must not be counted.
  image: "hugomods/hugo:exts-0.148.2"
  source: "site"
  output: "build/website"
  base_url: "https://marcozwyssig.github.io/simplon/#top"
  theme: "github.com/imfing/hextra@v0.12.3"
"""

#: What `comments_in_replaced_sections` has to answer for the manifest above, counted by hand: two lines
#: above `groups:`, four inside it, two above `import:` and two inside `tasks:`. The three-line header
#: above `product:` and the one inside `site:` are NOT in it - they survive the paste.
_COMMENTS_A_PASTE_WOULD_DROP = 10


def test_the_refusal_names_the_comment_lines_a_paste_would_drop():
    # arrange / act
    with pytest.raises(ValueError) as exc:
        manifest.load(_REAL_OLD_MANIFEST_COMMENTED, catalogue=catalogue_mod.load())
    message = str(exc.value)

    # assert: the count, the cause, and the way out - a reader who never opens the release notes learns
    # here that the block is a blueprint rather than a replacement
    assert f"replaces carry {_COMMENTS_A_PASTE_WOULD_DROP} comment line(s)" in message
    assert "rendered from the PARSED manifest" in message
    assert "blueprint" in message


def test_the_refusal_says_nothing_about_comments_when_the_manifest_has_none_to_lose():
    """The other direction, and it is what keeps the sentence diagnosis rather than decoration: a
    manifest with nothing in those sections but structure loses nothing by pasting, and telling its owner
    to be careful would be a warning that is simply false for them."""
    # arrange / act
    with pytest.raises(ValueError) as exc:
        manifest.load(_REAL_OLD_MANIFEST, catalogue=catalogue_mod.load())
    message = str(exc.value)

    # assert
    assert "comment line" not in message
    assert "blueprint" not in message


def test_with_no_manifest_text_the_refusal_says_the_block_carries_no_comments_and_claims_nothing_more():
    """"No comments in those sections" and "nobody handed me the text" are different facts. A caller that
    passes only the parsed document cannot be told the first, so it is told the limit without the count -
    printing nothing for both states is the collapse this kernel exists to refuse."""
    # arrange / act
    with pytest.raises(ValueError) as exc:
        treeform.check_no_old_form({"groups": {"build": {"wheel": {"impl": "a:b", "help": "h."}}}})
    message = str(exc.value)

    # assert
    assert "carries no comments" in message and "blueprint" in message
    assert "comment line(s)" not in message


def test_the_printed_rewrite_carries_none_of_the_manifests_comments():
    """si#56 acceptance 2, as an assurance rather than an observation: the block the refusal prints is
    the STRUCTURE, and the sentence beside it is only true for as long as that stays so. A renderer that
    later learned to carry comments would break this - and would have to change the sentence with it."""
    # arrange
    cat = catalogue_mod.load()

    # act
    rewrite = _refused_rewrite(_REAL_OLD_MANIFEST_COMMENTED, cat)

    # assert: not one comment line, and none of the manifest's own words
    assert not [line for line in rewrite.splitlines() if line.strip().startswith("#")]
    assert "impl-less AGGREGATE" not in rewrite
    assert "flat old form" not in rewrite


def test_the_comments_are_the_only_thing_the_two_manifests_differ_by():
    """What makes the count above a measurement of LOSS rather than of a string: the commented manifest
    and the stripped one rewrite to the same block, byte for byte. Everything the parse carries survives;
    the difference between the two files is exactly what does not.

    It is also what keeps the new sentence OUT of the pasteable block. Taken out of the message rather
    than off the renderer, so a sentence written on the wrong side of "Rewrite those sections as:" would
    land in one of these two blocks and not the other - measured red by moving it there."""
    # arrange
    cat = catalogue_mod.load()

    # act
    with_comments = _refused_rewrite(_REAL_OLD_MANIFEST_COMMENTED, cat)
    without = _refused_rewrite(_REAL_OLD_MANIFEST, cat)

    # assert
    assert with_comments == without


def test_only_the_comments_inside_the_replaced_sections_are_counted():
    # arrange / act
    counted = treeform.comments_in_replaced_sections(_REAL_OLD_MANIFEST_COMMENTED)

    # assert: the header above `product:` and the line inside `site:` survive the paste and are not part
    # of the loss - a count over the whole file would be 14 and would overstate what is at stake
    assert counted == _COMMENTS_A_PASTE_WOULD_DROP


def test_a_hash_inside_a_value_is_not_a_comment():
    # arrange: `base_url` above ends in `#top`. A count that read `#` anywhere would find it - and would
    # then report a loss to a product that has none.
    text = 'groups:\n  build:\n    web: { impl: "a:b", help: "see https://x/#top" }\n'

    # act / assert
    assert treeform.comments_in_replaced_sections(text) == 0


def test_a_comment_block_above_a_replaced_key_belongs_to_the_section_it_introduces():
    # arrange: where a section's reasoning is actually written - above the key, not inside it. A count
    # that started at the key would miss exactly the lines worth keeping.
    text = "# why the bodies stand here\n# and why they stay\ntasks:\n  img: { impl: \"a:b\" }\n"

    # act / assert
    assert treeform.comments_in_replaced_sections(text) == 2
