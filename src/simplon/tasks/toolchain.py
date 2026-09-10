"""`toolchain:run` - one pinned image, over the product tree, as the calling user (si#95).

WHY A FAMILY AND NOT A PLACEMENT. si#34 makes a coordinate opening with a group name a placement, and a
containerised toolchain is needed by `build` AND `test` - ctest, dotnet test and gradle test all belong
under the latter. As a family it is free to be filed where the product needs it.

WHY THE IMAGE REFUSAL IS BORROWED AND NOT WRITTEN. `docker.pinned_image` is the ONE gate every image in
this kernel goes through, and its own docstring says why a second one is worse than none: a rule the
kernel argues for and does not keep is a rule the next reader believes less. So the untagged image, the
empty tag and the literal `latest` are refused THERE, with its wording, and this module only carries the
diagnosis across to the way a command refuses - `log.die`, which is how the two other faults in
`declared` end. It raises `ValueError` because its other callers validate manifests at import; a command
body that let that escape would exit through a traceback instead of a diagnosis.

WHY `scaffold` SPLICES TEXT INSTEAD OF REWRITING THE FILE (si#110). It used to read the manifest with
`yaml.safe_load` and write it back with `yaml.safe_dump`, and a round trip through a plain loader keeps
no comment and no flow style: measured on a manifest `simplon init` had just written, 42 comment lines
at column 0 went to 0, and every `{ task: x }` collapsed to block style, so the diff was the whole file.
That spends exactly the argument scaffolding is chosen for - the product reads its own build in its own
file, which is what makes a review of it possible (si#95) - because a manifest without its explanations
is not a file anybody reads.

A round-trip-preserving loader (`ruamel.yaml`) would fix it and was rejected: every dependency in this
kernel is a constraint on every consumer forever (see pyproject's argued bounds), and a second YAML
implementation for ONE command is a large one. The splice reads the file as TEXT, finds
`groups:` -> `build:` -> `commands:`, and inserts the new commands after the last line already in that
block. Nothing it did not write is re-serialised, so comments, flow style, key order and blank lines
survive by construction rather than by a writer's care.

The cost is that a splice can fail to find its place, and the answer to that is a REFUSAL rather than a
guess: an unrecognised shape prints the block to paste and leaves the file untouched. Two things keep
that honest - the shape is located by indentation only (no reflow, no reindent of anything existing),
and the result is PARSED BACK and compared against what the old loader-based path would have produced
before a single byte is written. A splice that would change anything but the commands it adds never
reaches the disk.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

import typer
import yaml

from simplon import context, docker, labinstance, log
from simplon.tasks import profiles
from simplon.run import run


@dataclass(frozen=True)
class Cache:
    """A named volume mounted into the container, so a dependency graph survives the run."""

    volume: str
    path: str


@dataclass(frozen=True)
class Toolchain:
    """One command's containerised toolchain, as the manifest declares it."""

    image: str
    argv: list[str]
    workdir: str = "/work"
    env: dict[str, str] = field(default_factory=dict)
    caches: list[Cache] = field(default_factory=list)


def declared(body: Mapping[str, object], where: str) -> Toolchain:
    """Turn a command's `with:` body into a Toolchain, refusing what cannot be run.

    The image goes through `docker.pinned_image` rather than a check written here: one gate for every
    image in the kernel is the point of that function, and a second one drifts from it.

    Every refusal names the value, the key and the way out - `where` is the command it was read from, so
    a reader is told which manifest entry to edit rather than that something somewhere is wrong.
    """
    image = body.get("image")
    if not isinstance(image, str) or not image:
        log.die(f"{where}: no `image:` - a toolchain command names the image it runs in")
        raise SystemExit(1)
    argv = body.get("argv")
    if not isinstance(argv, Sequence) or isinstance(argv, str) or not argv:
        log.die(f"{where}: no `argv:` - a toolchain command names what to run inside the image")
        raise SystemExit(1)
    return Toolchain(
        image=_pinned(image, where),
        argv=[str(a) for a in argv],
        workdir=str(body.get("workdir", "/work")),
        env=_env(body.get("env"), where),
        caches=_caches(body.get("caches"), where),
    )


def docker_argv(cfg: Toolchain, root: Path, product: str, instance: str,
                extra: list[str], network: str | None = None) -> list[str]:
    """The full docker argv for one toolchain invocation. PURE: it assembles, it runs nothing.

    NAMED `docker_argv` SINCE si#105, and the rename is the loader's doing rather than taste: `argv:` is
    a key of the manifest block, so `run_toolchain` now takes a parameter called `argv` and a module
    function of that name would be shadowed inside the one body that has to call it.

    Pure for the reason `gradle_argv` is pure in netctl: the decisions here - which volume, whose uid,
    what order - are exactly what a test should be able to read without a docker daemon in the room.

    `extra` is APPENDED, never merged: the manifest pins what a CI step means, and a person at a terminal
    keeps the tool's whole vocabulary behind it. An empty `extra` therefore produces byte-for-byte what
    the manifest declares.

    A cache volume carries the PRODUCT and the INSTANCE (`<product>-<volume>-<instance>`), which is
    netctl#453's property made the kernel's: two agents in two worktrees stop contending by construction
    instead of by a convention each product writes out by hand.
    """
    volumes: list[str] = []
    for cache in cfg.caches:
        volumes += ["-v", f"{product}-{cache.volume}-{instance}:{cache.path}"]
    env: list[str] = []
    for key, value in cfg.env.items():
        env += ["-e", f"{key}={value}"]
    return ["docker", "run", "--rm",
            *(["--network", network] if network else []),
            *docker.user_args(),
            "-v", f"{root}:{cfg.workdir}", "-w", cfg.workdir,
            *volumes, *env,
            cfg.image, *cfg.argv, *extra]


def run_toolchain(ctx: typer.Context, image: str = "", argv: list[str] | None = None,
                  workdir: str = "/work", env: dict[str, str] | None = None,
                  caches: list[dict[str, str]] | None = None, network: str | None = None,
                  extra: list[str] | None = None) -> int:
    """Run one toolchain invocation. Thin: `declared` decides what is legal, `docker_argv` decides the line.

    THE PARAMETERS ARE THE MANIFEST'S KEYS, one for one, and that is a correction rather than a style
    (si#105). The loader binds a `with:` block to the impl's PARAMETERS, so a body taking an opaque
    `body` mapping made the design's own section 1 block unassemblable - `image`, `workdir` and `argv`
    were refused as parameters the impl does not take, and `support toolchain` therefore wrote a manifest
    that could not be loaded. Naming them here is what makes the declared shape the shape that runs.

    PIN THEM ALL. `simplon.cli`/`taskgen` render every NON-PINNED parameter as a real option, so a
    command that leaves `env:` out of its `with:` block grows a real `--env` - the same cost
    `simplon.tasks.testrun:gate` documents for its unpinned `--name`, and no profile pins `env:` or
    `caches:`, so every scaffolded command carries both. What a caller then types there is a MAPPING
    key's worth of text, which is why every value goes to `declared` untouched: those two options have
    to be refused by the gate, in the command's name, rather than crash inside a coercion.

    `network` is the one runtime value a manifest cannot supply - a scratch docker network exists only at
    call time - and it is passed through untouched. `extra` is the caller's own tail, declared in the
    catalogue as a variadic positional (`argument: true`) and paired there with `passthrough_args: true`
    so a flag reaches it instead of being refused as an unknown option: without both halves the appending
    rule the whole design rests on has no command line at all.

    `ctx` is here for the DIAGNOSIS and for nothing else. It is recognised by name, never rendered as a
    CLI parameter, and it carries the one thing the values cannot: which command the broken `with:` block
    was read from.

    IT IS ALSO WHY THIS BODY IS REACHABLE FROM A GATE AGAIN (si#136). `command_path` is the whole of what
    this body asks of a context, and a gate knows it - the manifest names the command the gate runs - so
    `simplon.tasks.testrun.GateContext` supplies it and nothing else. A body that reached for the rest of
    a Click context would be refused there by name; this one never does, and the annotation stays
    `typer.Context` because that is what the CLI hands it and the stand-in is structural.
    """
    where = ctx.command_path or "toolchain:run"
    # HANDED OVER RAW, not coerced on the way in, and that is not tidiness. `declared` is the gate that
    # decides what is legal and refuses in a command's voice; a `dict(env)` here would meet a stray
    # `--env foo` FIRST and hand the caller `ValueError: dictionary update sequence element #0 has
    # length 1` - a traceback where the module head promises a diagnosis. `_env` and `_caches` take
    # `object` for exactly this reason, None included.
    cfg = declared({"image": image, "argv": argv, "workdir": workdir,
                    "env": env, "caches": caches}, where)
    product = context.current()
    # The instance is resolved WHERE it is needed and not one line earlier (si#105): it is read from the
    # product's `instance:` section, `simplon init` writes no such section, and resolving it up front
    # meant every toolchain command in every fresh product died on a section that has nothing to do with
    # it. A cache volume still carries the id, because that is the one thing that actually needs one.
    instance = labinstance.resolve() if cfg.caches else ""
    line = docker_argv(cfg, root=product.root, product=product.name, instance=instance,
                       extra=list(extra or []), network=network)
    return run(line, capture=False).rc


def _pinned(image: str, where: str) -> str:
    """The one image gate, with its refusal delivered the way a command refuses (see the module head)."""
    try:
        return docker.pinned_image(image, where, hint="a toolchain must name its version")
    except ValueError as exc:
        log.die(str(exc))
        raise SystemExit(1) from exc


def _env(raw: object, where: str) -> dict[str, str]:
    """The environment the manifest names, and nothing else - no implicit inheritance from the caller."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        log.die(f"{where}: `env:` must be a mapping of NAME to value, got {type(raw).__name__}")
        raise SystemExit(1)
    return {str(key): str(value) for key, value in raw.items()}


def _caches(raw: object, where: str) -> list[Cache]:
    """The named volumes, each of which needs BOTH halves: without a path there is nothing to mount."""
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        log.die(f"{where}: `caches:` must be a list of "
                f"{{ volume: <name>, path: <path in the container> }} entries")
        raise SystemExit(1)
    out: list[Cache] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or "volume" not in entry or "path" not in entry:
            log.die(f"{where}: a `caches:` entry needs both `volume:` and `path:`, got {entry!r}")
            raise SystemExit(1)
        out.append(Cache(volume=str(entry["volume"]), path=str(entry["path"])))
    return out


def _manifest_path() -> Path:
    """The product's own manifest. A function rather than a constant, so a test can point it at a
    tmp_path - the same seam `context.current()` gives every other task."""
    return context.current().manifest_path


def scaffold(language: str, version: str) -> int:
    """Write a language's ready-made toolchain commands into THIS product's manifest (si#95).

    SCAFFOLDED, NOT RESOLVED AT RUN TIME, and that is the safety property rather than a convenience. A
    profile read while a build runs would let a kernel release change what that build does - the same
    class as an unpinned image, one level up. Written into the manifest, the product owns what it runs
    from here on, and the kernel's table can move without moving anybody's build.

    NEVER CLOBBERS. A command that already exists is left exactly as it is and NAMED, because a
    scaffolder that silently overwrites a hand-edited build is worse than no scaffolder: the edit was
    somebody's decision, and this command cannot tell a deliberate one from a stale one.

    AND NEVER REWRITES THE FILE (si#110). The new commands are SPLICED IN as text; every other byte of
    the manifest - comments first among them - is the byte that was there before. The module head
    carries why that is a text splice and not a round-trip-preserving YAML library, and what happens to
    a manifest whose shape the splice cannot read.

    `version` IS DECLARED AND NOT A `**params` BAG (si#105). Every profile's image is a template carrying
    `{version}`, and `simplon.signatures.bindable` drops a VAR_KEYWORD parameter - so the value a
    command supplied was accepted by the loader, never reached this body, and every language raised
    `KeyError: 'version'` on the first line. A parameter the CLI can carry has to be a parameter.
    """
    prof = profiles.profile(language, version=version)
    path = _manifest_path()
    text = path.read_text(encoding="utf-8")
    declared = _declared_build_commands(text)
    written, kept = [], []
    additions: dict[str, object] = {}
    for name, body in prof.commands.items():
        if name in declared:
            kept.append(name)
            continue
        additions[name] = {"task": "toolchain:run", "with": {"image": prof.image, **body}}
        written.append(name)
    if additions:
        path.write_text(_spliced(text, additions, path.name), encoding="utf-8")
    log.ok(f"{language}: wrote {len(written)} command(s)"
           + (f" - {', '.join(written)}" if written else ", nothing was missing"))
    for name in kept:
        log.info(f"kept your own '{name}' - scaffolding never overwrites an edited command")
    return 0


# --- the splice (si#110): text in, text out, and nothing re-serialised that was not written here ---

#: One `key:` line of a block mapping. The key charset is what a command/group name may be; anything
#: else on the line lands in `rest`, which is how a flow value (`groups: { ... }`) is recognised rather
#: than walked into.
_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")


def _declared_build_commands(text: str) -> Mapping[str, object]:
    """The command names already under `groups: build: commands:`, read through the ordinary loader.

    READING is what a plain loader is good at, and the never-clobber rule needs nothing more than the
    names. Only the WRITE goes through the splice.
    """
    data = yaml.safe_load(text) or {}
    node: object = data
    for key in ("groups", "build", "commands"):
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key)
    return node if isinstance(node, Mapping) else {}


def _spliced(text: str, additions: Mapping[str, object], where: str) -> str:
    """`text` with the new commands inserted under its build group, or a refusal that writes nothing.

    The verification at the end is the reason this can be trusted with somebody's manifest: the spliced
    text is parsed back and compared against the data the old loader-based path would have produced. A
    shape that fooled the line scanner therefore ends as a diagnosis, never as a corrupted file.
    """
    raw = text.splitlines(keepends=True)
    lines = [line.rstrip("\r\n") for line in raw]
    place = _place(lines)
    if place is None:
        _refuse(where, additions, indent=6)
    commands_at, empty_flow, insert_at, indent = place
    out = list(raw)
    if empty_flow:
        # `commands: {}` says "no commands" in flow style, and block entries cannot follow it. Dropping
        # the `{}` is the one existing byte this function touches, and it changes no data.
        out[commands_at] = lines[commands_at].split(":", 1)[0] + ":" + _newline(raw, commands_at)
    newline = _newline(raw, insert_at - 1)
    if not newline:  # the file ended without one; the appended block needs the line closed first
        out[insert_at - 1] = out[insert_at - 1] + "\n"
        newline = "\n"
    block = _entries(additions, indent)
    out[insert_at:insert_at] = [line + newline for line in block]
    spliced = "".join(out)
    if not _same_data(spliced, text, additions):
        _refuse(where, additions, indent=indent)
    return spliced


def _place(lines: list[str]) -> tuple[int, bool, int, int] | None:
    """Where the new commands go: (the `commands:` line, whether it holds an empty `{}`, the line to
    insert before, the indent to write them at). None when the shape is not the one this can splice."""
    groups = _find(lines, "groups", 0, len(lines), 0)
    if groups is None or groups[1]:
        return None
    _, groups_end = _extent(lines, groups[0] + 1, 0, len(lines))
    group_indent = _child_indent(lines, groups[0] + 1, groups_end)
    if group_indent is None:
        return None
    build = _find(lines, "build", groups[0] + 1, groups_end, group_indent)
    if build is None or build[1]:
        return None
    _, build_end = _extent(lines, build[0] + 1, group_indent, groups_end)
    key_indent = _child_indent(lines, build[0] + 1, build_end)
    if key_indent is None:
        return None
    commands = _find(lines, "commands", build[0] + 1, build_end, key_indent)
    if commands is None or commands[1] not in ("", "{}"):
        return None
    insert_at, commands_end = _extent(lines, commands[0] + 1, key_indent, build_end)
    entry_indent = _child_indent(lines, commands[0] + 1, commands_end)
    if entry_indent is None:  # nothing in there yet, so the block's own step decides
        entry_indent = key_indent + 2
    return commands[0], commands[1] == "{}", insert_at, entry_indent


def _find(lines: list[str], key: str, start: int, end: int, indent: int) -> tuple[int, str] | None:
    """The line index of `key:` at exactly `indent` within [start, end), and what stands after its colon
    (empty when it opens a block, so a caller can tell a block from a flow value)."""
    for i in range(start, end):
        if _skippable(lines[i]):
            continue
        match = _KEY.match(lines[i])
        if match and len(match["indent"]) == indent and match["key"] == key:
            value = match["rest"].strip()
            return i, "" if value.startswith("#") else value
    return None


def _extent(lines: list[str], start: int, indent: int, limit: int) -> tuple[int, int]:
    """(insert-before, end) of the block whose children are indented deeper than `indent`.

    The two differ on purpose. `end` closes the block; the insertion point is one past the last line
    that carries DATA, so a trailing comment introducing the next sibling keeps the sibling it belongs
    to instead of ending up under the commands spliced in above it.
    """
    insert_at = end = start
    for i in range(start, limit):
        if not lines[i].strip():
            continue
        if _line_indent(lines[i]) <= indent:
            break
        end = i + 1
        if not lines[i].lstrip().startswith("#"):
            insert_at = i + 1
    return insert_at, end


def _child_indent(lines: list[str], start: int, end: int) -> int | None:
    """The indent the block's own entries are written at, taken from the first one; None when empty."""
    for i in range(start, end):
        if not _skippable(lines[i]):
            return _line_indent(lines[i])
    return None


def _skippable(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _newline(raw: list[str], index: int) -> str:
    """The line terminator line `index` actually carries - CRLF stays CRLF, and a last line without one
    is reported as such rather than silently gaining a newline this function did not intend."""
    line = raw[index]
    return line[len(line.rstrip("\r\n")):]


def _entries(additions: Mapping[str, object], indent: int) -> list[str]:
    """The commands as manifest text, one block each, indented to sit under `commands:`.

    THE SHAPE IS `safe_dump`'s, unchanged, and deliberately so: si#110 is about not destroying what
    somebody else wrote, and the block this writes is its own. What that block should look like is
    si#105's question, and answering it here would put a second change in a diff whose whole claim is
    that nothing but the addition moved (`test_case_cpp_chapter` pins the current shape).
    """
    out: list[str] = []
    for name, body in additions.items():
        dumped = yaml.safe_dump({name: body}, sort_keys=False, width=96)
        out += [" " * indent + line if line else line for line in dumped.rstrip("\n").split("\n")]
    return out


def _same_data(spliced: str, text: str, additions: Mapping[str, object]) -> bool:
    """Does the spliced file carry EXACTLY the original data plus the added commands, and nothing else?"""
    try:
        got = yaml.safe_load(spliced)
    except yaml.YAMLError:
        return False
    want = yaml.safe_load(text) or {}
    groups = want.get("groups") or {}
    build = groups.get("build") or {}
    build["commands"] = {**(build.get("commands") or {}), **additions}
    groups["build"] = build
    want["groups"] = groups
    return bool(got == want)


def _refuse(where: str, additions: Mapping[str, object], indent: int) -> NoReturn:
    """Say where the block was meant to go, hand over the block, and change nothing.

    A shape the splice does not recognise is a manifest somebody wrote by hand in a way this scanner
    cannot read - not a licence to guess. What a reader can act on is the text itself, so it is printed.
    """
    log.info(f"{where}: no `groups:` -> `build:` -> `commands:` block mapping to splice into. "
             f"Paste this under your build group's `commands:`:")
    print("\n".join(_entries(additions, indent)))
    log.die(f"{where} was left unchanged - a scaffolder that guessed at the shape would corrupt it.")
