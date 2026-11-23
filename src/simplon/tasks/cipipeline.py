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
from collections.abc import Mapping, Sequence, Set
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
#: schedule, and every job on a dispatch. The cron is written into a single-quoted expression string unescaped:
#: that is safe because `load._ci_cadence` lets only digits, `*`, `,`, `-`, `/` and month or weekday names into
#: a field (si#860 final review), so no `'` can reach it.
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
#: si#860: the registration of every platform the job's leaves name in `ci: emulates:`, the last preparation step.
EMULATION = "emulation"

#: The step ids of the preparation steps. An `_`, never a `-`: a leaf's condition reads them in an expression,
#: where `steps.prepare-docker` would be a subtraction.
PREPARE = {"docker": "prepare_docker", "disk": "prepare_disk", "install": "prepare_install",
           "emulation": "prepare_emulation"}
_PREPARES = {DOCKER_PREFLIGHT: PREPARE["docker"], DISK_PREFLIGHT: PREPARE["disk"], INSTALL: PREPARE["install"],
             EMULATION: PREPARE["emulation"]}

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
    """Why a run with no leaf is refused, and the way out. Where the push run is empty because its leaves went to
    cadence files (si#860 final review), it says that: the leaves are not missing, the push path is what
    verifies nothing, and `workflows: ci:` now switches off ci.yml alone, so a push CI of the product's own
    keeps the cadence files."""
    elsewhere = [] if path != PATH else [_key_of(_path_of(group[0])) + ".yml" for group in _cadence_groups(manifest)]
    if elsewhere:
        return (f"derived CI: every unattended leaf of `ci build` and `ci test` carries a `cadence:`, so the "
                f"cadence leaves run in {', '.join(elsewhere)} and the push path verifies nothing - the derived "
                f"ci.yml would be a green tick over nothing on every push. Place a leaf without `cadence:` under "
                f"`ci build` or `ci test`, or declare `{workflowgen.SECTION}: {KEY}:` with a push CI of your own, "
                f"which switches off only ci.yml")
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
    """The leaves the main job runs in order: every one but the `after_all` ones and, since si#860, the ones with
    `ci: platforms:`, which run only in their cells (decision 6). None of them means no main job."""
    return [leaf for leaf in selection.leaves if not leaf.spec.after_all and not leaf.spec.ci.platforms]


def _cells(selection: Selection) -> list[Leaf]:
    """The leaves that get a matrix job of their own (si#860): `ci: python:` adds cells beside the main job's run,
    `ci: platforms:` replaces it."""
    return [leaf for leaf in selection.leaves if leaf.spec.ci.python or leaf.spec.ci.platforms]


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


def _cadence_groups(manifest: Manifest, own: Set[str] = frozenset()) -> list[tuple[str, ...]]:
    """The cadence values of each cadence workflow, one tuple per file, each only where a leaf carries its cadence
    and the product declares no workflow of that file's key (`own`, the one switch rule of `workflows`)."""
    cadences = _cadences(manifest)
    crons = tuple(c for c in cadences if c not in CADENCE_PATHS)
    groups = [*((c,) for c in ("nightly", "manual") if c in cadences), *((crons,) if crons else ())]
    return [group for group in groups if _key_of(_path_of(group[0])) not in own]


def _cadence_derivations(manifest: Manifest, data: Mapping[str, object],
                         own: Set[str] = frozenset()) -> tuple[Derivation, ...]:
    """The nightly, manual and scheduled workflows, each only where a leaf carries its cadence (si#860) and the
    product has not declared the file's key as its own."""
    return tuple(_derive(manifest, data, group) for group in _cadence_groups(manifest, own))


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
    jobs: list[workflowschema.Job] = []
    for at, (cadence, selection) in enumerate(zip(cadences, selections), 1):
        condition = _SCHEDULE_GATE.format(cron=cadence) if scheduled else ""
        cells = _cells(selection)
        # si#860: a run whose every leaf runs in platform cells (cleon's dispatched matrix) is the cell jobs
        # alone; with no cells either, `_job` refuses the empty run as before.
        if _runs(selection) or not cells:
            jobs.append(_job(manifest, data, f"{JOB}-{at}" if scheduled else JOB, selection, runner, labels, kernel,
                             path, condition=condition))
        jobs += [_cell_job(manifest, data, leaf, condition=condition) for leaf in cells]
    if path == PATH:
        events = [workflowschema.Trigger(event=event) for event in ("pull_request", "push_main", "dispatch")]
    else:
        crons = [NIGHTLY_CRON] if cadences == ("nightly",) else [] if cadences == ("manual",) else list(cadences)
        events = [*(workflowschema.Trigger(event="schedule", cron=cron) for cron in crons),
                  workflowschema.Trigger(event="dispatch")]
    model = workflowschema.Workflow(path=path, title=_key_of(path), job=tuple(jobs), trigger=tuple(events))
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
    last = [leaf for leaf in selection.leaves if leaf.spec.after_all and not leaf.spec.ci.platforms]
    if not runs:
        raise ValueError(_nothing_to_run(manifest, selection, path))
    _refuse_producers_moved_last(runs, last)
    kind = workflowschema.RUNNER_KINDS[runner.kind]
    steps = [workflowschema.Step(kernel_step=name) for name in (DOCKER_PREFLIGHT, DISK_PREFLIGHT, INSTALL)
             if name in kernel]
    steps += [workflowschema.Step(kernel_step=EMULATION)] if _emulates((*runs, *last)) and kind.can_emulate else []
    # si#860 decision 4: in a job other leaves share, the limit is the leaf's own step's.
    steps += [workflowschema.Step(command=leaf.spec, timeout_minutes=leaf.spec.ci.timeout_minutes)
              for leaf in (*runs, *last)]
    if any(leaf.spec.task == workflowgen.REPORT_TASK for leaf in last):
        _reports(data)  # refused here, at the decision, rather than when the step is written
        steps.append(workflowschema.Step(kernel_step=REPORT_UPLOAD))
    if DISK_CLEANUP in kernel:
        steps.append(workflowschema.Step(kernel_step=DISK_CLEANUP))
    return workflowschema.Job(key=key, step=tuple(steps), condition=condition,
                              runner=workflowschema.Runner(kind=kind, labels=labels))


def _emulates(leaves: Sequence[Leaf]) -> tuple[str, ...]:
    """Every platform the leaves name in `ci: emulates:`, once each, in first-written order (si#860): one
    registration serves the whole job, as binfmt is the machine's and not a step's."""
    return tuple(dict.fromkeys(platform for leaf in leaves for platform in leaf.spec.ci.emulates))


#: si#860: what a job says when a leaf of it names `ci: emulates:` and the job's machine cannot register any
#: (`can_emulate = false`, spec 5.4). Routing such a leaf to a machine that can is #722's, not this file's.
EMULATION_GAP = ("si#860: {leaves} name `ci: emulates:` ({platforms}), and this job's runner kind `{kind}` "
                 "cannot register emulation, so no step does it here and a leaf running a foreign binary "
                 "fails with `Exec format error`. Running such a leaf on a machine that can is #722.")

EMULATION_NOTE = ("si#860: the leaves' `ci: emulates:`, registered once for the job before any leaf runs; every "
                  "later leaf waits for its success. The image is the kernel's binfmt pin, as the release uses.")


#: si#860: the step a platform cell runs before anything else, and its script. In bash on every cell, Windows
#: included (Git Bash on windows-2025 prints `x86_64`), so one script and one expected value serve every cell.
ARCH_CHECK = "arch-check"
ARCH_CHECK_NAME = "Check the cell runs on the architecture it names"
ARCH_CHECK_SCRIPT = """arch="$(uname -m)"
if [ "$arch" != "$EXPECTED_ARCH" ]; then
  echo "::error::cell $CELL runs on $arch and names $EXPECTED_ARCH"
  exit 1
fi
echo "cell $CELL runs on $arch"
"""
ARCH_CHECK_NOTE = """si#860: a cell that silently runs on another architecture than it names (a runner label
GitHub re-pointed, an emulated interpreter) is green and has verified the wrong machine, so the job
checks what `uname -m` prints against the cell's expected value before anything else runs."""


def _cell_job(manifest: Manifest, data: Mapping[str, object], leaf: Leaf, *, condition: str) -> workflowschema.Job:
    """One leaf's matrix job (si#860): a cell per `ci: python:` version on `github-ubuntu` whatever the product's
    `runner:` is (decision 5), or a cell per `ci: platforms:` name on that cell's hosted machine. Every cell is a
    hosted machine, so it gets no disk preflight and no docker probe (the kind's `disk_persists` decides it, as
    for any job), and `support install` where the product declares `toolchains:`. A platform cell checks its
    architecture first. No report: a cell's result is its job's colour."""
    hosted, labels = runner_of({})
    kernel, _ = _kernel_steps(manifest, data, hosted)
    platforms, python = leaf.spec.ci.platforms, leaf.spec.ci.python
    steps = [workflowschema.Step(kernel_step=ARCH_CHECK)] if platforms else []
    steps += [workflowschema.Step(kernel_step=INSTALL)] if INSTALL in kernel else []
    # `emulates:` beside `platforms:` is refused at load, so this is a python cell on github-ubuntu, which can.
    steps += [workflowschema.Step(kernel_step=EMULATION)] if leaf.spec.ci.emulates else []
    steps.append(workflowschema.Step(command=leaf.spec))
    if platforms:
        labels = tuple(workflowschema.PLATFORMS[cell].label for cell in platforms)
    return workflowschema.Job(
        key=f"{leaf.words.replace(' ', '-')}-{'platforms' if platforms else 'python'}", step=tuple(steps),
        condition=condition, matrix=workflowschema.Matrix(platform=platforms, python=python),
        # si#860 decision 4: a leaf's own job carries its limit as the job's, the same for every cell.
        timeout_minutes=leaf.spec.ci.timeout_minutes,
        # `github-ubuntu` for a platform job too: what the kind decides holds for every hosted cell - no disk
        # that persists (so no preflight or probe) and no runner env - while the labels are the cells' own.
        runner=workflowschema.Runner(kind=workflowschema.RUNNER_KINDS[hosted.kind], labels=labels))


#: si#860, recorded rather than refused (review ruling): a platform job with a Windows cell that downloads a hand-off
#: unpacks it in that cell's job shell, `cmd`, with Windows' own tar and a `D:\...` runner temp path. Nobody has
#: run that on a Windows runner; GNU tar would read `D:` as a remote host, bsdtar should not. Said in the file.
WINDOWS_HANDOFF_UNMEASURED = (
    "si#860: on the Windows cell the hand-off is unpacked in `cmd` with Windows' tar from a `D:` path, "
    "and that has not been measured on a Windows runner; a red unpack step there is this gap, not the leaf.")


def _crosses(leaf: Leaf, artifacts: "Mapping[str, Declared]") -> bool:
    """Whether a cell job downloads a hand-off: its one leaf consumes an artifact nobody fetches from a registry,
    and a cell job produces nothing for itself, so `handoff.plan` brings it from another job."""
    return any(not (artifacts.get(a) is not None and artifacts[a].registry) for a in handoff._bound(leaf.spec.consumes))


def _orphan_note(selection: Selection, cadence: str, last: Sequence[Leaf]) -> str:
    """What a run with no main job would otherwise lose without a word (si#860): the derived note's cadence and
    left-out leaves, and each `after_all` leaf that has no main job to end and so does not run."""
    lines = ["si#858: derived from this product's command tree, which declares no `workflows: ci:`. si#860: this "
             "run has no main job, because every leaf it runs is a platform cell."]
    lines += [f"`{leaf.words}` runs after all the other leaves (`after_all`), in the main job, so it does not run "
              "here; a cell carries no report." for leaf in last]
    return "\n".join(textwrap.fill(line, width=95) for line in lines) + _left_out(selection, cadence)


def _cell_note(words: str, matrix: workflowschema.Matrix) -> str:
    if matrix.platform:
        what = ("once on each platform cell its `ci: platforms:` names, and nowhere else: its own machine, "
                "shell and launcher per cell")
    else:
        what = ("once per Python version its `ci: python:` names, on GitHub-hosted Ubuntu, and once more in the "
                "main job")
    return textwrap.fill(
        f"si#860: `{words}` runs here {what}. A cell carries no report: its result is this job's colour, one per "
        "cell, and `fail-fast` is off, so one red cell cancels none of the others.", width=95)


def _matrix(matrix: workflowschema.Matrix, product: str) -> dict[str, object]:
    """The `strategy:` of a cell job. A platform row carries what its cell differs in; `entry` is the launcher the
    product's checkout carries for that shell, `<product>.cmd` on Windows (scaffolded from launch.cmd.j2)."""
    if matrix.python:
        return {"fail-fast": False, "matrix": {"python": list(matrix.python)}}
    rows = []
    for cell in matrix.platform:
        platform = workflowschema.PLATFORMS[cell]
        rows.append({"cell": cell, "os": platform.label, "arch": platform.arch, "shell": platform.shell,
                     # si#666's `exec` on every bash row, so the launcher is the step's process and a cancel
                     # reaches the kernel; `cmd` has no exec builtin, so the Windows row is the bare launcher.
                     "entry": f"{product}.cmd" if platform.windows else f"exec {workflowgen.launcher(product)}"})
    return {"fail-fast": False, "matrix": {"include": rows}}


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
    return head + _left_out(selection, cadence)


def _left_out(selection: Selection, cadence: str) -> str:
    """The cadence a file runs and every leaf it leaves out, each paragraph led by a blank line; "" for none."""
    out = ""
    skipped = selection.skipped
    if cadence:
        skipped = tuple(s for s in skipped if s.reason != _PER_PUSH)
        out += "\n\n" + textwrap.fill(_cadence_note(cadence), width=95)
    if not skipped:
        return out
    return out + "\n\nLeft out:\n" + "\n".join(
        textwrap.fill(f"`{s.words}` - {s.reason}", width=95, subsequent_indent="  ") for s in skipped)


def _cadence_note(cadence: str) -> str:
    when = {"nightly": f"every night at `{NIGHTLY_CRON}` (UTC) and when dispatched",
            "manual": "only when somebody dispatches the workflow"}
    spelled = cadence if cadence in when else f'"{cadence}"'
    return (f"si#860: this job runs only the leaves with `cadence: {spelled}`, "
            f"{when.get(cadence, 'on that schedule and on every dispatch of this workflow')}, never per push. "
            "Every leaf without a `cadence:` runs in ci.yml; an `after_all` leaf without one (the report) runs "
            "here too, so this run carries its own verdict. "
            + ("A run in progress is never cancelled by the next; GitHub keeps one pending run per schedule "
               "(and one per dispatch), and a newer one replaces it." if cadence not in when else
               "A run in progress is never cancelled by the next; GitHub keeps one pending run, and a newer one "
               "replaces it."))


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


def to_workflow(derivation: Derivation, manifest: Manifest, data: Mapping[str, object], *,
                product: str) -> workflowgen.Workflow:
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
    `concurrency:` that queues the next run behind one in progress rather than cancelling it. `product` names
    the launchers a platform cell's matrix rows carry.
    """
    key = derivation.model.title
    mains = {job.condition for job in derivation.model.job if job.matrix is None}
    orphans: set[str] = set()
    jobs = []
    for job in derivation.model.job:
        # si#860: the first cell job of a run with no main job carries that run's note and its unrun reports.
        orphan = job.matrix is not None and job.condition not in mains and job.condition not in orphans
        if orphan:
            orphans.add(job.condition)
        jobs.append(_to_job(job, derivation.selection, manifest, data, key, product, orphan=orphan))
    # GitHub keeps one pending run per concurrency group and a newer pending run replaces it, so ci-scheduled.yml
    # keys its group on the schedule that fired: one cron's waiting run never displaces another's, and a dispatch
    # queues in a group of its own (si#860 final review).
    group = f"{key}-${{{{ github.event.schedule || 'dispatch' }}}}" if derivation.model.path == SCHEDULED_PATH else key
    queued = {} if key == KEY else {"concurrency": {"group": group, "cancel-in-progress": False}}
    # The least-privilege workflow default the release already gets (si#719): with no block, every job gets the
    # repository's default token scopes, which can include write.
    extras = {"permissions": dict(workflowgen._WORKFLOW_DEFAULT_PERMISSIONS), **queued,
              **workflowgen._workflow_extras({})}
    return workflowgen.Workflow(key=key, path=derivation.model.path, name=key, on=_on(derivation.model.trigger),
                                jobs=tuple(jobs), extras=extras, derived=True)


def _on(triggers: Sequence[workflowschema.Trigger]) -> dict[str, object]:
    """`on:` from the model's triggers; the `schedule` triggers are one list under one key, as GitHub reads it."""
    out: dict[str, object] = {}
    crons: list[dict[str, str]] = []
    for trigger in triggers:
        if trigger.event == "schedule":
            # the list is placed at the first schedule trigger, so `on:` keeps the model's order
            if not crons:
                out["schedule"] = crons
            crons.append({"cron": trigger.cron})
        else:
            event, body = _TRIGGERS[trigger.event]
            out[event] = body
    return out


def _to_job(job: workflowschema.Job, selection: Selection, manifest: Manifest, data: Mapping[str, object],
            key: str, product: str, *, orphan: bool = False) -> workflowgen.Job:
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

    by_spec = {id(leaf.spec): leaf for leaf in leaves}
    emulates = _emulates([by_spec[id(step.command)] for step in job.step if step.command is not None])
    steps: list[workflowgen.Step] = []
    first = True
    for step in job.step:
        if step.kernel_step == EMULATION:
            # si#860: the release's emulation step (si#570), with the id the later leaves' gate reads.
            from simplon.adapters.labhost import BINFMT_IMAGE
            steps.append(workflowgen.Step(note=EMULATION_NOTE, verbatim={
                "name": f"Register emulation for {', '.join(emulates)}", "id": PREPARE["emulation"],
                "uses": workflowgen.QEMU_ACTION, "with": {"image": BINFMT_IMAGE, "platforms": ",".join(emulates)}}))
        elif step.kernel_step in _PREPARES:
            prepared = kernel[step.kernel_step]
            steps.append(prepared._replace(modifiers={"id": _PREPARES[step.kernel_step], **prepared.modifiers}))
        elif step.kernel_step == REPORT_UPLOAD:
            # One run of ci-scheduled.yml runs every job on a dispatch, and upload-artifact@v4 refuses a second
            # artifact of one name in a run, so a job other than `ci` names its report after itself (si#860).
            named = workflowgen.RELEASE_ARCHIVE if job.key == JOB else f"{workflowgen.RELEASE_ARCHIVE}-{job.key}"
            steps.append(workflowgen.report_upload(_reports(data), named))
        elif step.kernel_step == ARCH_CHECK:
            steps.append(workflowgen.Step(note=ARCH_CHECK_NOTE, verbatim={
                "name": ARCH_CHECK_NAME, "shell": "bash",
                "env": {"EXPECTED_ARCH": "${{ matrix.arch }}", "CELL": "${{ matrix.cell }}"},
                "run": ARCH_CHECK_SCRIPT}))
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
            if step.timeout_minutes is not None:
                modifiers["timeout-minutes"] = step.timeout_minutes
            first = False
            steps.append(workflowgen.Step(command=line, modifiers=modifiers))
    labels = job.runner.labels
    gated: dict[str, object] = {"if": job.condition} if job.condition else {}
    where = f"derived workflow '{key}', job '{job.key}'"
    if job.matrix is not None:
        # si#860: a cell job. A platform job's machine, shell and launcher are the row's; a python job's is
        # github-ubuntu's, with the row's interpreter.
        platform = bool(job.matrix.platform)
        cell: dict[str, object] = {**gated, "strategy": _matrix(job.matrix, product)}
        if job.timeout_minutes is not None:
            cell["timeout-minutes"] = job.timeout_minutes
        if platform:
            cell["defaults"] = {"run": {"shell": "${{ matrix.shell }}"}}
        leaf = leaves[0]
        parts = [*unplaced, _cell_note(leaf.words, job.matrix)]
        windows = any(workflowschema.PLATFORMS[cell].windows for cell in job.matrix.platform)
        if windows and _crosses(leaf, artifactsection.declared(data)):
            parts.append(textwrap.fill(WINDOWS_HANDOFF_UNMEASURED, width=95))
        if orphan:
            cadence = leaf.spec.ci.cadence
            last = [other for other in selection.leaves if other.spec.after_all and not other.spec.ci.platforms
                    and other.spec.ci.cadence in ("", cadence)]
            parts.append(_orphan_note(selection, cadence, last))
        note = "\n\n".join(part for part in parts if part)
        return workflowgen.Job(name=job.key, runs_on="${{ matrix.os }}" if platform else labels[0],
                               steps=tuple(steps), note=note, runner=runner, prepared=True,
                               python="" if platform else "${{ matrix.python }}",
                               entry="${{ matrix.entry }}" if platform else "",
                               extras=workflowgen._with_runner_env(runner, cell, where))
    cadence = next(leaf.spec.ci.cadence for leaf in leaves if not leaf.spec.after_all)
    gap = ""
    if emulates and not job.runner.kind.can_emulate:
        named = ", ".join(f"`{leaf.words}`" for leaf in leaves if leaf.spec.ci.emulates)
        gap = textwrap.fill(EMULATION_GAP.format(leaves=named, platforms=", ".join(emulates), kind=kind), width=95)
    note = "\n\n".join(part for part in (workflowgen._note_of({}, runner), *unplaced, gap,
                                          _derived_note(selection, cadence)) if part)
    return workflowgen.Job(name=job.key, runs_on=labels[0] if len(labels) == 1 else labels, steps=tuple(steps),
                           note=note, runner=runner, prepared=True,
                           extras=workflowgen._with_runner_env(runner, gated, where))


# --- the switch (si#858 task 7) ----------------------------------------------------------------------------


def workflows(manifest: Manifest, data: Mapping[str, object], *, product: str) -> tuple[workflowgen.Workflow, ...]:
    """Every workflow `support github workflows` writes or checks: the declared ones, the derived ci.yml, and
    since si#860 a derived ci-nightly.yml, ci-manual.yml and ci-scheduled.yml where a leaf carries that cadence.

    ONE SWITCH RULE (si#860 final review): A DECLARED `workflows:` KEY SWITCHES OFF THE DERIVED WORKFLOW WITH THAT
    KEY, AND ONLY THAT ONE. `workflows: ci:` is the product's own push CI, so ci.yml is not derived and nothing
    else changes; `workflows: ci-nightly:` (and `ci-manual`, `ci-scheduled`) is the product's own cadence file,
    which is the way out `workflowgen._refuse_foreign_files` names for a hand-written one. A switch that took
    the cadence files with it would drop their leaves without a word. Every other product gets the derived
    workflows beside whatever it declares, and `_reject_duplicate_paths` runs over both together, so an entry
    under another key that writes a derived path is refused as two owners of one file (Review Focus 4) rather
    than overwritten by either.

    With ci.yml the product's own, a push leaf's variant key would shape nothing, and is refused
    (`_refuse_variants_nobody_derives`).

    A PRODUCT WITH NO LEAF A MACHINE MAY RUN gets no ci.yml when it declares other workflows: there is something
    to generate, and a refusal would withhold it over a file nobody asked for, so the run says why in one line.
    The cadence workflows are still derived then. With nothing declared, `derive`'s refusal stands, cadence
    leaves or not: the push path would verify nothing (Review Focus 2 of si#860).
    Only that case is told apart, and before deriving, so every other refusal of the derivation still reaches
    the caller.
    """
    declared = workflowgen.parse(data)
    own = {workflow.key for workflow in declared}
    derivations: list[Derivation] = []
    if KEY in own:
        _refuse_variants_nobody_derives(manifest, bool(_cadence_groups(manifest, own)))
    else:
        push = select(manifest, artifacts=artifactsection.declared(data))
        if declared and not _runs(push) and not _cells(push):
            log.info(f"no ci.yml is derived: `ci build` and `ci test` hold no unattended leaf a machine may run - "
                     f"place one with `unattended: true`, or declare `{workflowgen.SECTION}: {KEY}:` yourself")
        else:
            derivations.append(derive(manifest, data))
    derivations += _cadence_derivations(manifest, data, own)
    out = (*declared, *(to_workflow(derivation, manifest, data, product=product) for derivation in derivations))
    workflowgen._reject_duplicate_paths(out)
    return out


#: si#860: the `ci:` keys that shape how a leaf runs in a derived workflow, as `_ci_variant` reads them; `cadence`
#: is not one, since it says which derived workflow the leaf is in.
_VARIANT_KEYS = ("python", "platforms", "timeout_minutes", "emulates")


def _refuse_variants_nobody_derives(manifest: Manifest, cadence_files: bool) -> None:
    """Refuse a push leaf's variant key when ci.yml is the product's own (si#860 final review).

    Such a leaf runs in the product's ci.yml, which the kernel does not write, so `python:`, `platforms:`,
    `timeout_minutes:` or `emulates:` on it would shape nothing: a DIAGNOSIS, for the reason `ci:` on a command
    no derived CI selects is refused (si#858). A leaf with a `cadence:` is read by its cadence file, and an
    `after_all` leaf without one ends every derived cadence file, so its keys are read wherever one is derived.
    Only leaves a derived CI would run are asked: a skipped or attended leaf is no push leaf of any file.
    """
    for group in _ci_groups(manifest):
        for name, spec in manifest.commands[group].items():
            if not isinstance(spec, TaskCommand) or spec.ci_skip or not spec.unattended or spec.ci.cadence:
                continue
            if spec.after_all and cadence_files:
                continue
            written = [key for key in _VARIANT_KEYS if getattr(spec.ci, key) not in ((), None)]
            if written:
                raise ValueError(
                    f"'{_words(group, name)}' declares `ci: {written[0]}:` and has no `cadence:`, so it runs in "
                    f"ci.yml, and the manifest declares `{workflowgen.SECTION}: {KEY}:`: that file is the "
                    f"product's own, the kernel derives none, and the key would do nothing. Take the key off, or "
                    f"drop `{workflowgen.SECTION}: {KEY}:` so the kernel derives ci.yml and reads it")
