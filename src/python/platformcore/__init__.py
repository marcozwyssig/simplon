"""platformcore - the domain-agnostic shared core for the *ctl product family (netctl, infractl).

Consumed by each product via a sibling checkout on sys.path (dev-time; editable-install / published
artefacts come later). NOTE: the import package is deliberately `platformcore`, not `platform`, because
a top-level `platform` package would shadow the Python stdlib `platform` module.
"""
from __future__ import annotations

__version__ = "0.1.0"
