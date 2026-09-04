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
# by position: the kernel's own command bodies do not all take one (delivery.tasks.vcs:push takes
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
    annotation: object = inspect.Parameter.empty


# The annotations the generator may write into a wrapper's signature. Narrow on purpose: anything wider
# would need an import the generated module does not have. Rendering NO annotation is not the safe
# fallback it looks like - Typer infers a parameter's type from its annotation, and an UNANNOTATED
# `dry_run=False` becomes a text option rather than a boolean flag, silently replacing `--dry-run` with
# `--dry-run TEXT`. Whatever falls outside this set turns netctl's CLI-surface golden red, which is where
# it should be dealt with rather than here.
_ANNOTATIONS = {bool: "bool", int: "int", float: "float", str: "str"}

# Composite annotations recognised by their SOURCE SPELLING, mapped to the spelling the generator emits.
# A body written under `from __future__ import annotations` hands `inspect.signature` a string, so both
# the text and the object form are matched. `Optional[...]` normalises to the `| None` form, which needs
# no import in the generated module.
#
# Narrow on purpose, extended only when a body needs it: a variadic `list[str]` is what makes Typer
# render `nargs=-1`, and getting it wrong silently turns a positional argument list into a single
# `--message TEXT`. The golden is the oracle.
_COMPOSITES = {
    "list[str]": "list[str]",
    "list[str] | None": "list[str] | None",
    "Optional[list[str]]": "list[str] | None",
    "typing.Optional[list[str]]": "list[str] | None",
    "str | None": "str | None",
    "Optional[str]": "str | None",
    "typing.Optional[str]": "str | None",
}


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
                             required=param.default is param.empty,
                             annotation=param.annotation))
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


def annotation(param: Parameter) -> str | None:
    """The wrapper's type annotation for `param`, or None when none can be written.

    Preferred source is the body's own annotation; a body without one is typed from the RUNTIME TYPE of
    its default, which is the same fact stated less explicitly. A body whose module uses
    `from __future__ import annotations` yields the annotation as a STRING, so both forms are matched.
    """
    for form, spelling in _ANNOTATIONS.items():
        if param.annotation is form or param.annotation == spelling:
            return spelling
    if param.annotation is not inspect.Parameter.empty:
        text = param.annotation if isinstance(param.annotation, str) else str(param.annotation)
        if text in _COMPOSITES:
            return _COMPOSITES[text]
    if not param.required and type(param.default) in _ANNOTATIONS:
        return _ANNOTATIONS[type(param.default)]
    return None


class Shape(NamedTuple):
    """The declaration shape of one parameter: whether the manifest describes it at all, whether it lands
    as a positional, and the option decls in the order Click must see them."""

    declared: bool
    positional: bool
    decls: tuple[str, ...] = ()


def shape(name: str, *, required: bool, presentation) -> Shape:
    """The shape decision shared by BOTH renderings of a `params:` block (netctl#1444).

    `taskgen` renders a parameter as SOURCE for the generated module; `delivery.cli.assemble` builds the
    same declaration as a live Typer object at assembly time. They must agree exactly - a body is supposed
    to behave identically under either mechanism - so the decision lives here once instead of twice.
    """
    declared = presentation is not None and (presentation.help is not None
                                             or presentation.short is not None
                                             or getattr(presentation, "metavar", None) is not None
                                             or getattr(presentation, "argument", False))
    if not declared:
        return Shape(declared=False, positional=False)
    positional = required or getattr(presentation, "argument", False)
    if positional and presentation.short:
        # A positional has no flags, so a short decl on one renders nothing at all. The manifest model
        # already rejects `argument: true` + `short:`, but it cannot see the OTHER way a parameter becomes
        # positional - being REQUIRED in the body - so that pairing reached here and was silently dropped
        # while `help:` and `metavar:` beside it survived. "A flag that does nothing where it is written is
        # worse than no flag" is the rule this file's neighbours already follow.
        raise ValueError(
            f"parameter {name!r} declares short flag {presentation.short!r}, but it renders as a "
            f"POSITIONAL argument (it is required in the body, or declares `argument: true`) and a "
            f"positional has no flags - drop the `short:` or give the parameter a default")
    if positional:
        return Shape(declared=True, positional=True)
    # Click renders the decls in DECLARATION order, and netctl's surface uses both orders: `--watch -w` on
    # one command and `-f --follow` on the next. `short_first` is the one degree of freedom there is, since
    # the long decl is derived from the parameter name rather than declared.
    long_decl = f"--{name.replace('_', '-')}"
    short = presentation.short
    if short and getattr(presentation, "short_first", False):
        return Shape(declared=True, positional=False, decls=(short, long_decl))
    return Shape(declared=True, positional=False,
                 decls=(long_decl,) + ((short,) if short else ()))


def option_decl(name: str, literal_default: str | None, presentation, type_hint: str | None = None) -> str:
    """One wrapper parameter as source, given its rendered default and its manifest presentation.

    Three shapes, and the choice between them is load-bearing rather than cosmetic:

      - `argument: true` -> `typer.Argument`, for a parameter that is POSITIONAL rather than a flag.
        Typer cannot infer that: a `list[str] | None = None` parameter becomes `--name TEXT` unless the
        declaration says otherwise, and that is a different command line from a variadic positional.
      - nothing declared -> `name=default`, so Typer derives everything exactly as it does today,
        including the `--no-x` secondary it gives a bare bool. Emitting an explicit decl for every
        parameter would suppress that secondary and silently delete a working flag from the surface;
      - anything declared -> `typer.Option(default, "--long"[, "-s"], help=...)`, or `"-s", "--long"`
        where `short_first:` says so. Naming the long decl
        explicitly is what SUPPRESSES the `--no-x` secondary Typer derives for a bare bool, and that is
        the shape netctl's whole surface has: not one of its parameters carries a `--no-x`. A bool that
        wanted one would therefore have to stay out of `params:` - which is consistent, since it wants
        Typer's derivation and `params:` is where a command departs from it.

    A REQUIRED parameter has no default to carry, so it renders as a `typer.Argument` - the shape the
    product's bodies already use for one.

    `type_hint` is written in every shape, including the undeclared one: without it Typer reads a bool
    default as a text option (see `annotation`).

    `metavar:` is carried through where the manifest declares one. It names the placeholder Click prints
    in the usage line, so `[up|down|status|repos|cleanup]` is the difference between a member argument
    that lists its members and a bare `[MEMBER]`. It is the one presentation key netctl's CLI-surface
    golden did NOT pin before this, which is exactly why it needs a home here rather than nowhere: a body
    losing it on the way into generated source degrades `--help` while every assertion stays green.

    The netctl CLI-surface golden is the oracle for all three: any of them changing an option's decls,
    its secondaries or its type turns it red.
    """
    # PEP 8 spaces the `=` of an ANNOTATED parameter and closes up an unannotated one; generated code
    # that a reviewer reads should not look like generated code.
    typed, eq = (f"{name}: {type_hint}", " = ") if type_hint else (name, "=")
    form = shape(name, required=literal_default is None, presentation=presentation)
    if not form.declared:
        return typed if literal_default is None else f"{typed}{eq}{literal_default}"
    args = ["..." if literal_default is None else literal_default]
    args += [f'"{decl}"' for decl in form.decls]
    if getattr(presentation, "metavar", None):
        args.append(f"metavar={presentation.metavar!r}")
    if presentation.help:
        args.append(f"help={presentation.help!r}")
    factory = "typer.Argument" if form.positional else "typer.Option"
    return f"{typed}{eq}{factory}({', '.join(args)})"
