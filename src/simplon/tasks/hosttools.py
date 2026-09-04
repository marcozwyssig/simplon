"""`support install` - the host tooling the kernel itself cannot work without.

WHY A COMMAND WHEN THE GATES SELF-PROVISION. simplon.oras installs oras the moment a package operation
needs one, so a build never stops for it. That is the right behaviour mid-run and the wrong thing to
rely on when someone is SETTING UP a machine: an install that happens as a side effect of a build is an
install nobody chose, at the least convenient moment, over a network that may be the reason they are
building offline in the first place. This command is the same work, done deliberately and up front.

It provisions TOOLS, not credentials. A gh token without the package scopes fails a publish just as
hard as a missing oras, and the fix is `support git auth-scopes` - a different command, because one of
them touches a machine and the other opens a browser and asks a human to authorise something.
"""
from __future__ import annotations

from simplon import log, oras

# Every gate this command drives, in the order a fresh machine wants them. One entry today; the point
# of the list is that the next tool is a row rather than a rewrite. The gate is wrapped in a lambda
# rather than referenced directly, so the attribute is resolved when the command RUNS - a table of bound
# functions is a table a test cannot substitute and an operator cannot see through.
_GATES = (("oras", lambda: oras.ensure_oras(), oras.OrasError),)


def install() -> int:
    """Provision the host tooling the delivery kernel needs (today: oras); idempotent.

    Every gate is attempted even when an earlier one failed - a setup command that stops at the first
    problem hides the second one until the next run, and someone provisioning a machine wants the whole
    list now.
    """
    failed = []
    for name, gate, failure_type in _GATES:
        try:
            gate()
            log.ok(f"{name} is available")
        except failure_type as failure:
            log.warn(f"{name}: {failure}")
            failed.append(name)
    return 1 if failed else 0
