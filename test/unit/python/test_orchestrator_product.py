"""Runner tests for delivery.orchestrator.product: run_command (#896), the product-agnostic runner that
expands a command NAME through the #895 dependency plan (`Manifest.plan_for`), maps each planned leaf
through the product's step factory (`StepFactoryContext`) and dispatches the resulting Pipeline. Fake
step_factory (no real subprocess, no Textual) so the mapping, the stop_on_failure carry-through and the
rc propagation are tested in isolation. run_command calls `dispatch`; the tests either capture the
Pipeline before it runs or force the headless runner, so no TUI is launched. AAA throughout.
"""
from __future__ import annotations

import pytest

from delivery.orchestrator import product
from delivery.orchestrator.manifest import load as manifest_load
from delivery.orchestrator.steps import Outcome, Step, run_headless


def _factory(rc_by_cmd: dict[str, int] | None = None):
    """A fake step_factory: each command NAME becomes a Step whose action returns the injected rc (default
    0), so no subprocess runs. Records the order it was asked to build steps in."""
    rc_by_cmd = rc_by_cmd or {}
    built: list[str] = []

    def factory(cmd: str) -> Step:
        built.append(cmd)
        return Step(label=cmd, action=lambda cmd=cmd: Outcome(rc=rc_by_cmd.get(cmd, 0), output=""))

    return factory, built


# Manifests are loaded from YAML so the #895 load-time validation is on the path; `bringup` is an
# impl-less aggregate whose plan is (install, build, up, seed).

_DEPS_MANIFEST = """
groups:
  build:
    install: { impl: "demo.impls:install", help: "Install host prereqs." }
    build:   { impl: "demo.impls:build",   help: "Build the artefacts." }
    prep:    { help: "Install + build.", depends_on: [install, build] }
  deploy:
    up:      { impl: "demo.impls:up",   help: "Deploy up." }
    seed:    { impl: "demo.impls:seed", help: "Seed." }
    bringup: { help: "Full bring-up.", depends_on: [prep, up, seed] }
env_groups: [deploy]
"""


def test_run_command_builds_the_pipeline_from_the_dependency_plan(monkeypatch):
    # arrange: capture the dispatched pipeline instead of running it
    captured = {}
    monkeypatch.setattr(product, "dispatch", lambda p: captured.setdefault("pipeline", p) or 0)
    factory, built = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    mf = manifest_load(_DEPS_MANIFEST)

    # act
    product.run_command("bringup", mf, ctx)

    # assert: one step per PLANNED leaf, in dependency order; the aggregates are not steps
    assert built == ["install", "build", "up", "seed"]
    assert [s.label for s in captured["pipeline"].steps] == ["install", "build", "up", "seed"]
    assert captured["pipeline"].name == "bringup"


@pytest.mark.parametrize("stop_on_failure", [True, False])
def test_run_command_carries_the_commands_stop_on_failure_onto_the_pipeline(monkeypatch, stop_on_failure):
    # arrange: the aggregate declares its own stop_on_failure
    captured = {}
    monkeypatch.setattr(product, "dispatch", lambda p: captured.setdefault("pipeline", p) or 0)
    factory, _ = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    text = _DEPS_MANIFEST.replace("depends_on: [prep, up, seed]",
                                  f"depends_on: [prep, up, seed], stop_on_failure: {str(stop_on_failure).lower()}")
    mf = manifest_load(text)

    # act
    product.run_command("bringup", mf, ctx)

    # assert: the Pipeline respects the command's stop_on_failure verbatim
    assert captured["pipeline"].stop_on_failure is stop_on_failure


@pytest.mark.parametrize("declared, wrapped", [(True, True), (False, False)])
def test_run_command_holds_the_host_awake_for_a_plan_that_declares_it(monkeypatch, declared, wrapped):
    # arrange: the aggregate that replaced a hand-written multi-minute pipeline keeps that pipeline's
    # idle-sleep inhibitor (netctl#1238). There is no product code around a plan - the CLI callback is
    # kernel-synthesized - so if the runner does not wrap it, nothing does. Record whether the inhibitor
    # was HELD while the pipeline dispatched, not merely entered at some point.
    import contextlib

    held: list[bool] = []

    @contextlib.contextmanager
    def fake_keep_awake():
        held.append(True)
        try:
            yield
        finally:
            held.append(False)

    monkeypatch.setattr(product, "keep_awake", fake_keep_awake)
    monkeypatch.setattr(product, "dispatch", lambda p: (held.append("dispatch"), 0)[1])
    factory, _ = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    text = _DEPS_MANIFEST.replace("depends_on: [prep, up, seed]",
                                  f"depends_on: [prep, up, seed], keep_awake: {str(declared).lower()}")
    mf = manifest_load(text)

    # act
    product.run_command("bringup", mf, ctx)

    # assert: declared -> the dispatch happens INSIDE the with-block and the inhibitor is released after;
    # not declared -> nothing is spawned at all (a 3-second aggregate must not fork caffeinate)
    assert held == ([True, "dispatch", False] if wrapped else ["dispatch"])


def test_run_command_on_a_leaf_runs_just_that_leaf(monkeypatch):
    # arrange
    captured = {}
    monkeypatch.setattr(product, "dispatch", lambda p: captured.setdefault("pipeline", p) or 0)
    factory, built = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    mf = manifest_load(_DEPS_MANIFEST)

    # act
    product.run_command("seed", mf, ctx)

    # assert: a dep-less leaf plans as itself alone
    assert built == ["seed"]


def test_run_command_returns_zero_when_every_planned_step_passes(monkeypatch):
    # arrange: force the headless runner so real rc propagation is exercised (no TUI)
    monkeypatch.setattr(product, "dispatch", run_headless)
    factory, _ = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    mf = manifest_load(_DEPS_MANIFEST)

    # act
    rc = product.run_command("bringup", mf, ctx)

    # assert
    assert rc == 0


def test_run_command_returns_nonzero_when_a_planned_step_fails(monkeypatch):
    # arrange: a middle leaf fails; run headless so the pipeline's worst-rc verdict is real
    monkeypatch.setattr(product, "dispatch", run_headless)
    factory, _ = _factory({"build": 2})
    ctx = product.StepFactoryContext("demo", factory)
    mf = manifest_load(_DEPS_MANIFEST)

    # act
    rc = product.run_command("bringup", mf, ctx)

    # assert
    assert rc != 0


def test_run_command_disambiguates_an_ambiguous_root_via_the_group_keyword(monkeypatch):
    # arrange: `all` is owned by test AND deploy (the #519 shape)
    captured = {}
    monkeypatch.setattr(product, "dispatch", lambda p: captured.setdefault("pipeline", p) or 0)
    factory, built = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    text = """
groups:
  test:
    unit: { impl: "demo.impls:unit", help: "Unit gate." }
    all:  { help: "Every test stage.", depends_on: [unit] }
  deploy:
    up:  { impl: "demo.impls:up", help: "Deploy up." }
    all: { help: "Full bring-up.", depends_on: [up] }
env_groups: [deploy]
"""
    mf = manifest_load(text)

    # act / assert: the group keyword picks the owner's own plan; the bare name fails loudly
    product.run_command("all", mf, ctx, group="test")
    assert built == ["unit"]
    with pytest.raises(ValueError, match="no unambiguous command named 'all'"):
        product.run_command("all", mf, ctx)


def test_run_command_raises_a_clear_error_for_an_unknown_command():
    # arrange
    factory, _ = _factory()
    ctx = product.StepFactoryContext("demo", factory)
    mf = manifest_load(_DEPS_MANIFEST)

    # act / assert
    with pytest.raises(ValueError, match="no unambiguous command named 'nope'"):
        product.run_command("nope", mf, ctx)


def test_product_context_is_a_back_compat_alias_of_step_factory_context():
    # The class was renamed ProductContext -> StepFactoryContext (netctl#737) to stop colliding with
    # delivery.context.ProductContext; the old name stays as an alias so a not-yet-bumped consumer keeps
    # importing it until it migrates.
    # act / assert: same class, so `product.ProductContext(...)` still builds a usable step-factory context
    assert product.ProductContext is product.StepFactoryContext
    ctx = product.ProductContext("demo", lambda cmd: Step(label=cmd, action=lambda: Outcome(0, "")))
    assert ctx.product == "demo"
