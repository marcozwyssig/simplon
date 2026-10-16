"""si#344 C.3: a producer that exits 0 without writing its test result is a failed step.

A test result declared and never written would be "nothing to do" passing for "tested" - the house defect -
so `results.held` compares each result's state before and after the body, not whether a file exists.

AAA; the name states the behaviour under test.
"""
import os
import time

import pytest

from simplon.domain import command
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


# --- a release reads its evidence (si#434) ------------------------------------------------------------
# Rule 6 binds every test result about what a release publishes to its `evidence` port, and until si#434
# nothing opened them: a release after a red test and one after a green test ran alike. Missing, red,
# unreadable and (si#439) green-about-nothing are four answers, and each says so in its own words.

GREEN = '{"image": "app", "verdict": 0, "runs": [{"reference": "r:1", "id": "sha256:aa"}]}'


def _refused(evidence) -> int:
    return results.guarded(evidence, lambda: 0)

def _record(root, text: str) -> None:
    (root / "build" / "test").mkdir(parents=True, exist_ok=True)
    (root / "build" / "test" / "app.json").write_text(text, encoding="utf-8")


def test_a_green_record_lets_the_release_run(_product):
    # arrange
    _record(_product, GREEN)

    # act / assert
    assert _refused(("checked",)) == 0


def test_a_red_record_refuses_the_release_and_names_the_verdict(_product, capsys):
    # arrange
    _record(_product, '{"image": "app", "verdict": 3, "runs": []}')

    # act
    rc = _refused(("checked",))

    # assert
    assert rc == 1
    err = capsys.readouterr().err
    assert "'checked' (build/test/app.json) is red: verdict 3" in err


def test_a_missing_record_refuses_in_other_words_than_a_red_one(_product, capsys):
    # act
    rc = _refused(("checked",))

    # assert: "the test has not run here" and "the test failed" are two outcomes
    assert rc == 1
    err = capsys.readouterr().err
    assert "'checked' (build/test/app.json) has not been written" in err
    assert "is red" not in err


@pytest.mark.parametrize("text", ["not json", '{"verdict": "0"}', '{"verdict": true}', "[0]"])
def test_a_record_that_is_no_verdict_refuses_rather_than_reading_as_green(_product, capsys, text):
    # arrange
    _record(_product, text)

    # act
    rc = _refused(("checked",))

    # assert
    assert rc == 1
    assert "'checked' (build/test/app.json) holds no verdict" in capsys.readouterr().err


def test_a_directory_result_holds_no_verdict_a_release_can_read(_product, capsys):
    # arrange
    (_product / "build" / "test" / "report").mkdir(parents=True)

    # act
    rc = _refused(("report",))

    # assert
    assert rc == 1
    assert "holds no verdict" in capsys.readouterr().err


def test_every_record_is_read_even_after_one_is_red(_product, capsys):
    # arrange
    _record(_product, '{"verdict": 1}')

    # act
    rc = _refused(("checked", "report"))

    # assert: which of them failed is the whole content of the answer
    assert rc == 1
    err = capsys.readouterr().err
    assert "'checked'" in err and "'report'" in err


def _release_spec():
    from simplon.domain import manifest
    from simplon.domain.artifactschema import PORTS

    return command.TaskCommand(impl="m:f", help="Publish.", task="release:image",
                               consumes={"image": ("app",), "evidence": ("checked",)},
                               ports=PORTS["release:image"])


@pytest.mark.parametrize("record, ran, rc", [(GREEN, True, 0), ('{"verdict": 2}', False, 1),
                                             (None, False, 1)])
def test_the_assembled_cli_runs_a_release_body_only_on_green_evidence(_product, record, ran, rc):
    # arrange: the live dispatch path, around a body that records whether it ran
    import typer

    from simplon import cli

    calls: list[str] = []

    def publish(name: str = "", tag: str = "") -> int:
        calls.append(name)
        return 0

    if record is not None:
        _record(_product, record)
    bound = cli._bound(publish, _release_spec(), where="release image")

    # act
    with pytest.raises(typer.Exit) as exit_:
        bound(name="app", tag="")

    # assert
    assert exit_.value.exit_code == rc
    assert bool(calls) is ran


def test_evidence_is_what_a_command_binds_to_a_port_taking_a_test_result():
    # act / assert: the image the release publishes is not evidence; the test result is
    assert results.evidence_of(_release_spec()) == ("checked",)


# --- what the evidence ran (si#439) -------------------------------------------------------------------
# A green record from an earlier build read green too. Each run now names its reference and the daemon id
# it ran, the guard hands those to the body, and a record that names nothing is refused - not read for its
# verdict alone (Marco's choice on si#439).

@pytest.mark.parametrize("runs", ['[]', '[{"reference": "r:1"}]', '[{"reference": "r:1", "id": ""}]',
                                  '[{"id": "sha256:aa"}]', '"r:1"'])
def test_a_green_record_that_names_no_subject_is_refused_in_its_own_words(_product, capsys, runs):
    # arrange: the shape every record had before si#439
    _record(_product, '{"image": "app", "verdict": 0, "runs": %s}' % runs)
    called: list[int] = []

    # act
    rc = results.guarded(("checked",), lambda: called.append(1) or 0)

    # assert
    assert rc == 1 and not called
    err = capsys.readouterr().err
    assert "'checked' (build/test/app.json) is green but does not name what it tested" in err
    assert "is red" not in err and "holds no verdict" not in err


def test_the_body_learns_what_the_evidence_ran_and_only_while_it_runs(_product):
    # arrange
    _record(_product, GREEN)
    seen: list = []

    # act
    rc = results.guarded(("checked",), lambda: seen.append(results.tested()) or 0)

    # assert: inside the guard the subjects; outside it None - "bound to nothing", not "names nothing"
    assert rc == 0
    assert seen == [(results.Subject("checked", "r:1", "sha256:aa"),)]
    assert results.tested() is None
