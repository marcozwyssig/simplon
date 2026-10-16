"""si#400 4d: a command is an object of a Command class mirroring simplon.pipeline (TaskCommand, Deploy,
AggregateCommand, ReleaseCommand). AAA."""
import dataclasses
import pickle

import pytest

from simplon.domain import command


def test_a_task_command_carries_its_own_fields_and_reads_the_aggregates_as_empty_with_a_warning():
    # arrange
    leaf = command.TaskCommand(help="h", impl="m:f", task="build:image")

    # act / assert: netctl's tests read `depends_on` on every command (measured) - one release window
    with pytest.warns(command.CompatWarning, match=r"TaskCommand\.depends_on"):
        assert leaf.depends_on == ()
    assert leaf.impl == "m:f"


def test_an_aggregate_reads_impl_as_empty_with_a_warning():
    # arrange: netctl asserts `not spec.impl` on an aggregate (measured)
    agg = command.AggregateCommand(help="h", depends_on=("a",))

    # act / assert
    with pytest.warns(command.CompatWarning, match=r"AggregateCommand\.impl"):
        assert agg.impl == ""


def test_an_unknown_field_is_still_an_attribute_error():
    # act / assert
    with pytest.raises(AttributeError):
        command.TaskCommand(help="h").nonsense


def test_a_command_is_frozen_and_round_trips():
    # arrange
    agg = command.ReleaseCommand(help="h", depends_on=("a",), release="bundle")

    # act / assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        agg.release = "other"  # type: ignore[misc]
    assert pickle.loads(pickle.dumps(agg)) == agg


def test_the_hierarchy_mirrors_the_pipeline_model():
    # act / assert
    assert issubclass(command.Deploy, command.TaskCommand) and issubclass(command.TaskCommand, command.Command)
    assert issubclass(command.ReleaseCommand, command.AggregateCommand)
    assert issubclass(command.AggregateCommand, command.Command)
    assert not issubclass(command.AggregateCommand, command.TaskCommand)


def test_task_class_is_resolved_only_when_asked():
    # arrange: holding the name keeps manifest loading free of body imports (Marco's choice 2)
    leaf = command.TaskCommand(help="h", impl="simplon.tasks.vcs_push:VcsPush", task="vcs:push")

    # act
    cls = leaf.task_class(where="build push")

    # assert
    assert cls.KEY == "vcs:push"


def test_the_compatibility_is_gone_after_its_release():
    # arrange: the checkout's own version, as test_surface reads it for MOVED_DUE_AFTER
    from test_surface import _release_number

    # act / assert
    assert _release_number() <= command.COMPAT_DUE_AFTER, (
        f"the read compatibility on Command was due to go after {command.COMPAT_DUE_AFTER}: delete "
        f"`Command.__getattr__`, `_OTHER_KIND`, `CompatWarning` and these tests' compat cases")


def test_a_release_aggregate_is_a_release_command_naming_its_bundle():
    # arrange: simplon's own manifest releases through `release all` with `produces: { release: kernel-release }`
    from conftest import ROOT
    from simplon.domain import catalogue, manifest
    mf = manifest.load((ROOT / "simplon.yaml").read_text(encoding="utf-8"), catalogue=catalogue.load())

    # act
    releases = {f"{g} {n}": c for g, cs in mf.commands.items() for n, c in cs.items()
                if isinstance(c, command.ReleaseCommand)}

    # assert
    assert releases and all(c.release for c in releases.values())


def test_a_task_command_in_an_env_first_group_is_a_deploy_and_an_aggregate_there_is_not():
    # arrange: test_manifest's dependency fixture places leaves and aggregates under `cd: deploy:` and `ci: build:`
    from test_manifest import _DEPS
    from simplon.domain import manifest
    mf = manifest.load(_DEPS)

    # act
    up, stage, build = mf.spec_for("deploy", "up"), mf.spec_for("deploy", "stage"), mf.spec_for("build", "build")

    # assert: only a TASK command in an env-first group is a Deploy (simplon.pipeline)
    assert isinstance(up, command.Deploy)
    assert isinstance(stage, command.AggregateCommand) and not isinstance(stage, command.TaskCommand)
    assert type(build) is command.TaskCommand


# --- final review of 4d ------------------------------------------------------------------------------

def test_a_misplaced_aggregate_naming_two_outputs_is_told_where_it_stands_first():
    # arrange: the fix is to drop `produces:`, not to reshape it - so placement is said before shape,
    # as `ports._check_bundles` said it before 4d moved the shape half into the loader
    from test_manifest import _DEPS
    from simplon.domain import manifest
    text = _DEPS.replace('depends_on: ["prep", "up"]', 'depends_on: ["prep", "up"]\n'
                         '        produces: { release: rel, image: thing }')

    # act / assert
    with pytest.raises(ValueError, match=r"only an aggregate under `ci: release:` does"):
        manifest.load(text)


def test_a_task_command_in_a_nested_env_first_group_is_a_deploy_as_the_cli_gates_it():
    # arrange: env-first inherited from a node below the top level, which the CLI's gate honours
    from simplon.domain import manifest
    text = """
tasks:
  fix: { impl: "m:f", help: "Fix it." }

support:
  groups:
    cluster:
      env_first: true
      commands:
        fix: { task: "fix" }
"""
    mf = manifest.load(text)
    assert mf.taxonomy().group_requires_env("support.cluster")

    # act / assert
    assert isinstance(mf.spec_for("support.cluster", "fix"), command.Deploy)


def test_a_release_command_still_answers_its_bundle_under_produces_for_the_window():
    # arrange: before 4d the bundle WAS `produces: {release: (...)}`; reading it as empty would turn
    # "declared a bundle" into "declared nothing", the ambiguity the window exists to end
    release = command.ReleaseCommand(depends_on=("a",), release="kernel-release")

    # act / assert
    with pytest.warns(command.CompatWarning, match=r"ReleaseCommand\.produces"):
        assert release.produces == {"release": ("kernel-release",)}


def test_the_compatibility_hands_out_no_shared_mutable_value():
    # arrange
    first, second = command.AggregateCommand(), command.AggregateCommand()

    # act: one consumer writes into what it read
    with pytest.warns(command.CompatWarning):
        try:
            first.with_["leaked"] = 1
        except TypeError:
            pass

    # assert: nobody else sees it
    with pytest.warns(command.CompatWarning):
        assert "leaked" not in second.with_
