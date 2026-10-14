"""si#412: a cancelled run on the CONTAINER ROUTE leaves nothing running - not the kernel's own container,
and not the toolchain container the kernel had started inside it.

WHAT WAS THERE BEFORE, AND WHAT TURNED OUT TO BE MISSING. `launch.sh.j2` ended the container route with
`exec docker run --rm --init -i ...` and no name and no label, so firn's cleanup could find `toolchain:run`
containers by label after si#409 and this one only by its bind mount. si#412 read that as "no cleanup on
interrupt" as well, and the measurement says otherwise: because the line is `exec`ed, the pid a cancel
reaches IS the docker client, the client proxies SIGINT/SIGTERM into the container, and `--init` hands
them to the kernel. What was missing is only the label - which is exactly what a SIGKILL needs.

THE REPRODUCTION. A real scaffolded product, the real launcher, a real daemon, and a kernel image that is
real too - the newest one this machine holds - with ONE thing replaced: the product's `orchestrator`
module is a stand-in that starts a sibling `alpine sleep` through the WORKTREE's own
`docker.run_container`, copied into the mount, so the unwind under test is this branch's and not the
image's. Each test waits until both containers run, signals the SHELL - the process a runner cancel and a
`kill <pid>` reach - and asks the daemon what carries the product's label afterwards.

Seen red on 2026-10-14 against the launcher on main: every test, because the kernel container carried no
label and so could not be found at all - the `_start` wait for two labelled containers never ended.

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

import simplon
from conftest import docker_is_usable
from simplon.cli import bootstrap
from simplon.kernel.run import run

#: A published kernel image: python, the kernel's dependencies and a docker CLI. Which kernel version it
#: carries does not matter, because the stand-in below imports the worktree's `simplon` first.
KERNEL = "ghcr.io/marcozwyssig/simplon:v0.26.1"

#: The sibling the stand-in kernel starts, as in test_container_lifecycle_e2e.py.
SIBLING = "alpine:3.20"


def _have(image: str) -> bool:
    return docker_is_usable() and run(["docker", "image", "inspect", image]).ok


needs_images = pytest.mark.skipif(not (_have(KERNEL) and _have(SIBLING)),
                                  reason=f"needs a docker daemon holding {KERNEL} and {SIBLING}")

#: The stand-in kernel: start one sibling the way `toolchain:run` does, and wait on it.
STAND_IN = """
import os, sys
sys.path.insert(0, "/src/kernel-under-test")
from simplon.adapters import docker
product = os.environ["LAUNCH_PRODUCT"]
name = docker.container_name(product)
line = ["docker", "run", "--rm", *docker.lifecycle_args(name, product), "%s", "sleep", "60"]
sys.exit(docker.run_container(line, name).rc)
""" % SIBLING


def _labelled(product: str, *, running: bool = False) -> list[str]:
    argv = ["docker", "ps", "-q", "--filter", f"label=simplon.run={product}"]
    return run(argv if running else [*argv[:2], "-a", *argv[2:]]).out.split()


@pytest.fixture
def product(tmp_path):
    """A scaffolded product whose kernel is the stand-in, and every labelled container gone afterwards."""
    name = f"si412{uuid.uuid4().hex[:8]}"
    bootstrap.write(name, tmp_path)
    (tmp_path / "deploy" / "image").mkdir(parents=True, exist_ok=True)
    (tmp_path / "deploy" / "image" / "image.pin").write_text(f"{KERNEL}\n", encoding="utf-8")
    module = next(tmp_path.rglob("src/python/orchestrator"))
    (module / "__init__.py").write_text("", encoding="utf-8")
    (module / "__main__.py").write_text(STAND_IN, encoding="utf-8")
    shutil.copytree(Path(simplon.__file__).parent, tmp_path / "kernel-under-test" / "simplon",
                    ignore=shutil.ignore_patterns("__pycache__"))
    # the dependency install is not what is under test: a stamp newer than requirements.txt skips it
    stamp = tmp_path / "build" / "container" / "python" / ".deps-stamp"
    stamp.parent.mkdir(parents=True)
    stamp.touch()
    yield name, tmp_path
    for cid in _labelled(name):
        run(["docker", "rm", "-f", cid])


def _start(name: str, root: Path) -> subprocess.Popen[bytes]:
    """The launcher, on the container route, once BOTH its containers run: the kernel and its sibling."""
    shell = subprocess.Popen(["bash", str(root / f"{name}.sh")],
                             env={**os.environ, "DELIVERY_ROUTE": "container"},
                             stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if len(_labelled(name, running=True)) == 2:
            time.sleep(1.0)
            return shell
        if shell.poll() is not None:
            pytest.fail(f"the launcher exited rc {shell.returncode} before both containers ran")
        time.sleep(0.2)
    shell.kill()
    pytest.fail(f"never saw two containers labelled simplon.run={name}")


@needs_images
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_a_cancelled_container_route_leaves_neither_the_kernel_nor_its_sibling(product, sig):
    # arrange
    name, root = product
    shell = _start(name, root)

    # act: the cancel, delivered to the launcher's shell alone
    shell.send_signal(sig)
    rc = shell.wait(timeout=60)

    # assert: nothing labelled for this product is left, running or stopped
    assert _labelled(name) == [], f"{sig.name} left a container behind"
    # assert: and the run still looks cancelled - the launcher IS the client, which exits 128 + signal
    assert rc == 128 + sig, f"{sig.name}: the launcher exited rc {rc}"


@needs_images
def test_a_ctrl_c_that_reaches_the_whole_group_leaves_nothing_either(product):
    # arrange: a Ctrl-C at a terminal without `-t` signals the shell AND the docker client, so the kernel
    # is told twice - once by the client's own signal proxy, once by the trap
    name, root = product
    shell = _start(name, root)

    # act
    os.killpg(shell.pid, signal.SIGINT)
    shell.wait(timeout=60)

    # assert
    assert _labelled(name) == [], "a group-wide SIGINT left a container behind"


@needs_images
def test_a_SIGKILLed_launcher_leaves_containers_its_label_still_finds(product):
    # arrange: the one cancel no trap sees
    name, root = product
    shell = _start(name, root)

    # act
    shell.send_signal(signal.SIGKILL)
    shell.wait(timeout=60)

    # assert: both the kernel container and its sibling carry the product's label, so both are findable
    assert len(_labelled(name)) == 2
