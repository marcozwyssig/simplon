"""si#371: the firn profile against the published firn image - the contract a gate reads.

firn's exit codes are 0 clean, 1 model wrong, 2 usage, 3 no project and 70 internal, and a gate has to
compare against 0, never against 1. What this file holds is that `toolchain:run`'s line - the profile's
own body, `cwd:` included - starts firn where its `firn.toml` is and hands every code back UNCHANGED:
a "no project" that came back as 1 would read as "the model is wrong", and one that came back as 0 would
be the recurring defect this repository hunts, a run that cannot tell "nothing to check" from "clean".

The model is simplon's own (`src/firn/`), copied, so a model that stops checking takes this file with it.

AAA throughout.
"""
import shutil
from pathlib import Path

import pytest

from conftest import docker_is_usable
from simplon.run import run
from simplon.tasks import profiles, toolchain

FIRN = profiles.profile("firn", version="0.1.0")
OWN_MODEL = Path(__file__).resolve().parents[1] / "firn"

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")


def _rc(root: Path, command: str, extra: list[str] | None = None) -> int:
    cfg = toolchain.declared({"image": FIRN.image, **FIRN.commands[command], "cwd": "src/firn"},
                             where=f"firn.{command}")
    line = toolchain.docker_argv(cfg, root=root, product="firn-e2e", instance="", extra=extra or [],
                                 network=str(FIRN.commands[command]["network"]))
    return run(line, capture=True).rc


@pytest.fixture
def tree(tmp_path):
    """A product tree with simplon's own firn project under src/firn/."""
    shutil.copytree(OWN_MODEL, tmp_path / "src" / "firn",
                    ignore=shutil.ignore_patterns(".firn-cache", "gen"))
    return tmp_path


@needs_docker
def test_a_clean_model_checks_clean(tree):
    # arrange / act
    rc = _rc(tree, "check")

    # assert
    assert rc == 0


@needs_docker
def test_a_broken_model_comes_back_as_1(tree):
    # arrange
    model = tree / "src" / "firn" / "model" / "product" / "simplon" / "simplon.firn"
    model.write_text(model.read_text() + "\nbroken {{{\n")

    # act
    rc = _rc(tree, "check")

    # assert
    assert rc == 1


@needs_docker
def test_no_project_comes_back_as_3_and_not_as_a_wrong_model(tree):
    # arrange: the directory is there, the firn.toml is not
    (tree / "src" / "firn" / "firn.toml").unlink()

    # act
    rc = _rc(tree, "check")

    # assert
    assert rc == 3


@needs_docker
def test_a_usage_error_comes_back_as_2(tree):
    # arrange / act: the caller's tail is appended to the profile's argv
    rc = _rc(tree, "check", extra=["--no-such-option"])

    # assert
    assert rc == 2


@needs_docker
def test_gen_over_a_model_with_no_template_writes_nothing_and_succeeds(tree):
    # arrange / act
    rc = _rc(tree, "gen")

    # assert
    assert rc == 0
    assert not any((tree / "src" / "firn" / "gen").glob("**/*.*"))
