"""si#739: a child that needs no terminal runs in a process group of its own, and the limit, a stop and an
abandoned run reach everything it started. Decided by Marco 2026-11-18 (option 2 of the ticket).

Real processes throughout: what is under test is which processes are still alive afterwards. The two ways
a child gets its own group are both held - the caller's `terminal=False`, and a kernel with no controlling
terminal at all (`_has_terminal` patched, because whether the test run has one depends on who started it)
- and so is what must NOT change: a child that may need the terminal keeps this process's group.
"""
from __future__ import annotations

import os
import pty
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest
import procalive
from procalive import alive

from simplon.kernel import run as run_module
from simplon.kernel.run import run_stream

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX; Windows is unchanged")

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(run_module.__file__))))





def test_a_process_that_ends_between_open_and_read_reads_as_gone(monkeypatch):
    # arrange: /proc/<pid>/stat opened while the process lives, and the process reaped before the read -
    # the read then raises ESRCH, not FileNotFoundError (seen in CI on every PR after #759)
    proc = subprocess.Popen(["sleep", "30"])
    real_open = open

    def open_then_end(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        proc.kill()
        proc.wait()
        return handle

    monkeypatch.setattr(procalive, "open", open_then_end, raising=False)

    # act / assert
    assert alive(proc.pid) is False


def _pids_running(needle: str) -> list[int]:
    """Every live process whose command line carries `needle`."""
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                cmdline = f.read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if needle in cmdline and alive(int(entry)):
            found.append(int(entry))
    return found


def _gone_within(pids: list[int], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while any(alive(pid) for pid in pids):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


@pytest.fixture
def silent_remote():
    """A listener that accepts every connection and never says a word, as a stalled remote does."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            held.append(conn)

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/product.git"
    try:
        yield url
    finally:
        for pid in _pids_running(url):      # what the red run left behind
            os.kill(pid, signal.SIGKILL)
        stop.set()
        thread.join(5)
        for conn in held:
            conn.close()
        listener.close()


def _ls_remote(tmp_path, monkeypatch, url, **kw):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    return run_module.run(["git", "-C", str(tmp_path), "ls-remote", url], timeout=1, **kw)


# --- the limit: a timed-out child leaves nothing behind ----------------------------------------------------

def test_a_timed_out_git_ls_remote_that_needs_no_terminal_leaves_no_remote_helper(tmp_path, monkeypatch,
                                                                                  silent_remote):
    # act
    started = time.monotonic()
    res = _ls_remote(tmp_path, monkeypatch, silent_remote, terminal=False)

    # assert: the verdict, at once, and no `git remote-http` / `git-remote-http` left holding the socket
    assert res.timed_out
    assert "was left running" not in res.err
    assert time.monotonic() - started < 4, "the drain waited for a descendant that should have been killed"
    assert _gone_within(_pids_running(silent_remote), 2), "a remote helper outlived the limit"


def test_without_a_terminal_every_child_gets_its_own_group(tmp_path, monkeypatch, silent_remote):
    # arrange: a kernel with no controlling terminal (CI, a runner) - no child can need one there
    monkeypatch.setattr(run_module, "_has_terminal", lambda: False)

    # act: no declaration at all
    res = _ls_remote(tmp_path, monkeypatch, silent_remote)

    # assert
    assert res.timed_out
    assert _gone_within(_pids_running(silent_remote), 2), "a remote helper outlived the limit"


def test_a_child_that_may_need_the_terminal_keeps_this_process_group(monkeypatch):
    # arrange: there is a terminal, and the caller declared nothing - sudo, `gh auth refresh`, a prompt
    monkeypatch.setattr(run_module, "_has_terminal", lambda: True)

    # act
    res = run_module.run(["sh", "-c", "ps -o pgid= -p $$"])

    # assert: today's behaviour, unchanged
    assert int(res.out) == os.getpgrp()


def test_a_child_declared_to_need_no_terminal_leads_its_own_group(monkeypatch):
    # arrange
    monkeypatch.setattr(run_module, "_has_terminal", lambda: True)

    # act
    res = run_module.run(["sh", "-c", "echo $$; ps -o pgid= -p $$"], terminal=False)

    # assert
    pid, pgid = (int(word) for word in res.out.split())
    assert pgid == pid != os.getpgrp()


# --- an abandoned run_stream (si#743's grandchild) --------------------------------------------------------

@pytest.mark.parametrize("declared", [True, False], ids=["declared", "no-terminal"])
def test_an_abandoned_run_stream_kills_the_grandchild_too(monkeypatch, declared):
    # arrange: a shell whose first line is the pid of a sleep it started, and a sink that then gives up
    if not declared:
        monkeypatch.setattr(run_module, "_has_terminal", lambda: False)
    seen: list[int] = []

    def give_up(line: str) -> None:
        seen.append(int(line))
        raise RuntimeError("the sink is gone")

    # act
    with pytest.raises(RuntimeError, match="the sink is gone"):
        run_stream(["sh", "-c", "sleep 30 & echo $!; wait"], give_up,
                   **({"terminal": False} if declared else {}))

    # assert
    [grandchild] = seen
    try:
        assert _gone_within([grandchild], 2), "the shell's grandchild outlived the abandoned run"
    finally:
        if alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)


# --- a stop: handed on to the whole group, always ---------------------------------------------------------

_KERNEL = """
import sys
from simplon.kernel import run as run_module
run_module._STOP_GRACE = 5.0
run_module.run(sys.argv[1:], capture=False, terminal=False)
"""


def _kernel_env(pidfile) -> dict[str, str]:
    return {**os.environ, "SI739_PIDFILE": str(pidfile),
            "PYTHONPATH": os.pathsep.join([_SRC, *filter(None, [os.environ.get("PYTHONPATH")])])}


#: A shell that starts a sleep, writes its pid, and waits: the shell dies of a stop, the sleep only if the
#: stop reaches the group.
_SHELL = ["sh", "-c", 'sleep 60 & echo $! > "$SI739_PIDFILE"; wait']


def _wait_for_pid(pidfile, kernel) -> int:
    deadline = time.monotonic() + 30
    while not (pidfile.exists() and pidfile.read_text().strip()):
        assert kernel.poll() is None if hasattr(kernel, "poll") else True, "the kernel ended too early"
        assert time.monotonic() < deadline, "the child never came up"
        time.sleep(0.05)
    return int(pidfile.read_text())


def test_a_SIGTERM_to_the_kernel_reaches_what_its_child_started(tmp_path):
    # arrange
    pidfile = tmp_path / "grandchild.pid"
    kernel = subprocess.Popen([sys.executable, "-c", _KERNEL, *_SHELL], env=_kernel_env(pidfile),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    grandchild = _wait_for_pid(pidfile, kernel)
    try:
        # act
        kernel.send_signal(signal.SIGTERM)
        rc = kernel.wait(30)

        # assert: the kernel still ends BY the signal (si#649), and the sleep went with the shell
        assert rc == -signal.SIGTERM
        assert _gone_within([grandchild], 2), "the stop reached the child but not what it started"
    finally:
        if alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)


def test_a_ctrl_c_typed_at_the_terminal_still_reaches_a_child_in_its_own_group(tmp_path):
    """Measured for si#739: the terminal sends Ctrl-C to its FOREGROUND group only, and a child in a group of
    its own is not in it. So `run` hands the stop on itself, always, where it used to skip a Ctrl-C the
    child had already had."""
    # arrange: the kernel on a real pty, as somebody's shell would run it
    pidfile = tmp_path / "grandchild.pid"
    pid, fd = pty.fork()
    if pid == 0:                                                  # the kernel, on the pty
        os.execve(sys.executable, [sys.executable, "-c", _KERNEL, *_SHELL], _kernel_env(pidfile))
    grandchild = 0
    try:
        deadline = time.monotonic() + 30
        while not (pidfile.exists() and pidfile.read_text().strip()):
            assert time.monotonic() < deadline, "the child never came up"
            time.sleep(0.05)
        grandchild = int(pidfile.read_text())

        # act: Ctrl-C, typed
        os.write(fd, b"\x03")
        _, status = os.waitpid(pid, 0)

        # assert: the kernel was interrupted, and the stop reached the group within the grace
        assert os.waitstatus_to_exitcode(status) != 0
        assert _gone_within([grandchild], 2), "a typed Ctrl-C never reached the child's own group"
    finally:
        if grandchild and alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)
        os.close(fd)
