"""Handing an artifact from one job to the next (si#344 C.4, spec C.6).

A generated workflow runs commands in jobs, and GitHub gives every job a fresh machine. An artifact one job
produces is therefore not on the disk of the next job, however the manifest orders the two commands. The
`produces:`/`consumes:` edges already say which artifact goes from which command to which; this module reads
them per job and says what has to cross: the consumer's job needs the producer's job, the producer's job uploads
after its last producing step, the consumer's job downloads before its first consuming step.

Producer and consumer in one job hand nothing over: the files are already there.

WHAT IS REFUSED, and every one is a diagnosis: the workflow it would have written does not work, or works by
accident.
- A consumer whose producer runs in no job of this workflow, for an artifact with no `registry:`: nothing would
  put it there. A release's evidence is the sharp case, because the push does not read it and would be green
  with no test run (decided 2026-10-14, si#344).
- A step consuming before the step of its own job that produces it: rule 5, one job wide. The order is the
  manifest's and is not changed here.
- An artifact produced in more than one job, or in a matrix job, and consumed in a job that does not produce
  it: GitHub refuses a second upload under one name in one run, and which one to take would be a guess.
- An artifact with no `path:` that crosses: there is no file to hand over. An image lives in one job's docker
  daemon, and the next job's daemon has it only when the runner happens to be shared.
- An artifact whose name cannot be written safely, or whose `path:` tar would store somewhere else.
- A producer job that runs only under an `if:` its consumer does not share: a skipped job is not red.
- Jobs that need each other: GitHub refuses the file, far from the cause.

This module knows nothing about YAML or GitHub's steps; `workflowgen` writes them.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from simplon.domain.artifactsection import Declared
    from simplon.domain.command import TaskCommand


class Run(NamedTuple):
    """One job as the hand-off sees it. `steps[i]` holds the (command path, spec) of every leaf step `i` runs -
    one for a leaf, the plan for an aggregate, none for a verbatim step. `matrix` is true for a job with a
    `strategy:`, which runs once per entry. `needs` is what the product declared; `condition` is the
    job-level `if:` as text, empty for none."""

    job: str
    steps: "tuple[tuple[tuple[str, TaskCommand], ...], ...]"
    matrix: bool = False
    needs: tuple[str, ...] = ()
    condition: str = ""


class Handoff(NamedTuple):
    """What one job gains: the jobs it must wait for (only those the hand-off adds), the artifacts it uploads
    AFTER step i, and those it downloads BEFORE step i."""

    needs: tuple[str, ...] = ()
    uploads: Mapping[int, tuple[str, ...]] = {}
    downloads: Mapping[int, tuple[str, ...]] = {}


def _bound(sides: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(artifact for names in sides.values() for artifact in names)


#: What an artifact name that crosses may be made of. The name lands in a shell line and in upload-artifact's
#: `name:`, which rejects `" : < > | * ? \\ /`.
_SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")


def _relocated(path: str) -> bool:
    """True when tar would store `path` somewhere other than where it is read: GNU tar strips a leading `/` and
    `../` (exit 0, "Removing leading"), so the consumer would find nothing at the path."""
    posix = PurePosixPath(path)
    return posix.is_absolute() or ".." in posix.parts or re.match(r"[A-Za-z]:", path) is not None


def plan(workflow: str, runs: Sequence[Run], artifacts: Mapping[str, "Declared"]) -> dict[str, Handoff]:
    """Every job's hand-off, or a ValueError naming the workflow, the job and the artifact."""
    first: dict[str, dict[str, tuple[int, str]]] = {}
    last: dict[str, dict[str, int]] = {}
    for run in runs:
        for at, leaves in enumerate(run.steps):
            for path, spec in leaves:
                for artifact in _bound(spec.produces):
                    first.setdefault(artifact, {}).setdefault(run.job, (at, path))
                    last.setdefault(artifact, {})[run.job] = at
    matrix = {run.job: run.matrix for run in runs}
    condition = {run.job: run.condition for run in runs}
    added: dict[str, set[str]] = {run.job: set() for run in runs}
    needs: dict[str, list[str]] = {run.job: [] for run in runs}
    uploads: dict[str, dict[int, list[str]]] = {run.job: {} for run in runs}
    downloads: dict[str, dict[int, list[str]]] = {run.job: {} for run in runs}
    for run in runs:
        fetched: set[str] = set()
        for at, leaves in enumerate(run.steps):
            for path, spec in leaves:
                for artifact in _bound(spec.consumes):
                    where = f"workflow '{workflow}', job '{run.job}'"
                    makers = last.get(artifact, {})
                    if run.job in makers:
                        made_at, maker = first[artifact][run.job]
                        if made_at > at:
                            raise ValueError(
                                f"{where} runs '{path}' (step {at + 1}) before '{maker}' (step {made_at + 1}), and "
                                f"'{path}' consumes '{artifact}', which '{maker}' produces - put '{maker}' first")
                        continue
                    declared = artifacts.get(artifact)
                    if not makers:
                        if declared is not None and declared.registry:
                            continue
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}', and no job in this workflow produces it - "
                            f"run its producer in a job here, or give '{artifact}' a `registry:` it is fetched from")
                    if len(makers) > 1:
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}', which is produced in more than one job: "
                            f"{', '.join(repr(job) for job in makers)} - one run uploads an artifact once, so "
                            f"produce it in one job, or run '{path}' in a job that produces it itself")
                    (source, after), = makers.items()
                    if matrix[source]:
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}', which job '{source}' produces, and '{source}' "
                            f"runs once per matrix entry - one run uploads an artifact once, so produce it in a "
                            f"job without `strategy:`, or run '{path}' in '{source}'")
                    if declared is None or not declared.path:
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}' from job '{source}', and '{artifact}' declares "
                            f"no `path:`, so there is no file to hand over - run its producer and '{path}' in one job")
                    if not _SAFE_NAME.fullmatch(artifact):
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}' from job '{source}', and an artifact can be "
                            f"handed over only under a name of letters, digits, `.`, `_` and `-` - rename "
                            f"'{artifact}', or run its producer and '{path}' in one job")
                    if _relocated(declared.path):
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}' from job '{source}', and its `path:` "
                            f"'{declared.path}' is absolute or leaves the checkout, so tar would store it somewhere "
                            f"else and '{path}' would find nothing there - give '{artifact}' a path inside the "
                            f"checkout")
                    if condition[source] and condition[source] != condition[run.job]:
                        # A skipped producer skips its consumer through `needs:`, and a skipped job is not red.
                        # Before C.4 the consumer failed on the missing file; now the run would be green with
                        # nothing done.
                        raise ValueError(
                            f"{where}: '{path}' consumes '{artifact}' from job '{source}', which runs only "
                            f"`if: {condition[source]}`, and job '{run.job}' does not - when '{source}' is skipped "
                            f"GitHub skips '{run.job}' with it, and a skipped job is not a red one; give both jobs "
                            f"the same `if:`, or run '{path}' in '{source}'")
                    if artifact not in fetched:
                        fetched.add(artifact)
                        downloads[run.job].setdefault(at, []).append(artifact)
                    if artifact not in uploads[source].get(after, []):
                        uploads[source].setdefault(after, []).append(artifact)
                    if source not in needs[run.job] and source not in run.needs:
                        needs[run.job].append(source)
                        added[run.job].add(source)
    _acyclic(workflow, {run.job: (*run.needs, *needs[run.job]) for run in runs}, added)
    return {run.job: Handoff(tuple(needs[run.job]),
                             {at: tuple(names) for at, names in uploads[run.job].items()},
                             {at: tuple(names) for at, names in downloads[run.job].items()})
            for run in runs}


def _acyclic(workflow: str, needs: Mapping[str, tuple[str, ...]], added: Mapping[str, set[str]]) -> None:
    """Refuse jobs that wait for each other, through the hand-off or the product's own `needs:`. `added` is the
    edges the hand-off contributed (job -> jobs it was made to wait for); a loop with none of them is the
    product's own, and is not blamed on artifacts."""
    done: set[str] = set()

    def visit(job: str, trail: tuple[str, ...]) -> None:
        if job in done:
            return
        if job in trail:
            loop = (*trail[trail.index(job):], job)
            head = f"workflow '{workflow}': jobs need each other: {' -> '.join(loop)}"
            if not any(b in added.get(a, ()) for a, b in zip(loop, loop[1:])):
                raise ValueError(f"{head} - the jobs' own `needs:` form the loop; remove one of them")
            raise ValueError(
                f"{head} - an artifact one of them consumes is produced by a job that waits for it; move a "
                f"producer or a consumer so the jobs form a chain")
        for other in needs.get(job, ()):
            visit(other, (*trail, job))
        done.add(job)

    for job in needs:
        visit(job, ())
