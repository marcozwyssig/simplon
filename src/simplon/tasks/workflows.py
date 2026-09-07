"""The verb that makes the workflow generator addressable (si#40), beside `tasks:generate`.

DELIBERATELY THE SAME SHAPE AS `tasks:generate`, down to `--check` returning 1. That is not imitation for
its own sake: the generated files are COMMITTED rather than conjured at run time - the whole point of the
exercise is that a workflow stays greppable, diffable and reviewable - so the manifest and the file can
disagree, and one command has to serve both the pre-commit hook and the CI step that notices. A second
entry point for the gate would be a second thing to remember.

`--check` IS THE VALUE HERE, more than the generating is. A CLI module that has drifted from its manifest
is caught the moment somebody runs a command it no longer registers. A workflow that has drifted is
caught by nothing at all: it runs, it goes green, and it tests whatever it happens to say. That is not
hypothetical - agile-cockpit kept three assertions pointed at a `.gitlab-ci.yml` nothing had executed for
months, and the assertions passed the whole time.

A KERNEL MECHANISM under netctl#1280's rule: nothing here knows a product. The repo root, the manifest
and its filename arrive through `simplon.context.current()`, and everything that is genuinely the
product's - runner images, triggers, permissions, schedules, secrets - is data in its own manifest
section. What the kernel contributes is the step SEQUENCE, which was already in the manifest, and the
invariants a product should not have to remember.
"""
from __future__ import annotations

from simplon import context, log, workflowgen


def generate(check: bool = False) -> int:
    """Regenerate the product's GitHub workflows from its manifest; `--check` reports drift, writes nothing.

    `--check` returns 1 when a generated workflow disagrees with the manifest, and ALSO when the workflows
    directory holds a file no manifest entry names. The second case is the one si#40 was raised for: a
    workflow nobody generates and nobody declares is indistinguishable, from the directory, from one
    somebody maintains - and the way it goes wrong is that it keeps running long after it stopped meaning
    anything. Declaring it costs one line, either as a generated workflow or as `handwritten: "<why>"`.

    A workflow declared hand-written is REPORTED on every run rather than passed over in silence. It is a
    legitimate answer - some files really are hand-work, and simplon's own release workflow is two-thirds
    prose - but it is an answer somebody chose, so it is said out loud each time rather than becoming a
    thing nobody remembers is true.
    """
    ctx = context.current()
    source = ctx.manifest_path.name
    workflows = workflowgen.parse(ctx.manifest_data())
    manifest = ctx.manifest()

    if not check:
        changed = workflowgen.write(workflows, ctx.root, manifest=manifest, product=ctx.name,
                                    source=source)
        absent = tuple(w.path for w in workflows
                       if not w.generated and not (ctx.root / w.path).exists())
        _report_handwritten(workflows, absent)
        if changed:
            log.ok(f"regenerated {len(changed)} workflow(s) from {source} - commit them: "
                   f"{', '.join(changed)}")
        else:
            generated = [w.path for w in workflows if w.generated]
            log.ok(f"{len(generated)} workflow(s) already up to date")
        # The scan runs on a WRITE too. Generating is exactly when a file left behind by a rename stops
        # having an owner, and a run that had just rewritten the directory is the cheapest moment to say
        # so - rather than leaving it for whoever next happens to run the gate.
        return 1 if absent else _report_unmanaged(workflowgen.unmanaged(workflows, ctx.root), source)

    report = workflowgen.check(workflows, ctx.root, manifest=manifest, product=ctx.name, source=source)
    for path in report.agreed:
        log.ok(f"{path} agrees with {source}")
    _report_handwritten(workflows, report.absent)
    for drift in report.drifted:
        log.warn(f"{drift.path} disagrees with {source} - regenerate with "
                 f"`{ctx.name} support workflows`")
        print(drift.diff)
    rc = _report_unmanaged(report.unmanaged, source)
    return 1 if (report.drifted or report.absent) else rc


def _report_handwritten(workflows: tuple[workflowgen.Workflow, ...],
                        absent: tuple[str, ...] = ()) -> None:
    """Name every declared hand-written workflow, and why, on every run.

    Said out loud rather than counted, because the reason is the part that decays: "this one is
    hand-written" is easy to keep believing after it has stopped being true, and a line that repeats the
    stated reason is what gives somebody the chance to notice it no longer holds.

    A declaration whose FILE is gone is reported as the error it is, not as a hand-written workflow. It
    is the mirror image of an unmanaged file - a name with nothing behind it rather than a file with
    nobody in front of it - and it fails the same way, by looking accounted for.
    """
    for workflow in workflows:
        if workflow.generated:
            continue
        if workflow.path in absent:
            log.error(f"{workflow.path} is declared hand-written and does not exist - the declaration "
                      f"names a file nothing has: restore it, or drop the entry")
        else:
            log.info(f"{workflow.path} is declared hand-written: {workflow.handwritten}")


def _report_unmanaged(paths: tuple[str, ...], source: str) -> int:
    """0 when every file in the directory has an owner, 1 when one does not - and it says which.

    The rc is the point. A warning about an unowned workflow is a warning nobody reads; the same fact as
    a non-zero exit is the pre-commit hook and the CI step that stops it being written in the first
    place. What it costs to satisfy is one manifest line, and the message says which two forms that line
    can take, so the fix never requires reading this source.
    """
    if not paths:
        return 0
    log.warn(f"{len(paths)} workflow file(s) in {workflowgen.DIRECTORY}/ that {source} does not name: "
             f"{', '.join(paths)}")
    log.warn("a workflow nothing declares is one nothing keeps honest - declare it under "
             "`workflows:`, or say `handwritten: \"<why>\"` if it is deliberately somebody's own")
    return 1
