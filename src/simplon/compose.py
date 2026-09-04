"""Pure readings of a RESOLVED compose configuration - the document `docker compose config --format
json` prints (platform#43, the mechanism half of biz-cockpit#74).

Every function here takes that document and returns a decision: no subprocess, no filesystem, no Typer.
The split is the whole point. A deployment command has to judge what compose ACTUALLY RESOLVED rather
than what the env files say, because the shell environment overrides an `--env-file` - an exported
credential, or a secrets file dropped into the wrong directory, is invisible in the files and present in
the resolution. Keeping the judgement pure is what makes it testable without a docker daemon, and reading
the document needs none either (`config` is client-side), so a product's guards also work on a stopped
host.

Mechanism only, in both directions: the kernel knows HOW to read a resolved document, the product says
WHICH service, WHICH variables, WHICH mount point and WHICH uid it cares about. No service name, no
health path, no credential list and no container-side mount appears below - all of it arrives as
arguments, because all of it is product data ("gleiche Maschine, anderer Katalog").

The two preflights this exists for, both learned on a real deployment:

  * A missing bind SOURCE. Docker creates it - as a ROOT-owned directory - and an image running as an
    ordinary uid then starts and fails on its first write, a fault that surfaces at runtime, remotely,
    and reads like anything but its cause. `missing_bind_sources` and `foreign_owner_bind_sources` let a
    product refuse before `up` and name the directories.
  * A variable that must not carry a value. `assigned_variables` says which of the product's own list
    resolve to one; whether that is fatal, a warning or fine is the product's RULE, never the kernel's.
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath

# A published port bound to every interface (or to none in particular) is reached on the loopback: the
# host running the orchestrator is the host that published it. `::` is the IPv6 spelling of the same.
_ANY_HOST = ("", "0.0.0.0", "::", "[::]")


def service(config: Mapping[str, object], name: str) -> Mapping[str, object]:
    """One service's resolved definition, or an empty mapping when the document has no such service."""
    services = config.get("services") or {}
    if not isinstance(services, Mapping):
        return {}
    found = services.get(name) or {}
    return found if isinstance(found, Mapping) else {}


def service_environment(config: Mapping[str, object], name: str) -> dict[str, str]:
    """The resolved environment of one service, as plain strings. Compose renders `null` for a variable
    passed through WITHOUT a value; that is 'unset', so it reads as the empty string here and never as
    the string 'None' - which would otherwise look like a value to every check downstream."""
    raw = service(config, name).get("environment") or {}
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): ("" if value is None else str(value)) for key, value in raw.items()}


def assigned_variables(resolved: Mapping[str, str], keys: Iterable[str]) -> list[str]:
    """Which of `keys` actually carry a value in a resolved service environment, in the order of `keys`.

    The kernel's half of a "this instance must not see those variables" guard: a product hands in the
    list it considers dangerous (credentials that switch a fake adapter for a real client, a flag that
    arms a destructive path) and gets back the ones that are set. Whitespace is not a value; a variable
    absent from the environment is not set. What to DO about a non-empty answer - die, warn, or carry on
    behind an escape hatch - is the product's decision and stays there."""
    return [key for key in keys if str(resolved.get(key) or "").strip()]


def bind_sources(config: Mapping[str, object], name: str, *,
                 writable_only: bool = False) -> dict[str, str]:
    """`container target -> host source` for every bind mount of one service, in declaration order.

    Named volumes and tmpfs are not bind mounts and never appear. `writable_only` drops the read-only
    mounts: the container cannot write to them, so their ownership on the host is nobody's business."""
    volumes = service(config, name).get("volumes") or []
    if not isinstance(volumes, Iterable):
        return {}
    sources: dict[str, str] = {}
    for volume in volumes:
        if not isinstance(volume, Mapping) or volume.get("type") != "bind":
            continue
        if writable_only and volume.get("read_only"):
            continue
        target, source = volume.get("target"), volume.get("source")
        if target and source:
            sources[str(target)] = str(source)
    return sources


def missing_bind_sources(config: Mapping[str, object], name: str, exists) -> list[str]:
    """The host-side directories a service binds that do not exist yet, deduplicated and sorted.

    `exists` is injected (normally `os.path.exists`) so the decision stays pure. It is worth refusing on:
    Docker CREATES a missing bind source as a root-owned directory, and an image running as an ordinary
    uid then starts and fails on its first write - a miserable thing to diagnose over a VPN, and a
    trivial thing to name beforehand."""
    return sorted({source for source in bind_sources(config, name).values() if not exists(source)})


def foreign_owner_bind_sources(config: Mapping[str, object], name: str, owner, *,
                               uid: int) -> list[str]:
    """The host directories a service WRITES into that are not owned by `uid` - the uid the image runs
    as, which only the product knows (its Dockerfile picked it).

    `owner` is injected (normally `path -> os.stat(path).st_uid`) and returns None for a path that cannot
    be read; that is the missing case, which `missing_bind_sources` reports instead. Advisory by nature:
    exactly right on a Linux host, meaningless on a Docker Desktop or colima machine, which maps
    ownership through its own VM. A product should warn on this list, not die on it."""
    found = {source: owner(source)
             for source in bind_sources(config, name, writable_only=True).values()}
    return sorted(source for source, value in found.items() if value is not None and value != uid)


def published_endpoint(config: Mapping[str, object], name: str) -> tuple[str, int]:
    """`(host, port)` to reach a service's first published TCP port FROM THE HOST.

    A binding to every interface (or with no host part at all) is reached on the loopback; a binding
    pinned to one address is reached on exactly that address - which is how a probe keeps telling the
    truth once an instance is pinned to a VPN interface. UDP publications are skipped, and a published
    RANGE is entered at its first port. Raises LookupError when the service publishes no TCP port at all,
    so a caller reports "nothing to reach" instead of probing an invented address."""
    ports = service(config, name).get("ports") or []
    for entry in ports if isinstance(ports, Iterable) else []:
        if not isinstance(entry, Mapping) or entry.get("protocol") not in (None, "tcp"):
            continue
        published = str(entry.get("published") or "").split("-")[0].strip()
        if not published.isdigit():
            continue
        host = str(entry.get("host_ip") or "").strip()
        return ("127.0.0.1" if host in _ANY_HOST else host, int(published))
    raise LookupError(f"service '{name}' publishes no TCP port in the resolved configuration")


def health_url(config: Mapping[str, object], name: str, path: str, *, scheme: str = "http") -> str:
    """The URL that answers for a running instance, derived from what compose ACTUALLY published.

    The probe address is then configured nowhere: it follows the instance's published port and bind
    address instead of duplicating them in an env file that can drift. `path` and the service `name` are
    the product's (its liveness route, its front door); `scheme` covers a stack terminating TLS itself."""
    host, port = published_endpoint(config, name)
    return f"{scheme}://{host}:{port}{path}"


def snapshot_container_path(snapshot: str, host_source: str | None, mount: str) -> str:
    """Translate a file an operator names on the HOST into the path the CONTAINER sees under `mount`.

    A one-off container doing the work (a restore, an import) sees the host's directory as `mount` and
    nothing else of the host, so an operator's tab-completed path has to be rewritten before it means
    anything inside. Accepted, in this order:

      * a bare file name - the normal case, taken as relative to `mount`;
      * a path already expressed container-side (below `mount`) - passed through;
      * an absolute HOST path inside `host_source` (the bind source behind `mount`, read out of the
        resolved configuration) - rewritten onto `mount`.

    Anything else raises ValueError: a host path outside that directory is invisible to the container,
    and silently reading the wrong tree is exactly the accident worth failing on."""
    candidate = snapshot.strip()
    if not candidate:
        raise ValueError("no snapshot given")
    mount_path = PurePosixPath(mount)
    if os.path.isabs(candidate):
        pure = PurePosixPath(candidate)
        if pure == mount_path:
            raise ValueError(f"{candidate} is the mounted directory, not a file in it")
        if _is_relative_to(pure, mount_path):
            return str(pure)
        source = PurePosixPath(host_source) if host_source else None
        if source is not None and _is_relative_to(pure, source):
            return str(mount_path / pure.relative_to(source))
        raise ValueError(
            f"{candidate} is not inside this environment's directory"
            + (f" ({host_source})" if host_source else "")
            + f"; the container only sees {mount}. Copy the file there, or name it by file name.")
    relative = PurePosixPath(candidate)
    if any(part == ".." for part in relative.parts):
        raise ValueError(f"{candidate} escapes the mounted directory")
    return str(mount_path / relative)


def _is_relative_to(path: PurePosixPath, other: PurePosixPath) -> bool:
    """`PurePath.is_relative_to` without the deprecation dance, and False for equality."""
    return path != other and other in path.parents
