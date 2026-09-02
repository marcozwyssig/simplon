"""Unit tests for delivery.tasks.docs (netctl#1280): the docToolchain render, driven purely by the
manifest's pinned image tag and the product root, read through delivery.context - no product import.

The docker invocation is stubbed, so these assert the DECISIONS (which tag is pinned, what is refused)
rather than that docker works. AAA throughout.
"""
import pytest

from delivery import context, docker, log
from delivery.context import ProductContext
from delivery.run import Result
from delivery.tasks import docs as docs_cmd


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


def test_render_runs_the_container_as_root_on_the_amd64_platform(monkeypatch, tmp_path):
    # arrange: the image's default user (uid 100, `dtcuser`) cannot write the root-owned .gradle/ and
    # build/ trees a checkout carries, and the image publishes no arm64 variant. Measured as that user,
    # both `touch` probes give "Permission denied" (netctl#1133).
    _register(monkeypatch, tmp_path, {"doctoolchain_version": "v3.5.0"})
    seen = []
    _stub_run(monkeypatch, rc=0, seen=seen)
    _html(tmp_path)

    # act
    docs_cmd.render()

    # assert
    argv = seen[0]
    assert argv[argv.index("--user") + 1] == "0:0"
    assert argv[argv.index("--platform") + 1] == "linux/amd64"


def test_render_refuses_a_manifest_that_pins_no_version(monkeypatch, tmp_path):
    # arrange: an unpinned tool would render against whatever `latest` happens to be
    _register(monkeypatch, tmp_path, {})
    _stub_run(monkeypatch, rc=0)

    # act / assert
    with pytest.raises(ValueError, match="doctoolchain_version"):
        docs_cmd.render()


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
