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
`ci:` -> `build:` -> `commands:`, and inserts the new commands after the last line already in that
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

import os
import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

import typer
import yaml

from simplon.manifest import context, launcherenv, layout, outputs
from simplon.adapters import docker, hostpath, labinstance
from simplon.kernel import log
from simplon.tasks import profiles


@dataclass(frozen=True)
class Cache:
    """A named volume mounted into the container, so a dependency graph survives the run."""

    volume: str
    path: str


@dataclass(frozen=True)
class Mount:
    """A path under the product tree bind-mounted over a path in the container (si#511)."""

    source: str
    target: str
    readonly: bool = False


@dataclass(frozen=True)
class Toolchain:
    """One command's containerised toolchain, as the manifest declares it."""

    image: str
    argv: list[str]
    workdir: str = "/work"
    env: dict[str, str] = field(default_factory=dict)
    caches: list[Cache] = field(default_factory=list)
    cwd: str = ""
    # LAST, so a product that builds a Toolchain positionally (biz-cockpit does) keeps its meaning.
    mounts: list[Mount] = field(default_factory=list)


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
    workdir = str(body.get("workdir", "/work"))
    return Toolchain(
        image=_pinned(image, where),
        cwd=_cwd(body.get("cwd"), where),
        argv=[str(a) for a in argv],
        workdir=workdir,
        env=_env(body.get("env"), where),
        caches=_caches(body.get("caches"), where),
        mounts=_mounts(body.get("mounts"), where, workdir),
    )


def docker_argv(cfg: Toolchain, root: Path, product: str, instance: str,
                extra: list[str], network: str | None = None,
                build_root: str = "", home: str = "", name: str = "",
                passes: tuple[str, ...] = ()) -> list[str]:
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

    `--init`, `--name` and the `simplon.run=<product>` label are si#409's, and `docker.lifecycle_args`
    says why each is there: a cancelled run left its container running to the end (firn#965). The NAME
    is a parameter rather than chosen here, because choosing one is not pure - it is unique per
    invocation by construction - and `run_toolchain`, which runs the line, is the one that has to stop
    that container again. An empty `name` adds no `--name`, so a test that only reads the line reads
    the same line twice. They sit AFTER `--network`, so `docker run --rm --network <n>` keeps its shape.

    `passes` is the manifest's `launcher: env: pass:` (si#467), and each name is written BY NAME - `-e NAME`,
    never `-e NAME=<value>` - so a secret is in no argv and no log, and a name this process does not have
    stays unset in the container. Before the manifest's `env:`, so a value a product states still wins.
    """
    volumes: list[str] = []
    for cache in cfg.caches:
        volumes += ["-v", f"{product}-{cache.volume}-{instance}:{cache.path}"]
    # si#511: AFTER the caches and, like every flag, before the image - after it docker would hand the
    # flag to the tool as an argument. The points already exist: `invocation` made them, as the caller.
    for mount in cfg.mounts:
        volumes += hostpath.mount_argv(root, mount.source, posixpath.normpath(mount.target), readonly=mount.readonly,
                                       must_exist=False)
    env: list[str] = []
    for key, value in cfg.env.items():
        env += ["-e", f"{key}={value}"]
    # si#319: `HOME` FIRST and the manifest's environment after it, because docker takes the LAST `-e`
    # for a name - so the kernel hands over a home the calling uid owns and a product that states its own
    # still gets exactly what it stated. An empty `home` adds nothing: only a caller that knows the
    # product's output directory may name one, and a body invoked without one must not invent a path.
    return ["docker", "run", "--rm",
            *(["--network", network] if network else []),
            *docker.lifecycle_args(name, product, instance),
            *docker.user_args(),
            "-v", f"{hostpath.translate(root)}:{cfg.workdir}",
            "-w", _start_in(cfg, build_root),
            *volumes,
            *(["-e", f"HOME={home}"] if home else []),
            *[arg for passed in passes for arg in ("-e", passed)], *env,
            cfg.image, *cfg.argv, *extra]


def _start_in(cfg: Toolchain, build_root: str) -> str:
    """The container's working directory: the mount, then the product's build root, then `cwd:`."""
    base = layout.Layout(build_root=build_root).workdir(cfg.workdir)
    return posixpath.join(base, cfg.cwd) if cfg.cwd else base


def run_toolchain(ctx: typer.Context, image: str = "", argv: list[str] | None = None,
                  workdir: str = "/work", env: dict[str, str] | None = None,
                  caches: list[dict[str, str]] | None = None, network: str | None = None,
                  cwd: str | None = None, mounts: list[str] | None = None,
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

    `network` IS SUPPLIABLE BY A MANIFEST, and this docstring said the opposite until si#202 measured it.
    It is an ordinary parameter, so `with: { network: none }` binds to it like every other key. Driven on
    2026-09-12 on a scaffolded product: pinned, `ip -o link` inside the container lists 1 interface;
    left out, 2 - the default bridge. Unpinned it also renders as a real `--network` option, which is how
    a caller supplies the one value that genuinely only exists at call time, a scratch docker network.

    WHAT THE KEY DECIDES IS BIGGER THAN IT LOOKS, and si#197 paid for the lesson. An acceptance container
    started with no `network:` did not fail to reach its target: the service name resolved through the
    HOST's upstream resolver to 185.199.109.153 (GitHub Pages), which answered 404, and the scenario
    reported a defect in a product it had never touched. The 404 made that a false red. A 200 would have
    made it a false green, which is this repository's own recurring defect arriving through DNS.

    So the key is DOCUMENTED (`params:` in the catalogue) rather than made mandatory. A mandatory
    `network:` would refuse `build compile`, which wants no statement about networking at all, and
    `rules.md`'s own question - would the refused manifest have produced a working product - answers yes
    for every compile command in the four profiles. What the kernel can say truthfully it says in the
    table it owns: `profiles.PROFILES["python"]`'s `unit` and `analyse` pin `none`, because si#121
    measured both green without a network. A level that has to REACH something names the network that
    something is on, and this paragraph is why.

    `extra` is the caller's own tail, declared in the
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
    got = invocation(where, image=image, argv=argv, workdir=workdir, env=env, caches=caches,
                     network=network, cwd=cwd, mounts=mounts, extra=list(extra or []))
    if got is None:
        return 1
    return docker.run_container(*got).rc


def invocation(where: str, *, image: str, argv: list[str] | None, workdir: str, env: object, caches: object,
               network: str | None, cwd: str | None, extra: list[str],
               mounts: object = None) -> tuple[list[str], str] | None:
    """The `docker run` line for one toolchain invocation and its container's name, or None when the
    output tree is not the caller's (the fault is logged). Shared by `run_toolchain` and `firngen.generate`
    (si#400 4b), which needs the same line and firn's stdout back."""
    # HANDED OVER RAW, not coerced on the way in, and that is not tidiness. `declared` is the gate that
    # decides what is legal and refuses in a command's voice; a `dict(env)` here would meet a stray
    # `--env foo` FIRST and hand the caller `ValueError: dictionary update sequence element #0 has
    # length 1` - a traceback where the module head promises a diagnosis. `_env` and `_caches` take
    # `object` for exactly this reason, None included.
    cfg = declared({"image": image, "argv": argv, "workdir": workdir,
                    "env": env, "caches": caches, "cwd": cwd, "mounts": mounts}, where)
    product = context.current()
    # The instance is resolved WHERE it is needed and not one line earlier (si#105): it is read from the
    # product's `instance:` section, `simplon init` writes no such section, and resolving it up front
    # meant every toolchain command in every fresh product died on a section that has nothing to do with
    # it. A cache volume still carries the id, because that is the one thing that actually needs one.
    instance = labinstance.resolve() if cfg.caches else ""
    # si#319, BEFORE the container starts. A container run as the caller owns the bind mount and nothing
    # else, so the kernel hands it a home under the product's output directory - created here, host-side,
    # as the caller, which is what makes the uid inside the container the owner of what it writes.
    #
    # And the tree is checked for OWNERSHIP rather than writability, because that is the question the
    # failure asks: `chmod` may only be called by an owner, so a directory somebody else owns at mode 777
    # is writable by everyone and chmod-able by no-one else - one line into gradle's own bookkeeping,
    # `Operation not permitted`, in a tree si#78's `os.access` check calls clean. The run was going to
    # fail either way; refusing here is the difference between a message about the tree and a stack trace
    # about a registry file.
    #
    # WHAT IS WALKED IS THE OUTPUT DIRECTORY, and the limit is stated rather than hidden: a product's own
    # state outside it - a `.gradle/` beside the source, say - is not walked, because walking a whole
    # repository before every containerised command costs more than it buys. Bringing that state under
    # the home this function now provides is what brings it into the check.
    outputs.ensure_home()
    # si#511, for the same reason and in the same place: a mount point docker has to create is created
    # root-owned, so the kernel makes every one first, as the caller - or refuses before making any.
    fault = prepare_mounts(cfg, product.root, where) or docker.ownership_fault([outputs.root()], product.root)
    if fault:
        log.error(fault)
        return None
    # si#409: the kernel names the container, so a cancelled run can stop it - see `docker.run_container`.
    name = docker.container_name(product.name)
    line = docker_argv(cfg, root=product.root, product=product.name, instance=instance,
                       home=outputs.home_in_container(cfg.workdir),
                       build_root=layout.declared(context.current().manifest_data()).build_root,
                       extra=list(extra or []), network=network, name=name,
                       passes=launcherenv.declared(context.current().manifest_data()))
    return line, name


def _pinned(image: str, where: str) -> str:
    """The one image gate, with its refusal delivered the way a command refuses (see the module head)."""
    try:
        return docker.pinned_image(image, where, hint="a toolchain must name its version")
    except ValueError as exc:
        log.die(str(exc))
        raise SystemExit(1) from exc


def _cwd(raw: object, where: str) -> str:
    """The subdirectory of the mount a command starts in (si#371), or "" for the mount itself.

    firn reads `firn.toml` from the directory it starts in and takes no project option, so a firn project
    under `src/firn/` needs the container to START there while the whole tree stays mounted - which is
    all `cwd:` says. ABSENT IS THE DEFAULT and changes no byte of the line; a value goes through
    `layout._relative`, the gate `build_root:` already uses, so the two cannot disagree about what is
    inside the tree. That gate raises `ValueError` for the load-time section it serves; here it ends the
    way every other fault in `declared` ends, as `log.die` in the command's name.
    """
    if raw is None:
        return ""
    try:
        return layout._relative(raw, "cwd", where)
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


_MOUNT_FORM = "`<path under the tree>:<absolute path in the container>`, optionally followed by `:ro`"


def _mounts(raw: object, where: str, workdir: str) -> list[Mount]:
    """`mounts:` as Mount values, or a refusal naming the entry (si#511). Run time, like `_caches`.

    A target that IS the workdir or one of its ancestors is refused: it would mount over the tree the
    command runs in. Two entries on one target are refused here rather than by docker, which says
    `Duplicate mount point` only after `invocation` has made the directories.
    """
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        log.die(f"{where}: `mounts:` must be a list of {_MOUNT_FORM} strings, got {raw!r}")
        raise SystemExit(1)
    out: list[Mount] = []
    for entry in raw:
        if not isinstance(entry, str):
            log.die(f"{where}: a `mounts:` entry must be a string {_MOUNT_FORM}, got {entry!r}")
            raise SystemExit(1)
        parts = entry.split(":")
        readonly = len(parts) == 3 and parts[2] == "ro"
        if len(parts) not in (2, 3) or (len(parts) == 3 and not readonly):
            log.die(f"{where}: mount '{entry}' is not {_MOUNT_FORM}")
            raise SystemExit(1)
        source, target = parts[0], parts[1]
        try:
            hostpath.mount_source(Path("/"), source, target)
        except ValueError as refused:
            log.die(f"{where}: mount '{entry}': {refused}")
            raise SystemExit(1)
        out.append(Mount(source=source, target=target, readonly=readonly))
    fault = _placement_fault(out, where, workdir)
    if fault:
        log.die(fault)
        raise SystemExit(1)
    return out


def _entry(mount: Mount) -> str:
    return f"{mount.source}:{mount.target}" + (":ro" if mount.readonly else "")


def _placement_fault(mounts: Sequence[Mount], where: str, workdir: str) -> str:
    """Where the mounts land, ruled on: none may cover the tree, and no two may share a target. Shared by
    `_mounts` and `prepare_mounts`, so a Toolchain built in Python is held to what a manifest is."""
    tree = posixpath.normpath(workdir)
    seen: set[str] = set()
    for mount in mounts:
        normal = posixpath.normpath(mount.target)
        if normal == tree or tree.startswith(normal.rstrip("/") + "/"):
            return (f"{where}: mount '{_entry(mount)}' would cover {workdir}, the tree this command runs in; "
                    f"mount over a path below it instead")
        if normal in seen:
            return f"{where}: mount '{_entry(mount)}' names {normal} a second time; one path, one mount"
        seen.add(normal)
    return ""


def prepare_mounts(cfg: Toolchain, root: Path, where: str) -> str:
    """Make every mount's source, and its target's host counterpart when the target lies in the tree
    mount, exist as directories the caller owns - or return why not, having made nothing (si#511).

    Measured with docker 29.9.1 and `--user 4242:4242`: `-v` creates a missing source `root:root 755`,
    so the container cannot write into it, and a missing target nested in the tree mount is left on the
    host root-owned too, where the next host-side `npm install` meets it. So this runs BEFORE the line.

    SHALLOW, unlike `docker.ownership_fault`: the path itself, or its nearest existing ancestor when it
    is missing, must be the caller's. Walking a mounted `node_modules` would be tens of thousands of
    stat calls before every run, and that function's message calls the tree a build output, which a
    mount source need not be. Every check runs before the first `mkdir`, so a refusal leaves no half.
    """
    fault = _placement_fault(cfg.mounts, where, cfg.workdir)
    if fault:
        return fault
    uid = os.getuid() if hasattr(os, "getuid") else None
    tree = posixpath.normpath(cfg.workdir)
    wanted: list[tuple[str, Path]] = []
    for mount in cfg.mounts:
        entry, target = _entry(mount), posixpath.normpath(mount.target)
        # Both halves through `mount_source`, so a symlink in the tree that leads out of it - as the
        # source, or where the target lands in the tree - is refused before `mkdir` could follow it.
        try:
            wanted.append((entry, hostpath.mount_source(root, mount.source, target)))
            if target.startswith(tree.rstrip("/") + "/"):
                wanted.append((entry, hostpath.mount_source(root, posixpath.relpath(target, tree), "/")))
        except ValueError as refused:
            return f"{where}: mount '{entry}': {refused}"
    for entry, path in wanted:
        held = path
        while not held.exists() and held != root and held.parent != held:
            held = held.parent
        shown = held.relative_to(root).as_posix() if held != root else "."
        if held.exists() and not held.is_dir():
            return (f"{where}: mount '{entry}' runs through {shown}, which is not a directory; remove it or "
                    f"mount another path")
        if uid is not None and held.exists() and held.stat().st_uid != uid:
            return (f"{where}: mount '{entry}' needs {shown} owned by uid {uid}; it is owned by uid "
                    f"{held.stat().st_uid}. Remove it or chown it (it takes a root shell), then run this again.")
    for entry, path in wanted:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as failed:
            return f"{where}: mount '{entry}' could not be made: {failed}"
    return ""


def _manifest_path() -> Path:
    """The product's own manifest. A function rather than a constant, so a test can point it at a
    tmp_path - the same seam `context.current()` gives every other task."""
    return context.current().manifest_path


def scaffold(language: str, version: str = "") -> int:
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
    `{version}`, and `simplon.manifest.signatures.bindable` drops a VAR_KEYWORD parameter - so the value a
    command supplied was accepted by the loader, never reached this body, and every language raised
    `KeyError: 'version'` on the first line. A parameter the CLI can carry has to be a parameter.
    """
    path = _manifest_path()
    text = path.read_text(encoding="utf-8")
    # EVERY TOOLCHAIN IS NAMED IN `toolchains:` (si#525), the host ones too: it is the list the kernel
    # reads to know what is on, so a language scaffolded here also turns its Claude LSP set on. Named
    # FIRST, so an unknown name is refused before anything is written.
    listed = _toolchains_spliced(text, language, path.name)
    if language in profiles.HOST_TOOLCHAINS:
        _report_listed(language, listed != text)
        if listed != text:
            path.write_text(listed, encoding="utf-8")
        return 0
    if not version:
        log.die(f"{language} needs a version: its image is pinned to one "
                f"(`support toolchain {language} <version>`)")
        raise SystemExit(1)
    prof = profiles.profile(language, version=version)
    written, kept = [], []
    by_phase: dict[str, dict[str, object]] = {}
    for key, body in prof.commands.items():
        phase, name = prof.placement(key)
        # A profile that places commands outside `build` names every command with its phase, so the
        # report cannot say `test model, model`; the four that do not keep the bare name they printed.
        label = f"{phase} {name}" if prof.placements else name
        if name in _declared_commands(text, phase):
            kept.append(label)
            continue
        # A body that names its own catalogue task (si#522) is placed as that task; every other one is a
        # `toolchain:run`.
        rest = {k: v for k, v in body.items() if k != "task"}
        by_phase.setdefault(phase, {})[name] = {"task": body.get("task", "toolchain:run"),
                                                "with": {"image": prof.image, **rest}}
        written.append(label)
    # ALL OR NOTHING (si#371). Every phase is spliced into the text before anything is written, so a
    # phase the splice cannot place refuses the whole profile: a `build model` without the `test model`
    # that checks it would be half a toolchain, written silently.
    spliced = listed
    for phase, additions in by_phase.items():
        spliced = _spliced(spliced, additions, path.name, phase)
    if spliced != text:
        path.write_text(spliced, encoding="utf-8")
    _report_listed(language, listed != text)
    log.ok(f"{language}: wrote {len(written)} command(s)"
           + (f" - {', '.join(written)}" if written else ", nothing was missing"))
    for name in kept:
        log.info(f"kept your own '{name}' - scaffolding never overwrites an edited command")
    return 0


def _report_listed(name: str, added: bool) -> None:
    if added:
        log.ok(f"{name}: added to toolchains")
    else:
        log.info(f"{name}: already in toolchains")


#: The top-level `toolchains:` line, and a block-list item under it.
_TOOLCHAINS = re.compile(r"^toolchains:(?P<rest>.*)$")
_ITEM = re.compile(r"^(?P<indent> +)- ")


def _toolchains_spliced(text: str, name: str, where: str) -> str:
    """`text` with `name` in its top-level `toolchains:` list, or `text` itself when it is there already.

    The si#110 splice again: the list is edited as text, so a comment on the line survives. Three shapes
    are read - absent (a line goes in below `product:`), a flow list (`[a, b]`, the brackets are
    rewritten) and a block list (an item goes below the last one) - and anything else is refused by name
    with nothing written. The result is parsed back, and what it names must be exactly what it named
    before plus `name`, so a shape that fooled the scanner ends as a diagnosis.
    """
    import yaml

    def names(document: str) -> tuple[str, ...]:
        try:
            return profiles.declared_toolchains(yaml.safe_load(document) or {}, source=where)
        except (ValueError, yaml.YAMLError) as exc:
            log.die(f"{where}: cannot add '{name}' to toolchains: {exc}")
            raise SystemExit(1) from exc

    if name not in profiles.known_toolchains():
        log.die(f"no toolchain '{name}' - the kernel supports: {', '.join(profiles.known_toolchains())}")
        raise SystemExit(1)
    before = names(text)
    if name in before:
        return text
    lines = text.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if _TOOLCHAINS.match(line.rstrip("\r\n"))), None)
    if at is None:
        product = next((i for i, line in enumerate(lines) if line.startswith("product:")), -1)
        lines.insert(product + 1, f"toolchains: [{name}]\n")
    else:
        head = _TOOLCHAINS.match(lines[at].rstrip("\r\n"))
        assert head is not None   # `at` was found by this very pattern
        rest = head.group("rest")
        flow = re.match(r"^(?P<pre> *\[)(?P<items>[^\]]*)(?P<post>\].*)$", rest)
        if flow:
            items = flow.group("items").strip()
            joined = f"{items}, {name}" if items else name
            ending = lines[at][len(lines[at].rstrip("\r\n")):]
            lines[at] = f"toolchains:{flow.group('pre')}{joined}{flow.group('post')}{ending}"
        elif not rest.split("#")[0].strip():
            last = at
            while last + 1 < len(lines) and _ITEM.match(lines[last + 1]):
                last += 1
            if last == at:
                log.die(f"{where}: 'toolchains:' has no list under it; write `toolchains: [{name}]`")
                raise SystemExit(1)
            item = _ITEM.match(lines[last])
            assert item is not None   # `last` only ever advanced over lines this pattern matched
            indent = item.group("indent")
            lines.insert(last + 1, f"{indent}- {name}\n")
        else:
            log.die(f"{where}: 'toolchains:{rest}' is a shape this command does not edit; "
                    f"add '{name}' by hand")
            raise SystemExit(1)
    spliced = "".join(lines)
    if names(spliced) != (*before, name):
        log.die(f"{where}: adding '{name}' to toolchains would not have produced the list it should")
        raise SystemExit(1)
    return spliced


# --- the splice (si#110): text in, text out, and nothing re-serialised that was not written here ---

#: One `key:` line of a block mapping. The key charset is what a command/group name may be; anything
#: else on the line lands in `rest`, which is how a flow value (`ci: { ... }`) is recognised rather
#: than walked into.
_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<rest>.*)$")

#: The top-level section the build group stands in: `ci:` since si#344, where `build` is a phase of the
#: integration area. The `groups:` form before it no longer loads, so it is not read here either.
_AREA = "ci"


def _declared_commands(text: str, phase: str) -> Mapping[str, object]:
    """The command names already under `ci: <phase>: commands:`, read through the ordinary loader.

    READING is what a plain loader is good at, and the never-clobber rule needs nothing more than the
    names. Only the WRITE goes through the splice.
    """
    data = yaml.safe_load(text) or {}
    node: object = data
    for key in (_AREA, phase, "commands"):
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key)
    return node if isinstance(node, Mapping) else {}


def _spliced(text: str, additions: Mapping[str, object], where: str, phase: str = "build") -> str:
    """`text` with the new commands inserted under its `phase` group, or a refusal that writes nothing.

    The verification at the end is the reason this can be trusted with somebody's manifest: the spliced
    text is parsed back and compared against the data the old loader-based path would have produced. A
    shape that fooled the line scanner therefore ends as a diagnosis, never as a corrupted file.
    """
    raw = text.splitlines(keepends=True)
    lines = [line.rstrip("\r\n") for line in raw]
    place = _place(lines, phase)
    if place is None:
        _refuse(where, additions, indent=6, phase=phase)
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
    if not _same_data(spliced, text, additions, phase):
        _refuse(where, additions, indent=indent, phase=phase)
    return spliced


def _place(lines: list[str], phase: str = "build") -> tuple[int, bool, int, int] | None:
    """Where the new commands go: (the `commands:` line, whether it holds an empty `{}`, the line to
    insert before, the indent to write them at). None when the shape is not the one this can splice."""
    groups = _find(lines, _AREA, 0, len(lines), 0)
    if groups is None or groups[1]:
        return None
    _, groups_end = _extent(lines, groups[0] + 1, 0, len(lines))
    group_indent = _child_indent(lines, groups[0] + 1, groups_end)
    if group_indent is None:
        return None
    build = _find(lines, phase, groups[0] + 1, groups_end, group_indent)
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


class _BlockDumper(yaml.SafeDumper):
    """`safe_dump`, with one exception: a string that contains a newline is written as a literal block.

    WHY THE EXCEPTION IS NOT THE RESHAPING THE DOCSTRING BELOW REFUSES. si#240 put the first multi-line
    value into the profile table - the OpenAPI export program - and `safe_dump`'s default for one is a
    single-quoted FOLDED scalar, where every line break becomes a blank line:

        - 'import importlib, json, pathlib, sys
        <blank>
          module, _, attribute = sys.argv[1].partition(":")
        ...

    It round-trips exactly, and it is unreadable in the file a product is then supposed to own and edit -
    which is the whole premise of scaffolding rather than resolving. `|` renders the same five lines as
    five lines.

    AND IT MOVES NOTHING THAT EXISTED. Measured rather than asserted: no value in any profile carried a
    newline before today, so this representer cannot change one byte of what the scaffolder wrote for
    any earlier command. `test_toolchain_scaffold` holds that.
    """


def _literal_block(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


_BlockDumper.add_representer(str, _literal_block)


def _entries(additions: Mapping[str, object], indent: int) -> list[str]:
    """The commands as manifest text, one block each, indented to sit under `commands:`.

    THE SHAPE IS `safe_dump`'s, unchanged apart from `_BlockDumper` above, and deliberately so: si#110 is
    about not destroying what somebody else wrote, and the block this writes is its own. What that block
    should look like is si#105's question, and answering it here would put a second change in a diff
    whose whole claim is that nothing but the addition moved (`test_case_cpp_chapter` pins the current
    shape).
    """
    out: list[str] = []
    for name, body in additions.items():
        dumped = yaml.dump({name: body}, Dumper=_BlockDumper, sort_keys=False, width=96,
                           default_flow_style=False)
        out += [" " * indent + line if line else line for line in dumped.rstrip("\n").split("\n")]
    return out


def _same_data(spliced: str, text: str, additions: Mapping[str, object], phase: str = "build") -> bool:
    """Does the spliced file carry EXACTLY the original data plus the added commands, and nothing else?"""
    try:
        got = yaml.safe_load(spliced)
    except yaml.YAMLError:
        return False
    want = yaml.safe_load(text) or {}
    groups = want.get(_AREA) or {}
    build = groups.get(phase) or {}
    build["commands"] = {**(build.get("commands") or {}), **additions}
    groups[phase] = build
    want[_AREA] = groups
    return bool(got == want)


def _refuse(where: str, additions: Mapping[str, object], indent: int, phase: str = "build") -> NoReturn:
    """Say where the block was meant to go, hand over the block, and change nothing.

    A shape the splice does not recognise is a manifest somebody wrote by hand in a way this scanner
    cannot read - not a licence to guess. What a reader can act on is the text itself, so it is printed.
    """
    log.info(f"{where}: no `ci:` -> `{phase}:` -> `commands:` block mapping to splice into. "
             f"Paste this under `ci: {phase}: commands:`:")
    print("\n".join(_entries(additions, indent)))
    log.die(f"{where} was left unchanged - a scaffolder that guessed at the shape would corrupt it.")
