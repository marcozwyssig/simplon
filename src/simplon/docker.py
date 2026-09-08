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
`simplon.context`, so a product reuses this gate unchanged - "gleiche Maschine, anderer Katalog". Two do
today, and the pair is measured rather than assumed (#51): netctl (`orchestrator.lab`,
`orchestrator.tooling`) and asbundle (`orchestrator.container`).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import tarfile
import urllib.request
from pathlib import Path

from simplon import context
from simplon import log
from simplon import tools
from simplon.run import run

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
    """Product-owned tool directory the bootstrap installs into (wiped by `clean` with build/).

    The convention itself lives in simplon.tools, shared with the oras gate: two bootstraps answering
    "where does a fetched binary go" separately is one of them drifting later.
    """
    return tools.bin_dir()


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


def _invoking_user() -> str:
    """The account this process runs as - the one a docker group membership has to name."""
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def _join_docker_group(pfx: list) -> None:
    """Put the invoking user in the `docker` group, which is what OWNS the socket (root:docker 660).

    This is the DURABLE half of docker access, and si#87 moved it here from the failure path. It belongs
    to the install for two reasons. The install is the one moment privilege is known to be present and
    the state is being created from scratch; and `get.docker.com` creates the group but puts nobody in
    it, so without this step a fresh host has an EMPTY docker group and every non-root caller is locked
    out. Measured on three CI hosts: `getent group docker` -> `docker:x:991:`.

    root is skipped deliberately: it reaches the socket by being root, and the group exists precisely
    for those who are not.
    """
    run([*pfx, "groupadd", "-f", "docker"])
    user = _invoking_user()
    if user == "root":
        return
    run([*pfx, "usermod", "-aG", "docker", user])
    log.info(f"added {user} to the docker group; a LONG-LIVED service (a CI runner agent) must be "
             "restarted before it takes effect - a process inherits its groups at start")


def _install_engine(pfx: list) -> None:
    """Install the docker ENGINE via the official installer (#488; the same pipe-into-shell pattern
    as hostsetup._install_linux, never $(...)), enable+start the service, and establish the group
    membership that makes the socket reachable afterwards (si#87). Needs root/sudo."""
    log.info("docker missing; installing the engine via get.docker.com (root/sudo available)")
    shell = "sudo -E sh" if pfx else "sh"
    run(["bash", "-c", f"curl -fsSL https://get.docker.com | {shell}"], capture=False)
    run([*pfx, "systemctl", "enable", "--now", "docker"])
    _join_docker_group(pfx)


def _grant_socket_access(pfx: list) -> None:
    """Make the socket usable by THIS process, which cannot change its own groups any more (#488).

    A BRIDGE, not the fix - si#87 corrected the emphasis, because the emphasis was doing damage. The
    durable half is the group membership, established at install time by `_join_docker_group`; the ACL
    below (chmod 666 where setfacl is missing) only covers the running process, and the socket is
    recreated with default modes on the next daemon restart. Because the ACL works INSTANTLY, it used to
    hide the fact that the membership had not reached a long-lived caller at all: three CI hosts ran
    green for months on a permissive socket left behind by an earlier run, then failed at three
    unrelated moments when their daemons restarted.

    The membership is (re)established here too, so a host whose engine predates si#87 still gets it.
    """
    sock = _socket_path()
    if sock is None:
        return
    _join_docker_group(pfx)
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
            tools.prepend_to_path(cli.parent)
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


#: A docker tag: what may follow the ':' in an image reference. Used to reject the EMPTY tag ('hugo:',
#: 'hugo::'), which reads as pinned to a careless eye and is not.
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}\Z")
#: A content digest ('sha256:<hex>'): the strongest pin there is.
_DIGEST_RE = re.compile(r"[A-Za-z0-9]+(?:[.+_-][A-Za-z0-9]+)*:[A-Fa-f0-9]{32,}\Z")


def pinned_image(image: str, where: str, *, hint: str = "") -> str:
    """Refuse an image reference that does not name a version, and hand back the reference when it does.

    THE RULE. A build that renders something different depending on when it ran is not a build. An
    untagged reference means ':latest', and ':latest' means the same command runs something else
    tomorrow - so an untagged reference, an empty tag ('hugo:', 'hugo::', which read as pinned to a
    careless eye) and the literal 'latest' are all refused. A tag or a digest passes; a digest is the
    strongest form of the same statement.

    WHY IT LIVES HERE, in the module about running containers, rather than beside any one caller
    (si#47). It started in `tasks.site`, where it refused a PRODUCT's manifest image with a paragraph of
    reasons - while the kernel itself handed docker two references that would not have survived it, and
    `tasks.docs` demanded only that a tag be DECLARED, letting `doctoolchain_version: latest` through.
    A rule the kernel argues for and does not keep is a rule the next reader believes less, whatever the
    risk of the particular image. So there is now one gate and every image goes through it: the two the
    manifest declares (`site:` image, `doctoolchain_version`) and the ones the kernel names ITSELF, which
    are validated where they are declared, at import. That is the shape si#34 used for coordinate
    placement - the check runs over the MERGED tree, so the catalogue's own placements are held to it too.

    The registry is split off by docker's OWN rule, which needs BOTH halves: a first component is a host
    when it carries a '.' or a ':' AND a '/' follows it, or when it is 'localhost'. That is what keeps a
    private registry with a port (`registry.example:5000/hugo:0.148.2`) from being read as a tagged image
    - and, just as important, what keeps `my.image:1.0` from being read as a registry. Without a slash
    there is no registry, dot or no dot; docker reads such a reference as an image with a tag, and so does
    this. `registry.example:5000` alone therefore passes as image `registry.example` tag `5000`, which is
    what docker itself would do with it: nothing here can tell that port from a version without guessing,
    and guessing costs valid references.

    `hint` is the caller's, because the caller knows what the reader has to EDIT. A manifest key that
    holds a whole reference wants the default; one that holds a bare tag - `doctoolchain_version` - does
    not, and telling its author to write 'hugomods/hugo:exts-0.148.2' into it would be a message that
    sends them the wrong way with total confidence.
    """
    hint = hint or "pin it as '<image>:<tag>' (e.g. 'hugomods/hugo:exts-0.148.2'), or by digest"
    name, at, digest = image.partition("@")
    if at:
        if not name or not _DIGEST_RE.match(digest):
            raise ValueError(f"{where}: 'image' carries a broken digest in '{image}'; {hint}")
        return image
    parts = image.split("/")
    # A registry needs a '/' after it - `len(parts) > 1` IS that condition, and it is the half that stops
    # `my.image:1.0` from being mistaken for a host.
    registry = len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost")
    remainder = "/".join(parts[1:]) if registry else image
    repo, colon, tag = remainder.rpartition(":")
    if not colon:
        raise ValueError(f"{where}: 'image' must pin a version ('<image>:<tag>'), got '{image}' "
                         f"- an untagged image means ':latest', which moves under the build; {hint}")
    if not repo or not _TAG_RE.match(tag):
        raise ValueError(f"{where}: 'image' has no usable tag in '{image}'; {hint}")
    if tag == "latest":
        raise ValueError(f"{where}: 'image' must pin a version, not the moving tag 'latest' "
                         f"(got '{image}') - a build whose output depends on when it ran is not a "
                         f"build; {hint}")
    return image


def user_args() -> list[str]:
    """``--user uid:gid`` for a container that WRITES into a bind-mounted directory, and an empty list
    on a host with no uid concept (Windows, where the mount carries no ownership to get wrong).

    THE RULE, LEARNED TWICE. A bind mount hands the container the host's inodes, so whatever uid the
    image happens to run as is the uid that ends up owning the output. Both directions hurt, and both
    have been measured rather than assumed:

      - an image running as a NON-ROOT uid that is not the caller's cannot create anything in the
        mounted directory at all. `frankescobar/allure-docker-service` runs as uid 1000 against a host
        uid of 5015237, and allure died with `java.nio.file.AccessDeniedException` (#6, fixed in 0.1.7);
      - an image running as ROOT succeeds and leaves ROOT-OWNED files behind, which the caller then
        cannot delete. Measured with `hugomods/hugo` (its default user is uid 0): the run wrote
        `build/website/index.html` as `0:0`, the caller's `rm -rf build` came back `Permission denied`,
        and even the SOURCE tree kept a root-owned `.hugo_build.lock` - enough to make the next run fail
        with `failed to acquire a build lock` even when that one passed `--user` correctly.

    Running the container AS THE CALLER is the fix that leaves the mount as it is: the files it writes
    are the ones the caller can read, wipe and archive afterwards. It lives here rather than beside
    either caller because a convention restated in two modules is a convention that drifts in one of
    them - the same reason `tools.bin_dir` exists.
    """
    if not hasattr(os, "getuid"):        # Windows: no uid mapping to hand over
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


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
