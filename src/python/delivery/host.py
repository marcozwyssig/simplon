"""The Linux-vs-macOS execution router. On Linux the lab runs natively; on macOS it runs inside the
Colima VM, so commands that touch the lab (docker, a shell in the VM) must be prefixed with
`colima ssh --`. It is the ONLY module that knows about Colima, so parsers/status logic stay
host-agnostic and testable. The OS is self-detected via the stdlib `platform`, or injected via os_name.

It also answers "is the lab host usable at all?" (netctl#1031), and answers it from the DOCKER SOCKET
rather than from colima's status record. On the netctl#1002 incident that record read `Stopped` while 43
lab containers were running and the daemon was healthy, and every command that gated on it believed the
record. `colima ssh` reads the same record, so on macOS the whole routing goes down with it. The socket
cannot be fooled the same way: it either answers or the daemon is really gone.
"""
from __future__ import annotations

import os
import platform
import socket
from dataclasses import dataclass
from enum import Enum

from delivery.run import Result, run

# The docker socket colima publishes on the HOST filesystem, per profile - reachable WITHOUT the
# `colima ssh` hop, which is the entire point.
COLIMA_SOCKET = "~/.colima/{profile}/docker.sock"
DEFAULT_SOCKET = "/var/run/docker.sock"
# The daemon's cheapest endpoint: no auth, no payload, answers `200 OK` iff the engine is serving.
_PING = b"GET /_ping HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n"
_PING_TIMEOUT_S = 2.0
_STATUS_LINE_MAX = 256   # read until the status line is complete, never the whole response


class HostReach(str, Enum):
    """How the lab host answered a probe. Three states, because two of them are routinely confused:

      ROUTED       the routed command worked - the host is alive AND commands can be run on it;
      SOCKET_ONLY  the routing refused, but the docker socket answers: the daemon is alive and the
                   STATUS RECORD is stale (netctl#1002). Not the same fault as a stopped VM, and not the
                   same fix - `colima start` on a live VM makes it worse, `colima restart` is the cure;
      UNREACHABLE  nothing answered: the host really is down.
    """

    ROUTED = "routed"
    SOCKET_ONLY = "socket-only"
    UNREACHABLE = "unreachable"

    @property
    def reachable(self) -> bool:
        """True iff the lab host's docker daemon is ALIVE. SOCKET_ONLY counts: a stale status record is
        not an outage, which is the whole distinction netctl#1031 exists to draw."""
        return self is not HostReach.UNREACHABLE

    @property
    def actionable(self) -> bool:
        """True iff commands can actually be RUN on the lab host through the normal routing. SOCKET_ONLY
        does NOT count: the daemon answers, but `colima ssh` (and with it containerlab, the in-VM shell,
        every bridge operation) still refuses, so a caller that acts on it does damage while believing it
        succeeded - the netctl#1002 failure mode."""
        return self is HostReach.ROUTED


@dataclass(frozen=True)
class HostProbe:
    """What `Host.probe` established: the classification, the socket path it asked, and the operator
    facing cause when the host is anything but ROUTED (empty when it is)."""

    reach: HostReach
    socket_path: str
    cause: str


def docker_socket_path(*, darwin: bool, environ: dict | None = None) -> str:
    """The docker socket to open on THIS host: an explicit unix:// DOCKER_HOST wins, then the colima
    profile socket on macOS, then the default daemon socket. Empty for a non-unix DOCKER_HOST (tcp/ssh -
    nothing local to open). PURE (the environment is injectable), so the resolution is unit-tested with
    no host at all."""
    env = os.environ if environ is None else environ
    endpoint = env.get("DOCKER_HOST", "")
    if endpoint.startswith("unix://"):
        return endpoint.removeprefix("unix://")
    if endpoint:
        return ""
    if darwin:
        return os.path.expanduser(COLIMA_SOCKET.format(profile=env.get("COLIMA_PROFILE") or "default"))
    return DEFAULT_SOCKET


def socket_answers(path: str, timeout: float = _PING_TIMEOUT_S) -> bool:
    """Open the docker socket and ask the daemon to /_ping. The ONE I/O seam of the probe, kept to a raw
    AF_UNIX connect on purpose: it depends on neither the docker CLI, nor a docker context, nor colima, so
    nothing in the chain can report a state the daemon does not actually have. False on any refusal, and
    on a missing/unopenable path."""
    if not path:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path)
            sock.sendall(_PING)
            head = b""
            while b"\r\n" not in head and len(head) < _STATUS_LINE_MAX:
                block = sock.recv(64)
                if not block:
                    break
                head += block
    except OSError:
        return False
    status = head.split(b"\r\n", 1)[0].split()
    return len(status) > 1 and status[1] == b"200"


def classify_reachability(*, routed_ok: bool, socket_ok: bool) -> HostReach:
    """PURE: the lab-host classification. The routed command is the fast path (it proves both facts at
    once); when it fails, the DOCKER SOCKET decides - never colima's status record, and never `colima
    list` output, both of which read `Stopped` on a live VM (netctl#1002)."""
    if routed_ok:
        return HostReach.ROUTED
    return HostReach.SOCKET_ONLY if socket_ok else HostReach.UNREACHABLE


def probe_cause(reach: HostReach, routed_cause: str, socket_path: str) -> str:
    """PURE: the operator-facing diagnosis for a probe, naming the fault AND the fix that matches it. The
    two non-ROUTED cases get DIFFERENT remediation on purpose: restarting a live VM is not the same move
    as starting a stopped one."""
    if reach is HostReach.ROUTED:
        return ""
    if reach is HostReach.SOCKET_ONLY:
        return (f"the lab host's docker daemon ANSWERS on {socket_path}, but the routed command failed "
                f"({routed_cause}): the VM is alive and its status record is stale, not the other way "
                f"round. Restore the hop with `colima restart` - do NOT `colima start` a running VM")
    return (f"{routed_cause}; the docker socket {socket_path or '(none resolvable)'} did not answer "
            f"either, so the daemon really is down (on macOS: colima start)")


class Host:
    """Executes commands where the lab actually lives: directly on Linux, via `colima ssh` on macOS."""

    def __init__(self, os_name: str | None = None) -> None:
        self._darwin = (os_name or platform.system()) == "Darwin"

    @property
    def is_darwin(self) -> bool:
        """True when the lab lives inside a macOS Colima VM (commands are `colima ssh`-wrapped), False
        when it runs natively on Linux. Lets a lab-lifecycle caller pick the host-vs-VM invocation shape
        (e.g. `sudo` vs `$SUDO`) off the SAME injected Host the routing already keys on, instead of
        re-detecting the platform independently."""
        return self._darwin

    def sh(self, script: str, *, capture: bool = True) -> Result:
        """Run a shell snippet in the host/VM context: `bash -lc <script>` on Linux, the same wrapped in
        `colima ssh --` on macOS."""
        if self._darwin:
            return run(["colima", "ssh", "--", "bash", "-lc", script], capture=capture)
        return run(["bash", "-lc", script], capture=capture)

    def docker(self, *args: str, capture: bool = True) -> Result:
        """Run a docker command against the lab's daemon: local on Linux, via `colima ssh` on macOS."""
        if self._darwin:
            return run(["colima", "ssh", "--", "docker", *args], capture=capture)
        return run(["docker", *args], capture=capture)

    def probe(self) -> HostProbe:
        """Is this lab host usable, and can commands actually be run on it (netctl#1031)? Read-only by
        construction: a `docker ps -q` through the SAME routing seam every lab command uses, and, only
        when that fails, one AF_UNIX /_ping at the daemon socket. So a healthy host costs exactly one
        docker call and the extra probe runs precisely when the answer is in doubt.

        The socket is the oracle for "alive", never colima's status record: this probe issues no `colima
        status` and no `colima list`, because those read the record that goes stale (netctl#1002)."""
        res = self.docker("ps", "-q")
        lines = [ln.strip() for ln in ((res.err or "") + "\n" + (res.out or "")).splitlines() if ln.strip()]
        routed_cause = "" if res.ok else (
            lines[-1] if lines else f"docker on the lab host exited {res.rc} without a message")
        path = docker_socket_path(darwin=self._darwin)
        reach = classify_reachability(routed_ok=res.ok, socket_ok=not res.ok and socket_answers(path))
        return HostProbe(reach=reach, socket_path=path,
                         cause=probe_cause(reach, routed_cause, path))

    def container_logs(self, name: str, tail: int = 400) -> str:
        """The last `tail` lines of a container's combined log (stdout+stderr), or '' if unavailable."""
        res = self.docker("logs", "--tail", str(tail), name, capture=True)
        return (res.out or "") + (res.err or "")

    def _wrap(self, argv: list[str]) -> list[str]:
        """Prefix an argv with `colima ssh --` on macOS so it runs inside the VM; pass through on Linux."""
        return ["colima", "ssh", "--", *argv] if self._darwin else argv

    def logs(self, container: str, tail: str, follow: bool) -> Result:
        """Stream a container's logs. follow inherits the terminal (capture=False) so `-f` tails live
        until Ctrl-C."""
        argv = ["docker", "logs", "--tail", tail, *(["-f"] if follow else []), container]
        return run(self._wrap(argv), capture=not follow)

    def exec_shell(self, container: str) -> Result:
        """Open an interactive shell in a container, preferring bash, falling back to sh. Inherits the
        terminal (TTY) - this is an interactive session, not captured."""
        snippet = 'exec "$(command -v bash || command -v sh)"'
        argv = ["docker", "exec", "-it", container, "sh", "-c", snippet]
        return run(self._wrap(argv), capture=False)

    def ssh_device(self, ip: str) -> Result:
        """SSH into a managed device as admin, host-key checks off (lab). Interactive."""
        argv = ["ssh", "-t", "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null", f"admin@{ip}"]
        return run(self._wrap(argv), capture=False)
