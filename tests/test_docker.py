"""Unit tests for docker - the docker CLI gate + opt-in static bootstrap (netctl#477). Moved here from
netctl - the gate is platform's now (netctl#649). No network, no real downloads, no real PATH mutation
beyond the monkeypatched environment; AAA throughout."""
import pytest

from delivery import context
from delivery import docker


def _boom(msg):
    raise SystemExit(msg)


@pytest.fixture(autouse=True)
def _product_context(tmp_path, monkeypatch):
    """Every test runs with a registered product context (the die hints + tools_bin read
    `context.current()`); default product name 'netctl'. Individual tests re-register to assert
    per-product branding. monkeypatch restores the previous context after each test."""
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("netctl", tmp_path, tmp_path / "netctl.yaml"))


def test_gate_is_a_noop_when_docker_is_on_path(monkeypatch):
    # arrange: docker resolvable, bootstrap off; any die, fetch or daemon probe would be a failure
    monkeypatch.delenv(docker.DOCKER_BOOTSTRAP_ENV, raising=False)
    monkeypatch.setattr(docker.shutil, "which", lambda tool: "/usr/bin/docker")
    monkeypatch.setattr(docker.log, "die", _boom)
    monkeypatch.setattr(docker, "_fetch_static_cli", lambda dest: _boom("fetched"))
    monkeypatch.setattr(docker, "_daemon_reachable", lambda: _boom("probed"))

    # act / assert: returns silently
    docker.ensure_docker()


def test_bootstrap_probes_the_daemon_even_when_the_cli_is_present(monkeypatch):
    # arrange: bootstrap on, CLI there, daemon answers - the gate must verify end to end (#488)
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(docker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(docker.shutil, "which", lambda tool: "/usr/bin/docker")
    monkeypatch.setattr(docker.log, "die", _boom)
    probed = []
    monkeypatch.setattr(docker, "_daemon_reachable", lambda: probed.append(1) or True)

    # act
    docker.ensure_docker()

    # assert
    assert probed == [1]


def test_gate_dies_naming_the_flag_when_docker_missing_and_bootstrap_off(monkeypatch):
    # arrange: no docker, flag unset
    monkeypatch.setattr(docker.shutil, "which", lambda tool: None)
    monkeypatch.delenv(docker.DOCKER_BOOTSTRAP_ENV, raising=False)
    monkeypatch.setattr(docker.log, "die", _boom)

    # act / assert: today's failure, but the message names both fixes (the kernel-namespaced flag)
    with pytest.raises(SystemExit, match=docker.DOCKER_BOOTSTRAP_ENV):
        docker.ensure_docker()


def test_gate_die_hint_is_product_branded_from_the_context(monkeypatch, tmp_path):
    # arrange: a DIFFERENT product registers its context; the install hint must brand to IT, proving the
    # gate reads context.current().name instead of a hardcoded netctl (the netctl#649 extraction seam)
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("infractl", tmp_path, tmp_path / "infractl.yaml"))
    monkeypatch.setattr(docker.shutil, "which", lambda tool: None)
    monkeypatch.delenv(docker.DOCKER_BOOTSTRAP_ENV, raising=False)
    monkeypatch.setattr(docker.log, "die", _boom)

    # act / assert: the hint derives the product's shim name from the context
    with pytest.raises(SystemExit, match=r"\./infractl\.sh install"):
        docker.ensure_docker()


def test_gate_dies_not_bootstraps_off_linux_even_with_the_flag(monkeypatch):
    # arrange: flag set but a non-Linux host (no static linux binary would run there)
    monkeypatch.setattr(docker.shutil, "which", lambda tool: None)
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(docker.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(docker.log, "die", _boom)
    monkeypatch.setattr(docker, "_fetch_static_cli", lambda dest: _boom("fetched"))

    # act / assert
    with pytest.raises(SystemExit, match="missing required tool: docker"):
        docker.ensure_docker()


def test_bootstrap_fetches_the_cli_prepends_path_and_probes_the_daemon(monkeypatch, tmp_path):
    # arrange: flag on, Linux, NO privileges (static-client path), no docker until the fetch
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(docker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(docker, "tools_bin", lambda: bin_dir)
    monkeypatch.setattr(docker, "_sudo_prefix", lambda: None)
    monkeypatch.setattr(docker.log, "die", _boom)

    fetched = []

    def fake_fetch(dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("#!/bin/sh\n")
        fetched.append(dest)

    monkeypatch.setattr(docker, "_fetch_static_cli", fake_fetch)
    monkeypatch.setattr(docker.shutil, "which",
                        lambda tool: str(bin_dir / "docker") if (bin_dir / "docker").is_file() else None)
    monkeypatch.setattr(docker, "_daemon_reachable", lambda: True)

    # act
    docker.ensure_docker()

    # assert: exactly one fetch into the tool dir, which is now on the process PATH
    assert fetched == [bin_dir / "docker"]
    assert str(bin_dir) in docker.os.environ["PATH"].split(docker.os.pathsep)[0]


def test_bootstrap_dies_with_the_socket_hint_when_no_daemon_is_reachable(monkeypatch, tmp_path):
    # arrange: the CLI provisions fine, but `docker version` cannot reach a daemon (unmounted socket)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "docker").write_text("#!/bin/sh\n")
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(docker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(docker, "tools_bin", lambda: bin_dir)
    monkeypatch.setattr(docker, "_sudo_prefix", lambda: None)
    monkeypatch.setattr(docker, "_daemon_reachable", lambda: False)
    monkeypatch.setattr(docker.log, "die", _boom)

    # arrange detail: which() must report absent BEFORE the bootstrap branch is taken
    calls = {"n": 0}

    def which_missing_first(tool):
        calls["n"] += 1
        return None if calls["n"] == 1 else str(bin_dir / "docker")

    monkeypatch.setattr(docker.shutil, "which", which_missing_first)

    # act / assert: the die names the socket mount
    with pytest.raises(SystemExit, match="docker.sock"):
        docker.ensure_docker()


def test_static_cli_url_maps_machine_spellings_to_dockers_arch_dirs():
    # arrange / act / assert: both spellings per arch resolve to docker's directory names
    v = docker.DOCKER_CLI_VERSION
    assert docker.static_cli_url("x86_64").endswith(f"/x86_64/docker-{v}.tgz")
    assert docker.static_cli_url("amd64").endswith(f"/x86_64/docker-{v}.tgz")
    assert docker.static_cli_url("arm64").endswith(f"/aarch64/docker-{v}.tgz")
    assert docker.static_cli_url("aarch64").endswith(f"/aarch64/docker-{v}.tgz")


def test_static_cli_url_dies_on_an_unpublished_architecture(monkeypatch):
    # arrange
    monkeypatch.setattr(docker.log, "die", _boom)

    # act / assert
    with pytest.raises(SystemExit, match="riscv128"):
        docker.static_cli_url("riscv128")


def test_socket_state_names_an_unmounted_socket(monkeypatch, tmp_path):
    # arrange: DOCKER_HOST points at a unix socket path that does not exist in this namespace
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/docker.sock")

    # act / assert
    assert "NOT MOUNTED" in docker._socket_state()


def test_socket_state_names_a_mounted_but_unwritable_socket(monkeypatch, tmp_path):
    # arrange: the socket path exists but this uid has no write access (the --group-add gap)
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")
    monkeypatch.setattr(docker.os, "access", lambda p, m: False)

    # act / assert
    assert "NOT WRITABLE" in docker._socket_state()


def test_socket_state_names_a_writable_socket_with_a_dead_daemon(monkeypatch, tmp_path):
    # arrange: socket present and writable, so only the daemon side remains
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")

    # act / assert
    assert "daemon did not answer" in docker._socket_state()


def test_sudo_prefix_maps_root_sudo_and_unprivileged(monkeypatch):
    # arrange / act / assert: root needs no prefix
    monkeypatch.setattr(docker.os, "getuid", lambda: 0)
    assert docker._sudo_prefix() == []

    # non-root with working passwordless sudo
    from delivery.run import Result as R
    monkeypatch.setattr(docker.os, "getuid", lambda: 1000)
    monkeypatch.setattr(docker, "run", lambda argv, **kw: R(rc=0, out="", err=""))
    assert docker._sudo_prefix() == ["sudo", "-n"]

    # non-root without sudo
    monkeypatch.setattr(docker, "run", lambda argv, **kw: R(rc=1, out="", err=""))
    assert docker._sudo_prefix() is None


def test_bootstrap_installs_the_engine_when_privileged(monkeypatch, tmp_path):
    # arrange: flag on, Linux, root privileges; the engine install materialises the docker binary
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(docker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(docker, "_sudo_prefix", lambda: [])
    monkeypatch.setattr(docker.log, "die", _boom)
    monkeypatch.setattr(docker, "_fetch_static_cli", lambda dest: _boom("static fetch must not run"))
    monkeypatch.setattr(docker, "_daemon_reachable", lambda: True)

    installed = []
    binary = tmp_path / "docker"

    def fake_install(pfx):
        installed.append(pfx)
        binary.write_text("#!/bin/sh\n")

    monkeypatch.setattr(docker, "_install_engine", fake_install)
    monkeypatch.setattr(docker.shutil, "which",
                        lambda tool: str(binary) if binary.is_file() else None)

    # act
    docker.ensure_docker()

    # assert: engine path taken exactly once, static client never fetched
    assert installed == [[]]


def test_bootstrap_selffixes_socket_access_when_daemon_unreachable_with_privileges(monkeypatch, tmp_path):
    # arrange: CLI present, daemon dead until the socket grant; socket exists but is unwritable
    from delivery.run import Result as R
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setenv(docker.DOCKER_BOOTSTRAP_ENV, "1")
    monkeypatch.setenv("DOCKER_HOST", f"unix://{sock}")
    monkeypatch.setattr(docker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(docker.shutil, "which", lambda tool: "/usr/bin/docker")
    monkeypatch.setattr(docker, "_sudo_prefix", lambda: ["sudo", "-n"])
    monkeypatch.setattr(docker.log, "die", _boom)
    monkeypatch.setattr(docker.os, "access", lambda p, m: False)

    state = {"granted": False}
    monkeypatch.setattr(docker, "_daemon_reachable", lambda: state["granted"])
    monkeypatch.setattr(docker, "_grant_socket_access",
                        lambda pfx: state.__setitem__("granted", True))
    calls = []
    monkeypatch.setattr(docker, "run", lambda argv, **kw: calls.append(argv) or R(rc=0, out="", err=""))

    # act
    docker.ensure_docker()

    # assert: the service (re)start was attempted and the grant made the daemon reachable
    assert ["sudo", "-n", "systemctl", "enable", "--now", "docker"] in calls
    assert state["granted"] is True
