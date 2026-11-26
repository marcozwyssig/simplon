"""What a CI runner provides, as a TABLE the kernel carries once for everybody (si#267).

WHY THIS EXISTS. Moving this repository's own CI to a self-hosted runner took a full day, and every hour
of it was spent rediscovering something another product in this family already knew: that
`actions/setup-python` never installs Python, that a container job cannot be the thing that provisions
docker, that `DELIVERY_DOCKER_BOOTSTRAP=1` exists. None of it was in the kernel. All of it was in a
comment in netctl's manifest, learned there once and here a second time.

    *Wenn man Simplon verwendet, dann sollte alles gleich sein. Das ist ja der Vorteil von Simplon.*

That is the principle the catalogue already runs on - **add it to the platform's catalogue once, for
everybody** - applied to the machine a job runs on instead of to the commands it runs.

WHAT A KIND IS, AND WHAT IT IS NOT. A kind says what a MACHINE provides. It does not say which machine:
`ghr-8` is a label this account's runner carries and no other account has one, so the label stays the
product's. What stops being the product's is the consequence - "this runner is Debian, therefore no
`setup-python`, therefore the launcher builds its own venv, therefore docker arrives through the
bootstrap" - which is a fact about a KIND of machine and is the same for every product that reaches one.

EVERY FIELD BELOW WAS MEASURED, and where it was measured is written next to it. A table of guesses about
other people's machines would be worse than no table: a product that trusted it would be wrong in a way
it had no way to check.

WHY IT IS RESOLVED AT GENERATION AND NOT AT RUN TIME, which is the opposite of `tasks/profiles.py`. A
profile is written INTO a product's manifest and from that moment the product owns it, because a profile
decides how the product's code is COMPILED and a kernel bump must not change that silently. A runner kind
decides what a generated file says about a machine the kernel can re-derive at will - and the generated
file is committed and reviewed, so the change is visible in a diff before it is visible in a run. The
asymmetry is deliberate: the thing that must not move quietly is written down, the thing whose movement
shows up in review is derived.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, TypeGuard

from simplon.model import workflowschema
from simplon.model.task import class_ref

#: The manifest key a job names a kind with.
KEY = "runner"

#: The environment variable `simplon.adapters.docker` reads to decide whether it may install the engine itself.
#: Named here rather than spelled into the table twice.
BOOTSTRAP = "DELIVERY_DOCKER_BOOTSTRAP"


class Runner(NamedTuple):
    """One kind of machine, and the three consequences a generated workflow has to know about it."""

    #: The name a product writes.
    kind: str
    #: The labels to emit as `runs-on:` when the product names none of its own. Empty means the machine
    #: is the product's to identify - a self-hosted runner's label belongs to whoever registered it.
    labels: tuple[str, ...]
    #: Whether `actions/setup-python` can put an interpreter on this machine.
    setup_python: bool
    #: What a job on this machine needs in its environment, and nothing more.
    env: Mapping[str, str]
    #: One line, said out loud in the generated file, so a reader of the workflow is not sent here.
    why: str
    #: Does this machine still exist tomorrow? si#327, and it is the difference between a disk that can
    #: fill and one that cannot. A GitHub-hosted runner is destroyed after every job, so nothing it leaves
    #: behind can reach the next one. A self-hosted runner IS the next job's machine, and this account's
    #: own CI died of exactly that: 64 GB of images and build cache against a 64 GB refquota, reported to
    #: the pipeline as `E: You don't have enough free space in /var/cache/apt/archives/` inside a docker
    #: build, and on a second run as a step with no log at all and a runner that had gone offline.
    disk_persists: bool = False


#: Every kind the kernel knows, and no more than were measured. The kinds and the measurements behind them are
#: the firn model's since si#857 (src/firn/model/simplon/workflow/runners.firn); this is the shape the rest of
#: the kernel reads them in, built from the generated module rather than typed a second time.
TABLE: Mapping[str, Runner] = {
    kind: Runner(kind=kind, labels=data.labels, setup_python=data.setup_python,
                 env={e.env_name: e.env_value for e in data.env}, why=data.why, disk_persists=data.disk_persists)
    for kind, data in workflowschema.RUNNER_KINDS.items()
}

#: The two commands a job on a persistent-disk machine is given, and the task each one is (si#327).
#:
#: A COORDINATE AND AN IMPL, because the two answer different questions. The coordinate is what a product
#: WRITES to place the command; the impl is what the placement RESOLVES to, and it is the only thing that
#: identifies the task afterwards - a product may place `support:ci-disk-preflight` under any command name
#: it likes, and the generated step has to call the name that product chose. So the kernel looks the impl
#: up in the product's command tree rather than assuming a spelling.
#:
#: The reference is DERIVED from the coordinate since si#400 4c (`task.class_ref`, the coordinate's
#: generated class), where it used to be a typed second source for what `catalogue.yaml` declared, so the
#: two cannot drift. `test_runners.py` holds what still can: that each coordinate exists and runs a disk body.
PREFLIGHT = ("support:ci-disk-preflight", class_ref("support:ci-disk-preflight"))
CLEANUP = ("support:ci-disk-cleanup", class_ref("support:ci-disk-cleanup"))
#: The docker probe that goes before both (si#623), placed and looked up the same way and on the same
#: machines: the one that survives a job is the one this account updates, and a runner update is what
#: broke docker access on ghr-8 on 2026-11-11.
DOCKER_PREFLIGHT = ("support:ci-docker-preflight", class_ref("support:ci-docker-preflight"))


#: The kind a job gets when it names none, which is what every product's workflows meant before this
#: table existed. Changing it would rewrite files nobody asked to have rewritten.
DEFAULT = "github-ubuntu"


def kinds() -> tuple[str, ...]:
    """Every kind, in declaration order - for a refusal that wants to say what there is."""
    return tuple(TABLE)


def resolve(declared: object, where: str) -> tuple[Runner, tuple[str, ...]]:
    """`(kind, the labels to emit)` for what a job declared, or a refusal naming the line.

    Two spellings, and the second exists because a kind and a machine are different questions:

        runner: github-ubuntu
        runner: { kind: self-hosted-debian, labels: ghr-8 }

    `labels:` overrides the kind's own, and for a kind that carries none it is REQUIRED - a self-hosted
    machine has no label the kernel could guess, and guessing `[self-hosted, Linux, X64]` would hand the
    job to any machine the account ever registers. A single label may be written as a string, because
    one label is what most products have and a list of one reads like a mistake.
    """
    if declared is None:
        declared = DEFAULT
    labels: object = None
    if isinstance(declared, Mapping):
        unknown = sorted(str(key) for key in declared if str(key) not in {"kind", "labels"})
        if unknown:
            raise ValueError(f"{where}: `{KEY}:` takes `kind:` and `labels:`, not "
                             + ", ".join(repr(key) for key in unknown))
        labels = declared.get("labels")
        declared = declared.get("kind")
    if not isinstance(declared, str) or not declared:
        raise ValueError(f"{where}: `{KEY}:` names a kind of machine - one of "
                         + ", ".join(kinds())
                         + f" - and not {declared!r}")
    runner = TABLE.get(declared)
    if runner is None:
        raise ValueError(f"{where}: '{declared}' is not a runner kind this kernel knows. It carries "
                         + ", ".join(kinds())
                         + ". A kind is a fact about a MACHINE, so a new one is added to the kernel's "
                           "table once for everybody rather than described in a product's manifest")
    emit = _labels(labels, where) or runner.labels
    if not emit:
        raise ValueError(f"{where}: '{runner.kind}' carries no label of its own, so the job has to name "
                         f"the machine: `{KEY}: {{ kind: {runner.kind}, labels: <label> }}`. "
                         f"`[self-hosted, Linux, X64]` is not an answer - it describes every self-hosted "
                         f"Linux machine this account will ever register")
    return runner, emit


def _labels(declared: object, where: str) -> tuple[str, ...]:
    """The labels a job named, as a tuple - a bare string is one label, and absent is none."""
    if declared is None:
        return ()
    if isinstance(declared, str):
        return (declared,)
    if isinstance(declared, (list, tuple)):
        wrong = [item for item in declared if not isinstance(item, str)]
        if wrong:
            raise ValueError(f"{where}: `{KEY}.labels:` is a list of runner LABELS, and "
                             + ", ".join(repr(item) for item in wrong)
                             + " is not one")
        return tuple(declared)
    raise ValueError(f"{where}: `{KEY}.labels:` is a label or a list of labels, not "
                     f"{type(declared).__name__}")


def spelt_for_buildx(value: object) -> TypeGuard[list[str]]:
    """True iff `value` is a non-empty list of platforms in buildx's `<os>/<arch>[/<variant>]` spelling.

    The spelling of a command's `ci: { emulates: }` (si#860), on a CI leaf and, since si#862, on a release
    aggregate, where a workflow's `emulates:` beside `release:` (si#570) used to say it. It sits here because
    `manifest.load` cannot import `workflowgen`, which imports this module."""
    return (isinstance(value, list) and bool(value)
            and all(isinstance(p, str) and len(p.split("/")) in (2, 3) and all(p.split("/")) for p in value))
