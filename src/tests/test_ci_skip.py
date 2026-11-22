"""si#858: `ci: { skip: "<reason>" }` on a command - the opt-out a command uses to stay out of the derived CI.

A derived CI workflow runs every leaf a manifest places under the CI phases. A command that cannot run on a
hosted runner says so, and says why: the reason is read into `TaskCommand.ci_skip`, so a reader of the
manifest learns why a leaf is absent from the workflow. `ci` is also the name of the manifest's top-level
area, so a test holds that a command's `ci:` is read as the command key it is.
"""
from __future__ import annotations

import textwrap

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest


def _loaded(written: str):
    return manifest.load(textwrap.dedent("""
        tasks:
          ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
        ci:
          release:
            commands:
              lab: { task: ship, %s }
              all: { depends_on: [lab], help: "All." }
        """) % written, catalogue=catalogue.load())


def test_a_skip_with_its_reason_is_read():
    loaded = _loaded('ci: { skip: "  needs the lab " }')
    assert loaded.commands["release"]["lab"].ci_skip == "needs the lab"


def test_a_command_without_ci_runs_in_ci():
    assert _loaded("help: x").commands["release"]["lab"].ci_skip == ""


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
