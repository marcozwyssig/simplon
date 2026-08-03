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
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from delivery.clitaxonomy import CommandTaxonomy


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
    (e.g. NETCTL_SKIP_DEPS=1) - deliberately NOT built now. `stop_on_failure` (an aggregate's flag) makes
    a failed plan step skip the rest instead of running doomed work (default False = run every step and
    take the worst rc).
    """
    impl: str
    help: str
    passthrough_args: bool = False
    depends_on: tuple[str, ...] = ()
    stop_on_failure: bool = False


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

    def taxonomy(self) -> CommandTaxonomy:
        """The shared env-gate engine built from this manifest's taxonomy (one env-gate, not a copy)."""
        return CommandTaxonomy(self.groups, self.env_groups)

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

    def plan_for(self, name: str, *, group: str | None = None) -> tuple[str, ...]:
        """The execution plan for command `name` (#895): a post-order DFS over `depends_on`, so every
        transitive dependency is planned BEFORE its dependant; a `done` set dedups by name, so a command
        reached along several paths (a diamond) appears exactly ONCE per top-level invocation; and a node
        is emitted only if it carries its own `impl` - an impl-less AGGREGATE contributes its leaves,
        never itself. A grey-set (DFS trail) cycle guard fails loudly, defensively: load() already
        rejects cyclic manifests, so a validated manifest never trips it here.

        `name` is a bare command name; `group` disambiguates a ROOT owned by several groups (#519:
        `test all` vs `deploy all`). Dependency ENTRIES are always bare names - load() validates each as
        known and unambiguous, so they resolve via spec_by_name without a group."""
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

        root = (self.commands.get(group, {}).get(name) if group is not None
                else self.spec_by_name(name))
        if root is None:
            raise ValueError(f"no unambiguous command named '{name}' in the manifest")
        visit(name, root)
        return tuple(plan)


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

    model_config = ConfigDict(extra="ignore")

    impl: str = ""
    help: str = ""
    passthrough_args: bool = False
    depends_on: tuple[str, ...] = ()
    stop_on_failure: bool = False

    @field_validator("impl", "help", mode="before")
    @classmethod
    def _stripped_str(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("depends_on", mode="before")
    @classmethod
    def _str_tuple(cls, value: object) -> tuple[str, ...]:
        return tuple(str(dep) for dep in (value or ()))

    @field_validator("passthrough_args", "stop_on_failure", mode="before")
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
    name owned by several groups. The five validation rules run here (rule 1 groups non-empty; rule 2
    env_groups subset; rule 3 every spec has a non-empty help plus impl XOR depends_on; rule 4 every
    `depends_on` entry names a known, unambiguous command (#895); rule 5 the dependency graph is acyclic
    (#895)), each raised as a ValueError so `load()` surfaces the same clean message the imperative loader
    did."""

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

    @field_validator("env_groups", mode="before")
    @classmethod
    def _coerce_env_groups(cls, value: object) -> tuple[str, ...]:
        return tuple(str(group) for group in (value or ()))

    @model_validator(mode="after")
    def _validate_taxonomy(self) -> "_ManifestModel":
        # rule 1: `groups` maps each declared group to its ordered command tree (the ONE membership + spec source).
        if not self.groups:
            raise ValueError("manifest defines no groups")

        # rule 2: every `env_groups` entry names a declared group.
        for group in self.env_groups:
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


def load(text: str) -> Manifest:
    """Parse a product manifest YAML into a validated Manifest (pure: no import of the impls, no Typer).

    Validates through the private `_ManifestModel`, failing loudly with ValueError so a bad manifest is
    caught here and not deep in the CLI:
      - `groups` maps each declared group to its ordered command tree (group -> command -> spec, the ONE
        membership + spec source);
      - every `env_groups` entry is a declared group;
      - every command spec declares a non-empty `help`, plus either a well-formed "module:function" `impl`
        (a leaf) or a non-empty `depends_on` (an impl-less aggregate, #895) - never both;
      - every `depends_on` entry (#895) names a known, UNAMBIGUOUS command, and the dependency graph is
        acyclic.
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
                                  depends_on=spec.depends_on, stop_on_failure=spec.stop_on_failure)
                for name, spec in members.items()}
        for group, members in model.groups.items()
    }
    return Manifest(groups=groups, env_groups=frozenset(model.env_groups), commands=commands)


def resolve_impl(spec: CommandSpec) -> Callable[..., object]:
    """Import the module named in the spec's `impl` and return its function - where the manifest's
    declarative "module:function" becomes the real callable the CLI runs. Raises a clear ValueError if the
    module cannot be imported or the function is missing (so a stale impl ref fails loudly, not silently).
    """
    module_name, function_name = _split_impl(spec.impl, f"impl '{spec.impl}'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"impl '{spec.impl}': cannot import module '{module_name}': {exc}") from exc
    try:
        return getattr(module, function_name)
    except AttributeError as exc:
        raise ValueError(
            f"impl '{spec.impl}': module '{module_name}' has no attribute '{function_name}'") from exc
