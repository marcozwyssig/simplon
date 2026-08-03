"""Running a manifest-declared command as its dependency plan (#895/#896): the product-agnostic runner
that turns a command NAME into a live Pipeline. `run_command` expands the name through
`Manifest.plan_for` (transitive, deduped, each unique command once, in dependency order), maps each
planned leaf through the product's own step factory - typically a streaming `./<product>.sh <cmd>`
subprocess - and dispatches the resulting Pipeline through the shared runner. Multi-command pipelines
(bringup, test.all, ...) are thereby DATA in the product's manifest (impl-less aggregates carrying
`depends_on`) instead of hand-written product Python, so a second product (infractl) gets the same
runner and its own aggregates for free.

This module is PURE of any product import: the ONLY product-specific thing is the injected `step_factory`
on the `StepFactoryContext`. That name is deliberately DISTINCT from `delivery.context.ProductContext`
(which carries a product's identity/root/manifest path for the CLI engine): the two used to share the name
`ProductContext`, disambiguated only by a docstring, which was a footgun (netctl#737). This seam is the
step-runner one - a command name -> Step factory - so it is named for what it is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from delivery.orchestrator.manifest import Manifest
from delivery.orchestrator.steps import Pipeline, Step, dispatch


@dataclass(frozen=True)
class StepFactoryContext:
    """What `run_command` needs from a product: its name and a factory that, given a command NAME, returns
    the Step that runs it (typically a streaming `./<product>.sh <cmd>` subprocess step). Immutable; the
    product builds it once and passes it in, so the runner never imports the product.

    Named `StepFactoryContext` (not `ProductContext`) so it never collides with `delivery.context`'s
    identity `ProductContext` (netctl#737): the two live in different modules for different jobs, and a
    shared name disambiguated only by a docstring was a footgun."""

    product: str
    step_factory: Callable[[str], Step]


# Back-compat alias for the pre-rename name (netctl#737). netctl's orchestrator still imports
# `delivery.orchestrator.product.ProductContext`; it keeps working until that consumer bumps its submodule
# pointer and switches to `StepFactoryContext`, after which this alias can be dropped. New code uses the
# explicit name.
ProductContext = StepFactoryContext


def run_command(name: str, manifest: Manifest, ctx: StepFactoryContext, *, group: str | None = None) -> int:
    """Run the command `name` as its dependency-resolved plan (#895/#896) and return the pipeline's exit
    code (0 iff every planned step passed). `manifest.plan_for` is the whole of transitive + dedup + once
    + order; each planned leaf is mapped through `ctx.step_factory` into a Step (typically a streaming
    `./<product>.sh <leaf>` subprocess), wrapped in a Pipeline carrying the command's own
    `stop_on_failure`, and dispatched through the shared runner (TUI when available, else headless).

    `group` disambiguates a root name owned by several groups (the #519 `test all` shape); it flows
    through to `plan_for`. Fails loudly with a clear ValueError when `name` does not resolve."""
    spec = (manifest.commands.get(group, {}).get(name) if group is not None
            else manifest.spec_by_name(name))
    if spec is None:
        raise ValueError(f"no unambiguous command named '{name}' in the manifest")
    plan = manifest.plan_for(name, group=group)
    steps = [ctx.step_factory(cmd) for cmd in plan]
    pipeline = Pipeline(name=name, steps=steps, stop_on_failure=spec.stop_on_failure)
    return dispatch(pipeline)
