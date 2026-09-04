"""Unit tests for the Host execution router (delivery.host): on macOS the lab commands are wrapped in
`colima ssh --`, on Linux they run directly. The OS is injected via os_name so the routing is testable on
any host, with no real subprocess. AAA throughout.

Plus the lab-host reachability probe (netctl#1031): the classification must come from the DOCKER SOCKET,
never from colima's status record, which read `Stopped` on a live VM serving 43 lab containers
(netctl#1002)."""
from __future__ import annotations

import os
import socket
import tempfile
import threading

import pytest

from delivery import host
from delivery.run import Result


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


# --- netctl#1031: the lab-host classification comes from the docker socket -------------------------
#
# The netctl#1002 incident: `colima list`/`colima status` reported the VM `Stopped` while the docker
# daemon served 43 lab containers. On macOS every Host call tunnels through `colima ssh`, which reads
# the same record, so the routing failed too - and every command that treated that as "the host is gone"
# was wrong about WHICH fault it had, and therefore about the fix.

_STALE_RECORD = 'level=fatal msg="colima not running"'


def _routing_refuses(_argv, capture=True):
    """The routed `docker ps -q` as it failed in the netctl#1002 incident: colima's ssh hop refuses,
    quoting the stale status record."""
    return Result(rc=1, out="", err=f"{_STALE_RECORD}\n")


def test_a_stopped_status_record_is_classified_reachable_when_the_docker_socket_answers(monkeypatch):
    # arrange: the ssh hop refuses (stale record), but the daemon socket answers /_ping
    monkeypatch.setattr(host, "run", _routing_refuses)
    monkeypatch.setattr(host, "socket_answers", lambda path, timeout=2.0: True)
    h = host.Host(os_name="Darwin")

    # act
    probe = h.probe()

    # assert: the host is REACHABLE (the daemon is alive) but NOT actionable (the hop still refuses),
    # and the cause names the stale record plus the restart-do-not-start remedy
    assert probe.reach is host.HostReach.SOCKET_ONLY
    assert probe.reach.reachable is True
    assert probe.reach.actionable is False
    assert "status record is stale" in probe.cause
    assert "colima restart" in probe.cause and "do NOT `colima start`" in probe.cause
    assert _STALE_RECORD in probe.cause


def test_a_host_whose_docker_socket_stays_silent_is_classified_unreachable(monkeypatch):
    # arrange: the routing refuses AND the socket does not answer - a genuinely stopped VM
    monkeypatch.setattr(host, "run", _routing_refuses)
    monkeypatch.setattr(host, "socket_answers", lambda path, timeout=2.0: False)
    h = host.Host(os_name="Darwin")

    # act
    probe = h.probe()

    # assert: unreachable, and the remedy is to START the VM, not to restart a live one
    assert probe.reach is host.HostReach.UNREACHABLE
    assert probe.reach.reachable is False
    assert probe.reach.actionable is False
    assert "did not answer either" in probe.cause and "colima start" in probe.cause
    assert "colima restart" not in probe.cause


def test_the_probe_never_asks_colima_list_or_colima_status(monkeypatch):
    # arrange: record every argv the probe runs, with the routing refusing so the fallback path runs too
    seen: list[list[str]] = []

    def record(argv, capture=True):
        seen.append(argv)
        return Result(rc=1, out="", err=f"{_STALE_RECORD}\n")

    monkeypatch.setattr(host, "run", record)
    monkeypatch.setattr(host, "socket_answers", lambda path, timeout=2.0: True)

    # act
    host.Host(os_name="Darwin").probe()

    # assert: NOTHING in the classification reads colima's status record - not `colima status`, not
    # `colima list`; the only subprocess is the read-only routed `docker ps -q`
    assert seen == [["colima", "ssh", "--", "docker", "ps", "-q"]]
    assert not [argv for argv in seen if "list" in argv or "status" in argv]


def test_a_healthy_host_is_classified_routed_without_ever_opening_the_socket(monkeypatch):
    # arrange: the routed docker call answers; the socket probe must not be needed at all
    monkeypatch.setattr(host, "run", lambda argv, capture=True: Result(rc=0, out="abc123\n", err=""))
    probed: list[str] = []
    monkeypatch.setattr(host, "socket_answers", lambda path, timeout=2.0: probed.append(path) or True)

    # act
    probe = host.Host(os_name="Linux").probe()

    # assert: ROUTED, no cause to report, and the extra probe never ran (one docker call on a healthy host)
    assert probe.reach is host.HostReach.ROUTED
    assert probe.reach.actionable is True and probe.cause == ""
    assert probed == []


def test_a_routed_failure_without_any_message_still_names_a_cause(monkeypatch):
    # arrange: docker exits non-zero and prints nothing at all, socket silent too
    monkeypatch.setattr(host, "run", lambda argv, capture=True: Result(rc=127, out="", err=""))
    monkeypatch.setattr(host, "socket_answers", lambda path, timeout=2.0: False)

    # act
    probe = host.Host(os_name="Linux").probe()

    # assert: the operator is never left with an empty parenthesis
    assert probe.reach is host.HostReach.UNREACHABLE
    assert "exited 127" in probe.cause


def test_classify_reachability_is_pure_and_keys_only_on_the_two_probes():
    # arrange / act / assert: the full truth table, with no host and no I/O
    assert host.classify_reachability(routed_ok=True, socket_ok=True) is host.HostReach.ROUTED
    assert host.classify_reachability(routed_ok=True, socket_ok=False) is host.HostReach.ROUTED
    assert host.classify_reachability(routed_ok=False, socket_ok=True) is host.HostReach.SOCKET_ONLY
    assert host.classify_reachability(routed_ok=False, socket_ok=False) is host.HostReach.UNREACHABLE


# --- which socket gets opened ------------------------------------------------------------------------

def test_docker_socket_path_prefers_an_explicit_unix_docker_host():
    # arrange: an operator-set DOCKER_HOST wins over any default
    env = {"DOCKER_HOST": "unix:///run/user/1000/docker.sock"}

    # act / assert: on either OS
    assert host.docker_socket_path(darwin=True, environ=env) == "/run/user/1000/docker.sock"
    assert host.docker_socket_path(darwin=False, environ=env) == "/run/user/1000/docker.sock"


def test_docker_socket_path_falls_back_to_the_colima_profile_socket_on_darwin():
    # arrange: no DOCKER_HOST, a non-default colima profile
    env = {"COLIMA_PROFILE": "netctl"}

    # act
    path = host.docker_socket_path(darwin=True, environ=env)

    # assert: the profile's host-side socket, which is reachable WITHOUT the colima ssh hop
    assert path.endswith("/.colima/netctl/docker.sock")
    assert not path.startswith("~")               # expanded, so it can actually be opened


def test_docker_socket_path_uses_the_default_daemon_socket_on_linux():
    # arrange / act: no DOCKER_HOST on a native Linux lab host
    path = host.docker_socket_path(darwin=False, environ={})

    # assert
    assert path == host.DEFAULT_SOCKET


def test_docker_socket_path_is_empty_for_a_non_unix_docker_host():
    # arrange: a tcp:// endpoint - there is no local socket to open
    env = {"DOCKER_HOST": "tcp://10.0.0.5:2375"}

    # act / assert: empty, so socket_answers cannot claim a reachable daemon it never asked
    assert host.docker_socket_path(darwin=True, environ=env) == ""
    assert host.socket_answers("") is False


# --- the socket probe itself, against a real AF_UNIX listener ---------------------------------------

@pytest.fixture
def sock_dir():
    """A SHORT-pathed temp dir: an AF_UNIX path is capped at ~104 bytes on macOS, which pytest's own
    tmp_path routinely exceeds."""
    with tempfile.TemporaryDirectory(prefix="dh") as tmp:
        yield tmp


def _serve_once(path: str, reply: bytes) -> threading.Thread:
    """A one-shot AF_UNIX listener that answers the first connection with `reply`."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)

    def serve():
        with srv, srv.accept()[0] as conn:
            conn.recv(1024)
            conn.sendall(reply)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def test_socket_answers_is_true_when_the_daemon_answers_the_ping(sock_dir):
    # arrange: a listener on a real unix socket that answers /_ping the way dockerd does
    sock_path = os.path.join(sock_dir, "d.sock")
    thread = _serve_once(sock_path, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")

    # act
    answered = host.socket_answers(sock_path, timeout=5.0)

    # assert
    thread.join(timeout=5.0)
    assert answered is True


def test_socket_answers_is_false_when_the_socket_serves_something_that_is_not_a_daemon(sock_dir):
    # arrange: a listener that answers, but not with a 200 (a stale/foreign socket)
    sock_path = os.path.join(sock_dir, "d.sock")
    thread = _serve_once(sock_path, b"HTTP/1.1 500 Internal Server Error\r\n\r\n")

    # act
    answered = host.socket_answers(sock_path, timeout=5.0)

    # assert: an answering socket is not the same as an answering DAEMON
    thread.join(timeout=5.0)
    assert answered is False


def test_socket_answers_is_false_when_no_socket_exists_at_the_path(sock_dir):
    # arrange: a path where colima would publish its socket on a VM that was never started
    sock_path = os.path.join(sock_dir, "absent", "d.sock")

    # act / assert: a missing socket is a refusal, never an exception
    assert host.socket_answers(sock_path, timeout=1.0) is False
