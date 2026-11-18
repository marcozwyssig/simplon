"""Whether a process is still running, read from /proc - shared by the tests that check what a run left behind.

One copy on purpose: three tests carried their own, and all three read a process that ended between the
open and the read as an error (ESRCH from the read, not FileNotFoundError from the open). CI hit it on
every PR after #759.
"""
from __future__ import annotations

import contextlib
import os
import signal


def alive(pid: int) -> bool:
    """Running, as opposed to gone, a zombie waiting to be reaped (Z) or one being released (X)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except (FileNotFoundError, ProcessLookupError):  # gone before the open, or between the open and the read
        return False


def kill_if_alive(pid: int) -> None:
    """A test's cleanup: SIGKILL `pid` if it still runs. It can end between the check and the kill, so a
    process that is gone by then is not an error."""
    if alive(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
