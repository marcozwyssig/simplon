"""Pure resolver/arg-parse logic for the lab-interaction commands (logs / clients / connect) for the *ctl
orchestrators, ported from the bash cmd_logs/cmd_connect. The actual I/O (docker exec, ssh, docker logs)
lives in cli.py via host.py; the decision logic here - which container/IP a name resolves to, how the logs
flags parse - is pure and unit-tested, the part that used to be fiddly bash argument loops.
"""
from __future__ import annotations

from typing import NamedTuple

_PREFIX = "clab-netctl-"


def normalize_container(name: str) -> str:
    """Prefix a bare node name with `clab-netctl-` unless it already carries it (cmd_logs:1632,
    cmd_connect:1681)."""
    return name if name.startswith(_PREFIX) else _PREFIX + name


def strip_prefix(name: str) -> str:
    """Drop the `clab-netctl-` prefix for display (the `sed 's/clab-netctl-//'` in cmd_logs/cmd_clients)."""
    return name.replace(_PREFIX, "")


class LogsArgs(NamedTuple):
    node: str | None      # None -> list containers + usage
    follow: bool          # -f / --follow
    tail: str             # --tail=N (default "120")


def parse_logs_args(args: list[str]) -> LogsArgs:
    """Parse `logs` flags exactly like the cmd_logs loop (netctl.sh:1619): -f/--follow, --tail=N, and a
    positional node (the LAST non-flag wins, matching the bash `*) node="$a"`)."""
    follow = False
    tail = "120"
    node: str | None = None
    for a in args:
        if a in ("-f", "--follow"):
            follow = True
        elif a.startswith("--tail="):
            tail = a[len("--tail="):]
        else:
            node = a
    return LogsArgs(node=node, follow=follow, tail=tail)


class ConnectTarget(NamedTuple):
    kind: str             # "ssh" (a managed device) | "shell" (a container)
    value: str            # the mgmt IP (ssh) or the container name (shell)


def resolve_connect_target(name: str, devices: list[tuple[str, str]], site_names: list[str]) -> ConnectTarget:
    """Resolve a connect target the way cmd_connect does (netctl.sh:1660): a managed device name
    (l3s-*/w3s-*) -> SSH to its mgmt IP; a bare lab-site name -> its `netctl-<site>` controller
    container; anything else -> that container (prefixed if bare).

    devices is the (mgmt-ip, node-name) list (STATUS_DEVICES); site_names the lab.yml site names.
    """
    for ip, dev_name in devices:
        if dev_name == name:
            return ConnectTarget(kind="ssh", value=ip)
    if name in site_names:
        return ConnectTarget(kind="shell", value=f"{_PREFIX}netctl-{name}")
    return ConnectTarget(kind="shell", value=normalize_container(name))
