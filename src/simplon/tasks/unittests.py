"""`test:unit`: run a product's own pytest suite in a venv the kernel provisions (si#859, D7).

WHY THIS IS THE KERNEL'S. Running pytest over a set of directories in a venv built from a requirements
file needs no product knowledge. Measured on 2026-11-25 (the table is on si#859): cleon and asbundle each
carried the same two hand-written CI lines for it, netctl the multi-root form, and cleon-firn a suite
nothing ran. Which roots, which requirements and which configuration are the product's DATA, so they
arrive as the three parameters and nothing here names a product.

THE VENV IS KEYED ON THE REQUIREMENTS FILE'S CONTENT. A venv cached on nothing keeps whatever it was first
given, and `pip install -r` on top of it only ever adds: a package the file dropped stays importable, and
the suite goes on passing against a dependency the product no longer declares. That is this repository's
recurring defect (a stale cached result read as a current one), so the venv carries a stamp of what it
was built from and is rebuilt from scratch when the stamp differs. The stamp lives INSIDE the venv and is
written only after every install succeeded, so a venv `ensure_venv` had to rebuild, or one a failed pip
left half-built, carries no stamp and is never taken for a finished one.

THE VENV LIVES UNDER `build/` and not beside the requirements file, which is where `test:gate` puts its
suite venv. Beside the file would be wrong here: a product's unit requirements are typically its
orchestrator's `requirements.txt` (cleon, asbundle, cleon-firn), and the `.venv` beside that file is the
LAUNCHER'S own venv, which a rebuild would wipe. `build/` is the kernel's output directory, already
ignored by every scaffolded product.

pytest IS ADDED ONLY WHEN THE REQUIREMENTS DID NOT BRING IT (Marco, 2026-11-25), and the run says so. A
product that pins pytest gets exactly that pin; one that does not gets the kernel's, `PYTEST` below,
pinned so two runs of one requirements file install the same thing.

AN EMPTY COLLECTION IS RED (si#859, merged from #674). pytest exits 5 when it collected nothing, and a gate
that read that as anything but a failure would be green precisely because the suite it guards is gone.
"""
from __future__ import annotations

import hashlib
import shutil
from collections.abc import Sequence
from pathlib import Path

from simplon.adapters import pyvenv
from simplon.kernel import log
from simplon.kernel.run import run as _run
from simplon.manifest import context

#: The pytest the kernel installs when a product's requirements do not bring one. Pinned rather than
#: floating, so one requirements file always yields one venv; a product that wants another pins its own.
PYTEST = "pytest==9.1.1"

#: Where the unit venvs live, relative to the product root: one per requirements file.
VENVS = Path("build") / "venvs" / "unit"

#: The file inside a venv recording what it was built from (see the module docstring).
STAMP = "simplon-unit-requirements.sha256"

#: pytest's own exit code for "no tests were collected".
NO_TESTS_COLLECTED = 5

_FORM = "`with: { paths: [<dir>, ...], requirements: <file> }`"


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
    missing = [each for each in paths if not (root / each).is_dir()]
    if missing:
        raise context.TaskRefused(f"test:unit: {', '.join(missing)} is not a directory under {root}; nothing "
                                  f"was run. Fix the entry in `paths`, or remove it")
    return list(paths)


def _file(root: Path, value: str, name: str) -> Path:
    path = root / value
    if not path.is_file():
        raise context.TaskRefused(f"test:unit: the `{name}` file {value} does not exist under {root}; "
                                  f"nothing was run")
    return path


def _digest(requirements: Path) -> str:
    """What the venv is built from: the requirements file's bytes, and the kernel's fallback pin."""
    return hashlib.sha256(requirements.read_bytes() + b"\n" + PYTEST.encode()).hexdigest()


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
    rel = requirements.relative_to(root)
    venv = root / VENVS / "--".join(rel.parts)
    digest = _digest(requirements)
    if _stamp(venv) != digest:
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
        log.info(f"test:unit: {rel} does not bring pytest, so the kernel added {PYTEST}")
        if not _install(pip, [PYTEST], PYTEST):
            return None
    (venv / STAMP).write_text(digest + "\n", encoding="utf-8")
    return python


def run(paths: Sequence[str] = (), requirements: str = "", config: str = "") -> int:
    """Run the product's pytest suite over `paths` in a venv built from `requirements`.

    All three are relative to the product root, and pytest runs FROM the root, so a conftest that puts
    the product's own sources on `sys.path` (cleon, asbundle, cleon-firn) resolves as it does in their CI.
    """
    root = context.current().root
    roots = _roots(root, paths)
    if not requirements:
        raise context.TaskRefused(f"test:unit: no `requirements` file was named, so there is nothing to build "
                                  f"the venv from; write {_FORM}")
    requirements_path = _file(root, requirements, "requirements")
    config_args = ["-c", str(_file(root, config, "config"))] if config else []

    python = _venv(root, requirements_path)
    if python is None:
        return 1
    rc = _run([python, "-m", "pytest", *config_args, *roots], capture=False, cwd=str(root)).rc
    if rc == NO_TESTS_COLLECTED:
        log.error(f"test:unit: pytest collected no tests in {', '.join(roots)} (exit {rc}); an empty suite is "
                  f"red, not green. Point `paths` at the directories that hold the tests")
        return rc
    if rc == 0:
        log.ok(f"test:unit passed ({', '.join(roots)})")
    return rc
