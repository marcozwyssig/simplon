"""`deploy:carrier` - make the thing an environment stands on (si#5).

WHAT THIS IS AND WHAT IT IS NOT. It is a translation, not an invention: two programs that were driven
by hand against a real Proxmox on 2026-09-14/15 are rendered here from the `carriers:` section and run
in pinned containers. Nothing below was written ahead of a measurement.

    pulumi/pulumi-python  ->  the LXC or VM on Proxmox        (the goal, and its state)
    alpine/ansible        ->  Docker and a pinned Portainer,  (the steps, over SSH)
                             and/or a pinned actions runner (si#781)

WHY TWO TOOLS AND NOT ONE, which is the owner's decision of 2026-09-14 and worth the sentence: Pulumi
describes a GOAL and keeps state, so idempotence is the tool's problem rather than ours; Ansible
describes STEPS and keeps none, which is what configuring a running machine actually is. Each was chosen
for the half it is good at.

WHY PULUMI AND NOT TERRAFORM, also decided rather than assumed: `pulumi-proxmoxve` is the bridged
`bpg/proxmox` provider - the same resources - but the program is PYTHON, so `test typecheck-python`,
the suite and `surface.py` reach it. HCL would be a second language in the tree that no check here can
read.

WHY BOTH TOOLS COME IN CONTAINERS: the guiding idea recorded on si#5 - *"auf Docker-Basis, so wie
docs:render und docs:site ihre Werkzeuge mitbringen, statt sie auf der Maschine vorauszusetzen"*. Both
images are PINNED for `docker.pinned_image`'s reason, one level up: an unpinned toolchain means the same
command builds something different next month.

THE COMMAND SITS UNDER `deploy` AND NOT UNDER `support` (owner, 2026-09-14), which took back an earlier
placement and dissolved the whole conflict: setting a carrier up needs the environment, `support` is
environment-less by taxonomy, and `deploy` is already environment-first. No taxonomy change, no
environment variable as a back door, no seventh group.

WHAT THE STATE IS AND WHY IT IS COMMITTED. Pulumi's self-managed backend writes one JSON file, and it
goes into the product's tree (owner decision, "in git, mit Messung"). The measurement was taken against
a real run: the provider marks `apiToken` and `password` secret, so both are `v1:...` ciphertext in the
file, while the LXC resource marks NOTHING - so a container created with a PASSWORD would put it there
in clear text. `check_no_password` holds the condition the decision rests on.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from simplon.model import carrierspec
from simplon.manifest import context, environments
from simplon.adapters import docker, hostpath, portainer
from simplon.kernel import log, run
from simplon.tasks import proxmoxapi

#: The two toolchains, pinned. Bump them deliberately, the way `DOCKER_CLI_VERSION` is bumped.
PULUMI_IMAGE = docker.pinned_image("pulumi/pulumi-python:3.262.0", "simplon.tasks.carrier")
ANSIBLE_IMAGE = docker.pinned_image("alpine/ansible:2.21.0", "simplon.tasks.carrier")

#: What Ansible puts on the carrier. Pinned here rather than fetched: the community addon downloads its
#: compose file from `downloads.portainer.io/ce-sts/`, a moving channel, which is exactly the thing a
#: pin exists to stop.
PORTAINER_IMAGE = docker.pinned_image("portainer/portainer-ce:2.45.0", "simplon.tasks.carrier")

#: The port Portainer answers on. A CONSTANT and not a manifest field: it is what the image listens on,
#: the same for every carrier, and a product that wanted another would be changing the image's own
#: contract. The `endpoint:` a carrier declares is Portainer's id for the Docker environment it manages,
#: which is a different number entirely - naming them apart here is what stops them being confused.
PORTAINER_PORT = 9443

#: Where the rendered programs go - an OUTPUT, regenerated on every run, under the directory every other
#: kernel output lives in and every product already ignores.
PROGRAM_DIR = "build/carrier"

#: Where Pulumi's state goes - committed, which is the whole of the decision above. Beside the
#: deployment configuration rather than under `build/`, because it is the one thing here that must
#: survive a clean.
STATE_DIR = "deploy/carriers"

#: The passphrase Pulumi encrypts marked values with. A kernel-level variable rather than a manifest
#: field: it is about how the kernel keeps state, not about any product's Proxmox.
PASSPHRASE_ENV = "SIMPLON_STATE_PASSPHRASE"

#: The PATH to the private key Ansible reaches the carrier with. A path is not a secret and may be an
#: environment variable pointing at a file; the key itself never enters this process.
SSH_KEY_ENV = "SIMPLON_CARRIER_SSH_KEY"

#: Proxmox's own suffix. `token_from: PROXMOX` therefore means `PROXMOX_API_TOKEN`, which is
#: `credentials.py`'s convention with the suffix the API's header name asks for.
TOKEN_SUFFIX = "_API_TOKEN"

#: The names the two containers read their secrets under. They are set in THIS process's environment
#: and passed through with a bare `docker run -e NAME`, so no value is ever written into a file or onto
#: a command line - `credentials.py`'s two rules, applied to the one place this kernel starts a tool
#: that needs a credential.
CARRIER_TOKEN_ENV = "CARRIER_TOKEN"
PULUMI_PASSPHRASE_ENV = "PULUMI_CONFIG_PASSPHRASE"

#: Portainer's, read off the SAME prefix its `url_from:` names: `url_from: PORTAINER` means
#: `PORTAINER_PASSWORD`. One prefix, the credentials beside it - which is what keeps a carrier from
#: needing a second field for every secret it touches.
PASSWORD_SUFFIX = "_PASSWORD"

#: What Portainer 2.45 refuses to start with. Checked here rather than left to the container, because a
#: password the daemon rejects leaves a Portainer that never initialises and then locks itself - the
#: exact trap this whole half exists to close, arriving by a different door.
MIN_PASSWORD = 12

#: The actions/runner release the runner half installs (si#781), and the sha256 of each bundle the pin
#: covers, keyed by the runner's own architecture name - the si#668 rule for every pinned download. Source
#: of the digests: measured, by downloading both bundles on 2026-11-20; they equal the digests the release
#: notes of v2.338.2 publish. Bump the version AND both digests together.
RUNNER_VERSION = "2.338.2"
RUNNER_SHA256 = {
    "x64": "baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40",
    "arm64": "670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945",
}

#: The registration token's suffix: `runner: token_from: COCKPIT` reads `COCKPIT_RUNNER_TOKEN`.
RUNNER_TOKEN_SUFFIX = "_RUNNER_TOKEN"

#: Who the runner runs as, and where it lives. Not root: `config.sh` refuses root unless told otherwise,
#: and a job's user is the runner's user.
RUNNER_USER = "actions-runner"
RUNNER_DIR = "/opt/actions-runner"


def _carrier_of(env_name: str = "") -> ("tuple[environments.Environment, carrierspec.Carrier, "
                                        "carrierspec.Proxmox]"):
    """The environment being targeted and the carrier it points at, or a refusal that says which is
    missing. Both halves are read from the ONE manifest, so nothing here can disagree with `support
    environments`."""
    document = context.current().manifest_data()
    where = context.current().manifest_path.name
    declared = carrierspec.declared(document, where)

    registry = environments.parse_data(document, _backends(document))
    name = env_name or os.environ.get(context.ENVIRONMENT_ENV, "") or registry.default
    environment = registry.environments.get(name)
    if environment is None:
        log.die(f"'{name}' is not a declared environment - {where} declares: "
                f"{', '.join(sorted(registry.environments))}")
        raise SystemExit(1)
    if not environment.carrier:
        log.die(f"environment '{name}' declares no `carrier:`, so nothing says what it stands on. A "
                f"carrier is declared once under `{carrierspec.SECTION}:` and pointed at from here")
        raise SystemExit(1)
    carrier = declared[environment.carrier]
    if carrier.proxmox is None:
        # si#280: a carrier may now be a Portainer somebody else built. Every other command reaching a
        # carrier goes through `carrier.portainer`; this one is the machine-maker, so it is the one
        # place the absence has to be a refusal - and it names the alternative, because the reader is
        # here by accident rather than by mistake.
        log.die(f"carrier '{carrier.name}' declares no `proxmox:`, so there is no machine for this "
                f"command to make - it names a Portainer that already exists. Deploy to it with "
                f"`deploy up` and leave the machine to whoever built it; add `proxmox:` only if you "
                f"want the kernel to create one")
        raise SystemExit(1)
    # The machine travels with the carrier rather than being read off it again downstream. That is
    # what makes the refusal above a NARROWING and not an assertion nobody can ever see fail: every
    # caller of this function holds a `Proxmox`, because there is no way to hold one without having
    # come past those four lines.
    return environment, carrier, carrier.proxmox


def _backends(document: dict) -> tuple[str, ...]:
    """Every backend name the document itself uses. The kernel does not own this list - a product
    registers its own implementations - so the set is read off the matrix rather than fixed here."""
    declared = environments.matrix_section(document)["environments"] or {}
    names = {str((spec or {}).get("backend", "")).strip()
             for spec in declared.values() if isinstance(spec, dict)}
    return tuple(sorted(n for n in names if n)) or ("local",)


def _token(carrier: carrierspec.Carrier, machine: carrierspec.Proxmox) -> str:
    """The Proxmox API token, from the environment and never from the file."""
    if not machine.token_from:
        log.die(f"carrier '{carrier.name}' declares no `token_from:`, so nothing says which environment "
                f"variable holds the API token. It is a PREFIX: `token_from: PROXMOX` reads "
                f"PROXMOX{TOKEN_SUFFIX}")
        raise SystemExit(1)
    variable = f"{machine.token_from}{TOKEN_SUFFIX}"
    token = os.environ.get(variable, "")
    if not token:
        log.die(f"{variable} is not set, so carrier '{carrier.name}' cannot reach "
                f"{machine.endpoint or 'Proxmox'}. Export it; it may not be written into the "
                f"manifest, which is why the manifest has no field for it")
        raise SystemExit(1)
    return token


def _declared_portainer(carrier: carrierspec.Carrier) -> carrierspec.Portainer:
    """The carrier's Portainer half, for the paths that only run when it has one.

    A function rather than an `assert` or a `# type: ignore`, because the two callers below are reached
    only after `up` has checked - and a reader arriving at either of them should be told that, not left
    to trust it. If it ever raises, the branch in `up` has been lost.
    """
    if carrier.portainer is None:
        raise ValueError(
            f"carrier '{carrier.name}' declares no `portainer:`, so nothing here applies to it - this "
            f"path is only reached for a carrier that declares one")
    return carrier.portainer


def portainer_password(carrier: carrierspec.Carrier) -> str:
    """The Portainer admin password, from the environment and never from the file.

    IT IS NOT OPTIONAL, and that is the measurement rather than a preference: a Portainer started without
    one locks itself five minutes later and then wants a setup token out of its own log. Refusing here
    beats delivering a carrier whose Portainer nobody can ever log into.

    Only asked of a carrier that DECLARES a Portainer (si#258). A carrier with no `portainer:` block gets
    no playbook, so there is no admin account to be locked out of and nothing to ask for.
    """
    variable = f"{_declared_portainer(carrier).url_from}{PASSWORD_SUFFIX}"
    password = os.environ.get(variable, "")
    if not password:
        log.die(f"{variable} is not set. Portainer needs an admin password AT START - one that gets it "
                f"later does not exist, because an uninitialised instance locks itself after five "
                f"minutes. It is read from the environment; the manifest has no field for it")
        raise SystemExit(1)
    if len(password) < MIN_PASSWORD:
        log.die(f"{variable} is {len(password)} characters; Portainer wants at least {MIN_PASSWORD} and "
                f"refuses to start otherwise - which would leave exactly the uninitialised instance this "
                f"check exists to prevent")
        raise SystemExit(1)
    return password


def _declared_runner(carrier: carrierspec.Carrier) -> carrierspec.Runner:
    """The carrier's runner half, for the paths that only run when it has one - `_declared_portainer`'s
    reason, for the other half."""
    if carrier.runner is None:
        raise ValueError(
            f"carrier '{carrier.name}' declares no `runner:`, so nothing here applies to it - this path is "
            f"only reached for a carrier that declares one")
    return carrier.runner


def runner_token_variable(carrier: carrierspec.Carrier) -> str:
    """The NAME the registration token is read from - a name, which may be rendered and logged."""
    return f"{_declared_runner(carrier).token_from}{RUNNER_TOKEN_SUFFIX}"


def runner_token(carrier: carrierspec.Carrier) -> str:
    """The runner's registration token, from the environment and never from the file (si#781).

    Asked BEFORE the machine is made, like the Portainer password: a carrier created and then left
    without the runner it declares is a half-done outcome nobody asked for. A re-run asks for it too,
    although a runner that is already registered does not use it - the kernel cannot know that before it
    has reached the machine.
    """
    variable = runner_token_variable(carrier)
    token = os.environ.get(variable, "")
    if not token:
        repository = _declared_runner(carrier).repository
        log.die(f"{variable} is not set, so the runner on carrier '{carrier.name}' cannot register on "
                f"{repository}. Export a registration token - `gh api -X POST "
                f"repos/{repository}/actions/runners/registration-token --jq .token` makes one, valid "
                f"for an hour. It is read from the environment; the manifest has no field for it")
    return token


def check_no_password(machine: carrierspec.Proxmox) -> None:
    """THE CONDITION THE COMMITTED STATE RESTS ON, held rather than remembered.

    Measured 2026-09-14 against the provider and confirmed 2026-09-15 against a real run: Pulumi
    encrypts only what is MARKED secret, the provider marks its own `apiToken` and `password`, and the
    container resource marks nothing at all. So a carrier created with a root password puts that
    password into a file this kernel then asks the product to commit.

    The manifest has no `password:` key, so this cannot be reached from a document today - it is here
    because the field it guards against is one line away in the provider, and a future carrier growing
    one would otherwise quietly undo the decision that the state may be committed.
    """
    if getattr(machine, "password", ""):
        log.die(f"this carrier sets a password on the container. Pulumi encrypts only "
                f"MARKED values and the container resource marks none, so that password would stand in "
                f"clear text in the committed state. Use `ssh_key:` - a public key is not a secret")
        raise SystemExit(1)


PROGRAM = '''"""GENERATED by `deploy carrier` - do not edit. The carrier this environment stands on."""
import os

import pulumi
import pulumi_proxmoxve as proxmox

provider = proxmox.Provider(
    "proxmox",
    endpoint=os.environ["CARRIER_ENDPOINT"],
    api_token=os.environ["CARRIER_TOKEN"],
    insecure=os.environ.get("CARRIER_INSECURE") == "1",
)

container = proxmox.ContainerLegacy(
    "carrier",
    node_name=os.environ["CARRIER_NODE"],
    description="simplon carrier",
    unprivileged=True,
    # `nesting` AND NOT `keyctl`, measured rather than copied from a runbook. Proxmox refuses every
    # feature flag except nesting to an API token - HTTP 403, "only allowed for root@pam" - and Docker
    # does not need the other one: Debian 13, kernel 7.0, overlay2, cgroup v2, `docker run hello-world`
    # green with nesting alone.
    features=proxmox.ContainerLegacyFeaturesArgs(nesting=True),
    operating_system=proxmox.ContainerLegacyOperatingSystemArgs(
        template_file_id=os.environ["CARRIER_TEMPLATE"], type="debian"),
    disk=proxmox.ContainerLegacyDiskArgs(
        datastore_id=os.environ["CARRIER_STORAGE"], size=int(os.environ["CARRIER_DISK"])),
    memory=proxmox.ContainerLegacyMemoryArgs(dedicated=int(os.environ["CARRIER_MEMORY"])),
    cpu=proxmox.ContainerLegacyCpuArgs(cores=int(os.environ["CARRIER_CORES"])),
    initialization=proxmox.ContainerLegacyInitializationArgs(
        hostname=os.environ["CARRIER_HOSTNAME"],
        ip_configs=[proxmox.ContainerLegacyInitializationIpConfigArgs(
            ipv4=proxmox.ContainerLegacyInitializationIpConfigIpv4Args(address="dhcp"))],
        # A PUBLIC KEY AND NO PASSWORD. The container resource marks nothing secret, so a password here
        # would sit in clear text in the state this product commits.
        user_account=proxmox.ContainerLegacyInitializationUserAccountArgs(
            keys=[os.environ["CARRIER_SSH_KEY"]]),
    ),
    network_interfaces=[proxmox.ContainerLegacyNetworkInterfaceArgs(name="eth0", bridge="vmbr0")],
    started=True,
    opts=pulumi.ResourceOptions(provider=provider),
)

pulumi.export("vm_id", container.vm_id)
'''

PROJECT = '''name: simplon-carrier
runtime:
  name: python
  options:
    virtualenv: ""
description: GENERATED by `deploy carrier` - do not edit
'''

REQUIREMENTS = '''pulumi>=3.262.0,<4
pulumi-proxmoxve~=8.6.0
'''

PLAYBOOK = '''# GENERATED by `deploy carrier` - do not edit.
#
# NO COMPOSE, measured: Debian 13 carries only `docker-compose` v1 and answers `docker compose version`
# with "'compose' is not a docker command". Portainer is ONE container, so an orchestrator for it would
# be a dependency bought for nothing - and the community addon that uses one also fetches its file from
# a moving channel, which is what the pin below exists to avoid.
- name: A Proxmox container becomes a Portainer carrier
  hosts: carrier
  gather_facts: true
  vars:
    portainer_image: {image}
    portainer_port: {port}
    # READ FROM THE ENVIRONMENT, NOT WRITTEN HERE. The first version interpolated the password
    # into this file, which the kernel then wrote into `build/` at mode 0644 - the exact defect
    # `credentials.py` exists for, committed by the code that cites it. The rendered playbook now
    # carries no secret at all. The NAME is rendered (si#802): `<url_from>_PASSWORD`, the one variable
    # the kernel checked and forwarded. A fixed name read an empty string beside any other `url_from`.
    portainer_password: "{{{{ lookup('env', '{password_from}') }}}}"
  # `carrier_directories`: the `directories:` of every environment on this carrier (si#782), written by
  # the kernel beside this file with every value tagged `!unsafe` - so a path is data and never a piece
  # of the playbook, and Ansible does not template it. The manifest already refuses any path outside a
  # strict character set; the tag is the second wall, not the first.
  vars_files:
    - directories.yml

  tasks:
    - name: Docker is installed
      ansible.builtin.apt:
        name: docker.io
        state: present
        update_cache: true

    - name: The Docker daemon is running and enabled
      ansible.builtin.systemd_service:
        name: docker
        state: started
        enabled: true

    # BEFORE ANY STACK BINDS THEM (si#782). Docker creates a missing bind source itself, as root, and a
    # service running as uid 1000 then dies with "unable to open database file". What is not declared
    # is omitted rather than defaulted: an entry without `mode:` leaves the mode alone.
    #
    # THE PARENTS FIRST, AND PLAIN. Measured 2026-11-20 with this image: `file` creating
    # /srv/app/test/data in one step gives the missing /srv/app the DECLARED owner and mode as well -
    # a statement about a directory the manifest never named, shared by every environment below it.
    - name: The parents of those directories are there, as the system makes them
      ansible.builtin.file:
        path: "{{{{ item.path | dirname }}}}"
        state: directory
      loop: "{{{{ carrier_directories }}}}"

    - name: The directories the stacks bind are there, with their owner and mode
      ansible.builtin.file:
        path: "{{{{ item.path }}}}"
        state: directory
        owner: "{{{{ item.owner | default(omit) }}}}"
        group: "{{{{ item.group | default(omit) }}}}"
        mode: "{{{{ item.mode | default(omit) }}}}"
      loop: "{{{{ carrier_directories }}}}"

    - name: The pinned Portainer image is present
      ansible.builtin.command:
        cmd: "docker image inspect {{{{ portainer_image }}}}"
      register: image_present
      changed_when: false
      failed_when: false

    - name: Pull it when it is not
      ansible.builtin.command:
        cmd: "docker pull {{{{ portainer_image }}}}"
      when: image_present.rc != 0

    # THE ADMIN PASSWORD, WRITTEN BEFORE PORTAINER STARTS, and the whole reason is a measurement:
    # a Portainer with no admin account LOCKS ITSELF after five minutes -
    #   "the Portainer instance timed out for security purposes, to re-enable your Portainer
    #    instance, you will need to restart Portainer"
    # and `/api/users/admin/init` then answers 403 because 2.45 wants a setup token it prints into its
    # own log. Parsing a log for a token is fragile; starting Portainer already initialised is not.
    # Measured 2026-09-15: with the file below, `/api/users/admin/check` answers 204 from the first
    # second. Mode 0600 and outside any volume - it is a password on a disk.
    - name: The admin password is on the carrier
      ansible.builtin.copy:
        dest: /root/.portainer-admin
        content: "{{{{ portainer_password }}}}"
        mode: "0600"
      no_log: true

    # THE WHOLE INSPECT AND NOT A `--format`, deliberately: a Go template is `{{ ... }}` and so is
    # Jinja, so a format string here is read by Ansible before docker ever sees it. Searching the raw
    # JSON costs nothing and cannot be misread by either.
    - name: Is Portainer already there, and how was it started?
      ansible.builtin.command:
        cmd: "docker container inspect portainer"
      register: container_present
      changed_when: false
      failed_when: false

    # AND AN EXISTING PORTAINER THAT WAS STARTED WITHOUT IT IS REPLACED. A play that only acted on a
    # MISSING container would leave every carrier built before this change locked forever - which is the
    # difference between a run that converges and one that merely does nothing the second time.
    - name: An uninitialised Portainer is taken down
      ansible.builtin.command:
        cmd: docker rm -f portainer
      when: container_present.rc == 0 and "admin-password-file" not in container_present.stdout

    # THE IDEMPOTENCE, as one `when:` rather than a comment claiming it. Driven twice on 2026-09-15:
    # ok=9 changed=2, then ok=7 changed=0 skipped=2, with exactly one container on the machine.
    - name: Portainer is running
      ansible.builtin.command:
        cmd: >
          docker run -d --name portainer --restart always
          -p {{{{ portainer_port }}}}:9443
          -v /var/run/docker.sock:/var/run/docker.sock
          -v portainer_data:/data
          -v /root/.portainer-admin:/run/secrets/adminpw:ro
          {{{{ portainer_image }}}}
          --admin-password-file /run/secrets/adminpw
      when: container_present.rc != 0 or "admin-password-file" not in container_present.stdout

    - name: Portainer answers on its port
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/status"
        validate_certs: false
      register: status
      retries: 12
      delay: 5
      until: status.status == 200

    # A FRESH PORTAINER MANAGES NOTHING, measured the same day: `GET /api/endpoints` comes back EMPTY
    # while the carrier declares `endpoint: 1`. Without this, that number is a promise nobody keeps and
    # the first stack deployment fails against an environment that does not exist.
    - name: Log in as the admin
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/auth"
        method: POST
        body_format: json
        body: {{"Username": "admin", "Password": "{{{{ portainer_password }}}}"}}
        validate_certs: false
      register: auth
      failed_when: false
      no_log: true

    # `no_log` HIDES A FAILURE'S OWN WORDS with the secret (si#784), so every hidden API call here is
    # told not to fail on its own and the task after it fails instead - with the status, the module's
    # message and Portainer's, none of which carries the header or the body that was sent. si#781's
    # pattern for the runner's registration token.
    - name: The login answered
      ansible.builtin.fail:
        msg: "logging in as the admin failed: {{{{ auth.status | default('no answer') }}}} {{{{ auth.msg | default('') }}}} {{{{ auth.json.message | default('') }}}}"
      when: auth.status | default(-1) != 200

    # NO_LOG ON EVERY CALL THAT SENDS THE JWT (si#784): it is the admin's session for eight hours, and
    # Ansible prints a task's arguments at a higher verbosity.
    - name: Which Docker environments does it manage?
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/endpoints"
        headers:
          Authorization: "Bearer {{{{ auth.json.jwt }}}}"
        validate_certs: false
      register: endpoints
      failed_when: false
      no_log: true

    - name: The environments answered
      ansible.builtin.fail:
        msg: "listing Portainer's environments failed: {{{{ endpoints.status | default('no answer') }}}} {{{{ endpoints.msg | default('') }}}} {{{{ endpoints.json.message | default('') }}}}"
      when: endpoints.status | default(-1) != 200

    - name: The local one exists
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/endpoints"
        method: POST
        headers:
          Authorization: "Bearer {{{{ auth.json.jwt }}}}"
        body_format: form-multipart
        body:
          Name: local
          EndpointCreationType: "1"
        status_code: 200
        validate_certs: false
      register: local_endpoint
      failed_when: false
      no_log: true
      when: endpoints.json | length == 0

    - name: The local one was created
      ansible.builtin.fail:
        msg: "creating the local Docker environment failed: {{{{ local_endpoint.status | default('no answer') }}}} {{{{ local_endpoint.msg | default('') }}}} {{{{ local_endpoint.json.message | default('') }}}}"
      when: local_endpoint is not skipped and local_endpoint.status | default(-1) != 200

    - name: What it reports
      ansible.builtin.debug:
        msg: "Portainer {{{{ status.json.Version }}}} on {{{{ ansible_host }}}}:{{{{ portainer_port }}}}, admin ready"
'''

#: What the API token `deploy up` reads is known by on the Portainer side (si#784). FIXED, because it is
#: the only thing a second run can find the first run's token by: Portainer keeps a description and a
#: SHA-256 of the key, never the key itself (`api/apikey/service.go` at 2.45.0).
TOKEN_DESCRIPTION = "simplon deploy:carrier"

#: The token tasks by name, so the tests hold the tasks and not a copy of their wording.
TOKEN_FIRST_TASK = "Who the admin is"
MINT_TASK = "The API token deploy up reads is minted"
SHOW_TASK = "The API token, shown this once"
EXISTS_TASK = "An API token already exists, so none was minted"
NOT_INTERACTIVE_TASK = "No API token is minted into a log"

#: The extra variable the kernel's decision reaches the play under (`interactive`). Absent means false:
#: a play run by hand, with nobody having asked, mints nothing.
MINT_VAR = "simplon_mint_token"

# THE API TOKEN, IN THE PLAY AND NOT IN THE KERNEL (si#784), for one reason: the play already holds the
# admin's JWT and talks to Portainer on 127.0.0.1 inside SSH. Minting from the operator's machine would
# send the admin password across the network to a self-signed certificate nobody verifies.
#
# The API, read off Portainer CE 2.45.0's source rather than its docs:
#   POST /api/users/{{id}}/tokens  {{password, description}} -> {{rawAPIKey, apiKey}}
#     user_create_access_token.go: a JWT only ("API-Key based auth is not supported"), the caller
#     only for itself, and the password is required for the admin (user 1 always uses internal auth).
#   GET  /api/users/{{id}}/tokens  -> [{{id, description, prefix, dateCreated, lastUsed}}], digest blanked
#   DELETE /api/users/{{id}}/tokens/{{keyID}}  - by the user itself, with a JWT or the API key
#
# A SECOND RUN DOES NOT MINT A SECOND TOKEN, and that is decided, not defaulted: Portainer refuses no
# duplicate description, so minting on every run would leave one more live admin credential behind per
# run, each unrevokable by anyone who does not know which one is in use. The first run's value cannot be
# shown again either - only its digest exists. So a second run says a token exists and how to replace it.
#
# AND A RUN THAT IS NOT A PERSON AT A TERMINAL MINTS NONE (owner, on #804): the key is shown on stdout,
# and a CI job's stdout is a log somebody keeps. `interactive` decides in the kernel and hands it over.
TOKEN_TASKS = '''
    - name: {first}
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/users/me"
        headers:
          Authorization: "Bearer {{{{ auth.json.jwt }}}}"
        validate_certs: false
      register: me
      failed_when: false
      no_log: true

    - name: The admin was found
      ansible.builtin.fail:
        msg: "asking Portainer who the admin is failed: {{{{ me.status | default('no answer') }}}} {{{{ me.msg | default('') }}}} {{{{ me.json.message | default('') }}}}"
      when: me.status | default(-1) != 200

    - name: Which API tokens the admin already holds
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/users/{{{{ me.json.Id }}}}/tokens"
        headers:
          Authorization: "Bearer {{{{ auth.json.jwt }}}}"
        validate_certs: false
      register: tokens
      failed_when: false
      no_log: true

    - name: The tokens were listed
      ansible.builtin.fail:
        msg: "listing the admin's API tokens failed: {{{{ tokens.status | default('no answer') }}}} {{{{ tokens.msg | default('') }}}} {{{{ tokens.json.message | default('') }}}}"
      when: tokens.status | default(-1) != 200

    - name: Is one of them this command's?
      ansible.builtin.set_fact:
        existing: "{{{{ tokens.json | selectattr('description', 'equalto', '{description}') | list }}}}"

    # NO_LOG, because its result IS the token. `register` keeps it in memory only: the fact cache is
    # memory, no log path is set, and the run's work directory was searched for it after a real run.
    - name: {mint}
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/users/{{{{ me.json.Id }}}}/tokens"
        method: POST
        headers:
          Authorization: "Bearer {{{{ auth.json.jwt }}}}"
        body_format: json
        body: {{"password": "{{{{ portainer_password }}}}", "description": "{description}"}}
        status_code: 200
        validate_certs: false
      register: minted
      failed_when: false
      no_log: true
      changed_when: true
      when: existing | length == 0 and {mint_var} | default(false) | bool

    - name: The token was minted
      ansible.builtin.fail:
        msg: "minting the API token failed: {{{{ minted.status | default('no answer') }}}} {{{{ minted.msg | default('') }}}} {{{{ minted.json.message | default('') }}}}"
      when: minted is not skipped and minted.status | default(-1) != 200

    # THE ONE PLACE THE TOKEN IS WRITTEN, and it is the terminal - only ever a person's (`interactive`).
    - name: {show}
      ansible.builtin.debug:
        msg:
          - "{token_env}={{{{ minted.json.rawAPIKey }}}}"
          - "Shown ONCE: Portainer keeps only its digest and this run wrote it nowhere. Store it where
            `deploy up` reads {token_env}; a lost one is replaced by revoking it and running
            `deploy carrier` again."
      when: minted is not skipped

    - name: {not_interactive}
      ansible.builtin.debug:
        msg:
          - "No API token was minted: this run is not interactive (CI is set, or its output is not a
            terminal), and the token is shown on the output - which here is a log somebody keeps."
          - "Mint it by running `deploy carrier` from a terminal, outside CI; it then shows
            {token_env} once."
      when: existing | length == 0 and not ({mint_var} | default(false) | bool)

    - name: {exists}
      ansible.builtin.debug:
        msg:
          - "An API token described '{description}' already exists (prefix
            {{{{ existing | map(attribute='prefix') | join(', ') }}}}), so none was minted. Its value was
            shown once, when it was minted; Portainer keeps only its digest."
          - "To mint a new one, revoke it and run `deploy carrier` again - in Portainer under My account >
            Access tokens, or in bash: curl -k -X DELETE -H @<(echo X-API-Key: ${token_env})
            https://{{{{ ansible_host }}}}:{{{{ portainer_port }}}}/api/users/{{{{ me.json.Id }}}}/tokens/{{{{
            existing | map(attribute='id') | first }}}}"
      when: existing | length > 0
'''


def interactive() -> bool:
    """Whether this run may mint and show the API token: a person at a terminal, outside CI (si#784).

    DECIDED HERE AND NOT IN THE PLAY, because only the kernel can see its own stdout: the play runs in a
    `docker run` without `-t`, where every run looks non-interactive. `sys.stdout` and not fd 1, on
    purpose: a step that captures its output into a log answers `isatty()` False (`steps.py`), and a log
    is exactly where the key may not go. `CI` counts when it is non-empty, which is what CI services set.
    """
    return not os.environ.get("CI") and sys.stdout.isatty()


def playbook(carrier: carrierspec.Carrier, port: int = PORTAINER_PORT) -> str:
    """The play `deploy carrier` runs on a carrier that declares a Portainer: the machine, then the
    token. It carries names and never a value - the password and the token are read or minted at run
    time, and whether to mint at all arrives as `MINT_VAR`. The mint sends `portainer_password`, so it
    reads the same rendered `<url_from>_PASSWORD` the login does (si#802). The token is shown under the
    name `deploy up` reads and si#810 derives for the launcher, from the one spelling of it
    (`portainer.target_variables`) rather than a second copy here."""
    prefix = _declared_portainer(carrier).url_from
    token_env = portainer.target_variables(prefix)[1]
    return (PLAYBOOK.format(image=PORTAINER_IMAGE, port=port, password_from=f"{prefix}{PASSWORD_SUFFIX}")
            + TOKEN_TASKS.format(first=TOKEN_FIRST_TASK, mint=MINT_TASK, show=SHOW_TASK,
                                 exists=EXISTS_TASK, not_interactive=NOT_INTERACTIVE_TASK,
                                 mint_var=MINT_VAR, description=TOKEN_DESCRIPTION,
                                 token_env=token_env))


#: The runner half's play (si#781), its tasks as they run. NOT a format string, unlike `PLAYBOOK`: every
#: value it needs is a play variable `runner_play` renders above it as JSON, so no Jinja brace here has to
#: be doubled and no manifest string is ever spliced into YAML by hand.
#:
#: THE TOKEN, END TO END, and every hop is a measurement or a reading of the tool's own source:
#:   * kernel -> Ansible container: `docker run -e NAME`, bare - the value is in no argv and no file.
#:   * Ansible: `lookup('env', ...)` into a variable; only `no_log` tasks touch it.
#:   * Ansible -> carrier: PIPELINED (`ansible_pipelining`), so the module and its arguments travel on
#:     ssh's stdin. Without it Ansible writes each module WITH ITS ARGUMENTS to ~/.ansible/tmp on the
#:     target before running it, and the registration's arguments carry the token.
#:   * on the carrier: the token is the command module's `stdin`, read by `sh` into
#:     `ACTIONS_RUNNER_INPUT_TOKEN`. actions/runner reads every `ACTIONS_RUNNER_INPUT_<ARG>` as that
#:     argument, masks a secret one and REMOVES it from its environment (Runner.Listener/CommandSettings.cs,
#:     v2.338.2). `--token <value>` would sit in the carrier's process list for the whole registration.
#:     `env.sh`, which config.sh runs, writes a FIXED list of variables into `.env` - this is not one.
RUNNER_TASKS = '''
  tasks:
    - name: The runner's architecture is one the pin covers
      ansible.builtin.fail:
        msg: "actions/runner {{ runner_version }} is pinned for {{ runner_sha256.keys() | join(', ') }}; this machine is {{ ansible_architecture }}"
      when: runner_arch not in runner_sha256

    - name: The registration token reached the play
      ansible.builtin.fail:
        msg: "{{ runner_token_variable }} is empty inside the play, so the runner cannot register"
      when: runner_token | length == 0

    # The `self-hosted-debian` machine (`manifest/runners.py`): the launcher builds its venv with the
    # machine's own python3, which on Debian needs python3-venv, and docker is the engine itself.
    - name: Docker, git and a python3 that can make a venv are installed
      ansible.builtin.apt:
        name: [docker.io, git, python3, python3-venv]
        state: present
        update_cache: true

    - name: The Docker daemon is running and enabled
      ansible.builtin.systemd_service:
        name: docker
        state: started
        enabled: true

    - name: The runner's user exists and may reach docker
      ansible.builtin.user:
        name: "{{ runner_user }}"
        groups: [docker]
        append: true
        shell: /bin/bash
        create_home: true

    - name: The runner's directory belongs to it
      ansible.builtin.file:
        path: "{{ runner_dir }}"
        state: directory
        owner: "{{ runner_user }}"
        group: "{{ runner_user }}"
        mode: "0755"

    - name: The pinned runner is downloaded and its digest checked
      ansible.builtin.get_url:
        url: "https://github.com/actions/runner/releases/download/v{{ runner_version }}/actions-runner-linux-{{ runner_arch }}-{{ runner_version }}.tar.gz"
        dest: "/var/tmp/actions-runner-linux-{{ runner_arch }}-{{ runner_version }}.tar.gz"
        checksum: "sha256:{{ runner_sha256[runner_arch] }}"
        mode: "0644"

    - name: It is unpacked
      ansible.builtin.unarchive:
        src: "/var/tmp/actions-runner-linux-{{ runner_arch }}-{{ runner_version }}.tar.gz"
        dest: "{{ runner_dir }}"
        remote_src: true
        owner: "{{ runner_user }}"
        group: "{{ runner_user }}"
        creates: "{{ runner_dir }}/config.sh"

    - name: The runner's own dependencies are installed
      ansible.builtin.command:
        cmd: ./bin/installdependencies.sh
        chdir: "{{ runner_dir }}"
        creates: "{{ runner_dir }}/.runner"

    # `--replace`: a carrier made again takes its old name over instead of failing on it. `creates:` is
    # the idempotence - a registered runner is not registered twice, and its token is then not used.
    - name: The runner is registered on its repository
      ansible.builtin.command:
        argv:
          - runuser
          - -u
          - "{{ runner_user }}"
          - --
          - /bin/sh
          - -c
          - IFS= read -r ACTIONS_RUNNER_INPUT_TOKEN && export ACTIONS_RUNNER_INPUT_TOKEN && exec ./config.sh --unattended --replace --url "$1" --name "$2" --labels "$3"
          - register
          - "{{ runner_url }}"
          - "{{ runner_name }}"
          - "{{ runner_labels }}"
        chdir: "{{ runner_dir }}"
        stdin: "{{ runner_token }}"
        creates: "{{ runner_dir }}/.runner"
      register: registration
      failed_when: false
      no_log: true

    # `no_log` hides a failure's own words with the token, so they are said here - config.sh masks the
    # token in what it prints, which is what makes its output safe to show.
    - name: The registration succeeded
      ansible.builtin.fail:
        msg: "config.sh exited {{ registration.rc }}: {{ registration.stdout | default('') }} {{ registration.stderr | default('') }}"
      when: registration.rc is defined and registration.rc != 0

    - name: It runs as a service
      ansible.builtin.command:
        cmd: ./svc.sh install {{ runner_user }}
        chdir: "{{ runner_dir }}"
        creates: "{{ runner_dir }}/.service"

    - name: Which unit it is
      ansible.builtin.slurp:
        src: "{{ runner_dir }}/.service"
      register: unit

    - name: The service is running and enabled
      ansible.builtin.systemd_service:
        name: "{{ unit.content | b64decode | trim }}"
        state: started
        enabled: true

    # ONLINE, ASKED OF THE RUNNER ITSELF. It prints "Listening for Jobs" once its session with GitHub
    # stands; a service that is merely active may be retrying a rejected registration forever.
    - name: The runner says it is listening for jobs
      ansible.builtin.shell:
        cmd: >
          journalctl --no-pager -o cat
          _SYSTEMD_INVOCATION_ID="$(systemctl show -p InvocationID --value "$UNIT")"
      environment:
        UNIT: "{{ unit.content | b64decode | trim }}"
      register: journal
      changed_when: false
      until: "'Listening for Jobs' in journal.stdout"
      retries: 24
      delay: 5

    - name: What it reports
      ansible.builtin.debug:
        msg: "runner {{ runner_name }} on {{ ansible_host }} is listening for {{ runner_url }} with labels {{ runner_labels }}"
'''


def runner_play(carrier: carrierspec.Carrier) -> str:
    """The runner half's play, its values rendered as JSON (which YAML reads as it is) above its tasks.

    The token's NAME is rendered and never its value: the play reads the value with `lookup('env', ...)`,
    so this file is safe to write to `build/` - `test_the_token_reaches_no_rendered_file...` reads it back.
    """
    runner = _declared_runner(carrier)
    values = {
        "ansible_pipelining": True,
        "runner_version": RUNNER_VERSION,
        "runner_sha256": RUNNER_SHA256,
        "runner_arches": {"x86_64": "x64", "aarch64": "arm64"},
        "runner_user": RUNNER_USER,
        "runner_dir": RUNNER_DIR,
        "runner_url": f"https://github.com/{runner.repository}",
        "runner_name": carrier.name,
        "runner_labels": ",".join(runner.labels),
        "runner_token_variable": runner_token_variable(carrier),
    }
    lines = [f"    {key}: {json.dumps(value)}" for key, value in values.items()]
    lines.append("    runner_arch: \"{{ runner_arches[ansible_architecture] | default(ansible_architecture) }}\"")
    lines.append(f"    runner_token: \"{{{{ lookup('env', '{runner_token_variable(carrier)}') }}}}\"")
    return ("# GENERATED by `deploy carrier` - do not edit.\n"
            "- name: A Proxmox container becomes a self-hosted actions runner\n"
            "  hosts: carrier\n"
            "  gather_facts: true\n"
            "  vars:\n" + "\n".join(lines) + "\n" + RUNNER_TASKS)


def render(carrier: carrierspec.Carrier, root: Path) -> Path:
    """Write the Pulumi project out, and hand back where it went. Rendered on every run rather than
    committed: it is an output of the manifest, and a committed copy would be a second source of what
    the carrier is."""
    where = root / PROGRAM_DIR / carrier.name
    where.mkdir(parents=True, exist_ok=True)
    (where / "__main__.py").write_text(PROGRAM, encoding="utf-8")
    (where / "Pulumi.yaml").write_text(PROJECT, encoding="utf-8")
    (where / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    return where


def _pulumi(carrier: carrierspec.Carrier, machine: carrierspec.Proxmox, token: str, program: Path,
            state: Path, hostname: str) -> int:
    """Run `pulumi up` in the pinned image, over the rendered program, against the committed state.

    `PULUMI_BACKEND_URL` RATHER THAN `pulumi login`, measured on 2026-09-14: `pulumi login file://...`
    fails non-interactively with *"PULUMI_ACCESS_TOKEN must be set for login during non-interactive CLI
    sessions"* - the CLI falls back to Pulumi Cloud rather than reading the file URL. The environment
    variable skips the login step entirely, which is what a pipeline needs.

    NAMED AND LABELLED, AND DELIBERATELY NOT REMOVED ON INTERRUPT (si#412) - the one labelled container
    that is not. `docker rm -f` is a SIGKILL, and a `pulumi up` killed that way cannot write back what
    it was half-way through: Pulumi documents that it leaves the operations it had begun as PENDING in the
    checkpoint - here, the state file this product commits - and the next `up` stops on them until
    somebody resolves them by hand. NOT MEASURED HERE: there is no Proxmox in this suite to kill a
    Pulumi run against. Letting the run finish is the lesser harm for a tool that keeps its own state,
    so a cancel leaves it running - and `simplon.run=<product>` is what lets an operator find it and
    decide.

    A CLEAN STOP IS ONE SIGNAL, AND ONLY ONE (si#416). Measured on 2026-10-14 with this image and a file
    backend, a python program whose one resource sleeps: pulumi takes a SIGINT, or a SIGTERM, as "cancelling"
    - the operation in flight finishes and the update ends `update canceled`, state written. A SECOND
    signal of either kind is "terminating": the resource is left `(interrupted)`, which is the pending
    state above. `--init` hands what the client forwards to its direct child only, so the line ends in
    `exec pulumi up`: the image's bash 5.2 already replaces itself for the last command of an `&&` list
    (measured: pulumi's parent was docker-init), and the `exec` makes that a statement rather than a
    property of one bash version. A Ctrl-C at a terminal reaches the client in the same process group,
    the client forwards it, and pulumi cancels cleanly - measured through `run` with a stand-in.

    WHAT IS OUT OF REACH, and why it stays so: a SIGTERM to the kernel alone - a container-route cancel,
    a `kill` - never reaches this client, and the run goes on to its end (measured). The kernel could send
    the one signal itself, `docker kill --signal INT <name>`, but it cannot tell whether the client has
    already forwarded one: a group-wide signal reaches both. Its signal would then be the SECOND, which is
    the forced stop this function exists to avoid. Finishing is the lesser harm, as above.
    """
    state.mkdir(parents=True, exist_ok=True)
    # Into THIS process's environment, which `docker run -e NAME` then reads. The alternative -
    # `-e NAME=value` - puts the secret into the docker client's argv, where `/proc/<pid>/cmdline` and
    # `ps` can read it for as long as the container runs.
    os.environ[CARRIER_TOKEN_ENV] = token
    os.environ[PULUMI_PASSPHRASE_ENV] = os.environ.get(PASSPHRASE_ENV, "")
    argv = [
        "docker", "run", "--rm",
        # THROUGH `hostpath.translate`, and the guard that insisted is right: on si#201's container
        # route the kernel is itself a container and the daemon resolves a `-v` source against the HOST,
        # so handing it `/src` creates an empty directory and mounts that - rc 0, no message, and a
        # carrier built from an empty program.
        "-v", f"{hostpath.translate(program)}:/work",
        "-v", f"{hostpath.translate(state)}:/state", "-w", "/work",
        # `-e NAME` AND NEVER `-e NAME=value`: argv is world-readable - `/proc/<pid>/cmdline` on
        # Linux, `ps` on macOS - which is `credentials.py`'s own rule, and `docker run -e NAME` takes
        # the value out of THIS process's environment without ever writing it on a command line.
        *docker.lifecycle()[1],
        "-e", PULUMI_PASSPHRASE_ENV,
        "-e", "PULUMI_BACKEND_URL=file:///state",
        "-e", f"CARRIER_ENDPOINT={machine.endpoint}",
        "-e", CARRIER_TOKEN_ENV,
        "-e", f"CARRIER_INSECURE={'1' if machine.insecure else '0'}",
        "-e", f"CARRIER_NODE={machine.node}",
        "-e", f"CARRIER_TEMPLATE={machine.template}",
        "-e", f"CARRIER_STORAGE={machine.storage}",
        "-e", f"CARRIER_DISK={machine.disk}",
        "-e", f"CARRIER_MEMORY={machine.memory}",
        "-e", f"CARRIER_CORES={machine.cores}",
        "-e", f"CARRIER_HOSTNAME={hostname}",
        "-e", f"CARRIER_SSH_KEY={machine.ssh_key}",
        PULUMI_IMAGE,
        "bash", "-c",
        "pip install -q --root-user-action=ignore -r requirements.txt >/dev/null 2>&1 && "
        f"(pulumi stack init {carrier.name} --non-interactive >/dev/null 2>&1 || "
        f"pulumi stack select {carrier.name} >/dev/null 2>&1) && "
        "exec pulumi up --yes --non-interactive",
    ]
    return run.stream(argv)


def directories_on(carrier_name: str) -> "list[dict[str, str]]":
    """The `directories:` of EVERY environment standing on this carrier, as the play's `file` items (si#782).

    Every environment and not only the one `deploy carrier` was run for: the play configures the MACHINE,
    and `test` and `prod` on one carrier would otherwise each need a carrier run of their own before their
    first `deploy up` stopped refusing. A path two environments both declare is created once, as the first
    declares it; if they disagree, `deploy up` of the other one says so on the carrier.
    """
    document = context.current().manifest_data()
    registry = environments.parse_data(document, _backends(document))
    items: dict[str, dict[str, str]] = {}
    for environment in registry.environments.values():
        if environment.carrier != carrier_name:
            continue
        for directory in environment.directories:
            item = {"path": directory.path}
            if directory.uid is not None:
                item["owner"] = str(directory.uid)
            if directory.gid is not None:
                item["group"] = str(directory.gid)
            if directory.mode is not None:
                item["mode"] = f"0{directory.mode:o}"
            items.setdefault(directory.path, item)
    return list(items.values())


def unsafe_vars(directories: "list[dict[str, str]]") -> str:
    """The play's `carrier_directories` as a YAML vars file, every value tagged `!unsafe` (si#782).

    DEFENCE IN DEPTH, MEASURED 2026-11-20 with the pinned ansible image: a path written as
    `/srv/app/{{ 7*7 }}` in a plain vars file made the play create `/srv/app/49` - the value was
    templated on the carrier. Tagged `!unsafe` it is taken literally. Each value is a JSON string literal,
    which is a valid YAML double-quoted scalar, so no character in it can end the scalar or the line.
    """
    if not directories:
        return "carrier_directories: []\n"
    lines = ["carrier_directories:"]
    for item in directories:
        for n, (key, value) in enumerate(item.items()):
            lines.append(f"  {'-' if n == 0 else ' '} {key}: !unsafe {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def _ansible(carrier: carrierspec.Carrier, address: str, work: Path, key: Path, port: int,
             directories: "list[dict[str, str]] | None" = None) -> int:
    """Run the play in the pinned image, against the carrier's address, with the operator's own key.

    The key is MOUNTED, never copied into the tree and never passed as a value: what the manifest and
    the environment carry is a PATH, which is not a secret.

    Named, labelled, and removed if this run is interrupted (si#412). Unlike `_pulumi` there is no state
    to corrupt: a play stopped half-way leaves a host part-configured, and the next run converges it,
    which is what a play is for.
    """
    # ONE PLAY PER DECLARED HALF (si#781), in one file: each play is self-contained, so a carrier with
    # both halves runs both and one with either runs that one.
    plays: list[str] = []
    secrets: list[str] = []
    if carrier.portainer is not None:
        password_from = f"{_declared_portainer(carrier).url_from}{PASSWORD_SUFFIX}"
        plays.append(playbook(carrier, port))
        # The password rides the environment for the same reason, and the playbook reads it with
        # `lookup('env', ...)` rather than carrying a rendered copy of it on disk.
        secrets += ["-e", password_from]
    if carrier.runner is not None:
        plays.append(runner_play(carrier))
        secrets += ["-e", runner_token_variable(carrier)]
    (work / "carrier.yml").write_text("\n".join(plays), encoding="utf-8")
    # Read by the Portainer play's `vars_files:` (si#782); written either way, since it is data only.
    (work / "directories.yml").write_text(unsafe_vars(directories or []), encoding="utf-8")
    (work / "inventory.ini").write_text(
        f"[carrier]\n{carrier.name} ansible_host={address} ansible_user=root\n", encoding="utf-8")
    container, lifecycle = docker.lifecycle()
    argv = [
        "docker", "run", "--rm", *lifecycle,
        *secrets,
        "-v", f"{hostpath.translate(work)}:/work",
        "-v", f"{hostpath.translate(key)}:/key:ro", "-w", "/work",
        "-e", "ANSIBLE_HOST_KEY_CHECKING=False",
        ANSIBLE_IMAGE,
        "ansible-playbook", "-i", "inventory.ini", "carrier.yml", "--private-key", "/key",
        # A decision and not a secret, so a command-line extra variable is the right carrier for it.
        "-e", f"{MINT_VAR}={'true' if interactive() else 'false'}",
    ]
    with docker.stopped_on_interrupt(container):
        return run.stream(argv)


def up(environment: str = "") -> int:
    """Make the carrier this environment stands on: the machine, and what it declares on top of it.

    TWO SHAPES SINCE si#258, and the second one is the finding rather than a feature. A carrier that
    declares a `portainer:` gets the machine and the Portainer, as before. A carrier that declares none
    gets the machine and NOTHING ELSE - reported as its own outcome, because before this the
    apt -> Docker -> Portainer playbook ran at the end of every run with no branch in it, and a product
    that wanted a machine got a workload it had not asked for.

    IT IS ITS OWN COMMAND AND NOT A PREAMBLE TO `deploy up` (owner decision, 2026-09-14). Two verbs,
    two verdicts: when setting a carrier up fails, it says so instead of taking a deployment down with
    it - and a `deploy up` that created an LXC the first time it ran would be a very large command.

    ONE CARRIER SERVES MANY ENVIRONMENTS, which is why the hostname is the CARRIER's name and not the
    environment's. biz-cockpit's `test` and `prod` share one machine and are separated inside it; an
    implementation that named the machine after the environment would have quietly ruled that out.
    """
    environment_, carrier, machine = _carrier_of(environment)
    check_no_password(machine)
    # Called for its REFUSALS, not for its value: the password now reaches Ansible through the
    # environment, and what this returns is thrown away. Reading it here all the same is what stops a
    # carrier being built whose Portainer would then lock itself - the check belongs before the machine
    # exists, not after. Skipped for a carrier that declares no Portainer (si#258): there is no admin
    # account to be locked out of, so demanding a password for one would refuse a carrier that works.
    if carrier.portainer is not None:
        portainer_password(carrier)
    # The runner's registration token, for the same reason and with the same skip (si#781).
    if carrier.runner is not None:
        runner_token(carrier)
    root = context.current().root
    token = _token(carrier, machine)

    missing = [name for name, value in (("endpoint", machine.endpoint),
                                        ("template", machine.template),
                                        ("storage", machine.storage),
                                        ("ssh_key", machine.ssh_key)) if not value]
    if missing:
        log.die(f"carrier '{carrier.name}' declares no {', '.join(missing)} - every one of them is "
                f"configuration and belongs in the manifest")
        return 1

    # THE REFUSAL THAT USED TO ARRIVE THREE MINUTES LATE. Asked here, before a container starts.
    try:
        proxmoxapi.check_storage(machine.endpoint, token, machine.node,
                                 machine.storage, insecure=machine.insecure)
    except proxmoxapi.ProxmoxError as error:
        log.die(f"carrier '{carrier.name}': {error}")
        return 1

    log.info(f"carrier '{carrier.name}' for environment '{environment_.name}' on "
             f"{machine.node} ({machine.kind})")
    program = render(carrier, root)
    rc = _pulumi(carrier, machine, token, program, root / STATE_DIR, carrier.name)
    if rc != 0:
        log.error(f"the carrier was not created (pulumi exited {rc}), so nothing was configured on it")
        return rc

    if carrier.portainer is None and carrier.runner is None:
        # THE MACHINE IS THE WHOLE OUTCOME, and saying so is the point of si#258. Before it, an
        # apt -> Docker -> Portainer playbook ran here with no branch in it, so a carrier that wanted a
        # machine got a workload it never asked for - and on a machine with no apt, a red run. "Created
        # and not configured" is a third outcome beside created-and-configured and failed, and it is
        # reported as one rather than left to be inferred from a log that stops early.
        log.ok(f"carrier '{carrier.name}' exists on {machine.node} and nothing was installed on "
               f"it - it declares no `portainer:` and no `runner:`, so what runs on it is this product's own to "
               f"deploy")
        return 0

    key = os.environ.get(SSH_KEY_ENV, "")
    if not key:
        log.error(f"{SSH_KEY_ENV} is not set, so the machine exists and nothing could be installed on "
                  f"it. It names the PATH of the private key whose public half the carrier declares")
        return 1
    key_path = Path(key).expanduser()
    if not key_path.is_file():
        log.error(f"{SSH_KEY_ENV} points at {key_path}, which is not a file")
        return 1

    address = _address(carrier, machine, token)
    if not address:
        log.error(f"carrier '{carrier.name}' has no address yet - it is created but its interface has "
                  f"not answered. Run this again in a moment; nothing was lost")
        return 1
    return _ansible(carrier, address, program, key_path, PORTAINER_PORT, directories_on(carrier.name))


def _address(carrier: carrierspec.Carrier, machine: carrierspec.Proxmox, token: str) -> str:
    """The carrier's own IPv4, asked of Proxmox rather than guessed from a lease file.

    A container on DHCP has no address the manifest could carry, and the node knows it - which is the
    one piece of runtime truth this command needs and the only reason it asks twice.
    """
    try:
        vmid = proxmoxapi.container_id(machine.endpoint, token, machine.node,
                                       carrier.name, insecure=machine.insecure)
        if not vmid:
            log.error(f"no container named '{carrier.name}' on {machine.node}, though the "
                      f"carrier run reported success - which is a disagreement worth reading before "
                      f"running anything again")
            return ""
        return proxmoxapi.address(machine.endpoint, token, machine.node, vmid,
                                  insecure=machine.insecure)
    except proxmoxapi.ProxmoxError as error:
        log.error(f"carrier '{carrier.name}': {error}")
        return ""
