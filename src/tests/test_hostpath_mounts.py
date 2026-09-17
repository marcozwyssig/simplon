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
import os
from pathlib import Path

import pytest

from conftest import ROOT

from simplon import hostpath
from simplon.run import Result
from simplon.tasks import toolchain


def _Ok() -> Result:
    """What a stubbed `run` hands back: a call that happened and succeeded."""
    return Result(rc=0, out="", err="")

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


def test_the_mermaid_scratch_is_inside_the_tree_so_it_can_be_mounted_from_a_container(tmp_path,
                                                                                      monkeypatch):
    """The one mount source that used to be outside the product root, asserted through the argv.

    A `tempfile.mkdtemp()` path exists in the kernel container and nowhere else, so on the container
    route the daemon would create an empty directory of that name on the HOST and mount that - rc 0, no
    diagram, no message. Held by DRIVING `render_diagrams` and reading the mount out of the line it
    built, rather than by searching the module's text: this file's own prose says `tempfile` while
    explaining why the code no longer calls it, and a substring check cannot tell the two apart.
    """
    # arrange: the product root IS the mount, and the host knows it by another name
    from simplon import context
    from simplon.tasks import site
    monkeypatch.setenv(hostpath.HOST_ROOT_ENV, "/home/marco/proj")
    monkeypatch.setenv(hostpath.MOUNT_ROOT_ENV, str(tmp_path))
    context.set_current(context.ProductContext("democtl", tmp_path, tmp_path / "democtl.yaml"))
    page = tmp_path / "website" / "content" / "p.md"
    page.parent.mkdir(parents=True)
    page.write_text("# a page\n\n```mermaid\nflowchart TD\n  a-->b\n```\n", encoding="utf-8")
    seen: list[list[str]] = []

    def _fake(argv, **kw):
        seen.append(list(argv))
        # the render is judged on the SVG appearing, so write it where the argv says it goes - mapped
        # back through the translation, which is the whole point: the argv names the HOST path, and this
        # test IS the host
        host, container = argv[argv.index("-v") + 1].split(":", 1)
        here = tmp_path / Path(host).relative_to("/home/marco/proj")
        out = here / Path(str(argv[argv.index("-o") + 1])).name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("<svg/>", encoding="utf-8")
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(site, "run", _fake)
    monkeypatch.setattr(site.docker, "user_args", lambda: [])

    # act
    found, broken = site.render_diagrams(site.Site(image="hugomods/hugo:exts-0.148.2",
                                                   source="website", output="build"), tmp_path)

    # assert: one diagram, none broken, and the mount source is the HOST spelling of a directory inside
    # the tree - never a path that exists only in this container
    assert (found, broken) == (1, ())
    source = seen[0][seen[0].index("-v") + 1].split(":", 1)[0]
    assert source.startswith("/home/marco/proj/build/mermaid-")
