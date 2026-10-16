"""si#400 4d: a command of a loaded manifest is an object of a Command class, and the classes mirror
`simplon.pipeline` one to one - `TaskCommand` and its `Deploy`, `AggregateCommand` and its `ReleaseCommand`,
all deriving `Command` (Marco's choice list, si#400 comment 6219416834).

Each class carries only its own kind's fields. `CommandSpec`, which carried both kinds' fields on every
command, answered `impl` on an aggregate and `depends_on` on a leaf with an empty value, and a consumer
reading the other kind's field could not tell "this kind has none" from "this command declared none".
netctl's tests read exactly that (`assert not spec.impl` on an aggregate, `spec.depends_on` on every
command, measured 2026-10-16), so for one release window the base still answers the other kind's fields
with their empty value - with a `CompatWarning` naming the field and the question to ask instead
(`isinstance(command, TaskCommand)`). It is gone after `COMPAT_DUE_AFTER`, and a test notices the date.
"""
from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

# `task` at module level for the reason `task` gives for its own `manifest` import: the refusal census
# follows a module's imports, and `task_class`'s refusals must stay reachable from here.
from simplon.domain import task
from simplon.domain.artifactschema import Port

if TYPE_CHECKING:
    from simplon.domain.task import Task

#: The (major, minor) after which the read compatibility below goes: it ships in 0.33, so 0.34.0 removes it.
COMPAT_DUE_AFTER = (0, 33)


class CompatWarning(DeprecationWarning):
    """A read of a field the command's own kind does not have (si#400 4d, one release window)."""


class ParamPresentation(NamedTuple):
    """How a parameter is PRESENTED, never what it is (netctl#1437).

    The signature - name, type, default - is introspected from the body; declaring it in YAML would state
    it twice and let the two drift, which is the failure `impl:` already has. Its help text, its short
    flag, its metavar and the ORDER its decls are declared in are a different kind of thing: user-facing
    copy that exists nowhere in the signature, and the short flag in particular has no docstring form.
    They lived inside `typer.Option(...)` in the command body until the bodies became framework-free,
    and this is where they went.

    `short_first` exists because Click renders a parameter's decls in DECLARATION order and netctl's
    surface uses both: `--watch -w` on one command and `-f --follow` on the next. The long decl is still
    derived from the parameter name - listing both decls here would restate the signature, which is the
    drift this block refuses. What is declared is which of the two comes first.

    Only these presentation keys are accepted, so a `type:` or `default:` cannot bring the drift back
    through this door.
    """
    help: str | None = None
    short: str | None = None
    argument: bool = False
    metavar: str | None = None
    short_first: bool = False


#: Every field one kind has and the other lacks, with the empty value the other kind reads it as.
_OTHER_KIND: Mapping[str, object] = {
    "impl": "", "task": "", "passthrough_args": False, "with_": {}, "params": {}, "produces": {},
    "consumes": {}, "ports": (),
    "depends_on": (), "stop_on_failure": False, "parallel": False, "keep_awake": False, "passes": (),
    "release": "",
}


@dataclass(frozen=True)
class Command:
    """A command of a manifest: `simplon.pipeline.Command`. What every kind has.

    `unattended` (si#267): can this command run with nobody watching? `None` is the third state and means
    NOBODY HAS SAID - which is not the same as "no". A derivation that read an unset flag as false would
    quietly drop a command from a pipeline, and a pipeline missing a gate is green for the wrong reason;
    one that read it as true would put `test walk` on a runner, where it waits for an answer nobody is
    there to give. So the value has three meanings and gets three values, and the derivation refuses the
    middle one by name.

    `hidden` (netctl#1277): not listed in any `--help` while staying fully invocable.
    """
    help: str = ""
    hidden: bool = False
    unattended: bool | None = None

    def __getattr__(self, name: str) -> object:
        # Reached only when normal lookup fails. Dunders raise at once: copy and pickle probe them.
        if name.startswith("__") or name not in _OTHER_KIND:
            raise AttributeError(name)
        kind = type(self).__name__
        major, minor = COMPAT_DUE_AFTER
        warnings.warn(
            f"{kind}.{name} is not a field of a {kind}; it reads as empty until simplon {major}.{minor + 1}.0 "
            f"removes it - ask isinstance(command, TaskCommand) instead", CompatWarning, stacklevel=2)
        return _OTHER_KIND[name]


@dataclass(frozen=True)
class TaskCommand(Command):
    """A command that runs one task: `simplon.pipeline.TaskCommand`.

    `task` is the coordinate or the product task's bare name the command named; the class is resolved only
    when `task_class` is asked, so loading a manifest imports no body. `impl` is the `module:attribute`
    reference to that class (or, for a product task until spec step 6, to its function). `produces` and
    `consumes` bind artifacts to the task's `ports` (si#344 C.2). `passthrough_args` forwards unrecognised
    trailing arguments to the underlying tool; `with_` pins parameters; `params` presents them.
    """
    impl: str = ""
    task: str = ""
    passthrough_args: bool = False
    with_: Mapping[str, object] = field(default_factory=dict)
    params: Mapping[str, ParamPresentation] = field(default_factory=dict)
    produces: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    consumes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    ports: tuple[Port, ...] = ()

    def task_class(self, *, where: str) -> type[Task]:
        """The Task class this command runs, resolved now (it is not held, see `task.task_class`)."""
        return task.task_class(self.impl, self.task or where, where=where)


@dataclass(frozen=True)
class Deploy(TaskCommand):
    """A task command in an env-first group: `simplon.pipeline.Deploy`. No field of its own yet."""


@dataclass(frozen=True)
class AggregateCommand(Command):
    """A command that runs other commands: `simplon.pipeline.AggregateCommand`.

    `depends_on` names its members, run once each in dependency order; `stop_on_failure` skips the rest of
    its subtree after a failure; `parallel` runs its members at once; `keep_awake` holds the host awake for
    the whole plan; `passes` names the parameters it hands to its leaves (si#433). The full reasoning for
    each sits on the loader's rules in `simplon.domain.manifest`.
    """
    depends_on: tuple[str, ...] = ()
    stop_on_failure: bool = False
    parallel: bool = False
    keep_awake: bool = False
    passes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseCommand(AggregateCommand):
    """An aggregate that names its release bundle: `simplon.pipeline.ReleaseCommand` (si#344 C.3)."""
    release: str = ""
