# GENERATED from src/firn/model/simplon/workflow/workflow.firn (the classes) and runners.firn (the runner
# kinds) by `./simplon.sh build model`. Do not edit: firn rewrites the whole file on every run, and this
# file has no protected region. If it is missing or empty, every `./simplon.sh` command stops at import:
# `git checkout -- src/simplon/model/workflowschema.py`.
"""The vocabulary of a derived GitHub workflow (si#857), and the runner kinds the kernel knows (si#267)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class RunnerKind:
    """simplon.workflow.RunnerKind."""

    labels: tuple[str, ...] = ()
    setup_python: bool
    disk_persists: bool
    can_emulate: bool
    why: str
    env: tuple[RunnerEnv, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Platform:
    """simplon.workflow.Platform."""

    label: str
    arch: str
    shell: str
    windows: bool


@dataclass(frozen=True, kw_only=True)
class RunnerEnv:
    """simplon.workflow.RunnerEnv."""

    env_name: str
    env_value: str


@dataclass(frozen=True, kw_only=True)
class Runner:
    """simplon.workflow.Runner."""

    kind: RunnerKind
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Trigger:
    """simplon.workflow.Trigger."""

    event: str
    cron: str = ""
    dispatch_input: tuple[DispatchInput, ...] = ()
    workflows: tuple[str, ...] = ()
    types: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DispatchInput:
    """simplon.workflow.DispatchInput."""

    input_name: str
    description: str
    input_type: str
    required: bool
    default_value: str = ""


@dataclass(frozen=True, kw_only=True)
class DeployEnvironment:
    """simplon.workflow.DeployEnvironment."""

    environment_name: str
    url: str = ""


@dataclass(frozen=True, kw_only=True)
class Permission:
    """simplon.workflow.Permission."""

    scope: str
    access: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class Matrix:
    """simplon.workflow.Matrix."""

    platform: tuple[str, ...] = ()
    python: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Step:
    """simplon.workflow.Step."""

    command: object = None
    kernel_step: str = ""
    timeout_minutes: int | None = None
    params: tuple[StepParam, ...] = ()
    condition: str = ""
    env: tuple[RunnerEnv, ...] = ()
    step_id: str = ""


@dataclass(frozen=True, kw_only=True)
class StepParam:
    """simplon.workflow.StepParam."""

    param_name: str
    param_value: str = ""
    param_env: str = ""


@dataclass(frozen=True, kw_only=True)
class Gate:
    """simplon.workflow.Gate."""

    paths: tuple[str, ...] = ()
    label: str = ""
    pattern: str = ""


@dataclass(frozen=True, kw_only=True)
class Merge:
    """simplon.workflow.Merge."""

    ci_workflow: str
    triggers: tuple[str, ...] = ()
    derived_gates: tuple[str, ...] = ()
    labels: tuple[GateLabel, ...] = ()


@dataclass(frozen=True, kw_only=True)
class GateLabel:
    """simplon.workflow.GateLabel."""

    workflow: str
    label: str


@dataclass(frozen=True, kw_only=True)
class Job:
    """simplon.workflow.Job."""

    key: str
    runner: Runner
    step: tuple[Step, ...] = ()
    needs: tuple[Job, ...] = ()
    matrix: Matrix | None = None
    condition: str = ""
    timeout_minutes: int | None = None
    gate: Gate | None = None
    env: tuple[RunnerEnv, ...] = ()
    merge: Merge | None = None
    concurrency: str = ""
    starts_no_container: bool = False
    permission: tuple[Permission, ...] = ()
    environment: DeployEnvironment | None = None
    no_checkout: bool = False


@dataclass(frozen=True, kw_only=True)
class Workflow:
    """simplon.workflow.Workflow."""

    path: str
    title: str
    trigger: tuple[Trigger, ...] = ()
    job: tuple[Job, ...] = ()
    permission: tuple[Permission, ...] = ()


@dataclass(frozen=True, kw_only=True)
class WorkflowException:
    """simplon.workflow.WorkflowException."""

    path: str
    reason: str


#: Each runner kind -> what follows from it, keyed by the kernel's spelling, in model order.
RUNNER_KINDS: dict[str, RunnerKind] = {
    "github-ubuntu": RunnerKind(
        labels=("ubuntu-latest", ),
        setup_python=True,
        disk_persists=False,
        can_emulate=True,
        why="GitHub-hosted Ubuntu: `actions/setup-python` unpacks an interpreter here, and docker is already on the machine.",
        env=(),
    ),
    "self-hosted-debian": RunnerKind(
        labels=(),
        setup_python=False,
        disk_persists=True,
        can_emulate=True,
        why="A self-hosted Debian machine. `actions/setup-python` unpacks prebuilt archives and carries none for Debian, so the runner's own python3 is what the launcher builds its venv with; docker is reached through the bootstrap, because a container job would need docker in order to start.",
        env=(RunnerEnv(env_name="DELIVERY_DOCKER_BOOTSTRAP", env_value="1"), ),
    ),
    "self-hosted-container": RunnerKind(
        labels=(),
        setup_python=False,
        disk_persists=True,
        can_emulate=False,
        why="A self-hosted runner that is itself an LXC container. Python and docker are reached as on a self-hosted Debian machine; emulation cannot be registered from inside a job, because `/proc/sys/fs/binfmt_misc/register` is refused there (si#358, #722), so it is registered once by hand with `support:ci-arm64`.",
        env=(RunnerEnv(env_name="DELIVERY_DOCKER_BOOTSTRAP", env_value="1"), ),
    ),
}


#: Each platform cell a leaf's `platforms:` may name (si#860), keyed by the kernel's spelling, in model order.
PLATFORMS: dict[str, Platform] = {
    "linux-x64": Platform(label="ubuntu-24.04", arch="x86_64", shell="bash", windows=False),
    "linux-arm64": Platform(label="ubuntu-24.04-arm", arch="aarch64", shell="bash", windows=False),
    "macos-x64": Platform(label="macos-15-intel", arch="x86_64", shell="bash", windows=False),
    "macos-arm64": Platform(label="macos-15", arch="arm64", shell="bash", windows=False),
    "windows-x64": Platform(label="windows-2025", arch="x86_64", shell="cmd", windows=True),
}
# Generated by firn, do not edit outside protected regions. id=[WorkflowSchema:,d799fb7b17fd2fed]
