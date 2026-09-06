"""The five-phases chapter, held against the catalogue it describes (si#35).

WHY A TEST AND NOT PROOFREADING. The chapter prints a number per namespace - "In the catalogue today: 4
tasks." - and lists the coordinates behind it. Those are a SECOND source for something `catalogue.yaml`
already states, and a second source is a thing that drifts: the day a task lands the page is wrong and
nobody finds out, because a wrong sentence on a website fails nothing. So the page is read back and
compared with the catalogue, the way si#34's `test_the_website_quotes_the_refusal_word_for_word` reads
its block quote back and compares it with the real load error. Same construction, different source.

WHAT IS COMPARED, and why all three rather than one:

  * the OVERVIEW table - one row per namespace, its kind and its count - because that is the number a
    reader takes away;
  * each SECTION's own coordinate list, because the overview could be right while the list under it is
    stale;
  * the DIAGRAM, because the two empty ribs are marked as empty in it, and a marker on the wrong node is
    exactly the lie the ticket exists to prevent ("a page that draws an empty rib as filled is worse
    than no page").

THE DESCRIPTIONS ARE GONE, AND THAT IS THE FIX (si#46). The sections used to carry a sentence beside
each of the twenty-two coordinates, and `_section_coordinates` read only the FIRST cell, so the
sentences were an unchecked second source for something `catalogue.yaml` already states. si#46 offered
three ways out: quote the `help:` sentences word for word, accept a DERIVED form (imperative -> third
person) and refuse anything else, or drop the descriptions and point at the generated command
reference. The third was taken, and measurement is what settled it rather than taste: the drift the
ticket predicted had ALREADY happened, in paraphrases nobody had compared. `docs:render` had grown the
word "architecture"; `test:typecheck-python` had lost "(no Docker, no lab)"; `vcs:submodules` had lost
"lib/platform". A derived-form check would therefore have gone red on the page it was landing on,
forcing those rows to be rewritten, and would then have fenced in every future wording here for good -
a rule bought at the price of the flexibility the kernel exists to offer.

NO COUNT IS GIVEN, and the omission is deliberate rather than lazy. The first version of this docstring
said "nine and thirteen"; a mechanical word-for-word measure says ten and twelve, and a stricter reading
of what "changed in substance" means says fewer again. The number depends on the method, and the first
one here was typed rather than run - six paragraphs under a page which says that a count typed onto a
page is wrong on the day nobody checks it. The named examples above hold under every reading, which is
what makes them evidence and the number not.

A second source one does not have cannot drift, and it needs no rule to watch it either.

What replaced it is not a wording rule but a structural one, and it is the whole of what si#46's first
acceptance can still mean here: a coordinate in a section is a bare list item and nothing else, so a
description put back beside one - the ticket's own
`| build:image | Builds a wheel and uploads it to PyPI. |` included - makes this suite red. The
sentences themselves live in the generated command reference, which carries the catalogue's own `help:`
for all twenty-two and is rebuilt from it every time.

Nothing here counts the page against itself: every expectation is computed from `catalogue.load()`, and
the page is the thing being checked.

RED WHEN THERE IS NOTHING. A check that cannot tell "nothing to do" from "failed" is the defect this
repository keeps finding, so none of the helpers below returns an empty result for a missing page, a
missing heading or a missing table - each raises, and the suite goes red. `test_the_chapter_is_not_empty`
holds that at the top, and every count assertion is paired with the number of things it ruled on.

AAA throughout.
"""
import re

import pytest

from simplon import catalogue as catalogue_mod

from conftest import ROOT

#: The chapter under test.
CHAPTER = ROOT / "site" / "content" / "building" / "phases.md"

#: The chapter list this half of the site renders, and the place the new chapter has to appear in.
INDEX = ROOT / "site" / "content" / "building" / "_index.md"

#: The five phases of the delivery loop, spelled out rather than derived from the catalogue: a test that
#: read the set out of the same file it then asserts the set of would hold nothing. `support` is
#: deliberately absent - it is the group that supports the five, not a sixth of them (si#34).
PHASES = ("build", "test", "release", "deploy", "monitor")

#: The kind wording the overview table uses, per namespace. The page has to say which of the three a
#: namespace is, because the three behave differently, and the wording is checked rather than trusted.
AGNOSTIC_PHASE = "phase, agnostic"
ENV_FIRST_PHASE = "phase, env-first"
NOT_A_PHASE = "not a phase"
FAMILY = "family"

#: What the diagram writes on a phase the catalogue carries nothing for.
EMPTY_MARKER = "no catalogue task yet"

#: What it writes on a phase that takes an environment before the verb.
ENV_FIRST_MARKER = "env-first"


# --- what the catalogue actually says ------------------------------------------------------------------


def _catalogue_coordinates() -> dict[str, set[str]]:
    """Every catalogue coordinate, grouped by namespace - plus an EMPTY entry for a declared group that
    has no coordinate at all.

    The empty entries are the whole point of the ticket: `deploy` and `monitor` are groups the platform
    declares and offers nothing for, and a mapping built only from the tasks would not have a key for
    them, so the page could omit them and stay green.
    """
    cat = catalogue_mod.load()
    by_namespace: dict[str, set[str]] = {group: set() for group in cat.groups}
    for coordinate in cat.tasks:
        by_namespace.setdefault(coordinate.split(":", 1)[0], set()).add(coordinate)
    return by_namespace


def _expected_kind(namespace: str) -> str:
    """The wording the overview table must carry for one namespace, derived from the catalogue."""
    cat = catalogue_mod.load()
    if namespace not in cat.groups:
        return FAMILY
    if namespace not in PHASES:
        return NOT_A_PHASE
    return ENV_FIRST_PHASE if cat.groups[namespace].get("env_first") else AGNOSTIC_PHASE


# --- reading the page back -----------------------------------------------------------------------------


def _text() -> str:
    """The chapter, refusing to be empty. A page that is gone raises on read; a page that is blank would
    otherwise let every parser below return nothing and every comparison hold vacuously."""
    body = CHAPTER.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{CHAPTER} is empty")
    return body


#: A table row whose first cell is a single backticked token: `| `build` | phase, agnostic | 1 |`.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$")

#: The sentence each section prints its own count in.
_COUNT = re.compile(r"^\*\*In the catalogue today: (\d+) tasks?\.\*\*")


def _table(heading: str, header: str) -> dict[str, list[str]]:
    """One table on the page, as `first cell -> the remaining cells`.

    Located by its HEADING and its header row rather than by "the n-th table on the page", so a table
    added above it does not silently become the thing under test. A table that is not there raises: an
    empty mapping would make every comparison over it hold vacuously.
    """
    lines = _text().split("\n")
    start = lines.index(heading)
    rows: dict[str, list[str]] = {}
    seen_header = False
    for line in lines[start:]:
        if line.startswith(header):
            seen_header = True
            continue
        if not seen_header:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        match = _ROW.match(line)
        if not match:
            continue
        rows[match.group(1)] = [cell.strip().strip("*") for cell in match.group(2).split("|")]
    if not rows:
        raise ValueError(f"{CHAPTER}: no table '{header}...' under '{heading}'")
    return rows


def _groups_table() -> dict[str, list[str]]:
    """The opening table: group -> [what it means, takes an environment]."""
    return _table("## The five, and the one beside them", "| group |")


def _overview() -> dict[str, tuple[str, int]]:
    """The overview table: namespace -> (kind, printed count)."""
    return {name: (cells[0], int(cells[-1]))
            for name, cells in _table("## What the catalogue offers today", "| namespace |").items()}


def _section(namespace: str) -> list[str]:
    """The lines of one `### `<namespace>`` section, up to the next heading of any level."""
    lines = _text().split("\n")
    start = lines.index(f"### `{namespace}`")
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        out.append(line)
    return out


def _section_count(namespace: str) -> int:
    """The number that section prints for itself, or a ValueError if it prints none."""
    for line in _section(namespace):
        match = _COUNT.match(line)
        if match:
            return int(match.group(1))
    raise ValueError(f"{CHAPTER}: section '{namespace}' prints no 'In the catalogue today: N tasks.'")


#: A coordinate as a section lists one: a bullet whose ENTIRE content is one backticked coordinate.
#: Anchored at both ends on purpose - that is what makes "and nothing else" checkable, and what a
#: description put back beside the name would break.
_ITEM = re.compile(r"^- `([^`]+)`$")


def _section_coordinates(namespace: str) -> set[str]:
    """The coordinates that section lists. Prose mentions do not count - only a list item of its own."""
    found = set()
    for line in _section(namespace):
        match = _ITEM.match(line)
        if match and ":" in match.group(1):
            found.add(match.group(1))
    return found


def _diagram() -> str:
    """The mermaid block, refusing to be absent or blank."""
    match = re.search(r"^```mermaid\n(.*?)^```$", _text(), re.S | re.M)
    if match is None or not match.group(1).strip():
        raise ValueError(f"{CHAPTER}: no mermaid block")
    return match.group(1)


#: A mermaid node declaration: `deploy["deploy<br/>env-first"]`.
_NODE = re.compile(r'^\s*(\w+)\[\"(.*?)\"\]', re.M)

#: A labelled mermaid edge: `build -- "artefacts" --> test`.
_EDGE = re.compile(r'^\s*(\w+) -- "([^"]+)" --> (\w+)\s*$', re.M)


# --- the chapter exists, and is placed -----------------------------------------------------------------


def test_the_chapter_is_not_empty():
    """The one that has to fail first. Every comparison below reads this file, so a deleted or blanked
    page must be a red suite rather than a page of vacuous truths."""
    # act
    body = _text()

    # assert: a real chapter, not a stub - the sections the rest of this file parses are all here
    assert body.startswith("---\ntitle: \"The five phases\"\n")
    assert len(body.splitlines()) > 100


def test_the_chapter_comes_before_every_chapter_that_assumes_the_phases():
    """Acceptance 1: in the menu ahead of the chapters that presuppose the phases. Hextra orders by
    `weight:`, so the check is over the front matter of the whole directory rather than over one file."""
    # arrange
    weights = {}
    for page in sorted(CHAPTER.parent.glob("*.md")):
        if page.name == "_index.md":
            continue
        match = re.search(r"^weight: (\d+)$", page.read_text(encoding="utf-8"), re.M)
        assert match, f"{page} declares no weight"
        weights[page.stem] = int(match.group(1))

    # assert: every chapter that leans on the phases renders after this one
    assert weights["phases"] < weights["manifest"]
    assert weights["phases"] < weights["tasks"]
    assert weights["phases"] < weights["test-levels"]
    assert weights["phases"] < weights["environments"]
    assert weights["phases"] < weights["rules"]

    # assert: and the weights are still distinct, so the order is stated rather than left to a tie-break
    assert len(set(weights.values())) == len(weights)


def test_the_chapter_is_listed_on_the_section_index():
    """A page Hugo renders and nothing links to is a page nobody reads."""
    # act
    index = INDEX.read_text(encoding="utf-8")

    # assert
    assert 'card link="phases/"' in index


def test_the_opening_table_quotes_the_catalogues_own_wording():
    """The chapter opens by saying what each group MEANS, and every word of it is already in
    `catalogue.yaml` as the `help:` a product inherits. Two sources for one string is a thing that
    drifts, so the page is compared with the file rather than proofread against it."""
    # arrange
    cat = catalogue_mod.load()

    # act
    printed = _groups_table()

    # assert: the six groups, each carrying the catalogue's own sentence
    assert set(printed) == set(cat.groups)
    for name, node in cat.groups.items():
        assert printed[name][0] == node["help"], f"'{name}' is described as {printed[name][0]!r}"

    # assert: and the environment column is the `env_first:` flag, not a remembered one
    for name, node in cat.groups.items():
        assert printed[name][-1] == ("yes" if node.get("env_first") else "no"), name


# --- the counts, against the catalogue -----------------------------------------------------------------


def test_the_overview_table_lists_every_namespace_the_catalogue_has_and_no_other():
    """Acceptance 3, the outer half: the page cannot quietly omit a namespace, which is how a count
    stays right while the picture stops being complete."""
    # arrange
    expected = _catalogue_coordinates()

    # act
    printed = _overview()

    # assert: the six declared groups and the three families, exactly
    assert set(printed) == set(expected)
    assert len(printed) == 9


def test_the_overview_counts_are_the_catalogues_own():
    """Acceptance 3: every number in the overview is compared with the catalogue rather than read.

    The paired assertion at the end is the point - a comparison that ruled on nothing returns exactly
    like one that ruled on twenty-two, and only one of those is evidence.
    """
    # arrange
    expected = _catalogue_coordinates()

    # act
    printed = _overview()

    # assert
    ruled = 0
    for namespace, coordinates in expected.items():
        assert printed[namespace][1] == len(coordinates), (
            f"the page prints {printed[namespace][1]} for '{namespace}', the catalogue has "
            f"{len(coordinates)}: {sorted(coordinates)}")
        ruled += len(coordinates)

    # assert: and it ruled on the whole catalogue
    assert ruled == len(catalogue_mod.load().tasks)
    assert ruled > 0


def test_the_overview_says_which_namespaces_are_phases_env_first_and_families():
    """The `kind` column is derived too: a group promoted to env-first, or a family that becomes a
    group, changes the wording the page owes its reader."""
    # act
    printed = _overview()

    # assert
    for namespace, (kind, _count) in printed.items():
        assert kind == _expected_kind(namespace), f"'{namespace}' is described as '{kind}'"

    # assert: the split the ticket is about is really in there - five phases, one group beside them
    kinds = [kind for kind, _ in printed.values()]
    assert kinds.count(AGNOSTIC_PHASE) + kinds.count(ENV_FIRST_PHASE) == len(PHASES)
    assert kinds.count(NOT_A_PHASE) == 1


@pytest.mark.parametrize("namespace", sorted(_catalogue_coordinates()))
def test_each_sections_own_list_names_exactly_that_namespaces_coordinates(namespace):
    """Acceptance 3, the inner half. The overview could be right while the list under it is stale, so
    each section is compared with the catalogue on its own - and the section's own printed count with
    its own list, which is what keeps the two halves of the page honest with each other."""
    # arrange
    expected = _catalogue_coordinates()[namespace]

    # act
    listed = _section_coordinates(namespace)
    printed = _section_count(namespace)

    # assert
    assert listed == expected
    assert printed == len(expected)


def test_no_section_writes_a_description_beside_a_coordinate():
    """si#46's acceptance 1, in the only shape it can still have: the descriptions are GONE, so what has
    to be red is a description coming back.

    The sections used to print a sentence beside each coordinate, and nothing compared those sentences
    with the `help:` they were paraphrases of. By the time anybody measured, several had stopped saying
    what the catalogue says - how many depends on how strictly one reads, which is why no count stands
    here either (see the module docstring). The fix is not a rule about how a paraphrase may be
    worded - that would fence in every future sentence on this page to catch a copy nobody needs - but
    the removal of the copy: the coordinate is a bare list item, its sentence lives once, in the
    generated command reference.

    So this rules on SHAPE and never on wording, which is what keeps it from becoming the very thing
    si#46 rejected.
    """
    # arrange: every line of every namespace section, and the ticket's own example of the shape that
    # must not come back
    example = "| `build:image` | Builds a wheel and uploads it to PyPI. |"

    # act
    offenders = []
    listed = 0
    for namespace in _catalogue_coordinates():
        for line in _section(namespace):
            if "`" not in line or ":" not in line:
                continue
            if _ITEM.match(line):
                listed += 1
                continue
            if line.startswith(("|", "- `", "* `")):
                offenders.append(f"{namespace}: {line}")

    # assert
    assert offenders == [], ("a coordinate carries a description again; the catalogue's own sentence is "
                             f"in the generated command reference and belongs nowhere else: {offenders}")

    # assert: the ticket's example really is a shape this rejects, rather than one that happens not to
    # appear - the assertion above would pass just as happily over a page with nothing on it
    assert not _ITEM.match(example)
    assert listed == len(catalogue_mod.load().tasks)
    assert listed > 0


def test_the_page_sends_the_reader_to_the_one_place_the_sentences_live():
    """Dropping the descriptions is only honest if the page says where they went. The generated command
    reference carries the catalogue's own `help:` for every coordinate and is rebuilt from it on every
    build, so it is the single source rather than a second one.

    The link is looked for in the SECTION that holds the coordinate lists, not anywhere on the page: a
    chapter this long mentions the command reference in several places, and an assertion satisfied by
    any of them would be satisfied by a page that had dropped the pointer where it is owed.
    """
    # arrange: the part of the page between the heading that introduces the lists and the first list
    body = _text()
    start = body.index("## What the catalogue offers today")
    intro = body[start:body.index("### `", start)]

    # act / assert
    assert "../../using/commands/" in intro, "the sections drop the descriptions and point nowhere"

    # assert: and it is offered as the place the sentences live, rather than as a bare link
    assert "help:" in intro


def test_every_catalogue_coordinate_appears_somewhere_on_the_page():
    """The whole catalogue is accounted for. A task added tomorrow lands in no section, and this is the
    assertion that says so rather than a count that happens to stay right."""
    # arrange
    cat = catalogue_mod.load()

    # act
    listed: set[str] = set()
    for namespace in _catalogue_coordinates():
        listed |= _section_coordinates(namespace)

    # assert
    assert listed == set(cat.tasks)
    assert len(listed) == 22, "the count moved - update the page, then this number"


# --- the two empty ribs --------------------------------------------------------------------------------


def test_the_empty_phases_are_shown_as_empty():
    """Acceptance 4. `deploy` and `monitor` carry nothing, and the page has to say nothing rather than
    leaving the reader to infer it from a section with no table in it."""
    # arrange
    expected = _catalogue_coordinates()
    empty = {name for name in PHASES if not expected[name]}

    # assert: it is still these two - if the catalogue fills one, this test is the reminder
    assert empty == {"deploy", "monitor"}

    # assert: and each says so in its own words, and in the overview
    for name in empty:
        assert _section_count(name) == 0
        assert _overview()[name][1] == 0


def test_the_empty_ribs_are_exactly_the_env_first_phases():
    """The ticket's actual point, stated where it can stop being true: the two phases with no reusable
    task are the two where reuse would be worth the most, because they are the two about the shared
    environment rather than about the product's own material."""
    # arrange
    cat = catalogue_mod.load()
    expected = _catalogue_coordinates()

    # act
    empty = {name for name in PHASES if not expected[name]}
    env_first = {name for name in PHASES if cat.groups[name].get("env_first")}

    # assert
    assert empty == env_first

    # assert: and the page names the open question rather than leaving the gap unexplained
    body = _text()
    assert "https://github.com/marcozwyssig/simplon/issues/5" in body


# --- the diagram -----------------------------------------------------------------------------------


def test_the_diagram_draws_the_six_groups_and_nothing_else():
    """The picture is over the platform's groups, so a seventh box - or a missing one - is a picture of
    a different model."""
    # arrange
    expected = set(catalogue_mod.load().groups)

    # act
    nodes = dict(_NODE.findall(_diagram()))

    # assert
    assert set(nodes) == expected


def test_the_diagram_shows_what_each_phase_hands_the_next():
    """What the ticket asked the picture for: not five boxes in a row, but the five handovers - and a
    closed loop, because monitoring that reaches nobody is a fifth phase joined to no first."""
    # act
    edges = _EDGE.findall(_diagram())

    # assert: the loop, in order, each arrow carrying what flows along it
    assert edges == [
        ("build", "artefacts", "test"),
        ("test", "a verdict", "release"),
        ("release", "a published version", "deploy"),
        ("deploy", "a running instance", "monitor"),
        ("monitor", "what it observed", "build"),
    ]


def test_the_diagram_marks_as_empty_exactly_the_phases_the_catalogue_carries_nothing_for():
    """The strongest of the four acceptances, applied to the drawing: a marker on the wrong box is the
    lie the ticket exists to prevent, and the drawing is the place a reader believes fastest."""
    # arrange
    expected = _catalogue_coordinates()

    # act
    nodes = dict(_NODE.findall(_diagram()))

    # assert
    marked = {name for name, label in nodes.items() if EMPTY_MARKER in label}
    assert marked == {name for name in PHASES if not expected[name]}

    # assert: and no filled rib is drawn as empty either
    for name, label in nodes.items():
        assert (EMPTY_MARKER in label) == (name in expected and not expected[name]), name


def test_the_diagram_marks_the_env_first_phases():
    """`deploy` and `monitor` take the environment before the verb, and the picture says which two."""
    # arrange
    cat = catalogue_mod.load()

    # act
    nodes = dict(_NODE.findall(_diagram()))

    # assert
    marked = {name for name, label in nodes.items() if ENV_FIRST_MARKER in label}
    assert marked == {name for name, node in cat.groups.items() if node.get("env_first")}


def test_the_diagram_puts_support_beside_the_loop_and_not_in_it():
    """The owner's decision, drawn. `support` is the group that supports the five, so it is outside the
    subgraph and on none of the handovers - nothing is passed ALONG it."""
    # act
    diagram = _diagram()
    inside = diagram[diagram.index("subgraph"):diagram.index("\n  end")]

    # assert: the five are in the loop, support is not
    for phase in PHASES:
        assert f'{phase}["' in inside
    assert 'support["' not in inside

    # assert: and it carries none of the five handovers
    assert not [edge for edge in _EDGE.findall(diagram) if "support" in (edge[0], edge[2])]
