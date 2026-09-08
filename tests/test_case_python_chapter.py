"""The Python use case chapter, held against the things it claims (si#26).

WHY A TEST AND NOT PROOFREADING. `site/content/using/case-python.md` is a walk through one delivery
loop, and a walk is made of second sources: command names the manifest already carries, catalogue
coordinates `catalogue.yaml` already declares, image pins `simplon.yaml` already states, a version
derived by a scheme `pyproject.toml` already configures, and a count of its own rows. Every one of
those is a fact stated twice, and this repository has measured twice what an unwatched copy does - the
paraphrases of si#46 and the typed count of si#35, the second one written six paragraphs under the
sentence saying counts are read rather than typed.

WHAT THE CHAPTER PROMISES ITS READER, and therefore what has to be held:

  * THE LABELS. Each step says `run`, `derived` or `does not exist yet`, and the whole ticket is that
    those must be true. A fourth word, or a row with none, would let the promise dissolve quietly - so
    the vocabulary is closed, and a step that does not exist has to carry the ticket where it is open.
    The page's own ratio sentence is compared with the table it summarises.
  * THE COMMANDS. Every `./simplon.sh ...` the page types is resolved against the assembled command
    tree. A renamed command leaves a chapter telling people to type something that is gone.
  * THE COORDINATES. Every `namespace:name` is looked up in the catalogue.
  * THE FIVE OUTCOMES. The gate outcome table is computed from `simplon.verdict.Verdict`, including
    `ran` - which is the assertion si#55 is really about. A page that printed four outcomes, or that
    marked `killed` as evidence about the product, would be the very defect that ticket removed.
  * THE VERSION TRANSCRIPT. `git describe` and the wheel name are shown one under the other; the two
    halves are compared with each other and with the scheme `pyproject.toml` declares. A copied
    transcript with one half edited is exactly how such a block goes wrong.
  * THE PINS AND THE TAGS. The images the transcript shows are compared with `simplon.yaml`; every
    `vX.Y.Z` the page names has to be a tag this checkout carries.
  * THE LINKS. The chapter's whole design is to point at the pages that own each detail instead of
    telling it a second time - so a link that does not resolve is not a typo here, it is the design
    failing silently. Hugo renders a dead relative link without complaining.

WHAT IS NOT CHECKED. The prose, and deliberately: what a step MEANT is not derivable from anything.
Nor is agile-cockpit, the private sibling the chapter also follows - it is not on this machine in CI,
and a suite that read it would be green or red depending on which checkout it ran in. What the chapter
says about that product is dated evidence, the same standing as the transcripts quoted on the release
pages, and it is deliberately never a live claim.

RED WHEN THERE IS NOTHING. Every helper below raises rather than returning an empty result, and every
count assertion is paired with the number of things it ruled on: a comparison over zero rows returns
exactly like one over fourteen, and only one of those is evidence.

AAA throughout.
"""
from __future__ import annotations

import re
import subprocess

import pytest
import yaml

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod
from simplon.verdict import Verdict

from conftest import ROOT

#: The chapter under test.
CHAPTER = ROOT / "site" / "content" / "using" / "case-python.md"

#: The card list this half of the site renders, and the place the chapter has to appear in.
INDEX = ROOT / "site" / "content" / "using" / "_index.md"

#: The product manifest the chapter's commands and image pins are measured against.
MANIFEST = ROOT / "simplon.yaml"

#: The build configuration the version transcript is measured against.
PYPROJECT = ROOT / "pyproject.toml"

#: The closed vocabulary of honesty labels. si#26 asks for exactly these three and for them to be true;
#: a fourth would let "we are not sure" back in under a new name.
LABELS = ("run", "derived", "does not exist yet")

#: Small numbers as this site spells them in prose. A count read off the catalogue has to be compared
#: with a word, not with a digit, and inventing the mapping inside each assertion would spread it.
_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}

#: The label whose rows owe the reader a ticket. A step that does not exist and does not say where the
#: decision is open is the gap dressed up as a plan.
OPEN = "does not exist yet"


# --- reading the page back -----------------------------------------------------------------------------


def _text() -> str:
    """The chapter, refusing to be empty. Every parser below reads this, so a deleted or blanked page
    must be a red suite rather than a page of vacuous truths."""
    body = CHAPTER.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{CHAPTER} is empty")
    return body


def _prose() -> str:
    """The chapter with its fenced blocks removed - what is left is prose and tables.

    Transcripts are quoted output and hold strings that look like coordinates or commands but are
    neither; reading them as claims would make the checks below rule on the wrong text.
    """
    return re.sub(r"^```.*?^```", "", _text(), flags=re.S | re.M)


#: One row of a pipe table, as its cells.
def _rows(header_starts_with: str) -> list[list[str]]:
    """Every data row of the one table whose header row starts with `header_starts_with`.

    Located by its header rather than by "the n-th table", so a table added above it does not silently
    become the thing under test. A table that is not there raises.
    """
    out: list[list[str]] = []
    seen = False
    for line in _text().split("\n"):
        if line.startswith(header_starts_with):
            seen = True
            continue
        if not seen:
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        out.append(cells)
    if not out:
        raise ValueError(f"{CHAPTER}: no table whose header starts with {header_starts_with!r}")
    return out


def _steps() -> list[list[str]]:
    """The honesty table: [number, step, command, label, evidence] per row."""
    return _rows("| # | Step |")


def _outcomes() -> dict[str, tuple[str, str]]:
    """The gate outcome table: outcome -> (the `ran` column, the meaning)."""
    rows = _rows("| outcome |")
    parsed: dict[str, tuple[str, str]] = {}
    for cells in rows:
        name = cells[0].strip("`")
        parsed[name] = (cells[1], cells[2])
    return parsed


def _manifest():
    return manifest_mod.load(MANIFEST.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


# --- the chapter exists, and is placed -----------------------------------------------------------------


def test_the_chapter_is_not_empty():
    """The one that has to fail first. Every comparison below reads this file, so a deleted or blanked
    page must be a red suite rather than a page of vacuous truths."""
    # act
    body = _text()

    # assert: a real chapter, not a stub
    assert body.startswith('---\ntitle: "A Python product, end to end"\n')
    assert len(body.splitlines()) > 100


def test_the_chapter_is_listed_on_the_section_index():
    """A page Hugo renders and nothing links to is a page nobody reads."""
    # act
    index = INDEX.read_text(encoding="utf-8")

    # assert
    assert 'card link="case-python/"' in index


def test_the_chapter_renders_after_the_pages_it_leans_on():
    """It links onward to Getting started, the examples and Cutting a release rather than retelling
    them, so it must not be offered before them. Hextra orders by `weight:`, so the check is over the
    front matter of the whole directory rather than over one file."""
    # arrange
    weights = {}
    for page in sorted(CHAPTER.parent.glob("*.md")):
        if page.name in ("_index.md", "commands.md"):
            continue
        match = re.search(r"^weight: (\d+)$", page.read_text(encoding="utf-8"), re.M)
        assert match, f"{page} declares no weight"
        weights[page.stem] = int(match.group(1))

    # assert
    assert weights["case-python"] > weights["getting-started"]
    assert weights["case-python"] > weights["examples"]
    assert weights["case-python"] > weights["releasing"]

    # assert: and the weights are still distinct, so the order is stated rather than left to a tie-break
    assert len(set(weights.values())) == len(weights)


# --- the labels, which are the whole ticket ------------------------------------------------------------


def test_every_step_carries_exactly_one_of_the_three_labels():
    """si#26's honesty rule, in the only shape a machine can hold: the vocabulary is closed.

    Nothing here can prove a `run` label true - that took running the command, and the evidence column
    says where. What it CAN prove is that no row escaped the question, which is how such a table rots:
    a step is added, nobody knows whether it was driven, and the cell gets a fourth word that means
    "unsure" without admitting it.
    """
    # arrange
    rows = _steps()

    # act
    labels = [cells[3] for cells in rows]

    # assert
    assert rows, "the honesty table has no rows, so this test is ruling on nothing"
    for cells, label in zip(rows, labels):
        assert label in LABELS, f"step {cells[0]} is labelled {label!r}, which is not one of {LABELS}"

    # assert: and it really ruled on every row
    assert len(labels) == len(rows)


def test_every_step_that_does_not_exist_yet_links_the_ticket_where_it_is_open():
    """The label that would otherwise be a shrug. "Does not exist yet" is only honest if the reader can
    go and read why - otherwise it is indistinguishable from "we forgot", and this repository's whole
    argument is that those two must never look alike."""
    # arrange
    rows = [cells for cells in _steps() if cells[3] == OPEN]

    # act / assert
    assert rows, f"no step is labelled {OPEN!r}; if the loop is complete now, this test has to go"
    for cells in rows:
        assert re.search(r"https://github\.com/marcozwyssig/simplon/issues/\d+", cells[4]), (
            f"step {cells[0]} says {OPEN!r} and names no ticket: {cells[4]!r}")


def test_the_ratio_the_chapter_states_is_the_one_its_own_table_has():
    """The typed number, which is the failure this repository has now produced four times on this very
    site. The paragraph under the table counts the labels; the table is the source, so the paragraph is
    computed from it here rather than read."""
    # arrange
    rows = _steps()
    counted = {label: sum(1 for cells in rows if cells[3] == label) for label in LABELS}

    # act
    match = re.search(r"Of the (\d+) steps above, (\d+) are \*\*run\*\*, (\d+) are \*\*derived\*\* and "
                      r"(\d+) \*\*does not exist yet\*\*", _text())

    # assert
    assert match, "the chapter states no ratio for its own table, so the count is unwatched"
    total, run, derived, missing = (int(part) for part in match.groups())
    assert total == len(rows), f"the paragraph says {total} steps, the table has {len(rows)}"
    assert run == counted["run"]
    assert derived == counted["derived"]
    assert missing == counted[OPEN]

    # assert: and the three labels account for every row, so nothing hid outside the sum
    assert run + derived + missing == len(rows)


# --- the commands and coordinates it types -------------------------------------------------------------


def _typed_commands() -> list[tuple[str, ...]]:
    """Every `./simplon.sh ...` the chapter types, as its token path.

    Options and arguments are dropped: `release tag v0.4.0` names the same command as `release tag`,
    and a version is not a command name.
    """
    found = []
    for line in re.findall(r"\./simplon\.sh ([^\n`]+)", _text()):
        tokens = tuple(token for token in line.split() if not token.startswith("-"))
        if tokens:
            found.append(tokens)
    return found


def test_every_command_the_chapter_types_is_one_this_product_assembles():
    """A chapter that tells people to type a command which no longer exists is worse than one that says
    nothing: they conclude they misread the site rather than that the site is stale."""
    # arrange
    mf = _manifest()
    typed = _typed_commands()

    # act / assert
    assert typed, "the chapter types no command at all, so this test is ruling on nothing"
    ruled = 0
    for tokens in typed:
        group = tokens[0]
        assert group in mf.groups, f"'{' '.join(tokens)}': simplon has no group '{group}'"
        assert len(tokens) > 1, f"'{' '.join(tokens)}' names a group and no command"
        assert tokens[1] in mf.groups[group], (
            f"'{' '.join(tokens)}': group '{group}' has no command '{tokens[1]}' "
            f"(it has {sorted(mf.groups[group])})")
        ruled += 1

    # assert: the walk really covers the loop rather than one command repeated
    assert len({tokens[:2] for tokens in typed}) >= 5
    assert ruled == len(typed)


def test_every_catalogue_coordinate_the_chapter_names_exists():
    """The coordinates are the kernel's own vocabulary, and the chapter uses them to say which task
    stands behind a product's command. A coordinate that has been renamed or removed makes the sentence
    around it false without changing a word of it."""
    # arrange
    known = set(catalogue_mod.load().tasks)
    named = set(re.findall(r"`([a-z][a-z0-9-]*:[a-z][a-z0-9-]*)`", _prose()))

    # act / assert
    assert named, "the chapter names no coordinate, so this test is ruling on nothing"
    for coordinate in sorted(named):
        assert coordinate in known, f"the chapter names '{coordinate}', the catalogue does not carry it"


# --- the five outcomes (si#55) -------------------------------------------------------------------------


def test_the_outcome_table_names_every_gate_outcome_the_kernel_has_and_no_other():
    """si#55's acceptance, read back off the page. The ticket's finding was that a signal-killed run had
    no word of its own, so it borrowed one that made a false statement about the product. A page that
    still printed four outcomes would put that gap back into the documentation after it was closed in
    the code."""
    # arrange
    expected = {member.value for member in Verdict}

    # act
    printed = _outcomes()

    # assert
    assert set(printed) == expected, (
        f"the chapter prints {sorted(printed)}, the kernel has {sorted(expected)}")
    assert "killed" in printed, "the fifth outcome is the reason this table is on the page"

    # assert: and the count the prose above the table announces is the table's own, not a remembered
    # one. si#55 added the fifth outcome; a page saying "four" would be stale in the one word a reader
    # takes away.
    assert f"**{_WORDS[len(Verdict)]}** outcomes" in _text(), (
        f"the chapter does not announce {len(Verdict)} outcomes above its table")


def test_the_outcome_table_says_which_outcomes_are_evidence_about_the_product():
    """The `ran` column, computed from the enum rather than remembered. This is the load-bearing half:
    an outcome table that listed `killed` and then marked it as a statement about the product would have
    moved si#55's defect onto the website instead of removing it."""
    # act
    printed = _outcomes()

    # assert
    ruled = 0
    for name, (ran, _meaning) in printed.items():
        expected = "yes" if Verdict(name).ran else "no"
        assert ran == expected, f"the chapter says ran={ran!r} for '{name}'; the kernel says {expected!r}"
        ruled += 1

    # assert: both answers really occur, so the column is a distinction and not a constant
    assert {ran for ran, _ in printed.values()} == {"yes", "no"}
    assert ruled == len(Verdict)

    # assert: and the sentence that closes the section counts the non-verdicts off the same enum
    non_verdicts = sum(1 for member in Verdict if not member.ran)
    assert f"the {_WORDS[non_verdicts]} outcomes with `ran == False`" in _text(), (
        f"the chapter does not say that {non_verdicts} outcomes are not statements about the product")


def test_the_two_counts_the_chapter_takes_from_the_catalogue_are_the_catalogues_own():
    """Two more numbers typed into prose, and both are readable off `catalogue.yaml`: how many
    documentation commands there are to choose between, and how many groups the catalogue draws empty.

    Neither is this page's to state twice - `building/phases.md` owns the empty ribs and the examples own
    the documentation table - but the chapter points at both by saying how many there are, and a pointer
    carrying a stale number sends the reader looking for something that is not there.
    """
    # arrange
    cat = catalogue_mod.load()
    docs = {coordinate for coordinate in cat.tasks if coordinate.startswith("docs:")}
    empty = {group for group in cat.groups
             if not any(coordinate.startswith(f"{group}:") for coordinate in cat.tasks)}
    body = _text()

    # act / assert
    assert docs and empty, "the catalogue offers no docs tasks or has no empty group, so this is vacuous"
    assert f"the {_WORDS[len(docs)]} documentation commands" in body, (
        f"the catalogue carries {len(docs)} docs coordinates: {sorted(docs)}")
    assert f"one of the {_WORDS[len(empty)]} ribs" in body, (
        f"the catalogue draws {len(empty)} groups empty: {sorted(empty)}")


# --- the version transcript ----------------------------------------------------------------------------


def test_the_version_transcript_agrees_with_itself():
    """A transcript is two lines of quoted output, and the way one goes wrong is that somebody edits one
    half. The wheel name is derived from the `git describe` above it, so the derivation is redone here:
    same base version, same distance, and the abbreviated node really the start of the longer one."""
    # arrange
    body = _text()

    # act
    described = re.search(r"^v(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)$", body, re.M)
    built = re.search(r"simplon-(\d+\.\d+\.\d+)\.post1\.dev(\d+)\+g([0-9a-f]+)-py3-none-any\.whl", body)

    # assert
    assert described, "the chapter shows no `git describe` output to derive a version from"
    assert built, "the chapter shows no built wheel name in the no-guess-dev shape"
    assert described.group(1) == built.group(1), (
        f"the tag says {described.group(1)}, the wheel says {built.group(1)}")
    assert described.group(2) == built.group(2), (
        f"the tag is {described.group(2)} commits back, the wheel says dev{built.group(2)}")
    assert built.group(3).startswith(described.group(3)), (
        f"the wheel names commit g{built.group(3)}, `git describe` named g{described.group(3)}")


def test_the_version_scheme_the_chapter_names_is_the_one_this_product_declares():
    """The transcript only means what the chapter says it means if the scheme really is the one
    configured. Two sources for one setting, so the page is compared with `pyproject.toml`."""
    # arrange
    config = PYPROJECT.read_text(encoding="utf-8")
    body = _text()

    # act / assert: what the chapter claims
    assert "no-guess-dev" in body
    assert 'dynamic = ["version"]' in body

    # assert: and what the file actually says
    assert 'version_scheme = "no-guess-dev"' in config
    assert 'dynamic = ["version"]' in config
    assert not re.search(r"^version = ", config, re.M), (
        "pyproject.toml carries a static version, so the chapter's 'nothing chose that number' is false")


#: The one version the chapter names that must NOT be a tag: the row showing the release guard refusing.
#: An exemption from the assertion below, and a deliberate one - see the second test for its other half,
#: which is what keeps this from being a hole. A demonstration of a refusal is worthless if the thing
#: refused quietly came into existence anyway.
REFUSED_VERSION = "v9.9.9"


def test_every_release_the_chapter_names_is_a_tag_this_repository_carries():
    """The chapter states that a named version was cut, published and landed on PyPI. The local half of
    that - the tag exists - is checkable here, and it is the half that would rot first if a number were
    typed from memory."""
    # arrange
    out = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=True)
    tags = {line.strip() for line in out.stdout.splitlines() if line.strip()}

    # act
    # `(?<!@)` keeps a pinned Go module version - `hextra@v0.12.3` - out of the release names. That
    # exclusion is not a guess: without it this assertion went red on the theme pin, which is a version
    # of somebody else's software and was never a tag here.
    named = set(re.findall(r"(?<!@)\b(v\d+\.\d+\.\d+)\b", _prose()))

    # assert
    assert tags, "this checkout carries no tags at all, so the comparison would be vacuous"
    assert named, "the chapter names no release, so this test is ruling on nothing"
    for tag in sorted(named - {REFUSED_VERSION}):
        assert tag in tags, f"the chapter names {tag}; this checkout has no such tag"


def test_the_version_the_chapter_shows_being_refused_was_really_never_cut():
    """The other half of the exemption above, and the reason it is not a hole.

    Row 8 shows the release guard refusing a tag on a commit `main` does not carry. That row is evidence
    only if the tag never appeared - a refusal that left the tag behind would be the opposite of what the
    chapter claims, and the assertion above would have been the one place to notice.

    So the exemption is paid for: the version is excluded from "must be a tag" and required here to be
    absent. It also pins the row itself, because an exemption for a version the chapter no longer mentions
    is a rule guarding nothing.
    """
    # arrange
    out = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=True)
    tags = {line.strip() for line in out.stdout.splitlines() if line.strip()}

    # assert: the chapter still shows the refusal, and the refused tag still does not exist
    assert REFUSED_VERSION in _prose(), (
        f"the chapter no longer names {REFUSED_VERSION}, so its exemption above guards nothing")
    assert REFUSED_VERSION not in tags, (
        f"{REFUSED_VERSION} exists as a tag, so the chapter's row 8 shows a refusal that did not refuse")


def test_the_images_the_transcript_shows_are_the_ones_the_manifest_pins():
    """The docs transcript prints the Hugo image and the theme module. Both are pinned in `simplon.yaml`
    and a pin moves; a transcript that kept the old one would show a build that no longer happens."""
    # arrange
    site = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["site"]
    body = _text()

    # act / assert
    assert site["image"] in body, f"the chapter does not show the pinned image {site['image']}"
    assert site["theme"] in body, f"the chapter does not show the pinned theme {site['theme']}"

    # assert: and it shows no OTHER pin of either shape, which is how a stale one survives beside a fresh
    assert set(re.findall(r"hugomods/hugo:[\w.\-]+", body)) == {site["image"]}
    assert set(re.findall(r"github\.com/imfing/hextra@[\w.\-]+", body)) == {site["theme"]}


# --- the links, which are the chapter's design -----------------------------------------------------


# The URL base, the heading-id rule and the walk over every link now live in `sitepages` and are applied
# by `test_site_links.py` to the WHOLE site (si#67), which strictly contains this chapter: it reads the
# same relative links plus the theme shortcodes, resolves them with the same `url_dir`, and checks each
# fragment against the same `anchor`. The per-chapter copy that used to stand here is gone rather than
# kept beside it - two implementations of one rule is the second source this repository spends its time
# removing, and the copy would have been the one that drifted, because both would have stayed green.
#
# What stays here is the chapter's own DESIGN claim, which is not a fact about links in general.


def test_the_chapter_really_points_somewhere():
    """The parametrisation above is computed from the page, so a chapter that lost every link would run
    zero cases and report green. This is the paired assertion that makes the parametrised one evidence."""
    # act
    links = set(re.findall(r"\]\((\.\.?/[^)]*)\)", _text()))

    # assert: it defers to the pages that own each detail, and there are several of them
    assert len(links) >= 5, f"the chapter points at {len(links)} pages; its whole design is deferring"
