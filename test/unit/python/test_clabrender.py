"""netctl#731 Strand 2 - the generic clab render engine (delivery.clabrender) renders a topology manifest to
files, applies the #453 instance-scoping from the manifest's policy, and mints WireGuard keys - all with ZERO
product knowledge. The manifest used here is a deliberately-minimal, NON-netctl lab (a 2-node linear topology),
so a green suite proves the engine is not netctl-shaped: the same engine renders any product's manifest. AAA
throughout, goal-stating names incl. the negative validate_instance case.
"""
import base64

import pytest

from delivery import clabrender, topology

# A tiny, deliberately non-netctl manifest: two linux nodes on a mgmt net, one link, an instance policy.
_MINIMAL = """
name: tinylab
mgmt: { network: tinylab-mgmt, ipv4_subnet: 10.9.0.0/24 }
instance_scoping: { default_instance: dev, token_max_len: 2, token_charset: "[a-z0-9]" }
nodes:
  - { name: a, kind: linux, image: alpine:3, mgmt_ipv4: 10.9.0.10 }
  - { name: b, kind: linux, image: alpine:3, mgmt_ipv4: 10.9.0.11 }
links:
  - { endpoints: ["a:eth1", "b:eth1"] }
"""

# A minimal generic clab template driven purely by the schema fields + the engine's scoped identity.
_TEMPLATE = """name: {{ topo_name }}
mgmt:
  network: {{ mgmt_network }}
  ipv4-subnet: {{ mgmt_subnet }}
topology:
  nodes:
{% for n in nodes %}
    {{ n.name }}: { kind: {{ n.kind }}, image: {{ n.image }}, mgmt-ipv4: {{ n.mgmt_ipv4 }} }
{% endfor %}
  links:
{% for l in links %}
    - endpoints: {{ l.endpoints }}
{% endfor %}
"""


@pytest.fixture
def manifest() -> topology.TopologyManifest:
    # arrange: a validated, minimal, non-netctl manifest reused across the render tests.
    return topology.load(_MINIMAL)


@pytest.fixture
def templates_dir(tmp_path):
    # arrange: a throwaway templates dir holding the one generic clab template.
    (tmp_path / "tiny.clab.yml.j2").write_text(_TEMPLATE)
    return tmp_path


# --- WireGuard keygen (moved generic mechanism) -------------------------------------------------------

def test_wg_keypair_returns_two_distinct_base64_encoded_32_byte_keys():
    # act
    priv, pub = clabrender.wg_keypair()

    # assert: both are wg-format keys (base64 of raw 32-byte X25519) and a private != its public.
    assert priv != pub
    for key in (priv, pub):
        assert len(base64.b64decode(key)) == 32


def test_wg_keypair_mints_a_fresh_pair_each_call():
    # act / assert: non-deterministic by design (a fresh keypair per render), so two calls differ.
    assert clabrender.wg_keypair()[0] != clabrender.wg_keypair()[0]


# --- #453 instance-scoping primitives -----------------------------------------------------------------

def test_scoped_name_collapses_the_reserved_default_to_the_bare_base():
    # act / assert: the reserved instance renders byte-for-byte (no infix).
    assert clabrender.scoped_name("tinylab", "dev") == "tinylab"


def test_scoped_name_infixes_any_other_token():
    # act / assert: a non-default id is infixed as <base>-<id>.
    assert clabrender.scoped_name("tinylab", "a1") == "tinylab-a1"
    assert clabrender.scoped_name("tinylab-mgmt", "a1") == "tinylab-mgmt-a1"


def test_offset_mgmt_subnet_keeps_the_dev_subnet_for_the_reserved_instance():
    # act / assert: dev is byte-identical - the declared subnet, no offset.
    assert clabrender.offset_mgmt_subnet("10.9.0.0/24", "dev") == "10.9.0.0/24"


def test_offset_mgmt_subnet_moves_a_non_dev_instance_to_a_deterministic_collision_free_24():
    # act
    sub = clabrender.offset_mgmt_subnet("10.9.0.0/24", "a1")

    # assert: a stable 10.<128..223>.0.0/24, clear of the dev subnet, and deterministic across calls.
    assert sub != "10.9.0.0/24"
    assert sub.startswith("10.") and sub.endswith(".0.0/24")
    second_octet = int(sub.split(".")[1])
    assert 128 <= second_octet <= 223
    assert clabrender.offset_mgmt_subnet("10.9.0.0/24", "a1") == sub


def test_offset_mgmt_subnet_honours_an_explicit_override_for_any_instance():
    # act / assert: a product-supplied override wins even for the reserved instance.
    assert clabrender.offset_mgmt_subnet("10.9.0.0/24", "dev", override="10.44.0.0/24") == "10.44.0.0/24"


def test_offset_mgmt_subnet_rejects_a_non_slash24_override_loudly():
    # act / assert: a garbage / non-/24 override fails loudly, never silently mis-addressing the lab.
    with pytest.raises(ValueError):
        clabrender.offset_mgmt_subnet("10.9.0.0/24", "a1", override="not-a-cidr")
    with pytest.raises(ValueError):
        clabrender.offset_mgmt_subnet("10.9.0.0/24", "a1", override="10.44.0.0/16")


# --- apply_instance_scoping (manifest policy -> scoped identity) ---------------------------------------

def test_apply_instance_scoping_yields_bare_literals_for_the_reserved_instance(manifest):
    # act
    identity = clabrender.apply_instance_scoping(manifest, "dev")

    # assert: every axis collapses to the manifest's literal (the byte-for-byte guarantee).
    assert identity == clabrender.ScopedIdentity("tinylab", "tinylab-mgmt", "10.9.0.0/24")


def test_apply_instance_scoping_infixes_the_token_for_a_non_dev_instance(manifest):
    # act
    identity = clabrender.apply_instance_scoping(manifest, "a1")

    # assert: name + network are token-infixed (the mgmt subnet is taken from the manifest as-is - the
    # product compiler owns the offset because every mgmt IP derives from it).
    assert identity.topology_name == "tinylab-a1"
    assert identity.mgmt_network == "tinylab-mgmt-a1"


# --- validate_instance (policy-driven) ----------------------------------------------------------------

def test_validate_instance_accepts_the_default_and_a_legal_token(manifest):
    # act / assert
    assert clabrender.validate_instance("dev", manifest.instance_scoping) == "dev"
    assert clabrender.validate_instance("a1", manifest.instance_scoping) == "a1"


def test_validate_instance_rejects_an_over_long_or_ifname_unsafe_token(manifest):
    # arrange: token_max_len is 2 and the charset is [a-z0-9].
    # act / assert: a 3-char id and an uppercase id both fail loudly.
    with pytest.raises(ValueError):
        clabrender.validate_instance("abc", manifest.instance_scoping)
    with pytest.raises(ValueError):
        clabrender.validate_instance("A1", manifest.instance_scoping)


# --- the render engine (generic, byte-exact) ----------------------------------------------------------

def test_renderer_emits_the_clab_topology_with_the_dev_identity(manifest, templates_dir, tmp_path):
    # arrange
    renderer = clabrender.ClabRenderer(manifest, templates_dir=templates_dir, instance="dev")
    out = tmp_path / "out.clab.yml"

    # act: render the generic template driven purely by the manifest (nodes/links) + the scoped identity.
    renderer.render_topology("tiny.clab.yml.j2", out, {"nodes": manifest.nodes, "links": manifest.links})
    text = out.read_text()

    # assert: the header carries the dev literals and both nodes + the link are emitted.
    assert "name: tinylab\n" in text
    assert "network: tinylab-mgmt\n" in text
    assert "ipv4-subnet: 10.9.0.0/24\n" in text
    assert "a: { kind: linux, image: alpine:3, mgmt-ipv4: 10.9.0.10 }" in text
    assert "b: { kind: linux, image: alpine:3, mgmt-ipv4: 10.9.0.11 }" in text


def test_renderer_infixes_the_instance_token_into_the_topology_header(manifest, templates_dir, tmp_path):
    # arrange
    renderer = clabrender.ClabRenderer(manifest, templates_dir=templates_dir, instance="a1")
    out = tmp_path / "out.clab.yml"

    # act
    renderer.render_topology("tiny.clab.yml.j2", out, {"nodes": manifest.nodes, "links": manifest.links})
    text = out.read_text()

    # assert: the topology name + mgmt network carry the token (the #453 non-dev scoping).
    assert "name: tinylab-a1\n" in text
    assert "network: tinylab-mgmt-a1\n" in text


def test_renderer_uses_the_byte_exact_clab_jinja_flags(manifest, templates_dir, tmp_path):
    # arrange: a template whose block tags would leave stray blank lines WITHOUT trim_blocks/lstrip_blocks,
    # and a trailing newline that keep_trailing_newline must preserve.
    (templates_dir / "flags.j2").write_text("start\n{% for x in items %}\n{{ x }}\n{% endfor %}\nend\n")
    renderer = clabrender.ClabRenderer(manifest, templates_dir=templates_dir, instance="dev")
    out = tmp_path / "flags.txt"

    # act
    renderer.render_to_file("flags.j2", out, {"items": [1, 2]})

    # assert: trim_blocks + lstrip_blocks eat the tag lines; keep_trailing_newline preserves the final \n.
    assert out.read_text() == "start\n1\n2\nend\n"


def test_render_to_file_marks_an_executable_artifact_and_creates_parent_dirs(manifest, templates_dir, tmp_path):
    # arrange
    (templates_dir / "script.j2").write_text("#!/bin/sh\necho {{ msg }}\n")
    renderer = clabrender.ClabRenderer(manifest, templates_dir=templates_dir, instance="dev")
    out = tmp_path / "nested" / "dir" / "script.sh"

    # act: a nested path (parents must be created) rendered as an executable shell artifact.
    renderer.render_to_file("script.j2", out, {"msg": "hi"}, executable=True)

    # assert: the file exists with its rendered body and the executable bit set.
    import os
    assert out.read_text() == "#!/bin/sh\necho hi\n"
    assert os.access(out, os.X_OK)
