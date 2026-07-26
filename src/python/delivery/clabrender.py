"""A generic containerlab RENDER ENGINE that consumes a ``delivery.topology`` manifest (netctl#731 Strand 2).

Strand 1 (``delivery.topology``) proved a product-agnostic topology manifest can EXPRESS a containerlab mesh.
Strand 2 extracts the generic RENDER STAGE that turns a fully-derived context into on-disk artifacts: a Jinja
environment with the byte-exact containerlab flags, the #453 multi-tenant INSTANCE-SCOPING apply (topology
name + mgmt network + mgmt subnet), and the WireGuard X25519 KEYGEN. A product's derivation compiler (netctl:
``labgen.generate.build_context``) stays product-side and emits BOTH the manifest and its own render context;
this engine renders the product's templates to files, scoped by the manifest's ``InstanceScoping`` policy.

GENERIC vs PRODUCT boundary. This module knows NOTHING about a product's node types, services or address
policy. It knows only: (a) a Jinja template renders to a file, (b) a manifest carries a scoped identity + an
instance policy, (c) WireGuard keys are minted the same way for anyone. The netctl-specific templates + the
derived render context are the PRODUCT's; the engine drives them. That separation is what lets Strand 4 render
a deliberately-different (non-netctl) manifest through the same engine with zero product code - the anti-leak
proof.

Byte-for-byte discipline. The reserved ``default_instance`` (netctl: ``dev``) collapses every scoped axis to
its bare literal, so a product's committed golden survives the extraction unchanged; the Jinja environment
pins ``trim_blocks``/``lstrip_blocks``/``keep_trailing_newline`` exactly as a direct render would, so moving
the render behind this engine changes no emitted byte.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from jinja2 import Environment, FileSystemLoader

from delivery.topology import InstanceScoping, TopologyManifest

# The reserved instance that renders byte-for-byte (no token infix, no subnet offset). A manifest's
# ``InstanceScoping.default_instance`` overrides this per-product; kept as a module default for the
# policy-less path.
DEFAULT_INSTANCE = "dev"

# The deterministic mgmt-subnet offset band for non-default instances: 10.128.0.0/24 .. 10.223.0.0/24.
# Only the mgmt subnet needs a per-instance offset (docker refuses overlapping bridge subnets); every other
# prefix stays identical because it is isolated per OOB bridge / per-container netns. 96 distinct subnets.
_MGMT_OFFSET_BASE = 128
_MGMT_OFFSET_SPAN = 96


# ---------------------------------------------------------------------------
# WireGuard keygen - a generic mechanism (leak-inventory item 6: the keygen is movable, the peer-table
# BAKING stays product-side because it is keyed on the product's device-id derivation).
# ---------------------------------------------------------------------------
def wg_keypair() -> tuple[str, str]:
    """A WireGuard X25519 keypair as ``(private_b64, public_b64)`` - exactly wg's key format (raw 32-byte
    X25519 keys, base64). ``cryptography`` is imported lazily so merely importing this engine never requires
    it; only a product that actually mints wg keys pulls the dependency."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    priv = X25519PrivateKey.generate()
    private_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
    public_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    return private_b64, public_b64


# ---------------------------------------------------------------------------
# #453 instance-scoping - PURE naming/offset primitives driven by the manifest's InstanceScoping policy.
# ---------------------------------------------------------------------------
def scoped_name(base: str, instance: str, *, default_instance: str = DEFAULT_INSTANCE) -> str:
    """Scope a shared-namespace base name by the instance id. The reserved ``default_instance`` collapses to
    the bare base (byte-identical back-compat); any other id is infixed as ``<base>-<instance>``."""
    return base if instance == default_instance else f"{base}-{instance}"


def offset_mgmt_subnet(dev_subnet: str, instance: str, *, default_instance: str = DEFAULT_INSTANCE,
                       override: str | None = None) -> str:
    """The mgmt /24 for an instance: ``dev_subnet`` for the reserved instance, else a deterministic,
    collision-free ``10.<K>.0.0/24`` (K in [128,223], sha1 of the id - stable across processes, unlike the
    salted builtin hash). ``override`` (a product may pass an env value) wins for ANY instance and must be an
    IPv4 /24, else a loud ValueError so a typo cannot silently mis-address the lab."""
    if override and override.strip():
        net = ipaddress.ip_network(override.strip(), strict=True)
        if net.version != 4 or net.prefixlen != 24:
            raise ValueError(f"mgmt subnet override must be an IPv4 /24, got '{override}'")
        return str(net)
    if instance == default_instance:
        return dev_subnet
    digest = int(hashlib.sha1(instance.encode("utf-8")).hexdigest(), 16)
    return f"10.{_MGMT_OFFSET_BASE + digest % _MGMT_OFFSET_SPAN}.0.0/24"


def validate_instance(instance: str, policy: InstanceScoping | None) -> str:
    """Return ``instance`` if it is a legal id for ``policy``, else raise ValueError. The policy's
    ``default_instance`` is always legal; any other id must match ``token_charset`` and be at most
    ``token_max_len`` chars, so an ifname-unsafe / over-long id is rejected LOUDLY (never silently
    truncated, which would alias two labs onto one namespace). A ``None`` policy accepts any id (the
    unscoped path)."""
    if policy is None:
        return instance
    if instance == policy.default_instance:
        return instance
    charset = policy.token_charset.strip()
    if charset.startswith("[") and charset.endswith("]"):
        charset = charset[1:-1]
    if not re.fullmatch(rf"[{charset}]{{1,{policy.token_max_len}}}", instance):
        raise ValueError(
            f"instance id {instance!r} is invalid; use 1-{policy.token_max_len} chars of "
            f"'{policy.token_charset}' (the manifest's instance-scoping policy)")
    return instance


class ScopedIdentity(NamedTuple):
    """A manifest's identity after the #453 instance-scoping apply: the containerlab topology name, the mgmt
    docker network name and the mgmt subnet, each collapsed to its literal for the reserved instance."""

    topology_name: str
    mgmt_network: str
    mgmt_subnet: str


def apply_instance_scoping(manifest: TopologyManifest, instance: str) -> ScopedIdentity:
    """Apply the manifest's ``InstanceScoping`` policy to derive the scoped identity for ``instance``. The
    topology name and mgmt network are token-infixed; the mgmt subnet is taken from the manifest as-is (the
    product's compiler already offset it, because every mgmt IP derives from it - the offset is derivation
    input, not a render-only concern). For the reserved instance every axis is the bare literal, so a
    product's committed golden renders byte-for-byte."""
    default = manifest.instance_scoping.default_instance if manifest.instance_scoping else DEFAULT_INSTANCE
    return ScopedIdentity(
        topology_name=scoped_name(manifest.name, instance, default_instance=default),
        mgmt_network=scoped_name(manifest.mgmt.network, instance, default_instance=default),
        mgmt_subnet=manifest.mgmt.ipv4_subnet,
    )


# ---------------------------------------------------------------------------
# The render engine.
# ---------------------------------------------------------------------------
class ClabRenderer:
    """A generic containerlab render engine bound to a manifest + an instance. It pins the byte-exact Jinja
    environment (``trim_blocks``/``lstrip_blocks``/``keep_trailing_newline``, matching a direct clab render),
    resolves the manifest's scoped identity once, and exposes a render-to-file primitive a product drives to
    emit its clab topology + per-node config artifacts + seed. The engine holds NO product knowledge: the
    templates + the render context are the product's; the engine renders them."""

    def __init__(self, manifest: TopologyManifest, *, templates_dir: str | Path,
                 instance: str = DEFAULT_INSTANCE) -> None:
        self.manifest = manifest
        self.instance = instance
        self.identity = apply_instance_scoping(manifest, instance)
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
        )

    def topology_context(self) -> dict[str, str]:
        """The scoped identity as a render-context fragment (``topo_name`` / ``mgmt_network`` /
        ``mgmt_subnet``) a product's clab template consumes for its header."""
        return {
            "topo_name": self.identity.topology_name,
            "mgmt_network": self.identity.mgmt_network,
            "mgmt_subnet": self.identity.mgmt_subnet,
        }

    def render_str(self, template_name: str, context: Mapping[str, Any]) -> str:
        """Render a template to a string with the engine's byte-exact environment."""
        return self.env.get_template(template_name).render(**context)

    def render_to_file(self, template_name: str, out_path: str | Path, context: Mapping[str, Any],
                       *, executable: bool = False) -> Path:
        """Render ``template_name`` with ``context`` and write it to ``out_path`` (creating parent dirs);
        chmod 0o755 when ``executable`` (a shell artifact clab/an entrypoint runs). Returns the path."""
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.render_str(template_name, context))
        if executable:
            os.chmod(out_path, 0o755)
        return out_path

    def render_topology(self, template_name: str, out_path: str | Path, context: Mapping[str, Any],
                        *, executable: bool = False) -> Path:
        """Emit the clab topology: render ``template_name`` with ``context`` MERGED with the manifest's
        scoped identity (topo name / mgmt network / mgmt subnet), so the product template need not re-derive
        the #453 scoping. The explicit identity wins over any same-named key the product context carries."""
        merged = {**dict(context), **self.topology_context()}
        return self.render_to_file(template_name, out_path, merged, executable=executable)
