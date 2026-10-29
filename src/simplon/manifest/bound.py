"""A body reads the names bound to an input port that has no `param` (si#553).

A port with a `param` hands its one artifact name to that body parameter. A LIST port - `release:github-attach`'s
`files` - has none: the manifest binds several artifacts to it, and until si#553 no body could learn which. The
wrapper both dispatch paths put around a body (`cli._bound`, the generated module) therefore sets the names
here for the duration of the call, and the body asks `names(port)`, as a release asks `results.tested()` for
the records its evidence ran.

Two values for two answers, because "not called as a command" and "a command that bound nothing to this
port" send the caller to different places: `names` is None outside `within`, and `()` for a port the running
command leaves unbound. Test-result ports are not read here: those are the evidence guard's
(`results.evidence_of`), and a body that wants their subjects asks `results.tested()`.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar

#: port name -> the artifact names bound to it, for the body being run; None outside a command.
_bound: ContextVar["Mapping[str, tuple[str, ...]] | None"] = ContextVar("bound", default=None)


def of(spec: object) -> dict[str, tuple[str, ...]]:
    """The names `spec` binds to each of its input ports that have no `param` and take no test result.
    A port the command binds to nothing is absent, so an empty answer means there is nothing to wrap."""
    consumes = getattr(spec, "consumes", None) or {}
    return {port.name: tuple(consumes[port.name])
            for port in getattr(spec, "ports", ()) or ()
            if port.direction == "input" and not port.param and port.accepts != "test-result"
            and consumes.get(port.name)}


def within(names: Mapping[str, tuple[str, ...]], body: Callable[[], int]) -> int:
    """`body()`'s rc, with `names` readable through `names()` while it runs and reset after, even on a raise."""
    token = _bound.set(names)
    try:
        return body()
    finally:
        _bound.reset(token)


def names(port: str) -> "tuple[str, ...] | None":
    """The artifact names bound to `port` of the running command, `()` when it binds none, or None when
    nothing is running as a command (the body was called directly)."""
    current = _bound.get()
    return None if current is None else tuple(current.get(port, ()))
