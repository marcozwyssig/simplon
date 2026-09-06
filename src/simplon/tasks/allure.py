"""Allure + pytest test-report primitives for the *ctl orchestrators (netctl#730, extracted from netctl's
orchestrator testrun).

The mechanics of the merged single-file Allure report - the timestamped archive name, the pytest argv
that emits raw allure results + a machine-readable junit.xml, the per-module result merge that tags a
parent suite, and the render of the merged single-file HTML - are product-agnostic. A product keeps its OWN
suite wiring (which modules, which gradle tasks, which lab waits) and calls these to produce/merge/render
the report. No product knowledge, which is why it is a module of its own rather than a section of the
runner.

IT MOVED HERE FROM THE TOP LEVEL (#37), and the reason is the head above. It used to sit beside `cli.py`
and `context.py` on the strength of the claim that "both netctl and infractl reuse them" - and neither
does. Measured across every repository that installs simplon (the kernel's own orchestrator,
agile-cockpit, netctl, infractl, asbundle, cleon), the sole importer is `simplon.tasks.testrun`, in this
same directory. Product-agnostic is not the same as imported by a product: the first is a property of the
code, the second is a promise about a path, and only the second decides where a module belongs. `simplon`
keeps a tombstone at the old path that says where this went; see `simplon.surface`.

Everything here is pure + filesystem-only EXCEPT `render_report`, which shells out to the allure CLI (else
docker). It sits beside the runner rather than inside it because it is allure mechanism through and
through and because it composes `report_filename` (netctl#1406, moved out of netctl's orchestrator.testrun).
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


#: The image the DOCKER fallback renders in, PINNED and validated by the same gate a product's manifest
#: image goes through (si#47). It is validated HERE, at import, rather than in a test: the kernel refuses
#: an unpinned image in a product's manifest with a paragraph of reasons, and named this one without a tag
#: - which is ':latest', which is "the same command renders with a different allure next month". A rule
#: the kernel argues for and exempts itself from is worth less than no rule.
#:
#: 2.44.0 is what ':latest' resolved to when the pin was written (both tags,
#: sha256:dc171ec796d58e133f0258d4934066747434c99bc2e35ff561269b81b27285b1), so the pin changed the
#: guarantee and not the bytes. Bump it deliberately, the way `DOCKER_CLI_VERSION` is bumped.
IMAGE = docker.pinned_image("frankescobar/allure-docker-service:2.44.0", "simplon.tasks.allure")


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
            elif base == ENVIRONMENT:
                # MERGED, never copied. This file carries the run's verdict (#30) - the one line a
                # reader handed only the HTML can still see - and `shutil.copy` REPLACED it, so the
                # products that merge something into their report were exactly the ones that lost it.
                #
                # The DESTINATION wins a key both sides declare, for two reasons that hold separately.
                # The verdict is what the kernel itself is answerable for, and a merged directory
                # restating it is describing its own run. And a merged directory usually lives OUTSIDE
                # the results dir, so a `results: clear` never touches it and it SURVIVES a run: after a
                # run of only the unit gate, that directory still holds last week's system stamp. Source
                # wins would write those stale lines over the fresh ones - the same defect this function
                # is being fixed for, one level down.
                #
                # A dropped key is said out loud rather than vanishing. A conflict rule without a message
                # is a quieter version of the same problem.
                incoming = read_environment(f)
                existing = read_environment(os.path.join(dst, base))
                clashes = sorted(k for k in incoming if k in existing and incoming[k] != existing[k])
                if clashes:
                    log.warn(f"{src}: {ENVIRONMENT} restates {', '.join(clashes)}; keeping this run's "
                             f"values and dropping the merged directory's")
                write_environment(dst, {**incoming, **existing})
            else:
                shutil.copy(f, os.path.join(dst, base))


#: Allure's own convention: a `key=value` file in the RESULTS dir, rendered as the report's Environment
#: widget. Not a simplon invention - which is exactly why the verdict of a run belongs in it (#30): it is
#: the one place inside the archive that a later reader already looks at, and it needs no viewer we ship.
ENVIRONMENT = "environment.properties"


def read_environment(path: str) -> dict[str, str]:
    """The `key=value` pairs in one properties file, or an empty map when there is none. Pure enough to
    reuse: `write_environment` merges into the destination's, `merge_results` reads a source's."""
    values: dict[str, str] = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_environment(results: str, values: dict[str, str]) -> str:
    """Merge `values` into the results dir's ``environment.properties`` and return its path.

    MERGE rather than overwrite: several gates append into one results dir over a run, and a report that
    showed only the last gate's environment would be a narrower statement than the run made. Existing keys
    are replaced by the new value; keys nobody restated survive.

    Values are flattened to one line, because the format has no continuation and a stray newline would
    silently truncate the file at that point - a value that eats the keys below it is worse than a value
    that reads a little cramped.
    """
    os.makedirs(results, exist_ok=True)
    path = os.path.join(results, ENVIRONMENT)
    merged = read_environment(path)
    merged.update({key: " ".join(str(value).split()) for key, value in values.items()})
    with open(path, "w", encoding="utf-8") as fh:
        for key in sorted(merged):
            fh.write(f"{key}={merged[key]}\n")
    return path


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
                  "--entrypoint", "allure", IMAGE,
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
