"""si#346: every reachable manifest, migrated, exports to a model firn accepts (rc 0, never "not 1").

The eight manifests are the frozen fixtures of si#344 plan A, in the old form; `migrate_text` brings each
to the current form first, exactly as `test_migrate`'s golden test does (no `unknown_groups_into`, and
the manifest's own name as its path), so the model is the model of the manifest the golden test loads.
"""
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import docker_is_usable
from firnrun import firn_rc
import realmanifests
from simplon.domain import catalogue, manifestmodel
from simplon.domain import manifest as manifest_mod
from simplon.tasks.migrate import migrate_text

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "manifests"
SRC_FIRN = Path(__file__).resolve().parents[1] / "firn"
SRC_FIRN_TOML = SRC_FIRN.parent / "firn.toml"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.yaml"))

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")


def test_there_are_eight_reachable_manifests():
    # an empty parametrisation would be green over nothing
    assert len(NAMES) == 8


@needs_docker
@pytest.mark.parametrize("name", NAMES)
def test_a_reachable_manifest_exports_to_a_model_firn_accepts(tmp_path, name):
    # arrange
    migrated = migrate_text(realmanifests.text(name))
    assert migrated.status == "migrated", migrated.reason
    text = realmanifests.answer_release_rule(name, migrated.text)
    mf = manifest_mod.load(text, catalogue=catalogue.load(), manifest_path=f"{name}.yaml")
    out = manifestmodel.export(mf, yaml.safe_load(text), name, manifestmodel.KERNEL_SECTIONS)
    shutil.copy(SRC_FIRN_TOML, tmp_path / "firn.toml")
    shutil.copytree(SRC_FIRN, tmp_path / "firn")
    target = tmp_path / "firn" / "model" / "product" / manifestmodel.mangle(name)
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.firn").write_text(out, encoding="utf-8")

    # act
    rc, text_out = firn_rc(tmp_path, "check")

    # assert
    assert rc == 0, text_out
