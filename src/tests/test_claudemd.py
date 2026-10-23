"""si#525: `support claude-md` writes the central CLAUDE.md and keeps the product's own region.

The central part is the kernel's, versioned with the simplon pin, so no product writes the working
agreements again. The product's part sits between two markers and survives every regeneration, byte for
byte, whatever its line endings. On the first run over a CLAUDE.md that predates the markers, the whole
existing file becomes the region - nothing a product wrote is ever dropped. `.claude/settings.json` gets
`enabledPlugins` (and `extraKnownMarketplaces`) from the effective set, and every other key is left alone.
"""
from __future__ import annotations

import json
import types

import pytest

from simplon.tasks import claudemd, claudeplugins


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A product root with a manifest the test sets, and the context pointed at it."""
    box = types.SimpleNamespace(root=tmp_path, data={"toolchains": ["claude"]})
    ctx = types.SimpleNamespace(name="demo", root=tmp_path, manifest_path=tmp_path / "demo.yaml",
                                manifest_data=lambda: box.data)
    monkeypatch.setattr(claudemd.context, "current", lambda: ctx)
    monkeypatch.setattr(claudeplugins.context, "current", lambda: ctx)
    box.md = tmp_path / "CLAUDE.md"
    box.settings = tmp_path / ".claude" / "settings.json"
    return box


def _lines(monkeypatch):
    lines: list[tuple[str, str]] = []
    for level in ("info", "ok", "warn", "error"):
        monkeypatch.setattr(claudemd.log, level, lambda msg, _l=level: lines.append((_l, msg)))
    return lines


def test_off_without_claude_toolchain(product, monkeypatch):
    # arrange
    product.data = {}
    lines = _lines(monkeypatch)

    # act
    rc = claudemd.generate()

    # assert
    assert rc == 0
    assert not product.md.exists() and not product.settings.exists()
    assert any("off" in msg for _, msg in lines)


def test_a_fresh_product_gets_the_central_part_and_an_empty_region(product):
    # act
    claudemd.generate()

    # assert
    text = product.md.read_bytes().decode()
    assert text.startswith("# demo - working agreements\n")
    assert "`./demo.sh support claude-md`" in text
    assert "{{" not in text
    assert text.endswith(f"{claudemd.BEGIN}\n{claudemd.END}\n")
    assert "—" not in text


def test_first_generation_moves_the_existing_file_into_the_region(product):
    # arrange
    product.md.write_text("# Mine\nkeep me\n", encoding="utf-8")

    # act
    claudemd.generate()

    # assert
    text = product.md.read_text(encoding="utf-8")
    assert text.endswith(f"{claudemd.BEGIN}\n# Mine\nkeep me\n{claudemd.END}\n")
    assert text.index("## The recurring defect") < text.index(claudemd.BEGIN)


@pytest.mark.parametrize("existing", [b"# Mine\r\nkeep me\r\n", b"# Mine\nno final newline"])
def test_regeneration_is_byte_identical(product, existing):
    # arrange: Review Focus 3
    product.md.write_bytes(existing)
    claudemd.generate()
    once = product.md.read_bytes()

    # act
    claudemd.generate()

    # assert
    assert product.md.read_bytes() == once
    assert existing.rstrip(b"\n") in once


def test_check_is_red_after_an_edit_outside_the_region(product, monkeypatch):
    # arrange
    claudemd.generate()
    product.md.write_text(product.md.read_text().replace("## Working practices", "## My practices"))
    lines = _lines(monkeypatch)

    # act
    rc = claudemd.generate(check=True)

    # assert
    assert rc == 1
    said = " ".join(msg for _, msg in lines)
    assert "CLAUDE.md" in said and "support claude-md" in said


def test_check_is_green_after_an_edit_inside_the_region(product):
    # arrange
    claudemd.generate()
    text = product.md.read_text()
    product.md.write_text(text.replace(f"{claudemd.BEGIN}\n", f"{claudemd.BEGIN}\nour own rule\n"))
    before = product.md.read_text()

    # act
    rc = claudemd.generate(check=True)

    # assert
    assert rc == 0
    assert product.md.read_text() == before


@pytest.mark.parametrize("body", [
    f"x\n{claudemd.END}\n{claudemd.BEGIN}\n",
    f"{claudemd.BEGIN}\na\n{claudemd.BEGIN}\nb\n{claudemd.END}\n",
    f"{claudemd.BEGIN}\nno end\n",
])
def test_broken_markers_are_refused(product, monkeypatch, body):
    # arrange
    product.md.write_text(body, encoding="utf-8")
    lines = _lines(monkeypatch)

    # act
    rc = claudemd.generate()

    # assert: refused by name, and the file is not touched
    assert rc == 1
    assert product.md.read_text(encoding="utf-8") == body
    assert any("marker" in msg for _, msg in lines)


def test_settings_keeps_other_keys_and_order(product):
    # arrange: Review Focus 4
    product.settings.parent.mkdir()
    product.settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"x": 1},
                                            "enabledPlugins": {"old@claude-plugins-official": True}}))

    # act
    claudemd.generate()

    # assert
    data = json.loads(product.settings.read_text())
    assert list(data)[:3] == ["permissions", "hooks", "enabledPlugins"]
    assert data["permissions"] == {"allow": ["Bash(ls)"]} and data["hooks"] == {"x": 1}
    assert data["enabledPlugins"] == {plugin: True for plugin in claudeplugins.BASE_PLUGINS}
    assert data["extraKnownMarketplaces"] == {
        "alexgreensh-token-optimizer": {"source": {"source": "github", "repo": "alexgreensh/token-optimizer"}}}
    assert product.settings.read_text().endswith("}\n")


def test_settings_drift_is_red_in_check(product):
    # arrange
    claudemd.generate()
    data = json.loads(product.settings.read_text())
    data["enabledPlugins"].pop(claudeplugins.BASE_PLUGINS[0])
    product.settings.write_text(json.dumps(data, indent=2) + "\n")

    # act / assert
    assert claudemd.generate(check=True) == 1


def test_an_unreadable_settings_file_is_refused_not_overwritten(product, monkeypatch):
    # arrange
    product.settings.parent.mkdir()
    product.settings.write_text("{ not json")
    lines = _lines(monkeypatch)

    # act
    rc = claudemd.generate()

    # assert
    assert rc == 1
    assert product.settings.read_text() == "{ not json"
    assert any("settings.json" in msg for _, msg in lines)
