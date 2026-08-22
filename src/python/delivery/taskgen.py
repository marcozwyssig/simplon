"""Render a committed module of Invoke tasks from a product manifest (netctl#1434).

The manifest is the MODEL: it names each task, its help, its group and any `with:` overrides. Every
SIGNATURE is introspected from the body the task delegates to - declaring it in YAML would state it
twice and let the two drift, which is the failure `impl:` already has today.

Product-agnostic on purpose (netctl#1280): the only product input is the Manifest it is handed.
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


def _params(body: object, overrides: dict[str, object], *, where: str) -> list[_Param]:
    """The body's payload parameters, with `with:` values substituted as defaults.

    A parameter the impl declared REQUIRED stays required. Rendering it as `=None` would silently turn a
    mandatory argument into an optional one, moving the failure out of Invoke's parser and into whatever
    the body does with None.
    """
    out: list[_Param] = []
    for param in signatures.bindable(body):
        if param.name in overrides:
            out.append(_Param(param.name, signatures.literal(overrides[param.name], where=where)))
        elif param.required:
            out.append(_Param(param.name, None))
        else:
            out.append(_Param(param.name, signatures.literal(param.default, where=where)))
    return out


def render(manifest: Manifest, *, source: str) -> str:
    """The generated module's text for this manifest. Deterministic: same manifest, same bytes."""
    tasks: list[dict[str, object]] = []
    imports: list[str] = []
    groups: list[tuple[str, list[str]]] = []
    for group, members in manifest.commands.items():
        funcs: list[str] = []
        for name, spec in members.items():
            if not spec.impl:      # an impl-less depends_on aggregate is a PLAN, and a plan step runs
                continue           # as its own subprocess - there is no body to wrap
            where = f"`{group} {name}`"
            body = resolve_ref(spec.impl, where)
            module, attribute = spec.impl.split(":", 1)
            if module not in imports:
                imports.append(module)
            func = signatures.identifier(name, where=where)
            funcs.append(func)
            params = _params(body, spec.with_, where=where)
            tasks.append({"name_repr": repr(name), "func": func, "help_repr": repr(spec.help),
                          "impl": f"{module}.{attribute}",
                          "takes_context": signatures.takes_context(body),
                          "params": params})
        if funcs:
            groups.append((group, funcs))
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    return env.get_template("tasks.py.j2").render(source=source, imports=sorted(imports),
                                                  tasks=tasks, groups=groups)


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
