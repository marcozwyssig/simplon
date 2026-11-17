"""The bring-up health-gate DISCIPLINE (simplon.adapters.healthgate), moved here from netctl by netctl#1407.

The rule under test is product-agnostic: a bring-up verdict must read a health channel the deployed
system writes, not merely the deploy tool's exit code and a container count. netctl#1100/#1083 is the
evidence - four controllers crash-looping without Raft quorum while `up` printed ` OK up: all 4 steps
passed`, because every check it made was about the steps.

These tests pin the discipline itself, with the product's words injected as data:

  1. the verdict is PURE over observed statuses, so every branch is testable without a deployment;
  2. `unhealthy` is TERMINAL - the gate stops polling at once rather than burning its budget, because
     Docker only reports it after the start-period and 3 consecutive failures;
  3. an unfinished observation (still `starting` at the budget end) is a FAILURE, not a pass - that is
     the "the step ran" verdict this gate replaces;
  4. what the gate says about a subject is the PRODUCT's noun and the PRODUCT's remediation, never one
     hardcoded here.

AAA throughout; goal-stating names incl. the negative cases (a healthy deployment must still pass).
"""
import os
import shutil
import time

import pytest

from conftest import docker_is_usable
from simplon.adapters import healthgate


def _spec(subjects, **kw):
    """The product data a spec carries, defaulted to netctl's shape so the tests read like the case that
    produced the rule."""
    return healthgate.HealthGateSpec(
        subjects=tuple(subjects), budget_s=kw.pop("budget_s", 300), label=kw.pop("label", "controller"),
        interval_s=kw.pop("interval_s", 1), **kw)


# --- the pure verdict --------------------------------------------------------------------------------

def test_all_subjects_healthy_settles_as_a_pass():
    # arrange: the good bring-up
    statuses = {"clab-netctl-netctl-zh": "healthy", "clab-netctl-netctl-be": "healthy"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=False, label="controller")

    # assert: terminal AND green, so the gate stops polling and the bring-up proceeds
    assert (verdict.settled, verdict.healthy, verdict.reasons) == (True, True, ())


def test_an_unhealthy_subject_is_terminal_and_named_with_the_products_noun():
    # arrange: the #1083 shape - one node past its start-period with 3 failed readiness probes. Budget
    # is deliberately NOT exhausted: the point is that waiting longer cannot change this answer.
    statuses = {"clab-netctl-netctl-zh": "healthy", "clab-netctl-netctl-nms": "unhealthy"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=False, label="controller")

    # assert: settled (no further polling) and failing, with the node named so the operator sees WHICH
    assert verdict.settled is True
    assert verdict.healthy is False
    assert verdict.reasons == ("controller clab-netctl-netctl-nms is unhealthy",)


def test_still_starting_keeps_polling_while_there_is_budget():
    # arrange: a normal bring-up inside the image's start-period
    statuses = {"c-zh": "healthy", "c-be": "starting"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=False)

    # assert: NOT settled - a slow subject must not be called dead while it may still get there
    assert verdict.settled is False
    assert verdict.healthy is False


def test_still_starting_at_the_budget_end_is_a_failure_not_a_pass():
    # arrange: the same observation, but there is no time left to improve it
    statuses = {"c-zh": "healthy", "c-be": "starting"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=True)

    # assert: an unfinished observation is a failure - reporting it as success is exactly #1083
    assert (verdict.settled, verdict.healthy) == (True, False)
    assert verdict.reasons == ("still not ready within the budget: c-be",)


def test_a_missing_container_fails_instead_of_silently_passing():
    # arrange: a partial deploy that dropped a subject. `clablifecycle.container_count` would still be
    # non-zero, which is how a partial deploy stays merely "degraded" in the structural verdict.
    statuses = {"c-zh": "healthy", "c-be": "missing"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=False)

    # assert
    assert (verdict.settled, verdict.healthy) == (True, False)
    assert verdict.reasons == ("container c-be is missing",)


def test_a_container_without_a_healthcheck_is_a_failure_not_an_assumed_pass():
    # arrange: no HEALTHCHECK means there is no channel to read. Treating "no answer" as "good answer"
    # is the whole bug class this gate exists for.
    statuses = {"c-zh": "none"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=False)

    # assert
    assert (verdict.settled, verdict.healthy) == (True, False)
    assert verdict.reasons == ("container c-zh is none",)


def test_no_subjects_at_all_fails_rather_than_passing_vacuously():
    # arrange: nothing to check. An empty set trivially satisfies "all healthy", which would hand back
    # a green bring-up for zero subjects.
    # act
    verdict = healthgate.verdict({}, budget_exhausted=False)

    # assert
    assert (verdict.settled, verdict.healthy) == (True, False)
    assert verdict.reasons != ()


def test_every_failing_subject_is_reported_not_just_the_first():
    # arrange: two dead nodes, so the operator is not sent back for a second run to learn about the
    # second one
    statuses = {"c-be": "unhealthy", "c-gr": "missing", "c-zh": "healthy"}

    # act
    verdict = healthgate.verdict(statuses, budget_exhausted=False)

    # assert: both named, sorted so the output is stable across runs
    assert verdict.reasons == ("container c-be is unhealthy", "container c-gr is missing")


# --- the settle loop (the docker inspect stubbed) ----------------------------------------------------

@pytest.fixture
def scripted_health(monkeypatch):
    """Drive `settle` off a scripted sequence of per-round status maps, on a clock that only the sleep moves.
    Returns the recorder so a test can assert HOW MANY rounds actually ran (the early-exit contract)."""
    def _install(rounds: list[dict[str, str]], *, subjects=("c-zh", "c-be")):
        seen: list[dict[str, str]] = []
        now = [0.0]
        monkeypatch.setattr(healthgate, "_clock", lambda: now[0])
        monkeypatch.setattr(healthgate.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))

        def fake_observe(container: str) -> tuple[str, str]:
            # one map per round, the last one repeating once the script runs out
            idx = min(len(seen), len(rounds) - 1)
            status = rounds[idx][container]
            if container == subjects[-1]:
                seen.append(rounds[idx])
            return status, ""

        monkeypatch.setattr(healthgate, "observe", fake_observe)
        return seen
    return _install


def test_settle_returns_zero_once_every_subject_is_healthy(scripted_health):
    # arrange: two rounds still starting, then ready - the ordinary bring-up
    seen = scripted_health([
        {"c-zh": "starting", "c-be": "starting"},
        {"c-zh": "healthy", "c-be": "starting"},
        {"c-zh": "healthy", "c-be": "healthy"},
    ])

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be")))

    # assert: passes, and stops the moment it may (no burning the rest of the budget)
    assert rc == 0
    assert len(seen) == 3


def test_settle_stops_at_the_first_unhealthy_instead_of_waiting_out_the_budget(scripted_health):
    # arrange: a 300s budget at 1s per round would be 300 observations if `unhealthy` were not terminal
    seen = scripted_health([
        {"c-zh": "starting", "c-be": "starting"},
        {"c-zh": "healthy", "c-be": "unhealthy"},
    ])

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be")))

    # assert: fails, on the SECOND round - Docker's `unhealthy` is definitive, so waiting is wasted time
    assert rc != 0
    assert len(seen) == 2


def test_settle_fails_when_a_subject_never_leaves_starting(scripted_health):
    # arrange: a tiny budget (3 s at 1 s per round), never converging
    seen = scripted_health([{"c-zh": "healthy", "c-be": "starting"}])

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be"), budget_s=3))

    # assert: the budget is spent and the verdict is red, not a shrug - observed at 0, 1 and 2 s and once
    # more at the deadline (si#658: deadline-based, so the last look is at the budget's end)
    assert rc != 0
    assert len(seen) == 4


def test_settle_is_skippable_for_debugging_a_knowingly_degraded_deployment(scripted_health):
    # arrange: the escape hatch is a non-positive budget; how an operator asks for one is the product's
    # business (netctl: NETCTL_UP_HEALTH_TIMEOUT_S=0)
    seen = scripted_health([{"c-zh": "unhealthy", "c-be": "unhealthy"}])

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be"), budget_s=0))

    # assert: passes WITHOUT observing anything - the operator asked for it explicitly
    assert rc == 0
    assert seen == []


def test_a_failing_gate_prints_the_products_own_remediation(scripted_health, capsys):
    # arrange: the gate knows no product, so the next step an operator gets must come from the spec
    scripted_health([{"c-zh": "healthy", "c-be": "unhealthy"}])
    hint = "check the raft quorum indicator\n  then: ./netctl.sh down && ./netctl.sh up"

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be"), remediation=hint))
    out = capsys.readouterr().out

    # assert: failed, named the subject with the product's noun, and carried its remediation verbatim
    assert rc != 0
    assert "controller c-be is unhealthy" in out
    assert "./netctl.sh down && ./netctl.sh up" in out


def test_a_gate_with_no_remediation_still_reports_the_failure(scripted_health, capsys):
    # arrange: `remediation` is optional data - an empty one must not silence the verdict
    scripted_health([{"c-zh": "unhealthy", "c-be": "healthy"}])

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be")))
    out = capsys.readouterr().out

    # assert
    assert rc != 0
    assert "health gate FAILED" in out


# --- si#658: could not ask is not missing, the inspect is bounded, the budget is a deadline ------------

def _docker_answering(tmp_path, script: str) -> str:
    """A PATH whose `docker` is `script` (a real executable), with the rest of the PATH kept."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\n" + script, encoding="utf-8")
    docker.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="no docker CLI here to point at a dead daemon")
def test_an_unreachable_daemon_is_unknown_and_not_missing(monkeypatch, tmp_path):
    # arrange: the real docker CLI, aimed at a socket nothing listens on
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/no-daemon.sock")

    # act
    status, why = healthgate.observe("c-zh")

    # assert
    assert status == healthgate.UNKNOWN
    assert "no-daemon.sock" in why


@pytest.mark.skipif(shutil.which("docker") is None, reason="no docker CLI here to point at a dead daemon")
def test_the_gate_says_the_daemon_could_not_be_asked(monkeypatch, tmp_path, capsys):
    # arrange
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/no-daemon.sock")

    # act
    rc = healthgate.settle(_spec(("c-zh",), budget_s=30))
    out = capsys.readouterr().out

    # assert: red at once, and about the gate's eyes, not about the container
    assert rc != 0
    assert "docker could not be asked" in out and "is missing" not in out


@pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to ask about a container")
def test_a_container_docker_does_not_know_is_still_missing():
    # act
    status, why = healthgate.observe("simplon-si658-no-such-container")

    # assert
    assert (status, why) == (healthgate.MISSING, "")


def test_an_inspect_that_does_not_answer_is_unknown_within_its_limit(monkeypatch, tmp_path):
    # arrange: a docker that never answers, and a short limit
    monkeypatch.setenv("PATH", _docker_answering(tmp_path, "exec sleep 30\n"))
    monkeypatch.setattr(healthgate, "INSPECT_TIMEOUT_S", 0.5)

    # act
    started = time.monotonic()
    status, why = healthgate.observe("c-zh")

    # assert
    assert time.monotonic() - started < 5
    assert status == healthgate.UNKNOWN and "`docker inspect c-zh` gave no answer within 0.5 s" in why


def test_a_slow_probe_does_not_stretch_the_budget(monkeypatch, tmp_path):
    # arrange: every inspect takes 1 s and the subject never leaves `starting`; budget 3 s, 1 s per round.
    # Counting rounds, that was 3 probes and 2 sleeps, 5 s; the budget plus one probe is 4 s.
    monkeypatch.setenv("PATH", _docker_answering(tmp_path, "sleep 1\necho starting\n"))

    # act
    started = time.monotonic()
    rc = healthgate.settle(_spec(("c-zh",), budget_s=3, interval_s=1))
    took = time.monotonic() - started

    # assert
    assert rc != 0
    assert took < 4.5, f"the gate took {took:.1f} s on a 3 s budget with 1 s probes"
