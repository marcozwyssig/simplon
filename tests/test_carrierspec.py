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

from simplon import carrierspec, environments

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
    declared = carrierspec.declared({"carriers": {"hausportainer": HAUS}}, "simplon.yaml")

    # assert
    carrier = declared["hausportainer"]
    assert carrier.proxmox == carrierspec.Proxmox(node="pve1", kind="lxc")
    assert carrier.portainer == carrierspec.Portainer(url_from="PORTAINER", endpoint=1)


def test_the_endpoint_a_carrier_does_not_state_is_portainers_own_default():
    """A single-host install has exactly one endpoint and Portainer numbers it 1. A carrier that says
    nothing means that one, rather than being refused for not repeating a constant."""
    # arrange
    spec = {"proxmox": {"node": "pve1", "kind": "vm"}, "portainer": {"url_from": "P"}}

    # act
    carrier = carrierspec.declared({"carriers": {"c": spec}}, "x")["c"]

    # assert
    assert carrier.portainer.endpoint == carrierspec.DEFAULT_ENDPOINT == 1


def test_one_carrier_really_serves_two_environments():
    """THE REQUIREMENT THE SECTION EXISTS FOR. Both environments name the same carrier and differ only in
    what is deployed there - which is biz-cockpit's real arrangement and the owner's."""
    # arrange
    document = _document(
        test={"backend": "portainer", "carrier": "hausportainer", "stack": "bc-test",
              "repository": {"url": "github.com/marcozwyssig/biz-cockpit"}},
        prod={"backend": "portainer", "carrier": "hausportainer", "stack": "bc-prod",
              "repository": {"url": "github.com/marcozwyssig/biz-cockpit"}})

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
        carrierspec.declared({"carriers": {"hausportainer": leaking}}, "simplon.yaml")

    message = str(refused.value)
    assert "token" in message, "the refusal has to name the key, or the reader hunts for it"
    assert "keep the secret out of the file" in message


@pytest.mark.parametrize("spec, fragment", [
    # si#280 struck the row that used to stand first here - a carrier with only `portainer:` was refused
    # with "which node the carrier stands on", and it is now the legal way to name a Portainer somebody
    # else built. What replaced it is the case where BOTH halves are absent, which states nothing.
    ({}, "says nothing that can be acted on"),
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
        carrierspec.declared({"carriers": {"hausportainer": spec}}, "simplon.yaml")

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
    ({"backend": "portainer", "carrier": "hausportainer", "repository": {"url": "github.com/m/bc"}},
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
    assert carrierspec.declared(before, "x") == {}
    environment = registry.environments["dev"]
    assert (environment.carrier, environment.stack, environment.repository) == ("", "", None)
    assert environment.backend == "local"


# --- the configuration a carrier states (owner, 2026-09-14) -----------------------------------------

FULL = {
    "proxmox": {
        "endpoint": "https://10.0.0.6:8006/",
        "token_from": "PROXMOX",
        "insecure": True,
        "node": "pve",
        "kind": "lxc",
        "template": "local:vztmpl/debian-13-standard_amd64.tar.zst",
        "storage": "local-lvm",
        "ssh_key": "ssh-ed25519 AAAAC3Nz notarealkey",
    },
    "portainer": {"url_from": "PORTAINER"},
}


def test_the_manifest_carries_the_configuration_and_never_the_token():
    """The owner's rule: *"die Konfiguration muss im manifest stehen"*. Where the API is, which node,
    which datastore, how big - all of it in the file a reviewer reads. The token is the one thing that
    is not configuration, and `token_from:` is the prefix rather than a field it could be typed into."""
    # act
    proxmox = carrierspec.declared({"carriers": {"haus": FULL}}, "simplon.yaml")["haus"].proxmox

    # assert
    assert proxmox.endpoint == "https://10.0.0.6:8006/"
    assert proxmox.token_from == "PROXMOX"
    assert proxmox.storage == "local-lvm"
    assert "PROXMOX_API_TOKEN" not in str(FULL), "the token itself is nowhere in the document"


def test_the_sizes_a_carrier_leaves_out_are_the_helper_scripts_own():
    """Read off `ct/docker.sh` on 2026-09-14 - `var_cpu=2`, `var_ram=2048`, `var_disk=4` - rather than
    invented, so a carrier that says nothing gets what the tool the owner named would have given it."""
    # arrange
    quiet = {"proxmox": {"node": "pve", "kind": "lxc"}, "portainer": {"url_from": "P"}}

    # act
    proxmox = carrierspec.declared({"carriers": {"c": quiet}}, "x")["c"].proxmox

    # assert
    assert (proxmox.cores, proxmox.memory, proxmox.disk) == (2, 2048, 4)


def test_insecure_may_not_be_a_string():
    """THE NASTIEST OF THE THREE. `insecure:` turns TLS verification off, and every non-empty string is
    truthy - so `insecure: "no"` would mean the opposite of what it says and deploy happily."""
    # arrange
    spec = {"proxmox": {"node": "pve", "kind": "lxc", "insecure": "no"},
            "portainer": {"url_from": "P"}}

    # act / assert
    with pytest.raises(ValueError) as refused:
        carrierspec.declared({"carriers": {"c": spec}}, "simplon.yaml")

    assert "true or false" in str(refused.value)


def test_verification_is_on_unless_the_manifest_turns_it_off():
    """A default that weakens a check is a kernel deciding something a product should have to say in
    its own file."""
    # act
    quiet = {"proxmox": {"node": "pve", "kind": "lxc"}, "portainer": {"url_from": "P"}}

    # assert
    assert carrierspec.declared({"carriers": {"c": quiet}}, "x")["c"].proxmox.insecure is False


@pytest.mark.parametrize("value", [0, -1, "zwei"])
def test_a_size_that_is_not_a_positive_number_is_refused(value):
    """Zero is refused with the rest: a container with no cores and a container with the default number
    of cores are two different statements, and `int` would quietly make the first mean the second."""
    # arrange
    spec = {"proxmox": {"node": "pve", "kind": "lxc", "cores": value},
            "portainer": {"url_from": "P"}}

    # act / assert
    with pytest.raises(ValueError) as refused:
        carrierspec.declared({"carriers": {"c": spec}}, "simplon.yaml")

    assert "cores" in str(refused.value)


def test_a_lower_case_prefix_is_accepted_because_the_rule_against_it_was_struck():
    """WRITTEN AND WITHDRAWN, and asserted so it cannot come back unnoticed. A lower-case environment
    variable is legal, so a manifest saying `token_from: proxmox` and exporting `proxmox_API_TOKEN`
    would have worked - which makes a refusal an expression rule with no measured cause, the shape si#53
    struck `check_every_task_is_used` for."""
    # arrange
    spec = {"proxmox": {"node": "pve", "kind": "lxc", "token_from": "proxmox"},
            "portainer": {"url_from": "P"}}

    # act
    carrier = carrierspec.declared({"carriers": {"c": spec}}, "x")["c"]

    # assert
    assert carrier.proxmox.token_from == "proxmox"


# --- a carrier that is a machine and nothing else (si#258) ------------------------------------------

def test_a_carrier_may_declare_a_machine_and_nothing_to_put_on_it():
    """THE FINDING si#258 SURFACED, and it was larger than the ticket's own framing. `portainer:` was
    REQUIRED on every carrier, so "carrier" and "Portainer host" were the same word - and `deploy carrier`
    proved it by running an apt -> Docker -> Portainer playbook at the end of every run with no branch in
    it. A product that wanted a machine got a workload it never asked for, and on a machine with no apt, a
    red run."""
    # arrange
    machine = {"proxmox": {"node": "pve-2", "kind": "vm"}}

    # act
    carrier = carrierspec.declared({"carriers": {"lab": machine}}, "x")["lab"]

    # assert
    assert carrier.portainer is None, "absent, not an empty Portainer - the two are different statements"
    assert carrier.proxmox.node == "pve-2"


def test_the_portainer_backend_refuses_a_carrier_that_carries_no_portainer():
    """The half that keeps the looser vocabulary honest: `backend: portainer` pointed at a machine with
    no Portainer on it has nowhere to put the stack, and is told so by name rather than failing on an
    attribute."""
    # arrange
    from simplon import portainer

    machine = carrierspec.Carrier(name="lab",
                                  proxmox=carrierspec.Proxmox(node="pve-2", kind="vm"))

    # act / assert
    with pytest.raises(portainer.PortainerError) as refused:
        portainer.PortainerTarget.from_carrier(machine, "some-stack", {})

    message = str(refused.value)
    assert "lab" in message and "declares no `portainer:`" in message
    assert "a backend the product registers itself" in message, (
        "the way out has to be named, or the reader is told only that they are wrong")


def test_a_carrier_that_declares_a_portainer_is_unchanged():
    """The compatibility half. Nothing about the declared case moved."""
    # act
    carrier = carrierspec.declared({"carriers": {"hausportainer": HAUS}}, "x")["hausportainer"]

    # assert
    assert carrier.portainer == carrierspec.Portainer(url_from="PORTAINER", endpoint=1)


# --- si#280: a Portainer on a machine the kernel did not make ----------------------------------------


def test_a_carrier_may_name_a_portainer_without_describing_a_machine():
    """si#258's argument arriving from the other side.

    That ticket struck the refusal on a carrier with no `portainer:`, because a machine with nothing on
    it is a complete statement. The mirror is this one: a Portainer on a machine somebody else built is
    a complete statement too, and until si#280 it could not be said - every carrier had to describe a
    Proxmox first, with a `node:` and a `kind:` that had no true answer.

    Measured before it was changed: every reader of `carrier.proxmox` in this kernel lives in
    `tasks/carrier.py`, the command that CREATES the machine. Nothing on the deploy path consults it.
    """
    declared = carrierspec.declared(
        {"carriers": {"theirs": {"portainer": {"url_from": "PORTAINER", "insecure": True}}}})

    assert declared["theirs"].proxmox is None
    assert declared["theirs"].portainer is not None
    assert declared["theirs"].portainer.url_from == "PORTAINER"


def test_a_carrier_that_describes_neither_half_states_nothing_and_is_refused():
    """Each absence is a statement on its own; both at once are not.

    A carrier with neither block is a name no command can act on - `deploy carrier` has no machine to
    make, and no backend has anywhere to put a stack. That is the third state this repository always
    separates out rather than folding into one of the other two.
    """
    with pytest.raises(ValueError) as refused:
        carrierspec.declared({"carriers": {"empty": {}}}, "simplon.yaml")

    message = str(refused.value)
    assert "neither `proxmox:` nor `portainer:`" in message
    assert "a Portainer it can reach" in message


def test_the_deploy_path_never_reads_the_machine_half():
    """The measurement si#280 rests on, kept as an assertion rather than as a sentence in the ticket.

    `PortainerTarget.from_carrier` is the whole of what the deploy path asks of a carrier. Hand it one
    with no machine at all and it still resolves - which is what makes `proxmox:` optional a removal
    rather than a new shape to support.
    """
    from simplon import portainer

    carrier = carrierspec.declared(
        {"carriers": {"theirs": {"portainer": {"url_from": "PORTAINER"}}}})["theirs"]

    target = portainer.PortainerTarget.from_carrier(
        carrier, "some-stack", environ={"PORTAINER_URL": "https://p:9443", "PORTAINER_TOKEN": "t"})

    assert target.stack_name == "some-stack"
