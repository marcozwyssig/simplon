"""Unit tests for the allure test-report primitives (timestamped archive name, the pytest argv, the
per-module result merge). Moved here from netctl's testrun (netctl#730); no allure, no wall clock; AAA."""
import json
import os
import re
from datetime import datetime

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
