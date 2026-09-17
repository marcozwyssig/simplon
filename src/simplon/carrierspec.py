"""What an environment is realised ON, named once and pointed at many times (si#5).

THE NAME IS `carrierspec` AND NOT `carriers`, which is si#37's rule rather than a preference: a promised
module may not share a name with a task body, and `simplon.tasks.carrier` is the body that builds one.
`simplon.images` against `simplon.tasks.image` were one character of path apart and the reader at the
call site had nothing to go on; the library half is the half that gets renamed, because it is the half a
product types. The manifest section is still `carriers:` - what is renamed is the module, not the
vocabulary.

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

WHAT A CARRIER IS, RESTATED AFTER si#258. It is a MACHINE on a Proxmox node, and optionally the one
thing this kernel knows how to install on it. The `portainer:` half used to be required, which made
"carrier" and "Portainer host" the same word - and `deploy carrier` proved it by running an
apt -> Docker -> Portainer playbook at the end of every run, with no branch in it. A carrier that omits
the block is created and not configured, and that outcome is reported rather than implied.

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
#:
#: WHAT IS HERE IS CONFIGURATION AND ONLY CONFIGURATION (owner, 2026-09-14: "die Konfiguration muss im
#: manifest stehen"). The endpoint, the node, the datastores and the sizes are facts about a machine and
#: belong in the file a reviewer reads. The API token is not, and has no key: `token_from:` names the
#: PREFIX it is read from, exactly as `url_from:` does for Portainer.
#:
#: `nesting` AND `keyctl` ARE NOT HERE, AND THAT IS THE POINT. An unprivileged LXC will not start a
#: Docker daemon without both, and si#5 recorded the failure mode in one sentence: whoever sets them by
#: hand once forgets them. They are therefore not a field a product may get wrong - they are what a
#: carrier IS, set by the kernel on every container it creates.
PROXMOX_KEYS = ("endpoint", "token_from", "insecure", "node", "kind",
                "template", "storage", "cores", "memory", "disk", "ssh_key")
PORTAINER_KEYS = ("url_from", "endpoint", "insecure")

#: The defaults, READ OFF the community helper script rather than invented (`ct/docker.sh`, measured
#: 2026-09-14): `var_cpu=2`, `var_ram=2048`, `var_disk=4` for its Debian path. A carrier that says
#: nothing gets what the tool the owner named would have given it.
DEFAULT_CORES = 2
DEFAULT_MEMORY_MB = 2048
DEFAULT_DISK_GB = 4

#: Portainer's own default endpoint id, the local Docker environment it manages. A carrier that says
#: nothing means the one Portainer creates for itself, which is what a single-host install has.
DEFAULT_ENDPOINT = 1


class Proxmox(NamedTuple):
    """The Proxmox half: where the API is, which node, and what to put on it.

    `token_from` is a credential PREFIX like Portainer's `url_from` - `PROXMOX` means the token is read
    from `PROXMOX_API_TOKEN` - so this tuple carries no secret and the manifest has no field for one.

    `insecure` skips TLS verification, which a fresh Proxmox needs because it answers with a
    self-signed certificate. It defaults to FALSE: a product that wants the weaker check has to say so
    in its own file, where a reviewer sees it, rather than inheriting it from a kernel that decided
    verification was inconvenient.
    """

    node: str
    kind: str
    endpoint: str = ""
    token_from: str = ""
    insecure: bool = False
    template: str = ""
    storage: str = ""
    cores: int = DEFAULT_CORES
    memory: int = DEFAULT_MEMORY_MB
    disk: int = DEFAULT_DISK_GB
    ssh_key: str = ""


class Portainer(NamedTuple):
    """The Portainer half. `url_from` is the credential PREFIX, so `PORTAINER` means `PORTAINER_URL` and
    `PORTAINER_TOKEN` - the convention `credentials.py` fixed and `portainer.PortainerTarget.from_env`
    already reads.

    `insecure` arrived with the backend (si#5, slice 3) and it is a MEASUREMENT rather than a symmetry
    with `Proxmox.insecure`: the Portainer the kernel installs answers on 9443 with a certificate it
    generated for itself, and against the real carrier on 2026-09-16 a verifying request failed with
    `CERTIFICATE_VERIFY_FAILED: self-signed certificate` while the same request with verification off
    answered 200. Without this key the backend could not reach the Portainer the kernel's own
    `deploy carrier` had just built. It defaults to FALSE for the same reason Proxmox's does - a product
    that wants the weaker check says so in the file a reviewer reads.
    """

    url_from: str
    endpoint: int
    insecure: bool = False


class Carrier(NamedTuple):
    """One named carrier: a machine, and what the kernel installs on it - and either half may be absent.

    `proxmox` IS OPTIONAL SINCE si#280, which is si#258's own argument arriving from the other side. A
    carrier with no `proxmox:` is a Portainer somebody else built: the machine has been running for
    months, the kernel did not make it and will not, and the only thing this manifest needs from the
    carrier is where that Portainer answers. `deploy carrier` refuses such a carrier by name, because
    there is nothing for that command to make.

    THE MEASUREMENT THAT SAYS IT IS NOT A CONVENIENCE. Every reader of `carrier.proxmox` in this kernel
    lives in `tasks/carrier.py` - the command that CREATES the machine. `portainer.PortainerTarget`
    reads `carrier.name` and `carrier.portainer` and nothing else. So a product bringing its own machine
    had to declare a block that no code on its path ever consulted, and the two values with no defaults
    (`node:`, `kind:`) had no true answer to give. A value that never has an effect is the one that is
    wrong a year later and tells nobody - this module's neighbour records the same lesson about a count
    that was wrong within two days.

    `portainer` IS OPTIONAL SINCE si#258, and the reason is a finding rather than a feature request. The
    section was written as though a carrier and a Portainer host were the same thing: `portainer:` was
    required on every carrier, and `deploy carrier` ran an apt -> Docker -> Portainer playbook at the end
    of every run with no branch in it. So the kernel's answer to "make me a machine" was always "and I
    have decided what runs on it".

    A carrier with no `portainer:` is created and NOT configured. That is a complete outcome and is
    reported as one - the machine exists, the kernel installed nothing, and the manifest says why. What
    then runs on it is the product's own business, reached through a backend it registers itself.

    It cost no manifest anything: measured 2026-09-16 over the GitHub API, not one repository in this
    family declares a `carriers:` section at all, this kernel's own included.
    """

    name: str
    proxmox: "Proxmox | None" = None
    portainer: "Portainer | None" = None


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

    if "proxmox" not in spec:
        # A PORTAINER SOMEBODY ELSE BUILT, which is a complete statement and not half a carrier
        # (si#280). The refusal that used to stand here demanded a `node:` and a `kind:` from every
        # carrier - true only while the kernel was assumed to have made the machine. Nothing on the
        # deploy path reads this block; `deploy carrier` does, and it says so itself.
        machine = None
    else:
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
        machine = _proxmox(proxmox, node, kind, where)

    if "portainer" not in spec:
        if machine is None:
            # NEITHER HALF. Each absence is a statement on its own; both at once state nothing at all,
            # and the carrier would be a name that no command can act on - `deploy carrier` has no
            # machine to make and no backend has anywhere to put a stack.
            raise ValueError(
                f"{where} declares neither `proxmox:` nor `portainer:`, so it says nothing that can be "
                f"acted on. A carrier is a machine the kernel makes (`proxmox:`), a Portainer it can "
                f"reach (`portainer:`), or both")
        # A MACHINE AND NOTHING ELSE, which is a complete statement and not half a carrier. The refusal
        # that used to stand here said a carrier with no `portainer:` "declares no ... so nothing says
        # where the Portainer on it answers" - true only while a carrier and a Portainer host were the
        # same thing. What a product puts on the machine is now its own to say.
        return Carrier(name=name, proxmox=machine, portainer=None)

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

    return Carrier(name=name, proxmox=machine,
                   portainer=Portainer(url_from=url_from, endpoint=endpoint,
                                       insecure=_insecure(portainer, "portainer", where)))


def _positive(block: Mapping, key: str, default: int, where: str) -> int:
    """A size the manifest may state, refused when it is not a positive number.

    Zero is refused with the rest: a container with no cores and a container with a default number of
    cores are two different statements, and `int("0")` would quietly make the first mean the second.
    """
    raw = block.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{where}'s `proxmox: {key}:` must be a number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{where}'s `proxmox: {key}:` must be greater than zero, got {value}")
    return value


def _insecure(block: Mapping, half: str, where: str) -> bool:
    """`insecure:` on either half, refused when it is not a real boolean.

    ONE function for both halves because the refusal is the interesting part and it must read the same on
    each: every non-empty string is truthy, so `insecure: "no"` would turn verification OFF while saying
    the opposite. It is the one value in this section that is refused rather than read leniently.
    """
    value = block.get("insecure", False)
    if not isinstance(value, bool):
        raise ValueError(
            f"{where}'s `{half}: insecure:` must be true or false, got {value!r} - it turns TLS "
            f"verification OFF, so it is the one value here that may not be guessed from a string")
    return value


def _proxmox(block: Mapping, node: str, kind: str, where: str) -> Proxmox:
    """The whole Proxmox block, validated - built HERE rather than splatted from a mapping, because a
    `**dict[str, object]` hands mypy nothing and the type gate said so on the first run.

    Every one of these is CONFIGURATION - where the API is, which datastore, how big - and every one of
    them has a default, because the only field the provider itself requires is the node. A carrier
    states what it wants differently and stays silent about the rest.
    """
    insecure = _insecure(block, "proxmox", where)
    # NO RULE THAT THE PREFIX BE UPPER CASE, and it was written and then struck rather than never
    # considered. CLAUDE.md's first question is whether it forbids something a product might
    # legitimately want: a lower-case environment variable is perfectly legal on every platform this
    # kernel runs on, so a manifest saying `token_from: proxmox` and exporting `proxmox_API_TOKEN`
    # would have WORKED. That makes it an expression rule, and an expression rule with no measured
    # cause is what si#53 struck `check_every_task_is_used` for. Convention is documented on the site
    # instead, where it costs nobody a refusal.
    token_from = str(block.get("token_from", "")).strip()
    return Proxmox(
        node=node,
        kind=kind,
        endpoint=str(block.get("endpoint", "")).strip(),
        token_from=token_from,
        insecure=insecure,
        template=str(block.get("template", "")).strip(),
        storage=str(block.get("storage", "")).strip(),
        cores=_positive(block, "cores", DEFAULT_CORES, where),
        memory=_positive(block, "memory", DEFAULT_MEMORY_MB, where),
        disk=_positive(block, "disk", DEFAULT_DISK_GB, where),
        ssh_key=str(block.get("ssh_key", "")).strip(),
    )


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
