"""si#388: two load outcomes that could not tell "nothing to do" from "failed".

A misspelt area (`ic:` for `ci:`) loaded as a product data section and lost its commands; an empty document
loaded as a product with no name and only the catalogue's commands. Both are refused now, by name."""
import pathlib
import re

import pytest

import realmanifests

from simplon.manifest import catalogue
from simplon.manifest import load as manifest
from simplon.tasks.migrate import migrate_text

_SIMPLON = (pathlib.Path(__file__).resolve().parents[2] / "simplon.yaml").read_text(encoding="utf-8")


_OK_PRODUCT = "product: demo\n"


def _misspell(text: str, area: str, typo: str) -> str:
    new, count = re.subn(rf"^{area}:", f"{typo}:", text, count=1, flags=re.M)
    assert count == 1, f"simplon.yaml has no top-level `{area}:` to misspell"
    return new


@pytest.mark.parametrize("area, typo", [("ci", "ic"), ("support", "suport")])
def test_a_misspelt_area_is_refused_with_the_area_it_meant(area, typo):
    with pytest.raises(ValueError) as refused:
        manifest.load(_misspell(_SIMPLON, area, typo), catalogue=catalogue.load())
    assert f"declares `{typo}:`, which is not an area, yet it carries `{typo}." in str(refused.value)
    assert f"Did you mean `{area}:`?" in str(refused.value)


def test_a_misspelt_cd_with_its_matrix_is_refused():
    text = _OK_PRODUCT + "dc:\n  default: dev\n  environments:\n    dev: {}\n"
    with pytest.raises(ValueError) as refused:
        manifest.load(text, catalogue=catalogue.load())
    assert "declares `dc:`, which is not an area, yet it carries `dc.environments`" in str(refused.value)
    assert "Did you mean `cd:`?" in str(refused.value)


def test_a_data_section_without_commands_still_loads():
    # #159: a top-level key the kernel does not read is product data, and stays so - even one with
    # `impl:` inside it, which netctl's and swi's `suites:` gates carry.
    text = _SIMPLON + "\npacker:\n  default: dev\n  build: { cpus: 2 }\n  gates:\n    - { impl: \"x.y:z\" }\n"
    manifest.load(text, catalogue=catalogue.load())


def test_every_reachable_manifest_still_loads_after_migration():
    # The rule's measured population: no data section of the eight carries `commands:`.
    paths = sorted((pathlib.Path(__file__).parent / "fixtures" / "manifests").glob("*.yaml"))
    assert len(paths) == 8, [p.name for p in paths]
    for path in paths:
        text = realmanifests.text(path.stem)  # with each product's own hand edits (cleon, firn)
        result = migrate_text(text)
        assert result.status == "migrated", (path.name, result.reason)
        try:
            manifest.load(result.text, catalogue=catalogue.load())
        except ValueError as exc:
            # the release rule (si#344 C.3) is the one refusal a migrated fixture may meet, and only the
            # products measured to release untested
            assert path.stem in realmanifests.RELEASE_RULE_BILL, (path.name, str(exc))
            assert "no test produces a result about it" in str(exc), (path.name, str(exc))
            manifest.load(realmanifests.answer_release_rule(path.stem, result.text), catalogue=catalogue.load())


@pytest.mark.parametrize("text", ["", "---\n", "# only a comment\n"])
def test_an_empty_manifest_is_refused_at_load(text):
    with pytest.raises(ValueError, match="is empty: it declares no `product:`"):
        manifest.load(text, catalogue=catalogue.load())


def test_a_list_document_is_refused_at_load():
    with pytest.raises(ValueError, match="is not a mapping: found list"):
        manifest.load("[]\n", catalogue=catalogue.load())


@pytest.mark.parametrize("text, found", [("", "nothing"), ("---\n", "nothing"), ("[]\n", "a list"),
                                         ("just text\n", "a str")])
def test_migrate_refuses_a_document_that_is_not_a_manifest(text, found):
    result = migrate_text(text)
    assert result.status == "refused", result.status
    assert f"the document holds {found}, not a mapping" in result.reason
