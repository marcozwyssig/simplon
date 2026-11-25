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
from ghstub import calls_made, gh_on_path


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


@pytest.mark.parametrize(("glob", "char"), [("!docs/**", "!"), ("src/?.py", "?"), ("a+b/**", "+"),
                                           ("a[1]/**", "["), ("a]/**", "]")])
def test_a_glob_outside_the_star_subset_is_refused_naming_the_subset(glob, char):
    """GitHub's filter syntax gives `!`, `?`, `+` and `[...]` a meaning the decide step does not implement, so a
    glob with one would never match what it says: refused at load, naming the subset that is read."""
    with pytest.raises(ValueError) as refused:
        _loaded(f'ci: {{ gate: {{ paths: ["src/**", "{glob}"], label: y }} }}')
    said = str(refused.value)
    assert f'"{glob}"' in said and f"`{char}`" in said
    assert "the `*`/`**` subset of GitHub's filter syntax" in said


def test_a_glob_with_other_punctuation_is_read_literally():
    assert _gate('ci: { gate: { paths: ["x(1)/*", "a.b/**", "a{1}|b^$"] } }').paths == (
        "x(1)/*", "a.b/**", "a{1}|b^$")


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


@pytest.mark.parametrize(("written", "said"), [("{}", r"`ci: \{\}`"), ("false", "`ci: false`"),
                                              ("{ gate: { label: x } }", "`ci: gate:`")])
@pytest.mark.parametrize("command", ["all", "lab"])
def test_ci_outside_ci_build_or_test_names_what_was_written(written, said, command):
    """Outside `ci build`/`ci test` the refusal names the `ci:` as written, not a `skip:` nobody wrote."""
    ci = f", ci: {written}"
    lab, all_ = (ci, "") if command == "lab" else ("", ci)
    placement = (f"cd:\n  deploy:\n    commands:\n      lab: {{ task: ship{lab} }}\n"
                 f"      all: {{ depends_on: [lab], help: \"All.\"{all_} }}\n# %s")
    with pytest.raises(ValueError, match=rf"'deploy {command}' declares {said}, and ") as refused:
        _loaded("", placement)
    assert "`ci: skip:`" not in str(refused.value)


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
    with pytest.raises(ValueError, match=r"are all members of a gate, so they run in ci-test-lab.yml and the push "
                                         r"path verifies nothing - "):
        cipipeline.derive(loaded, yaml.safe_load(text))


def test_an_after_all_member_consuming_a_member_artifact_is_not_told_to_join():
    from simplon.tasks import cipipeline
    loaded = manifest.load((_MEMBERS % {"system": "", "more": ""})
                           .replace("system: { task: ship, unattended: true }",
                                    'system: { task: "toolchain:run", unattended: true, produces: { out: doc } }')
                           .replace("report: { task: ship, unattended: true, after_all: true }",
                                    'report: { task: "toolchain:run", unattended: true, after_all: true, '
                                    "consumes: { source: doc } }"), catalogue=catalogue.load())
    with pytest.raises(ValueError) as refused:
        cipipeline.select(loaded, artifacts=_declared())
    said = str(refused.value)
    assert ("'test report' runs after all the others (`after_all`) and ends every run, ci.yml included, so "
            "whatever it consumes must be produced in each run it ends") in said
    assert "Make 'test report' a member" not in said


def test_every_leaf_gated_or_skipped_lists_the_skipped_ones():
    import yaml
    from simplon.tasks import cipipeline
    text = (_MEMBERS % {"system": "", "more": ""}).replace(
        "unit: { task: ship, unattended: true }", 'unit: { task: ship, ci: { skip: "flaky on CI" } }')
    with pytest.raises(ValueError, match=r"are all members of a gate, so they run in ci-test-lab.yml and the push "
                                         r"path verifies nothing \(left out besides: `test unit` - flaky on CI\) - "):
        cipipeline.derive(manifest.load(text, catalogue=catalogue.load()), yaml.safe_load(text))


@pytest.mark.parametrize("glob, path, matches", [
    ("src/sidecar/api/grpc/**", "src/sidecar/api/grpc/a/b.proto", True),
    ("src/sidecar/api/grpc/**", "src/sidecar/api/grpcx/a", False),
    ("deploy/env/*/lab.yml", "deploy/env/dev/lab.yml", True),
    ("deploy/env/*/lab.yml", "deploy/env/a/b/lab.yml", False),
    ("deploy/env/*/lab.yml", "deploy/env/dev/labxyml", False),
    ("**/Dockerfile", "Dockerfile", True),
    ("**/Dockerfile", "a/b/Dockerfile", True),
    ("**/Dockerfile", "a/Dockerfile.bak", False),
    ("a.b/**", "a.b/c", True),
    ("a.b/**", "axb/c", False),
    ("x(1)/*", "x(1)/z", True),
    ("x(1)/*", "x1/z", False),
    ("x(1)/*", "x(1)/z/y", False),
    ("a{1}", "a{1}", True),
    ("a{1}", "a", False),
    ("a^b$", "a^b$", True),
    ("**", "a/b/c", True),
    ("**", "a", True),
    ("a/**/b", "a/b", True),
    ("a/**/b", "a/x/y/b", True),
    ("a/**/b", "a/xb", False),
    ("a|b", "a|b", True),
    ("a|b", "a", False),
    ("a|b", "b", False),
    ("a\\b", "a\\b", True),
    ("a\\b", "ab", False),
])
def test_glob_pattern(glob, path, matches):
    import re
    import subprocess
    from simplon.tasks import cipipeline
    pattern = cipipeline.glob_pattern([glob])
    assert (any(re.fullmatch(alt, path) for alt in re.split(r"(?<!\\)\|", pattern)) is matches), pattern
    grep = subprocess.run(["grep", "-qE", "--", pattern], input=path + "\n", text=True)
    assert (grep.returncode == 0) is matches, pattern


def test_glob_pattern_joins_alternatives():
    import subprocess
    from simplon.tasks import cipipeline
    pattern = cipipeline.glob_pattern(["a/**", "b.txt"])
    assert "(?:" not in pattern
    for path, matches in (("a/x", True), ("b.txt", True), ("bxtxt", False), ("c/a/x", False)):
        grep = subprocess.run(["grep", "-qE", "--", pattern], input=path + "\n", text=True)
        assert (grep.returncode == 0) is matches, (path, pattern)


# --- the gate's own workflow file (si#861 task 5) ---------------------------------------------------------

_LAB_GLOBS = ["src/sidecar/api/grpc/**", "src/sidecar/src/python/**",
              "src/netctl/src/java/infrastructure/src/main/java/**/rendering/**", "deploy/env/*/lab.yml",
              "deploy/provision/labgen/**", "**/Dockerfile", "test/system/python/**", "test/acceptance/python/**"]

#: netctl-shaped: a self-hosted machine with its preparation placed, toolchains, Deploy members in front of the
#: verifying ones, the report last. `%(gate)s` is the gate's keys, `%(more)s` the rest of the aggregate's `ci:`.
_LAB = """
tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
runner: { kind: self-hosted-debian, labels: ghr-1 }
toolchains:
  - python
suites:
  reports: tests/reports
  gates:
    - { name: unit, command: "test unit", results: clear }
support:
  commands:
    install: { task: "support:install" }
    ci-docker-preflight: { task: "support:ci-docker-preflight" }
    ci-disk-preflight: { task: "support:ci-disk-preflight" }
    ci-disk-cleanup: { task: "support:ci-disk-cleanup" }
cd:
  deploy:
    commands:
      down: { task: ship, unattended: true }
      up: { task: ship, unattended: true }
      seed: { task: ship, unattended: true }
ci:
  test:
    commands:
      unit: { task: ship, unattended: true }
      system: { task: ship, unattended: true%(system)s }
      acceptance-dataplane: { task: ship, unattended: true }
      report: { task: "test:report" }
      lab:
        depends_on: [down, up, seed, system, acceptance-dataplane, report]
        help: "Lab."
        ci:
          gate: { %(gate)s }
          %(more)s
%(tail)s"""

_LAB_GATE = ("paths: " + str(_LAB_GLOBS).replace("'", '"') + ", label: needs-lab, "
             "env: { NETCTL_MGMT_SUBNET: 10.128.0.0/24 }")
_LAB_PATH = ".github/workflows/ci-test-lab.yml"
_GOLDEN = ROOT / "src/tests/fixtures/workflows/ci-test-lab.golden.yml"


def _lab_text(gate: str = _LAB_GATE, more: str = "cadence: nightly\n          timeout_minutes: 95",
              tail: str = "", system: str = "") -> str:
    return _LAB % {"gate": gate, "more": more, "tail": tail, "system": system}


def _lab_workflows(text: str):
    import yaml
    from simplon.tasks import cipipeline
    loaded = manifest.load(text, catalogue=catalogue.load(), manifest_path="netctl.yaml")
    return loaded, {wf.path: wf for wf in cipipeline.workflows(loaded, yaml.safe_load(text), product="netctl")}


def _lab_rendered(text: str | None = None, path: str = _LAB_PATH) -> str:
    from simplon.tasks import workflowgen
    loaded, files = _lab_workflows(text or _lab_text())
    return workflowgen.render(files[path], manifest=loaded, product="netctl", source="netctl.yaml", artifacts={},
                              reports="tests/reports")


def _lab_doc(text: str | None = None) -> dict:
    import yaml
    return yaml.safe_load(_lab_rendered(text))


def _gated_steps(doc: dict) -> list[dict]:
    from simplon.tasks import workflowgen
    return [step for step in doc["jobs"]["test-lab"]["steps"] if step.get("name") != workflowgen.REAP_NAME]


def _lab_step(doc: dict, words: str) -> dict:
    return next(step for step in _gated_steps(doc) if step.get("run") == f"exec ./netctl.sh {words}")


def test_gate_file_golden():
    assert _lab_rendered() == _GOLDEN.read_text(encoding="utf-8")


def test_gate_triggers():
    on = _lab_doc()[True]  # YAML 1.1 reads the bare key `on` as a bool
    assert on == {"pull_request": {"types": ["opened", "reopened", "synchronize", "labeled"]},
                  "schedule": [{"cron": "17 2 * * *"}], "workflow_dispatch": None}
    assert "push" not in on


def test_gated_job_shape():
    doc = _lab_doc()
    job = doc["jobs"]["test-lab"]
    assert job["needs"] == "decide"
    assert job["if"] == "needs.decide.outputs.run == 'true'"
    assert job["timeout-minutes"] == 95
    assert job["env"]["NETCTL_MGMT_SUBNET"] == "10.128.0.0/24"
    # keyed on the verdict too, so a skipped job only ever shares a group with skipped ones
    assert job["concurrency"] == {"group": "ci-test-lab-${{ github.ref }}-${{ needs.decide.outputs.run }}",
                                  "cancel-in-progress": False}
    assert "concurrency" not in doc


def test_deploy_members_prepare():
    doc = _lab_doc()
    ids = [_lab_step(doc, f"deploy {name}").get("id") for name in ("down", "up", "seed")]
    assert all(ids) and len(set(ids)) == 3
    assert all("if" not in _lab_step(doc, f"deploy {name}") for name in ("down", "up", "seed"))
    system, dataplane = _lab_step(doc, "test system"), _lab_step(doc, "test acceptance-dataplane")
    for step in (system, dataplane):
        assert step["if"].startswith("${{ !cancelled() && ")
        for deploy in ids:
            assert f"steps.{deploy}.outcome == 'success'" in step["if"]
    assert "id" not in system or system["id"] not in dataplane["if"]
    assert "leaf_test_system" not in dataplane["if"]
    assert _lab_step(doc, "test report")["if"] == "always()"
    runs = [step["run"].removeprefix("exec ./netctl.sh ") for step in _gated_steps(doc) if "run" in step]
    assert runs == ["support ci-docker-preflight", "support ci-disk-preflight", "support install", "deploy down",
                    "deploy up", "deploy seed", "test system", "test acceptance-dataplane", "test report",
                    "support ci-disk-cleanup"]


def test_decide_job_shape():
    doc = _lab_doc()
    job = doc["jobs"]["decide"]
    assert job["runs-on"] == "ghr-1"
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert job["outputs"] == {"run": "${{ steps.decide.outputs.run }}", "why": "${{ steps.decide.outputs.why }}"}
    assert not any("uses" in step and step["uses"].startswith("actions/checkout") for step in job["steps"])
    assert not any("netctl.sh" in str(step.get("run", "")) for step in job["steps"])
    decide = next(step for step in job["steps"] if step.get("id") == "decide")
    assert decide["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "env" not in job
    assert not any("GH_TOKEN" in step.get("env", {}) for step in job["steps"] if step is not decide)
    assert "GH_TOKEN" not in str(doc["jobs"]["test-lab"])
    assert decide["env"]["LABEL"] == "needs-lab"
    from simplon.tasks import cipipeline
    assert decide["env"]["PATTERN"] == cipipeline.glob_pattern(_LAB_GLOBS)
    assert "${{" not in decide["run"]


# The decide table (decision 7), executed: the rendered `run:` of the decide step, with bash, a `gh` on PATH that
# prints the given changed files, and the event as GitHub hands it over in the step's `env:`.

_MATCH = ["README.md", "src/sidecar/api/grpc/lab.proto"]
_NO_MATCH = ["README.md", "docs/a.md"]


def _decide(tmp_path, *, event: str, action: str = "", added: str = "", labels=(), files=(), gh_rc: int = 0,
            pattern: str | None = None, total: object = None, label: str | None = None):
    """`total` is the pull request's `changed_files` as GitHub counts it, the number of `files` unless given."""
    import json
    import os
    import subprocess
    doc = _lab_doc()
    step = next(step for step in doc["jobs"]["decide"]["steps"] if step.get("id") == "decide")
    script = tmp_path / "decide.sh"
    script.write_text(step["run"], encoding="utf-8")
    (tmp_path / "files.txt").write_text("".join(f + "\n" for f in files), encoding="utf-8")
    (tmp_path / "total.txt").write_text(f"{len(files) if total is None else total}\n", encoding="utf-8")
    # the files call lists the files, the pull request call answers its `changed_files`
    bin_dir, gh_calls = gh_on_path(
        tmp_path, f'case "$*" in *"/files?"*) cat "{tmp_path}/files.txt" ;; *) cat "{tmp_path}/total.txt" ;; esac\n'
                  f'exit {gh_rc}\n')
    output = tmp_path / "output.txt"
    output.write_text("", encoding="utf-8")
    pr = event == "pull_request"
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(output),
           "GITHUB_REPOSITORY": "o/netctl", "GH_TOKEN": "t",
           "EVENT": event, "ACTION": action, "ADDED_LABEL": added,
           # GitHub's toJSON is indented; a missing pull request is `null`
           "LABELS": json.dumps(list(labels), indent=2) if pr else "null", "PR": "7" if pr else "",
           "PATTERN": step["env"]["PATTERN"] if pattern is None else pattern,
           "LABEL": step["env"]["LABEL"] if label is None else label}
    done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
    said = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)
    return done, said, calls_made(gh_calls)


@pytest.mark.parametrize(("event", "action", "added", "labels", "files", "runs", "why"), [
    ("workflow_dispatch", "", "", (), (), "true", "dispatch"),
    ("schedule", "", "", (), (), "true", "schedule"),
    ("pull_request", "opened", "", (), _MATCH, "true", "src/sidecar/api/grpc/lab.proto"),
    ("pull_request", "opened", "", ("needs-lab",), _NO_MATCH, "false", "labeled"),
    ("pull_request", "labeled", "needs-lab", ("needs-lab",), _NO_MATCH, "true", "needs-lab"),
    ("pull_request", "labeled", "needs-lab", ("needs-lab",), _MATCH, "false", "src/sidecar/api/grpc/lab.proto"),
    ("pull_request", "labeled", "other", ("other",), _MATCH, "false", "other"),
    ("pull_request", "synchronize", "", ("other", "needs-lab"), _NO_MATCH, "true", "needs-lab"),
    ("pull_request", "synchronize", "", ("other",), _NO_MATCH, "false", "needs-lab"),
    ("pull_request", "reopened", "", (), _MATCH, "true", "src/sidecar/api/grpc/lab.proto"),
])
def test_decide_script_table(tmp_path, event, action, added, labels, files, runs, why):
    done, said, calls = _decide(tmp_path, event=event, action=action, added=added, labels=labels, files=files)
    assert done.returncode == 0, done.stdout + done.stderr
    assert said["run"] == runs, said
    assert why in said["why"], said
    if calls:
        files_call, *count_call = calls.strip().splitlines()
        assert files_call == "api --paginate repos/o/netctl/pulls/7/files?per_page=100 --jq .[].filename"
        # the count is asked for only where no listed file matched
        assert count_call == ([] if files == _MATCH else ["api repos/o/netctl/pulls/7 --jq .changed_files"])
    if action in ("opened", "reopened", "synchronize") and runs == "true" and files == _MATCH:
        assert "src/sidecar/api/grpc/lab.proto" in done.stdout  # the changed files are in the log


@pytest.mark.parametrize(("action", "labels", "runs", "why"), [
    ("opened", (), "true", "opened, and the pull request changes 3001 files and GitHub lists only the first 2"),
    ("synchronize", (), "true", "synchronize, and the pull request changes 3001 files"),
    # a truncated list is taken as a match, which already ran the gate on `opened` or `synchronize`
    ("labeled", ("needs-lab",), "false", "so opened or synchronize already ran it for this head"),
])
def test_decide_script_a_truncated_file_list_is_not_read_as_no_match(tmp_path, action, labels, runs, why):
    """GitHub lists at most 3000 files: a pull request that changes more is not judged on the ones listed."""
    done, said, calls = _decide(tmp_path, event="pull_request", action=action, labels=labels,
                                added="needs-lab" if action == "labeled" else "", files=_NO_MATCH, total=3001)
    assert done.returncode == 0, done.stdout + done.stderr
    assert said["run"] == runs and why in said["why"], said
    assert "rather than trust a truncated list" in said["why"], said
    assert "api repos/o/netctl/pulls/7 --jq .changed_files" in calls


@pytest.mark.parametrize("total", ["", "null", "3001x"])
def test_decide_script_a_count_that_is_no_number_fails_the_step(tmp_path, total):
    done, said, _ = _decide(tmp_path, event="pull_request", action="opened", files=_NO_MATCH, total=total)
    assert done.returncode != 0 and "run" not in said
    assert "::error::" in done.stdout


def test_decide_script_lists_the_changed_files_with_workflow_commands_stopped(tmp_path):
    """A file name is the pull request author's: one that reads `::add-mask::x` or `::error::x` at the start of a
    line would be a workflow command, so the listing sits between `::stop-commands::<token>` and `::<token>::`."""
    import re
    evil = "::error::pwned"
    done, said, _ = _decide(tmp_path, event="pull_request", action="opened", files=[evil, *_MATCH])
    assert said["run"] == "true", said
    lines = done.stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("::stop-commands::"))
    token = lines[start].removeprefix("::stop-commands::")
    assert re.fullmatch(r"[A-Za-z0-9-]{8,}", token), token
    end = lines.index(f"::{token}::")
    assert start < lines.index(evil) < end
    assert lines[start + 1:end] == [evil, *_MATCH]


def test_decide_script_tokens_differ_between_runs(tmp_path):
    tokens = []
    for n in range(2):
        (tmp_path / str(n)).mkdir()
        done, _, _ = _decide(tmp_path / str(n), event="pull_request", action="opened", files=_MATCH)
        tokens.append(next(line for line in done.stdout.splitlines() if line.startswith("::stop-commands::")))
    assert tokens[0] != tokens[1]


def test_decide_script_opened_on_a_label_only_gate_says_it_opens_on_its_label(tmp_path):
    done, said, calls = _decide(tmp_path, event="pull_request", action="opened", files=_MATCH, pattern="")
    assert (said["run"], calls) == ("false", ""), said
    assert said["why"] == "opened, and the gate has no paths:; it opens on its label needs-lab", said


def test_decide_script_opened_on_a_paths_only_gate_mentions_no_label(tmp_path):
    done, said, _ = _decide(tmp_path, event="pull_request", action="opened", files=_NO_MATCH, label="")
    assert said["run"] == "false", said
    assert said["why"] == "opened, and no changed path matches the gate's paths", said


def test_decide_script_a_failed_gh_fails_the_step(tmp_path):
    """A failed probe is not "nothing changed": a red `gh` is a red decide step, and no verdict is written."""
    done, said, _ = _decide(tmp_path, event="pull_request", action="opened", files=_MATCH, gh_rc=1)
    assert done.returncode != 0
    assert "run" not in said


def test_decide_script_a_label_only_gate_asks_no_files(tmp_path):
    """With no `paths:` the pattern is empty, and an empty ERE would match every file: no file is asked for."""
    done, said, calls = _decide(tmp_path, event="pull_request", action="opened", files=_MATCH, pattern="")
    assert (done.returncode, said["run"], calls) == (0, "false", "")


def test_decide_script_label_named_in_a_longer_label_does_not_count(tmp_path):
    done, said, _ = _decide(tmp_path, event="pull_request", action="synchronize",
                            labels=("needs-lab-later", "pre-needs-lab"), files=_NO_MATCH)
    assert said["run"] == "false", said


def test_gate_env_clashing_with_the_runner_kind_is_refused():
    with pytest.raises(ValueError, match=r"derived workflow 'ci-test-lab', job 'test-lab'.*"
                                         r"'self-hosted-debian' already sets `DELIVERY_DOCKER_BOOTSTRAP: 1`"):
        _lab_workflows(_lab_text(gate=_LAB_GATE.replace("NETCTL_MGMT_SUBNET: 10.128.0.0/24",
                                                        'DELIVERY_DOCKER_BOOTSTRAP: "0"')))


def test_declared_key_switches_off_the_gate_file():
    _, files = _lab_workflows(_lab_text(tail="workflows:\n  ci-test-lab:\n    handwritten: the lab, by hand\n"))
    assert _LAB_PATH in files and not files[_LAB_PATH].derived
    assert files[".github/workflows/ci.yml"].derived
    ci = _lab_rendered(_lab_text(tail="workflows:\n  ci-test-lab:\n    handwritten: the lab, by hand\n"),
                       ".github/workflows/ci.yml")
    # the members are still out of ci.yml: the product's own gate file runs them
    assert "exec ./netctl.sh test unit" in ci and "exec ./netctl.sh test system" not in ci


def test_a_declared_ci_still_rules_on_the_members():
    """Carried from Task 3: with ci.yml the product's own, `gates` still runs, so a member's refusal is reached."""
    text = _lab_text(tail="workflows:\n  ci:\n    handwritten: our own\n").replace(
        "system: { task: ship, unattended: true }", "system: { task: ship, unattended: false }")
    with pytest.raises(ValueError, match=r"'test system' is a member of the gate of `test lab`.*unattended: false"):
        _lab_workflows(text)


def test_a_declared_ci_does_not_refuse_a_members_timeout():
    """A member's `timeout_minutes:` is read by the gate's file, so ci.yml being the product's own does not make it
    a key that shapes nothing."""
    _, files = _lab_workflows(_lab_text(system=", ci: { timeout_minutes: 30 }",
                                        tail="workflows:\n  ci:\n    handwritten: our own\n"))
    assert files[_LAB_PATH].derived


def test_gate_without_cadence_has_no_schedule():
    on = _lab_doc(_lab_text(more="timeout_minutes: 95"))[True]
    assert "schedule" not in on and "workflow_dispatch" in on


def test_gate_manual_cadence_has_no_schedule():
    on = _lab_doc(_lab_text(more="cadence: manual"))[True]
    assert "schedule" not in on and "workflow_dispatch" in on


def test_gate_cron_cadence_is_its_cron():
    on = _lab_doc(_lab_text(more='cadence: "0 4 * * 1"'))[True]
    assert on["schedule"] == [{"cron": "0 4 * * 1"}]


def test_gate_without_timeout_has_no_job_limit():
    assert "timeout-minutes" not in _lab_doc(_lab_text(more="cadence: nightly"))["jobs"]["test-lab"]


def test_the_empty_push_line_names_the_gate_file(capsys):
    text = _lab_text(tail="workflows:\n  release:\n    handwritten: by hand\n").replace(
        "      unit: { task: ship, unattended: true }\n", "").replace('command: "test unit"', 'command: "test system"')
    _, files = _lab_workflows(text)
    assert ".github/workflows/ci.yml" not in files and _LAB_PATH in files
    captured = capsys.readouterr()
    assert "ci-test-lab.yml" in captured.out + captured.err


def test_a_gate_label_with_an_expression_is_refused():
    with pytest.raises(ValueError, match=r"`ci: gate: label:` with a `\$\{\{` expression.*GitHub would evaluate it"):
        _loaded('ci: { gate: { label: "${{ github.actor }}" } }')


def test_a_gate_whose_members_all_run_after_all_is_refused():
    from simplon.tasks import cipipeline
    text = _lab_text().replace("depends_on: [down, up, seed, system, acceptance-dataplane, report]",
                               "depends_on: [report]")
    loaded = manifest.load(text, catalogue=catalogue.load())
    with pytest.raises(ValueError, match=r"the gate of `test lab` has no member that runs in order.*`test report`.*"
                                         r"ci-test-lab.yml would verify nothing"):
        cipipeline.gates(loaded)


@pytest.mark.parametrize("ci", ["workflows:\n  ci:\n    handwritten: our own\n", ""])
def test_a_member_variant_key_in_a_product_owned_gate_file_is_refused_naming_that_file(ci):
    tail = ci + ("" if ci else "workflows:\n") + "  ci-test-lab:\n    handwritten: the lab, by hand\n"
    with pytest.raises(ValueError) as refused:
        _lab_workflows(_lab_text(system=", ci: { timeout_minutes: 30 }", tail=tail))
    said = str(refused.value)
    assert "'test system' declares `ci: timeout_minutes:`" in said
    assert "the product's own ci-test-lab.yml" in said and "runs in ci.yml" not in said


def test_a_member_also_in_a_derived_gate_keeps_its_variant_key():
    """A member of a product-owned gate file that is also a member of a derived one: the derived file reads its
    `timeout_minutes:`, so the key shapes something and is not refused."""
    text = _lab_text(system=", ci: { timeout_minutes: 30 }",
                     tail="workflows:\n  ci-test-lab:\n    handwritten: the lab, by hand\n").replace(
        '      report: { task: "test:report" }\n',
        '      report: { task: "test:report" }\n'
        '      smoke: { depends_on: [system], help: "Smoke.", ci: { gate: { label: needs-smoke } } }\n')
    _, files = _lab_workflows(text)
    assert not files[_LAB_PATH].derived
    smoke = _lab_rendered(text, ".github/workflows/ci-test-smoke.yml")
    assert "exec ./netctl.sh test system" in smoke and "timeout-minutes: 30" in smoke


def test_an_after_all_deploy_member_tears_down_last_and_always():
    """A teardown is a Deploy member with `after_all: true`: it renders after the report with `if: always()`, so
    it runs after a red member too, and it prepares nothing. A leaf named twice in one plan runs once, so a
    pre-clean `down` and the final teardown are two commands."""
    text = _lab_text().replace(
        "      seed: { task: ship, unattended: true }\n",
        "      seed: { task: ship, unattended: true }\n"
        "      teardown: { task: ship, unattended: true, after_all: true }\n").replace(
        "depends_on: [down, up, seed, system, acceptance-dataplane, report]",
        "depends_on: [down, up, seed, system, acceptance-dataplane, report, teardown]")
    doc = _lab_doc(text)
    runs = [step["run"].removeprefix("exec ./netctl.sh ") for step in _gated_steps(doc) if "run" in step]
    assert runs[-3:] == ["test report", "deploy teardown", "support ci-disk-cleanup"]
    teardown = _lab_step(doc, "deploy teardown")
    assert teardown["if"] == "always()" and "id" not in teardown
    assert "teardown" not in _lab_step(doc, "test system")["if"]
    assert "teardown" not in _lab_rendered(text, ".github/workflows/ci.yml")


def _lab_with_env_param(name: str) -> str:
    """The lab, its `test system` member a body with a parameter that `ci: params:` binds to `$name`."""
    return (_lab_text()
            .replace('tasks:\n', 'tasks:\n  pick: { impl: "simplon.test_impls:target_and_mode", help: "Pick." }\n', 1)
            .replace("system: { task: ship, unattended: true }",
                     f"system: {{ task: pick, unattended: true, ci: {{ params: {{ target: {{ env: {name} }} }} }} }}"))


def test_a_gate_env_reaches_a_members_env_param():
    """si#863 final review: the gate's `env:` (si#861) is the gated job's, so a member's `ci: params:` may read
    it - `_parameters` asks per job, and the gate's names are that job's."""
    assert _lab_step(_lab_doc(_lab_with_env_param("NETCTL_MGMT_SUBNET")),
                     'test system -- "$NETCTL_MGMT_SUBNET"')


def test_a_members_env_param_the_gate_does_not_set_is_refused_at_generation():
    """The other side of the same seam: a name neither the gate nor GitHub sets would expand to nothing on the
    runner, so generation refuses it with `_parameters`' own message."""
    with pytest.raises(ValueError, match=r"`params: target` reads \$NOPE, and NOPE is set by no `env:`"):
        _lab_rendered(_lab_with_env_param("NOPE"))
