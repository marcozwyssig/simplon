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

from simplon import context, docker, labinstance, log
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


def argv(cfg: Toolchain, root: Path, product: str, instance: str,
         extra: list[str], network: str | None = None) -> list[str]:
    """The full docker argv for one toolchain invocation. PURE: it assembles, it runs nothing.

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


def run_toolchain(body: Mapping[str, object], where: str, extra: list[str],
                  network: str | None = None) -> int:
    """Run one toolchain invocation. Thin: `declared` decides what is legal, `argv` decides the line.

    `network` is the one runtime value a manifest cannot supply - a scratch docker network exists only at
    call time - and it is passed through untouched. Everything else about the run is manifest data.
    """
    cfg = declared(body, where)
    ctx = context.current()
    line = argv(cfg, root=ctx.root, product=ctx.name, instance=labinstance.resolve(),
                extra=extra, network=network)
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
