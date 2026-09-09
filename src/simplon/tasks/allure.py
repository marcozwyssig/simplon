"""Allure + pytest test-report primitives for the *ctl orchestrators (netctl#730, extracted from netctl's
orchestrator testrun).

The mechanics of the merged single-file Allure report - the timestamped archive name, the pytest argv
that emits raw allure results + a machine-readable junit.xml, the per-module result merge that tags a
parent suite, and the render of the merged single-file HTML - are product-agnostic. A product keeps its OWN
suite wiring (which modules, which gradle tasks, which lab waits) and calls these to produce/merge/render
the report. No product knowledge, which is why it is a module of its own rather than a section of the
runner.

IT MOVED HERE FROM THE TOP LEVEL (#37), and the reason is the head above. It used to sit beside `cli.py`
and `context.py` on the strength of the claim that two named products reused it - and neither did, and one
of the two does not install this kernel at all. Measured across every repository that DOES
(`simplon.surface.CONSUMERS` plus this one's own orchestrator), the sole importer is
`simplon.tasks.testrun`, in this same directory. Product-agnostic is not the same as imported by a product: the first is a property of the
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


@dataclass(frozen=True)
class Merge:
    """What one merge actually DID, so its caller can report a result instead of an intention (#64).

    `merge_results` used to return None, and the only thing a caller could say afterwards was that it had
    called it - which is what the log line said: ``per-module results merged (parentSuite=Java)``. Two
    different runs got that same sentence and neither had done what it claims. A JUnit XML falls into the
    verbatim branch and carries NO parentSuite, so the report showed three test cases with
    ``parentSuite=None`` under a line announcing they had one; and a declared source dir that does not
    exist is skipped silently, so a Gradle build that stopped before writing anything produced the same
    sentence as a successful merge. "Nothing to do" and "done" were indistinguishable from outside.

    This function is the only thing that knows the difference, so it is the thing that has to say it: how
    many results were tagged, how many were already labelled, how many files went through unchanged and
    therefore carry no parent suite, and which declared sources were not there at all.
    """

    parent_suite: str = ""
    tagged: int = 0
    already_labelled: int = 0
    copied: int = 0
    environments: int = 0
    present: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    skipped_dirs: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()

    @property
    def files(self) -> int:
        """Every entry this merge handled, however it handled it."""
        return self.tagged + self.already_labelled + self.copied + self.environments

    @property
    def results(self) -> int:
        """The entries that are RESULTS, as against the environment merged beside them (si#133).

        `empty` below counts everything this merge handled, which is the right question for the report
        step: did the merge do anything at all. A GATE asks something narrower - did this LEVEL produce
        evidence - and an `environment.properties` is not evidence, it is the run's own verdict travelling
        with the results. A source dir holding only that file would answer "not empty", and a runner that
        wrote one and then fell over before writing a single result would report green with no case in the
        archive, which is the false green the caller of this property exists to remove.
        """
        return self.tagged + self.already_labelled + self.copied

    @property
    def empty(self) -> bool:
        """Nothing was merged - the case that used to read exactly like a successful merge.

        A source dir holding ONLY subdirectories is empty by this measure and says so, which is the whole
        point: `binary/` next to no XML at all is a run that produced nothing, not a run that merged. A
        source dir holding only files older than this run is empty too, and that is the loudest case
        there is (si#70): the build wrote nothing, and what is lying there is the last run's.
        """
        return self.files == 0

    @property
    def line(self) -> str:
        """The one sentence the report step logs, and every number in it is counted rather than assumed."""
        declared = len(self.present) + len(self.missing)
        where = f"{len(self.present)} of {declared} declared source dirs"
        if self.empty:
            said = f"nothing merged: {where} present"
            if self.missing:
                said += f", missing: {', '.join(self.missing)}"
            elif not self.stale:
                said += " and they hold no files"
            return said + self._stale + self._dirs
        parts = []
        if self.tagged:
            parts.append(f"{self.tagged} tagged parentSuite={self.parent_suite}")
        if self.already_labelled:
            parts.append(f"{self.already_labelled} already labelled")
        if self.copied:
            # THE HALF THE OLD LINE GOT WRONG. These are not allure result files, so nothing tags them and
            # they reach the report under whatever suite their own format names.
            parts.append(f"{self.copied} copied unchanged, carrying no parentSuite")
        if self.environments:
            parts.append(f"{self.environments} {ENVIRONMENT} merged")
        said = f"merged {self.files} file{'' if self.files == 1 else 's'} from {where}: " + ", ".join(parts)
        if self.missing:
            said += f"; missing: {', '.join(self.missing)}"
        return said + self._stale + self._dirs + self._unreached

    @property
    def unreached(self) -> bool:
        """A parent suite was asked for and NOTHING here could take it (si#79).

        The `copied` count above already says these files carry no parentSuite; this is the question the
        CALLER has to ask, which is whether the merge as a whole managed to apply the one it was handed. A
        merge that tagged nothing is not the OK it used to be logged as - the manifest declared a grouping
        and the archive has none of it - and this is what lets the report step say so at the time instead
        of leaving the reader to notice a missing level in the Suites tree afterwards.
        """
        return bool(self.copied) and not self.tagged and not self.already_labelled

    @property
    def _unreached(self) -> str:
        """WHY the parent suite reached nothing, and what to do instead (si#79).

        `parent_suite:` is accepted from every manifest and applies only to allure raw results, so a
        product whose runner writes JUnit XML declares a key that cannot act. si#61's shape - a key taken
        and left inert - and there the repair was to make the inert half WORK rather than to forbid the
        key. So that was measured first, against a real file rather than assumed, and the answer is that
        allure cannot be told: MEASURED against the pinned image (allure 2.44.0) on gradle's own JUnit XML,
        the labels its junit-xml plugin produces are exactly resultFormat, suite, host, testClass and
        package, and five ways of asking for a sixth all came back without one - `allure.label.parentSuite`
        as a `<property>` on the `<testsuite>` and on the `<testcase>`, a bare `parentSuite` property, a
        `<testsuites>` wrapper carrying the name, and a `package=` attribute.

        So this is DIAGNOSIS and not a refusal. The kernel will not invent the label - writing allure raw
        results out of the XML would move the defect rather than remove it, and it would cost the capability
        si#62 measured: the XML travels unchanged and allure reads it with its own plugin, which is the only
        reason a product with no pytest gets an archive at all. What was missing is the sentence, at the
        moment, saying that the key did nothing and why, so the reader is not left to conclude they typed
        it wrong.
        """
        if not self.unreached:
            return ""
        return (f"; parentSuite={self.parent_suite} reached nothing - allure reads a non-allure result "
                f"with a format plugin of its own, and the junit-xml one has no parentSuite to set "
                f"(measured on allure 2.44.0: resultFormat, suite, host, testClass, package, and no "
                f"property, wrapper or attribute adds a sixth). Merge *-result.json to group a module, "
                f"or drop the key")

    @property
    def _stale(self) -> str:
        """The files that were there BEFORE this run started, named and not merged (si#70).

        This is the sentence the defect was missing. `merge_results` merges what lies in the source dir;
        whether it belongs to this run nobody used to ask, so a Gradle build that stopped in
        `:compileJava` produced an archive reading `{"failed":0,"passed":3,"total":3}` - the previous
        run's three green Java tests, presented as this run's result. Measured on a real product: the
        merged file's mtime was 66 seconds older than the run that shipped it.

        A skipped file is NAMED for the same reason a skipped subdirectory is: a silent skip is the same
        defect one line further down, and a reader whose runner legitimately preserves mtimes has to be
        able to see why their results did not travel.
        """
        if not self.stale:
            return ""
        return (f"; {len(self.stale)} file{'' if len(self.stale) == 1 else 's'} older than this run left "
                f"behind, as {'it is' if len(self.stale) == 1 else 'they are'} the previous run's "
                f"({', '.join(self.stale)})")

    @property
    def _dirs(self) -> str:
        """The subdirectories that were passed over, NAMED (#62).

        Not a footnote. A reader whose runner writes attachments into a subdirectory has to be told that
        those bytes did not travel, and a silent skip is the same defect this class was built against one
        line further down - the reason the crash it replaces was worth a ticket rather than an `isdir`.
        """
        if not self.skipped_dirs:
            return ""
        return (f"; skipped {len(self.skipped_dirs)} subdirector"
                f"{'y' if len(self.skipped_dirs) == 1 else 'ies'} allure would not read "
                f"({', '.join(self.skipped_dirs)})")


def merge_results(dst: str, srcs: list[str], *, parent_suite: str = "Unit",
                  not_before: float | None = None) -> Merge:
    """Copy each source dir's allure result files into ``dst``, tagging every ``*-result.json`` with
    ``parentSuite=<parent_suite>`` unless already labelled (so a merged report groups a module's results
    under one suite). Non-result files are copied through unchanged. Ported from the inline python in
    netctl's run_unit_tests.

    RETURNS WHAT IT DID (#64). A missing source dir is still skipped rather than refused - a standalone
    report step must archive what is present - but the skip is now COUNTED and named, because a caller
    that cannot tell it from a successful merge will announce one.

    THREE FATES, NOT TWO (#62). The docstring above described `*-result.json` and "everything else", and a
    SUBDIRECTORY was neither: it fell into `shutil.copy` and raised. It is now its own case - skipped, and
    named in the result - and the branch below carries the measurement the choice rests on.

    `not_before` IS THE ONE QUESTION THIS FUNCTION NEVER ASKED (si#70): does this file belong to the run
    that is merging it? A source dir is the PRODUCT's - a Gradle build's JUnit XML, an npm reporter's
    output - so nothing on the kernel's side of the seam ever empties it, and a run whose build stopped
    before writing anything merged the last run's results and shipped them as its own. Measured on a real
    Java product: a build that failed in `:compileJava` produced an archive reading
    `{"failed":0,"passed":3,"total":3}`, from a file 66 seconds older than the run.

    A caller that knows when its run began passes that instant and gets the files written since; every
    older one is SKIPPED and NAMED rather than dropped, because "nothing to merge" and "the last run's
    results are still lying here" are different sentences and the second is the interesting one. A caller
    with no run behind it - a standalone report step - passes None and merges what is present, which is
    that step's documented job.

    THE INSTANT IS THE CALLER'S AND IT SHOULD BE FLOORED TO THE SECOND. Some filesystems carry mtime at
    one- or two-second granularity, so a cutoff taken mid-second can read a file the run really did write
    as older than the run. Erring earlier merges at most a second of the previous run's leavings; erring
    later silently drops a genuine result, and only one of those two is recoverable by a reader.
    """
    os.makedirs(dst, exist_ok=True)
    tagged = labelled = copied = environments = 0
    present: list[str] = []
    missing: list[str] = []
    dirs: list[str] = []
    stale: list[str] = []
    for src in srcs:
        if not os.path.isdir(src):
            missing.append(src)
            continue
        present.append(src)
        for f in glob.glob(os.path.join(src, "*")):
            base = os.path.basename(f)
            if os.path.isdir(f):
                # A SUBDIRECTORY IS SKIPPED, AND SAID (#62). `glob` returns every entry, and this branch
                # used to hand each one to `shutil.copy`, which raises `IsADirectoryError` on a directory
                # - uncaught, with a `shutil` traceback and no sentence naming the cause. Gradle's default
                # `build/test-results/test/` holds exactly one (`binary/`, its own internal format beside
                # the JUnit XML), so the standard layout of the most common non-pytest runner in existence
                # made the report step crash, and the product had to redirect its Gradle report to a flat
                # directory to get an archive at all.
                #
                # Three answers were possible and they are not the same - skip, recurse, or refuse - so
                # the choice was MEASURED rather than argued. An allure results dir is read FLAT: a
                # results dir holding `aaa-result.json` and `sub/bbb-result.json`, rendered by the pinned
                # image, produced `total: 1` and the single suite `TopSuite`. The nested result was not
                # read at all. Recursing would therefore copy bytes the renderer ignores - and would do it
                # while reporting a merge, which is this module's own defect wearing a bigger hat.
                # Refusing would keep the crash under a nicer name and leave Gradle's ordinary layout
                # unusable. Skipping is the only one of the three that is true.
                #
                # It is COUNTED and NAMED, because a runner that does write attachments into a
                # subdirectory has to learn that they did not travel - and, by the measurement above, that
                # allure would not have read them there either.
                #
                # IT IS TESTED FIRST NOW (si#70), where it used to sit third. That is the same fix one
                # case over: a directory whose name happens to end in `-result.json` used to reach the
                # branch below and be opened as a file. Asking what an entry IS before asking what it is
                # called is the order that cannot be surprised.
                dirs.append(f)
                continue
            if not_before is not None and os.path.getmtime(f) < not_before:
                # OLDER THAN THE RUN THAT IS MERGING IT (si#70). Not this run's output, so not this run's
                # result - it stays where it is and is named in the line, and the archive says nothing
                # about it rather than presenting it as something that just happened.
                stale.append(f)
                continue
            if base.endswith("-result.json"):
                with open(f, encoding="utf-8") as fh:
                    r = json.load(fh)
                labels = r.setdefault("labels", [])
                if any(l.get("name") == "parentSuite" for l in labels):
                    labelled += 1
                else:
                    labels.append({"name": "parentSuite", "value": parent_suite})
                    tagged += 1
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
                environments += 1
            else:
                shutil.copy(f, os.path.join(dst, base))
                copied += 1
    return Merge(parent_suite=parent_suite, tagged=tagged, already_labelled=labelled, copied=copied,
                 environments=environments, present=tuple(present), missing=tuple(missing),
                 skipped_dirs=tuple(dirs), stale=tuple(stale))


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
