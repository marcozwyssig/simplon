"""si#95: writing a language's ready-made configuration into a product's manifest.

WHY SCAFFOLDED AND NOT RESOLVED AT RUN TIME. A profile read at run time would let a kernel release change
how a product builds - the same class as an unpinned image, one level up. Written into the manifest, the
product owns what it runs from then on, and the kernel's table is a starting point rather than a
dependency.

AAA; the name states the behaviour under test.
"""
from difflib import SequenceMatcher

import pytest
import yaml

from simplon import bootstrap, catalogue
from simplon.orchestrator import manifest as manifest_mod
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


@pytest.fixture
def scaffolded(tmp_path, monkeypatch):
    """The manifest `simplon init` really writes - comments, flow style and all - with the seam on it.

    The starter manifest rather than a hand-made fixture, because si#110 was measured on that exact file:
    42 comment lines at column 0, 66 counting the indented ones, and none of them left afterwards.
    """
    path = tmp_path / "cppdemo.yaml"
    path.write_text(bootstrap.manifest_yaml("cppdemo"), encoding="utf-8")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: path)
    return path


def _comments(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def test_every_comment_in_the_manifest_survives_the_scaffolding(scaffolded):
    # arrange: the argument FOR scaffolding is that the product then reads its own build in its own
    # file, and a manifest emptied of its explanations is not a file anybody reads (si#110)
    before = _comments(scaffolded.read_text(encoding="utf-8"))
    assert len(before) > 40, "the fixture has to carry comments, or this test proves nothing"

    # act
    toolchain.scaffold("cpp", version="19")

    # assert
    assert _comments(scaffolded.read_text(encoding="utf-8")) == before


def test_the_scaffolder_only_inserts_and_never_rewrites_a_line(scaffolded):
    # arrange: a round trip through safe_dump also expands every `{ task: x }` flow mapping, so the diff
    # of a scaffolded manifest is the whole file and a review of it says nothing
    before = scaffolded.read_text(encoding="utf-8").splitlines()

    # act
    toolchain.scaffold("cpp", version="19")

    # assert: every opcode is an insertion; nothing that was there was replaced, moved or deleted
    after = scaffolded.read_text(encoding="utf-8").splitlines()
    tags = {op[0] for op in SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes()}
    assert tags <= {"equal", "insert"}


def test_the_spliced_block_still_loads_and_assembles(scaffolded):
    # arrange / act
    toolchain.scaffold("cpp", version="19")

    # assert: through the loader a real product goes through, catalogue and all
    mf = manifest_mod.load(scaffolded.read_text(encoding="utf-8"), catalogue=catalogue.load())
    assert {"configure", "compile", "unit", "analyse"} <= set(mf.groups["build"])
    assert mf.commands["build"]["compile"].impl == "simplon.tasks.toolchain:run_toolchain"


def test_a_shape_the_splice_cannot_place_is_refused_with_the_block_to_paste(tmp_path, monkeypatch,
                                                                            capsys):
    # arrange: `groups:` in flow style - legal YAML, and no line for the splice to insert after
    path = tmp_path / "product.yaml"
    path.write_text("product: demo\ngroups: { build: { commands: {} } }\n", encoding="utf-8")
    monkeypatch.setattr(toolchain, "_manifest_path", lambda: path)
    monkeypatch.setattr(toolchain.log, "die",
                        lambda m, *a, **k: (_ for _ in ()).throw(RuntimeError(m)))
    before = path.read_text(encoding="utf-8")

    # act / assert: a diagnosis, not a corrupted file
    with pytest.raises(RuntimeError):
        toolchain.scaffold("cpp", version="19")
    assert path.read_text(encoding="utf-8") == before
    assert "toolchain:run" in capsys.readouterr().out
