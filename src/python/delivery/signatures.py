"""What a manifest may bind, and what may be embedded in generated source (netctl#1434).

Two questions the generator and the manifest validator must answer THE SAME WAY, which is why they live
here rather than in either caller: which of a body's parameters are real payload (as opposed to a CLI
context the wrapper supplies), and whether a default value can be written into Python source at all. When the two disagreed, `with: {c: ...}` passed validation and was then silently discarded.
"""
from __future__ import annotations

import inspect
import keyword
from typing import NamedTuple

# Parameter names a body uses for the CLI context (a `typer.Context`). Recognised BY NAME rather than
# by position: the kernel's own command bodies do not all take one (delivery.commands.vcs:push takes
# nothing at all, and vcs:commit's first parameter is its payload), so dropping index 0 unconditionally
# handed a context object to a payload parameter.
CONTEXT_NAMES = frozenset({"c", "ctx", "context"})

# Types whose repr() is valid, stable Python source. Anything else - a datetime PyYAML produced from an
# unquoted date, an Enum, a typer.OptionInfo, any object with the default <... at 0x...> repr - either
# needs an import the generated module does not have or embeds a memory address, which would make the
# render non-deterministic and the drift gate meaningless.
_LITERAL_TYPES = (str, int, float, bool, type(None))


class Parameter(NamedTuple):
    name: str
    default: object          # inspect.Parameter.empty when the parameter is REQUIRED
    required: bool


def takes_context(body: object) -> bool:
    """True iff the body's first parameter is named like a CLI context."""
    params = list(inspect.signature(body).parameters.values())
    return bool(params) and params[0].name in CONTEXT_NAMES


def bindable(body: object) -> list[Parameter]:
    """The body's payload parameters: everything except a leading context and any *args / **kwargs.

    *args is dropped deliberately. Neither Click nor Typer binds a variadic to a parameter, so a variadic
    body yields a command with no declared parameters; such commands are `passthrough_args` and their raw
    tail reaches the body through `ctx.args`, which the per-command context settings allow.
    """
    out: list[Parameter] = []
    for index, param in enumerate(inspect.signature(body).parameters.values()):
        if index == 0 and param.name in CONTEXT_NAMES:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        out.append(Parameter(name=param.name, default=param.default,
                             required=param.default is param.empty))
    return out


def literal(value: object, *, where: str) -> str:
    """`value` as Python source, or a ValueError naming why it cannot be written.

    Rejecting is the point. A value that cannot be rendered as a literal would otherwise produce a module
    that fails at import, or one whose text changes between processes - and `check()` compares text, so a
    non-deterministic render turns the drift gate into a permanent false green.
    """
    if isinstance(value, _LITERAL_TYPES):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError(f"{where}: {value!r} has no literal form in Python source")
        return repr(value)
    if isinstance(value, (list, tuple)):
        inner = ", ".join(literal(item, where=where) for item in value)
        return f"[{inner}]" if isinstance(value, list) else f"({inner},)" if len(value) == 1 else f"({inner})"
    if isinstance(value, dict):
        pairs = ", ".join(f"{literal(k, where=where)}: {literal(v, where=where)}"
                          for k, v in value.items())
        return "{" + pairs + "}"
    raise ValueError(
        f"{where}: a value of type {type(value).__name__} cannot be written into generated source "
        f"({value!r}). Quote it in the manifest if YAML typed it for you - an unquoted date becomes a "
        f"datetime, which needs an import the generated module does not have")


def identifier(name: str, *, where: str) -> str:
    """`name` as a legal Python function name, or a ValueError. `disk-guard` -> `disk_guard`."""
    candidate = name.replace("-", "_")
    if not candidate.isidentifier() or keyword.iskeyword(candidate):
        raise ValueError(
            f"{where}: command name {name!r} does not yield a legal Python identifier "
            f"({candidate!r}) - the generated module would not parse")
    return candidate
