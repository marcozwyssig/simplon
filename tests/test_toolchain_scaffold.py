"""si#95: writing a language's ready-made configuration into a product's manifest.

WHY SCAFFOLDED AND NOT RESOLVED AT RUN TIME. A profile read at run time would let a kernel release change
how a product builds - the same class as an unpinned image, one level up. Written into the manifest, the
product owns what it runs from then on, and the kernel's table is a starting point rather than a
dependency.

AAA; the name states the behaviour under test.
"""
import pytest
import yaml

from simplon.tasks import toolchain


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    """A product manifest with an empty build group, and the seam pointed at it."""
    path = tmp_path / "product.yaml"
    path.write_text("product: demo\ngroups:\n  build:\n    commands: {}\n", encoding="utf-8")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: path)
    return path


def test_scaffolding_writes_the_expanded_form_into_the_manifest(manifest):
    # arrange / act
    rc = toolchain.scaffold("cpp", version="19")

    # assert: the product reads its own build in its own file, which is what makes reviewing it possible
    data = yaml.safe_load(manifest.read_text())
    compile_cmd = data["groups"]["build"]["commands"]["compile"]
    assert rc == 0
    assert compile_cmd["task"] == "toolchain:run"
    assert compile_cmd["with"]["image"] == "silkeh/clang:19"
    assert compile_cmd["with"]["argv"][0] == "cmake"


def test_scaffolding_twice_changes_nothing_the_second_time(manifest):
    # arrange
    toolchain.scaffold("cpp", version="19")
    once = manifest.read_text()

    # act
    toolchain.scaffold("cpp", version="19")

    # assert: idempotent, so a product can re-run it after a kernel bump without fear
    assert manifest.read_text() == once


def test_a_hand_edited_command_is_never_clobbered(manifest, capsys):
    # arrange: a scaffolder that silently overwrites an edited build is worse than no scaffolder
    data = yaml.safe_load(manifest.read_text())
    data["groups"]["build"]["commands"]["compile"] = {
        "task": "toolchain:run", "with": {"image": "gcc:14", "argv": ["make"]}}
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    # act
    toolchain.scaffold("cpp", version="19")

    # assert: the edit survives, the reader is TOLD which command was left alone, and the rest still lands
    after = yaml.safe_load(manifest.read_text())
    commands = after["groups"]["build"]["commands"]
    assert commands["compile"]["with"]["image"] == "gcc:14"
    assert "unit" in commands
    assert "compile" in capsys.readouterr().out


def test_an_unknown_language_is_refused_before_anything_is_written(manifest, monkeypatch):
    # arrange
    monkeypatch.setattr(toolchain.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    before = manifest.read_text()

    # act / assert
    with pytest.raises(RuntimeError):
        toolchain.scaffold("cobol", "1")
    assert manifest.read_text() == before


def test_the_version_is_a_parameter_a_command_can_actually_carry(manifest):
    # arrange: `simplon.signatures.bindable` DROPS a VAR_KEYWORD parameter, so a `**params` body was
    # handed nothing at all - the loader accepted `with: { version: ... }` and discarded it, and every
    # language then raised `KeyError: 'version'` on the profile's first line (si#105)
    from simplon import signatures

    # act
    names = [p.name for p in signatures.bindable(toolchain.scaffold)]

    # assert: what the CLI can carry is exactly what the body declares
    assert names == ["language", "version"]
