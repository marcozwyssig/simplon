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
models). The PUBLIC surface stays the NamedTuples `CommandSpec` / `CompositeSpec` / `Manifest`: `load()`
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
    """
    impl: str
    help: str
    passthrough_args: bool = False


class CompositeSpec(NamedTuple):
    """A named, ordered command pipeline declared in the manifest (#456): the step command NAMES to run in
    order, and whether a failed step stops the rest (`stop_on_failure`, default False = run every step and
    take the worst rc). Every step must name a command that exists in the manifest (validated in `load()`).
    This makes composites (bringup, test.all, ...) DATA in the manifest instead of product Python, so a
    second product gets the same runner + its own composites for free. The runner lives in
    `delivery.orchestrator.product.run_composite`.
    """
    steps: tuple[str, ...]
    stop_on_failure: bool = False


class Manifest(NamedTuple):
    """A parsed, validated product manifest, held as ONE hierarchy (#729): the command taxonomy (group ->
    its command names, and the subset of env-first groups) plus each command's spec, nested under its group.
    `groups` is the membership projection (each group's ordered command names) the shared CommandTaxonomy
    consumes, so `taxonomy()` builds the env-gate without duplicating its logic. `commands` is the nested
    spec tree (group -> command -> spec), so `spec_for(group, name)` resolves a member's spec by NESTING -
    the same name may live in several groups (#519: `test all` next to `deploy all`), each owner carrying its
    own spec, with no flat dotted keys. `composites` maps a composite name to its ordered step commands
    (#456); empty on a manifest that declares none.
    """
    groups: dict[str, tuple[str, ...]]
    env_groups: frozenset[str]
    commands: dict[str, dict[str, CommandSpec]]
    composites: dict[str, CompositeSpec] = {}

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
        name OR an ambiguous one owned by several groups (#519: `all`). This flat view is used for the
        display LABEL of an unambiguous composite step (delivery.orchestrator.product maps a composite's bare
        step names through the product step factory); a caller that must disambiguate an owned-by-many name
        uses spec_for(group, name)."""
        owners = [group for group, specs in self.commands.items() if name in specs]
        return self.commands[owners[0]][name] if len(owners) == 1 else None


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
# `bool(...)`, `... or ()`). Rules whose error names a specific command / composite are enforced in the
# manifest-level `@model_validator` so the message can carry that name (the tests assert on those strings).


class _CommandSpecModel(BaseModel):
    """Parse/validate view of one command declaration. Coerces the scalars exactly like the former loader
    and IGNORES unknown keys inside a spec. The non-empty-impl/help and 'module:function' rules live on the
    manifest model so their errors can name the owning group + command."""

    model_config = ConfigDict(extra="ignore")

    impl: str = ""
    help: str = ""
    passthrough_args: bool = False

    @field_validator("impl", "help", mode="before")
    @classmethod
    def _stripped_str(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("passthrough_args", mode="before")
    @classmethod
    def _as_bool(cls, value: object) -> bool:
        return bool(value)


class _CompositeSpecModel(BaseModel):
    """Parse/validate view of one composite pipeline: its ordered step names and the stop-on-failure flag.
    Coerces like the former loader and IGNORES unknown keys; the non-empty-steps and known-step rules live
    on the manifest model so their errors can name the composite."""

    model_config = ConfigDict(extra="ignore")

    steps: tuple[str, ...] = ()
    stop_on_failure: bool = False

    @field_validator("steps", mode="before")
    @classmethod
    def _str_tuple(cls, value: object) -> tuple[str, ...]:
        return tuple(str(step) for step in (value or ()))

    @field_validator("stop_on_failure", mode="before")
    @classmethod
    def _as_bool(cls, value: object) -> bool:
        return bool(value)


class _ManifestModel(BaseModel):
    """Parse/validate view of the whole manifest. Unknown TOP-LEVEL sections (product, environments,
    default, images, ... - a product's own build data) are IGNORED, exactly as the former loader read only
    the taxonomy sections. `groups` is the ONE command tree (group -> command -> spec, #729); the former
    separate flat `commands` map and its dotted group-scoped keys are gone - NESTING resolves a name owned
    by several groups. The four validation rules run here (rule 1 groups non-empty; rule 2 env_groups subset;
    rule 3 every spec has a well-formed non-empty impl/help; rule 4 composite steps name real commands), each
    raised as a ValueError so `load()` surfaces the same clean message the imperative loader did."""

    model_config = ConfigDict(extra="ignore")

    groups: dict[str, dict[str, _CommandSpecModel]] = {}
    env_groups: tuple[str, ...] = ()
    composites: dict[str, _CompositeSpecModel] = {}

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

    @field_validator("composites", mode="before")
    @classmethod
    def _coerce_composites(cls, value: object) -> dict:
        # str-coerce the composite keys and treat a null body as an empty mapping (the sub-model defaults
        # then apply), mirroring the former `name = str(name); spec = spec or {}`.
        return {str(name): (spec or {}) for name, spec in (value or {}).items()}

    @model_validator(mode="after")
    def _validate_taxonomy(self) -> "_ManifestModel":
        # rule 1: `groups` maps each declared group to its ordered command tree (the ONE membership + spec source).
        if not self.groups:
            raise ValueError("manifest defines no groups")

        # rule 2: every `env_groups` entry names a declared group.
        for group in self.env_groups:
            if group not in self.groups:
                raise ValueError(f"env_groups entry '{group}' is not a declared group")

        # rule 3: every command spec declares a non-empty `help` and a well-formed "module:function" `impl`.
        # The error names the owning group + command (nesting makes the owner explicit).
        for group, members in self.groups.items():
            for name, spec in members.items():
                if not spec.impl:
                    raise ValueError(f"command '{group}.{name}': missing impl")
                _split_impl(spec.impl, f"command '{group}.{name}'")   # validates the "module:function" shape
                if not spec.help:
                    raise ValueError(f"command '{group}.{name}': missing help")

        # rule 4: every composite step names a command that is a member of some group (the flat name set), so
        # a typo fails loudly here, not deep in the runner. `stop_on_failure` default False.
        known_commands = {name for members in self.groups.values() for name in members}
        for name, spec in self.composites.items():
            if not spec.steps:
                raise ValueError(f"composite '{name}': needs a non-empty 'steps' list")
            for step in spec.steps:
                if step not in known_commands:
                    raise ValueError(
                        f"composite '{name}': step '{step}' is not a command in the manifest")

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
      - every command spec declares a non-empty `help` and a well-formed "module:function" `impl`;
      - every `composites` entry (#456) declares a non-empty `steps` list and every step names a command
        that exists in the manifest (a member of some group).
    Unknown top-level keys stay ignored (backward compatible). Any Pydantic ValidationError is re-raised as
    a plain ValueError (a raw ValidationError never escapes), then the validated model is converted into the
    public NamedTuples so callers see the unchanged types: `groups` is the membership projection (each
    group's ordered command names) and `commands` is the nested spec tree (group -> command -> spec).
    """
    data = yaml.safe_load(text) or {}
    try:
        model = _ManifestModel.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_validation_message(exc)) from exc

    groups = {group: tuple(members) for group, members in model.groups.items()}
    commands = {
        group: {name: CommandSpec(impl=spec.impl, help=spec.help, passthrough_args=spec.passthrough_args)
                for name, spec in members.items()}
        for group, members in model.groups.items()
    }
    composites = {
        name: CompositeSpec(steps=spec.steps, stop_on_failure=spec.stop_on_failure)
        for name, spec in model.composites.items()
    }
    return Manifest(groups=groups, env_groups=frozenset(model.env_groups),
                    commands=commands, composites=composites)


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
