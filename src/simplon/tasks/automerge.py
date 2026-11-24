"""The derived auto-merge workflow of a product that writes `merge: auto` (si#874).

THIS MODULE DECIDES what `.github/workflows/auto-merge.yml` listens to and what its one job is given, as a
`workflowschema.Workflow`; `cipipeline.to_workflow` renders it, the kernel step `auto-merge` as the generated
`MERGE_SCRIPT` (`simplon.model.automerge`) with its environment, as si#861's decide job is rendered.

The trigger workflows are the CI workflow and every gate's workflow, derived or declared. `workflow_run` names
them by their `name:`, the script asks for their runs by file, so both are read off the workflows
`support github workflows` writes (`ci`, `gate_workflows`); a hand-written one is read from its file under the
product root (Marco, 2026-11-24). Cadence workflows are no triggers: a nightly run says nothing about a pull
request's commit. The policy's data (the job's condition, the token's scopes) is the firn instance's.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import yaml

from simplon.manifest.load import Manifest
from simplon.model import automerge as policy
from simplon.model import workflowschema
from simplon.tasks import cipipeline, workflowgen

#: The `workflows:` key the derived workflow stands in for, which switches it off (the one switch rule), and its file.
KEY = "auto-merge"
PATH = ".github/workflows/auto-merge.yml"

#: A run that hangs is neither green nor red: the job asks GitHub a handful of questions and merges.
TIMEOUT_MINUTES = 10



def _file(workflow: workflowgen.Workflow) -> str:
    return workflow.path.rsplit("/", 1)[-1]


class Trigger(NamedTuple):
    """What the merge needs of a trigger workflow: its `name:` and its `on:`."""

    name: str
    on: object


def _trigger(workflow: workflowgen.Workflow, role: str, root: Path | None) -> Trigger:
    """A trigger workflow's `name:` and `on:`: the kernel's own for a generated one, the file's for a hand-written
    one, read now so `--check` sees a renamed workflow as drift.

    Each refusal is a DIAGNOSIS. No file: there is nothing to listen to. No `name:`: GitHub falls back to the
    file's path, and whether `workflow_run.workflows` matches that fallback is unmeasured, so it is not guessed -
    a guessed name is a filter that never fires, green over nothing."""
    if not workflow.handwritten:
        return Trigger(workflow.name, workflow.on)
    assert root is not None, "a hand-written trigger workflow is read from the product root, and none was given"
    said = f"merge: auto: {role} `{workflow.key}` is declared hand-written"
    target = root / workflow.path
    if not target.is_file():
        raise ValueError(
            f"{said}, and there is no file at {workflow.path} to read its `name:` and `on:` from. Commit the "
            f"workflow at that path, or take `{workflow.key}` out of `{workflowgen.SECTION}:` so the kernel derives it")
    try:
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{said}, and {workflow.path} is not a workflow: it is not valid YAML ({exc})") from exc
    if not isinstance(doc, Mapping):
        raise ValueError(f"{said}, and {workflow.path} is not a workflow: it is not a mapping. Fix the file")
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            f"{said}, and {workflow.path} has no `name:`, which `workflow_run` listens for; GitHub's fallback to "
            f"the file's path is not measured to match there. Add a `name:` to {workflow.path}")
    return Trigger(name, workflowgen.trigger_of(doc))


def _dispatchable(on: object) -> bool:
    """Whether a rendered `on:` carries `workflow_dispatch`, in each shape GitHub reads: a word, a list, a map."""
    if isinstance(on, str):
        return on == "workflow_dispatch"
    if isinstance(on, (list, tuple)):
        return "workflow_dispatch" in on
    return isinstance(on, Mapping) and "workflow_dispatch" in on


def derive(manifest: Manifest, data: Mapping[str, object], ci: workflowgen.Workflow | None,
           gate_workflows: Mapping[str, workflowgen.Workflow], root: Path | None = None) -> cipipeline.Derivation:
    """The auto-merge workflow as the generated model.

    `ci` is the product's CI workflow, derived or declared under `workflows: ci:`, None when there is neither;
    `gate_workflows` is each gate's workflow by its key (`ci-test-lab`), derived or declared; a hand-written one
    is read from its file under `root` (`_trigger`). Both are refused
    where the merge could not be what the policy says: no CI workflow leaves nothing to gate the merge, and one
    without `workflow_dispatch` could not be dispatched on the base after it (rule `dispatch-ci-on-base`). Both
    are DIAGNOSES naming the way out.
    """
    if ci is None:
        raise ValueError(
            "merge: auto: the product has no CI workflow - none is derived (no unattended leaf under `ci build` or "
            f"`ci test` outside a gate) and none is declared under `{workflowgen.SECTION}: {cipipeline.KEY}:` - so "
            "nothing gates the merge. Place a push leaf, declare a CI workflow of your own, or drop `merge: auto`")
    read = _trigger(ci, "the CI workflow", root)
    if not _dispatchable(read.on):
        raise ValueError(
            f"merge: auto: the CI workflow `{ci.key}` ({ci.path}) has no `workflow_dispatch` trigger, so it could "
            f"not be dispatched on the base branch after a merge, and the merged commit would stay unverified. "
            f"Add `workflow_dispatch` to its `on:`")
    gated = []
    names = [read.name]
    labels = []
    for run in cipipeline.gates(manifest):
        workflow = gate_workflows[cipipeline._key_of(run.path)]
        names.append(_trigger(workflow, f"the workflow of the gate of `{run.words}`", root).name)
        gated.append(workflow)
        if run.gate.label:
            labels.append(workflowschema.GateLabel(workflow=_file(workflow), label=run.gate.label))
    runner, runs_on = cipipeline.runner_of(data)
    job = workflowschema.Job(
        key=KEY, step=(workflowschema.Step(kernel_step=cipipeline.AUTO_MERGE),), condition=policy.CONDITION,
        timeout_minutes=TIMEOUT_MINUTES, starts_no_container=True,
        runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[runner.kind], labels=runs_on),
        merge=workflowschema.Merge(ci_workflow=_file(ci), triggers=tuple(_file(w) for w in (ci, *gated)),
                                   labels=tuple(labels)))
    triggers = (
        workflowschema.Trigger(event="workflow_run", workflows=tuple(names),
                               types=("completed",)),
        workflowschema.Trigger(event="pull_request_target", types=("labeled",)))
    permissions = tuple(workflowschema.Permission(scope=scope, access=access, reason=reason)
                        for scope, access, reason in policy.PERMISSIONS)
    model = workflowschema.Workflow(path=PATH, title=KEY, trigger=triggers, job=(job,), permission=permissions)
    return cipipeline.Derivation(model, cipipeline.Selection((), ()))
