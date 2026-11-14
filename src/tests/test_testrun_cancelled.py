"""si#667: a gate a stop ended is recorded as `killed`, not left out of the record.

The kernel runs in an interpreter of its own here, because what is under test is what that PROCESS records
when it is signalled mid-gate; a test process cannot SIGTERM itself and watch. The suite is a real pytest
that sleeps, and `run` is the kernel's own, so the stop travels the seam it travels under a runner's cancel
(si#649 hands it on to the child, then re-delivers it here). Only what is off the machine is stubbed: the
keep-awake window and the per-suite venv.
"""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from simplon.tasks import allure, testrun

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX signals; the Windows path is unchanged")

_KERNEL = """
import contextlib, sys
from pathlib import Path
from types import SimpleNamespace
from simplon.manifest import context
from simplon.manifest.context import ProductContext
from simplon.tasks import testrun

root, mode = Path(sys.argv[1]), sys.argv[2]
gates = [{"name": "unit", "suite": "slow", "results": "clear", "junit": "junit.xml"}]
if mode == "accept":
    gates = [{"name": "first", "suite": "fast", "results": "clear", "junit": "junit-first.xml"},
             {"name": "unit", "suite": "slow", "results": "append", "junit": "junit.xml"}]
data = {"suites": {"reports": "reports", "gates": gates}}
context._current = ProductContext("sample", root, root / "sample.yaml")
ProductContext.manifest_data = lambda self: data
testrun.keep_awake = contextlib.nullcontext
testrun.pyvenv.venv_python_pip = lambda d: (sys.executable, "pip")
if mode == "accept":
    sys.exit(testrun.accept([]))
sys.exit(testrun.gate(SimpleNamespace(info_name="unit", args=[]), name="unit"))
"""

_SLOW_SUITE = """
import os, time
def test_slow():
    with open(os.environ["SI667_PIDFILE"], "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
"""


def _cancelled(tmp_path, mode: str, signum: int) -> tuple[int, str]:
    """Run `mode` (one gate, or `accept` over a fast gate and the slow one) in a kernel process, send it
    `signum` once the slow suite is up, and return the kernel's rc and its output."""
    (tmp_path / "slow").mkdir()
    (tmp_path / "slow/test_slow.py").write_text(_SLOW_SUITE)
    (tmp_path / "fast").mkdir()
    (tmp_path / "fast/test_fast.py").write_text("def test_fast():\n    pass\n")
    pidfile = tmp_path / "child.pid"
    src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(testrun.__file__))))
    env = {**os.environ, "SI667_PIDFILE": str(pidfile),
           "PYTHONPATH": os.pathsep.join([src, *filter(None, [os.environ.get("PYTHONPATH")])])}
    # No terminal on any of the three streams: `run` does not hand on a SIGINT its terminal already sent the
    # whole group, and this SIGINT is sent to the kernel alone.
    kernel = subprocess.Popen([sys.executable, "-c", _KERNEL, str(tmp_path), mode], cwd=tmp_path, env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
    try:
        deadline = time.monotonic() + 30
        while not (pidfile.exists() and pidfile.read_text()):
            assert kernel.poll() is None, "the kernel ended before its suite came up:\n" + kernel.stdout.read()
            assert time.monotonic() < deadline, "the suite never came up"
            time.sleep(0.05)
        kernel.send_signal(signum)
        out, _ = kernel.communicate(timeout=30)
        return kernel.returncode, out
    finally:
        if kernel.poll() is None:
            kernel.kill()
        if pidfile.exists() and pidfile.read_text():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def _stamp(tmp_path) -> dict:
    path = tmp_path / "reports" / "test-verdict.json"
    assert path.exists(), "the cancelled run left no record at all"
    return json.loads(path.read_text(encoding="utf-8"))


@posix_only
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_gate_a_stop_ended_is_recorded_as_killed_and_the_stop_still_ends_the_process(tmp_path, signum):
    """Measured before the fix: the stop propagated out of `assess_gate` and the record held nothing - no
    stamp, no environment - so a gate that was stopped mid-run read exactly like one that never ran."""
    # act
    rc, out = _cancelled(tmp_path, "gate", signum)

    # assert: the process still ends BY the stop - a cancelled gate never reads green or as a plain red
    assert rc == -signum, out
    # ... and the record says which gate it was and what ended it, in the stamp, the archive and the log
    name = signal.Signals(signum).name
    stamp = _stamp(tmp_path)
    assert stamp["verdict"] == "killed"
    assert [(g["gate"], g["verdict"], g["rc"]) for g in stamp["gates"]] == [("unit", "killed", -signum)]
    assert f"killed ({name})" in stamp["line"]
    written = (tmp_path / "reports" / testrun.RESULTS / allure.ENVIRONMENT).read_text(encoding="utf-8")
    assert "verdict=killed" in written and f"killed ({name})" in written
    assert f"unit: killed ({name})" in out


@posix_only
def test_a_SIGINT_cancel_keeps_the_junit_the_suite_wrote_on_its_way_out(tmp_path):
    """si#649 lets pytest write its junit on a SIGINT; the record has to keep it, not clear it away."""
    # act
    _cancelled(tmp_path, "gate", signal.SIGINT)

    # assert
    assert (tmp_path / "reports" / "junit.xml").exists()


@posix_only
def test_a_run_cancelled_in_its_second_gate_does_not_leave_the_first_gates_green_as_the_runs_verdict(tmp_path):
    """Measured before the fix, and worse than the single gate: `accept` cancelled in its second gate left
    the stamp it wrote after the first one, `"verdict": "passed"`, as the record of a run that was stopped.
    """
    # act
    rc, out = _cancelled(tmp_path, "accept", signal.SIGINT)

    # assert
    assert rc == -signal.SIGINT, out
    stamp = _stamp(tmp_path)
    assert stamp["verdict"] == "killed"
    assert [(g["gate"], g["verdict"]) for g in stamp["gates"]] == [("first", "passed"), ("unit", "killed")]
