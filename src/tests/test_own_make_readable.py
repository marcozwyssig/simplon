"""simplon's own `make-readable` task (si#344 B1): the step after `firn gen` that undoes firn's 0600.

Here rather than beside the product because the product has no test directory of its own: its bodies
in `orchestrator.cli` are tested from this suite, as test_own_report.py does.

AAA; the name states the behaviour under test.
"""
import stat
import sys

import pytest

from conftest import ROOT  # noqa: E402 - the one product-root anchor (si#283)

sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
from orchestrator import cli  # noqa: E402 - the product's own module, only reachable from here


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    """`make_readable` resolves its paths against the product root; point that root at tmp_path."""
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return tmp_path


def test_every_named_file_written_0600_becomes_0644(rooted):
    # arrange: two files, because the site page joins the catalogue in Task 5
    names = ["a/catalogue.yaml", "b/kinds.md"]
    for name in names:
        (rooted / name).parent.mkdir(parents=True)
        (rooted / name).write_text("x", encoding="utf-8")
        (rooted / name).chmod(0o600)

    # act
    rc = cli.make_readable(names)

    # assert
    assert rc == 0
    assert [stat.S_IMODE((rooted / n).stat().st_mode) for n in names] == [0o644, 0o644]


def test_a_missing_file_is_rc_1_naming_it_not_a_silent_success(rooted, capsys):
    # arrange
    (rooted / "there.yaml").write_text("x", encoding="utf-8")

    # act
    rc = cli.make_readable(["there.yaml", "gone/kinds.md"])

    # assert: a stale entry in the list must not read as "done"
    assert rc == 1
    assert "gone/kinds.md" in capsys.readouterr().err


def test_no_files_at_all_is_rc_1(rooted, capsys):
    # act
    rc = cli.make_readable([])

    # assert: given nothing, it made nothing readable - that is not success
    assert rc == 1
    assert "no files" in capsys.readouterr().err
