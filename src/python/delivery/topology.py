"""A generic, Pydantic-validated containerlab TOPOLOGY MANIFEST (netctl#731 Strand 1).

The delivery kernel already turns a product's CLI + CI taxonomy into DATA (``delivery.orchestrator.manifest``).
This module is the second "one source, typed data" seam: a product-agnostic description of a containerlab
lab as a set of NODES (with a clab ``kind``, image, env, binds, exec, ports and an optional per-node config
template) wired by LINKS (``node:iface`` endpoint pairs), on one MGMT network, with first-class OOB BRIDGES
and #453 multi-tenant INSTANCE-SCOPING. A product ships the manifest (data); a future ``clab-from-topology``
engine (Strand 2) renders it to ``*.clab.yml`` + drives the lifecycle (Strand 3).

DESIGN ALTITUDE - deliberately the containerlab OUTPUT primitives, not a product's compact input model.
A manifest lists the concrete nodes/links a lab is made of; it does NOT know "a site expands into
postgres+controller+two routers+...". That expansion (role -> node set, address derivation, EVPN/WireGuard
wiring) is exactly the product-specific mass this schema must NOT absorb - see
``docs/topology-manifest-strand1-analysis.md`` for the feasibility argument and the leak inventory.

GENERIC vs PRODUCT boundary. The schema fields are all containerlab-generic (``kind``, ``image``, ``env``,
``binds``, ``exec``, ``ports``, ``mgmt_ipv4``, ``startup_config``, endpoints). Everything product-specific is
quarantined behind three indirections so it stays DATA, never new schema:
  * ``vendor_kinds`` - a registry mapping a product's vendor/platform label (frr/ios/vyos) to a clab ``kind``
    + default image, so the vendor set is data.
  * ``config_template`` - an opaque per-node reference the product's config engine renders (netctl:
    ``frr/underlay.sh``, ``ios/<node>.cfg``); the schema never parses it.
  * ``attributes`` - a free-form bag on ``Site`` and ``Node`` for product knobs (netctl: a site's
    ``http_port``/``keycloak_enabled``/``data_subnet``, a node's role-specific flags) that must not freeze
    into the shared schema.

Validation is FAIL-LOUD (the whole point of a schema): ``model_config = extra="forbid"`` catches a mistyped
key, and ``load()`` re-raises any Pydantic ``ValidationError`` as a plain ``ValueError`` (a raw
ValidationError never escapes), mirroring ``delivery.orchestrator.manifest.load``. Cross-object rules (unique
names, dangling site/vendor references, link endpoints naming a real node/bridge, resolvable kind) run in a
manifest-level ``@model_validator`` so the message can name the offending object (the tests assert the
strings).
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

# A containerlab endpoint is "<node>:<iface>" (the node/bridge name, then its interface / veth endpoint).
_ENDPOINT_RE = re.compile(r"^[^:\s]+:[^:\s]+$")
# An #453 instance token is a short, ifname-safe id; the charset is declared per-manifest, the length capped.
_DEFAULT_TOKEN_RE = re.compile(r"^[a-z0-9]+$")


class MgmtNetwork(BaseModel):
    """The lab's containerlab management network: the docker bridge NAME and its IPv4 subnet. Both are
    instance-scoped by the engine at render (the name gets the token infixed, the subnet a collision-free
    per-instance offset); the manifest carries the reserved-instance ("dev") literals."""

    model_config = ConfigDict(extra="forbid")

    network: str
    ipv4_subnet: str

    @field_validator("network")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("mgmt.network must be a non-empty docker network name")
        return value

    @field_validator("ipv4_subnet")
    @classmethod
    def _valid_cidr(cls, value: str) -> str:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"mgmt.ipv4_subnet '{value}' is not a valid CIDR: {exc}") from exc
        return value


class VendorKind(BaseModel):
    """A named vendor/platform -> containerlab node ``kind`` (+ optional default image and node ``type``).
    The registry that turns a product's vendor label into a concrete clab kind, so a lab's vendor set is DATA
    (netctl: frr -> linux/netctl-frr:local, ios -> cisco_iol, vyos -> vyosnetworks_vyos). Generic MECHANISM;
    the label names and images are the product's."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    image: str | None = None
    type: str | None = None

    @field_validator("kind")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("vendor kind must be a non-empty containerlab kind")
        return value


class Site(BaseModel):
    """A generic GROUPING of nodes with a numeric ``id``. The schema treats a site as no more than a named,
    id-bearing bucket (a node references it via ``Node.site``); the product's per-site semantics
    (http_port, keycloak_enabled, data_subnet, cascade, monitoring - all netctl) live in the free-form
    ``attributes`` bag, never in the shared schema. The numeric ``id`` is opaque here beyond "positive and
    unique"; a product's address-derivation keys off it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    id: int
    attributes: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError(f"site id must be a positive integer, got {value}")
        return value


class Node(BaseModel):
    """One containerlab node. Its clab ``kind`` is given EITHER explicitly (``kind``) OR by ``vendor`` (a key
    into ``vendor_kinds`` that supplies kind + default image); ``image``/``type`` override the vendor default.
    ``site`` groups it (a ``Site.name`` or None = a global node such as central monitoring); ``role`` is an
    OPAQUE structural label the product reads (l3s/w3s/ogw/controller/...). The clab payload fields
    (``env``/``binds``/``exec``/``ports``/``mgmt_ipv4``/``startup_config``/``wait_for``) are generic
    containerlab; ``config_template`` is an opaque product ref its config engine renders; ``attributes`` is
    the product-knob bag that keeps product-specifics out of the schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str | None = None
    vendor: str | None = None
    image: str | None = None
    type: str | None = None
    site: str | None = None
    role: str | None = None
    mgmt_ipv4: str | None = None
    image_pull_policy: str | None = None
    env: dict[str, str] = {}
    binds: list[str] = []
    exec: list[str] = []
    ports: list[str] = []
    cmd: str | None = None
    healthcheck: dict[str, Any] = {}
    startup_config: str | None = None
    config_template: str | None = None
    wait_for: list[str] = []
    attributes: dict[str, Any] = {}

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("node name must be non-empty")
        return value

    @model_validator(mode="after")
    def _has_kind_source(self) -> "Node":
        # A node must resolve to a clab kind: either an explicit ``kind`` or a ``vendor`` key (resolved
        # against the manifest registry at manifest level, which also checks the key exists).
        if not self.kind and not self.vendor:
            raise ValueError(f"node '{self.name}': needs either 'kind' or 'vendor'")
        return self


class Link(BaseModel):
    """A containerlab link: exactly two ``node:iface`` endpoints. Each endpoint's node part must name a
    declared node OR bridge (checked at manifest level); the iface part is free-form (a device interface or a
    bridge veth-endpoint name)."""

    model_config = ConfigDict(extra="forbid")

    endpoints: tuple[str, str]

    @field_validator("endpoints", mode="before")
    @classmethod
    def _two_endpoints(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f"link endpoints must be a pair [a, b], got {value!r}")
        for ep in value:
            if not isinstance(ep, str) or not _ENDPOINT_RE.match(ep):
                raise ValueError(f"link endpoint '{ep}' must be 'node:iface'")
        return value

    def node_names(self) -> tuple[str, str]:
        """The two node/bridge names (the part before the colon of each endpoint)."""
        return (self.endpoints[0].split(":", 1)[0], self.endpoints[1].split(":", 1)[0])


class Bridge(BaseModel):
    """A containerlab ``bridge`` node, modelled as a first-class object because OOB bridges are a load-bearing
    lab concern (netctl: the per-site isolated sidecar<->device management segment). ``site`` optionally
    groups it. A bridge name is a valid link-endpoint node."""

    model_config = ConfigDict(extra="forbid")

    name: str
    site: str | None = None

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("bridge name must be non-empty")
        return value


class InstanceScoping(BaseModel):
    """#453 multi-tenant instance scoping: N isolated copies of the lab on one host, one per agent/CI job.
    The reserved ``default_instance`` renders byte-for-byte (no infix); any other token is infixed into the
    declared ``scoped_axes`` (topology name, mgmt network + subnet offset, OOB bridge + veth endpoints, ...)
    and capped at ``token_max_len`` chars from ``token_charset`` (the 15-char IFNAMSIZ budget on OOB veth
    endpoints). The schema records the POLICY; the engine performs the infix/offset."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    default_instance: str = "dev"
    token_max_len: int = 2
    token_charset: str = "[a-z0-9]"
    scoped_axes: list[str] = []

    @field_validator("default_instance")
    @classmethod
    def _valid_default(cls, value: str) -> str:
        if not _DEFAULT_TOKEN_RE.match(value):
            raise ValueError(
                f"instance_scoping.default_instance '{value}' must be lowercase alnum")
        return value

    @field_validator("token_max_len")
    @classmethod
    def _positive_len(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("instance_scoping.token_max_len must be positive")
        return value


class TopologyManifest(BaseModel):
    """A parsed, validated containerlab topology: the mgmt network, a vendor->kind registry, the sites
    (groupings), the nodes + links + bridges, and the optional instance-scoping policy. Cross-object
    integrity is enforced in ``_validate_graph`` so a manifest that parses is internally consistent (unique
    names, no dangling site/vendor references, every link endpoint naming a real node/bridge, every node kind
    resolvable). Use ``load()`` to parse YAML text with fail-loud ValueError semantics."""

    model_config = ConfigDict(extra="forbid")

    name: str
    mgmt: MgmtNetwork
    vendor_kinds: dict[str, VendorKind] = {}
    sites: list[Site] = []
    nodes: list[Node] = []
    links: list[Link] = []
    bridges: list[Bridge] = []
    instance_scoping: InstanceScoping | None = None

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("topology name must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_graph(self) -> "TopologyManifest":
        # rule 1: site ids and names are unique.
        site_names = [s.name for s in self.sites]
        _reject_dupes(site_names, "site name")
        _reject_dupes([s.id for s in self.sites], "site id")
        site_name_set = set(site_names)

        # rule 2: node + bridge names are unique across the WHOLE graph (a link endpoint names one namespace).
        endpoint_owners = [n.name for n in self.nodes] + [b.name for b in self.bridges]
        _reject_dupes(endpoint_owners, "node/bridge name")
        owner_set = set(endpoint_owners)

        # rule 3: every node's site (if set) and vendor (if set) reference a declared object, and every node
        # resolves to a clab kind.
        for node in self.nodes:
            if node.site is not None and node.site not in site_name_set:
                raise ValueError(
                    f"node '{node.name}': site '{node.site}' is not a declared site")
            if node.vendor is not None and node.vendor not in self.vendor_kinds:
                raise ValueError(
                    f"node '{node.name}': vendor '{node.vendor}' is not a declared vendor_kind")
            if not self.kind_of(node):
                raise ValueError(f"node '{node.name}': could not resolve a containerlab kind")

        # rule 4: every bridge's site (if set) references a declared site.
        for bridge in self.bridges:
            if bridge.site is not None and bridge.site not in site_name_set:
                raise ValueError(
                    f"bridge '{bridge.name}': site '{bridge.site}' is not a declared site")

        # rule 5: every link endpoint names a declared node or bridge.
        for link in self.links:
            for owner in link.node_names():
                if owner not in owner_set:
                    raise ValueError(
                        f"link {list(link.endpoints)}: endpoint '{owner}' is not a declared node or bridge")

        return self

    # --- resolution helpers (a product's renderer consumes these) ---------------------------------------

    def kind_of(self, node: Node) -> str | None:
        """The node's effective containerlab kind: its explicit ``kind`` else its vendor's kind."""
        if node.kind:
            return node.kind
        if node.vendor:
            vk = self.vendor_kinds.get(node.vendor)
            return vk.kind if vk else None
        return None

    def image_of(self, node: Node) -> str | None:
        """The node's effective image: an explicit ``image`` overrides the vendor default."""
        if node.image:
            return node.image
        if node.vendor:
            vk = self.vendor_kinds.get(node.vendor)
            return vk.image if vk else None
        return None

    def nodes_for_site(self, site_name: str) -> list[Node]:
        """Every node grouped under ``site_name`` (in declaration order)."""
        return [n for n in self.nodes if n.site == site_name]


def _reject_dupes(values: list, what: str) -> None:
    """Raise a clear ValueError naming the first duplicate, so a copy-paste slip fails loudly at load."""
    seen: set = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {what}: {value!r}")
        seen.add(value)


def _validation_message(error: ValidationError) -> str:
    """Reduce a Pydantic ValidationError to a single human message (mirrors delivery.orchestrator.manifest):
    a rule ValueError is surfaced verbatim (its ctx carries the original), a pure shape/type error as
    ``<location>: <message>``. Only the first error is reported."""
    details = error.errors(include_url=False)
    for detail in details:
        original = (detail.get("ctx") or {}).get("error")
        if isinstance(original, Exception):
            return str(original)
    detail = details[0]
    location = ".".join(str(part) for part in detail.get("loc", ()))
    message = detail.get("msg", "invalid topology manifest")
    return f"{location}: {message}" if location else message


def load(text: str) -> TopologyManifest:
    """Parse a topology manifest YAML into a validated ``TopologyManifest`` (pure: no rendering, no clab).

    Fails loudly with ValueError so a bad manifest is caught here and not deep in the render/lifecycle:
    unknown keys are rejected (``extra="forbid"``), and the cross-object rules (unique names, dangling
    site/vendor references, link endpoints naming a real node/bridge, resolvable node kind) each raise a
    ValueError naming the offending object. Any Pydantic ``ValidationError`` is re-raised as a plain
    ValueError (a raw ValidationError never escapes)."""
    data = yaml.safe_load(text) or {}
    try:
        return TopologyManifest.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_validation_message(exc)) from exc
