"""Runner tests for delivery.orchestrator.product.run_composite (#456): the product-agnostic composite
runner that maps a manifest-declared composite's step NAMES through the product's step factory and
dispatches the resulting Pipeline. Fake step_factory (no real subprocess, no Textual) so the mapping, the
stop_on_failure carry-through and the rc propagation are tested in isolation. run_composite calls
`dispatch`; the tests either capture the Pipeline before it runs or force the headless runner, so no TUI is
launched. AAA throughout.
"""
from __future__ import annotations

import pytest

from delivery.orchestrator import product
from delivery.orchestrator.manifest import CompositeSpec, Manifest
from delivery.orchestrator.steps import Outcome, Step, run_headless


def _manifest(**composites: CompositeSpec) -> Manifest:
    """A minimal Manifest carrying only the composites under test (the runner reads nothing else)."""
    return Manifest(groups={}, env_groups=frozenset(), commands={}, composites=composites)


def _factory(rc_by_cmd: dict[str, int] | None = None):
    """A fake step_factory: each command NAME becomes a Step whose action returns the injected rc (default
    0), so no subprocess runs. Records the order it was asked to build steps in."""
    rc_by_cmd = rc_by_cmd or {}
    built: list[str] = []

    def factory(cmd: str) -> Step:
        built.append(cmd)
        return Step(label=cmd, action=lambda cmd=cmd: Outcome(rc=rc_by_cmd.get(cmd, 0), output=""))

    return factory, built


def test_run_composite_maps_each_step_through_the_factory_in_order(monkeypatch):
    # arrange: capture the dispatched pipeline instead of running it
    captured = {}
    monkeypatch.setattr(product, "dispatch", lambda p: captured.setdefault("pipeline", p) or 0)
    factory, built = _factory()
    ctx = product.ProductContext("demo", factory)
    mf = _manifest(bringup=CompositeSpec(steps=("install", "build", "up", "seed")))

    # act
    product.run_composite("bringup", mf, ctx)

    # assert: one step per command, in declared order, each built via the factory
    assert built == ["install", "build", "up", "seed"]
    assert [s.label for s in captured["pipeline"].steps] == ["install", "build", "up", "seed"]
    assert captured["pipeline"].name == "bringup"


@pytest.mark.parametrize("stop_on_failure", [True, False])
def test_run_composite_carries_the_composite_stop_on_failure_onto_the_pipeline(monkeypatch, stop_on_failure):
    # arrange
    captured = {}
    monkeypatch.setattr(product, "dispatch", lambda p: captured.setdefault("pipeline", p) or 0)
    factory, _ = _factory()
    ctx = product.ProductContext("demo", factory)
    mf = _manifest(c=CompositeSpec(steps=("install", "build"), stop_on_failure=stop_on_failure))

    # act
    product.run_composite("c", mf, ctx)

    # assert: the Pipeline respects the composite's stop_on_failure verbatim
    assert captured["pipeline"].stop_on_failure is stop_on_failure


def test_run_composite_returns_zero_when_every_step_passes(monkeypatch):
    # arrange: force the headless runner so real rc propagation is exercised (no TUI)
    monkeypatch.setattr(product, "dispatch", run_headless)
    factory, _ = _factory()
    ctx = product.ProductContext("demo", factory)
    mf = _manifest(c=CompositeSpec(steps=("install", "build", "up")))

    # act
    rc = product.run_composite("c", mf, ctx)

    # assert
    assert rc == 0


def test_run_composite_returns_nonzero_when_a_step_fails(monkeypatch):
    # arrange: the middle step fails; run headless so the pipeline's worst-rc verdict is real
    monkeypatch.setattr(product, "dispatch", run_headless)
    factory, _ = _factory({"build": 2})
    ctx = product.ProductContext("demo", factory)
    mf = _manifest(c=CompositeSpec(steps=("install", "build", "up")))

    # act
    rc = product.run_composite("c", mf, ctx)

    # assert: a failing fake step makes the overall verdict nonzero
    assert rc != 0


def test_run_composite_raises_a_clear_error_for_an_unknown_composite():
    # arrange
    factory, _ = _factory()
    ctx = product.ProductContext("demo", factory)
    mf = _manifest(bringup=CompositeSpec(steps=("install",)))

    # act / assert
    with pytest.raises(ValueError, match="no composite named 'nope'"):
        product.run_composite("nope", mf, ctx)
