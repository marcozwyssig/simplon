"""si#400 part 4: the base of every task class firn generates, one per task (`<package>/tasks/<name>.py`).

A task class carries its coordinate in `KEY`, its ports as `ClassVar[Port]` attributes, and its body as
`run`, which until a product moves the body into the method is the wrapper `run = staticmethod(<impl>)`
in the class's protected region (spec decision 3). The suite holds each one to the catalogue it is
generated from (tests/test_task_classes.py).

Since 4c every command's body runs through a class (`body_of`): a catalogue coordinate's generated one,
named by `class_ref` and imported only when it is resolved, or - for a product task, until spec step 6
generates its class - one built here around the function its `impl:` names.
"""
from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from simplon.model.command import TaskCommand

#: What a firn name may not carry (`mangle`).
_NOT_NAME = re.compile(r"[^A-Za-z0-9_]")


class Task:
    """A task: an instance of `simplon.pipeline.Task` in the model, a class here."""

    KEY: ClassVar[str]
    #: The body: in a generated class the wrapper `run = staticmethod(<impl>)` until the body moves into the
    #: method; its parameters are the command's (`signatures.bindable` reads them).
    run: Callable[..., object]


def mangle(name: str) -> str:
    """`name` as a firn name (firn docs/03 §2; firn#962 will allow `-`): every character outside
    [A-Za-z0-9_] becomes `_`, and a leading digit gets `_`."""
    out = _NOT_NAME.sub("_", name)
    return f"_{out}" if out[:1].isdigit() else out


def class_name(name: str) -> str:
    """A task class's name from its instance name: the Tasks template's `className`, in Python (snake_case
    to PascalCase over `[a-z0-9_]`, which is all `mangle` writes)."""
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


def class_ref(coordinate: str) -> str:
    """The generated class of a catalogue coordinate, as a `module:attribute` reference (si#400 4c). The
    class module is imported only when this is resolved, so naming every coordinate costs nothing."""
    name = mangle(coordinate)
    return f"simplon.tasks.{name}:{class_name(name)}"


def task_class(ref: str, key: str, *, where: str) -> type[Task]:
    """The Task class `ref` names: a generated class as it is, or - for a product task, until spec step 6
    generates its class - one built here around the callable, keyed by the task's own name (si#420: two
    tasks on one function are two classes). Anything else is refused, naming the command.

    A callable that is not a class is a body, as `resolve_ref` has always taken it (a function, a
    `functools.partial`); a class that is no Task, or a value that cannot be called, is not.

    NOT CACHED, measured: with an lru_cache six CLI tests failed in the suite and passed alone - a class
    built once held the function a later test had patched in its place. Resolving is an import lookup and
    building a class is cheap, so each call answers what the reference names NOW."""
    target = resolve_ref(ref, where)
    if isinstance(target, type) and issubclass(target, Task):
        return target
    if callable(target) and not isinstance(target, type):
        return type(class_name(mangle(key)), (Task,), {"KEY": key, "run": staticmethod(target),
                                                        "__module__": __name__})
    raise ValueError(f"{where}: `{ref}` is {type(target).__name__} {target!r:.60}, neither a Task class nor a "
                     f"callable, so there is no body to run")


def body_identity(impl: str) -> str:
    """One spelling per body, for the readers that ask whether two commands run the same one (si#400 4c).

    A catalogue coordinate's `impl` names its generated class, while a product task that reaches the same
    kernel body names the function (`simplon.tasks.cidisk:preflight`); comparing the two strings would say
    "two bodies". So a class reference answers the function the model gives its task (`BODIES`), which is
    what the class's wrapper runs, and anything else answers itself."""
    from simplon.model.artifactschema import BODIES
    by_class = {class_ref(coordinate): body for coordinate, body in BODIES.items()}
    return by_class.get(impl, impl)


def body_of(spec: TaskCommand, *, where: str) -> Callable[..., object]:
    """The callable a leaf runs: its task class's `run`. The one runtime path (si#400 4c)."""
    # `task_class` by name, not `spec.task_class(...)`: the refusal census follows calls by name, and the
    # method spelling hid `task_class`'s and `resolve_ref`'s refusals from it (measured, 270 -> 266).
    return task_class(spec.impl, spec.task or where, where=where)().run


def _split_impl(impl: str, context: str) -> tuple[str, str]:
    """Split a "module:function" reference into its two parts, failing loudly on a malformed one.

    `context` names what is being validated (a command name, or the impl itself) so the error points at
    the offending declaration.
    """
    module, sep, function = impl.partition(":")
    if sep != ":" or not module or not function or ":" in function:
        raise ValueError(f"{context}: impl must be 'module:function', got '{impl}'")
    return module, function


def resolve_ref(ref: str, where: str) -> Callable[..., object]:
    """Import a "module:function" reference and return the callable - the one place a declarative ref
    becomes real code. `where` labels the errors so a stale ref points at the declaration that carries it.

    A command's `impl:` is the original consumer, but it is not the only kind of ref a manifest carries: a
    product also declares HOOKS a kernel command calls back into (netctl#1406 - the lab preamble and the
    health precondition of a suite gate). Those are data in the manifest exactly as an impl is, so they
    resolve through the same function rather than a second, subtly different importer.
    """
    module_name, function_name = _split_impl(ref, where)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"{where}: cannot import module '{module_name}': {exc}") from exc
    try:
        return getattr(module, function_name)
    except AttributeError as exc:
        raise ValueError(
            f"{where}: module '{module_name}' has no attribute '{function_name}'") from exc
