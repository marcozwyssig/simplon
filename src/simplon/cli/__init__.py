"""Typer binding layer for the manifest-driven CLI (netctl#592 Train D).

The framework-free engine (simplon.manifest.load + simplon.manifest.clitaxonomy + simplon.manifest.environments)
stays Typer-free on purpose - it parses, validates and decides, but binds to no CLI framework. THIS is the
one delivery module that imports Typer: it turns a validated Manifest into a Typer app (`assemble`) and
runs the env-first dispatch (`main`). Both are product-AGNOSTIC - the product name, its environments and
its command aliases all flow IN as parameters, never hardcoded here - so a product inherits the CLI
assembly for free ("gleiche Maschine, anderer Katalog"). Measured rather than hoped for (#51): every
product in `simplon.cli.surface.CONSUMERS` assembles its CLI here, each from its own `orchestrator/cli.py`,
and so does the kernel's own orchestrator.

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
import contextlib
import os
import sys
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Protocol, TypedDict, cast

import typer

import simplon
from simplon.manifest import bound, clitaxonomy, outputs, signatures
from simplon.adapters import labinstance
from simplon.kernel import log, runhost
from simplon.manifest.context import ENVIRONMENT_ENV, ProductContext, environment_name, launcher
from simplon.manifest import launcherenv, load as manifest, results
from simplon.model import task
from simplon.model.command import AggregateCommand, Command, TaskCommand
from simplon.kernel.product import StepFactoryContext, run_command
from simplon.kernel.steps import NO_TUI_ENV, Pipeline
from simplon.kernel.provenance import provenance_line
from simplon.tasks.taskgen import _docstring

# The passthrough context settings: a passthrough command forwards unrecognised trailing args to its
# underlying tool (e.g. accept -> pytest). The manifest declares the intent (passthrough_args); this maps
# it to Typer's context settings - a generic mechanism, product-neutral.
_PASSTHROUGH_CTX = {"allow_extra_args": True, "ignore_unknown_options": True}


class _Introspectable(Protocol):
    """A callable that carries the two attributes Typer reads a command's surface from.

    `inspect.signature()` honours a `__signature__` attribute on any callable, and Typer builds every
    option, argument, default and annotation from what `inspect` answers - so for `_bound`'s wrapper that
    attribute IS the command line, not a decoration on it. Typeshed models neither it nor a writable
    `__doc__` on `functools.wraps`' `_Wrapped`, so this names the contract the wrapper actually has.
    """

    __doc__: str | None
    __signature__: inspect.Signature

    def __call__(self, *args: object, **kwargs: object) -> None: ...


class _DeclKwargs(TypedDict, total=False):
    """The Typer keyword arguments `_declaration` may build, spelled out rather than left as a bag.

    `total=False` is the point: each key is present only when the manifest declared it, which is what
    "undeclared means untouched" means one function down. A plain `dict[str, object]` cannot be splatted
    into `typer.Argument`/`typer.Option` at all - their parameters are heterogeneous, so no single value
    type fits them - and naming the two keys costs less than the `Any` that would otherwise buy silence.
    """
    metavar: str
    help: str


class _CommandKwargs(TypedDict, total=False):
    """The per-registration keyword arguments `assemble` may add to `Typer.command()`.

    Same shape, same reason. `help` is here because a callback shared by several commands cannot carry
    per-command help in its docstring; `context_settings` because a passthrough command needs Click's
    two flags. Both are optional and independent, which is exactly what `total=False` says.
    """
    context_settings: dict[str, bool]
    help: str

# Rich help panels group the top-level commands in `--help`. The CI panel is fully generic; the CD panel
# names the product token so the usage hint reads in the product's own voice, built from the product name
# passed into `assemble` rather than hardcoded here.
_CI_PANEL = "CI / agnostic (no env)"


def _cd_panel(product: str) -> str:
    return f"CD / env-first ({product} <env> <group> <cmd>, default dev)"


class EnvironmentProvider(Protocol):
    """The environments seam `main` needs from the product - `orchestrator/environments.py` in every
    consumer measured (#51). Structural: any module/object exposing these members satisfies it, so nothing
    named is imported here - the coupling flows product -> kernel, never the reverse.

    ``ENV_VAR`` is the process env var the active environment rides in; ``LOCAL`` is the backend name a
    product's own body gates on when it only works against one. ``names``/``default`` drive env-first
    token selection.

    NO BACKEND GATE IS DRIVEN FROM HERE ANY MORE (si#298). `main` used to ask this object whether the
    active backend could be driven, for every command in an env-first group - and measured over this
    family, five of eight products have only their OWN commands in those groups, which the kernel does
    not dispatch and has no registry for. The question belonged to the one place the kernel resolves a
    backend to an instance, and that is `tasks.deploy`. ``is_local`` and ``require_backend`` stay on this
    protocol because a product's own body still calls them when it works against one backend only.
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
    whose bodies still carry `typer.Option(...)` defaults assembling exactly as before - their defaults
    ARE those objects, and they pass through here unchanged. Two do today, measured (#51): biz-cockpit
    (three such parameters) and netctl (two).
    """
    form = signatures.shape(name, required=param.required, presentation=presentation)
    if not form.declared:
        return param.default
    kwargs: _DeclKwargs = {}
    if getattr(presentation, "metavar", None):
        kwargs["metavar"] = presentation.metavar
    if presentation.help:
        kwargs["help"] = presentation.help
    default = ... if param.required else param.default
    if form.positional:
        return typer.Argument(default, **kwargs)
    return typer.Option(default, *form.decls, **kwargs)


def _annotation(param: signatures.Parameter) -> object:
    """The annotation Typer may see for `param` - the body's own, or NOTHING where the kernel cannot
    render it (si#105).

    The generated module has always dropped such an annotation: `signatures.annotation` answers None for
    anything outside the narrow set it may write into source, and `option_decl` then emits a bare
    `name=default`. `assemble` handed Typer the raw annotation instead, and the two mechanisms therefore
    did not agree - which is the one thing this pair is written not to do. The disagreement is not
    cosmetic: Typer raises `RuntimeError: Type not yet supported: dict[str, str]` while BUILDING the
    command, so a body with a mapping parameter that a command leaves unpinned assembled into a CLI that
    could not be constructed at all, while the same body in a generated module worked.

    An unrenderable parameter is not lost - `with:` still binds it, which is how such a parameter is
    meant to be supplied. Left on the command line it renders exactly as the generated module renders
    it, as a text option, and the body's own validation refuses whatever text a caller puts there.
    """
    return param.annotation if signatures.annotation(param) is not None else inspect.Parameter.empty


def _bound(fn: Callable[..., object], spec: TaskCommand,
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
    stripped = {p.name for p in keep
                if p.name in by_name and _annotation(by_name[p.name]) is inspect.Parameter.empty
                and p.annotation is not inspect.Parameter.empty}
    new_params = [
        p.replace(annotation=_annotation(by_name[p.name]),
                  default=_declaration(p.name, by_name[p.name], presentation.get(p.name)))
        if p.name in by_name else p
        for p in keep
    ]

    # si#344 C.3: a command bound to produce a test result fails when its body exits 0 without writing it
    # (`simplon.manifest.results`) - the same check the generated module wraps its call in.
    produced = tuple(a for names in (spec.produces or {}).values() for a in names)
    # si#434: a command bound to evidence runs its body only when every record it is bound to is green,
    # and si#439: the body learns what those records ran (`results.tested`).
    evidence = results.evidence_of(spec)
    # si#553: the names bound to a list port (no `param`) reach the body through `bound.names`.
    listed = bound.of(spec)

    @functools.wraps(fn)
    def _wrapped(*args: object, **kwargs: object) -> None:
        def body() -> int:
            if not produced:
                return _rc(fn(*args, **{**kwargs, **pinned}))
            snapshot = results.before(produced)
            return results.held(snapshot, _rc(fn(*args, **{**kwargs, **pinned})))
        run = (lambda: results.guarded(evidence, body)) if evidence else body
        raise typer.Exit(code=bound.within(listed, run) if listed else run())

    # `_Introspectable` rather than a bare assignment, because `__signature__` is a CPython protocol that
    # the type system does not model: `inspect.signature()` reads it off ANY callable that carries it, and
    # that is the entire reason this wrapper works - Typer derives the command line from what `inspect`
    # answers, not from the wrapper's real `*args/**kwargs`. Typeshed types `functools.wraps`' result as
    # `_Wrapped`, which declares no such attribute, so the assignment below has to be made against a type
    # that states the protocol instead of against one that merely tolerates it.
    #
    # `functools.wraps` copied `fn.__doc__` onto `_wrapped` unconditionally, which is the OLD rule (the
    # body's docstring always renders). The chain is now the same one `taskgen._docstring` renders into
    # the generated module: the manifest's resolved `help` (command, then task) wins, the body's
    # docstring is only the last resort - so this must run AFTER `wraps`, overwriting what it copied.
    callback = cast(_Introspectable, _wrapped)
    callback.__doc__ = _docstring(spec, fn)
    callback.__signature__ = sig.replace(parameters=new_params)
    # `__annotations__` has to be corrected TOO, not just the signature (si#105). Typer reads a
    # parameter's type from `get_type_hints()` and only falls back to the signature, and
    # `functools.wraps` copied the body's whole annotation dict onto this wrapper - so an annotation
    # dropped from the signature above came straight back in through that door and Typer raised on it
    # anyway. Only the dropped names are removed; every other annotation, the return one included, is
    # left exactly as `wraps` copied it.
    if stripped:
        callback.__annotations__ = {name: ann for name, ann in callback.__annotations__.items()
                                    if name not in stripped}
    return callback


def _command_callback(mf: manifest.Manifest, group: str, name: str, spec: Command,
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
    framework-free body (`simplon.tasks.*`: plain parameters, `return rc`) bound directly here
    produced a CLI that always exited 0, however the body failed. The generated module has always
    coerced (`_rc` + `typer.Exit` in the template); this is the same coercion, so one body behaves
    identically under either mechanism. A body that raises `typer.Exit` itself never reaches the
    coercion, so the older style is untouched."""
    if isinstance(spec, TaskCommand):
        return _bound(manifest.resolve_impl(spec), spec, where=f"{group} {name}")
    if step_context is None:
        raise ValueError(f"command '{group}.{name}' is an impl-less aggregate; "
                         "assemble(step_context=...) is required to bind it")

    if isinstance(spec, AggregateCommand) and spec.passes:
        return _passing_aggregate(mf, group, name, spec, step_context)

    def _aggregate() -> None:
        raise typer.Exit(code=run_command(name, mf, step_context, group=group))

    _aggregate.__name__ = name.replace("-", "_")
    _aggregate.__doc__ = spec.help
    return _aggregate


class Receiver(NamedTuple):
    """One planned leaf that takes a value its aggregate passes (si#433), and how ITS command line spells it."""
    leaf: str
    positional: bool
    flag: str
    required: bool
    help: str | None


def receivers(mf: manifest.Manifest, group: str, name: str,
              spec: AggregateCommand) -> dict[str, list[Receiver]]:
    """For each parameter aggregate `group name` passes (si#433): the planned leaves that take it
    UNPINNED, in plan order, each with the form ITS OWN command line gives that parameter.

    The form is the leaf's, not the aggregate's, because the value lands on the leaf's command line:
    `release:tag`'s `tag` is required and so a POSITIONAL, `release:notes`' has a default and so is
    `--tag`. It is decided by `signatures.shape`, the one decision both CLI mechanisms already share.

    Refuses, naming the aggregate: a passed name no planned leaf takes unpinned (the declaration would
    reach nobody - the failure `passes:` exists to end), a FLAG (a value with no text form to hand on),
    and a body whose default is a Typer object (its spelling lives in that object, not in the manifest).
    """
    where = f"{group} {name}"
    tree = mf.plan_tree_for(name, group=group)
    out: dict[str, list[Receiver]] = {passed: [] for passed in spec.passes}
    for leaf in tree.leaves():
        leaf_spec = cast(TaskCommand, leaf.spec)
        params = signatures.bindable(manifest.resolve_impl(leaf_spec))
        for param in params:
            if param.name not in out or param.name in (leaf_spec.with_ or {}):
                continue
            if param.annotation in (bool, "bool") or isinstance(param.default, bool):
                raise ValueError(f"{where}: passes `{param.name}`, which `{leaf.path}` takes as a flag - "
                                 f"`passes:` hands on a value, and a flag has none to hand")
            if isinstance(param.default, (typer.models.OptionInfo, typer.models.ArgumentInfo)):
                raise ValueError(f"{where}: passes `{param.name}`, whose spelling `{leaf.path}` declares in "
                                 f"a Typer default - declare it under the command's `params:` instead")
            presentation = (leaf_spec.params or {}).get(param.name)
            form = signatures.shape(param.name, required=param.required, presentation=presentation)
            positional = signatures.positional(param, presentation)
            flag = form.decls[0] if form.decls else f"--{param.name.replace('_', '-')}"
            out[param.name].append(Receiver(leaf.name, positional, flag, param.required,
                                            getattr(presentation, "help", None)))
    for passed, takers in out.items():
        if not takers:
            raise ValueError(f"{where}: passes `{passed}`, but no leaf it plans takes it unpinned - "
                             f"planned are {', '.join(leaf.path for leaf in tree.leaves())}")
    return out


def leaf_arguments(takers: Mapping[str, list[Receiver]],
                   values: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    """The arguments each leaf's command line gets for `values` (si#433): options as `--flag=value`,
    which cannot be misread whatever the value starts with, then positionals after a `--`, in the order
    the leaf's body declares them. A value left unset (None) is handed to nobody."""
    options: dict[str, list[str]] = {}
    positionals: dict[str, list[str]] = {}
    for passed, receivers_of in takers.items():
        value = values.get(passed)
        if value is None:
            continue
        for taker in receivers_of:
            if taker.positional:
                positionals.setdefault(taker.leaf, []).append(str(value))
            else:
                options.setdefault(taker.leaf, []).append(f"{taker.flag}={value}")
    return {leaf: signatures.command_line(options.get(leaf, []), positionals.get(leaf, []))
            for leaf in {*options, *positionals}}


def _passing_aggregate(mf: manifest.Manifest, group: str, name: str, spec: AggregateCommand,
                       step_context: StepFactoryContext) -> Callable[..., object]:
    """An aggregate's callback with one OPTION per name it `passes:` (si#433), handed on to its leaves.

    Required where any receiving leaf requires it: `release all` without `--tag` is refused by the
    command line before a leaf runs, rather than stopping at its first leaf with "which release?". Where
    every receiver has a default the option defaults to None, and None is handed to nobody - each leaf
    then keeps its own default rather than one the aggregate invented.
    """
    takers = receivers(mf, group, name, spec)
    params = []
    for passed, receivers_of in takers.items():
        required = any(t.required for t in receivers_of)
        shown = next((t.help for t in receivers_of if t.help), None) or \
            f"Handed to {', '.join(t.leaf for t in receivers_of)}."
        params.append(inspect.Parameter(
            passed, inspect.Parameter.KEYWORD_ONLY,
            default=typer.Option(... if required else None, f"--{passed.replace('_', '-')}", help=shown,
                                 show_default=not required),
            annotation=str if required else (str | None)))

    def _aggregate(**values: object) -> None:
        raise typer.Exit(code=run_command(name, mf, step_context, group=group,
                                          leaf_args=leaf_arguments(takers, values)))

    _aggregate.__name__ = name.replace("-", "_")
    callback = cast(_Introspectable, _aggregate)
    callback.__doc__ = spec.help
    callback.__signature__ = inspect.Signature(params)
    return callback


# `provenance_line`, which simplon is answering (si#125), lives in `simplon.kernel.provenance` (si#391): the run
# transcript's header asks the same question, and the kernel may not import the cli.


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

    The assembled ROOT app also gets the si#125 provenance line in its epilog - which simplon assembled
    this CLI, and from where - appended below any epilog the product declared. Group sub-apps do not get
    it; see `provenance_line` above for the wording and for what each half says when it cannot be resolved.

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
            if isinstance(spec, TaskCommand):
                # by body, not by spelling: a coordinate names its class, a product task the function (si#400 4c)
                seen[task.body_identity(spec.impl)] = seen.get(task.body_identity(spec.impl), 0) + 1
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
            # The node's DECLARED `help:` where it has one, the synthesized "<label> commands." where it
            # has not, plus the addressing hint either way - `clitaxonomy.group_help`, which the generated
            # module renders through as well so the two mechanisms cannot drift (si#75).
            node = tax.resolve_path(group)
            ga = typer.Typer(add_completion=False, no_args_is_help=True,
                             help=clitaxonomy.group_help(group, product, env_first=env_first,
                                                         declared=node.help if node else ""))
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
            kw: _CommandKwargs = ({"context_settings": _PASSTHROUGH_CTX}
                                  if isinstance(spec, TaskCommand) and spec.passthrough_args else {})
            if isinstance(spec, TaskCommand) and task.body_identity(spec.impl) in shared_impls:
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

    # The provenance line, on the ROOT app only (si#125). Twenty group screens repeating it would be
    # noise, and the top level is where a reader looks for it. The epilog is the PRODUCT's slot, so a
    # product that wrote one keeps it and the kernel's line goes below: adopting a new kernel must not
    # silently delete a line somebody wrote on purpose.
    declared = app.info.epilog
    declared = declared.strip() if isinstance(declared, str) else ""
    # The console-mode line (si#517) goes between them: `--no-tui` is stripped before Click sees the
    # argv, so Click lists it nowhere, and a person who wanted it asked for it as a new feature.
    lines = [declared] if declared else []
    app.info.epilog = "\n\n".join([*lines, NO_TUI_LINE, provenance_line()])


def _group_paths(mf: manifest.Manifest, tax, skipped: frozenset[str]) -> list[str]:
    """Every group that needs a sub-app, ANCESTORS FIRST.

    `groups:` names only the nodes that hold members, so a nested group's ancestors (`support` above
    `support.git`) can be declared in the `taxonomy:` block alone and still need a sub-app for their
    children to hang from. Ordering matters because a child is attached to its parent's app.

    A collapsed flat group is skipped: it has no sub-app, its single member is a top-level command. So is
    a group the product registered from its generated module.

    The ancestor walk itself is `clitaxonomy.group_paths` (si#58), which `simplon.tasks.taskgen` and
    `simplon.tasks.completiongen` also call - what used to be this docstring's "mirrors taskgen._group_paths"
    is now one function rather than a promise about two.
    """
    return clitaxonomy.group_paths(
        (group for group in mf.groups if group not in skipped and not tax.is_flat_command_group(group)),
        exclude=skipped)


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


#: Set by the launcher right after it refreshed the venv's dependencies (si#525): run the `claude`
#: toolchain's plugin step once, before the command. Taken off the environment when read, so the
#: `./<product>.sh <leaf>` processes a plan is made of do not each repeat it.
PLUGIN_STEP_ENV = "SIMPLON_PLUGIN_STEP"


def plugin_step_after_refresh() -> None:
    """The launcher's plugin step: once per deps refresh, reported, and NEVER a failed command.

    OFF says nothing, as in `support install`. Any other outcome is one line, FAILED included, and the
    command then runs as asked - a plugin that would not install must not cost somebody their build. An
    error the step did not foresee is a warning for the same reason.
    """
    from simplon.tasks import claudeplugins

    if os.environ.pop(PLUGIN_STEP_ENV, "") != "1":
        return
    # ON STDERR, all of it: this runs before the command a person typed, and `V=$(./<product>.sh
    # release version)` right after a deps refresh must capture the version and nothing else.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            outcome = claudeplugins.step()
        except Exception as exc:     # noqa: BLE001 - the launcher's promise is that this never stops a command
            log.warn(f"Claude Code plugins were not checked: {exc}")
            return
        if outcome.state is not claudeplugins.State.OFF:
            claudeplugins.report(outcome)


#: What a person types to ask for the headless runner; `simplon.kernel.steps.NO_TUI_ENV` is what
#: actually travels (si#223 point 3).
NO_TUI_FLAG = "--no-tui"

#: The help screen's sentence for it, on the root app only: the flag is read before the first command
#: word and nowhere else, so a group screen naming it would be saying something false.
NO_TUI_LINE = (f"{NO_TUI_FLAG} before the command (or {NO_TUI_ENV}=1 in the environment) runs it on "
               "the console, without the Textual UI.")


def consume_no_tui(argv: list[str]) -> bool:
    """Take `--no-tui` off the argv IN PLACE and say whether it was there.

    CONSUMED HERE RATHER THAN REGISTERED ON A ROOT CALLBACK, deliberately. The root app belongs to the
    PRODUCT - `assemble` is handed one and registers no callback on it - so declaring a global option the
    Typer way would mean writing `app.callback(...)`, which silently REPLACES a callback a product wrote
    for itself. A flag that costs a product its own root callback on a kernel upgrade is not worth its
    discoverability, so the flag is stripped before Click ever sees the line and documented where
    `SIMPLON_MAX_PARALLEL` is documented.

    THE LEADING OPTION RUN AND NOTHING ELSE. A `passthrough_args` command forwards its unrecognised
    trailing args to an underlying tool, so `<product> test unit --no-tui` is pytest's token and not this
    kernel's - taking it would silently change what somebody's test runner was asked to do. Scanning only
    the options BEFORE the first ordinary token also has to happen before the env-first dispatch pops its
    own leading token, which is why this runs first in `main`: `<product> --no-tui dev build` must still
    leave `dev` where that code looks for it.

    Never UNSETS: the flag can only add to what the environment already said, so the two cannot contradict
    each other and there is no precedence rule to remember.
    """
    asked = False
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        if argv[index] == NO_TUI_FLAG:
            del argv[index]
            asked = True
            continue
        index += 1
    return asked


def _render(pipeline: Pipeline) -> int:
    """Draw `pipeline` in the Textual UI. The import is here, inside the call, because Textual is optional:
    a missing install raises ImportError, which `steps.dispatch` answers with the headless runner."""
    from simplon.ui.tui import run_pipeline
    return run_pipeline(pipeline)


def _walk(pipeline: Pipeline, prompt: Any) -> int:
    """Draw an acceptance walk in the Textual UI (si#394). `tui.run_walk` refuses a missing Textual itself,
    because a walk has no headless fallback."""
    from simplon.ui.tui import run_walk
    return run_walk(pipeline, prompt)


def run_host() -> runhost.RunHost:
    """What this CLI tells the kernel about a run (si#391): the product's log directory, the selected
    environment and the lab instance, each answered by the module that owns it, and the Textual UI for a
    run and for a walk."""
    return runhost.RunHost(log_directory=outputs.log_directory, environment=environment_name,
                           instance=labinstance.declared_id, render=_render, walk=_walk)


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
    # BEFORE the env token is popped, because `<product> --no-tui dev build` has to leave `dev` where the
    # selection below looks for it. Setting the VARIABLE rather than passing a flag down is what makes it
    # reach the `./<product>.sh <leaf>` subprocesses a plan is made of (si#223).
    if consume_no_tui(sys.argv):
        os.environ[NO_TUI_ENV] = "1"
    # Every run starts here, a product's and simplon's own, so this is where the layers above the kernel
    # tell it what they know (si#391). Before the env token is read, because nothing below asks yet.
    runhost.register(run_host())
    plugin_step_after_refresh()

    taxonomy = context.manifest().taxonomy()
    # si#467: ON THE CONTAINER ROUTE ONLY, the launcher that started this container has to forward what the
    # manifest's `launcher: env: pass:` declares. The launcher is bash and carries its own rendered copy of
    # the list, so a launcher not re-rendered after the list changed would hand this kernel a variable
    # unset - indistinguishable from one the host never set. `DELIVERY_ROUTE=inside` is the launcher's
    # own statement that this is that route; the venv route has no container and nothing to compare.
    if os.environ.get("DELIVERY_ROUTE") == "inside":
        stale = launcherenv.stale_launcher(
            launcherenv.declared(context.manifest_data(), str(context.manifest_path)),
            os.environ, launcher(context.name))
        if stale:
            log.die(stale)

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
    # ... and again in the kernel's own namespace, because the variable above is the PRODUCT's and its
    # name arrives through the injected provider - so no kernel leaf can read the answer back out of it.
    # See `context.ENVIRONMENT_ENV`; the run transcript is its first reader (si#148 item 4).
    os.environ[ENVIRONMENT_ENV] = env

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
        log.die(f"'{cmd}' is environment-agnostic and takes no env prefix; "
                f"run '{launcher(context.name)} {cmd}'")
    # NO BACKEND GATE HERE, and si#298 is the measurement that ended it. `gate-backend` fires for every
    # command in an env-first group, and for five of the eight products in this family those are their
    # OWN `up`, `down` and `install` - bodies the kernel does not dispatch and has no registry for.
    # Exactly one product resolves a command to a `deploy:*` task, and one calls `backend.register`.
    #
    # So a gate here asked a question about the KERNEL's dispatch and applied it to commands the kernel
    # never dispatches. Both of this week's failures are that mismatch from either end: si#288 killed
    # four of a consumer's own commands, and si#293 had to widen the accepted set until the gate could
    # not close at all - `registry()` parses the matrix against `valid_backends`, so `env.backend` was in
    # the accepted set by construction.
    #
    # The check did not disappear; it moved to where the kernel actually needs an instance, which is
    # `tasks.deploy` - see `_environment` and `backend.resolve`. #11's concern is met there and nowhere
    # else is governed.

    # `prog_name`, and without it Click derives one nobody can type (si#58). `_detect_program_name()`
    # sees `python -m orchestrator`, because that is literally how the launcher execs the module - so
    # every usage line and every Click error message named an invocation that works only with the
    # launcher's own PYTHONPATH already exported. The product IS driven through its launcher, so that is
    # the name; it comes off `simplon.manifest.context.launcher`, the same spelling the generated workflows call
    # and the generated completion registers on.
    app(prog_name=launcher(context.name))
