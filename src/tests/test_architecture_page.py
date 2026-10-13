"""si#390 part 1: the architecture page and the test data come from one model, so they agree."""
import re
from pathlib import Path

from generated import architecture

PAGE = Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "architecture.md"


def test_the_page_lists_every_component_with_its_layer():
    text = PAGE.read_text(encoding="utf-8")
    rows = {key: int(layer) for layer, key in re.findall(r"^\| (\d) \| `([a-z]+)` \|", text, re.M)}
    assert text.startswith("---\n"), "Hugo needs the front matter as the first bytes"
    assert rows == {key: layer for key, (layer, _) in architecture.COMPONENTS.items()}


def test_the_page_names_every_module_under_its_component():
    text = PAGE.read_text(encoding="utf-8")
    for key in architecture.COMPONENTS:
        section = re.search(rf"^## {key}\n\n(.*)$", text, re.M)
        assert section, f"no section for {key}"
        listed = set(re.findall(r"`([\w.]+)`", section.group(1)))
        assert listed == {m for m, c in architecture.MODULES.items() if c == key}


def test_the_page_lists_every_exception_with_its_ticket():
    text = PAGE.read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `([\w.]+)` -> `([\w.]+)` \| .* \| (si#\d+) \|$", text, re.M))
    assert rows == {(a, b, t) for a, b, _, t in architecture.EXCEPTIONS}


def test_the_page_says_what_the_test_does_not_see():
    assert "resolved at run time" in PAGE.read_text(encoding="utf-8")
