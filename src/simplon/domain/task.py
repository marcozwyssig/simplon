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

from collections.abc import Callable
from typing import TYPE_CHECKING, ClassVar

# `manifest` at module level, not inside `task_class`, and that is measured: imported there, the refusal
# census lost `resolve_ref`'s two refusals and `_split_impl`'s one (269 -> 267), because its walk follows a
# module's imports and a function-local one is none. `manifest` imports this module too; each reaches into
# the other only at call time, so the cycle resolves. `manifestmodel` stays local (it imports
# `manifest.Manifest` at load, a cycle that does not resolve), and its `mangle` refuses nothing.
from simplon.domain import manifest

if TYPE_CHECKING:
    from simplon.domain.manifest import CommandSpec


class Task:
    """A task: an instance of `simplon.pipeline.Task` in the model, a class here."""

    KEY: ClassVar[str]
    #: The body: in a generated class the wrapper `run = staticmethod(<impl>)` until the body moves into the
    #: method; its parameters are the command's (`signatures.bindable` reads them).
    run: Callable[..., object]


def class_name(name: str) -> str:
    """A task class's name from its instance name: the Tasks template's `className`, in Python (snake_case
    to PascalCase over `[a-z0-9_]`, which is all `mangle` writes)."""
    return "".join(part[:1].upper() + part[1:] for part in name.split("_"))


def class_ref(coordinate: str) -> str:
    """The generated class of a catalogue coordinate, as a `module:attribute` reference (si#400 4c). The
    class module is imported only when this is resolved, so naming every coordinate costs nothing."""
    from simplon.domain.manifestmodel import mangle
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
    from simplon.domain.manifestmodel import mangle
    target = manifest.resolve_ref(ref, where)
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
    from simplon.domain.artifactschema import BODIES
    by_class = {class_ref(coordinate): body for coordinate, body in BODIES.items()}
    return by_class.get(impl, impl)


def body_of(spec: CommandSpec, *, where: str) -> Callable[..., object]:
    """The callable a leaf runs: its task class's `run`. The one runtime path (si#400 4c)."""
    return task_class(spec.impl, spec.task or where, where=where)().run
