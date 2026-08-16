"""Engine tests for the shared steps-runner (delivery.orchestrator.steps): the product-agnostic step
model + runners moved out of netctl. Fake actions (no real subprocess, no Textual) so the state
transitions + overall verdict are tested in isolation. This is now the home of the generic runner + its
coverage (moved here from netctl's test_steps.py)."""
from __future__ import annotations

import shlex

import pytest

from delivery.orchestrator.manifest import load as manifest_load
from delivery.orchestrator.steps import (
    VERBOSE_ENV,
    Abort,
    Outcome,
    Pipeline,
    Step,
    StepState,
    abort_after,
    argv_step,
    overall_rc,
    run_headless,
)


def _step(label: str, rc: int, output: str = "") -> Step:
    return Step(label=label, action=lambda: Outcome(rc=rc, output=output))


def _command_step(command: str, rc: int = 0) -> Step:
    """A step carrying its exact-command identity, the way a product's step factory builds one - which is
    what lets the kernel verify a leaf-to-step pairing at all."""
    return Step(label=command, action=lambda: Outcome(rc=rc, output=""), command=command)


def test_step_run_transitions_to_ok_and_records_output():
    # Arrange: a passing step
    s = _step("docker engine", rc=0, output="Server: 28.0")
    # Act
    outcome = s.run()
    # Assert: OK state, output + rc captured, outcome reflects success
    assert s.state == StepState.OK
    assert s.rc == 0 and s.output == "Server: 28.0"
    assert outcome.ok is True


def test_step_run_transitions_to_failed_on_nonzero_rc():
    # Arrange: a failing step
    s = _step("host egress", rc=22, output="curl: (22) blocked")
    # Act
    s.run()
    # Assert
    assert s.state == StepState.FAILED
    assert s.rc == 22


def test_run_headless_returns_zero_when_all_pass():
    # Arrange: a pipeline of three passing steps
    p = Pipeline("doctor", [_step("a", 0), _step("b", 0), _step("c", 0)])
    # Act
    rc = run_headless(p)
    # Assert: overall success, every step OK
    assert rc == 0
    assert all(s.state == StepState.OK for s in p.steps)


def test_run_headless_returns_one_when_any_step_fails():
    # Arrange: one failing step among passing ones
    p = Pipeline("doctor", [_step("a", 0), _step("b", 1), _step("c", 0)])
    # Act
    rc = run_headless(p)
    # Assert: overall failure, but the later step still ran (no short-circuit)
    assert rc == 1
    assert p.steps[2].state == StepState.OK


def test_run_headless_prints_a_failing_action_steps_output(capsys):
    # Arrange: a gate that fails with a composed diagnosis (netctl#1047's freshness verdict, the case
    # netctl#1073 was filed for) - an action step, so nothing of its output has been shown yet
    diagnosis = "the app.jar inside netctl:local is a DEV-MODE build\n- clear web/build and rebuild"
    p = Pipeline("build", [_step("verify.build-freshness", 1, output=diagnosis)])
    # Act
    rc = run_headless(p)
    # Assert: the REASON reaches stdout (indented like the streamed lines), not just the rc
    out = capsys.readouterr().out
    assert rc == 1
    assert "  the app.jar inside netctl:local is a DEV-MODE build" in out
    assert "  - clear web/build and rebuild" in out
    assert "failed (rc 1)" in out


def test_run_headless_hides_a_passing_action_steps_output_by_default(capsys):
    # Arrange: a passing probe whose captured output is noise on a green run (a doctor `docker version`)
    p = Pipeline("doctor", [_step("docker version", 0, output="Server: 28.0")])
    # Act
    rc = run_headless(p)
    # Assert: the checklist stays compact - the output is NOT printed
    out = capsys.readouterr().out
    assert rc == 0
    assert "Server: 28.0" not in out


def test_run_headless_prints_a_passing_action_steps_output_when_verbose(capsys):
    # Arrange: the same passing probe, verbose asked for explicitly
    p = Pipeline("doctor", [_step("docker version", 0, output="Server: 28.0")])
    # Act
    run_headless(p, verbose=True)
    # Assert: the proof of WHAT was checked is shown, same indent
    assert "  Server: 28.0" in capsys.readouterr().out


def test_run_headless_verbose_defaults_to_the_delivery_verbose_env(capsys, monkeypatch):
    # Arrange: no explicit flag, the operator opted in via the env var
    monkeypatch.setenv(VERBOSE_ENV, "1")
    p = Pipeline("doctor", [_step("docker version", 0, output="Server: 28.0")])
    # Act
    run_headless(p)
    # Assert
    assert "  Server: 28.0" in capsys.readouterr().out


def test_run_headless_does_not_reprint_a_streaming_steps_live_output(capsys):
    # Arrange: a FAILING streaming step - its lines already went out live through emit, and
    # outcome.output is the same text again
    def stream(emit):
        emit("step 1/3: FROM alpine")
        return Outcome(rc=1, output="step 1/3: FROM alpine")

    p = Pipeline("build", [Step(label="web image", stream=stream)])
    # Act
    rc = run_headless(p, verbose=True)
    # Assert: printed exactly once (live), never a second time by the runner
    out = capsys.readouterr().out
    assert rc == 1
    assert out.count("step 1/3: FROM alpine") == 1


def test_overall_rc_matches_step_states():
    # Arrange
    p = Pipeline("doctor", [_step("a", 0), _step("b", 0)])
    for s in p.steps:
        s.run()
    # Act / Assert
    assert overall_rc(p) == 0
    p.steps[1].state = StepState.FAILED
    assert overall_rc(p) == 1


def test_step_requires_exactly_one_of_action_or_stream():
    # Arrange / Act / Assert: neither, and both, are rejected
    with pytest.raises(ValueError):
        Step(label="x")
    with pytest.raises(ValueError):
        Step(label="x", action=lambda: Outcome(0, ""), stream=lambda emit: Outcome(0, ""))


def test_streaming_step_feeds_lines_live_and_records_output():
    # Arrange: a streaming action that emits two lines then succeeds
    seen: list[str] = []

    def stream(emit):
        emit("line-1")
        emit("line-2")
        return Outcome(rc=0, output="line-1\nline-2")

    s = Step(label="build", stream=stream)
    # Act
    s.run(seen.append)
    # Assert: the emit saw each line live, and the final state/output are recorded
    assert seen == ["line-1", "line-2"]
    assert s.state == StepState.OK
    assert s.output == "line-1\nline-2"


def test_argv_step_is_a_streaming_step_for_an_arbitrary_command():
    # Arrange / Act: a build step wrapping a docker command
    s = argv_step("web image", ["docker", "build", "-t", "netctl-web:local", "."])
    # Assert: it streams (not a quick capture action)
    assert s.stream is not None
    assert s.action is None


def test_step_command_defaults_to_empty_so_the_label_stands():
    # Arrange / Act: a plain step that declares no command identity
    s = _step("host-checks", rc=0)
    # Assert: the command is empty, so `command or label` renders the label
    assert s.command == ""
    assert (s.command or s.label) == "host-checks"


def test_argv_step_command_defaults_to_the_shlex_joined_argv():
    # Arrange: a native argv step (a docker build) without an explicit command
    argv = ["docker", "build", "-t", "netctl-web:local", "."]
    # Act
    s = argv_step("web image", argv)
    # Assert: the section header identity is the REAL command it runs
    assert s.command == shlex.join(argv)
    assert s.command == "docker build -t netctl-web:local ."


def test_argv_step_takes_an_explicit_command_override():
    # Arrange / Act: an aggregate plan step whose header should be the dotted CLI path, not the raw argv
    s = argv_step("package: web jar", ["./netctl.sh", "package"], command="build.package")
    # Assert: the override wins over the shlex-joined argv
    assert s.command == "build.package"


def test_stop_on_failure_skips_the_steps_after_a_failure_when_there_is_no_tree():
    # Arrange: a stop_on_failure pipeline whose middle step fails (e.g. the build's web jar)
    p = Pipeline("build", [_step("unit gate", 0), _step("web jar", 1), _step("web image", 0)],
                 stop_on_failure=True)
    # Act
    rc = run_headless(p)
    # Assert: the failed step is FAILED, the one after it is SKIPPED (never run), overall is a failure
    assert p.steps[0].state == StepState.OK
    assert p.steps[1].state == StepState.FAILED
    assert p.steps[2].state == StepState.SKIPPED
    assert p.steps[2].rc is None                 # the skipped step's action never ran
    assert rc == 1


def test_without_stop_on_failure_a_failed_step_does_not_skip_the_rest():
    # Arrange: the default (bring-up) pipeline runs every step even after a failure
    p = Pipeline("bringup", [_step("a", 0), _step("b", 1), _step("c", 0)])
    # Act
    rc = run_headless(p)
    # Assert: the step after the failure still ran (no SKIPPED), overall still a failure
    assert p.steps[2].state == StepState.OK
    assert rc == 1


# --- the plan tree on the Pipeline (#1275) ------------------------------------------------------------


def test_pipeline_defaults_the_display_metadata_so_a_hand_built_pipeline_needs_neither():
    # Arrange / Act: `doctor` builds its Pipeline by hand and has no manifest plan behind it
    p = Pipeline("doctor", [_step("docker engine", 0)])
    # Assert: the new fields are optional display metadata, not a new requirement
    assert p.tree is None
    assert p.root_path == ""


def test_pipeline_still_takes_name_steps_and_stop_on_failure_positionally():
    # Arrange / Act: a dozen call sites construct it positionally, so the new fields must be APPENDED -
    # inserting either one earlier would silently rebind these arguments instead of failing loudly
    p = Pipeline("build", [_step("unit gate", 0)], True)
    # Assert
    assert p.name == "build"
    assert [s.label for s in p.steps] == ["unit gate"]
    assert p.stop_on_failure is True
    assert p.tree is None


def test_pipeline_carries_the_plan_tree_and_the_invoked_commands_dotted_path():
    # Arrange
    from delivery.orchestrator.manifest import CommandSpec, PlanNode

    node = PlanNode(name="seed", path="deploy.seed", spec=CommandSpec(impl="demo.impls:seed", help="Seed."))
    # Act
    p = Pipeline("seed", [_step("seed", 0)], False, node, "deploy.seed")
    # Assert: both ride along on the pipeline - the path purely so a renderer can show the invoked identity,
    # the tree additionally so a failure can be scoped to the subtree that declared stop_on_failure (#1317)
    assert p.tree is node
    assert p.root_path == "deploy.seed"


# --- stop_on_failure is a property of the SUBTREE (netctl#1317) ---------------------------------------
#
# `stop_on_failure` is declared per aggregate, so a failure must abort the subtree that declared it and
# leave that subtree's siblings alone. The oracle is the behaviour that existed before an aggregate's
# members became the parent's steps: a failing `up` aborted its own phases and the `test all` around it
# carried on to the next gate.
#
#     test.all              <- ROOT_FLAG
#       build.build         <- BUILD_FLAG
#         build.unit
#         build.image
#       deploy.up           <- UP_FLAG
#         deploy.up-preflight
#         deploy.up-deploy
#       test.accept
#
# Leaf (= step) order is therefore: unit, image, up-preflight, up-deploy, accept.

_GATES_MANIFEST = """
groups:
  build:
    unit:  { impl: "demo.impls:unit",  help: "The unit gate." }
    image: { impl: "demo.impls:image", help: "Build the image." }
    build: { help: "The full build.", depends_on: [unit, image], stop_on_failure: BUILD_FLAG }
  deploy:
    up-preflight: { impl: "demo.impls:preflight", help: "The image provenance guard." }
    up-deploy:    { impl: "demo.impls:deploy",    help: "Deploy the lab." }
    up:           { help: "Bring the lab up.", depends_on: [up-preflight, up-deploy],
                    stop_on_failure: UP_FLAG }
  test:
    accept: { impl: "demo.impls:accept", help: "The acceptance gate." }
    all:    { help: "Every gate.", depends_on: [build, up, accept], stop_on_failure: ROOT_FLAG }
env_groups: [deploy]
"""

# Three levels, so "the NEAREST flagged ancestor" and "the OUTERMOST flagged ancestor" are distinguishable:
#
#     run.root            <- ROOT_FLAG
#       gate.mid          <- MID_FLAG
#         gate.inner      <- INNER_FLAG
#           gate.a1
#           gate.a2
#         gate.b1
#       run.tail
#
# Leaf order: a1, a2, b1, tail.

_NESTED_GATES_MANIFEST = """
groups:
  gate:
    a1:    { impl: "demo.impls:a1", help: "Inner step one." }
    a2:    { impl: "demo.impls:a2", help: "Inner step two." }
    b1:    { impl: "demo.impls:b1", help: "The inner aggregate's sibling." }
    inner: { help: "The inner aggregate.", depends_on: [a1, a2], stop_on_failure: INNER_FLAG }
    mid:   { help: "The middle aggregate.", depends_on: [inner, b1], stop_on_failure: MID_FLAG }
  run:
    tail: { impl: "demo.impls:tail", help: "The step after everything." }
    root: { help: "The whole run.", depends_on: [mid, tail], stop_on_failure: ROOT_FLAG }
env_groups: [run]
"""


def _with_flags(text: str, **flags: bool) -> str:
    """The manifest with each FLAG placeholder replaced by a YAML boolean, so one readable manifest covers
    every flag combination without a wall of near-identical YAML."""
    for name, value in flags.items():
        text = text.replace(f"{name.upper()}_FLAG", str(value).lower())
    return text


def _planned(text: str, root: str) -> Pipeline:
    """A Pipeline built exactly as `run_command` builds one: one step per plan leaf, in leaf order, each
    carrying its dotted identity (so the leaf-to-step guard sees a well-paired tree), and the pipeline's own
    flag taken from the ROOT node - the fallback run_command sets for the degraded shape."""
    tree = manifest_load(text).plan_tree_for(root)
    steps = [Step(label=leaf.name, command=leaf.path, action=lambda: Outcome(rc=0, output=""))
             for leaf in tree.leaves()]
    return Pipeline(root, steps, tree.spec.stop_on_failure, tree, tree.path)


def _fail(pipeline: Pipeline, *names: str) -> Pipeline:
    """Make the named steps fail. Returns the pipeline so a test can arrange in one expression."""
    for step in pipeline.steps:
        if step.label in names:
            step.action = lambda: Outcome(rc=1, output="")
    return pipeline


def _states(pipeline: Pipeline) -> dict[str, StepState]:
    return {step.label: step.state for step in pipeline.steps}


def test_a_failure_aborts_the_flagged_subtree_and_lets_the_false_root_carry_on():
    """The defect this change exists for: `test all` is false because a suite must run every gate, but the
    `up` it plans is true because deploying on a dead preflight guard is forty doomed minutes."""
    # Arrange: the provenance guard dies inside the `true` up subtree, under a `false` root
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=False, build=False, up=True), "all"),
                     "up-preflight")
    # Act
    rc = run_headless(pipeline, verbose=False)
    # Assert: up's remaining phase is skipped, and the gates AROUND up still run
    assert _states(pipeline) == {
        "unit": StepState.OK,
        "image": StepState.OK,
        "up-preflight": StepState.FAILED,
        "up-deploy": StepState.SKIPPED,
        "accept": StepState.OK,
    }
    assert rc == 1


def test_a_true_root_aborts_the_whole_run_even_when_the_failure_is_in_a_false_subtree():
    """The reverse of the case above, and the reason an ancestor's `false` must not ABSORB a failure: it
    only declines to stop for it. A `bringup` that declared stop_on_failure would otherwise keep deploying
    after its own build died just because the build aggregate declared nothing."""
    # Arrange
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=True, build=False, up=False), "all"),
                     "up-preflight")
    # Act
    rc = run_headless(pipeline, verbose=False)
    # Assert: everything after the failure is skipped, up's own sibling gate included
    assert _states(pipeline) == {
        "unit": StepState.OK,
        "image": StepState.OK,
        "up-preflight": StepState.FAILED,
        "up-deploy": StepState.SKIPPED,
        "accept": StepState.SKIPPED,
    }
    assert rc == 1


def test_the_siblings_of_an_aborted_subtree_still_run():
    # Arrange: the unit gate dies inside a `true` build subtree; up and accept are build's siblings
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=False, build=True, up=True), "all"),
                     "unit")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: only build's own remainder is skipped
    assert _states(pipeline) == {
        "unit": StepState.FAILED,
        "image": StepState.SKIPPED,
        "up-preflight": StepState.OK,
        "up-deploy": StepState.OK,
        "accept": StepState.OK,
    }


def test_a_failure_with_no_ancestor_setting_the_flag_runs_every_remaining_step():
    """The negative case: nothing in the chain asks to stop, so nothing is skipped and the run still fails."""
    # Arrange
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=False, build=False, up=False), "all"),
                     "unit")
    # Act
    rc = run_headless(pipeline, verbose=False)
    # Assert
    assert all(state != StepState.SKIPPED for state in _states(pipeline).values())
    assert _states(pipeline)["unit"] == StepState.FAILED
    assert rc == 1


def test_each_flagged_subtree_aborts_only_its_own_remainder_when_two_of_them_fail():
    """Two independent failures in one run: each stops its own subtree, and the gate after both still runs.
    A single `stopped` latch cannot express this at all."""
    # Arrange
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=False, build=True, up=True), "all"),
                     "unit", "up-preflight")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert
    assert _states(pipeline) == {
        "unit": StepState.FAILED,
        "image": StepState.SKIPPED,
        "up-preflight": StepState.FAILED,
        "up-deploy": StepState.SKIPPED,
        "accept": StepState.OK,
    }


def test_the_walk_continues_past_the_nearest_flagged_ancestor_to_the_outermost_one():
    """The nearest ancestor aborts its subtree, and that abort is itself a failure its own parent sees. With
    both flags set the outer one therefore wins, which is the difference between "stop the phase" and "stop
    the run" being expressible in one manifest."""
    # Arrange: the inner aggregate AND the root both stop on failure
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=True, build=False, up=True), "all"),
                     "up-preflight")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: not just up-deploy - accept, which sits outside up entirely, is skipped too
    assert _states(pipeline)["up-deploy"] == StepState.SKIPPED
    assert _states(pipeline)["accept"] == StepState.SKIPPED


def test_a_leafs_own_stop_on_failure_is_rejected_at_load_rather_than_silently_scoping_to_nothing():
    """A leaf's subtree is the leaf, so the flag there could only ever skip nothing. That used to load
    cleanly and do nothing, which is the trap `keep_awake` and `hidden` are already rejected for; the walk
    would still be correct, so this pins the LOUD half. The message itself is pinned in test_manifest.py."""
    # Arrange: the flag on the LEAF, on no aggregate above it
    text = _with_flags(_GATES_MANIFEST, root=False, build=False, up=False).replace(
        'unit:  { impl: "demo.impls:unit",  help: "The unit gate." }',
        'unit:  { impl: "demo.impls:unit",  help: "The unit gate.", stop_on_failure: true }')
    # Act / Assert
    with pytest.raises(ValueError, match="stop_on_failure applies to an aggregate"):
        manifest_load(text)


def test_the_nearest_flagged_ancestor_leaves_its_own_sibling_running():
    # Arrange: three levels, the flag on the INNERMOST aggregate only
    pipeline = _fail(
        _planned(_with_flags(_NESTED_GATES_MANIFEST, root=False, mid=False, inner=True), "root"), "a1")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: only inner's own remainder goes; b1 (inner's sibling) and tail both run
    assert _states(pipeline) == {
        "a1": StepState.FAILED,
        "a2": StepState.SKIPPED,
        "b1": StepState.OK,
        "tail": StepState.OK,
    }


def test_a_flagged_middle_aggregate_takes_its_whole_subtree_and_not_the_step_after_it():
    # Arrange: the same three levels, the flag on the MIDDLE aggregate only
    pipeline = _fail(
        _planned(_with_flags(_NESTED_GATES_MANIFEST, root=False, mid=True, inner=False), "root"), "a1")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: mid's whole remainder (a2 AND b1) goes, tail runs
    assert _states(pipeline) == {
        "a1": StepState.FAILED,
        "a2": StepState.SKIPPED,
        "b1": StepState.SKIPPED,
        "tail": StepState.OK,
    }


def test_abort_after_names_the_subtree_that_stopped_so_a_ci_log_says_which_one(capsys):
    """The skip line is the only place a reader learns WHY a step did not run. "a previous step failed" was
    true when a failure stopped the run; with a subtree scope it would hide which subtree decided."""
    # Arrange
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=False, build=False, up=True), "all"),
                     "up-preflight")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert
    printed = capsys.readouterr().out
    assert "deploy.up stopped on a failure" in printed
    assert "deploy.up-deploy - skipped" in printed


def test_abort_after_reports_the_scope_and_the_doomed_step_indices():
    """The runners' shared answer, asserted directly: both a TUI thread and the headless loop consume it,
    so its shape is worth pinning independently of either runner."""
    # Arrange: leaves are unit, image, up-preflight, up-deploy, accept
    pipeline = _planned(_with_flags(_GATES_MANIFEST, root=False, build=False, up=True), "all")
    # Act
    abort = abort_after(pipeline, 2)          # up-preflight failed
    # Assert
    assert abort.scope == "deploy.up"
    assert abort.indices == frozenset({3})
    assert abort.reason == "deploy.up stopped on a failure"


def test_abort_after_reports_nothing_when_no_ancestor_of_the_failed_leaf_stops():
    # Arrange
    pipeline = _planned(_with_flags(_GATES_MANIFEST, root=False, build=True, up=False), "all")
    # Act: up-preflight failed, and only the BUILD subtree stops - which the failure is not in
    abort = abort_after(pipeline, 2)
    # Assert
    assert abort.indices == frozenset()
    assert abort.scope == ""
    assert abort.reason == "a previous step failed"


def test_a_tree_less_pipeline_keeps_the_single_flag_behaviour():
    """`doctor` and the other hand-built pipelines have no plan behind them, so the pipeline-wide flag is
    the only expression of intent there and must keep meaning exactly what it meant."""
    # Arrange
    stopping = Pipeline("doctor", [_step("a", 0), _step("b", 1), _step("c", 0), _step("d", 0)],
                        stop_on_failure=True)
    running = Pipeline("doctor", [_step("a", 0), _step("b", 1), _step("c", 0), _step("d", 0)],
                       stop_on_failure=False)
    # Act
    run_headless(stopping, verbose=False)
    run_headless(running, verbose=False)
    # Assert: true skips the WHOLE tail, false runs it
    assert [s.state for s in stopping.steps[2:]] == [StepState.SKIPPED, StepState.SKIPPED]
    assert [s.state for s in running.steps[2:]] == [StepState.OK, StepState.OK]


def test_a_tree_the_pairing_guard_rejects_falls_back_to_the_pipelines_own_flag():
    """A display-level degrade must not silently change EXECUTION semantics in either direction. The guard
    that drops the tree for `build_rows` drops it here too, so the run falls back to the same single flag a
    tree-less pipeline uses - never to subtree flags read off a tree that cannot be trusted to pair with
    the steps that actually run."""
    # Arrange: a plan whose subtrees BOTH stop on failure, against a step list the guard rejects (three
    # steps for five leaves), and a pipeline flag of false
    tree = manifest_load(_with_flags(_GATES_MANIFEST, root=False, build=True, up=True)).plan_tree_for("all")
    pipeline = Pipeline("all", [_step("unit", 1), _step("image", 0), _step("accept", 0)], False,
                        tree, tree.path)
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: the subtree flags are NOT consulted, so nothing is skipped
    assert [s.state for s in pipeline.steps] == [StepState.FAILED, StepState.OK, StepState.OK]


def test_a_rejected_tree_still_stops_the_run_when_the_pipeline_flag_says_so():
    """The other half of the fallback: degrading must not lose a stop that the single flag does ask for."""
    # Arrange: the same rejected pairing, this time with the pipeline flag set
    tree = manifest_load(_with_flags(_GATES_MANIFEST, root=True, build=False, up=False)).plan_tree_for("all")
    pipeline = Pipeline("all", [_step("unit", 1), _step("image", 0), _step("accept", 0)], True,
                        tree, tree.path)
    # Act
    run_headless(pipeline, verbose=False)
    # Assert
    assert [s.state for s in pipeline.steps] == [StepState.FAILED, StepState.SKIPPED, StepState.SKIPPED]


def test_a_doomed_steps_action_is_never_invoked_and_not_merely_marked_skipped():
    """SKIPPED is the state; not running is the POINT. Asserting the state alone would still pass over a
    runner that ran the doomed work and relabelled it afterwards, which is the entire cost this flag
    exists to avoid - forty minutes of deploying a stale image, marked skipped."""
    # Arrange: record every action that is actually entered
    ran: list[str] = []
    tree = manifest_load(_with_flags(_GATES_MANIFEST, root=False, build=True, up=False)).plan_tree_for("all")
    steps = [Step(label=leaf.name, command=leaf.path,
                  action=lambda name=leaf.name: (ran.append(name),
                                                 Outcome(rc=1 if name == "unit" else 0, output=""))[1])
             for leaf in tree.leaves()]
    pipeline = Pipeline("all", steps, tree.spec.stop_on_failure, tree, tree.path)
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: `image` was never entered, and carries none of the traces a run leaves behind
    assert ran == ["unit", "up-preflight", "up-deploy", "accept"]
    assert pipeline.steps[1].label == "image"
    assert pipeline.steps[1].state == StepState.SKIPPED
    assert pipeline.steps[1].rc is None and pipeline.steps[1].output == ""


def test_a_tree_whose_steps_name_nothing_falls_back_to_the_pipelines_own_flag():
    """The count and the order are right, but no step carries its identity, so the kernel cannot VERIFY the
    pairing. It must not scope a failure by a tree it cannot check: the probe that reversed such steps
    skipped `build.image` for a failure inside `deploy.up`, a subtree it is not even in."""
    # Arrange: the up subtree says stop, the pipeline's own flag says do not
    tree = manifest_load(_with_flags(_GATES_MANIFEST, root=False, build=False, up=True)).plan_tree_for("all")
    pipeline = Pipeline("all", [_step(leaf.name, rc=1 if leaf.name == "up-preflight" else 0)
                                for leaf in tree.leaves()], False, tree, tree.path)
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: no subtree flag was read at all
    assert _states(pipeline)["up-deploy"] == StepState.OK
    assert all(state != StepState.SKIPPED for state in _states(pipeline).values())


def test_the_degrade_to_the_flat_shape_says_out_loud_that_the_stop_scopes_went_with_it(capsys):
    """The degrade used to be silent, and with a `false` root that silently reinstates the very defect this
    change fixes: every subtree flag dropped, nothing skipped, and the only signal a flat-looking tree. The
    warning names the safety half, not merely the display shape."""
    # Arrange: a plan whose subtrees stop on failure, against a step list the guard rejects
    tree = manifest_load(_with_flags(_GATES_MANIFEST, root=False, build=True, up=True)).plan_tree_for("all")
    pipeline = Pipeline("all", [_command_step("build.unit", rc=1)], False, tree, tree.path)
    # Act
    run_headless(pipeline, verbose=False)
    # Assert
    printed = capsys.readouterr().out
    assert "does not pair with the steps that will run" in printed
    assert "stop_on_failure is dropped" in printed
    assert "nothing is skipped" in printed


def test_a_usable_tree_degrades_nothing_and_therefore_warns_about_nothing(capsys):
    """The negative case for the warning: a well-paired plan must not cry wolf on every single run."""
    # Arrange
    pipeline = _fail(_planned(_with_flags(_GATES_MANIFEST, root=False, build=True, up=True), "all"), "unit")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert
    assert "does not pair" not in capsys.readouterr().out


def test_the_pairing_verdict_is_computed_once_for_display_and_execution_alike(capsys):
    """Three evaluations over a mutable step list is three chances to disagree, and a run whose printed
    tree says one thing while its skipping does another is worse than either failing alone. One verdict,
    remembered - which a single warning for a run that asks from both sides is the visible proof of."""
    # Arrange: a rejected pairing, in a run that fails (execution asks) and then prints its tree (display)
    tree = manifest_load(_with_flags(_GATES_MANIFEST, root=True, build=False, up=False)).plan_tree_for("all")
    pipeline = Pipeline("all", [_command_step("build.unit", rc=1), _command_step("build.image")], True,
                        tree, tree.path)
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: warned once, and the verdict is stable however often it is asked afterwards
    assert capsys.readouterr().out.count("does not pair with the steps") == 1
    assert pipeline.usable_tree() is None and pipeline.usable_tree() is None


def test_an_abort_that_skips_nothing_cannot_name_a_subtree():
    """`reason` would otherwise announce that some node stopped a run in which nothing was stopped."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="must not name a scope"):
        Abort(scope="deploy.up", indices=frozenset())


def test_a_failure_in_the_last_leaf_of_a_flagged_subtree_is_no_abort_at_all():
    """The reachable shape behind that invariant: the flagged node has no remainder left to abort."""
    # Arrange: build stops on failure, and its LAST leaf (image, index 1) is the one that fails
    pipeline = _planned(_with_flags(_GATES_MANIFEST, root=False, build=True, up=False), "all")
    # Act
    abort = abort_after(pipeline, 1)
    # Assert
    assert abort.indices == frozenset()
    assert abort.scope == ""


# A dependency reached along several paths is planned at its FIRST occurrence, so `late` below declares
# `aot` but does not carry it: `early` got there first. EARLY_FLAG is the placeholder `_with_flags` fills:
# false makes the two declarers of `aot` disagree, which loader rule 6 rejects (netctl#1319); true makes
# them agree, which loads and leaves the relocation in place.
#
#     run.root
#       build.early          <- EARLY_FLAG, plans jar and aot
#         build.jar
#         build.aot
#       build.late           <- stop_on_failure, declares aot, carries only image
#         build.image
_RELOCATED_DEP_MANIFEST = """
groups:
  build:
    jar:   { impl: "demo.impls:jar",   help: "Build the jar." }
    aot:   { impl: "demo.impls:aot",   help: "The shared dependency." }
    image: { impl: "demo.impls:image", help: "Build the image." }
    early: { help: "Planned first.", depends_on: [jar, aot], stop_on_failure: EARLY_FLAG }
    late:  { help: "Declares aot too.", depends_on: [aot, image], stop_on_failure: true }
  run:
    root: { help: "The whole run.", depends_on: [early, late] }
env_groups: [run]
"""


def test_a_relocated_dependency_whose_declarers_disagree_never_reaches_the_runner():
    """The limitation `abort_after` names, closed at the manifest boundary (netctl#1319).

    `plan_tree_for` is a DFS SPANNING tree, so `aot` is planned under `early`, which reached it first, and
    `late` carries no node for it. `abort_after` walks the tree, so `late` is not on the failed leaf's chain
    and would not stop for the failure of a dependency it declared. Rather than change what a plan tree IS,
    loader rule 6 rejects the shape: `early` and `late` sit in ONE plan (`run.root`) and disagree over
    `aot`."""
    # Arrange / Act / Assert: the pipeline cannot even be built, because the manifest does not load
    with pytest.raises(ValueError, match="both declare dependency 'aot' but disagree on stop_on_failure"):
        _planned(_with_flags(_RELOCATED_DEP_MANIFEST, early=False), "root")


def test_a_relocated_dependency_between_agreeing_declarers_keeps_the_scope_of_whoever_carries_it():
    """The case netctl#1319 deliberately leaves open, pinned so the full cure notices when it moves.

    With both declarers flagged the manifest loads, and `aot` is still planned under `early` alone. The
    failure is therefore caught by `early`, whose remainder is empty, so `late`'s own subtree runs even
    though `late` declared the leaf that died. No declarer's POLICY is contradicted here - both asked to
    stop - only the scope is narrower than `late` intended, which is why the guard rejects disagreement
    and not relocation itself. Scoping the abort by the declaration graph is what would close it."""
    # Arrange: aot fails, with both aggregates that declared it stopping on failure
    pipeline = _fail(_planned(_with_flags(_RELOCATED_DEP_MANIFEST, early=True), "root"), "aot")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: `image`, which IS in late's subtree, still runs
    assert _states(pipeline) == {
        "jar": StepState.OK,
        "aot": StepState.FAILED,
        "image": StepState.OK,
    }


# The same hazard one level up, which rule 6 does NOT see: `first` and `mid` both declare `shared` and
# both default to false, so the guard compares two falses and passes - while the flag that matters sits on
# `guarded`, an ANCESTOR of `mid` rather than a declarer.
#
#     run.root
#       gate.first           <- plans shared
#         gate.shared
#       gate.guarded         <- stop_on_failure, ancestor of a declarer of shared
#         gate.mid           <- declares shared, carries only other
#           gate.other
#       gate.later
_ANCESTOR_FLAG_MANIFEST = """
groups:
  gate:
    shared:  { impl: "demo.impls:shared", help: "The shared dependency." }
    other:   { impl: "demo.impls:other",  help: "What the guard protects." }
    later:   { impl: "demo.impls:later",  help: "A step after the guard." }
    first:   { help: "Planned first.", depends_on: [shared] }
    mid:     { help: "Declares shared too.", depends_on: [shared, other] }
    guarded: { help: "Wants to stop.", depends_on: [mid], stop_on_failure: true }
  run:
    root: { help: "The whole run.", depends_on: [first, guarded, later] }
env_groups: [run]
"""


def test_a_flag_contradicted_through_an_ancestor_of_a_declarer_survives_the_guard_documents_a_limitation():
    """DOCUMENTS A KNOWN LIMITATION, it does not endorse it (netctl#1319, option 2 is the cure).

    Loader rule 6 compares each DIRECT declarer's own flag. Here both declarers of `shared` are unflagged,
    so the manifest loads - and the aggregate that really asked to stop, `guarded`, is an ANCESTOR of one
    of them. `shared` is planned under `first`, `guarded` is not on that leaf's chain, and its subtree runs
    although the leaf its own subtree declared has died. That is netctl#1319's opening paragraph one level
    up. Extending rule 6 to EFFECTIVE policy would make the comparison per plan and per declarer, which is
    the declaration-graph scoping this ticket defers; pinning the behaviour means that change will notice
    when it moves."""
    # Arrange: the manifest loads (the guard stays silent), and shared - planned under `first` - fails
    pipeline = _fail(_planned(_ANCESTOR_FLAG_MANIFEST, "root"), "shared")
    # Act
    run_headless(pipeline, verbose=False)
    # Assert: nothing is aborted at all, so `other` runs inside the subtree `guarded` claimed to guard
    assert abort_after(pipeline, 0) == Abort(scope="", indices=frozenset())
    assert _states(pipeline) == {
        "shared": StepState.FAILED,
        "other": StepState.OK,
        "later": StepState.OK,
    }
