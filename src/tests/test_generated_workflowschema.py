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


def test_runner_kinds_are_exactly_the_two_measured_kinds():
    # act
    kinds = tuple(workflowschema.RUNNER_KINDS)

    # assert: in model order, and not empty - an empty table is what a selector answering nothing writes
    assert kinds == ("github-ubuntu", "self-hosted-debian")


def test_each_runner_kind_carries_todays_values():
    # act
    table = workflowschema.RUNNER_KINDS

    # assert
    assert table["github-ubuntu"] == GITHUB_UBUNTU
    assert table["self-hosted-debian"] == SELF_HOSTED_DEBIAN


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
    assert fields == ["runner", "step", "needs", "matrix", "condition", "timeout_minutes"]
    assert workflowschema.Job.__dataclass_params__.frozen
