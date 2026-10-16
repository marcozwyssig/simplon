"""si#371: the firn profile against the published firn image - the contract a gate reads.

firn's exit codes are 0 clean, 1 model wrong, 2 usage, 3 no project and 70 internal, and a gate has to
compare against 0, never against 1. What this file holds is that `toolchain:run`'s line - the profile's
own body, `cwd:` included - starts firn where its `firn.toml` is and hands every code back UNCHANGED:
a "no project" that came back as 1 would read as "the model is wrong", and one that came back as 0 would
be the recurring defect this repository hunts, a run that cannot tell "nothing to check" from "clean".

The project is simplon's own (`src/firn.toml`, `src/firn/`), copied, so a model that stops checking takes this file with it.

AAA throughout.
"""
import re
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import docker_is_usable
from simplon.domain import catalogue
from simplon.kernel.run import run
from simplon.tasks import profiles, toolchain

FIRN = profiles.profile("firn", version="0.2.0")
OWN_MODEL = Path(__file__).resolve().parents[1] / "firn"

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")


def _rc(root: Path, command: str, extra: list[str] | None = None) -> int:
    cfg = toolchain.declared({"image": FIRN.image, **FIRN.commands[command], "cwd": "src"},
                             where=f"firn.{command}")
    line = toolchain.docker_argv(cfg, root=root, product="firn-e2e", instance="", extra=extra or [],
                                 network=str(FIRN.commands[command]["network"]))
    return run(line, capture=True).rc


@pytest.fixture
def tree(tmp_path):
    """A product tree with simplon's own firn project: src/firn.toml and the model under src/firn/."""
    shutil.copytree(OWN_MODEL, tmp_path / "src" / "firn", ignore=shutil.ignore_patterns(".firn-cache", "gen"))
    shutil.copy(OWN_MODEL.parent / "firn.toml", tmp_path / "src" / "firn.toml")
    return tmp_path


@needs_docker
def test_a_clean_model_checks_clean(tree):
    # arrange / act
    rc = _rc(tree, "validate")

    # assert
    assert rc == 0


@needs_docker
def test_a_broken_model_comes_back_as_1(tree):
    # arrange
    model = tree / "src" / "firn" / "model" / "product" / "simplon" / "simplon.firn"
    model.write_text(model.read_text() + "\nbroken {{{\n")

    # act
    rc = _rc(tree, "validate")

    # assert
    assert rc == 1


@needs_docker
def test_no_project_comes_back_as_3_and_not_as_a_wrong_model(tree):
    # arrange: the directory is there, the firn.toml is not
    (tree / "src" / "firn.toml").unlink()

    # act
    rc = _rc(tree, "validate")

    # assert
    assert rc == 3


@needs_docker
def test_a_usage_error_comes_back_as_2(tree):
    # arrange / act: the caller's tail is appended to the profile's argv
    rc = _rc(tree, "validate", extra=["--no-such-option"])

    # assert
    assert rc == 2


@needs_docker
def test_gen_writes_both_targets_and_the_fresh_catalogue_is_refused_for_having_no_tasks(tree):
    # arrange: the kinds the model declares, in the kernel's spelling (firn#962: a firn name has no `-`)
    kinds_model = tree / "src" / "firn" / "model" / "simplon" / "vocabulary" / "kinds.firn"
    model = re.findall(r"^(\w+) typeOf simplon\.pipeline\.ArtifactKind", kinds_model.read_text(), re.M)
    expected = {name.replace("_", "-") for name in model}
    catalogue_file = tree / "src" / "simplon" / "catalogue.yaml"
    page = tree / "src" / "site" / "content" / "with-what" / "kinds.md"

    # act: the copy carries no catalogue, so gen writes one from nothing - an empty region
    rc = _rc(tree, "gen")

    # assert: both targets written, every kind present
    assert rc == 0
    assert catalogue_file.is_file() and page.is_file()
    assert len(model) > 0, "the model regex found no kinds - this test would pass over nothing"
    assert set(yaml.safe_load(catalogue_file.read_text(encoding="utf-8"))["kinds"]) == expected
    # ...and a catalogue gen wrote over a missing file loads as nothing: the loader must refuse it
    with pytest.raises(ValueError, match="declares no tasks"):
        catalogue.load(catalogue_file)
