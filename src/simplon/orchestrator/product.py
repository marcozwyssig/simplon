"""Running a manifest-declared command as its dependency plan (#895/#896): the product-agnostic runner
that turns a command NAME into a live Pipeline. `run_command` expands the name through
`Manifest.plan_tree_for` (transitive, deduped, each unique command once, in dependency order), maps each
planned leaf through the product's own step factory - typically a streaming `./<product>.sh <cmd>`
subprocess - and dispatches the resulting Pipeline through the shared runner, optionally holding the host
awake for the duration (the `keep_awake` spec flag, netctl#1238). Multi-command pipelines
(bringup, test.all, build, ...) are thereby DATA in the product's manifest (impl-less aggregates carrying
`depends_on`) instead of hand-written product Python, so a second product (infractl) gets the same
runner and its own aggregates for free.

This module is PURE of any product import: the ONLY product-specific thing is the injected `step_factory`
on the `StepFactoryContext`. That name is deliberately DISTINCT from `delivery.context.ProductContext`
(which carries a product's identity/root/manifest path for the CLI engine): the two used to share the name
`ProductContext`, disambiguated only by a docstring, which was a footgun (netctl#737). This seam is the
step-runner one - a command name -> Step factory - so it is named for what it is.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from delivery.awake import keep_awake
from delivery.orchestrator.manifest import Manifest
from delivery.orchestrator.steps import Pipeline, Step, argv_step, dispatch


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

    @classmethod
    def for_shim(cls, product: str, script: str | Path, manifest: Manifest) -> "StepFactoryContext":
        """The context for the shape every shim-backed product has: a command NAME becomes a live-streamed
        `<script> <name>` step, STAMPED with that command's exact-command identity - the dotted
        `group.command` path the manifest gives it, or the bare name when several groups own it (#519) and
        the manifest cannot decide. Both spellings are what `Pipeline.usable_tree` accepts.

        The stamp is not decoration, which is why this factory lives HERE rather than being rewritten in
        each product: an unstamped step names its own argv, the kernel cannot verify the leaf-to-step
        pairing, and it drops the whole plan tree - taking every subtree's `stop_on_failure` with it, so a
        gate chain runs on after a failure (#42). Resolving the identity is pure kernel knowledge, so a
        product function doing it would be a shim rather than a seam.

        It stays an INDEPENDENT derivation, deliberately: the identity comes from the manifest by name, not
        from the leaf `run_command` is currently mapping. Handing each step the leaf's own path would make
        the pairing check agree with itself by construction and verify nothing - which is exactly why
        `run_command` does not stamp the steps it receives.

        `manifest` is the parsed manifest the product assembles its CLI from; a product that has none at
        hand reads it back through `delivery.context.current().manifest()`.
        """
        argv0 = str(script)

        def factory(cmd: str) -> Step:
            return argv_step(cmd, [argv0, cmd], command=manifest.path_by_name(cmd) or cmd)

        return cls(product=product, step_factory=factory)


# Back-compat alias for the pre-rename name (netctl#737). netctl's orchestrator still imports
# `delivery.orchestrator.product.ProductContext`; it keeps working until that consumer bumps its submodule
# pointer and switches to `StepFactoryContext`, after which this alias can be dropped. New code uses the
# explicit name.
ProductContext = StepFactoryContext


def run_command(name: str, manifest: Manifest, ctx: StepFactoryContext, *, group: str | None = None) -> int:
    """Run the command `name` as its dependency-resolved plan (#895/#896) and return the pipeline's exit
    code (0 iff every planned step passed). `manifest.plan_tree_for` is the whole of transitive + dedup +
    once + order; each planned leaf is mapped through `ctx.step_factory` into a Step (typically a streaming
    `./<product>.sh <leaf>` subprocess), wrapped in a Pipeline and dispatched through the shared
    runner (TUI when available, else headless).

    `stop_on_failure` rides along on the TREE, where it is declared: every node carries its own spec, and
    `delivery.orchestrator.steps.abort_after` scopes a failure to the OUTERMOST ancestor whose flag is true
    (netctl#1317). The Pipeline's own single flag is still set from the ROOT spec, as the fallback for the
    tree-less / degraded shape - with a usable tree it is the root NODE's flag that is read, and the two
    are the same value by construction.

    The plan is resolved ONCE, as a tree (`Manifest.plan_tree_for`, netctl#1275); the steps are built from
    its leaves, whose names in DFS order are identical to what `plan_for` returns, which the manifest parity
    test pins. Both the tree and the invoked command's dotted path ride along on the Pipeline, so a renderer
    shows the aggregate structure the plan really had instead of a flat list of leaves, and can never show a
    structure whose leaves are not the steps that ran. The tree is NOT decoration: since netctl#1317 it also
    carries the per-node stop flags a failure is scoped by, so this function is the one production builder
    of a Pipeline that decides what does not run. Building the steps and the tree from one traversal is
    therefore load-bearing twice over, and a step factory must stamp each Step with its leaf's exact-command
    identity - `Pipeline.usable_tree` cannot verify a step that names nothing and drops the whole tree,
    loudly, when one appears. `StepFactoryContext.for_shim` is the kernel's factory for the usual
    `./<product>.sh <cmd>` shape and stamps it; a product writing its own owes the same stamp (#42).

    A command that declares `keep_awake` (netctl#1238) has its WHOLE plan wrapped in
    `delivery.awake.keep_awake`, so a multi-minute aggregate inhibits host idle-sleep exactly as the
    hand-written pipeline it replaced did. The wrap belongs here because an aggregate has no product code
    around it - its CLI callback is kernel-synthesized - and because one inhibitor spanning the plan also
    covers the GAPS between steps, which per-leaf arming does not. Best-effort by keep_awake's own
    contract: a host with no inhibitor warns and runs anyway.

    `group` disambiguates a root name owned by several groups (the #519 `test all` shape); it flows
    through to `plan_tree_for`. Fails loudly with a clear ValueError when `name` does not resolve."""
    spec = manifest.root_spec_for(name, group=group)
    tree = manifest.plan_tree_for(name, group=group)
    steps = [ctx.step_factory(leaf.name) for leaf in tree.leaves()]
    pipeline = Pipeline(name=name, steps=steps, stop_on_failure=spec.stop_on_failure,
                        tree=tree, root_path=tree.path)
    # Ask the pairing verdict HERE, before anything runs. It is decided by the two lines above and cannot
    # change afterwards, but its consumers ask lazily - `abort_after` at the first FAILURE, `build_rows`
    # after the last step - so the warning for a rejected tree used to surface halfway down a run's own
    # output, or under the TUI, where it reads as one line among many. That is how a voided manifest
    # declaration went unnoticed until a `lint -> check-contract -> test` chain kept going after a failure
    # (#42). The verdict is computed once and remembered, so asking early changes nothing but WHERE the
    # warning lands: above the run, where it is still actionable.
    pipeline.usable_tree()
    with (keep_awake() if spec.keep_awake else contextlib.nullcontext()):
        return dispatch(pipeline)
