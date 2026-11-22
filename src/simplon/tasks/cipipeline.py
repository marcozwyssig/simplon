"""What the derived CI workflow of a product contains, decided from its manifest (si#858).

THIS MODULE DECIDES which leaves the workflow runs, in which order, and the model instances that
describe it (spec docs/superpowers/specs/2026-11-22-derived-workflows-design.md, sections 4 and 5).
It LEAVES TO `workflowgen` the text: how an instance is written out as a GitHub workflow file. The
split keeps the decision testable without parsing YAML and the rendering free of manifest knowledge.

This first part reads the one product value the decision needs before any leaf is chosen: the
machine the jobs run on, then chooses the leaves and puts them in order. `derive` builds the workflow as
the generated model (`simplon.model.workflowschema`, #857), and `to_workflow` turns that model into the
`workflowgen.Workflow` the existing renderer writes.
"""
from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, NamedTuple

from simplon.manifest import artifactsection, context, runners
from simplon.manifest.load import Manifest
from simplon.model import workflowschema
from simplon.model.command import TaskCommand
from simplon.model.task import class_ref
from simplon.tasks import handoff, workflowgen

if TYPE_CHECKING:
    from simplon.manifest.artifactsection import Declared


def runner_of(data: Mapping[str, object]) -> tuple[runners.Runner, tuple[str, ...]]:
    """The machine kind and the `runs-on:` labels for the product's top-level `runner:` section.

    An absent section is the normal case and means `github-ubuntu`; `runners.resolve` owns every
    refusal (an unknown kind, a self-hosted kind with no label), so this only reads and delegates.
    The key is the literal `"runner"` and not `runners.KEY`: the refusal census and the firn coverage
    test find a section by its literal key (si#435).
    """
    return runners.resolve(data.get("runner"), "runner:")


def runner() -> tuple[runners.Runner, tuple[str, ...]]:
    """`runner_of` for the registered product.

    The document is fetched and HANDED ON rather than read here: the refusal census walks what the
    kernel passes `manifest_data()` to, so this is what makes `runner:` a section the kernel reads
    (and `Product.runner` a modelled one) without this module being excused by hand.
    """
    return runner_of(context.current().manifest_data())


#: The phases whose leaves a derived CI runs; `release` is the CD half's business (si#858).
CI_PHASES = ("build", "test")

#: Why a leaf with `unattended: false` is not in the workflow.
ATTENDED = "it needs a person at the terminal (`unattended: false`)"


class Leaf(NamedTuple):
    """One command the CI runs: `words` is the command line as the CLI types it (`test lab smoke` for a
    nested group), `spec` the command's resolved spec."""

    words: str
    spec: TaskCommand


class Skipped(NamedTuple):
    """A leaf the CI leaves out, and why: `ci: { skip: }`'s reason, or `ATTENDED`. The reason is kept so the
    generated file can say where a reader will be standing when they wonder (as `workflowgen.derive` does)."""

    words: str
    reason: str


class Selection(NamedTuple):
    leaves: tuple[Leaf, ...]
    skipped: tuple[Skipped, ...]


def _words(group: str, name: str) -> str:
    return f"{group.replace('.', ' ')} {name}"


def select(manifest: Manifest, *, artifacts: "Mapping[str, Declared]") -> Selection:
    """The leaves a derived CI runs, in an order every consumer can be run in (si#858, spec section 4).

    A leaf is a `TaskCommand` in a `build` or `test` group (nested groups included) of the CI area, in the
    manifest's own order; an aggregate is passed over because its members are leaves in their own right, and
    a job stops at its first red step, so an aggregate would fold several verdicts into one. A leaf that
    nobody has ruled on is refused (`workflowgen.require_unattended`, one wording for both derivations);
    `unattended: false` and `ci: { skip: }` go to `skipped`, never silently absent.

    A CONSUMER OF A LEAF THE CI DOES NOT RUN IS REFUSED, because the run would fail on a missing file far
    from the cause. `artifacts` carries the product's declarations so an artifact with a `registry:` is
    exempt, as in `handoff.plan`: it is fetched, not produced here. `{}` means the product declares none, so
    every such consumer is refused - the safe reading, since an exemption must be claimed by the caller.
    """
    chosen: list[Leaf] = []
    skipped: list[Skipped] = []
    for group, members in manifest.commands.items():
        if group.split(".", 1)[0] not in CI_PHASES or manifest.area_of(group) != "ci":
            continue
        for name, spec in members.items():
            if not isinstance(spec, TaskCommand):
                continue
            words = _words(group, name)
            if spec.ci_skip:
                # Opted out by the product: skipped even where `unattended:` is undeclared, which only
                # matters to a leaf that would run.
                skipped.append(Skipped(words, spec.ci_skip))
                continue
            workflowgen.require_unattended(spec, words, "derived CI")
            if not spec.unattended:
                skipped.append(Skipped(words, ATTENDED))
            else:
                chosen.append(Leaf(words, spec))
    _refuse_consumers_of_absent_producers(manifest, chosen, dict(skipped), artifacts)
    return Selection(order(chosen), tuple(skipped))


def _refuse_consumers_of_absent_producers(manifest: Manifest, chosen: Sequence[Leaf],
                                          skipped: Mapping[str, str], artifacts: "Mapping[str, Declared]") -> None:
    running = {leaf.words for leaf in chosen}
    absent: dict[str, list[tuple[str, str]]] = {}
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            words = _words(group, name)
            if words in running or not isinstance(spec, TaskCommand):
                continue
            why = skipped.get(words) or f"it is not a CI leaf (it is in the '{group}' group)"
            for artifact in handoff._bound(spec.produces):
                absent.setdefault(artifact, []).append((words, why))
    for leaf in chosen:
        for artifact in handoff._bound(leaf.spec.consumes):
            declared = artifacts.get(artifact)
            if declared is not None and declared.registry:
                continue
            if any(artifact in handoff._bound(other.spec.produces) for other in chosen):
                continue
            for producer, why in absent.get(artifact, ()):
                raise ValueError(
                    f"derived CI: '{leaf.words}' consumes '{artifact}', which '{producer}' produces, and "
                    f"'{producer}' is not run by the CI ({why}) - the run would fail on a missing file. "
                    f"Run the producer in CI, or give '{artifact}' a `registry:` it is fetched from")


def order(leaves: Sequence[Leaf]) -> tuple[Leaf, ...]:
    """A stable topological sort: a consumer comes after the leaves that produce what it consumes.

    Among the leaves with nothing pending the earliest in the given order goes first, so a leaf moves only
    as far as its producers force it and nothing else is reshuffled. A product's own order stays the
    answer wherever it is already right (si#858).
    """
    produced: dict[str, list[int]] = {}
    for at, leaf in enumerate(leaves):
        for artifact in handoff._bound(leaf.spec.produces):
            produced.setdefault(artifact, []).append(at)
    before: list[dict[int, str]] = [{} for _ in leaves]
    for at, leaf in enumerate(leaves):
        for artifact in handoff._bound(leaf.spec.consumes):
            for maker in produced.get(artifact, ()):
                before[at].setdefault(maker, artifact)
    done: set[int] = set()
    out: list[Leaf] = []
    while len(done) < len(leaves):
        ready = next((at for at in range(len(leaves)) if at not in done and all(m in done for m in before[at])), None)
        if ready is None:
            raise ValueError(_cycle(leaves, before, done))
        done.add(ready)
        out.append(leaves[ready])
    return tuple(out)


def _cycle(leaves: Sequence[Leaf], before: Sequence[Mapping[int, str]], done: set[int]) -> str:
    """Name the loop: from the first leaf left over, follow each one's pending producer until one repeats."""
    at = next(i for i in range(len(leaves)) if i not in done)
    walk: list[int] = []
    while at not in walk:
        walk.append(at)
        at = next(m for m in before[at] if m not in done)
    loop = walk[walk.index(at):]
    steps = []
    for consumer in loop:
        maker = next(m for m in before[consumer] if m in loop)
        steps.append(f"'{leaves[consumer].words}' consumes '{before[consumer][maker]}' from '{leaves[maker].words}'")
    return ("derived CI: the leaves form a cycle through their artifacts, so none of them can run first: "
            + "; ".join(steps) + " - break the loop by splitting one of the artifacts")


# --- the derived workflow (si#858 task 6) ------------------------------------------------------------------

#: The `workflows:` key the derived workflow stands in for, the file it is written to, and its one job's id.
KEY = "ci"
PATH = ".github/workflows/ci.yml"
JOB = "ci"

#: The steps the kernel owns in the derived job, by the name the model carries (`Step.kernel_step`).
DOCKER_PREFLIGHT = "docker-preflight"
DISK_PREFLIGHT = "disk-preflight"
INSTALL = "install"
REPORT_UPLOAD = "report-upload"
DISK_CLEANUP = "disk-cleanup"

#: The step ids of the preparation steps. An `_`, never a `-`: a leaf's condition reads them in an expression,
#: where `steps.prepare-docker` would be a subtraction.
PREPARE = {"docker": "prepare_docker", "disk": "prepare_disk", "install": "prepare_install"}
_PREPARES = {DOCKER_PREFLIGHT: PREPARE["docker"], DISK_PREFLIGHT: PREPARE["disk"], INSTALL: PREPARE["install"]}

#: The coordinate `support install` instantiates; found in the product's tree by impl, as `runners.PREFLIGHT` is.
INSTALL_TASK = "support:install"

INSTALL_NOTE = """si#858: the product declares `toolchains:`, so the job provisions them before any leaf runs.
Every later leaf waits for this step's success: a missing toolchain would otherwise turn every leaf red."""

INSTALL_UNPLACED = """si#858: this product declares `toolchains:`, and places no command that instantiates
`support:install`, so this job provisions none of them and a leaf needing one fails for want of it. To get
it, place the coordinate and regenerate:

    install: { task: "support:install" }"""


class Derivation(NamedTuple):
    """The derived workflow as the generated model, and the selection it was built from.

    The selection travels with the model because the model carries no names (#857): a leaf's command words
    and the leaves left out are read off the selection by `to_workflow`."""

    model: workflowschema.Workflow
    selection: Selection


def _install(manifest: Manifest, data: Mapping[str, object]) -> "tuple[workflowgen.Step | None, str]":
    """`(the install step, the note for the file)`: a step only where the product declares `toolchains:` AND
    places `support:install`; declared and unplaced is a sentence in the job's note, never a guessed command."""
    if data.get("toolchains") is None:
        return None, ""
    placed = workflowgen._placed(manifest, class_ref(INSTALL_TASK))
    if not placed:
        return None, INSTALL_UNPLACED
    return workflowgen.Step(command=placed, note=INSTALL_NOTE), ""


def _kernel_steps(manifest: Manifest, data: Mapping[str, object],
                  runner: runners.Runner) -> "tuple[dict[str, workflowgen.Step], tuple[str, ...]]":
    """The kernel steps the derived job gets, by kernel step name in job order, and what is said instead of each
    one the product has not placed. The docker and disk steps are `workflowgen`'s own (si#327, si#623), asked
    of a job on the same machine, so a derived job and a declared one get the same steps and the same notes."""
    machine = workflowgen.Job(name=JOB, runs_on="", steps=(), runner=runner)
    probe, probe_unplaced = workflowgen._docker_step(machine, manifest)
    pre, post, disk_unplaced = workflowgen._disk_steps(machine, manifest)
    install, install_unplaced = _install(manifest, data)
    steps = {name: step for name, step in ((DOCKER_PREFLIGHT, probe), (DISK_PREFLIGHT, pre), (INSTALL, install),
                                           (DISK_CLEANUP, post)) if step is not None}
    return steps, tuple(note for note in (probe_unplaced, disk_unplaced, install_unplaced) if note)


def _ci_groups(manifest: Manifest) -> list[str]:
    return [group for group in manifest.commands
            if group.split(".", 1)[0] in CI_PHASES and manifest.area_of(group) == "ci"]


def _nothing_to_run(manifest: Manifest, selection: Selection) -> str:
    groups = ", ".join(f"`{group.replace('.', ' ')}`" for group in _ci_groups(manifest))
    held = f"it holds {groups}" if groups else "it holds no `ci build` or `ci test` group"
    left = "; ".join(f"`{s.words}` - {s.reason}" for s in selection.skipped)
    alone = ", ".join(f"`{leaf.words}`" for leaf in selection.leaves)
    return (f"derived CI: `ci build` and `ci test` hold no leaf a machine may run ({held}"
            + (f"; left out: {left}" if left else "")
            + (f"; {alone} runs after all the others and has nothing to run after" if alone else "")
            + "), so the derived ci.yml would run no step - a green tick over nothing. Place a leaf with "
              "`unattended: true` under `ci build` or `ci test`, or declare `workflows: ci:` yourself")


def derive(manifest: Manifest, data: Mapping[str, object]) -> Derivation:
    """The derived CI workflow of a product, as the generated model (si#858, spec section 5).

    One job on the product's machine (`runner:`), its steps in this order: the docker probe and the disk
    preflight where the machine's disk persists and the product placed them; `support install` where the
    product declares `toolchains:`; the leaves `select` chose, in its order; the `after_all` leaves (the
    report), in their own order, so a verdict over the run comes after the run; the report's upload; the
    disk cleanup. A job with no leaf to run is refused (Review Focus 2): its file would be a green tick over
    nothing. The conditions of the steps are not here: they are GitHub's spelling of the order, and
    `to_workflow` writes them.
    """
    selection = select(manifest, artifacts=artifactsection.declared(data))
    runs = [leaf for leaf in selection.leaves if not leaf.spec.after_all]
    last = [leaf for leaf in selection.leaves if leaf.spec.after_all]
    if not runs:
        raise ValueError(_nothing_to_run(manifest, selection))
    runner, labels = runner_of(data)
    kernel, _ = _kernel_steps(manifest, data, runner)
    steps = [workflowschema.Step(kernel_step=name) for name in (DOCKER_PREFLIGHT, DISK_PREFLIGHT, INSTALL)
             if name in kernel]
    steps += [workflowschema.Step(command=leaf.spec) for leaf in (*runs, *last)]
    if any(leaf.spec.task == workflowgen.REPORT_TASK for leaf in last):
        steps.append(workflowschema.Step(kernel_step=REPORT_UPLOAD))
    if DISK_CLEANUP in kernel:
        steps.append(workflowschema.Step(kernel_step=DISK_CLEANUP))
    job = workflowschema.Job(key=JOB, step=tuple(steps),
                             runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[runner.kind], labels=labels))
    model = workflowschema.Workflow(
        path=PATH, title=KEY, job=(job,),
        trigger=tuple(workflowschema.Trigger(event=event) for event in ("pull_request", "push_main", "dispatch")))
    return Derivation(model, selection)


def _derived_note(selection: Selection) -> str:
    """What the file says about where its steps came from, and every leaf it left out with the reason, where a
    reader of the workflow is standing when they wonder."""
    head = textwrap.fill(
        "si#858: derived from this product's command tree, which declares no `workflows: ci:`. This job runs "
        "every unattended leaf of `ci build` and `ci test` in manifest order, a consumer after its producer. "
        "Every leaf after the first runs unless the run is cancelled or a preparation step went red, so one "
        "red gate hides none of the others; a leaf that runs after all the others (the report) runs last and "
        "always.", width=95)
    if not selection.skipped:
        return head
    return head + "\n\nLeft out:\n" + "\n".join(
        textwrap.fill(f"`{s.words}` - {s.reason}", width=95, subsequent_indent="  ") for s in selection.skipped)


def to_workflow(derivation: Derivation, manifest: Manifest, data: Mapping[str, object]) -> workflowgen.Workflow:
    """The model as the `workflowgen.Workflow` the renderer writes (si#858).

    THE CONDITIONS ARE WRITTEN HERE AND NOWHERE ELSE. A preparation step carries its id and no `if:`. The first
    leaf has none either: GitHub's default, `success()`, already waits for every step before it. Every later
    leaf runs `!cancelled()` and the success of each preparation step present, so one red leaf hides none of
    the others while one red preflight stops them all and shows as one red step. An `after_all` leaf and the
    upload run `always()`; the cleanup keeps `_disk_steps`'s `always()` and `continue-on-error`.
    """
    (job,) = derivation.model.job
    kind = next(name for name, known in workflowschema.RUNNER_KINDS.items() if known is job.runner.kind)
    runner = runners.TABLE[kind]
    kernel, unplaced = _kernel_steps(manifest, data, runner)
    words = {id(leaf.spec): leaf.words for leaf in derivation.selection.leaves}
    ids = [_PREPARES[step.kernel_step] for step in job.step if step.kernel_step in _PREPARES]
    gate = "${{ " + " && ".join(["!cancelled()", *(f"steps.{i}.outcome == 'success'" for i in ids)]) + " }}"
    steps: list[workflowgen.Step] = []
    first = True
    for step in job.step:
        if step.kernel_step in _PREPARES:
            prepared = kernel[step.kernel_step]
            steps.append(prepared._replace(modifiers={"id": _PREPARES[step.kernel_step], **prepared.modifiers}))
        elif step.kernel_step == DISK_CLEANUP:
            steps.append(kernel[DISK_CLEANUP])
        elif step.kernel_step == REPORT_UPLOAD:
            steps.append(workflowgen.report_upload(workflowgen.report_dir(data)))
        elif step.kernel_step:
            raise ValueError(f"derived CI: the model names a kernel step '{step.kernel_step}' nothing renders")
        else:
            spec = step.command
            assert isinstance(spec, TaskCommand)
            modifiers: dict[str, object] = {}
            if spec.after_all:
                modifiers["if"] = "always()"
            elif not first:
                modifiers["if"] = gate
            first = first and spec.after_all
            steps.append(workflowgen.Step(command=words[id(spec)], modifiers=modifiers))
    labels = job.runner.labels
    note = "\n\n".join(part for part in (workflowgen._note_of({}, runner), *unplaced,
                                          _derived_note(derivation.selection)) if part)
    ci = workflowgen.Job(name=JOB, runs_on=labels[0] if len(labels) == 1 else labels, steps=tuple(steps),
                         note=note, runner=runner, prepared=True,
                         extras=workflowgen._with_runner_env(runner, {}, f"derived workflow '{KEY}', job '{JOB}'"))
    return workflowgen.Workflow(key=KEY, path=derivation.model.path, name=derivation.model.title,
                                on=workflowgen._CI_TRIGGER, jobs=(ci,), extras=workflowgen._workflow_extras({}),
                                derived=True)
