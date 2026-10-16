"""simplon - a delivery orchestrator for any software component that follows a CI/CD flow: it
assembles a component's CLI from one manifest and runs the steps, as a framework of tasks that a
component adopts and extends. It grew up inside netctl, which is still its largest consumer; who else
installs it is measured and written down in `simplon.cli.surface`.

A product installs `simplon` (PyPI) and pins it in its own requirements: the kernel arrives as an
ordinary dependency, nothing is vendored and no source path is prepended. NOTE: the import package is
deliberately `simplon`, not `platform` (a top-level `platform` package would shadow the Python stdlib
`platform` module) and not bare `orchestrator` (collides with product packages).
"""
from __future__ import annotations

# --- the version (#3) -------------------------------------------------------------------------------------
#
# NOT a literal. It used to be one, and it was the second of three hand-typed spellings of the same number
# (pyproject.toml, here, and the `simplon==` pin in bootstrap.py) that only a test held together, and only
# after a divergence already existed. The number now comes from the git tag via setuptools-scm; see the
# `[tool.setuptools_scm]` block in pyproject.toml for why, and for the version scheme.
#
# Two ways in, because a package is read in two shapes and only one of them has a `.git` beside it:
#
#   _version.py                 written by setuptools-scm at BUILD time and shipped inside the wheel. This
#                               is the installed package's answer, and it needs neither git nor the
#                               distribution metadata to give it.
#   distribution metadata       the fallback for a source tree that has been installed (`pip install -e .`)
#                               but not built in place - and for any consumer who somehow has the dist-info
#                               without the file.
#
# The last resort is deliberately a version nobody can mistake for a release AND that `released_pin` below
# refuses outright: reaching it means simplon is neither built nor installed (a bare `sys.path` insertion),
# and in that state there is no true answer to give - so the scaffolder must fail loudly rather than write
# an invented pin into somebody's requirements.txt.
try:
    from simplon._version import version as __version__  # type: ignore[import-not-found,unused-ignore]
except ImportError:  # pragma: no cover - exercised by the source-tree path, not by an installed package
    from importlib.metadata import PackageNotFoundError, version as _dist_version

    try:
        __version__ = _dist_version("simplon")
    except PackageNotFoundError:
        __version__ = "0.0.0.dev0+unknown"

# A moved module's old import path stays importable, as the very same module object, until the release
# `simplon.kernel.moved.MOVED_DUE_AFTER` names. No move is standing since 0.33.0 (si#470 removed si#399's
# aliases), so the finder answers no alias; it stays installed for the next one. What it does answer since
# si#473 is a removed path's TOMBSTONE (`moved.GONE`): the import still fails, naming the new home.
from .kernel import moved as _moved  # noqa: E402

_moved.install()


def __getattr__(name: str) -> object:
    """`from simplon import run` for a removed top-level module fails naming its new home (si#473).

    The finder alone is not enough for this one spelling, and that is measured: `from simplon import X`
    treats a ModuleNotFoundError whose `name` is `simplon.X` as "no such submodule" and swallows it, so the
    tombstone's message was replaced by a bare "cannot import name 'run' from 'simplon'"."""
    if name in _moved.GONE:
        raise _moved.GoneError(_moved.gone_message(f"simplon.{name}"), name=f"simplon.{name}")
    raise AttributeError(f"module 'simplon' has no attribute {name!r}")
