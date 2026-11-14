"""Unit tests for run - the subprocess seam: the live line-streaming helper the TUI builds on, and the
two shapes a command impl runs external tools with (platform#43). Real `sh` subprocesses, because what is
under test IS the plumbing of the real exit code."""
import errno
import os
import signal
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

from simplon.kernel import run as run_module
from simplon.kernel.run import Result, chain, run_stream, stream


def test_run_stream_emits_each_line_and_returns_the_real_rc():
    # arrange: a command that prints two lines and exits non-zero
    seen: list[str] = []

    # act
    rc = run_stream(["sh", "-c", "printf 'one\\ntwo\\n'; exit 5"], seen.append)

    # assert: every line was streamed (newline-stripped) and the real exit code is returned
    assert seen == ["one", "two"]
    assert rc == 5


def test_run_stream_returns_zero_on_success():
    # arrange / act
    seen: list[str] = []
    rc = run_stream(["sh", "-c", "echo ok"], seen.append)

    # assert
    assert rc == 0
    assert seen == ["ok"]


# --- the two shapes a command impl uses (platform#43) ------------------------------------------------

def test_stream_returns_the_real_exit_code():
    # arrange / act: a command whose rc is neither 0 nor 1, so a boolean-ish result cannot pass for it
    rc = stream(["sh", "-c", "echo streamed; exit 7"])

    # assert
    assert rc == 7


def test_stream_runs_in_the_directory_it_was_given(tmp_path):
    # arrange: a marker that exists ONLY in the given directory
    (tmp_path / "marker").write_text("here")

    # act
    inside = stream(["sh", "-c", "test -f marker"], cwd=str(tmp_path))
    outside = stream(["sh", "-c", "test -f marker"])

    # assert: the cwd is what decides, not the process' own directory
    assert (inside, outside) == (0, 1)


def test_chain_stops_at_the_first_failure_and_returns_ITS_code(tmp_path):
    # arrange: three steps, the second and third failing with DIFFERENT codes, each leaving a trace
    trace = tmp_path / "ran"

    # act
    rc = chain(["sh", "-c", f"echo one >> {trace}"],
               ["sh", "-c", f"echo two >> {trace}; exit 3"],
               ["sh", "-c", f"echo three >> {trace}; exit 4"])

    # assert: the code of the step that FAILED, not of the last one - and the last one never ran
    assert rc == 3
    assert trace.read_text().split() == ["one", "two"]


def test_chain_runs_every_step_when_none_fails(tmp_path):
    # arrange
    trace = tmp_path / "ran"

    # act
    rc = chain(["sh", "-c", f"echo one >> {trace}"],
               ["sh", "-c", f"echo two >> {trace}"])

    # assert
    assert rc == 0
    assert trace.read_text().split() == ["one", "two"]


def test_chain_runs_its_steps_in_the_directory_it_was_given(tmp_path):
    # arrange: a marker only the given directory has
    (tmp_path / "marker").write_text("here")

    # act
    rc = chain(["sh", "-c", "test -f marker"], ["sh", "-c", "test -f marker"], cwd=str(tmp_path))

    # assert
    assert rc == 0


def test_chain_of_nothing_succeeds():
    # arrange / act / assert: an empty plan is not a failure
    assert chain() == 0


# --- si#144: a segment is what arrived, not what ended in a newline ----------------------------------

def test_run_stream_hands_over_a_partial_line_when_the_child_goes_quiet():
    """The measured defect (si#144): pytest writes one dot per test and completes the line every 72 of
    them, so `for line in proc.stdout` froze the pane for up to 11.37s while the child was writing every
    few milliseconds. A reader that waits for the terminator is the whole of it."""
    # arrange: a child that writes an unterminated run of dots, pauses, then finishes the line
    seen: list[str] = []
    argv = ["sh", "-c", "printf '...'; sleep 0.5; printf '... [100%%]\\n'"]

    # act
    rc = run_stream(argv, seen.append, flush_after=0.05)

    # assert: the first three dots arrived on their own, before the line was ever terminated
    assert rc == 0
    assert seen == ["...", "... [100%]"]


def test_run_stream_splits_on_a_carriage_return_as_well_as_a_newline():
    """A repaint ends a segment for the same reason a newline does: what came before it is finished
    text. This passed before si#144 too - `text=True` makes `\\r` a terminator for `readline` - and is
    kept because the rewrite to a chunk reader must not lose it."""
    # arrange
    seen: list[str] = []

    # act
    rc = run_stream(["sh", "-c", "printf 'a  17%%\\rb 100%%\\n'"], seen.append)

    # assert
    assert rc == 0
    assert seen == ["a  17%", "b 100%"]


def test_run_stream_treats_crlf_as_one_break():
    # arrange: a Windows-ending child, which must not produce an empty segment between the two bytes
    seen: list[str] = []

    # act
    run_stream(["sh", "-c", "printf 'one\\r\\ntwo\\r\\n'"], seen.append)

    # assert
    assert seen == ["one", "two"]


def test_run_stream_keeps_a_multibyte_character_whole_across_a_chunk_boundary():
    """Chunked reading can cut a UTF-8 character in half, which `text=True` used to prevent. The state
    icons this kernel echoes (the run tree's glyphs) are exactly such characters."""
    # arrange: the two halves of one character, written 0.3s apart, so they land in different reads
    seen: list[str] = []
    argv = ["python3", "-c",
            "import sys,time; b='\\u2713'.encode(); sys.stdout.buffer.write(b[:1]);"
            " sys.stdout.buffer.flush(); time.sleep(0.3);"
            " sys.stdout.buffer.write(b[1:]+b'\\n'); sys.stdout.buffer.flush()"]

    # act
    run_stream(argv, seen.append, flush_after=0.05)

    # assert: one whole character, never two replacement marks
    assert "".join(seen) == "✓"


def test_run_stream_emits_the_last_line_when_the_child_never_terminates_it():
    # arrange
    seen: list[str] = []

    # act
    rc = run_stream(["sh", "-c", "printf 'no newline here'; exit 3"], seen.append)

    # assert
    assert (rc, seen) == (3, ["no newline here"])


def test_run_stream_reaps_the_child_when_the_sink_raises():
    """A leak the rewrite was the chance to close, and it was there before it too: when `on_line` raises
    - in the TUI it is a `call_from_thread`, which can - the exception used to propagate with the child
    never killed and never waited for. Measured on both readers: `ps --ppid` still showed the `sh`
    process alive after the exception had reached the caller."""
    # arrange: a child that would outlive the run by a mile, and a sink that refuses its first line
    proc_holder: dict[str, object] = {}
    real_popen = subprocess.Popen

    def remember(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        proc_holder["proc"] = proc
        return proc

    def refuse(_line: str) -> None:
        raise RuntimeError("the sink is gone")

    # act
    with mock.patch.object(subprocess, "Popen", remember):
        with pytest.raises(RuntimeError, match="the sink is gone"):
            run_stream(["sh", "-c", "echo one; sleep 30"], refuse)

    # assert: the child is dead and reaped, not left behind holding a terminal
    proc = proc_holder["proc"]
    assert proc.returncode is not None, "the child was never waited for"
    assert proc.poll() is not None


def test_run_stream_raises_when_the_pipe_could_not_be_read():
    """A read that FAILED is not a stream that ended. The two are otherwise indistinguishable here -
    `proc.wait()` returns the child's real exit code either way - so a failed read would report a green
    rc over half a log, which is exactly the class of defect this repository hunts."""
    # arrange: `os.read` fails, but ONLY on the reader thread, so nothing else in this process is hurt
    real_read = os.read

    def flaky(fd: int, size: int) -> bytes:
        if threading.current_thread().name == run_module._PUMP_THREAD:
            raise OSError(errno.EIO, "simulated")
        return real_read(fd, size)

    # act / assert
    # A SHORT child: with the re-raise removed the failed read looks exactly like EOF, so `run_stream`
    # returns normally and this must FAIL rather than sit here waiting for the child - a test that hangs
    # when the property it protects is broken is not an assertion.
    with mock.patch.object(run_module.os, "read", flaky):
        with pytest.raises(OSError) as caught:
            run_stream(["sh", "-c", "echo one; sleep 1"], lambda _line: None)
    assert caught.value.errno == errno.EIO


# --- si#274: succeeded and said nothing is not the same as succeeded ----------------------------------

@pytest.mark.parametrize("rc, out, ok, answered", [
    (0, "v1.2.3\n", True, True),
    (0, "", True, False),
    (0, "\n  \n", True, False),
    (1, "v1.2.3\n", False, False),
    (1, "", False, False),
])
def test_ok_and_answered_are_different_questions(rc, out, ok, answered):
    """si#274's seam, and the two columns are the whole point: `ok` asks whether the command succeeded,
    `answered` whether it said anything, and a caller that uses `out` as a VALUE needs the second.

    Two callers did not ask it, and both were found on the same machine within an hour: an empty
    `git rev-parse --show-toplevel` became `Path("")`, which is `PosixPath('.')` and resolves to the
    working directory, and an empty `<sha>^1..<sha>^2` became "these commits name no ticket".

    Whitespace counts as nothing on purpose. A command whose whole output is a newline said as little as
    one that wrote no bytes, and every caller here strips before using the value anyway.
    """
    # arrange
    result = Result(rc=rc, out=out, err="")

    # assert
    assert result.ok is ok
    assert result.answered is answered


# --- si#649: a stop that reaches the kernel reaches its child -------------------------------------------
#
# The kernel runs in an interpreter of its own here, because what is under test is what that PROCESS does
# when it is signalled; a test process cannot SIGTERM itself and watch. The child is a real pytest that
# sleeps, because the property si#649 asks for is pytest's: that it is given the chance to write its junit.

_KERNEL = """
import sys
from simplon.kernel import run as run_module
run_module._STOP_GRACE = float(sys.argv[1])
run_module.run(sys.argv[3:], capture=sys.argv[2] == "capture")
"""

_SLOW_SUITE = """
import os, time
def test_slow():
    with open(os.environ["SI649_PIDFILE"], "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
"""

_DEAF_CHILD = """
import os, signal, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(os.environ["SI649_PIDFILE"], "w") as f:
    f.write(str(os.getpid()))
time.sleep(60)
"""

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX signals; the Windows path is unchanged")


def _alive(pid: int) -> bool:
    """Running, as opposed to gone or a zombie waiting for init to reap it."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while _alive(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def _kernel_with_child(tmp_path, child: list[str], *, capture: bool = False, grace: float = 9.0):
    """Start a kernel process whose `run` runs `child`, and return it with the child's pid once the child
    has said it is up: a signal sent before that would measure the start, not the stop."""
    pidfile = tmp_path / "child.pid"
    src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(run_module.__file__))))
    env = {**os.environ, "SI649_PIDFILE": str(pidfile),
           "PYTHONPATH": os.pathsep.join([src, *filter(None, [os.environ.get("PYTHONPATH")])])}
    kernel = subprocess.Popen([sys.executable, "-c", _KERNEL, str(grace), "capture" if capture else "stream",
                               *child], cwd=tmp_path, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    while not (pidfile.exists() and pidfile.read_text()):
        assert kernel.poll() is None, "the kernel ended before its child came up"
        assert time.monotonic() < deadline, "the child never came up"
        time.sleep(0.05)
    return kernel, int(pidfile.read_text())


@pytest.fixture
def slow_pytest(tmp_path):
    (tmp_path / "test_slow.py").write_text(_SLOW_SUITE)
    junit = tmp_path / "junit.xml"
    return [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "test_slow.py",
            f"--junitxml={junit}"], junit


@posix_only
@pytest.mark.parametrize("capture", [False, True], ids=["streamed", "captured"])
def test_a_SIGTERM_to_the_kernel_does_not_leave_its_child_running(tmp_path, slow_pytest, capture):
    """si#649, the orphan. Measured before the fix: the kernel's python died on SIGTERM at once and its
    pytest child ran on, reparented to init, with no junit - the shape of the two orphans netctl's runner
    terminated at job cleanup. The stop has to reach the child, and the kernel still has to end BY the
    signal: a run that was cancelled must look cancelled."""
    # arrange
    argv, _ = slow_pytest
    kernel, child = _kernel_with_child(tmp_path, argv, capture=capture)
    try:
        # act
        kernel.send_signal(signal.SIGTERM)
        rc = kernel.wait(30)

        # assert
        assert _gone_within(child, 5), "the kernel ended and its child is still running"
        assert rc == -signal.SIGTERM
    finally:
        if _alive(child):
            os.kill(child, signal.SIGKILL)


@posix_only
def test_a_SIGINT_to_the_kernel_lets_its_pytest_child_write_the_junit(tmp_path, slow_pytest):
    """si#649, the missing report. A runner's cancel starts with SIGINT, and a SIGINT that reached only the
    kernel became `subprocess.run`'s KeyboardInterrupt path, which SIGKILLs the child 0.25 s later -
    measured: no junit. Handed on, pytest stops the way it stops on Ctrl-C and writes its report on the way
    out, and the kernel still ends interrupted, never green."""
    # arrange
    argv, junit = slow_pytest
    kernel, child = _kernel_with_child(tmp_path, argv)
    try:
        # act
        kernel.send_signal(signal.SIGINT)
        rc = kernel.wait(30)

        # assert
        assert junit.exists(), "the child was stopped before it could write its junit"
        assert not _alive(child)
        assert rc == -signal.SIGINT
    finally:
        if _alive(child):
            os.kill(child, signal.SIGKILL)


@posix_only
def test_a_child_that_ignores_the_stop_is_killed_once_the_grace_is_over(tmp_path):
    """The wait after a stop is BOUNDED, because a run that hangs is neither green nor red. A child deaf to
    both signals is killed by the kernel itself when the grace ends, rather than outliving it."""
    # arrange
    (tmp_path / "deaf.py").write_text(_DEAF_CHILD)
    kernel, child = _kernel_with_child(tmp_path, [sys.executable, "deaf.py"], grace=0.5)
    try:
        # act
        started = time.monotonic()
        kernel.send_signal(signal.SIGTERM)
        rc = kernel.wait(30)

        # assert
        assert not _alive(child)
        assert time.monotonic() - started < 10
        assert rc == -signal.SIGTERM
    finally:
        if _alive(child):
            os.kill(child, signal.SIGKILL)


def test_run_still_kills_the_child_on_its_own_timeout():
    # act / assert: handing a stop on must not have cost `timeout` its meaning
    with pytest.raises(subprocess.TimeoutExpired):
        run_module.run(["sleep", "30"], timeout=0.3)


def test_run_still_feeds_input_and_captures_both_streams():
    # act
    res = run_module.run(["sh", "-c", "cat; echo err >&2; exit 4"], input_text="fed\n")

    # assert
    assert (res.rc, res.out, res.err) == (4, "fed\n", "err\n")
