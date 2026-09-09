"""Unit tests for the task catalogue (simplon.catalogue, netctl#1437) and the `import:` expansion it
feeds (simplon.orchestrator.manifest).

The catalogue is the coordinate space between the platform and a product: `<namespace>:<name>` resolves
to whatever module currently holds the body, so a body can move inside the kernel without breaking a
product manifest. Every rejection here exists because its silent form is worse than a loud failure - a
typo that offers nothing, an override matching no import, a coordinate with no namespace to own it.

AAA throughout, including the negative cases.
"""
import textwrap
from pathlib import Path

import pytest

from simplon import catalogue
from simplon.orchestrator import manifest

_CATALOGUE = """
tasks:
  vcs:commit: { impl: "simplon.test_impls:no_context", help: "Commit." }
  vcs:push:   { impl: "simplon.test_impls:nullary",    help: "Push." }
  test:gate:  { impl: "simplon.test_impls:gradle",     help: "Run a suite.", passthrough_args: true }
"""


# --- resolving a coordinate ---------------------------------------------------------------------------

def test_a_coordinate_resolves_to_the_declaration_it_names():
    # arrange
    cat = catalogue.loads(_CATALOGUE)

    # act
    spec = cat.resolve("vcs:commit")

    # assert
    assert spec["impl"] == "simplon.test_impls:no_context"


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
    after = catalogue.loads(_CATALOGUE.replace("simplon.test_impls:no_context",
                                               "simplon.test_impls:nullary"))

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
    # `release` joined them with `release:artifact` (publishing a directory as an OCI artifact): the
    # mechanics are the same in every product, only the registry, package, directory and media type differ.
    # `build` is the newest namespace (#31): `build:image` produces a product's container image and
    # `release:image` publishes it, so the two halves of "this product ships a container" sit in the two
    # groups the five verbs put them in rather than in one command with a flag.
    # `toolchain` is the newest (si#95): a FAMILY rather than a placement, because a containerised
    # toolchain is needed by `build` AND by `test` - ctest, dotnet test and gradle test all belong under
    # the latter, which `build:toolchain` would have forbidden.
    assert cat.namespaces() == ["build", "docs", "release", "support", "tasks", "test", "toolchain",
                                "vcs"]
    assert sorted(cat.namespace("vcs")) == ["auth-scopes", "commit", "prune-branches", "push",
                                            "submodules"]
    # `support:install` provisions the host tooling the kernel cannot work without (oras), and
    # `vcs:auth-scopes` the gh token's package scopes - the two halves of "this machine can publish".
    assert "install" in cat.namespace("support")
    # `docs` is the newest (netctl#1280): the render is a kernel mechanism, its pinned image tag is the
    # product's data, so the coordinate lives here and the version stays in the product manifest. `site`
    # (#2) is the second SHAPE of that same capability, not a second category: docToolchain renders a
    # product's architecture documentation (HTML + PDF, for people working ON the system), hugo builds its
    # product WEBSITE (HTML only, for people working WITH it). Both are mechanism; where the sources live,
    # where the output goes, which theme and which base URL are the product's data, in its manifest.
    # `reference` (#2) is the third, and the only one that renders nothing a human wrote: it reads the
    # product's own assembled command line and writes it out as Markdown, so the page cannot fall behind
    # the CLI. Mechanism again - the output PATH is the product's datum and arrives as a parameter.
    assert sorted(cat.namespace("docs")) == ["reference", "render", "site"]
    # The container image, #31's whole subject. Neither half is PLACED (the assertion below walks the
    # tree and would catch it): both read an `images:` section naming the registry, the repository, the
    # Dockerfile and the build context, so a command declared in the catalogue's own `build:` group would
    # die on its first line in every product that ships no image.
    # `cmake-files` and `dotnet-solution` (si#102) are the newest, and they are the second half of si#95:
    # `toolchain:run` runs a pinned compiler over a product tree, these two write the files that compiler
    # reads. Declared and not placed by the same bar as `image` - a product written in neither language
    # has no tree they could read - and neither takes a parameter, because the root and the product name
    # come from the ProductContext and the one thing a directory cannot show is read from the product's
    # own `build: targets:` section.
    assert sorted(cat.namespace("build")) == ["cmake-files", "dotnet-solution", "image"]
    # `release:tag` (#32) is the newest, and the odd one out in its own namespace: `artifact` and `image`
    # publish what a build produced and both read a manifest section, while `tag` publishes NOTHING - it
    # cuts the name the release is made under and pushes it, which is what makes the workflows run at
    # all. It reads no product data, which is why it is also PLACED (the assertion below walks for that).
    # `release:asset` is the newest, and it pairs with `artifact` rather than adding a category: both
    # publish what a build produced, one to a registry a pipeline pulls from and one to a page a person
    # downloads from. A product may declare either, both or neither.
    assert sorted(cat.namespace("release")) == ["artifact", "asset", "image", "tag"]


def test_the_two_image_coordinates_reach_the_generated_reference():
    # arrange: #31 acceptance 1's second half. The reference is an OUTPUT, and a coordinate no product
    # places reaches it through the closing "platform tasks this product has not placed" section - so the
    # proof is the kernel's OWN manifest read against the kernel's own catalogue, not a fixture
    from simplon.tasks import cliref

    root = Path(__file__).resolve().parents[1]
    cat = catalogue.load()
    mf = manifest.load((root / "simplon.yaml").read_text(encoding="utf-8"), catalogue=cat)

    # act
    offered = dict(cliref.unplaced(mf, cat))

    # assert
    assert "build:image" in offered and "release:image" in offered
    assert "VERSION" in offered["build:image"]
    assert "verify" in offered["release:image"]


# --- placing a catalogue coordinate ---------------------------------------------------------------------
#
# `import:` + a coordinate-keyed `tasks:` entry was how a product reached the catalogue while manifests
# were flat. Both are gone with the flat form (si#33): a command names a coordinate directly with
# `task: "<namespace>:<name>"` and the merge does the rest, so the tests below are about the ONE
# remaining way in. What was tested about `import:` itself went with it; what was tested about the RULES
# (an unknown coordinate is loud, an override keeps the catalogue's body, a command has one declaration)
# is here, restated against the mechanism that survived.

def _loaded(text):
    return manifest.load(text, catalogue=catalogue.loads(_CATALOGUE))


def test_an_imported_task_lands_in_the_group_its_namespace_names():
    # arrange: a product places a task without restating anything else about it
    text = """
groups:
  vcs:
    commands:
      commit: { task: "vcs:commit" }
      push: { task: "vcs:push" }
env_groups: []
"""

    # act
    mf = _loaded(text)

    # assert
    assert mf.groups == {"vcs": ("commit", "push")}
    assert mf.spec_for("vcs", "commit").impl == "simplon.test_impls:no_context"


def test_an_imported_task_can_be_placed_into_a_group_of_the_products_choosing():
    # arrange: netctl wants the vcs verbs under `git`
    text = """
groups:
  git:
    commands:
      commit: { task: "vcs:commit" }
env_groups: []
"""

    # act / assert
    assert _loaded(text).groups == {"git": ("commit",)}


def test_an_override_wins_over_the_catalogues_own_declaration():
    # arrange: an entry without `impl:` defines nothing and overrides what the catalogue declared
    text = """
groups:
  test:
    commands:
      gate: { task: "test:gate", help: "SYSTEM gate." }
env_groups: []
"""

    # act
    spec = _loaded(text).spec_for("test", "gate")

    # assert: the product's wording, the catalogue's body and its other flags
    assert spec.help == "SYSTEM gate."
    assert spec.impl == "simplon.test_impls:gradle"
    assert spec.passthrough_args is True


def test_an_override_that_resolves_to_no_imported_coordinate_is_rejected():
    # arrange: a silent no-op here is exactly the failure `impl:` already has - a command that quietly
    # is not there
    text = """
groups:
  git:
    commands:
      comit: { task: "vcs:comit" }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="comit"):
        _loaded(text)


def test_a_coordinate_from_a_namespace_the_catalogue_does_not_carry_is_rejected():
    # arrange: the catalogue IS the coordinate space, so a name it never declared is a typo - and a typo
    # that loads clean is a command that quietly is not there
    text = """
groups:
  build:
    commands:
      site: { task: "docs:site" }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="docs:site"):
        _loaded(text)


def test_a_products_own_definition_needs_no_catalogue_and_keeps_its_key_as_the_command_name():
    # arrange
    text = """
tasks:
  disk-guard: { impl: "simplon.test_impls:nullary", help: "Guard the disk." }

groups:
  support:
    commands:
      disk-guard: { task: "disk-guard" }
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
    impl: "simplon.test_impls:nullary"
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
groups:
  git:
    commands:
      commit: { task: "vcs:commit", help: "" }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="help"):
        _loaded(text)


def test_a_manifest_with_neither_section_is_untouched_by_the_expansion():
    # arrange: this is what lets a product adopt the mechanism one command at a time
    text = """
tasks:
  commit: { impl: "simplon.test_impls:no_context", help: "Commit." }

groups:
  git:
    commands:
      commit: { task: "commit" }
env_groups: []
"""

    # act / assert
    assert manifest.load(text).groups == {"git": ("commit",)}


def test_naming_a_coordinate_without_a_catalogue_is_a_manifest_error_not_an_attribute_error():
    # arrange: the expansion used to reach `catalogue.namespace(...)` on None and die deep inside itself,
    # which reads as a broken loader rather than as the caller mistake it is. The colon is what says
    # "the platform's", so with no platform passed in there is nothing that could answer.
    text = """
groups:
  support:
    groups:
      git:
        commands:
          commit: { task: "vcs:commit" }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="platform catalogue"):
        manifest.load(text)


def test_a_products_own_body_left_behind_by_a_coordinate_placement_is_named():
    """The loss si#53 pinned as a characterisation, now NAMED (si#81).

    THE HISTORY, because the assertion below is the third state of this test and the middle one is the
    interesting one. Until si#53 this was a load error: `check_every_task_is_used` refused a `tasks:`
    entry no command instantiated. si#53 struck that rule - it was the one expression rule the kernel
    did not apply to itself, and it forbade a product what the kernel does throughout its own catalogue:
    treating a catalogue as an OFFER. The case below is what the deletion cost, and it was pinned here
    as a characterisation of the SILENCE rather than deleted with the rule.

    si#81 is the narrower diagnosis: the product's own body stands beside a command OF THE SAME NAME
    that runs the catalogue's `vcs:commit`, so the name is taken and the body written here is dead in
    the tree. That is a half-finished move, never an offer - and the offer stays legal, which is the
    assertion in `test_a_declared_task_no_command_places_is_accepted` and in the sibling below.
    """
    # arrange: the product's own `commit` beside a command that places the catalogue's `vcs:commit`
    text = """
tasks:
  commit: { impl: "simplon.test_impls:nullary", help: "The product's own commit." }

groups:
  git:
    commands:
      commit: { task: "vcs:commit" }
env_groups: []
"""

    # act / assert: it is refused, and the message names the dead body rather than only the rule
    with pytest.raises(ValueError) as exc:
        _loaded(text)
    assert "task 'commit' is declared under `tasks:` and instantiated by no command" in str(exc.value)
    assert "simplon.test_impls:nullary" in str(exc.value)
    assert "simplon.test_impls:no_context" in str(exc.value)


def test_a_products_own_definition_landing_on_an_existing_groups_entry_is_named():
    """The same loss, seen from the other side: two product tasks, one command, and the one the command
    does not name used to be dropped without a word. Named by the same diagnosis (si#81)."""
    # arrange
    text = """
tasks:
  disk-guard: { impl: "simplon.test_impls:nullary", help: "Guard the disk." }
  support-disk-guard:
    impl: "simplon.test_impls:no_context"
    help: "Guard it differently."

groups:
  support:
    commands:
      disk-guard: { task: "support-disk-guard" }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError) as exc:
        manifest.load(text)
    assert "task 'disk-guard' is declared under `tasks:` and instantiated by no command" in str(exc.value)
    assert "simplon.test_impls:nullary" in str(exc.value)


def test_a_declared_task_whose_name_no_command_took_is_an_offer_and_still_loads():
    """The other half of si#81, and the half that decides whether the rule is narrow or merely renamed.

    An unplaced task whose name NOTHING has taken is exactly what si#53 made legal, and the diagnosis
    above must not reach it. Stated here, next to the two cases it borders on, because a refusal is only
    as narrow as the assertion that holds its edge - `test_a_declared_task_no_command_places_is_accepted`
    holds the same edge without a catalogue, and a rule broad enough to catch an offer has to break both.
    """
    # arrange: `push` is declared and placed nowhere; no command anywhere is called `push`
    text = """
tasks:
  commit: { impl: "simplon.test_impls:nullary", help: "The product's own commit." }
  push: { impl: "simplon.test_impls:no_context", help: "Declared and not placed - an offer." }

groups:
  git:
    commands:
      commit: { task: "commit" }
env_groups: []
"""

    # act
    loaded = _loaded(text)

    # assert: it loads, the placed task runs the product's body, and the offer simply is not a command
    assert loaded.groups == {"git": ("commit",)}
    assert loaded.commands["git"]["commit"].impl == "simplon.test_impls:nullary"
    assert "push" not in loaded.commands["git"]


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
  vcs:push: { impl: "simplon.test_impls:nullary", help: "Push." }
"""


def test_a_product_contributes_members_to_a_group_the_catalogue_shapes():
    # arrange: THE point of the catalogue owning the loop. The product's bare `groups:` key carries the
    # group's MEMBERS; it is not a second declaration of the group, and treating it as one made "the
    # platform owns the tree" unimplementable.
    text = """
tasks:
  compile: { impl: "simplon.test_impls:nullary", help: "Compile." }

groups:
  build:
    commands:
      compile: { task: "compile" }
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
  build: { help: "The product's own idea of build." }
tasks:
  compile: { impl: "simplon.test_impls:nullary", help: "Compile." }

groups:
  build:
    commands:
      compile: { task: "compile" }
env_groups: []
"""

    # act / assert
    with pytest.raises(ValueError, match="taxonomy"):
        manifest.load(text, catalogue=catalogue.loads(_SHAPED))


def test_env_gating_comes_with_the_shape_so_the_product_need_not_restate_it():
    # arrange: env-first is part of a group's shape, so a product contributing members to `deploy` must
    # not have to list it in `env_groups:` as well - that would be the shape stated twice, in two files.
    text = """
tasks:
  up: { impl: "simplon.test_impls:nullary", help: "Bring it up." }

groups:
  deploy:
    commands:
      up: { task: "up" }
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
tasks:
  thing: { impl: "simplon.test_impls:nullary", help: "Do the thing." }

groups:
  bespoke:
    commands:
      thing: { task: "thing" }
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
tasks:
  something-only-this-product-has:
    impl: "simplon.test_impls:nullary"
    help: "Very specific."

groups:
  build:
    commands:
      something-only-this-product-has: { task: "something-only-this-product-has" }
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
tasks:
  push: { impl: "simplon.test_impls:nullary", help: "Push." }

groups:
  support:
    groups:
      git:
        commands:
          push: { task: "push" }
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
  vcs:push: { impl: "simplon.test_impls:nullary", help: "Push." }
"""
    text = """
tasks:
  thing: { impl: "simplon.test_impls:nullary", help: "Do the thing." }

groups:
  bespoke:
    commands:
      thing: { task: "thing" }
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
    # arrange: the real catalogue.yaml, not a fixture - this is the assertion that the platform's own
    # data obeys the rule the platform enforces
    cat = catalogue.load()

    # act: walk the WHOLE tree, not just support.git and tasks - the mistake this guards against would
    # realistically place a product-data task under a group this narrower walk never inspected (e.g.
    # `test:gate` under `test:`), and a two-branch walk would stay green while that happened
    git = cat.groups["support"]["groups"]["git"]["commands"]
    tasks = cat.groups["support"]["groups"]["tasks"]["commands"]
    placed = _placed_tasks(cat.groups)

    # assert
    assert set(git) == {"commit", "push", "prune-branches", "submodules", "auth-scopes"}
    assert set(tasks) == {"catalogue", "generate"}
    # `support:install` and `vcs:auth-scopes` are placed for the same reason the git verbs are: both
    # read nothing from a product manifest - one drives the tool gates, the other the gh token.
    # `release:tag` is NOT here, and that is the placement rule doing its work (#39). Placing a command
    # gives it to every product that adopts the manifest's tree form, and it cannot be declined - so what
    # is placed has to be useful in EVERY product, not merely harmless in most. `release:tag` publishes:
    # it cuts a tag and pushes it, the damage of a misfire is public and irreversible, and a product with
    # no tag-triggered workflow has nothing waiting for it. It stays OFFERED; a product that releases by
    # tag declares it in one line, which is what simplon itself does.
    #
    # The old rationale, kept because it is still true of the ones that remain: the first PHASE command to
    # tag, the repo root and the remote's default branch are all it reads, so unlike its two neighbours
    # in the `release` namespace it cannot die on its first line in a product that declared nothing.
    #
    # `support:completion` joins them (si#58), and by the same test rather than by exception: it reads no
    # manifest section - the command tree it writes out is the one every manifest already has - it
    # publishes nothing and it touches only the product's own root. What settles it is what the thing IS:
    # a completion that has to be asked for is a completion nobody has, because the way somebody would
    # discover it is by pressing TAB, and that is precisely what does not work yet. `tasks:generate` is
    # the standing precedent for the write - placed, and writing a generated file at a kernel-chosen path.
    assert placed == {"vcs:commit", "vcs:push", "vcs:prune-branches", "vcs:submodules",
                      "vcs:auth-scopes", "support:install", "support:completion",
                      "tasks:catalogue", "tasks:generate"}
    # `release` is DECLARED and holds nothing. The group exists so a product can place its own release
    # commands into it - the rule that a coordinate opening with a phase name belongs to that phase is
    # unchanged - but the kernel places none of its own there (#39): a command that publishes has to be
    # asked for, not handed out.
    assert "commands" not in cat.groups["release"]
    assert cat.groups["release"]["help"]


def test_the_shipped_gate_task_documents_name_while_every_real_instantiation_pins_it():
    # arrange: catalogue.yaml's `test:gate` declares `params: { name: ... }` to document the option for a
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
      vcs:commit: { impl: simplon.tasks.vcs:commit, help: "commit." }
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
    text = 'tasks:\n  vcs:commit: { impl: simplon.tasks.vcs:commit, help: "commit." }\n'

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
          vcs:push: { impl: simplon.tasks.vcs:push, help: "push it." }
        groups:
          build: { help: "Produce the artefacts." }
    """))
    old_form = textwrap.dedent("""
        product: demo
        tasks:
          yeehaw: { impl: "demo.cli:yeehaw", help: "ride." }

        groups:
          wildwest:
            commands:
              yeehaw: { task: "yeehaw" }
    """)

    # act / assert
    with pytest.raises(ValueError, match="does not declare"):
        manifest.load(old_form, catalogue=cat)
