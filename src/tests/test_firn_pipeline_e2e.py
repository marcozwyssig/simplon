"""si#346: simplon.pipeline checks, and every SelectorRelation answers what the fixture says.

`firn check` does not compile a SelectorRelation's selector (measured on v0.1.0, 2026-10-11): a misspelt
property passes rc 0 and answers EMPTY. The release rule reads `TestResult.about`, so an empty answer
would let an untested release through - the house defect, arriving through a model. Each relation is
therefore asked for its value over a fixture whose answer is known, and an empty answer is red.

AAA throughout.
"""
import shutil
from pathlib import Path

import pytest

from conftest import docker_is_usable
from firnrun import firn_rc

SRC_FIRN = Path(__file__).resolve().parents[1] / "firn"
DEMO = Path(__file__).resolve().parent / "fixtures" / "firn" / "pipeline_demo"

needs_docker = pytest.mark.skipif(not docker_is_usable(), reason="no docker daemon here to run firn in")


@pytest.fixture
def demo(tmp_path):
    """The demo project with the real simplon.pipeline beside it, as one firn project."""
    shutil.copytree(DEMO, tmp_path, dirs_exist_ok=True)
    shutil.copytree(SRC_FIRN / "model" / "simplon" / "pipeline", tmp_path / "model" / "simplon" / "pipeline")
    return tmp_path


@needs_docker
def test_simplons_own_firn_project_checks_clean():
    # arrange / act
    rc, _ = firn_rc(SRC_FIRN.parents[1], "check", cwd="src/firn")

    # assert
    assert rc == 0


@needs_docker
@pytest.mark.parametrize("selector, expected", [
    ("TestResult.about", ["demo.build.image.kernel"]),
    ("AggregateCommand.produced", ["demo.build.save.kernel_archive"]),
    ("Release.published", ["demo.build.image.kernel", "demo.test.image.checked"]),
])
def test_every_selector_relation_answers_what_the_fixture_says(demo, selector, expected):
    # arrange / act
    rc, out = firn_rc(demo, "query", selector)

    # assert: a value, not merely a clean exit - empty is exactly the failure firn does not report
    assert rc == 0
    assert sorted(out.split()) == sorted(expected)
