"""Docker-disk-guard decision logic as pure functions. Repeated image builds pile up dangling layers; if
the docker data filesystem fills, initdb-style bootstraps fail and container deploys hang on a
never-healthy dependency. The decision - parse `df`, compute free %, decide whether to prune - is pure
here; the actual `docker prune` wiring lives in the consuming product.
"""
from __future__ import annotations

DEFAULT_MIN_FREE_PCT = 15


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
