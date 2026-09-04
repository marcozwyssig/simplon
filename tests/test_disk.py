"""Unit tests for disk - the docker-disk-guard parse/decision logic. Moved here from netctl - the guard is
platform's now."""
from delivery import disk


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
