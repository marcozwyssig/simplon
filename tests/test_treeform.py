"""The new-form command tree, lowered to the flat form the manifest model validates (netctl#1469).

AAA throughout. Every rejection has a negative test, because a rule that only ever runs on valid input
is a rule nobody has seen work.
"""
import textwrap

import pytest

from conftest import ROOT
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


def test_the_refusal_names_the_release_that_abolished_the_form_and_the_page_that_replaced_it():
    """si#85 struck the renderer that used to print the replacement, so this message is now the WHOLE of
    what the refusal offers - and a message that says only "gone" leaves the reader exactly where the
    missing-key error further down would have left them.

    Three facts, because those are the three that cannot be recovered from the manifest itself: which
    shape it is in, which release stopped loading it, and where the shape that replaced it is written
    down. The page is asserted as a REACHABLE coordinate rather than as a string: `site/content` is
    where it is maintained, so a page renamed out from under this refusal turns this red.
    """
    # arrange / act
    with pytest.raises(ValueError) as exc:
        manifest.load(_REAL_OLD_MANIFEST, catalogue=catalogue_mod.load())
    message = str(exc.value)

    # assert: the release, and the page - the deep link by its ANCHOR rather than by a heading a reader
    # would have to search a 500-line page for
    assert "abolished in 0.4.0" in message
    assert "building/manifest/#the-flat-form-and-how-to-leave-it" in message
    # and the anchor resolves: Hugo derives it from the heading, so the heading has to be spelled that
    # way on the page this refusal sends people to
    page = (ROOT / "site" / "content" / "building" / "manifest.md").read_text(encoding="utf-8")
    headings = [line[3:].strip() for line in page.splitlines() if line.startswith("## ")]
    slugs = {heading.lower().replace(",", "").replace(" ", "-") for heading in headings}
    assert "the-flat-form-and-how-to-leave-it" in slugs


def test_the_refusal_no_longer_promises_a_rewrite():
    """The other half of si#85, and the one a deletion silently gets wrong: a message that still says
    "Rewrite those sections as:" and then prints nothing is worse than one that never offered it."""
    # arrange / act
    with pytest.raises(ValueError) as exc:
        manifest.load(_REAL_OLD_MANIFEST, catalogue=catalogue_mod.load())
    message = str(exc.value)

    # assert
    assert "Rewrite those sections as" not in message
    assert "blueprint" not in message
    assert "comment line" not in message
    assert not hasattr(treeform, "rewrite_of_old_form")


def test_a_task_that_places_its_own_command_is_told_to_delete_the_group_key():
    """The one case where following the message literally leaves the reader refused a second time.

    A `tasks:` entry with `group:` already HAS its body under `tasks:`, so "declare the body once under
    `tasks:` and point a command at it" describes work that is done. What makes it flat is the `group:`
    key, and `old_form_tasks` keeps flagging the manifest until it goes.
    """
    # arrange / act
    with pytest.raises(ValueError) as exc:
        treeform.check_no_old_form({"tasks": {"lab": {"impl": "o.cli:lab", "group": "build"}}})
    message = str(exc.value)

    # assert
    assert "DELETE its `group:` key" in message
    # and it is NOT told the kernel owns its body, which is the other finding's note
    assert "keeps its body in the kernel" not in message


def test_a_coordinate_named_task_with_its_own_impl_is_told_the_body_is_the_products():
    """Two different files land in the same finding, and only one of them belongs to the platform.

    A bare coordinate names the KERNEL's body. One carrying its own `impl:` is the PRODUCT's body under
    a name shaped like the platform's - si#33's own migration had both - so a note saying "the body stays
    in the kernel" would send its owner to a body that is not theirs and lose the one that is.
    """
    # arrange: both shapes at once, so the message has to distinguish rather than pick
    data = {"tasks": {"docs:site": {"group": "build"},
                      "docs:reference": {"impl": "my.own:renderer", "group": "build"}}}

    # act
    with pytest.raises(ValueError) as exc:
        treeform.check_no_old_form(data)
    message = str(exc.value)

    # assert: one note each, and the product's own body named
    assert "keeps its body in the kernel" in message
    assert "'docs:reference' declare an `impl:` of their own" in message
    assert "the body is YOURS and not the platform's" in message
    assert "'docs:site' declare an `impl:`" not in message

