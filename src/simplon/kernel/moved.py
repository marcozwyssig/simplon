"""Where every module si#399 moved now lives, and the import alias that keeps the old paths working.

si#399 put each module into the package of its component (`kernel`, `domain`, `adapters`, `tasks`, `ui`,
`cli`) and dissolved `simplon.orchestrator`. About two hundred import lines in seven products name an old
path - measured per line in `simplon.cli.surface.MOVED_CONSUMERS` - so every old path stays importable until
the release `MOVED_DUE_AFTER` names, and announces the move when it is imported.

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

#: Old import path (relative to `simplon`) -> the module's home since si#399.
MOVED: dict[str, str] = {
    "artifactschema": "simplon.domain.artifactschema",
    "artifactsection": "simplon.domain.artifactsection",
    "awake": "simplon.kernel.awake",
    "backend": "simplon.adapters.backend",
    "bootstrap": "simplon.cli.bootstrap",
    "carrierspec": "simplon.domain.carrierspec",
    "catalogue": "simplon.domain.catalogue",
    "checksum": "simplon.adapters.checksum",
    "clablifecycle": "simplon.adapters.clablifecycle",
    "clabrender": "simplon.adapters.clabrender",
    "clitaxonomy": "simplon.domain.clitaxonomy",
    "completiongen": "simplon.tasks.completiongen",
    "compose": "simplon.adapters.compose",
    "context": "simplon.domain.context",
    "credentials": "simplon.adapters.credentials",
    "degraded": "simplon.kernel.degraded",
    "deployment": "simplon.domain.deployment",
    "devcontainer": "simplon.adapters.devcontainer",
    "disk": "simplon.adapters.disk",
    "diskguard": "simplon.adapters.diskguard",
    "docker": "simplon.adapters.docker",
    "environments": "simplon.domain.environments",
    "fetch": "simplon.adapters.fetch",
    "filelock": "simplon.kernel.filelock",
    "githubpackages": "simplon.adapters.githubpackages",
    "healthgate": "simplon.adapters.healthgate",
    "host": "simplon.adapters.host",
    "hostpath": "simplon.adapters.hostpath",
    "imagenames": "simplon.adapters.imagenames",
    "interact": "simplon.adapters.interact",
    "labegress": "simplon.adapters.labegress",
    "labhost": "simplon.adapters.labhost",
    "labinstance": "simplon.adapters.labinstance",
    "labnet": "simplon.adapters.labnet",
    "layout": "simplon.domain.layout",
    "linux": "simplon.adapters.linux",
    "log": "simplon.kernel.log",
    "manifestmodel": "simplon.domain.manifestmodel",
    "nexusproxy": "simplon.adapters.nexusproxy",
    "oras": "simplon.adapters.oras",
    "orchestrator.manifest": "simplon.domain.manifest",
    "orchestrator.model.treeform": "simplon.domain.treeform",
    "orchestrator.plan": "simplon.kernel.plan",
    "orchestrator.product": "simplon.kernel.product",
    "orchestrator.steps": "simplon.kernel.steps",
    "orchestrator.tui": "simplon.ui.tui",
    "outputs": "simplon.domain.outputs",
    "portainer": "simplon.adapters.portainer",
    "ports": "simplon.adapters.ports",
    "provenance": "simplon.kernel.provenance",
    "pyvenv": "simplon.adapters.pyvenv",
    "run": "simplon.kernel.run",
    "runhost": "simplon.kernel.runhost",
    "runners": "simplon.domain.runners",
    "signatures": "simplon.domain.signatures",
    "steplog": "simplon.kernel.steplog",
    "surface": "simplon.cli.surface",
    "taskgen": "simplon.tasks.taskgen",
    "tools": "simplon.adapters.tools",
    "topology": "simplon.adapters.topology",
    "tracker": "simplon.adapters.tracker",
    "verdict": "simplon.kernel.verdict",
    "waits": "simplon.kernel.waits",
    "workflowgen": "simplon.tasks.workflowgen",
    "yamlkeys": "simplon.domain.yamlkeys",
}

#: Packages si#399 dissolved. Nothing lives in them any more, but `from simplon.orchestrator import steps`
#: needs the package to import before it can reach the alias for its child, so each is answered with an
#: empty package that holds only what its children's aliases put there.
DISSOLVED = frozenset({"orchestrator", "orchestrator.model"})

#: The (major, minor) after which the old paths are removed: the move ships in 0.31, and the products have
#: two minors to migrate (Marco, 2026-10-13), so 0.33 is the first release without them.
#: `test_surface.py` turns red on the release run of the first minor past this pair.
MOVED_DUE_AFTER = (0, 32)


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
    """Answers the old paths, and only them; every other name goes on to the ordinary finders."""

    def find_spec(self, fullname: str, path: object = None,
                  target: ModuleType | None = None) -> importlib.machinery.ModuleSpec | None:
        old = fullname.removeprefix("simplon.")
        if old == fullname:
            return None
        if old in MOVED:
            return importlib.machinery.ModuleSpec(fullname, _Alias(fullname, MOVED[old]))
        if old in DISSOLVED:
            return importlib.machinery.ModuleSpec(fullname, _Dissolved(), is_package=True)
        return None


def install() -> None:
    """Put the finder first on `sys.meta_path`, once."""
    if not any(isinstance(each, MovedFinder) for each in sys.meta_path):
        sys.meta_path.insert(0, MovedFinder())
