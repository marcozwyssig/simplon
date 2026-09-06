"""Tombstone: this module now lives at `simplon.nexusproxy` (#37).

It collided with `simplon.tasks.nexus`, the `nexus` command body that calls it - the two were one
character of path apart and nothing at a call site said which was which. Both keep their jobs; only the
mechanism is renamed, because it is the half that says what it IS rather than which command it serves:
what lives there is the lifecycle of a Sonatype Nexus artefact PROXY - bring the container up, create
the proxy repositories, report honest state.

It still imports and every name still resolves - the attribute is fetched from the new module and a
`FutureWarning` says where it went. That is deliberate: a product on the old path gets a working run
with a message in it rather than a stack trace, and has until the next minor release to change the
line, at which point this file goes.
"""
from __future__ import annotations

from typing import Any

from simplon import surface


def __getattr__(name: str) -> Any:
    """Serve every name from the new home, announcing the move on use."""
    return surface.moved_attr(__name__, "simplon.nexusproxy", name)
