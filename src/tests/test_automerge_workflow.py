"""si#874: `merge: auto` derives `.github/workflows/auto-merge.yml` through the workflow model.

`automerge.derive` builds a `workflowschema.Workflow` (the `workflow_run` and `pull_request_target` triggers, the
workflow's permissions, the job's condition, the kernel step `auto-merge`), and `cipipeline.to_workflow` renders
it, the kernel step as the generated `MERGE_SCRIPT` with its environment. The script itself is
test_automerge_script.py's.
"""
from __future__ import annotations

import pytest
import yaml

from simplon.manifest import catalogue
from simplon.manifest import load as manifest

from conftest import ROOT

#: netctl-shaped: a self-hosted machine, a push leaf, and a gate on `test lab` with a label.
_NETCTL = """
tasks:
  ship: { impl: "simplon.test_impls:nullary", help: "Ship." }
runner: { kind: self-hosted-debian, labels: ghr-1 }
%(merge)s
ci:
  test:
    commands:
      unit: { task: ship, unattended: true }
      system: { task: ship, unattended: true }
      lab:
        depends_on: [system]
        help: "Lab."
        ci:
          gate: { paths: ["src/**"], label: needs-lab }
%(tail)s"""

_PATH = ".github/workflows/auto-merge.yml"
_GOLDEN = ROOT / "src/tests/fixtures/workflows/auto-merge.golden.yml"


def _text(merge: str = "merge: auto", tail: str = "") -> str:
    return _NETCTL % {"merge": merge, "tail": tail}


def _workflows(text: str):
    from simplon.tasks import cipipeline
    loaded = manifest.load(text, catalogue=catalogue.load(), manifest_path="netctl.yaml")
    return loaded, {wf.path: wf for wf in cipipeline.workflows(loaded, yaml.safe_load(text), product="netctl")}


def _rendered(text: str | None = None, path: str = _PATH) -> str:
    from simplon.tasks import workflowgen
    loaded, files = _workflows(text or _text())
    return workflowgen.render(files[path], manifest=loaded, product="netctl", source="netctl.yaml", artifacts={})


def _doc(text: str | None = None) -> dict:
    return yaml.safe_load(_rendered(text))


def _merge_step(doc: dict) -> dict:
    from simplon.model import automerge as policy
    return next(step for step in doc["jobs"]["auto-merge"]["steps"] if step.get("run") == policy.MERGE_SCRIPT)


def test_golden():
    assert _rendered() == _GOLDEN.read_text(encoding="utf-8")


def test_derive_is_a_workflow_model():
    from simplon.model import workflowschema
    from simplon.tasks import automerge, cipipeline
    text = _text()
    loaded = manifest.load(text, catalogue=catalogue.load(), manifest_path="netctl.yaml")
    data = yaml.safe_load(text)
    files = {wf.key: wf for wf in cipipeline.workflows(loaded, data, product="netctl")}
    derivation = automerge.derive(loaded, data, files["ci"], {"ci-test-lab": files["ci-test-lab"]})
    assert isinstance(derivation.model, workflowschema.Workflow)
    assert (derivation.model.title, derivation.model.path) == ("auto-merge", _PATH)
    assert [step.kernel_step for job in derivation.model.job for step in job.step] == ["auto-merge"]


def test_triggers():
    doc = _doc()
    on = doc[True]  # YAML 1.1 reads the bare key `on` as a bool
    assert on == {"workflow_run": {"workflows": ["ci", "ci-test-lab"], "types": ["completed"]},
                  "pull_request_target": {"types": ["labeled"]}}
    assert doc["jobs"]["auto-merge"]["if"] == (
        "(github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success' "
        "&& github.event.workflow_run.event != 'schedule') || (github.event_name == 'pull_request_target' "
        "&& github.event.label.name == 'auto-merge')")


def test_permissions_and_concurrency():
    doc = _doc()
    assert doc["permissions"] == {"contents": "write", "pull-requests": "write", "actions": "write",
                                  "issues": "write"}
    assert doc["concurrency"] == {
        "group": "auto-merge-${{ github.event.workflow_run.head_branch || github.event.pull_request.head.ref }}",
        "cancel-in-progress": False}


def test_no_checkout_and_env():
    doc = _doc()
    job = doc["jobs"]["auto-merge"]
    assert job["runs-on"] == "ghr-1"
    assert isinstance(job["timeout-minutes"], int)
    assert not any(str(step.get("uses", "")).startswith("actions/checkout") for step in job["steps"])
    assert not any("netctl.sh" in str(step.get("run", "")) for step in job["steps"])
    env = _merge_step(doc)["env"]
    assert env == {
        "GH_TOKEN": "${{ github.token }}", "GH_REPO": "${{ github.repository }}",
        "BRANCH": "${{ github.event.workflow_run.head_branch || github.event.pull_request.head.ref }}",
        "SHA": "${{ github.event.workflow_run.head_sha || github.event.pull_request.head.sha }}",
        "EVENT": "${{ github.event_name }}", "CI_WORKFLOW": "ci.yml", "TRIGGERS": "ci.yml ci-test-lab.yml",
        "GATES": "ci-test-lab.yml needs-lab"}


def test_rule_comments_come_from_the_policy():
    from simplon.model import automerge as policy
    flat = " ".join(line.lstrip("# ").strip() for line in _rendered().splitlines() if line.lstrip().startswith("#"))
    for key, reason, source in policy.RULES:
        assert key in flat and source in flat
        assert " ".join(reason.split()) in flat, key


_OWN_CI = """workflows:
  ci:
    path: .github/workflows/build.yml
    name: Build and test
    on: { pull_request: null, %s }
    jobs:
      test: { runs-on: ubuntu-latest, steps: [ { command: test unit } ] }
"""


def test_declared_ci_workflow_is_the_trigger():
    doc = _doc(_text(tail=_OWN_CI % "workflow_dispatch: null"))
    assert doc[True]["workflow_run"]["workflows"] == ["Build and test", "ci-test-lab"]
    env = _merge_step(doc)["env"]
    assert (env["CI_WORKFLOW"], env["TRIGGERS"]) == ("build.yml", "build.yml ci-test-lab.yml")


def test_ci_without_dispatch_is_refused():
    with pytest.raises(ValueError, match=r"merge: auto.*`ci`.*no `workflow_dispatch`.*Add `workflow_dispatch`"):
        _workflows(_text(tail=_OWN_CI % "push: null"))


def test_handwritten_ci_is_refused():
    with pytest.raises(ValueError, match=r"merge: auto.*`ci`.*hand-written.*cannot read its `name:`"):
        _workflows(_text(tail="workflows:\n  ci: { handwritten: \"ours\" }\n"))


def test_no_ci_workflow_is_refused():
    # Every push leaf is a gate member and another workflow is declared, so no ci.yml is derived and none declared.
    text = _text(tail="workflows:\n  docs:\n    jobs:\n      d: { runs-on: ubuntu-latest, steps: [ { command: test system } ] }\n"
                 ).replace("      unit: { task: ship, unattended: true }\n", "")
    with pytest.raises(ValueError, match=r"merge: auto.*no CI workflow.*nothing gates the merge"):
        _workflows(text)


def test_declared_auto_merge_switches_it_off():
    _, files = _workflows(_text(tail="workflows:\n  auto-merge: { handwritten: \"ours\" }\n"))
    assert files[_PATH].handwritten == "ours"
    assert not files[_PATH].derived


def test_no_merge_section_is_byte_identical():
    _, without = _workflows(_text(merge=""))
    assert _PATH not in without
    _, with_merge = _workflows(_text())
    assert set(with_merge) - set(without) == {_PATH}
    for path in without:
        assert _rendered(_text(), path) == _rendered(_text(merge=""), path), path
