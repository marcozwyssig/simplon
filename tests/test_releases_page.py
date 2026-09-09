"""The releases page against the tags that exist (#53).

WHY THIS IS PINNED AT ALL. Release notes are a second source: the truth is the tag and the commits it
carries, the page is a copy, and this repository has learned twice this week what an unwatched copy does.
The coordinate descriptions in `building/phases.md` were paraphrases nobody compared, and by the time
anybody measured, several had drifted (#46). A count typed onto a page was wrong six paragraphs under the
sentence saying counts are read from the catalogue (#35).

WHAT IS AND IS NOT CHECKED, and the line between them is the point. The PROSE of a release note cannot be
derived - it says what a change meant, which no tool knows. So nothing here reads the prose. What IS
derivable is whether a released version has a section at all, and that is the failure this guards: a
release goes out and nobody writes it down. That failure is silent today and would stay silent forever.

WHY THE FLOOR. Notes start at 0.4.0, declared on the page itself. Demanding a section for all fourteen
earlier tags would mean writing them from memory now, and a reconstructed record is indistinguishable
from a real one - the same objection this repository raised against a rewrite that only illustrates. The
floor is therefore a constant here, read back from the page's own sentence so the two cannot disagree.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "content" / "using" / "releases.md"

#: The first release with notes. Earlier tags are out of scope, and the page says so in prose; the
#: assertion below holds the two together so the floor cannot move in one place only.
FLOOR = (0, 4, 0)


def _version(tag: str) -> tuple[int, ...] | None:
    """`v1.2.3` -> (1, 2, 3); anything else -> None (release candidates, stray local tags)."""
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(int(part) for part in match.groups()) if match else None


def released_versions() -> list[tuple[int, ...]]:
    """Every `vX.Y.Z` tag in this checkout, newest last. The tag IS the version (#3), so this is the
    authority the page is measured against - not a list maintained beside it."""
    out = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=True)
    found = [_version(line.strip()) for line in out.stdout.splitlines() if line.strip()]
    return sorted(v for v in found if v is not None)


def documented_versions() -> list[tuple[int, ...]]:
    """Every version the page gives a section to, read from its `## X.Y.Z` headings."""
    body = PAGE.read_text(encoding="utf-8")
    found = [_version("v" + m) for m in re.findall(r"^## (\d+\.\d+\.\d+)\s*$", body, re.MULTILINE)]
    return sorted(v for v in found if v is not None)


def test_every_release_at_or_above_the_floor_has_a_section():
    """The failure this exists for: a version is tagged, published, and never written up.

    Nothing here judges what the section says - only that the release is not missing from the page.
    """
    documented = documented_versions()
    missing = [v for v in released_versions() if v >= FLOOR and v not in documented]
    assert not missing, (
        "released but not on the releases page: "
        + ", ".join("v" + ".".join(str(p) for p in v) for v in missing)
        + f" (documented: {[ '.'.join(str(p) for p in v) for v in documented ]})")


def test_the_page_states_the_floor_it_is_held_to():
    """The floor lives in two places - this module and the page's own prose - so it is pinned here.

    Without this, moving the floor in the constant alone would quietly excuse a missing section while
    the page still promised to cover it.
    """
    floor = ".".join(str(part) for part in FLOOR)
    assert floor in PAGE.read_text(encoding="utf-8"), (
        f"the page must name {floor} as the first release with notes, because that is the floor this "
        f"suite holds it to")


def test_the_page_documents_nothing_beyond_the_release_being_prepared():
    """A section for a version that does not exist is a promise about a release nobody can install.

    With ONE exception, and it is the workflow rather than a loophole: the notes for a release have to be
    written BEFORE its tag, because the tag has to carry them - `git tag` is the whole act of choosing the
    version (#3), and it points at a tree. So exactly one undocumented version is legitimate, the one
    above every tag that exists, and it is the release being prepared.

    Two sections above the highest tag is not that. It is either a version somebody forgot to cut or a
    number written down twice, and both are the failure this file exists for: a page that promises a
    release nobody can install.
    """
    released = released_versions()
    ahead = sorted(v for v in documented_versions() if v not in released)
    highest = released[-1] if released else (0, 0, 0)
    unexplained = [v for v in ahead if v <= highest] + ahead[1:]
    assert not unexplained, (
        "the releases page documents versions that carry no tag and are not the one being prepared: "
        + ", ".join("v" + ".".join(str(p) for p in v) for v in unexplained)
        + f" (highest tag: v{'.'.join(str(p) for p in highest)})")


# --- the section against the merges in its range (si#82) ---------------------------------------------
#
# WHAT WENT WRONG WITHOUT THIS. Everything above passed while the 0.5.0 section described TWO of the
# fourteen changes the tag carries and opened with the words "Two changes". Nobody made a mistake: the
# tag was cut through a pull request whose own scope was exactly those two, twelve further merges landed
# on `main` beside it, and the notes correctly described the PR and wrongly described the TAG. The two
# terms had simply never been held apart, and the suite could not tell the difference because it was
# asking whether a heading existed.
#
# So this is the same defect the rest of this repository hunts, wearing the notes as a hat: an outcome
# that cannot tell "described" from "a heading exists" - green precisely because nobody looks.
#
# WHAT IS DERIVABLE AND WHAT IS NOT, and this line is exactly where the module docstring drew it. The
# PROSE is not derivable: what a change MEANT is knowledge no tool has, and nothing below reads a word of
# it. COMPLETENESS is derivable, because the range is: the merges between one tag and the next are a
# fact, and whether a section mentions each of their numbers is a string search. That is the whole claim
# here - a number appears - and it is deliberately the weakest claim that would have caught si#82.


#: The first release whose section is held to completeness, and the ONE exemption this file grants.
#:
#: WHY THERE IS AN EXEMPTION AT ALL. 0.4.0's notes were written before this rule and name no ticket
#: number anywhere: fifteen were merged into its range and the section carries none. Retro-fitting them
#: would mean deciding, a release later, which paragraph each of fifteen numbers belongs beside - and two
#: of them (si#48 and si#49) have no paragraph at all, so it would mean writing new prose about a
#: released version from the outside. That is reconstruction, which is the objection the page's own floor
#: paragraph raises against writing the older releases up at all.
#:
#: HOW IT IS PAID FOR, because an exemption nothing checks is a hole with a comment over it. Two
#: assertions below: `test_exactly_one_section_is_excused_from_completeness` pins the excused population
#: at one and requires it to BE the floor, so the exemption cannot grow to cover a release somebody did
#: not feel like writing up; and `test_the_excused_section_really_is_the_one_that_could_not_pass` requires
#: the excused section to be genuinely incomplete, so the day somebody does write those numbers in, this
#: constant is told to come down rather than quietly outliving its reason. The page states the boundary
#: in its own prose too, and `test_the_page_says_from_which_release_every_ticket_is_named` holds the two
#: together the way the floor above is held.
COMPLETE_FROM = (0, 5, 0)

#: The three spellings a merge subject in this repository uses for a ticket, and it is MEASURED which
#: source is complete rather than chosen.
#:
#:   * `#40` and `si#24` - `_TICKET`, the ordinary spelling.
#:   * `si40-workflows` - `_BRANCH`, the branch name GitHub writes into a default merge subject
#:     ("Merge remote-tracking branch 'origin/main' into si40-workflows") and this repository writes by
#:     hand for a branch merged without a PR ("merge: si51-modulkoepfe").
#:
#: THE MEASUREMENT, over `v0.4.0..v0.5.0` - the range si#82 was raised about, whose fourteen merges are
#: the population any candidate source has to produce whole:
#:
#:   | source                          | numbers | verdict                                          |
#:   | merge SUBJECTS, both spellings  |      14 | exactly the fourteen                             |
#:   | merge subjects, `#N` only       |      14 | but leaves one merge naming nothing              |
#:   | merge subjects AND bodies       |      19 | adds si#5, si#34, si#47, si#49, si#52            |
#:   | every commit, subject and body  |      27 | adds eight more, and `#1444`, not a ticket here   |
#:
#: The third row is why bodies are not read. A merge body argues, and arguing cites: si#24's body names
#: si#47 and si#34 as the movement it repeats, si#58's names si#49 and si#52 as the same shape of defect.
#: Those are tickets from EARLIER releases, and demanding them in this section would make the rule
#: overbroad in the direction that is hardest to notice - it would fail against notes that are correct.
#: The fourth row adds `#1444`, a foreign issue number quoted in a comment, which is the same failure
#: with the mask off - it is `netctl#1444`, another project's issue quoted in a comment.
#:
#: THE LIMIT IS RECORDED RATHER THAN IMPLIED. A subject is what the rule can read, so a ticket closed
#: inside another ticket's merge is invisible to it: si#52 shipped under `merge: si49-benutzbarkeit` and
#: this rule will never ask for it. That is a floor on what the notes must say, not a claim that it is
#: the ceiling.
_TICKET = re.compile(r"(?:si)?#(\d+)\b")
_BRANCH = re.compile(r"\bsi(\d+)-")

#: The subject GitHub composes for the merge it builds itself - two full hashes and not one word more
#: (si#97). It is matched in that EXACT machine format on purpose: a subject a person wrote is a subject a
#: person can put the number into, so a short hash, a branch name, or anything past the second hash is
#: still held to the rule.
_GITHUB_MERGE = re.compile(r"Merge [0-9a-f]{40} into [0-9a-f]{40}")


def _tag(version: tuple[int, ...]) -> str:
    """`(0, 5, 0)` -> `v0.5.0`, the spelling `git` knows this version by."""
    return "v" + ".".join(str(part) for part in version)


def tickets_in(subject: str) -> set[int]:
    """Every ticket number a merge subject names, in either spelling."""
    return {int(n) for n in _TICKET.findall(subject)} | {int(n) for n in _BRANCH.findall(subject)}


def is_githubs_own_merge(subject: str) -> bool:
    """True for the ephemeral merge GitHub builds for a `pull_request` run, and for nothing else.

    CI runs `on: [push, pull_request]`, and the `pull_request` event checks out `refs/pull/N/merge`: a
    commit GitHub creates on the fly to test the branch against the base, which exists on no branch and is
    never pushed. It is `HEAD` in that checkout, so it lands inside the prepared release's range, and its
    subject is written by GitHub - there is no author to ask for a ticket and no place to write one.
    """
    return _GITHUB_MERGE.fullmatch(subject) is not None


def merge_subjects(start: str, end: str) -> list[str]:
    """The subject line of every merge commit in `start..end`, newest first.

    MERGES AND NOT COMMITS, because a merge is the unit a release is assembled from here: work happens on
    a branch and arrives in one commit whose subject says which ticket arrived. Counting commits instead
    would count a branch's internal history, which nobody promised to describe.

    GitHub's own ephemeral merge is dropped (si#97). It is not a change this release carries - it is the
    scaffolding a `pull_request` run is built on, gone the moment the pull request closes - so it belongs
    in no release range's population at all, and asking it for a ticket made every pull request red.
    """
    out = subprocess.run(["git", "log", "--merges", "--format=%s", f"{start}..{end}"],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    return [line.strip() for line in out.stdout.splitlines()
            if line.strip() and not is_githubs_own_merge(line.strip())]


def sections() -> dict[tuple[int, ...], str]:
    """Each `## X.Y.Z` heading's body, up to the next heading of the same level."""
    body = PAGE.read_text(encoding="utf-8")
    parts = re.split(r"^## (\d+\.\d+\.\d+)\s*$", body, flags=re.MULTILINE)
    return {_version("v" + name): text for name, text in zip(parts[1::2], parts[2::2])
            if _version("v" + name) is not None}


def ranges_under_test() -> dict[tuple[int, ...], tuple[str, str]]:
    """Every documented version at or above the floor, with the `git` range its section describes.

    A RELEASED version's range ends at its own tag. The one version that is documented and NOT tagged is
    the release being prepared - the existing assertion above allows exactly one - and its range ends at
    `HEAD`, because that is what the tag will point at. Writing the notes before the tag is the workflow
    (#3), so the prepared section has to be measurable before there is anything to measure it against.

    A version with no earlier tag is skipped: its range has no lower end, so there is nothing to compute.
    """
    released = released_versions()
    out: dict[tuple[int, ...], tuple[str, str]] = {}
    for version in sorted(sections()):
        if version < FLOOR:
            continue
        earlier = [v for v in released if v < version]
        if not earlier:
            continue
        out[version] = (_tag(earlier[-1]), _tag(version) if version in released else "HEAD")
    return out


def test_every_merge_in_a_documented_range_names_its_ticket():
    """The precondition the rule below rests on, held as its own assertion rather than assumed.

    A completeness check reading merge subjects is worth exactly what those subjects say. A merge that
    names no ticket is a change this file cannot ask for, so it would be a silent hole in the population -
    and the rule would go on passing while the thing it counts got smaller.

    MEASURED, and it is a zero rather than an allowance: across every documented range - 34 merges from
    `v0.3.0` to `HEAD` - not one names nothing. That includes the five merges that are pure
    re-integrations of `main` - eight of the thirty-four - which is the case the objection to this rule is
    usually made about: they carry no prose of their own and deserve none, and they name their ticket
    anyway. So no exemption is
    needed here, and the answer to "not every merge deserves a paragraph" is that the rule below does not
    ask for one - it takes the UNION of the numbers and asks that each appear somewhere in the section.
    Those eight cost the notes nothing, because their numbers are already there.
    """
    # arrange
    ranges = ranges_under_test()

    # act
    silent = {rng: subject for rng in ranges.values()
              for subject in merge_subjects(*rng) if not tickets_in(subject)}
    counted = sum(len(merge_subjects(*rng)) for rng in ranges.values())

    # assert
    assert ranges, "no documented version has a measurable range, so this suite is ruling on nothing"
    assert counted, "the ranges under test contain no merges at all, so the population is empty"
    assert not silent, (
        "these merges name no ticket in their subject, so no release section can be asked to describe "
        "them: " + "; ".join(f"{rng[0]}..{rng[1]}: {subject!r}" for rng, subject in silent.items())
        + ". A merge subject is where a release range says what it carries - write the number into it "
          "(`#42`, `si#42`, or a `si42-` branch name), or this file cannot see the change at all")


def test_githubs_own_ephemeral_merge_is_not_counted_as_silent():
    """The one merge in a range that no author wrote and no author can fix (si#97).

    CI runs `on: [push, pull_request]`, and the `pull_request` event checks out `refs/pull/N/merge` - a
    merge commit GitHub creates on the fly to test the branch against the base. It is `HEAD` there, so it
    falls inside the prepared release's range; its subject is machine-written and carries no ticket. The
    rule above therefore failed on EVERY pull request, for the one commit its author could not touch.
    """
    # arrange
    subject = ("Merge 528027af46caeab8a57bad0e9f8ce41852b67599 into "
               "d128e1bcba34a7f6d4f9c5dd24cd37fbcd116d38")

    # act
    skipped = is_githubs_own_merge(subject)

    # assert
    assert not tickets_in(subject), "the premise: this subject names nothing, so the rule would fail on it"
    assert skipped, "GitHub's ephemeral merge is not a merge this repository wrote, so it cannot be asked "\
                    "for a ticket - and no author can put one into it"


def test_a_real_merge_that_names_no_ticket_is_still_counted_as_silent():
    """The assurance the skip must not spend, held as its own assertion.

    The whole worth of the rule above is that a merge landing without a number is caught. So the skip is
    the EXACT machine format and nothing near it: a short hash, a branch name, or any word past the
    second hash means a human wrote the subject, and a human can write the number in.
    """
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
    skipped = [subject for subject in written_by_a_human if is_githubs_own_merge(subject)]

    # assert
    assert not any(tickets_in(subject) for subject in written_by_a_human), \
        "the premise: none of these names a ticket, so each one is a merge the rule has to catch"
    assert not skipped, ("these subjects were written by a person and name no ticket, so the rule must "
                         "still fail on them: " + "; ".join(repr(s) for s in skipped))


def test_every_ticket_merged_into_a_release_is_named_in_its_section():
    """The failure si#82 was raised for: a section that describes the pull request instead of the tag.

    Nothing here reads the prose - only that each number merged into the range appears somewhere in the
    section. A section may say MORE than its range (0.5.0 names si#82, which explains why it was rewritten
    after the tag; 0.6.0 names si#81, which is open), and it may name one number twice: si#61's
    measurement landed in 0.5.0 and its repair in 0.6.0, si#26's Python half in one release and its Java
    half in the next. A number in two sections is therefore correct and expected, and what the sections
    have to do - which no assertion can check - is say which half was which.
    """
    # arrange
    body = sections()
    under_test = {v: rng for v, rng in ranges_under_test().items() if v >= COMPLETE_FROM}

    # act
    gaps = {}
    for version, (start, end) in under_test.items():
        merged = {number for s in merge_subjects(start, end) for number in tickets_in(s)}
        named = tickets_in(body[version])
        if merged - named:
            gaps[version] = (sorted(merged - named), start, end, len(merged))

    # assert
    assert under_test, f"no documented version is at or above {_tag(COMPLETE_FROM)}, so nothing is checked"
    assert not gaps, "\n".join(
        f"the {_tag(v)} section names {n - len(missing)} of the {n} tickets merged into {start}..{end}; "
        f"missing: {', '.join('si#' + str(m) for m in missing)}"
        for v, (missing, start, end, n) in sorted(gaps.items()))


def test_the_page_says_from_which_release_every_ticket_is_named():
    """The boundary lives in two places - `COMPLETE_FROM` and the page's own prose - so it is pinned.

    Read out of the INTRODUCTION rather than the whole page, and that is what makes it an assertion: every
    version has a `## X.Y.Z` heading, so a search over the whole file would find `0.5.0` whatever the page
    said about it. The introduction is the text before the first section, and a number there is one
    somebody wrote about the rule.
    """
    # arrange
    intro = PAGE.read_text(encoding="utf-8").split("\n## ", 1)[0]

    # assert
    assert ".".join(str(part) for part in COMPLETE_FROM) in intro, (
        f"the page's introduction must name {_tag(COMPLETE_FROM)} as the release from which every merged "
        f"ticket is listed, because that is the boundary this suite holds it to")


def test_exactly_one_section_is_excused_from_completeness():
    """Half of what pays for `COMPLETE_FROM`: the exemption may not grow.

    An exemption's real cost is not the case it was written for, it is the second case somebody adds to it
    quietly. So the excused population is pinned rather than described: exactly one documented version is
    below the completeness floor, and it is the floor of the page itself. Raising `COMPLETE_FROM` to
    excuse a release somebody did not feel like writing up fails here, naming it.
    """
    # arrange
    documented = documented_versions()

    # act
    excused = [v for v in documented if v >= FLOOR and v < COMPLETE_FROM]

    # assert
    assert excused == [FLOOR], (
        f"exactly one section is excused from naming its tickets - {_tag(FLOOR)}, whose notes predate the "
        f"rule - and the excused set is now {[_tag(v) for v in excused]}; a release below "
        f"{_tag(COMPLETE_FROM)} that is not the page's own floor is a release nobody wrote up")


def test_the_excused_section_really_is_the_one_that_could_not_pass():
    """The other half, and the reason the exemption is not simply a hole.

    An exemption is worth nothing if the thing it excuses would have passed anyway - it then guards
    nothing and merely stands there looking justified. So the excused section is required to be genuinely
    incomplete. The day somebody writes those numbers into it, this goes red and says the useful thing:
    the exemption has outlived its reason, so move `COMPLETE_FROM` down and delete it.

    Same shape as `REFUSED_VERSION` in `test_case_python_chapter.py`, where a version exempted from "must
    be a tag" is required, in its own assertion, to really never have been cut.
    """
    # arrange
    start, end = ranges_under_test()[FLOOR]
    merged = {number for s in merge_subjects(start, end) for number in tickets_in(s)}
    named = tickets_in(sections()[FLOOR])

    # assert
    assert merged, f"no ticket was merged into {start}..{end}, so the exemption rules on nothing"
    assert merged - named, (
        f"the {_tag(FLOOR)} section now names every one of the {len(merged)} tickets merged into "
        f"{start}..{end}, so its exemption guards nothing: set COMPLETE_FROM to {FLOOR} and delete it")
