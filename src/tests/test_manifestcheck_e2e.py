"""si#522: `test:manifest-model` against the real firn image - green over every manifest within reach, red with
firn's own message over a broken export.

Each manifest runs as a product of its own in `tmp_path`, so the stage, the mount and the start directory
are the ones a product gets. The eight fixtures are migrated and answered exactly as
`test_manifestmodel_e2e.py` does. AAA throughout.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import ROOT, docker_is_usable
import realmanifests
from simplon.manifest import context
from simplon.tasks import manifestcheck, profiles
from simplon.tasks.migrate import migrate_text
from test_manifestmodel_e2e import NAMES

pytestmark = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")

IMAGE = profiles.profile("firn", version="0.2.0").image


def _as_product(monkeypatch, root: Path, name: str, text: str) -> None:
    monkeypatch.setattr(context, "_current", None)
    manifest = root / f"{name}.yaml"
    manifest.write_text(text, encoding="utf-8")
    context.set_current(context.ProductContext(name=name, root=root, manifest_path=manifest))


def _check() -> int:
    return manifestcheck.check(SimpleNamespace(command_path="test manifest-model"), image=IMAGE)


def test_simplons_own_manifest_is_green(tmp_path, monkeypatch):
    # arrange
    _as_product(monkeypatch, tmp_path, "simplon", (ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # act / assert
    assert _check() == 0


@pytest.mark.parametrize("name", NAMES)
def test_every_reachable_fixture_manifest_is_green(tmp_path, monkeypatch, name):
    # arrange
    migrated = migrate_text(realmanifests.text(name))
    assert migrated.status == "migrated", migrated.reason
    _as_product(monkeypatch, tmp_path, name, realmanifests.answer_release_rule(name, migrated.text))

    # act / assert
    assert _check() == 0


def test_a_broken_export_is_red_with_firns_message(tmp_path, monkeypatch, capfd):
    # arrange: a literal the M2 does not define
    _as_product(monkeypatch, tmp_path, "simplon", (ROOT / "simplon.yaml").read_text(encoding="utf-8"))
    name, text = manifestcheck.manifestmodel.current()
    broken = text.replace("simplon.pipeline.Area.ci", "simplon.pipeline.Area.nosuch", 1)
    assert broken != text
    monkeypatch.setattr(manifestcheck.manifestmodel, "current", lambda: (name, broken))

    # act
    rc = _check()

    # assert
    out = capfd.readouterr()
    assert rc == 1 and "E200" in out.out + out.err and "Area.nosuch" in out.out + out.err
