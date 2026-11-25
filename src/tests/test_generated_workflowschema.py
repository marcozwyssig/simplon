"""si#857: the workflow vocabulary and the runner kinds are a WHOLE module firn writes from the model.

The module has no protected region, so nothing in it survives a bad run, and firn has written an empty module
with rc 0 before (si#344 B2's measurement). Every property is pinned here, on the committed file, without docker.
The runner kinds are compared against LITERAL values (today's, moved from runners.py's hand-typed table), not
against `runners.TABLE`, which is built from this module and would agree with anything.

AAA; the name states the behaviour under test.
"""
import dataclasses
import re
from pathlib import Path

from simplon.model import workflowschema
from simplon.model.workflowschema import RunnerEnv, RunnerKind

WORKFLOW_MODEL = Path(__file__).resolve().parents[1] / "firn" / "model" / "simplon" / "workflow" / "workflow.firn"

GITHUB_UBUNTU = RunnerKind(
    labels=("ubuntu-latest",), setup_python=True, disk_persists=False, can_emulate=True,
    why="GitHub-hosted Ubuntu: `actions/setup-python` unpacks an interpreter here, and docker is already on the "
        "machine.",
    env=())
SELF_HOSTED_DEBIAN = RunnerKind(
    labels=(), setup_python=False, disk_persists=True, can_emulate=True,
    why="A self-hosted Debian machine. `actions/setup-python` unpacks prebuilt archives and carries none for "
        "Debian, so the runner's own python3 is what the launcher builds its venv with; docker is reached through "
        "the bootstrap, because a container job would need docker in order to start.",
    env=(RunnerEnv(env_name="DELIVERY_DOCKER_BOOTSTRAP", env_value="1"),))
SELF_HOSTED_CONTAINER = RunnerKind(
    labels=(), setup_python=False, disk_persists=True, can_emulate=False,
    why="A self-hosted runner that is itself an LXC container. Python and docker are reached as on a self-hosted "
        "Debian machine; emulation cannot be registered from inside a job, because "
        "`/proc/sys/fs/binfmt_misc/register` is refused there (si#358, #722), so it is registered once by hand with "
        "`support:ci-arm64`.",
    env=(RunnerEnv(env_name="DELIVERY_DOCKER_BOOTSTRAP", env_value="1"),))


def test_runner_kinds_are_exactly_the_measured_kinds():
    # act
    kinds = tuple(workflowschema.RUNNER_KINDS)

    # assert: in model order, and not empty - an empty table is what a selector answering nothing writes
    assert kinds == ("github-ubuntu", "self-hosted-debian", "self-hosted-container")


def test_each_runner_kind_carries_todays_values():
    # act
    table = workflowschema.RUNNER_KINDS

    # assert
    assert table["github-ubuntu"] == GITHUB_UBUNTU
    assert table["self-hosted-debian"] == SELF_HOSTED_DEBIAN
    assert table["self-hosted-container"] == SELF_HOSTED_CONTAINER


def test_every_metamodel_class_has_a_generated_dataclass():
    # arrange
    names = re.findall(r"^(\w+) typeOf firn\.core\.Class", WORKFLOW_MODEL.read_text(encoding="utf-8"), re.M)
    assert names, "the model regex found no classes - the comparison below would rule on nothing"

    # act
    generated = {name for name, obj in vars(workflowschema).items()
                 if isinstance(obj, type) and dataclasses.is_dataclass(obj)}

    # assert
    assert generated == set(names)


def test_job_fields_follow_the_model_and_the_class_is_frozen():
    # act
    fields = [f.name for f in dataclasses.fields(workflowschema.Job)]

    # assert
    assert fields == ["key", "runner", "step", "needs", "matrix", "condition", "timeout_minutes", "gate", "env", "merge",
                      "concurrency", "starts_no_container", "permission", "environment", "no_checkout"]
    assert workflowschema.Job.__dataclass_params__.frozen


def test_job_carries_a_gate_and_env():
    """si#861: the decide job carries the gate, the gated job its literal env; any other job carries neither."""
    # arrange
    runner = workflowschema.Runner(kind=GITHUB_UBUNTU)
    gate = workflowschema.Gate(paths=("src/**",), label="needs-lab", pattern="^src/.*")
    env = (RunnerEnv(env_name="NETCTL_MGMT_SUBNET", env_value="10.128.0.0/24"),)

    # act
    gated = workflowschema.Job(key="decide", runner=runner, gate=gate, env=env)
    plain = workflowschema.Job(key="main", runner=runner)

    # assert
    assert gated.gate == gate and gated.env == env
    assert plain.gate is None and plain.env == ()


def test_a_job_carries_the_key_github_names_it_by():
    """si#858: `jobs:` and `needs:` read GitHub's job id, which no other property of Job carries."""
    # act
    key = {f.name: f for f in dataclasses.fields(workflowschema.Job)}.get("key")

    # assert
    assert key is not None, "Job has no field `key`"
    assert key.type in (str, "str")
    assert key.default is dataclasses.MISSING and key.default_factory is dataclasses.MISSING


def _model_properties() -> dict[str, list[str]]:
    """Each class of workflow.firn -> its own property names, in declaration order."""
    text = WORKFLOW_MODEL.read_text(encoding="utf-8")
    classes = re.split(r"^(?=\w+ typeOf firn\.core\.Class)", text, flags=re.M)[1:]
    found = {block.split()[0]: re.findall(r"^\s+property (\w+) typeOf", block, re.M) for block in classes}
    assert found and all(found.values()), "the model parse found no class or a class with no property"
    return found


def test_every_model_property_is_a_field_of_its_dataclass():
    """The template writes a field only for the ranges and cardinalities it has a branch for, and drops any
    other property with rc 0 - `test generated` stays green, because regenerating writes the same short file.
    So every class's fields are held to the model's own property list, not only Job's."""
    # arrange
    model = _model_properties()

    # act
    generated = {name: [f.name for f in dataclasses.fields(getattr(workflowschema, name))] for name in model}

    # assert
    assert generated == model
