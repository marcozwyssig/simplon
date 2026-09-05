"""Allure + pytest test-report primitives for the *ctl orchestrators (netctl#730, extracted from netctl's
orchestrator testrun).

The mechanics of the merged single-file Allure report - the timestamped archive name, the pytest argv
that emits raw allure results + a machine-readable junit.xml, the per-module result merge that tags a
parent suite, and the render of the merged single-file HTML - are product-agnostic. A product keeps its OWN
suite wiring (which modules, which gradle tasks, which lab waits) and calls these to produce/merge/render
the report. No product knowledge, so both netctl and infractl reuse them.

Everything here is pure + filesystem-only EXCEPT `render_report`, which shells out to the allure CLI (else
docker). It lives here rather than beside the caller because it is allure mechanism through and through and
because it composes `report_filename` (netctl#1406, moved out of netctl's orchestrator.testrun).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime

from simplon import docker, log
from simplon.run import run


def report_filename(now: datetime | None = None, *, prefix: str = "allure") -> str:
    """The archived single-file report name for a run: ``<prefix>-YYYYMMDD-HHMMSS.html`` (netctl#402). Pure
    and now-injectable so the timestamped naming is unit-tested without invoking allure or the wall clock."""
    return f"{prefix}-{(now or datetime.now()):%Y%m%d-%H%M%S}.html"


def integration_pytest_argv(py: str, results: str, junit: str, extra: list[str]) -> list[str]:
    """The integration pytest argv: allure raw results + a small machine-readable junit.xml, and NO
    pytest-html (netctl#402 dropped --html/--self-contained-html; the single-file allure report supersedes
    the per-suite report.html). Pure so the flag set is locked by a unit test; ``extra`` is appended
    verbatim (e.g. a caller's -k filter)."""
    return [py, "-m", "pytest", f"--alluredir={results}", f"--junit-xml={junit}", *extra]


def merge_results(dst: str, srcs: list[str], *, parent_suite: str = "Unit") -> None:
    """Copy each source dir's allure result files into ``dst``, tagging every ``*-result.json`` with
    ``parentSuite=<parent_suite>`` unless already labelled (so a merged report groups a module's results
    under one suite). Non-result files are copied through unchanged. Ported from the inline python in
    netctl's run_unit_tests."""
    os.makedirs(dst, exist_ok=True)
    for src in srcs:
        if not os.path.isdir(src):
            continue
        for f in glob.glob(os.path.join(src, "*")):
            base = os.path.basename(f)
            if base.endswith("-result.json"):
                with open(f, encoding="utf-8") as fh:
                    r = json.load(fh)
                labels = r.setdefault("labels", [])
                if not any(l.get("name") == "parentSuite" for l in labels):
                    labels.append({"name": "parentSuite", "value": parent_suite})
                with open(os.path.join(dst, base), "w", encoding="utf-8") as fh:
                    json.dump(r, fh)
            else:
                shutil.copy(f, os.path.join(dst, base))


@dataclass(frozen=True)
class Render:
    """What one render attempt produced, so a caller can tell the TWO no-archive cases apart (#6).

    ``tool`` is the renderer that was actually available (``"allure"``, ``"docker"``, or None when the host
    has neither); ``report`` is the archive path when one was written. Hence ``failed``: a tool was there
    and did not produce the archive - the case that must be visible - as against a host with no renderer at
    all, which stays a hint. Same ``ok`` idiom as `simplon.run.Result`, and for the same reason: the caller
    inspects the outcome rather than guessing it from an exception that never comes.
    """

    report: str | None = None
    tool: str | None = None

    @property
    def ok(self) -> bool:
        """An archive was written."""
        return self.report is not None

    @property
    def failed(self) -> bool:
        """A render tool WAS available and produced no archive."""
        return self.tool is not None and self.report is None


def _docker_user() -> list[str]:
    """``--user uid:gid`` for the render container - `simplon.docker.user_args`, which is where this body
    moved when a SECOND containerised step needed the same argument for the same reason (#2's hugo site
    build). The rule and both measured failures are documented there; the case that put it in this module
    was `frankescobar/allure-docker-service` running as uid 1000 against a host uid that is not 1000, where
    allure died with ``java.nio.file.AccessDeniedException`` (#6). The local-CLI branch never had this
    because it already runs as the caller.
    """
    return docker.user_args()


def render_report(report_dir: str, results: str | None = None, *, prefix: str = "allure") -> Render:
    """Render the merged single-file allure HTML to a timestamped ``report_dir/<prefix>-YYYYMMDD-HHMMSS.html``
    (netctl#402) via the local allure CLI, else docker. ``results`` defaults to ``report_dir/allure-results``;
    a caller running an EXPLORATORY (argument-filtered) suite passes its own quarantined results dir plus a
    distinct prefix, so that run's archive can never be mistaken for the canonical one.

    ``allure --single-file`` emits index.html into an output DIR, so the render goes into a transient scratch
    dir and that one self-contained file is moved out to the dated name; each run thus archives a portable,
    diffable report (the regression baseline). Never raises: a MISSING render tool leaves the raw results in
    place with a hint, because archiving must not itself be the reason a run is red.

    A render tool that is PRESENT and fails is the other case, and not the same one (#6): there the warning
    was the only trace, and a caller that measures a run by its exit code - that is, every CI - learned
    nothing. It is now reported on stderr via `log.error` and, more usefully, in the returned `Render`,
    whose ``failed`` says a renderer was there and produced nothing. Still no exception: the decision of how
    red that gets belongs to the caller, which is the one that knows whether the archive was the point.
    """
    results = results or os.path.join(report_dir, "allure-results")
    scratch = os.path.join(report_dir, "allure-report")   # transient allure -o dir (holds the single index.html)
    report = os.path.join(report_dir, report_filename(prefix=prefix))
    hint = f"raw results kept; view them with: allure serve '{results}'"
    if shutil.which("allure") is not None:
        tool = "allure"
        log.info("generating allure HTML report (local CLI, single-file)")
        ok = run(["allure", "generate", "--single-file", "--clean", results, "-o", scratch]).ok
        if not ok:
            log.error(f"allure generate failed; no report archived for this run. {hint}")
            return Render(tool=tool)
    elif shutil.which("docker") is not None:
        tool = "docker"
        log.info("no local allure CLI; rendering the allure HTML report via docker (single-file)")
        ok = run(["docker", "run", "--rm", *_docker_user(), "-v", f"{report_dir}:/work", "-w", "/work",
                  "--entrypoint", "allure", "frankescobar/allure-docker-service",
                  "generate", "--single-file", "--clean",
                  os.path.join("/work", os.path.relpath(results, report_dir)), "-o", "/work/allure-report"]).ok
        if not ok:
            log.error(f"docker allure render failed; no report archived for this run. {hint}")
            return Render(tool=tool)
    else:
        log.info("install allure (your product's `install` command, or 'brew install allure') for the report")
        return Render()
    index = os.path.join(scratch, "index.html")
    if os.path.isfile(index):
        shutil.move(index, report)
        shutil.rmtree(scratch, ignore_errors=True)
        log.ok(f"allure HTML report: {report}")
        return Render(report=report, tool=tool)
    log.error(f"{tool} allure exited 0 but produced no {index}; no report archived for this run. {hint}")
    return Render(tool=tool)
