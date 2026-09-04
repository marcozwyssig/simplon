"""netctl#731 Strand 4 - the ANTI-LEAK PROOF. Strand 1 proved the manifest CAN express netctl's mesh;
that alone does not prove the schema/renderer/substrate are not secretly netctl-shaped. This suite renders
a SECOND, deliberately-non-netctl topology (`clos-2t`, a 2-tier leaf-spine DC fabric) through the SAME
generic schema (S1 `delivery.topology`), the SAME generic engine (S2 `delivery.clabrender`) and the SAME
substrate verdict (S3 `delivery.labnet`/`delivery.clablifecycle`) - with ZERO product code.

clos-2t differs from netctl on every axis: a Clos graph (not a site mesh); a vendor mix Nokia SR Linux +
Arista cEOS + Alpine (none of frr/ios/vyos, no cisco_iol); opaque roles spine/leaf/host (none of l3s/w3s/
ogw); NO OGW/EVPN/MPLS/WireGuard; NO OOB bridges; NO controllers/`/api`/seed; NO #453 scoping.

Each test falsifies ONE leak-inventory item: if the generic renderer or the substrate verdict demanded
anything only netctl can supply, that test would fail. The single SHARPEST proof is that the substrate
declares the lab UP from the CONTAINER COUNT alone (`labnet.deploy_verdict`), never an `/api` probe - so a
controller-less lab like clos-2t can reach "UP". AAA throughout; the render assertions read the PARSED clab
document (not raw text) so an explanatory comment can never satisfy an assertion by accident.

HONEST LIMIT: a LIVE `clab deploy` of clos-2t needs real Nokia SR Linux + Arista cEOS images, which are not
pullable in this unit environment. This suite proves S4 at the RENDER + VERDICT-LOGIC level; the live
bring-up (real images + the S3 substrate on a Colima Mac) is a separate, manual completing step.
"""
import inspect
from pathlib import Path

import pytest
import yaml

from delivery import clablifecycle, clabrender, degraded, labnet, topology
from delivery.clablifecycle import BringUpSpec
from delivery.run import Result

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "clos-2t.topology.yml"

# The netctl fingerprints clos-2t must NOT carry (the leak inventory made concrete).
_NETCTL_KINDS = {"cisco_iol", "vyosnetworks_vyos"}
_NETCTL_VENDORS = {"frr", "ios", "vyos"}
_NETCTL_ROLE_NODES = ("l3s", "w3s", "ogw", "sidecar", "postgres", "netctl", "keycloak", "openbao", "zabbix")


@pytest.fixture
def manifest() -> topology.TopologyManifest:
    # arrange: the clos-2t sample loaded through the S1 schema (proves it validates as-is)
    return topology.load(_FIXTURE.read_text())


@pytest.fixture
def clab_doc(manifest, tmp_path) -> dict:
    # arrange/act: render clos-2t through the fully-generic engine (NO product templates dir) and parse the
    # emitted *.clab.yml back as YAML - the render surface every leak test inspects.
    out = tmp_path / "clos-2t.clab.yml"
    clabrender.ClabRenderer.generic(manifest, instance="dev").render_generic_topology(out)
    return yaml.safe_load(out.read_text())


# --- S1: the non-netctl manifest validates against the generic schema as-is ---------------------------

def test_clos2t_validates_against_the_generic_schema_extra_forbid_clean(manifest):
    # assert: the manifest parses into typed objects - 6 nodes, 6 links, ONE site, NO bridges, NO scoping;
    # the vendor registry resolves the non-netctl kinds. (extra="forbid" already ran inside load().)
    assert manifest.name == "clos-2t"
    assert [n.name for n in manifest.nodes] == ["spine1", "spine2", "leaf1", "leaf2", "h1", "h2"]
    assert len(manifest.links) == 6
    assert [s.name for s in manifest.sites] == ["dc1"]
    assert manifest.bridges == []           # no OOB bridge declared
    assert manifest.instance_scoping is None  # no #453 scoping declared
    assert set(manifest.vendor_kinds) == {"srl", "ceos", "host"}


def test_clos2t_renders_to_a_valid_clab_topology_through_the_generic_engine(clab_doc):
    # assert: the generic render is a well-formed clab document - name, mgmt header, all 6 nodes, 6 links
    assert clab_doc["name"] == "clos-2t"
    assert clab_doc["mgmt"] == {"network": "clos-mgmt", "ipv4-subnet": "172.20.20.0/24"}
    assert set(clab_doc["topology"]["nodes"]) == {"spine1", "spine2", "leaf1", "leaf2", "h1", "h2"}
    assert len(clab_doc["topology"]["links"]) == 6


# --- leak item: no OOB bridge required ----------------------------------------------------------------

def test_render_needs_no_oob_bridge(manifest, clab_doc):
    # arrange: clos-2t declares zero bridges
    assert manifest.bridges == []

    # assert: it renders anyway, and NOT ONE emitted clab node is a bridge (OOB is optional, not baked)
    kinds = {name: node.get("kind") for name, node in clab_doc["topology"]["nodes"].items()}
    assert "bridge" not in kinds.values(), f"a bridge leaked into a bridge-less topology: {kinds}"


# --- leak item: no instance-scoping / site-id address derivation --------------------------------------

def test_render_needs_no_instance_scoping_policy(manifest, tmp_path):
    # arrange: clos-2t declares no instance_scoping; render at the default AND at a non-dev instance
    assert manifest.instance_scoping is None
    dev = tmp_path / "dev.clab.yml"
    a1 = tmp_path / "a1.clab.yml"

    # act: both must succeed - a missing policy is not a render prerequisite
    clabrender.ClabRenderer.generic(manifest, instance="dev").render_generic_topology(dev)
    clabrender.ClabRenderer.generic(manifest, instance="a1").render_generic_topology(a1)

    # assert: dev is the bare literal; a non-dev id still scopes the name off the module default (proving
    # scoping is a render-time OPTION applied uniformly, never a structural demand on the manifest)
    assert yaml.safe_load(dev.read_text())["name"] == "clos-2t"
    assert yaml.safe_load(a1.read_text())["name"] == "clos-2t-a1"


def test_mgmt_addresses_come_from_the_manifest_not_a_netctl_derivation(manifest, clab_doc):
    # arrange: the manifest pins the spine/leaf mgmt IPs on 172.20.20.x; the hosts declare none
    nodes = clab_doc["topology"]["nodes"]

    # assert: each address is EXACTLY the manifest's literal - no netctl _did/0x800/0x900 derivation, no
    # site-id math produced them; and the address-less hosts get NO fabricated mgmt-ipv4 (clab auto-assigns)
    assert nodes["spine1"]["mgmt-ipv4"] == "172.20.20.11"
    assert nodes["spine2"]["mgmt-ipv4"] == "172.20.20.12"
    assert nodes["leaf1"]["mgmt-ipv4"] == "172.20.20.21"
    assert nodes["leaf2"]["mgmt-ipv4"] == "172.20.20.22"
    assert "mgmt-ipv4" not in nodes["h1"] and "mgmt-ipv4" not in nodes["h2"]


# --- leak item: opaque roles, no l3s/w3s/ogw, no controller/sidecar -----------------------------------

def test_roles_are_opaque_the_render_never_reads_them(manifest, tmp_path):
    # arrange: render clos-2t as-is (roles spine/leaf/host), then re-render with EVERY role rewritten to
    # netctl's own l3s/w3s/ogw - if the renderer keyed off role, the bytes would differ
    baseline = tmp_path / "baseline.clab.yml"
    clabrender.ClabRenderer.generic(manifest).render_generic_topology(baseline)

    mutated = topology.load(_FIXTURE.read_text())
    for node, netctl_role in zip(mutated.nodes, ["l3s", "w3s", "ogw", "l3s", "w3s", "ogw"]):
        node.role = netctl_role
    rerendered = tmp_path / "rerendered.clab.yml"
    clabrender.ClabRenderer.generic(mutated).render_generic_topology(rerendered)

    # assert: byte-identical - role is a purely opaque label the render ignores structurally
    assert rerendered.read_bytes() == baseline.read_bytes()


def test_no_controller_sidecar_or_netctl_role_node_is_required(clab_doc):
    # assert: the topology is controller-less - no node name carries a netctl role/service token, and there
    # is no `/api`-bearing controller node. The lab is purely spine/leaf/host.
    names = set(clab_doc["topology"]["nodes"])
    for token in _NETCTL_ROLE_NODES:
        assert not any(token in name for name in names), f"a netctl role node '{token}' leaked into {names}"
    # role is manifest-internal and is NEVER emitted as a clab key on any node
    for name, node in clab_doc["topology"]["nodes"].items():
        assert "role" not in node, f"node {name} leaked the manifest-internal 'role' as a clab key"


# --- leak item: no frr/ios/vyos vendor, no hardcoded cisco_iol/amd64 ----------------------------------

def test_vendor_kinds_are_the_manifests_not_netctls(manifest, clab_doc):
    # arrange: clos-2t's vendor set is srl/ceos/host -> nokia_srlinux/arista_ceos/linux
    assert _NETCTL_VENDORS.isdisjoint(manifest.vendor_kinds)

    # assert: the emitted kinds are EXACTLY the manifest's resolved kinds; no netctl kind is hardcoded, and
    # no cisco_iol/amd64 is injected independent of the manifest
    kinds = {node["kind"] for node in clab_doc["topology"]["nodes"].values()}
    assert kinds == {"nokia_srlinux", "arista_ceos", "linux"}
    assert kinds.isdisjoint(_NETCTL_KINDS)
    images = {node.get("image") for node in clab_doc["topology"]["nodes"].values()}
    assert images == {"ghcr.io/nokia/srlinux:24.7.1", "ceos:4.32.0F", "alpine:3.20"}


# --- leak item: startup_config is an OPAQUE ref -------------------------------------------------------

def test_startup_config_is_carried_verbatim_as_an_opaque_ref(clab_doc):
    # assert: each startup-config is the manifest's ref byte-for-byte - the renderer never rewrote it to a
    # netctl `frr/underlay.sh` / `ios/<node>.cfg`, nor parsed/interpreted its contents
    nodes = clab_doc["topology"]["nodes"]
    assert nodes["spine1"]["startup-config"] == "cfg/spine1.cfg"
    assert nodes["spine2"]["startup-config"] == "cfg/spine2.cfg"
    assert nodes["leaf1"]["startup-config"] == "cfg/leaf1.cfg"
    assert nodes["leaf2"]["startup-config"] == "cfg/leaf2.cfg"
    # the address-less hosts declared no startup_config, so none is fabricated
    assert "startup-config" not in nodes["h1"] and "startup-config" not in nodes["h2"]


# --- the SHARPEST proof: the up-verdict is container-count-based, never an /api probe ------------------

class _CountingHost:
    """A fake docker host with NO controller and NO REST surface: it answers `sh` (clab deploy succeeds)
    and `docker ps` (a fixed running-container count). Driving the substrate through it proves the up-verdict
    is decided from the container COUNT alone - there is nothing here an `/api` readiness probe could call."""

    is_darwin = False

    def __init__(self, running: int):
        self._running = running
        self.sh_calls: list[str] = []

    def sh(self, script, *, capture=True):
        self.sh_calls.append(script)
        return Result(rc=0, out="", err="")  # clab deploy completes cleanly

    def docker(self, *args, capture=True):
        if args[:1] == ("ps",):
            return Result(rc=0, out="\n".join(f"c{i}" for i in range(self._running)), err="")
        return Result(rc=0, out="", err="")


@pytest.fixture(autouse=True)
def _reset_degraded():
    degraded.reset()
    yield
    degraded.reset()


def test_deploy_verdict_decides_up_from_the_container_count_with_no_api_argument():
    # assert: the DECISION takes only (deployed, container_count) - no host, no url, no /api readiness. A
    # clean deploy of clos-2t's 6 containers is "ok" (UP); nothing about a controller enters the verdict.
    params = list(inspect.signature(labnet.deploy_verdict).parameters)
    assert params == ["deployed", "container_count"]
    assert labnet.deploy_verdict(True, 6) == "ok"       # 6 nodes up, clean deploy -> UP
    assert labnet.deploy_verdict(False, 6) == "degraded"  # partial -> degraded, still not an /api question
    assert labnet.deploy_verdict(False, 0) == "die"      # nothing up -> fatal (a missing image)


def test_controller_less_clos2t_reaches_up_with_zero_controllers_no_oob_no_seed(manifest):
    # arrange: the BringUpSpec a product would derive for clos-2t - NO OOB bridges (the manifest declares
    # none), NO amd64 flag inferred by the substrate, and crucially NO controller/api/seed anywhere.
    spec = BringUpSpec(
        output_dir=Path("/lab/clos-2t"),
        topology_file="clos-2t.clab.yml",
        topology_path=Path("/lab/clos-2t/clos-2t.clab.yml"),
        container_prefix="clab-clos-2t-",
        mgmt_network="clos-mgmt",
        bridges=tuple(b.name for b in manifest.bridges),  # () - clos-2t has no OOB bridge
    )
    assert spec.bridges == ()
    host = _CountingHost(running=6)  # all 6 clos-2t nodes come up

    # act: deploy, then the authoritative verdict - two phases the product runs, here controller-less
    deploy_rc = clablifecycle.deploy(host, spec)
    verdict_rc = clablifecycle.up_verdict(strict=False)

    # assert: the lab is UP purely from the container count - clean deploy, ZERO degradation, and the
    # substrate never created an OOB bridge (no `ip link add` ran) nor probed any REST endpoint
    assert deploy_rc == 0 and verdict_rc == 0
    assert degraded.items() == []
    assert not any("ip link add" in s for s in host.sh_calls)


def test_the_up_verdict_logic_references_no_http_api_readiness_probe():
    # assert (structural): neither the substrate's post-deploy DECISION nor its authoritative verdict names
    # an HTTP/`/api` readiness probe. Convergence-waiting is a product callback injected AROUND the
    # substrate (netctl's wait_stable), never a capability the substrate performs to declare "up".
    for fn in (labnet.deploy_verdict, clablifecycle.up_verdict):
        src = inspect.getsource(fn).lower()
        for forbidden in ("/api", "http", "requests", "wait_stable", "readiness", "curl"):
            assert forbidden not in src, f"{fn.__name__} references '{forbidden}' - the up-verdict leaked a probe"
