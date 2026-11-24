"""The `sources:` section (si#873): the git submodules a product's jobs check out beside the product.

    sources:
      - submodule: lib/platform          # a path in `.gitmodules`, relative to the checkout
        secret: PLATFORM_REPO_TOKEN      # optional: the variable that holds a token for a private clone

`declared` is the one reading, called from the loader, so a bad section is refused before any command runs.
What a run does with an entry (`support sources`) and what a workflow job does with it are read off the tuple
this returns and are not decided here. A section that is absent is `()`, the normal case: a product with no
submodule declares nothing.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import NamedTuple

_KEYS = ("submodule", "secret")
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Source(NamedTuple):
    """One submodule, and the name of the variable that carries its token ("" for a public one)."""

    submodule: str
    secret: str = ""


def declared(document: Mapping[str, object]) -> tuple[Source, ...]:
    """Each `sources:` entry, in declared order, or `()` when the section is absent."""
    raw = document.get("sources")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"`sources:` must be a list of {{submodule, secret}} entries, found {type(raw).__name__}")
    found: list[Source] = []
    for index, entry in enumerate(raw):
        where = f"'sources[{index}]'"
        if not isinstance(entry, Mapping):
            raise ValueError(f"{where} is not a mapping - a source declares `submodule:` and optionally `secret:`")
        for key in entry:
            if key not in _KEYS:
                raise ValueError(f"{where} declares unknown key '{key}'; the keys are: {', '.join(_KEYS)}")
        if "submodule" not in entry:
            raise ValueError(f"{where} declares no `submodule:`, the path of the submodule to check out")
        path = entry.get("submodule")
        if not isinstance(path, str) or not path.strip() or path.startswith("/"):
            raise ValueError(f"{where}: `submodule:` must be a non-empty relative path, found {path!r}")
        if ".." in path.split("/"):
            raise ValueError(f"{where}: `submodule: {path}` must not contain '..'; "
                             f"a submodule is a path inside the checkout")
        secret = entry.get("secret", "")
        if not isinstance(secret, str) or (secret and not _VARIABLE.fullmatch(secret)):
            raise ValueError(f"{where}: `secret:` must be a variable name ([A-Za-z_][A-Za-z0-9_]*), "
                             f"found {secret!r}")
        if any(source.submodule == path for source in found):
            raise ValueError(f"{where} names the submodule '{path}' twice")
        found.append(Source(path, secret))
    return tuple(found)
