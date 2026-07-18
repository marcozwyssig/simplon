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
"""
from __future__ import annotations

import importlib
from typing import Callable, NamedTuple

import yaml

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


def load(text: str) -> Manifest:
    """Parse a product manifest YAML into a validated Manifest (pure: no import of the impls, no Typer).

    Validates, failing loudly with ValueError so a bad manifest is caught here and not deep in the CLI:
      - `groups` maps each declared group to its ordered command names (the single membership source);
      - every `env_groups` entry is a declared group;
      - no command appears in more than one group;
      - every command listed in a group has a spec, and every spec's command is in exactly one group
        (membership and specs agree, both ways);
      - every spec declares a non-empty `help` and a well-formed "module:function" `impl`;
      - every `composites` entry (#456) declares a non-empty `steps` list and every step names a command
        that exists in the manifest (a member of some group).
    Unknown top-level keys stay ignored (backward compatible). Mirrors the style of
    delivery.environments.parse.
    """
    data = yaml.safe_load(text) or {}

    raw_groups = data.get("groups") or {}
    if not raw_groups:
        raise ValueError("manifest defines no groups")
    groups: dict[str, tuple[str, ...]] = {
        str(name): tuple(str(m) for m in (members or ())) for name, members in raw_groups.items()
    }

    # env_groups: every entry must name a declared group.
    env_groups_names = [str(g) for g in (data.get("env_groups") or ())]
    for g in env_groups_names:
        if g not in groups:
            raise ValueError(f"env_groups entry '{g}' is not a declared group")
    env_groups = frozenset(env_groups_names)

    # multi-owner reverse index: the SAME name may live in several groups (#519), in which case every
    # owner must declare a group-scoped spec (validated below) and the name loses its flat form.
    command_groups: dict[str, list[str]] = {}
    for group, members in groups.items():
        for cmd in members:
            command_groups.setdefault(cmd, []).append(group)

    raw_commands = data.get("commands") or {}
    commands: dict[str, CommandSpec] = {}
    for name, spec in raw_commands.items():
        name = str(name)
        spec = spec or {}
        impl = str(spec.get("impl", "")).strip()
        if not impl:
            raise ValueError(f"command '{name}': missing impl")
        _split_impl(impl, f"command '{name}'")   # validates the "module:function" shape
        help_text = str(spec.get("help", "")).strip()
        if not help_text:
            raise ValueError(f"command '{name}': missing help")
        commands[name] = CommandSpec(impl=impl, help=help_text,
                                     passthrough_args=bool(spec.get("passthrough_args", False)))

    # membership and specs must agree, both ways. A spec key is either a plain command name or a
    # group-scoped `<group>.<name>` (#519); a name owned by SEVERAL groups must be declared scoped
    # per owner (a lone plain spec would be ambiguous), and every scoped key must point at a real
    # member of that group.
    missing_spec = sorted(
        c for c, owners in command_groups.items()
        if any(c not in commands and f"{g}.{c}" not in commands for g in owners))
    if missing_spec:
        raise ValueError(f"commands declared in a group but missing a spec: {missing_spec}")
    ambiguous_plain = sorted(
        c for c, owners in command_groups.items()
        if len(owners) > 1 and any(f"{g}.{c}" not in commands for g in owners))
    if ambiguous_plain:
        raise ValueError(
            f"commands owned by several groups need a group-scoped spec per owner "
            f"('<group>.<name>'): {ambiguous_plain}")
    orphans: list[str] = []
    for key in commands:
        group, sep, name = key.partition(".")
        if sep and group in groups:
            if name not in groups[group]:
                raise ValueError(f"scoped spec '{key}': '{name}' is not a member of group '{group}'")
        elif key not in command_groups:
            orphans.append(key)
    if orphans:
        raise ValueError(f"commands with a spec but not in any declared group: {sorted(orphans)}")

    # composites (#456): a named, ordered pipeline of existing commands. Every step must name a command
    # that is a member of some group (command_groups is that membership index, built above), so a typo or a
    # renamed command fails loudly here, not deep in the runner. `stop_on_failure` defaults to False.
    known_commands = set(command_groups)
    raw_composites = data.get("composites") or {}
    composites: dict[str, CompositeSpec] = {}
    for name, spec in raw_composites.items():
        name = str(name)
        spec = spec or {}
        steps = tuple(str(s) for s in (spec.get("steps") or ()))
        if not steps:
            raise ValueError(f"composite '{name}': needs a non-empty 'steps' list")
        for step in steps:
            if step not in known_commands:
                raise ValueError(
                    f"composite '{name}': step '{step}' is not a command in the manifest")
        composites[name] = CompositeSpec(
            steps=steps, stop_on_failure=bool(spec.get("stop_on_failure", False)))

    return Manifest(groups=groups, env_groups=env_groups, commands=commands, composites=composites)


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
