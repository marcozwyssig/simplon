"""Poll / retry / convergence control logic for the *ctl orchestrators, ported from the shell
wait_http/wait_stable. The control flow (how many tries, when to reset the stability streak, when the
cluster counts as converged) is factored OUT from the actual probing so it can be unit-tested with a
fake probe and a no-op sleep - no network, no real time.

`probe_http`/`await_http` are that live HTTP wiring, arrived (platform#43, from biz-cockpit#74): one
knock, and the bounded wait built on it. They keep the same discipline - the DECISION (when to stop, what
to report) is separated from the knocking, so a fake probe and an injected clock test the whole of it.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
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


# --- knocking on an endpoint until it answers --------------------------------------------------------

# One knock's patience. Short on purpose: `await_http` has its own budget, and a probe that hangs for a
# minute turns a bounded wait into an unbounded one.
DEFAULT_PROBE_TIMEOUT_S = 5.0


def probe_http(url: str, *, timeout: float = DEFAULT_PROBE_TIMEOUT_S) -> tuple[bool, str]:
    """ONE knock on `url`: (it answered 200, what happened).

    The detail is the point. A bare False leaves an operator guessing between "not up yet", "up and
    answering 500" and "no route at all"; here it is the answer body (its first 200 bytes) on success,
    else the HTTP status or the exception that prevented an answer. The ONLY I/O in this module, and the
    seam `await_http` takes as a parameter."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - caller's URL
            body = response.read(200).decode("utf-8", "replace").strip()
            if response.status == 200:
                return True, body
            return False, f"HTTP {response.status}"
    except (urllib.error.URLError, OSError) as error:
        return False, f"{type(error).__name__}: {error}"


def await_http(url: str, *, budget_s: float, interval_s: float = 1.0,
               probe: Callable[[str], tuple[bool, str]] = probe_http,
               sleep: Callable[[float], None] = time.sleep,
               now: Callable[[], float] = time.monotonic) -> tuple[bool, str]:
    """Knock on `url` until it answers 200 or `budget_s` seconds have passed: (healthy, what happened).

    Deadline-based rather than try-counting, because what an operator names after a deploy is a duration,
    not a number of attempts - and because a probe's own latency then comes out of the budget instead of
    silently extending it. A budget of 0 knocks exactly once, which is what makes the same call serve
    both "wait for the stack to come up" and "tell me its state right now".

    The reported detail is always the LAST one: after waiting a minute, what matters is why it is still
    not answering, not what the first knock said. A budget below zero is the same as zero, and for the
    same reason: the knock comes before the deadline is ever read.

    `probe`, `sleep` and `now` are injectable, so the whole control flow is unit-tested without a socket
    and without spending the budget."""
    deadline = now() + budget_s
    while True:
        healthy, detail = probe(url)
        if healthy:
            return True, detail
        if now() >= deadline:
            return False, detail
        sleep(interval_s)
