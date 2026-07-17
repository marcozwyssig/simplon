"""Docker-disk guard: prune dangling images + build cache when the docker data filesystem runs low, so a
full disk never silently breaks an initdb-style bootstrap or a container deploy. The parse/decision is
platformcore.disk; this wires it to the real df probe + prune via a Host. The consuming product owns the
enable toggle + the threshold and calls this.
"""
from __future__ import annotations

import shutil

from platformcore import disk, log
from platformcore.host import Host
from platformcore.run import run


def disk_guard(host: Host | None = None, *, min_free_pct: int = 15,
               docker_data_dir: str = "/var/lib/docker") -> int:
    """Prune when the docker data fs free-% drops below min_free_pct. Pure decision via platformcore.disk;
    the df probe + prune are the only I/O. A docker-less host is a no-op. Returns 0 (best-effort)."""
    if shutil.which("docker") is None:
        return 0
    host = host or Host()
    res = host.sh(f"df -P {docker_data_dir} 2>/dev/null | tail -1")
    if not res.ok:
        return 0
    used = disk.used_pct(res.out or "")
    if used is None:  # unparseable -> skip silently
        return 0
    free = disk.free_pct(used)
    if not disk.should_prune(free, min_free_pct):
        return 0
    log.warn(f"docker data disk {free}% free (< {min_free_pct}%); pruning dangling images + build cache")
    run(["docker", "image", "prune", "-f"])
    run(["docker", "builder", "prune", "-f"])
    res = host.sh(f"df -P {docker_data_dir} 2>/dev/null | tail -1")
    used = disk.used_pct(res.out or "")
    if used is None:
        log.ok("prune done")
    else:
        log.ok(f"prune done; docker data disk now {disk.free_pct(used)}% free")
    return 0
