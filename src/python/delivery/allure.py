"""Allure + pytest test-report primitives for the *ctl orchestrators (netctl#730, extracted from netctl's
orchestrator testrun).

The mechanics of the merged single-file Allure report - the timestamped archive name, the pytest argv
that emits raw allure results + a machine-readable junit.xml, and the per-module result merge that tags a
parent suite - are product-agnostic. A product keeps its OWN suite wiring (which modules, which gradle
tasks, which lab waits) and calls these to produce/merge the report. Pure + filesystem-only, no product
knowledge, so both netctl and infractl reuse them.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
from datetime import datetime


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
