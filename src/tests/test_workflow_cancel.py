"""si#666: a cancelled GENERATED step stops the kernel's pytest the way si#649 stops it, end to end.

si#649 made `kernel.run.run` hand a SIGINT or SIGTERM on to its child, which only helps once the signal
reaches the kernel. actions/runner cancels a step by signalling the step shell's pid alone
(`src/Runner.Sdk/ProcessInvoker.cs`, `CancelAndKillProcessTree` / `SendSignal`): SIGINT, wait 7.5 s,
SIGTERM, wait 2.5 s, then kill. This test plays that sequence against the `run:` line the generator
actually writes, run the way the runner runs a step on Linux (`bash -e <script>`).

The launcher is a stand-in, and that is the one assumption written into it: like the real one
(`launch.sh.j2`, every route ends in `exec ... python -u -m`), it `exec`s a python, here one whose `run`
runs a pytest that sleeps. What is measured is everything above it - the generated line, bash, the kernel's
`run` and pytest - all real.
"""
import os
import signal
import subprocess
import sys
import time

import pytest
import yaml

from simplon.kernel import run as run_module
from simplon.manifest import catalogue as catalogue_mod
from simplon.manifest import load as manifest_mod
from simplon.tasks import workflowgen

_MANIFEST = """
tasks:
  suite: { impl: "simplon.test_impls:nullary", help: "Run every test." }
ci:
  test:
    commands:
      all: { task: suite }
"""

_WORKFLOWS = """
ci:
  on: [push]
  jobs:
    build:
      runs-on: ubuntu-latest
      steps:
        - command: test all
"""

#: The stand-in launcher: `exec`s the kernel, as the real launcher does on each of its routes.
_LAUNCHER = """#!/bin/bash
exec "$SI666_PYTHON" -u kernel.py
"""

_KERNEL = """
import os, sys
from simplon.kernel.run import run
with open("kernel.pid", "w") as f:
    f.write(str(os.getpid()))
r = run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "test_slow.py",
         "--junitxml=junit.xml"], capture=False)
sys.exit(1 if r.rc else 0)
"""

_SLOW_SUITE = """
import os, time
def test_slow():
    with open("child.pid", "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
"""

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX signals; actions/runner on Linux")


def _alive(pid: int) -> bool:
    """Running, as opposed to gone or a zombie waiting for init to reap it."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _generated_run_line() -> str:
    manifest = manifest_mod.load(_MANIFEST, catalogue=catalogue_mod.load())
    workflow = workflowgen.parse({"workflows": yaml.safe_load(_WORKFLOWS)})[0]
    text = workflowgen.render(workflow, manifest=manifest, product="sample", source="sample.yaml", artifacts={})
    run = yaml.safe_load(text)["jobs"]["build"]["steps"][-1]["run"]
    assert "sample.sh test all" in run, f"the step is not the launcher call: {run!r}"
    return run


def _runner_cancel(step: subprocess.Popen) -> None:
    """actions/runner's cancel on Linux: every signal to the step shell's pid, never to its group."""
    step.send_signal(signal.SIGINT)
    try:
        step.wait(7.5)
        return
    except subprocess.TimeoutExpired:
        pass
    step.send_signal(signal.SIGTERM)
    try:
        step.wait(2.5)
    except subprocess.TimeoutExpired:
        step.kill()
        step.wait()


@posix_only
def test_a_cancelled_generated_step_lets_pytest_write_its_junit_and_leaves_nothing_running(tmp_path):
    """Measured without `exec` (the line the generator wrote before si#666): bash survives the SIGINT,
    because it waits out its foreground child, and dies alone on the SIGTERM at 7.5 s; the kernel's python
    and its pytest run on, reparented to init, and no junit is written. With `exec` the kernel is the
    step's pid, hands the SIGINT on, and pytest stops the way it stops on Ctrl-C."""
    # arrange
    (tmp_path / "step.sh").write_text(_generated_run_line() + "\n")
    (tmp_path / "sample.sh").write_text(_LAUNCHER)
    (tmp_path / "sample.sh").chmod(0o755)
    (tmp_path / "kernel.py").write_text(_KERNEL)
    (tmp_path / "test_slow.py").write_text(_SLOW_SUITE)
    src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(run_module.__file__))))
    env = {**os.environ, "SI666_PYTHON": sys.executable,
           "PYTHONPATH": os.pathsep.join([src, *filter(None, [os.environ.get("PYTHONPATH")])])}
    # A session of its own, as the runner's step is not in the test's group; started from python, so the
    # step inherits SIGINT at its default disposition, as it does under the runner.
    step = subprocess.Popen(["bash", "-e", "step.sh"], cwd=tmp_path, env=env, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pidfile = tmp_path / "child.pid"
    deadline = time.monotonic() + 30
    while not (pidfile.exists() and pidfile.read_text()):
        assert step.poll() is None, "the step ended before pytest came up"
        assert time.monotonic() < deadline, "pytest never came up"
        time.sleep(0.05)
    child = int(pidfile.read_text())
    try:
        # act
        _runner_cancel(step)
        time.sleep(1)

        # assert
        assert not _alive(child), "the step ended and the kernel's pytest is still running"
        assert (tmp_path / "junit.xml").exists(), "pytest was stopped before it could write its junit"
        assert step.returncode != 0, "a cancelled step must not end green"
    finally:
        for marker in (tmp_path / "kernel.pid", pidfile):
            if marker.exists() and _alive(int(marker.read_text())):
                os.kill(int(marker.read_text()), signal.SIGKILL)
