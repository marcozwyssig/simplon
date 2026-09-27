"""Unit tests for simplon.diskguard.disk_guard - the docker-disk probe/decide/prune engine. A fake
Host feeds canned `df` Results (no real subprocess, no docker); the prune commands are captured via a
patched run. AAA throughout. (Moved here from netctl's guard tests - the guard mechanism is platform's now;
the netctl-side toggle stays in netctl.)"""
from simplon import diskguard
from simplon.run import Result


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


# --- the preflight, which FAILS instead of pruning (si#327) ---------------------------------------------
# A guard prunes and carries on; a preflight decides whether a job may start at all. They are different
# answers to different questions, so they are different functions - and the preflight is the one that may
# return non-zero, because "this machine is too full to build on" is exactly what a job needs told BEFORE
# it spends eight minutes discovering it as `E: You don't have enough free space in /var/cache/apt`.


def test_preflight_passes_when_there_is_room():
    # arrange: 70% used -> 30% free
    host = _FakeHost(Result(0, "/dev/vda1 100 70 30 70% /var/lib/docker", ""))

    # act
    rc = diskguard.preflight(host)

    # assert
    assert rc == 0


def test_preflight_fails_fast_when_the_disk_is_too_full():
    # arrange: 90% used -> 10% free, below the 15% default (i.e. above the 85%-used line)
    host = _FakeHost(Result(0, "/dev/vda1 100 90 10 90% /var/lib/docker", ""))

    # act
    rc = diskguard.preflight(host)

    # assert: NON-zero - the whole point. A job on this machine is going to die in a later step.
    assert rc == 1


def test_preflight_needs_no_docker_because_df_does_not(monkeypatch):
    # arrange: no docker binary at all. The guard no-ops here (it cannot prune without docker), but a
    # preflight only reads `df`, and a machine whose engine has not been bootstrapped yet still has a
    # disk that can be full. Measured shape: DELIVERY_DOCKER_BOOTSTRAP installs the engine INSIDE the
    # job, so the first step runs before docker exists.
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: None)
    host = _FakeHost(Result(0, "/dev/vda1 100 90 10 90% /", ""))

    # act
    rc = diskguard.preflight(host)

    # assert: it still measured, and it still refused
    assert rc == 1
    assert host.calls, "a preflight must probe the disk even with no docker on the machine"


def test_preflight_falls_back_to_the_root_filesystem_when_the_data_dir_is_absent():
    # arrange: first probe fails (no /var/lib/docker yet - pre-bootstrap), second answers for `/`
    host = _FakeHost(Result(1, "", "df: /var/lib/docker: No such file or directory"),
                     Result(0, "/dev/vda1 100 90 10 90% /", ""))

    # act
    rc = diskguard.preflight(host)

    # assert: it did not give up on the first miss, and the fallback verdict stands
    assert rc == 1
    assert len(host.calls) == 2
    assert host.calls[0].startswith("df -P /var/lib/docker")
    assert host.calls[1].startswith("df -P / ")


def test_preflight_does_not_pass_silently_when_it_cannot_measure(monkeypatch):
    # arrange: both probes unparseable - the case that used to be indistinguishable from a healthy disk
    said: list[str] = []
    monkeypatch.setattr(diskguard.log, "warn", lambda msg: said.append(msg))
    host = _FakeHost(Result(0, "garbage", ""), Result(0, "garbage", ""))

    # act
    rc = diskguard.preflight(host)

    # assert: it does NOT fail the job on an unreadable df - a preflight that blocks every build because
    # `df` changed its output would be worse than the defect - but it SAYS SO, loudly, which is the half
    # that was missing.
    assert rc == 0
    assert said, "an unmeasurable disk must be reported, not passed over"


def test_preflight_honours_a_custom_threshold():
    # arrange: 20% free, and 25 demanded
    host = _FakeHost(Result(0, "/dev/vda1 100 80 20 80% /var/lib/docker", ""))

    # act / assert
    assert diskguard.preflight(host, min_free_pct=25) == 1


# --- the cleanup, which runs after the verdict is already known -----------------------------------------


def test_cleanup_prunes_the_build_cache_with_an_age_filter(monkeypatch):
    # arrange
    ran: list[list[str]] = []
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: ran.append(argv) or Result(0, "", ""))

    # act
    rc = diskguard.cleanup()

    # assert: the age filter is what keeps a warm cache warm - an unfiltered -af on every job would
    # trade a full disk for a cold build every time.
    assert rc == 0
    assert ran == [["docker", "builder", "prune", "-af", "--filter", "until=24h"]]


def test_cleanup_does_not_touch_volumes(monkeypatch):
    # arrange: a runner with persistent volumes would lose them - so the flag is asserted ABSENT
    ran: list[list[str]] = []
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: ran.append(argv) or Result(0, "", ""))

    # act
    diskguard.cleanup()

    # assert
    assert not any("--volumes" in arg for argv in ran for arg in argv)


def test_cleanup_is_a_noop_without_docker(monkeypatch):
    # arrange
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: None)
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: (_ for _ in ()).throw(
        AssertionError("cleanup must not shell out to a docker that is not there")))

    # act / assert
    assert diskguard.cleanup() == 0


def test_cleanup_reports_a_refusing_docker_instead_of_swallowing_it(monkeypatch):
    # arrange: docker is there and the prune fails
    monkeypatch.setattr(diskguard.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(diskguard, "run", lambda argv, **kw: Result(1, "", "permission denied"))

    # act
    rc = diskguard.cleanup()

    # assert: non-zero. The WORKFLOW decides this is not fatal (`continue-on-error`); the command does
    # not decide it by returning 0 for a prune that did not happen.
    assert rc == 1
