"""Unit tests for ports - freeing a TCP port before a dev server binds it (platform#43).

No real lsof, no real signals, no real waiting: `run` is faked with a scripted sequence of lsof answers,
`os.kill` records what it was asked to do, and the sleep is a list append. Every case uses TWO listeners
with different pids so a wrong implementation cannot pass by signalling "the pid" or "all of them".
AAA throughout.
"""
import signal

import pytest

from delivery import ports
from delivery.run import Result


@pytest.fixture
def fake_lsof(monkeypatch):
    """Script the answers `lsof` gives, one per call, and record the argv it was asked with."""
    state = {"answers": [], "argv": []}

    def _run(argv, **_kwargs):
        state["argv"].append(argv)
        out = state["answers"].pop(0) if state["answers"] else ""
        return Result(rc=0 if out else 1, out=out, err="")

    monkeypatch.setattr(ports, "run", _run)
    return state


@pytest.fixture
def signals(monkeypatch):
    """Record every (pid, signal) this module sends instead of sending it."""
    sent = []
    monkeypatch.setattr(ports.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    return sent


# --- reading lsof's answer ---------------------------------------------------------------------------

def test_the_pids_are_read_in_the_order_lsof_reports_them():
    # arrange / act
    pids = ports.parse_pids("4242\n17\n")

    # assert
    assert pids == [4242, 17]


def test_a_repeated_pid_is_reported_once():
    # arrange / act
    pids = ports.parse_pids("4242\n17\n4242\n")

    # assert
    assert pids == [4242, 17]


def test_a_non_numeric_line_is_not_a_pid():
    # arrange: a warning that reached stdout must not become an int() traceback
    pids = ports.parse_pids("lsof: WARNING: can't stat() nfs\n4242\n")

    # act / assert
    assert pids == [4242]


def test_nothing_listening_reads_as_no_pids():
    # arrange / act / assert
    assert ports.parse_pids("") == []


def test_the_probe_asks_lsof_for_the_listening_tcp_sockets_of_that_port(fake_lsof):
    # arrange
    fake_lsof["answers"] = ["4242\n"]

    # act
    found = ports.listeners(3000)

    # assert: listeners only - a client connected TO that port is somebody else's business
    assert found == [4242]
    assert fake_lsof["argv"] == [["lsof", "-ti", "tcp:3000", "-sTCP:LISTEN"]]


# --- freeing the port --------------------------------------------------------------------------------

def test_a_free_port_is_left_alone(fake_lsof, signals):
    # arrange: nothing is listening
    fake_lsof["answers"] = [""]

    # act
    stopped = ports.free(8000, sleep=lambda _s: None)

    # assert: nothing signalled, nothing to report
    assert stopped == []
    assert signals == []


def test_a_missing_lsof_is_a_no_op_and_not_an_error(monkeypatch, signals):
    # arrange: `lsof` is not installed - a non-zero rc with an empty stdout
    monkeypatch.setattr(ports, "run",
                        lambda argv, **kw: Result(rc=127, out="", err="lsof: command not found"))

    # act
    stopped = ports.free(8000, sleep=lambda _s: None)

    # assert: a courtesy, never a gate
    assert stopped == []
    assert signals == []


def test_every_listener_is_asked_to_stop_and_none_is_killed_when_they_do(fake_lsof, signals):
    # arrange: two listeners, both gone after the first look
    fake_lsof["answers"] = ["4242\n17\n", ""]
    sleeps = []

    # act
    stopped = ports.free(3000, sleep=sleeps.append)

    # assert: TERM for both, KILL for neither
    assert stopped == [4242, 17]
    assert signals == [(4242, signal.SIGTERM), (17, signal.SIGTERM)]
    assert sleeps == [ports.DEFAULT_INTERVAL_S]


def test_only_the_listener_that_survives_the_grace_period_is_force_killed(fake_lsof, signals):
    # arrange: two listeners; 4242 goes on TERM, 17 holds the port through every look
    fake_lsof["answers"] = ["4242\n17\n", "17\n", "17\n", "17\n"]
    sleeps = []

    # act
    stopped = ports.free(3000, grace_s=3.0, interval_s=1.0, sleep=sleeps.append)

    # assert: the survivor alone is killed, and the one that already went is not signalled twice
    assert stopped == [4242, 17]
    assert signals == [(4242, signal.SIGTERM), (17, signal.SIGTERM), (17, signal.SIGKILL)]
    assert sleeps == [1.0, 1.0, 1.0]


def test_the_wait_stops_as_soon_as_the_port_is_free(fake_lsof, signals):
    # arrange: a listener that takes two looks to go, with a grace period good for five
    fake_lsof["answers"] = ["4242\n", "4242\n", ""]
    sleeps = []

    # act
    ports.free(3000, grace_s=5.0, interval_s=1.0, sleep=sleeps.append)

    # assert: it did not sit out the rest of the grace period, and killed nothing
    assert sleeps == [1.0, 1.0]
    assert signals == [(4242, signal.SIGTERM)]


def test_the_grace_period_bounds_how_long_a_listener_is_waited_for(fake_lsof, signals):
    # arrange: a listener that never goes, and a grace period of two intervals
    fake_lsof["answers"] = ["4242\n", "4242\n", "4242\n", "4242\n"]
    sleeps = []

    # act
    ports.free(3000, grace_s=2.0, interval_s=1.0, sleep=sleeps.append)

    # assert: two looks, then the kill
    assert sleeps == [1.0, 1.0]
    assert signals == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


def test_a_process_this_user_may_not_signal_does_not_stop_the_others(fake_lsof, monkeypatch):
    # arrange: two listeners; signalling the first is refused
    fake_lsof["answers"] = ["4242\n17\n", ""]
    sent = []

    def _kill(pid, sig):
        if pid == 4242:
            raise PermissionError("Operation not permitted")
        sent.append((pid, sig))

    monkeypatch.setattr(ports.os, "kill", _kill)

    # act
    stopped = ports.free(3000, sleep=lambda _s: None)

    # assert: the second listener was still asked to stop, and nothing was raised at the caller
    assert stopped == [4242, 17]
    assert sent == [(17, signal.SIGTERM)]
