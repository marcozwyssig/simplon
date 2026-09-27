"""Unit tests for disk - the docker-disk-guard parse/decision logic. Moved here from netctl - the guard is
platform's now."""
from simplon import disk


def test_used_pct_parses_the_fifth_df_field():
    # arrange: a `df -P /var/lib/docker` data line
    line = "/dev/vda1  61202244  50000000  8000000  88% /var/lib/docker"

    # act
    assert disk.used_pct(line) == 88


def test_used_pct_returns_none_for_unparseable_line():
    # arrange: too few fields / non-numeric use% (the numeric guard)
    # act / assert
    assert disk.used_pct("garbage line") is None
    assert disk.used_pct("a b c d xx% e") is None


def test_free_pct_is_hundred_minus_used():
    # arrange / act / assert
    assert disk.free_pct(88) == 12


def test_should_prune_only_below_threshold():
    # arrange / act / assert: prune when free is BELOW min (default 15)
    assert disk.should_prune(12) is True
    assert disk.should_prune(15) is False
    assert disk.should_prune(20) is False
    assert disk.should_prune(5, min_free=10) is True


# --- the verdict, which exists because an rc of 0 said four different things (si#327) -------------------
# `disk_guard` returned 0 for "no docker", "could not read df", "enough free" and "pruned" alike. That is
# this repository's hunted defect verbatim - an outcome that cannot tell "nothing to do" from "failed" -
# and it is the reason a fail-fast preflight could not be built on the guard as it stood. Each meaning
# gets its own value here, in the pure layer, where it can be asserted without a subprocess.


def test_verdict_says_enough_when_free_is_at_or_above_the_threshold():
    # arrange: 80% used -> 20% free, threshold 15
    line = "/dev/vda1  61202244  48000000  12000000  80% /var/lib/docker"

    # act
    state, free = disk.verdict(line)

    # assert
    assert (state, free) == (disk.ENOUGH, 20)


def test_verdict_says_low_below_the_threshold_and_carries_the_free_pct():
    # arrange: 88% used -> 12% free, below the default 15
    line = "/dev/vda1  61202244  50000000  8000000  88% /var/lib/docker"

    # act
    state, free = disk.verdict(line)

    # assert: the number travels with the verdict, so a caller reports it without re-parsing
    assert (state, free) == (disk.LOW, 12)


def test_verdict_is_low_at_exactly_the_documented_85_percent_used():
    # arrange: the operational threshold this was asked for - "fail fast above 85% used" - is the
    # guard's own default expressed the other way round, and the boundary is asserted rather than
    # assumed: 85% used is 15% free, which `should_prune` calls NOT low.
    # act / assert
    assert disk.verdict("a b c d 85% /")[0] == disk.ENOUGH
    assert disk.verdict("a b c d 86% /")[0] == disk.LOW


def test_verdict_says_unknown_when_the_line_cannot_be_parsed():
    # arrange: the case that used to be indistinguishable from "enough"
    # act
    state, free = disk.verdict("garbage")

    # assert: no number, and a state of its own - a preflight may not report "fine" here
    assert (state, free) == (disk.UNKNOWN, None)


def test_verdict_honours_a_custom_threshold():
    # arrange / act / assert: 20% free is low when 25 is demanded
    assert disk.verdict("a b c d 80% /", min_free=25)[0] == disk.LOW


def test_the_three_states_are_distinct():
    # arrange / act / assert: three meanings, three values - the whole point of the widening
    assert len({disk.UNKNOWN, disk.ENOUGH, disk.LOW}) == 3
