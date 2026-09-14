"""THE KERNEL RENDERS A REPORT OF ITS OWN SUITE (si#248) - the join between the manifest, the impl and
both workflows.

WHY THIS IS GUARDED AT ALL. The catalogue carried `test:report` and simplon placed it nowhere, while
`with-what/test-levels.md` describes the report at length; a reader could only conclude the kernel ran
one on itself. That is the same shape as the type gate si#8 found - a capability shipped to everybody
else and never adopted at home - and the same shape as the empty `deploy` and `monitor` ribs, except
those are documented as empty and this was not.

THE ONE JOIN THAT CANNOT BE READ OFF EITHER SIDE, and it is why this module exists rather than a
paragraph. The directory the suite writes its raw results into is named TWICE: absolutely in
`orchestrator.cli:ALLURE_RESULTS`, because pytest runs with `cwd` inside `tests/` and a relative
`--alluredir` would land wherever the runner happened to stand; and relatively in the manifest, because
that is the only spelling `suites:` takes. Two spellings of one path is #46's second-source problem, and
nothing but this compares them. A rename on either side leaves a report that renders, exits 0, and
carries nothing - which is precisely this repository's recurring defect wearing an archive's clothes.
Measured on 2026-09-14 in the first draft of this very feature: a 2.5 MB Allure archive of zero tests,
with `OK` printed beside it.

AND THE `if: always()` RULE, which is the whole reason a CI report is worth rendering. A GitHub job stops
at its first failed step, so a report step without it exists for exactly the runs nobody needs it for.

AAA throughout.
"""
from __future__ import annotations

import pathlib

import yaml

from simplon.tasks import testrun

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
REPORT_COMMAND = "./simplon.sh test report"
ARTIFACT_ACTION = "actions/upload-artifact"


def _manifest() -> dict:
    return yaml.safe_load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))


def _suites() -> testrun.Suites:
    """The manifest's taxonomy through the KERNEL's own loader, not through a second reading of the YAML:
    a section this test accepted and the kernel refused would say nothing about what runs."""
    return testrun.declared(_manifest(), "simplon.yaml")


def _steps() -> list[tuple[str, dict]]:
    """Every step of every job in every workflow, as (file, the step mapping)."""
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, WORKFLOWS
    out = []
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if isinstance(step, dict):
                    out.append((path.name, step))
    return out


def test_the_manifest_declares_a_gate_the_kernels_own_loader_accepts():
    """A `suites:` section that `declared` refuses is a report step that fails at run time, on a runner,
    with the manifest three minutes behind it."""
    # act
    cfg = _suites()

    # assert
    assert [gate.name for gate in cfg.gates] == ["unit"], (
        "this kernel has one suite; a second gate arriving is a manifest that has to say which one clears")
    assert cfg.gates[0].command == "test suite", (
        "the gate names the product's own command rather than handing the pytest root to the kernel - "
        "this suite runs from INSIDE tests/ so its conftest applies")


def test_the_results_directory_is_the_same_one_on_both_sides_of_the_manifest():
    """THE SECOND SOURCE. `orchestrator.cli` writes the raw results, the manifest says where to read
    them, and a rename on either side renders an archive of nothing and exits 0."""
    # arrange
    import sys
    sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
    from orchestrator import cli  # noqa: PLC0415 - the product's own module, only reachable from here

    cfg = _suites()

    # act
    written = pathlib.Path(cli.ALLURE_RESULTS).resolve()

    # assert
    assert written == (ROOT / cfg.gates[0].results_from).resolve(), (
        f"the gate's `results_from:` must name the directory the suite really writes: "
        f"{cfg.gates[0].results_from} against {written}")
    assert list(cfg.merge) == [cfg.gates[0].results_from], (
        f"and the report step must merge that same directory - simplon's workflows run its own `test "
        f"suite` and then `test report`, so the report arrives with no gate run behind it and merges "
        f"only what `report: merge:` names. Got {list(cfg.merge)}")


def test_the_suite_really_writes_into_that_directory():
    """The half the path comparison above cannot see: that the argv carries `--alluredir` at all. Without
    it both sides agree about a directory nothing ever writes to."""
    # arrange
    import inspect
    import sys
    sys.path.insert(0, str(ROOT / "deploy" / "orchestrator" / "src" / "python"))
    from orchestrator import cli  # noqa: PLC0415

    # act
    body = inspect.getsource(cli.test_suite)

    # assert
    assert "--alluredir" in body and "ALLURE_RESULTS" in body, (
        f"the suite has to emit raw allure results for anything downstream to merge:\n{body}")


def test_every_workflow_that_reports_also_uploads_the_archive():
    """A report rendered onto a runner's disk and never uploaded is a step that spends time and produces
    nothing a person can open."""
    # act
    reporting = {name for name, step in _steps() if step.get("run", "").strip() == REPORT_COMMAND}
    uploading = {name for name, step in _steps() if ARTIFACT_ACTION in str(step.get("uses", ""))}

    # assert
    assert reporting, f"no workflow runs `{REPORT_COMMAND}`, so this test is ruling on nothing"
    assert reporting <= uploading, (
        f"these workflows render a report and upload nothing: {sorted(reporting - uploading)}")


def test_both_the_report_and_its_upload_run_even_when_a_gate_went_red():
    """THE POINT OF A CI REPORT. A GitHub job stops at its first failed step, so without `if: always()`
    the archive exists for exactly the runs nobody needs it for."""
    # act
    offenders = [f"{name}: {step.get('run') or step.get('uses')}"
                 for name, step in _steps()
                 if (step.get("run", "").strip() == REPORT_COMMAND
                     or ARTIFACT_ACTION in str(step.get("uses", "")))
                 and str(step.get("if", "")).strip() != "always()"]

    # assert
    assert offenders == [], (
        f"a report step that is skipped on failure archives only green runs: {offenders}")


def test_the_upload_refuses_to_find_nothing():
    """`if-no-files-found` defaults to a WARNING, which is the recurring defect in its most ordinary
    clothes: an upload that found no report and one that uploaded a good one look the same in the log."""
    # act
    uploads = [(name, step) for name, step in _steps() if ARTIFACT_ACTION in str(step.get("uses", ""))]

    # assert
    assert uploads, "no workflow uploads the archive, so this test is ruling on nothing"
    for name, step in uploads:
        assert (step.get("with") or {}).get("if-no-files-found") == "error", (
            f"{name}: an upload that finds no report must say so, not warn")
