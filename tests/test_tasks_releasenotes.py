"""`test:release-notes` - the product's declaration, and the mechanism it is measured with (si#89, si#103).

WHAT IS UNDER TEST HERE, and the split is the whole of si#89. `declared()` is the seam the PRODUCT
reaches through: three values in a `releases:` section, refused by name when they are missing or
malformed. Everything below it is MECHANISM - which versions a repository has, which a page documents,
what lies in the range between two tags, and what a merge subject names - and none of it knows a product.

THE REPOSITORIES ARE REAL. Every mechanism test builds a git repository in `tmp_path` with real commits,
real merges made by `git merge --no-ff -m <subject>` and real tags, and asks the mechanism about it. A
test that handed `tickets_of` a string it had just written would prove that a regex matches a literal,
which is not the claim: the claim is about what `git log` says of a merge GitHub made, and only a merge
can answer that. si#103 in particular is unprovable any other way - its whole subject is the relationship
between a merge commit's SUBJECT and the commits it brought in, and a string has no second parent.

AAA throughout, per the house convention.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplon import context
from simplon.tasks import releasenotes

from conftest import ROOT  # noqa: F401  (keeps the src tree on sys.path)


# --- a real repository, built for each test ---------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return out.stdout


def _repo(tmp_path: Path) -> Path:
    """An empty git repository with an identity, so commits and merges can actually be made."""
    root = tmp_path / "product"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "guard@example.com")
    _git(root, "config", "user.name", "The Guard")
    _git(root, "config", "commit.gpgsign", "false")
    return root


def _commit(root: Path, subject: str, *, path: str = "work.txt") -> str:
    (root / path).write_text(subject, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", subject)
    return _git(root, "rev-parse", "HEAD").strip()


def _merge(root: Path, branch: str, subjects: list[str], merge_subject: str) -> str:
    """A real branch carrying `subjects`, merged back with `merge_subject` as the merge commit's own.

    `--no-ff` is what makes it a merge commit with two parents, which is the only shape `tickets_of` can
    read one level down through.
    """
    _git(root, "checkout", "-q", "-b", branch)
    for subject in subjects:
        _commit(root, subject, path=f"{branch.replace('/', '-')}.txt")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--no-ff", "-m", merge_subject, branch)
    return _git(root, "rev-parse", "HEAD").strip()


def _manifest(root: Path, body: str) -> None:
    (root / "sample.yaml").write_text(body, encoding="utf-8")
    context.set_current(context.ProductContext("sample", root, root / "sample.yaml"))


THREE_KEYS = """
product: sample
releases:
  page: "notes.md"
  from: "0.4.0"
  complete_from: "0.5.0"
"""


# --- the product's declaration ----------------------------------------------------------------------

def test_the_three_declared_values_are_read_back_as_the_product_wrote_them(tmp_path):
    """The whole of what a product says, and the whole of what the kernel may know about it."""
    # arrange
    root = _repo(tmp_path)
    _manifest(root, THREE_KEYS)

    # act
    spec = releasenotes.declared()

    # assert
    assert spec is not None
    assert spec.page == root / "notes.md"
    assert spec.first == (0, 4, 0)
    assert spec.complete_from == (0, 5, 0)


def test_a_manifest_with_no_releases_section_is_refused_naming_the_three_keys(tmp_path, capsys):
    """A product that placed the command and declared nothing gets a sentence, not a traceback.

    The refusal is at RUN time rather than at load, deliberately: the section is read inside the body,
    the same shape `tasks.artifact` reads `artifacts:` with, so no load-time refusal is added and the
    kernel's refusal census keeps its counts. A product only meets this by asking for the gate.
    """
    # arrange
    root = _repo(tmp_path)
    _manifest(root, "product: sample\n")

    # act
    spec = releasenotes.declared()

    # assert
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert spec is None
    assert "releases" in said
    assert "page" in said and "from" in said and "complete_from" in said


@pytest.mark.parametrize("missing", ["page", "from", "complete_from"])
def test_each_missing_key_is_refused_by_its_own_name(tmp_path, capsys, missing):
    """Three values and three refusals: "something is wrong with your manifest" is not a diagnosis."""
    # arrange
    root = _repo(tmp_path)
    _manifest(root, "\n".join(line for line in THREE_KEYS.splitlines()
                              if not line.strip().startswith(f"{missing}:")))

    # act
    spec = releasenotes.declared()

    # assert
    assert spec is None
    captured = capsys.readouterr()
    assert missing in captured.out + captured.err


@pytest.mark.parametrize("value", ["0.4", "v0.4.0", "latest", "0.4.0.1", ""])
def test_a_floor_that_is_not_a_three_part_version_is_refused_with_the_value_in_it(tmp_path, capsys, value):
    """`from:` is a VERSION, spelled the way the page spells its headings - not the tag, not a range.

    `v0.4.0` is refused too, and that is the interesting one: the tag carries the `v`, the heading does
    not, and a product that wrote the tag here would get a floor that matches no section at all.
    """
    # arrange
    root = _repo(tmp_path)
    _manifest(root, THREE_KEYS.replace('from: "0.4.0"', f'from: "{value}"'))

    # act
    spec = releasenotes.declared()

    # assert
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert spec is None
    assert "from" in said
    assert (value in said) if value else True


def test_a_completeness_floor_below_the_notes_floor_is_refused(tmp_path, capsys):
    """It would excuse nothing and mean nothing: a section below `from` is not required to exist at all,
    so requiring it to be COMPLETE is a statement about a section the same manifest says may be absent."""
    # arrange
    root = _repo(tmp_path)
    _manifest(root, THREE_KEYS.replace('complete_from: "0.5.0"', 'complete_from: "0.3.0"'))

    # act
    spec = releasenotes.declared()

    # assert
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert spec is None
    assert "complete_from" in said and "0.3.0" in said and "0.4.0" in said


def test_the_two_floors_may_be_equal_and_then_nothing_is_excused(tmp_path):
    """A product adopting the guard from its first release excuses nothing, and says so by writing the
    same number twice. The excused set is the GAP between the two floors, so an empty gap is the normal
    state rather than a special case - which is the reason there is no exemption LIST to grow quietly."""
    # arrange
    root = _repo(tmp_path)
    _manifest(root, THREE_KEYS.replace('complete_from: "0.5.0"', 'complete_from: "0.4.0"'))

    # act
    spec = releasenotes.declared()

    # assert
    assert spec is not None
    assert spec.first == spec.complete_from == (0, 4, 0)


@pytest.mark.parametrize("page", ["/etc/passwd", "../outside/notes.md"])
def test_a_page_outside_the_product_root_is_refused(tmp_path, capsys, page):
    """The path is only ever READ, so this is diagnosis rather than protection: a manifest naming a file
    outside its own checkout as its release notes is broken, and saying so costs a product nothing."""
    # arrange
    root = _repo(tmp_path)
    _manifest(root, THREE_KEYS.replace('page: "notes.md"', f'page: "{page}"'))

    # act
    spec = releasenotes.declared()

    # assert
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert spec is None
    assert "page" in said


# --- the mechanism: what the repository says ---------------------------------------------------------

def test_only_a_three_part_v_tag_counts_as_a_released_version(tmp_path):
    """The tag IS the version (si#3), so `git tag` is the authority - but not every tag is a release.

    A release candidate and a stray local tag are neither released versions nor mistakes; they are
    simply not what the page documents, and counting them would demand a section for each.
    """
    # arrange
    root = _repo(tmp_path)
    _commit(root, "feat(#1): the first thing")
    for name in ("v0.4.0", "v0.5.0", "v0.5.0-rc1", "scratch", "0.6.0"):
        _git(root, "tag", name)

    # act
    found = releasenotes.released_versions(root)

    # assert
    assert found == [(0, 4, 0), (0, 5, 0)]


def test_merges_in_a_range_are_the_merge_commits_and_not_the_work_behind_them(tmp_path):
    """A merge is the unit a release is assembled from: work happens on a branch and ARRIVES in one
    commit. Counting the commits instead would count a branch's internal history, which nobody promised
    to describe."""
    # arrange
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): one", "feat(#40): two"], "merge: si40-workflows")
    _merge(root, "si41-thing", ["feat(#41): one"], "merge: the thing (si#41)")

    # act
    found = releasenotes.merges_in(root, "v0.4.0", "HEAD")

    # assert: two merges, newest first, and neither of the three authored commits among them
    assert [subject for _, subject in found] == ["merge: the thing (si#41)", "merge: si40-workflows"]


def test_githubs_own_ephemeral_merge_is_out_of_the_population(tmp_path):
    """The one merge in a range that no author wrote and no author can fix (si#97).

    CI runs `on: [push, pull_request]`, and the `pull_request` event checks out `refs/pull/N/merge` - a
    commit GitHub creates on the fly to test the branch against the base. It is HEAD in that checkout, so
    it lands inside the prepared release's range, and its subject is machine-written with no place to put
    a ticket. It is not a change the release carries; it is the scaffolding the run is built on.
    """
    # arrange: the exact machine format, on a real merge commit
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    _git(root, "tag", "v0.4.0")
    ephemeral = ("Merge 528027af46caeab8a57bad0e9f8ce41852b67599 into "
                 "d128e1bcba34a7f6d4f9c5dd24cd37fbcd116d38")
    _merge(root, "si42-work", ["feat(#42): the work"], ephemeral)

    # act
    found = releasenotes.merges_in(root, "v0.4.0", "HEAD")

    # assert
    assert releasenotes.is_githubs_own_merge(ephemeral)
    assert found == []


def test_a_subject_a_person_wrote_is_never_mistaken_for_githubs_own(tmp_path):
    """The assurance the skip must not spend. The skip is the EXACT machine format and nothing near it:
    a short hash, a branch name, or any word past the second hash means a human wrote the subject, and a
    human can write the number in."""
    # arrange
    written_by_a_human = [
        "Merge branch 'main' into aufraeumen",
        "merge: aufraeumen",
        "Merge 528027a into d128e1b",
        ("Merge 528027af46caeab8a57bad0e9f8ce41852b67599 into "
         "d128e1bcba34a7f6d4f9c5dd24cd37fbcd116d38 (manual)"),
        ("Merge 528027af46caeab8a57bad0e9f8ce41852b67599 into "
         "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"),
    ]

    # act
    skipped = [subject for subject in written_by_a_human
               if releasenotes.is_githubs_own_merge(subject)]

    # assert
    assert not any(releasenotes.tickets_in(subject) for subject in written_by_a_human), \
        "the premise: none of these names a ticket, so each one is a merge the rule has to catch"
    assert skipped == []


@pytest.mark.parametrize("subject, expected", [
    ("merge: die Gruppenmitgliedschaft gehoert zum Install (#87)", {87}),
    ("merge: the thing (si#87)", {87}),
    ("Merge remote-tracking branch 'origin/main' into si40-workflows", {40}),
    ("merge: si51-modulkoepfe", {51}),
])
def test_the_three_spellings_a_subject_names_a_ticket_in(subject, expected):
    """`#40`, `si#40` and the `si40-` branch name GitHub writes into a default merge subject. It is
    MEASURED which source is complete rather than chosen: over `v0.4.0..v0.5.0` in this repository, both
    spellings together produce exactly the fourteen merges, `#N` alone leaves one merge naming nothing,
    and reading BODIES adds five tickets from earlier releases that the section correctly never names."""
    # arrange / act / assert
    assert releasenotes.tickets_in(subject) == expected


def test_a_web_merge_is_read_from_the_commits_it_brought_and_not_from_its_pull_request_number(tmp_path):
    """si#103, and it is proven on a real merge because nothing else can prove it.

    A pull request merged from GitHub's web interface gets `Merge pull request #N from <branch>`. The
    number there is the PULL REQUEST's - a statement about the vorgang, not about the work - so the
    notes PR names ITSELF, and no notes could have anticipated their own merge. A follow-up PR would
    bring its own number too; the regress has no floor. v0.8.0 died on exactly this.

    So a subject GitHub composed is not read as a statement. The commits it brought in are, because that
    is where the author wrote what the work was.
    """
    # arrange: the real shape - a notes branch for si#92, merged as pull request #94
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    sha = _merge(root, "docs/92-the-0-8-0-notes", ["docs(#92): the 0.8.0 notes"],
                 "Merge pull request #94 from marcozwyssig/docs/92-the-0-8-0-notes")
    subject = "Merge pull request #94 from marcozwyssig/docs/92-the-0-8-0-notes"

    # act
    named = releasenotes.tickets_of(root, sha, subject)

    # assert
    assert 94 in releasenotes.tickets_in(subject), "the premise: the PR number IS in the subject"
    assert named == {92}, "the author's own number, and not the one GitHub wrote"


def test_a_web_merge_whose_commits_name_nothing_falls_back_to_its_number(tmp_path):
    """Several merges from before the convention name nothing in their commits either. Dropping them
    would EXCUSE work rather than describe it, so the number in the subject is the floor."""
    # arrange
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    sha = _merge(root, "feat/release-asset", ["wip", "more wip"],
                 "Merge pull request #72 from marcozwyssig/feat/release-asset")

    # act
    named = releasenotes.tickets_of(root, sha, "Merge pull request #72 from marcozwyssig/feat/release-asset")

    # assert
    assert named == {72}


def test_an_authored_merge_subject_is_still_read_exactly_as_written(tmp_path):
    """The assurance does not weaken. What a person wrote is still what the range is measured against;
    it is simply looked for where the author wrote it."""
    # arrange
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    sha = _merge(root, "si87-install", ["chore: something nobody numbered"],
                 "merge: die Gruppenmitgliedschaft gehoert zum Install (#87)")

    # act
    named = releasenotes.tickets_of(root, sha, "merge: die Gruppenmitgliedschaft gehoert zum Install (#87)")

    # assert: the subject wins, and the un-numbered commit behind it is never consulted
    assert named == {87}


# --- the mechanism: what the page says ---------------------------------------------------------------

PAGE = """---
title: "Releases"
---

Notes start at 0.4.0, and every section from 0.5.0 on names its tickets.

## 0.6.0

The one being prepared, naming si#61.

## 0.5.0

Naming si#40 and si#41.

## 0.4.0

Prose, and no numbers at all.
"""


def test_a_section_is_a_heading_and_everything_under_it_up_to_the_next():
    """Each `## X.Y.Z` heading's body. What is in it is never judged - only searched for numbers."""
    # arrange / act
    found = releasenotes.sections(PAGE)

    # assert
    assert sorted(found) == [(0, 4, 0), (0, 5, 0), (0, 6, 0)]
    assert "si#40" in found[(0, 5, 0)] and "si#61" not in found[(0, 5, 0)]


def test_a_released_range_ends_at_its_own_tag_and_the_prepared_one_at_head(tmp_path):
    """A RELEASED version's range ends at its own tag. The one documented version that is NOT tagged is
    the release being prepared, and its range ends at `HEAD`, because that is what the tag will point at.
    Writing the notes before the tag is the workflow (si#3), so the prepared section has to be measurable
    before there is anything to measure it against.

    A version with no earlier tag is skipped: its range has no lower end, so there is nothing to compute.
    """
    # arrange
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): a thing"], "merge: si40-workflows")
    _git(root, "tag", "v0.5.0")
    _merge(root, "si61-census", ["feat(#61): another"], "merge: si61-census")

    # act
    ranges = releasenotes.ranges_under_test(root, PAGE, (0, 4, 0))

    # assert: 0.4.0 has no earlier tag, so it is not measurable and is absent
    assert ranges == {(0, 5, 0): ("v0.4.0", "v0.5.0"), (0, 6, 0): ("v0.5.0", "HEAD")}


def test_the_floor_keeps_an_older_section_out_of_the_ranges(tmp_path):
    """A section below the floor is out of scope by the product's own statement, so no range is computed
    for it even when one could be."""
    # arrange
    root = _repo(tmp_path)
    _commit(root, "chore: the root commit")
    _git(root, "tag", "v0.3.0")
    _merge(root, "si1-a", ["feat(#1): a"], "merge: si1-a")
    _git(root, "tag", "v0.4.0")
    _merge(root, "si40-workflows", ["feat(#40): a thing"], "merge: si40-workflows")
    _git(root, "tag", "v0.5.0")

    # act
    above = releasenotes.ranges_under_test(root, PAGE, (0, 5, 0))

    # assert
    assert sorted(above) == [(0, 5, 0), (0, 6, 0)]
    assert (0, 4, 0) not in above
