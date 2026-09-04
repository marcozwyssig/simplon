"""simplon - the delivery orchestrator kernel, the domain-agnostic shared core for the *ctl
product family (netctl, infractl).

A product installs `simplon` (PyPI) and pins it in its own requirements: the kernel arrives as an
ordinary dependency, nothing is vendored and no source path is prepended. NOTE: the import package is
deliberately `simplon`, not `platform` (a top-level `platform` package would shadow the Python stdlib
`platform` module) and not bare `orchestrator` (collides with product packages).
"""
from __future__ import annotations

__version__ = "0.1.0"
