"""simplon's own `region-guard` task (si#344 B1): what `build model` checks before `firn gen` runs.

firn keeps the catalogue's protected region and rewrites everything outside it, with rc 0. A task appended
after the id line - the end of the file, the natural place to add one - loads, and the next `gen` deletes it
without a word; `test generated` is then green over the deletion if it was unstaged, and asks for it to be
committed if it was staged (final review of B1, measured on a scratch copy). So the outside of the region is
pinned here, by the same function the guard step runs.

AAA; the name states the behaviour under test.
"""
import sys

import pytest

from conftest import ROOT  # noqa: E402 - the one product-root anchor (si#283)

sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
from orchestrator import cli  # noqa: E402 - the product's own module, only reachable from here

CATALOGUE = ROOT / "src" / "simplon" / "catalogue.yaml"


def _committed() -> str:
    return CATALOGUE.read_text(encoding="utf-8")


def test_the_committed_catalogue_has_nothing_outside_its_region_that_firn_would_not_write_back():
    # act
    offending = cli.outside_region(_committed())

    # assert
    assert offending == []


def test_a_task_appended_after_the_id_line_is_refused_by_line_number():
    # arrange: the reviewer's case - a task at the end of the file, below firn's id line
    text = _committed()
    first_new = len(text.splitlines()) + 1
    text += "  late:\n    impl: \"x:y\"\n"

    # act
    offending = cli.outside_region(text)

    # assert
    assert offending == [first_new, first_new + 1]


def test_a_stray_key_above_the_begin_marker_is_refused_by_line_number():
    # arrange: a hand-written key among the generated kinds
    lines = _committed().splitlines(keepends=True)
    lines.insert(3, "stray: true\n")

    # act
    offending = cli.outside_region("".join(lines))

    # assert
    assert offending == [4]


_END = "# End Protected Region  [handwritten]\n"
_BEGIN = "# Begin Protected Region [handwritten]\n"


@pytest.mark.parametrize("damage", [
    pytest.param(lambda t: t.replace(_END, ""), id="End-gone"),
    pytest.param(lambda t: t.replace(_BEGIN, _BEGIN + _BEGIN), id="Begin-doubled"),
])
def test_a_catalogue_without_exactly_one_of_each_marker_is_refused_rather_than_judged(damage):
    # arrange: with a marker gone firn wipes the region; "nothing outside" would be the wrong answer
    text = damage(_committed())

    # act / assert
    with pytest.raises(ValueError, match="expected exactly one"):
        cli.outside_region(text)


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    """`region_guard` resolves its path against the product root; point that root at tmp_path."""
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return tmp_path


def test_the_guard_step_is_rc_1_naming_the_lines_and_where_they_belong(rooted, capsys):
    # arrange
    (rooted / "catalogue.yaml").write_text(_committed() + "  late: {}\n", encoding="utf-8")
    line = len(_committed().splitlines()) + 1

    # act
    rc = cli.region_guard("catalogue.yaml")

    # assert
    err = capsys.readouterr().err
    assert rc == 1
    assert f"line {line}" in err
    assert "inside the protected region" in err


def test_the_guard_step_is_rc_0_on_a_catalogue_with_nothing_outside(rooted):
    # arrange
    (rooted / "catalogue.yaml").write_text(_committed(), encoding="utf-8")

    # act / assert
    assert cli.region_guard("catalogue.yaml") == 0


@pytest.mark.parametrize("name", [None, "gone.yaml"])
def test_the_guard_step_given_no_file_or_a_missing_one_is_rc_1_not_a_silent_pass(rooted, capsys, name):
    # act
    rc = cli.region_guard(name)

    # assert: a guard that checked nothing has not passed anything
    assert rc == 1
    assert capsys.readouterr().err
