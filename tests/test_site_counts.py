"""Every count the site states about something this repository can compute (si#66).

WHY A TEST AND NOT PROOFREADING. si#66 found three pages counting the worked examples and all three
saying something other than eight - two had been right once, the third never was, and nothing anywhere
read any of them. That is the FOURTH typed number to go stale on this site, on a site whose own rules
chapter says a number typed into a document is wrong on the first day nobody checks it.

THE FIX IS NOT A NEW NUMBER, and si#66 is explicit about why: replacing "seven" with "eight" moves the
defect instead of removing it, and in half a year the page says eight over nine sections. So every count
below is COMPUTED from the thing it counts and compared with the page word for word - the construction
`test_the_summary_sentence_counts_the_catalogue_and_not_a_memory` already uses on `phases.md`, and
`sitepages.number_word` is its number-word helper, moved there so there is one of it rather than two.

WHAT THE SWEEP FOUND, which is the more valuable half of the ticket. Looking for OTHER unwatched counts
turned up five more families across four pages, none of them read by anything:

  * the two ribs the catalogue draws empty, in the `phases/` card on `building/_index.md`. `phases.md`
    itself has had this checked since si#35; the card that summarises it never did;
  * the six design rules, counted in the home page's feature grid, in `building/_index.md`'s card, and
    FOUR MORE TIMES in `rules.md`'s own prose - a chapter that counts itself six times and reads itself
    none;
  * the five refusals the loader raises for a task, counted in `task-and-command.md`'s own heading, in
    its closing callout, and in `building/_index.md`'s card;
  * the four keys a task may declare, counted in the same chapter's prose while the loader's `TASK_KEYS`
    sits one import away.

Every one of them is CORRECT today. That is the point rather than an anticlimax: si#66's three were the
ones that had already rotted, and these are the same construction one commit before it happens. The
count that has not drifted yet is exactly the one worth reading back, because nothing else ever will.

WHAT IS NOT CHECKED, recorded rather than left as a silence:

  * ORDINALS. `rules.md` writes "whether the seventh is sitting in your own tree" and "Before you add the
    seventeenth", and both are a derived count plus one. `number_word` spells cardinals; an ordinal
    helper would be a second formatter for one job, and the second of those numbers belongs to the
    refusal census (`test_refusal_census.py`), which owns that population. Named here so the gap has a
    name;
  * the FIVE REFUSAL MESSAGES `task-and-command.md` quotes in block quotes. Those are quoted error text,
    which this repository holds to a different rule ("a quoted error text is a second source for a
    string, not prose") and pins elsewhere - `test_coordinate_placement.py` and `test_why_chapter.py`
    both do it for their own page. These five are unpinned. That is a finding about strings rather than
    about counts, so it is reported rather than fixed here;
  * the count of PAGES, chapters or links. `test_site_links.py` holds those, and holds a floor rather
    than a number, for the reason stated there.

RED WHEN THERE IS NOTHING. Every source below raises rather than returning zero, and every assertion is
paired with the population it ruled on: a comparison over an empty page returns exactly like one over
eight sections, and only one of those is evidence.

AAA throughout.
"""
from __future__ import annotations

import re

from simplon import catalogue as catalogue_mod
from simplon.orchestrator.model import treeform

import sitepages
from sitepages import CONTENT, number_word

#: The pages that carry a count of something.
EXAMPLES = CONTENT / "using" / "examples.md"
USING_INDEX = CONTENT / "using" / "_index.md"
GETTING_STARTED = CONTENT / "using" / "getting-started.md"
HOME = CONTENT / "_index.md"
BUILDING_INDEX = CONTENT / "building" / "_index.md"
RULES = CONTENT / "building" / "rules.md"
TASK_AND_COMMAND = CONTENT / "building" / "task-and-command.md"


def _text(page):
    """One page, refusing to be empty - a blanked page would let every `in` below hold or fail for the
    wrong reason, and a missing one would raise somewhere less legible."""
    if not page.is_file():
        raise FileNotFoundError(f"{page} is not a page, so the count on it could not be read")
    body = page.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{page} is empty")
    return body


def _section(page, heading: re.Pattern) -> tuple[str, str]:
    """One `## ` section of a page, located by a PATTERN rather than by its text, plus what the heading
    line itself said.

    The pattern matters: several of the headings below carry the very number under test, so locating the
    section by its full text would mean the section could only ever be found while the number was already
    right - a check that passes because it cannot fail.
    """
    lines = _text(page).split("\n")
    for index, line in enumerate(lines):
        match = heading.match(line)
        if not match:
            continue
        body = []
        for following in lines[index + 1:]:
            if following.startswith("## "):
                break
            body.append(following)
        return line, "\n".join(body)
    raise ValueError(f"{page}: no heading matching {heading.pattern!r}")


# --- the worked examples, which is si#66 -----------------------------------------------------------------

#: A worked example's own heading: `## 3. Read what a step actually printed`.
_NUMBERED = re.compile(r"^##\s+(\d+)\.\s+\S", re.M)

#: Any number word this site could spell, longest first so `six` never matches inside `sixteen`.
_ANY_NUMBER = "|".join(sorted((number_word(n) for n in range(100)), key=len, reverse=True))

#: A count of jobs, however it is spelled: "seven jobs", "Seven real jobs". Number words only - "the jobs
#: that actually come up" is prose and not a claim about how many there are.
_COUNTED_JOBS = re.compile(rf"\b({_ANY_NUMBER})\s+(?:real\s+)?jobs\b", re.I)


def _worked_examples() -> list[int]:
    """The numbers the worked-example headings carry, in the order they appear.

    Raises on a chapter with no numbered section: three pages state this count, and a source that
    answered zero would make all three of them wrong in the one direction nobody would question.
    """
    numbers = [int(match.group(1)) for match in _NUMBERED.finditer(_text(EXAMPLES))]
    if not numbers:
        raise ValueError(f"{EXAMPLES} carries no numbered `## N.` section, so there is nothing to count")
    return numbers


def test_the_worked_examples_are_numbered_one_to_n_without_a_gap():
    """The source has to be a source before anything can be counted off it.

    Without this the count is the number of numbered headings, which is not the same as the number the
    reader sees: a chapter numbered 1, 2, 2, 3 has four headings and says three, and every page below
    would then agree with a number that is wrong on the page it came from.
    """
    # act
    numbered = _worked_examples()

    # assert
    assert numbered == list(range(1, len(numbered) + 1)), (
        f"{EXAMPLES.name} numbers its sections {numbered}; a count off them only means anything while "
        f"they run 1..N")
    assert len(numbered) > 1


def test_the_three_pages_that_count_the_worked_examples_count_the_chapter():
    """si#66's acceptance. Three pages, one source: the chapter's own section headings.

    Each sentence is BUILT here and looked for verbatim, so the failure names the sentence the page must
    carry rather than saying a number is wrong somewhere. The three wordings differ because the three
    contexts differ, and that is fine - what may not differ is the number in them.
    """
    # arrange
    count = len(_worked_examples())
    word = number_word(count)

    # act / assert: the chapter's own opening
    assert f"the other half: {word} jobs" in _text(EXAMPLES), (
        f"{EXAMPLES.name} must say 'the other half: {word} jobs' - it has {count} numbered sections")

    # assert: the card that offers the chapter
    assert f"{word.capitalize()} real jobs, end to end:" in _text(USING_INDEX), (
        f"{USING_INDEX.parent.name}/_index.md must say '{word.capitalize()} real jobs, end to end:'")

    # assert: and the page that sends the reader there
    assert f"walks {word} jobs end to end." in _text(GETTING_STARTED), (
        f"{GETTING_STARTED.name} must say 'walks {word} jobs end to end.'")

    # assert: the comparison really ruled on a chapter rather than on an empty one
    assert count > 1


def test_no_page_counts_the_worked_examples_a_second_time_and_differently():
    """What the three assertions above cannot catch, and what si#66 actually found: a page can carry the
    right sentence and a stale one beside it, and the `in` check would be satisfied by the first.

    Two of the three counts were once right and stopped being so; the way that survives a fix is a second
    copy nobody looked for. So every number word this site could spell is looked for in front of "jobs",
    across the whole site, and every one of them has to be the computed one.
    """
    # arrange
    word = number_word(len(_worked_examples()))

    # act
    spelled = {(page.relative_to(CONTENT), match.group(1).lower())
               for page in sitepages.pages()
               for match in _COUNTED_JOBS.finditer(sitepages.without_code(_text(page)))}

    # assert
    assert {found for _page, found in spelled} == {word}, (
        f"the site counts the worked examples as {sorted({f for _p, f in spelled})}; the chapter has "
        f"{word}: {sorted(spelled)}")

    # assert: and it found the three pages the ticket names, not one of them three times
    assert len({page for page, _found in spelled}) == 3, f"only {sorted(spelled)} state this count"


# --- the empty ribs, counted a second time on a card -----------------------------------------------------


def test_the_card_for_the_phases_chapter_counts_the_empty_ribs_off_the_catalogue():
    """The count `phases.md` has had checked since si#35, restated on the card that offers the page and
    read by nothing until now.

    A group the catalogue declares and carries no coordinate for is the thing being counted, exactly as
    `test_the_empty_phases_are_shown_as_empty` computes it - a task landing in `deploy` moves this number
    and would otherwise leave the card saying two forever.
    """
    # arrange
    cat = catalogue_mod.load()
    empty = {group for group in cat.groups
             if not any(coordinate.startswith(f"{group}:") for coordinate in cat.tasks)}

    # act
    word = number_word(len(empty))

    # assert
    assert f"the {word} ribs that are still empty" in _text(BUILDING_INDEX), (
        f"the phases card must say 'the {word} ribs that are still empty'; the catalogue draws "
        f"{sorted(empty)} empty")

    # assert: and the catalogue really has both kinds, so the count is a distinction and not a constant
    assert empty and len(empty) < len(cat.groups)


# --- the six rules, counted six times --------------------------------------------------------------------

#: What every rule section on `rules.md` ends with, and what the chapter's own introduction promises:
#: "Each rule ends with a way to check whether your own code has the same shape." That promise is what
#: makes this the source - the number of rules is the number of things that carry the closing check, not
#: the number of `##` headings, two of which are not rules at all.
_CHECK_YOUR_OWN = "**Check your own:**"


def _rules() -> int:
    """How many rules `rules.md` states, counted by the closing check each one carries."""
    found = _text(RULES).count(_CHECK_YOUR_OWN)
    if not found:
        raise ValueError(f"{RULES} carries no {_CHECK_YOUR_OWN!r}, so its rules could not be counted; "
                         f"the chapter promises one per rule")
    return found


def test_every_page_that_counts_the_design_rules_counts_the_chapter():
    """Six statements of one number across three pages, and nothing read any of them.

    The two cards are what a reader sees before opening anything; the four in `rules.md` are the chapter
    describing itself, which is the kind of sentence that survives a seventh rule being added without
    anybody thinking of it. All six are built from the same source here.
    """
    # arrange
    count = _rules()
    word = number_word(count)

    # act
    owed = {
        HOME: [f"{word.capitalize()} design rules"],
        BUILDING_INDEX: [f"{word.capitalize()} rules the kernel is built on"],
        RULES: [f"Before the {word},",
                f"these {word} things happened",
                f"of the {word} are silence",
                f"every one of the {word} lives"],
    }

    # assert
    ruled = 0
    for page, sentences in owed.items():
        body = _text(page)
        for sentence in sentences:
            assert sentence in body, (
                f"{page.relative_to(CONTENT)} must say '{sentence}' - {RULES.name} states {count} rules "
                f"(counted by '{_CHECK_YOUR_OWN}')")
            ruled += 1

    # assert: and it ruled on all six statements, not on the first page it happened to open
    assert ruled == sum(len(sentences) for sentences in owed.values())
    assert count > 1


# --- the five refusals, and the four keys ----------------------------------------------------------------

#: The refusals section's heading, matched on its SHAPE. The number in it is the thing under test, so
#: matching on the full text would find the section only while it was already right.
_REFUSALS_HEADING = re.compile(r"^## The (\w+) refusals$")

#: One refusal's lead-in: a paragraph that opens with a bold sentence naming the shape being refused.
_REFUSAL = re.compile(r"^\*\*A [^*]+\*\*", re.M)


def _refusals() -> int:
    """How many refusals `task-and-command.md` lists, counted by the bold lead-ins in its own section."""
    _heading, body = _section(TASK_AND_COMMAND, _REFUSALS_HEADING)
    found = len(_REFUSAL.findall(body))
    if not found:
        raise ValueError(f"{TASK_AND_COMMAND}: the refusals section lists none, so nothing was counted")
    return found


def test_every_page_that_counts_the_loader_refusals_counts_the_section():
    """A number in a heading, a number in the callout under it, and a number on a card in the other half
    of the site - all three saying how many refusals the loader raises for a task, all three unread."""
    # arrange
    count = _refusals()
    word = number_word(count)

    # act
    heading, _body = _section(TASK_AND_COMMAND, _REFUSALS_HEADING)

    # assert: the section names its own size
    assert heading == f"## The {word} refusals", (
        f"{TASK_AND_COMMAND.name} heads the section '{heading}' and lists {count} refusals under it")

    # assert: and so does the callout that closes it, and the card that offers the chapter
    assert f"Read the {word} together" in _text(TASK_AND_COMMAND)
    assert f"the {word} things the loader refuses" in _text(BUILDING_INDEX)

    # assert: the section really listed something
    assert count > 1


def test_the_chapter_counts_the_task_keys_the_loader_accepts():
    """The smallest of the unwatched counts and the one with the shortest way to its source: the chapter
    says a task key outside "the four" is rejected, and the four are `treeform.TASK_KEYS`, one import
    away. Add a fifth key tomorrow and the sentence is wrong with nothing to say so."""
    # arrange
    word = number_word(len(treeform.TASK_KEYS))

    # act / assert
    assert f"Anything outside the {word} is rejected" in _text(TASK_AND_COMMAND), (
        f"the chapter must say 'Anything outside the {word} is rejected' - a task takes "
        f"{', '.join(treeform.TASK_KEYS)}")

    # assert: and the loader really declares a set to count
    assert len(treeform.TASK_KEYS) > 1
