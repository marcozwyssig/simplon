"""What an environment is realised ON, named once and pointed at many times (si#5).

WHY A SECTION OF ITS OWN AND NOT MORE KEYS ON AN ENVIRONMENT. A Portainer serves several applications
and, on the same instance, several environments - the owner's own shape, and biz-cockpit's: their `test`
and `prod` share ONE carrier and are separated by directory. Written into each environment, the carrier
would then stand in the document two or three times, and two environments on the same Portainer could
drift apart without anything noticing. That is the second-source defect this repository removes
everywhere else, and a section is what removes it here: the carrier is stated once and referred to.

WHAT THIS IS NOT. It is not the backend seam. `simplon.backend` stays what it is - the ONE axis meant to
be extended, where a product registers an implementation per backend name - and an environment still
declares its `backend:`. A carrier is the DATA that backend needs, not a second way to select one. The
two answer different questions: `backend:` says who deploys, `carrier:` says onto what.

NOTHING HERE MAY HOLD A SECRET, and the guarantee is structural rather than advisory. `credentials.py`
records why - a product repository leaked a token out of a committed YAML file once, and *"leaving no
such field is what stops that repeating"*. So `portainer:` takes `url_from:`, a credential PREFIX, and
an unknown key under either block is REFUSED rather than ignored: a `token: ghp_...` typed into this
section has to fail loudly, and a parser that skipped what it did not recognise would let it sit in a
committed file instead.

WHY THE CHAIN IS TWO NAMED BLOCKS AND NOT A GENERAL LIST OF LAYERS. The expressive form was considered
and declined with a number: `backend: local` is the only value in all eight environments of all six
products this kernel can reach. A general layer mechanism for a chain nobody declares yet is the kind of
flexibility si#48 counts as rule creep. The form here carries both chains that two consumers have
actually described - Proxmox -> Portainer -> stack, and Proxmox -> compose -> app behind Caddy - and the
general list stays the way out if a third arrives that it cannot carry.
"""
from __future__ import annotations

from typing import Mapping, NamedTuple

#: The manifest section this module owns.
SECTION = "carriers"

#: What a Proxmox carrier may be. Both, and it is per environment (owner decision, 2026-09-05): an LXC
#: is cheaper and a VM is what you reach for when the workload will not live in a container.
LXC = "lxc"
VM = "vm"
KINDS = (LXC, VM)

#: The keys each block accepts. Named rather than implied, because the refusal of everything else is the
#: whole of the no-secret guarantee: a key that is not here is a key that fails.
PROXMOX_KEYS = ("node", "kind")
PORTAINER_KEYS = ("url_from", "endpoint")

#: Portainer's own default endpoint id, the local Docker environment it manages. A carrier that says
#: nothing means the one Portainer creates for itself, which is what a single-host install has.
DEFAULT_ENDPOINT = 1


class Proxmox(NamedTuple):
    """The Proxmox half: which node, and what kind of thing to put on it."""

    node: str
    kind: str


class Portainer(NamedTuple):
    """The Portainer half. `url_from` is the credential PREFIX, so `PORTAINER` means `PORTAINER_URL` and
    `PORTAINER_TOKEN` - the convention `credentials.py` fixed and `portainer.PortainerTarget.from_env`
    already reads."""

    url_from: str
    endpoint: int


class Carrier(NamedTuple):
    """One named carrier: a Proxmox node and the Portainer installed on it."""

    name: str
    proxmox: Proxmox
    portainer: Portainer


def _block(spec: Mapping, key: str, allowed: tuple[str, ...], where: str) -> Mapping:
    """One block of a carrier, with every key it carries checked against `allowed`.

    THE UNKNOWN-KEY REFUSAL IS THE POINT, not tidiness. It is what turns a `token:` typed into this
    section from a line nobody notices into a run that stops and says so.
    """
    raw = spec.get(key)
    if raw is None:
        raise ValueError(f"{where} declares no `{key}:`, so nothing says {_what(key)}")
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}'s `{key}:` must be a mapping, not {type(raw).__name__}")
    unknown = sorted(str(k) for k in raw if str(k) not in allowed)
    if unknown:
        raise ValueError(
            f"{where}'s `{key}:` does not take {', '.join(unknown)} - it takes "
            f"{', '.join(allowed)}. A credential does not belong in a manifest at all: name the "
            f"environment-variable prefix with `url_from:` and keep the secret out of the file")
    return raw


def _what(key: str) -> str:
    return {"proxmox": "which node the carrier stands on",
            "portainer": "where the Portainer on it answers"}.get(key, f"the `{key}:` half")


def _carrier(name: str, spec: object, where: str) -> Carrier:
    """One validated carrier. Every rule names the offending key, because the reader is looking at a
    file and needs to know which line."""
    if not isinstance(spec, Mapping):
        raise ValueError(f"{where} must be a mapping, not {type(spec).__name__}")

    proxmox = _block(spec, "proxmox", PROXMOX_KEYS, where)
    node = str(proxmox.get("node", "")).strip()
    if not node:
        raise ValueError(f"{where}'s `proxmox:` declares no `node:`, so no host is named")
    kind = str(proxmox.get("kind", "")).strip()
    if kind not in KINDS:
        raise ValueError(
            f"{where}'s `proxmox: kind:` must be {' or '.join(KINDS)}, got '{kind}'. An {LXC} is a "
            f"container on the node, a {VM} a full machine - the choice is per environment and the "
            f"kernel cannot infer it")

    portainer = _block(spec, "portainer", PORTAINER_KEYS, where)
    url_from = str(portainer.get("url_from", "")).strip()
    if not url_from:
        raise ValueError(
            f"{where}'s `portainer:` declares no `url_from:`, so nothing says where the URL and the "
            f"token are read from. It is a PREFIX, not a value: `url_from: PORTAINER` means "
            f"PORTAINER_URL and PORTAINER_TOKEN")
    raw_endpoint = portainer.get("endpoint", DEFAULT_ENDPOINT)
    try:
        endpoint = int(raw_endpoint)
    except (TypeError, ValueError):
        raise ValueError(
            f"{where}'s `portainer: endpoint:` must be a number, got {raw_endpoint!r} - it is "
            f"Portainer's own id for the Docker environment it manages") from None

    return Carrier(name=name, proxmox=Proxmox(node=node, kind=kind),
                   portainer=Portainer(url_from=url_from, endpoint=endpoint))


def declared(data: Mapping[str, object], source: str = "manifest") -> dict[str, Carrier]:
    """Every carrier the document declares, validated.

    An ABSENT section is not a refusal and returns nothing: a product that deploys nowhere yet has no
    carrier to describe, and this section only becomes required the moment an environment points at one.
    That check belongs to `environments`, which is the half that knows whether anybody pointed.
    """
    section = data.get(SECTION)
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section must be a mapping of name -> carrier, "
                         f"not {type(section).__name__}")
    return {str(name): _carrier(str(name), spec, f"{source}: '{SECTION}.{name}'")
            for name, spec in section.items()}
