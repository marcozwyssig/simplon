"""si#344 C.4: which artifacts cross from one job to another, and which cannot (spec C.6).

AAA; the name states the behaviour under test. The specs come from a loaded manifest, so the edges are the ones
the loader binds, not hand-built tuples.
"""
import pytest

from simplon.manifest import artifactsection, catalogue, load as manifest
from simplon.tasks import handoff

import yaml

TEXT = """
product: demo
tasks:
  copy:
    impl: "simplon.test_impls:nullary"
    help: "Copy one directory into another."
    input:  { source: { accepts: directory } }
    output: { target: { accepts: directory } }
  seed:
    impl: "simplon.test_impls:nullary"
    help: "Write a directory."
    output: { target: { accepts: directory } }
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
  left: { kind: directory, path: build/left }
  right: { kind: directory, path: build/right }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
      left: { task: "seed", produces: { target: left } }
      right: { task: "copy", consumes: { source: left }, produces: { target: right } }
      back: { task: "copy", consumes: { source: right }, produces: { target: left } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      push-image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""

LOADED = manifest.load(TEXT, catalogue=catalogue.load(), manifest_path="demo.yaml")
ARTIFACTS = artifactsection.declared(yaml.safe_load(TEXT))


def _leaf(path):
    group, name = path.rsplit(" ", 1)
    return (path, LOADED.spec_for(group, name))


def _run(job, *steps, matrix=False, needs=(), condition=""):
    """A job whose step i runs the one leaf `steps[i]`."""
    return handoff.Run(job, tuple((_leaf(step),) for step in steps), matrix=matrix, needs=needs, condition=condition)


def test_a_result_made_in_one_job_and_consumed_in_another_is_handed_over():
    # arrange
    runs = [_run("test", "build image", "test image"), _run("release", "build image", "release push-image")]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out["test"] == handoff.Handoff(uploads={1: ("app-checked",)})
    assert out["release"] == handoff.Handoff(needs=("test",), downloads={1: ("app-checked",)})


def test_producer_and_consumer_in_one_job_hand_nothing_over():
    # arrange
    runs = [_run("all", "build image", "test image", "release push-image")]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out == {"all": handoff.Handoff()}


def test_the_upload_follows_the_last_producing_step_and_the_download_precedes_the_first_consumer():
    # arrange: job a writes `left` twice (seed at step 0, back at step 2 - back consumes `right`, which
    # a also makes, at step 1); job b reads `left` at steps 1 and 2
    runs = [handoff.Run("a", ((_leaf("build left"),), (_leaf("build right"),), (_leaf("build back"),))),
            handoff.Run("b", ((_leaf("build image"),), (_leaf("build right"),), (_leaf("build right"),)))]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out["a"] == handoff.Handoff(uploads={2: ("left",)})
    assert out["b"] == handoff.Handoff(needs=("a",), downloads={1: ("left",)})  # b makes `right` itself


def test_a_consumer_whose_producer_runs_in_no_job_of_the_workflow_is_refused():
    # arrange: the release job runs the push, and no job runs the test that writes its evidence
    runs = [_run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match="no job in this workflow produces it"):
        handoff.plan("release", runs, ARTIFACTS)


def test_a_consumed_artifact_with_a_registry_and_no_producer_in_the_workflow_is_fetched():
    # arrange: `app` has a registry; the test job does not build it
    runs = [_run("test", "test image")]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out == {"test": handoff.Handoff()}


def test_a_step_consuming_before_the_step_that_produces_it_in_the_same_job_is_refused():
    # arrange
    runs = [_run("all", "test image", "build image")]

    # act / assert
    with pytest.raises(ValueError, match="runs 'test image' .step 1. before 'build image' .step 2."):
        handoff.plan("ci", runs, ARTIFACTS)


def test_an_artifact_made_in_two_jobs_and_consumed_in_a_third_is_refused():
    # arrange
    runs = [_run("t1", "build image", "test image"), _run("t2", "build image", "test image"),
            _run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match="is produced in more than one job: 't1', 't2'"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_an_artifact_made_in_a_matrix_job_and_consumed_elsewhere_is_refused():
    # arrange
    runs = [_run("test", "build image", "test image", matrix=True),
            _run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match="runs once per matrix entry"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_a_matrix_job_may_consume_what_another_job_hands_over():
    # arrange
    runs = [_run("test", "build image", "test image"),
            _run("release", "build image", "release push-image", matrix=True)]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert
    assert out["release"].needs == ("test",)


def test_an_artifact_without_a_path_across_a_job_boundary_is_refused_whatever_its_kind():
    # arrange: `app` is built in one job and tested in another, and an image has no file to hand over
    runs = [_run("build", "build image"), _run("test", "test image")]

    # act / assert
    with pytest.raises(ValueError, match="declares no `path:`, so there is no file to hand over"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_jobs_that_need_each_other_through_their_artifacts_are_refused():
    # arrange: a seeds `left` and copies `right` back into it; b copies `left` into `right`
    runs = [_run("a", "build left", "build back"), _run("b", "build right")]

    # act / assert
    with pytest.raises(ValueError, match="need each other: a -> b -> a"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_a_cycle_through_a_declared_needs_is_refused_too():
    # arrange: b needs a by hand-off; a declares `needs: b` itself
    runs = [_run("a", "build left", needs=("b",)), _run("b", "build right")]

    # act / assert
    with pytest.raises(ValueError, match="need each other"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_a_declared_needs_is_not_repeated_in_the_added_ones():
    # arrange
    runs = [_run("test", "build image", "test image"),
            _run("release", "build image", "release push-image", needs=("test",))]

    # act
    out = handoff.plan("ci", runs, ARTIFACTS)

    # assert: the hand-off still downloads, and adds no second `test`
    assert out["release"] == handoff.Handoff(downloads={1: ("app-checked",)})


def _variant(old, new):
    """The same manifest with `old` replaced everywhere, so a spec binds the name or path being tried."""
    text = TEXT.replace(old, new)
    loaded = manifest.load(text, catalogue=catalogue.load(), manifest_path="demo.yaml")
    leaf = lambda path: (path, loaded.spec_for(*path.rsplit(" ", 1)))  # noqa: E731
    return (lambda job, *steps, **kw: handoff.Run(job, tuple((leaf(s),) for s in steps), **kw),
            artifactsection.declared(yaml.safe_load(text)))


def test_an_artifact_name_the_shell_or_upload_would_choke_on_is_refused():
    # arrange: `app:checked` is a legal manifest name, and upload-artifact rejects the colon
    run, artifacts = _variant("app-checked", "app:checked")

    # act / assert
    with pytest.raises(ValueError, match="can be handed over only under a name of letters, digits, `.`, `_` and `-`"):
        handoff.plan("ci", [run("test", "build image", "test image"), run("release", "build image", "release push-image")], artifacts)


@pytest.mark.parametrize("path", ["/tmp/app.json", "../up/app.json", "a/../../app.json", "C:/app.json"])
def test_a_path_tar_would_store_somewhere_else_is_refused(path):
    # arrange
    run, artifacts = _variant("build/test/app.json", path)

    # act / assert
    with pytest.raises(ValueError, match="tar would store it somewhere else"):
        handoff.plan("ci", [run("test", "build image", "test image"), run("release", "build image", "release push-image")], artifacts)


def test_a_producer_that_runs_only_under_a_condition_its_consumer_lacks_is_refused():
    # arrange
    runs = [_run("test", "build image", "test image", condition="github.ref == 'refs/heads/main'"),
            _run("release", "build image", "release push-image")]

    # act / assert
    with pytest.raises(ValueError, match=r"runs only `if: github.ref == 'refs/heads/main'`, and job 'release' does not"):
        handoff.plan("ci", runs, ARTIFACTS)


def test_the_same_condition_on_both_jobs_is_allowed():
    # arrange: both are skipped together, so nothing is green by accident
    runs = [_run("test", "build image", "test image", condition="github.ref == 'x'"),
            _run("release", "build image", "release push-image", condition="github.ref == 'x'")]

    # act / assert
    assert handoff.plan("ci", runs, ARTIFACTS)["release"].needs == ("test",)


def test_a_loop_of_declared_needs_alone_is_not_blamed_on_artifacts():
    # arrange: no artifact crosses at all
    runs = [_run("a", "build image", needs=("b",)), _run("b", "build left", needs=("a",))]

    # act / assert
    with pytest.raises(ValueError, match=r"need each other: a -> b -> a - the jobs' own `needs:` form the loop"):
        handoff.plan("ci", runs, ARTIFACTS)
