"""Unit tests for the allure test-report primitives (timestamped archive name, the pytest argv, the
per-module result merge). Moved here from netctl's testrun (netctl#730); no allure, no wall clock; AAA."""
import json
import os
import re
from datetime import datetime
from types import SimpleNamespace

from delivery import allure


def test_report_filename_produces_a_timestamped_single_file_html_name_for_a_given_time():
    # arrange: a fixed run start time
    now = datetime(2026, 7, 8, 14, 30, 15)

    # act
    name = allure.report_filename(now)

    # assert: allure-YYYYMMDD-HHMMSS.html, exactly (the dated regression baseline per run)
    assert name == "allure-20260708-143015.html"


def test_report_filename_defaults_to_now_matching_the_timestamp_pattern():
    # arrange / act: no time given -> uses the wall clock
    name = allure.report_filename()

    # assert: still the timestamped single-file shape
    assert re.fullmatch(r"allure-\d{8}-\d{6}\.html", name)


def test_report_filename_honours_a_custom_prefix():
    # arrange / act: a product may name the archive after its own suite
    name = allure.report_filename(datetime(2026, 7, 8, 14, 30, 15), prefix="report")

    # assert
    assert name == "report-20260708-143015.html"


def test_integration_pytest_argv_writes_allure_and_junit_with_no_pytest_html_flags():
    # arrange
    results, junit = "/r/allure-results", "/r/junit.xml"

    # act
    argv = allure.integration_pytest_argv("py", results, junit, [])

    # assert: raw allure results + machine-readable junit.xml are kept; pytest-html is gone (netctl#402)
    assert argv[:3] == ["py", "-m", "pytest"]
    assert f"--alluredir={results}" in argv
    assert f"--junit-xml={junit}" in argv
    assert not any(a.startswith("--html") for a in argv)
    assert "--self-contained-html" not in argv


def test_integration_pytest_argv_passes_extra_args_through_last():
    # arrange: caller-supplied pytest args (e.g. a -k filter)
    extra = ["-k", "dataplane"]

    # act
    argv = allure.integration_pytest_argv("py", "/r/allure-results", "/r/junit.xml", extra)

    # assert: extra args are appended verbatim after the standard flags
    assert argv[-2:] == extra


def test_merge_results_tags_result_json_with_the_parent_suite(tmp_path):
    # arrange: one source module with a result file that has no parentSuite yet, plus an attachment
    src = tmp_path / "src"
    src.mkdir()
    (src / "abc-result.json").write_text(json.dumps({"name": "t", "labels": []}), encoding="utf-8")
    (src / "abc-attachment.txt").write_text("log", encoding="utf-8")
    dst = tmp_path / "dst"

    # act
    allure.merge_results(str(dst), [str(src)])

    # assert: the result file gained parentSuite=Unit; the attachment copied through unchanged
    merged = json.loads((dst / "abc-result.json").read_text(encoding="utf-8"))
    assert {"name": "parentSuite", "value": "Unit"} in merged["labels"]
    assert (dst / "abc-attachment.txt").read_text(encoding="utf-8") == "log"


def test_merge_results_does_not_double_tag_an_already_labelled_result(tmp_path):
    # arrange: a result already carrying a parentSuite label
    src = tmp_path / "src"
    src.mkdir()
    labelled = {"name": "t", "labels": [{"name": "parentSuite", "value": "Existing"}]}
    (src / "x-result.json").write_text(json.dumps(labelled), encoding="utf-8")
    dst = tmp_path / "dst"

    # act
    allure.merge_results(str(dst), [str(src)], parent_suite="Unit")

    # assert: the existing label is preserved, none appended
    merged = json.loads((dst / "x-result.json").read_text(encoding="utf-8"))
    suites = [l for l in merged["labels"] if l["name"] == "parentSuite"]
    assert suites == [{"name": "parentSuite", "value": "Existing"}]


def test_merge_results_skips_missing_source_dirs(tmp_path):
    # arrange / act: a non-existent source dir must be ignored, not raise
    dst = tmp_path / "dst"
    allure.merge_results(str(dst), [str(tmp_path / "nope")])

    # assert: dst is created and empty
    assert dst.is_dir()
    assert list(dst.iterdir()) == []


# --- render_report (moved here from netctl's testrun.allure_report, netctl#1406) ------------------------


def _fake_allure_generate(argv, **kwargs):
    """Stand in for the allure CLI: write the single-file index.html into whatever -o names."""
    out = argv[argv.index("-o") + 1]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<html>allure single-file</html>")
    return SimpleNamespace(ok=True, rc=0)


def test_render_report_moves_the_single_file_to_the_timestamped_name_and_removes_the_scratch_dir(tmp_path, monkeypatch):
    # arrange: allure CLI present; a fake `generate` that writes the single-file index.html into -o
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/allure" if name == "allure" else None)
    monkeypatch.setattr(allure, "report_filename", lambda **kw: "allure-20260708-143015.html")
    monkeypatch.setattr(allure, "run", _fake_allure_generate)

    # act
    allure.render_report(report_dir)

    # assert: exactly the dated single-file report remains; the transient scratch dir is cleaned up
    dated = os.path.join(report_dir, "allure-20260708-143015.html")
    assert os.path.isfile(dated)
    assert "allure single-file" in open(dated, encoding="utf-8").read()
    assert not os.path.exists(os.path.join(report_dir, "allure-report"))


def test_render_report_renders_the_results_dir_and_prefix_it_is_given(tmp_path, monkeypatch):
    # arrange: an EXPLORATORY run passes its own quarantined results dir and its own archive prefix, so
    # its report can never be mistaken for the canonical one (netctl#1406)
    report_dir = str(tmp_path)
    quarantine = os.path.join(report_dir, "allure-results-filtered")
    os.makedirs(quarantine)
    seen = {}
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/allure" if name == "allure" else None)
    monkeypatch.setattr(allure, "run",
                        lambda argv, **kw: seen.update(argv=argv) or _fake_allure_generate(argv, **kw))

    # act
    allure.render_report(report_dir, quarantine, prefix="allure-filtered")

    # assert: allure read the quarantined dir, and the archive carries the distinguishing prefix
    assert quarantine in seen["argv"]
    assert any(f.startswith("allure-filtered-") and f.endswith(".html") for f in os.listdir(report_dir))
    assert not any(re.fullmatch(r"allure-\d{8}-\d{6}\.html", f) for f in os.listdir(report_dir))


def test_render_report_writes_no_report_and_keeps_results_when_neither_allure_nor_docker_present(tmp_path, monkeypatch):
    # arrange: no allure CLI and no docker -> the render tool is unavailable
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: None)

    def _must_not_run(*a, **k):
        raise AssertionError("render_report must not shell out when no render tool is available")

    monkeypatch.setattr(allure, "run", _must_not_run)

    # act
    allure.render_report(report_dir)

    # assert: no dated report was produced; the raw results dir is left intact for a later `allure serve`
    assert not any(f.startswith("allure-") and f.endswith(".html") for f in os.listdir(report_dir))
    assert os.path.isdir(os.path.join(report_dir, "allure-results"))
