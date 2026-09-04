"""Unit tests for delivery.labegress (netctl#1408, epic netctl#1403): the lab's egress isolation, moved
out of netctl's orchestrator.firewall so any `*ctl` product with a containerlab mesh inherits it.

What is worth testing here is the part a lab gate cannot show quickly and a mistake in which is silent:
the exact iptables argv, and the SCOPING that keeps two concurrent labs from deleting each other's
rules. The rules themselves are proven on a real lab (the isolation probes in the acceptance level);
these tests prove the construction is what gets sent.

The three product values arrive as manifest DATA through delivery.context; the tests register a fake
ProductContext, and use a `democtl` tag throughout precisely because a module that named a product
would pass with netctl's and fail for the next one. AAA throughout, negative cases included.
"""
import pytest

from delivery import context, labegress
from delivery.context import ProductContext

_SPEC = {"isolation_env": "DEMO_LAB_ISOLATION", "harden_env": "DEMO_HOST_HARDEN", "rule_tag": "democtl"}


def _register(monkeypatch, tmp_path, data=None):
    """Register a fake ProductContext carrying `data` as the raw manifest."""
    ctx = ProductContext("democtl", tmp_path, tmp_path / "democtl.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data",
                        lambda self: {"lab_egress": _SPEC} if data is None else data)
    return ctx


# --- the manifest read ---------------------------------------------------------------------------

def test_spec_reads_the_three_product_values_from_the_manifest(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path)

    # act
    got = labegress.spec()

    # assert
    assert (got.isolation_env, got.harden_env, got.rule_tag) == (
        "DEMO_LAB_ISOLATION", "DEMO_HOST_HARDEN", "democtl")


def test_spec_rejects_a_manifest_without_a_lab_egress_section(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, data={})

    # act / assert - silently defaulting the env var name would make the operator's documented escape
    # hatch do nothing at all.
    with pytest.raises(ValueError, match="lab_egress"):
        labegress.spec()


@pytest.mark.parametrize("missing", ["isolation_env", "harden_env", "rule_tag"])
def test_spec_rejects_a_manifest_missing_any_of_the_three_keys(monkeypatch, tmp_path, missing):
    # arrange
    partial = {k: v for k, v in _SPEC.items() if k != missing}
    _register(monkeypatch, tmp_path, data={"lab_egress": partial})

    # act / assert
    with pytest.raises(ValueError, match=missing):
        labegress.spec()


def test_spec_rejects_a_rule_tag_containing_the_comment_separator(monkeypatch, tmp_path):
    # arrange - `<tag>:<instance>` would become ambiguous, and unambiguous scoping is the whole point
    _register(monkeypatch, tmp_path, data={"lab_egress": {**_SPEC, "rule_tag": "demo:ctl"}})

    # act / assert
    with pytest.raises(ValueError, match="rule_tag"):
        labegress.spec()


# --- the switches --------------------------------------------------------------------------------

def test_isolation_is_on_unless_the_env_var_is_explicitly_zero():
    # arrange / act / assert - a default that silently omits a safety property repeats the incident
    assert labegress.enabled("DEMO_LAB_ISOLATION", {}) is True
    assert labegress.enabled("DEMO_LAB_ISOLATION", {"DEMO_LAB_ISOLATION": ""}) is True
    assert labegress.enabled("DEMO_LAB_ISOLATION", {"DEMO_LAB_ISOLATION": "1"}) is True
    assert labegress.enabled("DEMO_LAB_ISOLATION", {"DEMO_LAB_ISOLATION": "false"}) is True


def test_only_an_explicit_zero_disables_a_switch():
    # arrange / act / assert - whitespace around it is still the explicit 0
    assert labegress.enabled("DEMO_LAB_ISOLATION", {"DEMO_LAB_ISOLATION": "0"}) is False
    assert labegress.enabled("DEMO_LAB_ISOLATION", {"DEMO_LAB_ISOLATION": " 0 "}) is False


# --- rule construction ---------------------------------------------------------------------------

def test_the_rule_comment_scopes_a_rule_to_one_product_and_one_instance():
    # arrange / act
    got = labegress.rule_comment("democtl", "a1")

    # assert
    assert got == "democtl:a1"


def test_the_bridge_name_is_dockers_twelve_char_truncation_of_the_network_id():
    # arrange
    network_id = "0123456789abcdef0123456789abcdef"

    # act / assert - the same truncation `docker network ls` shows
    assert labegress.bridge_interface(network_id) == "br-0123456789ab"


def test_the_isolation_rules_accept_replies_before_they_drop_egress():
    # arrange / act
    rules = labegress.isolation_rules("br-deadbeef0001", "democtl", "dev")

    # assert - order is load-bearing: both are INSERTED, so the ACCEPT must go to position 1 and the
    # DROP to 2, leaving the chain as ACCEPT, DROP, dockerd's RETURN.
    assert [r[3] for r in rules] == ["1", "2"]
    assert rules[0][-1] == "ACCEPT" and rules[1][-1] == "DROP"
    assert "--ctstate" in rules[0] and "RELATED,ESTABLISHED" in rules[0]
    assert "--ctstate" not in rules[1]


def test_the_isolation_rules_match_traffic_leaving_the_bridge_and_not_intra_lab_traffic():
    # arrange / act
    rules = labegress.isolation_rules("br-deadbeef0001", "democtl", "dev")

    # assert - `-i br ! -o br` is what excludes container-to-container traffic when br_netfilter
    # routes it through FORWARD. Dropping that negation isolates the lab from ITSELF.
    for rule in rules:
        assert rule[rule.index("-i") + 1] == "br-deadbeef0001"
        assert rule[rule.index("!") + 1] == "-o"
        assert rule[rule.index("!") + 2] == "br-deadbeef0001"


def test_every_installed_rule_carries_the_instance_scoped_comment():
    # arrange / act
    rules = labegress.isolation_rules("br-x", "democtl", "a1")

    # assert - an untagged rule could never be removed by exactly one instance's teardown
    for rule in rules:
        assert rule[rule.index("--comment") + 1] == "democtl:a1"


# --- teardown scoping (the property that keeps concurrent labs apart) ------------------------------

_LISTING = "\n".join([
    "-N DOCKER-USER",
    '-A DOCKER-USER -i br-aaa ! -o br-aaa -m conntrack --ctstate RELATED,ESTABLISHED '
    '-m comment --comment "democtl:a1" -j ACCEPT',
    '-A DOCKER-USER -i br-aaa ! -o br-aaa -m comment --comment "democtl:a1" -j DROP',
    '-A DOCKER-USER -i br-bbb ! -o br-bbb -m comment --comment "democtl:a" -j DROP',
    '-A DOCKER-USER -i br-ccc -m comment --comment "someone-else" -j DROP',
    "-A DOCKER-USER -j RETURN",
])


def test_teardown_removes_exactly_this_instances_rules():
    # arrange / act
    deletions = labegress.deletion_rules(_LISTING, "democtl", "a1")

    # assert
    assert len(deletions) == 2
    for d in deletions:
        assert d[:3] == ["iptables", "-D", "DOCKER-USER"]
        assert "democtl:a1" in d


def test_teardown_does_not_match_an_instance_whose_id_is_a_prefix_of_another():
    # arrange - `a` and `a1` are both legal ids, and a substring match would have `a` delete `a1`'s
    # rules. The comment is compared as a whole TOKEN for exactly this reason.
    # act
    deletions = labegress.deletion_rules(_LISTING, "democtl", "a")

    # assert
    assert len(deletions) == 1
    assert "democtl:a" in deletions[0] and "democtl:a1" not in deletions[0]


def test_teardown_never_touches_another_tools_rules():
    # arrange / act
    deletions = labegress.deletion_rules(_LISTING, "democtl", "a1")

    # assert - the foreign rule and dockerd's own RETURN both survive
    flat = [" ".join(d) for d in deletions]
    assert not any("someone-else" in f for f in flat)
    assert not any("RETURN" in f for f in flat)


def test_teardown_of_an_instance_with_no_rules_deletes_nothing():
    # arrange / act
    deletions = labegress.deletion_rules(_LISTING, "democtl", "zz")

    # assert - a quiet no-op, not an error: `down` runs on labs that were never isolated
    assert deletions == []


def test_teardown_ignores_an_unparsable_listing_line():
    # arrange - an unbalanced quote cannot be one of ours; we only ever write shlex-clean rules
    listing = '-A DOCKER-USER -m comment --comment "unterminated\n' + _LISTING

    # act
    deletions = labegress.deletion_rules(listing, "democtl", "a1")

    # assert - it skips the bad line instead of throwing mid-teardown and leaving rules behind
    assert len(deletions) == 2
