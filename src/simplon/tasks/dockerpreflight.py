"""`support:docker-preflight` (si#564): does docker answer on this host, and - with `editor: devcontainer` -
will VS Code's Dev Containers extension find it?

Two questions, kept apart because one used to stop the other. firn's own preflight (firn#287) refused
`deploy devcontainer` on a Mac with Colima whenever /var/run/docker.sock was missing, although docker
answered on the active context, and its only way out was a `sudo ln -sf` that macOS's /var/run does not
keep across a reboot. Here a missing /var/run/docker.sock is never red by itself.

WHAT THE EXTENSION DOES, read from its code (ms-vscode-remote.remote-containers 0.471.0), not run on a Mac:
"Check Docker is running" runs `docker version` and opens no socket. It picks the context from the
settings `containers.environment.DOCKER_CONTEXT`, `docker.environment.DOCKER_CONTEXT` and
`docker.context`, then the env DOCKER_CONTEXT, then `docker context ls`; a `context ls` that throws
becomes `default`. `docker.host` is read only when the context came out `default`.
`dev.containers.dockerSocketPath` is not read by that check at all. And VS Code started from the Dock
inherits no shell export. So the editor part asks docker WITHOUT DOCKER_HOST and DOCKER_CONTEXT, and the
one way out it names is `"docker.context": "<name>"` in the VS Code user settings: read first, kept
across a reboot, no path in it.

This runs no `sudo` and writes nothing into the editor's configuration: it says, the user decides.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from simplon.adapters import docker, host
from simplon.kernel import log
from simplon.kernel.run import run
from simplon.tasks import imagefile

#: The editors the `editor` parameter knows; absent means no editor check.
EDITORS = ("devcontainer",)
_OVERRIDES = ("DOCKER_HOST", "DOCKER_CONTEXT")
#: `docker version` asks the daemon, and over an ssh:// context a silent host can hold it for good. A run
#: that hangs is neither green nor red, so the question has a limit and running out of it is red.
VERSION_TIMEOUT_S = 30.0


def preflight(editor: str = "") -> int:
    """Check that docker answers on this host's active context; with `editor: devcontainer`, also say
    which VS Code setting lets the Dev Containers extension find it. Red only when docker does not answer."""
    if editor and editor not in EDITORS:
        log.error(f"editor {editor!r} is not one this check knows; it knows {', '.join(EDITORS)} "
                  "(or leave it out to check docker alone)")
        return 1
    if shutil.which("docker") is None:
        log.error("no `docker` on PATH: install docker, or Colima on macOS (https://github.com/abiosoft/colima)")
        return 1
    try:
        answered = run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=VERSION_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.error(f"docker did not answer within {VERSION_TIMEOUT_S:g} s; check that its daemon runs and "
                  "that `docker context ls` marks one this host can reach")
        return 1
    if not answered.ok:
        log.error("no docker daemon answers on this host:")
        for line in (answered.err or answered.out or "").strip().splitlines():
            log.error(f"    {line}")
        log.error("start it (`colima start` on macOS, `systemctl start docker` on Linux, or Docker Desktop), "
                  "and check that `docker context ls` marks the one that runs")
        return 1

    terminal = host.context_endpoint()
    version = answered.out.strip()
    if terminal is None:
        log.warn(f"docker {version} answers, but docker could not name the context it uses "
                 "(`docker context inspect` failed), so nothing is said about any editor")
        return 0
    log.ok(f"docker {version} answers on context {terminal.name!r} ({terminal.endpoint})")
    if not editor:
        return 0
    return _devcontainer(terminal)


#: What the CI probe starts (si#623): the kernel's own pinned busybox, which `test:file` already pulls, so a
#: runner holds one small image for both and the probe adds no second pin to keep current.
PROBE_IMAGE = imagefile.FILE_TEST_IMAGE
#: The probe may have to pull PROBE_IMAGE first. Bounded, because a run that hangs is no verdict.
PROBE_TIMEOUT_S = 120.0


def ci_preflight() -> int:
    """`support:ci-docker-preflight` (si#623): run a container from where the kernel uses docker - inside the
    kernel container through the mounted socket, or on the host - and on a refusal name the facts.

    PRESENCE IS NOT CAPABILITY. `docker version` answers on a socket the caller may still not be allowed to
    start a container through, and `ci-disk-preflight` was green on ghr-8 on 2026-11-11 while every docker
    call after it was refused. So green comes from a container that ran, and nothing less.
    """
    if shutil.which("docker") is None:
        log.error("no `docker` on PATH, so no job step here can start a container")
        return 1
    argv = ["docker", "run", "--rm", "--network", "none", PROBE_IMAGE, "true"]
    try:
        result = run(argv, timeout=PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.error(f"`docker run {PROBE_IMAGE}` did not finish within {PROBE_TIMEOUT_S:g} s; the daemon or the "
                  "registry is not answering")
        return 1
    where = ("inside the kernel container" if os.environ.get("DELIVERY_ROUTE") == "inside"
             else "on this host")
    if result.ok:
        log.ok(f"docker ran a container {where} ({PROBE_IMAGE})")
        return 0
    log.error(f"docker could not run a container {where} (`{' '.join(argv)}`, rc {result.rc}):")
    for line in (result.err or result.out or "").strip().splitlines():
        log.error(f"    {line}")
    for line in docker.socket_access_report():
        log.error(f"  {line}")
    return 1


def _devcontainer(terminal: host.DockerContext) -> int:
    """The editor half: what the Dev Containers extension will see, asked the way it asks. Always 0."""
    if os.name == "nt":
        log.info("on Windows the extension reaches docker through a named pipe; that is not checked here "
                 "(unmeasured)")
        return 0
    overridden = [name for name in _OVERRIDES if os.environ.get(name)]
    if overridden:
        log.warn(f"this terminal sets {' and '.join(overridden)}; VS Code started from the Dock does not see "
                 "it, so what follows is what the extension sees without it")
    seen = host.context_endpoint(host.without_docker_overrides())
    if seen is None:
        advice = (f"add {_setting('docker.context', terminal.name)} to the VS Code user settings"
                  if terminal.name != "default" else "check `docker context ls`")
        log.warn("docker could not name the context VS Code would get, so the Dev Containers extension may "
                 f"fall back to `default`; {advice}")
        return 0
    if seen.name != "default":
        log.warn(f"the Dev Containers extension falls back to `default` when its `docker context ls` fails "
                 f"(firn#287); add {_setting('docker.context', seen.name)} to the VS Code user settings, "
                 "which it reads first")
        return 0
    if _local_socket_exists(seen.endpoint):
        log.ok(f"VS Code's Dev Containers extension finds docker on the default context ({seen.endpoint})")
        return 0
    if terminal.name != "default":
        log.warn(f"VS Code would use the default context, and nothing listens on {seen.endpoint}; add "
                 f"{_setting('docker.context', terminal.name)} to the VS Code user settings")
    elif _local_socket_exists(terminal.endpoint):
        log.warn(f"VS Code would use the default context, and nothing listens on {seen.endpoint}; add "
                 f"{_setting('docker.host', terminal.endpoint)} to the VS Code user settings")
    else:
        log.warn(f"VS Code would use the default context, and nothing listens on {seen.endpoint}; this "
                 f"terminal reaches docker on {terminal.endpoint}, which no VS Code setting can name as a "
                 "local socket - check `docker context ls`")
    return 0


def _setting(key: str, value: str) -> str:
    return f'"{key}": "{value}"'


def _local_socket_exists(endpoint: str) -> bool:
    return endpoint.startswith("unix://") and Path(endpoint.removeprefix("unix://")).exists()
