"""si#409: a cancelled `toolchain:run` must not leave its container running.

WHAT firn MEASURED (firn#965, simplon 0.30.0): a GitHub runner cancel emulated about 4 s into
`./firn.sh test all` - SIGINT, then SIGTERM, then SIGKILL to bash, python and the docker client - and the
`gradle check` container survived all three, ran to exit 0 22 s after it started, and only then did
`--rm` remove it. On a single self-hosted runner the next job checks out into the same tree while that
orphan is still writing `build/`. The job says *cancelled*; the work it started has not stopped - this
repository's recurring defect, at the seam between a client and the daemon it talks to.

THE REPRODUCTION, and why it signals PYTHON and not the docker client. The kernel's process is what a
runner cancel reaches first and what a Ctrl-C interrupts, and it is the only process this kernel can
make behave. So each test starts the line `toolchain.docker_argv` assembles through the call
`run_toolchain` makes, `docker.run_container`, in a child python; waits until the container is REALLY
running (by its label, so an image pull does not eat the head start); signals the child; and then asks
the daemon what is left - `docker ps -a`, so a stopped container that was not removed counts as left.

Seen red on 2026-10-13 against the code before si#409 (`run(line, capture=False)`, no `--init`, no
name, no label): SIGINT and SIGTERM both left the container alive. SIGKILL is the case no handler can
see, so its test asserts the other half of the promise - that what it leaves is FINDABLE by its label.

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import simplon
from conftest import docker_is_usable
from simplon.kernel.run import run

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to cancel a run in")

#: Small, pinned, and already used by this suite (test_toolchain_cli.py). `sleep` is the whole workload:
#: what is under test is whether the container outlives its client, not what it does meanwhile.
IMAGE = "alpine:3.20"

#: How long the container would run on its own - long enough that "still alive afterwards" can only mean
#: "survived the cancel", never "had not finished yet".
SLEEP = "60"

#: The child: assemble the toolchain line for one product and run it the way `run_toolchain` does.
CHILD = """
import sys
from pathlib import Path
from simplon.adapters import docker
from simplon.tasks import toolchain
product, root, image, seconds = sys.argv[1:5]
cfg = toolchain.declared({"image": image, "argv": ["sleep", seconds]}, where="si409")
name = docker.container_name(product)
line = toolchain.docker_argv(cfg, root=Path(root), product=product, instance="", extra=[],
                             network="none", name=name)
print(name, flush=True)
sys.exit(docker.run_container(line, name).rc)
"""


def _left_by(product: str) -> list[str]:
    """Every container, running or not, that carries this product's run label."""
    out = run(["docker", "ps", "-a", "-q", "--filter", f"label=simplon.run={product}"]).out
    return out.split()


def _start(product: str, root: Path) -> tuple[subprocess.Popen[str], str]:
    """The child and the container name it chose, returned only once that container is running.

    The name is read HERE, before any signal: after a SIGKILL the orphaned docker client still holds the
    child's stdout open, so reading it then waits for the container to finish - which, first time round,
    is exactly how this test waited 60 s and then found nothing left to find."""
    src = str(Path(simplon.__file__).resolve().parents[1])
    child = subprocess.Popen([sys.executable, "-c", CHILD, product, str(root), IMAGE, SLEEP],
                             env={**os.environ, "PYTHONPATH": src},
                             stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None
    name = child.stdout.readline().strip()
    deadline = time.monotonic() + 120          # a cold image pull is the only slow part
    while time.monotonic() < deadline:
        running = run(["docker", "ps", "-q", "--filter", f"label=simplon.run={product}"]).out.split()
        if running:
            time.sleep(1.0)                    # firn's cancel came seconds in, not at the first instant
            return child, name
        if child.poll() is not None:
            pytest.fail(f"the child exited rc {child.returncode} before its container ever ran")
        time.sleep(0.2)
    child.kill()
    pytest.fail("the container never started")


@pytest.fixture
def product():
    """A product name no other run on this daemon carries, and every container under it gone afterwards."""
    name = f"si409-{uuid.uuid4().hex[:8]}"
    yield name
    for cid in _left_by(name):
        run(["docker", "rm", "-f", cid])


@needs_docker
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_cancelled_run_leaves_no_container_behind(product, tmp_path, sig):
    # arrange
    child, _ = _start(product, tmp_path)

    # act: the cancel, delivered to the kernel's own process
    child.send_signal(sig)
    rc = child.wait(timeout=60)

    # assert: nothing from this run is alive, or even left stopped
    assert _left_by(product) == [], f"{sig.name} left a container behind"
    # assert: and the cancel still LOOKS like a cancel - the process died by the signal it was sent,
    # rather than reporting an exit code of the cleanup's choosing
    assert rc == -sig, f"{sig.name}: the client exited rc {rc}"


@needs_docker
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_signal_that_reaches_only_the_docker_client_still_stops_the_container(product, tmp_path, sig):
    # arrange: firn's cancel reached the docker client too. The client forwards SIGINT and SIGTERM to
    # the container - and without `--init` the tool is PID 1 there, which Linux delivers no signal to
    # that it installed no handler for. Measured 2026-10-13 with `sleep 30`: without `--init` the client
    # was still waiting 8 s later; with it, the client returned 130 / 143 in 0.2 s.
    child, _ = _start(product, tmp_path)
    clients = run(["ps", "-o", "pid=", "--ppid", str(child.pid)]).out.split()
    assert len(clients) == 1, f"expected the one docker client under the child, found {clients}"

    # act: the signal goes to the client alone; the kernel's python is not told anything
    subprocess.run(["kill", f"-{sig.name.removeprefix('SIG')}", clients[0]], check=True)
    try:
        rc = child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        pytest.fail(f"{sig.name} to the docker client did not stop the run within 20 s")

    # assert: the container stopped, `--rm` removed it, and the rc says why
    assert _left_by(product) == []
    assert rc == 128 + sig, f"{sig.name}: the run exited rc {rc}"


@needs_docker
def test_a_SIGKILLed_run_leaves_a_container_its_label_still_finds(product, tmp_path):
    # arrange: the one cancel no handler sees, so the run's container outlives it by construction
    child, name = _start(product, tmp_path)

    # act
    child.send_signal(signal.SIGKILL)
    child.wait(timeout=60)

    # assert: the label is what makes the orphan findable - and the name says it is this run's
    left = _left_by(product)
    assert len(left) == 1, f"expected the one orphan SIGKILL cannot prevent, found {left}"
    names = run(["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"label=simplon.run={product}"])
    assert names.out.split() == [name]


# --- si#412: a catalogue site, not only `toolchain:run` -----------------------------------------------

#: The child for a SITE: `test:image`'s `_run_once`, exactly as `smoke` calls it, under a registered
#: product - the shape every si#412 site shares (`docker.lifecycle` + `docker.stopped_on_interrupt`
#: around the site's own `run`). Captured output, unlike `toolchain:run`'s streamed one.
SITE_CHILD = """
import sys
from pathlib import Path
from simplon.domain import context
from simplon.tasks import image
product, root, ref, seconds = sys.argv[1:5]
context.set_current(context.ProductContext(product, Path(root), Path(root) / "x.yaml"))
print("-", flush=True)
sys.exit(image._run_once(ref, [], "sleep " + seconds, "", 0))
"""


@needs_docker
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_a_cancelled_smoke_run_leaves_no_container_behind(product, tmp_path, sig):
    # arrange: the child is the same as `_start`'s except for what it runs
    src = str(Path(simplon.__file__).resolve().parents[1])
    child = subprocess.Popen([sys.executable, "-c", SITE_CHILD, product, str(tmp_path), IMAGE, SLEEP],
                             env={**os.environ, "PYTHONPATH": src}, stdout=subprocess.PIPE, text=True)
    assert child.stdout is not None
    child.stdout.readline()
    deadline = time.monotonic() + 120
    while not _left_by(product):
        assert time.monotonic() < deadline and child.poll() is None, "the smoke container never started"
        time.sleep(0.2)
    time.sleep(1.0)

    # act
    child.send_signal(sig)
    rc = child.wait(timeout=60)

    # assert
    assert _left_by(product) == [], f"{sig.name} left the smoke container behind"
    assert rc == -sig, f"{sig.name}: the child exited rc {rc}"
