"""Where a moved module now lives, and the import alias that keeps an old path working until its deadline.

si#399 put each module into the package of its component (`kernel`, `domain`, `adapters`, `tasks`, `ui`,
`cli`) and dissolved `simplon.orchestrator`. About two hundred import lines in seven products named an old
path - measured per line in `simplon.cli.surface.MOVED_CONSUMERS` - so every old path stayed importable
through the release `MOVED_DUE_AFTER` names, and announced the move when it was imported.

THAT PERIOD IS OVER (si#470, 0.33.0). `MOVED` and `DISSOLVED` are empty, so the finder answers no alias.
The mechanism stays, installed and tested against a synthetic pair, because the next move needs exactly
this: a move fills the two tables and sets the deadline, and nothing else.

AND A REMOVED PATH IS A TOMBSTONE, NOT A BARE MISS (si#473). In the same release si#473 split
`simplon.domain` into `simplon.model` and `simplon.manifest` with no alias window. So that a product
bumping past both does not have to guess, every removed path - si#399's and `domain`'s - is in `GONE`:
its import still fails, as a `GoneError` (a `ModuleNotFoundError`), and the message names the new home.
The tombstones stand through the release `GONE_DUE_AFTER` names.

AN ALIAS, NOT A STUB FILE, and the difference is a measured defect (Marco, 2026-10-13). The 0.4 tombstones
were modules of their own that served attributes through `__getattr__`. Products patch the kernel by
string at 13 sites - `patch("simplon.orchestrator.steps.run_stream")` - and a patch on a stub sets the
attribute on the STUB: the real module keeps its function, the product's test stays green, and it tests
nothing. That is this repository's recurring defect, a green that cannot tell "patched" from "missed".
`MovedFinder` instead answers an old path with THE SAME MODULE OBJECT as the new one, so
`sys.modules["simplon.run"] is sys.modules["simplon.kernel.run"]` and a patch through either name lands on
the code that runs.

This module lives in the kernel rather than beside `surface` because `simplon/__init__.py` installs the
finder, and importing `simplon.cli.surface` from there would import the whole command line first. It
imports nothing of simplon.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import warnings
from types import ModuleType

#: Old import path (relative to `simplon`) -> the module's new home. EMPTY SINCE 0.33.0 (si#470): the 65
#: paths si#399 moved were promised through 0.32 and came out on that deadline. The record stays, empty,
#: for the next move.
MOVED: dict[str, str] = {}

#: Packages a move dissolved. Nothing lives in one any more, but `from simplon.orchestrator import steps`
#: needs the package to import before it can reach the alias for its child, so each is answered with an
#: empty package that holds only what its children's aliases put there. Empty since 0.33.0 with `MOVED`;
#: si#399's two were `orchestrator` and `orchestrator.model`.
DISSOLVED: frozenset[str] = frozenset()

#: The (major, minor) after which the old paths are removed: si#399's move shipped in 0.31, and the products
#: had two minors to migrate (Marco, 2026-10-13), so 0.33 is the first release without them. That promise
#: was kept (si#470); the pair stays as its record until the next move names its own.
#: `test_surface.py` turns red on the release run of the first minor past this pair while `MOVED` is not
#: empty.
MOVED_DUE_AFTER = (0, 32)


#: Old import path (relative to `simplon`) -> where the module lives now: the TOMBSTONES (si#473). An old
#: path here does not import, but its failure says where the module went instead of the bare "No module
#: named". EMPTY SINCE 0.34.0 (si#485): si#399's 65 paths, `domain`'s split and `tasks.tasks` stood here
#: through 0.33, the release that removed them, and came out on that deadline. An old path is now a plain
#: `ModuleNotFoundError`; `with-what/surface.md` keeps the table of where each one went. The record stays,
#: empty, for the next removal.
GONE: dict[str, str] = {}

#: Packages that no longer exist, and whose every old child is a tombstone above: importing one fails
#: naming where each of its modules went. Empty since 0.34.0 with `GONE`; si#473's were `domain`,
#: `orchestrator` and `orchestrator.model`.
GONE_PACKAGES: frozenset[str] = frozenset()

#: The (major, minor) after which the tombstones themselves go: they stood through 0.33, and 0.34.0 is the
#: first release without them (Marco, 2026-10-16). That promise was kept (si#485); the pair stays as its
#: record until the next removal names its own. `test_surface.py` turns red on the release run of the first
#: minor past this pair while `GONE` is not empty.
GONE_DUE_AFTER = (0, 33)


class GoneError(ModuleNotFoundError):
    """An old import path that was removed: a `ModuleNotFoundError` like any unknown name, whose message
    names the module's new home."""


def gone_message(old: str) -> str:
    """The one wording a tombstone fails with. Single source, pinned by the tests."""
    rel = old.removeprefix("simplon.")
    removed = "{}.{}.0".format(*GONE_DUE_AFTER)
    if rel in GONE:
        return f"{old} has moved to {GONE[rel]}; import it from there. The old path was removed in {removed}."
    children = ", ".join(f"simplon.{child} -> {GONE[child]}" for child in sorted(GONE)
                         if child.startswith(rel + "."))
    return f"{old} no longer exists; it was removed in {removed}. Its modules moved: {children}."


def moved_message(old: str, new: str) -> str:
    """The one wording a move announces itself with. Single source, pinned by the tests."""
    major, minor = MOVED_DUE_AFTER
    return (f"{old} has moved to {new}; import it from there. "
            f"The old path still works and is removed in {major}.{minor + 1}.0.")


class _Alias(importlib.abc.Loader):
    """Loads an old path as the module that lives at the new one."""

    def __init__(self, old: str, new: str) -> None:
        self.old, self.new = old, new

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        # stacklevel 2 is the line that imported: `warnings` already skips importlib's own frames. And
        # FutureWarning, not DeprecationWarning - Python's default filters show a DeprecationWarning only
        # when `__main__` triggers it, and the line that imports an old path is a product's module.
        warnings.warn(moved_message(self.old, self.new), FutureWarning, stacklevel=2)
        module = importlib.import_module(self.new)
        self._spec = module.__spec__
        return module

    def exec_module(self, module: ModuleType) -> None:
        # The import system has just set `module.__spec__` to the OLD name's spec, unconditionally. Put
        # the real one back, so the module still says where it lives (reload, pickle and inspect read it).
        module.__spec__ = self._spec


class _Dissolved(importlib.abc.Loader):
    """An empty package standing where a dissolved one was, so its children's aliases can be reached."""

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        module.__path__ = []


class MovedFinder(importlib.abc.MetaPathFinder):
    """Answers the old paths, and only them; every other name goes on to the ordinary finders.

    A tombstoned path (`GONE`, `GONE_PACKAGES`) is answered by RAISING: `find_spec` - and so
    `importlib.util.find_spec("simplon.run")` - raises `GoneError`, a ModuleNotFoundError naming the new
    home, rather than returning None the way a finder says "not mine"."""

    def find_spec(self, fullname: str, path: object = None,
                  target: ModuleType | None = None) -> importlib.machinery.ModuleSpec | None:
        old = fullname.removeprefix("simplon.")
        if old == fullname:
            return None
        if old in MOVED:
            return importlib.machinery.ModuleSpec(fullname, _Alias(fullname, MOVED[old]))
        if old in DISSOLVED:
            return importlib.machinery.ModuleSpec(fullname, _Dissolved(), is_package=True)
        if old in GONE or old in GONE_PACKAGES:
            raise GoneError(gone_message(fullname), name=fullname)
        return None


def install() -> None:
    """Put the finder first on `sys.meta_path`, once."""
    if not any(isinstance(each, MovedFinder) for each in sys.meta_path):
        sys.meta_path.insert(0, MovedFinder())
