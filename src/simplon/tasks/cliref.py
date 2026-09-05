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

#: The section holding every command that has no group token: a single-member group collapsed onto its one
#: command (`clitaxonomy.is_flat_command_group`) and a command the product registered on the root app
#: itself. They share a section because they share the only thing a reader needs to know about them - that
#: there is no group to type - and NOT a group note, because they are not one group and need not agree
#: about the environment token.
TOP_LEVEL_HEADING = "## Top-level commands"

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
    #: A leaf sitting directly on the ROOT, so there is no group token between the product and it. Two
    #: unrelated shapes land here and neither is a group: a single-member group whose one command carries
    #: its name, which `assemble` collapses to one visible top-level command, and a command the product
    #: registered on the root app itself. Describing either as a group put a command line on the page
    #: (`<product> <name> <command>`) that nothing can execute.
    top_level: bool = False


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
    """The placeholder a user sees for a parameter.

    NOT Click's own rule, and the difference is chosen rather than overlooked. Click names a plain OPTION
    after its TYPE (`--title TEXT`) and an ARGUMENT after its NAME (`TARGET`); here both are named after
    the parameter, because the table beside the usage line already carries the type and `--title TITLE`
    then says the one thing the type does not.

    The exception is a CHOICE, where the type IS the information. Its members are rendered `[a|b]` - the
    spelling Click uses - because a placeholder that swallowed the accepted values would leave the page
    saying less than `--help` does, which is the one thing a generated reference may never do.

    `Parameter.make_metavar()` is not called for any of it: its signature changed between Click 8.1 and
    8.2 (it now takes a context), so calling it would tie the page to one Click release.
    """
    choices = getattr(param.type, "choices", None)
    base = param.metavar or (f"[{'|'.join(str(choice) for choice in choices)}]" if choices
                             else (param.name or "").upper())
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


def _flat_spellings(root: click.Command) -> frozenset[str]:
    """Every HIDDEN leaf registered on the ROOT - which is more than the back-compat aliases, and is meant
    to be: it is the raw set, and a name only becomes a second spelling further down, where it matches the
    leaf name of a command documented inside a group.

    That match is by NAME, which is the same rule `assemble` registers an alias by - it gives one to every
    UNAMBIGUOUS command name, so a matching name belongs to exactly one command and cannot be attached to
    the wrong one. Callback identity would not work: Typer builds a fresh wrapper per registration, so the
    two spellings of one command share no object.
    """
    return frozenset(name for name, cmd in getattr(root, "commands", {}).items()
                     if cmd.hidden and not isinstance(cmd, click.Group))


def entries(root: click.Command, *,
            env_first: Callable[[str], bool] = lambda group: False) -> list[Entry]:
    """Every command the app offers a human, in the order the app declares them.

    Declaration order rather than alphabetical: it is the order the product's manifest chose, which groups
    a build stage next to the stage it feeds instead of next to whatever starts with the same letter.
    """
    aliases = _flat_spellings(root)
    found: list[Entry] = []

    def entry(cmd: click.Command, path: tuple[str, ...], *, default_action: bool) -> Entry:
        # A group's bare token IS its group. A leaf's group is its parent - and a leaf on the ROOT has
        # none, so its own name is used for the env-gate lookup only: that answers correctly for a
        # collapsed single-member group (the taxonomy knows it under exactly that name) and falsely-but-
        # harmlessly for a product-only root command (the taxonomy has no such path, and
        # `group_requires_env` answers False for a path it cannot resolve). What the name must NEVER
        # become is a group token on the page, which is what `top_level` below is for.
        top_level = len(path) == 1 and not default_action
        group = ".".join(path) if default_action else (".".join(path[:-1]) or path[0])
        text = str(cmd.help or "").strip()
        return Entry(path=path, group=group, summary=_summary(text), help=text,
                     env_first=bool(env_first(group)), params=_params(cmd),
                     alias=path[-1] if len(path) > 1 and path[-1] in aliases else "",
                     default_action=default_action, top_level=top_level)

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
            token = param.metavar
        elif param.type_name == FLAG:
            token = param.decls[0]
        else:
            token = f"{param.decls[0]} {param.metavar}"
        # Brackets mean OPTIONAL. Putting them round a required option would have the usage line
        # contradict the table beside it, which says "required" for the same parameter.
        tokens.append(token if param.required else f"[{token}]")
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


def _yaml(value: str) -> str:
    """A YAML double-quoted scalar.

    Not `repr`. The title arrives from a manifest, so it is not the kernel's to trust, and Python picks a
    quote style by what the string happens to contain - a title carrying both quote characters comes out
    as valid Python source and invalid YAML, which breaks the front matter and with it the page's title.
    Whitespace is collapsed first, so a newline in the value cannot end the scalar either.
    """
    text = " ".join(str(value).split())
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _top_level_note(entry: Entry) -> str:
    """The environment statement for a command with no group token.

    Stated per COMMAND here, while a real group states it once for all its members: env-firstness is a
    property of a GROUP, and the top-level section is not one group - it is every command that has no
    group at all, and two of them need not agree.
    """
    if entry.env_first:
        return "*Environment-first: takes a leading environment token.*"
    return "*Environment-agnostic: takes no environment token.*"


def _group_note(group: str, env_first: bool, product: str) -> str:
    spelled = group.replace(".", " ")
    if env_first:
        return (f"Environment-first: these commands take a leading environment token - "
                f"`{product} <env> {spelled} <command>`.")
    return (f"Environment-agnostic: these commands take no environment token - "
            f"`{product} {spelled} <command>`.")


def render(found: Sequence[Entry], *, product: str, title: str,
           unplaced_tasks: Iterable[tuple[str, str]] = ()) -> str:
    """The whole page, as Markdown with Hugo front matter.

    The front matter carries a `title` because without one Hugo names the page after its FILE, and a
    navigation entry reading "commands" is not the same page as one reading "simplon command reference".
    Everything else on the page is content, so nothing here assumes a theme.
    """
    count = len(found)
    out: list[str] = [
        "---",
        f"title: {_yaml(title)}",
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

    # Sections are keyed on the GROUP, with one shared key for everything that has no group: a section
    # per top-level command would head a one-command section with the command's own name and then have to
    # say something about a group that is not there.
    seen: set[str] = set()
    for entry in found:
        section = "" if entry.top_level else entry.group
        if section not in seen:
            seen.add(section)
            if entry.top_level:
                out += ["", TOP_LEVEL_HEADING, "",
                        f"These take no group token: each is typed straight after `{product}`. A "
                        f"single-member group collapses onto its one command, and a product may also "
                        f"register a command on the root itself; neither has a group to type. Each says "
                        f"below whether it takes an environment token."]
            else:
                out += ["", f"## {entry.group.replace('.', ' ')}", "",
                        _group_note(entry.group, entry.env_first, product)]
        out += ["", f"### `{_spelling(entry, product)}`"]
        if entry.top_level:
            out += ["", _top_level_note(entry)]
        out += ["", "```text", _usage(entry, product), "```"]
        if entry.default_action:
            out += ["", f"The group's default action: `{_spelling(entry, product)}` with no subcommand "
                        f"runs this."]
        if entry.alias:
            out += ["", f"Also spelled `{product} {entry.alias}`."]
        if entry.help:
            out += ["", entry.help]
        out += _param_table(entry)

    rows = list(unplaced_tasks)
    if rows:
        out += ["", UNPLACED_HEADING, "",
                "These are coordinates the delivery kernel's catalogue offers that no command of this "
                "product instantiates, so they are in no group above and cannot be typed here. The list "
                "is what the PLATFORM offers - not what this manifest imports, which for a flat-form "
                "manifest is a separate declaration.", "",
                "Adopting one is not always just a command declaration. Most of them read product data "
                "of their own - a manifest section, a configuration file, a running environment - and "
                "placed without it they would fail on their first line. The kernel's catalogue says, at "
                "each coordinate, what that one needs.", "",
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
                  unplaced_tasks=unplaced(mf, catalogue_mod.load()))
    path = ctx.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    log.ok(f"command reference -> {relative}")
    return 0
