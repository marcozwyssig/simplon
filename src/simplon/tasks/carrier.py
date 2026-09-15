"""`deploy:carrier` - make the thing an environment stands on (si#5).

WHAT THIS IS AND WHAT IT IS NOT. It is a translation, not an invention: two programs that were driven
by hand against a real Proxmox on 2026-09-14/15 are rendered here from the `carriers:` section and run
in pinned containers. Nothing below was written ahead of a measurement.

    pulumi/pulumi-python  ->  the LXC or VM on Proxmox        (the goal, and its state)
    alpine/ansible        ->  Docker and a pinned Portainer   (the steps, over SSH)

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

import os
import shutil
from pathlib import Path

from simplon import carrierspec, context, docker, environments, hostpath, log, run
from simplon.tasks import proxmoxapi

#: The two toolchains, pinned. Bump them deliberately, the way `DOCKER_CLI_VERSION` is bumped.
PULUMI_IMAGE = "pulumi/pulumi-python:3.262.0"
ANSIBLE_IMAGE = "alpine/ansible:2.21.0"

#: What Ansible puts on the carrier. Pinned here rather than fetched: the community addon downloads its
#: compose file from `downloads.portainer.io/ce-sts/`, a moving channel, which is exactly the thing a
#: pin exists to stop.
PORTAINER_IMAGE = "portainer/portainer-ce:2.45.0"

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


def _carrier_of(env_name: str = "") -> tuple[environments.Environment, carrierspec.Carrier]:
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
    return environment, declared[environment.carrier]


def _backends(document: dict) -> tuple[str, ...]:
    """Every backend name the document itself uses. The kernel does not own this list - a product
    registers its own implementations - so the set is read off the matrix rather than fixed here."""
    declared = document.get("environments") or {}
    names = {str((spec or {}).get("backend", "")).strip()
             for spec in declared.values() if isinstance(spec, dict)}
    return tuple(sorted(n for n in names if n)) or ("local",)


def _token(carrier: carrierspec.Carrier) -> str:
    """The Proxmox API token, from the environment and never from the file."""
    if not carrier.proxmox.token_from:
        log.die(f"carrier '{carrier.name}' declares no `token_from:`, so nothing says which environment "
                f"variable holds the API token. It is a PREFIX: `token_from: PROXMOX` reads "
                f"PROXMOX{TOKEN_SUFFIX}")
        raise SystemExit(1)
    variable = f"{carrier.proxmox.token_from}{TOKEN_SUFFIX}"
    token = os.environ.get(variable, "")
    if not token:
        log.die(f"{variable} is not set, so carrier '{carrier.name}' cannot reach "
                f"{carrier.proxmox.endpoint or 'Proxmox'}. Export it; it may not be written into the "
                f"manifest, which is why the manifest has no field for it")
        raise SystemExit(1)
    return token


def portainer_password(carrier: carrierspec.Carrier) -> str:
    """The Portainer admin password, from the environment and never from the file.

    IT IS NOT OPTIONAL, and that is the measurement rather than a preference: a Portainer started without
    one locks itself five minutes later and then wants a setup token out of its own log. Refusing here
    beats delivering a carrier whose Portainer nobody can ever log into.
    """
    variable = f"{carrier.portainer.url_from}{PASSWORD_SUFFIX}"
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


def check_no_password(carrier: carrierspec.Carrier) -> None:
    """THE CONDITION THE COMMITTED STATE RESTS ON, held rather than remembered.

    Measured 2026-09-14 against the provider and confirmed 2026-09-15 against a real run: Pulumi
    encrypts only what is MARKED secret, the provider marks its own `apiToken` and `password`, and the
    container resource marks nothing at all. So a carrier created with a root password puts that
    password into a file this kernel then asks the product to commit.

    The manifest has no `password:` key, so this cannot be reached from a document today - it is here
    because the field it guards against is one line away in the provider, and a future carrier growing
    one would otherwise quietly undo the decision that the state may be committed.
    """
    if getattr(carrier.proxmox, "password", ""):
        log.die(f"carrier '{carrier.name}' sets a password on the container. Pulumi encrypts only "
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
    # carries no secret at all.
    portainer_password: "{{{{ lookup('env', 'PORTAINER_PASSWORD') }}}}"

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
      no_log: true

    - name: Which Docker environments does it manage?
      ansible.builtin.uri:
        url: "https://127.0.0.1:{{{{ portainer_port }}}}/api/endpoints"
        headers:
          Authorization: "Bearer {{{{ auth.json.jwt }}}}"
        validate_certs: false
      register: endpoints

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
      when: endpoints.json | length == 0

    - name: What it reports
      ansible.builtin.debug:
        msg: "Portainer {{{{ status.json.Version }}}} on {{{{ ansible_host }}}}:{{{{ portainer_port }}}}, admin ready"
'''


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


def _pulumi(carrier: carrierspec.Carrier, token: str, program: Path, state: Path, hostname: str) -> int:
    """Run `pulumi up` in the pinned image, over the rendered program, against the committed state.

    `PULUMI_BACKEND_URL` RATHER THAN `pulumi login`, measured on 2026-09-14: `pulumi login file://...`
    fails non-interactively with *"PULUMI_ACCESS_TOKEN must be set for login during non-interactive CLI
    sessions"* - the CLI falls back to Pulumi Cloud rather than reading the file URL. The environment
    variable skips the login step entirely, which is what a pipeline needs.
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
        "-e", PULUMI_PASSPHRASE_ENV,
        "-e", "PULUMI_BACKEND_URL=file:///state",
        "-e", f"CARRIER_ENDPOINT={carrier.proxmox.endpoint}",
        "-e", CARRIER_TOKEN_ENV,
        "-e", f"CARRIER_INSECURE={'1' if carrier.proxmox.insecure else '0'}",
        "-e", f"CARRIER_NODE={carrier.proxmox.node}",
        "-e", f"CARRIER_TEMPLATE={carrier.proxmox.template}",
        "-e", f"CARRIER_STORAGE={carrier.proxmox.storage}",
        "-e", f"CARRIER_DISK={carrier.proxmox.disk}",
        "-e", f"CARRIER_MEMORY={carrier.proxmox.memory}",
        "-e", f"CARRIER_CORES={carrier.proxmox.cores}",
        "-e", f"CARRIER_HOSTNAME={hostname}",
        "-e", f"CARRIER_SSH_KEY={carrier.proxmox.ssh_key}",
        docker.pinned_image(PULUMI_IMAGE, "the carrier's Pulumi toolchain"),
        "bash", "-c",
        "pip install -q --root-user-action=ignore -r requirements.txt >/dev/null 2>&1 && "
        f"(pulumi stack init {carrier.name} --non-interactive >/dev/null 2>&1 || "
        f"pulumi stack select {carrier.name} >/dev/null 2>&1) && "
        "pulumi up --yes --non-interactive",
    ]
    return run.stream(argv)


def _ansible(carrier: carrierspec.Carrier, address: str, work: Path, key: Path, port: int) -> int:
    """Run the play in the pinned image, against the carrier's address, with the operator's own key.

    The key is MOUNTED, never copied into the tree and never passed as a value: what the manifest and
    the environment carry is a PATH, which is not a secret.
    """
    (work / "carrier.yml").write_text(
        PLAYBOOK.format(image=PORTAINER_IMAGE, port=port), encoding="utf-8")
    (work / "inventory.ini").write_text(
        f"[carrier]\n{carrier.name} ansible_host={address} ansible_user=root\n", encoding="utf-8")
    argv = [
        "docker", "run", "--rm",
        # The password rides the environment for the same reason, and the playbook reads it with
        # `lookup('env', ...)` rather than carrying a rendered copy of it on disk.
        "-e", f"{carrier.portainer.url_from}{PASSWORD_SUFFIX}",
        "-v", f"{hostpath.translate(work)}:/work",
        "-v", f"{hostpath.translate(key)}:/key:ro", "-w", "/work",
        "-e", "ANSIBLE_HOST_KEY_CHECKING=False",
        docker.pinned_image(ANSIBLE_IMAGE, "the carrier's Ansible toolchain"),
        "ansible-playbook", "-i", "inventory.ini", "carrier.yml", "--private-key", "/key",
    ]
    return run.stream(argv)


def up(environment: str = "") -> int:
    """Make the carrier this environment stands on: the machine, then the Portainer on it.

    IT IS ITS OWN COMMAND AND NOT A PREAMBLE TO `deploy up` (owner decision, 2026-09-14). Two verbs,
    two verdicts: when setting a carrier up fails, it says so instead of taking a deployment down with
    it - and a `deploy up` that created an LXC the first time it ran would be a very large command.

    ONE CARRIER SERVES MANY ENVIRONMENTS, which is why the hostname is the CARRIER's name and not the
    environment's. biz-cockpit's `test` and `prod` share one machine and are separated inside it; an
    implementation that named the machine after the environment would have quietly ruled that out.
    """
    environment_, carrier = _carrier_of(environment)
    check_no_password(carrier)
    # Called for its REFUSALS, not for its value: the password now reaches Ansible through the
    # environment, and what this returns is thrown away. Reading it here all the same is what stops a
    # carrier being built whose Portainer would then lock itself - the check belongs before the machine
    # exists, not after.
    portainer_password(carrier)
    root = context.current().root
    token = _token(carrier)

    missing = [name for name, value in (("endpoint", carrier.proxmox.endpoint),
                                        ("template", carrier.proxmox.template),
                                        ("storage", carrier.proxmox.storage),
                                        ("ssh_key", carrier.proxmox.ssh_key)) if not value]
    if missing:
        log.die(f"carrier '{carrier.name}' declares no {', '.join(missing)} - every one of them is "
                f"configuration and belongs in the manifest")
        return 1

    # THE REFUSAL THAT USED TO ARRIVE THREE MINUTES LATE. Asked here, before a container starts.
    try:
        proxmoxapi.check_storage(carrier.proxmox.endpoint, token, carrier.proxmox.node,
                                 carrier.proxmox.storage, insecure=carrier.proxmox.insecure)
    except proxmoxapi.ProxmoxError as error:
        log.die(f"carrier '{carrier.name}': {error}")
        return 1

    log.info(f"carrier '{carrier.name}' for environment '{environment_.name}' on "
             f"{carrier.proxmox.node} ({carrier.proxmox.kind})")
    program = render(carrier, root)
    rc = _pulumi(carrier, token, program, root / STATE_DIR, carrier.name)
    if rc != 0:
        log.error(f"the carrier was not created (pulumi exited {rc}), so nothing was configured on it")
        return rc

    key = os.environ.get(SSH_KEY_ENV, "")
    if not key:
        log.error(f"{SSH_KEY_ENV} is not set, so the machine exists and nothing could be installed on "
                  f"it. It names the PATH of the private key whose public half the carrier declares")
        return 1
    key_path = Path(key).expanduser()
    if not key_path.is_file():
        log.error(f"{SSH_KEY_ENV} points at {key_path}, which is not a file")
        return 1

    address = _address(carrier, token)
    if not address:
        log.error(f"carrier '{carrier.name}' has no address yet - it is created but its interface has "
                  f"not answered. Run this again in a moment; nothing was lost")
        return 1
    return _ansible(carrier, address, program, key_path, PORTAINER_PORT)


def _address(carrier: carrierspec.Carrier, token: str) -> str:
    """The carrier's own IPv4, asked of Proxmox rather than guessed from a lease file.

    A container on DHCP has no address the manifest could carry, and the node knows it - which is the
    one piece of runtime truth this command needs and the only reason it asks twice.
    """
    try:
        vmid = proxmoxapi.container_id(carrier.proxmox.endpoint, token, carrier.proxmox.node,
                                       carrier.name, insecure=carrier.proxmox.insecure)
        if not vmid:
            log.error(f"no container named '{carrier.name}' on {carrier.proxmox.node}, though the "
                      f"carrier run reported success - which is a disagreement worth reading before "
                      f"running anything again")
            return ""
        return proxmoxapi.address(carrier.proxmox.endpoint, token, carrier.proxmox.node, vmid,
                                  insecure=carrier.proxmox.insecure)
    except proxmoxapi.ProxmoxError as error:
        log.error(f"carrier '{carrier.name}': {error}")
        return ""
