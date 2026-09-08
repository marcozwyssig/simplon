"""Every surface that names a group, and what a declared `help:` does on each of them (si#77).

WHY THIS IS A MODULE AND NOT ONE MORE TEST. si#75 asked "is the group's `help:` rendered?", found one
renderer that ignored it, fixed that one, and pinned it against a second with
`test_both_mechanisms_render_the_same_group_blurb`. Two out of four. The generated command reference kept
printing the invented sentence for another release, because nothing anywhere said how many surfaces there
are - so the question "did we get them all?" had no place to be asked and no way to be answered.

That is si#61's lesson at a level above refusals: A CENSUS COUNTS ONLY WHAT IT IS POINTED AT, and here
there was no census at all. This module is it.

THE POPULATION IS DERIVED, not listed. A surface reaches the command tree through `Manifest.taxonomy()`,
and that call is in the source rather than in anybody's memory, so `_taxonomy_consumers` reads the call
sites off the kernel. What each consumer DOES with the tree is declared - that is the same division the
refusal census makes, and for the same reason: a module that starts reading the taxonomy tomorrow cannot
join quietly, whether or not it renders anything.

THE FOUR SURFACES, and the fourth is a limit rather than a defect:

  - `simplon.cli.assemble`      the running `--help`                   carries the description
  - `simplon.taskgen.render`    the generated command module           carries the description
  - `simplon.tasks.cliref`      the generated command reference page   carries it since si#77
  - `simplon.completiongen`     the committed shell completion         NAMES ONLY, measured below

The completion is bash, and its answer is a word list handed to `compgen -W`. There is no slot in that
mechanism for a description - not a truncated one, not an aligned one - so `test_the_completion_offers_
names_and_no_descriptions` records the absence as a measurement rather than leaving it as an omission
somebody rediscovers. Recording a limit is what stops it being mistaken for the defect si#77 reports.

AAA throughout.
"""
import ast
import types

import click
import pytest
import typer
from click.testing import CliRunner
from typer.main import get_command

from simplon import catalogue as catalogue_mod
from simplon import cli, completiongen, taskgen
from simplon.orchestrator import manifest as manifest_mod
from simplon.tasks import cliref

from conftest import ROOT

SRC = ROOT / "src" / "simplon"

#: The accessor every surface reaches the command tree through. Read off the call sites rather than
#: assumed, so a rename turns `test_every_taxonomy_consumer_is_a_counted_surface` red instead of quietly
#: emptying the population.
TAXONOMY_ACCESSOR = "taxonomy"

#: What each surface does with a group's declared description. The POPULATION is computed; this is the
#: classification, and it is the half a human owes an answer for.
CARRIES = "shows the group's declared description"
NAMES_ONLY = "offers the group's name and no text at all"

SURFACES = {
    "cli": CARRIES,
    "taskgen": CARRIES,
    "tasks.cliref": CARRIES,
    # bash hands `compgen -W` a list of WORDS. A description is not a word, and there is no second column
    # in that mechanism to put one in - see this module's head.
    "completiongen": NAMES_ONLY,
}

#: A module that consults the taxonomy and renders nothing, with the reason. `environments` asks whether a
#: token names a group in order to decide whether it is an environment name; nothing it answers reaches a
#: screen, so a group description would have nowhere to arrive.
NOT_A_SURFACE = {
    "environments": "asks whether a token names a group, to tell an environment name from a group token - "
                    "it renders nothing",
}

#: The platform's tree. Every group lives here because that is what the kernel's own catalogue does and
#: what `treeform.merge` enforces once a catalogue declares any group at all: the platform owns which
#: groups exist, so a product contributes MEMBERS and never restates a group's shape. si#75's fixture in
#: `tests/test_taskgen.py` covers the other arrangement - a manifest with no catalogue, declaring its own
#: groups and their `help:` - so between the two every source of a description is exercised.
_CATALOGUE = """
groups:
  build: { help: "Produce the artefacts." }
  # The one group with no description, so "carries the declaration" cannot be satisfied by a renderer that
  # prints the same synthesized sentence for every group.
  code: {}
  deploy: { help: "Put them into an environment.", env_first: true }
  support:
    help: "Host preflight, environment introspection and host tooling."
    commands:
      doctor: { task: "support:doctor" }
    groups:
      git:
        help: "Version-control helpers."
        commands:
          push: { task: "vcs:push" }
tasks:
  build:wheel: { impl: "blurb_impls:wheel", help: "Build the wheel." }
  support:doctor: { impl: "blurb_impls:doctor", help: "Check the host." }
  vcs:push: { impl: "blurb_impls:push", help: "Push." }
"""

#: The product, contributing a member to three of the platform's groups: a plain one, an env-first one, and
#: the one whose node declares no description at all. `support` and `support.git` reach the surface through
#: the catalogue's own placements, which is how the kernel's own nested group gets there too.
_MANIFEST = """
product: sample
default: dev
environments:
  dev: { backend: local }
tasks:
  up: { impl: "blurb_impls:up", help: "Bring it up." }
  fmt: { impl: "blurb_impls:fmt", help: "Format." }
groups:
  build:
    commands:
      wheel: { task: "build:wheel" }
  code:
    commands:
      fmt: { task: "fmt" }
  deploy:
    commands:
      up: { task: "up" }
"""

#: group path -> the description its node declares. Read off the two source files by the loader itself,
#: rather than repeated here: the manifest above is the fixture, and what the loader made of it is the
#: expectation.
DECLARING = ("build", "deploy", "support", "support.git")

#: The one group above that declares nothing, so an assertion about the others cannot pass by accident on a
#: renderer that prints the same sentence everywhere.
SILENT = "code"


@pytest.fixture
def impls():
    import sys

    module = types.ModuleType("blurb_impls")
    for name in ("wheel", "up", "push", "fmt", "doctor"):
        setattr(module, name, (lambda: 0))
    sys.modules["blurb_impls"] = module
    try:
        yield
    finally:
        del sys.modules["blurb_impls"]


def _loaded():
    return manifest_mod.load(_MANIFEST, catalogue=catalogue_mod.loads(_CATALOGUE))


def _declared(mf, group: str) -> str:
    """The description the loaded tree carries for a group path, refusing to answer for a node that is not
    there - an expectation of "" would make every comparison below hold vacuously."""
    node = mf.taxonomy().resolve_path(group)
    if node is None:
        raise ValueError(f"the fixture manifest has no group '{group}'")
    return node.help


def _cli_text(mf) -> str:
    """What the running application puts on screen: the root listing plus every group's own `--help`."""
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="sample root")
    cli.assemble(app, mf, product="sample")
    root = get_command(app)
    runner = CliRunner()
    out = [runner.invoke(root, ["--help"]).output]
    for group in (*DECLARING, SILENT):
        out.append(runner.invoke(root, [*group.split("."), "--help"]).output)
    return "\n".join(out)


def _taskgen_text(mf) -> str:
    return taskgen.render(mf, source="sample.yaml", product="sample")


def _cliref_text(mf) -> str:
    app = typer.Typer(add_completion=False, no_args_is_help=True, help="sample root")
    cli.assemble(app, mf, product="sample")
    root = get_command(app)
    return cliref.render(cliref.entries(root, env_first=mf.taxonomy().group_requires_env,
                                        group_blurb=cliref._declared_blurb(mf)),
                         product="sample", title="sample commands")


def _completion_text(mf) -> str:
    return completiongen.render(completiongen.tree(mf, environments=("dev",)),
                                product="sample", source="sample.yaml")


#: One renderer per surface, producing the text that surface puts in front of a human.
RENDER = {
    "cli": _cli_text,
    "taskgen": _taskgen_text,
    "tasks.cliref": _cliref_text,
    "completiongen": _completion_text,
}


def _taxonomy_consumers() -> set[str]:
    """Every kernel module that asks a manifest for its command tree, read off the call sites.

    Raises on an empty result: a population of nothing would make the accounting test below pass while
    describing no surface at all, which is the shape of defect this whole module is about.
    """
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Call) and getattr(node.func, "attr", "") == TAXONOMY_ACCESSOR
               for node in ast.walk(tree)):
            parts = list(path.relative_to(SRC).with_suffix("").parts)
            found.add(".".join(parts))
    if not found:
        raise ValueError(
            f"no kernel module calls `.{TAXONOMY_ACCESSOR}()` - the walk is broken, not the kernel")
    return found


# --- the population -------------------------------------------------------------------------------------


def test_every_taxonomy_consumer_is_a_counted_surface_or_declared_not_to_be():
    """The check si#77 asks for, and the one that did not exist when the reference was missed.

    A module that reads the command tree either renders it to a human - and then a declared description has
    to arrive on it - or it does not, and says so here with the reason. A new one is neither, and this goes
    red naming it.
    """
    # arrange
    consumers = _taxonomy_consumers()

    # act
    unaccounted = sorted(consumers - set(SURFACES) - set(NOT_A_SURFACE))

    # assert
    assert unaccounted == [], (
        "a module reads the command taxonomy and is in neither half of this census. If it shows a group to "
        "a human, put it in SURFACES and say whether a declared description reaches it; if it does not, say "
        f"in NOT_A_SURFACE what it does instead: {unaccounted}")

    # assert: and the declared halves still describe modules that exist, so neither can outlive its subject
    assert set(SURFACES) | set(NOT_A_SURFACE) <= consumers, (
        f"a declared entry names a module that no longer reads the taxonomy: "
        f"{sorted((set(SURFACES) | set(NOT_A_SURFACE)) - consumers)}")

    # assert: and there really were several, so the accounting above ruled on something
    assert len(SURFACES) > 2
    assert len(consumers) > len(NOT_A_SURFACE)


def test_every_counted_surface_has_a_renderer_to_measure_it_with():
    """SURFACES and RENDER are two lists of the same thing, and two lists of the same thing drift."""
    # assert
    assert set(RENDER) == set(SURFACES)


# --- what a declared description does on each of them -----------------------------------------------------


@pytest.mark.parametrize("surface", sorted(name for name, kind in SURFACES.items() if kind == CARRIES))
def test_a_declared_group_description_arrives_on_every_surface_that_carries_text(surface, impls):
    """ACCEPTANCE. One manifest, one declaration per group, and the same sentence has to come out of every
    renderer that has room for a sentence.

    This is what si#75's two-mechanism test grows into. The failing case it now covers is the one si#77
    reports: the generated reference named the group, printed how it is addressed, and left out what it IS.
    """
    # arrange
    mf = _loaded()

    # act
    text = RENDER[surface](mf)

    # assert: every declared description reaches this surface
    for group in DECLARING:
        declared = _declared(mf, group)
        assert declared, f"the fixture's group '{group}' declares no description, so this proves nothing"
        assert declared in text, (
            f"the {surface} surface names group '{group}' and does not carry its declared description "
            f"{declared!r}. A description declared once has to arrive everywhere the group is named")

    # assert: the surface really named the silent group too, so the loop above is about the DESCRIPTION and
    # not about which groups a renderer happens to include
    assert SILENT in text


@pytest.mark.parametrize("surface", sorted(SURFACES))
def test_every_surface_names_every_group_the_manifest_declares(surface, impls):
    """The premise the test above rests on: these four really are surfaces for the same taxonomy. Without
    it, a renderer that had quietly stopped emitting a group would satisfy "the description arrives
    wherever the group is named" by naming it nowhere."""
    # arrange
    mf = _loaded()

    # act
    text = RENDER[surface](mf)

    # assert
    for group in (*DECLARING, SILENT):
        assert group.rsplit(".", 1)[-1] in text, (
            f"the {surface} surface does not name group '{group}' at all")


def test_the_completion_offers_names_and_no_descriptions(impls):
    """The fourth surface, measured rather than assumed - the ticket asks for exactly this.

    bash's `compgen -W` takes a list of words. There is no place in it for a description, so the completion
    offers the group's name and nothing else, and this records that as the mechanism's limit. It is here so
    that the parametrised test above can EXCLUDE it honestly instead of silently.
    """
    # arrange
    mf = _loaded()

    # act
    text = RENDER["completiongen"](mf)

    # assert: the names are all there
    for group in (*DECLARING, SILENT):
        assert f"'{group.rsplit('.', 1)[-1]}'" in text, f"the completion does not offer group '{group}'"

    # assert: and not one description, which is what NAMES_ONLY claims
    carried = [group for group in DECLARING if _declared(mf, group) in text]
    assert carried == [], (
        f"the completion now carries a group description for {carried} - if bash can show one after all, "
        f"this surface is no longer NAMES_ONLY and belongs with the other three")


def test_the_generated_reference_shows_what_a_group_is_before_how_it_is_addressed(impls):
    """si#77's own defect, pinned at the place it lived rather than only in the aggregate above.

    The page used to head each section with the group's name and then say only how the group is addressed -
    true, and not what the reader asked. Both sentences are there now, and their ORDER is the assertion:
    what the group is, then how to type it.
    """
    # arrange
    mf = _loaded()

    # act
    text = RENDER["tasks.cliref"](mf)
    section = text.split("## support git", 1)[1].split("###", 1)[0]

    # assert
    assert "Version-control helpers." in section
    assert "Environment-agnostic" in section
    assert section.index("Version-control helpers.") < section.index("Environment-agnostic"), (
        "the page says how the group is addressed before it says what the group is")

    # assert: a group that declares nothing gets the note alone rather than an invented sentence
    silent = text.split(f"## {SILENT}", 1)[1].split("###", 1)[0]
    assert "Environment-agnostic" in silent
    assert f"{SILENT} commands." not in silent, (
        "the page prints the synthesized sentence for a group that declared none - that is the invented "
        "wording si#75 removed from the other two surfaces")
