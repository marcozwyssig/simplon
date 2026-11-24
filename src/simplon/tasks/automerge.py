"""The derived auto-merge workflow of a product that writes `merge: auto` (si#874).

THIS MODULE DECIDES what `.github/workflows/auto-merge.yml` listens to and what its one job is given, as a
`workflowschema.Workflow`; `cipipeline.to_workflow` renders it, the kernel step `auto-merge` as the generated
`MERGE_SCRIPT` (`simplon.model.automerge`) with its environment, as si#861's decide job is rendered.

The trigger workflows are the CI workflow and every gate's workflow, derived or declared. `workflow_run` names
them by their `name:`, the script asks for their runs by file, so both are read off the workflows
`support github workflows` writes (`ci`, `gate_workflows`). Cadence workflows are no triggers: a nightly run
says nothing about a pull request's commit.
"""
from __future__ import annotations

from collections.abc import Mapping

from simplon.manifest.load import Manifest
from simplon.model import automerge as policy
from simplon.model import workflowschema
from simplon.tasks import cipipeline, workflowgen

#: The `workflows:` key the derived workflow stands in for, which switches it off (the one switch rule), and its file.
KEY = "auto-merge"
PATH = ".github/workflows/auto-merge.yml"

#: A run that hangs is neither green nor red: the job asks GitHub a handful of questions and merges.
TIMEOUT_MINUTES = 10

#: The job's filter on the two events (decision 9 and the event filter of #874): a completed trigger run that
#: succeeded and was not a scheduled one, or the merge label just added. The label is the policy's; a label is a
#: name GitHub restricts, and the policy's own is a plain word, so it is written into the expression as it is.
CONDITION = (
    "(github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success' "
    "&& github.event.workflow_run.event != 'schedule') || (github.event_name == 'pull_request_target' "
    f"&& github.event.label.name == '{policy.LABEL}')")

#: The token's scopes, each with the reason netctl measured or si#874 decided.
PERMISSIONS = (
    ("contents", "write", "the squash merge writes the base branch and deletes the head branch"),
    ("pull-requests", "write", "the merge itself, and reading the pull requests (rule token-scope)"),
    ("actions", "write", "dispatching the CI workflow on the base after the merge (rule dispatch-ci-on-base); "
                         "without it the dispatch is refused, netctl run 30950192001"),
    ("issues", "write", "GitHub closes the issues the pull request names as the merging actor, which needs it "
                        "(netctl#1429)"),
)


def _file(workflow: workflowgen.Workflow) -> str:
    return workflow.path.rsplit("/", 1)[-1]


def _readable(workflow: workflowgen.Workflow, role: str) -> None:
    """A hand-written workflow's `name:` and trigger are in a file the kernel does not read, so neither the
    `workflow_run` filter nor rule 7's dispatch could be derived from it. A DIAGNOSIS: a guessed name would be a
    filter that never fires, green over nothing."""
    if workflow.handwritten:
        raise ValueError(
            f"merge: auto: {role} `{workflow.key}` ({workflow.path}) is declared hand-written, so the kernel "
            f"cannot read its `name:`, which `workflow_run` listens for, nor whether it can be dispatched. Declare "
            f"`{workflowgen.SECTION}: {workflow.key}:` with its jobs so the kernel writes it, or drop `merge: auto` "
            f"and keep an auto-merge workflow of your own")


def _dispatchable(on: object) -> bool:
    """Whether a rendered `on:` carries `workflow_dispatch`, in each shape GitHub reads: a word, a list, a map."""
    if isinstance(on, str):
        return on == "workflow_dispatch"
    if isinstance(on, (list, tuple)):
        return "workflow_dispatch" in on
    return isinstance(on, Mapping) and "workflow_dispatch" in on


def derive(manifest: Manifest, data: Mapping[str, object], ci: workflowgen.Workflow | None,
           gate_workflows: Mapping[str, workflowgen.Workflow]) -> cipipeline.Derivation:
    """The auto-merge workflow as the generated model.

    `ci` is the product's CI workflow, derived or declared under `workflows: ci:`, None when there is neither;
    `gate_workflows` is each gate's workflow by its key (`ci-test-lab`), derived or declared. Both are refused
    where the merge could not be what the policy says: no CI workflow leaves nothing to gate the merge, and one
    without `workflow_dispatch` could not be dispatched on the base after it (rule `dispatch-ci-on-base`). Both
    are DIAGNOSES naming the way out.
    """
    if ci is None:
        raise ValueError(
            "merge: auto: the product has no CI workflow - none is derived (no unattended leaf under `ci build` or "
            f"`ci test` outside a gate) and none is declared under `{workflowgen.SECTION}: {cipipeline.KEY}:` - so "
            "nothing gates the merge. Place a push leaf, declare a CI workflow of your own, or drop `merge: auto`")
    _readable(ci, "the CI workflow")
    if not _dispatchable(ci.on):
        raise ValueError(
            f"merge: auto: the CI workflow `{ci.key}` ({ci.path}) has no `workflow_dispatch` trigger, so it could "
            f"not be dispatched on the base branch after a merge, and the merged commit would stay unverified. "
            f"Add `workflow_dispatch` to its `on:`")
    gated = []
    labels = []
    for run in cipipeline.gates(manifest):
        workflow = gate_workflows[cipipeline._key_of(run.path)]
        _readable(workflow, f"the workflow of the gate of `{run.words}`")
        gated.append(workflow)
        if run.gate.label:
            labels.append(workflowschema.GateLabel(workflow=_file(workflow), label=run.gate.label))
    runner, runs_on = cipipeline.runner_of(data)
    job = workflowschema.Job(
        key=KEY, step=(workflowschema.Step(kernel_step=cipipeline.AUTO_MERGE),), condition=CONDITION,
        timeout_minutes=TIMEOUT_MINUTES,
        runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[runner.kind], labels=runs_on),
        merge=workflowschema.Merge(ci_workflow=_file(ci), triggers=tuple(_file(w) for w in (ci, *gated)),
                                   labels=tuple(labels)))
    triggers = (
        workflowschema.Trigger(event="workflow_run", workflows=tuple(w.name for w in (ci, *gated)),
                               types=("completed",)),
        workflowschema.Trigger(event="pull_request_target", types=("labeled",)))
    permissions = tuple(workflowschema.Permission(scope=scope, access=access, reason=reason)
                        for scope, access, reason in PERMISSIONS)
    model = workflowschema.Workflow(path=PATH, title=KEY, trigger=triggers, job=(job,), permission=permissions)
    return cipipeline.Derivation(model, cipipeline.Selection((), ()))
