"""Whether a process is still running, read from /proc - shared by the tests that check what a run left behind.

One copy on purpose: three tests carried their own, and all three read a process that ended between the
open and the read as an error (ESRCH from the read, not FileNotFoundError from the open). CI hit it on
every PR after #759.
"""
from __future__ import annotations


def alive(pid: int) -> bool:
    """Running, as opposed to gone or a zombie waiting to be reaped."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):  # gone before the open, or between the open and the read
        return False
