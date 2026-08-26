"""Render a committed module of Typer commands from a product manifest (netctl#1434, retargeted #1437).

The manifest is the MODEL: it names each task, its help, its group and any `with:` overrides. Every
SIGNATURE is introspected from the body the task delegates to - declaring it in YAML would state it
twice and let the two drift, which is the failure `impl:` already has today.

Product-agnostic on purpose (netctl#1280): the only product input is the Manifest it is handed.

The target framework is Typer, and the coupling to it lives HERE and in the template, nowhere else.
Invoke was measured during design and rejected: its task listing is a flat dotted list with no panels
and it derives short flags of its own, so netctl's help display would have had to be rebuilt by hand
(design section 0).
"""
from __future__ import annotations

import difflib
import inspect
from pathlib import Path
from typing import NamedTuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from delivery import signatures
from delivery.orchestrator.manifest import Manifest, resolve_ref

_TEMPLATES = Path(__file__).resolve().parent / "templates"

# The rich panels the root listing is split into. Both are `delivery.cli`'s, reproduced here because the
# generated module IS the assembly now; the CD one names the product token so the usage hint reads in the
# product's own voice, which is why `render` takes a product name rather than hardcoding one.
_CI_PANEL = "CI / agnostic (no env)"

# What Click needs so a command forwards its unrecognised trailing args to the tool behind it. Per
# COMMAND, which is the property that matters: an unknown flag stays an error on every other command.
_PASSTHROUGH_CTX = {"allow_extra_args": True, "ignore_unknown_options": True}


def _cd_panel(product: str) -> str:
    return f"CD / env-first ({product} <env> <group> <cmd>, default dev)"


def _group_help(group: str, product: str, *, env_first: bool) -> str:
    """One group's `--help` blurb.

    A nested group is named by its OWN segment and addressed by its PATH: `support.git` reads "git
    commands." and is typed `<product> support git <cmd>`. Using the dotted path for either would put a
    string on screen that nobody can type (netctl#1444, plan 5).
    """
    label, addressed = group.rpartition(".")[2], group.replace(".", " ")
    return f"{label} commands. " + (f"Env-first: `{product} <env> {addressed} <cmd>` (default dev)."
                                    if env_first else "Environment-agnostic (no env).")


class _Param(NamedTuple):
    name: str
    literal: str | None      # None for a REQUIRED parameter: it must not gain a default
    presentation: object = None   # the manifest's `params:` entry, or None when it declares nothing
    type_hint: str | None = None  # the annotation the wrapper carries; None when none can be written
    pinned: bool = False          # fixed by `with:`, so it is not a command-line parameter at all


def _params(body: object, overrides: dict[str, object], presentation: dict, *, where: str) -> list[_Param]:
    """The body's payload parameters: which reach the command line, and with what default.

    **`with:` PINS** (netctl#1442). A parameter the manifest fixes leaves the wrapper's signature and the
    call passes the literal, so it is not a command-line parameter at all.

    That is one rule rather than two. Substituting the value as a DEFAULT instead reads the same for an
    optional parameter and is wrong for a required one: the body declared it mandatory, and giving it a
    default moves the failure out of the CLI parser into whatever the body does with a value nobody
    passed. Pinning a required parameter is also a designed use - design section 6 replaces
    `typer.Context.info_name` in the suite runner with a generator-supplied `gate(name="system")`, where
    `name` is required - so rejecting the combination would have removed the feature the key exists for.

    A parameter that should stay settable simply does not belong in `with:`.
    """
    out: list[_Param] = []
    for param in signatures.bindable(body):
        shown, hint = presentation.get(param.name), signatures.annotation(param)
        if param.name in overrides:
            if shown is not None:
                raise ValueError(
                    f"{where}: `{param.name}` is fixed by `with:` and also described in `params:`, but a "
                    f"pinned parameter has no command line to appear on - drop one of the two")
            out.append(_Param(param.name, signatures.literal(overrides[param.name], where=where),
                              shown, hint, pinned=True))
        elif param.required:
            out.append(_Param(param.name, None, shown, hint))
        else:
            out.append(_Param(param.name, signatures.literal(param.default, where=where), shown, hint))
    return out


def _signature(params: list[_Param], *, takes_context: bool) -> str:
    """The wrapper's parameter list as source.

    A pinned parameter is absent here and present in the CALL: `with:` fixes it, so it is not on the
    command line (netctl#1442).

    A body that declares a CLI context gets one: the wrapper takes `ctx: typer.Context` and forwards it,
    which is exactly how `delivery.cli.assemble` binds such a body today (it reads `ctx.args`, which is
    how `passthrough_args` reaches the tool behind the command). Typer does not treat `ctx` as a CLI
    parameter, so it stays invisible on the command line. Moving those bodies to a plain `extra: list[str]`
    parameter is a later step and a separate diff.
    """
    parts = ["ctx: typer.Context"] if takes_context else []
    parts += [signatures.option_decl(p.name, p.literal, p.presentation, p.type_hint)
              for p in params if not p.pinned]
    return ", ".join(parts)


def _call(impl: str, params: list[_Param], *, takes_context: bool) -> str:
    """The delegation into the body: the context positionally if it wants one, the payload by keyword.

    A PINNED parameter is passed as its literal - it never reached the command line, so there is no
    variable in scope to forward.
    """
    args = ["ctx"] if takes_context else []
    args += [f"{p.name}={p.literal if p.pinned else p.name}" for p in params]
    return f"{impl}({', '.join(args)})"


def _docstring(spec, body: object) -> str:
    """The wrapper's docstring, which is what Typer renders as the command's help summary.

    Command help wins, then the task's, then the body's docstring: an instance's own wording is instance
    data, a template's is the fallback, and the body's is the last resort for a task nobody described
    (netctl#1469 spec 3.7). This replaces the rule where a non-shared body's docstring beat the
    manifest - an artefact of the reflective assembly, which bound the body itself as the callback.
    """
    if spec.help:
        return spec.help
    doc = (getattr(body, "__doc__", None) or "").strip()
    return doc or spec.help


def _kwargs(spec) -> str:
    """The registration kwargs a command carries beyond its name, as source."""
    out = []
    if spec.passthrough_args:
        out.append(f"context_settings={_PASSTHROUGH_CTX!r}")
    return "".join(", " + kw for kw in out)


def render(manifest: Manifest, *, source: str, product: str,
           groups: frozenset[str] | None = None) -> str:
    """The generated module's text for this manifest. Deterministic: same manifest, same bytes.

    `product` shapes only the usage hints (the CD panel and each group's blurb), exactly as it does in the
    reflective assembly, so a second *ctl product reads in its own voice from the same generator.

    `groups` restricts the render to a subset of the taxonomy, which is how a product migrates off the
    reflective assembly without one all-or-nothing PR (netctl#1444). Per GROUP rather than per command,
    and that is forced rather than chosen: a group registers ONE sub-app, so a group split across the two
    mechanisms would have both of them call `add_typer` under the same name and one would overwrite the
    other's members. `None` renders everything.

    The generated module names what it covers in `COVERED`, so the product can tell the reflective
    assembly to leave those groups alone rather than restating the list on both sides.
    """
    tax = manifest.taxonomy()
    selected = _selected(manifest, groups)
    cd_panel = _cd_panel(product)
    tasks: list[dict[str, object]] = []
    imports: list[str] = []
    body: list[str] = []
    has_aggregate = False

    # Every function first, so the module reads as a list of what a task IS before how it is wired.
    funcs = _function_names(manifest)
    for group, members in manifest.commands.items():
        if group not in selected:
            continue
        for name, spec in members.items():
            where = f"`{group} {name}`"
            func = funcs[(group, name)]
            if spec.impl:
                module, attribute = spec.impl.split(":", 1)
                if module not in imports:
                    imports.append(module)
                impl_body = resolve_ref(spec.impl, where)
                takes_ctx = signatures.takes_context(impl_body)
                params = _params(impl_body, spec.with_, spec.params, where=where)
                call = _call(f"{module}.{attribute}", params, takes_context=takes_ctx)
                tasks.append({"func": func, "help_repr": repr(_docstring(spec, impl_body)),
                              "signature": _signature(params, takes_context=takes_ctx),
                              "call": f"_rc({call})"})
            else:
                # An impl-less AGGREGATE has no body to wrap: it expands through its dependency plan,
                # which the product dispatches. Skipping it would delete a real, invocable command
                # (`netctl build`, `netctl test all`) from the surface.
                has_aggregate = True
                tasks.append({"func": func, "help_repr": repr(spec.help), "signature": "",
                              "call": f"_plan({name!r}, {group!r})"})

    if has_aggregate:
        body.append("if aggregate is None:")
        body.append('    raise ValueError("this manifest declares impl-less aggregates; '
                    'register(aggregate=...) is required to bind them")')
        body.append("global _aggregate")
        body.append("if _aggregate is not None and _aggregate is not aggregate:")
        body.append('    raise ValueError("this module is already registered with a different '
                    'aggregate dispatcher; it belongs to one manifest and one product")')
        body.append("_aggregate = aggregate")

    # One sub-app per non-flat group. A collapsed single-member flat group gets none - its member IS the
    # group token, so a sub-app would collide with it.
    apps: dict[str, str] = {}
    for group in _group_paths(manifest):
        if group not in selected or tax.is_flat_command_group(group):
            continue
        # `_g_` prefixed, and not merely for tidiness: a group-default group's sub-app variable would
        # otherwise SHADOW the module-level function of the same name, so its own callback would call the
        # Typer object instead of the command (`build = typer.Typer(...)` over `def build()`).
        var = "_g_" + signatures.identifier(group.replace(".", "_"), where=f"group `{group}`")
        apps[group] = var
        env_first = tax.group_requires_env(group)
        help_text = _group_help(group, product, env_first=env_first)
        if group not in manifest.groups:
            # An ANCESTOR node: declared in the taxonomy, holding subgroups rather than members of its
            # own (`support` above `support.git`). It still needs a sub-app for its children to hang
            # from. Its blurb follows the same shape every other group's does; the `taxonomy:` block's
            # own `help:` is not carried on TaxonomyNode today, which is a gap step 7 has to close.
            body.append(f"{var} = typer.Typer(add_completion=False, no_args_is_help=True, "
                        f"help={help_text!r})")
        elif tax.is_group_default_command(group):
            # #592 D4: the bare token runs the namesake member as the group's DEFAULT action, so
            # `<product> build` still runs the pipeline while `<product> build diff` dispatches a sibling
            # and `--help` renders the listing before the callback runs.
            body.append(f"{var} = typer.Typer(add_completion=False, invoke_without_command=True, "
                        f"no_args_is_help=False, help={manifest.spec_for(group, group).help!r})")
            body.append(f"@{var}.callback(invoke_without_command=True)")
            body.append(f"def {var}_default(ctx: typer.Context) -> None:")
            body.append("    if ctx.invoked_subcommand is None:")
            body.append(f"        {funcs[(group, group)]}()")
        else:
            body.append(f"{var} = typer.Typer(add_completion=False, no_args_is_help=True, "
                        f"help={help_text!r})")

    for group, var in apps.items():
        panel = cd_panel if tax.group_requires_env(group) else _CI_PANEL
        parent, _, leaf = group.rpartition(".")
        target = apps[parent] if parent else "app"
        body.append(f"{target}.add_typer({var}, name={leaf!r}, rich_help_panel={panel!r})")

    # Each command under its group, plus the HIDDEN flat back-compat alias bound to the SAME function.
    for group, names in manifest.groups.items():
        if group not in selected:
            continue
        spec_of = {name: manifest.spec_for(group, name) for name in names}
        panel = cd_panel if tax.group_requires_env(group) else _CI_PANEL
        default_member = tax.is_group_default_command(group)
        for name in names:
            if default_member and name == group.rpartition(".")[2]:
                continue      # the namesake is the sub-app's callback, registered above
            spec = spec_of[name]
            func, kw = funcs[(group, name)], _kwargs(spec)
            if tax.is_flat_command_group(group):
                body.append(f"app.command(name={name!r}, rich_help_panel={panel!r}, "
                            f"hidden={spec.hidden!r}{kw})({func})")
            else:
                body.append(f"{apps[group]}.command(name={name!r}, hidden={spec.hidden!r}{kw})({func})")
                # A name owned by SEVERAL groups gets NO flat alias: a bare ambiguous token must fail as
                # unknown rather than silently pick one owner (`test all` vs `<env> deploy all`).
                if not tax.is_ambiguous(name):
                    body.append(f"app.command(name={name!r}, hidden=True{kw})({func})")

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    covered = sorted((group, name) for group in selected
                     for name in manifest.groups.get(group, ()))
    return env.get_template("cli.py.j2").render(source=source, imports=sorted(imports),
                                                tasks=tasks, body=body, covered=covered,
                                                has_aggregate=has_aggregate)


def _selected(manifest: Manifest, groups: frozenset[str] | None) -> frozenset[str]:
    """The group paths this render covers, ancestors included.

    An ancestor is pulled in even when the caller did not name it: `support.git` cannot be registered
    without a `support` sub-app to hang from, and asking a product to list both would be bookkeeping the
    generator can do for it.
    """
    if groups is None:
        return frozenset(_group_paths(manifest))
    unknown = sorted(set(groups) - set(_group_paths(manifest)))
    if unknown:
        raise ValueError(f"cannot generate group(s) the manifest does not declare: {', '.join(unknown)}")
    out: set[str] = set()
    for group in groups:
        parts = group.split(".")
        out.update(".".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    return frozenset(out)


def unrenderable(manifest: Manifest) -> dict[tuple[str, str], str]:
    """Every command whose wrapper cannot be written, and why.

    The blocker is always the same shape: a default that is not a literal, which today means a body still
    carrying `typer.Option` / `typer.Argument` in its signature. A product uses this to prove that the
    groups it has NOT migrated are held back by a real body rather than by forgetfulness - which is what
    keeps the migration a ratchet instead of a list someone stops updating.

    PER COMMAND, and that is the whole of it. `render` can also fail on a manifest-WIDE identifier clash
    (`_function_names`), which belongs to no single command and is a manifest defect rather than migration
    state. A caller that wants both must ask for both - `render(groups=frozenset())` renders nothing and
    still runs that check, which is how a product asserts no clash is hiding behind an empty report here.
    """
    out: dict[tuple[str, str], str] = {}
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            if not spec.impl:
                continue
            where = f"`{group} {name}`"
            try:
                _params(resolve_ref(spec.impl, where), spec.with_, spec.params, where=where)
            except ValueError as exc:
                out[(group, name)] = str(exc)
    return out


def _group_paths(manifest: Manifest) -> list[str]:
    """Every group that needs a sub-app, ancestors first.

    `groups:` names only the nodes that HOLD members. A nested group's ancestors (`support` above
    `support.git`) hold none and are declared in the `taxonomy:` block, yet each still needs a sub-app
    for its children to hang from - and it must exist before them, which is why the order matters.
    """
    out: list[str] = []
    for group in manifest.groups:
        parts = group.split(".")
        for depth in range(1, len(parts) + 1):
            path = ".".join(parts[:depth])
            if path not in out:
                out.append(path)
    return out


def _function_names(manifest: Manifest) -> dict[tuple[str, str], str]:
    """One Python identifier per command, proven unique across the whole module.

    A name declared in several groups is qualified with its group, because two `def all(...)` in one
    module would silently shadow each other - the second definition wins and `test all` would run the
    deploy plan.

    Qualifying is not enough on its own, which is why this ends in a uniqueness check rather than in the
    qualification. The invented `test_all` can collide with a command literally NAMED `test_all` in some
    third group: that one is unambiguous by its bare name, so it is not qualified, and the two land on
    one identifier. Python then binds the second `def` over the first and the wrong body is dispatched -
    the exact failure the qualification exists to prevent, one shape further out.

    There is no automatic disambiguation to reach for here. A generated suffix would make the identifier
    depend on manifest ORDER, and the drift gate compares text. So a genuine clash is a manifest error
    with both culprits named.
    """
    out: dict[tuple[str, str], str] = {}
    owners: dict[str, list[str]] = {}
    ambiguous = {name for name in {n for members in manifest.commands.values() for n in members}
                 if sum(1 for members in manifest.commands.values() if name in members) > 1}
    for group, members in manifest.commands.items():
        for name in members:
            where = f"`{group} {name}`"
            candidate = f"{group}_{name}".replace(".", "_") if name in ambiguous else name
            func = signatures.identifier(candidate, where=where)
            owners.setdefault(func, []).append(f"{group} {name}")
            out[(group, name)] = func
    clashes = {func: who for func, who in owners.items() if len(who) > 1}
    if clashes:
        func, who = sorted(clashes.items())[0]
        raise ValueError(
            f"commands {' and '.join(sorted(who))} both render the Python function `{func}`, so one "
            f"would silently shadow the other and dispatch the wrong body - rename one of them")
    return out


def write(manifest: Manifest, target: Path, *, source: str, product: str,
          groups: frozenset[str] | None = None) -> bool:
    """Render the module to `target`. Returns True iff the bytes changed."""
    text = render(manifest, source=source, product=product, groups=groups)
    if target.exists() and target.read_text() == text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return True


def check(manifest: Manifest, target: Path, *, source: str, product: str,
          groups: frozenset[str] | None = None) -> str | None:
    """A unified diff when `target` disagrees with the manifest, else None.

    A MISSING target is a diff, not an error: a fresh checkout that never generated must be told what to
    run, and a gate that raises there reads as a broken gate rather than as drift.
    """
    text = render(manifest, source=source, product=product,
                  groups=groups).splitlines(keepends=True)
    current = target.read_text().splitlines(keepends=True) if target.exists() else []
    if current == text:
        return None
    return "".join(difflib.unified_diff(current, text, fromfile=f"{target} (committed)",
                                        tofile="manifest (now)"))
