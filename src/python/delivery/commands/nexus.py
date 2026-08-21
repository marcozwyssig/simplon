"""The `nexus` group's Typer callback (netctl#1405): the manifest points its `impl:` straight at this.

Same shape as `delivery.commands.vcs`: the MECHANISM lives in `delivery.nexus`, and this module exists
because a manifest-resolved impl must be a real callable Typer introspects for its `Argument`/`Option`
signatures - a bare `nexus_cmd = delivery.nexus.dispatch` alias would silently drop the member argument.

The product's Nexus DATA (container, compose file, repository script, proxy repositories, the one
client-side base-URL variable) is read from its manifest through `delivery.context.current()`, never from a
product import, so nothing here knows which product it is serving.
"""
from __future__ import annotations

from typing import Optional

import typer

from delivery import nexus


def nexus_cmd(
    member: Optional[str] = typer.Argument(None, metavar="[up|down|status|repos|cleanup]",
                                           help="the group member to run; omit to list them"),
) -> None:
    """Drive the LAN Sonatype Nexus artefact proxy (netctl#948): `up` / `down` start and stop the
    long-lived service from the compose file the manifest names, `status` reports container state AND
    whether the EULA is accepted and anonymous read enabled (a GREEN container that answers 403 is the
    failure mode people hit), `repos` creates the proxy repositories this product needs, `cleanup` sets the
    Nexus cleanup policies that keep the blob-store volume from growing unbounded (netctl#994). A bare
    call lists the members - pure group logic, no default action.

    `status` asks its reachability question from BOTH vantage points and reports them separately
    (netctl#996): the operator's shell and a build container disagree on a VM-hosted daemon, and reporting
    only the shell's answer made the command claim a dead proxy while every build resolved through it.

    A MEMBER ARGUMENT rather than a manifest sub-group, deliberately: `up`, `down` and `status` are
    typically already owned by a product's deploy/monitor groups, and a second owner would make those names
    AMBIGUOUS in the shared taxonomy - which silently deletes the hidden flat aliases that docs, CI
    workflows and runbooks use. The addressing (`<cli> support nexus <member>`, flat-aliased
    `<cli> nexus <member>`, bare lists) is byte-for-byte the group UX; only the registration differs.

    Standalone by design: `nexus` belongs in NO composite. A build must not hard-depend on the proxy, the
    service is long-lived rather than per-build, and the EULA is an operator action no pipeline may click
    through. See delivery/nexus.py."""
    raise typer.Exit(nexus.dispatch(member))
