"""Docker-disk-guard decision logic as pure functions. Repeated image builds pile up dangling layers; if
the docker data filesystem fills, initdb-style bootstraps fail and container deploys hang on a
never-healthy dependency. The decision - parse `df`, compute free %, decide whether to prune - is pure
here; the actual `docker prune` wiring lives in the consuming product.

TWO CALLERS, TWO QUESTIONS, AND THAT IS WHY `verdict` EXISTS ALONGSIDE `should_prune`. A guard asks "may I
prune now", which is a yes/no and `should_prune` answers it. A PREFLIGHT asks "is this machine fit to
start a job on", and that is not a yes/no: it can also be "I could not tell", and a preflight that reports
"fine" when it could not read `df` is green precisely because nobody looks. So the range is widened here
rather than at the seam - `UNKNOWN`, `ENOUGH`, `LOW`, each meaning its own value - and the caller decides
what to DO about each. See `simplon.diskguard`, whose `disk_guard` returned rc 0 for "no docker", "df
unreadable", "enough free" and "pruned" alike until si#327 had to build a fail-fast on top of it.
"""
from __future__ import annotations

DEFAULT_MIN_FREE_PCT = 15

#: The three things a probe of a filesystem's fullness can honestly say. Strings rather than an Enum
#: because they are logged and compared and nothing else, and a string shows up readably in a test
#: failure and in a CI log without anybody calling `.value`.
#:
#: `UNKNOWN` is the one that had no value before, and it is the reason for the widening: it means the
#: probe did not run or its output did not parse, which is NOT the same as a healthy machine.
UNKNOWN = "unknown"
ENOUGH = "enough"
LOW = "low"


def used_pct(df_line: str) -> int | None:
    """The used-% of a `df -P` data line (the 5th field, e.g. '88%'), as an int, or None if the line is
    unparseable - matching a `df` + numeric guard."""
    fields = df_line.split()
    if len(fields) < 5:
        return None
    raw = fields[4].replace("%", "")
    if not raw.isdigit():
        return None
    return int(raw)


def free_pct(used: int) -> int:
    """Free % = 100 - used."""
    return 100 - used


def should_prune(free: int, min_free: int = DEFAULT_MIN_FREE_PCT) -> bool:
    """Prune when free % is BELOW the threshold."""
    return free < min_free


def verdict(df_line: str, min_free: int = DEFAULT_MIN_FREE_PCT) -> "tuple[str, int | None]":
    """`(state, free-%)` for one `df -P` data line: `UNKNOWN`/`None` when it does not parse, else
    `LOW`/`ENOUGH` against the threshold with the free-% travelling alongside.

    The free-% is returned WITH the state so a caller can report the number it decided on rather than
    parse the line a second time - the two-sources-for-one-string problem `CLAUDE.md` names, at the
    smallest possible scale.

    The threshold is expressed as free-%, so the operational phrasing "fail above 85% used" is
    `min_free=15`, which is `DEFAULT_MIN_FREE_PCT` and needs no second number.
    """
    used = used_pct(df_line)
    if used is None:
        return UNKNOWN, None
    free = free_pct(used)
    return (LOW if should_prune(free, min_free) else ENOUGH), free
