"""clablifecycle - "bring a RENDERED containerlab topology up/down on a labhost" (netctl#731 Strand 3).

The dev-lab SUBSTRATE's lifecycle layer: given a rendered ``*.clab.yml`` (Strand 2's `clabrender` output)
and a `BringUpSpec` (the injected inputs - output dir, topology + container names, the OOB bridge list,
retries, and whether the lab carries an x86 kind), it drives the load-bearing bring-up sequence
(OOB bridges -> amd64 emulation -> binfmt watchdog -> `containerlab deploy` with retry -> verdict) and the
teardown (`containerlab destroy` -> name-prefix sweep -> OOB bridges down). The mechanism is generic; every
product specific is in the spec, so the module names NO product.

Extracted from netctl's `orchestrator.lab` (the `_clab` wrapper, `oob_up`/`oob_down`, `up_deploy`, `down`,
`_sweep_leftovers`, `_lab_container_count`, `up_verdict`). The DECISIONS were already unit-tested in
`delivery.labnet` (`deploy_verdict`, the OOB-bridge snippets); this is the I/O wiring around them + the amd64
watchdog from `delivery.labhost`.

The degraded-file contract. A product runs `deploy()` and `up_verdict()` in SEPARATE processes (netctl's
`_up deploy` / `_up finish` sub-phases): `deploy()` records a partial-deploy degradation via
`delivery.degraded.add`, which appends to the shared `DELIVERY_DEGRADED_FILE`, and a later `up_verdict()`
reads the union back (`degraded.items()`). So the substrate writes and the product's finish phase reads the
SAME degraded channel across processes - the coupling that must survive the extraction verbatim.

"Lab up" is a CONTAINER-COUNT verdict, never an /api probe. `deploy()` declares success from
`containerlab`'s own rc and, on a non-clean deploy, from the lab container count via
`labnet.deploy_verdict` - it knows nothing about a controller REST endpoint. The product runs its own
convergence waits (netctl's `wait_stable`/`wait_dataplane_ready`) AFTER, against its controllers; those
STAY product-side. Keeping the substrate's liveness signal purely structural is the anti-leak invariant
(Strand 4 falsifies against it).
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from delivery import degraded, labhost, labnet, log
from delivery.host import Host
from delivery.run import Result


@dataclass(frozen=True)
class BringUpSpec:
    """The injected inputs a product hands the substrate to bring ITS rendered lab up/down. Everything the
    lifecycle needs that would otherwise name a product: the render output location, the clab topology +
    container-name identity, the OOB bridge list (a product derives it from its sites), the deploy retry
    budget, and whether the lab carries an x86 kind (so the amd64 emulation + watchdog run). The substrate
    reads only these - it never imports the product's paths/manifest.
    """

    output_dir: Path                 # where the rendered *.clab.yml + configs live (clab's cwd)
    topology_file: str               # the clab topology filename (containerlab -t argument)
    topology_path: Path              # its full path (down's existence guard before clab destroy)
    container_prefix: str            # `docker ps --filter name=` prefix scoping this lab's containers
    mgmt_network: str                # the mgmt docker network to sweep on teardown
    bridges: tuple[str, ...] = ()    # the OOB management bridge names (product derives them per site)
    deploy_retries: int = 3          # clab deploy attempts (the x86 binfmt-flush race self-heals on retry)
    amd64_emulation: bool = False    # register amd64 binfmt + the watchdog (the lab carries an x86 kind)


# --- containerlab + docker plumbing -----------------------------------------------------------------

def _clab(host: Host, args: list[str], spec: BringUpSpec, *, capture: bool = False) -> Result:
    """Run containerlab where it can actually run: natively on Linux, inside the colima VM on macOS (same
    path, since colima mounts /Users). capture=False streams the deploy output live to the terminal and
    still returns the real rc. On macOS clab needs root (`sudo`); on Linux the sudo binary is overridable
    via $SUDO (a rootless-docker CI runner sets it empty)."""
    inner = "containerlab " + " ".join(shlex.quote(a) for a in args)
    if host.is_darwin:
        script = f"cd {shlex.quote(str(spec.output_dir))} && sudo {inner}"
    else:
        sudo = os.environ.get("SUDO", "sudo")
        script = f"cd {shlex.quote(str(spec.output_dir))} && {sudo} {inner}".strip()
    return host.sh(script, capture=capture)


def container_count(host: Host, container_prefix: str) -> int:
    """How many of this lab's containers are up (running), by name prefix."""
    res = host.docker("ps", "--filter", f"name={container_prefix}", "-q")
    return len([ln for ln in (res.out or "").splitlines() if ln.strip()])


# --- OOB management bridges -------------------------------------------------------------------------

def oob_up(host: Host, bridges: tuple[str, ...] | list[str]) -> None:
    """Create the given OOB management bridges in the docker host (idempotent). A bridge that cannot be
    created is degraded, not fatal (the rest of the lab still comes up). The bridge NAMES are the product's
    (it derives them per site + instance); the substrate just applies the shared labnet snippet."""
    for bridge in bridges:
        if host.sh(labnet.oob_bridge_up_snippet(bridge)).ok:
            log.ok(f"OOB bridge {bridge} ready")
        else:
            degraded.add(f"OOB bridge {bridge} not created (devices/sidecar behind it may not reach mgmt)")


def oob_down(host: Host, bridges: tuple[str, ...] | list[str]) -> None:
    for bridge in bridges:
        host.sh(labnet.oob_bridge_down_snippet(bridge))


# --- deploy (the load-bearing bring-up core, today's up_deploy) -------------------------------------

def deploy(host: Host, spec: BringUpSpec) -> int:
    """Bring the rendered topology up: OOB bridges, then the LOAD-BEARING amd64-emulation -> watchdog ->
    clab-deploy(retry) sequence, then the deploy verdict. ONE atomic phase - the ordering must never split.
    A TOTAL failure log.die's (aborts the product's pipeline via its stop_on_failure); a PARTIAL deploy
    records a degraded note (in the shared DELIVERY_DEGRADED_FILE) and returns 0, left to up_verdict.

    amd64 emulation + the binfmt watchdog run only when the lab carries an x86 kind (`spec.amd64_emulation`,
    a product-derived flag) AND the host is a macOS Colima VM (the labhost functions self-gate on that); the
    substrate never names a specific x86 kind. A failed deploy is RETRIED, each attempt re-running
    `--reconfigure` under the watchdog, so a lost binfmt-flush race self-heals."""
    log.info("creating the OOB management bridges")
    oob_up(host, spec.bridges)

    # ORDER IS LOAD-BEARING: register amd64 emulation, start the watchdog, then deploy under it. lima
    # flushes binfmt when the x86 containers (re)start; the watchdog re-registers the handler within
    # microseconds so the x86 binary catches a live one. --reconfigure makes the deploy idempotent.
    if spec.amd64_emulation:
        labhost.ensure_amd64_emulation(host)
    log.info("deploying the containerlab topology")
    if spec.amd64_emulation:
        labhost.binfmt_watchdog_start(host)
    dmax = spec.deploy_retries
    deployed = False
    for attempt in range(1, dmax + 1):
        if _clab(host, ["deploy", "-t", spec.topology_file, "--reconfigure"], spec).ok:
            deployed = True
            break
        if attempt < dmax:
            log.warn(f"deploy attempt {attempt}/{dmax} did not complete; redeploying (e.g. the x86 amd64 "
                     "emulation race, or a missing image - see the clab ERROR above)")
    if spec.amd64_emulation:
        labhost.binfmt_watchdog_stop(host)

    # Never report a false 'lab up'. A TOTAL failure (no lab containers) is fatal; a PARTIAL deploy (an
    # accepted flake floor) is degraded and left to up_verdict. Decision: labnet.deploy_verdict.
    if not deployed:
        count = container_count(host, spec.container_prefix)
        verdict = labnet.deploy_verdict(deployed, count)
        if verdict == "die":
            log.die(f"containerlab deploy failed on all {dmax} attempt(s) and NO lab containers exist - "
                    "see the clab ERROR above (a missing image? build the images first)")
        degraded.add(f"containerlab deploy did not complete cleanly (only {count} container(s) up); "
                     "see the clab ERROR above")
    return 0


# --- down (destroy + name-prefix sweep, today's down) -----------------------------------------------

def down(host: Host, spec: BringUpSpec) -> int:
    """Destroy the containerlab topology (with --cleanup so any NVRAM is wiped and a redeploy imports the
    regenerated startup-config) and remove the OOB bridges."""
    # clab destroy needs the RENDERED topology file; on a fresh checkout (CI) it does not exist yet -
    # clab then treats the name as a URL, destroys NOTHING and down used to still report OK (#525).
    # Only run it when the file is there; the name-based sweep below cleans up either way.
    if spec.topology_path.exists():
        log.info("destroying the containerlab topology")
        _clab(host, ["destroy", "-t", spec.topology_file, "--cleanup"], spec)
    else:
        log.warn(f"no rendered topology at {spec.topology_path}; skipping clab destroy")
    sweep_leftovers(host, spec)
    log.info("removing the OOB management bridges")
    oob_down(host, spec.bridges)
    log.ok("lab down")
    return 0


def sweep_leftovers(host: Host, spec: BringUpSpec) -> None:
    """Belt to clab's braces (#525): remove this lab's containers and mgmt docker network BY NAME,
    independent of any rendered topology file. Without this, a killed job leaves the mgmt network behind
    across CI jobs - and when its subnet shadows the runner host's own LAN (#523), that leftover alone keeps
    the runner's entire egress dead. Idempotent: a clean host is a no-op (the network rm on a non-existent
    network just errors quietly)."""
    res = host.docker("ps", "-aq", "--filter", f"name={spec.container_prefix}")
    ids = res.out.split() if res.ok else []
    if ids:
        log.info(f"removing {len(ids)} leftover lab container(s) by name prefix {spec.container_prefix}")
        host.docker("rm", "-f", *ids)
    host.docker("network", "rm", spec.mgmt_network)


# --- the authoritative bring-up verdict (today's up_verdict) ----------------------------------------

def up_verdict(*, strict: bool = False) -> int:
    """The authoritative bring-up verdict: clean -> 'lab up' (0); any degraded condition -> warn each and
    (when `strict`) fail. Reads the shared cross-process degraded channel (`degraded.items()`), so a
    degradation recorded by the deploy phase (a separate process) still counts here. `strict` is the
    product's toggle (netctl's NETCTL_STRICT_UP), passed in - the substrate names no product env var."""
    items = degraded.items()
    if not items:
        log.ok("lab up")
        return 0
    log.warn(f"lab up (degraded): {len(items)} issue(s)")
    for d in items:
        log.warn(f"  - {d}")
    if strict:
        log.die("strict bring-up: degraded, failing (see warnings above)")
    return 0
