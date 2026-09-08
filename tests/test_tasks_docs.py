"""Unit tests for simplon.tasks.docs (netctl#1280): the docToolchain render, driven purely by the
manifest's pinned image tag and the product root, read through simplon.context - no product import.

The docker invocation is stubbed, so these assert the DECISIONS (which tag is pinned, what is refused)
rather than that docker works. AAA throughout.
"""
import os

import pytest

from simplon import context, docker, log
from simplon.context import ProductContext
from simplon.run import Result
from simplon.tasks import docs as docs_cmd


def _register(monkeypatch, tmp_path, data):
    ctx = ProductContext("sample", tmp_path, tmp_path / "sample.yaml")
    monkeypatch.setattr(context, "_current", ctx)
    monkeypatch.setattr(ProductContext, "manifest_data", lambda self: data)
    monkeypatch.setattr(docker, "ensure_docker", lambda: None)
    return ctx


def _stub_run(monkeypatch, rc=0, seen=None):
    def fake(argv, **kwargs):
        if seen is not None:
            seen.append(argv)
        return Result(rc=rc, out="", err="")
    monkeypatch.setattr(docs_cmd, "run", fake)


def _html(root):
    """A rendered artefact where the command looks for one."""
    out = root / docs_cmd.OUTPUT_DIR / "html5"
    out.mkdir(parents=True)
    (out / "index.html").write_text("<html></html>", encoding="utf-8")


# --- the pinned version ---------------------------------------------------------------------------------


def test_render_pins_the_image_tag_the_manifest_declares(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v9.9.9"})
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    rc = docs_cmd.render()

    # assert: the tag reaches the image reference verbatim, and the product root is what is mounted
    assert rc == 0
    argv = seen[0]
    assert "doctoolchain/doctoolchain:v9.9.9" in argv
    assert f"{tmp_path}:/project" in argv


def test_render_runs_the_container_on_the_amd64_platform(monkeypatch, tmp_path):
    # arrange: the image publishes no arm64 variant, so on Apple Silicon it runs under emulation or not
    # at all
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert
    argv = seen[0]
    assert argv[argv.index("--platform") + 1] == "linux/amd64"


# --- which uid the container runs as (si#78) -------------------------------------------------------------


def _blocked(path):
    """A directory the calling user cannot write, without being root: the permission bits are enough,
    because `os.access` asks with the real uid and an owner is refused by their own mode."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o500)


def test_render_runs_the_container_as_the_caller_when_the_tree_is_the_callers(monkeypatch, tmp_path):
    # arrange: the ordinary case - a product whose own build runs `--user`, so nothing under the tree is
    # root-owned. `--user 0:0` here is what made `build docs` followed by `build jar` rc 1 with
    # `Cannot create directory '/work/.gradle/8.14.3/fileHashes'` (si#78)
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert: the caller's own uid, and specifically NOT root - the second half is the assertion, because
    # a fix that merely stopped SAYING 0:0 while still running as root would pass the first
    argv = seen[0]
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "0:0" not in argv


def test_render_leaves_nothing_the_caller_cannot_delete_when_it_ran_as_the_caller(monkeypatch, tmp_path):
    # arrange: the same run, asserted from the consumer's side. `docker.user_args` is the kernel's one
    # rule about a container writing into a bind mount, and this render used to be its only exception
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert
    assert [a for a in seen[0] if a == "--user"] == ["--user"]
    assert docker.user_args() == ["--user", seen[0][seen[0].index("--user") + 1]]


def test_render_falls_back_to_root_when_the_tree_it_must_write_is_not_writable(monkeypatch, tmp_path):
    # arrange: netctl's case, unchanged - its `gradle_argv` passes no `--user`, so its containerised gradle
    # runs as root and leaves `.gradle/` root-owned. Measured against docToolchain v3.5.0: the same render
    # as the caller dies with `Could not update /project/.gradle/8.1.1/fileChanges/last-build.bin`, as root
    # it is rc 0
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    _blocked(tmp_path / docs_cmd.GRADLE_STATE)
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert
    argv = seen[0]
    assert argv[argv.index("--user") + 1] == "0:0"


def test_render_falls_back_to_root_for_an_unwritable_directory_below_the_tree(monkeypatch, tmp_path):
    # arrange: the MIXED tree, which is the one a real checkout carries after one root render and one
    # `--user` build: `.gradle/` belongs to the caller, `.gradle/8.1.1/` below it belongs to root. A check
    # that stats only the two tops calls this writable and hands the render a uid that dies on its first
    # bookkeeping write
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    _blocked(tmp_path / docs_cmd.GRADLE_STATE / "8.1.1" / "fileHashes")
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert
    argv = seen[0]
    assert argv[argv.index("--user") + 1] == "0:0"


def test_render_says_which_path_forced_it_to_run_as_root(monkeypatch, tmp_path, capsys):
    # arrange: the half si#78 asked for independently of the uid decision - a render that leaves a tree the
    # product's own build cannot write should say so, instead of letting gradle say it two commands later
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    _blocked(tmp_path / docs_cmd.GRADLE_STATE / "8.1.1")
    _stub_run(monkeypatch, rc=0)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert: the offending path, the consequence in the words gradle will use, and the way out
    said = capsys.readouterr().out
    assert str(docs_cmd.GRADLE_STATE / "8.1.1") in said
    assert "root-owned" in said
    assert "Cannot create directory" in said
    assert "root shell" in said


def test_render_does_not_run_as_root_merely_because_the_written_paths_exist(monkeypatch, tmp_path):
    # arrange: existence is not the question - ownership is. A check keyed on "has this tree been built
    # before" would send every second run back to root and rebuild the defect
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    for rel in docs_cmd.WRITTEN_PATHS:
        (tmp_path / rel / "deep" / "deeper").mkdir(parents=True)
        (tmp_path / rel / "deep" / "a-file").write_text("x", encoding="utf-8")
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert
    assert "0:0" not in seen[0]


def test_render_names_the_uid_it_ran_as_when_the_container_fails(monkeypatch, tmp_path, capsys):
    # arrange: with two branches, WHICH one ran is part of the cause - a permission message from the
    # caller branch means something entirely different from one out of the root branch
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    _stub_run(monkeypatch, rc=1)

    # act
    with pytest.raises(SystemExit):
        docs_cmd.render()

    # assert
    assert f"as {os.getuid()}:{os.getgid()}" in capsys.readouterr().err


def test_render_refuses_a_manifest_that_pins_no_version(monkeypatch, tmp_path):
    # arrange: an unpinned tool would render against whatever `latest` happens to be
    _register(monkeypatch, tmp_path, {})
    _stub_run(monkeypatch, rc=0)

    # act / assert
    with pytest.raises(ValueError, match="doctoolchain_version"):
        docs_cmd.render()


@pytest.mark.parametrize("version", ["latest", "", "  "])
def test_render_refuses_a_tag_that_is_declared_but_moves(monkeypatch, tmp_path, version):
    # arrange: si#47. This check used to ask only that a tag be DECLARED, so `doctoolchain_version:
    # latest` came through - while `docs:site` refused exactly that shape in a product's manifest, at
    # length and in writing. A kernel that argues for a pin in one task and takes `latest` in the other
    # has a rule and an exception, and the exception is what a reader remembers
    _register(monkeypatch, tmp_path, {"doctoolchain_version": version})
    _stub_run(monkeypatch, rc=0)

    # act / assert
    with pytest.raises(ValueError):
        docs_cmd.render()


def test_render_refuses_the_moving_tag_by_the_same_gate_the_site_build_uses(monkeypatch, tmp_path):
    # arrange: not "a check that behaves the same" but the same function - `simplon.docker.pinned_image`,
    # which is also what `docs:site` calls and what the kernel's own two images are validated by. The
    # message names the manifest key, so the reader is told which line to change
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "latest"})
    _stub_run(monkeypatch, rc=0)

    # act / assert
    with pytest.raises(ValueError) as excinfo:
        docs_cmd.render()
    message = str(excinfo.value)
    assert docs_cmd.VERSION_KEY in message
    assert "latest" in message

    # assert: and the hint sends the author to the right edit. This key holds a TAG, so the default
    # hint - "pin it as '<image>:<tag>', e.g. 'hugomods/hugo:exts-0.148.2'" - would be a message that
    # is confidently wrong about the one line the reader is about to change
    assert "hugomods" not in message
    assert f"{docs_cmd.VERSION_KEY}: v3.5.0" in message


@pytest.mark.parametrize("version", ["v3.5.0", "3.5.0", "5.3.2-boneyard"])
def test_render_accepts_a_tag_that_names_one_version(monkeypatch, tmp_path, version):
    # arrange: the gate must not cost a valid pin. The refusal is about tags that MOVE, and the tags
    # docToolchain actually publishes - a leading 'v' or not, a suffixed build - have to keep working.
    # 'v3.5.0' is not an example: it is the value netctl's manifest declares today, and this refusal is
    # an EXPRESSION rule, so the one manifest it can actually reach has to keep loading
    _register(monkeypatch, tmp_path, {"doctoolchain_version": version})
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    rc = docs_cmd.render()

    # assert
    assert rc == 0
    assert f"{docs_cmd.IMAGE_REPOSITORY}:{version}" in seen[0]


# --- the two failures ------------------------------------------------------------------------------------


def test_render_dies_when_the_container_reports_a_failure(monkeypatch, tmp_path):
    # arrange
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    _stub_run(monkeypatch, rc=1)

    # act / assert
    with pytest.raises(SystemExit):
        docs_cmd.render()


def test_render_dies_when_a_green_run_produced_no_html(monkeypatch, tmp_path):
    # arrange: docToolchain reports a config naming a missing file as a WARNING, so a stale path after a
    # directory move exits 0 with an empty tree (netctl#548) - the case this check exists for
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    _stub_run(monkeypatch, rc=0)

    # act / assert
    with pytest.raises(SystemExit):
        docs_cmd.render()
