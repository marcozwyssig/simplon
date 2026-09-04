"""Lab egress isolation: an emulated network on a developer's machine must be UNABLE to reach or affect
anything outside its host (netctl#1004, moved here by netctl#1408, epic netctl#1403).

That a lab must not touch the LAN is not one product's property. It is a property of running a
containerlab mesh on a machine that also has a real network, and it exists because of a real incident
(netctl#1003: the dev lab's mgmt bridge hijacked the LAN's default-gateway ARP path). #1003 fixed the
ADDRESSING; this removes the CAPABILITY. Any `*ctl` product with a clab mesh inherits both the need and
the incident, so the kernel is where the `if` belongs - beside `labnet` and `clablifecycle`, which
already own the substrate.

Two layers, both instance-scoped so concurrent labs never clobber each other:

1. Mgmt-plane default-deny (`install`, hooked after the deploy created the mgmt docker network): two
   DOCKER-USER rules scoped to the mgmt bridge interface - ACCEPT conntrack RELATED,ESTABLISHED
   (replies of externally INITIATED connections, so published-port access from the host AND from other
   LAN machines keeps working), then DROP everything else the containers initiate towards the outside
   (internet AND local LAN). Intra-bridge lab traffic is untouched either way: without br_netfilter it
   never reaches FORWARD, and with it (docker loads the module) it arrives as `-i <br> -o <br>`, which
   the `! -o <br>` match excludes - verified live, container-to-container on an isolated bridge keeps
   working. Docker's embedded DNS (127.0.0.11) needs NO exception: dockerd proxies it on the host side
   of the veth, so container DNS lookups never hit FORWARD (verified live on a throwaway network:
   lookups answer while all egress is dropped). The mgmt network is IPv4-only, so plain iptables
   suffices - no ip6tables leg.

2. ARP hardening on the LAN uplinks (`harden_uplinks`, up-preflight, defence in depth): arp_ignore=1
   (answer ARP only for addresses configured on the incoming interface) + arp_announce=2 (announce with
   the best local source address) on the interface(s) carrying the default route, so host-owned bridge
   IPs are never announced on the LAN regardless of addressing. Idempotent, NOT reverted on down
   (hardening is host state, not lab state). macOS is a no-op: the lab lives in a NATed VM that cannot
   ARP on the physical LAN.

Every rule carries `-m comment --comment "<tag>:<instance>"`; install flushes exactly its own instance's
rules first (re-up safe) and teardown removes exactly its own and nothing else. Failure to install is
FATAL (isolation is a correctness property of the lab, not best-effort); the escape hatch is the
product's isolation env var set to 0, loudly. The rule CONSTRUCTION is pure and unit-tested; the
iptables/sysctl I/O is thin and routed through `delivery.host.Host` so it lands on the docker host (a VM
on macOS, the host itself on Linux), like every other lab-host mutation.

What the PRODUCT supplies, as manifest data read through `delivery.context` - never as an import:

```yaml
lab_egress:
  isolation_env: NETCTL_LAB_ISOLATION   # the escape hatch's spelling; 0 disables the default-deny
  harden_env: NETCTL_HOST_HARDEN        # the ARP hardening's opt-out
  rule_tag: netctl                      # the `-m comment` scope, tagged `<rule_tag>:<instance>`
```

Plus, at the call site rather than as config, the two values only the product's paths adapter can
derive: the mgmt docker network's name for this instance, and the uplink interface list.

There is deliberately NO third, build-network layer, and this is the record of why so it is not tried
again. netctl#1004 drafted a Nexus-only allow-list for the build containers (ACCEPT the mirror address,
ACCEPT replies, DROP the rest) and netctl#1017 asked for a dedicated build network to hang it on.
Measurement killed all three of its premises, so #1017 was closed won't-do and the constructor plus its
unit tests were DELETED rather than left lying around as a half-finished trap:

* it would SEVER the mirror fallback instead of tightening it. The mirror is prepended and the origins
  stay behind it on purpose, so an artefact the mirror does not carry 404s and the build walks on to the
  origin for THAT artefact. The allow-list would arm off the single up-front reachability probe, i.e.
  whenever the mirror answers, and so would cut that per-artefact walk exactly inside the
  Central-429 window the mirror exists to survive;
* the ACCEPT on the mirror address can never match. The mirror is a long-lived service on the docker
  HOST, reached from a container via the bridge gateway, and container-to-host is delivered through
  INPUT while DOCKER-USER hangs off FORWARD. One of the three rules was dead on arrival;
* DROP is the wrong verdict for a build anyway: every severed fallthrough stalls for the full TCP
  connect timeout (~40s) where a REJECT fails instantly.

Reopening this needs new measurements, not the old rules back.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from delivery import context, log
from delivery.host import Host
from delivery.run import Result, run

# The manifest section carrying the three product values above.
MANIFEST_SECTION = "lab_egress"

# Docker's dedicated user hook chain in the filter table's FORWARD path: dockerd creates it, jumps to it
# FIRST from FORWARD, and never flushes it - the documented place for operator rules like these.
DOCKER_USER_CHAIN = "DOCKER-USER"

# The sysctl pairs the uplink hardening applies (layer 2). arp_ignore=1: reply to ARP only for target
# addresses configured on the INCOMING interface, so a lab bridge IP is never claimed on the LAN uplink.
# arp_announce=2: always use the best LOCAL address for the ARP announcement source.
ARP_SYSCTLS = (("arp_ignore", "1"), ("arp_announce", "2"))
IPV4_CONF_ROOT = Path("/proc/sys/net/ipv4/conf")


@dataclass(frozen=True)
class EgressSpec:
    """What a product declares in its manifest's ``lab_egress:`` section."""

    isolation_env: str
    harden_env: str
    rule_tag: str


def spec() -> EgressSpec:
    """Read the product's ``lab_egress:`` section RAW through ``delivery.context``, the same seam the
    build data and `labinstance` use. Fails loudly naming the manifest and the missing key: a silently
    defaulted env-var name would mean the operator's documented escape hatch does nothing, and a
    silently defaulted tag would make one product's teardown delete another's rules."""
    ctx = context.current()
    data = ctx.manifest_data().get(MANIFEST_SECTION)
    if not isinstance(data, dict):
        raise ValueError(f"delivery: manifest {ctx.manifest_path} is missing the '{MANIFEST_SECTION}' section")
    values = {}
    for key in ("isolation_env", "harden_env", "rule_tag"):
        value = str(data.get(key) or "").strip()
        if not value:
            raise ValueError(f"delivery: manifest {ctx.manifest_path} is missing '{MANIFEST_SECTION}.{key}'")
        values[key] = value
    # A tag carrying the separator would make `<tag>:<instance>` ambiguous, and the whole point of the
    # tag is that one instance's teardown can never match another's rule.
    if ":" in values["rule_tag"]:
        raise ValueError(f"delivery: manifest {ctx.manifest_path} '{MANIFEST_SECTION}.rule_tag' must not "
                         f"contain ':' (it is the separator in the rule comment), got {values['rule_tag']!r}")
    return EgressSpec(**values)


# --- pure decisions + rule construction (unit-tested, no I/O) ----------------------------------------

def enabled(env_var: str, env: dict[str, str] | None = None) -> bool:
    """False only on an EXPLICIT `0`. Pure; `env` injectable. Both switches share this: isolation and the
    ARP hardening are ON unless the operator says otherwise in so many words, because the default that
    silently omits a safety property is the one that repeats the incident."""
    src = os.environ if env is None else env
    return (src.get(env_var) or "").strip() != "0"


def rule_comment(tag: str, instance: str) -> str:
    """The `-m comment` tag scoping every rule to ONE instance (`<tag>:<id>`), so install/remove of
    concurrent labs can never touch each other's rules. Pure."""
    return f"{tag}:{instance}"


def bridge_interface(network_id: str) -> str:
    """Docker's default host bridge name for a bridge network: `br-` + the first 12 chars of the network
    id (the same truncation `docker network ls` shows). Pure."""
    return f"br-{network_id[:12]}"


def isolation_rules(bridge: str, tag: str, instance: str) -> list[list[str]]:
    """The exact iptables argvs installing the mgmt-plane default-deny (layer 1), in execution order.
    Inserted at positions 1 and 2 because dockerd seeds DOCKER-USER with a `-j RETURN` that an appended
    rule would sit BEHIND (dead); the resulting chain order is ACCEPT, DROP, RETURN. Both rules match
    `-i <bridge> ! -o <bridge>` - traffic LEAVING the mgmt bridge for anywhere that is not the bridge
    itself - so intra-lab traffic (excluded by `! -o` even when br_netfilter routes it through FORWARD)
    and inbound published-port traffic (whose replies the conntrack ACCEPT covers) are untouched. Pure."""
    comment = rule_comment(tag, instance)
    match = ["-i", bridge, "!", "-o", bridge]
    return [
        ["iptables", "-I", DOCKER_USER_CHAIN, "1", *match,
         "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED",
         "-m", "comment", "--comment", comment, "-j", "ACCEPT"],
        ["iptables", "-I", DOCKER_USER_CHAIN, "2", *match,
         "-m", "comment", "--comment", comment, "-j", "DROP"],
    ]


def deletion_rules(chain_listing: str, tag: str, instance: str) -> list[list[str]]:
    """Given `iptables -S DOCKER-USER` output, the exact `iptables -D ...` argvs removing THIS instance's
    rules and nothing else. Matches the comment TOKEN exactly (shlex-parsed, so the quoting `iptables -S`
    adds is transparent): `netctl:a` never matches `netctl:a1`, and another instance's or another tool's
    rules are never touched. Pure."""
    comment = rule_comment(tag, instance)
    deletions: list[list[str]] = []
    for line in chain_listing.splitlines():
        try:
            tokens = shlex.split(line.strip())
        except ValueError:
            continue  # an unparsable line cannot be one of ours (we only ever write shlex-clean rules)
        if len(tokens) < 3 or tokens[0] != "-A" or tokens[1] != DOCKER_USER_CHAIN:
            continue
        tagged = any(tokens[i] == "--comment" and tokens[i + 1] == comment
                     for i in range(len(tokens) - 1))
        if tagged:
            deletions.append(["iptables", "-D", DOCKER_USER_CHAIN, *tokens[2:]])
    return deletions


# --- thin I/O (iptables on the docker host, sysctl on the Linux uplinks) -----------------------------

def _sudo_prefix(host: Host) -> list[str]:
    """The privilege prefix for iptables, mirroring clablifecycle's: plain `sudo` inside the VM on macOS,
    the overridable $SUDO on Linux (a root shell or rootless setup sets SUDO= empty)."""
    if host.is_darwin:
        return ["sudo"]
    sudo = os.environ.get("SUDO", "sudo").strip()
    return [sudo] if sudo else []


def _iptables(host: Host, argv: list[str]) -> Result:
    """Run one `iptables ...` argv on the docker host (VM-routed on macOS via Host.sh)."""
    return host.sh(shlex.join([*_sudo_prefix(host), *argv]))


def mgmt_bridge(host: Host, network: str) -> str | None:
    """The host bridge interface of a docker bridge network: the explicit
    `com.docker.network.bridge.name` option when the network sets one, else docker's default
    `br-<first 12 of the id>`. None when the network does not exist."""
    res = host.docker("network", "inspect", "-f", "{{.Id}}", network)
    network_id = (res.out or "").strip()
    if not res.ok or not network_id:
        return None
    named = host.docker("network", "inspect", "-f",
                        '{{index .Options "com.docker.network.bridge.name"}}', network)
    custom = (named.out or "").strip() if named.ok else ""
    return custom or bridge_interface(network_id)


def preflight(host: Host | None = None) -> int:
    """up-preflight gate: prove iptables + the DOCKER-USER chain are usable on the docker host BEFORE the
    long deploy, because the post-deploy install is fatal on failure. Fails loudly (no root, missing
    binary, rootless docker without the chain); the product's isolation env var set to 0 skips with a
    prominent warning."""
    product = spec()
    if not enabled(product.isolation_env):
        log.warn(f"{product.isolation_env}=0: lab egress isolation is DISABLED - the mgmt plane will be "
                 f"able to reach and interfere with the LAN and the internet; debugging only")
        return 0
    host = host or Host()
    if not _iptables(host, ["iptables", "-S", DOCKER_USER_CHAIN]).ok:
        log.die(f"iptables cannot list the {DOCKER_USER_CHAIN} chain on the docker host (missing binary, "
                f"no privileges, or a docker without the chain), so the lab egress isolation cannot be "
                f"installed. Isolation is a correctness property since the LAN incident - fix the host, "
                f"or explicitly run without isolation: {product.isolation_env}=0")
    return 0


def install(network: str, instance: str, host: Host | None = None) -> int:
    """Install the mgmt-plane default-deny (layer 1), called right after the deploy created the mgmt
    docker network. `network` is the product's per-instance mgmt network name - the one value only its
    paths adapter can derive. Flushes exactly this instance's own rules first, so a re-`up` never stacks
    duplicates. Any iptables failure is FATAL - a lab that CAN reach the LAN is the incident waiting to
    repeat - with the product's isolation env var set to 0 as the loud escape hatch."""
    product = spec()
    if not enabled(product.isolation_env):
        log.warn(f"{product.isolation_env}=0: skipping the mgmt egress default-deny - this lab CAN reach "
                 f"and interfere with the LAN and the internet")
        return 0
    host = host or Host()
    bridge = mgmt_bridge(host, network)
    if bridge is None:
        log.die(f"mgmt docker network '{network}' not found after the deploy, so the egress isolation "
                f"cannot be installed (a broken deploy? {product.isolation_env}=0 skips isolation)")
    remove(instance, host)  # re-up safe: replace our own rules, never stack them
    for rule in isolation_rules(bridge, product.rule_tag, instance):
        res = _iptables(host, rule)
        if not res.ok:
            log.die(f"could not install the egress isolation on {bridge} "
                    f"({shlex.join(rule)}: {(res.err or res.out or '').strip() or 'iptables failed'}). "
                    f"Isolation is a correctness property; {product.isolation_env}=0 is the explicit "
                    f"escape hatch")
    log.ok(f"mgmt egress default-deny installed on {bridge} (instance '{instance}': container-initiated "
           f"egress to LAN/internet is dropped; published ports keep working)")
    return 0


def remove(instance: str, host: Host | None = None) -> int:
    """Remove exactly THIS instance's rules (symmetric teardown, `down` calls this). Quiet no-op when the
    chain is unreadable (then nothing was ever installed - `up` would have died) or when no tagged rule
    exists. Never touches another instance's rules."""
    product = spec()
    host = host or Host()
    listing = _iptables(host, ["iptables", "-S", DOCKER_USER_CHAIN])
    if not listing.ok:
        return 0
    deletions = deletion_rules(listing.out or "", product.rule_tag, instance)
    for rule in deletions:
        _iptables(host, rule)
    if deletions:
        log.ok(f"removed {len(deletions)} egress-isolation rule(s) of instance '{instance}'")
    return 0


def harden_uplinks(interfaces: list[str], *, is_linux: bool = True,
                   conf_root: Path = IPV4_CONF_ROOT) -> int:
    """ARP-harden the LAN uplinks (layer 2, up-preflight, defence in depth): arp_ignore=1 +
    arp_announce=2 on every interface carrying a default route, so host-owned bridge IPs are never
    announced on the LAN regardless of mgmt addressing. Idempotent - reads each value and writes only on
    change, ONE log line per changed interface - and deliberately NOT reverted on `down`: hardening is
    host state, not lab state. The product's harden env var set to 0 opts out; a non-Linux host no-ops
    (the lab lives in a NATed VM that cannot ARP on the physical LAN). A write failure only warns: this
    layer is defence in depth, the correctness property is the iptables default-deny.

    `interfaces` is passed rather than probed: the default-route probe belongs to the product's paths
    adapter, which owns the host-uplink question already."""
    product = spec()
    if not enabled(product.harden_env):
        log.warn(f"{product.harden_env}=0: skipping the uplink ARP hardening")
        return 0
    if not is_linux:
        return 0
    sudo = os.environ.get("SUDO", "sudo").strip()
    for interface in interfaces:
        changed: list[str] = []
        for key, want in ARP_SYSCTLS:
            knob = conf_root / interface / key
            try:
                current = knob.read_text().strip()
            except OSError:
                continue  # interface vanished / exotic sysfs; nothing to harden here
            if current == want:
                continue
            write = ([sudo] if sudo else []) + ["sh", "-c", f"echo {want} > {knob}"]
            if run(write).ok:
                changed.append(f"{key}={want}")
            else:
                log.warn(f"could not set {key}={want} on uplink {interface} (the ARP hardening is "
                         f"defence in depth; the iptables default-deny still isolates the lab)")
        if changed:
            log.ok(f"hardened ARP on uplink {interface}: {', '.join(changed)} "
                   f"(host state, not reverted on down; {product.harden_env}=0 opts out)")
    return 0
