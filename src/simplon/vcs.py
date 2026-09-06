"""Tombstone: this module now lives at `simplon.tasks.gitops` (#37).

Nothing outside `simplon/tasks/` imported it - `simplon.tasks.release` and `simplon.tasks.vcs` were
the only two - so the kernel's `git -C <ROOT>` seam belongs with the bodies that use it. It also
collided with `simplon.tasks.vcs`, the command body, which is now the only `vcs` in the package.

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
    return surface.moved_attr(__name__, "simplon.tasks.gitops", name)
