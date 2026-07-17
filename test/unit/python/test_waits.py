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
