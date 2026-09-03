"""Unit tests for the task catalogue (delivery.catalogue, netctl#1437) and the `import:` expansion it
feeds (delivery.orchestrator.manifest).

The catalogue is the coordinate space between the platform and a product: `<namespace>:<name>` resolves
to whatever module currently holds the body, so a body can move inside the kernel without breaking a
product manifest. Every rejection here exists because its silent form is worse than a loud failure - a
typo that offers nothing, an override matching no import, a coordinate with no namespace to own it.

AAA throughout, including the negative cases.
"""
import textwrap

import pytest

from delivery import catalogue
from delivery.orchestrator import manifest

_CATALOGUE = """
tasks:
  vcs:commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
  vcs:push:   { impl: "delivery.test_impls:nullary",    help: "Push." }
  test:gate:  { impl: "delivery.test_impls:gradle",     help: "Run a suite.", passthrough_args: true }
"""


# --- resolving a coordinate ---------------------------------------------------------------------------

def test_a_coordinate_resolves_to_the_declaration_it_names():
    # arrange
    cat = catalogue.loads(_CATALOGUE)

    # act
    spec = cat.resolve("vcs:commit")

    # assert
    assert spec["impl"] == "delivery.test_impls:no_context"


def test_importing_a_namespace_pulls_every_task_in_it_and_nothing_from_a_neighbour():
    # arrange
    cat = catalogue.loads(_CATALOGUE)

    # act
    names = sorted(cat.namespace("vcs"))

    # assert
    assert names == ["commit", "push"]


def test_a_moved_body_keeps_the_coordinate_stable():
    # arrange: the whole point of the indirection - the product names the coordinate, never the module
    before = catalogue.loads(_CATALOGUE)
    after = catalogue.loads(_CATALOGUE.replace("delivery.test_impls:no_context",
                                               "delivery.test_impls:nullary"))

    # act / assert
    assert set(before.tasks) == set(after.tasks)
    assert before.resolve("vcs:commit")["impl"] != after.resolve("vcs:commit")["impl"]


def test_an_unknown_coordinate_in_a_known_namespace_names_what_the_namespace_does_offer():
    # arrange
    cat = catalogue.loads(_CATALOGUE)

    # act / assert
    with pytest.raises(ValueError) as exc:
        cat.resolve("vcs:comit")
    assert "commit" in str(exc.value) and "push" in str(exc.value)


def test_an_unknown_namespace_is_rejected_rather_than_returning_an_empty_map():
    # arrange: an `import:` typo would otherwise offer nothing at all, and read at the point of use as if
    # the platform simply had no such tasks
    cat = catalogue.loads(_CATALOGUE)

    # act / assert
    with pytest.raises(ValueError, match="vsc"):
        cat.namespace("vsc")


# --- what a catalogue may declare ----------------------------------------------------------------------

@pytest.mark.parametrize("key", ["commit", "a:b:c", ":commit", "vcs:"])
def test_a_task_that_is_not_a_namespace_qualified_coordinate_is_rejected(key):
    # arrange: a bare `commit:` has no coordinate space, so two namespaces could not both offer one and a
    # product could not say which it meant
    text = f'tasks:\n  "{key}": {{ impl: "a:b", help: "x" }}\n'

    # act / assert
    with pytest.raises(ValueError, match="coordinate"):
        catalogue.loads(text)


def test_a_catalogue_task_without_an_impl_is_rejected():
    # arrange: the catalogue is where a body LIVES; an entry without one resolves to no code at all
    text = 'tasks:\n  vcs:commit: { help: "Commit." }\n'

    # act / assert
    with pytest.raises(ValueError, match="impl"):
        catalogue.loads(text)


def test_the_shipped_catalogue_parses_and_offers_the_namespaces_netctl_imports():
    # arrange / act: the real file, not a fixture - a catalogue that does not parse is a broken product
    cat = catalogue.load()

    # assert
    assert cat.namespaces() == ["docs", "support", "tasks", "test", "vcs"]
    assert sorted(cat.namespace("vcs")) == ["commit", "prune-branches", "push", "submodules"]
    # `docs` is the newest (netctl#1280): the render is a kernel mechanism, its pinned image tag is the
    # product's data, so the coordinate lives here and the version stays in the product manifest.
    assert sorted(cat.namespace("docs")) == ["render"]


# --- the `import:` + `tasks:` expansion ------------------------------------------------------------------

def _loaded(text):
    return manifest.load(text, catalogue=catalogue.loads(_CATALOGUE))


def test_an_imported_task_lands_in_the_group_its_namespace_names():
    # arrange: a product places a task without restating anything else about it
    text = """
import:
  delivery: [vcs]
tasks:
  vcs:commit: {}
  vcs:push: {}
env_groups: []
"""

    # act
    mf = _loaded(text)

    # assert
    assert mf.groups == {"vcs": ("commit", "push")}
    assert mf.spec_for("vcs", "commit").impl == "delivery.test_impls:no_context"


def test_an_imported_task_can_be_placed_into_a_group_of_the_products_choosing():
    # arrange: netctl wants the vcs verbs under `git`
    text = """
import:
  delivery: [vcs]
tasks:
  vcs:commit: { group: git }
env_groups: []
"""

    # act / assert
    assert _loaded(text).groups == {"git": ("commit",)}


def test_an_override_wins_over_the_catalogues_own_declaration():
    # arrange: an entry without `impl:` defines nothing and overrides what the catalogue declared
    text = """
import:
  delivery: [test]
tasks:
  test:gate: { help: "SYSTEM gate.", group: test }
env_groups: []
"""

    # act
    spec = _loaded(text).spec_for("test", "gate")

    # assert: the product's wording, the catalogue's body and its other flags
    assert spec.help == "SYSTEM gate."
    assert spec.impl == "delivery.test_impls:gradle"
    assert spec.passthrough_args is True


def test_an_override_that_resolves_to_no_imported_coordinate_is_rejected():
    # arrange: a silent no-op here is exactly the failure `impl:` already has - a command that quietly
    # is not there
    text = """
import:
  delivery: [vcs]
tasks:
  vcs:comit: { group: git }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="comit"):
        _loaded(text)


def test_a_task_from_a_namespace_that_was_not_imported_is_rejected():
    # arrange: importing is what makes a coordinate available; resolving one anyway would make `import:`
    # decoration rather than a declaration
    text = """
import:
  delivery: [vcs]
tasks:
  test:gate: { group: test }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="test:gate"):
        _loaded(text)


def test_a_products_own_definition_needs_no_catalogue_and_keeps_its_key_as_the_command_name():
    # arrange
    text = """
tasks:
  disk-guard:
    impl: "delivery.test_impls:nullary"
    help: "Guard the disk."
    group: support
env_groups: []
"""

    # act
    mf = manifest.load(text)

    # assert
    assert mf.groups == {"support": ("disk-guard",)}


def test_a_definition_keyed_by_a_coordinate_is_rejected():
    # arrange: a coordinate is what the CATALOGUE assigns; a product minting one would make two sources
    # of the same namespace
    text = """
tasks:
  vcs:disk-guard:
    impl: "delivery.test_impls:nullary"
    help: "Guard the disk."
    group: support
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="coordinate"):
        manifest.load(text)


def test_imported_tasks_are_validated_by_every_rule_a_declared_command_is():
    # arrange: expansion happens BEFORE validation, which is the point of expanding there - an imported
    # command with no help is as broken as a declared one with no help
    text = """
import:
  delivery: [vcs]
tasks:
  vcs:commit: { help: "", group: git }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="help"):
        _loaded(text)


def test_an_unknown_import_source_is_rejected():
    # arrange: `delivery` is the only catalogue there is
    text = """
import:
  platform: [vcs]
tasks:
  vcs:commit: { group: git }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="platform"):
        _loaded(text)


def test_a_manifest_with_neither_section_is_untouched_by_the_expansion():
    # arrange: this is what lets a product adopt the mechanism one command at a time
    text = """
groups:
  git:
    commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
env_groups: []
"""

    # act / assert
    assert manifest.load(text).groups == {"git": ("commit",)}


def test_an_import_without_a_catalogue_is_a_manifest_error_not_an_attribute_error():
    # arrange: the expansion used to reach `catalogue.namespace(...)` on None and die deep inside itself,
    # which reads as a broken loader rather than as the caller mistake it is
    text = """
import:
  delivery: [vcs]
groups:
  git:
    commit: { impl: "delivery.test_impls:no_context", help: "Commit." }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="catalogue"):
        manifest.load(text)


def test_an_imported_task_landing_on_an_existing_groups_entry_is_rejected():
    # arrange: the likeliest mistake of the whole migration. A product adopting `import:` one command at
    # a time keeps its own `groups:` declaration next to the new one - and the LOCAL body, the one still
    # being maintained, is the half that used to disappear without a word.
    text = """
import:
  delivery: [vcs]
groups:
  git:
    commit: { impl: "delivery.test_impls:nullary", help: "The product's own commit." }
tasks:
  vcs:commit: { group: git }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError) as exc:
        _loaded(text)
    assert "git commit" in str(exc.value)


def test_a_products_own_definition_landing_on_an_existing_groups_entry_is_rejected():
    # arrange: same rule for a definition - a command has ONE declaration
    text = """
groups:
  support:
    disk-guard: { impl: "delivery.test_impls:nullary", help: "Guard the disk." }
tasks:
  disk-guard:
    impl: "delivery.test_impls:no_context"
    help: "Guard it differently."
    group: support
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="disk-guard"):
        manifest.load(text)


# --- the catalogue owns the tree's SHAPE (netctl#1444, spec step 7) -------------------------------------

_SHAPED = """
taxonomy:
  build:   { help: "Produce the artefacts." }
  deploy:  { help: "Put them somewhere.", env_first: true }
  support:
    help: "Host upkeep."
    groups:
      git: { help: "Version control." }
tasks:
  vcs:push: { impl: "delivery.test_impls:nullary", help: "Push." }
"""


def test_a_product_contributes_members_to_a_group_the_catalogue_shapes():
    # arrange: THE point of the catalogue owning the loop. The product's bare `groups:` key carries the
    # group's MEMBERS; it is not a second declaration of the group, and treating it as one made "the
    # platform owns the tree" unimplementable.
    text = """
groups:
  build:
    compile: { impl: "delivery.test_impls:nullary", help: "Compile." }
env_groups: []
"""

    # act
    mf = manifest.load(text, catalogue=catalogue.loads(_SHAPED))

    # assert
    assert mf.tree["build"].commands == ("compile",)
    assert mf.groups["build"] == ("compile",)


def test_a_product_may_not_shape_the_tree_at_all_once_the_catalogue_does():
    # arrange: the `taxonomy:` block is the loophole in the lock below - a product that may declare its
    # own shape can declare any group and then satisfy a check that asks "is it in SOME taxonomy". So
    # once the catalogue shapes the loop, the product's block is refused outright rather than merged.
    # This case used to be allowed as a "contradiction" only when the two files named the SAME group.
    text = """
taxonomy:
  build: { help: "The product's own build." }
groups:
  build:
    compile: { impl: "delivery.test_impls:nullary", help: "Compile." }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="taxonomy"):
        manifest.load(text, catalogue=catalogue.loads(_SHAPED))


def test_env_gating_comes_with_the_shape_so_the_product_need_not_restate_it():
    # arrange: env-first is part of a group's shape, so a product contributing members to `deploy` must
    # not have to list it in `env_groups:` as well - that would be the shape stated twice, in two files.
    text = """
groups:
  deploy:
    up: { impl: "delivery.test_impls:nullary", help: "Bring it up." }
env_groups: []
"""

    # act
    mf = manifest.load(text, catalogue=catalogue.loads(_SHAPED))

    # assert
    assert mf.tree["deploy"].env_first is True
    assert mf.taxonomy().group_requires_env("deploy") is True


def test_a_group_the_catalogue_does_not_declare_is_rejected(): 
    # arrange: the lock (netctl#1462). A product used to be able to invent a top-level group out of thin
    # air, which left the catalogue owning a group's SHAPE but not its EXISTENCE - and that is most of
    # the value gone. The point of hoisting the taxonomy onto the platform is that every *ctl product
    # runs the SAME loop under the SAME group names, so the general tasks sit in the same place
    # everywhere. A product that can put `lint` next to `test` has the drift back.
    text = """
groups:
  bespoke:
    thing: { impl: "delivery.test_impls:nullary", help: "Do the thing." }
env_groups: []
"""

    # act / assert: the message has to name the way out, because "not allowed" alone leaves an author
    # with a legitimate new group nowhere to go - the way out is the catalogue's `groups:`, where every
    # product gets it.
    with pytest.raises(ValueError, match="bespoke") as exc:
        manifest.load(text, catalogue=catalogue.loads(_SHAPED))
    assert "`groups:`" in str(exc.value)


def test_a_product_adds_a_task_the_catalogue_never_heard_of_to_a_platform_group():
    # arrange: the freedom the lock must NOT touch. Groups are fixed; TASKS are the product's own. This
    # command exists in no catalogue at all - it is netctl's `wireguard-guard` case, a product-specific
    # body in a platform group.
    text = """
groups:
  build:
    something-only-this-product-has: { impl: "delivery.test_impls:nullary", help: "Very specific." }
env_groups: []
"""

    # act
    mf = manifest.load(text, catalogue=catalogue.loads(_SHAPED))

    # assert
    assert mf.tree["build"].commands == ("something-only-this-product-has",)


def test_a_nested_group_the_catalogue_declares_is_reachable_by_its_dotted_path():
    # arrange: the lock is on TOP-LEVEL keys; a dotted key names members of a node the catalogue already
    # built, and has always been validated against the tree separately. Asserted here so a future
    # tightening of the lock cannot quietly take `support.git` with it.
    text = """
groups:
  support.git:
    push: { impl: "delivery.test_impls:nullary", help: "Push." }
env_groups: []
"""

    # act
    mf = manifest.load(text, catalogue=catalogue.loads(_SHAPED))

    # assert
    assert mf.tree["support"].groups["git"].commands == ("push",)


def test_without_a_catalogue_taxonomy_a_product_still_owns_its_own_tree():
    # arrange: the lock is conditional on the catalogue actually shaping something. A product on a
    # catalogue that offers only tasks - and every pure-parse fixture, which loads with no catalogue at
    # all - keeps the freedom it has today, which is what lets a product adopt the shape in its own time.
    tasks_only = """
tasks:
  vcs:push: { impl: "delivery.test_impls:nullary", help: "Push." }
"""
    text = """
groups:
  bespoke:
    thing: { impl: "delivery.test_impls:nullary", help: "Do the thing." }
env_groups: []
"""

    # act
    mf = manifest.load(text, catalogue=catalogue.loads(tasks_only))

    # assert
    assert sorted(mf.tree) == ["bespoke"]


def test_a_catalogue_taxonomy_that_is_not_a_mapping_is_rejected():
    # arrange: a list here would silently shape nothing at all
    with pytest.raises(ValueError, match="taxonomy"):
        catalogue.loads("taxonomy: [build, test]\ntasks: {}\n")


def _placed_tasks(groups: dict) -> set[str]:
    """Every coordinate placed anywhere in a group tree, however deeply nested - `commands` at THIS level
    plus whatever `groups` nests below it."""
    placed: set[str] = set()
    for node in groups.values():
        placed |= {spec["task"] for spec in (node.get("commands") or {}).values()}
        placed |= _placed_tasks(node.get("groups") or {})
    return placed


def test_the_shipped_catalogue_places_the_general_commands_and_nothing_that_needs_product_data():
    # arrange: the real delivery.yaml, not a fixture - this is the assertion that the platform's own
    # data obeys the rule the platform enforces
    cat = catalogue.load()

    # act: walk the WHOLE tree, not just support.git and tasks - the mistake this guards against would
    # realistically place a product-data task under a group this narrower walk never inspected (e.g.
    # `test:gate` under `test:`), and a two-branch walk would stay green while that happened
    git = cat.groups["support"]["groups"]["git"]["commands"]
    tasks = cat.groups["support"]["groups"]["tasks"]["commands"]
    placed = _placed_tasks(cat.groups)

    # assert
    assert set(git) == {"commit", "push", "prune-branches", "submodules"}
    assert set(tasks) == {"catalogue", "generate"}
    assert placed == {"vcs:commit", "vcs:push", "vcs:prune-branches", "vcs:submodules",
                       "tasks:catalogue", "tasks:generate"}


def test_the_shipped_gate_task_documents_name_while_every_real_instantiation_pins_it():
    # arrange: delivery.yaml's `test:gate` declares `params: { name: ... }` to document the option for a
    # caller that leaves it unpinned, while netctl's two real commands each pin `name` with `with:`. The
    # question this proves an answer to (netctl#1469 vocabulary review, item F5): `treeform.resolve` only
    # rejects a COMMAND's OWN `params:` for a key it also pins - never the TEMPLATE's - so a task
    # documents a parameter once and every pinning instance still resolves clean.
    cat = catalogue.load()
    text = """
groups:
  test:
    commands:
      system:              { task: "test:gate", with: { name: system } }
      acceptance-dataplane: { task: "test:gate", with: { name: acceptance-dataplane } }
env_groups: []
"""

    # act
    mf = manifest.load(text, catalogue=cat, validate_with=True)

    # assert: both resolve, each keeps its own pin, and `name` renders as a stray option for neither
    system = mf.spec_for("test", "system")
    dataplane = mf.spec_for("test", "acceptance-dataplane")
    assert system.with_ == {"name": "system"} and system.params == {}
    assert dataplane.with_ == {"name": "acceptance-dataplane"} and dataplane.params == {}


def test_the_shipped_catalogue_declares_the_whole_ci_cd_loop():
    # arrange
    cat = catalogue.load()

    # act / assert: the shape every *ctl product inherits, and the two env-first groups
    assert set(cat.groups) == {"build", "test", "release", "deploy", "monitor", "support"}
    assert set(cat.groups["support"]["groups"]) == {"git", "tasks"}
    assert cat.groups["deploy"]["env_first"] is True
    assert cat.groups["monitor"]["env_first"] is True


# --- the kernel's command tree (netctl#1469) -----------------------------------------------------------

def test_the_catalogue_carries_the_command_tree_it_declares():
    # arrange: a catalogue that declares a group with a command in it
    text = """
    tasks:
      vcs:commit: { impl: delivery.tasks.vcs:commit, help: "commit." }
    groups:
      support:
        help: "Host tooling."
        groups:
          git:
            help: "Version-control helpers."
            commands:
              commit: { task: "vcs:commit" }
    """

    # act
    cat = catalogue.loads(textwrap.dedent(text))

    # assert
    assert cat.groups["support"]["groups"]["git"]["commands"]["commit"] == {"task": "vcs:commit"}


def test_a_catalogue_without_a_groups_block_carries_an_empty_tree():
    # arrange: the shape every catalogue had before netctl#1469
    text = 'tasks:\n  vcs:commit: { impl: delivery.tasks.vcs:commit, help: "commit." }\n'

    # act
    cat = catalogue.loads(text)

    # assert
    assert cat.groups == {}


def test_a_groups_block_that_is_not_a_mapping_is_rejected():
    # arrange
    text = 'tasks:\n  vcs:commit: { impl: a:b, help: "h." }\ngroups: [build, test]\n'

    # act / assert
    with pytest.raises(ValueError, match="catalogue 'groups' must be a mapping"):
        catalogue.loads(text)


def test_an_old_form_product_still_cannot_invent_a_group_after_the_tree_moved():
    # arrange: the netctl#1462 lock, now reading the tree instead of the deleted `taxonomy:` block. Not
    # a hypothetical - Plan 1 Task 7 removed the block the lock used to read.
    cat = catalogue.loads(textwrap.dedent("""
        tasks:
          vcs:push: { impl: delivery.tasks.vcs:push, help: "push it." }
        groups:
          build: { help: "Produce the artefacts." }
    """))
    old_form = textwrap.dedent("""
        product: demo
        groups:
          wildwest:
            yeehaw: { impl: "demo.cli:yeehaw", help: "ride." }
    """)

    # act / assert
    with pytest.raises(ValueError, match="does not declare"):
        manifest.load(old_form, catalogue=cat)
