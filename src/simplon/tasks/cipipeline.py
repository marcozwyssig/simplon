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

import re
import textwrap
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, NamedTuple

from simplon.kernel import log
from simplon.manifest import artifactsection, runners
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


def select(manifest: Manifest, *, artifacts: "Mapping[str, Declared]", cadence: str = "") -> Selection:
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

    si#860: `cadence` is the `ci: cadence:` value of the run this selection is for, "" for the push run. A leaf
    with another cadence goes to `skipped`, named with the file it runs in, so the absent-producer check and the
    file's note both see why it is missing here. An `after_all` leaf with no cadence of its own (the report) is
    a verdict over whichever run it ends, so it is chosen for every cadence.
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
            elif spec.ci.cadence == cadence or (spec.after_all and not spec.ci.cadence):
                chosen.append(Leaf(words, spec))
            else:
                skipped.append(Skipped(words, _elsewhere(spec.ci.cadence)))
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

#: si#860: the file each `ci: cadence:` value is derived into; every cron string goes to `SCHEDULED_PATH`, one
#: job per distinct cron. The workflow's key and title is the file's stem.
NIGHTLY_CRON = "17 2 * * *"  # off the full hour on purpose, as agile-cockpit's hand-written nightly is
SCHEDULED_PATH = ".github/workflows/ci-scheduled.yml"
CADENCE_PATHS: Mapping[str, str] = {"": PATH, "nightly": ".github/workflows/ci-nightly.yml",
                                    "manual": ".github/workflows/ci-manual.yml"}

#: The job gate in `SCHEDULED_PATH`: every cron of the file starts every job, so each job runs only on its own
#: schedule, and every job on a dispatch.
_SCHEDULE_GATE = "${{{{ github.event_name == 'workflow_dispatch' || github.event.schedule == '{cron}' }}}}"


def _path_of(cadence: str) -> str:
    return CADENCE_PATHS.get(cadence, SCHEDULED_PATH)


def _key_of(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".yml")


#: Why a leaf without a cadence is missing from a cadence workflow; the note of such a file does not list it.
_PER_PUSH = "it has no `cadence:`, so it runs in ci.yml, per push"


def _elsewhere(cadence: str) -> str:
    """Why a leaf of another cadence is not in this run, naming the file it is in (si#860)."""
    if not cadence:
        return _PER_PUSH
    if cadence in CADENCE_PATHS:
        return f"it has `cadence: {cadence}`, so it runs in {_key_of(_path_of(cadence))}.yml"
    return f'it has `cadence: "{cadence}"`, so it runs in {_key_of(SCHEDULED_PATH)}.yml on that schedule'

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

#: The model's trigger events, as the `on:` keys and bodies GitHub reads. `derive` names the events and
#: `to_workflow` writes them from here, so the rendered `on:` is the model's and not a second copy; the default
#: set renders exactly `workflowgen._CI_TRIGGER`.
_TRIGGERS: Mapping[str, tuple[str, object]] = {
    "pull_request": ("pull_request", None),
    "push_main": ("push", {"branches": [workflowgen.DEFAULT_BRANCH]}),
    "dispatch": ("workflow_dispatch", None),
}

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


def _nothing_to_run(manifest: Manifest, selection: Selection, path: str) -> str:
    groups = ", ".join(f"`{group.replace('.', ' ')}`" for group in _ci_groups(manifest))
    held = f"it holds {groups}" if groups else "it holds no `ci build` or `ci test` group"
    left = "; ".join(f"`{s.words}` - {s.reason}" for s in selection.skipped)
    alone = ", ".join(f"`{leaf.words}`" for leaf in selection.leaves)
    return (f"derived CI: `ci build` and `ci test` hold no leaf a machine may run ({held}"
            + (f"; left out: {left}" if left else "")
            + (f"; {alone} runs after all the others and has nothing to run after" if alone else "")
            + f"), so the derived {_key_of(path)}.yml would run no step - a green tick over nothing. Place a "
              "leaf with `unattended: true` under `ci build` or `ci test`, or declare `workflows: ci:` yourself")


def _runs(selection: Selection) -> list[Leaf]:
    """The leaves that run in order, every one but the `after_all` ones; none of them means no derived ci.yml."""
    return [leaf for leaf in selection.leaves if not leaf.spec.after_all]


def _refuse_producers_moved_last(runs: Sequence[Leaf], last: Sequence[Leaf]) -> None:
    """An `after_all` leaf runs after every other leaf, so one that produces what another leaf consumes would run
    after its consumer: `order` put it first, and moving it last undoes that. Refused, naming both, because the
    run would fail on a missing file far from the cause."""
    for late in last:
        for artifact in handoff._bound(late.spec.produces):
            for leaf in runs:
                if artifact in handoff._bound(leaf.spec.consumes):
                    raise ValueError(
                        f"derived CI: '{leaf.words}' consumes '{artifact}', which '{late.words}' produces, and "
                        f"'{late.words}' runs after all the other leaves (`after_all`), so after its consumer - "
                        f"the run would fail on a missing file. Take `after_all` off '{late.words}', or produce "
                        f"'{artifact}' in a leaf that runs in order")


def _reports(data: Mapping[str, object]) -> str:
    """The directory the report upload archives, with testrun's refusal saying who asked for it."""
    try:
        return workflowgen.report_dir(data)
    except ValueError as missing:
        raise ValueError(
            f"derived CI: the report upload after `{workflowgen.REPORT_TASK}` archives `suites: reports:`, "
            f"and it cannot be read: {missing}") from missing


def derive(manifest: Manifest, data: Mapping[str, object]) -> Derivation:
    """The derived CI workflow of a product, as the generated model (si#858, spec section 5): the push run,
    `ci.yml`. The cadence workflows are `derive_all`'s (si#860).

    One job on the product's machine (`runner:`), its steps in this order: the docker probe and the disk
    preflight where the machine's disk persists and the product placed them; `support install` where the
    product declares `toolchains:`; the leaves `select` chose, in its order; the `after_all` leaves (the
    report), in their own order, so a verdict over the run comes after the run; the report's upload; the
    disk cleanup. A job with no leaf to run is refused (Review Focus 2): its file would be a green tick over
    nothing. The conditions of the steps are not here: they are GitHub's spelling of the order, and
    `to_workflow` writes them.
    """
    return _derive(manifest, data, ("",))


def _cadences(manifest: Manifest) -> list[str]:
    """Every `ci: cadence:` value a CI leaf that may run carries, in first-written order (si#860)."""
    found = [spec.ci.cadence for group in _ci_groups(manifest) for spec in manifest.commands[group].values()
             if isinstance(spec, TaskCommand) and not spec.ci_skip and spec.unattended and spec.ci.cadence]
    return list(dict.fromkeys(found))


def _cadence_derivations(manifest: Manifest, data: Mapping[str, object]) -> tuple[Derivation, ...]:
    """The nightly, manual and scheduled workflows, each only where a leaf carries its cadence (si#860)."""
    cadences = _cadences(manifest)
    crons = tuple(c for c in cadences if c not in CADENCE_PATHS)
    named = [(c,) for c in ("nightly", "manual") if c in cadences]
    return tuple(_derive(manifest, data, group) for group in (*named, *((crons,) if crons else ())))


def derive_all(manifest: Manifest, data: Mapping[str, object]) -> tuple[Derivation, ...]:
    """Every derived CI workflow (si#860): `ci.yml` first, then `ci-nightly.yml`, `ci-manual.yml` and
    `ci-scheduled.yml`, each only when a leaf carries its cadence. `derive`'s refusal of a push run with nothing
    to run stands here too (Review Focus 2)."""
    return (derive(manifest, data), *_cadence_derivations(manifest, data))


def _derive(manifest: Manifest, data: Mapping[str, object], cadences: tuple[str, ...]) -> Derivation:
    """One derived workflow: a job per cadence value, all of them in the one file those values go to. Only a
    cron string shares a file with others, so only `ci-scheduled.yml` has more than one job (si#860).

    Each job is selected and checked on its own: two crons fire apart, so a producer in one job is as absent
    from the other's run as a nightly producer is from the push run (Review Focus 4)."""
    path = _path_of(cadences[0])
    artifacts = artifactsection.declared(data)
    selections = [select(manifest, artifacts=artifacts, cadence=cadence) for cadence in cadences]
    runner, labels = runner_of(data)
    kernel, _ = _kernel_steps(manifest, data, runner)
    scheduled = path == SCHEDULED_PATH
    jobs = tuple(
        _job(manifest, data, f"{JOB}-{at}" if scheduled else JOB, selection, runner, labels, kernel, path,
             condition=_SCHEDULE_GATE.format(cron=cadence) if scheduled else "")
        for at, (cadence, selection) in enumerate(zip(cadences, selections), 1))
    if path == PATH:
        events = [workflowschema.Trigger(event=event) for event in ("pull_request", "push_main", "dispatch")]
    else:
        crons = [NIGHTLY_CRON] if cadences == ("nightly",) else [] if cadences == ("manual",) else list(cadences)
        events = [*(workflowschema.Trigger(event="schedule", cron=cron) for cron in crons),
                  workflowschema.Trigger(event="dispatch")]
    model = workflowschema.Workflow(path=path, title=_key_of(path), job=jobs, trigger=tuple(events))
    return Derivation(model, _merged(selections))


def _merged(selections: Sequence[Selection]) -> Selection:
    """One file's selection: every job's leaves once, and what none of its jobs runs."""
    if len(selections) == 1:
        return selections[0]
    leaves = {leaf.words: leaf for selection in selections for leaf in selection.leaves}
    return Selection(tuple(leaves.values()), tuple(s for s in selections[0].skipped if s.words not in leaves))


def _job(manifest: Manifest, data: Mapping[str, object], key: str, selection: Selection, runner: runners.Runner,
         labels: tuple[str, ...], kernel: Mapping[str, object], path: str, *, condition: str = "") -> workflowschema.Job:
    """One derived job over `selection`'s leaves: the preparation, the leaves in order, the `after_all` leaves and
    the report upload, the cleanup (see `derive`)."""
    runs = _runs(selection)
    last = [leaf for leaf in selection.leaves if leaf.spec.after_all]
    if not runs:
        raise ValueError(_nothing_to_run(manifest, selection, path))
    _refuse_producers_moved_last(runs, last)
    steps = [workflowschema.Step(kernel_step=name) for name in (DOCKER_PREFLIGHT, DISK_PREFLIGHT, INSTALL)
             if name in kernel]
    steps += [workflowschema.Step(command=leaf.spec) for leaf in (*runs, *last)]
    if any(leaf.spec.task == workflowgen.REPORT_TASK for leaf in last):
        _reports(data)  # refused here, at the decision, rather than when the step is written
        steps.append(workflowschema.Step(kernel_step=REPORT_UPLOAD))
    if DISK_CLEANUP in kernel:
        steps.append(workflowschema.Step(kernel_step=DISK_CLEANUP))
    return workflowschema.Job(key=key, step=tuple(steps), condition=condition,
                              runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[runner.kind], labels=labels))


def _derived_note(selection: Selection, cadence: str = "") -> str:
    """What the file says about where its steps came from, and every leaf it left out with the reason, where a
    reader of the workflow is standing when they wonder. A cadence file says which cadence it runs and when, and
    does not list the push leaves one by one: they are every leaf without a cadence (si#860)."""
    head = textwrap.fill(
        "si#858: derived from this product's command tree, which declares no `workflows: ci:`. This job runs "
        "every unattended leaf of `ci build` and `ci test` in manifest order, a consumer after its producer. "
        "Every leaf after the first runs unless the run is cancelled or a preparation step went red, so one "
        "red gate hides none of the others; a consumer also waits for its producer's success, so a red "
        "producer shows as one red step and its consumer as skipped. A leaf that runs after all the others "
        "(the report) runs last and always.", width=95)
    skipped = selection.skipped
    if cadence:
        skipped = tuple(s for s in skipped if s.reason != _PER_PUSH)
        head += "\n\n" + textwrap.fill(_cadence_note(cadence), width=95)
    if not skipped:
        return head
    return head + "\n\nLeft out:\n" + "\n".join(
        textwrap.fill(f"`{s.words}` - {s.reason}", width=95, subsequent_indent="  ") for s in skipped)


def _cadence_note(cadence: str) -> str:
    when = {"nightly": f"every night at `{NIGHTLY_CRON}` (UTC) and when dispatched",
            "manual": "only when somebody dispatches the workflow"}
    spelled = cadence if cadence in when else f'"{cadence}"'
    return (f"si#860: this job runs only the leaves with `cadence: {spelled}`, "
            f"{when.get(cadence, 'on that schedule and on every dispatch of this workflow')}, never per push. "
            "Every leaf without a `cadence:` runs in ci.yml; an `after_all` leaf without one (the report) runs "
            "here too, so this run carries its own verdict. A run in progress is never cancelled by the next.")


def _leaf_ids(words: Sequence[str]) -> dict[str, str]:
    """A step id for each leaf's command words: `leaf_` and the words with every character GitHub does not allow
    in an id, and `-`, turned into `_` (a `-` in `steps.<id>` would be a subtraction, as `PREPARE` says). Two
    command lines that spell the same id get `_2`, `_3` in the order given, so each id is unique in the job."""
    out: dict[str, str] = {}
    taken: set[str] = set(PREPARE.values())
    for line in words:
        base = "leaf_" + re.sub(r"[^A-Za-z0-9_]", "_", line)
        candidate, n = base, 1
        while candidate in taken:
            n += 1
            candidate = f"{base}_{n}"
        taken.add(candidate)
        out[line] = candidate
    return out


def _producers(leaves: Sequence[Leaf]) -> dict[str, list[str]]:
    """For each leaf that consumes what another leaf of the job produces, the command words of those producers,
    in job order; a consumer of a fetched artifact (`registry:`) or of nothing is absent."""
    makers: dict[str, list[str]] = {}
    for leaf in leaves:
        for artifact in handoff._bound(leaf.spec.produces):
            makers.setdefault(artifact, []).append(leaf.words)
    out: dict[str, list[str]] = {}
    for leaf in leaves:
        found = [maker for artifact in handoff._bound(leaf.spec.consumes) for maker in makers.get(artifact, ())
                 if maker != leaf.words]
        if found:
            out[leaf.words] = list(dict.fromkeys(found))
    return out


def to_workflow(derivation: Derivation, manifest: Manifest, data: Mapping[str, object]) -> workflowgen.Workflow:
    """The model as the `workflowgen.Workflow` the renderer writes (si#858).

    THE CONDITIONS ARE WRITTEN HERE AND NOWHERE ELSE. A preparation step carries its id and no `if:`. The first
    leaf has none either: GitHub's default, `success()`, already waits for every step before it. Every later
    leaf runs `!cancelled()` and the success of each preparation step present, so one red leaf hides none of
    the others while a red preflight skips every leaf after it. A leaf that consumes what another leaf produces
    also waits for that producer's success (the producer carries an id for it): a consumer whose producer went
    red is skipped rather than red on the missing file, so one cause shows as one red step. An `after_all` leaf
    and the upload run `always()`, so the report still says what it found; the cleanup keeps `_disk_steps`'s
    `always()` and `continue-on-error`. `on:` is the model's triggers, written through `_TRIGGERS`.

    si#860: every job of the model is written the same way (`_to_job`); a cadence workflow also gets a
    `concurrency:` that queues the next run behind one in progress rather than cancelling it.
    """
    key = derivation.model.title
    jobs = tuple(_to_job(job, derivation.selection, manifest, data, key) for job in derivation.model.job)
    queued = {} if key == KEY else {"concurrency": {"group": key, "cancel-in-progress": False}}
    # The least-privilege workflow default the release already gets (si#719): with no block, every job gets the
    # repository's default token scopes, which can include write.
    extras = {"permissions": dict(workflowgen._WORKFLOW_DEFAULT_PERMISSIONS), **queued,
              **workflowgen._workflow_extras({})}
    return workflowgen.Workflow(key=key, path=derivation.model.path, name=key, on=_on(derivation.model.trigger),
                                jobs=jobs, extras=extras, derived=True)


def _on(triggers: Sequence[workflowschema.Trigger]) -> dict[str, object]:
    """`on:` from the model's triggers; the `schedule` triggers are one list under one key, as GitHub reads it."""
    out: dict[str, object] = {}
    for trigger in triggers:
        if trigger.event == "schedule":
            crons = out.setdefault("schedule", [])
            assert isinstance(crons, list)
            crons.append({"cron": trigger.cron})
        else:
            event, body = _TRIGGERS[trigger.event]
            out[event] = body
    return out


def _to_job(job: workflowschema.Job, selection: Selection, manifest: Manifest, data: Mapping[str, object],
            key: str) -> workflowgen.Job:
    """One model job as the renderer's job, its conditions written as `to_workflow` describes."""
    kind = next(name for name, known in workflowschema.RUNNER_KINDS.items() if known is job.runner.kind)
    runner = runners.TABLE[kind]
    kernel, unplaced = _kernel_steps(manifest, data, runner)
    words = {id(leaf.spec): leaf.words for leaf in selection.leaves}
    mine = {id(step.command) for step in job.step if step.command is not None}
    leaves = [leaf for leaf in selection.leaves if id(leaf.spec) in mine]
    ids = [_PREPARES[step.kernel_step] for step in job.step if step.kernel_step in _PREPARES]
    producers = _producers(leaves)
    leaf_ids = _leaf_ids(list(dict.fromkeys(maker for makers in producers.values() for maker in makers)))

    def gate(line: str) -> str:
        waits = [*ids, *(leaf_ids[maker] for maker in producers.get(line, ()))]
        return "${{ " + " && ".join(["!cancelled()", *(f"steps.{i}.outcome == 'success'" for i in waits)]) + " }}"

    steps: list[workflowgen.Step] = []
    first = True
    for step in job.step:
        if step.kernel_step in _PREPARES:
            prepared = kernel[step.kernel_step]
            steps.append(prepared._replace(modifiers={"id": _PREPARES[step.kernel_step], **prepared.modifiers}))
        elif step.kernel_step == REPORT_UPLOAD:
            # One run of ci-scheduled.yml runs every job on a dispatch, and upload-artifact@v4 refuses a second
            # artifact of one name in a run, so a job other than `ci` names its report after itself (si#860).
            named = workflowgen.RELEASE_ARCHIVE if job.key == JOB else f"{workflowgen.RELEASE_ARCHIVE}-{job.key}"
            steps.append(workflowgen.report_upload(_reports(data), named))
        elif step.kernel_step:
            steps.append(kernel[step.kernel_step])  # DISK_CLEANUP: only `derive` builds the model
        else:
            spec = step.command
            assert isinstance(spec, TaskCommand)
            line = words[id(spec)]
            modifiers: dict[str, object] = {"id": leaf_ids[line]} if line in leaf_ids else {}
            if spec.after_all:
                modifiers["if"] = "always()"
            elif not first:
                modifiers["if"] = gate(line)
            first = False
            steps.append(workflowgen.Step(command=line, modifiers=modifiers))
    cadence = next(leaf.spec.ci.cadence for leaf in leaves if not leaf.spec.after_all)
    labels = job.runner.labels
    note = "\n\n".join(part for part in (workflowgen._note_of({}, runner), *unplaced,
                                          _derived_note(selection, cadence)) if part)
    gated: dict[str, object] = {"if": job.condition} if job.condition else {}
    return workflowgen.Job(name=job.key, runs_on=labels[0] if len(labels) == 1 else labels, steps=tuple(steps),
                           note=note, runner=runner, prepared=True,
                           extras=workflowgen._with_runner_env(runner, gated, f"derived workflow '{key}', job '{job.key}'"))


# --- the switch (si#858 task 7) ----------------------------------------------------------------------------


def workflows(manifest: Manifest, data: Mapping[str, object]) -> tuple[workflowgen.Workflow, ...]:
    """Every workflow `support github workflows` writes or checks: the declared ones, the derived ci.yml, and
    since si#860 a derived ci-nightly.yml, ci-manual.yml and ci-scheduled.yml where a leaf carries that cadence.

    THE DERIVATION IS SWITCHED OFF BY DECLARING `workflows: ci:`, and by nothing else: a product that declares
    its CI keeps exactly what it renders today. Every other product gets the derived workflow beside whatever it
    declares, and `_reject_duplicate_paths` runs over both together, so an entry under another key that writes
    ci.yml is refused as two owners of one file (Review Focus 4) rather than overwritten by either.

    A PRODUCT WITH NO LEAF A MACHINE MAY RUN gets no ci.yml when it declares other workflows: there is something
    to generate, and a refusal would withhold it over a file nobody asked for, so the run says why in one line.
    The cadence workflows are still derived then. With nothing declared, `derive`'s refusal stands, cadence
    leaves or not: the push path would verify nothing (Review Focus 2 of si#860).
    Only that case is told apart, and before deriving, so every other refusal of the derivation still reaches
    the caller.
    """
    declared = workflowgen.parse(data)
    if any(workflow.key == KEY for workflow in declared):
        return declared
    if declared and not _runs(select(manifest, artifacts=artifactsection.declared(data))):
        log.info(f"no ci.yml is derived: `ci build` and `ci test` hold no unattended leaf a machine may run - "
                 f"place one with `unattended: true`, or declare `{workflowgen.SECTION}: {KEY}:` yourself")
        # si#860: the cadence workflows have leaves of their own and are derived all the same.
        out = (*declared, *(to_workflow(derivation, manifest, data)
                            for derivation in _cadence_derivations(manifest, data)))
        workflowgen._reject_duplicate_paths(out)
        return out
    out = (*declared, *(to_workflow(derivation, manifest, data) for derivation in derive_all(manifest, data)))
    workflowgen._reject_duplicate_paths(out)
    return out
