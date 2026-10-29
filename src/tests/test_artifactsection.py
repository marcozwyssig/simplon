"""The `artifacts:` section, one reading for every reader (si#344 B2): a kind on every entry, a reader that
accepts its kind and every kind that refines it, the generated shapes, and what each reader needs.
AAA throughout."""
import importlib
import re
import sys
import types

import pytest
import yaml

import simplon.model
from simplon.manifest import artifactsection, catalogue
from simplon.model import artifactschema
from simplon.manifest import load as manifest
from simplon.tasks.migrate import migrate_text

import realmanifests
from test_manifest import _OK

PARENTS = artifactschema.REFINES
PRODUCTS = sorted(p.stem for p in (realmanifests.FIXTURES / "golden").glob("*.json"))
KINDS = "artifact, image, directory, file, homebrew-formula, site, nuget, maven, conan, test-result, release-notes, tag, release, github-release, release-assets"


@pytest.mark.parametrize("wanted,kind,accepted", [
    ("directory", "directory", True),
    ("directory", "site", True),
    ("artifact", "site", True),
    ("site", "directory", False),
    ("image", "directory", False),
    ("image", "nosuch", False),
])
def test_a_reader_accepts_its_kind_and_every_kind_that_refines_it(wanted, kind, accepted):
    # act / assert: the promised form and the general one agree
    assert artifactsection.accepts(PARENTS, wanted, kind) is accepted
    assert artifactsection.is_a(kind, wanted) is accepted


def test_a_parent_map_with_a_circle_is_answered_not_looped():
    # act / assert
    assert artifactsection.accepts({"a": "b", "b": "a"}, "c", "a") is False


@pytest.mark.parametrize("product", PRODUCTS)
def test_every_entry_of_every_migrated_real_manifest_passes_the_load_time_check(product):
    # arrange: Review Focus 1 - no reachable manifest may be refused for a key a reader accepted before
    document = yaml.safe_load(migrate_text(realmanifests.text(product)).text)

    # act: raises on the first entry it refuses
    artifactsection.check(document, catalogue.load().kinds, f"{product}.yaml")

    # assert
    assert all(isinstance(body, dict) and body.get("kind") in PARENTS
               for body in (document.get("artifacts") or {}).values())


def test_the_load_time_check_ruled_on_every_entry_the_fixtures_carry():
    # act: asbundle and swi carry none, so the parametrisation above is vacuous for them (review M7)
    entries = sum(len(yaml.safe_load(migrate_text(realmanifests.text(p)).text).get("artifacts") or {})
                  for p in PRODUCTS)

    # assert: netctl 10, biz-cockpit 2, firn 2, agile-cockpit 1, cleon 1, simplon 1 - measured 2026-10-12
    assert entries == 17


@pytest.mark.parametrize("section,sentence", [
    ("[a, b]", "demo.yaml: `artifacts:` must be a mapping of artifact name to its entry, found list"),
    ("{ app: 'demo:local' }",
     "demo.yaml: 'artifacts.app' is not a mapping - an artifact declares its `kind:` and its keys"),
    ("{ app: { kind: widget } }",
     "demo.yaml: 'artifacts.app' declares `kind: widget`, which the catalogue does not declare; the kinds "
     f"are: {KINDS}"),
    ("{ app: { registry: r } }",
     "demo.yaml: 'artifacts.app' declares no `kind:`; every entry names one of the catalogue's kinds: "
     f"{KINDS}"),
    ("{ app: { kind: image, platforms: linux/amd64 } }",
     "demo.yaml: 'artifacts.app': 'platforms' must be a list of non-empty strings, e.g. [a, b]"),
    ("{ app: { kind: conan, mediatype: x } }",
     "demo.yaml: 'artifacts.app': 'mediatype' is not a key of the `conan` artifact - did you mean "
     "'media_type'?; it takes kind, media_type, path, registry, repository, tag"),
])
def test_the_load_time_check_names_the_entry_and_the_key(section, sentence):
    # arrange
    document = yaml.safe_load(f"artifacts: {section}\n")

    # act
    with pytest.raises(ValueError) as caught:
        artifactsection.check(document, PARENTS, "demo.yaml")

    # assert
    assert str(caught.value) == sentence


def test_a_number_loads_as_a_value():
    # act: decision A - `tag: 25` loads, as the readers' `str(...)` always read it
    artifactsection.check({"artifacts": {"app": {"kind": "maven", "tag": 25}}}, PARENTS, "demo.yaml")
    loaded = artifactschema.validate("maven", {"kind": "maven", "tag": 25})

    # assert: a value, the text the readers always made of it - not only "nothing raised"
    assert loaded.tag == "25"


def test_the_catalogue_is_the_authority_at_load():
    # arrange: a catalogue that declares fewer kinds than the generated schema (review M10)
    document = {"artifacts": {"app": {"kind": "image"}}}

    # act
    with pytest.raises(ValueError) as caught:
        artifactsection.check(document, {"artifact": ""}, "demo.yaml")

    # assert
    assert str(caught.value) == ("demo.yaml: 'artifacts.app' declares `kind: image`, which the catalogue does "
                                 "not declare; the kinds are: artifact")


def test_the_loader_checks_against_the_catalogues_kinds():
    # act / assert
    with pytest.raises(ValueError, match="declares `kind: widget`, which the catalogue does not declare"):
        manifest.load("product: demo\nartifacts:\n  app: { kind: widget }\n", catalogue=catalogue.load(),
                      manifest_path="demo.yaml")


def test_a_load_without_a_catalogue_checks_against_the_generated_kinds():
    # act / assert: a catalogue-less load (most unit tests) still checks - it does not skip
    with pytest.raises(ValueError, match=re.escape(f"declares `kind: widget`, which the catalogue does not "
                                                   f"declare; the kinds are: {KINDS}")):
        manifest.load(_OK + "artifacts:\n  app: { kind: widget }\n")


def test_a_use_of_an_entry_of_another_kind_names_both_kinds():
    # act
    with pytest.raises(ValueError) as caught:
        artifactsection.entry({"app": {"kind": "image"}}, "app", artifactschema.DirectoryEntry, "demo.yaml",
                              "release:artifact")

    # assert
    assert str(caught.value) == (
        "demo.yaml: 'artifacts.app' is of kind 'image', and this task reads a 'directory' or a kind that "
        "refines it - name an entry of that kind, or change the entry's `kind:`")


def test_a_use_of_an_entry_that_is_not_a_mapping_is_refused_before_the_schema_sees_it():
    # act: the generated `validate` would answer a non-mapping with pydantic's own error, which carries no
    # `raise` the census can count - so `entry` refuses it first, in its own sentence (Task 1's review)
    with pytest.raises(ValueError) as caught:
        artifactsection.entry({"app": "demo:local"}, "app", artifactschema.DirectoryEntry, "demo.yaml",
                              "release:artifact")

    # assert
    assert str(caught.value) == ("demo.yaml: 'artifacts.app' is not a mapping - an artifact declares its "
                                 "`kind:` and its keys")


@pytest.mark.parametrize("body,said", [({"kind": "widget"}, "'widget'"), ({"kind": 3}, "3")])
def test_a_use_of_an_entry_of_no_known_kind_is_refused_before_the_schema_sees_it(body, said):
    # act: the generated `validate` takes the kind it is HANDED and never asks the body's
    # (`validate("image", {"kind": "nuget"})` is an ImageEntry), so `entry` rules on the body's kind itself
    with pytest.raises(ValueError) as caught:
        artifactsection.entry({"app": body}, "app", artifactschema.DirectoryEntry, "demo.yaml",
                              "release:artifact")

    # assert
    assert str(caught.value) == (f"demo.yaml: 'artifacts.app' names no kind this kernel knows ({said}); "
                                 f"the kinds are: {KINDS}")


def test_a_use_of_an_entry_with_no_kind_says_it_declares_none():
    # act
    with pytest.raises(ValueError) as caught:
        artifactsection.entry({"app": {"registry": "r"}}, "app", artifactschema.DirectoryEntry, "demo.yaml",
                              "release:artifact")

    # assert: the wording `check` uses, not "names no kind ... (None)"
    assert str(caught.value) == (f"demo.yaml: 'artifacts.app' declares no `kind:`; the kinds are: {KINDS}")


def test_a_port_that_binds_another_parameter_is_read_by_that_parameter():
    # arrange: si#536's two artifact ports bind `wheel` and `formula`, so neither is in READERS or NEEDS
    section = {"dist": {"kind": "directory"}, "f": {"kind": "homebrew-formula", "path": "f.rb"}}

    # act / assert: each port reads its own kind and its own needs, and no port reads by `name`
    got = artifactsection.entry(section, "f", artifactschema.Homebrew_formulaEntry, "demo.yaml",
                                "build:homebrew-formula", param="formula")
    assert got.path == "f.rb"
    with pytest.raises(ValueError, match="declares no `path:`, which build:homebrew-formula needs"):
        artifactsection.entry(section, "dist", artifactschema.DirectoryEntry, "demo.yaml", "build:homebrew-formula",
                              param="wheel")
    with pytest.raises(KeyError):
        artifactsection.entry(section, "dist", artifactschema.DirectoryEntry, "demo.yaml", "build:homebrew-formula")


def test_a_use_names_the_first_key_its_coordinate_needs_and_all_of_them():
    # act
    with pytest.raises(ValueError) as caught:
        artifactsection.entry({"lib": {"kind": "nuget", "registry": "nuget.pkg.github.com/o"}}, "lib",
                              artifactschema.NugetEntry, "demo.yaml", "release:nuget")

    # assert: decision B - the same entry is enough for `build:nuget-config`, which needs a registry only
    assert str(caught.value) == ("demo.yaml: 'artifacts.lib' declares no `image:`, which release:nuget needs - "
                                 "it reads registry, image, path")
    assert artifactsection.entry({"lib": {"kind": "nuget", "registry": "nuget.pkg.github.com/o"}}, "lib",
                                 artifactschema.NugetEntry, "demo.yaml", "build:nuget-config").registry


def test_a_use_of_a_refining_kind_is_accepted_and_typed():
    # act
    entry = artifactsection.entry(
        {"docs": {"kind": "site", "registry": "r", "repository": "d", "media_type": "m", "path": "build/site"}},
        "docs", artifactschema.DirectoryEntry, "demo.yaml", "release:artifact")

    # assert
    assert isinstance(entry, artifactschema.SiteEntry) and entry.path == "build/site"


def test_a_broken_schema_names_its_recovery(monkeypatch):
    # arrange: what firn#966 leaves - a module with nothing in it (an id-line-only file imports as this)
    empty = types.ModuleType("simplon.model.artifactschema")
    monkeypatch.setitem(sys.modules, "simplon.model.artifactschema", empty)
    monkeypatch.setattr(simplon.model, "artifactschema", empty)
    monkeypatch.delitem(sys.modules, "simplon.manifest.artifactsection")

    # act
    with pytest.raises(ImportError) as caught:
        importlib.import_module("simplon.manifest.artifactsection")

    # assert: the sentence IS the way out, because no `./simplon.sh` command runs until it is taken
    assert "git checkout -- src/simplon/model/artifactschema.py" in str(caught.value)
    assert "./simplon.sh build model" in str(caught.value)


def test_every_reader_module_names_exactly_the_coordinates_the_catalogue_routes_to_it():
    # arrange: a coordinate passed to `entry` is how a body learns its needs; a wrong one would apply
    # another reader's needs, so each module's literals are held to the catalogue
    tasks = catalogue.load().tasks
    routed: dict[str, set[str]] = {}
    for coordinate in artifactschema.READERS:
        # the body's module, as the model names it - since si#400 4c the catalogue's `impl` names the class
        routed.setdefault(artifactschema.BODIES[coordinate].split(":")[0], set()).add(coordinate)

    # act
    named = {module: set(re.findall(r'"([a-z]+:[a-z-]+)"', importlib.import_module(module).__loader__
                                    .get_source(module))) & set(artifactschema.READERS)
             for module in routed}

    # assert
    assert named == routed
