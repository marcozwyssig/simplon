"""Placement or family: what a coordinate's namespace says about where it may be placed (si#34).

THE RULE, decided in the ticket: a coordinate that starts with one of the PLATFORM'S OWN GROUP NAMES
belongs in exactly that group; any other namespace is a FAMILY, and the product places it where it likes.

NOT "phase or family", and the difference is the owner's call: five of the platform's groups are the
phases of the delivery loop - build, test, release, deploy, monitor - and `support` is the group that
SUPPORTS those five rather than a sixth phase. The rule still covers it, because `support:install` would
otherwise be the one placed coordinate nothing governed, so the rule is stated over GROUPS and "phase"
keeps meaning the five things it means in getting-started.md and in `bootstrap`.

Two axes survive it, which is the whole reason this rule was chosen over the two cheaper ones. `docs:site`
sits under `build` in simplon and could sit under `release` in another product; `build:image` sits under
`build`, always. What the rule removes is the third state - a namespace that reads like a group and is
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

import sitepages
from conftest import ROOT

#: The platform's own top-level groups, spelled out rather than read back out of the catalogue: a test
#: that derived the set from the same file it then asserts the set of would hold nothing.
PLATFORM_GROUPS = frozenset({"build", "test", "release", "deploy", "monitor", "support"})

#: The five of them that are PHASES of the delivery loop. `support` is deliberately absent - it is the
#: group that supports the five, not a sixth of them - and this split is what the wording of the rule,
#: the refusal and the website all have to keep straight.
PHASES = frozenset({"build", "test", "release", "deploy", "monitor"})


def test_the_catalogue_still_declares_exactly_the_six_groups_the_rule_is_written_against():
    """The rule's set is the catalogue's top-level groups, so a seventh group added without a thought
    for this rule must show up here rather than silently widen it."""
    # arrange / act
    groups = frozenset(catalogue_mod.load().groups)

    # assert
    assert groups == PLATFORM_GROUPS


def test_support_is_a_group_the_rule_covers_and_not_a_sixth_phase():
    """The owner's decision, held where it can break. `support` carries a placement exactly like the
    five - `support:install` under `test` is a violation - and it is still not a phase, which is why no
    message and no page may count six of those."""
    # arrange / act / assert: covered by the rule
    with pytest.raises(ValueError):
        treeform.check_coordinate_placement({"test": {"install": {"task": "support:install"}}},
                                            PLATFORM_GROUPS)

    # assert: and not one of the loop's phases
    assert "support" not in PHASES
    assert PHASES < PLATFORM_GROUPS


# --- the rejection ------------------------------------------------------------------------------------


def test_a_group_named_coordinate_placed_in_another_group_is_rejected():
    # arrange: `build:image` is a placement, not a family - it says `build` and means it
    flat = {"test": {"image": {"task": "build:image"}}}

    # act / assert
    with pytest.raises(ValueError, match="one of the platform's own group names"):
        treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)


def test_the_rejection_names_both_coordinates_the_allowed_group_and_the_way_out():
    """The repository's error form: a refusal that names only the offence leaves the reader to guess the
    fix. This one carries the placement it found, the coordinate that forbids it, the group it does
    belong in, and the two ways out."""
    # arrange
    flat = {"test": {"image": {"task": "build:image"}}}

    # act
    with pytest.raises(ValueError) as caught:
        treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)
    message = str(caught.value)

    # assert: both coordinates - the placement in the tree, and the one in the catalogue
    assert "'test image'" in message
    assert "'build:image'" in message
    # the allowed group, named as the manifest spells it
    assert "`groups: build:`" in message
    # and both ways out: move the command, or make the namespace a family
    assert "`groups: build: commands: image:`" in message
    assert "names no group" in message
    assert "docs:site" in message
    # the group set itself, so "does my namespace name one?" is answerable from the message alone -
    # and the enumeration carries the difference rather than flattening six groups into six phases
    assert "build, deploy, monitor, release, support, test" in message
    assert "the phases of the delivery loop, plus the group that supports them" in message
    assert "The phases are" not in message


def test_the_rejection_never_calls_support_a_phase():
    """The contradiction this correction removes: a user who read getting-started.md learned five
    phases, so a refusal listing six would teach them a vocabulary the rest of the site does not use."""
    # arrange: the one coordinate that would make the mistake visible
    flat = {"test": {"install": {"task": "support:install"}}}

    # act
    with pytest.raises(ValueError) as caught:
        treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)
    message = str(caught.value)

    # assert: it is named as a group, never as a phase
    assert "'support' is one of the platform's own group names" in message
    assert "'support' is a phase" not in message


def test_the_rejection_spells_a_nested_group_the_way_the_manifest_does():
    """The tree is dotted; the CLI and every manifest are spaced. `support.git` appears in no file the
    reader can edit, so the message must not send them looking for it."""
    # arrange
    flat = {"support.git": {"image": {"task": "build:image"}}}

    # act
    with pytest.raises(ValueError) as caught:
        treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)
    message = str(caught.value)

    # assert
    assert "command 'support git image'" in message
    assert "under 'support git'" in message
    assert "support.git" not in message


def test_the_rejection_reaches_a_product_through_the_loader():
    """The check has to be ON the load path, not merely importable: si#33 moved every product onto
    `treeform.merge`, and a rule wired anywhere else would hold over nothing a product actually runs."""
    # arrange: a catalogue with a real group-named coordinate, and a manifest that misfiles it
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


def test_the_same_coordinate_under_its_own_group_loads():
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


def test_one_family_coordinate_placed_in_two_different_groups_passes():
    """The capability the two rejected alternatives would have cost. `docs:site` is a family: it says
    what the task IS and nothing about where it runs, so two products may file it differently and this
    check must have no opinion about either."""
    # arrange: the same coordinate, two groups - as it would look across two products
    under_build = {"build": {"site": {"task": "docs:site"}}}
    under_release = {"release": {"site": {"task": "docs:site"}}}

    # act
    ruled_build = treeform.check_coordinate_placement(under_build, PLATFORM_GROUPS)
    ruled_release = treeform.check_coordinate_placement(under_release, PLATFORM_GROUPS)

    # assert: neither is rejected, and the count says the rule ruled on NEITHER - a family is outside it
    assert (ruled_build, ruled_release) == (0, 0)


def test_a_group_named_coordinate_under_its_own_group_is_ruled_on_rather_than_merely_not_rejected():
    """The count is the difference between "the rule agreed" and "the rule never looked"."""
    # arrange
    flat = {"build": {"image": {"task": "build:image"}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)

    # assert
    assert ruled == 1


def test_a_group_named_coordinate_in_a_subgroup_of_its_group_passes():
    """Only the first path segment decides. `support git` is still `support`, so a coordinate filed one
    shelf deeper inside its own group runs in the group it names."""
    # arrange
    flat = {"support.git": {"install": {"task": "support:install"}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)

    # assert
    assert ruled == 1


def test_a_bare_task_name_is_outside_the_rule_entirely():
    """A name without a colon is this manifest's own task, not a coordinate - there is no namespace to
    read, and a product's `wheel` under any group it likes is none of this rule's business."""
    # arrange
    flat = {"test": {"wheel": {"task": "wheel"}, "all": {"depends_on": ["wheel"]}}}

    # act
    ruled = treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)

    # assert
    assert ruled == 0


def test_with_no_catalogue_there_are_no_groups_and_every_namespace_is_a_family():
    """"Which names carry a placement" is the platform's statement. A loader handed no catalogue has no
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
    ruled = treeform.check_coordinate_placement(_placements(text), PLATFORM_GROUPS)

    # assert: green, AND the green is worth something - simplon places `test:typecheck-python` under
    # `test`, `release:tag` under `release` and the catalogue's own `support:install` under `support`,
    # so a run that ruled on fewer than three of them agreed with nothing. The third of those is the
    # KERNEL's own placement, reached because `_placements` merges: the rule holds over the catalogue's
    # tree, not only over what a product wrote.
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
    ruled = treeform.check_coordinate_placement(_placements(AGILE_COCKPIT), PLATFORM_GROUPS)

    # assert: seven group-named placements - `build:image`, four under `test`, `release:image` and the
    # catalogue's `support:install`. The count is the point: agile-cockpit is the manifest that leans on
    # group namespaces hardest, so it is the one whose green says most.
    assert ruled >= 7


def test_the_agile_cockpit_manifest_still_loads_with_the_rule_on_the_load_path():
    # act
    mf = manifest_mod.load(AGILE_COCKPIT, catalogue=catalogue_mod.load())

    # assert
    assert mf.commands["build"]["build"].impl
    assert mf.commands["release"]["image"].impl


# --- the website quotes the refusal, so the website is held to it --------------------------------------


#: The chapter that states the rule, and the heading whose block quote reproduces the load error.
CHAPTER = sitepages.chapter("task-and-command.md")
REFUSAL_HEADING = "### The refusal"


def _quoted_refusal() -> str:
    """The block quote under "The refusal", unwrapped back into one line.

    The page reproduces a real load error, which is two sources for one string and therefore something
    that drifts - the first draft of this section quoted it with a full stop the real message does not
    have. Reading it back out and comparing beats proofreading it.
    """
    lines = CHAPTER.read_text(encoding="utf-8").split("\n")
    start = lines.index(REFUSAL_HEADING)
    quoted = []
    for line in lines[start:]:
        if line.startswith("> "):
            quoted.append(line[2:].strip())
        elif quoted:
            break
    return " ".join(" ".join(quoted).replace("`", "").split())


def test_the_website_quotes_the_refusal_word_for_word():
    # arrange: the very placement the page uses as its example
    flat = {"test": {"image": {"task": "build:image"}}}

    # act
    with pytest.raises(ValueError) as caught:
        treeform.check_coordinate_placement(flat, PLATFORM_GROUPS)
    real = " ".join(str(caught.value).replace("`", "").split())

    # assert: not "close enough" - the page shows a reader what they will see, so a full stop the
    # loader does not print is a small lie in the one place a reader checks their own output against
    assert _quoted_refusal() == real
