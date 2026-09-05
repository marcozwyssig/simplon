"""simplon - a delivery orchestrator for any software component that follows a CI/CD flow: it
assembles a component's CLI from one manifest and runs the steps, as a framework of tasks that a
component adopts and extends. The *ctl product family (netctl, infractl) is its first user.

A product installs `simplon` (PyPI) and pins it in its own requirements: the kernel arrives as an
ordinary dependency, nothing is vendored and no source path is prepended. NOTE: the import package is
deliberately `simplon`, not `platform` (a top-level `platform` package would shadow the Python stdlib
`platform` module) and not bare `orchestrator` (collides with product packages).
"""
from __future__ import annotations

__version__ = "0.1.8"
