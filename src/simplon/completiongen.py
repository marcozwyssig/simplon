"""Render a product's committed shell completion from its manifest (si#58) - the THIRD of the outputs
this one manifest carries, beside the runtime CLI and the CI workflows.

WHY GENERATED AND NOT TYPER'S OWN. Typer ships `--install-completion`, which writes a hook that runs the
program on every TAB. Measured on this machine, three runs of `./simplon.sh --help`: 340 / 340 / 360 ms -
the launcher's venv and stamp check, the interpreter start, the manifest load, the Typer tree. That is
what would sit between the key and the answer, and a completion that slow is one people turn off. This
module writes the tree out ONCE, into a file of shell, so the TAB costs a `case` statement in the shell
the user is already running: no Python, no venv, no fork. Measured on the generated file: 1000 calls of
`_simplon_complete` took 164 ms, so 0.16 ms each - some two thousand times cheaper than a start.

WHAT IT COSTS INSTEAD, said plainly, because the trade is real: the file is a SECOND SOURCE for the
command tree, and a second source drifts. The whole answer to that is `check` below plus the assertion in
`tests/test_own_completion.py` - regenerate, compare, and be red when the manifest has grown a command
the completion does not know. Without it this would be worth less than nothing; si#40 made the same trade
for the CI workflows and answered it the same way.

WHERE IT IS REGISTERED, and this was measured rather than read. The bash manual (5.3.9, Programmable
Completion) says a command word carrying a path prefix falls back to "the portion following the final
slash" when the full pathname has no compspec. So `complete -F ... simplon.sh` should also answer for
`./simplon.sh`, which is what everybody actually types. Measured on bash 5.3.9(1) in a pty with a
compspec registered for `simplon.sh` alone: `./simplon.sh typech<TAB>` completed to `typecheck-python`,
so did the same line typed with an absolute path, and so did the bare `simplon.sh`; with nothing sourced
the same keystrokes completed nothing at all, which is what makes the first three a measurement rather
than a coincidence. The registration therefore uses `simplon.context.shim` - the basename - while the
usage line Click prints uses `simplon.context.launcher` - the `./` form - and both come off one spelling.

THE `<env>` SLOT, and the ticket's premise about it is wrong in this kernel's own code. si#58 says the
environment names "come NOT from the manifest but from the product's `environments` module". They come
from the manifest: `simplon.environments.Provider.registry` reads `context.current().manifest_data()` and
`parse_data` takes the names out of its `environments:` section. Measured on agile-cockpit's real
manifest, which is the one product on this machine that HAS an env-first group: `env_groups: [deploy]`
and `environments: {dev: {backend: local}}`, both in `agile-cockpit.yaml`. So the names are static data
like everything else here and are rendered from the manifest. What stays true in the ticket is the
narrower version: `EnvironmentProvider` is a structural protocol, so a product MAY supply names from
somewhere else - and for such a product this file would offer the manifest's answer, which is why
`environments_of` reads the section and offers nothing when there is none, rather than inventing `dev`.

TWO RULES ABOUT WHAT IS OFFERED, both decisions rather than derivations.

1. A HIDDEN command is not completed. Every grouped command is additionally registered as a hidden flat
   alias (`simplon.cli.assemble`, the netctl#147 pattern), and a command may declare `hidden: true` of
   its own. Both are deliberately absent from `--help`; completion is the same surface as `--help` -
   what the tool volunteers when asked what it can do - so offering them here would overrule a decision
   the product already made, and would bury six real groups under seventeen aliases at the first TAB.
   They stay invocable, exactly as they are today.
2. An environment token is offered only when the product HAS an env-first group, and never for a name
   that is also a group. Both mirror `simplon.cli.main`: it consumes a leading env token only when the
   token names no group, and an agnostic group given an explicit env is refused outright. Offering `dev`
   in a product with no env-first group would complete a line the dispatcher then rejects.

WHAT THIS DOES NOT KNOW, stated so nobody reads the absence as a bug: a command's OPTIONS and ARGUMENTS.
The manifest carries them, but the shell has to fall back to filenames at some point or a path argument
becomes unusable - so the generated function answers with the tree where it has one and leaves the rest
to `complete -o default`, which is what bash would have done for an unregistered command anyway. Neither
does it know a command a product registered directly on its root Typer app: the manifest is the source,
and what the manifest does not say, this does not offer.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from simplon import clitaxonomy, context
from simplon.orchestrator.manifest import Manifest

#: Where the generated file goes, relative to the product root. Not configurable: a knob here would be a
#: second place to look for one file, and the one thing an installation instruction must be able to do is
#: name the path without asking.
DIRECTORY = "completions"

#: The node key for "an environment token has been consumed". It is not a group path and cannot collide
#: with one - a group name is a shell token and `@` is refused by `_token` below.
ENV_NODE = "@env"

#: What a group or command name may look like for the generated shell to be able to say it literally.
#: Anything else is refused at generation time rather than written into a `case` arm that would then be a
#: pattern, a quote or a syntax error in the user's interactive shell.
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def path_for(product: str) -> str:
    """Where a product's completion file lives, relative to its root."""
    return f"{DIRECTORY}/{product}.bash"


class Drift(NamedTuple):
    """The committed completion disagreeing with the manifest, and the diff that shows how."""

    path: str
    diff: str


@dataclass(frozen=True)
class Tree:
    """The completable command tree: what may be typed at each position.

    `nodes` maps a dotted group PATH to the tokens completable under it, with `""` for the root and
    `ENV_NODE` for the position after a consumed environment token. A path that is absent has nothing to
    offer, which is how the generated function knows it has walked past a leaf into that command's own
    arguments.
    """

    nodes: dict[str, tuple[str, ...]]
    environments: tuple[str, ...]


def environments_of(data: Mapping[str, object]) -> tuple[str, ...]:
    """The environment names a raw manifest declares, in declaration order.

    Reads the same section `simplon.environments.parse_data` reads, so the completion cannot offer an
    environment the dispatcher does not know. A manifest with no section yields NOTHING rather than the
    `dev` that `Provider.registry` falls back to: that fallback is a runtime convenience for a product
    which has not reached deployment, and completing a name no manifest states would put a token on
    screen that this file cannot show the source of.
    """
    declared = data.get("environments")
    if not isinstance(declared, Mapping):
        return ()
    return tuple(str(name) for name in declared)


def tree(mf: Manifest, *, environments: Iterable[str] = ()) -> Tree:
    """The completable tree for one manifest - the same shape `simplon.cli.assemble` binds to Typer.

    Every rule below is `assemble`'s, read off the same taxonomy rather than restated: a group that gets
    a sub-app is completable under its parent, a collapsed single-member flat group contributes its one
    VISIBLE top-level command instead, and a group-default group's namesake member is the bare token
    rather than a subcommand of itself. Hidden commands are left out - see this module's head, rule 1.
    """
    tax = mf.taxonomy()
    nodes: dict[str, list[str]] = {"": []}
    #: Which ROOT tokens sit inside an env-first subtree. Carried alongside rather than recomputed from
    #: the token, because the root mixes two kinds - a group's own leaf name and a collapsed flat group's
    #: MEMBER name - and only the first is a group path `group_requires_env` can answer about.
    env_first: list[str] = []

    for group in clitaxonomy.group_paths(
            group for group in mf.groups if not tax.is_flat_command_group(group)):
        parent, _, leaf = group.rpartition(".")
        nodes.setdefault(group, [])
        nodes.setdefault(parent, []).append(_token(leaf, f"group '{group}'"))
        if not parent and tax.group_requires_env(group):
            env_first.append(leaf)

    for group, names in mf.groups.items():
        flat = tax.is_flat_command_group(group)
        namesake = group.rsplit(".", 1)[-1] if tax.is_group_default_command(group) else None
        for name in names:
            if name == namesake or mf.spec_for(group, name).hidden:
                continue
            # A collapsed flat group's member is registered on the ROOT app, not under its parent - that
            # is what `assemble` does today, at every depth.
            where = "" if flat else group
            nodes.setdefault(where, []).append(_token(name, f"command '{group} {name}'"))
            if flat and tax.group_requires_env(group):
                env_first.append(name)

    env = _env_names(mf, tax, environments)
    if env:
        nodes[""].extend(env)
        nodes[ENV_NODE] = env_first

    return Tree(nodes={path: tuple(words) for path, words in nodes.items()},
                environments=env)


def _env_names(mf: Manifest, tax: clitaxonomy.CommandTaxonomy,
               environments: Iterable[str]) -> tuple[str, ...]:
    """The environment names worth completing at the first position, or nothing - and the difference is
    the point.

    NOTHING when the product declares no env-first group: `simplon.cli.main` refuses an explicit env to
    an agnostic group, so every such completion would be a line the dispatcher then rejects.

    And nothing for a name that also names a top-level GROUP, which is `main`'s own condition read off
    the same projection it reads (`taxonomy.groups`, the tree's top level - wider than `mf.groups`,
    since a catalogue group holding no command is still a name the dispatch will not treat as an
    environment). That is how netctl's `test` environment and `test` group coexist; completing it would
    suggest an environment selection the very next token turns into a group dispatch.
    """
    if not mf.env_groups:
        return ()
    return tuple(_token(str(name), "environment") for name in environments
                 if str(name) not in tax.groups)


def _token(name: str, where: str) -> str:
    """`name` if the generated shell can say it literally, else a refusal naming where it came from.

    DIAGNOSIS, not an expression rule: a name outside this set cannot be a usable shell token in the
    first place - it would need quoting to type - so nothing a product could legitimately want is
    refused. What it prevents is a manifest turning into a `case` arm that is a glob, an unbalanced
    quote or a syntax error in somebody's interactive shell, where the failure would arrive with no
    connection to the manifest that caused it.
    """
    if not _TOKEN.match(name):
        raise ValueError(
            f"{where}: '{name}' cannot be written into a shell completion - a group or command name "
            f"must start with a letter or digit and hold only letters, digits, '.', '_' and '-'")
    return name


# --- rendering ---------------------------------------------------------------------------------------


def identifier(product: str) -> str:
    """The shell function-name stem for a product: `agile-cockpit` -> `_agile_cockpit`.

    Derived rather than passed in, so a product cannot end up with a completion whose functions are named
    after a different one. A leading underscore keeps it out of the way of anything a user might type.
    """
    return "_" + re.sub(r"[^A-Za-z0-9]+", "_", product).strip("_")


def render(spec: Tree, *, product: str, source: str) -> str:
    """The completion file's text. Deterministic: same manifest, same bytes.

    NOTHING MACHINE-SPECIFIC in it, and that is a constraint rather than a preference: the file is
    committed, so an absolute path baked into the header would make it drift between two checkouts of the
    same commit and turn the drift gate into noise. The absolute path belongs in what the COMMAND prints,
    where it is true for exactly one machine and nobody stores it.
    """
    fn = identifier(product)
    shim, typed = context.shim(product), context.launcher(product)
    out = [
        f"# GENERATED from {source} by `{product} support completion`. Do not edit.",
        "#",
        f"# The command tree below is {source}'s, resolved once here so that a TAB costs a `case`",
        "# statement in the shell you are already running - no interpreter start, no virtualenv check.",
        f"# Regenerate it with `{typed} support completion`; `--check` reports drift and writes nothing.",
        "#",
        "# INSTALL IT - a generated completion nobody sources completes nothing. From the product root:",
        "#",
        f'#     echo "source $PWD/{path_for(product)}" >> ~/.bashrc',
        "#",
        "# and open a new shell. In zsh the same file works once bash's completion API is loaded:",
        "#",
        "#     autoload -U +X bashcompinit && bashcompinit",
        f'#     echo "source $PWD/{path_for(product)}" >> ~/.zshrc',
        "#",
        f"# It is registered on `{shim}` rather than on `{typed}`, and that covers both: bash falls back",
        "# to the portion of a command word following the final slash when the full pathname carries no",
        "# compspec of its own (bash manual 5.3.9, Programmable Completion).",
        "",
        f"{fn}_nodes() {{",
        f"    {fn}_reply=()",
        '    case "$1" in',
    ]
    for path, words in spec.nodes.items():
        if not words:
            continue
        arm = "''" if path == "" else f"'{path}'"
        out.append(f"        {arm}) {fn}_reply=({' '.join(f'{word!r}' for word in words)}) ;;")
    out += [
        "    esac",
        "}",
        "",
        f"{fn}_is_env() {{",
    ]
    if spec.environments:
        out += ['    case "$1" in',
                "        " + "|".join(f"{name!r}" for name in spec.environments) + ") return 0 ;;",
                "    esac"]
    out += [
        "    return 1",
        "}",
        "",
        f"{fn}_complete() {{",
        "    local cur tok node word i hit",
        f"    local -a {fn}_reply",
        "    COMPREPLY=()",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        "    node=''",
        "    # Walk the tokens already typed down the tree. An option never moves the node, an",
        "    # environment token is consumed once and only in first position, and a token the current",
        "    # node does not carry means we are inside a command's own arguments - which this file does",
        "    # not describe, so it answers nothing and lets `complete -o default` offer filenames.",
        '    for (( i = 1; i < COMP_CWORD; i++ )); do',
        '        tok="${COMP_WORDS[i]}"',
        '        case "$tok" in ""|-*) continue ;; esac',
        f'        if [ -z "$node" ] && {fn}_is_env "$tok"; then',
        f"            node='{ENV_NODE}'",
        "            continue",
        "        fi",
        f'        {fn}_nodes "$node"',
        f'        [ ${{#{fn}_reply[@]}} -gt 0 ] || return 0',
        "        hit=''",
        f'        for word in "${{{fn}_reply[@]}}"; do',
        '            if [ "$word" = "$tok" ]; then hit=1; break; fi',
        "        done",
        '        [ -n "$hit" ] || return 0',
        f'        if [ "$node" = \'{ENV_NODE}\' ]; then node="$tok"; else node="${{node:+$node.}}$tok"; fi',
        "    done",
        f'    {fn}_nodes "$node"',
        f'    [ ${{#{fn}_reply[@]}} -gt 0 ] || return 0',
        f'    for word in "${{{fn}_reply[@]}}"; do',
        '        case "$word" in "$cur"*) COMPREPLY+=( "$word" ) ;; esac',
        "    done",
        "}",
        "",
        f"complete -o default -F {fn}_complete {shim}",
        "",
    ]
    return "\n".join(out)


# --- write, check ------------------------------------------------------------------------------------


def write(spec: Tree, root: Path, *, product: str, source: str) -> bool:
    """Render the completion under `root`. True when the bytes CHANGED, so a caller can say which."""
    text = render(spec, product=product, source=source)
    target = root / path_for(product)
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return True


def check(spec: Tree, root: Path, *, product: str, source: str) -> Drift | None:
    """The drift, or None when the committed file is what this manifest renders.

    A MISSING file is drift, not an error, exactly as it is in `simplon.workflowgen` and
    `simplon.taskgen`: a checkout that has never generated has to be told what to run, and raising there
    would read as a broken gate rather than as the ordinary thing it is.
    """
    text = render(spec, product=product, source=source)
    relative = path_for(product)
    target = root / relative
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if current == text:
        return None
    return Drift(path=relative, diff="".join(difflib.unified_diff(
        current.splitlines(keepends=True), text.splitlines(keepends=True),
        fromfile=f"{relative} (committed)", tofile=f"{source} (now)")))


def install_hint(root: Path, product: str) -> Sequence[str]:
    """What to type so the generated file actually does something, on THIS machine.

    Said by the command rather than only written into the file, because the two answer different
    questions: the file explains itself to whoever opens it, and this answers "and now what?" for
    somebody who has just run the generator and has no reason to open anything. It is also the only place
    an absolute path may appear - see `render`.
    """
    target = root / path_for(product)
    return (f"source it from your shell to make TAB work: "
            f"echo 'source {target}' >> ~/.bashrc  (then open a new shell)",
            f"zsh reads the same file after `autoload -U +X bashcompinit && bashcompinit`")
