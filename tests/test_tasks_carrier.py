"""`deploy:carrier` - the thing an environment stands on (si#5).

WHAT IS ASSERTED HERE AND WHAT WAS MEASURED ELSEWHERE. The command was driven end to end against a real
Proxmox (PVE 9.2.18, node `pve-2`) on 2026-09-14/15: it created an LXC, installed Docker and brought up
Portainer 2.45.0, and a second run reported `3 unchanged` from Pulumi and `changed=0 skipped=2` from
Ansible. None of that is reproducible in a suite without a hypervisor, so what is held here is the half
that CAN go wrong silently between such runs - the two programs the kernel renders, and the conditions
the decisions rest on.

THE THREE FACTS IN THE RENDERED PROGRAM THAT COST A MEASUREMENT EACH, and every one of them is a line
somebody would "tidy up" without knowing what it bought:

  1. `nesting` AND NOT `keyctl`. Proxmox refuses every feature flag except nesting to an API TOKEN -
     HTTP 403, "only allowed for root@pam", even for a root token made with `--privsep 0`. And Docker
     does not need it: Debian 13, kernel 7.0, `docker run hello-world` green with nesting alone.
  2. `keys` AND NOT `password`. Pulumi encrypts only MARKED values; the provider marks its own
     `apiToken` and `password`, the container resource marks nothing. A password would therefore stand
     in clear text in the state the product commits.
  3. NO COMPOSE in the playbook. Debian 13 carries only `docker-compose` v1 and answers
     `docker compose version` with "'compose' is not a docker command".

AAA throughout.
"""
from __future__ import annotations

import pytest

from simplon import carrierspec
from simplon.tasks import carrier, proxmoxapi

def _code(text: str) -> str:
    """`text` with its comment lines removed.

    Both programs EXPLAIN what they do not do - keyctl, compose, `downloads.portainer.io` - so a test
    that searched the whole file would pass just as happily on a program that did those things and
    described them. Stripping the comments is what makes the assertion about the code.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


CARRIER = carrierspec.Carrier(
    name="hausportainer",
    proxmox=carrierspec.Proxmox(node="pve-2", kind="lxc", endpoint="https://10.0.0.6:8006/",
                                token_from="PROXMOX", insecure=True, template="local:vztmpl/deb.tar.zst",
                                storage="local-zfs", ssh_key="ssh-ed25519 AAAA notarealkey"),
    portainer=carrierspec.Portainer(url_from="PORTAINER", endpoint=1),
)


def test_the_rendered_project_is_the_three_files_pulumi_needs(tmp_path):
    # act
    where = carrier.render(CARRIER, tmp_path)

    # assert
    assert {p.name for p in where.iterdir()} == {"__main__.py", "Pulumi.yaml", "requirements.txt"}
    assert where.is_relative_to(tmp_path / carrier.PROGRAM_DIR), (
        "the program is an OUTPUT and belongs under build/, which every product already ignores - the "
        "STATE is the half that is committed")


def test_the_program_sets_nesting_and_does_not_set_keyctl():
    """MEASURED, not copied from a runbook. si#5 carried `keyctl=1` as a named precondition from
    2026-09-05; the API refuses it to a token at all, and Docker runs without it."""
    # act: the CODE, with the comments stripped - both words appear in the comment that explains them,
    # and a test that could not tell the two apart would pass on a program that sets keyctl and says so
    code = _code(carrier.PROGRAM)

    # assert
    assert "nesting=True" in code
    assert "keyctl" not in code, (
        "keyctl may appear in the comment that explains why it is absent, never in the resource")


def test_the_program_hands_a_public_key_and_never_a_password():
    """THE CONDITION THE COMMITTED STATE RESTS ON. The container resource marks nothing secret, so a
    password here would sit in clear text in a file the product is asked to commit."""
    # act
    program = carrier.PROGRAM

    # assert
    assert "keys=[os.environ[\"CARRIER_SSH_KEY\"]]" in program
    assert "password" not in program.replace("# ", "").split("user_account=")[1]


def test_a_carrier_that_set_a_password_would_be_refused(monkeypatch):
    """The manifest has no `password:` key, so this cannot be reached from a document today. It is here
    because the field is one line away in the provider, and a carrier growing one would otherwise
    quietly undo the decision that the state may be committed."""
    # arrange
    with_password = CARRIER._replace(proxmox=CARRIER.proxmox)
    monkeypatch.setattr(type(with_password.proxmox), "password", "geheim", raising=False)

    # act / assert
    with pytest.raises(SystemExit):
        carrier.check_no_password(with_password)


def test_the_playbook_names_a_pinned_portainer_and_fetches_no_compose_file():
    """The community addon does `curl https://downloads.portainer.io/ce-sts/portainer-compose.yaml` - a
    moving channel - and runs compose. Both are what a pin exists to stop."""
    # act
    playbook = carrier.PLAYBOOK.format(image=carrier.PORTAINER_IMAGE, port=carrier.PORTAINER_PORT)

    # assert
    steps = _code(playbook)
    assert carrier.PORTAINER_IMAGE in steps
    assert "downloads.portainer.io" not in steps
    assert "docker compose" not in steps and "docker-compose" not in steps


@pytest.mark.parametrize("image", [carrier.PULUMI_IMAGE, carrier.ANSIBLE_IMAGE,
                                   carrier.PORTAINER_IMAGE])
def test_every_image_this_command_runs_is_pinned(image):
    """`docker.pinned_image`'s rule one level up: an unpinned toolchain means the same command builds
    something different next month. It applies to the tools as much as to what they install."""
    # assert
    tag = image.rsplit(":", 1)[-1]
    assert ":" in image and tag not in ("latest", "stable", "lts", "sts"), image


# --- the refusal that used to arrive three minutes late ---------------------------------------------

def _storage(name: str, *, content: str, enabled: bool = True, active: bool = True):
    return proxmoxapi.Storage(name=name, content=tuple(content.split(",")),
                              enabled=enabled, active=active)


@pytest.mark.parametrize("storage, why", [
    (_storage("local-zfs", content="rootdir,images"), "serves containers"),
    (_storage("local", content="iso,backup,vztmpl"), "no rootdir"),
    (_storage("local-lvm", content="rootdir,images", enabled=False, active=False), "another node's"),
])
def test_a_storage_serves_containers_only_when_all_three_fields_say_so(storage, why):
    """MEASURED on the real cluster: `/nodes/pve-2/storage` lists `local-lvm` with `enabled: 0,
    active: 0` because it is defined for `pve-1`. A listing that includes what cannot be used is the
    recurring defect wearing an inventory's clothes - the answer cannot tell 'this node has it' from
    'this node knows of it'."""
    # assert
    assert storage.serves_containers is (why == "serves containers")
