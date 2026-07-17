"""Poll / retry / convergence control logic for the *ctl orchestrators, ported from the shell
wait_http/wait_stable. The control flow (how many tries, when to reset the stability streak, when the
cluster counts as converged) is factored OUT from the actual probing so it can be unit-tested with a
fake probe and a no-op sleep - no network, no real time. The live HTTP wiring lands in a later
increment; this is the tested foundation.
"""
from __future__ import annotations

import json
import time
from typing import Callable

# A probe is any zero-arg callable returning truthy on success (e.g. "the controller answered 200").
Probe = Callable[[], bool]


def poll_until(probe: Probe, *, tries: int = 60, interval: float = 3.0,
               sleep: Callable[[float], None] = time.sleep) -> bool:
    """Call `probe` up to `tries` times, returning True on the first success; sleep `interval` between
    attempts (NOT after the last). Returns False if it never succeeds. Mirrors wait_http (netctl.sh:150);
    `sleep` is injectable so tests run instantly.
    """
    for attempt in range(1, tries + 1):
        if probe():
            return True
        if attempt < tries:
            sleep(interval)
    return False


def device_count(body: str) -> int:
    """The number of devices a controller reports from /api/devices: the length of the JSON array, or
    -1 when the body is not a JSON list / cannot be parsed. Ported from the inline python in wait_stable
    (netctl.sh:176)."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return -1
    return len(data) if isinstance(data, list) else -1


# A round of the stability check: either None (a controller failed to respond, so the round is void) or
# the list of per-controller device counts gathered that round.
Round = "list[int] | None"


def round_is_stable(counts: "list[int] | None") -> bool:
    """A single round counts as stable when every controller responded, they ALL agree on the same
    count, and that count is > 0 (a converged, non-empty inventory). Mirrors the inner test in
    wait_stable (netctl.sh:183-185)."""
    if not counts:
        return False
    first = counts[0]
    return first > 0 and all(c == first for c in counts)


def is_converged(rounds: "list[list[int] | None]", need: int = 3) -> bool:
    """True once `need` CONSECUTIVE rounds are each stable (the streak resets on any void/disagreeing
    round). This is the gate wait_stable applies before the test suite runs (netctl.sh:166), so the
    suite never runs against a still-converging cluster.
    """
    streak = 0
    for counts in rounds:
        streak = streak + 1 if round_is_stable(counts) else 0
        if streak >= need:
            return True
    return False
