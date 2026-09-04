"""Pure helpers for a containerlab-style lab lifecycle (up/down): the OOB-bridge shell snippets and the
post-deploy verdict decision, ported from a *ctl orchestrator's shell as testable functions (netctl#730,
extracted from netctl's orchestrator).

The orchestration itself (a product's lab.py) does the I/O - colima/containerlab/docker - but the
DECISIONS live here so they can be unit-tested without a VM, the same pattern as disk.py / waits.py.
Product-agnostic: the bridge name and the container count are caller-supplied, so any *ctl product that
drives an OOB-bridged lab reuses these unchanged.
"""
from __future__ import annotations


def oob_bridge_up_snippet(bridge: str) -> str:
    """The shell snippet that idempotently creates + ups an OOB management bridge in the docker host
    (a product's oob_up). Already-present -> no-op."""
    return (f"ip link show {bridge} >/dev/null 2>&1 || "
            f"{{ sudo ip link add {bridge} type bridge && sudo ip link set {bridge} up; }}")


def oob_bridge_down_snippet(bridge: str) -> str:
    """The shell snippet that removes an OOB bridge if present (a product's oob_down)."""
    return f"ip link show {bridge} >/dev/null 2>&1 && sudo ip link del {bridge} || true"


def deploy_verdict(deployed: bool, container_count: int) -> str:
    """Decide the post-deploy outcome the way a product's cmd_up does:

    - "ok"        - clab deploy completed on some attempt.
    - "die"       - it failed every attempt AND no lab containers exist (a missing image / bad topology):
                    fatal, since continuing on an empty lab is what masks failures as success.
    - "degraded"  - it did not complete cleanly but SOME containers are up (an accepted flake floor):
                    surfaced as degraded, left to the caller's up_verdict.
    """
    if deployed:
        return "ok"
    if container_count == 0:
        return "die"
    return "degraded"
