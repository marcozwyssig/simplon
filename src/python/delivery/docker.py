"""Docker CLI gate + opt-in static bootstrap (netctl#477, kernel-extracted netctl#649).

Every docker-consuming command funnels through ensure_docker(): with docker on PATH it is a no-op;
without it, it dies naming the fixes - UNLESS DELIVERY_DOCKER_BOOTSTRAP=1, which fetches the pinned
STATIC docker CLI (client binary only, never the engine, no root needed) into <root>/build/tools/bin
and prepends it to this process' PATH. Built for ephemeral CI runner containers running
docker-outside-of-docker: the host mounts /var/run/docker.sock, the container only needs the client.

The bootstrap is an explicit opt-in flag ON PURPOSE (default off): host mutations belong in the
product's `install` command, which provisions the full engine on a real host. A product's ci.yml sets
the flag for its self-hosted runner, where the socket-mount shape is intended.

Product-agnostic: the repo root and the product name (for the install hint) come from the registered
`delivery.context`, so both netctl and infractl reuse this gate unchanged - "gleiche Maschine, anderer
Katalog".
"""
from __future__ import annotations

import os
import platform
import shutil
import tarfile
import urllib.request
from pathlib import Path

from delivery import context
from delivery import log
from delivery.run import run

# Pinned static-CLI release (download.docker.com/linux/static/stable); bump deliberately.
DOCKER_CLI_VERSION = "29.6.1"
# platform.machine() spellings -> docker's static-download arch directory names.
_ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
# Kernel-namespaced opt-in toggle (the DELIVERY_* namespace, netctl#592); a product's ci.yml sets it.
DOCKER_BOOTSTRAP_ENV = "DELIVERY_DOCKER_BOOTSTRAP"


def bootstrap_enabled() -> bool:
    """True iff the operator opted into the static-CLI bootstrap (DELIVERY_DOCKER_BOOTSTRAP=1)."""
    return os.environ.get(DOCKER_BOOTSTRAP_ENV, "0") == "1"


def static_cli_url(machine: str, version: str = DOCKER_CLI_VERSION) -> str:
    """The pinned static-bundle URL for a platform.machine() string. Pure (unit-tested); dies on an
    architecture docker does not publish static binaries for."""
    arch = _ARCHES.get(machine.lower())
    if arch is None:
        log.die(f"docker bootstrap: no static docker CLI for architecture '{machine}'")
    return f"https://download.docker.com/linux/static/stable/{arch}/docker-{version}.tgz"


def tools_bin() -> Path:
    """Product-owned tool directory the bootstrap installs into (wiped by `clean` with build/). The repo
    root comes from the registered product context, so the layout convention stays product-agnostic."""
    return context.current().root / "build" / "tools" / "bin"


def _fetch_static_cli(dest: Path) -> None:
    """Download the pinned bundle and extract ONLY the client binary to dest (the bundle also carries
    the engine binaries, which are useless in a container and stay out of the tool dir)."""
    url = static_cli_url(platform.machine())
    log.info(f"docker missing; fetching the static docker CLI {DOCKER_CLI_VERSION} "
             f"(client only, no root; the daemon must come from the host's socket)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    bundle = dest.parent / "docker.tgz.part"
    urllib.request.urlretrieve(url, bundle)
    try:
        with tarfile.open(bundle) as tar:
            member = tar.getmember("docker/docker")
            member.name = dest.name
            tar.extract(member, dest.parent)
    finally:
        bundle.unlink(missing_ok=True)
    dest.chmod(0o755)


def _daemon_reachable() -> bool:
    """One cheap `docker version` probe; separated for unit-testability."""
    return run(["docker", "version"]).ok


def _sudo_prefix() -> list | None:
    """The privilege prefix for host mutations: [] when already root, ["sudo", "-n"] when
    passwordless sudo answers, None when this process has no way to escalate."""
    if os.getuid() == 0:
        return []
    if run(["sudo", "-n", "true"]).ok:
        return ["sudo", "-n"]
    return None


def _install_engine(pfx: list) -> None:
    """Install the docker ENGINE via the official installer (#488; the same pipe-into-shell pattern
    as hostsetup._install_linux, never $(...)) and enable+start the service. Needs root/sudo."""
    log.info("docker missing; installing the engine via get.docker.com (root/sudo available)")
    shell = "sudo -E sh" if pfx else "sh"
    run(["bash", "-c", f"curl -fsSL https://get.docker.com | {shell}"], capture=False)
    run([*pfx, "systemctl", "enable", "--now", "docker"])


def _grant_socket_access(pfx: list) -> None:
    """Make the daemon socket usable by the CURRENT process (#488): usermod covers future sessions,
    but a running process cannot pick up a new group without re-login, so grant an ACL on the socket
    now (chmod 666 as the fallback where setfacl is not installed - acceptable on a dedicated CI
    runner, and the socket is recreated with default modes on the next daemon restart)."""
    import pwd
    sock = _socket_path()
    if sock is None:
        return
    run([*pfx, "usermod", "-aG", "docker", pwd.getpwuid(os.getuid()).pw_name])
    if not run([*pfx, "setfacl", "--modify", f"user:{os.getuid()}:rw", str(sock)]).ok:
        log.warn(f"setfacl unavailable; falling back to chmod 666 on {sock}")
        run([*pfx, "chmod", "666", str(sock)])


def ensure_docker() -> None:
    """The gate every docker-consuming command calls instead of a bare which() check. Without the
    bootstrap flag: no-op when docker is on PATH, die naming the fixes otherwise (unchanged for dev
    hosts - on macOS the daemon may legitimately come up later via colima). With
    DELIVERY_DOCKER_BOOTSTRAP=1 on Linux the gate makes docker WORK end to end (#477/#488): install the
    engine when root/sudo is available, else fetch the static CLI; then verify the daemon and
    self-fix what privileges allow (start the service, grant socket access)."""
    bootstrap = bootstrap_enabled() and platform.system() == "Linux"
    if shutil.which("docker") and not bootstrap:
        return
    if not shutil.which("docker"):
        if not bootstrap:
            name = context.current().name
            log.die(f"missing required tool: docker (./{name}.sh install provisions it; on a CI "
                    f"runner set {DOCKER_BOOTSTRAP_ENV}=1 to let {name} provision docker itself)")
        pfx = _sudo_prefix()
        if pfx is not None:
            _install_engine(pfx)
        if not shutil.which("docker"):
            # Unprivileged (or the engine install failed): the static CLIENT still enables the
            # docker-outside-of-docker shape where a daemon socket is provided by the host.
            cli = tools_bin() / "docker"
            if not cli.is_file():
                _fetch_static_cli(cli)
            os.environ["PATH"] = f"{cli.parent}{os.pathsep}{os.environ.get('PATH', '')}"
        if shutil.which("docker") is None:
            log.die("docker bootstrap failed: no usable docker CLI after engine install / static fetch")
    # Bootstrap mode verifies the daemon end to end and self-fixes what privileges allow.
    if _daemon_reachable():
        return
    pfx = _sudo_prefix()
    if pfx is not None:
        run([*pfx, "systemctl", "enable", "--now", "docker"])
        sock = _socket_path()
        if sock is not None and sock.exists() and not os.access(sock, os.W_OK):
            _grant_socket_access(pfx)
        if _daemon_reachable():
            return
    name = context.current().name
    log.die(f"docker CLI present but no daemon is reachable (socket: {_socket_state()}). Install the "
            f"engine (./{name}.sh install / get.docker.com, or give the runner user NOPASSWD sudo so "
            f"{name} can), or on a container runner mount the host socket: "
            "-v /var/run/docker.sock:/var/run/docker.sock (plus --group-add its gid)")


def _socket_path() -> Path | None:
    """The unix socket the docker CLI will talk to: DOCKER_HOST's unix path when set, the default
    socket otherwise, None for a non-unix DOCKER_HOST (tcp/ssh - nothing local to inspect)."""
    host = os.environ.get("DOCKER_HOST", "")
    if host and not host.startswith("unix://"):
        return None
    return Path(host.removeprefix("unix://")) if host else Path("/var/run/docker.sock")


def _socket_state() -> str:
    """Name the exact docker-socket gap for the daemon-unreachable die: not mounted at all, mounted
    but not writable by this uid (the --group-add gap), or writable yet dead."""
    path = _socket_path()
    if path is None:
        return f"DOCKER_HOST={os.environ.get('DOCKER_HOST', '')} (non-unix, cannot inspect)"
    if not path.exists():
        return f"{path} NOT MOUNTED"
    if not os.access(path, os.W_OK):
        return f"{path} mounted but NOT WRITABLE by uid {os.getuid()} (missing --group-add)"
    return f"{path} mounted and writable, but the daemon did not answer"
