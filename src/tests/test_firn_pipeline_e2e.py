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
    rc, _ = firn_rc(SRC_FIRN.parents[1], "check", cwd="src")

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


@needs_docker
def test_the_vocabulary_is_eleven_kinds_each_reaching_artifact_and_refining_only_within_itself():
    # arrange / act: spec B.2 - one root, and every other kind reaches it. `ArtifactKind.refines` answers
    # the targets as one flat set, which says nothing about WHICH kind reaches the root; so each kind is
    # asked for its own parent and the chain is walked here (si#346's final review)
    rc, kinds = firn_rc(SRC_FIRN.parents[1], "query", "ArtifactKind", cwd="src")
    rc_refines, refines = firn_rc(SRC_FIRN.parents[1], "query", "ArtifactKind.refines", cwd="src")

    # assert: both queries exited clean, so an empty answer cannot be a failed query passing as green
    assert rc == 0
    assert rc_refines == 0
    # the vocabulary is the simplon.vocabulary.* set; the product models beside it (product.simplon, the
    # exported manifest) are left out of the count by the prefix filter on purpose
    root = "simplon.vocabulary.artifact"
    names = {n for n in kinds.split() if n.startswith("simplon.vocabulary.")}
    assert len(names) == 11
    assert root in names
    # every refines target, unfiltered, is inside the vocabulary: a target outside it is a failure here
    targets = set(refines.split())
    assert targets and targets <= names

    # the parent of each kind, one query per kind - rc 0 every time, so an empty answer is a real "none"
    parent: dict[str, set[str]] = {}
    for name in sorted(names):
        rc_one, answer = firn_rc(SRC_FIRN.parents[1], "query",
                                 f'ArtifactKind[name=="{name.rsplit(".", 1)[1]}"].refines', cwd="src")
        assert rc_one == 0, answer
        parent[name] = set(answer.split())
    assert parent[root] == set(), "the root refines nothing"
    # positive: the per-kind answers are the flat answer, split - so none of them was lost on the way
    assert set().union(*parent.values()) == targets
    # every kind other than the root reaches it through refines (refines is 0..N, so: through ANY chain)
    for name in sorted(names - {root}):
        seen, frontier = {name}, {name}
        while frontier and root not in seen:
            frontier = set().union(*(parent[k] for k in frontier)) - seen
            seen |= frontier
        assert root in seen, f"{name} does not reach {root} through refines: it reaches {sorted(seen)}"
