"""Tombstone: this module now lives at `simplon.imagenames` (#37).

Two things were wrong at once. The name collided with `simplon.tasks.image`, the container-image task
body - the #31 review tripped over exactly that pair - and the two are unrelated: the task body does
not import this module and never did. What is here is two pure string derivations, the version tag and
the fully-qualified repo string, so `imagenames` says what it is and no longer reads like the task.

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
    return surface.moved_attr(__name__, "simplon.imagenames", name)
