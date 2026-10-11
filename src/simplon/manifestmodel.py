"""The manifest as a firn M1 model (si#346, spec D.2): a validated manifest in, `.firn` text out.
(Task 5 completes this module; until then it holds only the name mapping.)
"""
from __future__ import annotations

import re

_NOT_NAME = re.compile(r"[^A-Za-z0-9_]")


class ModelExportError(ValueError):
    """A manifest the bridge cannot write as a model without losing something."""


def mangle(name: str) -> str:
    """`name` as a firn name (firn docs/03 §2; firn#962 will allow `-`): every character outside
    [A-Za-z0-9_] becomes `_`, and a leading digit gets `_`."""
    out = _NOT_NAME.sub("_", name)
    return f"_{out}" if out[:1].isdigit() else out
