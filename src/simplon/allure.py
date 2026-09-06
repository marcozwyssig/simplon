"""Tombstone: this module now lives at `simplon.tasks.allure` (#37).

Nothing outside `simplon/tasks/` imported it: the only consumer is `simplon.tasks.testrun`, so the
allure report mechanics are the innards of one task body and now sit beside it. Its own head used to
claim two named products reused it; neither did, which is how the placement went unnoticed.

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
    return surface.moved_attr(__name__, "simplon.tasks.allure", name)
