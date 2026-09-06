"""simplon - a delivery orchestrator for any software component that follows a CI/CD flow: it
assembles a component's CLI from one manifest and runs the steps, as a framework of tasks that a
component adopts and extends. It grew up inside netctl, which is still its largest consumer; who else
installs it is measured and written down in `simplon.surface`.

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
    from ._version import version as __version__  # type: ignore[import-not-found,unused-ignore]
except ImportError:  # pragma: no cover - exercised by the source-tree path, not by an installed package
    from importlib.metadata import PackageNotFoundError, version as _dist_version

    try:
        __version__ = _dist_version("simplon")
    except PackageNotFoundError:
        __version__ = "0.0.0.dev0+unknown"
