"""si#861: `ci: { gate: { paths, label, env } }` on an aggregate under `ci build` or `ci test`.

The gate is read into `AggregateCommand.gate`, a `CiGate`; its members run in a workflow file of their own.
Each refusal here is a diagnosis except the gate on a leaf, which is an expression rule (census).
"""
from __future__ import annotations

import textwrap

import pytest

from simplon.manifest import catalogue
from simplon.manifest import load as manifest
from simplon.model.command import AggregateCommand, CiGate

from conftest import ROOT


def _loaded(ci: str, placement: str = "ci:\n  test:\n    commands:\n      lab: { task: ship }\n"
                                       "      all: { depends_on: [lab], help: \"All.\", %s }\n"):
    text = textwrap.dedent("""
        tasks:
          ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
        """) + (placement % ci) + "\n"
    return manifest.load(text, catalogue=catalogue.load())


def _gate(ci: str):
    return _loaded(ci).commands["test"]["all"].gate


def test_gate_reads_paths_label_env():
    gate = _gate('ci: { gate: { paths: ["src/**", "**/Dockerfile"], label: needs-lab, '
                 'env: { NETCTL_MGMT_SUBNET: 10.128.0.0/24 } } }')
    assert gate == CiGate(paths=("src/**", "**/Dockerfile"), label="needs-lab",
                          env={"NETCTL_MGMT_SUBNET": "10.128.0.0/24"})


def test_gate_takes_cadence_and_timeout():
    gate = _gate('ci: { gate: { label: needs-lab }, cadence: nightly, timeout_minutes: 95 }')
    assert (gate.cadence, gate.timeout_minutes) == ("nightly", 95)


def test_gate_env_scalars_are_strings_as_github_reads_them():
    gate = _gate('ci: { gate: { label: x, env: { A: true, B: 10, C: false } } }')
    assert gate.env == {"A": "true", "B": "10", "C": "false"}


def test_an_aggregate_without_a_gate_has_none():
    command = _loaded("hidden: false").commands["test"]["all"]
    assert isinstance(command, AggregateCommand) and command.gate is None


def test_gate_on_a_leaf_is_refused_and_names_the_wrapping_form():
    with pytest.raises(ValueError, match=r"`ci: gate:` sits on an aggregate.*depends_on: \[lab\]"):
        _loaded("hidden: false", "ci:\n  test:\n    commands:\n      lab: { task: ship, ci: { gate: { label: x } } }\n"
                           "      all: { depends_on: [lab], help: \"All.\", %s }\n")


@pytest.mark.parametrize("written", ["cadence: nightly", "timeout_minutes: 5"])
def test_cadence_or_timeout_on_an_aggregate_without_a_gate_is_refused(written):
    with pytest.raises(ValueError, match=r"aggregate 'test all'.*holds `gate:`, and "
                                         r"`cadence:`/`timeout_minutes:` beside it"):
        _loaded(f"ci: {{ {written} }}")


@pytest.mark.parametrize("written", ['platforms: [linux-x64]', 'python: ["3.14"]', "emulates: [linux/arm64]",
                                     'skip: "no"'])
def test_a_leaf_key_on_an_aggregate_is_refused_even_beside_a_gate(written):
    with pytest.raises(ValueError, match=r"aggregate 'test all' declares `ci: " + written.split(":")[0]
                                         + r":`.*holds `gate:`"):
        _loaded("ci: { gate: { label: x }, " + written + " }")


def test_a_gate_outside_ci_build_or_test_is_refused():
    with pytest.raises(ValueError, match=r"'deploy all' declares `ci: gate:`.*only the leaves under `ci build`"):
        _loaded("ci: { gate: { label: x } }",
                "cd:\n  deploy:\n    commands:\n      lab: { task: ship }\n"
                "      all: { depends_on: [lab], help: \"All.\", %s }\n")


@pytest.mark.parametrize("written", ["{}", "{ env: { A: b } }"])
def test_a_gate_with_neither_paths_nor_label_is_refused(written):
    with pytest.raises(ValueError, match="a gate with neither `paths:` nor `label:` never runs on a pull request"):
        _loaded(f"ci: {{ gate: {written} }}")


def test_an_unknown_gate_key_is_refused_naming_the_keys():
    with pytest.raises(ValueError, match="key path.*paths, label, env"):
        _loaded("ci: { gate: { path: [x], label: y } }")


def test_a_gate_that_is_not_a_mapping_is_refused():
    with pytest.raises(ValueError, match="`ci: gate:` is a mapping"):
        _loaded("ci: { gate: yes-please }")


@pytest.mark.parametrize("paths", ["x", "[]", '[""]', "[1]", '["a", " "]'])
def test_paths_must_be_a_list_of_non_empty_strings(paths):
    with pytest.raises(ValueError, match="`paths:` is a non-empty list of non-empty globs"):
        _loaded(f"ci: {{ gate: {{ paths: {paths}, label: y }} }}")


@pytest.mark.parametrize("label", ['""', "[a]", "7", '"  "'])
def test_label_must_be_a_non_empty_string(label):
    with pytest.raises(ValueError, match="`label:` is the name of a pull request label"):
        _loaded(f"ci: {{ gate: {{ label: {label} }} }}")


@pytest.mark.parametrize("name", ['"1A"', '"A-B"', '"A B"'])
def test_an_env_name_must_be_a_variable_name(name):
    with pytest.raises(ValueError, match="no environment variable name"):
        _loaded(f"ci: {{ gate: {{ label: y, env: {{ {name}: v }} }} }}")


@pytest.mark.parametrize("value", ["[a]", "{ a: b }", "null"])
def test_an_env_value_must_be_a_scalar(value):
    with pytest.raises(ValueError, match="An env value is a scalar"):
        _loaded(f"ci: {{ gate: {{ label: y, env: {{ A: {value} }} }} }}")


def test_an_env_that_is_not_a_mapping_is_refused():
    with pytest.raises(ValueError, match="`env:` is a mapping of variable names"):
        _loaded("ci: { gate: { label: y, env: [A] } }")


def test_an_env_value_with_an_expression_points_at_the_secrets_module():
    with pytest.raises(ValueError, match=r"secrets reach a job through the secrets module \(si#833\)"):
        _loaded('ci: { gate: { label: y, env: { A: "${{ secrets.X }}" } } }')


def test_the_kernels_own_catalogue_and_manifest_declare_no_gate():
    loaded = manifest.load((ROOT / "simplon.yaml").read_text(), catalogue=catalogue.load())
    assert all(getattr(command, "gate", None) is None
               for group in loaded.commands.values() for command in group.values())


def test_an_unquoted_float_env_value_is_refused_and_says_quote_it():
    with pytest.raises(ValueError, match=r"V: 3.1.*read as a number.*quote it"):
        _loaded("ci: { gate: { label: y, env: { V: 3.10 } } }")


def test_an_env_key_yaml_reads_as_a_bool_is_refused_and_says_quote_it():
    with pytest.raises(ValueError, match=r"name true, which YAML read as a bool.*quote it"):
        _loaded("ci: { gate: { label: y, env: { on: x } } }")


@pytest.mark.parametrize(("written", "said"), [("{}", r"`ci: \{\}`"), ("false", "`ci: false`")])
def test_an_empty_or_boolean_ci_on_an_aggregate_names_what_was_written(written, said):
    with pytest.raises(ValueError, match=rf"aggregate 'test all' declares {said}"):
        _loaded(f"ci: {written}")


# --- the members of a gate, and where they run (si#861 task 3) --------------------------------------------

_MEMBERS = """
tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
artifacts:
  doc: { kind: file, path: build/doc.txt }
  note: { kind: file, path: build/note.txt, registry: ghcr.io/o/note }
cd:
  deploy:
    commands:
      down: { task: ship, unattended: true }
      up: { task: ship, unattended: true }
      seed: { task: ship, unattended: true }
ci:
  build:
    commands:
      compile: { task: ship, unattended: true }
      image: { task: ship, unattended: true }
      all: { depends_on: [compile, image], help: "All." }
  test:
    commands:
      unit: { task: ship, unattended: true }
      system: { task: ship, unattended: true%(system)s }
      report: { task: ship, unattended: true, after_all: true }
      lab: { depends_on: [down, up, seed, all, compile, system, report], help: "Lab.",
             ci: { gate: { label: needs-lab } } }
%(more)s"""


def _members(system: str = "", more: str = ""):
    return manifest.load(_MEMBERS % {"system": system, "more": more}, catalogue=catalogue.load())


_IN_LAB = "it runs in ci-test-lab.yml, behind the gate of `test lab`"


def test_gate_members_are_its_plan_leaves():
    from simplon.tasks import cipipeline
    (run,) = cipipeline.gates(_members())
    assert run.words == "test lab" and run.gate == CiGate(label="needs-lab")
    # the member aggregate `build all` contributes its leaves; `compile`, named twice, is there once
    assert [leaf.words for leaf in run.members] == [
        "deploy down", "deploy up", "deploy seed", "build compile", "build image", "test system", "test report"]
    assert run.path == ".github/workflows/ci-test-lab.yml"


def test_member_leaves_the_push_run():
    from simplon.tasks import cipipeline
    selection = cipipeline.select(_members(), artifacts={})
    assert cipipeline.Skipped("test system", _IN_LAB) in selection.skipped
    assert cipipeline.Skipped("build compile", _IN_LAB) in selection.skipped
    assert [leaf.words for leaf in selection.leaves] == ["test unit", "test report"]


def test_member_leaves_the_nightly_run():
    from simplon.tasks import cipipeline
    loaded = _members(more="      late: { task: ship, unattended: true, ci: { cadence: nightly } }\n")
    selection = cipipeline.select(loaded, artifacts={}, cadence="nightly")
    # named with the gate's file, not with ci.yml's "it has no `cadence:`"
    assert cipipeline.Skipped("test system", _IN_LAB) in selection.skipped
    assert [leaf.words for leaf in selection.leaves] == ["test report", "test late"]  # manifest order


def _system_as(written: str):
    return manifest.load((_MEMBERS % {"system": "", "more": ""}).replace(
        "system: { task: ship, unattended: true }", "system: { task: ship" + written + " }"), catalogue=catalogue.load())


def test_attended_member_refused():
    from simplon.tasks import cipipeline
    with pytest.raises(ValueError, match=r"'test system' is a member of the gate of `test lab`.*unattended: false"):
        cipipeline.gates(_system_as(", unattended: false"))


def test_undecided_member_refused_naming_the_gate():
    from simplon.tasks import cipipeline
    loaded = _system_as("")
    with pytest.raises(ValueError, match=r"the gate of `test lab`: command 'test system' does not say"):
        cipipeline.gates(loaded)


def test_skipped_member_refused():
    from simplon.tasks import cipipeline
    with pytest.raises(ValueError, match=r"'test system'.*membership already keeps it out of the main job"):
        cipipeline.gates(_members(', ci: { skip: "flaky" }'))


@pytest.mark.parametrize(("written", "key"), [("cadence: nightly", "cadence"), ("platforms: [linux-x64]", "platforms"),
                                              ('python: ["3.14"]', "python")])
def test_member_with_cadence_or_cells_refused(written, key):
    from simplon.tasks import cipipeline
    with pytest.raises(ValueError, match=rf"'test system' is a member of the gate of `test lab`.*`ci: {key}:`"
                                         r".*the gate's file decides when and where it runs"):
        cipipeline.gates(_members(f", ci: {{ {written} }}"))


@pytest.mark.parametrize("written", ["timeout_minutes: 30", "emulates: [linux/arm64]"])
def test_member_timeout_and_emulation_are_allowed(written):
    from simplon.tasks import cipipeline
    (run,) = cipipeline.gates(_members(f", ci: {{ {written} }}"))
    assert "test system" in [leaf.words for leaf in run.members]


def _crossing(system: str, unit: str):
    return manifest.load((_MEMBERS % {"system": system, "more": ""}).replace(
        "unit: { task: ship, unattended: true }", "unit: { task: \"toolchain:run\", unattended: true" + unit + " }")
        .replace("system: { task: ship,", "system: { task: \"toolchain:run\","), catalogue=catalogue.load())


def _declared():
    import yaml
    from simplon.manifest import artifactsection
    return artifactsection.declared(yaml.safe_load(_MEMBERS % {"system": "", "more": ""}))


def test_member_consumes_main_job_artifact_refused():
    from simplon.tasks import cipipeline
    loaded = _crossing(", consumes: { source: doc }", ", produces: { out: doc }")
    with pytest.raises(ValueError, match=r"'test system' runs in ci-test-lab.yml, behind the gate of `test lab`, "
                                         r"and consumes 'doc', which 'test unit' produces, and 'test unit' runs in "
                                         r"ci.yml - artifacts do not cross workflow files"):
        cipipeline.select(loaded, artifacts=_declared())


def test_main_job_consumes_member_artifact_refused():
    from simplon.tasks import cipipeline
    loaded = _crossing(", produces: { out: doc }", ", consumes: { source: doc }")
    with pytest.raises(ValueError, match=r"'test unit' runs in ci.yml and consumes 'doc', which 'test system' "
                                         r"produces, and 'test system' is a member of `test lab` \(" + _IN_LAB
                                         + r"\) - artifacts do not cross workflow files"):
        cipipeline.select(loaded, artifacts=_declared())


@pytest.mark.parametrize(("system", "unit"), [(", consumes: { source: note }", ", produces: { out: note }"),
                                              (", produces: { out: note }", ", consumes: { source: note }")])
def test_a_registry_artifact_crosses_the_gate(system, unit):
    from simplon.tasks import cipipeline
    selection = cipipeline.select(_crossing(system, unit), artifacts=_declared())
    assert "test unit" in [leaf.words for leaf in selection.leaves]


def test_every_leaf_gated_names_the_gate_file():
    import yaml
    from simplon.tasks import cipipeline
    text = (_MEMBERS % {"system": "", "more": ""}).replace("      unit: { task: ship, unattended: true }\n", "")
    loaded = manifest.load(text, catalogue=catalogue.load())
    with pytest.raises(ValueError, match=r"is a member of a gate, so they run in ci-test-lab.yml and the push "
                                         r"path verifies nothing"):
        cipipeline.derive(loaded, yaml.safe_load(text))
