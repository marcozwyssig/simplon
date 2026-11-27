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
import stat
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


def prepare(path: Path, label: str, base: Path) -> tuple[Path | None, str]:
    """Make `path` (`directory(base, ...)`) exist as a directory the caller owns: `(resolved path, "")`,
    or `(None, why not)` having run nothing. The caller MOUNTS THE RESOLVED PATH it is handed - the one
    that was checked - rather than spelling the lexical one again.

    `label` opens every sentence (the command and the entry), so the reader is told which declaration to
    look at.

    NO LINK BELOW THE ROOT (si#865 review). A cache root can be shared - a runner's tool cache, or a
    `DELIVERY_DIR_CACHE` other users write to - and somebody who can write it could plant
    `<root>/<product>` or the entry itself as a link to a directory the CALLER owns elsewhere; mounted,
    the container would read and overwrite it. So the product directory and the entry are checked with
    `lstat` - a real directory, the caller's - and the entry's resolved path must still be under the
    resolved root, the rule `hostpath.mount_source` keeps for tree mounts. The root itself is followed:
    it is the caller's own choice, and a runner's tool cache is often a link. What this kernel creates
    below it is mode 0700, so the next caller's directory is nobody else's to plant in.

    AND NO SWAP BETWEEN THE CHECK AND THE MOUNT (second review). Inside a 0700 product directory nobody
    else can rename anything; what is left is the ROOT. A principal who can write it could rename
    `<product>` away after the check and plant a link before `docker run -v`. So the root - followed, with
    `os.stat`, because it is the caller's choice - must be writable by its owner alone, or sticky, which
    stops anybody else renaming the caller's entries (the shape of /tmp).
    """
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as failed:
        return None, (f"{label}: {base} could not be made ({failed}). Point {CACHE_ENV} at a directory you "
                      f"can write, and run this again.")
    mode = os.stat(base).st_mode
    if mode & (stat.S_IWGRP | stat.S_IWOTH) and not mode & stat.S_ISVTX:
        return None, (f"{label} needs the cache root {base} writable by its owner alone or sticky; it is mode "
                      f"{stat.S_IMODE(mode):04o}, so another user could swap what is checked here before it "
                      f"is mounted. Run `chmod g-w,o-w {base}` or `chmod +t {base}`, then run this again.")
    for held in (path.parent, path):
        fault = _held(held, label)
        if fault:
            return None, fault
    resolved = path.resolve()
    if not resolved.is_relative_to(base.resolve()):
        return None, (f"{label} needs {path} under the cache root {base.resolve()}; it resolves to "
                      f"{resolved}. Remove it (rm -rf {path}) and run this again.")
    return resolved, ""


def _held(path: Path, label: str) -> str:
    """Make one level below the root, mode 0700, or rule on what is already there: a real directory the
    caller owns, or a sentence naming the path and the repair."""
    try:
        # mkdir FIRST: up to four steps run at once (`steps.py`), and two of them making one cache must
        # both find it there rather than one losing a race. A plain `mkdir` never follows a link.
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as failed:
        return (f"{label}: {path} could not be made ({failed}). Point {CACHE_ENV} at a directory you can "
                f"write, and run this again.")
    found = os.lstat(path)
    if stat.S_ISLNK(found.st_mode):
        return (f"{label} needs {path} as a real directory; it is a symbolic link. Remove it (rm {path}) "
                f"and run this again.")
    if not stat.S_ISDIR(found.st_mode):
        return f"{label} needs {path} as a directory; it is not one. Remove it and run this again."
    uid = os.getuid() if hasattr(os, "getuid") else None
    if uid is not None and found.st_uid != uid:
        return (f"{label} needs {path} owned by uid {uid}; it is owned by uid {found.st_uid}. It is a cache: "
                f"remove it (rm -rf {path}, a root shell if another uid owns it) and run this again.")
    return ""
