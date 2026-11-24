"""The `merge:` section (si#874): `merge: auto` has the kernel derive the auto-merge workflow.

    merge: auto

One value, a fixed policy with no parameters; the label and the merge method become parameters only when a
second product needs another one. `declared` is the one reading, called from the loader, so a bad value is
refused before any command or workflow derivation meets it. An absent section is `False`, the normal case; a
bare `merge:` (null) is refused on purpose, since a half-typed intent is not "off".
"""
from __future__ import annotations

from collections.abc import Mapping

_VALUE = "auto"


def declared(document: Mapping[str, object]) -> bool:
    """True for `merge: auto`, False when the section is absent; any other value is refused."""
    if "merge" not in document:
        return False
    raw = document.get("merge")
    if raw != _VALUE or not isinstance(raw, str):
        raise ValueError(f"`merge:` must be `{_VALUE}` (the only value there is: a fixed policy, no parameters), "
                         f"found {raw!r}")
    return True
