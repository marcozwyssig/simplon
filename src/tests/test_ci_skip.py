"""si#858: `ci: { skip: "<reason>" }` on a command - the opt-out a command uses to stay out of the derived CI.

A derived CI workflow runs every leaf a manifest places under the CI phases. A command that cannot run on a
hosted runner says so, and says why: the reason is read into `TaskCommand.ci_skip`, so a reader of the
manifest learns why a leaf is absent from the workflow. `ci` is also the name of the manifest's top-level
area, so a test holds that a command's `ci:` is read as the command key it is.
"""
from __future__ import annotations

import re
import textwrap

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest

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


def test_an_unknown_key_under_ci_is_refused():
    with pytest.raises(ValueError, match="only key.*`skip`"):
        _loaded("ci: { cadence: nightly }")


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
