"""What the kernel reads of a manifest, as the kernel's own types (si#391).

The step model and `run_command` are the kernel (layer 0), and the manifest reader is the domain above it.
The kernel used to import `Manifest` and `PlanNode` from it, so the lowest layer named a type of the one
above. The kernel now says what it reads. `CommandDecl` lists the six fields of a command's declaration it
uses, `Plan` lists the four questions it asks a manifest, and `PlanNode`, the tree a plan is built as, lives
here. `orchestrator.manifest` imports `PlanNode` from here (downward), so `manifest.PlanNode` is still the
same class, and `Manifest` and `CommandSpec` satisfy the two protocols without naming them.

si#400 replaces the hand-written `Manifest` and `CommandSpec` with generated classes. These protocols are
what the generated classes have to satisfy.
"""
from __future__ import annotations

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
