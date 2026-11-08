"""One retry for a test attempt that talks to the live network (si#589).

The brew e2e tests run the real brew image against the real PyPI and GitHub. A network failure there
reaches the test in two shapes: as an exception (`PyPIError`, a `ValueError` from the closure) or, inside
`brew audit` run after `set +e` (homebrewtap.py), as `audit_rc != 0`, a red verdict that is
indistinguishable from a real formula defect. So the retry covers the whole attempt and every
`Exception`, an `AssertionError` included: a real defect fails twice and stays red, a passing network
blip does not.

Not retried: anything that is not an `Exception` - a pytest skip or xfail, `KeyboardInterrupt`. A skip is
a verdict of its own, and an interrupt is the person at the keyboard.

The retry is never silent. It warns a `RetryWarning` naming the first failure, which pytest prints in the
warnings summary of a GREEN run too, so a test that needed it does not look like one that passed first
time. When the second attempt fails as well, that failure is the one raised and the first is attached to
it as a note, so the report shows both.
"""
from __future__ import annotations

import time
import warnings
from typing import Callable, TypeVar

T = TypeVar("T")

#: Seconds between the attempts. A network blip on a CI runner (a DNS hiccup, a reset connection, a
#: registry 5xx) is usually over within seconds; 30 s gives it room without making a real defect,
#: which fails twice, cost more than one more brew run already does (each attempt takes minutes).
PAUSE = 30


class RetryWarning(UserWarning):
    """A test attempt failed and was run once more."""


def retry_once(attempt: Callable[[], T], *, pause: float = PAUSE, sleep: Callable[[float], object] = time.sleep) -> T:
    """`attempt()`, and if it fails, once more after `pause` seconds. The second failure is the one raised.

    `attempt` must set up its own state: the second call must not see what the first left behind."""
    try:
        return attempt()
    except Exception as first:
        said = f"{type(first).__name__}: {first}"
        warnings.warn(f"si#589: attempt 1 failed, retrying once in {pause} s - {said}", RetryWarning, stacklevel=2)
        sleep(pause)
        try:
            return attempt()
        except Exception as second:
            second.add_note(f"si#589: attempt 2 failed too; attempt 1 had failed with {said}")
            raise
