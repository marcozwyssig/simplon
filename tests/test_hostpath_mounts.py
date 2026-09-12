"""Every bind mount this kernel writes goes through the host-path translation (si#201).

WHY A SWEEP AND NOT SIX ASSERTIONS. The container route breaks one task at a time: a mount source that
was not translated does not fail, it mounts an EMPTY directory the daemon creates on the host, and the
task then runs against nothing. Measured, with rc 0 and no message. So the thing that has to be held is
not "these six sites are right today" but "a seventh cannot be added without this file noticing", and
only a sweep over the tree says that.

The named CACHE volumes in `toolchain.docker_argv` are the deliberate exception and the reason the sweep
below is about the module rather than about the line: a `-v <product>-gradle-cache-dev:/home/gradle` names
a docker VOLUME, which the daemon owns on both routes and which must not be translated into a path.
"""
import ast
from pathlib import Path

import pytest

from conftest import ROOT

from simplon import hostpath
from simplon.tasks import toolchain

SRC = ROOT / "src" / "simplon"

#: What a bind-mount flag looks like in this kernel's argv builders.
MOUNT_FLAG = "-v"


def _modules_writing_a_mount() -> list[Path]:
    """Every kernel module whose SOURCE holds a `-v` argv element, found by parsing rather than grepping.

    Parsed for the reason `test_own_orch_block._counts_out_a_parent` gives: this file's own prose says
    `-v` while explaining the rule, and a text search cannot tell a docstring from an argv.
    """
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Constant) and node.value == MOUNT_FLAG for node in ast.walk(tree)):
            found.append(path)
    return found


def test_the_modules_that_write_a_bind_mount_are_the_ones_that_know_how_to_translate_it():
    # arrange / act
    writing = _modules_writing_a_mount()

    # assert: there is at least one, so this is not a sweep over nothing - the failure mode si#200's own
    # pin test names - and every one of them imports the translation
    assert writing, "no module writes a bind mount any more; this sweep has stopped saying anything"
    untranslated = [p.relative_to(ROOT).as_posix() for p in writing
                    if "hostpath" not in p.read_text(encoding="utf-8")]
    assert untranslated == [], (
        f"these build a `docker run -v` without simplon.hostpath: {untranslated}. On the container "
        f"route the daemon resolves that source against the HOST, creates an empty directory and mounts "
        f"it - rc 0, no message")


def test_the_toolchain_mount_is_the_host_path_when_there_is_one(tmp_path, monkeypatch):
    # arrange: the commonest of the mount sites, and the only one that is a pure function
    monkeypatch.setenv(hostpath.HOST_ROOT_ENV, "/home/marco/proj")
    monkeypatch.setenv(hostpath.MOUNT_ROOT_ENV, "/src")
    from simplon import context
    context.set_current(context.ProductContext("democtl", tmp_path, tmp_path / "democtl.yaml"))
    cfg = toolchain.Toolchain(image="python:3.12-slim", argv=["pytest"],
                              caches=[toolchain.Cache(volume="pip-cache", path="/cache")])

    # act
    argv = toolchain.docker_argv(cfg, type(tmp_path)("/src"), "democtl", "dev", [])

    # assert: the tree's mount moved onto the host root, and the NAMED volume beside it did not
    assert f"/home/marco/proj:{cfg.workdir}" in argv
    assert "democtl-pip-cache-dev:/cache" in argv


def test_the_toolchain_mount_is_unchanged_on_the_venv_route(tmp_path, monkeypatch):
    # arrange: the Gegenprobe, so the test above is about the translation rather than about any rewrite
    monkeypatch.delenv(hostpath.HOST_ROOT_ENV, raising=False)
    monkeypatch.delenv(hostpath.MOUNT_ROOT_ENV, raising=False)
    from simplon import context
    context.set_current(context.ProductContext("democtl", tmp_path, tmp_path / "democtl.yaml"))
    cfg = toolchain.Toolchain(image="python:3.12-slim", argv=["pytest"])

    # act
    argv = toolchain.docker_argv(cfg, tmp_path, "democtl", "dev", [])

    # assert
    assert f"{tmp_path}:{cfg.workdir}" in argv


def test_the_mermaid_scratch_lives_in_the_tree_so_it_can_be_mounted_from_a_container():
    # arrange: the one mount source that used to be outside the product root. A tempfile.mkdtemp() path
    # exists in the kernel container and nowhere else, so on the container route the daemon would create
    # an empty directory of that name on the HOST and mount that - the measured silent failure
    from simplon.tasks import site

    # act
    source = (SRC / "tasks" / "site.py").read_text(encoding="utf-8")

    # assert
    assert "tempfile" not in source, "the mermaid scratch is outside the mount again"
    assert 'scratch = root / "build" / "mermaid"' in source
    assert site.MERMAID_MOUNT      # the destination is still declared, so the pair is still a pair
