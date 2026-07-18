"""Running a manifest-declared composite (#456): the product-agnostic runner that turns a `composites:`
entry into a live Pipeline. A composite is a named, ordered list of command NAMES (bringup, test.all, ...);
this module maps each name through the product's own step factory - typically a streaming `./<product>.sh
<cmd>` subprocess - and dispatches the resulting Pipeline through the shared runner. The composites become
DATA in the product's manifest instead of hand-written product Python, so a second product (infractl) gets
the same runner and its own composites for free.

This module is PURE of any product import: the ONLY product-specific thing is the injected `step_factory`
on the `ProductContext`. (Note: this `ProductContext` is the composite-runner seam - a command name -> Step
factory - and is deliberately distinct from `delivery.context.ProductContext`, which carries a product's
identity/root/manifest path for the CLI engine.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from delivery.orchestrator.manifest import Manifest
from delivery.orchestrator.steps import Pipeline, Step, dispatch


@dataclass(frozen=True)
class ProductContext:
    """What `run_composite` needs from a product: its name and a factory that, given a command NAME, returns
    the Step that runs it (typically a streaming `./<product>.sh <cmd>` subprocess step). Immutable; the
    product builds it once and passes it in, so the runner never imports the product."""

    product: str
    step_factory: Callable[[str], Step]


def run_composite(name: str, manifest: Manifest, ctx: ProductContext) -> int:
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
