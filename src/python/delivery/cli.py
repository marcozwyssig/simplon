"""Typer binding layer for the manifest-driven CLI (netctl#592 Train D).

The framework-free engine (delivery.orchestrator.manifest + delivery.clitaxonomy + delivery.environments)
stays Typer-free on purpose - it parses, validates and decides, but binds to no CLI framework. THIS is the
one delivery module that imports Typer: it turns a validated Manifest into a Typer app (`assemble`) and
runs the env-first dispatch (`main`). Both are product-AGNOSTIC - the product name, its environments and
its command aliases all flow IN as parameters, never hardcoded here - so a second consumer (infractl)
inherits the CLI assembly for free ("gleiche Maschine, anderer Katalog").

Product responsibilities that stay OUTSIDE this module:
  - creating the ROOT Typer app (its help blurb is the product's voice) and registering any product-only
    internal commands on it via `@app.command`, THEN calling `assemble(app, manifest, product=...)`;
  - shipping the command impl callables the manifest's `module:function` refs resolve to;
  - providing the environments module (backend names, the ENV var, the deployment gate) injected into
    `main(environments=...)` and the alias map injected into `main(aliases=...)`.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Mapping, Protocol

import typer

from delivery import log
from delivery.context import ProductContext
from delivery.orchestrator import manifest

# The passthrough context settings: a passthrough command forwards unrecognised trailing args to its
# underlying tool (e.g. accept -> pytest). The manifest declares the intent (passthrough_args); this maps
# it to Typer's context settings - a generic mechanism, product-neutral.
_PASSTHROUGH_CTX = {"allow_extra_args": True, "ignore_unknown_options": True}

# Rich help panels group the top-level commands in `--help`. The CI panel is fully generic; the CD panel
# names the product token so the usage hint reads in the product's own voice (netctl / infractl), built
# from the product name passed into `assemble` rather than hardcoded here.
_CI_PANEL = "CI / agnostic (no env)"


def _cd_panel(product: str) -> str:
    return f"CD / env-first ({product} <env> <group> <cmd>, default dev)"


class EnvironmentProvider(Protocol):
    """The environments seam `main` needs from the product (netctl's `orchestrator.environments`, or
    infractl's equivalent). Structural: any module/object exposing these members satisfies it, so nothing
    named is imported here - the coupling flows product -> kernel, never the reverse.

    ``ENV_VAR`` is the process env var the active environment rides in; ``LOCAL`` is the backend name a CD
    command gates on. ``names``/``default`` drive env-first token selection; ``is_local``/``require_backend``
    drive the env-gate for a CD group.
    """

    ENV_VAR: str
    LOCAL: str

    def names(self) -> list[str]: ...
    def default(self) -> str: ...
    def is_local(self, name: str | None = ...) -> bool: ...
    def require_backend(self, backend: str = ...) -> None: ...


def _group_default_app(help_text: str, default_fn: Callable[..., object]) -> typer.Typer:
    """A sub-app whose bare token runs `default_fn` as the group's DEFAULT action (#592 D4). Used for a
    group whose name equals one of its (several) members: `<product> build` runs the build pipeline while
    `<product> build diff` still dispatches the `diff` sibling and `<product> build --help` lists them.

    Implemented with Typer's invoke-without-command callback: with no subcommand Click invokes the callback
    (which runs the namesake member), a subcommand short-circuits it, and `--help` renders the group listing
    before the callback runs. The namesake member is parameterless in this role (its bare token takes no
    args); a namesake needing options would declare them on this callback, out of scope here."""
    ga = typer.Typer(add_completion=False, invoke_without_command=True, no_args_is_help=False,
                     help=help_text)

    @ga.callback(invoke_without_command=True)
    def _default(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            default_fn()

    return ga


def assemble(app: typer.Typer, mf: manifest.Manifest, *, product: str) -> None:
    """Assemble a product's Typer app from its loaded manifest (#437). One sub-app per non-flat group
    (rich-panelled CI vs CD); each command is registered under its group AND again as a HIDDEN flat
    back-compat alias bound to the SAME callback, so `<product> <env> deploy up` and the bare `<product> up`
    dispatch identically (the #147 pattern, extended to the full taxonomy). A single-member flat group
    (#424: `package`) has no sub-app - its member is registered ONCE as a VISIBLE flat top-level command, so
    a bare `<product> package` runs the pipeline instead of printing group help. A MULTI-member group whose
    name equals one of its members (#592 D4: `build` = build/diff/docs) becomes a sub-app whose bare token
    runs that namesake member as the DEFAULT action (so `<product> build` still runs the pipeline) while its
    siblings register as subcommands (`<product> build diff`) plus their hidden flat aliases (`<product>
    diff`). Env-first vs agnostic panelling comes from the shared taxonomy; each callback is resolved from
    its manifest impl ("module:function"). Per-command `--help` is unchanged: help stays with each callback's
    docstring, which Typer renders. The product name only shapes the usage hints (panel + group help), so a
    second product reads in its own voice.
    """
    tax = mf.taxonomy()
    cd_panel = _cd_panel(product)

    # a sub-app per non-flat group, in manifest order (a collapsed flat group is skipped - no sub-app, so
    # no name collision with its same-named flat command). A group-default group (D4) is a sub-app too, but
    # its bare token runs the namesake member instead of printing group help.
    group_apps: dict[str, typer.Typer] = {}
    for group in mf.groups:
        if tax.is_flat_command_group(group):
            continue
        env_first = tax.group_requires_env(group)
        if tax.is_group_default_command(group):
            ga = _group_default_app(mf.spec_for(group, group).help,
                                    manifest.resolve_impl(mf.spec_for(group, group)))
        else:
            ga = typer.Typer(add_completion=False, no_args_is_help=True,
                             help=(f"{group} commands. " + ("Env-first: `" + product + " <env> " + group
                                   + " <cmd>` (default dev)." if env_first else "Environment-agnostic (no env).")))
        group_apps[group] = ga
        app.add_typer(ga, name=group, rich_help_panel=(cd_panel if env_first else _CI_PANEL))

    # each command under its group + a HIDDEN flat alias (same callback); a collapsed flat group's member is
    # registered ONCE as a VISIBLE flat top-level command. The callback comes from the manifest impl
    # (spec_for: the group-scoped declaration wins, #519). A name owned by SEVERAL groups gets NO flat
    # alias - it is addressable only via its group token (`test all` vs `<env> deploy all`), so a bare
    # ambiguous token fails as unknown instead of silently picking a group. In a group-default group the
    # namesake member is the sub-app's DEFAULT action (registered on its callback above), so it is neither a
    # subcommand nor a separate top-level flat command - only its siblings register here.
    for group, cmds in mf.groups.items():
        panel = cd_panel if tax.group_requires_env(group) else _CI_PANEL
        default_member = tax.is_group_default_command(group)
        for name in cmds:
            if default_member and name == group:
                continue
            spec = mf.spec_for(group, name)
            fn = manifest.resolve_impl(spec)
            kw = {"context_settings": _PASSTHROUGH_CTX} if spec.passthrough_args else {}
            if tax.is_flat_command_group(group):
                app.command(name=name, rich_help_panel=panel, **kw)(fn)
            else:
                group_apps[group].command(name=name, **kw)(fn)
                if not tax.is_ambiguous(name):
                    app.command(name=name, hidden=True, **kw)(fn)


def main(*, app: typer.Typer, context: ProductContext,
         environments: EnvironmentProvider, aliases: Mapping[str, str]) -> None:
    """Env-first dispatch for an assembled product app. Consumes a leading `dev|test|uat|prod` env token,
    applies the product's command aliases + the `help` -> `--help` shim, runs the env-gate off the manifest
    taxonomy, then hands control to Typer. Everything product-specific is injected: `app` is the assembled
    root app (with any product-only internal commands already on it), `context` yields the manifest/taxonomy,
    `environments` is the product's environments module, and `aliases` is its back-compat alias map.

    The engine hardcodes no product name, no env list and no alias table; that is why a second product runs
    the same dispatcher unchanged.
    """
    taxonomy = context.manifest().taxonomy()

    # Environment-first selection (#15): a leading `dev|test|uat|prod` token picks the target
    # environment and is consumed here; with none, the descriptor default (dev) applies. So Typer only
    # ever sees `<command> ...`, and `<product> up` == `<product> dev up`.
    env = environments.default()
    # capture whether an env was given EXPLICITLY before consuming it, so an agnostic group can reject it.
    # A leading token that names a GROUP is the command layer, never an env token - this resolves the one
    # env/group name collision (`test` is BOTH the exoscale env and the CI gate group): `netctl test unit`
    # dispatches the test GROUP, not env=test, so the whole taxonomy stays reachable. No runnable capability
    # is lost: env `test` is an unimplemented exoscale #11 stub that already dies at the backend gate.
    env_explicit = (len(sys.argv) >= 2 and sys.argv[1] in environments.names()
                    and sys.argv[1] not in taxonomy.groups)
    if env_explicit:
        env = sys.argv.pop(1)
    os.environ[environments.ENV_VAR] = env

    # Preserve the bash dispatcher's UX: `<product> help` -> Typer help, and the command aliases.
    if len(sys.argv) >= 2:
        if sys.argv[1] == "help":
            sys.argv[1] = "--help"
        elif sys.argv[1] in aliases:
            sys.argv[1] = aliases[sys.argv[1]]

    # The env-gate reads the command's GROUP (from the manifest taxonomy): an agnostic group rejects an
    # explicit env; a CD group (deploy/operate/monitor) gates on the active backend so a non-local target
    # fails clean (#11) instead of mis-running the local containerlab path. `--help` is informational -> passes.
    cmd = sys.argv[1] if len(sys.argv) >= 2 else None
    asking_help = "--help" in sys.argv or "-h" in sys.argv
    verdict = taxonomy.env_verdict(cmd, env_explicit)
    if verdict == "reject-env" and not asking_help:
        log.die(f"'{cmd}' is environment-agnostic and takes no env prefix; run '{context.name} {cmd}'")
    if verdict == "gate-backend" and not asking_help and not environments.is_local(env):
        environments.require_backend(environments.LOCAL)

    app()
