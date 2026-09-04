"""Free a TCP port before something binds it (platform#43, from biz-cockpit#88).

Every product that starts a dev server on a fixed port needs this, and the kernel had nothing for it. The
accident it prevents is entirely ordinary: a crashed Ctrl-C, a run that outlived its terminal, a second
window - and the next start fails with `address already in use` on a port whose owner nobody can name.

Deliberately a COURTESY, never a gate. A free port, an absent `lsof` and a process this user may not
signal are all no-ops: the caller is about to bind the port and will learn the truth from `bind()` in any
case, so failing here would only replace a clear error with an earlier, vaguer one.

The decision this module makes - TERM, wait out the grace period, KILL whatever still holds the port - is
tested with an injected clock and a fake `lsof`, so the suite kills nothing and waits for nothing.
"""
from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable, Iterable

from delivery import log
from delivery.run import run

# How long a listener may take to shut down on its own before it is killed, and how often to look.
DEFAULT_GRACE_S = 5.0
DEFAULT_INTERVAL_S = 1.0


def parse_pids(text: str) -> list[int]:
    """The pids in `lsof -t` output, first occurrence first, ignoring blank and non-numeric lines. PURE,
    and deliberately forgiving: `lsof` writes its complaints to stderr, but a warning that reaches stdout
    on some platform must not turn into an int() traceback in front of a dev server."""
    seen: list[int] = []
    for token in text.split():
        if token.isdigit() and int(token) not in seen:
            seen.append(int(token))
    return seen


def listeners(port: int) -> list[int]:
    """The pids currently LISTENing on TCP `port`, in the order lsof reports them.

    Only listeners: a client connection to that port belongs to somebody else's business and must not be
    killed. Empty when nothing listens - and empty when lsof is missing, which is why the rc is ignored
    (lsof exits non-zero for "nothing found" just as it does for "no such tool")."""
    return parse_pids(run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"]).out)


def free(port: int, *, grace_s: float = DEFAULT_GRACE_S, interval_s: float = DEFAULT_INTERVAL_S,
         sleep: Callable[[float], None] = time.sleep) -> list[int]:
    """Stop whatever LISTENs on TCP `port`; the pids it signalled, empty when the port was already free.

    TERM first, so a server gets to close its files, then KILL for whatever still holds the port when the
    grace period is spent - and only for those, never for the ones that already went. `sleep` is
    injectable so the wait is unit-testable without spending it."""
    holders = listeners(port)
    if not holders:
        return []
    log.info(f"port {port} in use - stopping PID(s): {_names(holders)}")
    _signal(holders, signal.SIGTERM)
    survivors = _await_release(port, grace_s=grace_s, interval_s=interval_s, sleep=sleep)
    if survivors:
        log.warn(f"port {port} still busy - force killing: {_names(survivors)}")
        _signal(survivors, signal.SIGKILL)
    return holders


def _await_release(port: int, *, grace_s: float, interval_s: float,
                   sleep: Callable[[float], None]) -> list[int]:
    """Look again every `interval_s` until the port is free or the grace period is spent; whatever still
    holds it. At least one look, so a zero grace period still re-reads the port rather than assuming."""
    rounds = max(1, int(grace_s // interval_s)) if interval_s > 0 else 1
    holders: list[int] = []
    for _ in range(rounds):
        sleep(interval_s)
        holders = listeners(port)
        if not holders:
            return []
    return holders


def _signal(pids: Iterable[int], sig: int) -> None:
    """Signal each pid, ignoring the ones already gone and the ones this user may not signal - both are
    somebody else's problem, and neither is a reason to stop before the next pid."""
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            continue


def _names(pids: Iterable[int]) -> str:
    return ", ".join(str(pid) for pid in pids)
