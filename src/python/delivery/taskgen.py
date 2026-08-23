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


class _Param(NamedTuple):
    name: str
    literal: str | None      # None for a REQUIRED parameter: it must not gain a default
    presentation: object = None   # the manifest's `params:` entry, or None when it declares nothing
    type_hint: str | None = None  # the annotation the wrapper carries; None when none can be written


def _params(body: object, overrides: dict[str, object], presentation: dict, *, where: str) -> list[_Param]:
    """The body's payload parameters, with `with:` values substituted as defaults.

    A parameter the impl declared REQUIRED stays required. Rendering it as `=None` would silently turn a
    mandatory argument into an optional one, moving the failure out of the CLI parser and into whatever
    the body does with None.
    """
    out: list[_Param] = []
    for param in signatures.bindable(body):
        shown, hint = presentation.get(param.name), signatures.annotation(param)
        if param.name in overrides:
            out.append(_Param(param.name, signatures.literal(overrides[param.name], where=where),
                              shown, hint))
        elif param.required:
            out.append(_Param(param.name, None, shown, hint))
        else:
            out.append(_Param(param.name, signatures.literal(param.default, where=where), shown, hint))
    return out


def _signature(params: list[_Param], *, takes_context: bool) -> str:
    """The wrapper's parameter list as source.

    A body that declares a CLI context gets one: the wrapper takes `ctx: typer.Context` and forwards it,
    which is exactly how `delivery.cli.assemble` binds such a body today (it reads `ctx.args`, which is
    how `passthrough_args` reaches the tool behind the command). Typer does not treat `ctx` as a CLI
    parameter, so it stays invisible on the command line. Moving those bodies to a plain `extra: list[str]`
    parameter is a later step and a separate diff.
    """
    parts = ["ctx: typer.Context"] if takes_context else []
    parts += [signatures.option_decl(p.name, p.literal, p.presentation, p.type_hint)
              for p in params]
    return ", ".join(parts)


def _call(impl: str, params: list[_Param], *, takes_context: bool) -> str:
    """The delegation into the body: the context positionally if it wants one, the payload by keyword."""
    args = ["ctx"] if takes_context else []
    args += [f"{p.name}={p.name}" for p in params]
    return f"{impl}({', '.join(args)})"


def render(manifest: Manifest, *, source: str) -> str:
    """The generated module's text for this manifest. Deterministic: same manifest, same bytes."""
    tasks: list[dict[str, object]] = []
    imports: list[str] = []
    groups: list[dict[str, str]] = []
    registrations: list[str] = []
    for group, members in manifest.commands.items():
        var = signatures.identifier(group, where=f"group `{group}`")
        lines: list[str] = []
        for name, spec in members.items():
            if not spec.impl:      # an impl-less depends_on aggregate is a PLAN, and a plan step runs
                continue           # as its own subprocess - there is no body to wrap
            where = f"`{group} {name}`"
            body = resolve_ref(spec.impl, where)
            module, attribute = spec.impl.split(":", 1)
            if module not in imports:
                imports.append(module)
            func = signatures.identifier(name, where=where)
            takes_ctx = signatures.takes_context(body)
            params = _params(body, spec.with_, spec.params, where=where)
            tasks.append({"func": func, "help_repr": repr(spec.help),
                          "signature": _signature(params, takes_context=takes_ctx),
                          "call": _call(f"{module}.{attribute}", params, takes_context=takes_ctx)})
            lines.append(f"{var}.command(name={name!r})({func})")
        if lines:
            groups.append({"var": var, "help_repr": repr(f"{group} commands.")})
            registrations += lines
            registrations.append(f"app.add_typer({var}, name={group!r})")
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    return env.get_template("cli.py.j2").render(source=source, imports=sorted(imports),
                                                tasks=tasks, groups=groups,
                                                registrations=registrations)


def write(manifest: Manifest, target: Path, *, source: str) -> bool:
    """Render the module to `target`. Returns True iff the bytes changed."""
    text = render(manifest, source=source)
    if target.exists() and target.read_text() == text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return True


def check(manifest: Manifest, target: Path, *, source: str) -> str | None:
    """A unified diff when `target` disagrees with the manifest, else None.

    A MISSING target is a diff, not an error: a fresh checkout that never generated must be told what to
    run, and a gate that raises there reads as a broken gate rather than as drift.
    """
    text = render(manifest, source=source).splitlines(keepends=True)
    current = target.read_text().splitlines(keepends=True) if target.exists() else []
    if current == text:
        return None
    return "".join(difflib.unified_diff(current, text, fromfile=f"{target} (committed)",
                                        tofile="manifest (now)"))
