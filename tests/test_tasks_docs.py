"""Unit tests for simplon.tasks.docs (netctl#1280): the docToolchain render, driven purely by the
manifest's pinned image tag and the product root, read through simplon.context - no product import.

The docker invocation is stubbed, so these assert the DECISIONS (which tag is pinned, what is refused)
rather than that docker works. AAA throughout.
"""
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
