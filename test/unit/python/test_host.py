"""Unit tests for the Host execution router (platformcore.host): on macOS the lab commands are wrapped in
`colima ssh --`, on Linux they run directly. The OS is injected via os_name so the routing is testable on
any host, with no real subprocess. AAA throughout."""
from platformcore import host


def test_host_wraps_docker_in_colima_ssh_on_darwin(monkeypatch):
    # arrange: a Darwin host; capture the argv that would be run
    captured = {}
    monkeypatch.setattr(host, "run", lambda argv, capture=True: captured.setdefault("argv", argv))
    h = host.Host(os_name="Darwin")

    # act
    h.docker("ps")

    # assert: the docker call is routed through the Colima VM
    assert captured["argv"] == ["colima", "ssh", "--", "docker", "ps"]


def test_host_runs_docker_directly_on_linux(monkeypatch):
    # arrange: a Linux host
    captured = {}
    monkeypatch.setattr(host, "run", lambda argv, capture=True: captured.setdefault("argv", argv))
    h = host.Host(os_name="Linux")

    # act
    h.docker("ps")

    # assert: docker runs on the local daemon, no colima prefix
    assert captured["argv"] == ["docker", "ps"]


def test_host_wraps_interactive_argv_via_wrap_on_darwin(monkeypatch):
    # arrange: a Darwin host; exec_shell inherits the TTY (capture=False) and must be VM-wrapped
    captured = {}
    monkeypatch.setattr(host, "run", lambda argv, capture=True: captured.setdefault("argv", argv))
    h = host.Host(os_name="Darwin")

    # act
    h.exec_shell("clab-node")

    # assert: the docker exec is prefixed with the colima ssh hop
    assert captured["argv"][:4] == ["colima", "ssh", "--", "docker"]
    assert "clab-node" in captured["argv"]
