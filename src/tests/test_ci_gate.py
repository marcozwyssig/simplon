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
