"""The one question the kernel asks Proxmox before a carrier is built (si#5).

WHY THIS MODULE IS SMALL ON PURPOSE. Making the carrier is Pulumi's job and configuring it is Ansible's;
neither is reimplemented here. What is here is the check that turns a failure arriving three minutes
into a provider run into a refusal that names a line in a file.

THE DEFECT IT EXISTS FOR, MEASURED ON 2026-09-14 against a real cluster. `/nodes/pve-2/storage` lists
`local-lvm`. Creating a container on it answers:

    received an HTTP 500 response - Reason: storage 'local-lvm' is not available on node 'pve-2'

Both are true. The storage is DEFINED cluster-wide and restricted to another node, so the node's own
listing carries it with `active: 0, enabled: 0`. A listing that includes what cannot be used is this
repository's recurring defect wearing an inventory's clothes: the answer cannot tell "this node has it"
from "this node knows of it".

The same call answers the question properly, and it is three fields away: `enabled`, `active`, and
whether `content` carries `rootdir`. Asked here, before anything runs, the operator gets the storages
their node really offers instead of an HTTP 500 out of a provider's belly.

`urllib` FROM THE STANDARD LIBRARY, the same decision `portainer.py` records: the orchestrator has to
run on a host that has nothing but Python.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import NamedTuple

#: What a carrier's disk needs the storage to serve. Proxmox spells a container's root filesystem
#: `rootdir`; `images` is for VM disks and is NOT a substitute - a storage offering only `images` will
#: refuse an LXC.
ROOTDIR = "rootdir"

_TIMEOUT_S = 20.0


class ProxmoxError(RuntimeError):
    """A failure the caller can print as a sentence, not as a traceback."""


class Storage(NamedTuple):
    """One storage as the NODE reports it - not as the cluster defines it, which is the difference this
    module exists for."""

    name: str
    content: tuple[str, ...]
    enabled: bool
    active: bool

    @property
    def serves_containers(self) -> bool:
        return self.enabled and self.active and ROOTDIR in self.content


def _context(insecure: bool) -> ssl.SSLContext | None:
    """The TLS context, and `None` means the default one WITH verification.

    A fresh Proxmox answers with a self-signed certificate, so `insecure` is real and a carrier may
    declare it. It is never the default: a kernel that turned verification off for everybody would be
    deciding something a product has to say in its own file, where a reviewer sees it.
    """
    if not insecure:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _get(endpoint: str, token: str, path: str, *, insecure: bool) -> object:
    """One authenticated GET against the Proxmox API, with the failure said in words.

    The token NEVER reaches a command line - it is a header on a request this process makes, which is
    `credentials.py`'s rule at the one place in this kernel that talks to Proxmox at all.
    """
    url = f"{endpoint.rstrip('/')}/api2/json{path}"
    request = urllib.request.Request(url, headers={"Authorization": f"PVEAPIToken={token}"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S,
                                    context=_context(insecure)) as response:
            return json.loads(response.read()).get("data")
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise ProxmoxError(
                f"{endpoint} refused the token (401). The token is read from the environment, not from "
                f"the manifest - check the prefix the carrier declares and that both halves are "
                f"exported") from None
        raise ProxmoxError(f"{endpoint} answered {error.code} for {path}: {error.reason}") from None
    except urllib.error.URLError as error:
        raise ProxmoxError(
            f"{endpoint} could not be reached: {error.reason}. A self-signed certificate is the usual "
            f"cause and is what `insecure: true` on the carrier is for") from None


def storages(endpoint: str, token: str, node: str, *, insecure: bool) -> list[Storage]:
    """Every storage the NODE reports, with the three fields that decide whether it can be used."""
    raw = _get(endpoint, token, f"/nodes/{node}/storage", insecure=insecure)
    if not isinstance(raw, list):
        raise ProxmoxError(f"{endpoint} did not answer with a storage list for node '{node}'")
    found = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        found.append(Storage(
            name=str(entry.get("storage", "")),
            content=tuple(str(entry.get("content", "")).split(",")),
            enabled=bool(entry.get("enabled", 0)),
            active=bool(entry.get("active", 0)),
        ))
    return found


def check_storage(endpoint: str, token: str, node: str, storage: str, *, insecure: bool) -> None:
    """Refuse HERE if the carrier's storage is not one this node can put a container on.

    Named rather than boolean: the operator is told which storages the node really offers, because the
    next thing they have to do is choose one, and a bare "not available" sends them to the web
    interface to find out what is.
    """
    found = storages(endpoint, token, node, insecure=insecure)
    usable = [s.name for s in found if s.serves_containers]
    if storage in usable:
        return
    known = next((s for s in found if s.name == storage), None)
    if known is None:
        raise ProxmoxError(
            f"node '{node}' has no storage '{storage}'. It offers {', '.join(usable) or 'none'} for "
            f"containers")
    raise ProxmoxError(
        f"node '{node}' knows storage '{storage}' but cannot put a container on it "
        f"(enabled={known.enabled}, active={known.active}, content={','.join(known.content)}). A "
        f"storage defined for another node is listed here all the same. It offers "
        f"{', '.join(usable) or 'none'} for containers")


def container_id(endpoint: str, token: str, node: str, name: str, *, insecure: bool) -> int:
    """The vmid of the container with this hostname on this node, or 0.

    BY NAME AND NOT BY ID, because an id is not something a manifest can carry: Proxmox allocates it.
    The carrier's name is what a person typed, so it is what this looks for - and a node carrying two
    containers of the same name is impossible, so the answer is unambiguous.
    """
    raw = _get(endpoint, token, f"/nodes/{node}/lxc", insecure=insecure)
    if not isinstance(raw, list):
        return 0
    for entry in raw:
        if isinstance(entry, dict) and str(entry.get("name", "")) == name:
            return int(entry.get("vmid", 0))
    return 0


def address(endpoint: str, token: str, node: str, vmid: int, *, insecure: bool) -> str:
    """The container's own IPv4, without the mask, or "".

    A container on DHCP has no address any manifest could carry and the node is the only thing that
    knows it. `lo` is skipped for the obvious reason; an interface that has not come up yet reports
    nothing at all, which is why the empty string is a real answer here rather than a failure - the
    caller says "not yet" and means it.
    """
    raw = _get(endpoint, token, f"/nodes/{node}/lxc/{vmid}/interfaces", insecure=insecure)
    if not isinstance(raw, list):
        return ""
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("name") == "lo":
            continue
        inet = str(entry.get("inet", ""))
        if inet:
            return inet.split("/")[0]
    return ""
