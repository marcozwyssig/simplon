"""si#95: the toolchain declaration a product writes, and what the kernel refuses."""
import pytest

from simplon.tasks import toolchain


def _boom(msg, *a, **k):
    raise RuntimeError(msg)


def test_a_declaration_becomes_a_toolchain(monkeypatch):
    # arrange
    body = {"image": "gradle:jdk25", "workdir": "/work",
            "argv": ["gradle", "build"],
            "env": {"GRADLE_USER_HOME": "/home/gradle/.gradle"},
            "caches": [{"volume": "gradle-cache", "path": "/home/gradle/.gradle"}]}

    # act
    cfg = toolchain.declared(body, where="build.compile")

    # assert
    assert cfg.image == "gradle:jdk25"
    assert cfg.argv == ["gradle", "build"]
    assert cfg.caches == [toolchain.Cache(volume="gradle-cache", path="/home/gradle/.gradle")]


def test_an_unpinned_image_is_refused_by_the_one_gate(monkeypatch):
    # arrange: the refusal must come from pinned_image, not a second check written here
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle", "argv": ["gradle"]}, where="build.compile")
    assert "gradle" in str(e.value)


def test_a_declaration_without_argv_is_refused_by_name(monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.log, "die", _boom)

    # act / assert: the message names the key and where it was missing
    with pytest.raises(RuntimeError) as e:
        toolchain.declared({"image": "gradle:jdk25"}, where="build.compile")
    assert "argv" in str(e.value) and "build.compile" in str(e.value)


def test_workdir_defaults_so_a_product_need_not_write_it():
    # arrange / act
    cfg = toolchain.declared({"image": "gcc:14", "argv": ["make"]}, where="build.compile")

    # assert: the spec's "the user has only their parameters" - /work is the kernel's answer
    assert cfg.workdir == "/work"
