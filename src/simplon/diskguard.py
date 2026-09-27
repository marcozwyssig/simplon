"""Docker-disk guard: prune dangling images + build cache when the docker data filesystem runs low, so a
full disk never silently breaks an initdb-style bootstrap or a container deploy. The parse/decision is
simplon.disk; this wires it to the real df probe + prune via a Host. The consuming product owns the
enable toggle + the threshold and calls this.

THREE FUNCTIONS, THREE MOMENTS, and keeping them apart is the whole of si#327's repair:

  * `disk_guard` - best effort, DURING a run: notice a low disk and prune it, then carry on either way.
  * `preflight`  - BEFORE a run: decide whether this machine is fit to start a job on, and say no.
  * `cleanup`    - AFTER a run: give back what this run took, whatever the run's own verdict was.

WHY THE PREFLIGHT DOES NOT REUSE THE GUARD'S PROBE, recorded rather than quietly repaired because the
guard has a consumer (`simplon.labhost`) and changing what it does is a separate argument. The guard probes
with `df -P <dir> 2>/dev/null | tail -1`, and in a pipeline the exit status is `tail`'s, so it is 0 even
when `df` failed; the empty output then parses as "unparseable" and the guard returns 0 - "skip silently".
For a best-effort pruner that is defensible. For a preflight it is the defect this repository hunts: a
machine nobody could measure would report as a machine with room. So the preflight probes WITHOUT a pipe,
keeps `df`'s own exit status, folds stderr into the output so the reason can be printed, and distinguishes
"could not measure" from "fine" - see `simplon.disk.verdict`.
"""
from __future__ import annotations

import shutil

from simplon import disk, log
from simplon.host import Host
from simplon.run import run


#: What the build cache is pruned down to after a job, and the reason there is a filter at all: an
#: unfiltered `builder prune -af` on every run trades a full disk for a cold build every time, which is
#: the cost nobody measures until the pipeline is twice as slow. 24h keeps today's cache and drops the
#: layers no job has touched since yesterday.
CLEANUP_UNTIL = "24h"

#: The filesystem a preflight looks at when the docker data directory cannot be measured - which is the
#: normal state on a runner whose engine arrives through `DELIVERY_DOCKER_BOOTSTRAP` inside the job, so
#: the first step runs before /var/lib/docker exists.
FALLBACK_DIR = "/"


def _probe(host: Host, path: str, min_free: int) -> "tuple[str, int | None, str]":
    """`(state, free-%, the line we read)` for one filesystem - the honest probe described in the head.

    No pipe, so the exit status is `df`'s own; `2>&1` so a refusal is readable in the message instead of
    being sent to /dev/null and reported as "unparseable".
    """
    res = host.sh(f"df -P {path} 2>&1")
    line = (res.out or "").strip().splitlines()[-1:] or [""]
    if not res.ok:
        return disk.UNKNOWN, None, line[0]
    state, free = disk.verdict(line[0], min_free)
    return state, free, line[0]


def preflight(host: Host | None = None, *, min_free_pct: int = disk.DEFAULT_MIN_FREE_PCT,
              docker_data_dir: str = "/var/lib/docker") -> int:
    """Refuse to start a job on a machine that is too full to finish one. 1 when the disk is low.

    THE FAILURE THIS REPLACES was measured on this repository's own CI, twice on one commit: every gate
    green, then `build image` dying eight minutes in with `E: You don't have enough free space in
    /var/cache/apt/archives/`, and on the second run the step ending with `conclusion: null`, no log at
    all and the runner going offline. Neither text mentions a disk. A step that costs one second and says
    "12% free, this job will not finish" is the difference between a diagnosis and an afternoon.

    IT NEEDS NO DOCKER. `df` does not, and a runner whose engine is installed inside the job has no
    docker at the moment this runs - which is exactly when it is most useful.

    AN UNMEASURABLE DISK DOES NOT FAIL THE JOB, and that is a decision rather than an oversight: a
    preflight that blocked every build because `df` changed its output would cost more than the defect it
    guards. It warns instead, and the warning is the part that was missing - see the head.
    """
    host = host or Host()
    state, free, line = _probe(host, docker_data_dir, min_free_pct)
    where = docker_data_dir
    if state == disk.UNKNOWN and docker_data_dir != FALLBACK_DIR:
        state, free, line = _probe(host, FALLBACK_DIR, min_free_pct)
        where = FALLBACK_DIR
    if state == disk.UNKNOWN:
        log.warn(f"could not measure the disk at {where}; this job may still die of a full one. "
                 f"df said: {line or '(nothing)'}")
        return 0
    if state == disk.LOW:
        log.error(f"{where} has {free}% free (< {min_free_pct}%); refusing to start a job that is going "
                  f"to run out. Free space on the runner - `docker system prune -af --filter until=48h`, "
                  f"`docker builder prune -af` - and run it again")
        return 1
    log.ok(f"{where} has {free}% free")
    return 0


def cleanup(*, until: str = CLEANUP_UNTIL) -> int:
    """Give back what this run took: prune the build cache older than `until`. 1 when docker refused.

    NO `--volumes`. A runner with a persistent volume would lose it, and a cleanup step that destroys
    state nobody asked it to destroy is worse than the disk it was freeing.

    IT RETURNS NON-ZERO ON A REFUSAL, and whether that is fatal is the WORKFLOW's call rather than this
    function's - a generated cleanup step carries `continue-on-error:` for exactly that reason. Returning
    0 for a prune that did not happen is the defect this repository hunts, one seam further along.
    """
    if shutil.which("docker") is None:
        return 0
    res = run(["docker", "builder", "prune", "-af", "--filter", f"until={until}"])
    if not res.ok:
        log.warn(f"`docker builder prune` failed (rc={res.rc}); the build cache was NOT reclaimed")
        return 1
    log.ok(f"build cache older than {until} pruned")
    return 0


def disk_guard(host: Host | None = None, *, min_free_pct: int = 15,
               docker_data_dir: str = "/var/lib/docker") -> int:
    """Prune when the docker data fs free-% drops below min_free_pct. Pure decision via simplon.disk;
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
