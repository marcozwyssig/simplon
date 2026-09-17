"""Unit tests for docker - the docker CLI gate + opt-in static bootstrap (netctl#477). Moved here from
netctl - the gate is platform's now (netctl#649). No network, no real downloads, no real PATH mutation
beyond the monkeypatched environment; AAA throughout."""
import pytest

from simplon import context
from simplon import docker


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
                        context.ProductContext("asbundle", tmp_path, tmp_path / "asbundle.yaml"))
    monkeypatch.setattr(docker.shutil, "which", lambda tool: None)
    monkeypatch.delenv(docker.DOCKER_BOOTSTRAP_ENV, raising=False)
    monkeypatch.setattr(docker.log, "die", _boom)

    # act / assert: the hint derives the product's shim name from the context
    with pytest.raises(SystemExit, match=r"\./asbundle\.sh install"):
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
    from simplon.run import Result as R
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


def test_the_engine_install_puts_the_invoking_user_in_the_docker_group(monkeypatch):
    # arrange (si#87): a non-root caller with sudo. get.docker.com creates the `docker` group but puts
    # nobody in it, and a long-lived service - a CI runner agent - inherits its groups at START, so the
    # membership has to exist as part of the install rather than on ensure_docker's failure path.
    from simplon.run import Result as R
    calls = []
    monkeypatch.setattr(docker, "run", lambda argv, **kw: calls.append(argv) or R(rc=0, out="", err=""))
    monkeypatch.setattr(docker, "_invoking_user", lambda: "runner")

    # act
    docker._install_engine(["sudo", "-n"])

    # assert: the group exists and the caller is in it, both under the same privilege the install used
    assert ["sudo", "-n", "groupadd", "-f", "docker"] in calls
    assert ["sudo", "-n", "usermod", "-aG", "docker", "runner"] in calls


def test_the_engine_install_does_not_put_root_in_the_docker_group(monkeypatch):
    # arrange: already root - an empty prefix is what _sudo_prefix returns there. root reaches the socket
    # by being root, so a membership would be noise in a group whose whole purpose is non-root access.
    from simplon.run import Result as R
    calls = []
    monkeypatch.setattr(docker, "run", lambda argv, **kw: calls.append(argv) or R(rc=0, out="", err=""))
    monkeypatch.setattr(docker, "_invoking_user", lambda: "root")

    # act
    docker._install_engine([])

    # assert
    assert not [c for c in calls if "usermod" in c]


def test_bootstrap_selffixes_socket_access_when_daemon_unreachable_with_privileges(monkeypatch, tmp_path):
    # arrange: CLI present, daemon dead until the socket grant; socket exists but is unwritable
    from simplon.run import Result as R
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


# --- --user for a container that writes into a bind mount (#6, and #2's site build) ---------------------


def test_user_args_hands_the_container_the_calling_uid_and_gid():
    # arrange: a bind mount hands the container the host's inodes, so the uid the image runs as is the uid
    # that owns the output. Measured both ways: an image running as uid 1000 could not create anything in
    # a mount owned by uid 5015237 (#6, allure), and an image running as root left root-owned files the
    # caller could not delete (hugomods/hugo, #2)
    import os

    # act
    args = docker.user_args()

    # assert
    assert args == ["--user", f"{os.getuid()}:{os.getgid()}"]


def test_user_args_is_empty_where_the_host_has_no_uid_concept(monkeypatch):
    # arrange: Windows - the mount carries no ownership to get wrong, and `--user` would be nonsense
    monkeypatch.delattr(docker.os, "getuid", raising=False)

    # act / assert
    assert docker.user_args() == []


# --- the stored docker credential, asked before a push (si#200) -----------------------------------------


def _config(path, body):
    """A `~/.docker/config.json` at `path`, as the docker CLI writes one."""
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_host_with_an_entry_in_the_docker_config_counts_as_logged_in(tmp_path, monkeypatch):
    # arrange: what `docker login registry.example.com` leaves behind
    monkeypatch.setenv("DOCKER_CONFIG", str(_config(tmp_path / "cfg",
                                                    {"auths": {"registry.example.com": {"auth": "eA=="}}})))

    # act / assert
    assert docker.has_stored_login("registry.example.com") is True


def test_a_host_the_config_says_nothing_about_is_not_logged_in(tmp_path, monkeypatch):
    # arrange
    monkeypatch.setenv("DOCKER_CONFIG", str(_config(tmp_path / "cfg",
                                                    {"auths": {"ghcr.io": {"auth": "eA=="}}})))

    # act / assert
    assert docker.has_stored_login("docker.io") is False


def test_with_no_config_file_at_all_there_is_no_credential(tmp_path, monkeypatch):
    # arrange: a fresh host, or a CI runner that never logged in. The docker CLI reads this one file and
    # nothing else, so there is nowhere else a credential could be hiding
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "nothing-here"))

    # act / assert
    assert docker.has_stored_login("docker.io") is False


def test_docker_hub_is_found_under_the_index_key_the_cli_writes(tmp_path, monkeypatch):
    # arrange: `docker login` does not store Docker Hub under 'docker.io'. It stores it under docker's own
    # IndexServer constant, and a check that looked for the host name would refuse a host that IS logged in
    monkeypatch.setenv("DOCKER_CONFIG", str(_config(
        tmp_path / "cfg", {"auths": {"https://index.docker.io/v1/": {"auth": "eA=="}}})))

    # act / assert
    assert docker.has_stored_login("docker.io") is True
    assert docker.has_stored_login("index.docker.io") is True


def test_a_credential_helper_for_the_host_counts_as_a_credential(tmp_path, monkeypatch):
    # arrange: the helper holds the secret and the config holds no `auths` entry at all
    monkeypatch.setenv("DOCKER_CONFIG", str(_config(
        tmp_path / "cfg", {"credHelpers": {"docker.io": "osxkeychain"}})))

    # act / assert
    assert docker.has_stored_login("docker.io") is True


def test_a_global_credential_store_is_unknowable_here_so_it_does_not_refuse(tmp_path, monkeypatch):
    # arrange: with a `credsStore` every credential lives in the helper, and the file says nothing about
    # which hosts it holds. Refusing on that would be refusing on a guess, and a guess that stops a working
    # publish is worse than no check
    monkeypatch.setenv("DOCKER_CONFIG", str(_config(tmp_path / "cfg", {"credsStore": "desktop"})))

    # act / assert
    assert docker.has_stored_login("docker.io") is True


def test_a_config_that_cannot_be_read_is_not_read_as_absence(tmp_path, monkeypatch):
    # arrange: broken JSON says nothing about credentials either way
    path = tmp_path / "cfg"
    path.mkdir()
    (path / "config.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("DOCKER_CONFIG", str(path))

    # act / assert
    assert docker.has_stored_login("docker.io") is True
