"""si#511 against a real daemon: a container that is not root writes through a declared mount, and the
tree is left with no root-owned directory - the anti-goal, measured rather than argued.

Measured before the kernel made the mount points (docker 29.9.1, `--user 4242:4242`): `-v` with a
missing source makes the daemon create it `root:root 755`, the container's write then fails with
`Permission denied`, and a missing target nested in the tree mount is left on the host root-owned too.

THE CALLER IS UID 4242 HERE, not whoever runs the suite. On a machine where the suite runs as root a
root caller proves nothing - root may write anywhere - so the mount points are made in a child process
that has become 4242, and the container runs as 4242. As any other uid the test is the caller itself.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from conftest import docker_is_usable
from simplon.kernel.run import run
from simplon.tasks import toolchain

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run a mount in")

IMAGE = "busybox:1.36"


def _as(uid: int, work) -> None:
    """Run `work()` as `uid` in a child process when this one is root; in this process otherwise."""
    if os.geteuid() != 0:
        work()
        return
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child
        try:
            os.setgid(uid)
            os.setuid(uid)
            work()
            os._exit(0)
        except BaseException:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0, "making the mount points as the caller failed"


@pytest.fixture
def tree():
    """An empty tree in a directory every uid can reach. pytest's own tmp_path sits under a 0700
    `pytest-of-<user>`, which a caller that became 4242 cannot enter."""
    made = Path(tempfile.mkdtemp(prefix="si511-"))
    os.chmod(made, 0o755)
    yield made
    shutil.rmtree(made, ignore_errors=True)


@needs_docker
def test_a_non_root_container_writes_through_a_mount_and_leaves_no_root_owned_dir(tree, monkeypatch):
    # arrange: a tree the caller owns, and a mount whose source and target do not exist yet
    caller = 4242 if os.geteuid() == 0 else os.getuid()
    if os.geteuid() == 0:
        os.chown(tree, caller, caller)
    cfg = toolchain.declared({"image": IMAGE, "argv": ["sh", "-c", "touch /work/src/frontend/node_modules/ok"],
                              "mounts": ["build/nm:/work/src/frontend/node_modules"]}, where="e2e")

    def make() -> None:
        assert toolchain._prepare_mounts(cfg, tree, "e2e") == ""

    _as(caller, make)
    monkeypatch.setattr(toolchain.docker, "user_args", lambda: ["--user", f"{caller}:{caller}"])

    # act
    line = toolchain.docker_argv(cfg, root=tree, product="e2e", instance="", extra=[])
    result = run(line, capture=True)

    # assert: the write went through the mount into the tree-local source, and nothing is root's
    assert result.rc == 0, result.out
    assert (tree / "build/nm/ok").is_file()
    owners = {Path(d, n).stat().st_uid for d, dirs, files in os.walk(tree) for n in dirs + files}
    assert owners == {caller}
