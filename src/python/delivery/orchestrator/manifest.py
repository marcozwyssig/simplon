"""Manifest-driven CLI assembly for the CI/CD orchestrator: a per-product YAML manifest is the ONE
declarative source for the command taxonomy (groups + env-gating), each command's implementation
reference ("module:function") and its help summary. A product ships the manifest + the command impls;
this engine reads the manifest and the product assembles its CLI from it - product-specifics become
DATA, not code, which dissolves the platform -> product coupling.

The manifest is ONE hierarchy (#729): `groups` maps each group to a group -> command -> spec TREE, so a
command's membership and its spec live together. The former separate flat `commands` map (and the dotted
group-scoped keys `test.all` / `deploy.all` it needed because `all` collides across groups in a flat
namespace) is gone - the collision is resolved by NESTING instead.

The engine is PURE and framework-free: it parses + validates the manifest (loudly, like
delivery.environments.parse), resolves an impl reference to the real callable, and builds the shared
CommandTaxonomy (the env-gate) from the manifest so that logic is reused, not copied. It deliberately
imports no CLI framework: registering Typer commands / sub-apps / help panels is the PRODUCT's job (the
engine must not bind to one CLI framework). "One source, two outputs": the same manifest assembles the
runtime CLI now and, in Phase 2, the CI workflows.

Parsing + validation run through the private Pydantic v2 models below (`_ManifestModel` and its spec
models). The PUBLIC surface stays the NamedTuples `CommandSpec` / `Manifest`: `load()`
converts the validated model into those tuples before returning, so consumers see byte-for-byte the same
types (field access, tuple unpacking, `taxonomy()`, `spec_for()`, `spec_by_name()`). The fail-loud
contract is unchanged - every rule violation is raised as a ValueError, and `load()` re-raises any Pydantic
ValidationError as a plain ValueError so a raw ValidationError never escapes.
"""
from __future__ import annotations

import importlib
from typing import Callable, NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from delivery.clitaxonomy import CommandTaxonomy, TaxonomyNode, merge_trees


class CommandSpec(NamedTuple):
    """One command's declaration: its implementation reference and a one-line help summary.

    `impl` is a "module:function" reference (e.g. "netctl.cli:seed") the engine resolves to the callable
    that runs the command. `help` is the canonical short summary (used in listings + consumed by the
    Phase-2 CI-doc generation). `passthrough_args` marks a command that forwards any unrecognised trailing
    args to an underlying tool (e.g. a test runner) - a generic intent the product maps to its CLI
    framework's settings. The owning GROUP is deliberately NOT stored here: it is the key of the group that
    nests this spec in the manifest's `commands` tree (the single membership source), so a command can never
    disagree with it.

    `depends_on` (#895) names the commands this one depends on: the runner resolves them transitively,
    DEDUPLICATES by name and runs each unique command exactly once per top-level invocation, in dependency
    order (`Manifest.plan_for`). Idempotency is each command's own guarantee - there is no freshness/Make
    tracking, only dedup-once. `impl` and `depends_on` are mutually exclusive (v1 lock): a command is
    either a leaf-with-impl or an impl-less AGGREGATE. Rationale: plan steps execute as `./<product>.sh
    <leaf>` SUBPROCESSES, so an impl-bearing command that also carried deps would re-expand them in the
    child and break dedup-once. Forward path if a hybrid is ever needed: a child-side skip-deps env guard
    (e.g. NETCTL_SKIP_DEPS=1) - deliberately NOT built now. `stop_on_failure` (an AGGREGATE's flag, rejected
    on a leaf) makes a failure skip the rest of THIS command's subtree instead of running doomed work
    (default False = run every step below it and take the worst rc). It is scoped to the subtree, not to the
    run (netctl#1317): a failing `up` aborts its own phases while the `test all` that planned it carries on
    to the next gate, which is what a flag declared PER AGGREGATE has to mean. The scope of a failure is the
    OUTERMOST ancestor whose flag is true, so an explicit `false` reads the same as an unset one and cannot
    shield its subtree from a `true` above it. `delivery.orchestrator.steps.abort_after` owns the walk.
    Because a plan tree is a SPANNING tree, a dependency two aggregates both declare is planned under one
    of them only, and the other's flag would never fire for it; `load()` rule 6 (netctl#1319) rejects that
    ambiguity where the two aggregates sit in ONE plan and their flags disagree.

    `keep_awake` (an aggregate's flag, netctl#1238) declares that the host must not idle-sleep while this
    command's PLAN runs: `run_command` wraps the whole dispatch in `delivery.awake.keep_awake`. It exists
    because a plan has no product code around it - the callback the CLI binds for an aggregate is
    kernel-synthesized - so an aggregate that replaced a hand-written multi-minute pipeline would silently
    lose the inhibitor that pipeline's command had. Declaring it beats each leaf arming its own: the
    inhibitor then spans the GAPS between steps too, and one line in the manifest replaces the same `with`
    block repeated in every long leaf.

    `hidden` (netctl#1277) declares that the command must not appear in any `--help` listing while staying
    fully INVOCABLE - a plan step named in a `depends_on` (loader rule 4) must be a real manifest command,
    but a bring-up PHASE or a raw `-only` leaf ("prefer the aggregate") clutters the listing meant for a
    human. `delivery.cli.assemble` is the sole consumer: it threads the flag onto the command's GROUP
    registration, on top of the flat back-compat alias, which has always been hidden regardless of this
    flag. On a group-default group's NAMESAKE member the flag is meaningless - that member is never a
    listed subcommand or a separate flat command to begin with, it is the sub-app's default callback - so
    `load()` rejects it there, the same reasoning `keep_awake` on a leaf already uses (netctl#1238): a flag
    that does nothing where it is written is worse than no flag.
    """
    impl: str
    help: str
    passthrough_args: bool = False
    depends_on: tuple[str, ...] = ()
    stop_on_failure: bool = False
    keep_awake: bool = False
    hidden: bool = False
    with_: dict[str, object] = {}


class Manifest(NamedTuple):
    """A parsed, validated product manifest, held as ONE hierarchy (#729): the command taxonomy (group ->
    its command names, and the subset of env-first groups) plus each command's spec, nested under its group.
    `groups` is the membership projection (each group's ordered command names) the shared CommandTaxonomy
    consumes, so `taxonomy()` builds the env-gate without duplicating its logic. `commands` is the nested
    spec tree (group -> command -> spec), so `spec_for(group, name)` resolves a member's spec by NESTING -
    the same name may live in several groups (#519: `test all` next to `deploy all`), each owner carrying its
    own spec, with no flat dotted keys.
    """
    groups: dict[str, tuple[str, ...]]
    env_groups: frozenset[str]
    commands: dict[str, dict[str, CommandSpec]]
    tree: dict[str, TaxonomyNode]

    def taxonomy(self) -> CommandTaxonomy:
        """The shared env-gate engine built from this manifest's tree (one env-gate, not a copy)."""
        return CommandTaxonomy.from_tree(self.tree)

    def spec_for(self, group: str, name: str) -> CommandSpec:
        """The spec for a group member, resolved by nesting (`commands[group][name]`). load() guarantees
        membership IS the spec tree (every member of every group carries a spec), so this lookup cannot miss
        on a validated manifest."""
        return self.commands[group][name]

    def spec_by_name(self, name: str) -> CommandSpec | None:
        """The spec for a command by its BARE name when exactly ONE group owns it, else None - an absent
        name OR an ambiguous one owned by several groups (#519: `all`). This flat view resolves the bare
        dependency names in a `depends_on` plan (delivery.orchestrator.product maps each planned leaf
        through the product step factory); a caller that must disambiguate an owned-by-many name uses
        spec_for(group, name)."""
        owners = [group for group, specs in self.commands.items() if name in specs]
        return self.commands[owners[0]][name] if len(owners) == 1 else None

    def path_by_name(self, name: str) -> str | None:
        """The dotted `group.command` CLI path for a BARE command name when exactly ONE group owns it,
        else None - an absent name OR an ambiguous one owned by several groups (#519: `all`). This is
        the exact-command identity the orchestrator renders as a step's section header (netctl#897),
        replacing the earlier name+help label vocabulary there."""
        owners = [group for group, specs in self.commands.items() if name in specs]
        return f"{owners[0]}.{name}" if len(owners) == 1 else None

    def root_spec_for(self, name: str, *, group: str | None = None) -> CommandSpec:
        """The spec for a plan ROOT: `name` scoped to `group` when given (the #519 `test all` vs
        `deploy all` disambiguation), else resolved by bare name via `spec_by_name`. Raises the same
        ValueError `plan_for`, `plan_tree_for` and `run_command` each used to raise inline, from the one
        place that now owns the expression all three used to repeat."""
        spec = self.commands.get(group, {}).get(name) if group is not None else self.spec_by_name(name)
        if spec is None:
            raise ValueError(f"no unambiguous command named '{name}' in the manifest")
        return spec

    def plan_for(self, name: str, *, group: str | None = None) -> tuple[str, ...]:
        """The execution plan for command `name` (#895): a post-order DFS over `depends_on`, so every
        transitive dependency is planned BEFORE its dependant; a `done` set dedups by name, so a command
        reached along several paths (a diamond) appears exactly ONCE per top-level invocation; and a node
        is emitted only if it carries its own `impl` - an impl-less AGGREGATE contributes its leaves,
        never itself. A grey-set (DFS trail) cycle guard fails loudly, defensively: load() already
        rejects cyclic manifests, so a validated manifest never trips it here.

        `name` is a bare command name; `group` disambiguates a ROOT owned by several groups (#519:
        `test all` vs `deploy all`). Dependency ENTRIES are always bare names - load() validates each as
        known and unambiguous, so they resolve via spec_by_name without a group.

        Kept as an INDEPENDENT traversal rather than reimplemented in terms of `plan_tree_for` (e.g. via
        `PlanNode.leaves()`): it is the ORACLE the parity test checks `plan_tree_for` against, and
        reimplementing it in terms of the tree would turn that test into a tautology."""
        plan: list[str] = []
        done: set[str] = set()
        trail: list[str] = []   # the DFS path = the grey set, kept ordered for the cycle message

        def visit(cmd: str, spec: CommandSpec) -> None:
            if cmd in done:
                return
            if cmd in trail:
                raise ValueError("dependency cycle: " + " -> ".join(trail[trail.index(cmd):] + [cmd]))
            trail.append(cmd)
            for dep in spec.depends_on:
                dep_spec = self.spec_by_name(dep)
                if dep_spec is None:
                    raise ValueError(
                        f"command '{cmd}': dependency '{dep}' is not an unambiguous command in the manifest")
                visit(dep, dep_spec)
            trail.pop()
            done.add(cmd)
            if spec.impl:
                plan.append(cmd)

        visit(name, self.root_spec_for(name, group=group))
        return tuple(plan)

    def _path_for(self, name: str, group: str | None = None) -> str:
        """The dotted `group.command` identity of a plan node: the explicit `group` when the caller
        disambiguated the root (the #519 `test all` vs `deploy all` shape, where `path_by_name` cannot
        decide), else the unambiguous owner, else the bare name as a last resort."""
        if group is not None:
            return f"{group}.{name}"
        return self.path_by_name(name) or name

    def plan_tree_for(self, name: str, *, group: str | None = None) -> "PlanNode":
        """The execution plan for command `name` as a TREE (#1275): the structured view of `plan_for`.

        Same DFS, same dedup, same order. A `done` set means a command reached along several paths appears
        exactly ONCE, at its first occurrence, so the result is a spanning tree of the DAG rather than the
        DAG itself. An aggregate that contributes nothing (its whole subtree was already planned) is
        OMITTED rather than rendered as an empty node; the ROOT is always returned even then, because it is
        the pipeline's identity. A grey-set cycle guard fails loudly, defensively: `load()` already rejects
        cyclic manifests, so a validated manifest never trips it - exactly the stance `plan_for` takes.

        `leaves()` on the result yields `PlanNode`s whose names, in DFS order, are identical to
        `plan_for(name, group=group)`. The parity test pins that, and it is why `run_command` can build its
        steps from the tree without a second traversal.
        """
        done: set[str] = set()
        trail: list[str] = []   # the DFS path = the grey set, kept ordered for the cycle message

        def visit(cmd: str, spec: CommandSpec, path: str) -> "PlanNode | None":
            if cmd in done:
                return None
            if cmd in trail:
                raise ValueError("dependency cycle: " + " -> ".join(trail[trail.index(cmd):] + [cmd]))
            trail.append(cmd)
            children: list[PlanNode] = []
            for dep in spec.depends_on:
                dep_spec = self.spec_by_name(dep)
                if dep_spec is None:
                    raise ValueError(
                        f"command '{cmd}': dependency '{dep}' is not an unambiguous command in the manifest")
                child = visit(dep, dep_spec, self._path_for(dep))
                if child is not None:
                    children.append(child)
            trail.pop()
            done.add(cmd)
            if spec.impl:
                return PlanNode(name=cmd, path=path, spec=spec, children=tuple(children))
            return PlanNode(name=cmd, path=path, spec=spec, children=tuple(children)) if children else None

        root_spec = self.root_spec_for(name, group=group)
        root_path = self._path_for(name, group)
        root = visit(name, root_spec, root_path)
        # An aggregate always bottoms out at leaves in a validated manifest, so `visit` returning None for
        # the ROOT cannot happen; return the bare node rather than None so the caller's type never widens.
        return root if root is not None else PlanNode(name=name, path=root_path, spec=root_spec)


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
    spec: CommandSpec
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


def _split_impl(impl: str, context: str) -> tuple[str, str]:
    """Split a "module:function" reference into its two parts, failing loudly on a malformed one.

    `context` names what is being validated (a command name, or the impl itself) so the error points at
    the offending declaration.
    """
    module, sep, function = impl.partition(":")
    if sep != ":" or not module or not function or ":" in function:
        raise ValueError(f"{context}: impl must be 'module:function', got '{impl}'")
    return module, function


# --- internal Pydantic parse/validate layer ---------------------------------------------------------
# The manifest is PARSED and VALIDATED through these private Pydantic v2 models; `load()` then converts the
# validated model into the public NamedTuples above. Modelling it here (rather than an imperative wall of
# ValueError checks) keeps the schema declarative and the unknown-key tolerance explicit, while the public
# types stay unchanged. The scalar coercions reproduce the former loader exactly (`str(...).strip()`,
# `bool(...)`, `... or ()`). Rules whose error names a specific command are enforced in the
# manifest-level `@model_validator` so the message can carry that name (the tests assert on those strings).


class _CommandSpecModel(BaseModel):
    """Parse/validate view of one command declaration. Coerces the scalars exactly like the former loader
    and IGNORES unknown keys inside a spec. The non-empty-impl/help and 'module:function' rules live on the
    manifest model so their errors can name the owning group + command."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    impl: str = ""
    help: str = ""
    with_: dict[str, object] = Field(default_factory=dict, alias="with")
    passthrough_args: bool = False
    depends_on: tuple[str, ...] = ()
    stop_on_failure: bool = False
    keep_awake: bool = False
    hidden: bool = False

    @field_validator("impl", "help", mode="before")
    @classmethod
    def _stripped_str(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("depends_on", mode="before")
    @classmethod
    def _str_tuple(cls, value: object) -> tuple[str, ...]:
        return tuple(str(dep) for dep in (value or ()))

    @field_validator("passthrough_args", "stop_on_failure", "keep_awake", "hidden", mode="before")
    @classmethod
    def _as_bool(cls, value: object) -> bool:
        return bool(value)


class _ManifestModel(BaseModel):
    """Parse/validate view of the whole manifest. Unknown TOP-LEVEL sections (product, environments,
    default, images, ... - a product's own build data) are IGNORED, exactly as the former loader read only
    the taxonomy sections. The ONE exception is the REMOVED `composites` section (netctl#898): a leftover
    `composites:` key is rejected LOUDLY (never silently dropped by the extra-ignore tolerance), pointing
    the manifest author at `depends_on`. `groups` is the ONE command tree (group -> command -> spec, #729);
    the former separate flat `commands` map and its dotted group-scoped keys are gone - NESTING resolves a
    name owned by several groups. The six validation rules run here (rule 1 groups non-empty; rule 2
    env_groups subset; rule 3 every spec has a non-empty help plus impl XOR depends_on; rule 4 every
    `depends_on` entry names a known, unambiguous command (#895); rule 5 the dependency graph is acyclic
    (#895); rule 6 two aggregates in ONE plan agree on `stop_on_failure` over a dependency they both
    declare (netctl#1319)), each raised as a ValueError so `load()` surfaces the same clean message the
    imperative loader did."""

    model_config = ConfigDict(extra="ignore")

    groups: dict[str, dict[str, _CommandSpecModel]] = {}
    env_groups: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_composites(cls, data: object) -> object:
        # The composites concept was REMOVED (netctl#898, subsumed by depends_on). A leftover `composites:`
        # key must fail loudly here - silently dropping it via extra="ignore" would turn a still-declared
        # pipeline into dead data. Every other unknown top-level key stays ignored (backward compatible).
        if isinstance(data, dict) and "composites" in data:
            raise ValueError(
                "manifest declares 'composites', which has been removed: declare an impl-less "
                "aggregate command with 'depends_on' instead (netctl#898)")
        return data

    @field_validator("groups", mode="before")
    @classmethod
    def _coerce_groups(cls, value: object) -> dict:
        # group name -> {command name -> spec body}, str-coerced. A null/absent member map becomes an empty
        # group; a null spec body becomes an empty mapping so the sub-model defaults apply (then the
        # missing-impl rule below names it). Ordered: dict insertion order is the member order.
        return {str(group): {str(name): (spec or {}) for name, spec in (members or {}).items()}
                for group, members in (value or {}).items()}

    taxonomy: dict[str, dict] = {}

    @field_validator("env_groups", mode="before")
    @classmethod
    def _coerce_env_groups(cls, value: object) -> tuple[str, ...]:
        return tuple(str(group) for group in (value or ()))

    @model_validator(mode="after")
    def _validate_taxonomy(self) -> "_ManifestModel":
        # rule 1: `groups` maps each declared group to its ordered command tree (the ONE membership + spec source).
        if not self.groups:
            raise ValueError("manifest defines no groups")

        # rule 2: every `env_groups` entry names a declared TOP-LEVEL group. A dotted entry is rejected
        # rather than honoured: `env_groups` is the flat key, a nested node declares `env_first: true` in
        # the `taxonomy:` block, and accepting the dotted spelling loaded cleanly while making the env
        # gate a silent no-op for that group - a CD command that must be backend-gated reached "ok".
        for group in self.env_groups:
            if "." in group:
                raise ValueError(
                    f"env_groups entry '{group}' names a NESTED group. env_groups takes top-level "
                    f"groups only - declare `env_first: true` on that group in the `taxonomy:` block "
                    f"instead; every descendant inherits it")
            if group not in self.groups:
                raise ValueError(f"env_groups entry '{group}' is not a declared group")

        # rule 3: every command spec declares a non-empty `help`, plus EITHER a well-formed
        # "module:function" `impl` (a leaf) OR a non-empty `depends_on` (an impl-less aggregate, #895) -
        # never both (v1 lock: plan steps run as subprocesses, so an impl-bearing command with deps would
        # re-expand them in the child and break dedup-once; forward path is a child-side skip-deps env
        # guard, deliberately not built). The error names the owning group + command.
        for group, members in self.groups.items():
            for name, spec in members.items():
                if spec.impl and spec.depends_on:
                    raise ValueError(
                        f"command '{group}.{name}': impl and depends_on are mutually exclusive")
                # A passthrough command forwards trailing args to ONE underlying tool; an aggregate's plan
                # runs each leaf as its own subprocess, so there is no single forwarding target (#896).
                if spec.depends_on and spec.passthrough_args:
                    raise ValueError(
                        f"command '{group}.{name}': passthrough_args cannot combine with depends_on")
                # stop_on_failure scopes to the SUBTREE of the command that declares it (netctl#1317), and
                # a leaf's subtree is the leaf: by the time it has failed there is nothing left below it to
                # skip. Someone writing it on `up-preflight` to stop the bring-up would get a clean load and
                # no effect whatsoever, which is the same trap keep_awake and hidden are rejected for.
                if spec.stop_on_failure and not spec.depends_on:
                    raise ValueError(
                        f"command '{group}.{name}': stop_on_failure applies to an aggregate "
                        f"(depends_on); on a leaf it would scope to that leaf alone and skip nothing - "
                        f"declare it on the aggregate whose remaining steps should be skipped")
                # keep_awake is honoured by `run_command`, which only ever runs an aggregate's PLAN. The
                # CLI binds a leaf straight to its impl, so the flag there would be silently ignored -
                # and a flag that does nothing where it is written is worse than no flag (netctl#1238).
                if spec.keep_awake and not spec.depends_on:
                    raise ValueError(
                        f"command '{group}.{name}': keep_awake applies to an aggregate's plan "
                        f"(depends_on); a leaf's own impl arms it itself")
                # hidden (netctl#1277) is honoured by delivery.cli.assemble, which threads it onto a
                # command's GROUP registration. A group-default group's NAMESAKE member (#592 D4: the
                # member whose name equals its multi-member group's name) never reaches that registration
                # at all - it is bound as the sub-app's default callback, never a listed subcommand or a
                # separate flat command - so hidden there would do nothing, the same reasoning that rejects
                # keep_awake on a leaf above.
                if spec.hidden and name == group and len(members) > 1:
                    raise ValueError(
                        f"command '{group}.{name}': hidden has no effect on a group-default namesake "
                        f"member (it is the sub-app's default action, never a listed command); "
                        f"hidden a sibling instead")
                if not spec.impl and not spec.depends_on:
                    raise ValueError(f"command '{group}.{name}': missing impl")
                if spec.impl:
                    _split_impl(spec.impl, f"command '{group}.{name}'")   # validates the "module:function" shape
                if not spec.help:
                    raise ValueError(f"command '{group}.{name}': missing help")

        # rule 4 (#895): every `depends_on` entry names a KNOWN, UNAMBIGUOUS command - a dependency is a
        # bare name, so a name owned by SEVERAL groups cannot be depended on (Manifest.plan_for could not
        # resolve it), and a typo fails loudly here, not deep in the runner.
        owners_by_name: dict[str, list[str]] = {}
        for group, members in self.groups.items():
            for name in members:
                owners_by_name.setdefault(name, []).append(group)
        for group, members in self.groups.items():
            for name, spec in members.items():
                for dep in spec.depends_on:
                    owners = owners_by_name.get(dep, [])
                    if not owners:
                        raise ValueError(
                            f"command '{group}.{name}': dependency '{dep}' is not a command in the manifest")
                    if len(owners) > 1:
                        raise ValueError(
                            f"command '{group}.{name}': dependency '{dep}' is ambiguous "
                            f"(owned by groups {sorted(owners)})")

        # rule 5 (#895): the depends_on graph is ACYCLIC - a 3-colour DFS (white = unvisited, grey = on
        # the current path, black = done) over the flat name graph. Only unambiguous names carry edges
        # (rule 4), so an ambiguous name can never sit inside a cycle; its own out-edges are still walked
        # because every dependency it names is an unambiguous node visited below.
        deps_by_name = {name: self.groups[owners[0]][name].depends_on
                        for name, owners in owners_by_name.items() if len(owners) == 1}
        done: set[str] = set()

        def walk(cmd: str, trail: list[str]) -> None:
            if cmd in done:
                return
            if cmd in trail:
                raise ValueError("dependency cycle: " + " -> ".join(trail[trail.index(cmd):] + [cmd]))
            trail.append(cmd)
            for dep in deps_by_name.get(cmd, ()):
                walk(dep, trail)
            trail.pop()
            done.add(cmd)

        for name in deps_by_name:
            walk(name, [])

        # rule 6 (netctl#1319): two aggregates that ONE plan reaches must not disagree on stop_on_failure
        # over a dependency they BOTH declare. `plan_tree_for` is a DFS SPANNING tree, so such a dependency
        # is planned under whichever aggregate the traversal reaches first and deduplicated under the
        # other; the loser is then not on that leaf's chain at all and `abort_after` never consults its
        # flag - it said "stop on failure", its own dependency died, and the subtree it guards ran anyway.
        # The comparison is between the two DIRECT declarers' OWN flags, and that is the exact extent of
        # what the guard catches. Two things it deliberately does not: a relocation between declarers that
        # AGREE still narrows the abort scope to whichever of them carries the dependency, and a declarer
        # whose flag is false under a `true` ANCESTOR has an effective policy the guard never compares, so
        # the same contradiction reappears one level up. Extending it to effective policy is not a bigger
        # check but a different one - a declarer's outermost true ancestor differs per entry point, so the
        # comparison would become per plan AND per declarer - which is the declaration-graph scoping this
        # ticket defers, not this guard. `steps.abort_after` states the surviving shapes in the same terms.
        #
        # "Within one plan" is the whole substance of the rule. Two aggregates share a plan exactly when
        # some command's plan reaches both, which is equivalent to sharing an ENTRY POINT (a command no
        # other command depends on): every common ancestor has an entry-point ancestor of its own, and in
        # an acyclic graph - rule 5 above has just proven this one is - every node has at least one. Naming
        # that entry point is also the actionable half of the message, because it is a plan a human really
        # invokes. Aggregates under DIFFERENT entry points keep their differing policy, which is the case a
        # manifest-wide rule would have got wrong: netctl's `deploy bringup` (a strict chain) and its two
        # `all` collections disagree over five shared commands today, correctly, and must keep loading.
        #
        # Cost: the reverse walk runs only for a dependency whose declarers already disagree, so a manifest
        # with no such dependency pays one pass to build the maps. Measured on netctl's manifest (71
        # commands, 47 dependency edges, 5 disagreeing dependencies, 0 rejections): ~5 us per load, against
        # ~47 us for the alternative of planning every command as a root.
        declarers: dict[str, list[tuple[str, bool]]] = {}
        parents_by_path: dict[str, set[str]] = {}
        for group, members in self.groups.items():
            for name, spec in members.items():
                path = f"{group}.{name}"
                for dep in spec.depends_on:
                    # rule 4 has passed, so `dep` names exactly one owner and the dotted path is exact.
                    declarers.setdefault(dep, []).append((path, spec.stop_on_failure))
                    parents_by_path.setdefault(f"{owners_by_name[dep][0]}.{dep}", set()).add(path)

        entry_points: dict[str, frozenset[str]] = {}

        def plans_reaching(path: str) -> frozenset[str]:
            """The plans that contain `path`: the ancestors it has that nothing depends on, memoised.

            `path` ITSELF is in the result when nothing depends on it - a plan contains its own root, and
            that is what makes the declarer-is-the-entry-point case (one declarer sitting above the other)
            come out as a collision rather than as two disjoint sets."""
            if path not in entry_points:
                roots: set[str] = set()
                seen, stack = {path}, [path]
                while stack:
                    node = stack.pop()
                    parents = parents_by_path.get(node, ())
                    if not parents:
                        roots.add(node)
                    for parent in parents:
                        if parent not in seen:
                            seen.add(parent)
                            stack.append(parent)
                entry_points[path] = frozenset(roots)
            return entry_points[path]

        for dep in sorted(declarers):
            declared_by = declarers[dep]
            for index, (first, first_stops) in enumerate(declared_by):
                for second, second_stops in declared_by[index + 1:]:
                    if first_stops == second_stops:
                        continue
                    shared = plans_reaching(first) & plans_reaching(second)
                    if shared:
                        raise ValueError(
                            f"aggregates '{first}' and '{second}' both declare dependency '{dep}' but "
                            f"disagree on stop_on_failure, and plan '{sorted(shared)[0]}' reaches both: "
                            f"the plan tree is a spanning tree, so '{dep}' is planned under ONE of them "
                            f"and the other's stop_on_failure never fires for its own dependency - give "
                            f"both aggregates the same stop_on_failure (netctl#1319)")

        return self


def _validation_message(error: ValidationError) -> str:
    """Reduce a Pydantic ValidationError to the single human message the former hand-rolled loader raised.

    A rule violation surfaces as a `value_error` whose ctx carries the original ValueError, so its message
    is returned verbatim (the tests assert on those exact strings). A pure shape/type error (a malformed
    manifest Pydantic rejected before the rules could run) is rendered as `<location>: <message>`. Only the
    first error is reported, mirroring the former fail-on-first-problem behaviour.
    """
    details = error.errors(include_url=False)
    for detail in details:
        original = (detail.get("ctx") or {}).get("error")
        if isinstance(original, Exception):
            return str(original)
    detail = details[0]
    location = ".".join(str(part) for part in detail.get("loc", ()))
    message = detail.get("msg", "invalid manifest")
    return f"{location}: {message}" if location else message


def load(text: str, *, validate_with: bool = False) -> Manifest:
    """Parse a product manifest YAML into a validated Manifest (pure: no import of the impls, no Typer).

    Validates through the private `_ManifestModel`, failing loudly with ValueError so a bad manifest is
    caught here and not deep in the CLI:
      - `groups` maps each declared group to its ordered command tree (group -> command -> spec, the ONE
        membership + spec source);
      - every `env_groups` entry is a declared group;
      - every command spec declares a non-empty `help`, plus either a well-formed "module:function" `impl`
        (a leaf) or a non-empty `depends_on` (an impl-less aggregate, #895) - never both;
      - every `depends_on` entry (#895) names a known, UNAMBIGUOUS command, and the dependency graph is
        acyclic;
      - `keep_awake` (netctl#1238) is declared only on an AGGREGATE, because `run_command` - which runs a
        plan - is its only consumer; on a leaf it would be silently ignored;
      - `stop_on_failure` (netctl#1317) is likewise declared only on an AGGREGATE: it scopes to the
        subtree of the command that declares it, and a leaf's subtree is the leaf, so there is nothing
        left below it to skip;
      - two aggregates that ONE plan reaches agree on `stop_on_failure` over a dependency they BOTH
        declare (netctl#1319): a plan tree is a spanning tree, so that dependency is planned under one of
        them only and the other's flag would never fire for it. Aggregates in DIFFERENT plans (two entry
        points that never meet, such as a strict bring-up chain next to a test collection) keep their
        differing policy, which is why the rule is scoped per plan rather than manifest-wide;
      - `hidden` (netctl#1277) is rejected on a group-default group's NAMESAKE member, because that member
        never reaches the registration `delivery.cli.assemble` would apply it to.
    Unknown top-level keys stay ignored (backward compatible), with ONE exception: a leftover `composites:`
    key is rejected loudly (the concept was removed in netctl#898; declare an impl-less aggregate command
    with `depends_on` instead) - silently dropping it would turn a still-declared pipeline into dead data.
    Any Pydantic ValidationError is re-raised as a plain ValueError (a raw ValidationError never escapes),
    then the validated model is converted into the public NamedTuples so callers see the unchanged types:
    `groups` is the membership projection (each group's ordered command names) and `commands` is the nested
    spec tree (group -> command -> spec).
    """
    data = yaml.safe_load(text) or {}
    try:
        model = _ManifestModel.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_validation_message(exc)) from exc

    groups = {group: tuple(members) for group, members in model.groups.items()}
    commands = {
        group: {name: CommandSpec(impl=spec.impl, help=spec.help, passthrough_args=spec.passthrough_args,
                                  depends_on=spec.depends_on, stop_on_failure=spec.stop_on_failure,
                                  keep_awake=spec.keep_awake, hidden=spec.hidden, with_=spec.with_)
                for name, spec in members.items()}
        for group, members in model.groups.items()
    }
    env_groups = frozenset(model.env_groups)
    tree = merge_trees(_catalogue_tree(model.taxonomy, groups), _flat_tree(groups, env_groups))
    # Every DOTTED `groups:` key must name a node the `taxonomy:` block actually declares. Without this,
    # an unmatched path was dropped from the tree while `groups`/`commands` kept it: the commands stayed
    # registered and runnable but were invisible to the taxonomy, so they were never env-gated and never
    # counted towards ambiguity. A typo in a nested path has to fail at load, not disable a gate.
    taxonomy = CommandTaxonomy.from_tree(tree)
    for name in groups:
        if "." in name and taxonomy.resolve_path(name) is None:
            raise ValueError(
                f"groups entry '{name}' names a nested group the `taxonomy:` block does not declare - "
                f"declare it there, or move its commands to a top-level group")
    if validate_with:
        _validate_with_bindings(commands)
    return Manifest(groups=groups, env_groups=env_groups, commands=commands, tree=tree)


def _catalogue_tree(declared: dict[str, dict],
                    members: dict[str, tuple[str, ...]]) -> dict[str, TaxonomyNode]:
    """Build the NESTED part of the tree from a `taxonomy:` block, attaching each group's members.

    A group's members are declared under its dotted PATH in `groups:` (`support.git`), so a node's
    commands are looked up by the path this recursion has walked, not by its bare name.
    """
    def build(spec: dict[str, dict], prefix: str) -> dict[str, TaxonomyNode]:
        out: dict[str, TaxonomyNode] = {}
        for name, node in spec.items():
            here = f"{prefix}.{name}" if prefix else name
            out[name] = TaxonomyNode(name=name,
                                     commands=members.get(here, ()),
                                     groups=build(node.get("groups", {}) or {}, here),
                                     env_first=bool(node.get("env_first", False)))
        return out

    return build(declared, "")


def _flat_tree(members: dict[str, tuple[str, ...]],
               env_groups: frozenset[str]) -> dict[str, TaxonomyNode]:
    """The depth-1 tree for every BARE `groups:` key - the product's own top-level groups.

    A DOTTED key (`support.git`) names members of a node the taxonomy block already built, so it is not
    a top-level group and is skipped here. A bare key is the product's, and if the catalogue declares it
    too, merge_trees() raises - which is the point. Filtering these out by "the taxonomy block already
    claims this name" would swallow exactly the contradiction the merge rule exists to catch.
    """
    return {name: TaxonomyNode(name=name, commands=cmds, env_first=name in env_groups)
            for name, cmds in members.items() if "." not in name}


def _validate_with_bindings(commands: dict[str, dict[str, "CommandSpec"]]) -> None:
    """Reject a `with:` key that is not a parameter of the command's impl.

    This is the check that makes `with:` worth having: without it a typo is a silently ignored override,
    which is the failure mode the task generator exists to remove. It costs an IMPORT of every impl that
    binds one, which is why it is opt-in - the pure-parse tests must stay import-free - and why the
    generator always turns it on.
    """
    from delivery import signatures      # lazy: taskgen/signatures must not be a load-time dependency

    for group, members in commands.items():
        for name, spec in members.items():
            if not spec.with_ or not spec.impl:
                continue
            body = resolve_ref(spec.impl, f"{group} {name}")
            # BINDABLE parameters only, the same set the generator will substitute into. Using every
            # signature name accepted `with: {c: ...}` - binding the CLI context, the likeliest real
            # typo - and the generator then discarded it silently.
            params = {p.name for p in signatures.bindable(body)}
            unknown = sorted(set(spec.with_) - params)
            if unknown:
                raise ValueError(
                    f"`{group} {name}` binds `with:` key(s) {', '.join(unknown)} that are not parameters "
                    f"of {spec.impl} (it takes: {', '.join(sorted(params))})")


def resolve_ref(ref: str, where: str) -> Callable[..., object]:
    """Import a "module:function" reference and return the callable - the one place a declarative ref
    becomes real code. `where` labels the errors so a stale ref points at the declaration that carries it.

    A command's `impl:` is the original consumer, but it is not the only kind of ref a manifest carries: a
    product also declares HOOKS a kernel command calls back into (netctl#1406 - the lab preamble and the
    health precondition of a suite gate). Those are data in the manifest exactly as an impl is, so they
    resolve through the same function rather than a second, subtly different importer.
    """
    module_name, function_name = _split_impl(ref, where)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"{where}: cannot import module '{module_name}': {exc}") from exc
    try:
        return getattr(module, function_name)
    except AttributeError as exc:
        raise ValueError(
            f"{where}: module '{module_name}' has no attribute '{function_name}'") from exc


def resolve_impl(spec: CommandSpec) -> Callable[..., object]:
    """Import the module named in the spec's `impl` and return its function - where the manifest's
    declarative "module:function" becomes the real callable the CLI runs. Raises a clear ValueError if the
    module cannot be imported or the function is missing (so a stale impl ref fails loudly, not silently).
    """
    return resolve_ref(spec.impl, f"impl '{spec.impl}'")
