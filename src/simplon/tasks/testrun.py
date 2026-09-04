"""The lab-based suite runner and its allure plumbing (netctl#1406, moved out of netctl's
orchestrator.testrun).

Creating a per-suite venv, running pytest into a shared allure results dir, merging the already-written
per-module results and rendering the single-file archive is MECHANISM: it needs to know nothing about the
product whose suites it runs. The kernel already owned the two primitives it is built on (`delivery.pyvenv`,
`delivery.allure`), so this finishes a seam that was half-built.

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
A gate may also be declared as a bare `impl:` instead of a pytest `suite:`, for a level whose runner is the
product's own (a browser journey suite, say); the kernel just calls it for its rc and sequences it.

EXPLORATORY RUNS (netctl#1406). A gate that declares `args: true` forwards the command's passthrough args
to pytest, which is what makes `<product> test system -k <expr>` - a ~60s answer instead of a ~24min gate -
possible at all. Such a run is by definition PARTIAL, so it must never write into the shared results dir:
clearing it and then filling it with one test's results would leave an archive that looks like a full gate
and reports a single test, and appending would mix two runs. Any run carrying extra args is therefore
QUARANTINED into its own results dir for the whole run (`filtered_results`), which is cleared up front and
rendered under its own archive prefix. The canonical archive of the last real gate stays untouched.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable

import typer

from delivery import allure, context, log, pyvenv
from delivery.awake import keep_awake
from delivery.orchestrator.manifest import resolve_ref
from delivery.run import run

# The manifest section this module owns.
SECTION = "suites"

# The shared results dir every canonical gate writes into, under the product's report dir. Fixed rather
# than declared: it is the allure convention every tool in the chain (`allure serve`, the render below,
# CI's artefact upload) already assumes, so making it configurable would buy nothing.
RESULTS = "allure-results"
# The transient dir `allure generate -o` writes into; cleared alongside the results by a `clear` gate.
SCRATCH = "allure-report"

CLEAR, APPEND = "clear", "append"


@dataclass(frozen=True)
class Gate:
    """One test level, as the product's manifest declares it.

    Either `suite` (a pytest root the kernel runs) or `impl` (a product-owned runner the kernel calls for
    its rc) is set, never both. `results` says whether this gate CLEARS the shared results dir or APPENDS
    into it - the whole of the clear-versus-append rule, held as data. `args` marks the ONE gate a run's
    passthrough pytest args belong to.
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
        # An `impl:` gate is opaque: the kernel calls the product's runner for its rc and nothing else, so
        # it neither writes the shared results, nor takes pytest args, nor runs the preamble. Declaring any
        # of those on it must FAIL rather than be dropped - `results: clear` on an impl gate would otherwise
        # satisfy the exactly-one-clearing-gate rule below while nothing ever cleared, which is the silent
        # forever-appending archive that rule exists to prevent.
        stray = [key for key in ("results", "junit", "args", "preamble") if key in body]
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
                         f"(the first one to run); got {clearing or 'none'}")
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


def _hook(ref: str, where: str) -> Callable[..., object]:
    return resolve_ref(ref, f"'{SECTION}.{where}'")


def _reports_dir(cfg: Suites) -> str:
    return str(context.current().root / cfg.reports)


def results_dir(cfg: Suites, *, filtered: bool) -> str:
    """Where THIS run's allure results go: the shared dir for a canonical run, the quarantined one for an
    exploratory (argument-carrying) run. One decision per run, taken once and threaded through every gate
    plus the report step, so a run can never end up half in one dir and half in the other."""
    return os.path.join(_reports_dir(cfg), cfg.filtered_results if filtered else RESULTS)


def run_gate(gate: Gate, cfg: Suites, extra: list[str], *, filtered: bool) -> int:
    """Run ONE gate and return its rc.

    A declared precondition runs FIRST and a non-zero verdict returns immediately, having cleared nothing -
    the stale results of the last real run must survive a gate that never started. Then, for a pytest gate:
    the venv, the clear (only where the taxonomy says so), and the run itself with the product's lab
    preamble inside the same keep-awake window, so a long convergence wait cannot idle-sleep the host.
    """
    if gate.precondition:
        rc = _hook(gate.precondition, f"gates.{gate.name}.precondition")()
        if rc != 0:
            return rc
    if gate.impl:
        return _hook(gate.impl, f"gates.{gate.name}.impl")()

    log.info(gate.announce or f"{gate.name} gate: {gate.suite} against the running lab")
    suite_dir = str(context.current().root / gate.suite)
    reports = _reports_dir(cfg)
    results = results_dir(cfg, filtered=filtered)
    py, _ = pyvenv.venv_python_pip(suite_dir)
    if gate.clears:
        # The FIRST gate clears the run's results + the transient render dir exactly once; every later gate
        # appends into it, so the report step sees every suite of the run and only this run.
        shutil.rmtree(results, ignore_errors=True)
        shutil.rmtree(os.path.join(reports, SCRATCH), ignore_errors=True)
    os.makedirs(results, exist_ok=True)
    junit = os.path.join(reports, f"{os.path.splitext(gate.junit)[0]}-filtered.xml" if filtered else gate.junit)
    with keep_awake():
        if gate.preamble:
            _hook(gate.preamble, f"gates.{gate.name}.preamble")()
        # cwd is the level's own python root so its conftest.py loads and the subjects below it collect.
        rc = run(allure.integration_pytest_argv(py, results, junit, extra),
                 capture=False, cwd=suite_dir).rc
    log.ok(f"{gate.name} results written to {results}")
    return rc


def report(cfg: Suites | None = None, *, filtered: bool = False) -> int:
    """Merge the per-module results the product's OTHER gates already wrote into this run's results dir,
    then render the merged single-file archive. Runs NO tests: it archives the verdict of what ran before
    it. Always rc 0 - archiving is best-effort and never itself the reason a run is red, because the gates
    carry the verdict."""
    cfg = cfg or config()
    root = context.current().root
    results = results_dir(cfg, filtered=filtered)
    os.makedirs(results, exist_ok=True)
    if cfg.merge:
        allure.merge_results(results, [str(root / d) for d in cfg.merge], parent_suite=cfg.parent_suite)
        log.ok(f"per-module results merged (parentSuite={cfg.parent_suite})")
    log.ok(f"allure results written to {results}")
    allure.render_report(_reports_dir(cfg), results,
                         prefix="allure-filtered" if filtered else "allure")
    return 0


def accept(extra: list[str], cfg: Suites | None = None) -> int:
    """Run every declared gate in order, then the report step, and return a BINARY verdict over all of them.

    All gates run - no fail-fast - because the point of the convenience is the full red/green picture and an
    archived report either way; but a red suite MUST surface as a red exit code (netctl#571: a chained
    overnight gate read 0 with seven failed tests). The section-level precondition is the one exception: an
    unhealthy cluster aborts in seconds rather than wasting the whole collection.
    """
    cfg = cfg or config()
    if cfg.precondition:
        rc = _hook(cfg.precondition, "precondition")()
        if rc != 0:
            return rc
    filtered = bool(extra)
    if filtered:
        _warn_filtered(cfg)
    log.info(f"accept: running the lab-based suites ({' + '.join(g.name for g in cfg.gates)} + report)")
    rcs = {gate.name: run_gate(gate, cfg, extra if gate.args else [], filtered=filtered)
           for gate in cfg.gates}
    report(cfg, filtered=filtered)
    if any(rc != 0 for rc in rcs.values()):
        log.warn("accept is RED (" + ", ".join(f"{name} rc {rc}" for name, rc in rcs.items()) + ")")
        return 1
    return 0


def _warn_filtered(cfg: Suites) -> None:
    """Say, loudly and once, that an argument-carrying run is exploratory and does not touch the archive."""
    quarantine = results_dir(cfg, filtered=True)
    log.warn(f"filtered run: results go to {quarantine} and the shared {RESULTS} archive is left alone; "
             f"view with: allure serve '{quarantine}'")


# --- the Typer callbacks a product's manifest points its `impl:` at ------------------------------------
# `gate` is bound to SEVERAL commands - one per declared level - so it identifies itself by the name it was
# INVOKED as (`ctx.info_name`), which is the manifest command name and therefore the gate name. A callback
# shared by several commands cannot carry per-command help in its docstring, so `delivery.cli.assemble`
# takes the help from each command's manifest `help:` instead; that is the product's own wording anyway.

def gate(ctx: typer.Context, name: str = "") -> None:
    """Run one declared test level against the running lab. Which suite that is, where its results go and
    whether it clears or appends to the shared allure results comes from the product manifest's `suites`
    section; trailing args reach pytest verbatim where the level declares `args: true`.

    `name` is a manifest-pinned parameter (`with: { name: ... }`, netctl#1469 plan 2): the command-tree
    form places this ONE task at several commands, each pinning its own suite name, so the gate resolves
    from a value rather than from which command it was invoked as. The empty default plus the
    `or ctx.info_name` fallback is TRANSITIONAL - it is what lets a product that has not migrated keep
    naming this module raw per command and telling two commands bound to it apart by invocation name
    (netctl#1406). Plan 3 deletes the fallback along with the old form it exists for.

    THIS IS A BREAKING CHANGE for a caller that does not pin `name`, BY CONSTRUCTION, not by accident -
    measured, not assumed. `signatures.shape` renders every NON-PINNED parameter as a visible option
    regardless of whether the manifest describes it (`params:` only shapes an ALREADY-visible parameter's
    presentation, it does not hide one); only `with:` removes a parameter from the wrapper's signature
    entirely (`treeform`/`taskgen`'s pin logic). So `name`'s empty default does NOT keep it invisible - a
    command bound to this function that pins nothing (netctl's current `system` / `acceptance-dataplane`,
    both still old-form `impl: "delivery.tasks.testrun:gate"`) grows a real, stray `--name` option the
    moment the generated module is regenerated against this signature. That is why this lands as its own
    platform PR rather than folded into the per-group-partition PR: netctl's pointer bump to THIS commit
    must happen in the same commit as its `test` group migration, which supplies the `with: { name: ... }`
    pins that make the option disappear again. A red `tasks generate --check` / `test_mechanism_parity`
    on an unmigrated caller between the two pointer bumps is expected, not a regression.
    """
    cfg = config()
    extra = list(ctx.args)
    filtered = bool(extra)
    if filtered:
        _warn_filtered(cfg)
    raise typer.Exit(run_gate(cfg.gate(name or ctx.info_name), cfg, extra, filtered=filtered))


def report_cmd() -> None:
    """REPORT step: merge the per-module results the earlier gates already wrote into the shared Allure
    results and render the merged single-file Allure HTML archive. Runs NO tests; it archives the verdict of
    the gates that ran before it, and is always green so archiving never reddens a run."""
    raise typer.Exit(report())


def accept_cmd(ctx: typer.Context) -> None:
    """Convenience: run every lab-based gate in its declared order and then the report step, against the
    running lab. Trailing args reach the pytest of the gate that declares `args: true`; a run carrying any
    is exploratory and is quarantined into its own results dir, leaving the archive of the last full gate
    intact. The gates it chains are also addressable individually."""
    raise typer.Exit(accept(list(ctx.args)))
