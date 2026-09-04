"""The bring-up health-gate DISCIPLINE (delivery.healthgate), moved here from netctl by netctl#1407.

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
import pytest

from delivery import healthgate


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
    """Drive `settle` off a scripted sequence of per-round status maps, with the sleep removed. Returns
    the recorder so a test can assert HOW MANY rounds actually ran (the early-exit contract)."""
    def _install(rounds: list[dict[str, str]], *, subjects=("c-zh", "c-be")):
        seen: list[dict[str, str]] = []
        monkeypatch.setattr(healthgate.time, "sleep", lambda _s: None)

        def fake_status(container: str) -> str:
            # one map per round, the last one repeating once the script runs out
            idx = min(len(seen), len(rounds) - 1)
            status = rounds[idx][container]
            if container == subjects[-1]:
                seen.append(rounds[idx])
            return status

        monkeypatch.setattr(healthgate, "container_health", fake_status)
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
    # arrange: a tiny budget (3 rounds at 1s), never converging
    seen = scripted_health([{"c-zh": "healthy", "c-be": "starting"}])

    # act
    rc = healthgate.settle(_spec(("c-zh", "c-be"), budget_s=3))

    # assert: the budget is spent and the verdict is red, not a shrug
    assert rc != 0
    assert len(seen) == 3


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
