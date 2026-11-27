"""The host-directory caches a container mounts, made as the caller outside the product tree (si#865).

WHY A DIRECTORY AND NOT A VOLUME. Every container this kernel runs over a tree runs as the caller
(`docker.user_args`), and docker creates a new named volume with the owner and mode of the mount point in
the image: root:root 0755 when the image has no such directory. Measured, docker 29.10.1:

    docker run --rm --user 1000:1000 -v v:/cache/gradle busybox:1.36 touch /cache/gradle/x
    touch: /cache/gradle/x: Permission denied

and the same line over a host directory owned by 1000:1000 writes, rc 0, the file 1000:1000 on the host.
A host directory the daemon has to create itself is root-owned too (measured: the same denial), so the
kernel makes it first, as the caller - the rule `toolchain.prepare_mounts` already keeps for `mounts:`.
Decided by Marco on 2026-11-22 (si#865, option (b)); the other option, a one-shot root chown of the
volume, was not taken.

WHY OUTSIDE THE TREE. A cache under the product tree dies with every `clean`, every fresh checkout and
every CI job (actions/checkout empties `build/`), which is what firn#1403 measured: 12 first CI attempts
red resolving everything from the network with an empty Gradle home. So the root follows build:fetch's
download cache (si#600), under a name of its own: `DELIVERY_DIR_CACHE`, else
`$RUNNER_TOOL_CACHE/simplon/caches` on a CI runner, else `${XDG_CACHE_HOME:-$HOME/.cache}/simplon/caches`.
`caches`, not the product name, is the level under `simplon/`, so a product called `dist` cannot land in
the download cache. One entry is `<root>/<product>/<name>-<instance>`: the product and the instance, as
the volume form names its volume (netctl#453's property).

OWNERSHIP IS CHECKED SHALLOW, and the limit is stated rather than hidden. The directory must be the
caller's; its contents are not walked. A Gradle home is tens of thousands of files, and walking it before
every run is the cost `prepare_mounts` declined for a `node_modules`. What the shallow check catches is
the case a shared runner produces: a first job under another uid made the directory. What it misses is a
directory the caller owns with another uid's files inside, which takes a run as another uid into the
caller's own cache root.

NO `off`. A cache the tool was told to use and cannot reach is not a miss here, as it is for the download
cache: the tool would write into a path in the image the caller cannot write. So a directory that cannot
be made is a refusal before the run, never a quiet run without it.

REUSABLE BY ANY CONTAINER-RUNNING TASK: `toolchain:run` is the first caller, `test:image` (si#866) the
next. A caller resolves `root()` once, names each entry with `directory`, calls `prepare` before the run
and mounts `hostpath.translate(path)`, which on the launcher's container route maps the cache mount to its
host side.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

#: The variable naming the cache root, in THIS process' coordinates (the container route's launcher sets
#: it to the mount point it chose). The same name as `hostpath.CACHE_MOUNT_ENV`, which reads one side of
#: the mapping from it; a test holds the two equal.
CACHE_ENV = "DELIVERY_DIR_CACHE"

#: Characters a name may not carry: a separator would land the entry somewhere else under (or above) the
#: root, and `-v` splits its argument on `:`.
_FORBIDDEN = ("/", "\\", ":")


def root(environ: Mapping[str, str] | None = None) -> Path:
    """The cache root the environment names (si#865); the chain `fetchfile.cache_dir` uses, under `caches`."""
    env = os.environ if environ is None else environ
    named = env.get(CACHE_ENV, "").strip()
    if named:
        return Path(named)
    runner = env.get("RUNNER_TOOL_CACHE", "").strip()
    if runner:
        return Path(runner) / "simplon" / "caches"
    base = env.get("XDG_CACHE_HOME", "").strip() or str(Path(env.get("HOME", "").strip() or Path.home()) / ".cache")
    return Path(base) / "simplon" / "caches"


def name_fault(name: str) -> str:
    """Why `name` cannot name one directory under the root, or "" when it can. Pure."""
    if name in ("", ".", "..") or any(c in name for c in _FORBIDDEN):
        return (f"{name!r} is not a plain name - it becomes one directory under the cache root, so it may "
                f"not be empty, `.` or `..`, nor carry `/`, `\\` or `:`")
    return ""


def directory(base: Path, product: str, name: str, instance: str) -> Path:
    """`<base>/<product>/<name>-<instance>`. Pure."""
    return base / product / f"{name}-{instance}"


def prepare(path: Path, label: str) -> str:
    """Make `path` exist as a directory the caller owns, or say why it cannot be, having run nothing.

    `label` opens every sentence (the command and the entry), so the reader is told which declaration to
    look at. Returns "" once the directory is there and the caller's.
    """
    # mkdir FIRST, with exist_ok: up to four steps run at once (`steps.py`), and two of them making one
    # cache must both find it there rather than one of them losing a race to the other.
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        return f"{label} needs {path} as a directory; it is not one. Remove it and run this again."
    except OSError as failed:
        return (f"{label}: {path} could not be made ({failed}). Point {CACHE_ENV} at a directory you can "
                f"write, and run this again.")
    uid = os.getuid() if hasattr(os, "getuid") else None
    owner = path.stat().st_uid
    if uid is not None and owner != uid:
        return (f"{label} needs {path} owned by uid {uid}; it is owned by uid {owner}. It is a cache: "
                f"remove it (rm -rf {path}, a root shell if another uid owns it) and run this again.")
    return ""
