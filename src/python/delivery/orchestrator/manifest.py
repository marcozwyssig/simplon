"""Manifest-driven CLI assembly for the CI/CD orchestrator: a per-product YAML manifest is the ONE
declarative source for the command taxonomy (groups + env-gating), each command's implementation
reference ("module:function") and its help summary. A product ships the manifest + the command impls;
this engine reads the manifest and the product assembles its CLI from it - product-specifics become
DATA, not code, which dissolves the platform -> product coupling.

The engine is PURE and framework-free: it parses + validates the manifest (loudly, like
delivery.environments.parse), resolves an impl reference to the real callable, and builds the shared
CommandTaxonomy (the env-gate) from the manifest so that logic is reused, not copied. It deliberately
imports no CLI framework: registering Typer commands / sub-apps / help panels is the PRODUCT's job (the
engine must not bind to one CLI framework). "One source, two outputs": the same manifest assembles the
runtime CLI now and, in Phase 2, the CI workflows.

Parsing + validation run through the private Pydantic v2 models below (`_ManifestModel` and its spec
models). The PUBLIC surface stays the NamedTuples `CommandSpec` / `CompositeSpec` / `Manifest`: `load()`
converts the validated model into those tuples before returning, so consumers see byte-for-byte the same
types (field access, tuple unpacking, `taxonomy()`, `spec_for()`). The fail-loud contract is unchanged -
every rule violation is raised as a ValueError, and `load()` re-raises any Pydantic ValidationError as a
plain ValueError so a raw ValidationError never escapes.
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
    framework's settings. The owning GROUP is deliberately NOT stored here: it is derivable from the
    manifest's `groups` map (the single membership source), so a command can never disagree with it.
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
    """A parsed, validated product manifest: the command taxonomy (group -> its command names, and the
    subset of env-first groups) plus each command's spec. `groups` and `env_groups` already have the exact
    shape the shared CommandTaxonomy consumes, so `taxonomy()` builds the env-gate without duplicating its
    logic. `commands` keeps the spec keys AS DECLARED - plain (`up`) or group-scoped (`deploy.all`, #519);
    resolve a member's spec through `spec_for`, which knows the scoped-first precedence. `composites` maps a
    composite name to its ordered step commands (#456); empty on a manifest that declares none.
    """
    groups: dict[str, tuple[str, ...]]
    env_groups: frozenset[str]
    commands: dict[str, CommandSpec]
    composites: dict[str, CompositeSpec] = {}

    def taxonomy(self) -> CommandTaxonomy:
        """The shared env-gate engine built from this manifest's taxonomy (one env-gate, not a copy)."""
        return CommandTaxonomy(self.groups, self.env_groups)

    def spec_for(self, group: str, name: str) -> CommandSpec:
        """The spec for a group member: its group-scoped declaration (`<group>.<name>`) when present,
        else the plain one. load() guarantees every member resolves (and that a name owned by several
        groups is declared scoped per owner), so this lookup cannot miss on a validated manifest."""
        scoped = self.commands.get(f"{group}.{name}")
        return scoped if scoped is not None else self.commands[name]


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
    manifest model so their errors can name the owning command."""

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
    groups/env_groups/commands/composites. The six validation rules run here (rule 1 groups non-empty;
    rule 2 env_groups subset; rule 3 multi-owner reverse index; rule 4 membership<->specs agreement both
    ways; rule 5 well-formed non-empty impl/help; rule 6 composite steps exist), each raised as a ValueError
    so `load()` surfaces the same clean message the imperative loader did."""

    model_config = ConfigDict(extra="ignore")

    groups: dict[str, tuple[str, ...]] = {}
    env_groups: tuple[str, ...] = ()
    commands: dict[str, _CommandSpecModel] = {}
    composites: dict[str, _CompositeSpecModel] = {}

    @field_validator("groups", mode="before")
    @classmethod
    def _coerce_groups(cls, value: object) -> dict:
        # each group name -> its ordered members, str-coerced; a null/absent member list becomes empty.
        return {str(name): tuple(str(member) for member in (members or ()))
                for name, members in (value or {}).items()}

    @field_validator("env_groups", mode="before")
    @classmethod
    def _coerce_env_groups(cls, value: object) -> tuple[str, ...]:
        return tuple(str(group) for group in (value or ()))

    @field_validator("commands", "composites", mode="before")
    @classmethod
    def _coerce_spec_map(cls, value: object) -> dict:
        # str-coerce the spec keys and treat a null spec body as an empty mapping (the sub-model defaults
        # then apply), mirroring the former `name = str(name); spec = spec or {}`.
        return {str(name): (spec or {}) for name, spec in (value or {}).items()}

    @model_validator(mode="after")
    def _validate_taxonomy(self) -> "_ManifestModel":
        # rule 1: `groups` maps each declared group to its ordered command names (the single membership source).
        if not self.groups:
            raise ValueError("manifest defines no groups")

        # rule 2: every `env_groups` entry names a declared group.
        for group in self.env_groups:
            if group not in self.groups:
                raise ValueError(f"env_groups entry '{group}' is not a declared group")

        # rule 5: every spec declares a non-empty `help` and a well-formed "module:function" `impl`. Enforced
        # here (not on _CommandSpecModel) so the error names the owning command, as the former loader did.
        for name, spec in self.commands.items():
            if not spec.impl:
                raise ValueError(f"command '{name}': missing impl")
            _split_impl(spec.impl, f"command '{name}'")   # validates the "module:function" shape
            if not spec.help:
                raise ValueError(f"command '{name}': missing help")

        # multi-owner reverse index: the SAME name may live in several groups (#519), in which case every
        # owner must declare a group-scoped spec (validated below) and the name loses its flat form.
        command_groups: dict[str, list[str]] = {}
        for group, members in self.groups.items():
            for cmd in members:
                command_groups.setdefault(cmd, []).append(group)

        # rule 4 (membership -> spec): every group member resolves to a spec (plain or group-scoped).
        missing_spec = sorted(
            c for c, owners in command_groups.items()
            if any(c not in self.commands and f"{g}.{c}" not in self.commands for g in owners))
        if missing_spec:
            raise ValueError(f"commands declared in a group but missing a spec: {missing_spec}")

        # rule 3: a name owned by SEVERAL groups must be declared group-scoped per owner (a lone plain spec
        # would be ambiguous).
        ambiguous_plain = sorted(
            c for c, owners in command_groups.items()
            if len(owners) > 1 and any(f"{g}.{c}" not in self.commands for g in owners))
        if ambiguous_plain:
            raise ValueError(
                f"commands owned by several groups need a group-scoped spec per owner "
                f"('<group>.<name>'): {ambiguous_plain}")

        # rule 4 (spec -> membership): a scoped key names a real member of its group; a plain key is a member
        # of some group; anything else is an orphan spec.
        orphans: list[str] = []
        for key in self.commands:
            group, sep, name = key.partition(".")
            if sep and group in self.groups:
                if name not in self.groups[group]:
                    raise ValueError(f"scoped spec '{key}': '{name}' is not a member of group '{group}'")
            elif key not in command_groups:
                orphans.append(key)
        if orphans:
            raise ValueError(f"commands with a spec but not in any declared group: {sorted(orphans)}")

        # rule 6: every composite step names a command that is a member of some group (command_groups is that
        # membership index), so a typo fails loudly here, not deep in the runner. `stop_on_failure` default False.
        known_commands = set(command_groups)
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
      - `groups` maps each declared group to its ordered command names (the single membership source);
      - every `env_groups` entry is a declared group;
      - no command appears in more than one group without a group-scoped spec per owner;
      - every command listed in a group has a spec, and every spec's command is in exactly one group
        (membership and specs agree, both ways);
      - every spec declares a non-empty `help` and a well-formed "module:function" `impl`;
      - every `composites` entry (#456) declares a non-empty `steps` list and every step names a command
        that exists in the manifest (a member of some group).
    Unknown top-level keys stay ignored (backward compatible). Any Pydantic ValidationError is re-raised as
    a plain ValueError (a raw ValidationError never escapes), then the validated model is converted into the
    public NamedTuples so callers see the unchanged types.
    """
    data = yaml.safe_load(text) or {}
    try:
        model = _ManifestModel.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_validation_message(exc)) from exc

    commands = {
        name: CommandSpec(impl=spec.impl, help=spec.help, passthrough_args=spec.passthrough_args)
        for name, spec in model.commands.items()
    }
    composites = {
        name: CompositeSpec(steps=spec.steps, stop_on_failure=spec.stop_on_failure)
        for name, spec in model.composites.items()
    }
    return Manifest(groups=model.groups, env_groups=frozenset(model.env_groups),
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
