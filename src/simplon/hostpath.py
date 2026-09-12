"""Where a bind mount really is, asked from inside a container that runs containers (si#201).

THE PROBLEM, AND IT IS THE WHOLE MODULE. Every containerised task this kernel runs is a
`docker run -v <path>:<workdir>`, and the `-v` source is resolved by the DAEMON. On the venv route the
daemon and the kernel share a filesystem, so a path the kernel holds is a path the daemon knows. On
si#201's container route the kernel is itself a container with the socket mounted, and the tree it reads
at `/src` is somewhere else entirely on the host. Handing `/src` to the daemon is not an error there; it
is worse than one.

MEASURED on 2026-09-12, with the tree at `/tmp/wt-201/.scratch/m1` mounted into a kernel container at
`/src`:

    inside the container: docker run --rm -v /src:/x busybox ls -la /x
      total 1
      drwxr-xr-x 2 root root 2 .
      drwxr-xr-x 1 root root 3 ..

    on the host afterwards: ls -ld /src
      drwxr-xr-x 2 root root 2 /src

rc 0, an empty directory, and a root-owned `/src` created on the host that nobody asked for. A gate
handed an empty tree finds nothing to fail on, which is this repository's oldest defect arriving through
a mount. So the wrong answer here is silent and green, and that is why the two paths this module cannot
answer for REFUSE rather than fall back.

HOW THE HOST PATH IS OBTAINED: the launcher passes it in, as ``DELIVERY_HOST_ROOT``. Three ways were
measured before that was chosen, and the other two are recorded because each looks better than it is.

  * `docker inspect $(hostname)` and read `.Mounts` back. It WORKS - 11 ms, and it needs nothing from
    the caller, which is its real attraction: a hand-typed `docker run` would be translated correctly
    too. Two things sink it. It needs a docker CLI at the moment the question is asked, and si#200
    deliberately left the CLI out of the image (the kernel fetches it: 84 MB and 15.0 s, measured on
    this box), so the cheapest question in the kernel would become its most expensive. And it breaks on
    a container whose hostname was set: measured with `--hostname buildbox`, `docker inspect buildbox`
    answers `Error: No such object: buildbox`.
  * `/proc/self/mountinfo`. No CLI, no daemon, and WRONG in a way a reader would not look for. The
    field is the source path relative to the source FILESYSTEM's root, not to the host's. Measured:
    for a tree at `/tmp/wt-201/.scratch/m1` on a host where `/tmp` is a tmpfs, mountinfo says
    `/wt-201/.scratch/m1`. The `/tmp` prefix is simply not in the file, and a bind mount of that path
    would be an empty directory again.
  * the environment variable. It costs nothing, and the process that sets it - the launcher - is the
    one process that provably knows the answer, because it wrote the `-v` itself.

WHAT BREAKS IT: nobody setting it. `docker run <kernel image> ...` typed by hand reaches exactly the
measurement at the top of this docstring, so `translate` asks whether it is in a container at all and
refuses by name when it is and the variable is absent. What does NOT break it, contrary to the shape of
the question: a symlinked checkout. `pwd` in the launcher yields the LOGICAL path and the daemon
resolves symlinks on the host itself, so both halves name a path the daemon can open - driven with a
symlink to the tree, and the mount carried the tree. Nor a launcher invoked from a subdirectory: the
launcher derives its root from `BASH_SOURCE` and `cd`s there before anything else, on both routes.

WHAT THE CONTAINER ROUTE THEREFORE CANNOT DO, stated rather than left to be met. A container can hand a
sibling only a path the DAEMON can resolve, and on this route the product tree is the only thing mounted
- so a task that mounts a directory outside the tree refuses here and works on the venv route. Every
mount site in this kernel is inside the tree today; the one that was not was the mermaid scratch, and
si#201 moved it into `build/` rather than special-case it. What is left is simplon's own e2e suite:
thirteen tests scaffold a fixture product into pytest's temp directory and really run its gate, and those
meet the refusal below. The trigger that reopens this is a PRODUCT task that must mount something outside
its tree; the answer then is a second mount on the kernel container and a list of mappings here, not a
guess.

WHAT WAS REJECTED: mounting the tree at its own host path (`-v $ROOT:$ROOT`), which makes translation
unnecessary because the two paths are equal. It is the smaller change and it is not the honest one. It
does not solve the sibling-container problem, it arranges for it not to arise, and it arranges that only
where the host path happens to be a legal Linux mount destination - on Windows a `C:` drive path is not,
so `simplon.cmd` would need the translation anyway and there would be two shapes for one route. si#200's
Dockerfile also states `/src` as the place a product's tree is expected, and a launcher that mounted
somewhere else would make that sentence false.
"""
from __future__ import annotations

import os
from pathlib import Path

from simplon import log

#: The ONE bind mount, stated as the pair it is: where the host directory is, and where this process sees
#: it. Both are written by the launcher's container route and by nothing else; both absent on the venv
#: route, which is what makes that route's argv unchanged.
#:
#: TWO VARIABLES RATHER THAN ONE, and that was a measured correction. The first version read the
#: container side off `context.current().root`, on the reasoning that the product root IS the mount.
#: It is, in production - and `test_suites_command_gate_e2e` registers a context at a scaffolded fixture
#: INSIDE the mount, at which point the assumption silently mapped that subdirectory onto the host root
#: and a sibling container was handed the wrong tree: `CMake Error: The source directory "/src" does not
#: appear to contain CMakeLists.txt`, from a test that was only ever about a refusal. A product scaffolded
#: into a subdirectory of the mount would meet the same thing with no test in the room. A mapping is two
#: paths; carrying one and inferring the other is what made it wrong.
HOST_ROOT_ENV = "DELIVERY_HOST_ROOT"
MOUNT_ROOT_ENV = "DELIVERY_MOUNT_ROOT"

#: The files a container runtime writes into its own filesystem. Docker's is `/.dockerenv` (measured
#: present in the kernel image); podman and the other OCI runtimes write `/run/.containerenv`. Neither is
#: a promise, which is why they are only consulted to sharpen a REFUSAL - a missing marker never turns a
#: translation on, it only costs the reader a better sentence.
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")


def in_a_container() -> bool:
    """Whether this process is running inside a container runtime, as far as its filesystem shows."""
    return any(os.path.exists(marker) for marker in CONTAINER_MARKERS)


def _drive_letter(value: str) -> bool:
    """Whether `value` is a Windows drive path (`C:\\...` or `C:/...`). Pure."""
    return len(value) > 1 and value[0].isalpha() and value[1] == ":"


def declared_mount() -> tuple[str, str]:
    """The declared bind mount as `(host side, container side)`, `("", "")` when none was declared."""
    return (os.environ.get(HOST_ROOT_ENV, "").strip(),
            os.environ.get(MOUNT_ROOT_ENV, "").strip())


def translate(path: str | Path) -> str:
    """The `-v` SOURCE for `path`: unchanged on the venv route, moved onto the host side of the mount on
    the container route, and a refusal when it can be neither.

    Every mount source in this kernel goes through here, so a task never has to know which route it is
    on. The venv route returns the string it was given, which is what keeps the two routes' argv
    byte-identical rather than merely equivalent.
    """
    given = str(path)
    host, mount = declared_mount()
    if not host and not mount:
        if in_a_container():
            log.die(
                f"this kernel is running in a container and was not told where its tree is on the HOST, "
                f"so it cannot mount {given} into a sibling container. The daemon would resolve that "
                f"path against the host, find nothing, and CREATE an empty directory there - measured, "
                f"rc 0 and no message. Set {HOST_ROOT_ENV} and {MOUNT_ROOT_ENV} to the two sides of the "
                f"bind mount (the launcher's container route does this for you)")
        return given
    if not host or not mount:
        log.die(f"a bind mount is two paths and only one is declared ({HOST_ROOT_ENV}='{host}', "
                f"{MOUNT_ROOT_ENV}='{mount}'). Half a mapping cannot be applied to {given}, and guessing "
                f"the other half is how a container gets handed the wrong tree")
    for name, value in ((HOST_ROOT_ENV, host), (MOUNT_ROOT_ENV, mount)):
        if _drive_letter(value):
            # THE WINDOWS GAP, named where somebody meets it rather than left to the message below,
            # which would blame a named volume for something else entirely. `<product>.cmd` sets
            # HOST_ROOT from `%~dp0`, so on Windows it is `C:\...`; this kernel is then running in a
            # LINUX container, where nothing joins a drive-letter path onto a POSIX one and where the
            # daemon-side spelling Docker Desktop wants for such a mount is not a thing that can be
            # decided without a Windows to drive it. There was none for si#201.
            log.die(f"{name} is '{value}', a Windows drive path, and this kernel is running in a Linux "
                    f"container - so there is no path it can hand the daemon for {given}. The container "
                    f"route's Windows half is UNDRIVEN (see the launcher's own note); use "
                    f"DELIVERY_ROUTE=venv there until somebody can measure what Docker Desktop's daemon "
                    f"accepts as a `-v` source from inside a Linux container")
        if not value.startswith("/"):
            log.die(f"{name} is '{value}', which is not an absolute path - docker reads a `-v` source "
                    f"without a leading slash as a NAMED VOLUME, so this would mount an empty volume "
                    f"instead of the tree")
    # NORMALISED FIRST, lexically. `relative_to` compares path COMPONENTS, which is right for the case
    # that matters - `/srcfoo` is refused against a `/src` mount, where a string prefix test would have
    # passed it - but it does not fold `..` away: `/src/a/../../etc` came through as `<host>/a/../../etc`,
    # which the daemon then resolves OUTSIDE the mount. No caller in this kernel builds such a path;
    # `normpath` costs one call and removes the question rather than leaving it to the next one who does.
    # Lexical rather than `resolve()` on purpose: resolve() reads the filesystem and would answer about
    # the CONTAINER's symlinks, which are not the ones the daemon will follow.
    try:
        inside = Path(os.path.normpath(given)).relative_to(mount)
    except ValueError:
        log.die(f"cannot mount {given} from inside this container: it is not under {mount}, which is the "
                f"only directory bind-mounted from the host ({host}), so the daemon has no path for it. "
                f"A directory a container hands to another container has to live in the mount")
    return str(Path(host).joinpath(*inside.parts))
