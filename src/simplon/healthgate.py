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

import time
from dataclasses import dataclass

from delivery import log
from delivery.run import run

# Docker's own health states, plus the two absences the gate has to name itself. `missing` is a container
# docker does not know (a partial deploy that dropped one); `none` is a container without a HEALTHCHECK,
# which cannot be judged and must therefore never be read as a pass.
HEALTHY = "healthy"
STARTING = "starting"
UNHEALTHY = "unhealthy"
MISSING = "missing"
NONE = "none"

DEFAULT_INTERVAL_S = 5


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
            label: str = "container") -> HealthGateVerdict:
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
    """
    if not statuses:
        return HealthGateVerdict(settled=True, healthy=False,
                                 reasons=(f"no {label} containers to check (nothing resolved)",))
    bad = sorted((n, s) for n, s in statuses.items() if s not in (HEALTHY, STARTING))
    if bad:
        return HealthGateVerdict(
            settled=True, healthy=False,
            reasons=tuple(f"{label} {n} is {s}" for n, s in bad))
    starting = sorted(n for n, s in statuses.items() if s == STARTING)
    if not starting:
        return HealthGateVerdict(settled=True, healthy=True, reasons=())
    if budget_exhausted:
        return HealthGateVerdict(
            settled=True, healthy=False,
            reasons=(f"still not ready within the budget: {', '.join(starting)}",))
    return HealthGateVerdict(settled=False, healthy=False, reasons=())


def container_health(container: str) -> str:
    """Docker's own health verdict for one container. A container docker does not know is `missing`; one
    without a HEALTHCHECK is `none` (the template prints it, so both absences are distinguishable from a
    real status without a second call)."""
    res = run(["docker", "inspect", "-f",
               "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", container])
    if not res.ok:
        return MISSING
    return (res.out or "").strip() or MISSING


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
    rounds = max(1, spec.budget_s // max(1, spec.interval_s))
    for attempt in range(1, rounds + 1):
        statuses = {c: container_health(c) for c in spec.subjects}
        round_verdict = verdict(statuses, budget_exhausted=attempt >= rounds, label=spec.label)
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
        time.sleep(spec.interval_s)
    return 1  # unreachable: the last round always settles (budget_exhausted)
