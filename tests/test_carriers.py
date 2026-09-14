"""The carrier section, and the one thing it exists to make sayable (si#5).

THE SHAPE IT WAS CHOSEN FOR. A Portainer serves several applications and, on the same instance, several
environments - the owner's shape, and biz-cockpit's, whose `test` and `prod` share one carrier and are
separated by directory. The alternative considered was writing the chain into each environment, and what
decided against it is the same thing that decides most questions here: it would put the carrier in the
document two or three times, and two environments on the same Portainer could then drift apart with
nothing comparing them. `test_one_carrier_really_serves_two_environments` is that requirement, not a
convenience.

WHY THE UNKNOWN-KEY REFUSAL IS TESTED AT ALL, given that it looks like tidiness. It is the only
structural half of the no-secret rule. `credentials.py` records the measured cause - a product
repository leaked a token out of a committed YAML file, and the repair was to leave no field one could
be written into. A parser that skipped what it did not recognise puts that field straight back, silently,
in a file somebody commits. The census counts this one as an EXPRESSION RULE for exactly that reason: a
manifest carrying a stray `token:` would have worked, so refusing it costs flexibility and is billed.

WHAT IS NOT HERE: any Proxmox, any Portainer, any network. This slice is the vocabulary, and the
vocabulary is pure - which is what lets two waiting consumers adopt it before a single provider exists.

AAA throughout.
"""
from __future__ import annotations

import pytest

from simplon import carriers, environments

HAUS = {
    "proxmox": {"node": "pve1", "kind": "lxc"},
    "portainer": {"url_from": "PORTAINER", "endpoint": 1},
}


def _document(**environs: dict) -> dict:
    """The manifest shape both halves read: carriers beside environments, in one document."""
    return {"carriers": {"hausportainer": HAUS},
            "environments": environs,
            "default": next(iter(environs))}


def test_a_carrier_is_read_as_the_two_halves_it_declares():
    # act
    declared = carriers.declared({"carriers": {"hausportainer": HAUS}}, "simplon.yaml")

    # assert
    carrier = declared["hausportainer"]
    assert carrier.proxmox == carriers.Proxmox(node="pve1", kind="lxc")
    assert carrier.portainer == carriers.Portainer(url_from="PORTAINER", endpoint=1)


def test_the_endpoint_a_carrier_does_not_state_is_portainers_own_default():
    """A single-host install has exactly one endpoint and Portainer numbers it 1. A carrier that says
    nothing means that one, rather than being refused for not repeating a constant."""
    # arrange
    spec = {"proxmox": {"node": "pve1", "kind": "vm"}, "portainer": {"url_from": "P"}}

    # act
    carrier = carriers.declared({"carriers": {"c": spec}}, "x")["c"]

    # assert
    assert carrier.portainer.endpoint == carriers.DEFAULT_ENDPOINT == 1


def test_one_carrier_really_serves_two_environments():
    """THE REQUIREMENT THE SECTION EXISTS FOR. Both environments name the same carrier and differ only in
    what is deployed there - which is biz-cockpit's real arrangement and the owner's."""
    # arrange
    document = _document(
        test={"backend": "portainer", "carrier": "hausportainer", "stack": "bc-test",
              "repository": "github.com/marcozwyssig/biz-cockpit"},
        prod={"backend": "portainer", "carrier": "hausportainer", "stack": "bc-prod",
              "repository": "github.com/marcozwyssig/biz-cockpit"})

    # act
    registry = environments.parse_data(document, ("portainer",))

    # assert
    assert registry.environments["test"].carrier == registry.environments["prod"].carrier
    assert {registry.environments["test"].stack, registry.environments["prod"].stack} == {
        "bc-test", "bc-prod"}, "the two differ in the stack and in nothing else"


def test_a_secret_typed_into_the_manifest_is_refused_rather_than_ignored():
    """THE MEASURED CAUSE, one level across. `credentials.py` exists because a token was committed in a
    YAML file once; this is the parser refusing to accept the field back."""
    # arrange
    leaking = {"proxmox": {"node": "pve1", "kind": "lxc"},
               "portainer": {"url_from": "PORTAINER", "token": "ghp_notarealtoken"}}

    # act / assert
    with pytest.raises(ValueError) as refused:
        carriers.declared({"carriers": {"hausportainer": leaking}}, "simplon.yaml")

    message = str(refused.value)
    assert "token" in message, "the refusal has to name the key, or the reader hunts for it"
    assert "keep the secret out of the file" in message


@pytest.mark.parametrize("spec, fragment", [
    ({"portainer": {"url_from": "P"}}, "which node the carrier stands on"),
    ({"proxmox": {"node": "pve1", "kind": "lxc"}}, "where the Portainer on it answers"),
    ({"proxmox": {"node": "", "kind": "lxc"}, "portainer": {"url_from": "P"}}, "no host is named"),
    ({"proxmox": {"node": "pve1", "kind": "container"}, "portainer": {"url_from": "P"}},
     "a container on the node, a"),
    ({"proxmox": {"node": "pve1", "kind": "lxc"}, "portainer": {"url_from": ""}},
     "It is a PREFIX, not a value"),
    ({"proxmox": {"node": "pve1", "kind": "lxc"}, "portainer": {"url_from": "P", "endpoint": "one"}},
     "must be a number"),
])
def test_every_incomplete_carrier_is_refused_by_the_line_it_is_missing(spec, fragment):
    """A refusal that says 'invalid carrier' sends a reader through the whole section. Each of these
    names the key."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        carriers.declared({"carriers": {"hausportainer": spec}}, "simplon.yaml")

    assert fragment in str(refused.value)


def test_an_environment_pointing_at_no_declared_carrier_is_refused_and_told_which_exist():
    # arrange
    document = _document(prod={"backend": "portainer", "carrier": "andereskiste"})

    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(document, ("portainer",))

    message = str(refused.value)
    assert "andereskiste" in message and "hausportainer" in message, (
        f"the refusal must name both what was asked for and what exists: {message}")


@pytest.mark.parametrize("spec, fragment", [
    ({"backend": "portainer", "stack": "bc-prod"}, "nowhere for that stack to go"),
    ({"backend": "portainer", "carrier": "hausportainer", "repository": "github.com/m/bc"},
     "nothing says what the compose document"),
])
def test_half_a_chain_is_refused(spec, fragment):
    """A stack with no carrier has nowhere to be created; a repository with no stack says where a compose
    document comes from and nothing about what it would become."""
    # act / assert
    with pytest.raises(ValueError) as refused:
        environments.parse_data(_document(prod=spec), ("portainer",))

    assert fragment in str(refused.value)


def test_a_product_that_declares_no_carrier_is_untouched():
    """The six products this kernel can reach declare `backend: local` and nothing else - all eight of
    their environments. Every field si#5 adds defaults to empty, and an absent `carriers:` section is not
    a refusal, so none of them has a line to change."""
    # arrange
    before = {"environments": {"dev": {"backend": "local", "description": "Local development."}},
              "default": "dev"}

    # act
    registry = environments.parse_data(before, ("local",))

    # assert
    assert carriers.declared(before, "x") == {}
    environment = registry.environments["dev"]
    assert (environment.carrier, environment.stack, environment.repository) == ("", "", "")
    assert environment.backend == "local"
