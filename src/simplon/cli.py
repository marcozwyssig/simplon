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

import functools
import inspect
import os
import sys
from typing import Callable, Mapping, Protocol

import typer

from delivery import log, signatures
from delivery.context import ProductContext
from delivery.orchestrator import manifest
from delivery.orchestrator.product import StepFactoryContext, run_command
from delivery.taskgen import _docstring

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


def _rc(value: object) -> int:
    """A body's return value as a process exit code.

    `None` and an int are exit codes; ANYTHING ELSE IS IGNORED, deliberately differing from the generated
    module's stricter `_rc`, which raises there. The two are not serving the same contract: a generated
    module is rendered against bodies whose shape the product controls, while `assemble` binds whatever
    body an arbitrary product already wrote - and Click has always discarded those return values, so a
    body returning a log line or a result object is not a defect, it is a body written when the return
    value could not matter. Raising would turn a working CLI into a crashing one on upgrade.

    A bool is excluded on purpose: `return True` from such a body means success, and `int(True)` would
    exit 1.
    """
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _declaration(name: str, param, presentation) -> object:
    """One parameter's LIVE Typer declaration, or its plain default when the manifest describes none.

    The runtime twin of `signatures.option_decl`, which renders the same decision as SOURCE for the
    generated module. Both ask `signatures.shape` so they cannot disagree: a body is meant to behave
    identically under either mechanism, and until netctl#1444 it did not - `assemble` bound the raw body,
    so a framework-free one lost every help text, every short flag and the positional-ness of its
    arguments, silently turning `<product> commit some words` into `--message TEXT`.

    Undeclared means UNTOUCHED: the body's own default is returned as-is. That is what keeps a product
    whose bodies still carry `typer.Option(...)` defaults (infractl, biz-cockpit) assembling exactly as
    before - their defaults ARE those objects, and they pass through here unchanged.
    """
    form = signatures.shape(name, required=param.required, presentation=presentation)
    if not form.declared:
        return param.default
    kwargs: dict[str, object] = {}
    if getattr(presentation, "metavar", None):
        kwargs["metavar"] = presentation.metavar
    if presentation.help:
        kwargs["help"] = presentation.help
    default = ... if param.required else param.default
    if form.positional:
        return typer.Argument(default, **kwargs)
    return typer.Option(default, *form.decls, **kwargs)


def _bound(fn: Callable[..., object], spec: manifest.CommandSpec,
           *, where: str) -> Callable[..., object]:
    """`fn` as a Typer callback: the manifest's `params:` applied, its `with:` pinned, its return value
    coerced into the process exit code.

    The wrapper carries an explicit `__signature__` rather than `*args/**kwargs` because Typer derives the
    whole command line from it - every option, argument, default and annotation. A pinned parameter is
    absent from that signature and supplied at call time, which is what `with:` means: the manifest fixes
    it, so it is not on the command line at all (netctl#1442).
    """
    pinned = dict(spec.with_ or {})
    presentation = spec.params or {}
    params = signatures.bindable(fn)
    known = {p.name for p in params}
    unknown = sorted((set(pinned) | set(presentation)) - known)
    if unknown:
        raise ValueError(f"{where}: `with:`/`params:` name parameter(s) the impl does not take: "
                         f"{', '.join(unknown)}")

    sig = inspect.signature(fn)
    keep = [p for p in sig.parameters.values()
            if p.name not in pinned and not (p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD))]
    by_name = {p.name: p for p in params}
    new_params = [
        p.replace(default=_declaration(p.name, by_name[p.name], presentation.get(p.name)))
        if p.name in by_name else p
        for p in keep
    ]

    @functools.wraps(fn)
    def _wrapped(*args: object, **kwargs: object) -> None:
        raise typer.Exit(code=_rc(fn(*args, **{**kwargs, **pinned})))

    # `functools.wraps` copied `fn.__doc__` onto `_wrapped` unconditionally, which is the OLD rule (the
    # body's docstring always renders). The chain is now the same one `taskgen._docstring` renders into
    # the generated module: the manifest's resolved `help` (command, then task) wins, the body's
    # docstring is only the last resort - so this must run AFTER `wraps`, overwriting what it copied.
    _wrapped.__doc__ = _docstring(spec, fn)
    _wrapped.__signature__ = sig.replace(parameters=new_params)
    return _wrapped


def _command_callback(mf: manifest.Manifest, group: str, name: str, spec: manifest.CommandSpec,
                      step_context: StepFactoryContext | None) -> Callable[..., object]:
    """The Typer callback for one manifest command. A leaf resolves to its own impl callable, unchanged.
    An impl-less AGGREGATE (#895/#896) has no callable of its own, so the kernel synthesizes one: it
    expands the command through the dependency plan (`run_command`) and exits with the pipeline's rc via
    `typer.Exit`. The closure is GROUP-scoped, so an aggregate name owned by several groups still resolves
    its own plan (`test all` vs `deploy all`). Binding an aggregate requires the product's
    `StepFactoryContext` (the `step_context` kwarg on `assemble`); a manifest that declares an aggregate
    while the product supplied none fails loudly at ASSEMBLY time, not at first invocation. The spec's
    help becomes the closure's docstring, which Typer renders as the command help.

    A leaf's impl is WRAPPED rather than bound raw (netctl#1444). Click discards a callback's return
    value in standalone mode - only a raised `typer.Exit` sets the process exit code - so a
    framework-free body (`delivery.tasks.*`: plain parameters, `return rc`) bound directly here
    produced a CLI that always exited 0, however the body failed. The generated module has always
    coerced (`_rc` + `typer.Exit` in the template); this is the same coercion, so one body behaves
    identically under either mechanism. A body that raises `typer.Exit` itself never reaches the
    coercion, so the older style is untouched."""
    if spec.impl:
        return _bound(manifest.resolve_impl(spec), spec, where=f"{group} {name}")
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
    for group in _group_paths(mf, tax, skipped_groups):
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

    # A nested group hangs from its PARENT's sub-app under its LEAF name, not from the root under its
    # dotted path (netctl#1444). Registering `support.git` on the root produced one shell token literally
    # containing a dot - invokable only as `<product> support.git <cmd>`, which is not what any help text
    # here or in the generated module claims. `_group_paths` yields ancestors first, so a parent's sub-app
    # always exists by the time its child is attached.
    for group, ga in group_apps.items():
        parent, _, leaf = group.rpartition(".")
        target = group_apps[parent] if parent else app
        panel = cd_panel if tax.group_requires_env(group) else _CI_PANEL
        target.add_typer(ga, name=leaf, rich_help_panel=panel)

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


def _group_paths(mf: manifest.Manifest, tax, skipped: frozenset[str]) -> list[str]:
    """Every group that needs a sub-app, ANCESTORS FIRST.

    `groups:` names only the nodes that hold members, so a nested group's ancestors (`support` above
    `support.git`) can be declared in the `taxonomy:` block alone and still need a sub-app for their
    children to hang from. Ordering matters because a child is attached to its parent's app.

    A collapsed flat group is skipped: it has no sub-app, its single member is a top-level command. So is
    a group the product registered from its generated module. Mirrors `taskgen._group_paths`, which is
    what makes the two mechanisms produce the same tree.
    """
    out: list[str] = []
    for group in mf.groups:
        if group in skipped or tax.is_flat_command_group(group):
            continue
        parts = group.split(".")
        for depth in range(1, len(parts) + 1):
            path = ".".join(parts[:depth])
            if path not in out and path not in skipped:
                out.append(path)
    return out


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
