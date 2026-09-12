"""Type-check a product's Python sources with mypy, in the host venv the CLI already runs in.

WHY THIS IS THE KERNEL'S. Running a type checker needs no product knowledge. mypy reads its own config
file, resolves its own roots from it, and reports against its own rules - none of that is a *ctl
convention. What IS the product's is the DATA: which sources are covered, which third-party modules have
no stubs, and which module is exempt and why. All of it lives in the product's `mypy.ini`, so a
per-product function forwarding this call would be a shim rather than a seam.

WHY AN INTERPRETER, not Docker. The checker needs to SEE the product's installed dependencies, or every
third-party import degrades into a blanket exception and the gate stops meaning anything. So the one
thing this task has to get right is WHICH interpreter it asks. Two shapes exist among the *ctl products
and both are served by one parameter:

  - the HOST VENV, which is the default. The orchestrator itself runs in it, so `sys.executable` is
    already the right answer and there is nothing to bootstrap. A product whose Python IS the host venv
    (netctl: sidecar + orchestrator + labgen) names nothing at all.
  - a BLOCK'S OWN venv, named with `with: { python: ... }`. A product that manages a block's
    dependencies separately (cockpit: the backend is a uv project) has its installed set there and not
    on the host, and pointing the checker at the host venv would type a program nobody ships.

Either way this stays the cheapest gate in the catalogue - no image, no daemon, no lab.

AND IT IS ALREADY OFF THE HOST, WHICH IS si#203'S ANSWER AND NOT ITS ASSUMPTION. si#199's rule is that a
product depends on no application installed on the system, and this gate reads like the second thing
standing outside it. It is not. `sys.executable` is an ABSOLUTE path to the interpreter the kernel is
already running in, and `mypy_argv` runs mypy as a MODULE of it, so nothing here is looked up on PATH.
Driven on 2026-09-12 with every `python*` removed from PATH and the kernel started from its own venv
interpreter: `Success: no issues found in 87 source files`, `typecheck-python passed`, rc 0. The same
PATH ran `test:gate` into `FileNotFoundError: [Errno 2] No such file or directory: 'python3'`, which is
the boundary si#202 measures and this gate is on the other side of it.

So the gate travels with the KERNEL rather than with a container of its own: the day the launcher gets
si#199's second route, this command is inside that container, reading exactly the installed set the
kernel runs against - which is the property the two paragraphs above insist on, obtained for nothing.

WHAT A CONTAINER OF ITS OWN WOULD HAVE COST, measured on a real product (this kernel, 87 source files)
rather than estimated, because si#163's "3.4 seconds" is this gate's own runtime and not the number the
decision turns on. The python profile's shape (si#121): `pip install --user` into the bind mount under
`PYTHONUSERBASE`, then `python -m mypy`.

  * mypy 1.18.2 + types-PyYAML alone:                 55 MB in the tree
  * plus the product's own dependencies (`-e .[typecheck]`): 108 MB, 9.0s of install
  * `python -m mypy --config-file mypy.ini` after that:  3.7s, `Success: no issues found in 87 source
    files` - the SAME verdict the host gate gives in 0.39s warm and 4.7s cold
  * the editable install needed `SETUPTOOLS_SCM_PRETEND_VERSION` to run at all: the mount is a git
    WORKTREE whose `.git` is a file pointing outside it, so setuptools-scm inside the container answers
    `unable to detect version for /src`

108 MB and a network round per product, to reproduce a verdict that is already identical and already
container-ready. That is the third answer si#203 asked for.

A SETUP FAILURE IS NOT A FINDING, AND THE EXIT CODE CANNOT TELL THEM APART. This module already draws
that line once, for a missing checker (`_require_mypy`), and it did not draw it for the missing
INSTALLED SET, which is the same class one level in. Measured in the container above with the product's
dependencies absent: rc 1 and 20 errors, 20 of 20 `Cannot find implementation or library stub for module
named ...`, not one about the product. With one deliberate `return 42` added to the same tree: rc 1 and
28 errors, 27 of them import resolution and 1 the real finding. A reader holding only the number cannot
tell those two runs from a clean tree with a single type error, and `1` is what a CI step reads.

So the run is CLASSIFIED rather than passed on. A run whose errors are ALL import resolution is refused
as a setup error in `_require_mypy`'s own voice - the checker did not see what it was pointed at, so it
ruled on nothing. A run that carries both says so and then reports the findings, because the findings
are real and the verdict over the rest is not one the gate earned. `--show-error-codes` and `--no-pretty` are on the
argv and not left to the config for exactly this reason: a product may write `hide_error_codes = True`
or `pretty = True`, and either one switches the classification off - the second by wrapping a long
message so the `[code]` bracket lands on the continuation line. Measured against mypy 1.18.2 both ways,
and `mypy_argv` carries why.

WHY A WORKING DIRECTORY. mypy resolves the source roots in its config against the CURRENT directory, not
against the config's own location. A product whose config sits inside a block therefore needs the gate to
run there, which is `with: { workdir: ... }`. It defaults to the product root, so a product with one
config at the top names nothing.

WHY THE TOOL IS AN EXTRA. mypy is not a runtime dependency of the kernel - a product that never
declares this command should not inherit a constraint on which type checker it may install. It lives in
`simplon[typecheck]` instead, which means the checker can legitimately be absent from the interpreter
this task points at. That is a SETUP error, not a finding, and the two must not look alike: a gate that
reports "mypy found problems" when mypy was never installed teaches a product to distrust it.

WHY A CONFIG FILE IS REQUIRED. mypy without one checks whatever it is pointed at, with defaults nobody
wrote down. A gate whose rules are implicit cannot be argued with when it goes red, and the first
argument it loses is its own existence. The file is the product's stated position - which layers are
covered, what is exempt, and the reason for each - so this task refuses rather than inventing one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NoReturn

from simplon import context, log
from simplon.run import Result, run

#: mypy's own convention, not a product's. A product that wants another name pins it with
#: `with: { config: <path> }` on its command; the path is read relative to the product root.
DEFAULT_CONFIG = "mypy.ini"

#: mypy's error codes for "I could not resolve this import", and the whole of si#203's split. Both say
#: the same thing about the ENVIRONMENT rather than about the product: `import-not-found` is a module the
#: checker found nothing for, `import-untyped` one it found without types. A run made only of these ruled
#: on nothing, whatever its exit code suggests.
IMPORT_CODES = ("import-not-found", "import-untyped")

#: One mypy diagnostic: `<path>:<line>: error: <message>  [<code>]`. `note:` lines are deliberately not
#: matched - each one explains an error that is already counted, so counting both reports every missing
#: import twice and turns one fault into two.
_ERROR = re.compile(r"^.+?: error: (?P<message>.*?)(?:  \[(?P<code>[a-z0-9-]+)\])?$", re.MULTILINE)

#: The module name inside a mypy import diagnostic. Both wordings quote it and neither quotes anything
#: else: `Cannot find implementation or library stub for module named "typer"` and `Library stubs not
#: installed for "yaml"`. A message that quotes nothing is reported whole rather than dropped.
_QUOTED = re.compile(r'"([^"]+)"')


def _config_path(where: Path, config: str) -> Path:
    """The product's mypy configuration, or a loud failure naming what is missing."""
    path = where / (config or DEFAULT_CONFIG)
    if not path.is_file():
        raise ValueError(
            f"mypy: no configuration at {path} - a type gate states which sources it covers and what "
            f"is exempt; without that file there is nothing to enforce"
        )
    return path


def _interpreter(workdir: Path, python: str) -> str:
    """The interpreter to run mypy with: the one the CLI runs in, or the one the product names.

    A named interpreter that is not there is an ERROR, not a fallback to the host venv. Falling back
    would run the checker against a different installed set than the product declares and still report
    success, which is the one outcome a gate must never produce.
    """
    if not python:
        return sys.executable
    named = workdir / python
    if not named.is_file():
        raise ValueError(
            f"mypy: no interpreter at {named} - the gate must read the product's OWN installed set, "
            f"so it will not silently fall back to the host venv"
        )
    return str(named)


def _require_mypy(python_exe: str) -> None:
    """Fail with the name of the extra when the checker is absent from the target interpreter.

    Probed rather than inferred from the exit code: `python -m mypy` and a real type error both exit
    non-zero, so without this the missing tool would be reported as findings. The probe is cheap next
    to a mypy run, and it has to be a subprocess because the interpreter may not be this one.
    """
    if run([python_exe, "-c", "import mypy"]).rc == 0:
        return
    raise ValueError(
        f"mypy: not installed in {python_exe} - the type gate's tooling is an optional extra, so "
        f"install it with `pip install simplon[typecheck]` (or add `simplon[typecheck]` to the "
        f"requirements file for that interpreter). This is a setup error, not a type finding"
    )


def _unresolved_imports(unresolved: list[str], python_exe: str) -> NoReturn:
    """Refuse a run whose every error is an import mypy could not resolve (si#203).

    THE SAME RULE `_require_mypy` KEEPS, one level in. There it is the checker that is absent; here it is
    the installed set the checker was pointed at, and the consequence is identical - mypy exits non-zero
    for a reason that is not the product's code, and a reader holding the exit code cannot tell it from a
    type error. Measured on this kernel in a container with its dependencies absent: rc 1, 20 errors, 20
    of 20 import resolution, not one about the product. si#121 measured the same shape on a scaffolded
    product at five of five.

    REFUSED RATHER THAN REPORTED, which is si#203's open question answered. Reporting it as findings
    teaches a product that the gate is noisy, and a gate a product has learned to disbelieve is worse
    than one it does not have. The message therefore says which modules, in which interpreter, and that
    nothing was decided about the code.

    The rc is still 1, and widening it to mypy's own 2 was rejected: `log.die` is how every other setup
    fault in this module ends, `test all` collapses a step's rc to 0 or 1 anyway (si#163), and a second
    number nothing reads would be a seam invented rather than found. What separates the two outcomes is
    the sentence, and the sentence is what a reader meets first.
    """
    modules = ", ".join(sorted(set(unresolved)))
    raise ValueError(
        f"mypy: {len(set(unresolved))} module(s) could not be resolved in {python_exe} ({modules}) and "
        f"NOTHING else was reported - the checker did not see the installed set it was pointed at, so "
        f"it ruled on none of this product's code. This is a setup error, not a type finding: install "
        f"the product's dependencies into that interpreter (or point the gate at the one that has them "
        f"with `with: {{ python: ... }}`), and add a stub package for a dependency that ships none"
    )


def mypy_argv(python_exe: str, config: Path) -> list[str]:
    """PURE: the argv for the type gate. Separated so the wiring is assertable without running mypy.

    TWO FLAGS ARE ON THE LINE rather than left to the product's configuration, and that is si#203's
    classification made unswitchable. `classify` below reads one diagnostic per line and takes the code
    in brackets to tell a checker that could not see the installed set from a checker reporting on the
    product. A product's own `mypy.ini` can break either half:

      * `hide_error_codes = True` removes the code. Measured against mypy 1.18.2: `--show-error-codes`
        on the line still prints `  [return-value]`.
      * `pretty = True` WRAPS a long message, and the `  [code]` bracket lands on the continuation line.
        Measured on a tree whose only fault is a missing dependency: `classify` returned no import
        faults and two findings, so the gate said "mypy reported findings" and named neither the module
        nor the interpreter - a setup failure blamed on the product's code, which is the exact confusion
        this classification exists to end, arriving through a formatting option. `--no-pretty` overrides
        it, measured the same way.

    THE COST IS THE PRETTY RENDERING, in this one command, for a product that asked for it: the source
    line and the caret are gone from the gate's output. It is paid because a gate that misreads a broken
    environment as a defect in the code is worse than a gate that prints plainly, and because the
    formatting is a preference where the reading is a verdict.
    """
    return [python_exe, "-m", "mypy", "--config-file", str(config),
            "--show-error-codes", "--no-pretty"]


def classify(output: str) -> tuple[list[str], int]:
    """PURE: (the modules mypy could not resolve, the number of errors that are about the product).

    The whole of si#203's decision in one function, kept pure so the split is assertable without a mypy
    run and without an uninstalled tree. A caller reads the two halves as three cases: import faults
    alone is a SETUP failure, findings alone is the ordinary red, and both is a red whose verdict over
    everything the missing modules touch was never earned.

    Duplicates are kept rather than collapsed here. One missing module is reported once per importing
    file - `typer` was 4 of this kernel's own 20 - and a caller that wants the distinct names says so;
    a caller counting FILES affected would otherwise have nothing to count.
    """
    unresolved: list[str] = []
    findings = 0
    for match in _ERROR.finditer(output):
        if match["code"] in IMPORT_CODES:
            quoted = _QUOTED.findall(match["message"])
            unresolved.append(quoted[-1] if quoted else match["message"])
        else:
            findings += 1
    return unresolved, findings


def _echo(result: Result) -> None:
    """Put mypy's own output back in front of the reader, unchanged.

    The run is CAPTURED since si#203, because `simplon.run`'s own rule says to capture when the caller
    inspects the output and reports its own verdict - which is exactly what `classify` now does. The
    findings are what a person came for, so they are written out verbatim rather than summarised, and
    they go through this process' stdout so the step log and the TUI transcript carry them too.

    THE COST IS THAT THE GATE IS SILENT UNTIL MYPY ENDS, named here rather than left to be met. That is
    the half of the same rule that goes wrong quietly, and it is paid because this step is short and
    reports rather than transfers: 0.39s warm and 4.7s cold over this kernel's 87 source files. A
    product large enough for that to matter is the one that reopens the choice, and the way out is
    `run_stream`, not `capture=False` - the classification needs the text either way.
    """
    sys.stdout.write(result.out)
    sys.stderr.write(result.err)


def check(config: str = DEFAULT_CONFIG, workdir: str = "", python: str = "") -> int:
    """Type-check the product's Python sources (mypy) using its own configuration.

    ``workdir`` is where mypy runs, relative to the product root (default: the root itself), because
    mypy resolves its source roots against the current directory. ``config`` and ``python`` are read
    relative to THAT directory, so a block-local gate names its block once and everything else stays
    relative to it. A product with one config at the top and its dependencies in the host venv pins
    nothing at all.
    """
    ctx = context.current()
    where = ctx.root / workdir if workdir else ctx.root
    resolved = _config_path(where, config)
    python_exe = _interpreter(where, python)
    _require_mypy(python_exe)

    log.info(f"typecheck-python: mypy --config-file {resolved.relative_to(ctx.root)} "
             f"({'host venv' if not python else python})")
    result = run(mypy_argv(python_exe, resolved), cwd=str(where))
    _echo(result)
    if result.rc == 0:
        log.ok("typecheck-python passed")
        return 0
    unresolved, findings = classify(result.out + result.err)
    if unresolved and not findings:
        _unresolved_imports(unresolved, python_exe)
    if unresolved:
        log.warn(f"mypy could not resolve {len(set(unresolved))} module(s) in {python_exe} "
                 f"({', '.join(sorted(set(unresolved)))}), so everything they touch was checked against "
                 f"nothing - the findings above are real, the silence around them is not a verdict")
    log.die("mypy reported findings (see output above)")
