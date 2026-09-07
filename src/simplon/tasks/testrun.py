"""The lab-based suite runner and its allure plumbing (netctl#1406, moved out of netctl's
orchestrator.testrun).

Creating a per-suite venv, running pytest into a shared allure results dir, merging the already-written
per-module results and rendering the single-file archive is MECHANISM: it needs to know nothing about the
product whose suites it runs. The kernel already owned the two primitives it is built on (`simplon.pyvenv`,
`simplon.tasks.allure`), so this finishes a seam that was half-built.

WHAT THE PRODUCT CONTRIBUTES IS DATA, in its manifest's `suites` section, read RAW through
`ProductContext.manifest_data()` the way every other product-owned section is. That section is the test-level
TAXONOMY: which suite lives at which path, in which ORDER the gates run, and which gate CLEARS the shared
results dir versus APPENDS into it. Those are statements about a product's own test tree, so encoding them
as an `if` in here would be exactly the product knowledge the kernel must not hold.

Two kinds of callback flow in as data too, as "module:function" refs the kernel resolves the same way it
resolves a command's `impl:`:
  - `precondition` - a fail-fast health verdict run BEFORE any suite work (a non-zero rc aborts, and
    nothing is cleared, because nothing ran);
  - `preamble`     - the idempotent lab preparation a gate needs (converged inventory, provisioned
    services, a settled forwarding plane).
Both are SETUP, and a setup that falls over is not a red suite: the suite never ran, so the run has learned
nothing about the product. `simplon.verdict` holds that vocabulary and the reasoning for keeping it out of
the rc; `assess_gate` below produces it and writes it where a later reader actually looks - the stamp beside
the report dir and the archive's own Environment widget (#30). A suite that prepares its own lab inside a
session fixture, out of the kernel's sight, says so through the marker file at `SETUP_MARKER_ENV`.

A gate may also be declared as a bare `impl:` instead of a pytest `suite:`, for a level whose runner is the
product's own (a browser journey suite, say); the kernel just calls it for its rc and sequences it. SUCH A
GATE MAY OWN THE RESULTS DIR (si#61): `results: clear` on it says the run opens with this gate and the dir
starts empty, which is the only way a product with no pytest anywhere in it can write a loadable taxonomy.
Measured before the fix, on a Java product: both spellings of that section were refused, and the way out
was a pytest gate containing `assert True`, a 29 MB suite venv, and an archive that counted four tests for
a product that has three. Clearing is not writing - the kernel still learns exactly one number here - and
the empty half is pinned in `tests/test_suites_impl_only.py` beside the running half. It
therefore reports that gate in terms of the rc AND SAYS SO (#65) rather than borrowing the sentence written
for a suite it ran itself, and it opens the same setup marker to it as to a pytest gate (#59), so a runner
that knows its own preparation fell over has somewhere to say it.

EXPLORATORY RUNS (netctl#1406). A gate that declares `args: true` forwards the command's passthrough args
to pytest, which is what makes `<product> test system -k <expr>` - a ~60s answer instead of a ~24min gate -
possible at all. Such a run is by definition PARTIAL, so it must never write into the shared results dir:
clearing it and then filling it with one test's results would leave an archive that looks like a full gate
and reports a single test, and appending would mix two runs. Any run carrying extra args is therefore
QUARANTINED into its own results dir for the whole run (`filtered_results`), which is cleared up front and
rendered under its own archive prefix. The canonical archive of the last real gate stays untouched.
"""
from __future__ import annotations

import contextlib
import os
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Callable

import typer

from simplon import context, log, pyvenv, verdict
from simplon.tasks import allure
from simplon.awake import keep_awake
from simplon.orchestrator.manifest import resolve_ref
from simplon.run import run
from simplon.verdict import GateVerdict, RunVerdict, Verdict

# The manifest section this module owns.
SECTION = "suites"

# The shared results dir every canonical gate writes into, under the product's report dir. Fixed rather
# than declared: it is the allure convention every tool in the chain (`allure serve`, the render below,
# CI's artefact upload) already assumes, so making it configurable would buy nothing.
RESULTS = "allure-results"
# The transient dir `allure generate -o` writes into; cleared alongside the results by a `clear` gate.
SCRATCH = "allure-report"

CLEAR, APPEND = "clear", "append"

#: The name the report step carries in a run's record. It is not a declared gate, but it is a step the run
#: is answerable for, so the stamp names it the same way every time - including when it is the step that
#: raised (#63) and the record has to say which one that was.
REPORT = "report"
#: The rc the record carries for a step that raised. An exception leaves this process through the CLI,
#: which exits 1, so the record and the exit code agree; and `GateVerdict` refuses a red verdict carrying
#: rc 0 outright, because a red record with a green exit is the confusion the whole module is against.
ABANDONED_RC = 1

#: The file a SUITE OR A PRODUCT-OWNED RUNNER may drop to say that its own preparation fell over (#30),
#: and the environment variable that tells it where. The kernel names the two setup stages it sequences
#: itself - `precondition` and `preamble` - but a product whose lab is built inside a pytest session
#: fixture prepares it where the kernel cannot see: from out here that failure is just a non-zero pytest
#: rc, indistinguishable from a red suite. This is the seam for it, and it is deliberately the cheapest
#: one that works: a path in the environment and a file with a stage name in it. No import of the kernel
#: from inside the suite's own venv, no protocol, nothing to keep in step across a version bump.
#:
#: AN `impl:` GATE REACHES IT TOO (#59). It used to be a pytest-only seam by accident of placement rather
#: than by decision - the impl branch returned above it - which left the runner that needs it most, one
#: the kernel cannot see into at all, with two of the five outcomes. The cheapness is what makes it work
#: for both: an in-process callable reads the same environment variable and writes the same file as a
#: pytest child does.
SETUP_MARKER = "setup-failed"
SETUP_MARKER_ENV = "SIMPLON_SETUP_FAILED"
#: The rc a setup failure gets when the thing that failed left none of its own - a suite that dropped the
#: marker and still exited 0. The generic failure code, because the kernel has no better one to offer and
#: the alternative (passing the 0 on) is a red record with a green exit.
SETUP_FAILED_RC = 1

#: What a RED `impl:` gate says instead of `GateVerdict.line`'s default, and the whole of #65 in one
#: string. The default explains a failure by saying "the suite ran and reported failures", which is the
#: right sentence for a suite the kernel itself started and a FALSE one here: the kernel called a Python
#: callable, took a number back, and saw neither a suite nor a result file. Measured on a Gradle build
#: that stopped in `:compileJava` - no class compiled, no test executed, no JUnit XML written - where all
#: three records said the suite had run and reported failures.
#:
#: It says what the kernel actually observed and then says, in as many words, that the rest is not its to
#: state. "I do not know" is a statement a record may carry; "the suite reported" is not. It deliberately
#: does not guess at a cause, name a stage or read the rc as a signal - a runner that knows any of those
#: says so itself, through the marker file the branch now opens (#59).
IMPL_DETAIL = ("the product's own runner returned this rc; the kernel did not run a suite here and "
               "cannot say whether one ran at all")


@dataclass(frozen=True)
class Gate:
    """One test level, as the product's manifest declares it.

    Either `suite` (a pytest root the kernel runs) or `impl` (a product-owned runner the kernel calls for
    its rc) is set, never both. `results` says whether this gate CLEARS the shared results dir or APPENDS
    into it - the whole of the clear-versus-append rule, held as data. `args` marks the ONE gate a run's
    passthrough pytest args belong to.

    `results` IS THE ONE KEY THAT MEANS THE SAME THING ON BOTH KINDS (si#61). It is not a statement about
    what a gate writes - an `impl` gate writes nothing the kernel can see - but about whose run the
    results dir belongs to, and that question has the same answer whoever runs the tests. It used to be
    refused on an `impl` gate, which left a product whose only runner is its own unable to say it at all.
    """

    name: str
    suite: str = ""
    impl: str = ""
    results: str = APPEND
    junit: str = ""
    args: bool = False
    precondition: str = ""
    preamble: str = ""
    announce: str = ""

    @property
    def clears(self) -> bool:
        return self.results == CLEAR


@dataclass(frozen=True)
class Suites:
    """The product's whole lab-based test taxonomy: where reports go, where an exploratory run is
    quarantined, the gates IN THE ORDER they run, and what the report step merges in at the end."""

    reports: str
    filtered_results: str
    gates: tuple[Gate, ...]
    merge: tuple[str, ...]
    parent_suite: str
    precondition: str = ""

    def gate(self, name: str) -> Gate:
        """The gate a command name addresses, or a loud error naming the section - a command bound to this
        module with no matching gate is a manifest typo, not a runtime condition to limp along with."""
        for gate in self.gates:
            if gate.name == name:
                return gate
        raise ValueError(f"'{SECTION}.gates' declares no gate '{name}' "
                         f"(declared: {', '.join(g.name for g in self.gates) or 'none'})")


def _str(body: Mapping, key: str, where: str, *, required: bool = False) -> str:
    value = body.get(key)
    if value is None:
        if required:
            raise ValueError(f"{where}: '{key}' is required")
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _gate(body: object, where: str) -> Gate:
    """One validated gate entry. Every rule names the offending key, and the suite-XOR-impl lock is checked
    here so a half-declared level fails at load time rather than as a confusing empty pytest run."""
    if not isinstance(body, Mapping):
        raise ValueError(f"{where}: each gate must be a mapping")
    name = _str(body, "name", where, required=True)
    where = f"{where} ('{name}')"
    suite, impl = _str(body, "suite", where), _str(body, "impl", where)
    if bool(suite) == bool(impl):
        raise ValueError(f"{where}: declare exactly one of 'suite' (a pytest root) or 'impl' "
                         f"(a product-owned runner), not both and not neither")
    if impl:
        # An `impl:` gate is opaque: the kernel calls the product's runner for its rc and learns nothing
        # else, so it takes no pytest args, has no junit file of the kernel's making and gets no preamble.
        # Declaring any of those on it must FAIL rather than be dropped.
        #
        # `results` LEFT THIS LIST (si#61), and the reason is the one the list is built on. It was refused
        # because `results: clear` here would satisfy the exactly-one-clearing-gate rule below while
        # nothing ever cleared - `assess_gate` returned on the impl branch above the clear - and a key
        # that counts and does nothing is worse than one that is refused. That was true of the code and
        # it was the wrong repair. The clear could hang on NOTHING ELSE, so a product whose only test
        # runner is its own could write no loadable `suites:` section at all. Measured on a Java product
        # with no Python in it: both spellings refused, rc 1, no report; the way out was to ship a pytest
        # gate holding `assert True` purely to own the directory, at 29 MB of suite venv and a report
        # that counted four tests where the product has three.
        #
        # So the inert declaration was fixed where it was inert - `assess_gate` honours the clear on this
        # branch now - and the refusal has nothing left to protect. An impl gate that declares the clear
        # says exactly what it does: this gate OPENS the run, and the run's results dir starts empty. It
        # still writes nothing into that dir; that is a different statement, and `test_suites_impl_only`
        # keeps it pinned, because a fix that let the kernel invent a result for a runner it cannot see
        # would have moved this defect rather than removed it.
        stray = [key for key in ("junit", "args", "preamble") if key in body]
        if stray:
            raise ValueError(f"{where}: an 'impl' gate cannot declare {', '.join(repr(k) for k in stray)} "
                             f"- the kernel only calls its runner for the rc")
    results = _str(body, "results", where) or APPEND
    if results not in (CLEAR, APPEND):
        raise ValueError(f"{where}: 'results' must be '{CLEAR}' or '{APPEND}', got '{results}'")
    junit = _str(body, "junit", where)
    if suite and not junit:
        raise ValueError(f"{where}: a pytest gate must declare its own 'junit' file name")
    return Gate(name=name, suite=suite, impl=impl, results=results, junit=junit,
                args=bool(body.get("args", False)),
                precondition=_str(body, "precondition", where),
                preamble=_str(body, "preamble", where),
                announce=_str(body, "announce", where))


def declared(data: Mapping[str, object], source: str = "manifest") -> Suites:
    """The suite taxonomy the manifest declares, validated LOUDLY.

    An absent or malformed section fails HERE, naming the key, rather than surfacing later as a pytest run
    against a path that does not exist. Exactly one gate may CLEAR the shared results: two would mean the
    second silently deletes the first's results, which is the failure mode the clear-versus-append rule
    exists to prevent, and none would mean every run appends onto the last one forever.
    """
    section = data.get(SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping")
    reports = _str(section, "reports", f"{source}: '{SECTION}'", required=True)
    filtered = _str(section, "filtered_results", f"{source}: '{SECTION}'") or f"{RESULTS}-filtered"

    raw_gates = section.get("gates")
    if not isinstance(raw_gates, (list, tuple)) or not raw_gates:
        raise ValueError(f"{source}: '{SECTION}.gates' must be a non-empty list, in the order they run")
    gates = tuple(_gate(body, f"{source}: '{SECTION}.gates[{i}]'") for i, body in enumerate(raw_gates))
    names = [gate.name for gate in gates]
    if len(set(names)) != len(names):
        raise ValueError(f"{source}: '{SECTION}.gates' declares a duplicate gate name")
    # The passthrough args belong to ONE gate. Two would each receive the same `-k <expr>` verbatim, and
    # an expression written for one suite filters a different suite down to nothing while still reporting
    # green - a partial run that does not look like one.
    taking = [gate.name for gate in gates if gate.args]
    if len(taking) > 1:
        raise ValueError(f"{source}: at most one gate may declare args: true; got {taking}")
    clearing = [gate.name for gate in gates if gate.clears]
    if len(clearing) != 1:
        raise ValueError(f"{source}: exactly one gate must declare results: {CLEAR} "
                         f"(the first one to run); got {clearing or 'none'}. Any gate may carry it, an "
                         f"'impl' one included - that gate then opens the run's results dir without "
                         f"writing into it.")
    if not gates[0].clears:
        raise ValueError(f"{source}: '{clearing[0]}' clears the shared results but is not the FIRST gate; "
                         f"a later clear deletes what the gates before it wrote")

    report = section.get("report") or {}
    if not isinstance(report, Mapping):
        raise ValueError(f"{source}: '{SECTION}.report' must be a mapping")
    merge = report.get("merge") or []
    if not isinstance(merge, (list, tuple)):
        raise ValueError(f"{source}: '{SECTION}.report.merge' must be a list of result dirs")
    for entry in merge:
        # A non-string entry would stringify into a nonsense path that merge_results then SKIPS silently
        # (a missing dir is not an error there, so a standalone report still archives what is present) -
        # so the typo has to fail here or it never fails at all.
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{source}: '{SECTION}.report.merge' holds a non-path entry: {entry!r}")
    return Suites(reports=reports, filtered_results=filtered, gates=gates,
                  merge=tuple(entry.strip() for entry in merge),
                  parent_suite=_str(report, "parent_suite", f"{source}: '{SECTION}.report'") or "Unit",
                  precondition=_str(section, "precondition", f"{source}: '{SECTION}'"))


def config() -> Suites:
    """The registered product's suite taxonomy."""
    ctx = context.current()
    return declared(ctx.manifest_data(), source=str(ctx.manifest_path))


def _verdict(value: object) -> int:
    """A product hook's return value as an exit code, coerced at the seam it enters the kernel through.

    THIS IS WHERE #8 WAS HIDING. `_hook` used to hand back the resolved callable untouched, typed
    `Callable[..., object]`, and every caller then wrote `if rc != 0: return rc`. A hook is an ordinary
    Python function a product wrote - and an ordinary Python function that just does its work RETURNS
    NONE. `None != 0` is True, so a precondition that succeeded aborted its gate; the gate then returned
    `None`, which `simplon.cli._rc` turns into exit 0. The suite never ran and the run reported GREEN.
    A test gate that skips itself and calls that a pass is the one outcome a gate must never produce,
    and mypy had been naming it - `Incompatible return value type (got "object", expected "int")` at the
    three `if rc != 0` sites - for as long as the checker has been pointed at this tree.

    The rule is `simplon.cli._rc`'s, deliberately: a body that returns something other than an rc is a
    body written when the return value could not matter, not a failure. Only a real int is a verdict.
    A bool is excluded for the same reason it is there - `return True` means success, and `int(True)`
    would exit 1. tests/test_tasks_testrun.py asserts the two spellings agree.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _hook(ref: str, where: str) -> Callable[..., int]:
    """A product hook as a callable that yields an EXIT CODE.

    The coercion sits here rather than at each call site because there are four of them and they must
    not be able to drift: a hook is a hook whether it is a precondition, a preamble or a gate's own
    impl.
    """
    fn = resolve_ref(ref, f"'{SECTION}.{where}'")

    def call(*args: object, **kwargs: object) -> int:
        return _verdict(fn(*args, **kwargs))

    return call


def _reports_dir(cfg: Suites) -> str:
    return str(context.current().root / cfg.reports)


def results_dir(cfg: Suites, *, filtered: bool) -> str:
    """Where THIS run's allure results go: the shared dir for a canonical run, the quarantined one for an
    exploratory (argument-carrying) run. One decision per run, taken once and threaded through every gate
    plus the report step, so a run can never end up half in one dir and half in the other."""
    return os.path.join(_reports_dir(cfg), cfg.filtered_results if filtered else RESULTS)


@contextlib.contextmanager
def _setup_marker(reports: str) -> Iterator[str]:
    """Offer the suite a place to say its own setup fell over, and read it back afterwards.

    The marker is REMOVED on the way in, so a file left by an earlier run can never be read as this run's
    verdict - a stale "setup failed" is the same defect as a stale "passed", pointing the other way. The
    path is exported for the child pytest through `os.environ` and restored afterwards, because
    `simplon.run.run` takes no environment of its own and widening it for one caller would be a bigger
    change than the seam is worth; the value is a path this process just computed, not user input.
    """
    path = os.path.join(reports, SETUP_MARKER)
    os.makedirs(reports, exist_ok=True)
    with contextlib.suppress(OSError):
        os.unlink(path)
    previous = os.environ.get(SETUP_MARKER_ENV)
    os.environ[SETUP_MARKER_ENV] = path
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop(SETUP_MARKER_ENV, None)
        else:
            os.environ[SETUP_MARKER_ENV] = previous


def _reported_stage(path: str) -> str:
    """The setup stage the suite named in the marker, or "" when it left none.

    A marker with nothing in it still counts: the suite said the setup fell over, and losing that because
    it did not also name a stage would trade the whole distinction for a detail. The generic wording is
    what it gets in that case.
    """
    if not os.path.isfile(path):
        return ""
    with contextlib.suppress(OSError):
        with open(path, encoding="utf-8") as fh:
            first = fh.read().strip().splitlines()
        if first and first[0].strip():
            return first[0].strip()
    return "the suite's own setup"


def _clear_results(results: str, reports: str) -> None:
    """Empty the run's results dir and the transient render dir, and leave the results dir THERE.

    One place, because two branches reach it now (si#61) and a second copy of a rule is a second rule.
    The scratch dir goes with the results because `allure generate -o` writes into it and a stale render
    of the last run standing beside this run's results is the same lie one directory across.

    The dir is RECREATED rather than merely removed: "cleared" is a statement about ownership, and an
    absent directory and an empty one say different things to the report step that reads it next.
    """
    shutil.rmtree(results, ignore_errors=True)
    shutil.rmtree(os.path.join(reports, SCRATCH), ignore_errors=True)
    os.makedirs(results, exist_ok=True)


def assess_gate(gate: Gate, cfg: Suites, extra: list[str], *, filtered: bool,
                earlier: tuple[GateVerdict, ...] = ()) -> GateVerdict:
    """Run ONE gate and say not only whether it was red but whether it was red ABOUT anything (#30).

    A declared precondition runs FIRST and a non-zero verdict returns immediately, having cleared nothing -
    the stale results of the last real run must survive a gate that never started; that is `NOT_RUN`. Then,
    for a pytest gate: the venv, the clear (only where the taxonomy says so), and the run itself with the
    product's lab preamble inside the same keep-awake window, so a long convergence wait cannot idle-sleep
    the host.

    THE PREAMBLE'S OWN VERDICT IS NOW HONOURED, and that is a fix, not a refinement: its rc used to be
    computed and dropped on the floor, so a lab that failed to converge ran the suite anyway, against a
    lab that was not there, and whatever the suite then reported was recorded as a statement about the
    product. `SETUP_FAILED` is that case, and the suite does not run.

    A SUITE ENDED BY A SIGNAL IS `KILLED`, not red (#55). The rc read back here is the pytest child's wait
    status, so a negative one IS the signal - and a suite that was shot reported nothing, which makes
    "the suite ran and reported failures" a statement about the product that nobody made.

    A gate declared as a bare `impl:` stays opaque, deliberately. The kernel calls the product's runner for
    its rc and nothing else, so it has no honest basis for saying more than passed/failed about it - not
    even the signal reading above, since that rc never passed through a wait status.

    THAT OPACITY IS THE REASON FOR `IMPL_DETAIL`, NOT AN EXCUSE FOR THE OLD SENTENCE (#65). The reasoning
    above is right and the consequence drawn from it was not: from "the kernel does not know" the kernel
    concluded that it might say the default, and the default is "the suite ran and reported failures" -
    a statement about a suite it never saw. Measured against a real Gradle build with a deliberate
    compiler error: nothing compiled, no test ran, no result file was written, and the log line, the
    stamp and the archive's environment widget all said the suite had run and reported failures. Not
    knowing is a thing a record may say; it is not a licence to say something else. So an impl gate now
    states exactly what happened - the product's runner returned an rc - and nothing about a suite.

    AND THE MARKER IS OPEN TO IT (#59). `_setup_marker` is the seam a runner uses to say "my own
    preparation fell over", and it used to sit BELOW this branch, so the one outcome a product-owned
    runner most needs was the one it could not reach: of the five outcomes, an impl gate had two. It is
    opened here without widening what the kernel claims, because the kernel still claims nothing - the
    marker is the PRODUCT speaking, in the product's own words, exactly as a pytest session fixture
    speaks through the same file. A runner that stays silent still gets `passed`/`failed` and no invented
    stage; that is asserted, because a fix that hallucinated a stage would have moved this defect rather
    than removed it.

    `earlier` is what the gates before this one in the SAME invocation found. It exists so the environment
    this gate writes into the shared results dir states the RUN's verdict rather than its own: the write is
    a last-wins merge, so a gate stating a run verdict from its own knowledge alone would let a later green
    gate overwrite an earlier gate's `setup-failed` - the precedence rule defeated inside the one artefact
    it protects. Empty for a gate invoked on its own, which is then the whole run.
    """
    if gate.precondition:
        rc = _hook(gate.precondition, f"gates.{gate.name}.precondition")()
        if rc != 0:
            return GateVerdict(gate.name, Verdict.NOT_RUN, rc, verdict.PRECONDITION)
    reports = _reports_dir(cfg)
    results = results_dir(cfg, filtered=filtered)
    if gate.impl:
        # THE CLEAR IS HONOURED HERE TOO (si#61), and that is the whole of the fix. It used to be
        # unreachable on this branch and refused at load in consequence, which left a product whose only
        # runner is its own with no way to say that its run OWNS the results dir - the clear could hang
        # on a pytest gate and on nothing else. It hangs on this one now: the gate opens the run, the
        # dir starts empty, and the report step that follows sees this run and no other.
        #
        # It clears and it still WRITES NOTHING. The two are not the same claim: clearing is about whose
        # run the directory belongs to, writing is about what the kernel learned, and the kernel learned
        # one number here. `test_suites_impl_only` pins the second by asserting the dir stays empty.
        if gate.clears:
            _clear_results(results, reports)
        # NOT `verdict.of_subprocess`: this rc is a Python callable's return value, not a child's wait
        # status, so a negative one names no signal and reading it as one would invent a statement. Same
        # reason the docstring gives for saying nothing else about an impl gate.
        #
        # The marker window is the product's, not the kernel's: it is opened, and what comes out of it is
        # whatever the runner chose to write. Nothing is read if nothing is written.
        with _setup_marker(reports) as marker:
            rc = _hook(gate.impl, f"gates.{gate.name}.impl")()
            stage = _reported_stage(marker)
        if stage:
            # The runner's own claim wins over its rc, including over a green one - the same precedence a
            # pytest gate's marker gets below, and for the same reason: a runner that reports a broken
            # setup and still returns 0 is a runner whose green means nothing.
            return GateVerdict(gate.name, Verdict.SETUP_FAILED, rc or SETUP_FAILED_RC, stage)
        if rc == 0:
            return GateVerdict(gate.name, Verdict.PASSED, rc)
        return GateVerdict(gate.name, Verdict.FAILED, rc, detail=IMPL_DETAIL)

    log.info(gate.announce or f"{gate.name} gate: {gate.suite} against the running lab")
    suite_dir = str(context.current().root / gate.suite)
    py, _ = pyvenv.venv_python_pip(suite_dir)
    if gate.clears:
        # The FIRST gate clears the run's results + the transient render dir exactly once; every later gate
        # appends into it, so the report step sees every suite of the run and only this run.
        _clear_results(results, reports)
    os.makedirs(results, exist_ok=True)
    junit = os.path.join(reports, f"{os.path.splitext(gate.junit)[0]}-filtered.xml" if filtered else gate.junit)
    with _setup_marker(reports) as marker, keep_awake():
        if gate.preamble:
            rc = _hook(gate.preamble, f"gates.{gate.name}.preamble")()
            if rc != 0:
                return _written(GateVerdict(gate.name, Verdict.SETUP_FAILED, rc, verdict.PREAMBLE),
                                results, earlier, filtered)
        # cwd is the level's own python root so its conftest.py loads and the subjects below it collect.
        rc = run(allure.integration_pytest_argv(py, results, junit, extra),
                 capture=False, cwd=suite_dir).rc
        stage = _reported_stage(marker)
    if verdict.of_subprocess(rc) is Verdict.KILLED:
        # THE SUITE DID NOT REPORT; IT WAS SHOT (#55). This is the one place in the kernel that may read a
        # negative rc as a signal, because this rc is a child process's wait status and nothing else.
        #
        # Checked BEFORE the suite's own setup marker, deliberately. A marker is the suite's claim about a
        # run that then did not finish; the signal is the reason nothing came back at all, and it is the
        # one fact that also explains a half-written marker. `verdict.rank` places the two the same way
        # round for the same reason, and the two orderings have to agree or a run and a gate would name
        # different causes for one event.
        return _written(GateVerdict(gate.name, Verdict.KILLED, rc), results, earlier, filtered)
    if stage:
        # The suite's own claim wins over its exit code, INCLUDING over a green one. A suite that reports
        # a broken setup and still exits 0 is a suite whose green means nothing, and believing the rc there
        # would reinstate exactly the "red run, green record" this exists against.
        #
        # AND THE CLAIM WINS OVER THE EXIT CODE THE GATE ITSELF RETURNS. A `SETUP_FAILED` carrying rc 0
        # would say "the setup broke" in the record and hand `simplon.cli._rc` a green exit - a red run
        # reported as a success, which is the failure class of this ticket with the two halves swapped.
        # `GateVerdict` refuses that pair outright; SETUP_FAILED_RC is what the kernel supplies when the
        # suite left it no rc of its own to pass on.
        return _written(GateVerdict(gate.name, Verdict.SETUP_FAILED, rc or SETUP_FAILED_RC, stage),
                        results, earlier, filtered)
    log.ok(f"{gate.name} results written to {results}")
    return _written(GateVerdict(gate.name, verdict.of_subprocess(rc), rc), results, earlier, filtered)


def _written(gv: GateVerdict, results: str, earlier: tuple[GateVerdict, ...], filtered: bool) -> GateVerdict:
    """Put the RUN's verdict so far INSIDE the archive this gate just wrote, and say this gate's line once
    on the terminal.

    Only a gate that owns this run's results dir gets here - every outcome except `NOT_RUN`, whose whole
    point is that it touched nothing. Writing there would overwrite the environment of the last real run's
    archive with the verdict of a run that never started, which is the original defect with the sign
    flipped.
    """
    (log.ok if gv.ok else log.warn)(f"{gv.gate}: {gv.line}")
    allure.write_environment(results, RunVerdict(earlier + (gv,), filtered=filtered).environment())
    return gv


def run_gate(gate: Gate, cfg: Suites, extra: list[str], *, filtered: bool) -> int:
    """Run ONE gate and return its rc - `assess_gate` for a caller that only wants the exit code.

    The rc stays exactly what it was before #30: zero or not, with no reserved value carrying the reason.
    That is the point. Everything a later reader needs is in what was WRITTEN, and a caller who wants it in
    hand calls `assess_gate` instead of decoding the rc.

    `verdict.exit_code` is not an exception to that (#55). A gate a signal killed still returns simply
    non-zero; what it does is stop the wait status from being MANGLED into 241 by `sys.exit`'s modulo, and
    hand on the 128+n a shell would have reported for the same child. No new distinction, one fewer lie.
    """
    return verdict.exit_code(assess_gate(gate, cfg, extra, filtered=filtered).rc)


def report(cfg: Suites | None = None, *, filtered: bool = False, run: RunVerdict | None = None) -> int:
    """Merge the per-module results the product's OTHER gates already wrote into this run's results dir,
    then render the merged single-file archive. Runs NO tests: it archives the verdict of what ran before
    it.

    rc 0 when the archive was written AND when the host has no render tool at all - archiving is
    best-effort there and never itself the reason a run is red, because the gates carry the verdict. rc 1
    when a render tool WAS present and failed (#6): that is not best-effort any more, it is a step that was
    asked to do something it can do and did not, and a run that silently ships no archive is
    indistinguishable from one that shipped a good one - which is precisely how the broken docker render
    survived several releases.

    `run`, when a caller has one, is the verdict of the gates that ran before this step, and it goes into
    the archive's own Environment widget (#30). That is the half a later reader meets: the stamp beside the
    report says why a run was red, and this says it INSIDE the report, where somebody who was handed only
    the HTML file can still see that a gate's setup fell over rather than its suite.
    """
    cfg = cfg or config()
    root = context.current().root
    results = results_dir(cfg, filtered=filtered)
    os.makedirs(results, exist_ok=True)
    if run is not None and run.wrote_results:
        # Only when some gate of this run actually owned the results dir. A run made entirely of gates that
        # never started must leave the last real run's archive alone - stating this run's verdict in it
        # would be the stale-verdict defect pointing the other way.
        allure.write_environment(results, run.environment())
    if cfg.merge:
        # THE RESULT, NOT THE INTENTION (#64). The old line said `per-module results merged
        # (parentSuite=X)` unconditionally, and it was the same sentence for a merge that tagged three
        # results, for one that copied a JUnit XML through untagged, and for one whose declared source
        # dir did not exist because the build had stopped before writing it. `merge_results` is the only
        # thing that can tell those apart, so it now says which it was and this only reports it.
        #
        # A missing source is a WARNING and not a failure: skipping it is deliberate (a standalone report
        # step archives what is present), but a declared dir that is not there is the runtime twin of the
        # typo `declared` refuses at load, and the run it belongs to is usually one where something
        # upstream never got that far.
        merged = allure.merge_results(results, [str(root / d) for d in cfg.merge],
                                      parent_suite=cfg.parent_suite)
        (log.warn if merged.missing or merged.empty else log.ok)(f"per-module results: {merged.line}")
    log.ok(f"allure results written to {results}")
    render = allure.render_report(_reports_dir(cfg), results,
                                  prefix="allure-filtered" if filtered else "allure")
    return 1 if render.failed else 0


def accept(extra: list[str], cfg: Suites | None = None) -> int:
    """Run every declared gate in order, then the report step, and return a BINARY verdict over all of them.

    All gates run - no fail-fast - because the point of the convenience is the full red/green picture and an
    archived report either way; but a red suite MUST surface as a red exit code (netctl#571: a chained
    overnight gate read 0 with seven failed tests). The report step counts towards that verdict for the same
    reason (#6) - a run whose archive silently failed to render is not a green run - though only when a
    render tool was there to fail; the section-level precondition is the one exception: an unhealthy cluster
    aborts in seconds rather than wasting the whole collection.

    A STAMP IS WRITTEN AFTER EVERY GATE, not once at the end (#30). The stamp always holds everything this
    invocation knows so far, so a run killed in its third gate still leaves a record of the first two
    instead of leaving the last complete run's verdict standing as though it were this one's. The
    section-level abort writes one too: "this run never started" is a thing the record has to be able to
    say, and it is the one thing the old code could only say by staying silent.

    AND A STAMP IS WRITTEN WHEN A STEP RAISES (#63), which is the half that rule was missing. Stamping
    after every gate means the record is always one step behind; while the run finishes normally the last
    write catches up, and when it does not, the stamp that stays on the disk is a true statement about the
    last gate and a FALSE one about the run. Measured: a run that ended with rc 1 and an
    `IsADirectoryError` out of the report step left `test-verdict.json` saying `"verdict": "passed"`,
    `"line": "passed"`, with no `report` entry to hint that anything had been cut short. The gates really
    had been green; the run had not, and the record a reader consults a week later is the record of the
    run. The exception is re-raised afterwards - this adds a record, it does not swallow a failure.
    """
    cfg = cfg or config()
    reports = _reports_dir(cfg)
    # Known BEFORE the section precondition: an exploratory run that aborts there must stamp into its own
    # file like every other exploratory run, or the abort of a one-test hunt overwrites the canonical
    # record of the last full run.
    filtered = bool(extra)
    if cfg.precondition:
        rc = _hook(cfg.precondition, "precondition")()
        if rc != 0:
            verdict.write_stamp(reports, RunVerdict(
                (GateVerdict("accept", Verdict.NOT_RUN, rc, verdict.PRECONDITION),), filtered=filtered))
            return rc
    if filtered:
        _warn_filtered(cfg)
    log.info(f"accept: running the lab-based suites ({' + '.join(g.name for g in cfg.gates)} + report)")
    verdicts: list[GateVerdict] = []
    step = cfg.gates[0].name
    try:
        for gate in cfg.gates:
            step = gate.name
            verdicts.append(assess_gate(gate, cfg, extra if gate.args else [], filtered=filtered,
                                        earlier=tuple(verdicts)))
            verdict.write_stamp(reports, RunVerdict(tuple(verdicts), filtered=filtered))
        step = REPORT
        rc = report(cfg, filtered=filtered, run=RunVerdict(tuple(verdicts), filtered=filtered))
    except Exception as exc:
        # AN ABANDONED RUN LEAVES AN ABANDONED RUN'S RECORD (#63). The stamp after the last completed gate
        # is a true statement about that gate and a false one about the run, because it is the only thing
        # a later reader finds: measured, a run that ended with rc 1 and an `IsADirectoryError` out of the
        # report step left `test-verdict.json` saying `"verdict": "passed"` with no `report` entry at all.
        # `write_stamp` is called after every gate precisely so a run that stops early still leaves a
        # record - and the one place it could not reach was the step that runs last.
        #
        # The exception is RE-RAISED, so the operator keeps the traceback and the process keeps its exit
        # code: this adds a record, it does not swallow a failure. `Exception` and not `BaseException` -
        # a KeyboardInterrupt is the operator ending their own run, not a run that reports green.
        verdicts.append(_abandoned(step, exc))
        verdict.write_stamp(reports, RunVerdict(tuple(verdicts), filtered=filtered))
        raise
    # The report step runs NO tests, so it must not borrow the sentence written for a gate that does: it
    # renders an archive, and when it is red the archive is what is missing. Handing it the default wording
    # would put "the suite ran and reported failures" into the stamp - and, when it is the run's weakest
    # element, into `verdict.summary` - about a step that ran no suite at all.
    verdicts.append(GateVerdict(REPORT, Verdict.PASSED if rc == 0 else Verdict.FAILED, rc,
                                detail="" if rc == 0 else "a render tool was present and wrote no "
                                                          "archive; this run has none"))
    run = RunVerdict(tuple(verdicts), filtered=filtered)
    verdict.write_stamp(reports, run)
    if not all(gv.ok for gv in verdicts):
        log.warn("accept is RED (" + ", ".join(f"{gv.gate} {gv.line}" for gv in verdicts) + ")")
        return 1
    return 0


def _abandoned(step: str, exc: BaseException) -> GateVerdict:
    """The record entry for a step that RAISED - the one thing the stamp could not previously say (#63).

    It names the step, the exception type and its message, because a record whose whole purpose is to be
    read a week later must carry the cause and not only the fact. The message is flattened onto one line
    for the same reason `allure.write_environment` flattens: this string is also written into a properties
    file, whose format has no continuation.

    WHY `FAILED` AND NOT A SIXTH OUTCOME. The five outcomes answer "what did the gate learn about the
    product"; a step that raised did not get far enough to learn anything, and none of the three non-verdicts
    fits - nothing about a SETUP broke, and the step was not skipped. `FAILED` with an explicit `detail` is
    the idiom this function's only other non-suite neighbour already uses: the report step's render failure,
    which is likewise a statement about the step rather than about the product, and which the `detail` field
    exists for. Widening `Verdict` to say "abandoned" would be a change to the vocabulary every consumer
    reads, made in passing while fixing a stamp that says the opposite of what happened; that belongs in a
    ticket of its own, and the limit is recorded here rather than left to whoever hits it.
    """
    said = " ".join(str(exc).split())
    return GateVerdict(step, Verdict.FAILED, ABANDONED_RC,
                       detail=f"the step raised {type(exc).__name__}" + (f": {said}" if said else "")
                              + ", so the run was abandoned there and nothing after it ran")


def _warn_filtered(cfg: Suites) -> None:
    """Say, loudly and once, that an argument-carrying run is exploratory and does not touch the archive."""
    quarantine = results_dir(cfg, filtered=True)
    log.warn(f"filtered run: results go to {quarantine} and the shared {RESULTS} archive is left alone; "
             f"view with: allure serve '{quarantine}'")


# --- the Typer callbacks a product's manifest points its `impl:` at ------------------------------------
# `gate` is bound to SEVERAL commands - one per declared level - so it identifies itself by the name it was
# INVOKED as (`ctx.info_name`), which is the manifest command name and therefore the gate name. A callback
# shared by several commands cannot carry per-command help in its docstring, so `simplon.cli.assemble`
# takes the help from each command's manifest `help:` instead; that is the product's own wording anyway.

def gate(ctx: typer.Context, name: str = "") -> int:
    """Run one declared test level against the running lab. Which suite that is, where its results go and
    whether it clears or appends to the shared allure results comes from the product manifest's `suites`
    section; trailing args reach pytest verbatim where the level declares `args: true`.

    `name` is a manifest-pinned parameter (`with: { name: ... }`, netctl#1469 plan 2): the command tree
    places this ONE task at several commands, each pinning its own suite name, so the gate resolves from
    a value rather than from which command it was invoked as.

    THE `or ctx.info_name` FALLBACK SURVIVED THE FLAT FORM'S DELETION (si#33), and deliberately - the
    docstring here used to say plan 3 would take it along. It would have been the wrong deletion. The
    fallback exists for a command that does not PIN `name`, and that is still a legal command in the tree
    form: `unit: { task: "test:gate" }` with no `with:` names its suite by the only thing it has, the name
    it was invoked as. What went with the flat form is the reason the fallback used to be called
    transitional, not the case it answers.

    WHAT AN UNPINNED COMMAND COSTS, stated because it is easy to meet by accident. `signatures.shape`
    renders every NON-PINNED parameter as a visible option regardless of whether the manifest describes
    it (`params:` only shapes an ALREADY-visible parameter's presentation, it does not hide one); only
    `with:` removes a parameter from the wrapper's signature entirely (`treeform`/`taskgen`'s pin logic).
    So an unpinned command grows a real, stray `--name` option, and a caller can then ask one gate to run
    another gate's suite. Pin it.
    """
    cfg = config()
    extra = list(ctx.args)
    filtered = bool(extra)
    if filtered:
        _warn_filtered(cfg)
    # `ctx.info_name` is Optional in Click's own types (a context can exist without an invoked command),
    # so the unpinned fallback has to say what happens when it is absent instead of handing None to a
    # lookup over strings. An empty level reaches `Suites.gate`, which refuses it by name and lists the
    # gates that ARE declared - the same loud manifest-typo error an unknown level already gets.
    level = name or ctx.info_name or ""
    gv = assess_gate(cfg.gate(level), cfg, extra, filtered=filtered)
    # One gate invoked on its own is still a run, and it stamps what IT did (#30) - a one-gate record
    # rather than a merge into the last full run's, because pretending the other gates still hold from an
    # earlier invocation is the stale-verdict problem again, one level up. An exploratory run stamps into
    # its OWN file: the quarantine that already keeps its results out of the archive has to keep its
    # verdict out of the canonical record too, or a one-test hunt overwrites the finding of a full gate.
    verdict.write_stamp(_reports_dir(cfg), RunVerdict((gv,), filtered=filtered))
    # The record keeps the wait status it observed; the PROCESS gets the number a shell can read (#55).
    return verdict.exit_code(gv.rc)


def report_cmd() -> int:
    """REPORT step: merge the per-module results the earlier gates already wrote into the shared Allure
    results and render the merged single-file Allure HTML archive. Runs NO tests; it archives the verdict of
    the gates that ran before it. Green when the archive was written, and green on a host with no render
    tool at all; red only when a render tool was present and failed to produce the archive (#6)."""
    return report()


def accept_cmd(ctx: typer.Context) -> int:
    """Convenience: run every lab-based gate in its declared order and then the report step, against the
    running lab. Trailing args reach the pytest of the gate that declares `args: true`; a run carrying any
    is exploratory and is quarantined into its own results dir, leaving the archive of the last full gate
    intact. The gates it chains are also addressable individually."""
    return accept(list(ctx.args))
