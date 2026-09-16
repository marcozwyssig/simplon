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

from simplon import carrierspec, environments
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
    playbook = _play()

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


# --- the two gaps that left a carrier unusable (si#5, measured 2026-09-15) --------------------------

def _play() -> str:
    return carrier.PLAYBOOK.format(image=carrier.PORTAINER_IMAGE, port=carrier.PORTAINER_PORT,
                                   password="not-a-real-password")


def test_portainer_is_started_already_initialised():
    """THE FIVE-MINUTE TRAP. A Portainer with no admin account locks itself - *"the Portainer instance
    timed out for security purposes"* - and `/api/users/admin/init` then answers 403 because 2.45 wants
    a setup token it prints into its own log. Measured: with the password file, `/api/users/admin/check`
    answers 204 from the first second."""
    # act
    steps = _code(_play())

    # assert
    assert "--admin-password-file" in steps
    assert "/run/secrets/adminpw" in steps


def test_a_portainer_that_was_started_without_it_is_replaced():
    """A play that acted only on a MISSING container would leave every carrier built before this change
    locked forever. That is the difference between converging and merely doing nothing twice - and it
    was driven: the trap was recreated by hand, the command took the instance down and rebuilt it."""
    # act
    steps = _code(_play())

    # assert
    assert "docker rm -f portainer" in steps
    assert steps.count('"admin-password-file" not in container_present.stdout') == 2, (
        "both the removal and the creation have to test it, or one of the two runs on its own")


def test_the_local_docker_environment_is_created():
    """A fresh Portainer manages NOTHING - `GET /api/endpoints` comes back empty while the carrier
    declares `endpoint: 1`. Without this, that number is a promise nobody keeps."""
    # act
    steps = _code(_play())

    # assert
    assert "EndpointCreationType" in steps
    assert "endpoints.json | length == 0" in steps, (
        "creating it unconditionally would add a second environment on every run")


def test_the_playbook_uses_no_go_template():
    """`{{ ... }}` is a Go template AND Jinja, so a `docker --format` string is read by Ansible before
    docker ever sees it. Measured: the play failed to parse at all - *"Values starting with a quote must
    end with the same quote"*. Searching the raw inspect JSON costs nothing and cannot be misread."""
    # act
    steps = _code(_play())

    # assert
    assert "--format" not in steps and "join .Config" not in steps


def test_the_host_may_not_share_the_groups_name():
    """Ansible warns *"Found both group and host with same name: carrier"* and the two then shadow each
    other in ways that surface as a missing variable three tasks later."""
    # arrange
    import inspect as _inspect

    # act
    source = _inspect.getsource(carrier._ansible)

    # assert
    assert "{carrier.name} ansible_host=" in source


@pytest.mark.parametrize("value, why", [("", "not set at all"), ("kurz", "shorter than Portainer takes")])
def test_a_missing_or_short_admin_password_is_refused_before_anything_runs(monkeypatch, value, why):
    """Refusing here beats delivering a carrier whose Portainer nobody can ever log into: Portainer
    refuses to start on a short password, and one that never starts never initialises."""
    # arrange
    monkeypatch.setenv("PORTAINER_PASSWORD", value)

    # act / assert
    with pytest.raises(SystemExit):
        carrier.portainer_password(CARRIER)


def test_the_password_is_read_off_the_same_prefix_the_url_is(monkeypatch):
    """One prefix, the credentials beside it - which is what keeps a carrier from needing a second field
    for every secret it touches."""
    # arrange
    monkeypatch.setenv("PORTAINER_PASSWORD", "long-enough-password")

    # act / assert
    assert carrier.portainer_password(CARRIER) == "long-enough-password"


# --- no secret is written to a file or onto a command line ------------------------------------------

def test_the_rendered_playbook_carries_no_password():
    """THE DEFECT THIS EXISTS FOR, and it was mine. The first version interpolated the admin password
    into the playbook, which the kernel then wrote into `build/carrier/<name>/carrier.yml` at mode
    0644 - world-readable on the operator's machine, and the exact thing `credentials.py` exists to
    prevent, committed by the code that cites it.

    The play reads the value with `lookup('env', ...)` now, so the rendered file carries the NAME and
    never the value.
    """
    # arrange
    secret = "a-password-nobody-should-find"

    # act
    rendered = carrier.PLAYBOOK.format(image=carrier.PORTAINER_IMAGE, port=carrier.PORTAINER_PORT)

    # assert
    assert secret not in rendered
    assert "lookup('env', 'PORTAINER_PASSWORD')" in rendered, (
        "the play has to NAME the variable, or it reads nothing and Portainer starts uninitialised")
    assert "{password}" not in carrier.PLAYBOOK, (
        "a format field for the value is the defect itself, waiting for a caller to fill it")


def test_no_secret_is_put_on_a_docker_command_line():
    """`credentials.py`'s own rule: argv is world-readable - `/proc/<pid>/cmdline` on Linux, `ps` on
    macOS - and a command line lands in the shell history. `docker run -e NAME` takes the value out of
    this process's environment; `-e NAME=value` writes it where anyone on the host can read it for as
    long as the container runs.

    Read off the SOURCE rather than by running docker, because what is being held is how the argv is
    built, and a test that needed a daemon would not run in this suite at all.
    """
    # arrange
    import inspect as _inspect
    import re

    # arrange: the variables that carry a SECRET, and only those. The first draft of this test flagged
    # every interpolated `-e NAME=value` and therefore flagged the node name, the datastore and the
    # PUBLIC ssh key - configuration, all of it, and none of it a problem on a command line. A rule that
    # reports configuration as a leak is a rule somebody loosens on the day it is inconvenient, and then
    # it no longer catches the real case.
    secret_bearing = {carrier.CARRIER_TOKEN_ENV, carrier.PULUMI_PASSPHRASE_ENV,
                      f"PORTAINER{carrier.PASSWORD_SUFFIX}"}

    # act
    source = _inspect.getsource(carrier._pulumi) + _inspect.getsource(carrier._ansible)
    with_value = {name for name in re.findall(r'"-e",\s*f?"([A-Z_]+)=', source)}

    # assert
    leaked = sorted(secret_bearing & with_value)
    assert leaked == [], (
        f"these put a secret's VALUE on the command line: {leaked}. Set it in os.environ and pass the "
        f"bare name, which is what `docker run -e NAME` is for")


# --- a carrier that is a machine and nothing else (si#258) ------------------------------------------

MACHINE = carrierspec.Carrier(
    name="lab",
    proxmox=carrierspec.Proxmox(node="pve-2", kind="vm", endpoint="https://10.0.0.6:8006/",
                                token_from="PROXMOX", insecure=True, template="local:vztmpl/deb.tar.zst",
                                storage="local-zfs", ssh_key="ssh-ed25519 AAAA notarealkey"),
)


def _stub(monkeypatch, tmp_path, carrier_, seen: list) -> None:
    """Everything `up` reaches outside itself, replaced. Nothing here runs Pulumi, Ansible or Proxmox."""
    from simplon import context

    monkeypatch.setattr(carrier, "_carrier_of",
                        lambda env: (environments.Environment("prod", "portainer", ""), carrier_))
    monkeypatch.setattr(carrier, "_token", lambda c: "tok")
    monkeypatch.setattr(carrier, "_pulumi", lambda *a, **k: 0)
    monkeypatch.setattr(carrier, "_address", lambda *a, **k: "10.0.0.9")
    monkeypatch.setattr(carrier, "_ansible", lambda *a, **k: seen.append("ansible") or 0)
    monkeypatch.setattr(carrier.proxmoxapi, "check_storage", lambda *a, **k: None)
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("p", tmp_path, tmp_path / "p.yaml"))


def test_a_carrier_with_no_portainer_is_created_and_nothing_is_installed(monkeypatch, tmp_path):
    """THE BRANCH si#258 ASKED FOR. Before it, `_ansible` ran at the end of every `up` regardless of what
    the carrier declared - an apt -> Docker -> Portainer playbook on a machine that may have no apt."""
    # arrange
    seen: list[str] = []
    _stub(monkeypatch, tmp_path, MACHINE, seen)

    # act
    rc = carrier.up("prod")

    # assert
    assert rc == 0
    assert seen == [], "nothing may be configured on a carrier that declares nothing"


def test_a_machine_only_carrier_needs_no_admin_password(monkeypatch, tmp_path):
    """The refusal that guards a Portainer must not reach a carrier that has none: there is no admin
    account to be locked out of, and demanding one would refuse a carrier that works."""
    # arrange
    seen: list[str] = []
    _stub(monkeypatch, tmp_path, MACHINE, seen)
    monkeypatch.delenv("PORTAINER_PASSWORD", raising=False)

    # act / assert - no SystemExit
    assert carrier.up("prod") == 0


def test_a_carrier_that_declares_a_portainer_still_gets_one(monkeypatch, tmp_path):
    """The compatibility half, and the one that would have caught a branch written the wrong way round."""
    # arrange
    seen: list[str] = []
    _stub(monkeypatch, tmp_path, CARRIER, seen)
    monkeypatch.setenv("PORTAINER_PASSWORD", "a-long-enough-password")
    monkeypatch.setenv(carrier.SSH_KEY_ENV, str(tmp_path / "key"))
    (tmp_path / "key").write_text("notarealkey\n", encoding="utf-8")

    # act
    rc = carrier.up("prod")

    # assert
    assert rc == 0
    assert seen == ["ansible"], "a declared Portainer is still installed"
