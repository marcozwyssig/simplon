"""si#526: the outcome type and the privileged runner every host-install gate shares.

The six outcomes are kept apart because each tells the person something different - "not this product's",
"there", "installed", "not this machine", "cannot here" and "broken" - and the recurring defect is two of them
reading alike, or a "cannot here" exiting 0. AAA throughout.
"""
from __future__ import annotations

import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import ROOT
from simplon.adapters import hostinstall
from simplon.adapters.hostinstall import Outcome, State


@pytest.mark.parametrize("state", list(State))
def test_rc_is_one_only_for_no_route_and_failed(state):
    # act
    rc = hostinstall.rc(Outcome(state))

    # assert
    assert rc == (1 if state in (State.NO_ROUTE, State.FAILED) else 0)


def test_off_reports_nothing(capsys):
    # act
    hostinstall.report("gh", Outcome(State.OFF))

    # assert
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_each_state_reports_in_its_own_words(capsys):
    # arrange
    lines = []

    # act
    for state in State:
        if state is State.OFF:
            continue
        hostinstall.report("gh", Outcome(state, "why"))
        captured = capsys.readouterr()
        lines.append(captured.out + captured.err)

    # assert: every line names the tool, and no two read alike
    assert all("gh" in line for line in lines)
    assert len(set(lines)) == len(lines)


def test_privileged_runs_as_is_for_root():
    # act
    argv = hostinstall.privileged(["apt-get", "update"], euid=0, have=lambda _: None)

    # assert
    assert argv == ["apt-get", "update"]


def test_privileged_prefixes_sudo():
    # act
    argv = hostinstall.privileged(["apt-get", "update"], euid=1000, have=lambda tool: f"/usr/bin/{tool}")

    # assert
    assert argv == ["sudo", "apt-get", "update"]


def test_privileged_is_none_without_sudo():
    # act
    argv = hostinstall.privileged(["apt-get", "update"], euid=1000, have=lambda _: None)

    # assert
    assert argv is None


def test_act_reports_a_timeout_as_a_reason():
    # act
    reason = hostinstall.act(["/bin/sleep", "5"], timeout_s=0.2)

    # assert
    assert "timed out after" in reason


def test_act_reports_a_nonzero_exit():
    # act
    reason = hostinstall.act(["/bin/false"])

    # assert
    assert "exited 1" in reason


def test_act_reports_a_missing_program_as_a_reason():
    # act
    reason = hostinstall.act(["/nonexistent/tool"])

    # assert
    assert reason and "/nonexistent/tool" in reason


def test_act_is_empty_on_success():
    # act
    reason = hostinstall.act(["/bin/true"])

    # assert
    assert reason == ""


def test_act_adds_its_env_to_this_process_environment(monkeypatch):
    """#670 item 7: `env` is what the command needs ADDED (Homebrew's NONINTERACTIVE), as `run(env=...)` takes
    it, not a whole environment to replace this one with."""
    # arrange
    monkeypatch.setenv("SI670_INHERITED", "kept")

    # act
    reason = hostinstall.act(["sh", "-c", 'test "$SI670_INHERITED/$SI670_ADDED" = kept/added'],
                             env={"SI670_ADDED": "added"})

    # assert
    assert reason == ""


_KERNEL = """
import sys
from simplon.adapters import hostinstall
from simplon.kernel import run
run._STOP_GRACE = 5.0
hostinstall.act([sys.executable, "-c",
                 "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)",
                 sys.argv[1]])
"""


@pytest.mark.skipif(os.name != "posix", reason="SIGTERM is POSIX")
def test_a_stop_to_the_kernel_reaches_the_install_command(tmp_path):
    """#670 item 7: through `run()` the install command gets the stop (si#649). Through `subprocess.run` it
    did not, and an install the kernel was told to stop ran on, reparented to init."""
    # arrange
    pidfile = tmp_path / "install.pid"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"),
                                                        *filter(None, [os.environ.get("PYTHONPATH")])])}
    kernel = subprocess.Popen([sys.executable, "-c", _KERNEL, str(pidfile)], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while not (pidfile.exists() and pidfile.read_text().strip()):
        assert kernel.poll() is None, "the kernel ended before the install command started"
        assert time.monotonic() < deadline, "the install command never started"
        time.sleep(0.05)
    child = int(pidfile.read_text())
    try:
        # act
        kernel.send_signal(signal.SIGTERM)
        kernel.wait(30)

        # assert
        deadline = time.monotonic() + 2
        while _running(child):
            assert time.monotonic() < deadline, "the install command outlived the stop"
            time.sleep(0.05)
    finally:
        if _running(child):
            os.kill(child, signal.SIGKILL)


def _running(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):      # gone, or gone between the open and the read
        return False


def _tool(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_runs_is_false_for_a_tool_whose_version_fails(tmp_path):
    # arrange: presence on PATH is not capability
    _tool(tmp_path, "gh", "exit 3")

    # act
    ok = hostinstall.runs("gh", {"PATH": str(tmp_path)})

    # assert
    assert ok is False


def test_runs_is_true_for_a_tool_that_answers(tmp_path):
    # arrange
    _tool(tmp_path, "gh", "echo gh version 1")

    # act
    ok = hostinstall.runs("gh", {"PATH": str(tmp_path)})

    # assert
    assert ok is True


def test_runs_is_false_for_an_absent_tool(tmp_path):
    # act
    ok = hostinstall.runs("gh", {"PATH": str(tmp_path)})

    # assert
    assert ok is False


@pytest.mark.parametrize("env, container, expected", [
    ({}, True, "container"),
    ({"CI": "true"}, False, "CI=true"),
    ({"GITHUB_ACTIONS": "true"}, False, "GITHUB_ACTIONS=true"),
    ({}, False, ""),
])
def test_machine_skip_reason(env, container, expected):
    # act
    reason = hostinstall.machine_skip_reason(env, container)

    # assert
    assert (expected in reason) if expected else reason == ""
