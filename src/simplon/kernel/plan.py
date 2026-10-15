"""What the kernel reads of a manifest, as the kernel's own types (si#391).

The step model and `run_command` are the kernel (layer 0), and the manifest reader is the domain above it.
The kernel used to import `Manifest` and `PlanNode` from it, so the lowest layer named a type of the one
above. The kernel now says what it reads. `CommandDecl` lists the six fields of a command's declaration it
uses, `Plan` lists the four questions it asks a manifest, and `PlanNode`, the tree a plan is built as, lives
here. `orchestrator.manifest` imports `PlanNode` from here (downward), so `manifest.PlanNode` is still the
same class, and `Manifest` and `CommandSpec` satisfy the two protocols without naming them.

What a plan may run at the same time (`schedule_of`, `Fan`, `parallel_siblings`) lives here too and not in
`steps`, because it is read off the tree alone: the runner schedules by it, and the load rule that refuses
a fan racing a consumer past its producer (si#419) asks the same function before anything runs.

si#400 replaces the hand-written `Manifest` and `CommandSpec` with generated classes. These protocols are
what the generated classes have to satisfy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol


class CommandDecl(Protocol):
    """The fields of one command's declaration that the kernel reads: whether it runs (`impl`), what it
    says it does (`help`), what it waits for (`depends_on`), and how its plan runs."""

    @property
    def impl(self) -> str: ...
    @property
    def help(self) -> str: ...
    @property
    def depends_on(self) -> tuple[str, ...]: ...
    @property
    def stop_on_failure(self) -> bool: ...
    @property
    def parallel(self) -> bool: ...
    @property
    def keep_awake(self) -> bool: ...


class PlanNode(NamedTuple):
    """One node of a command's execution plan, kept as a TREE (#1275) instead of the flat leaf tuple
    `plan_for` returns. `name` is the bare command name, `path` its dotted `group.command` CLI identity
    (what the TUI renders as the row), `spec` its declaration, and `children` the nodes it expands into:
    empty for a leaf, one entry per CONTRIBUTING dependency for an aggregate.

    The tree is a DFS SPANNING TREE of the dependency DAG, not the DAG: `plan_tree_for` dedups by name
    exactly as `plan_for` does, so a diamond appears ONCE, at its first occurrence. That is what keeps the
    names `leaves()` returns identical to `plan_for`'s, and that equality is the whole point - display and
    execution cannot disagree when they come from one traversal.
    """
    name: str
    path: str
    spec: CommandDecl
    children: tuple["PlanNode", ...] = ()

    @property
    def is_leaf(self) -> bool:
        """True for an impl-bearing command (a step that really runs), False for an aggregate (a display
        node whose state a renderer derives from its children)."""
        return bool(self.spec.impl)

    def leaves(self) -> tuple["PlanNode", ...]:
        """This node's executable leaves in POST-ORDER (every child's leaves before this node's own, so a
        dependency always precedes its dependant) - the execution plan itself. The order is STRUCTURAL: it
        walks `children`, which is populated for every node regardless of `is_leaf`, rather than resting on
        the v1 impl-XOR-depends_on lock that happens to keep a leaf childless today. `run_command` maps
        these to Steps; the parity test pins their names against `plan_for`."""
        return (tuple(leaf for child in self.children for leaf in child.leaves())
                + ((self,) if self.is_leaf else ()))


class Plan(Protocol):
    """The four questions the kernel asks a manifest: a command's declaration and its dotted CLI path by
    name, the declaration a run starts from, and the plan tree it runs."""

    def spec_by_name(self, name: str) -> CommandDecl | None: ...
    def path_by_name(self, name: str) -> str | None: ...
    def root_spec_for(self, name: str, *, group: str | None = None) -> CommandDecl: ...
    def plan_tree_for(self, name: str, *, group: str | None = None) -> PlanNode: ...


@dataclass(frozen=True)
class Fan:
    """Branches that may run at the SAME time, each branch itself an ordered `Schedule`.

    A branch and not a step, because a `parallel:` aggregate's dependency may itself be a chain: netctl's
    `web-jar` is `[builder-image, web-jar-only]`, and a fan that flattened its members to leaves would
    run gradle in an image that does not exist yet. What runs side by side is the SUBTREES."""
    branches: tuple["Schedule", ...]


#: One thing after another: a step INDEX into `Pipeline.steps`, or a `Fan` whose branches are not
#: ordered against each other. Everything after a `Fan` in the same tuple is its JOIN - it starts when
#: every branch has finished - which is why no separate barrier exists: `depends_on` already means
#: "after", and a fan is the one place it stops meaning it.
Schedule = tuple["int | Fan", ...]


def schedule_indices(schedule: Schedule) -> tuple[int, ...]:
    """Every step index in `schedule`, nested fans included, in PLAN order.

    SORTED rather than in traversal order, and that is the property the headless log rests on: a reader
    of a CI log follows the plan, not the scheduler, so the blocks come out in the order the tree
    declares them whichever branch happened to finish first."""
    flat: list[int] = []
    for item in schedule:
        if isinstance(item, Fan):
            flat += [index for branch in item.branches for index in schedule_indices(branch)]
        else:
            flat.append(item)
    return tuple(sorted(flat))


def parallel_siblings(schedule: Schedule) -> dict[int, frozenset[int]]:
    """Step index -> the steps that are running BESIDE it by declaration: every index in the other
    branches of every fan it sits in. Empty for a step no fan contains.

    WHAT IT IS FOR, and it is the sharpest decision in si#147. When a step fails, `abort_after` skips the
    work in its scope that has not begun - and inside a fan "has not begun" is a RACE. Three branches
    start within microseconds of each other; if the first one fails instantly, whether the other two were
    far enough along to count as started depends on the OS scheduler, the bound, and the machine's load.
    A run whose set of executed steps varies between two runs of the same plan is unreproducible, and
    unreproducible is worse than either answer to the question.

    So a fan's members are never skipped FOR EACH OTHER, and the reason is the declaration itself rather
    than a tie-break: `parallel:` says these subtrees do not have to wait for each other, which is a
    statement that none of them needs what another produces. A failure in one therefore does not make
    another's work doomed - their results are still worth having, which is the whole reason they were
    declared parallel. What IS doomed is whatever comes after the join, and that is skipped exactly as it
    always was.

    Within ONE branch nothing changes: a branch is an ordered chain, so the step after a failed one is
    doomed in the ordinary way and is skipped by the ordinary rule.

    The cost is stated: a fan of forty in which the first fails still runs the other thirty-nine. The
    lever for that is the bound, and the manifest cannot express "stop the fan too" - v1 declines to add a
    second flag for a shape no reachable manifest has."""
    out: dict[int, frozenset[int]] = {}

    def walk(sched: Schedule, inherited: frozenset[int]) -> None:
        for item in sched:
            if isinstance(item, Fan):
                own = [frozenset(schedule_indices(branch)) for branch in item.branches]
                whole = frozenset[int]().union(*own) if own else frozenset[int]()
                for branch, mine in zip(item.branches, own):
                    walk(branch, inherited | (whole - mine))
            else:
                out[item] = inherited

    walk(schedule, frozenset())
    return out

def schedule_of(tree: PlanNode) -> Schedule:
    """What `tree` may do at the same time: its leaves numbered by their position in `tree.leaves()`, with
    a `Fan` wherever a node says `parallel: true`. `steps.schedule_for` runs a pipeline by it, and the
    load rule that refuses a consumer racing its producer (si#419, `ports._check_plan`) reads the same
    answer, so what is refused is exactly what the runner would race. `schedule_for` argues why the fan
    is declared rather than derived."""
    index_of = {id(leaf): index for index, leaf in enumerate(tree.leaves())}

    def walk(node: "PlanNode") -> Schedule:
        # `leaves()` is post-order - a node's own step comes after its children's - and this mirrors it,
        # because the schedule and the step list have to agree about what "after" means.
        # `index_of[...]` unguarded, deliberately: it is built from this very tree, so a missing leaf is a
        # broken invariant and a KeyError says so. A `.get` here would DROP that step from the schedule -
        # it would never run and nothing would say why, which is the "cannot tell nothing-to-do from
        # failed" defect at the one place it would be invisible.
        own: Schedule = ((index_of[id(node)],) if node.is_leaf else ())
        if not node.children:
            return own
        if node.spec.parallel:
            return (Fan(tuple(walk(child) for child in node.children)),) + own
        return tuple(item for child in node.children for item in walk(child)) + own

    return walk(tree)
