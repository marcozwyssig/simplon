"""Unit tests for waits - the poll/retry/convergence control logic (fake probe + no-op sleep)."""
from delivery import waits


def test_poll_until_succeeds_within_tries_and_stops_early():
    # arrange: a probe that fails twice then succeeds; record sleeps
    calls = {"n": 0}
    sleeps = []

    def probe():
        calls["n"] += 1
        return calls["n"] >= 3

    # act
    ok = waits.poll_until(probe, tries=10, interval=3.0, sleep=sleeps.append)

    # assert: returns True, probed exactly 3 times, slept between the 2 failures only
    assert ok is True
    assert calls["n"] == 3
    assert sleeps == [3.0, 3.0]


def test_poll_until_returns_false_after_exhausting_tries():
    # arrange: a probe that never succeeds
    sleeps = []

    # act
    ok = waits.poll_until(lambda: False, tries=4, interval=1.0, sleep=sleeps.append)

    # assert: False, and it did NOT sleep after the final attempt
    assert ok is False
    assert sleeps == [1.0, 1.0, 1.0]


def test_device_count_returns_list_length():
    # arrange / act / assert
    assert waits.device_count('[{"id": "a"}, {"id": "b"}]') == 2


def test_device_count_minus_one_for_non_list_or_garbage():
    # arrange / act / assert: a dict, and unparseable text, both yield -1
    assert waits.device_count('{"not": "a list"}') == -1
    assert waits.device_count("not json at all") == -1


def test_round_is_stable_requires_agreement_and_nonzero():
    # arrange / act / assert
    assert waits.round_is_stable([3, 3, 3]) is True
    assert waits.round_is_stable([3, 3, 2]) is False     # disagreement
    assert waits.round_is_stable([0, 0, 0]) is False     # empty inventory
    assert waits.round_is_stable(None) is False          # a controller failed
    assert waits.round_is_stable([]) is False


def test_is_converged_needs_consecutive_stable_rounds():
    # arrange: three stable rounds in a row reach the default need=3
    rounds = [[2, 2, 2], [2, 2, 2], [2, 2, 2]]

    # act / assert
    assert waits.is_converged(rounds) is True


def test_is_converged_resets_streak_on_a_void_or_disagreeing_round():
    # arrange: a disagreeing round in the middle breaks the streak, so 3-in-a-row is never reached
    rounds = [[2, 2, 2], [2, 2, 2], None, [2, 2, 2], [2, 2, 2]]

    # act / assert
    assert waits.is_converged(rounds, need=3) is False
    # but a clean run of 3 after the reset would pass
    assert waits.is_converged(rounds + [[2, 2, 2]], need=3) is True


# --- knocking on an endpoint until it answers (platform#43) ------------------------------------------

class _Answer:
    """A stand-in for what urlopen returns: a context manager with a status and a readable body."""

    def __init__(self, status, body=b""):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, size):
        return self._body[:size]


def test_a_probe_reports_the_answer_body_when_the_endpoint_says_200(monkeypatch):
    # arrange: a healthy endpoint answering with a body
    monkeypatch.setattr(waits.urllib.request, "urlopen",
                        lambda url, timeout: _Answer(200, b'  {"status":"ok"}  '))

    # act
    healthy, detail = waits.probe_http("http://127.0.0.1:8080/health")

    # assert: the body, stripped - so an operator sees what the service actually said
    assert (healthy, detail) == (True, '{"status":"ok"}')


def test_a_probe_reports_a_long_answer_only_up_to_the_first_200_bytes(monkeypatch):
    # arrange: a chatty endpoint
    monkeypatch.setattr(waits.urllib.request, "urlopen",
                        lambda url, timeout: _Answer(200, b"x" * 5000))

    # act
    healthy, detail = waits.probe_http("http://127.0.0.1:8080/health")

    # assert
    assert healthy is True
    assert detail == "x" * 200


def test_a_probe_reports_the_status_when_the_endpoint_answers_something_else(monkeypatch):
    # arrange: the proxy is up but has no backend to route to yet
    monkeypatch.setattr(waits.urllib.request, "urlopen",
                        lambda url, timeout: _Answer(503, b"no upstream"))

    # act
    healthy, detail = waits.probe_http("http://127.0.0.1:8080/health")

    # assert: NOT healthy, and the reason is the status rather than the body
    assert (healthy, detail) == (False, "HTTP 503")


def test_a_probe_that_gets_a_redirect_has_not_found_a_healthy_endpoint(monkeypatch):
    # arrange: something answered - a proxy sending the caller elsewhere - but the health route did not
    monkeypatch.setattr(waits.urllib.request, "urlopen",
                        lambda url, timeout: _Answer(302, b"see /login"))

    # act
    healthy, detail = waits.probe_http("http://127.0.0.1:8080/health")

    # assert: only 200 is an answer; "it answered SOMETHING" is how a login page passes for a service
    assert (healthy, detail) == (False, "HTTP 302")


def test_a_probe_reports_the_reason_when_nothing_answers_at_all(monkeypatch):
    # arrange: nothing is listening yet
    def _refused(url, timeout):
        raise ConnectionRefusedError("Connection refused")

    monkeypatch.setattr(waits.urllib.request, "urlopen", _refused)

    # act
    healthy, detail = waits.probe_http("http://127.0.0.1:8080/health")

    # assert: the exception type and its message, so "not up yet" is distinguishable from "up and 500"
    assert healthy is False
    assert detail == "ConnectionRefusedError: Connection refused"


def test_an_endpoint_that_answers_at_once_is_not_waited_for():
    # arrange: a healthy endpoint and a clock that would expire immediately
    sleeps = []

    # act
    healthy, detail = waits.await_http("http://x/health", budget_s=30,
                                       probe=lambda url: (True, "ok"),
                                       sleep=sleeps.append, now=lambda: 0.0)

    # assert: answered on the first knock, nothing slept
    assert (healthy, detail) == (True, "ok")
    assert sleeps == []


def test_an_endpoint_that_needs_a_moment_is_waited_for_within_the_budget():
    # arrange: two refusals with DIFFERENT reasons, then a healthy answer; a clock inside the budget
    answers = [(False, "refused-1"), (False, "refused-2"), (True, "ready")]
    sleeps = []

    # act
    healthy, detail = waits.await_http("http://x/health", budget_s=30, interval_s=0.5,
                                       probe=lambda url: answers.pop(0),
                                       sleep=sleeps.append, now=lambda: 0.0)

    # assert: the last answer is the verdict, and it slept the caller's interval between knocks
    assert (healthy, detail) == (True, "ready")
    assert sleeps == [0.5, 0.5]


def test_an_endpoint_that_never_answers_reports_the_LAST_reason_when_the_budget_runs_out():
    # arrange: a clock that starts at 0 and is past a 10s budget on the second reading
    answers = [(False, "refused-1"), (False, "gateway-2"), (False, "gateway-3")]
    clock = [0.0, 0.0, 4.0, 11.0]   # the deadline reading, then one per failed knock
    sleeps = []

    # act
    healthy, detail = waits.await_http("http://x/health", budget_s=10,
                                       probe=lambda url: answers.pop(0),
                                       sleep=sleeps.append, now=lambda: clock.pop(0))

    # assert: why it is STILL not answering, not why it was not answering a minute ago
    assert (healthy, detail) == (False, "gateway-3")
    assert sleeps == [1.0, 1.0]


def test_a_budget_of_zero_knocks_exactly_once():
    # arrange: a dead endpoint and a clock that does not move. ONE scripted answer, so a knock the
    # budget did not pay for raises here rather than spinning on a clock that never expires.
    answers = [(False, "refused")]
    knocks = []
    sleeps = []

    def probe(url):
        knocks.append(url)
        return answers.pop(0)

    # act
    healthy, detail = waits.await_http("http://x/health", budget_s=0, probe=probe,
                                       sleep=sleeps.append, now=lambda: 7.0)

    # assert: one knock, no wait - the same call serves "tell me its state right now"
    assert (healthy, detail) == (False, "refused")
    assert knocks == ["http://x/health"]
    assert sleeps == []


def test_a_negative_budget_is_read_as_no_budget_and_not_as_a_deadline_in_the_past():
    # arrange: a clock that does not move, so a negative budget could only expire before the first knock
    answers = [(False, "refused")]
    knocks = []

    # act
    healthy, detail = waits.await_http("http://x/health", budget_s=-5,
                                       probe=lambda url: knocks.append(url) or answers.pop(0),
                                       sleep=lambda _s: None, now=lambda: 7.0)

    # assert: it still knocked once and reported why
    assert (healthy, detail) == (False, "refused")
    assert knocks == ["http://x/health"]
