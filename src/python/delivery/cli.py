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
from delivery.orchestrator.product import StepFactoryContext, run_command

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


def _command_callback(mf: manifest.Manifest, group: str, name: str, spec: manifest.CommandSpec,
                      step_context: StepFactoryContext | None) -> Callable[..., object]:
    """The Typer callback for one manifest command. A leaf resolves to its own impl callable, unchanged.
    An impl-less AGGREGATE (#895/#896) has no callable of its own, so the kernel synthesizes one: it
    expands the command through the dependency plan (`run_command`) and exits with the pipeline's rc via
    `typer.Exit`. The closure is GROUP-scoped, so an aggregate name owned by several groups still resolves
    its own plan (`test all` vs `deploy all`). Binding an aggregate requires the product's
    `StepFactoryContext` (the `step_context` kwarg on `assemble`); a manifest that declares an aggregate
    while the product supplied none fails loudly at ASSEMBLY time, not at first invocation. The spec's
    help becomes the closure's docstring, which Typer renders as the command help."""
    if spec.impl:
        return manifest.resolve_impl(spec)
    if step_context is None:
        raise ValueError(f"command '{group}.{name}' is an impl-less aggregate; "
                         "assemble(step_context=...) is required to bind it")

    def _aggregate() -> None:
        raise typer.Exit(code=run_command(name, mf, step_context, group=group))

    _aggregate.__name__ = name.replace("-", "_")
    _aggregate.__doc__ = spec.help
    return _aggregate


def assemble(app: typer.Typer, mf: manifest.Manifest, *, product: str,
             step_context: StepFactoryContext | None = None,
             skip: frozenset[tuple[str, str]] = frozenset()) -> None:
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

    `skip` names (group, command) pairs a product has already registered from its GENERATED module
    (netctl#1444), so the two mechanisms can run side by side while the migration is under way. Whole
    GROUPS are skipped, never single commands within one: a group registers exactly one sub-app, so a
    group split across both mechanisms would have each of them call `add_typer` under the same name and
    one would overwrite the other's members. A partial group is rejected here rather than producing that
    silently.

    An impl-less AGGREGATE (#896) binds a kernel-synthesized callback that runs its #895 dependency plan
    (`run_command`) instead of a resolved impl; `step_context` injects the product's `StepFactoryContext`
    for that binding and is only required when the manifest declares aggregates. Registration behaviour is
    unchanged: an aggregate registers under its group plus the hidden flat alias unless its name is
    ambiguous, exactly like a leaf.

    Help normally comes from each callback's DOCSTRING. The one exception is an impl bound to several
    commands (netctl#1406: one kernel suite-runner callback backs every declared test level, identifying
    itself by the name it was invoked as): a shared function has one docstring, so all of them would render
    the same blurb. There the manifest's per-command `help:` is used instead, which is the product's own
    wording either way.

    A command whose spec declares `hidden: true` (netctl#1277) stays reachable exactly as above but is
    additionally hidden from ITS GROUP's listing (the flat alias has always been hidden, unconditionally):
    a plan step named by a `depends_on` entry must be a real manifest command, yet need not clutter `--help`
    meant for a human. See the loop below for how each registration shape threads the flag.
    """
    tax = mf.taxonomy()
    skipped_groups = _skipped_groups(mf, skip)
    cd_panel = _cd_panel(product)
    # impl refs bound to MORE than one command (see the help override in the registration loop below).
    seen: dict[str, int] = {}
    for specs in mf.commands.values():
        for spec in specs.values():
            if spec.impl:
                seen[spec.impl] = seen.get(spec.impl, 0) + 1
    shared_impls = {ref for ref, count in seen.items() if count > 1}

    # a sub-app per non-flat group, in manifest order (a collapsed flat group is skipped - no sub-app, so
    # no name collision with its same-named flat command). A group-default group (D4) is a sub-app too, but
    # its bare token runs the namesake member instead of printing group help.
    group_apps: dict[str, typer.Typer] = {}
    for group in mf.groups:
        if group in skipped_groups or tax.is_flat_command_group(group):
            continue
        env_first = tax.group_requires_env(group)
        if tax.is_group_default_command(group):
            ga = _group_default_app(mf.spec_for(group, group).help,
                                    _command_callback(mf, group, group, mf.spec_for(group, group),
                                                      step_context))
        else:
            # A nested group is named by its OWN segment and addressed by its PATH: `support.git` reads
            # "git commands." and is typed `<product> support git <cmd>`. Either spelled as the dotted
            # path would put a string on screen that nobody can type (netctl#1444, plan 5).
            label, addressed = group.rpartition(".")[2], group.replace(".", " ")
            ga = typer.Typer(add_completion=False, no_args_is_help=True,
                             help=(f"{label} commands. " + ("Env-first: `" + product + " <env> "
                                   + addressed + " <cmd>` (default dev)."
                                   if env_first else "Environment-agnostic (no env).")))
        group_apps[group] = ga
        app.add_typer(ga, name=group, rich_help_panel=(cd_panel if env_first else _CI_PANEL))

    # each command under its group + a HIDDEN flat alias (same callback); a collapsed flat group's member is
    # registered ONCE as a VISIBLE flat top-level command. The callback comes from the manifest impl
    # (spec_for: the group-scoped declaration wins, #519). A name owned by SEVERAL groups gets NO flat
    # alias - it is addressable only via its group token (`test all` vs `<env> deploy all`), so a bare
    # ambiguous token fails as unknown instead of silently picking a group. In a group-default group the
    # namesake member is the sub-app's DEFAULT action (registered on its callback above), so it is neither a
    # subcommand nor a separate top-level flat command - only its siblings register here.
    #
    # `spec.hidden` (netctl#1277) is threaded through per registration SHAPE, deliberately, because each
    # shape means something different for "absent from --help while still invocable":
    #   - a collapsed flat single-member group has exactly ONE registration (its group IS the command), so
    #     `hidden` there hides that one and only top-level entry;
    #   - an ordinary grouped command has TWO registrations, and only the GROUP one changes: the flat alias
    #     has always been hidden (the #147 back-compat pattern, unconditional), so a hidden command simply
    #     stops being the one exception that was visible somewhere;
    #   - a group-default namesake never reaches this loop (the `continue` above) and `load()` already
    #     rejects `hidden` there, so there is nothing to thread for it here.
    for group, cmds in mf.groups.items():
        if group in skipped_groups:
            continue
        panel = cd_panel if tax.group_requires_env(group) else _CI_PANEL
        default_member = tax.is_group_default_command(group)
        for name in cmds:
            if default_member and name == group:
                continue
            spec = mf.spec_for(group, name)
            fn = _command_callback(mf, group, name, spec, step_context)
            kw = {"context_settings": _PASSTHROUGH_CTX} if spec.passthrough_args else {}
            if spec.impl in shared_impls:
                # A callback several commands share cannot carry per-command help in its docstring, which
                # is where Typer otherwise reads it from - all of them would render the same blurb. The
                # manifest's `help:` is the canonical short summary and is per command, so it wins here
                # (netctl#1406, where one kernel suite-runner callback backs every declared test level).
                kw["help"] = spec.help
            if tax.is_flat_command_group(group):
                app.command(name=name, rich_help_panel=panel, hidden=spec.hidden, **kw)(fn)
            else:
                group_apps[group].command(name=name, hidden=spec.hidden, **kw)(fn)
                if not tax.is_ambiguous(name):
                    app.command(name=name, hidden=True, **kw)(fn)


def _skipped_groups(mf: manifest.Manifest, skip: frozenset[tuple[str, str]]) -> frozenset[str]:
    """The groups `skip` covers ENTIRELY, or a ValueError naming the ones it covers only in part.

    Half a group is the failure this exists to prevent: both mechanisms would register a sub-app under
    the same name and Click keeps one of them, so the other's members vanish from the surface with
    nothing raised. Rejecting is cheap; diagnosing that is not.
    """
    named = {group for group, _ in skip}
    partial = sorted(group for group in named
                     if set(mf.groups.get(group, ())) - {n for g, n in skip if g == group})
    if partial:
        raise ValueError(
            f"skip covers group(s) {', '.join(partial)} only in part; a group registers ONE sub-app, so "
            f"it belongs entirely to the generated module or entirely to this assembly")
    unknown = sorted(named - set(mf.groups))
    if unknown:
        raise ValueError(f"skip names group(s) the manifest does not declare: {', '.join(unknown)}")
    return frozenset(named)


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
