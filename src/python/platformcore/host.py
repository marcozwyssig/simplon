"""The Linux-vs-macOS execution router. On Linux the lab runs natively; on macOS it runs inside the
Colima VM, so commands that touch the lab (docker, a shell in the VM) must be prefixed with
`colima ssh --`. It is the ONLY module that knows about Colima, so parsers/status logic stay
host-agnostic and testable. The OS is self-detected via the stdlib `platform`, or injected via os_name.
"""
from __future__ import annotations

import platform

from platformcore.run import Result, run


class Host:
    """Executes commands where the lab actually lives: directly on Linux, via `colima ssh` on macOS."""

    def __init__(self, os_name: str | None = None) -> None:
        self._darwin = (os_name or platform.system()) == "Darwin"

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
