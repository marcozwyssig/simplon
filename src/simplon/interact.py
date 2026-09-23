"""Pure resolver/arg-parse logic for the lab-interaction commands (logs / clients / connect) for the *ctl
orchestrators, ported from the bash cmd_logs/cmd_connect. The actual I/O (docker exec, ssh, docker logs)
lives in cli.py via host.py; the decision logic here - which container/IP a name resolves to, how the logs
flags parse - is pure and unit-tested, the part that used to be fiddly bash argument loops.

THE CONTAINER PREFIX IS PASSED IN, ALWAYS (si#312). This module used to carry one product's prefix as a
constant, and not even that product's general case: it was the spelling of that product's RESERVED
instance, so every command answered correctly for that one instance and silently for all the others. The
measured consequence was an orchestrator naming an instance with zero containers and getting another
instance's live log, and - the finding that decided the ticket - `connect` opening a shell in another
instance's controller while the operator had named their own.

So the kernel derives no container name of its own. It holds no product name, no reserved instance id and
NO DEFAULT PREFIX - a preset value would be the same defect by a detour, answering for whoever happens to
match it. The caller resolved the instance and therefore knows the prefix; the mechanism is the kernel's,
the naming knowledge stays with the product that owns it.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NamedTuple


class InstanceNotPresent(RuntimeError):
    """No running container belongs to the instance a command was pointed at.

    A RuntimeError rather than a returned verdict, because a returned verdict can be ignored and this one
    exists precisely against a command that carried on and reported success.
    """


def require_instance_present(prefix: str, container_names: Iterable[str]) -> None:
    """Refuse unless at least one of ``container_names`` belongs to ``prefix``'s instance. PURE.

    For commands that PRESUPPOSE the instance rather than create it - that is the line, and it is netctl's
    rather than ours: a bring-up starts from zero containers, so zero is its ordinary beginning; `logs`,
    `connect` and a tear-down do not. Without this, "the instance is not there" and "the instance is there
    and quiet" are the same outcome, and a tear-down of an empty instance reports success while somebody
    else's lab keeps running (netctl#1040). That is this project's recurring defect, at this seam.

    Belonging is `startswith`, not the substring match `docker ps --filter name=` performs, which would
    count a container whose name merely CONTAINS the prefix.

    ONE LIMIT, AND IT IS THE CALLER'S TO CLOSE: where a product collapses a reserved instance id away, that
    instance's prefix is a prefix of every sibling's, so a sibling's containers satisfy this check for the
    collapsed one. The kernel cannot see that - it does not hold the collapse rule and is not going to -
    and a caller that needs the distinction filters before calling.
    """
    for name in container_names:
        if name.startswith(prefix):
            return
    raise InstanceNotPresent(
        f"simplon: no container name starts with '{prefix}'. This command acts on an instance that is "
        f"already up and does not create one, so there is nothing here to act on - and whatever else is "
        f"running is another instance's.")


def normalize_container(name: str, prefix: str) -> str:
    """Prefix a bare node name with ``prefix`` unless it already carries it (cmd_logs:1632,
    cmd_connect:1681). PURE."""
    return name if name.startswith(prefix) else prefix + name


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


def strip_prefix(text: str, prefix: str) -> str:
    """Drop the FIRST occurrence of ``prefix`` from ``text`` for display (the `sed 's/<prefix>//'` in
    cmd_logs/cmd_clients). PURE.

    NOT `removeprefix`, and the reason is measured rather than assumed: what the callers hand over is a
    `docker ps --format '  {{.Names}}\\t{{.Status}}'` LINE, indented and with a second column, so the name
    does not sit at position 0 and a strict prefix strip would be a no-op on every real input. It is not
    `str.replace` either, which is what it used to be: that emptied every occurrence, so a prefix
    appearing again in the status column or an image name corrupted the rest of the line too.
    """
    head, found, tail = text.partition(prefix)
    return head + tail if found else text


class ConnectTarget(NamedTuple):
    kind: str             # "ssh" (a managed device) | "shell" (a container)
    value: str            # the mgmt IP (ssh) or the container name (shell)


def resolve_connect_target(name: str, devices: list[tuple[str, str]],
                           site_controllers: Mapping[str, str], prefix: str) -> ConnectTarget:
    """Resolve a connect target the way cmd_connect does (netctl.sh:1660): a managed device name
    (l3s-*/w3s-*) -> SSH to its mgmt IP; a lab-site name -> the controller container the caller mapped it
    to; anything else -> that container (prefixed if bare). PURE.

    ``devices`` is the (mgmt-ip, node-name) list (STATUS_DEVICES). ``site_controllers`` maps a site name
    to its controller container's BARE name, and it is a map rather than the list of site names this took
    before si#312 because the old shape needed the kernel to build `<product>-<site>` itself - a second
    product name in a module that is not allowed one. The caller knows its controllers; the kernel places
    them on an instance.
    """
    for ip, dev_name in devices:
        if dev_name == name:
            return ConnectTarget(kind="ssh", value=ip)
    if name in site_controllers:
        return ConnectTarget(kind="shell", value=normalize_container(site_controllers[name], prefix))
    return ConnectTarget(kind="shell", value=normalize_container(name, prefix))
