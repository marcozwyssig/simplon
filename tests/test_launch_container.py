"""The launcher's second route: the kernel as a container (si#199/si#201).

DRIVEN, NOT READ. The interesting half of this route is an argv a shell assembles, so the tests below
scaffold a product, put a fake `docker` on PATH that records what it was called with, and run the real
launcher. Asserting on the template's text would pass for a launcher that never dispatches.

WHAT THE FAKE PROVES AND WHAT IT DOES NOT. It proves the flags, the mounts and the environment the
launcher writes - which is where si#201's whole problem lives, because a wrong `-v` source is silent: the
daemon creates an empty directory on the host and mounts that, rc 0. It does not prove that the image
exists or that the kernel inside it runs; that is what the both-routes gate run in the ticket did.

THE BATCH LAUNCHER IS HELD AS TEXT, and that is the evidence split this repository already keeps for the
CRLF policy: there is no Windows here, so what can be asserted is that the two files declare the same
contract - the same parameters, the same mount destinations, the same environment names - and the rest
is inherited.
"""
import os
import subprocess
from pathlib import Path

import pytest

from simplon import bootstrap

#: A pinned reference of the shape `docker.pinned_image` accepts, standing in for a published kernel.
PINNED = "registry.example:5000/simplon:v0.13.0"


def _fake_docker(bin_dir: Path, log: Path) -> None:
    """A `docker` on PATH that records its argv, one invocation per line, and succeeds."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "docker"
    script.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$DOCKER_LOG"\nexit 0\n',
                      encoding="utf-8")
    script.chmod(0o755)


def _product(tmp_path: Path, *, pin: str | None = PINNED) -> Path:
    """A scaffolded product with a kernel image pinned beside its Dockerfile (or none, when pin is None)."""
    bootstrap.write("democtl", tmp_path)
    if pin is not None:
        pin_file = tmp_path / "deploy" / "image" / "image.pin"
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        pin_file.write_text(f"# a comment the reader is meant to skip\n\n{pin}\n", encoding="utf-8")
    return tmp_path


def _run(root: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the scaffolded launcher with a fake docker on PATH and the real one out of reach."""
    log = root / "docker.log"
    bin_dir = root / "fakebin"
    _fake_docker(bin_dir, log)
    environ = {**os.environ,
               "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               "DOCKER_LOG": str(log),
               "DELIVERY_ROUTE": "container"}
    environ.update(env or {})
    done = subprocess.run(["bash", str(root / "democtl.sh"), *args],
                          capture_output=True, text=True, env=environ)
    done.docker = log.read_text(encoding="utf-8").splitlines() if log.exists() else []   # type: ignore
    return done


# --- the route is taken, and it carries the pin ---------------------------------------------------------


def test_the_container_route_runs_the_pinned_image_with_the_product_module(tmp_path):
    # arrange
    root = _product(tmp_path)

    # act
    done = _run(root, "support", "doctor")

    # assert: the last docker invocation is the CLI itself, in the image the pin names
    assert done.returncode == 0, done.stderr
    last = done.docker[-1]
    assert PINNED in last
    assert "python -u -m orchestrator support doctor" in last


def test_the_tree_is_mounted_at_src_and_the_host_path_travels_with_it(tmp_path):
    # arrange: the whole of si#201. The kernel is about to start sibling containers through the mounted
    # socket, and the daemon resolves THEIR `-v` sources against the host - so the launcher has to say
    # where the mount really is, because nothing inside the container can find out cheaply
    root = _product(tmp_path)

    # act
    done = _run(root, "support", "doctor")

    # assert
    last = done.docker[-1]
    assert f"-v {root}:/src" in last
    assert "-w /src" in last
    assert f"-e DELIVERY_HOST_ROOT={root}" in last
    assert "-e DELIVERY_MOUNT_ROOT=/src" in last


def test_the_products_own_dependencies_are_installed_into_the_mount_before_the_command_runs(tmp_path):
    # arrange: the image carries the KERNEL and nothing of any product (si#200/si#121), so `pytest`,
    # `build` and whatever else the product's requirements name are still this checkout's to provide
    root = _product(tmp_path)

    # act
    done = _run(root, "support", "doctor")

    # assert: two invocations, install first, and the install lands under build/ rather than in the venv
    assert len(done.docker) == 2, done.docker
    assert "pip install --user" in done.docker[0]
    assert "requirements.txt" in done.docker[0]
    assert "-e PYTHONUSERBASE=/src/build/container/python" in done.docker[0]


def test_the_dependency_install_is_skipped_once_the_stamp_is_newer_than_the_requirements(tmp_path):
    # arrange: the same condition the venv route uses, so neither route pays a pip resolve per call
    root = _product(tmp_path)
    _run(root, "support", "doctor")
    (root / "docker.log").unlink()

    # act
    done = _run(root, "support", "doctor")

    # assert
    assert len(done.docker) == 1, done.docker
    assert "pip install" not in done.docker[0]


# --- the TTY, which CI does not have ---------------------------------------------------------------------


def test_no_tty_means_no_dash_t_because_docker_refuses_one_that_is_not_there(tmp_path):
    # arrange: pytest's subprocess has no terminal, which is also what a CI runner is. `docker run -t`
    # without one fails outright with "the input device is not a TTY", so the flag has to be conditional
    # - and the headless path is then reached exactly as it is on the venv route, through the TUI's own
    # `sys.stdout.isatty()` check inside the container
    root = _product(tmp_path)

    # act
    done = _run(root, "support", "doctor")

    # assert: interactive stdin is always attached (a pipe must still reach the CLI), a terminal is not
    last = done.docker[-1]
    assert " -i " in f" {last} "
    assert " -t " not in f" {last} "


# --- the refusals ----------------------------------------------------------------------------------------


def test_a_checkout_with_no_pin_is_told_it_has_no_container_route(tmp_path):
    # arrange: si#200's contract, inherited. No line means nothing is published, which is a statement
    # rather than a gap - and the launcher must say which route DOES work
    root = _product(tmp_path, pin=None)

    # act
    done = _run(root, "support", "doctor")

    # assert
    assert done.returncode == 1
    assert "no container route" in done.stderr
    assert "DELIVERY_ROUTE=venv" in done.stderr


def test_a_pin_file_that_is_all_comments_counts_as_no_pin(tmp_path):
    # arrange: which is exactly the file si#200 committed - the rule has to be the reference-or-nothing
    # one, not the file-exists one
    root = _product(tmp_path, pin=None)
    pin = root / "deploy" / "image" / "image.pin"
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text("# there is no line yet, and that is a statement\n\n   \n", encoding="utf-8")

    # act
    done = _run(root, "support", "doctor")

    # assert
    assert done.returncode == 1 and "no container route" in done.stderr


def test_an_unknown_route_is_refused_by_name(tmp_path):
    # arrange
    root = _product(tmp_path)

    # act
    done = _run(root, "support", "doctor", env={"DELIVERY_ROUTE": "docker"})

    # assert
    assert done.returncode == 1
    assert "venv, container, auto, inside" in done.stderr


def test_a_linked_git_worktree_is_refused_rather_than_left_to_fail_inside(tmp_path):
    # arrange: measured. Such a checkout's `.git` is a FILE naming a gitdir under the MAIN checkout,
    # which is outside the mount, so `git log` in the container answers `fatal: not a git repository`
    # and the release-notes guard, `release tag` and any editable install of the tree go with it
    root = _product(tmp_path)
    (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")

    # act
    done = _run(root, "support", "doctor")

    # assert
    assert done.returncode == 1
    assert "LINKED GIT WORKTREE" in done.stderr
    assert "/elsewhere/.git/worktrees/wt" in done.stderr


# --- the venv route is untouched --------------------------------------------------------------------------


def test_the_venv_route_starts_no_container_at_all(tmp_path):
    # arrange: the Gegenprobe. A host with a python must behave exactly as it did before si#201, and the
    # default is `auto`, which prefers the venv - so nothing above may have leaked into it
    root = _product(tmp_path)

    # act: `auto` on this host, which has a python3
    done = _run(root, "--help", env={"DELIVERY_ROUTE": "auto"})

    # assert
    assert done.docker == [], f"the venv route started a container: {done.docker}"


# --- the two launchers declare the same route -------------------------------------------------------------


@pytest.mark.parametrize("token", [
    "LAUNCH_IMAGE_PIN",                          # the fifth parameter
    "DELIVERY_ROUTE",                            # the choice
    "DELIVERY_HOST_ROOT",                        # si#201's answer, host side
    "DELIVERY_MOUNT_ROOT=/src",                  # ... and container side
    "DELIVERY_ROUTE=inside",                     # what a nested aggregate step must not re-decide
    "PYTHONUSERBASE=/src/build/container/python",
    "/var/run/docker.sock",                      # the daemon, mounted in from the host
    ":/src",
    "-w /src",
    "python -u -m",
])
def test_both_launchers_declare_the_same_container_route(token):
    # arrange / act
    rendered = bootstrap.render("democtl")

    # assert: held as text because there is no Windows here to run the batch on, and a contract stated
    # in one file and not the other is the failure `test_init_contract` exists for
    assert token in rendered["democtl.sh"], f"{token} missing from the sh launcher"
    assert token in rendered["democtl.cmd"], f"{token} missing from the cmd launcher"


def test_the_batch_launcher_forwards_the_products_own_environment_namespace():
    # arrange / act: the prefix is DERIVED from the product name, so a product called `foo-ctl` forwards
    # FOO_CTL_* and not something a scaffolder typed
    rendered = bootstrap.render("foo-ctl")

    # assert
    assert "set FOO_CTL_ 2^>nul" in rendered["foo-ctl.cmd"]
    assert "{{ product_env_prefix }}" not in rendered["foo-ctl.cmd"]
