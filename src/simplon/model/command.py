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
from types import MappingProxyType
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, NamedTuple

from simplon.model.artifactschema import Port

if TYPE_CHECKING:
    from simplon.model.task import Task

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


#: Every field one kind has and the other lacks, with the empty value the other kind reads it as. The maps
#: are read-only: one object answers every command, so a consumer writing into what it read would otherwise
#: write into every other command's answer too (final review of 4d).
_EMPTY: Mapping[str, object] = MappingProxyType({})
_OTHER_KIND: Mapping[str, object] = {
    "impl": "", "task": "", "passthrough_args": False, "publishes": False, "token": "", "with_": _EMPTY, "params": _EMPTY, "produces": _EMPTY,
    "consumes": _EMPTY, "ports": (),
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

    `hidden` (netctl#1277) declares that the command must not appear in any `--help` listing while staying
    fully INVOCABLE - a plan step named in a `depends_on` (loader rule 4) must be a real manifest command,
    but a bring-up PHASE or a raw `-only` leaf ("prefer the aggregate") clutters the listing meant for a
    human. `simplon.cli.assemble` is the sole consumer: it threads the flag onto the command's GROUP
    registration, on top of the flat back-compat alias, which has always been hidden regardless of this
    flag. On a group-default group's NAMESAKE member the flag is meaningless - that member is never a
    listed subcommand or a separate flat command to begin with, it is the sub-app's default callback - so
    `load()` rejects it there, the same reasoning `keep_awake` on a leaf already uses (netctl#1238): a flag
    that does nothing where it is written is worse than no flag.
    """
    #: Whether this kind runs a task itself, which is all the kernel asks to tell the kinds apart
    #: (`simplon.kernel.plan.CommandDecl`): the kernel is the layer below and names no class of this one.
    is_leaf: ClassVar[bool] = False

    help: str = ""
    hidden: bool = False
    unattended: bool | None = None

    def __getattr__(self, name: str) -> object:
        # Reached only when normal lookup fails. Dunders raise at once: copy and pickle probe them.
        if name.startswith("__") or name not in _OTHER_KIND:
            raise AttributeError(name)
        _warn(self, name, "reads as empty")
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
    is_leaf: ClassVar[bool] = True

    impl: str = ""
    task: str = ""
    passthrough_args: bool = False
    #: si#490: inherited from the task like `unattended` - `publishes` puts a derived release's dry run
    #: past this leaf, `token: github` puts the run's GITHUB_TOKEN in its step's `env:` and no other step's
    #: (the checkout's persisted credential is si#507's).
    publishes: bool = False
    token: str = ""
    with_: Mapping[str, object] = field(default_factory=dict)
    params: Mapping[str, ParamPresentation] = field(default_factory=dict)
    produces: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    consumes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    ports: tuple[Port, ...] = ()

    def task_class(self, *, where: str) -> type[Task]:
        """The Task class this command runs, resolved now (it is not held, see `task.task_class`).

        `task` is imported here and not at module level, and both are measured: `task` imports the manifest
        loader, and `ports` - which `simplon manifest migrate` imports for a manifest the loader refuses -
        imports these classes, so a module-level import put the loader on the migration's path
        (test_importing_the_migration_does_not_import_the_manifest_loader). The refusal census reaches
        `task_class` through `manifest`'s own import of `task`, and `task.body_of` calls it by name."""
        from simplon.model import task
        return task.task_class(self.impl, self.task or where, where=where)


@dataclass(frozen=True)
class Deploy(TaskCommand):
    """A task command in an env-first group: `simplon.pipeline.Deploy`. No field of its own yet."""


@dataclass(frozen=True)
class AggregateCommand(Command):
    """A command that runs other commands: `simplon.pipeline.AggregateCommand`. It moved here from
    `CommandSpec` with si#400 4d; the reasoning for each field is what it was there.

    `depends_on` (#895) names the commands this one depends on: the runner resolves them transitively,
    DEDUPLICATES by name and runs each unique command exactly once per top-level invocation, in dependency
    order (`Manifest.plan_for`). Idempotency is each command's own guarantee - there is no freshness/Make
    tracking, only dedup-once. `impl` and `depends_on` are mutually exclusive (v1 lock): a command is
    either a leaf-with-impl or an impl-less AGGREGATE. Rationale: plan steps execute as `./<product>.sh
    <leaf>` SUBPROCESSES, so an impl-bearing command that also carried deps would re-expand them in the
    child and break dedup-once. Forward path if a hybrid is ever needed: a child-side skip-deps env guard
    (e.g. NETCTL_SKIP_DEPS=1) - deliberately NOT built now. `stop_on_failure` (an AGGREGATE's flag, rejected
    on a leaf) makes a failure skip the rest of THIS command's subtree instead of running doomed work
    (default False = run every step below it and take the worst rc). It is scoped to the subtree, not to the
    run (netctl#1317): a failing `up` aborts its own phases while the `test all` that planned it carries on
    to the next gate, which is what a flag declared PER AGGREGATE has to mean. The scope of a failure is the
    OUTERMOST ancestor whose flag is true, so an explicit `false` reads the same as an unset one and cannot
    shield its subtree from a `true` above it. `simplon.kernel.steps.abort_after` owns the walk.
    Because a plan tree is a SPANNING tree, a dependency two aggregates both declare is planned under one
    of them only, and the other's flag would never fire for it; `load()` rule 6 (netctl#1319) rejects that
    ambiguity where the two aggregates sit in ONE plan and their flags disagree.

    `parallel` (an aggregate's flag, si#147) declares that this command's dependencies do NOT have to wait
    for each other: its planned children run at the SAME time instead of in list order, and the command
    itself is the join - whatever follows it in its own parent's list starts only once all of them are
    done. DECLARED rather than derived, and the measurement is why. `depends_on` states ORDER, and across
    the six manifests this kernel can reach (`simplon.cli.surface.CONSUMERS` plus its own) 541 pairs of planned
    leaves have no edge between them - and 466 of those would BREAK if run together, because the order
    between siblings is stated by their POSITION in the list and nowhere else. `build docs` in this very
    file says so in prose ("Siblings execute in list order, so [reference, site] IS the edge"), asbundle's
    build chain says "in the order listed", and the kernel's own #901 leaf/aggregate idiom - an aggregate
    `[builder-image, web-jar-only]` whose two members carry no edge - turns every chained build into such a
    pair. A derived executor would run gradle in an image that does not exist yet, in five products at
    once. So the flag is opt-in and its default is exactly today's behaviour.

    Rejected on a LEAF for the reason `stop_on_failure` and `keep_awake` already are: a leaf has no
    children, so the flag would do nothing where it is written. `parallel` and `stop_on_failure` compose
    without a special case - a failure inside a fan skips what has not STARTED and lets what is already
    running finish (`simplon.kernel.steps.abort_after`, which takes the started set for it).

    `keep_awake` (an aggregate's flag, netctl#1238) declares that the host must not idle-sleep while this
    command's PLAN runs: `run_command` wraps the whole dispatch in `simplon.kernel.awake.keep_awake`. It exists
    because a plan has no product code around it - the callback the CLI binds for an aggregate is
    kernel-synthesized - so an aggregate that replaced a hand-written multi-minute pipeline would silently
    lose the inhibitor that pipeline's command had. Declaring it beats each leaf arming its own: the
    inhibitor then spans the GAPS between steps too, and one line in the manifest replaces the same `with`
    block repeated in every long leaf.

    `passes` (an aggregate's, si#433) names parameters the aggregate takes on its OWN command line and
    hands to every planned leaf whose body takes that parameter unpinned. Each leaf runs as its own
    subprocess, so without it an aggregate could not give its leaves anything: simplon's `release all`
    stopped at its first leaf with "which release?". DECLARED rather than derived from the leaves'
    signatures, because a shared parameter NAME is not a shared meaning - `name` is the notes file on
    one release leaf and the image on the next - and forwarding by name alone would hand one value to
    both. Rejected on a leaf for `parallel`'s reason: a leaf plans nothing to pass it to.
    """
    depends_on: tuple[str, ...] = ()
    stop_on_failure: bool = False
    parallel: bool = False
    keep_awake: bool = False
    passes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseCommand(AggregateCommand):
    """An aggregate that names its release bundle: `simplon.pipeline.ReleaseCommand` (si#344 C.3).

    Until 4d the bundle WAS `produces: {release: (<bundle>,)}`, so for the window `produces` answers that
    and not the empty map every other aggregate reads: "declared a bundle" must not read as "declared
    nothing", which is the ambiguity the window exists to end."""
    release: str = ""

    def __getattr__(self, name: str) -> object:
        if name == "produces":
            _warn(self, name, "reads as `{release: (<release>,)}`")
            return MappingProxyType({"release": (self.release,)})
        return super().__getattr__(name)


def _warn(command: Command, name: str, reads: str) -> None:
    kind = type(command).__name__
    major, minor = COMPAT_DUE_AFTER
    # stacklevel 3: past this helper and `__getattr__`, at the consumer's read
    warnings.warn(
        f"{kind}.{name} is not a field of {kind}; it {reads} until simplon {major}.{minor + 1}.0 removes "
        f"it - ask isinstance(command, TaskCommand) instead", CompatWarning, stacklevel=3)

