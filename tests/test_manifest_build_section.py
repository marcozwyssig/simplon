"""`build` is a GROUP name and a data-section name at once, and what that costs, driven (si#172).

WHAT THE KERNEL USED TO CLAIM. `src/simplon/tasks/buildfiles.py` reads its `targets:` block out of a
TOP-LEVEL `build:` section, and the comment on `SECTION` said that was safe because a product's command
tree hangs off `groups:`, "so the two names never meet". That sentence was a property the code did not
have.

WHAT WAS MEASURED, on 2026-09-11, over every manifest this kernel can reach - its own `simplon.yaml`,
the five products in `simplon.surface.CONSUMERS`, and `secure-windows-images` on its
`migrate-to-simplon` branch, the seven si#159 read:

    carry a top-level `build:` data section   2   cleon, secure-windows-images
    ... of which hold a `targets:` key        0
    place `build:cmake-files` today           0
    place `build:dotnet-solution` today       0

cleon's section holds `bundle:`, `ant:` and `site:`; secure-windows-images' holds `packer:` and
`templates:`. Both are recorded verbatim below, because a measurement of another repository cannot be
re-taken by a test without a network, and a datum with its date on it is what `simplon.surface` does
with the same problem.

THE ONE THING NOBODY HAD DRIVEN, and it is what decides how bad this is: what the generator does when
it meets a `build:` that holds no `targets:`. The ticket's worry was a silent empty model - si#102
refuses a tree that yields no target, and the question was whether that refusal even fires on this path.
It does not need to. Driven here through a real product CLI:

    cleon's real `build:`, tree with targets    exit 0, three CMakeLists.txt, identical to no section
    swi's real `build:`, tree with targets      exit 0, three CMakeLists.txt, identical to no section
    either one, tree with NO targets            exit 1, si#102's refusal, naming the tree
    a `targets:` of the product's own shape     exit 1, refused by name

**There is no silent empty model on this path at all**, and the reason is si#102's own decision rather
than luck: the TREE is the declaration and `targets:` only adds the dependency edges a directory cannot
show, so an absent `targets:` inside a shared `build:` says exactly what an absent `build:` says. A test
asserting the model came back empty would be asserting a defect; these assert that the generator
GENERATED, and that it generated the same thing.

WHY THE FIX IS A SENTENCE AND NOT A RULE. Refusing a product's top-level `build:` is what si#172 forbids
by name, on si#159's measurement: 11 of the 70 top-level keys across those seven manifests are read by
product task bodies in repositories this kernel cannot see, so a rule over the top-level namespace lands
on names it cannot watch being used and refuses two live products on its first run (si#53, si#85).
Renaming the section away from `build:` is free today - no reachable manifest declares `build: targets:`
- and was rejected for moving the generators' input out of the group whose coordinates produce it, to
buy a collision measured at zero cost, days after si#159 published the name. What is left is the shared-
section rule, published on `building/manifest.md` and held by this module.

WHAT IS STILL SHARP AND IS HELD HERE: inside `build:`, the word `targets` is the kernel's. cleon's Ant
block is one rename away from tripping it (`generate_targets:`, `compile_targets:`, `package_targets:`),
so the two refusals that fire are driven, and what they SAY is asserted - a refusal that blames the
product for a section the product owns is the same defect one level down.

AAA throughout.
"""
from __future__ import annotations

import re

import pytest
import typer
import yaml
from typer.testing import CliRunner

from simplon import catalogue as catalogue_mod
from simplon import cli, context
from simplon.context import ProductContext
from simplon.tasks import buildfiles
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

#: The page that publishes the rule, and the row on it this module holds. A heading rather than a line
#: number, for the reason `test_manifest_top_level` gives: a page moves.
PAGE = ROOT / "site" / "content" / "building" / "manifest.md"

#: cleon's REAL top-level `build:` section, `marcozwyssig/cleon@master`, read 2026-09-11. Verbatim, and
#: trimmed to nothing: the sub-keys are the measurement, and `generate_targets:` under `ant:` is the
#: near-miss this module exists to name - one rename from being `targets:`.
CLEON_BUILD = yaml.safe_load("""
bundle:
  directory: build/bundle
  registry: ghcr.io/marcozwyssig
  repository: asbundle-bundle
  tag: ''
ant:
  generate_file: deploy/provision/asbuild.generate.xml
  package_file: deploy/provision/asbuild.package.xml
  generate_targets: [generate]
  compile_targets: [compile]
  package_targets: [package]
site:
  project: cleon.site
  profile: SDKProfile
""")

#: secure-windows-images' REAL top-level `build:` section, `migrate-to-simplon`, read 2026-09-11. This
#: is the manifest si#159 was reported from, and the one that carries a hand-written comment telling its
#: own authors "DO NOT ADD A `targets:` KEY HERE ... Nothing breaks, and the reason is luck rather than
#: design". That comment is the smell si#172 acts on: a product should not have to explain the kernel's
#: namespace in its own file.
SWI_BUILD = yaml.safe_load("""
packer:
  cpus: 4
  memory: 8192
templates:
  win2022:
    iso_url: https://example.invalid/win2022.iso
""")

#: The smallest C++ tree the generator recognises: one library and one executable, so a run that
#: generates has something to say and a run that does not is visibly empty.
SOURCES = {
    "src/calculator/calculator.h": "#pragma once\nint add(int, int);\n",
    "src/calculator/calculator.cpp": '#include "calculator.h"\nint add(int a, int b) { return a + b; }\n',
    "src/demo/main.cpp": '#include "calculator.h"\nint main() { return add(1, 2) == 3 ? 0 : 1; }\n',
}

#: The command tree of a product that DOES place the generator - which is the whole condition si#172's
#: proof standard names. Without this placement the collision is unreachable and any verdict about it
#: would be about nothing.
GROUPS = {"build": {"commands": {"cmake-files": {"task": "build:cmake-files"}}}}


def _run(monkeypatch, tmp_path, build_section):
    """Build a real product that places `build:cmake-files`, run the command through a real CLI, and
    return what the run said plus every file it wrote.

    NOTHING IS STUBBED, and that is si#172's proof standard rather than thoroughness for its own sake:
    the manifest is written to disk and read back by the task, the Typer app is assembled from that
    manifest against the REAL catalogue, and the command is invoked by the words a person types. The
    collision under test is between a manifest key and a catalogue group name, so a harness that called
    `_declared_targets` directly would have removed the only two things that can collide.

    `build_section` is the product's top-level `build:`, or None for a product that has none - the
    control the other runs are compared against.
    """
    for rel, text in SOURCES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    document: dict = {"product": "demo", "groups": GROUPS}
    if build_section is not None:
        document["build"] = build_section
    text = yaml.safe_dump(document, sort_keys=False)
    (tmp_path / "demo.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))

    app = typer.Typer()
    cli.assemble(app, manifest_mod.load(text, catalogue=catalogue_mod.load()), product="demo")
    result = CliRunner().invoke(app, ["build", "cmake-files"])

    written = {path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
               for path in sorted(tmp_path.rglob("CMakeLists.txt"))}
    return result, written


# --- what a shared `build:` costs the generator ---------------------------------------------------------

def test_a_product_with_no_build_section_generates_its_files(monkeypatch, tmp_path):
    """The control. Bound to a name and asserted, because the two tests below compare against it and a
    control that quietly wrote nothing would make both of them pass by agreeing on emptiness."""
    # arrange / act
    result, written = _run(monkeypatch, tmp_path, None)

    # assert
    assert result.exit_code == 0, result.output
    assert set(written) == {"CMakeLists.txt", "src/calculator/CMakeLists.txt", "src/demo/CMakeLists.txt"}


@pytest.mark.parametrize("section", [CLEON_BUILD, SWI_BUILD], ids=["cleon", "secure-windows-images"])
def test_a_live_products_own_build_section_costs_the_generator_nothing(section, monkeypatch, tmp_path):
    """si#172's proof standard, done literally: a real product `build:` section in a product that places
    `build:cmake-files`.

    The assertion is that the generator GENERATED, and generated the same bytes as the control - not
    that the model came back empty. An empty model is the defect the ticket was written about, so a test
    that asserted it would be pinning the failure in place. What the run actually does is write the
    three files the tree describes, which is si#102's design working: the tree is the declaration and
    `targets:` only adds the edges a directory cannot show, so a section with no `targets:` withholds
    nothing that was ever there to withhold.
    """
    # arrange
    control, control_files = _run(monkeypatch, tmp_path / "control", None)
    assert control.exit_code == 0, control.output

    # act
    result, written = _run(monkeypatch, tmp_path / "shared", section)

    # assert
    assert result.exit_code == 0, (
        f"a product carrying its own `build:` section and placing `build:cmake-files` was refused: "
        f"{result.output!r}")
    assert written == control_files, (
        "the product's own `build:` section changed what the generator wrote, so the two meanings of "
        "the name are not independent after all")
    assert written, "the control and the shared run agree on writing NOTHING, which proves neither"


def test_a_tree_with_no_targets_is_still_refused_when_a_build_section_exists(monkeypatch, tmp_path):
    """si#102's refusal has to survive the shared section, because it is the thing that stands between a
    reader and an empty committed project.

    It is driven with the section PRESENT for exactly one reason: `_declared_targets` returns an empty
    mapping on this path, and an empty mapping is also what a product with no section at all produces.
    If the refusal depended on the section, the two would differ and nobody would find out until a
    manifest with a `build:` block generated a project that configures and compiles nothing.
    """
    # arrange: a product with the section and a tree the generator cannot read a target out of
    (tmp_path / "README.md").write_text("no sources here\n", encoding="utf-8")
    document = yaml.safe_dump({"product": "demo", "groups": GROUPS, "build": SWI_BUILD}, sort_keys=False)
    (tmp_path / "demo.yaml").write_text(document, encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    app = typer.Typer()
    cli.assemble(app, manifest_mod.load(document, catalogue=catalogue_mod.load()), product="demo")

    # act
    result = CliRunner().invoke(app, ["build", "cmake-files"])

    # assert
    assert result.exit_code == 1, result.output
    assert "nothing to build under" in result.output, result.output
    assert not list(tmp_path.rglob("CMakeLists.txt")), "an empty project was written and committed-ready"


# --- the one name inside `build:` that is not the product's -----------------------------------------------

def test_a_products_own_targets_list_is_refused_and_told_to_rename(monkeypatch, tmp_path):
    """The near-miss made real: cleon's Ant block carries `generate_targets:`, `compile_targets:` and
    `package_targets:`, so a product writing plain `targets:` for Ant targets is one rename away.

    What is asserted is not only that it is refused. A refusal that blames the product for a key the
    product owns is si#172 one level down, so the message has to say that the name is taken INSIDE
    `build:` and that the product's key is the one to rename.
    """
    # arrange / act
    result, written = _run(monkeypatch, tmp_path,
                           {"ant": {"file": "build.xml"}, "targets": ["generate", "compile"]})

    # assert
    assert result.exit_code == 1, result.output
    assert "rename" in result.output, (
        f"a product's own `targets:` was refused without telling anybody whose name it is: "
        f"{result.output!r}")
    assert not written


@pytest.mark.parametrize("section", [["generate", "compile"], 4], ids=["a list", "a scalar"])
def test_a_build_section_that_cannot_hold_a_key_says_the_section_is_shared(section, monkeypatch,
                                                                          tmp_path):
    """A `build:` that holds no keys at all - a product writing its build data as a list of steps, or
    as a single value.

    This refusal is right and its old wording was not: it said the section "must be a mapping holding
    `targets:`", which is the kernel claiming a section it shares. The section is the product's; what
    the kernel may say is that it reads one key out of it and that this value has none.

    BOTH SHAPES ARE DRIVEN because the message interpolates `type(section).__name__` into a sentence,
    and a sentence built around a type name is one an unmeasured case renders wrong - the first draft
    of this wording said "a int holds no keys at all" for `build: 4`, and no test would have seen it.
    """
    # arrange / act
    result, written = _run(monkeypatch, tmp_path, section)

    # assert
    assert result.exit_code == 1, result.output
    assert "must be a mapping holding" not in result.output, (
        f"the refusal still tells a product what its own section must hold: {result.output!r}")
    assert "the product's own" in result.output, result.output
    assert not written


# --- the comment, and the page ----------------------------------------------------------------------------

def test_the_kernel_no_longer_says_the_two_names_never_meet():
    """si#172's one unconditional requirement. The claim was wrong for two live manifests on the day it
    was written, and a comment asserting a property the code does not have is how the next reader gets
    it wrong - which is measurable here rather than rhetorical: the same mistake had already reached
    `building/manifest.md`, where the `build:` row named the wrong reader (see the test below)."""
    # arrange
    text = (ROOT / "src" / "simplon" / "tasks" / "buildfiles.py").read_text(encoding="utf-8")

    # act
    head = text.split("SECTION = ", 1)[0]

    # assert
    assert "never meet" not in text, (
        "`buildfiles.py` asserts again that the group name and the section name never meet - measured "
        "on 2026-09-11, cleon and secure-windows-images both carry a top-level `build:` section")
    assert "si#172" in head, "the comment on SECTION no longer says which ticket measured the collision"


def test_the_page_names_the_coordinates_that_actually_read_the_build_section():
    """The manifest page's `build:` row said `support:toolchain`, and `support:toolchain` never reads a
    top-level `build:` at all - it edits `groups: build: commands:`, the GROUP.

    That is not a typo worth a one-line fix and nothing else: it is si#172's own confusion, committed to
    the page si#159 wrote to end exactly this class of guessing, and it is the evidence that the
    collision misleads readers rather than the hypothesis that it might. So the row is derived from
    `catalogue.yaml` and held here: the coordinates that read this section are the ones whose `impl:`
    lands in `simplon.tasks.buildfiles`.
    """
    # arrange
    catalogue = yaml.safe_load((ROOT / "src" / "simplon" / "catalogue.yaml").read_text(encoding="utf-8"))
    module = buildfiles.__name__
    readers = sorted(name for name, body in catalogue["tasks"].items()
                     if isinstance(body, dict) and str(body.get("impl", "")).startswith(f"{module}:"))
    row = next((line for line in PAGE.read_text(encoding="utf-8").splitlines()
                if line.startswith(f"| `{buildfiles.SECTION}:` |")), None)

    # act / assert
    assert readers, f"no catalogue coordinate has an `impl:` in {module} - the derivation is broken"
    assert row is not None, f"{PAGE} has no row for `{buildfiles.SECTION}:`"
    for coordinate in readers:
        assert f"`{coordinate}`" in row, (
            f"{coordinate} reads the `{buildfiles.SECTION}:` section and the page's row does not say "
            f"so: {row}")
    assert "support:toolchain" not in row, (
        f"the page still names `support:toolchain` as a reader of the top-level "
        f"`{buildfiles.SECTION}:` section; it reads `groups: {buildfiles.SECTION}: commands:`, which is "
        f"the group of the same name - si#172's confusion, in the documentation")


def test_the_page_publishes_the_shared_section_rule():
    """The rule si#172 asks to be STATED, held to the page so it cannot quietly go back to being
    discoverable only by reading `buildfiles.py` - which is the trap si#159 closed for `releases:`."""
    # arrange
    text = PAGE.read_text(encoding="utf-8")

    # act
    section = text.split("### `build:` is shared", 1)
    body = section[1].split("\n### ", 1)[0] if len(section) > 1 else ""

    # assert
    assert len(section) > 1, f"{PAGE} no longer publishes the shared-section rule si#172 decided"
    for product in ("cleon", "secure-windows-images"):
        assert product in body, f"the rule does not name {product}, one of the two manifests measured"
    assert re.search(r"[Aa]n \*{0,2}absent\*{0,2} `targets:`", body), (
        "the page states no rule for an absent `targets:` in a `build:` that exists for another reason, "
        "which is the half si#172 says has to be decided either way")
