"""Unit tests for the task catalogue (delivery.catalogue, netctl#1437) and the `import:` expansion it
feeds (delivery.orchestrator.manifest).

The catalogue is the coordinate space between the platform and a product: `<namespace>:<name>` resolves
to whatever module currently holds the body, so a body can move inside the kernel without breaking a
product manifest. Every rejection here exists because its silent form is worse than a loud failure - a
typo that offers nothing, an override matching no import, a coordinate with no namespace to own it.

AAA throughout, including the negative cases.
"""
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
    assert cat.namespaces() == ["support", "test", "vcs"]
    assert sorted(cat.namespace("vcs")) == ["commit", "prune-branches", "push", "submodules"]


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
