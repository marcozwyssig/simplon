"""Running a manifest-declared composite (#456): the product-agnostic runner that turns a `composites:`
entry into a live Pipeline. A composite is a named, ordered list of command NAMES (bringup, test.all, ...);
this module maps each name through the product's own step factory - typically a streaming `./<product>.sh
<cmd>` subprocess - and dispatches the resulting Pipeline through the shared runner. The composites become
DATA in the product's manifest instead of hand-written product Python, so a second product (infractl) gets
the same runner and its own composites for free.

This module is PURE of any product import: the ONLY product-specific thing is the injected `step_factory`
on the `StepFactoryContext`. That name is deliberately DISTINCT from `delivery.context.ProductContext`
(which carries a product's identity/root/manifest path for the CLI engine): the two used to share the name
`ProductContext`, disambiguated only by a docstring, which was a footgun (netctl#737). This seam is the
composite-runner one - a command name -> Step factory - so it is named for what it is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from delivery.orchestrator.manifest import Manifest
from delivery.orchestrator.steps import Pipeline, Step, dispatch


@dataclass(frozen=True)
class StepFactoryContext:
    """What `run_composite` needs from a product: its name and a factory that, given a command NAME, returns
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


def run_composite(name: str, manifest: Manifest, ctx: StepFactoryContext) -> int:
    """Run the composite `name` declared in `manifest` and return the pipeline's exit code (0 iff every step
    passed). Each step command is mapped through `ctx.step_factory` into a Step, wrapped in a Pipeline that
    carries the composite's `stop_on_failure`, and dispatched through the shared runner (TUI when available,
    else headless). Fails loudly with a clear ValueError when no such composite is declared."""
    try:
        spec = manifest.composites[name]
    except KeyError:
        raise ValueError(
            f"no composite named '{name}' in the manifest (declared: {sorted(manifest.composites)})"
        ) from None
    steps = [ctx.step_factory(cmd) for cmd in spec.steps]
    pipeline = Pipeline(name=name, steps=steps, stop_on_failure=spec.stop_on_failure)
    return dispatch(pipeline)
