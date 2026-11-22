"""What the derived CI workflow of a product contains, decided from its manifest (si#858).

THIS MODULE DECIDES which leaves the workflow runs, in which order, and the model instances that
describe it (spec docs/superpowers/specs/2026-11-22-derived-workflows-design.md, sections 4 and 5).
It LEAVES TO `workflowgen` the text: how an instance is written out as a GitHub workflow file. The
split keeps the decision testable without parsing YAML and the rendering free of manifest knowledge.

This first part reads the one product value the decision needs before any leaf is chosen: the
machine the jobs run on, then chooses the leaves and puts them in order.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, NamedTuple

from simplon.manifest import context, runners
from simplon.manifest.load import Manifest
from simplon.model.command import TaskCommand
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


def select(manifest: Manifest, *, artifacts: "Mapping[str, Declared] | None" = None) -> Selection:
    """The leaves a derived CI runs, in an order every consumer can be run in (si#858, spec section 4).

    A leaf is a `TaskCommand` in a `build` or `test` group (nested groups included) of the CI area, in the
    manifest's own order; an aggregate is passed over because its members are leaves in their own right, and
    a job stops at its first red step, so an aggregate would fold several verdicts into one. A leaf that
    nobody has ruled on is refused (`workflowgen.require_unattended`, one wording for both derivations);
    `unattended: false` and `ci: { skip: }` go to `skipped`, never silently absent.

    A CONSUMER OF A LEAF THE CI DOES NOT RUN IS REFUSED, because the run would fail on a missing file far
    from the cause. `artifacts` carries the product's declarations so an artifact with a `registry:` is
    exempt, as in `handoff.plan`: it is fetched, not produced here. None means no registry is known, so every
    such consumer is refused - the safe reading, since an exemption must be claimed by the caller.
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
            workflowgen.require_unattended(spec, words, "derived CI")
            if spec.ci_skip:
                skipped.append(Skipped(words, spec.ci_skip))
            elif not spec.unattended:
                skipped.append(Skipped(words, ATTENDED))
            else:
                chosen.append(Leaf(words, spec))
    _refuse_consumers_of_absent_producers(manifest, chosen, dict(skipped), artifacts or {})
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
