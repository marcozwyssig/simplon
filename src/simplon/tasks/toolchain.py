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
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

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

    `version` IS DECLARED AND NOT A `**params` BAG (si#105). Every profile's image is a template carrying
    `{version}`, and `simplon.signatures.bindable` drops a VAR_KEYWORD parameter - so the value a
    command supplied was accepted by the loader, never reached this body, and every language raised
    `KeyError: 'version'` on the first line. A parameter the CLI can carry has to be a parameter.
    """
    prof = profiles.profile(language, version=version)
    path = _manifest_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    commands = data.setdefault("groups", {}).setdefault("build", {}).setdefault("commands", {})
    written, kept = [], []
    for name, body in prof.commands.items():
        if name in commands:
            kept.append(name)
            continue
        commands[name] = {"task": "toolchain:run", "with": {"image": prof.image, **body}}
        written.append(name)
    if written:
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    log.ok(f"{language}: wrote {len(written)} command(s)"
           + (f" - {', '.join(written)}" if written else ", nothing was missing"))
    for name in kept:
        log.info(f"kept your own '{name}' - scaffolding never overwrites an edited command")
    return 0
