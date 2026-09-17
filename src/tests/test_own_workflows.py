"""simplon's OWN workflows, held against simplon's own manifest (si#40).

WHY THIS FILE EXISTS SEPARATELY from test_workflowgen.py. That module proves the generator works on a
fixture. This one proves it is USED - that the two files in `.github/workflows/` are the ones
`simplon.yaml` describes, and that neither of them has quietly stopped being either generated or
declared. It is the drift gate itself, run by the product's own unit suite, exactly as
`tasks:generate --check` is meant to be.

THE RULE IT KEEPS, and it is this repository's oldest: a tool never used in its own house rots unseen.
The catalogue's head says so about a path resolution that was silently wrong once installed, because
nobody had ever run the kernel the way a consumer does. A workflow generator that simplon shipped and
did not point at itself would be the same thing again, one phase further along - and it would have the
particular sting of being a generator whose whole selling point is that drift becomes visible.

WHAT THIS DOES NOT CLAIM. Not that GitHub runs these files - that takes a real Actions run, and nothing
here can stand in for it. What it holds is everything that would make such a run do the wrong thing
quietly: a workflow that no longer says what the manifest says, and a file in the directory that nothing
at all is responsible for.

THE COMPLEMENT ALREADY EXISTS. tests/test_release_workflow.py, tests/test_type_gate.py and
tests/test_version_source.py assert twenty-odd properties over these same two files, and they were
written against HAND-WRITTEN ones. They are the counter-check on the generated `ci.yml`: it satisfies
every one of them, which is the "gegengeprüft, nicht behauptet" half of si#40's acceptance - the
generated file does what the hand-written file did, measured by assertions written before the generator
existed and by somebody who was not trying to make it pass.
"""
import yaml

from simplon import catalogue as catalogue_mod, workflowgen
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

MANIFEST = ROOT / "simplon.yaml"

#: The product token the launcher carries, and therefore the one the generated steps must use.
PRODUCT = "simplon"


def _declared():
    return workflowgen.parse(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))


def _loaded():
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


def _report():
    return workflowgen.check(_declared(), ROOT, manifest=_loaded(), product=PRODUCT,
                             source=MANIFEST.name)


# --- the gate ------------------------------------------------------------------------------------------


def test_the_committed_workflows_agree_with_the_manifest():
    """THE drift gate, and the reason `--check` exists at all.

    A CLI module that has drifted is caught the moment somebody runs a command it no longer registers.
    A workflow that has drifted is caught by nothing: it runs, it goes green, and it tests whatever it
    happens to say. So the gate has to be somebody's job, and it is this suite's.
    """
    # Arrange / Act
    report = _report()

    # Assert
    assert [drift.path for drift in report.drifted] == [], (
        "a committed workflow no longer says what simplon.yaml says; regenerate with "
        "`./simplon.sh support workflows`\n" + "\n".join(d.diff for d in report.drifted))


def test_every_file_in_the_workflows_directory_has_an_owner():
    """No file that nothing generates and nothing declares.

    This is the assertion that would have caught agile-cockpit's dead `.gitlab-ci.yml`, and the one that
    catches the next workflow somebody adds here by hand without deciding which of the two it is.
    """
    # Arrange / Act
    report = _report()

    # Assert
    assert report.unmanaged == (), (
        f"these workflow files are named by nothing in {MANIFEST.name}: {list(report.unmanaged)}")


def test_the_gate_is_ruling_on_something():
    """A check over a predicate goes green when nothing matches it, which is how a gate quietly stops
    holding anything. Both files are named, so both are ruled on - and if a rename makes this red, the
    rename also has to say what now carries the pipeline."""
    # Arrange / Act
    report = _report()

    # Assert
    assert set(report.agreed) | set(report.handwritten) == {".github/workflows/ci.yml",
                                                            ".github/workflows/release.yml"}


# --- the two decisions this repository made, stated as assertions ------------------------------------------


def test_the_ci_workflow_is_the_generated_one():
    """si#40's own house. simplon builds and tests itself with the kernel it ships, and now it generates
    its pipeline with it too."""
    # Arrange / Act
    generated = [w.path for w in _declared() if w.generated]

    # Assert
    assert generated == [".github/workflows/ci.yml"]


def test_the_release_workflow_is_declared_hand_written_with_its_reason():
    """A DECISION, and si#40 asked for exactly this to be an explained possibility rather than an
    emergency exit.

    The generator carries comments, so prose is not what keeps release.yml out. What keeps it out is that
    it is roughly two-thirds reasoning and carries two multi-line shell scripts - the on-main report of
    si#23 and the wheel-is-the-tag check of si#3 - and declaring those would move that work rather than
    remove it. It stays hand-written and it stays NAMED, which is the difference between a decision and
    a gap.
    """
    # Arrange / Act
    declined = [w for w in _declared() if not w.generated]

    # Assert
    assert [w.path for w in declined] == [".github/workflows/release.yml"]
    assert declined[0].handwritten.strip(), "a decline with no reason is indistinguishable from neglect"


def test_the_generated_workflow_carries_the_prose_it_was_written_with():
    """The comments that used to be hand-written in ci.yml are still in ci.yml.

    si#40's second hard question, checked on the real file rather than on a fixture: a generator that
    dropped the reasoning would have made this file worse than the one it replaced. Three specific
    sentences, because "some comments survived" is not the claim - these did.
    """
    # Arrange / Act
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    # Assert
    assert "Stage zero is the working tree" in text
    assert "Two ways to reach one verdict is the shape that produced that" in text
    assert "setuptools-scm" in text, "the reason for `fetch-depth: 0` left the file with the setting"


def test_the_generated_workflow_runs_only_commands_the_manifest_declares():
    """The join, on the real pair. Every `run:` in the generated file is the launcher plus a command that
    resolves - so a rename anywhere in the command tree breaks generation instead of leaving this file
    calling something that is gone."""
    # Arrange
    manifest = _loaded()
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))

    # Act
    runs = [step["run"] for job in doc["jobs"].values() for step in job["steps"] if "run" in step]

    # Assert
    assert runs, "the generated workflow runs no product command at all"
    for run in runs:
        assert run.startswith(f"./{PRODUCT}.sh "), run
        workflowgen.resolve_command(manifest, run.split(" ", 1)[1], where=f"ci.yml: {run}")


# --- si#267: what the derivation would produce here, measured against what this repository runs -------


def _ci_steps() -> list[str]:
    """The commands simplon's own `self-build` job runs, in order, as the manifest declares them."""
    job = next(job for w in _declared() if w.key == "ci" for job in w.jobs)
    return [step.command for step in job.steps if step.command]


def test_the_derived_pipeline_over_this_manifest_is_a_pipeline_that_would_run():
    """si#267's own claim, held against the only manifest this repository can measure.

    The ticket asks for a generator that produces a WORKING file rather than a template with holes, and
    the cheapest way for that claim to be false is for the derivation to emit something that cannot run.
    Every command below was run by hand on this machine before this test was written - the four this
    repository's CI does not run included - and all four exit 0 and leave the tree clean.
    """
    derived = workflowgen.derive(_loaded(), ["build", "test"], where="measurement")

    assert [step.command for step in derived.steps] == [
        "build wheel", "build reference", "build acceptance", "build site", "build image",
        "test suite", "test typecheck-python", "test release-notes", "test report", "test generated"]


def test_this_repository_runs_seven_of_those_ten_and_the_difference_is_a_choice_not_a_defect():
    """THE FINDING si#267 ends on, kept as a measurement instead of a sentence in a document.

    A derived pipeline here would be correct and would cost more: `build site` pulls Hugo and
    mermaid-cli and takes about three and a half minutes, and every push to this repository starts two
    runs. The other two it adds are nearly free - `build reference` and `build acceptance` take about a
    second each - so the bill is one command, not four.

    simplon's own CI stays hand-written all the same, for a reason a derivation cannot carry: its order
    is argued in the manifest, chiefly that the prose gate goes LAST so a release section still to be
    written cannot hide a red suite. The derived order follows the manifest's declaration order instead.

    What this test holds is that the difference stays VISIBLE. If the derivation starts emitting what
    the CI runs, or the CI starts running what is derived, somebody should be told rather than left to
    assume the two agree.
    """
    derived = {step.command for step in workflowgen.derive(_loaded(), ["build", "test"],
                                                           where="measurement").steps}

    run_here = set(_ci_steps())

    assert run_here < derived
    assert sorted(derived - run_here) == ["build acceptance", "build reference", "build site"]


def test_the_command_this_repository_never_puts_in_ci_is_the_one_the_catalogue_marks_attended():
    """The two halves of si#267 meeting: the flag the catalogue declares and the choice this repository
    made years before it existed agree, and they were arrived at independently."""
    loaded = _loaded()

    assert loaded.commands["test"]["walk"].unattended is False
    assert "test walk" not in _ci_steps()
