"""`test:unit`: run a product's own pytest suite in a venv the kernel provisions (si#859, D7).

WHY THIS IS THE KERNEL'S. Running pytest over a set of directories in a venv built from a requirements
file needs no product knowledge. Measured on 2026-11-25 (the table is on si#859): cleon and asbundle each
carried the same two hand-written CI lines for it, netctl the multi-root form, and cleon-firn a suite
nothing ran. Which roots, which requirements and which configuration are the product's DATA, so they
arrive as parameters and nothing here names a product.

THE VENV IS KEYED ON THE REQUIREMENTS' CONTENT. A venv cached on nothing keeps whatever it was first
given, and `pip install -r` on top of it only ever adds: a package the file dropped stays importable, and
the suite goes on passing against a dependency the product no longer declares. That is this repository's
recurring defect (a stale cached result read as a current one), so the venv carries a stamp of what it
was built from and is rebuilt from scratch when the stamp differs. The stamp covers the requirements file
AND every file it pulls in with `-r` or `-c`, because a pin that moved one include down is the same
change. It lives INSIDE the venv and is written only after every install succeeded, so a venv
`ensure_venv` had to rebuild, or one a failed pip left half-built, carries no stamp and is never taken for
a finished one.

THE VENV LIVES UNDER `build/` and not beside the requirements file, which is where `test:gate` puts its
suite venv. Beside the file would be wrong here: a product's unit requirements are typically its
orchestrator's `requirements.txt` (cleon, asbundle, cleon-firn), and the `.venv` beside that file is the
LAUNCHER'S own venv, which a rebuild would wipe. `build/` is the kernel's output directory, already
ignored by every scaffolded product.

pytest IS ADDED ONLY WHEN THE REQUIREMENTS DID NOT BRING IT, AND UNPINNED (Marco, 2026-11-25), and the run
says so in one line. A product that pins pytest gets exactly that pin. One that does not gets the release
of the day the venv was built, and keeps it: the stamp freezes the venv until the requirements change.
In derived CI the checkout (`actions/checkout` without `clean: false`, which runs `git clean -ffdx`)
removes the ignored `build/` directory, so every CI job builds the unit venv fresh and an unpinned
fallback pytest is the current release. The stamp's reuse holds on a developer's checkout. Rebuilding
fresh is intended.

A ROOT WITH NO TESTS IS RED (si#859, merged from #674). pytest exits 5 when it collected nothing, and a
gate that read that as anything but a failure would be green precisely because the suite it guards is
gone. With several roots that is not enough: `pytest a b` with `b` empty exits 0, so each root is
collected on its own first.
"""
from __future__ import annotations

import hashlib
import shlex
import shutil
from collections.abc import Sequence
from pathlib import Path

from simplon.adapters import pyvenv
from simplon.kernel import log
from simplon.kernel.run import run as _run
from simplon.manifest import context

#: The seconds a `test:unit` run may take when the command names no `timeout`. A run that hangs is
#: neither green nor red, so there is always a limit; this one is generous because it bounds a product's
#: WHOLE unit suite in one pytest run, not one test. Venv provisioning is not inside it.
UNIT_TIMEOUT = 1800

#: Where the unit venvs live, relative to the product root: one per requirements file.
VENVS = Path("build") / "venvs" / "unit"

#: The file inside a venv recording what it was built from (see the module docstring).
STAMP = "simplon-unit-requirements.sha256"

#: pytest's own exit code for "no tests were collected".
NO_TESTS_COLLECTED = 5

#: The pip requirements-file options that pull another file in, each relative to the including file.
_INCLUDES = ("-r", "--requirement", "-c", "--constraint")

_FORM = "`with: { paths: [<dir>, ...], requirements: <file> }`"


def _inside(root: Path, value: str, name: str) -> Path:
    """`value` under the product root, or a refusal: every parameter here is relative to the root."""
    path = (root / value).resolve()
    if Path(value).is_absolute() or not path.is_relative_to(root.resolve()):
        raise context.TaskRefused(f"test:unit: `{name}` names {value}, which is not under the product root "
                                  f"{root}; write it relative to the root, as in {_FORM}")
    return path


def _roots(root: Path, paths: object) -> list[str]:
    """The test roots as written, after refusing a shape or a directory pytest could only misreport.

    A path that does not exist is refused HERE, before any venv is built: pytest would otherwise exit 4
    ("file or directory not found") or 5, and the message would blame the collection for a typo.
    """
    if isinstance(paths, str) or not isinstance(paths, Sequence):
        raise context.TaskRefused(f"test:unit: `paths` must be a list of directories relative to the product "
                                  f"root, got {paths!r}; write {_FORM}")
    if not paths:
        raise context.TaskRefused(f"test:unit: no `paths` were given, so there is no suite to run; "
                                  f"write {_FORM}")
    if not all(isinstance(each, str) and each for each in paths):
        raise context.TaskRefused(f"test:unit: every entry of `paths` must be a directory name, got {paths!r}")
    missing = [each for each in paths if not _inside(root, each, "paths").is_dir()]
    if missing:
        raise context.TaskRefused(f"test:unit: {', '.join(missing)} is not a directory under {root}; nothing "
                                  f"was run. Fix the entry in `paths`, or remove it")
    return list(paths)


def _file(root: Path, value: str, name: str) -> Path:
    path = _inside(root, value, name)
    if not path.is_file():
        raise context.TaskRefused(f"test:unit: the `{name}` file {value} does not exist under {root}; "
                                  f"nothing was run")
    return path


def _timeout(timeout: object) -> int:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise context.TaskRefused(f"test:unit: `timeout: {timeout}` is no limit, and a run without one has no "
                                  f"verdict; give `timeout:` in seconds, greater than 0, or leave it out "
                                  f"for {UNIT_TIMEOUT}")
    return timeout


def _included(path: Path) -> list[Path]:
    """The files `path` pulls in with `-r`/`-c` (both spellings, `=` or a space), relative to `path`."""
    found: list[Path] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue
        for i, word in enumerate(words):
            option, eq, value = word.partition("=")
            if option in _INCLUDES and eq:
                found.append(path.parent / value)
            elif word in _INCLUDES and i + 1 < len(words):
                found.append(path.parent / words[i + 1])
            elif word[:2] in ("-r", "-c") and len(word) > 2 and not word.startswith("--"):
                found.append(path.parent / word[2:])
    return found


def _digest(requirements: Path) -> str:
    """What the venv is built from: the requirements file and every file it includes, recursively.

    An include that does not exist is hashed as its name alone; pip then refuses it, quoted, and no stamp
    is written, so the digest never has to be right about a venv that was not built.
    """
    digest = hashlib.sha256()
    seen: set[Path] = set()
    pending = [requirements]
    while pending:
        path = pending.pop(0).resolve()
        if path in seen:
            continue
        seen.add(path)
        digest.update(str(path).encode() + b"\0")
        if path.is_file():
            digest.update(path.read_bytes() + b"\0")
            pending.extend(_included(path))
    return digest.hexdigest()


def _stamp(venv: Path) -> str:
    try:
        return (venv / STAMP).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _install(pip: str, args: list[str], what: str) -> bool:
    """pip install `args`; False after quoting pip, because only pip knows which line it could not meet."""
    installed = _run([pip, "install", "-q", "--disable-pip-version-check", *args])
    if installed.ok:
        return True
    said = (installed.err or installed.out).rstrip() or "(pip wrote nothing at all)"
    log.error(f"test:unit: {what} did not install (pip rc {installed.rc}); the suite was not run, so "
              f"nothing it might have reported would be about the product:\n{said}")
    return False


def _venv(root: Path, requirements: Path) -> str | None:
    """The interpreter of a venv holding exactly `requirements` (plus pytest), or None after saying why."""
    rel = requirements.relative_to(root.resolve())
    venv = root / VENVS / "--".join(rel.parts)
    digest = _digest(requirements)
    if _stamp(venv) != digest:
        # Ignoring errors is safe: a tree that survives is rebuilt or refused by `ensure_venv` (it dies when
        # it cannot), and a leftover stamp in it would still differ from `digest`, so nothing stale is reused.
        shutil.rmtree(venv, ignore_errors=True)
    pyvenv.ensure_venv(venv)
    python, pip = str(venv / "bin" / "python"), str(venv / "bin" / "pip")
    if _stamp(venv) == digest:
        log.info(f"test:unit: venv for {rel} reused ({venv.relative_to(root)}, requirements unchanged)")
        return python
    log.info(f"test:unit: building the venv for {rel} in {venv.relative_to(root)}")
    if not _install(pip, ["-r", str(requirements)], f"the requirements in {rel}"):
        return None
    if not _run([python, "-c", "import pytest"]).ok:
        log.info(f"test:unit: {rel} does not bring pytest, so the kernel added pytest (unpinned)")
        if not _install(pip, ["pytest"], "pytest"):
            return None
    (venv / STAMP).write_text(digest + "\n", encoding="utf-8")
    return python


def _empty_roots(python: str, root: Path, config_args: list[str], roots: list[str], timeout: int) -> list[str]:
    """The roots that collect no test on their own (pytest exit 5), each asked separately.

    Only asked when there are several: with one root the run's own exit 5 says the same, for free. A root
    whose collection fails for another reason is not called empty; the run reports that error itself.
    """
    if len(roots) < 2:
        return []
    return [each for each in roots
            if _run([python, "-m", "pytest", "--collect-only", "-q", *config_args, each],
                    cwd=str(root), timeout=timeout).rc == NO_TESTS_COLLECTED]


def run(paths: Sequence[str] = (), requirements: str = "", config: str = "",
        timeout: int = UNIT_TIMEOUT) -> int:
    """Run the product's pytest suite over `paths` in a venv built from `requirements`.

    All three paths are relative to the product root, and pytest runs FROM the root, so a conftest that
    puts the product's own sources on `sys.path` (cleon, asbundle, cleon-firn) resolves as it does in their
    CI. `timeout` bounds the pytest run in seconds.
    """
    root = context.current().root
    roots = _roots(root, paths)
    if not requirements:
        raise context.TaskRefused(f"test:unit: no `requirements` file was named, so there is nothing to build "
                                  f"the venv from; write {_FORM}")
    requirements_path = _file(root, requirements, "requirements")
    config_args = ["-c", str(_file(root, config, "config"))] if config else []
    limit = _timeout(timeout)

    python = _venv(root, requirements_path)
    if python is None:
        return 1
    empty = _empty_roots(python, root, config_args, roots, limit)
    if empty:
        log.error(f"test:unit: pytest collected no tests in {', '.join(empty)}; a root with no tests is red, "
                  f"not green. Point `paths` at the directories that hold the tests, or remove the entry")
        return 1
    result = _run([python, "-m", "pytest", *config_args, *roots], capture=False, cwd=str(root), timeout=limit)
    if result.timed_out:
        log.error(f"test:unit: the suite in {', '.join(roots)} did not finish within its timeout of {limit} s "
                  f"and was stopped; it has no verdict. Find the test that hangs, or raise `timeout:`")
        return 1
    if result.rc == NO_TESTS_COLLECTED:
        log.error(f"test:unit: pytest collected no tests in {', '.join(roots)} (exit {result.rc}); an empty "
                  f"suite is red, not green. Point `paths` at the directories that hold the tests")
        return result.rc
    if result.rc == 0:
        log.ok(f"test:unit passed ({', '.join(roots)})")
    return result.rc
