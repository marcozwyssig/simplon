"""si#344 B1: the kernel's catalogue is written by firn, and firn v0.1.0 loses data with rc 0.

Measured on v0.1.0, 2026-10-12: a deleted region marker wipes the hand-written region (819 -> 17 lines,
rc 0), and a `kinds` selector that answers nothing writes an empty `kinds:` (rc 0). Neither is visible to
firn, so both are visible here. These run on the committed file, without docker, so they hold in every
environment the suite runs in.

AAA; the name states the behaviour under test.
"""
import re
from pathlib import Path

import yaml

from simplon import catalogue

CATALOGUE = Path(catalogue.__file__).resolve().parent / "catalogue.yaml"
KINDS_MODEL = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "vocabulary" / "kinds.firn"
BEGIN = "# Begin Protected Region [handwritten]"
END = "# End Protected Region  [handwritten]"


def _lines() -> list[str]:
    return CATALOGUE.read_text(encoding="utf-8").splitlines()


def test_the_hand_written_region_is_marked_exactly_once_and_in_order():
    # arrange / act
    lines = _lines()

    # assert: a lost marker makes the next `firn gen` discard everything between them, silently
    assert lines.count(BEGIN) == 1, "the Begin marker is missing or doubled"
    assert lines.count(END) == 1, "the End marker is missing or doubled"
    assert lines.index(BEGIN) < lines.index(END)


def test_the_region_carries_the_task_tree():
    # arrange
    lines = _lines()
    region = "\n".join(lines[lines.index(BEGIN) + 1:lines.index(END)])

    # act
    data = yaml.safe_load(region) or {}

    # assert: the region is where the tasks and groups live - not merely non-empty
    assert set(data) >= {"groups", "tasks"}, sorted(data)
    assert data["tasks"], "the region holds no tasks"


def test_every_kind_in_the_model_is_in_the_generated_section():
    # arrange: the kernel's spelling of a firn name (firn#962: a firn name has no `-`)
    model = re.findall(r"^(\w+) typeOf simplon\.pipeline\.ArtifactKind", KINDS_MODEL.read_text(), re.M)
    expected = {name.replace("_", "-") for name in model}

    # act
    kinds = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")).get("kinds") or {}

    # assert: an empty selector writes `kinds:` with rc 0, so the set must be compared, not just present
    assert len(model) > 0, "the model regex found no kinds - this test would pass over nothing"
    assert set(kinds) == expected


def test_the_generated_section_says_where_to_edit():
    # arrange
    lines = _lines()

    # act
    head = "\n".join(lines[:lines.index(BEGIN)])

    # assert: an edit outside the region is overwritten by the next gen without warning (firn#921)
    assert "kinds.firn" in head and "protected region" in head.lower()
