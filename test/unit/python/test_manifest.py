"""Unit tests for the manifest-driven CLI assembly engine (delivery.orchestrator.manifest): the pure
YAML load + schema validation of the nested group -> command -> spec TREE (#729), the impl-reference
resolution, and the shared-taxonomy build - exercised on a SYNTHETIC manifest so the engine is validated
independently of any product's command set. No Typer, no product impls; AAA throughout.
"""
import json

import pytest

from delivery.orchestrator import manifest

_OK = """
product: demo
groups:
  code:
    fmt:  { impl: "demo.impls:fmt",  help: "Format the sources." }
    lint: { impl: "demo.impls:lint", help: "Lint the sources." }
  build:
    build: { impl: "demo.impls:build", help: "Build the artefacts." }
  deploy:
    up:   { impl: "demo.impls:up",   help: "Deploy up.", passthrough_args: true }
    down: { impl: "demo.impls:down", help: "Tear down." }
env_groups: [deploy]
"""


def test_load_reads_the_groups_tree_as_membership_and_specs():
    # arrange / act
    mf = manifest.load(_OK)

    # assert: `groups` is the membership projection (each group's ordered command names) ...
    assert mf.groups == {"code": ("fmt", "lint"), "build": ("build",), "deploy": ("up", "down")}
    assert mf.env_groups == frozenset({"deploy"})
    # ... and `commands` is the nested spec tree, resolved via spec_for(group, name)
    assert set(mf.commands) == {"code", "build", "deploy"}
    assert set(mf.commands["code"]) == {"fmt", "lint"}
    assert mf.spec_for("code", "fmt").impl == "demo.impls:fmt"
    assert mf.spec_for("code", "fmt").help == "Format the sources."


def test_load_reads_the_passthrough_args_flag_defaulting_to_false():
    # arrange / act
    mf = manifest.load(_OK)

    # assert: only the command that declared it is a passthrough command
    assert mf.spec_for("deploy", "up").passthrough_args is True
    assert mf.spec_for("code", "fmt").passthrough_args is False


def test_taxonomy_reuses_the_shared_env_gate_built_from_the_manifest():
    # arrange
    mf = manifest.load(_OK)

    # act
    tax = mf.taxonomy()

    # assert: the flat single-member group, the env requirement, and the verdicts come from the shared engine
    assert tax.is_flat_command_group("build") is True
    assert tax.is_flat_command_group("code") is False
    assert tax.group_requires_env("deploy") is True
    assert tax.env_verdict("fmt", env_explicit=True) == "reject-env"
    assert tax.env_verdict("up", env_explicit=False) == "gate-backend"
    assert tax.env_verdict("fmt", env_explicit=False) == "ok"


def test_load_rejects_a_manifest_with_no_groups():
    # arrange / act / assert: a manifest with no `groups` tree (unknown top-level keys are ignored)
    with pytest.raises(ValueError, match="no groups"):
        manifest.load("product: demo\n")


def test_load_rejects_an_env_group_that_is_not_a_declared_group():
    # arrange: env_groups names a group that does not exist
    text = ("groups:\n  code:\n    fmt: { impl: 'm:f', help: 'x' }\n"
            "env_groups: [deploy]\n")

    # act / assert
    with pytest.raises(ValueError, match="env_groups entry 'deploy'"):
        manifest.load(text)


# A name owned by two groups, each nesting its OWN spec - the #519 shape (netctl: `test all` runs every test
# stage, `deploy all` stays the full e2e bring-up). Nesting resolves the collision; no dotted keys.
_DUPLICATE_OK = """
groups:
  test:
    unit: { impl: "demo.impls:unit",     help: "Unit gate." }
    all:  { impl: "demo.impls:test_all", help: "Run every test stage." }
  deploy:
    up:  { impl: "demo.impls:up",         help: "Deploy up." }
    all: { impl: "demo.impls:deploy_all", help: "Full e2e bring-up." }
env_groups: [deploy]
"""


def test_load_resolves_a_name_owned_by_several_groups_by_nesting():
    # arrange / act
    mf = manifest.load(_DUPLICATE_OK)

    # assert: each group resolves ITS own spec for the shared name; unique names resolve too
    assert mf.spec_for("test", "all").impl == "demo.impls:test_all"
    assert mf.spec_for("deploy", "all").impl == "demo.impls:deploy_all"
    assert mf.spec_for("test", "unit").impl == "demo.impls:unit"


def test_spec_by_name_resolves_an_unambiguous_command_but_not_an_ambiguous_one():
    # arrange: `unit` is owned by exactly one group; `all` is owned by two
    mf = manifest.load(_DUPLICATE_OK)

    # act / assert: the bare-name flat view returns the sole owner's spec, and None for the ambiguous name
    assert mf.spec_by_name("unit").impl == "demo.impls:unit"
    assert mf.spec_by_name("all") is None
    assert mf.spec_by_name("nonesuch") is None


def test_load_rejects_a_group_member_with_an_empty_spec():
    # arrange: `lint` is a member of code but carries no impl/help (an empty spec body)
    text = ("groups:\n  code:\n    fmt:  { impl: 'm:f', help: 'x' }\n    lint: {}\n")

    # act / assert: an empty spec fails loudly, naming the owning group + command
    with pytest.raises(ValueError, match="command 'code.lint': missing impl"):
        manifest.load(text)


def test_load_rejects_a_command_with_a_missing_help():
    # arrange: fmt has an impl but no help
    text = "groups:\n  code:\n    fmt: { impl: 'm:f' }\n"

    # act / assert
    with pytest.raises(ValueError, match="missing help"):
        manifest.load(text)


@pytest.mark.parametrize("bad_impl", ["nocolon", ":func", "module:", "a:b:c"])
def test_load_rejects_a_malformed_impl_reference(bad_impl):
    # arrange: an impl that is not a clean "module:function"
    text = f"groups:\n  code:\n    fmt: {{ impl: '{bad_impl}', help: 'x' }}\n"

    # act / assert
    with pytest.raises(ValueError, match="module:function"):
        manifest.load(text)


def test_resolve_impl_imports_the_module_and_returns_the_function():
    # arrange: an impl reference to a real importable function (stdlib, so the test needs no product code)
    spec = manifest.CommandSpec(impl="json:dumps", help="x")

    # act
    fn = manifest.resolve_impl(spec)

    # assert: it is exactly json.dumps and is callable
    assert fn is json.dumps
    assert fn([1, 2]) == "[1, 2]"


def test_resolve_impl_raises_a_clear_error_on_a_missing_module():
    # arrange
    spec = manifest.CommandSpec(impl="no_such_module_xyz:foo", help="x")

    # act / assert
    with pytest.raises(ValueError, match="cannot import module"):
        manifest.resolve_impl(spec)


def test_resolve_impl_raises_a_clear_error_on_a_missing_function():
    # arrange
    spec = manifest.CommandSpec(impl="json:no_such_function_xyz", help="x")

    # act / assert
    with pytest.raises(ValueError, match="has no attribute"):
        manifest.resolve_impl(spec)


# --- composites (#456): named, ordered command pipelines declared in the manifest -------------------

_COMPOSITES = """
product: demo
groups:
  build:
    install: { impl: "demo.impls:install", help: "Install host prereqs." }
    build:   { impl: "demo.impls:build",   help: "Build the artefacts." }
  deploy:
    up:   { impl: "demo.impls:up",   help: "Deploy up." }
    seed: { impl: "demo.impls:seed", help: "Seed." }
env_groups: [deploy]
composites:
  bringup: { steps: [install, build, up, seed] }
  strict:  { steps: [install, build], stop_on_failure: true }
"""


def test_load_reads_a_composites_block_with_steps_and_stop_on_failure():
    # arrange / act
    mf = manifest.load(_COMPOSITES)

    # assert: each composite carries its ordered steps; stop_on_failure defaults to False
    assert mf.composites["bringup"].steps == ("install", "build", "up", "seed")
    assert mf.composites["bringup"].stop_on_failure is False
    assert mf.composites["strict"].steps == ("install", "build")
    assert mf.composites["strict"].stop_on_failure is True


def test_load_defaults_composites_to_empty_when_absent():
    # arrange: a manifest that declares no composites (backward compatible)
    mf = manifest.load(_OK)

    # act / assert
    assert mf.composites == {}


def test_load_rejects_a_composite_step_naming_an_unknown_command():
    # arrange: the composite references a command that is not in the manifest
    text = _COMPOSITES.replace("steps: [install, build, up, seed]", "steps: [install, nope]")

    # act / assert: the error names the composite and the bad step
    with pytest.raises(ValueError, match="composite 'bringup': step 'nope'"):
        manifest.load(text)


def test_load_rejects_a_composite_with_no_steps():
    # arrange: an empty steps list
    text = _COMPOSITES.replace("steps: [install, build], stop_on_failure: true", "steps: []")

    # act / assert
    with pytest.raises(ValueError, match="composite 'strict': needs a non-empty 'steps' list"):
        manifest.load(text)
