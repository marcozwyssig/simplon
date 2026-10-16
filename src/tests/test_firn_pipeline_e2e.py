"""si#346: simplon.pipeline checks, and every SelectorRelation answers what the fixture says.

`firn check` does not compile a SelectorRelation's selector (measured on v0.1.0, 2026-10-11): a misspelt
property passes rc 0 and answers EMPTY. The release rule reads `TestResult.about`, so an empty answer
would let an untested release through - the house defect, arriving through a model. Each relation is
therefore asked for its value over a fixture whose answer is known, and an empty answer is red.

Since firn v0.2.0 (si#410), `firn validate` refuses a selector step that no type in the model declares
(E012, measured 2026-10-16 on each of the three relations with one step misspelt). A selector spelt right
that walks the wrong relation still answers empty, which is what the value tests below are for.

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
    for package in ("pipeline", "manifest"):   # the demo is shaped like the export: a Product owns it all
        shutil.copytree(SRC_FIRN / "model" / "simplon" / package, tmp_path / "model" / "simplon" / package)
    return tmp_path


@needs_docker
def test_simplons_own_firn_project_checks_clean():
    # arrange / act
    rc, _ = firn_rc(SRC_FIRN.parents[1], "validate", cwd="src")

    # assert
    assert rc == 0


@needs_docker
def test_the_demo_checks_clean(demo):
    # arrange / act: `query` answers over a model `validate` refuses (measured 2026-10-14: the demo still
    # composed its artifacts under `produces` after C.2 made it an Association - E009 - and every query
    # below stayed green), so a demo that has drifted from the metamodel is red here and not nowhere
    rc, out = firn_rc(demo, "validate")

    # assert
    assert rc == 0, out


@needs_docker
def test_a_task_without_a_key_is_refused_by_firn(demo):
    # arrange: si#400 part 4, decision 4 - the coordinate is required, and firn says so, not the kernel
    path = demo / "model" / "demo" / "demo.firn"
    path.write_text(path.read_text().replace('  key = "save-image"\n', "", 1))

    # act
    rc, out = firn_rc(demo, "validate")

    # assert
    assert rc == 1
    assert "E004" in out and "simplon.pipeline.Task.key" in out


@needs_docker
@pytest.mark.parametrize("selector, expected", [
    ("TestResult.about", ["demo.demo.a_kernel"]),
    ("AggregateCommand.produced", ["demo.demo.a_kernel_archive"]),
    ("Release.published", ["demo.demo.a_kernel", "demo.demo.a_checked"]),
])
def test_every_selector_relation_answers_what_the_fixture_says(demo, selector, expected):
    # arrange / act
    rc, out = firn_rc(demo, "query", selector)

    # assert: a value, not merely a clean exit - empty is exactly the failure firn does not report
    assert rc == 0
    assert sorted(out.split()) == sorted(expected)


@needs_docker
def test_the_vocabulary_is_twelve_kinds_each_reaching_artifact_and_refining_only_within_itself():
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
    assert len(names) == 12
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
