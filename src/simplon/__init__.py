"""delivery - the Delivery Orchestrator kernel, the domain-agnostic shared core for the *ctl
product family (netctl, infractl).

Consumed by each product via the lib/platform submodule on sys.path (dev-time; editable-install /
published artefacts come later). NOTE: the import package is deliberately `delivery`, not
`platform` (a top-level `platform` package would shadow the Python stdlib `platform` module) and
not bare `orchestrator` (collides with product packages).
"""
from __future__ import annotations

__version__ = "0.1.0"
