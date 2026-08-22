"""Unit tests for the manifest-driven CLI assembly engine (delivery.orchestrator.manifest): the pure
YAML load + schema validation of the nested group -> command -> spec TREE (#729), the impl-reference
resolution, and the shared-taxonomy build - exercised on a SYNTHETIC manifest so the engine is validated
independently of any product's command set. No Typer, no product impls; AAA throughout.
"""
import json
import os
import pathlib
import subprocess
import sys

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


def test_path_by_name_returns_the_dotted_path_for_a_unique_owner_only():
    # arrange: `unit` is owned by exactly one group; `all` is owned by two
    mf = manifest.load(_DUPLICATE_OK)

    # act / assert: the sole owner yields the dotted group.command path; ambiguous and unknown yield None
    assert mf.path_by_name("unit") == "test.unit"
    assert mf.path_by_name("all") is None
    assert mf.path_by_name("nonesuch") is None


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


# --- removed composites (#898): a leftover `composites:` key fails loudly ---------------------------

def test_load_rejects_a_leftover_composites_key_loudly():
    # arrange: a manifest still carrying the removed `composites:` section
    text = _OK + "composites:\n  bringup: { steps: [fmt, lint] }\n"

    # act / assert: it is NOT silently dropped by the unknown-key tolerance; the error points at depends_on
    with pytest.raises(ValueError, match="'composites', which has been removed.*depends_on"):
        manifest.load(text)


def test_load_ignores_other_unknown_top_level_keys():
    # arrange: product build data in extra top-level sections (the backward-compatible tolerance)
    text = _OK + "images:\n  app: demo:local\nvolumes:\n  build_cache: demo-cache\n"

    # act
    mf = manifest.load(text)

    # assert: only `composites` gets the targeted rejection; everything else stays ignored
    assert set(mf.commands) == {"code", "build", "deploy"}


# --- depends_on (#895): the command dependency model -------------------------------------------------
# Under the v1 impl-XOR-depends_on lock a LEAF never carries deps, so every chain flows through impl-less
# AGGREGATES. A diamond on purpose: bringup reaches `prep` both directly and via `stage`, so prep's
# leaves are reachable twice - the plan must still run each exactly once.

# `prep` is a diamond: `bringup` reaches it directly AND through `stage`. Both declarers therefore carry
# the same stop_on_failure, which loader rule 6 (netctl#1319) requires of two aggregates in ONE plan.
_DEPS = """
product: demo
groups:
  build:
    install: { impl: "demo.impls:install", help: "Install host prereqs." }
    build:   { impl: "demo.impls:build",   help: "Build the artefacts." }
    prep:    { help: "Install + build.", depends_on: [install, build] }
  deploy:
    up:      { impl: "demo.impls:up",   help: "Deploy up." }
    seed:    { impl: "demo.impls:seed", help: "Seed." }
    stage:   { help: "Prep + deploy up.", depends_on: [prep, up], stop_on_failure: true }
    bringup: { help: "Full bring-up.", depends_on: [stage, prep, seed], stop_on_failure: true }
env_groups: [deploy]
"""


def test_load_reads_depends_on_and_stop_on_failure_defaulting_to_empty_and_false():
    # arrange / act
    mf = manifest.load(_DEPS)

    # assert: declared deps come through as tuples; a leaf defaults to () / False
    assert mf.spec_for("build", "prep").depends_on == ("install", "build")
    assert mf.spec_for("deploy", "bringup").depends_on == ("stage", "prep", "seed")
    assert mf.spec_for("deploy", "bringup").stop_on_failure is True
    assert mf.spec_for("build", "install").depends_on == ()
    assert mf.spec_for("build", "install").stop_on_failure is False


def test_plan_for_resolves_transitively_in_dependency_order_and_dedups_the_diamond():
    # arrange: bringup reaches prep twice (directly and via stage), so its leaves are reachable twice
    mf = manifest.load(_DEPS)

    # act
    plan = mf.plan_for("bringup")

    # assert: every transitive dep before its dependant, each unique command exactly once
    assert plan == ("install", "build", "up", "seed")


def test_plan_for_never_emits_an_impl_less_aggregate_only_its_leaves():
    # arrange / act
    mf = manifest.load(_DEPS)
    plan = mf.plan_for("bringup")

    # assert: the aggregates contribute their leaves, never themselves
    assert "bringup" not in plan and "stage" not in plan and "prep" not in plan


def test_plan_for_a_nested_aggregate_and_a_bare_leaf():
    # arrange / act
    mf = manifest.load(_DEPS)

    # assert: a nested aggregate expands to its transitive leaves; a leaf plans as just itself
    assert mf.plan_for("stage") == ("install", "build", "up")
    assert mf.plan_for("install") == ("install",)


def test_plan_for_rejects_an_unknown_command_name():
    # arrange
    mf = manifest.load(_DEPS)

    # act / assert
    with pytest.raises(ValueError, match="no unambiguous command named 'nope'"):
        mf.plan_for("nope")


def test_plan_for_disambiguates_an_ambiguous_root_via_the_group_keyword():
    # arrange: `all` is owned by test AND deploy (the #519 shape), so the bare name cannot resolve
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
    mf = manifest.load(text)

    # act / assert: the group keyword resolves each owner's own aggregate; the bare name fails loudly
    assert mf.plan_for("all", group="test") == ("unit",)
    assert mf.plan_for("all", group="deploy") == ("up",)
    with pytest.raises(ValueError, match="no unambiguous command named 'all'"):
        mf.plan_for("all")


def test_load_rejects_a_dependency_naming_an_unknown_command():
    # arrange: prep depends on a command that is not in the manifest
    text = _DEPS.replace("depends_on: [install, build]", "depends_on: [nope, build]")

    # act / assert: the error names the owning command and the bad dependency
    with pytest.raises(ValueError, match="command 'build.prep': dependency 'nope' is not a command"):
        manifest.load(text)


def test_load_rejects_a_dependency_naming_an_ambiguous_command():
    # arrange: `all` is owned by two groups, so no bare dependency can name it
    text = """
groups:
  test:
    all: { impl: "demo.impls:test_all", help: "Every test stage." }
  deploy:
    all:   { impl: "demo.impls:deploy_all", help: "Full bring-up." }
    combo: { help: "Aggregate over an ambiguous name.", depends_on: [all] }
"""

    # act / assert
    with pytest.raises(ValueError, match="command 'deploy.combo': dependency 'all' is ambiguous"):
        manifest.load(text)


def test_load_rejects_a_dependency_cycle_naming_its_path():
    # arrange: a -> b -> a
    text = """
groups:
  code:
    a: { help: "A.", depends_on: [b] }
    b: { help: "B.", depends_on: [a] }
"""

    # act / assert: the 3-colour DFS reports the cycle path
    with pytest.raises(ValueError, match="dependency cycle: a -> b -> a"):
        manifest.load(text)


def test_load_rejects_a_command_declaring_both_impl_and_depends_on():
    # arrange: the v1 lock - a command is a leaf-with-impl XOR an impl-less aggregate
    text = ("groups:\n  code:\n    fmt: { impl: 'm:f', help: 'x' }\n"
            "    fix: { impl: 'm:g', help: 'y', depends_on: [fmt] }\n")

    # act / assert
    with pytest.raises(ValueError, match="command 'code.fix': impl and depends_on are mutually exclusive"):
        manifest.load(text)


def test_load_still_rejects_a_command_with_neither_impl_nor_depends_on():
    # arrange: an empty spec is neither a leaf nor an aggregate
    text = "groups:\n  code:\n    fmt: { help: 'x' }\n"

    # act / assert: the pre-#895 missing-impl message is unchanged
    with pytest.raises(ValueError, match="command 'code.fmt': missing impl"):
        manifest.load(text)


def test_load_rejects_an_aggregate_declaring_passthrough_args():
    # arrange: a passthrough command forwards trailing args to ONE tool; an aggregate's plan runs each
    # leaf as its own subprocess, so there is no single forwarding target (#896)
    text = ("groups:\n  code:\n    fmt: { impl: 'm:f', help: 'x' }\n"
            "    fix: { help: 'y', depends_on: [fmt], passthrough_args: true }\n")

    # act / assert
    with pytest.raises(ValueError, match="command 'code.fix': passthrough_args cannot combine with depends_on"):
        manifest.load(text)


def test_load_reads_keep_awake_defaulting_to_false():
    # arrange: an aggregate whose plan runs for many minutes declares that the host must not idle-sleep
    # while it runs (netctl#1238); everything else defaults to False
    text = ("groups:\n  build:\n    jar: { impl: 'm:f', help: 'x' }\n"
            "    images: { help: 'y', depends_on: [jar], keep_awake: true }\n")

    # act
    mf = manifest.load(text)

    # assert
    assert mf.spec_for("build", "images").keep_awake is True
    assert mf.spec_for("build", "jar").keep_awake is False


def test_load_rejects_keep_awake_on_a_leaf():
    # arrange: `run_command` is the flag's only consumer and it only ever runs an AGGREGATE's plan - the
    # CLI binds a leaf straight to its impl - so on a leaf the flag would do nothing at all (netctl#1238)
    text = "groups:\n  build:\n    jar: { impl: 'm:f', help: 'x', keep_awake: true }\n"

    # act / assert: a flag that does nothing where it is written fails loudly instead
    with pytest.raises(ValueError, match="command 'build.jar': keep_awake applies to an aggregate's plan"):
        manifest.load(text)


def test_load_rejects_stop_on_failure_on_a_leaf():
    # arrange: the flag scopes to the SUBTREE of the command that declares it (netctl#1317), and a leaf's
    # subtree is the leaf - by the time it has failed there is nothing below it left to skip. Someone
    # writing it on a preflight guard expecting the bring-up to stop would get a clean load and no effect.
    text = "groups:\n  build:\n    jar: { impl: 'm:f', help: 'x', stop_on_failure: true }\n"

    # act / assert: a flag that does nothing where it is written fails loudly instead, exactly as
    # keep_awake and hidden already do
    with pytest.raises(ValueError,
                       match="command 'build.jar': stop_on_failure applies to an aggregate"):
        manifest.load(text)


def test_load_allows_stop_on_failure_on_an_aggregate():
    # arrange: the negative half - the rejection must not swallow the case the flag exists for
    text = ("groups:\n  build:\n    jar:    { impl: 'm:f', help: 'x' }\n"
            "    images: { help: 'y', depends_on: [jar], stop_on_failure: true }\n")

    # act
    mf = manifest.load(text)

    # assert
    assert mf.spec_for("build", "images").stop_on_failure is True


# --- rule 6: in-plan agreement on stop_on_failure (netctl#1319) -------------------------------------
# The shape the ticket names: `first` (unflagged) and `guarded` (flagged) both declare `shared`, and one
# plan - `run.root` - reaches both. The spanning tree plans `shared` under whichever of the two the DFS
# reaches first, so the other's stop_on_failure never fires for its OWN dependency. The two fixtures
# differ only in the order that decides that race, because the verdict must not depend on it.
_IN_PLAN_GUARD_SECOND = """
groups:
  gate:
    shared:  { impl: "demo:shared", help: "The contested dependency." }
    other:   { impl: "demo:other",  help: "What the guard protects." }
    later:   { impl: "demo:later",  help: "A step after the guard." }
    first:   { help: "Reaches shared first.", depends_on: [shared] }
    guarded: { help: "Wants to stop.", depends_on: [shared, other], stop_on_failure: true }
  run:
    root: { help: "The plan that reaches both.", depends_on: [first, guarded, later] }
"""

_IN_PLAN_GUARD_FIRST = """
groups:
  gate:
    shared:  { impl: "demo:shared", help: "The contested dependency." }
    other:   { impl: "demo:other",  help: "What the guard protects." }
    later:   { impl: "demo:later",  help: "A step after the guard." }
    guarded: { help: "Wants to stop.", depends_on: [shared, other], stop_on_failure: true }
    first:   { help: "Reaches shared second.", depends_on: [shared] }
  run:
    root: { help: "The plan that reaches both.", depends_on: [guarded, first, later] }
"""


@pytest.mark.parametrize("text", [_IN_PLAN_GUARD_SECOND, _IN_PLAN_GUARD_FIRST],
                         ids=["guard-declared-second", "guard-declared-first"])
def test_load_rejects_in_plan_aggregates_disagreeing_on_stop_on_failure(text):
    # arrange: both orders of the same diamond - the flagged aggregate as the FIRST and as the SECOND
    # parent of `shared`, which is what decides who wins the spanning tree's dedup

    # act / assert: the dedup order must not decide whether the manifest loads, so both are rejected
    with pytest.raises(ValueError,
                       match="both declare dependency 'shared' but disagree on stop_on_failure"):
        manifest.load(text)


def test_load_accepts_disagreeing_aggregates_that_live_in_different_plans():
    # arrange: netctl's real shape as a regression fixture - `deploy bringup` (a strict chain, flagged) and
    # `test all` (a collection, unflagged) share `up` and `seed`, but they are separate ENTRY POINTS that
    # never appear in one plan. A manifest-wide rule would reject five such commands in netctl today; that
    # their failure policy over the same command differs is exactly right and must keep loading.
    text = """
groups:
  deploy:
    up:      { impl: "demo:up",   help: "Bring the lab up." }
    seed:    { impl: "demo:seed", help: "Seed the lab." }
    bringup: { help: "Cold-host bring-up.", depends_on: [up, seed], stop_on_failure: true }
  test:
    unit: { impl: "demo:unit", help: "Unit tests." }
    all:  { help: "The complete e2e.", depends_on: [up, seed, unit], stop_on_failure: false }
"""

    # act
    mf = manifest.load(text)

    # assert: both keep their own policy over the two shared commands
    assert mf.spec_for("deploy", "bringup").stop_on_failure is True
    assert mf.spec_for("test", "all").stop_on_failure is False
    assert [leaf.name for leaf in mf.plan_tree_for("bringup").leaves()] == ["up", "seed"]
    assert [leaf.name for leaf in mf.plan_tree_for("all", group="test").leaves()] == ["up", "seed", "unit"]


def test_load_accepts_in_plan_aggregates_agreeing_on_stop_on_failure():
    # arrange: netctl's two genuine in-plan diamonds have this shape - `aot` and `web-image` both declare
    # `jar` from inside one plan, and both stop on failure. Whoever catches the failure catches it with the
    # same policy, so the relocation is harmless and the rule must not touch it.
    text = """
groups:
  build:
    jar:       { impl: "demo:jar", help: "The shared artefact." }
    aot:       { help: "AOT image.", depends_on: [jar], stop_on_failure: true }
    web-image: { help: "Web image.", depends_on: [jar], stop_on_failure: true }
    images:    { help: "Every image.", depends_on: [aot, web-image], stop_on_failure: true }
"""

    # act
    mf = manifest.load(text)

    # assert: the diamond still collapses to one occurrence of the shared leaf
    assert mf.plan_for("images") == ("jar",)
    assert mf.spec_for("build", "aot").stop_on_failure is True


# Two entry points reach both declarers, so the message has to CHOOSE which plan it names. `zulu` is
# declared first, so insertion order cannot pass for the alphabetical tie-break.
_TWO_PLANS_COLLIDE = """
groups:
  gate:
    shared:  { impl: "demo:shared", help: "The contested dependency." }
    first:   { help: "Reaches shared first.", depends_on: [shared] }
    guarded: { help: "Wants to stop.", depends_on: [shared], stop_on_failure: true }
  run:
    zulu:  { help: "One plan over both.", depends_on: [first, guarded] }
    alpha: { help: "Another plan over both.", depends_on: [first, guarded] }
"""


def test_the_named_plan_is_the_alphabetically_first_candidate_whatever_the_hash_seed():
    # arrange: the candidate plans arrive as a SET, whose iteration order Python randomises per process, so
    # a single in-process assertion would pass half the time even if the tie-break were dropped. Run the
    # load under several PYTHONHASHSEEDs instead and require ONE message out of all of them.
    source = str(pathlib.Path(manifest.__file__).parents[2])
    probe = (f"import sys; sys.path.insert(0, {source!r})\n"
             "from delivery.orchestrator import manifest\n"
             "try:\n"
             f"    manifest.load({_TWO_PLANS_COLLIDE!r})\n"
             "except ValueError as exc:\n"
             "    print(exc)\n")

    # act
    messages = {subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                               env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout.strip()
                for seed in range(4)}

    # assert: one message across every seed, naming the alphabetically first of the two candidate plans
    assert len(messages) == 1
    assert "plan 'run.alpha' reaches both" in messages.pop()


def test_the_in_plan_disagreement_message_names_both_aggregates_the_dependency_and_the_plan():
    # arrange: without all three the reader cannot act - the SAME pair of aggregates is legal in a
    # different plan, so the plan is what makes the message a diagnosis instead of a complaint
    with pytest.raises(ValueError) as caught:
        manifest.load(_IN_PLAN_GUARD_SECOND)

    # act
    message = str(caught.value)

    # assert
    assert "gate.first" in message
    assert "gate.guarded" in message
    assert "'shared'" in message
    assert "run.root" in message


def test_load_reads_hidden_defaulting_to_false():
    # arrange: a plan step named by a depends_on entry (loader rule 4) must be a real command, but need
    # not clutter --help (netctl#1277); everything else defaults to False
    text = ("groups:\n  build:\n    jar:  { impl: 'm:f', help: 'x' }\n"
            "    step: { impl: 'm:g', help: 'y', hidden: true }\n")

    # act
    mf = manifest.load(text)

    # assert
    assert mf.spec_for("build", "step").hidden is True
    assert mf.spec_for("build", "jar").hidden is False


def test_load_rejects_hidden_on_a_group_default_namesake():
    # arrange: `build` is the group-default namesake of the multi-member `build` group (#592 D4) - it is
    # bound as the sub-app's default callback, never a listed subcommand or a separate flat command, so
    # `hidden` there would do nothing (the same reasoning that rejects keep_awake on a leaf)
    text = ("groups:\n  build:\n    build: { impl: 'm:f', help: 'x', hidden: true }\n"
            "    diff:  { impl: 'm:g', help: 'y' }\n")

    # act / assert: a flag that does nothing where it is written fails loudly instead
    with pytest.raises(ValueError, match="command 'build.build': hidden has no effect on a group-default "
                                          "namesake member"):
        manifest.load(text)


def test_load_allows_hidden_on_a_group_default_sibling():
    # arrange: only the NAMESAKE is rejected; a sibling in the same group-default group is an ordinary
    # grouped command, so hidden is meaningful there
    text = ("groups:\n  build:\n    build: { impl: 'm:f', help: 'x' }\n"
            "    diff:  { impl: 'm:g', help: 'y', hidden: true }\n")

    # act
    mf = manifest.load(text)

    # assert
    assert mf.spec_for("build", "diff").hidden is True


def test_load_allows_hidden_on_a_single_member_flat_group():
    # arrange: `package` collapses to ONE visible flat top-level command (is_flat_command_group) - hidden
    # there is meaningful too, it hides that one and only registration
    text = "groups:\n  package:\n    package: { impl: 'm:f', help: 'x', hidden: true }\n"

    # act
    mf = manifest.load(text)

    # assert
    assert mf.spec_for("package", "package").hidden is True


def test_load_rejects_an_aggregate_with_a_missing_help():
    # arrange: an impl-less aggregate still owes its help line
    text = ("groups:\n  code:\n    fmt: { impl: 'm:f', help: 'x' }\n"
            "    fix: { depends_on: [fmt] }\n")

    # act / assert
    with pytest.raises(ValueError, match="command 'code.fix': missing help"):
        manifest.load(text)


# --- plan_tree_for (#1275): the same plan, keeping the structure plan_for drops -----------------------
# `plan_for` returns the flat leaf tuple, so an aggregate contributes its leaves and never itself - which
# is why `build` disappears as a concept inside `bringup`'s step list. The tree keeps the aggregates as
# nodes while resolving to exactly the same leaves, and THAT equality is the property both the runner and
# the TUI depend on: display and execution can never disagree if they come from one traversal.

_SHARED = """
groups:
  build:
    a:   { impl: "demo.impls:a", help: "A leaf." }
    x:   { help: "X.", depends_on: [a] }
    y:   { help: "Y.", depends_on: [a] }
    top: { help: "Top.", depends_on: [x, y] }
"""


def test_plan_tree_for_keeps_the_aggregates_that_the_flat_plan_drops():
    # arrange
    mf = manifest.load(_DEPS)

    # act
    tree = mf.plan_tree_for("bringup")

    # assert: the root is the aggregate itself, and `stage` survives as an intermediate node
    assert tree.name == "bringup"
    assert tree.is_leaf is False
    stage = tree.children[0]
    assert stage.name == "stage"
    assert [child.name for child in stage.children] == ["prep", "up"]
    assert [grandchild.name for grandchild in stage.children[0].children] == ["install", "build"]


def test_plan_tree_for_shows_a_diamond_once_at_its_first_occurrence():
    # arrange: bringup depends on [stage, prep, seed] and stage already pulls prep in
    mf = manifest.load(_DEPS)

    # act
    tree = mf.plan_tree_for("bringup")

    # assert: the SECOND reach of prep contributes nothing, so it is not a direct child of bringup
    assert [child.name for child in tree.children] == ["stage", "seed"]


def test_plan_tree_for_omits_an_aggregate_whose_whole_subtree_was_already_planned():
    # arrange: x and y both depend on the single leaf a, so y contributes nothing once x has been walked
    mf = manifest.load(_SHARED)

    # act
    tree = mf.plan_tree_for("top")

    # assert: y is dropped rather than rendered as an empty node, and the leaf still appears once
    assert [child.name for child in tree.children] == ["x"]
    assert [leaf.name for leaf in tree.leaves()] == ["a"]


def test_plan_tree_for_a_leaf_root_is_a_childless_node_that_is_its_own_leaf():
    # arrange / act
    mf = manifest.load(_DEPS)
    tree = mf.plan_tree_for("install")

    # assert
    assert tree.name == "install"
    assert tree.children == ()
    assert tree.is_leaf is True
    assert [leaf.name for leaf in tree.leaves()] == ["install"]


@pytest.mark.parametrize("root", ["bringup", "stage", "prep", "install"])
def test_the_trees_leaves_in_dfs_order_are_exactly_the_flat_plan(root):
    # arrange: the invariant the whole slice rests on - one plan, two views. plan_for is an INDEPENDENT
    # implementation, so this really compares two traversals rather than one against itself.
    mf = manifest.load(_DEPS)

    # act
    tree = mf.plan_tree_for(root)

    # assert
    assert tuple(leaf.name for leaf in tree.leaves()) == mf.plan_for(root)


@pytest.mark.parametrize("root", ["top", "x", "y"])
def test_the_trees_leaves_in_dfs_order_are_exactly_the_flat_plan_for_an_omitted_aggregate(root):
    # arrange: _SHARED is the one shape _DEPS never exercises - `top` reaches the leaf `a` via both `x`
    # and `y`, so `y` contributes nothing and is OMITTED from the tree entirely. plan_for is an INDEPENDENT
    # implementation, so this still compares two traversals rather than one against itself.
    mf = manifest.load(_SHARED)

    # act
    tree = mf.plan_tree_for(root)

    # assert
    assert tuple(leaf.name for leaf in tree.leaves()) == mf.plan_for(root)


def test_plan_tree_for_carries_the_dotted_group_command_path_on_every_node():
    # arrange
    mf = manifest.load(_DEPS)

    # act
    tree = mf.plan_tree_for("bringup")

    # assert: the path is the CLI identity the TUI renders, not the bare name
    assert tree.path == "deploy.bringup"
    assert tree.children[0].path == "deploy.stage"
    assert tree.children[0].children[0].path == "build.prep"
    assert tree.children[0].children[0].children[0].path == "build.install"


def test_plan_tree_for_disambiguates_an_ambiguous_root_via_the_group_keyword():
    # arrange: `all` is owned by test AND deploy (the #519 shape), so path_by_name cannot decide
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
    mf = manifest.load(text)

    # act / assert: the group keyword resolves the owner's own plan AND its path; the bare name fails loudly
    assert mf.plan_tree_for("all", group="test").path == "test.all"
    assert mf.plan_tree_for("all", group="deploy").path == "deploy.all"
    assert [leaf.name for leaf in mf.plan_tree_for("all", group="test").leaves()] == ["unit"]
    with pytest.raises(ValueError, match="no unambiguous command named 'all'"):
        mf.plan_tree_for("all")

    # assert: the parity property holds for EACH group's own disambiguated root too, not only the
    # unambiguous shape _DEPS exercises
    assert (tuple(leaf.name for leaf in mf.plan_tree_for("all", group="test").leaves())
            == mf.plan_for("all", group="test"))
    assert (tuple(leaf.name for leaf in mf.plan_tree_for("all", group="deploy").leaves())
            == mf.plan_for("all", group="deploy"))


def test_plan_tree_for_rejects_an_unknown_command_name():
    # arrange
    mf = manifest.load(_DEPS)

    # act / assert: the same message plan_for gives, so the two views fail identically
    with pytest.raises(ValueError, match="no unambiguous command named 'nope'"):
        mf.plan_tree_for("nope")


# --- the taxonomy TREE (netctl#1431): an optional nested `taxonomy:` block, merged with `groups:` ----

def test_a_manifest_without_a_taxonomy_key_yields_the_flat_groups_as_a_depth_one_tree():
    # arrange: netctl's shape throughout netctl#1431 - no taxonomy block at all
    text = """
groups:
  build:
    build: { impl: "m:f", help: "Build it." }
  deploy:
    up: { impl: "m:g", help: "Bring it up." }
env_groups: [deploy]
"""

    # act
    m = manifest.load(text)

    # assert: identical to what the flat constructor produced before the rewrite
    assert sorted(m.tree) == ["build", "deploy"]
    assert m.tree["deploy"].env_first is True
    assert m.tree["build"].groups == {}
    assert m.taxonomy().resolve_group("up") == "deploy"


def test_a_nested_taxonomy_block_places_a_group_beneath_another():
    # arrange: what a catalogue will declare, exercised here through the product manifest
    text = """
taxonomy:
  support:
    help: "Host and tooling upkeep."
    groups:
      git: { help: "Version control verbs." }
groups:
  support.git:
    commit: { impl: "m:f", help: "Commit." }
"""

    # act
    m = manifest.load(text)

    # assert
    assert m.taxonomy().resolve_path("support.git") is not None
    assert m.taxonomy().resolve_group("commit") == "support.git"


def test_a_group_declared_in_both_the_taxonomy_block_and_as_a_flat_group_is_rejected():
    # arrange: the merge contradiction, surfaced at manifest-load time rather than at dispatch
    text = """
taxonomy:
  build: { help: "Produce the artefacts." }
groups:
  build:
    build: { impl: "m:f", help: "Build it." }
"""

    # act / assert
    with pytest.raises(ValueError, match="build"):
        manifest.load(text)
