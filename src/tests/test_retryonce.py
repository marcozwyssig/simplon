"""The one retry the brew e2e tests take on a failed attempt (si#589). The sleep is injected: no test here waits."""
from __future__ import annotations

import warnings

import pytest

from retryonce import RetryWarning, retry_once


class Attempts:
    """A test attempt that fails with the given exceptions in turn, then returns "done"."""

    def __init__(self, *failures):
        self.failures = list(failures)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "done"


def test_a_first_attempt_that_passes_runs_once_and_never_pauses():
    attempt, pauses = Attempts(), []

    with warnings.catch_warnings(record=True) as said:
        warnings.simplefilter("always")
        assert retry_once(attempt, pause=30, sleep=pauses.append) == "done"

    assert (attempt.calls, pauses) == (1, [])
    assert [w for w in said if issubclass(w.category, RetryWarning)] == []


def test_one_failure_is_retried_after_the_pause_and_the_retry_is_visible():
    attempt, pauses = Attempts(AssertionError("audit_rc 1: curl timed out")), []

    with pytest.warns(RetryWarning, match="curl timed out") as said:
        assert retry_once(attempt, pause=30, sleep=pauses.append) == "done"

    assert (attempt.calls, pauses) == (2, [30])
    assert "AssertionError" in str(said[0].message)


def test_two_failures_raise_the_second_and_name_the_first():
    first, second = ValueError("pypi unreachable"), AssertionError("rc 1, audit says: article")
    attempt, pauses = Attempts(first, second), []

    with pytest.warns(RetryWarning), pytest.raises(AssertionError) as raised:
        retry_once(attempt, pause=30, sleep=pauses.append)

    assert raised.value is second
    assert (attempt.calls, pauses) == (2, [30])
    assert "pypi unreachable" in "\n".join(getattr(raised.value, "__notes__", []))


def test_a_skip_or_an_interrupt_is_not_a_failure_and_is_not_retried():
    for stop in (pytest.skip.Exception("no docker"), KeyboardInterrupt()):
        attempt, pauses = Attempts(stop), []

        with pytest.raises(type(stop)):
            retry_once(attempt, pause=30, sleep=pauses.append)

        assert (attempt.calls, pauses) == (1, [])
