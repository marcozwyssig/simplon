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
