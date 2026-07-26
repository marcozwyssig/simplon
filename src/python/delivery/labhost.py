"""labhost - "a Colima VM that runs containerlab, with x86 emulation kept alive" (netctl#731 Strand 3).

This is the dev-lab SUBSTRATE's host layer: the macOS Colima VM lifecycle (sizing / start / resources /
install / remove), the binfmt/Rosetta amd64 watchdog that keeps x86 emulation alive across a lima flush,
and the docker-disk-guard toggle. It is the mechanism a product's `up`/`install` drives; it names NO
product - every product specific (extra dev tooling, the install fallback, the toggle values) is INJECTED.

Extracted from netctl's `orchestrator.hostsetup` + `orchestrator.lab` (the `hostsetup.py`(367) VM-sizing +
install core and the `lab.py` amd64/binfmt/colima-guard set), the same "decisions unit-tested without a VM"
discipline as `disk.py` / `waits.py` / `labnet.py`: the PURE sizing/argv/parse/verdict helpers decide, and
the thin I/O around them (`run`, `Host`) is the only impure part.

Darwin vs Linux. On Linux the lab runs natively and there is no Colima VM, so the VM functions no-op; on
macOS the lab lives in a Colima VM and these drive it via `colima ...` / `colima ssh --`. The OS is a
module-level `IS_DARWIN` flag (self-detected via the stdlib `platform`), which a test overrides to exercise
either path without a real host - exactly the seam netctl's tests used before the extraction.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import time
from typing import Callable

from delivery import diskguard, log
from delivery.host import Host
from delivery.run import run

# Self-detected host platform. Module-level (not a per-call probe) so a test flips it once to drive the
# Darwin or Linux path with no real host - the seam the netctl tests already keyed on (`paths.IS_DARWIN`).
IS_DARWIN = platform.system() == "Darwin"
ARCH = platform.machine()     # 'x86_64' | 'arm64' - drives the Rosetta decision on Apple Silicon
_BYTES_PER_GB = 1024 ** 3


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


# --- pinned VM resources (unit-tested) --------------------------------------------------------------
#
# #425 hypothesis: a controller goes persistently Raft-partitioned when the Colima/lima VM is starved (a
# heavy image build running against the live mesh), so its heartbeats + inter-node gRPC to its peers time
# out and it never rejoins. Mitigation: PIN the VM to explicit, adequate resources. These constants +
# vm_sizing reconcile with the maintainer's known-good
# `colima start --cpu 14 --memory 32 --disk 60 --vm-type vz --mount-type virtiofs` - on the reference
# 16-core / 36 GB host vm_sizing yields exactly 14 CPU / 32 GB; disk + mount-type are pinned here. virtiofs
# is the fast host<->VM mount (far less filesystem I/O overhead than the default sshfs/9p), which is the
# very contention that starts heartbeats timing out under a concurrent build.

VM_MEM_FLOOR_GB = 6         # a smaller VM cannot boot the ~30-container mesh
VM_MEM_CEILING_GB = 32      # the lab does not benefit beyond ~32 GB
VM_MEM_HEADROOM_GB = 4      # leave the host RAM for the IDE / browser
VM_CPU_FLOOR = 2
VM_CPU_HEADROOM = 2         # leave the host 2 cores
VM_DISK_GB = 60             # the ~30-container lab + images + Ratis storage
VM_MOUNT_TYPE = "virtiofs"  # vz-only fast mount; the default mount is the I/O bottleneck (#425)


def vm_sizing(host_mem_gb: int, host_cores: int) -> tuple[int, int]:
    """Size the Colima VM from the host: memory = host RAM minus headroom clamped to [6, 32]; CPU = host
    cores minus headroom, at least 2. A fixed 4 CPU / 8 GB under-provisions the ~30-container lab + the
    qemu-emulated x86 nodes and starves the Raft mesh (#425)."""
    vm_mem = max(VM_MEM_FLOOR_GB, min(VM_MEM_CEILING_GB, host_mem_gb - VM_MEM_HEADROOM_GB))
    vm_cpu = max(VM_CPU_FLOOR, host_cores - VM_CPU_HEADROOM)
    return vm_mem, vm_cpu


def colima_start_argv(vm_cpu: int, vm_mem_gb: int, *, rosetta: bool) -> list[str]:
    """The `colima start` argv that pins the VM to explicit, adequate resources (#425). cpu/mem come from
    vm_sizing; disk + vm-type + mount-type are pinned constants. Static public DNS (not the lima host-DNS
    forwarder) avoids the stale-resolver `000` egress failure after a host network/VPN switch. Pure, so the
    argv shape is unit-tested without ever starting a VM."""
    argv = ["colima", "start",
            "--cpu", str(vm_cpu), "--memory", str(vm_mem_gb), "--disk", str(VM_DISK_GB),
            "--vm-type", "vz", "--mount-type", VM_MOUNT_TYPE,
            "--dns", "1.1.1.1", "--dns", "8.8.8.8"]
    if rosetta:
        argv.append("--vz-rosetta")
    return argv


def parse_colima_resources(list_json: str) -> tuple[int, int, int] | None:
    """Parse `colima list --json` (one JSON object per line) into (cpu, mem_gb, disk_gb) for the lab
    profile, or None when nothing parses (colima absent / no VM). memory + disk are reported in bytes,
    cpus as an int. Pure - unit-tested against a captured colima payload."""
    for line in list_json.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        cpu = int(rec.get("cpus", 0) or 0)
        mem_gb = round(int(rec.get("memory", 0) or 0) / _BYTES_PER_GB)
        disk_gb = round(int(rec.get("disk", 0) or 0) / _BYTES_PER_GB)
        if cpu or mem_gb or disk_gb:
            return cpu, mem_gb, disk_gb
    return None


def vm_underprovisioned(cpu: int, mem_gb: int, disk_gb: int,
                        min_cpu: int, min_mem_gb: int, min_disk_gb: int) -> tuple[str, ...]:
    """The dimensions where an EXISTING VM falls short of what this host should now provision. Empty tuple
    = adequately resourced. Pure so it decides without a VM (#425: an under-resourced reused VM is the
    leading cause of a Raft partition; a resize needs a stop+start, so the caller only warns)."""
    short: list[str] = []
    if cpu < min_cpu:
        short.append("cpu")
    if mem_gb < min_mem_gb:
        short.append("memory")
    if disk_gb < min_disk_gb:
        short.append("disk")
    return tuple(short)


def _host_capacity() -> tuple[int, int]:
    """(host_mem_gb, host_cores) read from sysctl on macOS. Thin I/O around the pure vm_sizing."""
    host_mem_gb = int(run(["sysctl", "-n", "hw.memsize"]).out or "0") // _BYTES_PER_GB
    host_cores = int(run(["sysctl", "-n", "hw.logicalcpu"]).out or "2")
    return host_mem_gb, host_cores


def warn_if_vm_underprovisioned() -> tuple[str, ...]:
    """Detect an EXISTING Colima VM that is under-resourced vs what this host should now provision and warn
    (a resize needs stop+start, so we NEVER auto-apply it mid-lab). No-op off macOS / when no VM parses.
    Returns the short dimensions (for callers/tests). #425 remediation surface: a reused VM silently keeps
    whatever CPU/mem it was first created with, which is how a node ends up starved on repeated up/down."""
    if not IS_DARWIN:
        return ()
    current = parse_colima_resources(run(["colima", "list", "--json"]).out or "")
    if current is None:
        return ()
    want_mem, want_cpu = vm_sizing(*_host_capacity())
    cpu, mem_gb, disk_gb = current
    short = vm_underprovisioned(cpu, mem_gb, disk_gb, want_cpu, want_mem, VM_DISK_GB)
    if short:
        log.warn(f"Colima VM under-resourced ({cpu} CPU / {mem_gb} GB RAM / {disk_gb} GB disk); this host "
                 f"warrants {want_cpu} CPU / {want_mem} GB / {VM_DISK_GB} GB. Short on: {', '.join(short)}. "
                 f"An under-resourced VM starves the Raft mesh (#425). A resize needs a restart: "
                 f"colima stop && colima start --cpu {want_cpu} --memory {want_mem} --disk {VM_DISK_GB} "
                 f"--vm-type vz --mount-type {VM_MOUNT_TYPE}")
    return short


# --- amd64 emulation + the deploy-scoped rosetta watchdog (Darwin only) -----------------------------

def ensure_amd64_emulation(host: Host) -> None:
    """Ensure an F-flagged (container-capable) amd64 binfmt handler exists in the VM, so x86 nodes can
    exec. colima's Rosetta counts; only register qemu as a fallback when neither rosetta nor a qemu-x86_64
    F-handler is present. No-op on Linux."""
    if not IS_DARWIN:
        return
    probe = ('grep -q "flags:.*F" /proc/sys/fs/binfmt_misc/rosetta '
             '/proc/sys/fs/binfmt_misc/qemu-x86_64 2>/dev/null')
    if run(["colima", "ssh", "--", "sh", "-c", probe]).ok:
        return
    log.info("registering F-flagged amd64 (qemu) emulation in the colima VM (x86 nodes need it)")
    if run(["colima", "ssh", "--", "sudo", "docker", "run", "--privileged", "--rm",
            "tonistiigi/binfmt", "--install", "amd64"]).ok:
        log.ok("amd64 emulation registered (qemu, F-flagged) - x86 nodes can exec")
    else:
        log.warn("amd64 emulation registration failed; x86 nodes may fail - native-arch sites still come up")


_BINFMT_WD = "/tmp/binfmt-wd.sh"
_QEMU_CONF = "/tmp/qemu-x86_64.binfmt"


def _binfmt_wd_script(handler: str, conf: str) -> str:
    """The watchdog spin loop for one amd64 handler: re-register it from `conf` the instant
    binfmt_misc is flushed. Deploy-scoped; killed by stop. NO sleep - a TIGHT stat-spin keeps the
    re-register gap at ~microseconds so the x86 entrypoint almost always finds a live handler."""
    return f"""#!/bin/sh
# Re-register the {handler} amd64 handler the instant binfmt_misc is flushed (deploy-scoped, #583).
while true; do
  [ -e /proc/sys/fs/binfmt_misc/{handler} ] || cat {conf} > /proc/sys/fs/binfmt_misc/register 2>/dev/null
done
"""


def qemu_binfmt_register_line(proc_entry: str) -> str | None:
    """Rebuild the binfmt_misc register line for the qemu-x86_64 handler from its /proc entry
    (`cat /proc/sys/fs/binfmt_misc/qemu-x86_64`), so the watchdog can re-register the handler
    after a lima flush even on a VM WITHOUT rosetta (#583). Returns None when the entry is
    disabled or unparseable - the caller must then not install a spin loop at all."""
    fields: dict[str, str] = {}
    lines = [ln.strip() for ln in (proc_entry or "").splitlines() if ln.strip()]
    if not lines or lines[0] != "enabled":
        return None
    for ln in lines[1:]:
        key, _, value = ln.partition(" ")
        fields[key.rstrip(":")] = value.strip()
    interpreter, flags = fields.get("interpreter"), fields.get("flags", "")
    offset, magic, mask = fields.get("offset", "0"), fields.get("magic"), fields.get("mask")
    if not (interpreter and magic and mask):
        return None
    def escape(hexstr: str) -> str:
        return "".join(f"\\x{hexstr[i:i + 2]}" for i in range(0, len(hexstr), 2))
    return f":qemu-x86_64:M:{offset}:{escape(magic)}:{escape(mask)}:{interpreter}:{flags}"


def binfmt_watchdog_start(host: Host) -> None:
    """Keep the VM's amd64 binfmt handler alive across the WHOLE deploy: lima flushes binfmt when
    the x86 containers start, and this watchdog re-registers the handler within ~microseconds of any
    flush so the x86 binary catches a live one. Guards rosetta when its lima config exists, else the
    qemu-x86_64 fallback ensure_amd64_emulation registered (#583) - previously the qemu case was
    unguarded and one flush killed the x86 nodes on every deploy attempt."""
    if not (IS_DARWIN and _have("colima")):
        return
    if run(["colima", "ssh", "--", "test", "-e", "/usr/lib/binfmt.d/rosetta.conf"]).ok:
        handler, conf = "rosetta", "/usr/lib/binfmt.d/rosetta.conf"
    else:
        entry = run(["colima", "ssh", "--", "sh", "-c",
                     "cat /proc/sys/fs/binfmt_misc/qemu-x86_64 2>/dev/null"])
        line = qemu_binfmt_register_line(entry.out or "") if entry.ok else None
        if line is None:
            log.warn("neither rosetta.conf nor a readable qemu-x86_64 handler in the VM; "
                     "x86 nodes may exit 126 on a binfmt flush")
            return
        # Persist the reconstructed register line so the spin loop can cat it on every flush.
        run(["colima", "ssh", "--", "sudo", "tee", _QEMU_CONF], input_text=line + "\n")
        handler, conf = "qemu-x86_64", _QEMU_CONF
    run(["colima", "ssh", "--", "sudo", "pkill", "-f", _BINFMT_WD])  # clear any stale watchdog
    log.info(f"starting the {handler} binfmt watchdog for the deploy (keeps x86 amd64 emulation alive)")
    # Write the watchdog script into the VM, then fully detach it (new session + fds off /dev/null) so the
    # ssh channel closes and this returns instead of waiting on the backgrounded process.
    run(["colima", "ssh", "--", "sudo", "tee", _BINFMT_WD], input_text=_binfmt_wd_script(handler, conf))
    launch = f"chmod +x '{_BINFMT_WD}'; setsid '{_BINFMT_WD}' </dev/null >/dev/null 2>&1 &"
    if not run(["colima", "ssh", "--", "sudo", "sh", "-c", launch]).ok:
        log.warn("binfmt watchdog could not start; x86 nodes may exit 126")


def binfmt_watchdog_stop(host: Host) -> None:
    if not (IS_DARWIN and _have("colima")):
        return
    run(["colima", "ssh", "--", "sudo", "sh", "-c",
         f"pkill -f '{_BINFMT_WD}' 2>/dev/null; rm -f '{_BINFMT_WD}' '{_QEMU_CONF}'"])
    log.info("stopped the binfmt watchdog")


# --- colima VM guard (Darwin) -----------------------------------------------------------------------

def ensure_colima_vm(*, install: Callable[[], object]) -> None:
    """`up` needs a running colima VM. Missing colima / never-created VM -> the product's `install`
    callback (a full host install); present but stopped -> start it. So `up` is self-sufficient. No-op on
    Linux. `install` is INJECTED (the substrate never names a product's install entry point); netctl passes
    a callback that runs `./netctl.sh install`."""
    if not IS_DARWIN:
        return
    # `colima delete` (clean vm / reset) removes the lima instance dir, so its presence distinguishes a
    # never-created/deleted VM (-> install) from a merely stopped one.
    vm_present = os.path.isdir(os.path.expanduser("~/.colima/_lima/colima"))
    if not _have("colima") or not vm_present:
        log.warn("Colima VM not present - running install first (one-time setup)")
        install()
        return
    if not run(["colima", "status"]).ok:
        log.info("Colima VM present but stopped - starting it")
        if not run(["colima", "start"]).ok:
            log.warn("colima start failed - running install")
            install()
    # #425: a reused VM keeps whatever CPU/mem it was first created with (a resize needs a stop+start), so
    # an under-resourced VM silently starves the Raft mesh into a partition. Detect + warn only, never
    # resize mid-lab.
    warn_if_vm_underprovisioned()


# --- docker-disk guard toggle ------------------------------------------------------------------------

def disk_guard(host: Host | None = None, *, enabled: bool = True, min_free_pct: int = 15) -> int:
    """Prune docker dangling images + build cache when the data fs is low, so a full disk never silently
    breaks an initdb / a clab deploy. The mechanism is the shared delivery.diskguard; this is the substrate
    TOGGLE the host preflight drives. The consuming product owns the enable flag + the threshold VALUES (it
    reads its own env) and passes them in; `enabled=False` short-circuits before any probe. Returns 0."""
    if not enabled:
        return 0
    return diskguard.disk_guard(host, min_free_pct=min_free_pct)


# --- host install (docker + containerlab; the Colima stack on macOS) --------------------------------

def install_host(*, os_name: str | None = None,
                 extra_macos_tooling: Callable[[], object] | None = None,
                 min_host_mem_gb: int = 8) -> int:
    """Install the host prerequisites for a containerlab dev-lab: Docker + containerlab on Linux, the full
    Colima + docker + containerlab stack on macOS. The SUBSTRATE only; product/host mutations layered on
    top (a submodule init, an /etc/hosts alias) stay in the product's `install`, which wraps this. macOS
    dev-tooling that is NOT the substrate (a test-report renderer, an editor CLI) is injected as
    `extra_macos_tooling`, so the kernel names none of it."""
    os_name = os_name or platform.system()
    if os_name == "Linux":
        return _install_linux()
    if os_name == "Darwin":
        return _install_macos(extra_tooling=extra_macos_tooling, min_host_mem_gb=min_host_mem_gb)
    log.die(f"unsupported OS: {os_name}")
    return 1


def _install_linux() -> int:
    # Docker is installed automatically for parity with the macOS path (#468, where brew provisions
    # colima + docker). The official convenience script handles Ubuntu/Debian/RHEL alike and enables
    # the service; same pipe-into-shell pattern as the containerlab installer below (never $(...)).
    if not _have("docker"):
        log.info("installing Docker (official get.docker.com installer, uses sudo)")
        res = run(["bash", "-c", "curl -fsSL https://get.docker.com | sudo -E sh"], capture=False)
        if not res.ok:
            log.die(f"Docker install failed (rc {res.rc}); install it manually (apt install docker.io, "
                    f"or Docker's official repo) and re-run install")
            return res.rc
        # Trust the binary on PATH, not the exit code (mirrors the macOS colima verification: the
        # installer can exit 0 on a soft failure).
        if not _have("docker"):
            log.die("Docker install failed: no 'docker' binary on PATH after the installer ran. "
                    "Install it manually and re-run install.")
            return 1
        log.ok("docker installed")
        log.warn("for root-less docker add your user to the docker group: "
                 "sudo usermod -aG docker $USER (re-login required)")
    if _have("containerlab"):
        log.ok("containerlab already installed")
        return 0
    log.info("installing containerlab (official installer, uses sudo)")
    # Pipe the installer into bash; do NOT wrap it in $(...), or bash runs the downloaded
    # script TEXT as a command and chokes on the "#!/bin/bash" shebang. Mirrors the VM path below.
    res = run(["bash", "-c", "curl -sL https://get.containerlab.dev | sudo -E bash"], capture=False)
    if not res.ok:
        log.die(f"containerlab install failed (rc {res.rc})")
        return res.rc
    log.ok("containerlab installed")
    return 0


def _fix_docker_credstore() -> None:
    """Drop a stale credsStore=desktop from ~/.docker/config.json (Docker Desktop not installed), which
    otherwise blocks every image pull."""
    cfg = os.path.expanduser("~/.docker/config.json")
    if not os.path.isfile(cfg):
        return
    try:
        data = json.load(open(cfg, encoding="utf-8"))
    except (OSError, ValueError):
        return
    if data.get("credsStore") != "desktop":
        return
    log.warn(f"{cfg} still points credsStore at Docker Desktop (not installed).")
    log.warn("this blocks every image pull incl. the devcontainer. fixing it now.")
    shutil.copy(cfg, f"{cfg}.bak.{int(time.time())}")
    data.pop("credsStore", None)
    with open(cfg, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    log.ok("removed credsStore from ~/.docker/config.json (backup kept next to it)")


def _install_macos(*, extra_tooling: Callable[[], object] | None = None, min_host_mem_gb: int = 8) -> int:
    if not _have("brew"):
        log.die("Homebrew is required on macOS: https://brew.sh")
    log.info("installing Colima + Docker CLI via Homebrew")
    # NONINTERACTIVE=1 is Homebrew's documented non-interactive switch (brew has NO apt-style -y): it
    # suppresses the auto-update and every interactive prompt, so a cold-start bring-up that runs install
    # first never blocks on a Homebrew prompt (#429). Wrapped via `env` because run() takes a plain argv.
    run(["env", "NONINTERACTIVE=1", "brew", "install", "colima", "docker"], capture=False)
    # Verify the install actually produced a colima binary before we try to start a VM. `brew install`
    # exits 0 even when the formula is broken/unavailable, so trust the binary on PATH, not the exit code.
    if not _have("colima"):
        log.die("colima install failed: no 'colima' binary on PATH after 'brew install colima'. "
                "Fix Homebrew (brew doctor) and rerun install.")
        return 1
    log.ok("colima binary present after install")
    # Product/dev tooling that is NOT the substrate (a test-report renderer, an editor CLI) - injected, so
    # the kernel installs none of it by name. Runs at the historical point (after the colima verify, before
    # the credstore fix) so a product keeps its brew ordering.
    if extra_tooling is not None:
        extra_tooling()
    _fix_docker_credstore()

    rosetta = ARCH == "arm64"
    if rosetta:
        log.info("Apple Silicon detected: enabling Rosetta so x86 images can run")
    host_mem_gb, host_cores = _host_capacity()
    if host_mem_gb < min_host_mem_gb:
        log.die(f"this Mac has {host_mem_gb} GB RAM; the lab needs at least {min_host_mem_gb} GB - "
                f"install aborted.")
    vm_mem, vm_cpu = vm_sizing(host_mem_gb, host_cores)
    log.info(f"host: {host_cores} cores / {host_mem_gb} GB  ->  Colima VM: {vm_cpu} CPU / {vm_mem} GB / "
             f"{VM_DISK_GB} GB disk (vz backend, {VM_MOUNT_TYPE} mount)")
    # Pin the VM to static public resolvers instead of the Lima gateway's host-DNS forwarder (that forwarder
    # freezes the host's upstream DNS at VM-creation time, so a later network/VPN switch strands the VM on a
    # dead resolver -> hard `000` egress timeouts), AND to virtiofs + explicit CPU/mem/disk so a heavy build
    # cannot starve the live mesh into a Raft partition (#425). See colima_start_argv for the reconciliation.
    if not run(colima_start_argv(vm_cpu, vm_mem, rosetta=rosetta), capture=False).ok:
        log.warn(f"colima start returned non-zero (it may already be running; resize needs: "
                 f"colima stop && colima start --cpu {vm_cpu} --memory {vm_mem})")
    log.info("installing containerlab inside the Colima VM")
    run(["colima", "ssh", "--", "bash", "-lc", "curl -sL https://get.containerlab.dev | sudo -E bash"], capture=False)
    log.ok("containerlab installed inside the Colima VM")
    log.warn("macOS notes:")
    log.warn(" - build uses the Colima Docker context; up/down/seed run inside the VM.")
    log.warn(" - keep this project under your home dir so its path resolves in the VM.")
    log.warn(" - x86 nodes run under Rosetta (slower). For native ARM speed, use an ARM image.")
    return 0


def remove_colima() -> None:
    """FULLY remove Colima on macOS: stop + delete the VM, uninstall the brew package (which autoremoves
    the lima dependency), and wipe the ~/.colima / ~/.lima host state. `colima delete` alone removes only
    the VM and LEAVES the lima host-side network state, which gets corrupted by a VPN/network switch
    (containers then hit hard `000` egress timeouts while the host stays fine) and survives a plain
    delete && start - which is why a delete alone never cleared it. This deep removal is the only reliable
    fix; a fresh install reinstalls from scratch."""
    log.info("full reset: removing the colima VM, the colima/lima packages and the corrupt host state")
    run(["colima", "stop"], capture=False)          # best-effort; the VM may already be stopped
    run(["colima", "delete", "--force"], capture=False)
    # NONINTERACTIVE=1 here too, so the reset/reinstall path's brew call never prompts / auto-updates (#429).
    run(["env", "NONINTERACTIVE=1", "brew", "uninstall", "colima"], capture=False)   # autoremoves lima
    for state in ("~/.colima", "~/.lima"):
        shutil.rmtree(os.path.expanduser(state), ignore_errors=True)
    log.ok("colima fully removed (VM + packages + host state)")
