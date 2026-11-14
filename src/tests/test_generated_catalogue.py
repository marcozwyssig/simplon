"""si#344 B1: the kernel's catalogue is written by firn, and firn v0.1.0 loses data with rc 0. Since si#561 it is
written whole: `kinds:`, `groups:` and `tasks:` all come from the model, and there is no region left.

Measured on v0.1.0, 2026-10-12: a deleted region marker wipes the hand-written region (819 -> 17 lines,
rc 0), and a `kinds` selector that answers nothing writes an empty `kinds:` (rc 0). Neither is visible to
firn, so both are visible here. These run on the committed file, without docker, so they hold in every
environment the suite runs in.

AAA; the name states the behaviour under test.
"""
import re
from pathlib import Path

import yaml

from simplon.manifest import catalogue

CATALOGUE = catalogue.DEFAULT_PATH
KINDS_MODEL = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "vocabulary" / "kinds.firn"
TASKS_MODEL = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "catalogue" / "tasks.firn"
BEGIN = "# Begin Protected Region [handwritten]"
END = "# End Protected Region  [handwritten]"


def _lines() -> list[str]:
    return CATALOGUE.read_text(encoding="utf-8").splitlines()


def test_the_catalogue_is_generated_whole_with_no_hand_written_region():
    """si#561: `groups:` and `tasks:` are generated too, so nothing is left for a region to keep - and a region
    would keep a hand edit that `test generated` could not see."""
    # act
    lines = _lines()

    # assert
    assert BEGIN not in lines and END not in lines


def test_every_task_in_the_model_is_in_the_generated_section():
    # arrange
    model = re.findall(r'^\w+ typeOf simplon\.pipeline\.CatalogueTask \{\n  key = "([^"]+)"',
                       TASKS_MODEL.read_text(), re.M)

    # act
    tasks = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")).get("tasks") or {}

    # assert: an empty selector writes `tasks:` with rc 0, so the set must be compared, not just present
    assert len(model) > 0, "the model regex found no tasks - this test would pass over nothing"
    assert list(tasks) == model, "the generated section lists the model's tasks, in the model's order"


def test_every_kind_in_the_model_is_in_the_generated_section():
    # arrange: the kernel's spelling of a firn name (firn#962: a firn name has no `-`)
    model = re.findall(r"^(\w+) typeOf simplon\.pipeline\.ArtifactKind", KINDS_MODEL.read_text(), re.M)
    expected = {name.replace("_", "-") for name in model}

    # act
    kinds = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")).get("kinds") or {}

    # assert: an empty selector writes `kinds:` with rc 0, so the set must be compared, not just present
    assert len(model) > 0, "the model regex found no kinds - this test would pass over nothing"
    assert set(kinds) == expected


def test_the_generated_file_says_where_to_edit():
    # arrange
    lines = _lines()

    # act
    head = "\n".join(lines[:lines.index("kinds:")])

    # assert: an edit here is firn's W303 on the next gen (si#561, measured), so the head names the sources
    assert all(source in head for source in ("kinds.firn", "groups.firn", "tasks.firn"))


PAGE = Path(__file__).resolve().parents[1] / "site" / "content" / "with-what" / "kinds.md"


def test_the_reference_page_lists_every_kind_the_catalogue_offers_and_what_it_refines():
    # arrange
    kinds = catalogue.load().kinds
    text = PAGE.read_text(encoding="utf-8")

    # act
    rows = dict(re.findall(r"^\| `([\w-]+)` \| `?([\w-]*)`? \|", text, re.M))

    # assert: the page and the loader read the same model, so they agree or one of them is stale
    assert text.startswith("---\n"), "Hugo needs the front matter as the first bytes"
    assert rows == {k: v for k, v in kinds.items()}
