"""What the kernel needs to know about a run and cannot ask for itself, registered from above (si#391).

The step log and the run transcript need four facts: where the logs go, the environment, the lab instance
and a way to draw the run. Each of those belongs to a layer above the kernel. The log directory comes from
the product's manifest (`outputs`), the environment from what `cli.main` selected (`context`), the instance
from the manifest's `instance:` section (`labinstance`), and the interactive drawing from the Textual UI.
The kernel used to import all four modules, so the lowest layer depended on every layer above it.

Now the layer that starts the run says what it knows. `cli.main` (layer 4) registers a `RunHost` before it
hands control to Typer, and every run, a product's or simplon's own, starts there. The kernel reads it.

NOTHING REGISTERED IS AN ANSWER, never a guess. A unit test or a scaffolder run imports the kernel without a
host. Then there are no logs (`log_directory` answered None for an unregistered product before si#391
too), the header says `not set` and `not declared`, and `steps.dispatch` says out loud that nothing drew
the run, instead of quietly running it headless.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:   # type-only: steps imports steplog, which imports this module
    from simplon.orchestrator.steps import Pipeline


@dataclass(frozen=True)
class RunHost:
    """The facts a run's layers above the kernel supply. `render` draws a pipeline interactively and
    returns its rc; None means this host draws nothing, so the run is headless and says why."""

    log_directory: Callable[[], Path | None]
    environment: Callable[[], str]
    instance: Callable[[], str]
    render: Callable[["Pipeline"], int] | None = None


_current: RunHost | None = None


def register(host: RunHost | None) -> RunHost | None:
    """Register the process' run host, or clear it with None; returns what was registered."""
    global _current
    _current = host
    return host


def current() -> RunHost | None:
    """The registered run host, or None when nothing registered one."""
    return _current
