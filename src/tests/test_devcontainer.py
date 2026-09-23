"""Unit tests for simplon.devcontainer - the second backend the kernel ships.

No Docker and no network: `run` and `stream` are the two seams, and every case here replaces them. What
is asserted is the argv the backend builds, the refusals it gives, and the fact that a teardown finds its
containers BY LABEL rather than by a name this module invents.
"""
import pytest

from simplon import context, devcontainer
from simplon.deployment import Version
from simplon.environments import Environment
from simplon.run import Result

_ENV = Environment("dev", devcontainer.BACKEND, "The development container.")
_LOCAL = Version(selector="local", tag="", builds=True)
_PUBLISHED = Version(selector="1.4.0", tag="1.4.0", builds=False)


@pytest.fixture
def described(tmp_path, monkeypatch):
    """A product root that describes a devcontainer, registered the way the CLI registers one."""
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text('{"image": "alpine"}')
    monkeypatch.setattr(devcontainer, "_root", lambda: tmp_path)
    monkeypatch.setattr(devcontainer.docker, "ensure_docker", lambda: None)
    monkeypatch.setattr(devcontainer, "cli", lambda: ["devcontainer"])
    return tmp_path


def test_up_runs_the_specifications_own_cli_against_the_workspace_folder(described, monkeypatch):
    # arrange
    seen: list[list[str]] = []
    monkeypatch.setattr(devcontainer, "stream", lambda argv: seen.append(argv) or 0)

    # act
    rc = devcontainer.DevcontainerBackend().deploy(_ENV, _LOCAL)

    # assert: the reference CLI, the workspace folder, and nothing about an editor
    assert rc == 0
    assert seen == [["devcontainer", "up", "--workspace-folder", str(described)]]
    assert not any("code" in part or "vscode" in part for part in seen[0])


def test_up_refuses_a_published_version_and_says_which_word_to_use(described):
    # act / assert: a devcontainer runs the working tree; a tag names something else entirely
    with pytest.raises(ValueError) as refused:
        devcontainer.DevcontainerBackend().deploy(_ENV, _PUBLISHED)
    assert "1.4.0" in str(refused.value)
    assert "`local`" in str(refused.value)


def test_up_refuses_a_repository_that_describes_no_container_and_names_the_file(tmp_path, monkeypatch):
    # arrange: an environment pointing at this backend, in a tree with no specification
    monkeypatch.setattr(devcontainer, "_root", lambda: tmp_path)

    # act / assert
    with pytest.raises(ValueError) as refused:
        devcontainer.DevcontainerBackend().deploy(_ENV, _LOCAL)
    assert str(tmp_path / devcontainer.SPEC) in str(refused.value)
    assert "containers.dev" in str(refused.value)


def test_down_removes_what_the_bring_up_labelled(described, monkeypatch):
    # arrange: two containers carry this folder's label
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "ps" in argv:
            return Result(rc=0, out="abc123\ndef456\n", err="")
        return Result(rc=0, out="", err="")

    monkeypatch.setattr(devcontainer, "run", fake_run)

    # act
    rc = devcontainer.DevcontainerBackend().destroy(_ENV)

    # assert: found by LABEL, removed by id
    assert rc == 0
    assert f"label={devcontainer.LABEL}={described}" in calls[0]
    assert calls[-1] == ["docker", "rm", "--force", "abc123", "def456"]


def test_down_over_nothing_is_green_and_says_so(described, monkeypatch):
    # arrange: no container carries the label
    monkeypatch.setattr(devcontainer, "run", lambda argv, **kw: Result(rc=0, out="", err=""))

    # act
    rc = devcontainer.DevcontainerBackend().destroy(_ENV)

    # assert: nothing to do is not a failure
    assert rc == 0


def test_status_tells_a_described_environment_from_a_running_one(described, monkeypatch):
    # arrange
    monkeypatch.setattr(devcontainer, "run", lambda argv, **kw: Result(rc=0, out="", err=""))

    # act
    described_only = devcontainer.DevcontainerBackend().status(_ENV)

    # assert
    assert "not running" in described_only


def test_the_cli_refusal_names_the_command_that_installs_it(monkeypatch):
    # arrange: neither the CLI nor npx is on this machine
    monkeypatch.setattr(devcontainer.shutil, "which", lambda name: None)

    # act / assert
    with pytest.raises(ValueError) as refused:
        devcontainer.cli()
    assert "npm install -g @devcontainers/cli" in str(refused.value)


def test_npx_is_taken_when_the_cli_itself_is_not_installed(monkeypatch):
    # arrange
    monkeypatch.setattr(devcontainer.shutil, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)

    # act
    argv = devcontainer.cli()

    # assert
    assert argv == ["/usr/bin/npx", "--yes", "@devcontainers/cli"]


def test_the_kernel_ships_it_beside_portainer():
    # arrange / act: the registry the deploy commands resolve against
    from simplon.tasks import deploy

    shipped = deploy.drivable_backends()

    # assert: two, and this one answers to its own tag
    assert shipped[devcontainer.BACKEND].name == devcontainer.BACKEND
    assert "portainer" in shipped
