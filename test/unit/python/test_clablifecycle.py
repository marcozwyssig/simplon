"""Unit tests for delivery.clablifecycle - the dev-lab lifecycle substrate (netctl#731 Strand 3, extracted
from netctl's orchestrator.lab). Covers the load-bearing deploy sequence + retry + verdict, the OOB-bridge
apply over an INJECTED bridge list, teardown + name-prefix sweep, and the cross-process degraded channel
the product's finish phase reads. No real VM/docker: a fake Host records every call. AAA throughout."""
from pathlib import Path

import pytest

from delivery import clablifecycle, degraded
from delivery.clablifecycle import BringUpSpec
from delivery.run import Result


class _FakeHost:
    """Records `sh` scripts + `docker` argvs and answers each with a scripted Result. `is_darwin` is
    injectable so the _clab argv-shape branch is exercised on either platform without a real host."""

    def __init__(self, *, is_darwin=False, sh_ok=True, docker_out="", docker_ok=True):
        self.is_darwin = is_darwin
        self._sh_ok = sh_ok
        self._docker_out = docker_out
        self._docker_ok = docker_ok
        self.sh_calls: list[str] = []
        self.docker_calls: list[tuple[str, ...]] = []

    def sh(self, script, *, capture=True):
        self.sh_calls.append(script)
        return Result(rc=0 if self._sh_ok else 1, out="", err="")

    def docker(self, *args, capture=True):
        self.docker_calls.append(args)
        return Result(rc=0 if self._docker_ok else 1, out=self._docker_out, err="")


def _spec(**over) -> BringUpSpec:
    base = dict(
        output_dir=Path("/lab/out"),
        topology_file="netctl.clab.yml",
        topology_path=Path("/lab/out/netctl.clab.yml"),
        container_prefix="clab-netctl-",
        mgmt_network="netctl-mgmt",
        bridges=("oob-zh", "oob-be"),
        deploy_retries=3,
        amd64_emulation=False,
    )
    base.update(over)
    return BringUpSpec(**base)


@pytest.fixture(autouse=True)
def _reset_degraded():
    # each test starts with an empty in-memory degraded collector (it is process-global)
    degraded.reset()
    yield
    degraded.reset()


# --- _clab argv shape -------------------------------------------------------------------------------

def test_clab_wraps_with_sudo_and_cd_into_the_output_dir_on_darwin():
    # arrange: a macOS host  act
    host = _FakeHost(is_darwin=True)
    clablifecycle._clab(host, ["deploy", "-t", "netctl.clab.yml"], _spec())
    # assert: cd into the rendered output dir + sudo containerlab (host.sh adds the colima hop)
    assert host.sh_calls == ["cd /lab/out && sudo containerlab deploy -t netctl.clab.yml"]


def test_clab_honours_the_SUDO_override_on_linux(monkeypatch):
    # arrange: a rootless-docker CI runner sets SUDO="" so clab runs without sudo
    monkeypatch.setenv("SUDO", "")
    host = _FakeHost(is_darwin=False)
    # act
    clablifecycle._clab(host, ["destroy", "-t", "netctl.clab.yml", "--cleanup"], _spec())
    # assert: no sudo binary in the command (the empty $SUDO leaves the historical double space verbatim -
    # byte-identical to netctl's pre-extraction _clab); still cd into the output dir
    assert host.sh_calls == ["cd /lab/out &&  containerlab destroy -t netctl.clab.yml --cleanup"]


# --- OOB bridges over the injected list -------------------------------------------------------------

def test_oob_up_applies_the_snippet_for_each_injected_bridge():
    # arrange: two bridges, all snippets succeed  act
    host = _FakeHost(sh_ok=True)
    clablifecycle.oob_up(host, ("oob-zh", "oob-be"))
    # assert: one host.sh per bridge, each the idempotent create-and-up snippet; no degradation
    assert len(host.sh_calls) == 2
    assert "ip link add oob-zh type bridge" in host.sh_calls[0]
    assert "ip link add oob-be type bridge" in host.sh_calls[1]
    assert degraded.items() == []


def test_oob_up_records_a_degraded_note_when_a_bridge_cannot_be_created():
    # arrange (negative): the snippet fails -> degraded, not fatal
    host = _FakeHost(sh_ok=False)
    # act
    clablifecycle.oob_up(host, ("oob-zh",))
    # assert: a degraded condition names the bridge; the run did not raise
    items = degraded.items()
    assert len(items) == 1
    assert "oob-zh" in items[0]


def test_oob_down_removes_each_injected_bridge():
    # arrange / act
    host = _FakeHost()
    clablifecycle.oob_down(host, ("oob-zh", "oob-be"))
    # assert: one down snippet per bridge
    assert len(host.sh_calls) == 2
    assert "ip link del oob-zh" in host.sh_calls[0]
    assert "ip link del oob-be" in host.sh_calls[1]


# --- container_count --------------------------------------------------------------------------------

def test_container_count_counts_only_non_blank_ids():
    # arrange: docker ps -q returns three ids with a trailing blank line
    host = _FakeHost(docker_out="a\nb\nc\n")
    # act
    n = clablifecycle.container_count(host, "clab-netctl-")
    # assert
    assert n == 3
    assert host.docker_calls[0] == ("ps", "--filter", "name=clab-netctl-", "-q")


# --- deploy: the load-bearing sequence + verdict ----------------------------------------------------

class _DeployHost(_FakeHost):
    """A host whose `_clab` deploys fail for the first `fail_attempts` attempts, then succeed. Container
    count is scripted for the verdict path."""

    def __init__(self, *, fail_attempts=0, count_after_fail=0, is_darwin=False):
        super().__init__(is_darwin=is_darwin)
        self._fail_attempts = fail_attempts
        self._count_after_fail = count_after_fail
        self.deploy_attempts = 0

    def sh(self, script, *, capture=True):
        self.sh_calls.append(script)
        if "containerlab deploy" in script:
            self.deploy_attempts += 1
            ok = self.deploy_attempts > self._fail_attempts
            return Result(rc=0 if ok else 1, out="", err="")
        return Result(rc=0, out="", err="")

    def docker(self, *args, capture=True):
        self.docker_calls.append(args)
        # container_count uses `ps ... -q`
        out = "\n".join(str(i) for i in range(self._count_after_fail)) if args[:1] == ("ps",) else ""
        return Result(rc=0, out=out, err="")


def test_deploy_succeeds_first_try_and_records_no_degradation():
    # arrange: clab deploys cleanly on the first attempt
    host = _DeployHost(fail_attempts=0)
    # act
    rc = clablifecycle.deploy(host, _spec())
    # assert: rc 0, exactly one deploy attempt, no degradation
    assert rc == 0
    assert host.deploy_attempts == 1
    assert degraded.items() == []


def test_deploy_retries_until_it_succeeds():
    # arrange: the first two attempts fail (the x86 binfmt-flush race), the third succeeds
    host = _DeployHost(fail_attempts=2)
    # act
    rc = clablifecycle.deploy(host, _spec(deploy_retries=3))
    # assert: it retried up to success, no degradation
    assert rc == 0
    assert host.deploy_attempts == 3
    assert degraded.items() == []


def test_deploy_degrades_when_it_never_completes_but_some_containers_are_up():
    # arrange: every attempt fails BUT some containers are up (the accepted partial-deploy flake floor)
    host = _DeployHost(fail_attempts=99, count_after_fail=18)
    # act
    rc = clablifecycle.deploy(host, _spec(deploy_retries=3))
    # assert: NOT fatal - returns 0 and records a degraded note for the verdict phase
    assert rc == 0
    assert host.deploy_attempts == 3
    items = degraded.items()
    assert len(items) == 1 and "did not complete cleanly" in items[0]


def test_deploy_dies_when_it_never_completes_and_no_containers_exist(monkeypatch):
    # arrange (negative): every attempt fails AND nothing is up -> fatal (a missing image / bad topology)
    host = _DeployHost(fail_attempts=99, count_after_fail=0)

    def boom(msg):
        raise SystemExit(msg)

    monkeypatch.setattr(clablifecycle.log, "die", boom)
    # act / assert: a dead deploy must never reach a false 'lab up'
    with pytest.raises(SystemExit):
        clablifecycle.deploy(host, _spec(deploy_retries=2))


def test_deploy_registers_amd64_emulation_and_the_watchdog_only_when_the_flag_is_set(monkeypatch):
    # arrange: a lab WITH an x86 kind -> amd64 emulation + the binfmt watchdog must bracket the deploy
    order: list[str] = []
    monkeypatch.setattr(clablifecycle.labhost, "ensure_amd64_emulation", lambda h: order.append("amd64"))
    monkeypatch.setattr(clablifecycle.labhost, "binfmt_watchdog_start", lambda h: order.append("wd-start"))
    monkeypatch.setattr(clablifecycle.labhost, "binfmt_watchdog_stop", lambda h: order.append("wd-stop"))
    host = _DeployHost(fail_attempts=0)
    orig_sh = host.sh

    def tracking_sh(script, *, capture=True):
        if "containerlab deploy" in script:
            order.append("deploy")
        return orig_sh(script, capture=capture)

    host.sh = tracking_sh
    # act
    clablifecycle.deploy(host, _spec(amd64_emulation=True))
    # assert: LOAD-BEARING order - amd64 emulation, watchdog start, deploy, watchdog stop
    assert order == ["amd64", "wd-start", "deploy", "wd-stop"]


def test_deploy_skips_amd64_emulation_when_the_lab_has_no_x86_kind(monkeypatch):
    # arrange (negative): a native-only lab -> the substrate must not touch amd64 emulation at all
    def boom(*a, **k):
        raise AssertionError("amd64 emulation must not run when the lab carries no x86 kind")

    monkeypatch.setattr(clablifecycle.labhost, "ensure_amd64_emulation", boom)
    monkeypatch.setattr(clablifecycle.labhost, "binfmt_watchdog_start", boom)
    monkeypatch.setattr(clablifecycle.labhost, "binfmt_watchdog_stop", boom)
    host = _DeployHost(fail_attempts=0)
    # act / assert (no raise == pass)
    assert clablifecycle.deploy(host, _spec(amd64_emulation=False)) == 0


# --- the cross-process degraded channel (the contract that must survive verbatim) -------------------

def test_deploy_degradation_is_readable_by_up_verdict_across_processes(tmp_path, monkeypatch):
    # arrange: simulate the two subprocesses (`_up deploy` then `_up finish`) sharing one degraded file -
    # deploy writes to DELIVERY_DEGRADED_FILE, a fresh-process up_verdict reads the union back.
    degfile = tmp_path / "degraded"
    monkeypatch.setenv(degraded.DEGRADED_FILE_ENV, str(degfile))
    host = _DeployHost(fail_attempts=99, count_after_fail=18)
    # act (process 1): a partial deploy appends its degradation to the shared file
    clablifecycle.deploy(host, _spec(deploy_retries=1))
    # simulate a NEW process for the verdict: only the file carries the state
    degraded.reset()
    rc = clablifecycle.up_verdict(strict=False)
    # assert: the verdict still saw the deploy-phase degradation (via the file), lab up (degraded) -> 0
    assert rc == 0
    assert any("did not complete cleanly" in ln for ln in degfile.read_text().splitlines())


# --- down + sweep -----------------------------------------------------------------------------------

def test_down_destroys_when_the_rendered_topology_exists_then_sweeps_and_downs_bridges(tmp_path):
    # arrange: the rendered topology file exists
    topo = tmp_path / "netctl.clab.yml"
    topo.write_text("name: netctl\n")
    host = _FakeHost()
    spec = _spec(topology_path=topo, output_dir=tmp_path)
    # act
    rc = clablifecycle.down(host, spec)
    # assert: clab destroy ran (via host.sh), the mgmt network was swept, and both bridges came down
    assert rc == 0
    assert any("containerlab destroy" in s and "--cleanup" in s for s in host.sh_calls)
    assert ("network", "rm", "netctl-mgmt") in host.docker_calls
    assert any("ip link del oob-zh" in s for s in host.sh_calls)


def test_down_skips_clab_destroy_when_no_rendered_topology_but_still_sweeps():
    # arrange (#525): a fresh checkout has no rendered topology - clab destroy must be SKIPPED (else clab
    # treats the name as a URL and destroys nothing while reporting OK), but the name-sweep must still run
    host = _FakeHost()
    spec = _spec(topology_path=Path("/does/not/exist/netctl.clab.yml"))
    # act
    rc = clablifecycle.down(host, spec)
    # assert: no clab destroy; the by-name sweep (network rm) still ran
    assert rc == 0
    assert not any("containerlab destroy" in s for s in host.sh_calls)
    assert ("network", "rm", "netctl-mgmt") in host.docker_calls


def test_sweep_removes_leftover_containers_by_name_prefix_and_the_mgmt_network():
    # arrange: two leftover containers match the prefix
    host = _FakeHost(docker_out="c1 c2")
    # act
    clablifecycle.sweep_leftovers(host, _spec())
    # assert: it force-removes the matched containers, then rms the mgmt network
    assert ("ps", "-aq", "--filter", "name=clab-netctl-") in host.docker_calls
    assert ("rm", "-f", "c1", "c2") in host.docker_calls
    assert ("network", "rm", "netctl-mgmt") in host.docker_calls


# --- up_verdict -------------------------------------------------------------------------------------

def test_up_verdict_is_lab_up_when_nothing_is_degraded():
    # arrange: a clean run  act / assert
    assert clablifecycle.up_verdict(strict=False) == 0


def test_up_verdict_warns_but_returns_zero_on_degraded_without_strict():
    # arrange: a degraded condition, non-strict
    degraded.add("something is degraded")
    # act
    rc = clablifecycle.up_verdict(strict=False)
    # assert: reported but not fatal
    assert rc == 0


def test_up_verdict_dies_on_degraded_when_strict(monkeypatch):
    # arrange (negative): strict mode promotes any degradation to a failure
    degraded.add("something is degraded")

    def boom(msg):
        raise SystemExit(msg)

    monkeypatch.setattr(clablifecycle.log, "die", boom)
    # act / assert
    with pytest.raises(SystemExit):
        clablifecycle.up_verdict(strict=True)
