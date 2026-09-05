"""Write a product's command reference as Markdown, read off the app that is RUNNING (#2).

WHAT IS DERIVABLE IS GENERATED. A hand-written command list is a second copy of something the manifest and
the catalogue already say, and the second copy is the one that goes stale: a command is added, the page is
not, and nothing anywhere goes red. This module exists so that cannot happen - the page is an output, not a
document, and the only way to change it is to change the CLI.

FROM THE BUILT APP, NOT FROM `catalogue.yaml`. The catalogue states the INTENT; the assembled app is the
RESULT, and between them lies the merge with the product manifest - the very place 0.1.6 found a silent
name collision. A reference generated from the catalogue would have described BOTH colliding commands and
kept quiet about the fact that only one of them runs. So the source here is `click.get_current_context()`:
the live root of the app this process is executing. That also picks up what no manifest knows - a
product-only command its composition root registers directly on the root app (`simplon.cli.assemble`
documents that seam) - because the promise of this page is what a user can actually type.

THE CLICK OBJECT TREE, NOT `--help`. Typer builds on Click, and a `click.Command` carries its parameters,
their types, their defaults and their help as OBJECTS. Parsing text that another tool formatted breaks on
the next Click release - and breaks QUIETLY, because a chapter that came out empty still looks like a
chapter. Everything below reads attributes (`Group.commands`, `Parameter.opts`, `ParamType.name`) and
formats them itself.

WHAT COUNTS AS A COMMAND, decided rather than assumed, because the plan's first acceptance is a COUNT and
a count needs a rule:

  - a HIDDEN command is not documented. Two shapes arrive hidden and both are meant to be: the flat
    back-compat alias `assemble` registers for every grouped command (documenting it would double every
    entry and make the count meaningless), and a command whose manifest declares `hidden: true` - a plan
    step a `depends_on` names, deliberately kept out of `--help`. A reference that re-exposed the second
    would overrule the product's own declaration about its surface, which is not the generator's call.
    The flat alias is not LOST, though: it is named on the command it belongs to as a second spelling,
    which is documentation without a second entry;
  - a GROUP that runs without a subcommand IS a command. `<product> build` runs the namesake member of a
    group-default group, so a user can type it, so it is documented - as one entry, next to its siblings;
  - `--help` is Click's, not the command's, and is left out of every parameter table.

ONE PAGE, NOT ONE PER GROUP. Decided on size: simplon's own app has three groups holding three commands,
so a per-group split would produce three pages of one command each and a navigation tree deeper than the
thing it navigates. One page also keeps the acceptance readable - the count is stated on it - and lets a
browser's find, and the theme's search, reach the whole surface at once. A product whose app outgrows one
page wants a directory of pages, which is a second output shape rather than a knob on this one; that is a
follow-up, and it is not needed by anything today.

THE UNPLACED PLATFORM TASKS get a closing section, and it is deliberately NOT part of the count. A
catalogue task nobody instantiated (`docs:site` in this very kernel) appears in no group and would
otherwise be invisible to the one reader who most needs it - somebody building a product on the kernel and
asking what else it offers. Naming them in a section headed by what they are - available, not installed -
states exactly the truth a catalogue-generated reference would have blurred, instead of hiding it.

NO LINKS IN THE INDEX. Anchor ids are the renderer's business, so a generated link would encode a guess
about Hugo's heading-id rule and break as a dead link the day the guess is wrong - silently, again. The
index carries the command names; the theme's search and the browser's find do the jumping.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import click

from simplon import catalogue as catalogue_mod
from simplon import context, log
from simplon.bootstrap import validate_relative_dir
from simplon.orchestrator.manifest import Manifest

#: The closing section's heading. A constant because it is the seam between what this product HAS and what
#: the platform merely offers, and a test asserts nothing from the first half leaks into the second.
UNPLACED_HEADING = "## Platform tasks this product has not placed"

#: How a flag is named in the type column. Click's `ParamType.name` for a boolean is "boolean", which is
#: true and useless: the thing a user types is a flag, not a value.
FLAG = "flag"


@dataclass(frozen=True)
class Param:
    """One parameter of one command, as the Click object carries it.

    `decls` are an option's switches INCLUDING the secondary ones Typer derives for a bare bool
    (`--remote/--no-remote`): the secondary is a switch a user can type, so leaving it out would document
    a smaller command line than the one that exists. An ARGUMENT has no switches at all and is named by
    its metavar instead, which is why both fields are here rather than one.
    """

    name: str
    decls: tuple[str, ...]
    metavar: str
    type_name: str
    required: bool
    default: object
    variadic: bool
    is_argument: bool
    help: str = ""


@dataclass(frozen=True)
class Entry:
    """One documented command: where it sits, what it says about itself, and how it is invoked.

    `path` is the token sequence AFTER the product name (`("support", "git", "commit")`), so the invocation
    line is built by joining it - no dotted spelling ever reaches the page, because nobody can type one.
    `env_first` is read from the manifest taxonomy rather than from the rich help panel `assemble` writes:
    the panel is a display string carrying the product's name, and reading it back would be parsing
    formatted text, which is the mistake this whole module is written to avoid.
    """

    path: tuple[str, ...]
    group: str
    summary: str
    help: str
    env_first: bool
    params: tuple[Param, ...]
    alias: str = ""
    default_action: bool = False


def root_command() -> click.Command:
    """The root of the app THIS PROCESS is running, or a loud failure.

    `click.get_current_context()` is only meaningful inside an invocation, which is exactly the condition
    that makes the answer trustworthy: the tree it returns is the one that parsed the command line that
    reached here, product-only root commands and all. Outside one there is no app to describe, and
    guessing at a second-best source (re-assembling from the manifest, say) would let the page differ
    depending on how it was produced - the silent divergence this module exists to rule out.
    """
    try:
        ctx = click.get_current_context()
    except RuntimeError as exc:                     # click raises this when no invocation is in progress
        raise RuntimeError(
            "simplon: the command reference is read off the running CLI, and no command is being "
            "invoked - run it as a command of the product it documents "
            "(`<product> <group> <command> <output>`), not as a plain function call") from exc
    return ctx.find_root().command


def _metavar(param: click.Parameter) -> str:
    """The placeholder a user sees for a parameter, without asking Click to format it.

    `Parameter.make_metavar()` changed signature between Click 8.1 and 8.2 (it now requires a context), so
    calling it would tie the page to one Click release for no gain - the rule is `metavar or NAME`, and the
    `...` on a variadic is the same suffix Click appends.
    """
    base = param.metavar or param.name.upper()
    return f"{base}..." if param.nargs == -1 else base


def _param(param: click.Parameter) -> Param:
    """One Click parameter object as a documented parameter."""
    is_argument = isinstance(param, click.Argument)
    flag = bool(getattr(param, "is_flag", False)) or bool(param.secondary_opts)
    return Param(
        name=param.name or "",
        decls=tuple(param.opts) + tuple(param.secondary_opts) if not is_argument else (),
        metavar=_metavar(param),
        type_name=FLAG if flag else param.type.name,
        required=bool(param.required),
        default=param.default,
        variadic=param.nargs == -1,
        is_argument=is_argument,
        help=str(getattr(param, "help", "") or ""),
    )


def _params(cmd: click.Command) -> tuple[Param, ...]:
    """A command's own parameters. `cmd.params` deliberately, not `get_params(ctx)`: the latter appends
    Click's `--help`, which belongs to every command ever written and tells a reader nothing."""
    return tuple(_param(p) for p in cmd.params if not getattr(p, "hidden", False))


def _summary(text: str) -> str:
    """The first paragraph of a help text, on one line - the one-liner an index needs."""
    first = text.strip().split("\n\n", 1)[0]
    return " ".join(first.split())


def _aliases(root: click.Command) -> frozenset[str]:
    """The names registered as HIDDEN commands on the root: the flat back-compat spellings.

    Matched by NAME, which is the same rule `assemble` registers them by - it gives a flat alias to every
    UNAMBIGUOUS command name, so a name that reaches here belongs to exactly one command and the match
    cannot go to the wrong one. Callback identity would not work: Typer builds a fresh wrapper per
    registration, so the two spellings of one command share no object.
    """
    return frozenset(name for name, cmd in getattr(root, "commands", {}).items()
                     if cmd.hidden and not isinstance(cmd, click.Group))


def entries(root: click.Command, *,
            env_first: Callable[[str], bool] = lambda group: False) -> list[Entry]:
    """Every command the app offers a human, in the order the app declares them.

    Declaration order rather than alphabetical: it is the order the product's manifest chose, which groups
    a build stage next to the stage it feeds instead of next to whatever starts with the same letter.
    """
    aliases = _aliases(root)
    found: list[Entry] = []

    def entry(cmd: click.Command, path: tuple[str, ...], *, default_action: bool) -> Entry:
        # A group's bare token IS its group; a leaf's group is its parent, and a leaf sitting on the root
        # is a flat-collapsed single-member group whose path is its own name.
        group = ".".join(path) if default_action else (".".join(path[:-1]) or path[0])
        text = str(cmd.help or "").strip()
        return Entry(path=path, group=group, summary=_summary(text), help=text,
                     env_first=bool(env_first(group)), params=_params(cmd),
                     alias=path[-1] if len(path) > 1 and path[-1] in aliases else "",
                     default_action=default_action)

    def walk(cmd: click.Command, path: tuple[str, ...]) -> None:
        for name, sub in getattr(cmd, "commands", {}).items():
            if sub.hidden:
                continue
            here = (*path, name)
            if isinstance(sub, click.Group):
                if sub.invoke_without_command:
                    found.append(entry(sub, here, default_action=True))
                walk(sub, here)
            else:
                found.append(entry(sub, here, default_action=False))

    walk(root, ())
    return found


def unplaced(mf: Manifest, cat: catalogue_mod.Catalogue) -> tuple[tuple[str, str], ...]:
    """The catalogue coordinates no command of this product instantiates, each with the platform's own
    one-line summary.

    Matched on the resolved `impl`, the way `simplon.tasks.tasks._reached_namespaces` does: a coordinate
    can reach a product's surface three ways (placed by the platform's own tree, named by a `task:`, or
    left as a bare `impl:` by a half-migrated group) and all three end as the same resolved impl once the
    manifest is loaded. Matching what the loader PRODUCED needs no per-mechanism walk and cannot miss a
    fourth one a later migration adds.
    """
    placed = {spec.impl for members in mf.commands.values() for spec in members.values() if spec.impl}
    return tuple((str(coordinate), str((spec or {}).get("help", "")))
                 for coordinate, spec in sorted((getattr(cat, "tasks", {}) or {}).items())
                 if (spec or {}).get("impl") not in placed)


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell: one line, and no unescaped column separator."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _default(param: Param) -> str:
    """What a parameter falls back to when it is not given, as a reader needs it."""
    if param.required:
        return "required"
    if param.default is None:
        return "none"
    if callable(param.default):
        # Click lets a default be computed at parse time. Printing it would put a function repr - with a
        # memory address in it - on the page, which is both meaningless and different on every run.
        return "computed"
    if param.default == "":
        return '`""`'
    return f"`{param.default}`"


def _usage(entry: Entry, product: str) -> str:
    """The line a user types. The environment token sits where it is actually typed - between the product
    and the group - which is the whole agnostic/env-first distinction stated in the form that answers it.
    """
    tokens = [product] + (["<env>"] if entry.env_first else []) + list(entry.path)
    for param in entry.params:
        if param.is_argument:
            tokens.append(param.metavar if param.required else f"[{param.metavar}]")
        elif param.type_name == FLAG:
            tokens.append(f"[{param.decls[0]}]")
        else:
            tokens.append(f"[{param.decls[0]} {param.metavar}]")
    return " ".join(tokens)


def _spelling(entry: Entry, product: str) -> str:
    return f"{product} {' '.join(entry.path)}"


def _param_table(entry: Entry) -> list[str]:
    if not entry.params:
        return []
    rows = ["", "| Parameter | Type | Default | Description |", "| --- | --- | --- | --- |"]
    for param in entry.params:
        shown = param.metavar if param.is_argument else ", ".join(f"`{d}`" for d in param.decls)
        name = f"`{shown}`" if param.is_argument else shown
        rows.append(f"| {name} | {_cell(param.type_name)} | {_default(param)} | {_cell(param.help)} |")
    return rows


def _group_note(group: str, env_first: bool, product: str) -> str:
    spelled = group.replace(".", " ")
    if env_first:
        return (f"Environment-first: these commands take a leading environment token - "
                f"`{product} <env> {spelled} <command>`.")
    return (f"Environment-agnostic: these commands take no environment token - "
            f"`{product} {spelled} <command>`.")


def render(found: Sequence[Entry], *, product: str, title: str,
           unplaced: Iterable[tuple[str, str]] = ()) -> str:
    """The whole page, as Markdown with Hugo front matter.

    The front matter carries a `title` because without one Hugo names the page after its FILE, and a
    navigation entry reading "commands" is not the same page as one reading "simplon command reference".
    Everything else on the page is content, so nothing here assumes a theme.
    """
    count = len(found)
    out: list[str] = [
        "---",
        f"title: {title!r}",
        "---",
        "",
        "<!-- GENERATED by the simplon task `docs:reference` from the built command-line application.",
        "     Do not edit: the next build overwrites it. Change the manifest or the catalogue instead. -->",
        "",
        f"This page documents {count} command{'' if count == 1 else 's'}, read off "
        f"`{product}`'s command-line application as it is actually assembled - so it lists what can be "
        f"typed, not what was intended.",
        "",
        "Some commands are **environment-agnostic** and take no environment token; others are "
        "**environment-first** and take one between the product and the group "
        f"(`{product} <env> <group> <command>`). Each command below says which it is, and its usage line "
        "shows the token where it belongs.",
        "",
        "| Command | Environment | Summary |",
        "| --- | --- | --- |",
    ]
    for entry in found:
        kind = "env-first" if entry.env_first else "agnostic"
        out.append(f"| `{_spelling(entry, product)}` | {kind} | {_cell(entry.summary)} |")

    seen: set[str] = set()
    for entry in found:
        if entry.group not in seen:
            seen.add(entry.group)
            out += ["", f"## {entry.group.replace('.', ' ')}", "",
                    _group_note(entry.group, entry.env_first, product)]
        out += ["", f"### `{_spelling(entry, product)}`", "", "```text",
                _usage(entry, product), "```"]
        if entry.default_action:
            out += ["", f"The group's default action: `{_spelling(entry, product)}` with no subcommand "
                        f"runs this."]
        if entry.alias:
            out += ["", f"Also spelled `{product} {entry.alias}`."]
        if entry.help:
            out += ["", entry.help]
        out += _param_table(entry)

    rows = list(unplaced)
    if rows:
        out += ["", UNPLACED_HEADING, "",
                "These are tasks the delivery kernel offers that this product declares no command for, so "
                "they are in no group above and cannot be typed here. They are listed because adopting "
                "one is a manifest line, not a port.", "",
                "| Task | What it does |", "| --- | --- |"]
        out += [f"| `{coordinate}` | {_cell(help_text)} |" for coordinate, help_text in rows]
    return "\n".join(out) + "\n"


def reference(output: str, title: str = "") -> int:
    """Write the product's command reference to `output`, as Markdown for Hugo.

    `output` is a plain relative path under the product root, checked by the rule `--orch-dir` and the
    site build's own paths already use (`simplon.bootstrap.validate_relative_dir`): the value comes from a
    manifest and is then written to, so an absolute one would land outside the product entirely. It is a
    FILE here rather than a directory, which is all that rule's wording gets wrong - the escape it refuses
    is the same one.

    Normally pinned by the product with `with: { output: ... }`, since where the page belongs is the
    product's layout and not the kernel's business; left unpinned it is an ordinary positional argument,
    so the task is placeable by a product that has no website yet.
    """
    ctx = context.current()
    relative = validate_relative_dir(
        output, "the reference output path",
        "give a plain relative path under the product root, e.g. 'site/content/reference/commands.md'",
        inside="the product root")
    mf = ctx.manifest()
    page = render(entries(root_command(), env_first=mf.taxonomy().group_requires_env),
                  product=ctx.name,
                  title=title or f"{ctx.name} command reference",
                  unplaced=unplaced(mf, catalogue_mod.load()))
    path = ctx.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    log.ok(f"command reference -> {relative}")
    return 0
