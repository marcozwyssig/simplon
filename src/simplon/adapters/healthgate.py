"""The bring-up health gate: the verdict discipline that reads a health channel the deployed system WRITES.

One sentence, and it holds for any product deploying anything:

    a bring-up verdict must read a health channel that the deployed system writes, not merely the deploy
    tool's exit code and a container count.

The evidence is netctl#1100 (moved here by netctl#1407). `up` asserted two things and neither was about
the deployed system: containerlab exited 0 (`labnet.deploy_verdict`) and - only in the failure branch -
some containers were RUNNING (`clablifecycle.container_count`). `clablifecycle.up_verdict` then read the
shared degraded channel, found it empty, and printed OK over four controllers that were crash-looping and
could never form quorum. Three green checks, none of them about the deployed system.

The channel is Docker's own per-container HEALTHCHECK bookkeeping (`.State.Health.Status`) - the deployed
system writes it by passing or failing its OWN readiness probe, so it is the artifact talking rather than
the step. `clablifecycle`'s liveness signal stays purely structural on purpose (that module's anti-leak
invariant), which is exactly why this gate is a separate one: it is the non-structural half.

What a healthy subject PROVES is the product's business and arrives as DATA in the `HealthGateSpec`
(netctl: its readiness group carries the raft quorum indicator, so a healthy controller is one whose
cluster has a leader). The gate names no product, no container and no env var; it derives nothing itself.

The decision (`verdict`) is pure and unit-tested; the docker inspect is the only impurity.
"""
from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass

from simplon.kernel import log
from simplon.kernel.run import run

# Docker's own health states, plus the three the gate has to name itself. `missing` is a container
# docker does not know (a partial deploy that dropped one); `none` is a container without a HEALTHCHECK,
# which cannot be judged and must therefore never be read as a pass; `unknown` is a container docker could
# not be ASKED about (si#658) - a daemon that is down, a socket this user may not open, an inspect that
# did not answer - which says nothing about the container and must never be read as `missing`.
HEALTHY = "healthy"
STARTING = "starting"
UNHEALTHY = "unhealthy"
MISSING = "missing"
NONE = "none"
UNKNOWN = "unknown"

DEFAULT_INTERVAL_S = 5

#: How long one `docker inspect` may take. It reads the daemon's own state, so it answers in well under a
#: second when the daemon is there; a hung daemon must not hang a gate that has a budget.
INSPECT_TIMEOUT_S = 10.0

#: docker's words for a container it does not know. `no such object` is what this host's CLI says (measured,
#: docker 29 on 2026-11-17); `no such container` is the daemon's own wording, which other CLI versions pass
#: through (not measured here).
_NO_SUCH = re.compile(r"no such (object|container)", re.IGNORECASE)

#: The clock the budget is measured on; a name of its own so a test can drive it without a real wait.
_clock = time.monotonic


@dataclass(frozen=True)
class HealthGateSpec:
    """What a product hands the gate: WHICH containers carry the verdict, what a healthy one proves, how
    long they may take, and what the operator does when they do not make it. All of it data, so the gate
    imports no product.

    `budget_s` is the product's because its floor is the product image's HEALTHCHECK arithmetic
    (start-period + retries x interval): a budget under that floor can only ever time out mid-`starting`
    and would report "slow" where the truth is "dead". A budget <= 0 DISABLES the gate, for debugging a
    knowingly-degraded deployment; the product decides how an operator asks for that (an env var of its
    own namespace), the gate only sees the resulting number."""

    subjects: tuple[str, ...]              # the containers whose health channel IS the bring-up verdict
    budget_s: int                          # how long they may take to settle; <= 0 disables the gate
    label: str = "container"               # the product's noun for one subject, for the operator's lines
    proves: str = ""                       # what a healthy subject proves, in the product's own words
    remediation: str = ""                  # what the operator does next when the gate fails
    interval_s: int = DEFAULT_INTERVAL_S   # seconds between observations


@dataclass(frozen=True)
class HealthGateVerdict:
    """One observation's verdict. `settled` is the polling decision: True means no further round can
    change the outcome, so the caller stops immediately instead of burning the rest of its budget - which
    is what makes the common failure (`unhealthy`) an answer in the time it took to observe rather than
    the whole budget. `reasons` is empty iff `healthy`, else one line per failed check."""

    settled: bool
    healthy: bool
    reasons: tuple[str, ...]


def verdict(statuses: dict[str, str], *, budget_exhausted: bool,
            label: str = "container", why: Mapping[str, str] | None = None) -> HealthGateVerdict:
    """PURE: what one round of observed container health means for the bring-up verdict.

    - anything that is neither `healthy` nor `starting` is TERMINAL. Docker reports `unhealthy` only
      after the start-period and 3 consecutive failed probes, so it is a definitive answer, not a race;
      `missing` and `none` are terminal for the different reason that no amount of waiting produces a
      health status that was never going to exist.
    - all `healthy` -> pass.
    - some still `starting` -> keep polling while there is budget; when there is not, that is a failure
      and not a pass, because an unfinished observation is exactly the "the step ran" verdict this gate
      exists to replace.
    - no subjects at all -> failure. A bring-up reaching this point with nothing to check means the
      subject list was lost, and reporting a green bring-up for zero subjects is the same shape again.
    - `unknown` is terminal too, and its reason says that docker could not be asked, with docker's words
      from `why` (si#658): the verdict is about the gate's own eyes, not about the container.
    """
    if not statuses:
        return HealthGateVerdict(settled=True, healthy=False,
                                 reasons=(f"no {label} containers to check (nothing resolved)",))
    bad = sorted((n, s) for n, s in statuses.items() if s not in (HEALTHY, STARTING))
    if bad:
        return HealthGateVerdict(
            settled=True, healthy=False,
            reasons=tuple(_reason(label, n, s, (why or {}).get(n, "")) for n, s in bad))
    starting = sorted(n for n, s in statuses.items() if s == STARTING)
    if not starting:
        return HealthGateVerdict(settled=True, healthy=True, reasons=())
    if budget_exhausted:
        return HealthGateVerdict(
            settled=True, healthy=False,
            reasons=(f"still not ready within the budget: {', '.join(starting)}",))
    return HealthGateVerdict(settled=False, healthy=False, reasons=())


def _reason(label: str, name: str, status: str, why: str) -> str:
    if status == UNKNOWN:
        return f"{label} {name}: docker could not be asked about it, so its health is unknown" + (
            f" ({why})" if why else "")
    return f"{label} {name} is {status}"


def observe(container: str) -> tuple[str, str]:
    """Docker's own health verdict for one container, and - for `unknown` - why docker could not say.

    A container docker does not know is `missing`; one without a HEALTHCHECK is `none` (the template
    prints it, so both absences are distinguishable from a real status without a second call).

    "COULD NOT ASK" IS NOT "NOT THERE" (si#658). `docker inspect` exits 1 for both, and this used to read
    every failure as `missing`: a daemon that is down was reported as a container a partial deploy
    dropped. Only docker's own "no such object" / "no such container" (`_NO_SUCH`) is `missing`; a
    failure that says anything else, a timeout and a CLI that would not start are `unknown`, with why.
    """
    res = run(["docker", "inspect", "--format={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
               container], timeout=INSPECT_TIMEOUT_S)
    said = (res.err or res.out or "").strip()
    if res.ok:
        return (res.out or "").strip() or MISSING, ""
    if not res.timed_out and not res.not_started and _NO_SUCH.search(said):
        return MISSING, ""
    return UNKNOWN, said.splitlines()[-1] if said else f"`docker inspect` failed (rc {res.rc})"


def container_health(container: str) -> str:
    """Docker's own health verdict for one container (`observe` without the reason)."""
    return observe(container)[0]


def settle(spec: HealthGateSpec) -> int:
    """Wait, bounded, until every subject is healthy in Docker's own bookkeeping; 0 iff they all are.

    Belongs where a bring-up's LAST word is formed: after whatever host-side provisioning a subject needs
    before it can become ready at all, and before the product's own verdict - so that verdict is about
    the deployed system rather than the steps that ran. A non-zero return is FATAL to the bring-up by the
    caller's own hand; softening it into a degraded condition would route a dead deployment straight back
    through the verdict this gate exists to correct."""
    if spec.budget_s <= 0:
        log.warn(f"{spec.label} health gate skipped (budget {spec.budget_s}s)")
        return 0
    proves = f" ({spec.proves})" if spec.proves else ""
    total = len(spec.subjects)
    log.info(f"{spec.label} health gate: waiting up to {spec.budget_s}s for {total} {spec.label}(s) to "
             f"report ready{proves}")
    # DEADLINE-BASED (si#658), as `kernel.waits.await_http` is: each round's probes come out of the budget
    # instead of extending it. Counting rounds made the wall time the budget PLUS every probe's latency.
    # The last observation is made at the deadline, so the wall time is the budget plus one round.
    deadline = _clock() + spec.budget_s
    while True:
        observed = {c: observe(c) for c in spec.subjects}
        statuses = {c: status for c, (status, _) in observed.items()}
        why = {c: reason for c, (_, reason) in observed.items() if reason}
        left = deadline - _clock()
        round_verdict = verdict(statuses, budget_exhausted=left <= 0, label=spec.label, why=why)
        if round_verdict.settled:
            if round_verdict.healthy:
                log.ok(f"{spec.label}s ready: {total}/{total} healthy{proves}")
                return 0
            log.warn(f"{spec.label} health gate FAILED - this bring-up is not usable:")
            for reason in round_verdict.reasons:
                log.warn(f"  - {reason}")
            for line in spec.remediation.splitlines():
                log.warn(line)
            return 1
        time.sleep(min(spec.interval_s, left))
