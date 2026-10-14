"""si#344 C.3: a producer that exits 0 without writing its test result is a failed step.

A test result declared and never written would be "nothing to do" passing for "tested" - the house defect -
so `results.held` compares each result's state before and after the body, not whether a file exists.

AAA; the name states the behaviour under test.
"""
import os
import time

import pytest

from simplon.domain import context, results
from simplon.domain.context import ProductContext

_MANIFEST = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  checked: { kind: test-result, path: build/test/app.json }
  report: { kind: test-result, path: build/test/report }
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    return tmp_path


def test_a_result_the_body_wrote_holds_the_rc(_product):
    # arrange
    snap = results.before(("checked",))
    (_product / "build" / "test").mkdir(parents=True)
    (_product / "build" / "test" / "app.json").write_text("{}", encoding="utf-8")

    # act / assert
    assert results.held(snap, 0) == 0


def test_a_result_not_written_turns_rc_0_into_1_naming_the_path(_product, capsys):
    # arrange
    snap = results.before(("checked",))

    # act
    rc = results.held(snap, 0)

    # assert
    assert rc == 1
    assert "build/test/app.json" in capsys.readouterr().err


def test_a_result_left_from_an_earlier_run_does_not_count_as_written(_product):
    # arrange: yesterday's file is there before the body runs, and the body does not touch it
    (_product / "build" / "test").mkdir(parents=True)
    old = _product / "build" / "test" / "app.json"
    old.write_text("{}", encoding="utf-8")
    os.utime(old, ns=(time.time_ns() - 10**10, time.time_ns() - 10**10))
    snap = results.before(("checked",))

    # act / assert
    assert results.held(snap, 0) == 1


def test_a_directory_result_counts_when_a_file_inside_it_is_new(_product):
    # arrange
    snap = results.before(("report",))
    (_product / "build" / "test" / "report").mkdir(parents=True)
    (_product / "build" / "test" / "report" / "a.json").write_text("{}", encoding="utf-8")

    # act / assert
    assert results.held(snap, 0) == 0


def test_a_failing_body_keeps_its_own_rc(_product):
    # act / assert
    assert results.held(results.before(("checked",)), 3) == 3


def test_an_artifact_that_is_not_a_test_result_is_not_watched(_product):
    # act / assert
    assert results.before(("app",)) == {}


def test_path_of_refuses_an_entry_that_is_not_a_test_result(_product):
    # act / assert
    with pytest.raises(ValueError, match="is a `image`, not a `test-result`"):
        results.path_of("app")
