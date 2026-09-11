"""The Java use case chapter, held against the things it claims (si#26).

WHY A TEST AND NOT PROOFREADING. `site/content/using/case-java.md` walks one delivery loop with a
toolchain the kernel has never met, and the walk is made of second sources: command names its product's
manifest already assembles, coordinates `catalogue.yaml` already declares, an image reference
`simplon.docker.pinned_image` already rules on, refusal and verdict sentences the kernel already builds
word for word, and a table of its own rows. Every one of those is a fact stated twice, and this
repository has now measured five times what an unwatched copy does.

WHAT IS DIFFERENT HERE FROM `test_case_python_chapter.py`, and why the suites are two rather than one.
The Python chapter follows THIS product, so its commands resolve against `simplon.yaml` sitting in the
checkout. The Java one follows a product that is not in this repository and never will be - so its
manifest travels with the chapter as `tests/fixtures/case_java_manifest.yaml`, and every
`./javademo.sh ...` the page types is resolved against the tree ASSEMBLED from that file by the same
loader a real product goes through. That is the honest version of the check: the fixture is the manifest
the chapter's transcripts were produced with, and a kernel change that would stop it loading turns this
suite red rather than leaving a chapter describing a product that no longer assembles.

WHAT THE CHAPTER PROMISES ITS READER, and therefore what has to be held:

  * THE LABELS. `run`, `derived`, `does not exist yet`, nothing else, and a step that does not exist has
    to carry the ticket where the decision is open. The page's own ratio sentence is computed from the
    table it summarises.
  * THE COMMANDS AND COORDINATES. Resolved against the assembled product tree and the catalogue.
  * THE MANIFEST IT QUOTES. Every YAML block on the page has to be a verbatim part of the fixture. A
    chapter quoting a manifest it has edited for the page is the same defect as a transcript with one
    half retyped.
  * THE REFUSAL AND THE VERDICTS. The pin gate's message and the two gate sentences are quoted output,
    which this repository holds to a stricter rule than prose: they are second sources for a string and
    are pinned against the code that builds them.
  * THE ARCHIVE NUMBERS. Nothing here can prove a measurement, and nothing tries. What it CAN prove is
    that the three statistic blocks are arithmetically coherent, that they agree with the suite size the
    chapter states one screen higher, and that the `setup-failed` run is the empty one - which is the
    property si#70 and si#61 are about, and the one a copied-and-edited table would break first.
  * THE COUNTS. The scaffold's Python files, the empty ribs, and the price of the detour this chapter's
    seam removed - each read off the thing that owns it rather than typed.

WHAT IS NOT CHECKED, said rather than left as a silence. The prose. The transcripts, which are dated
evidence from one machine on one day and are deliberately never a live claim - the same standing the
Python chapter's are given. And the links, which are not this suite's: `test_site_links.py` walks EVERY
page there is with `sitepages`, so this chapter is inside its population already, and a second walker
here would be the drifting copy this repository spends its time deleting.

RED WHEN THERE IS NOTHING. Every helper raises rather than returning an empty result, and every count
assertion is paired with the population it ruled on.

AAA throughout.
"""
from __future__ import annotations

import json
import re

import pytest
import yaml

from simplon import bootstrap, docker
from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod
from simplon.tasks import docs as docs_task
from simplon.tasks.testrun import IMPL_DETAIL
from simplon.verdict import GateVerdict, Verdict

import sitepages
from conftest import ROOT

#: The chapter under test.
CHAPTER = sitepages.chapter("case-java.md")

#: The card list this half of the site renders, and the place the chapter has to appear in.
INDEX = sitepages.index("what")

#: The manifest of the product the chapter follows. It is not in this repository - javademo is a Java
#: product driven for si#26 - so it travels with the chapter, and every command the page types is
#: resolved against the tree this file assembles.
FIXTURE = ROOT / "tests" / "fixtures" / "case_java_manifest.yaml"

#: The page that owns the price of the detour this chapter's seam removed (si#61). The chapter restates
#: those numbers to make its point; they are read back off the page that measured them.
TEST_LEVELS = sitepages.chapter("test-levels.md")

#: The closed vocabulary of honesty labels - the same three the Python chapter carries, deliberately, so
#: a reader moving between the two cases is reading one scale and not two.
LABELS = ("run", "derived", "does not exist yet")

#: The label whose rows owe the reader a ticket.
OPEN = "does not exist yet"

#: The image reference the chapter shows being refused. The `where` that goes with it is NOT typed here:
#: it is read off the pin-gate call the same page prints, so the two halves of that story cannot drift.
UNPINNED = "gradle:latest"


# --- reading the page back -----------------------------------------------------------------------------


def _text() -> str:
    """The chapter, refusing to be empty."""
    body = CHAPTER.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{CHAPTER} is empty")
    return body


def _prose() -> str:
    """The chapter with its fenced blocks removed - what is left is prose and tables."""
    return sitepages.without_code(_text())


def _blocks(language: str) -> list[str]:
    """Every fenced block of one language, refusing to be empty.

    A chapter that lost its YAML would otherwise make the "the manifest it quotes is the product's own"
    assertion pass over nothing at all.
    """
    found = re.findall(rf"^```{language}\n(.*?)^```", _text(), re.S | re.M)
    if not found:
        raise ValueError(f"{CHAPTER}: no ```{language} block, so there is nothing to compare")
    return found


def _flat(text: str) -> str:
    """One line, single-spaced - the shape a quoted message can be compared in after the page wrapped it
    across three lines to fit a column."""
    return " ".join(text.split())


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


def _runs() -> list[list[str]]:
    """The three-run archive table: [run, rc, statistic JSON, verdict] per row."""
    return _rows("| run | rc |")


def _product():
    """The javademo command tree, assembled from the fixture by the loader a real product goes through."""
    return manifest_mod.load(FIXTURE.read_text(encoding="utf-8"), catalogue=catalogue_mod.load())


def _environments() -> set[str]:
    """The env names the fixture declares - the outer token an env-first command takes."""
    raw = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    names = set(raw.get("environments") or {})
    if not names:
        raise ValueError(f"{FIXTURE} declares no environment, so an env-first command could not be read")
    return names


# --- the chapter exists, and is placed -----------------------------------------------------------------


def test_the_chapter_is_not_empty():
    """The one that has to fail first. Every comparison below reads this file, so a deleted or blanked
    page must be a red suite rather than a page of vacuous truths."""
    # act
    body = _text()

    # assert: a real chapter, not a stub
    assert body.startswith('---\ntitle: "A Java product, end to end"\n')
    assert len(body.splitlines()) > 100


def test_the_chapter_is_listed_on_the_section_index():
    """A page Hugo renders and nothing links to is a page nobody reads."""
    # act
    index = INDEX.read_text(encoding="utf-8")

    # assert
    assert 'card link="case-java/"' in index


def test_the_chapter_renders_next_to_the_python_one_it_is_the_counterpart_to():
    """The two cases are a pair and the page says so in its first sentence, so the reader must meet them
    together: after the chapter of jobs both lean on, and immediately after its sibling. Hextra orders by
    `weight:`, so the check is over the front matter of the whole directory.

    WHAT si#170 RETIRED HERE, said rather than deleted. This used to compare this chapter's weight with
    `getting-started` and `releasing` as well. `weight:` orders within a SECTION, and after the site was
    divided by question those two are in `how/`, which is offered AFTER `what/` - deliberately, because
    the division shows what the loop looks like before it explains it. So "must not be offered before
    them" is no longer true of this site, and a weight comparison across two sections would be a
    number that holds for a reason nobody stated. What replaces it is the half that was always the
    point and is section-independent: the chapter POINTS at those pages instead of retelling them."""
    # arrange
    weights = {}
    for page in sorted(CHAPTER.parent.glob("*.md")):
        if page.name == "_index.md" or page in sitepages.generated_pages():
            continue
        match = re.search(r"^weight: (\d+)$", page.read_text(encoding="utf-8"), re.M)
        assert match, f"{page} declares no weight"
        weights[page.stem] = int(match.group(1))

    # assert: after the chapter it defers to and shares a section with
    assert weights["case-java"] > weights["examples"]

    # assert: it points at the pages it leans on rather than retelling them
    linked = {sitepages.resolve(link) for link in sitepages.internal_links(CHAPTER)}
    for name in ("getting-started.md", "examples.md", "releasing.md"):
        assert sitepages.chapter(name) in linked, (
            f"{CHAPTER.name} no longer links to {name}, so it either retells that page or leaves the "
            f"reader without it")

    # assert: and directly after its sibling, with nothing between them
    assert weights["case-java"] == weights["case-python"] + 1

    # assert: the weights are still distinct, so the order is stated rather than left to a tie-break
    assert len(set(weights.values())) == len(weights)


# --- the labels, which are the whole ticket ------------------------------------------------------------


def test_every_step_carries_exactly_one_of_the_three_labels():
    """si#26's honesty rule, in the only shape a machine can hold: the vocabulary is closed.

    Nothing here can prove a `run` label true - that took running the command, and the evidence column
    says where. What it CAN prove is that no row escaped the question, which is how such a table rots: a
    step is added, nobody knows whether it was driven, and the cell gets a fourth word that means
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
    go and read why - otherwise it is indistinguishable from "we forgot"."""
    # arrange
    rows = [cells for cells in _steps() if cells[3] == OPEN]

    # act / assert
    assert rows, f"no step is labelled {OPEN!r}; if the loop is complete now, this test has to go"
    for cells in rows:
        assert re.search(r"https://github\.com/marcozwyssig/simplon/issues/\d+", cells[4]), (
            f"step {cells[0]} says {OPEN!r} and names no ticket: {cells[4]!r}")


def test_the_ratio_the_chapter_states_is_the_one_its_own_table_has():
    """The typed number, which is the failure this repository has now produced five times on this site.
    The paragraph under the table counts the labels; the table is the source, so the paragraph is
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

    # assert: the chapter's own argument is that a Java case can really be driven, so most of it has to
    # be. A page that had quietly become mostly `derived` would still pass every check above.
    assert run > derived + missing, (
        f"{run} of {len(rows)} steps are `run`; a chapter of derivations is the result si#26 refuses")


# --- the commands and coordinates it types -------------------------------------------------------------


def _typed_commands() -> list[tuple[str, ...]]:
    """Every `./javademo.sh ...` the chapter types, as its token path with the env prefix removed.

    Options and arguments are dropped: `release tag v0.1.0` names the same command as `release tag`. An
    env-first command carries its environment as the OUTER token (`./javademo.sh dev deploy up`), which
    is a value and not part of the command's name, so a leading token the fixture declares as an
    environment comes off here.
    """
    envs = _environments()
    found = []
    for line in re.findall(r"\./javademo\.sh ([^\n`]+)", _text()):
        tokens = [token for token in line.split() if not token.startswith("-")]
        if tokens and tokens[0] in envs:
            tokens = tokens[1:]
        if tokens:
            found.append(tuple(tokens))
    return found


def test_every_command_the_chapter_types_is_one_this_product_assembles():
    """A chapter that tells people to type a command which no longer exists is worse than one that says
    nothing: they conclude they misread the site rather than that the site is stale.

    Resolved against the tree ASSEMBLED from the fixture, not against a list of names read out of it - so
    a kernel change that breaks the load path for a product whose only runner is its own turns this red,
    which is exactly the change si#61 made possible and this chapter is about.
    """
    # arrange
    product = _product()
    typed = _typed_commands()

    # act / assert
    assert typed, "the chapter types no command at all, so this test is ruling on nothing"
    ruled = 0
    for tokens in typed:
        group = tokens[0]
        assert group in product.groups, f"'{' '.join(tokens)}': javademo has no group '{group}'"
        assert len(tokens) > 1, f"'{' '.join(tokens)}' names a group and no command"
        assert tokens[1] in product.groups[group], (
            f"'{' '.join(tokens)}': group '{group}' has no command '{tokens[1]}' "
            f"(it has {sorted(product.groups[group])})")
        ruled += 1

    # assert: the walk really covers the loop rather than one command repeated
    assert len({tokens[:2] for tokens in typed}) >= 5
    assert ruled == len(typed)


def test_every_catalogue_coordinate_the_chapter_names_exists():
    """The coordinates are the kernel's own vocabulary, and the chapter uses them to say which task
    stands behind a product's command. A coordinate that has been renamed or removed makes the sentence
    around it false without changing a word of it.

    A coordinate is recognised by its NAMESPACE being one the catalogue carries, which is what keeps an
    image reference the chapter also writes in backticks - `gradle:latest`, quoted because the page shows
    it being refused - from being read as a task nobody declared.
    """
    # arrange
    catalogue = catalogue_mod.load()
    known = set(catalogue.tasks)
    namespaces = {coordinate.split(":")[0] for coordinate in known}
    assert namespaces, "the catalogue carries no task at all, so this test is ruling on nothing"
    pattern = rf"`(({'|'.join(sorted(namespaces))}):[a-z][a-z0-9-]*)`"

    # act
    named = {match[0] for match in re.findall(pattern, _prose())}

    # assert
    assert named, "the chapter names no coordinate, so this test is ruling on nothing"
    for coordinate in sorted(named):
        assert coordinate in known, f"the chapter names '{coordinate}', the catalogue does not carry it"


# --- the manifest it quotes ----------------------------------------------------------------------------


def test_every_manifest_block_the_chapter_quotes_is_the_products_own():
    """A chapter quoting a manifest it edited for the page is a transcript with one half retyped. Both
    YAML blocks are compared with the fixture the commands above were resolved against, verbatim, so the
    page and the product cannot describe two different declarations."""
    # arrange
    fixture = FIXTURE.read_text(encoding="utf-8")
    quoted = _blocks("yaml")

    # act / assert
    ruled = 0
    for block in quoted:
        for line in block.splitlines():
            if not line.strip():
                continue
            assert line in fixture, f"the chapter quotes a manifest line javademo does not have: {line!r}"
            ruled += 1

    # assert: it really compared something, and both blocks were reached
    assert len(quoted) >= 2, f"the chapter quotes {len(quoted)} manifest blocks; it walks a loop"
    assert ruled >= 10


def test_the_taxonomy_the_chapter_calls_nine_lines_is_nine_lines():
    """The one number in the `test` section that is the page's own to state, and therefore the one that
    goes stale silently. The block is right underneath the sentence; the sentence is computed from it."""
    # arrange
    blocks = [block for block in _blocks("yaml") if block.lstrip().startswith("suites:")]

    # act / assert
    assert len(blocks) == 1, f"the chapter shows {len(blocks)} taxonomy blocks; the sentence names one"
    lines = [line for line in blocks[0].splitlines() if line.strip()]
    word = sitepages.number_word(len(lines))
    assert f"fits in {word} lines" in _text(), (
        f"the taxonomy block is {len(lines)} lines; the chapter does not say '{word}'")


# --- the refusal and the verdicts, which are quoted strings ---------------------------------------------


def test_the_pin_gate_call_the_chapter_shows_is_one_that_passes():
    """The chapter's `build` section argues that a product can put its OWN toolchain reference through
    the kernel's image gate, and shows the line that does it. Both halves of that call are read off the
    page and handed to the real gate here: a reference that stopped passing would leave the chapter
    printing a line that no longer runs."""
    # arrange
    shown = [re.search(r"docker\.pinned_image\(\"([^\"]+)\", \"([^\"]+)\"\)", block)
             for block in _blocks("python")]
    calls = [match.groups() for match in shown if match]

    # act / assert
    assert len(calls) == 1, f"the chapter shows {len(calls)} pin-gate calls; its argument rests on one"
    image, where = calls[0]
    assert docker.pinned_image(image, where) == image, f"the chapter's own example does not pass the gate"

    # assert: and the `where` is the product's module, not the kernel's - which is the whole point of
    # showing the call at all
    assert not where.startswith("simplon"), (
        f"the chapter shows the KERNEL pinning an image ({where}); the section is about a product doing it")


def test_the_pin_refusal_the_chapter_quotes_is_the_gates_own_message():
    """A quoted error text is a second source for a string, not prose. The chapter shows what the product
    gets for writing `gradle:latest`, and the message is built here rather than remembered - including
    the `where`, read off the same call the test above checks, which is what makes the message name the
    PRODUCT's module rather than the kernel's."""
    # arrange
    quoted = [block for block in _blocks("text") if "must pin a version" in block]
    assert len(quoted) == 1, f"the chapter shows {len(quoted)} pin refusals; it argues from one"
    where = re.search(r"docker\.pinned_image\(\"[^\"]+\", \"([^\"]+)\"\)", "".join(_blocks("python")))
    assert where, "the chapter shows no pin-gate call to take the caller's name from"

    # act
    with pytest.raises(ValueError) as raised:
        docker.pinned_image(UNPINNED, where.group(1))

    # assert
    shown = _flat(quoted[0]).removeprefix("ValueError: ")
    assert shown == _flat(str(raised.value)), (
        f"the chapter quotes:\n  {shown}\nthe gate says:\n  {_flat(str(raised.value))}")


def test_the_two_gate_sentences_the_chapter_quotes_are_the_kernels_own():
    """The load-bearing quotation on the page. Both sentences are the point of the chapter's `test`
    section - one says the kernel cannot see inside the product's runner, the other says the runner told
    it something the kernel could not have known - and both are BUILT here from the value object, so a
    page that softened either into something more confident goes red."""
    # arrange
    body = _flat(_text())

    # act
    opaque = GateVerdict(gate="unit", verdict=Verdict.FAILED, rc=1, detail=IMPL_DETAIL).line
    setup = GateVerdict(gate="unit", verdict=Verdict.SETUP_FAILED, rc=1,
                        stage="gradle build (:test never ran)").line

    # assert
    assert _flat(opaque) in body, f"the chapter does not quote the impl gate's own sentence:\n  {opaque}"
    assert _flat(setup) in body, f"the chapter does not quote the setup-failed sentence:\n  {setup}"

    # assert: and both really say the thing they are quoted for, so this is not two string comparisons
    # over sentences that lost their meaning
    assert "cannot say whether one ran at all" in opaque
    assert "says nothing about the product" in setup


def test_every_outcome_word_the_chapter_prints_is_one_the_kernel_has():
    """The chapter defers the five-outcome table to its sibling and prints only the three verdicts its
    own runs produced. Those three still have to be the kernel's words: a page saying `error` or
    `broken` would be inventing a vocabulary beside the one `simplon.verdict` owns."""
    # arrange
    known = {member.value for member in Verdict}
    rows = _runs()

    # act
    printed = [cells[3].strip("`") for cells in rows]

    # assert
    assert printed, "the archive table has no rows, so this test is ruling on nothing"
    for word in printed:
        assert word in known, f"the chapter prints the outcome '{word}'; the kernel has {sorted(known)}"

    # assert: exactly one of them is a non-verdict, and it is the run the chapter calls the empty one
    non_verdicts = [word for word in printed if not Verdict(word).ran]
    assert non_verdicts == [Verdict.SETUP_FAILED.value], (
        f"the chapter's three runs report {printed}; one of them has to be the one that says nothing "
        f"about the product")


# --- the archive numbers -------------------------------------------------------------------------------


def test_the_three_archives_agree_with_each_other_and_with_the_suite_the_chapter_shows():
    """The measurement is not derivable and nothing here pretends otherwise. What IS derivable is that
    the three statistic blocks are coherent - each one's parts sum to its own total, the two runs that
    reached the tests report the suite the chapter says the product has, and the run reported as
    `setup-failed` is the EMPTY one.

    That last pairing is the property si#70 and si#61 bought and the one a copied-and-edited table would
    break first: a compiler error that arrived carrying the previous run's three passes is exactly the
    defect the chapter says was removed.
    """
    # arrange
    rows = _runs()
    tests = re.search(r"src/test/java/demo/CalculatorTest\.java\s+(\w+) @Test methods", _text())
    assert tests, "the chapter's tree listing does not say how many tests the product has"
    size = {word: number for number, word in enumerate(
        ["zero", "one", "two", "three", "four", "five", "six", "seven"])}[tests.group(1)]

    # act
    ruled = 0
    for cells in rows:
        statistic = json.loads(cells[2].strip("`"))
        parts = sum(value for key, value in statistic.items() if key != "total")

        # assert: the block adds up to its own total
        assert parts == statistic["total"], (
            f"the '{cells[0]}' run's parts sum to {parts} and it states total {statistic['total']}")

        # assert: and the run's own outcome word is the one that total belongs to
        outcome = Verdict(cells[3].strip("`"))
        if outcome.ran:
            assert statistic["total"] == size, (
                f"the '{cells[0]}' run reports {statistic['total']} tests; the product has {size}")
        else:
            assert statistic["total"] == 0, (
                f"the '{cells[0]}' run never reached the tests and still reports "
                f"{statistic['total']} of them")
        ruled += 1

    # assert: both answers really occur, so the table is a distinction and not a constant
    assert {Verdict(cells[3].strip("`")).ran for cells in rows} == {True, False}
    assert ruled == len(rows) >= 3

    # assert: and the green run is green and the red one red, which is the pair the chapter is about
    verdicts = {cells[0]: json.loads(cells[2].strip("`")) for cells in rows}
    assert verdicts["green"]["failed"] == 0 and verdicts["green"]["passed"] == size
    assert any(block["failed"] > 0 for name, block in verdicts.items() if name != "green"), (
        "no run in the table reports a failing test, so the chapter never shows a red Java test arriving "
        "red - which is the thing si#26 asks for")


# --- the counts it takes from somewhere else ------------------------------------------------------------


def test_the_scaffold_count_the_chapter_states_is_the_one_simplon_init_writes():
    """The first row of the honesty table says how much Python `simplon init` puts in a product, and the
    tree listing adds the two modules this one wrote. Both numbers are read off `bootstrap.render`, which
    IS the scaffold - so a template gaining a module turns this red instead of leaving a chapter whose
    opening claim quietly stopped being true."""
    # arrange
    scaffolded = [name for name in bootstrap.render("javademo") if name.endswith(".py")]
    body = _text()

    # act / assert: what the scaffold writes
    assert scaffolded, "the scaffold writes no Python at all, so this test is ruling on nothing"
    word = sitepages.number_word(len(scaffolded))
    assert f"{word} Python files" in body, (
        f"`simplon init` writes {len(scaffolded)} Python files: {sorted(scaffolded)}")

    # assert: and the tree listing's arithmetic - the product's own two on top of them
    listing = re.search(r"orchestrator/src/python/orchestrator/\s+(\w+) \.py files - (\w+) scaffolded, "
                        r"(\w+) written here", body)
    assert listing, "the chapter's tree listing does not break its Python file count down"
    total, base, own = listing.groups()
    numbers = {sitepages.number_word(n): n for n in range(0, 100)}
    assert numbers[base] == len(scaffolded), (
        f"the listing says {base} scaffolded; `simplon init` writes {len(scaffolded)}")
    assert numbers[total] == numbers[base] + numbers[own], (
        f"the listing says {total} = {base} + {own}, which does not add up")


def test_the_empty_ribs_count_the_chapter_names_is_the_catalogues_own():
    """`deploy` is one of the groups the catalogue draws empty, and the chapter says how many there are
    while pointing at the page that owns the argument. A pointer carrying a stale number sends the reader
    looking for something that is not there."""
    # arrange
    catalogue = catalogue_mod.load()
    empty = {group for group in catalogue.groups
             if not any(coordinate.startswith(f"{group}:") for coordinate in catalogue.tasks)}

    # act / assert
    assert empty, "the catalogue draws no group empty, so this test is ruling on nothing"
    word = sitepages.number_word(len(empty))
    assert f"one of the {word} ribs" in _text(), (
        f"the catalogue draws {len(empty)} groups empty: {sorted(empty)}")

    # assert: and `deploy` - the rib this chapter's own section is about - is really one of them
    assert "deploy" in empty


def test_the_price_of_the_detour_is_the_one_the_page_that_measured_it_carries():
    """The chapter restates what a Java product used to have to pay to get a report at all - a pytest
    gate holding `assert True`, its venv, and an archive counting a test the product does not have. Those
    numbers were measured for si#61 and belong to `building/test-levels.md`; here they are a second copy,
    so they are read back off the page that owns them rather than retyped."""
    # arrange
    owner = TEST_LEVELS.read_text(encoding="utf-8")
    body = _text()
    venv = r"(\d+) MB of suite venv"
    counted = r"counted (\w+) tests\s+where the product has (\w+)"

    # act
    here = (re.search(venv, body), re.search(counted, body))
    there = (re.search(venv, owner), re.search(counted, owner))

    # assert
    assert all(there), f"{TEST_LEVELS} no longer carries the measurement this chapter quotes"
    assert all(here), f"{CHAPTER} no longer quotes the measurement it argues from"
    assert here[0].group(1) == there[0].group(1), (
        f"the chapter says {here[0].group(1)} MB, test-levels.md measured {there[0].group(1)} MB")
    assert here[1].groups() == there[1].groups(), (
        f"the chapter says {here[1].groups()}, test-levels.md measured {there[1].groups()}")


def test_the_doctoolchain_key_the_chapter_names_is_the_one_the_task_reads():
    """The `docs` section tells a Java product the two things it has to declare to get a PDF. One of them
    is a manifest key, and the key's name lives in `simplon.tasks.docs` - a rename there would leave the
    chapter telling people to write something the task never looks for."""
    # arrange
    body = _text()

    # act / assert
    assert f"{docs_task.VERSION_KEY}:" in body, (
        f"the chapter does not name the manifest key '{docs_task.VERSION_KEY}' the render reads")
    assert docs_task.CONFIG_FILE in body, (
        f"the chapter does not name the config file '{docs_task.CONFIG_FILE}' docToolchain looks for")

    # assert: and the version it shows is one the product really declares, held to the same pin gate
    declared = str(yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))[docs_task.VERSION_KEY])
    assert f'{docs_task.VERSION_KEY}: "{declared}"' in body
    assert docker.pinned_image(f"{docs_task.IMAGE_REPOSITORY}:{declared}", "the chapter")


# --- the chapter's own design ---------------------------------------------------------------------------


def test_the_chapter_defers_rather_than_retelling_the_python_one():
    """Its whole design is to be the SECOND case: the same five verbs with a different toolchain, leaning
    on the pages that own each detail instead of restating them. Two things follow, and both are checked
    because Hugo would render either failure silently.

    (The links themselves are `test_site_links.py`'s, which walks every page there is - this chapter is
    inside that population already, and a second walker here would be the drifting copy.)
    """
    # act
    links = set(re.findall(r"\]\((\.\.?/[^)]*)\)", _text()))

    # assert: it really points somewhere, and at several different places
    assert len(links) >= 5, f"the chapter points at {len(links)} pages; its whole design is deferring"

    # assert: and it points at its sibling, which is the one link the pairing depends on
    assert any(link.startswith("../case-python/") for link in links), (
        "the chapter never links the Python case it is the counterpart to")

    # assert: it does NOT restate the five-outcome table its sibling owns - a second copy of that table
    # is precisely the second source si#66 keeps finding on this site
    assert "| outcome |" not in _text(), (
        "the chapter reprints the gate outcome table; `case-python.md` owns it and this page links it")
