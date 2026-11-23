"""si#858: `ci: { skip: "<reason>" }` on a command - the opt-out a command uses to stay out of the derived CI.

A derived CI workflow runs every leaf a manifest places under the CI phases. A command that cannot run on a
hosted runner says so, and says why: the reason is read into `TaskCommand.ci_skip`, so a reader of the
manifest learns why a leaf is absent from the workflow. `ci` is also the name of the manifest's top-level
area, so a test holds that a command's `ci:` is read as the command key it is.

si#860 widens the same `ci:` to the variant keys (`cadence`, `platforms`, `python`, `timeout_minutes`,
`emulates`), read into `TaskCommand.ci`, a `CiVariant`; the tests for them follow the skip tests.
"""
from __future__ import annotations

import re
import textwrap

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest
from simplon.model.command import CiVariant
from simplon.model.workflowschema import PLATFORMS

from conftest import ROOT


def _loaded(written: str):
    return manifest.load(textwrap.dedent("""
        tasks:
          ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
        ci:
          test:
            commands:
              lab: { task: ship, %s }
              all: { depends_on: [lab], help: "All." }
        """) % written, catalogue=catalogue.load())


def test_a_skip_with_its_reason_is_read():
    loaded = _loaded('ci: { skip: "  needs the lab " }')
    assert loaded.commands["test"]["lab"].ci_skip == "needs the lab"


def test_a_command_without_ci_runs_in_ci():
    assert _loaded("help: x").commands["test"]["lab"].ci_skip == ""


@pytest.mark.parametrize("written", ['ci: { skip: "" }', "ci: { skip: true }", 'ci: { skip: "  " }'])
def test_a_skip_without_a_reason_is_refused(written):
    with pytest.raises(ValueError, match="`ci: skip:` says why"):
        _loaded(written)


@pytest.mark.parametrize("value", ["false", "true"])
def test_a_boolean_ci_is_refused_as_echoed_and_names_the_form(value):
    with pytest.raises(ValueError, match=rf'`ci: {value}`.*nobody can read back.*\{{ skip: "<reason>" \}}'):
        _loaded(f"ci: {value}")


def test_a_ci_that_is_not_a_mapping_is_a_diagnosis():
    with pytest.raises(ValueError, match='`ci: "nope"`, but `ci:` on a command is a mapping'):
        _loaded('ci: "nope"')


def test_an_unknown_key_under_ci_is_refused_naming_every_key_read():
    with pytest.raises(ValueError, match="key cadance.*skip, cadence, platforms, python, timeout_minutes, "
                                         "emulates"):
        _loaded("ci: { cadance: nightly }")


def test_ci_skip_on_an_aggregate_is_refused():
    with pytest.raises(ValueError, match="aggregate 'release all'.*`ci: skip:`"):
        manifest.load(textwrap.dedent("""
            tasks:
              ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
            ci:
              release:
                commands:
                  lab: { task: ship }
                  all: { depends_on: [lab], help: "All.", ci: { skip: "no" } }
            """), catalogue=catalogue.load())


@pytest.mark.parametrize(("placement", "words"), [
    ("cd:\n  deploy:\n    commands:\n      up: { task: ship, ci: { skip: \"x\" } }", "deploy up"),
    ("support:\n  commands:\n    tidy: { task: ship, ci: { skip: \"x\" } }", "support tidy"),
    ("ci:\n  release:\n    commands:\n      cut: { task: ship, ci: { skip: \"x\" } }", "release cut"),
])
def test_ci_skip_outside_a_ci_build_or_test_leaf_is_refused(placement, words):
    """si#858 final review: a derived CI selects only the leaves under `ci build` and `ci test`, so `ci:` on any
    other command would do nothing - the same diagnosis as on an aggregate."""
    with pytest.raises(ValueError, match=rf"'{words}' declares `ci: skip:`.*only.*`ci build`.*`ci test`.*"
                                         r"would do nothing"):
        manifest.load(textwrap.dedent("""
            tasks:
              ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
            """) + placement + "\n", catalogue=catalogue.load())


def test_ci_skip_on_a_nested_ci_test_leaf_is_read():
    nested = catalogue.loads(textwrap.dedent("""
        groups:
          ci:
            transparent: true
            groups:
              build: { help: "Produce the artefacts." }
              test:
                help: "Verify them."
                groups:
                  lab: { help: "Needs the lab." }
        """))
    loaded = manifest.load(textwrap.dedent("""
        tasks:
          ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
        ci:
          test:
            groups:
              lab:
                commands:
                  smoke: { task: ship, ci: { skip: "needs the lab" } }
        """), catalogue=nested)
    assert loaded.commands["test.lab"]["smoke"].ci_skip == "needs the lab"


def test_the_manifest_chapter_s_skip_example_loads_as_written():
    """how/manifest.md shows `ci: { skip: }` on a placed catalogue leaf; the snippet is read from the page itself
    and loaded, so the example a reader copies is one the kernel accepts and reads the reason from."""
    page = (ROOT / "src" / "site" / "content" / "how" / "manifest.md").read_text(encoding="utf-8")
    (snippet,) = [block for block in re.findall(r"```yaml\n(.*?)```", page, re.S) if "ci: { skip:" in block]

    loaded = manifest.load(snippet, catalogue=catalogue.load())

    assert loaded.commands["test"]["lab"].ci_skip == "needs a running lab; run by hand before a release"


# --- si#860: the variant keys -------------------------------------------------------------------------


def test_the_manifest_chapter_s_variant_example_loads_and_names_every_platform_cell():
    """how/manifest.md shows one leaf per variant key; the snippet is read from the page and loaded, so each
    example is one the kernel reads as written, and its `platforms:` list is held against the kernel's cells,
    so the page cannot name a cell the kernel lost or miss one it gained."""
    page = (ROOT / "src" / "site" / "content" / "how" / "manifest.md").read_text(encoding="utf-8")
    (snippet,) = [block for block in re.findall(r"```yaml\n(.*?)```", page, re.S) if "ci: { platforms:" in block]

    leaves = manifest.load(snippet, catalogue=catalogue.load()).commands["test"]

    assert {name: leaf.ci for name, leaf in leaves.items()} == {
        "compose": CiVariant(cadence="nightly"),
        "weekly": CiVariant(cadence="17 3 * * 1"),
        "cells": CiVariant(platforms=tuple(PLATFORMS)),
        "newest": CiVariant(python=("3.14",)),
        "lab": CiVariant(timeout_minutes=95),
        "foreign": CiVariant(emulates=("linux/arm64",)),
    }


def _ci(written: str) -> CiVariant:
    return _loaded(f"ci: {written}").commands["test"]["lab"].ci


def test_the_variant_keys_are_read_as_written():
    assert _ci('{ cadence: nightly, python: ["3.14"], timeout_minutes: 30, emulates: [linux/arm64] }') == \
        CiVariant(cadence="nightly", python=("3.14",), timeout_minutes=30, emulates=("linux/arm64",))


def test_platforms_are_read_in_the_order_written():
    assert _ci("{ platforms: [windows-x64, linux-x64] }").platforms == ("windows-x64", "linux-x64")


@pytest.mark.parametrize("cadence", ["manual", "17 2 * * *", "  0 4 * * 1  "])
def test_a_cadence_is_a_word_or_a_five_field_cron(cadence):
    assert _ci(f'{{ cadence: "{cadence}" }}').cadence == " ".join(cadence.split())


def test_a_command_without_ci_has_no_variant():
    assert _loaded("help: x").commands["test"]["lab"].ci == CiVariant()


def test_a_skip_has_no_variant():
    assert _ci('{ skip: "needs the lab" }') == CiVariant()


def test_a_skip_beside_another_key_is_refused():
    with pytest.raises(ValueError, match=r"`ci: skip:` beside cadence.*the leaf does not run in CI, so"):
        _ci('{ skip: "needs the lab", cadence: nightly }')


def test_a_variant_key_on_an_aggregate_names_that_key():
    with pytest.raises(ValueError, match="aggregate 'test all' declares `ci: cadence:`.*never an aggregate"):
        manifest.load(textwrap.dedent("""
            tasks:
              ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
            ci:
              test:
                commands:
                  lab: { task: ship }
                  all: { depends_on: [lab], help: "All.", ci: { cadence: nightly } }
            """), catalogue=catalogue.load())


@pytest.mark.parametrize("cadence", ['"17 2 * *"', "weekly", '""', "3"])
def test_a_cadence_that_is_neither_a_word_nor_five_fields_is_refused(cadence):
    with pytest.raises(ValueError, match="`ci: cadence:` is `nightly`, `manual` or a cron string"):
        _ci(f"{{ cadence: {cadence} }}")


def test_an_unknown_platform_is_refused_naming_it_and_the_cells():
    with pytest.raises(ValueError, match=r"solaris.*" + re.escape(", ".join(PLATFORMS))):
        _ci("{ platforms: [linux-x64, solaris] }")


@pytest.mark.parametrize("platforms", ["[]", "[linux-x64, linux-x64]", "linux-x64"])
def test_an_empty_duplicate_or_bare_platforms_is_refused(platforms):
    with pytest.raises(ValueError, match="`ci: platforms:` is a non-empty list of distinct cells"):
        _ci(f"{{ platforms: {platforms} }}")


def test_an_unquoted_python_version_is_refused_with_the_fix():
    with pytest.raises(ValueError, match="3.10 unquoted reads as 3.1: quote the version"):
        _ci("{ python: [3.10] }")


@pytest.mark.parametrize("python", ["[]", '["3.14", "3.14"]', '"3.14"', '[""]'])
def test_an_empty_duplicate_or_bare_python_is_refused(python):
    with pytest.raises(ValueError, match="`ci: python:` is a non-empty list of distinct versions"):
        _ci(f"{{ python: {python} }}")


@pytest.mark.parametrize("minutes", ["true", "0", "-5", '"30"', "1.5"])
def test_a_timeout_that_is_not_a_positive_whole_number_is_refused(minutes):
    with pytest.raises(ValueError, match="`ci: timeout_minutes:` is a positive whole number of minutes"):
        _ci(f"{{ timeout_minutes: {minutes} }}")


@pytest.mark.parametrize("emulates", ["[]", "[arm64]", '"linux/arm64"', "[linux/]"])
def test_emulates_not_spelt_as_buildx_is_refused(emulates):
    with pytest.raises(ValueError, match="`ci: emulates:` is a non-empty list of platforms as buildx spells"):
        _ci(f"{{ emulates: {emulates} }}")


def test_platforms_with_python_is_refused():
    with pytest.raises(ValueError, match="`ci: platforms:` and `ci: python:` on one leaf"):
        _ci('{ platforms: [linux-x64], python: ["3.14"] }')


def test_platforms_with_emulates_is_refused():
    with pytest.raises(ValueError, match="`ci: platforms:` and `ci: emulates:` on one leaf"):
        _ci("{ platforms: [linux-arm64], emulates: [linux/arm64] }")


# --- the final review of si#860: cron fields, stripped versions, an empty `ci:` -------------------------------

@pytest.mark.parametrize("cadence", ["every night at two am", "17 2 * * MON'", "0 3 * JAN-MAR FOO",
                                     "0 3 MON * *", "0 3 * * JAN"])
def test_a_cron_field_outside_the_cron_alphabet_is_refused_naming_it(cadence):
    """Final review item 4: five words are not a cron. Each field holds only digits, `*`, `,`, `-` and `/`, and
    the month and weekday fields also their names, so a quote can never reach `_SCHEDULE_GATE`."""
    with pytest.raises(ValueError, match="field") as refused:
        _ci(f"{{ cadence: \"{cadence}\" }}")
    assert "`ci: cadence:`" in str(refused.value)


@pytest.mark.parametrize("cadence", ["17 2 * * *", "*/15 0-6 1,15 JAN-MAR MON-FRI", "0 3 * jan sun"])
def test_a_cron_with_valid_fields_is_read(cadence):
    assert _ci(f'{{ cadence: "{cadence}" }}').cadence == cadence


def test_python_versions_are_stripped_before_the_duplicate_check():
    """Final review item 7: `" 3.14"` is the version 3.14, so beside "3.14" it is a duplicate."""
    with pytest.raises(ValueError, match="`ci: python:` is a non-empty list of distinct versions"):
        _ci('{ python: ["3.14", " 3.14"] }')
    assert _ci('{ python: [" 3.14"] }').python == ("3.14",)


def test_an_empty_ci_is_refused_as_saying_nothing():
    """Final review item 8: `ci: {}` is neither a skip nor a variant; read as a skip without a reason it would
    send the reader to write one."""
    with pytest.raises(ValueError, match=r"`ci: \{\}` says nothing") as refused:
        _loaded("ci: {}")
    said = str(refused.value)
    assert "skip" in said and "cadence" in said and "drop `ci:`" in said
