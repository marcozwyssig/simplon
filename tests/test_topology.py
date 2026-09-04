"""Unit tests for the generic containerlab topology manifest schema (delivery.topology): the pure YAML load
+ Pydantic validation of nodes/links/bridges/sites/vendor_kinds/instance_scoping, the cross-object integrity
rules (unique names, dangling references, endpoint resolution, kind resolution) and the resolution helpers.
Exercised on SYNTHETIC manifests so the schema is validated independently of any product's mesh. AAA
throughout, including the negative cases (the fail-loud contract is the whole value of the schema).
"""
import pytest

from delivery import topology

_OK = """
name: demo-lab
mgmt:
  network: demo-mgmt
  ipv4_subnet: 10.0.0.0/24
vendor_kinds:
  frr:  { kind: linux, image: demo-frr:local }
  ios:  { kind: cisco_iol, image: demo/iol:17, type: l2 }
sites:
  - { name: a, id: 1, attributes: { http_port: 8080 } }
  - { name: b, id: 2 }
nodes:
  - { name: r-a, site: a, role: router, vendor: frr, mgmt_ipv4: 10.0.0.11, config_template: cfg/r-a.sh }
  - { name: r-b, site: b, role: router, vendor: ios, image: demo/iol:custom }
  - { name: mon, kind: linux, image: prom:latest }
bridges:
  - { name: oob-a, site: a }
links:
  - { endpoints: ["r-a:eth1", "r-b:eth1"] }
  - { endpoints: ["r-a:eth9", "oob-a:oob-a-r"] }
instance_scoping:
  default_instance: dev
  token_max_len: 2
  scoped_axes: [topology_name, mgmt_network, oob_bridge]
"""


def test_load_parses_a_well_formed_manifest_into_typed_objects():
    # arrange / act
    mf = topology.load(_OK)

    # assert: the top-level shape is the typed manifest with its sites/nodes/links/bridges
    assert mf.name == "demo-lab"
    assert mf.mgmt.network == "demo-mgmt"
    assert [s.name for s in mf.sites] == ["a", "b"]
    assert {n.name for n in mf.nodes} == {"r-a", "r-b", "mon"}
    assert len(mf.links) == 2
    assert [b.name for b in mf.bridges] == ["oob-a"]


def test_load_keeps_product_knobs_in_the_free_form_attributes_bag():
    # arrange / act: a site's product-specific knob is carried in attributes, not a schema field
    mf = topology.load(_OK)

    # assert: the bag round-trips verbatim (the schema does not freeze http_port into itself)
    site_a = next(s for s in mf.sites if s.name == "a")
    assert site_a.attributes == {"http_port": 8080}


def test_vendor_registry_resolves_kind_and_default_image():
    # arrange
    mf = topology.load(_OK)

    # act
    r_a = next(n for n in mf.nodes if n.name == "r-a")

    # assert: the vendor supplies both kind and the default image
    assert mf.kind_of(r_a) == "linux"
    assert mf.image_of(r_a) == "demo-frr:local"


def test_node_image_override_wins_over_the_vendor_default():
    # arrange
    mf = topology.load(_OK)

    # act: r-b declares ios (default demo/iol:17) but overrides the image
    r_b = next(n for n in mf.nodes if n.name == "r-b")

    # assert: the explicit image overrides, the kind still comes from the vendor
    assert mf.kind_of(r_b) == "cisco_iol"
    assert mf.image_of(r_b) == "demo/iol:custom"


def test_explicit_kind_needs_no_vendor():
    # arrange / act: `mon` is a global node with an explicit kind and no vendor
    mf = topology.load(_OK)
    mon = next(n for n in mf.nodes if n.name == "mon")

    # assert: it resolves without a registry entry, and has no site (global)
    assert mf.kind_of(mon) == "linux"
    assert mon.site is None


def test_nodes_for_site_groups_by_the_site_label():
    # arrange
    mf = topology.load(_OK)

    # act / assert: only the site-a nodes come back, in declaration order
    assert [n.name for n in mf.nodes_for_site("a")] == ["r-a"]
    assert [n.name for n in mf.nodes_for_site("b")] == ["r-b"]


def test_link_node_names_split_the_endpoint_owner_from_the_iface():
    # arrange
    mf = topology.load(_OK)

    # act / assert: a bridge is a valid endpoint owner alongside a node
    assert mf.links[0].node_names() == ("r-a", "r-b")
    assert mf.links[1].node_names() == ("r-a", "oob-a")


# --- fail-loud: shape / type errors -----------------------------------------------------------------

def test_load_rejects_an_unknown_top_level_key():
    # arrange: a typo'd top-level section must not be silently ignored (extra=forbid)
    text = _OK + "\nndoes: []\n"

    # act / assert
    with pytest.raises(ValueError):
        topology.load(text)


def test_load_rejects_an_unknown_node_key():
    # arrange: a mistyped node key (imgae) is the exact slip a schema exists to catch
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: n1, kind: linux, imgae: oops }
"""

    # act / assert
    with pytest.raises(ValueError):
        topology.load(text)


def test_load_rejects_an_invalid_mgmt_subnet():
    # arrange
    text = "name: x\nmgmt: { network: m, ipv4_subnet: 10.0.0.0/33 }\n"

    # act / assert
    with pytest.raises(ValueError, match="not a valid CIDR"):
        topology.load(text)


def test_load_rejects_a_link_endpoint_that_is_not_node_colon_iface():
    # arrange: an endpoint missing the iface part
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: n1, kind: linux }
links:
  - { endpoints: ["n1", "n1:eth1"] }
"""

    # act / assert
    with pytest.raises(ValueError, match="must be 'node:iface'"):
        topology.load(text)


def test_load_rejects_a_link_with_the_wrong_endpoint_count():
    # arrange: three endpoints is not a clab link
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: n1, kind: linux }
links:
  - { endpoints: ["n1:eth1", "n1:eth2", "n1:eth3"] }
"""

    # act / assert
    with pytest.raises(ValueError, match="pair"):
        topology.load(text)


# --- fail-loud: cross-object integrity rules --------------------------------------------------------

def test_load_rejects_a_node_with_neither_kind_nor_vendor():
    # arrange
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: n1, role: router }
"""

    # act / assert
    with pytest.raises(ValueError, match="needs either 'kind' or 'vendor'"):
        topology.load(text)


def test_load_rejects_a_node_referencing_an_undeclared_vendor():
    # arrange: the vendor key is not in the registry
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
vendor_kinds: { frr: { kind: linux } }
nodes:
  - { name: n1, vendor: nope }
"""

    # act / assert
    with pytest.raises(ValueError, match="vendor 'nope' is not a declared vendor_kind"):
        topology.load(text)


def test_load_rejects_a_node_referencing_an_undeclared_site():
    # arrange
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
sites: [ { name: a, id: 1 } ]
nodes:
  - { name: n1, kind: linux, site: b }
"""

    # act / assert
    with pytest.raises(ValueError, match="site 'b' is not a declared site"):
        topology.load(text)


def test_load_rejects_a_link_endpoint_naming_an_undeclared_node():
    # arrange: the second endpoint names a node that does not exist
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: n1, kind: linux }
links:
  - { endpoints: ["n1:eth1", "ghost:eth1"] }
"""

    # act / assert
    with pytest.raises(ValueError, match="endpoint 'ghost' is not a declared node or bridge"):
        topology.load(text)


def test_load_accepts_a_link_endpoint_naming_a_declared_bridge():
    # arrange: a bridge IS a valid endpoint owner (the OOB wiring case)
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: n1, kind: linux }
bridges:
  - { name: oob }
links:
  - { endpoints: ["n1:eth9", "oob:oob-n1"] }
"""

    # act
    mf = topology.load(text)

    # assert: it validates and the bridge is the endpoint owner
    assert mf.links[0].node_names() == ("n1", "oob")


def test_load_rejects_duplicate_node_names():
    # arrange
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: dup, kind: linux }
  - { name: dup, kind: linux }
"""

    # act / assert
    with pytest.raises(ValueError, match="duplicate node/bridge name"):
        topology.load(text)


def test_load_rejects_a_node_and_bridge_sharing_a_name():
    # arrange: nodes and bridges share ONE endpoint namespace, so a clash is ambiguous
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
nodes:
  - { name: clash, kind: linux }
bridges:
  - { name: clash }
"""

    # act / assert
    with pytest.raises(ValueError, match="duplicate node/bridge name"):
        topology.load(text)


def test_load_rejects_duplicate_site_ids():
    # arrange
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
sites:
  - { name: a, id: 1 }
  - { name: b, id: 1 }
"""

    # act / assert
    with pytest.raises(ValueError, match="duplicate site id"):
        topology.load(text)


def test_load_rejects_a_non_positive_site_id():
    # arrange
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
sites: [ { name: a, id: 0 } ]
"""

    # act / assert
    with pytest.raises(ValueError, match="positive integer"):
        topology.load(text)


# --- instance scoping -------------------------------------------------------------------------------

def test_instance_scoping_parses_the_policy():
    # arrange / act
    mf = topology.load(_OK)

    # assert: the #453 policy is carried verbatim for the engine to consume
    assert mf.instance_scoping is not None
    assert mf.instance_scoping.default_instance == "dev"
    assert mf.instance_scoping.token_max_len == 2
    assert "oob_bridge" in mf.instance_scoping.scoped_axes


def test_instance_scoping_rejects_an_invalid_default_token():
    # arrange: the reserved instance token must be ifname-safe (lowercase alnum)
    text = """
name: x
mgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }
instance_scoping: { default_instance: "DEV!" }
"""

    # act / assert
    with pytest.raises(ValueError, match="lowercase alnum"):
        topology.load(text)


def test_instance_scoping_is_optional():
    # arrange: a manifest may omit scoping entirely (a single-tenant lab)
    text = "name: x\nmgmt: { network: m, ipv4_subnet: 10.0.0.0/24 }\n"

    # act / assert
    mf = topology.load(text)
    assert mf.instance_scoping is None
