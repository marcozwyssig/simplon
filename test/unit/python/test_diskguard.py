"""Unit tests for platformcore.diskguard.disk_guard - the docker-disk probe/decide/prune engine. A fake
Host feeds canned `df` Results (no real subprocess, no docker); the prune commands are captured via a
patched run. AAA throughout. (Moved here from netctl's guard tests - the guard mechanism is platform's now;
the netctl-side toggle stays in netctl.)"""
from platformcore import diskguard
from platformcore.run import Result


class _FakeHost:
    """Returns the queued `df` Results in order (then a benign default), recording each probe."""

    def __init__(self, *results: Result) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    def sh(self, script: str, *, capture: bool = True) -> Result:
        self.calls.append(script)
        return self._results.pop(0) if self._results else Result(0, "", "")


def test_disk_guard_is_a_noop_when_docker_is_absent(monkeypatch):
    # arrange: no docker binary on PATH
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: None)
    host = _FakeHost()

    # act
    rc = diskguard.disk_guard(host)

    # assert: returns 0 and never probed the disk
    assert rc == 0
    assert host.calls == []


def test_disk_guard_skips_when_df_line_is_unparseable(monkeypatch):
    # arrange: docker present, but df yields no numeric capacity field
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    pruned: list[list[str]] = []
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: pruned.append(argv) or Result(0, "", ""))
    host = _FakeHost(Result(0, "garbage line without fields", ""))

    # act
    rc = diskguard.disk_guard(host)

    # assert: skipped silently, no prune
    assert rc == 0
    assert pruned == []


def test_disk_guard_prunes_when_free_below_threshold(monkeypatch):
    # arrange: 8% free (< 15%) -> must prune; second df shows recovered space
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    pruned: list[list[str]] = []
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: pruned.append(argv) or Result(0, "", ""))
    host = _FakeHost(
        Result(0, "overlay 100 92 8 92% /var/lib/docker", ""),
        Result(0, "overlay 100 40 60 40% /var/lib/docker", ""),
    )

    # act
    rc = diskguard.disk_guard(host)

    # assert: both prune commands ran
    assert rc == 0
    assert ["docker", "image", "prune", "-f"] in pruned
    assert ["docker", "builder", "prune", "-f"] in pruned


def test_disk_guard_does_not_prune_when_enough_free(monkeypatch):
    # arrange: 60% free (>= 15%) -> no prune
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    pruned: list[list[str]] = []
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: pruned.append(argv) or Result(0, "", ""))
    host = _FakeHost(Result(0, "overlay 100 40 60 40% /var/lib/docker", ""))

    # act
    rc = diskguard.disk_guard(host)

    # assert
    assert rc == 0
    assert pruned == []


def test_disk_guard_honours_a_custom_min_free_pct(monkeypatch):
    # arrange: 20% free; default 15% would NOT prune, but a 25% threshold must
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    pruned: list[list[str]] = []
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: pruned.append(argv) or Result(0, "", ""))
    host = _FakeHost(
        Result(0, "overlay 100 80 20 80% /var/lib/docker", ""),
        Result(0, "overlay 100 50 50 50% /var/lib/docker", ""),
    )

    # act
    rc = diskguard.disk_guard(host, min_free_pct=25)

    # assert: the higher threshold triggered a prune
    assert rc == 0
    assert ["docker", "image", "prune", "-f"] in pruned
