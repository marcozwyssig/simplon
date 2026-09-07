"""Unit tests for the allure test-report primitives (timestamped archive name, the pytest argv, the
per-module result merge). Moved here from netctl's testrun (netctl#730); no allure, no wall clock; AAA."""
import json
import os
import pathlib
import re
from datetime import datetime
from types import SimpleNamespace

from simplon.tasks import allure


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


# --- what a merge REPORTS about itself (si#64) ------------------------------------------------------------


def test_a_merge_that_did_nothing_is_distinguishable_from_one_that_worked(tmp_path):
    # arrange: the two runs that used to produce the identical log line - one real merge, one whose
    # declared source dir is not there because the build stopped before writing it
    src = tmp_path / "src"
    src.mkdir()
    (src / "a-result.json").write_text(json.dumps({"name": "t", "labels": []}), encoding="utf-8")

    # act
    did = allure.merge_results(str(tmp_path / "d1"), [str(src)], parent_suite="Java")
    nothing = allure.merge_results(str(tmp_path / "d2"), [str(tmp_path / "gone")], parent_suite="Java")

    # assert: the whole of si#64's second half. "Nothing to do" and "done" now differ in the value AND in
    # the sentence, which is the only place the caller could ever have got it from.
    assert not did.empty and nothing.empty
    assert did.line != nothing.line
    assert "nothing merged" in nothing.line
    assert str(tmp_path / "gone") in nothing.line


def test_a_merge_says_how_many_results_it_tagged_and_how_many_it_only_copied(tmp_path):
    # arrange: exactly the mixture a Java product produces - allure raw results from its pytest gate and a
    # JUnit XML from Gradle, in one merge
    src = tmp_path / "src"
    src.mkdir()
    (src / "a-result.json").write_text(json.dumps({"name": "t", "labels": []}), encoding="utf-8")
    (src / "b-result.json").write_text(
        json.dumps({"name": "u", "labels": [{"name": "parentSuite", "value": "Existing"}]}),
        encoding="utf-8")
    (src / "TEST-demo.CalculatorTest.xml").write_text("<testsuite/>", encoding="utf-8")

    # act
    merged = allure.merge_results(str(tmp_path / "dst"), [str(src)], parent_suite="Java")

    # assert: three files, three different fates, and the sentence keeps them apart
    assert (merged.tagged, merged.already_labelled, merged.copied) == (1, 1, 1)
    assert merged.files == 3
    assert "1 tagged parentSuite=Java" in merged.line
    assert "1 already labelled" in merged.line
    assert "1 copied unchanged, carrying no parentSuite" in merged.line


def test_a_merge_does_not_claim_a_parent_suite_for_the_files_it_only_copied(tmp_path):
    # arrange: a JUnit XML alone - the measured Java case, where the report showed three test cases with
    # parentSuite=None under a log line announcing they had one
    src = tmp_path / "src"
    src.mkdir()
    (src / "TEST-demo.CalculatorTest.xml").write_text("<testsuite/>", encoding="utf-8")

    # act
    merged = allure.merge_results(str(tmp_path / "dst"), [str(src)], parent_suite="Java")

    # assert: nothing was tagged, and the sentence does not say a parent suite was applied to anything.
    # The FILE still has to arrive - allure reads JUnit XML with its own plugin, and a merge that
    # protected the sentence by dropping the file would have removed a capability to fix a message.
    assert merged.tagged == 0
    assert "tagged parentSuite" not in merged.line
    assert (tmp_path / "dst" / "TEST-demo.CalculatorTest.xml").is_file()


def test_a_merge_counts_the_sources_it_found_and_names_the_ones_it_did_not(tmp_path):
    # arrange: two declared sources, one of them absent - a product whose second module never ran
    src = tmp_path / "there"
    src.mkdir()
    (src / "a-result.json").write_text(json.dumps({"name": "t", "labels": []}), encoding="utf-8")
    gone = str(tmp_path / "not-there")

    # act
    merged = allure.merge_results(str(tmp_path / "dst"), [str(src), gone], parent_suite="Java")

    # assert: a partial merge reports as a partial merge, with the missing dir named rather than counted
    assert merged.present == (str(src),) and merged.missing == (gone,)
    assert "1 of 2 declared source dirs" in merged.line
    assert f"missing: {gone}" in merged.line


# --- a subdirectory in a source dir (si#62) ---------------------------------------------------------------


def _gradle_layout(tmp_path):
    """Gradle's DEFAULT `build/test-results/test/`, byte for byte the shape that crashed the report step:
    the JUnit XML beside a `binary/` directory of Gradle's own internal format."""
    src = tmp_path / "test-results" / "test"
    (src / "binary").mkdir(parents=True)
    (src / "TEST-demo.CalculatorTest.xml").write_text("<testsuite/>", encoding="utf-8")
    for name in ("output.bin", "output.bin.idx", "results.bin"):
        (src / "binary" / name).write_bytes(b"\x00\x01")
    return src


def test_merge_results_does_not_die_on_gradles_default_layout(tmp_path):
    # arrange: the measured crash - `IsADirectoryError: [Errno 21] Is a directory: .../test/binary`,
    # uncaught, out of shutil, with no sentence naming the cause
    src = _gradle_layout(tmp_path)
    dst = tmp_path / "dst"

    # act
    merged = allure.merge_results(str(dst), [str(src)], parent_suite="Java")

    # assert: it completes, and the file that MATTERS arrived. Before this, a Java product had to redirect
    # its Gradle report to a flat directory to get an archive at all.
    assert (dst / "TEST-demo.CalculatorTest.xml").is_file()
    assert merged.copied == 1


def test_a_skipped_subdirectory_is_named_rather_than_silently_dropped(tmp_path):
    # arrange
    src = _gradle_layout(tmp_path)

    # act
    merged = allure.merge_results(str(tmp_path / "dst"), [str(src)], parent_suite="Java")

    # assert: "nothing to do" that nobody is told about is the defect this module hunts. A runner that
    # writes attachments into a subdirectory has to learn that those bytes did not travel.
    assert merged.skipped_dirs == (str(src / "binary"),)
    assert "skipped 1 subdirectory allure would not read" in merged.line
    assert str(src / "binary") in merged.line


def test_a_skipped_subdirectory_is_not_copied_in_some_other_shape(tmp_path):
    # arrange
    src = _gradle_layout(tmp_path)
    dst = tmp_path / "dst"

    # act
    allure.merge_results(str(dst), [str(src)], parent_suite="Java")

    # assert: skip means SKIP. Measured against the pinned allure image, a results dir holding
    # `aaa-result.json` and `sub/bbb-result.json` renders `total: 1` and the suite `TopSuite` alone - the
    # nested result is not read - so recursing would copy bytes the renderer ignores while reporting a
    # merge, and a flattened `binary/` would put Gradle's internal format where allure looks for results.
    assert sorted(p.name for p in dst.iterdir()) == ["TEST-demo.CalculatorTest.xml"]


def test_a_source_dir_holding_only_a_subdirectory_reports_nothing_merged(tmp_path):
    # arrange: the run where Gradle wrote its binary output and no XML - nothing for the report to take
    src = tmp_path / "only-dirs"
    (src / "binary").mkdir(parents=True)

    # act
    merged = allure.merge_results(str(tmp_path / "dst"), [str(src)], parent_suite="Java")

    # assert: a merge that met one directory and no file is EMPTY, and does not read as a merge that
    # worked merely because the source dir existed
    assert merged.empty
    assert "nothing merged" in merged.line
    assert "skipped 1 subdirectory" in merged.line


def test_the_verbatim_passthrough_is_how_foreign_results_reach_the_report_at_all(tmp_path):
    """THE CAPABILITY THIS MUST NOT LOSE, stated as an assertion because it was never designed.

    A Gradle product's JUnit XML reaches the archive for one reason only: it is not `*-result.json`, so it
    falls into the verbatim branch and is copied through, and allure then reads it with its own junit-xml
    plugin - no converter anywhere in this kernel. That is incidental rather than decided, which is
    exactly why it needs a test: a later tidy-up of this function that filtered the `else` down to "files
    allure understands" would delete a working capability and pass every other assertion here.

    Measured end to end on the real product (si#26, re-measured on si#63): with the XML merged, the
    rendered archive reports `{"failed":0,"passed":3,"total":3}` green and `{"failed":1,"passed":2,
    "total":3}` with one Java test flipped red - two Java cases plus the one Python case.
    """
    # arrange: Gradle's XML, an unrelated attachment, and a subdirectory, in one source
    src = _gradle_layout(tmp_path)
    (src / "some-attachment.txt").write_text("stderr", encoding="utf-8")
    dst = tmp_path / "dst"

    # act
    merged = allure.merge_results(str(dst), [str(src)], parent_suite="Java")

    # assert: BOTH non-result files travelled, byte for byte, and the skip took only the directory
    assert (dst / "TEST-demo.CalculatorTest.xml").read_text(encoding="utf-8") == "<testsuite/>"
    assert (dst / "some-attachment.txt").read_text(encoding="utf-8") == "stderr"
    assert merged.copied == 2


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


def _fake_docker_allure(report_dir):
    """Stand in for `docker run ... allure generate`: write index.html where the CONTAINER path maps to on
    the host, so the fake obeys the same `-v {report_dir}:/work` mount the real call declares."""
    def _run(argv, **kwargs):
        out = argv[argv.index("-o") + 1]
        host = os.path.join(report_dir, os.path.relpath(out, "/work"))
        os.makedirs(host, exist_ok=True)
        with open(os.path.join(host, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html>allure single-file</html>")
        return SimpleNamespace(ok=True, rc=0)
    return _run


def test_render_report_via_docker_runs_as_the_calling_user_so_the_mounted_report_dir_stays_writable(tmp_path, monkeypatch):
    # arrange: no local allure CLI, docker present. The image runs as uid 1000; the mounted report dir
    # belongs to the HOST user, so a container writing as its own uid hits
    # java.nio.file.AccessDeniedException: /work/allure-report on every host whose uid is not 1000 (#6).
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    seen = {}
    monkeypatch.setattr(allure, "run",
                        lambda argv, **kw: seen.update(argv=argv) or _fake_docker_allure(report_dir)(argv, **kw))

    # act
    allure.render_report(report_dir)

    # assert: the container writes as the calling user, and the flag is a `docker run` flag (before the image)
    argv = seen["argv"]
    assert "--user" in argv, f"docker render must pass --user; got {argv}"
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert argv.index("--user") < argv.index(allure.IMAGE)


def test_render_report_returns_the_archive_path_it_wrote(tmp_path, monkeypatch):
    # arrange: a working local CLI
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/allure" if name == "allure" else None)
    monkeypatch.setattr(allure, "report_filename", lambda **kw: "allure-20260708-143015.html")
    monkeypatch.setattr(allure, "run", _fake_allure_generate)

    # act
    render = allure.render_report(report_dir)

    # assert: the caller can tell an archive was written, and where
    assert render.ok
    assert not render.failed
    assert render.report == os.path.join(report_dir, "allure-20260708-143015.html")
    assert render.tool == "allure"


def test_render_report_calls_a_present_local_cli_that_exits_nonzero_a_failure(tmp_path, monkeypatch):
    # arrange: the allure CLI is installed and the generate fails
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/allure" if name == "allure" else None)
    monkeypatch.setattr(allure, "run", lambda argv, **kw: SimpleNamespace(ok=False, rc=1))

    # act
    render = allure.render_report(report_dir)

    # assert: a tool that IS there and failed is a failure the caller can act on - the case a bare warning
    # hid behind rc 0 (#6). Still no exception: the caller decides how loud it gets.
    assert render.failed
    assert not render.ok
    assert render.tool == "allure"


def test_render_report_calls_a_present_docker_render_that_exits_nonzero_a_failure(tmp_path, monkeypatch):
    # arrange: docker is there (so the tool exists) and the container fails - the AccessDenied case of #6
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(allure, "run", lambda argv, **kw: SimpleNamespace(ok=False, rc=1))

    # act
    render = allure.render_report(report_dir)

    # assert
    assert render.failed
    assert render.tool == "docker"


def test_render_report_calls_a_tool_that_produced_no_index_html_a_failure(tmp_path, monkeypatch):
    # arrange: the CLI exits 0 but writes nothing - green rc, no archive; still a present tool that failed
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: "/usr/bin/allure" if name == "allure" else None)
    monkeypatch.setattr(allure, "run", lambda argv, **kw: SimpleNamespace(ok=True, rc=0))

    # act
    render = allure.render_report(report_dir)

    # assert
    assert render.failed
    assert render.report is None


def test_render_report_does_not_call_a_MISSING_tool_a_failure(tmp_path, monkeypatch):
    # arrange: neither allure nor docker. This stays a hint, NOT a failure - archiving must not itself be
    # the reason a run is red when the host simply has no render tool (the rule the docstring states).
    report_dir = str(tmp_path)
    os.makedirs(os.path.join(report_dir, "allure-results"))
    monkeypatch.setattr(allure.shutil, "which", lambda name: None)

    # act
    render = allure.render_report(report_dir)

    # assert: nothing rendered, and nothing to report as broken
    assert not render.ok
    assert not render.failed
    assert render.tool is None


# --- the environment the report shows (#30) ---------------------------------------------------------------


def test_write_environment_writesTheValuesAsAllurePropertiesInTheResultsDir(tmp_path):
    # arrange
    results = str(tmp_path / "allure-results")

    # act
    path = allure.write_environment(results, {"verdict": "setup-failed", "verdict.gate.system": "broke"})

    # assert: allure's own convention, so the report's Environment widget shows it with no viewer of ours
    assert os.path.basename(path) == allure.ENVIRONMENT
    lines = open(path, encoding="utf-8").read().splitlines()
    assert lines == ["verdict=setup-failed", "verdict.gate.system=broke"]


def test_write_environment_mergesIntoWhatIsAlreadyThere_becauseSeveralGatesShareOneResultsDir(tmp_path):
    # arrange: an earlier gate's environment
    results = str(tmp_path / "allure-results")
    allure.write_environment(results, {"verdict.gate.system": "passed", "lab": "gitlab-17"})

    # act: a later gate restates the run's verdict and adds its own line
    allure.write_environment(results, {"verdict.gate.acceptance": "failed (rc 1)", "verdict": "failed"})

    # assert: the earlier gate's line survives - a report showing only the last gate would be a narrower
    # statement than the run made
    written = dict(line.split("=", 1) for line in
                   open(results + "/" + allure.ENVIRONMENT, encoding="utf-8").read().splitlines())
    assert written == {"verdict": "failed", "verdict.gate.system": "passed",
                       "verdict.gate.acceptance": "failed (rc 1)", "lab": "gitlab-17"}


def test_write_environment_flattensAMultilineValue_soItCannotEatTheKeysBelowIt(tmp_path):
    # arrange: the format has no continuation, so a stray newline would truncate the file at that point
    results = str(tmp_path / "allure-results")

    # act
    allure.write_environment(results, {"note": "setup failed\nno suite ran", "after": "still here"})

    # assert
    lines = open(results + "/" + allure.ENVIRONMENT, encoding="utf-8").read().splitlines()
    assert lines == ["after=still here", "note=setup failed no suite ran"]


# --- merging must not delete the verdict it finds (#38) ----------------------------------------------

def _props(path):
    return dict(line.split("=", 1) for line in
                pathlib.Path(path).read_text(encoding="utf-8").splitlines() if "=" in line)


def test_merging_keeps_the_environment_the_destination_already_had(tmp_path):
    """#30 put the verdict INSIDE the report, where a reader handed only the HTML can still see why a run
    was red. `merge_results` copied every non-result file through, so a merged directory carrying its own
    environment.properties REPLACED it - and the products that lost the verdict were the ones that care
    enough about their report to merge something into it."""
    dst, src = tmp_path / "results", tmp_path / "system-stamp"
    dst.mkdir(); src.mkdir()
    allure.write_environment(str(dst), {"verdict": "passed", "verdict.gate.unit": "passed"})
    (src / allure.ENVIRONMENT).write_text("Systemtests.ergebnis=bestanden\n", encoding="utf-8")

    allure.merge_results(str(dst), [str(src)])

    merged = _props(dst / allure.ENVIRONMENT)
    assert merged["verdict"] == "passed"                      # survived
    assert merged["Systemtests.ergebnis"] == "bestanden"      # arrived


def test_the_destination_wins_a_key_both_sides_declare(tmp_path):
    """The verdict is the one line the kernel itself is answerable for. A merged directory restating it
    is describing its own run, not this one."""
    dst, src = tmp_path / "results", tmp_path / "stamp"
    dst.mkdir(); src.mkdir()
    allure.write_environment(str(dst), {"verdict": "failed"})
    (src / allure.ENVIRONMENT).write_text("verdict=passed\n", encoding="utf-8")

    allure.merge_results(str(dst), [str(src)])

    assert _props(dst / allure.ENVIRONMENT)["verdict"] == "failed"


def test_a_key_dropped_in_a_conflict_is_said_out_loud(tmp_path, capsys):
    """Today the alphabetically last source wins and the other's lines vanish without a word. A silent
    loss in a report is the shape of defect this whole issue is about."""
    dst, src = tmp_path / "results", tmp_path / "stamp"
    dst.mkdir(); src.mkdir()
    allure.write_environment(str(dst), {"verdict": "failed"})
    (src / allure.ENVIRONMENT).write_text("verdict=passed\n", encoding="utf-8")

    allure.merge_results(str(dst), [str(src)])

    # stdout, not stderr: this kernel matches bash, where only `die` writes to stderr and a warning is
    # ordinary output. Asserting the wrong stream is how a test claims a message is missing that is there.
    assert "verdict" in capsys.readouterr().out
