"""Phase or family: what a coordinate's namespace says about where it may be placed (si#34).

THE RULE, decided in the ticket: a coordinate that starts with a PHASE name belongs in exactly that
phase; any other namespace is a FAMILY, and the product places it where it likes.

Two axes survive it, which is the whole reason this rule was chosen over the two cheaper ones. `docs:site`
sits under `build` in simplon and could sit under `release` in another product; `build:image` sits under
`build`, always. What the rule removes is the third state - a namespace that reads like a phase and is
placed somewhere else - because that is the only case where a reader cannot tell which of the two axes a
name is on.

WHY THIS FILE HOLDS BOTH HALVES, and why neither alone would do. The rule was measured against both of
today's manifests BEFORE it was written and found 0 violations in each, so a check that runs over them
and stays green proves only that it breaks nothing. That is worth having and it is not the rule working.
So every green here is paired: the rejection is seen RED with its message read, and the passes carry the
count of placements the rule actually ruled on - because a check that ruled on nothing returns exactly
like a check that ruled on twenty, and only one of those is evidence.

AAA throughout.
"""
import textwrap

import pytest
import yaml

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod
from simplon.orchestrator.model import treeform

from conftest import ROOT

#: The platform's own top-level groups, spelled out rather than read back out of the catalogue: a test
#: that derived the phase set from the same file it then asserts the phase set of would hold nothing.
PHASES = frozenset({"build", "test", "release", "deploy", "monitor", "support"})


def test_the_catalogue_still_declares_exactly_the_six_phases_the_rule_is_written_against():
    """The rule's phase set is the catalogue's top-level groups, so a seventh group added without a
    thought for this rule must show up here rather than silently widen it."""
    # arrange / act
    groups = frozenset(catalogue_mod.load().groups)

    # assert
    assert groups == PHASES


# --- the rejection ------------------------------------------------------------------------------------


def test_a_phase_named_coordinate_placed_in_another_phase_is_rejected():
    # arrange: `build:image` is a placement, not a family - it says `build` and means it
    flat = {"test": {"image": {"task": "build:image"}}}

    # act / assert
    with pytest.raises(ValueError, match="is a phase"):
        treeform.check_coordinate_placement(flat, PHASES)


def test_the_rejection_names_both_coordinates_the_allowed_group_and_the_way_out():
    """The repository's error form: a refusal that names only the offence leaves the reader to guess the
    fix. This one carries the placement it found, the coordinate that forbids it, the group it does
    belong in, and the two ways out."""
    # arrange
    flat = {"test": {"image": {"task": "build:image"}}}

    # act
    with pytest.raises(ValueError) as caught:
        treeform.check_coordinate_placement(flat, PHASES)
    message = str(caught.value)

    # assert: both coordinates - the placement in the tree, and the one in the catalogue
    assert "'test image'" in message
    assert "'build:image'" in message
    # the allowed group, named as the manifest spells it
    assert "`groups: build:`" in message
    # and both ways out: move the command, or make the namespace a family
    assert "`groups: build: commands: image:`" in message
    assert "not a phase" in message
    assert "docs:site" in message
    # the phase set itself, so "is it a phase?" is answerable from the message alone
    assert "build, deploy, monitor, release, support, test" in message


def test_the_rejection_reaches_a_product_through_the_loader():
    """The check has to be ON the load path, not merely importable: si#33 moved every product onto
    `treeform.merge`, and a rule wired anywhere else would hold over nothing a product actually runs."""
    # arrange: a catalogue with a real phase-named coordinate, and a manifest that misfiles it
    catalogue = catalogue_mod.loads(textwrap.dedent("""
        tasks:
          build:image: { impl: "simplon.tasks.image:build", help: "Build the image." }
        groups:
          build:   { help: "Produce the artefacts." }
          test:    { help: "Verify them." }
          release: { help: "Publish them." }
    """))
    text = textwrap.dedent("""
        product: demo
        groups:
          test:
            commands:
              image: { task: "build:image" }
    """)

    # act / assert
    with pytest.raises(ValueError, match=r"'test image' places the coordinate 'build:image'"):
        manifest_mod.load(text, catalogue=catalogue)


def test_the_same_coordinate_under_its_own_phase_loads():
    """The other half of the pair above: the rejection is about the PLACEMENT, so the identical
    manifest with the command moved must load, or the rule would be a ban rather than a rule."""
    # arrange
    catalogue = catalogue_mod.loads(textwrap.dedent("""
        tasks:
          build:image: { impl: "simplon.tasks.image:build", help: "Build the image." }
        groups:
          build:   { help: "Produce the artefacts." }
          test:    { help: "Verify them." }
    """))
    text = textwrap.dedent("""
        product: demo
        groups:
          build:
            commands:
              image: { task: "build:image" }
    """)

    # act
    mf = manifest_mod.load(text, catalogue=catalogue)

    # assert
    assert mf.commands["build"]["image"].impl == "simplon.tasks.image:build"


# --- the two axes, which the rule exists to keep -------------------------------------------------------


def test_one_family_coordinate_placed_in_two_different_phases_passes():
    """The capability the two rejected alternatives would have cost. `docs:site` is a family: it says
    what the task IS and nothing about where it runs, so two products may file it differently and this
    check must have no opinion about either."""
    # arrange: the same coordinate, two phases - as it would look across two products
    under_build = {"build": {"site": {"task": "docs:site"}}}
    under_release = {"release": {"site": {"task": "docs:site"}}}

    # act
    ruled_build = treeform.check_coordinate_placement(under_build, PHASES)
    ruled_release = treeform.check_coordinate_placement(under_release, PHASES)

    # assert: neither is rejected, and the count says the rule ruled on NEITHER - a family is outside it
    assert (ruled_build, ruled_release) == (0, 0)


def test_a_phase_named_coordinate_under_its_own_phase_is_ruled_on_rather_than_merely_not_rejected():
    """The count is the difference between "the rule agreed" and "the rule never looked"."""
    # arrange
    flat = {"build": {"image": {"task": "build:image"}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, PHASES)

    # assert
    assert ruled == 1


def test_a_phase_named_coordinate_in_a_subgroup_of_its_phase_passes():
    """Only the first path segment is the phase. `support.git` is still `support`, so a coordinate
    filed one shelf deeper inside its own phase runs in the phase it names."""
    # arrange
    flat = {"support.git": {"install": {"task": "support:install"}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, PHASES)

    # assert
    assert ruled == 1


def test_a_bare_task_name_is_outside_the_rule_entirely():
    """A name without a colon is this manifest's own task, not a coordinate - there is no namespace to
    read, and a product's `wheel` under any group it likes is none of this rule's business."""
    # arrange
    flat = {"test": {"wheel": {"task": "wheel"}, "all": {"depends_on": ["wheel"]}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, PHASES)

    # assert
    assert ruled == 0


def test_with_no_catalogue_there_are_no_phases_and_every_namespace_is_a_family():
    """"Which names are phases" is the platform's statement. A loader handed no catalogue has no
    platform, so `build:image` under `test` is not a violation there - it is a coordinate that resolves
    to nothing, which `resolve` reports in its own words rather than this rule pre-empting it."""
    # arrange
    flat = {"test": {"image": {"task": "build:image"}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, frozenset())

    # assert
    assert ruled == 0


# --- both of today's manifests, and what their green is worth -----------------------------------------
#
# Measured BEFORE the rule was written: 0 violations in each. So these two are the "it describes rather
# than breaks" half of the acceptance, and each carries the count of what the rule actually weighed -
# without it, a manifest that had drifted to families throughout would keep this file green while the
# rule held over nothing.


def _placements(text: str) -> dict:
    """A manifest's flat member map, built the way `manifest.load` builds it: the product's tree merged
    onto the catalogue's, so the platform's OWN placed commands are counted too."""
    catalogue = catalogue_mod.load()
    data = yaml.safe_load(text) or {}
    merged = treeform.merge(catalogue.groups, data.get("groups") or {},
                            product_tasks=dict(data.get("tasks") or {}),
                            catalogue_tasks=catalogue.tasks, locked=True)
    return treeform.lower(merged)[1]


def test_the_rule_holds_over_this_repositorys_own_manifest():
    # arrange
    text = (ROOT / "simplon.yaml").read_text(encoding="utf-8")

    # act
    ruled = treeform.check_coordinate_placement(_placements(text), PHASES)

    # assert: green, AND the green is worth something - simplon places `test:typecheck-python` under
    # `test`, `release:tag` under `release` and the catalogue's own `support:install` under `support`,
    # so a run that ruled on fewer than three of them agreed with nothing.
    assert ruled >= 3


def test_this_repositorys_own_manifest_still_loads_with_the_rule_on_the_load_path():
    """The rule costs simplon no rename, which is only true if the real loader still reads the real
    file."""
    # arrange
    text = (ROOT / "simplon.yaml").read_text(encoding="utf-8")

    # act
    mf = manifest_mod.load(text, catalogue=catalogue_mod.load())

    # assert: the two-axis case is the one to name - a family coordinate filed under `build`
    assert mf.commands["build"]["site"].impl


#: agile-cockpit's placements, reproduced here because the manifest itself lives in another repository
#: and this public kernel cannot read it. Every command that carries a COORDINATE is copied verbatim -
#: which is the whole of what this rule reads - and the product-local bodies behind its bare `task:`
#: names are stubbed, since the rule never looks at them.
AGILE_COCKPIT = textwrap.dedent("""
    product: agile-cockpit
    tasks:
      serve: { impl: "orchestrator.cli:serve", help: "Serve it." }
      up:    { impl: "orchestrator.cli:up",    help: "Bring it up." }
      down:  { impl: "orchestrator.cli:down",  help: "Take it down." }
    groups:
      build:
        commands:
          build: { task: "build:image", with: { name: app } }
      test:
        commands:
          typecheck-python: { task: "test:typecheck-python" }
          unit:   { task: "test:gate", with: { name: unit } }
          system: { task: "test:gate", with: { name: system } }
          report: { task: "test:report" }
      support:
        commands:
          serve: { task: serve }
        groups:
          git:
            commands:
              commit: {}
              push: {}
              prune-branches: {}
              submodules: {}
      release:
        commands:
          image: { task: "release:image", with: { name: app } }
      deploy:
        commands:
          up:   { task: up }
          down: { task: down }
          all:  { help: "Build and start.", depends_on: [build, up], stop_on_failure: true }
""")


def test_the_rule_holds_over_the_agile_cockpit_manifest():
    # act
    ruled = treeform.check_coordinate_placement(_placements(AGILE_COCKPIT), PHASES)

    # assert: seven phase-named placements - `build:image`, four under `test`, `release:image` and the
    # catalogue's `support:install`. The count is the point: agile-cockpit is the manifest that leans on
    # phase namespaces hardest, so it is the one whose green says most.
    assert ruled >= 7


def test_the_agile_cockpit_manifest_still_loads_with_the_rule_on_the_load_path():
    # act
    mf = manifest_mod.load(AGILE_COCKPIT, catalogue=catalogue_mod.load())

    # assert
    assert mf.commands["build"]["build"].impl
    assert mf.commands["release"]["image"].impl
