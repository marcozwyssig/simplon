"""Keep the host awake for the duration of a long lab/build run (netctl#546, extracted to the delivery
kernel in netctl#592 Train B).

A full `build`/`up`/`seed`/`monitor accept` cycle runs for tens of minutes with no keypress; on a laptop
the host then idle-sleeps mid-run, dropping the Colima VM / SSH channel and wedging the pipeline. This
wraps those long commands in a context manager that inhibits idle sleep while they run and lets the host
sleep normally again on exit. Product-agnostic: any *ctl orchestrator with multi-minute commands reuses it.

The OS decision is a PURE helper (`_keep_awake_argv`) so it is unit-tested without spawning anything: on
macOS it yields `caffeinate -dimsu` (prevent display/idle/system/disk sleep + keep-awake on AC and
battery), on Linux/other it yields a `systemd-inhibit --what=idle` wrapper around a blocking `sleep`, and
where neither applies it yields None (no-op). The context manager is STRICTLY best-effort: a missing or
failing inhibitor logs a WARNING and continues - keeping the host awake is a convenience, never a reason
to fail the actual run.
"""
from __future__ import annotations

import contextlib
import platform
import subprocess
from collections.abc import Iterator

from delivery import log

__all__ = ["keep_awake"]


def _keep_awake_argv(os_name: str) -> list[str] | None:
    """PURE: the argv of a long-lived process that inhibits host idle-sleep on `os_name`, or None when
    there is nothing sensible to spawn.

    macOS (`Darwin`) -> ``caffeinate -dimsu``: -d display, -i idle system sleep, -m disk idle, -s system
    sleep on AC, -u declare user active. It runs until killed, which is exactly the enter/exit lifetime.
    Linux -> ``systemd-inhibit --what=idle sleep infinity``: holds an idle inhibitor lock for its own
    lifetime; killed on exit. Anything else -> None (no-op)."""
    if os_name == "Darwin":
        return ["caffeinate", "-dimsu"]
    if os_name == "Linux":
        return ["systemd-inhibit", "--what=idle", "--why=netctl lab/build run", "sleep", "infinity"]
    return None


@contextlib.contextmanager
def keep_awake() -> Iterator[None]:
    """Inhibit host idle-sleep for the duration of the `with` block; restore normal sleep on exit.

    Best-effort by contract: if the platform has no inhibitor, or spawning it fails (binary missing,
    permission), it logs a WARNING and yields anyway - a long run never fails because the host could not
    be kept awake. The inhibitor process is always terminated in the `finally`, so sleep is re-enabled the
    moment the wrapped command returns (or raises)."""
    argv = _keep_awake_argv(platform.system())
    proc: subprocess.Popen | None = None
    if argv is not None:
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info(f"keeping the host awake for this run ({argv[0]})")
        except (OSError, ValueError) as exc:
            log.warn(f"could not keep the host awake ({argv[0]}: {exc}); the run may be interrupted by idle-sleep")
            proc = None
    try:
        yield
    finally:
        if proc is not None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
