"""The `test:release-notes` gate's own verdict, driven end to end (si#89, si#103).

WHY THIS FILE IS SEPARATE FROM `test_tasks_releasenotes.py`. That one pins the mechanism - what a tag
list is, what a merge subject names. This one is the deliverable: it constructs whole repositories with
whole releases pages and asks the GATE, through `check()`, the question a product asks it. The two proofs
si#89 and si#103 are worth are both here, and both are executed rather than asserted about:

  * a merged ticket the notes do not name is REFUSED, and the refusal text is read back;
  * a notes pull request naming its own PR number is ACCEPTED, on a real web-interface merge.

A guard that cannot fail is this repository's recurring defect, and it is expensive precisely because it
looks exactly like a guard that works. So the red half of every rule is here beside the green half, and
each red is produced by breaking the ARTEFACT - deleting a section, dropping a number, leaving a merge
un-numbered - rather than by breaking the rule.

AAA throughout.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from simplon import context
from simplon.tasks import releasenotes

from conftest import ROOT  # noqa: F401  (keeps the src tree on sys.path)


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return out.stdout


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "guard@example.com")
    _git(root, "config", "user.name", "The Guard")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore: the root commit")
    return root


def _merge(root: Path, branch: str, subjects: list[str], merge_subject: str) -> str:
    _git(root, "checkout", "-q", "-b", branch)
    for subject in subjects:
        (root / f"{branch.replace('/', '-')}.txt").write_text(subject, encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", subject)
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--no-ff", "-m", merge_subject, branch)
    return _git(root, "rev-parse", "HEAD").strip()


MANIFEST = """
product: sample
releases:
  page: "notes.md"
  from: "0.4.0"
  complete_from: "0.5.0"
"""


def _product(monkeypatch, root: Path, page: str, manifest: str = MANIFEST) -> None:
    """Register the repository as the current product, with `page` as its release notes.

    Through `monkeypatch` rather than `set_current`: the latter is a module global and would leak this
    test's product into the next one. pytest reverts a monkeypatched attribute at the end of the test
    that set it, which is the shape `tests/test_tasks_artifact.py` already uses.
    """
    (root / "notes.md").write_text(page, encoding="utf-8")
    (root / "sample.yaml").write_text(manifest, encoding="utf-8")
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("sample", root, root / "sample.yaml"))


def _complete_release(tmp_path: Path) -> Path:
    """A repository whose page is correct: 0.4.0 excused, 0.5.0 released and complete, 0.6.0 prepared."""
    root = _repo(tmp_path)
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): the workflows"], "merge: si40-workflows")
    _merge(root, "si41-thing", ["feat(#41): the thing"], "merge: the thing (si#41)")
    _git(root, "tag", "v0.5.0")
    _merge(root, "si61-census", ["feat(#61): the census"], "merge: si61-census")
    return root


COMPLETE_PAGE = """---
title: "Releases"
---

Notes start at 0.4.0; every section from 0.5.0 on names its tickets.

## 0.6.0

The release being prepared, and it carries si#61.

## 0.5.0

si#40 brought the workflows and si#41 the thing.

## 0.4.0

Prose written before the rule, naming no numbers at all.
"""


# --- green: the shape a correct page has ---------------------------------------------------------------

def test_a_page_that_names_every_merged_ticket_passes(tmp_path, capsys, monkeypatch):
    """The baseline the reds below are measured against: without it, a red proves only that the gate is
    broken."""
    # arrange
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr()
    assert rc == 0, said.out + said.err
    assert "the release notes are complete" in said.out


# --- red: the failure si#82 was raised for, produced by breaking the page -------------------------------

def test_a_ticket_merged_into_a_release_and_missing_from_its_section_is_refused(tmp_path, capsys, monkeypatch):
    """THE PROOF si#89 IS WORTH. The repository carries a merge for si#41 and the 0.5.0 section does not
    name it, so the section describes less than the release it names - which is exactly the failure that
    shipped once here, a section describing the pull request it was written in rather than the tag.

    Nothing about the prose is judged. The section still reads perfectly well; it is simply not about the
    whole release, and the only derivable half of that - a number appears - is what goes red.
    """
    # arrange: the correct page with ONE number taken out of it
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE.replace("si#40 brought the workflows and si#41 the thing.",
                                         "si#40 brought the workflows."))

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "the v0.5.0 section names 1 of the 2 tickets merged into v0.4.0..v0.5.0" in said
    assert "missing: si#41" in said


def test_a_tagged_release_with_no_section_at_all_is_refused(tmp_path, capsys, monkeypatch):
    """The failure the guard was built for first: a version is tagged, published, and never written up.
    Silent today, and silent forever - nothing else in a repository notices."""
    # arrange
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE.replace("## 0.5.0", "## 0.5.1"))

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "released but not on the page: v0.5.0" in said


def test_a_section_for_a_version_nobody_can_install_is_refused(tmp_path, capsys, monkeypatch):
    """A section for a version that carries no tag is a promise about a release nobody can install.

    With ONE exception, and it is the workflow rather than a loophole: the notes for a release are
    written BEFORE its tag, because the tag has to carry them. So exactly one undocumented version is
    legitimate - the one above every tag - and it is the release being prepared. Two is either a release
    somebody forgot to cut or a number written down twice.
    """
    # arrange: a second section above every tag, beside the prepared one
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE.replace("## 0.6.0", "## 0.7.0\n\nAnother one, si#61.\n\n## 0.6.0"))

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "documents versions that carry no tag and are not the one being prepared" in said
    assert "v0.7.0" in said, "the prepared release is the NEXT one after the highest tag, so 0.6.0 is " \
                             "the legitimate one and 0.7.0 is the promise nobody can install"


def test_a_merge_that_names_no_ticket_is_refused_before_completeness_is_judged(tmp_path, capsys, monkeypatch):
    """The precondition the completeness rule rests on, held as its own verdict rather than assumed.

    A rule reading merge subjects is worth exactly what those subjects say. A merge that names nothing is
    a change no section can be asked to describe, so it would be a silent hole in the population - and
    the rule above it would go on passing while the thing it counts got smaller.
    """
    # arrange
    root = _complete_release(tmp_path)
    _merge(root, "aufraeumen", ["chore: tidy up"], "merge: aufraeumen")
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "these merges name no ticket in their subject" in said
    assert "'merge: aufraeumen'" in said
    assert "write the number into it" in said


def test_a_section_below_the_completeness_floor_is_not_held_to_naming_its_tickets(tmp_path, capsys, monkeypatch):
    """The exemption, and it is the GAP between the two declared floors rather than a list.

    0.4.0's notes here predate the rule and name no number at all. An exemption list would be the thing
    that grows quietly; a second floor can only be raised in public, and a product that excuses nothing
    writes the same number twice.
    """
    # arrange: a range for 0.4.0 that it does not describe, and a floor that excuses it
    root = _repo(tmp_path)
    _git(root, "tag", "v0.3.0")
    _merge(root, "si1-early", ["feat(#1): from before the rule"], "merge: si1-early")
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): the workflows"], "merge: si40-workflows")
    _git(root, "tag", "v0.5.0")
    _product(monkeypatch, root, """---
title: "Releases"
---

Notes start at 0.4.0; every section from 0.5.0 on names its tickets.

## 0.5.0

si#40 brought the workflows.

## 0.4.0

Prose written before the rule, naming no numbers at all.
""")

    # act
    rc = releasenotes.check()

    # assert: si#1 is merged into 0.4.0's range and named nowhere, and the run is still green
    said = capsys.readouterr()
    assert rc == 0, said.out + said.err
    assert "not held to completeness" in said.out


# --- si#103: the self-reference, accepted ---------------------------------------------------------------

def test_a_notes_pull_request_naming_its_own_number_is_accepted(tmp_path, capsys, monkeypatch):
    """THE PROOF si#103 IS WORTH, and the case that stopped a release outright.

    The notes for 0.6.0 are written on a branch for si#61 and merged from GitHub's web interface, so the
    merge subject is `Merge pull request #62 from ...`. The number in it is the PULL REQUEST's - it did
    not exist when the notes were written, and a follow-up PR would have brought its own number too, so
    the regress has no floor.

    The page therefore names si#61, the ticket the author knew before the branch existed, and does NOT
    name #62, which nobody could have known. The gate accepts it, because a subject GitHub composed is
    not a statement about the work: the commits the merge brought in are read instead.
    """
    # arrange
    root = _repo(tmp_path)
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): the workflows"], "merge: si40-workflows")
    _git(root, "tag", "v0.5.0")
    _merge(root, "docs/61-the-0-6-0-notes", ["docs(#61): the 0.6.0 notes"],
           "Merge pull request #62 from marcozwyssig/docs/61-the-0-6-0-notes")
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr()
    assert rc == 0, said.out + said.err
    assert "62" not in said.out.split("HEAD is")[0], "the PR number is not what the section is asked for"


def test_the_same_pull_request_still_has_to_name_the_ticket_its_commits_do(tmp_path, capsys, monkeypatch):
    """The assurance si#103 must not spend. What the author WROTE is still required - it is simply looked
    for where the author wrote it. Take si#61 out of the section and the same merge goes red."""
    # arrange: the identical repository, with the ticket removed from the prepared section
    root = _repo(tmp_path)
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): the workflows"], "merge: si40-workflows")
    _git(root, "tag", "v0.5.0")
    _merge(root, "docs/61-the-0-6-0-notes", ["docs(#61): the 0.6.0 notes"],
           "Merge pull request #62 from marcozwyssig/docs/61-the-0-6-0-notes")
    _product(monkeypatch, root, COMPLETE_PAGE.replace("The release being prepared, and it carries si#61.",
                                         "The release being prepared."))

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "missing: si#61" in said


# --- the range, made legible ----------------------------------------------------------------------------

def test_every_run_says_what_head_resolved_to_and_which_range_each_section_answers_for(tmp_path, capsys, monkeypatch):
    """The half that was missing when this guard fired twice in one evening and surprised people twice.

    The range is `<last tag>..HEAD` of the STATE being checked, and which state that is depends on the
    event. Nothing used to say so, so a branch green on its own tip and red on `refs/pull/N/merge` read
    as a flaky gate rather than as two different ranges. Both facts are printed on every run, green ones
    included - a run that explains itself only when it fails teaches nobody why it passed.
    """
    # arrange
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    releasenotes.check()

    # assert
    said = capsys.readouterr().out
    assert "HEAD is " in said and "merge: si61-census" in said
    assert "v0.5.0     v0.4.0..v0.5.0" in said
    assert "v0.6.0     v0.5.0..HEAD" in said


def test_githubs_own_merge_at_head_is_named_as_the_pull_request_checkout(tmp_path, capsys, monkeypatch):
    """The exact surprise, reproduced: a `pull_request` run's HEAD is GitHub's merge of the branch with
    the base, so the range is the branch AS MERGED and carries whatever the base gained meanwhile. That
    sentence is printed instead of left for somebody to reconstruct from a red."""
    # arrange: a real merge commit wearing GitHub's machine-written subject
    root = _complete_release(tmp_path)
    left = _git(root, "rev-parse", "HEAD").strip()
    _merge(root, "pull-62", ["feat(#61): more of the census"],
           f"Merge {'a' * 40} into {left}")
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    releasenotes.check()

    # assert
    said = capsys.readouterr().out
    assert "GitHub's own merge, which is what a `pull_request` run checks out" in said
    assert "not at your branch tip" in said


# --- the gate that ruled on nothing ----------------------------------------------------------------------

def test_a_run_that_ruled_on_nothing_is_red_rather_than_green(tmp_path, capsys, monkeypatch):
    """The defect this repository hunts most, in the one place a release-notes gate would hide it well.

    A floor above every release leaves the gate with nothing to measure, and a green there is a report
    that nobody looked. It is red instead, and the message says which of the three causes it is.
    """
    # arrange: a floor above every tag this repository carries
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE, manifest=MANIFEST.replace('from: "0.4.0"', 'from: "9.0.0"')
                                                  .replace('complete_from: "0.5.0"', 'complete_from: "9.0.0"'))

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "ruled on NOTHING" in said
    assert "9.0.0" in said


def test_a_checkout_with_no_tags_is_diagnosed_as_the_checkout_and_not_as_the_page(tmp_path, capsys, monkeypatch):
    """A red that names the wrong cause costs more than no red at all, and this is where one was found.

    With no tag in the checkout, the rule about sections that promise an uninstallable version fires on
    EVERY section - correctly by its own terms and uselessly, because `git tag` answered nothing. A
    shallow clone does exactly that, and it is `actions/checkout`'s default. So the tag-less checkout is
    diagnosed first, by itself, and names `fetch-depth: 0` as the fix.
    """
    # arrange: a real repository, real merges, real page - and no tags
    root = _repo(tmp_path)
    _merge(root, "si40-workflows", ["feat(#40): the workflows"], "merge: si40-workflows")
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "no `vX.Y.Z` tag at all" in said
    assert "fetch-depth: 0" in said
    assert "carry no tag and are not the one being prepared" not in said, \
        "the page must not be blamed for what the checkout did not fetch"


def test_a_missing_page_is_refused_by_the_path_the_manifest_named(tmp_path, capsys, monkeypatch):
    """The manifest says where the notes live, so a page that is not there is a broken declaration, and
    the message names the path rather than the mistake."""
    # arrange
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE)
    (root / "notes.md").unlink()

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "notes.md" in said and "does not exist" in said


def test_a_checkout_git_cannot_read_is_a_failure_and_not_an_empty_answer(tmp_path, capsys, monkeypatch):
    """`git tag` in a directory that is no repository exits non-zero, and an empty answer there would
    read as "no releases" - a broken checkout coming out green. So it is a refusal with git's own words
    in it."""
    # arrange: a product tree that is not a git repository
    root = tmp_path / "product"
    root.mkdir()
    _product(monkeypatch, root, COMPLETE_PAGE)

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "git tag" in said


def test_a_manifest_without_the_section_stops_the_gate_before_it_touches_git(tmp_path, capsys, monkeypatch):
    """A product that placed the command and declared nothing is told which three values it owes."""
    # arrange
    root = _complete_release(tmp_path)
    _product(monkeypatch, root, COMPLETE_PAGE, manifest="product: sample\n")

    # act
    rc = releasenotes.check()

    # assert
    said = capsys.readouterr().err
    assert rc == 1
    assert "`releases:` section" in said
