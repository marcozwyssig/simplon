"""The two sections si#29 added to `using/why.md`, held against the sources they describe.

WHY A TEST AND NOT PROOFREADING. Both new sections make claims that are already stated somewhere the
program reads: the kinds-of-work table is a second grouping of `catalogue.yaml`'s coordinate set, the
container section quotes a real load error and two real catalogue `help:` strings word for word, and the
"opposite verdict" sentence is a claim about which of two modules calls `docker.ensure_docker`. A second
source drifts, and a wrong sentence on a website fails nothing - so each of them is compared with its
source, the way si#34's `test_the_website_quotes_the_refusal_word_for_word` and si#35's
`tests/test_phases_chapter.py` are.

RED WHEN THERE IS NOTHING. A check that cannot tell "nothing to do" from "failed" is the defect this
repository keeps finding, so no helper below returns an empty result for a missing page, a missing table
or a missing block quote - each raises, and the suite goes red. `test_the_new_sections_are_not_empty`
holds that at the top, and every set comparison is paired with the number of things it ruled on.

WHAT WOULD MAKE EACH ONE RED, since an assurance nobody can break is not one:

  * the page deleted, blanked, or stripped of either section -> `_text` / `_kinds_table` / `_quotes`;
  * a task added to or removed from the catalogue -> the union assertion, which is the catalogue set;
  * a coordinate filed under two kinds of work, or under none -> the same one;
  * the pin refusal reworded in `simplon.tasks.site` -> the word-for-word quote;
  * a third task that runs in a container, or the type gate moved into one -> the derived-set assertions
    over the catalogue's own `help:` wording;
  * `simplon.tasks.image` dropping its docker gate, or `simplon.tasks.site` gaining one -> the AST check;
  * si#27 or si#45 quietly dropped from the cost list -> the link assertion;
  * "discipline" reused for a kind of work, on the site OR in the kernel -> the two terminology
    assertions. The second one exists because the first round of si#29 shipped a callout claiming
    something about `src/` that only `site/content/` was holding up, and the claim was false.

WHAT IS NOT COVERED, stated here rather than left to be discovered:

  * WHICH KIND OF WORK A COORDINATE IS FILED UNDER is editorial. The union is held against the
    catalogue, so nothing can be omitted or filed twice - but `test:report` moved into the
    "documentation" row would stay green. Judging that mechanically would mean deciding what a body IS,
    and the catalogue does not say.
  * THE MIDDLE COLUMN - the tools each row names - is editorial for the same reason, with one twist that
    makes it worse rather than better: the column names the TOOL and the kernel's argv names the
    LAUNCHER. `hugo` never appears in an argv anywhere; it runs as
    `docker run ... --entrypoint hugo`, so a check over invoked binaries would contradict a column that
    is right. The two ABSOLUTE claims in it are held -
    `test_the_bodies_the_page_says_reach_no_external_tool_really_do_not` - and the rest is prose.
  * THE COLLOCATION RULE over `src/` reads word neighbourhoods, not meaning. It catches the shape both
    real violations had ("a discipline gains sibling commands") and the shape a reintroduction would
    have; a sentence using the word for a kind of work while naming no command, group or namespace
    would pass.

AAA throughout.
"""
import ast
import re

from simplon import catalogue as catalogue_mod
from simplon.tasks import site as site_mod

from conftest import ROOT

#: The chapter under test.
CHAPTER = ROOT / "site" / "content" / "using" / "why.md"

#: The chapter that owns the OTHER meaning of "discipline", and has to keep owning it alone.
TASKS_CHAPTER = ROOT / "site" / "content" / "building" / "tasks.md"

#: The site as a whole, because a terminology rule that only looked at one page would not be one.
CONTENT = ROOT / "site" / "content"

#: The two Python trees the callout makes a claim ABOUT ("and so does the kernel's own source,
#: throughout"). A rule that stopped at `site/content/` would leave that half of the sentence held up by
#: nothing - which is how the first round of si#29 shipped a callout that was wrong about two docstrings.
CODE = (ROOT / "src", ROOT / "tests")

#: The vocabulary that gives the OTHER sense away. "discipline" next to any of these is the owner's
#: meaning - a kind of work with its own commands - not rigour, and that is the collision the callout
#: promises does not exist in the kernel. Both real violations found in review said "sibling commands".
#:
#: The six group NAMES are deliberately not in this list as bare words: `test`, `build`, `support` and
#: `release` are ordinary English too, and "these tests pin the discipline itself" is not a violation.
#: They are matched below in the form the kernel uses when it means the group - backticked, or as the
#: namespace half of a coordinate.
GROUP_WORDS = ("command", "subcommand", "group", "namespace", "verb")

#: A group named the way the kernel names one when it means the group: `build`, or `build:image`.
GROUP_TOKEN = re.compile(r"`(?:build|test|release|deploy|monitor|support)(?::[a-z-]+)?`")

#: The two headings si#29 added.
KINDS_HEADING = "## The same five verbs over very different work"
CONTAINER_HEADING = "## Why the technology travels in a container"

#: The header row of the kinds-of-work table, used to locate it by what it IS rather than by position.
KINDS_HEADER = "| the work |"

#: The phrase the site uses instead of "discipline", and the sentence that says why.
CHOSEN_TERM = "kinds of work"

#: The open costs the ticket refused to let the page leave out. si#45 was one of them and is no longer
#: open: `docs:site` now renders every Mermaid block and is red when one does not draw, so the bullet
#: stayed in the cost list - a second image and a version the reader's browser need not share are real
#: costs - and the ticket link went, because a page that keeps pointing at a closed issue is the second
#: source this repository keeps deleting.
COST_ISSUES = ("https://github.com/marcozwyssig/simplon/issues/27",)

#: A catalogue coordinate as the page writes one: `docs:site`.
_COORD = re.compile(r"`([a-z][a-z0-9-]*:[a-z][a-z0-9-]*)`")


# --- reading the page back -----------------------------------------------------------------------------


def _text() -> str:
    """The chapter, refusing to be empty. A page that is gone raises on read; a blank one would let every
    parser below return nothing and every comparison hold vacuously."""
    body = CHAPTER.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{CHAPTER} is empty")
    return body


def _section(heading: str) -> list[str]:
    """The lines under one `## ` heading, up to the next heading of the same level. Raises when the
    heading is not there: an empty section would make every assertion over it hold vacuously."""
    lines = _text().split("\n")
    if heading not in lines:
        raise ValueError(f"{CHAPTER}: no section '{heading}'")
    start = lines.index(heading)
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    if not [line for line in out if line.strip()]:
        raise ValueError(f"{CHAPTER}: section '{heading}' is empty")
    return out


def _kinds_table() -> dict[str, set[str]]:
    """The kinds-of-work table, as `the work -> the coordinates it claims`.

    Located by its heading AND its header row rather than by "the n-th table on the page", so a table
    added above it does not silently become the thing under test. A table that is not there raises.
    """
    rows: dict[str, set[str]] = {}
    seen_header = False
    for line in _section(KINDS_HEADING):
        if line.startswith(KINDS_HEADER):
            seen_header = True
            continue
        if not seen_header:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3 or set(cells[0]) <= set("-: "):
            continue
        rows[cells[0]] = set(_COORD.findall(cells[2]))
    if not rows:
        raise ValueError(f"{CHAPTER}: no table '{KINDS_HEADER}...' under '{KINDS_HEADING}'")
    return rows


def _quotes(heading: str) -> list[str]:
    """Every block quote in one section, each unwrapped back into a single line.

    The page reproduces real messages, which is two sources for one string and therefore something that
    drifts - si#34's first draft quoted a load error with a full stop the loader does not print. Reading
    them back out and comparing beats proofreading them. A section with no block quote raises.
    """
    found: list[str] = []
    current: list[str] = []
    for line in _section(heading):
        if line.startswith(">"):
            current.append(line.lstrip(">").strip())
        elif current:
            found.append(" ".join(" ".join(current).split()))
            current = []
    if current:
        found.append(" ".join(" ".join(current).split()))
    if not found:
        raise ValueError(f"{CHAPTER}: section '{heading}' quotes nothing")
    return found


# --- what the sources actually say ---------------------------------------------------------------------


def _catalogue_helps() -> dict[str, str]:
    """Every catalogue coordinate and the `help:` the kernel declares for it."""
    return {coordinate: str(body.get("help", ""))
            for coordinate, body in catalogue_mod.load().tasks.items()}


def _unpinned_image_refusal() -> str:
    """The real load error for an image reference that names no version, normalised to one line."""
    try:
        site_mod.declared({"site": {"image": "hugomods/hugo", "source": "s", "output": "o"}},
                          source="simplon.yaml")
    except ValueError as caught:
        return " ".join(str(caught).split())
    raise AssertionError("an unpinned image was accepted - the page's quoted refusal no longer happens")


#: The sentence that opens why.md's one permitted mention of the word.
DEMARCATION = "**A word this page does not use.**"


def _demarcation_block(lines: list[str]) -> set[int]:
    """The line numbers of the callout that hands the word "discipline" back to its established sense.

    Raises when there is none: an empty range would make the "every mention is inside it" assertion below
    hold for a page that had stopped demarcating anything at all.
    """
    opened = None
    for number, line in enumerate(lines):
        if line.strip().startswith("{{< callout"):
            opened = number
        elif line.strip().startswith("{{< /callout"):
            if opened is not None and any(DEMARCATION in inner for inner in lines[opened:number + 1]):
                return set(range(opened, number + 1))
            opened = None
    raise ValueError(f"{CHAPTER}: no callout carrying {DEMARCATION!r}")


def _calls_ensure_docker(dotted: str) -> bool:
    """Whether a module's SOURCE really calls `docker.ensure_docker()`.

    Parsed rather than grepped on purpose: both modules discuss the gate in their docstrings - the page's
    claim is about which one CALLS it, and a substring search would answer yes for both.
    """
    path = ROOT / "src" / (dotted.replace(".", "/") + ".py")
    if not path.is_file():
        raise ValueError(f"no such module source: {path}")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "ensure_docker"
               for node in ast.walk(tree))


# --- the sections exist --------------------------------------------------------------------------------


def test_the_new_sections_are_not_empty():
    """The one that has to fail first. Every comparison below reads this file, so a deleted, blanked or
    gutted page must be a red suite rather than a page of vacuous truths."""
    # act
    kinds = _section(KINDS_HEADING)
    container = _section(CONTAINER_HEADING)

    # assert: real sections, not stubs
    assert len([line for line in kinds if line.strip()]) > 15
    assert len([line for line in container if line.strip()]) > 25

    # assert: and the chapter they were added to is still the chapter, not something else
    assert _text().startswith("---\ntitle: \"What Simplon is\"\n")


# --- the kinds of work, against the catalogue ----------------------------------------------------------


def test_every_coordinate_in_the_kinds_table_is_a_real_one():
    """A table of invented coordinates would pass every count below and still be fiction."""
    # arrange
    known = set(_catalogue_helps())

    # act
    listed = {coordinate for row in _kinds_table().values() for coordinate in row}

    # assert
    assert listed <= known, f"the page names coordinates the catalogue does not have: {listed - known}"
    assert len(listed) > 0


def test_the_kinds_of_work_cover_the_whole_catalogue_exactly_once():
    """The strongest assertion here, and the one si#35 established the shape of: the UNION of the
    sections is the catalogue set. A task added tomorrow lands in no row, and this says so - a table that
    quietly omitted a coordinate would stay right about everything it did list."""
    # arrange
    expected = set(_catalogue_helps())

    # act
    table = _kinds_table()
    listed = [coordinate for row in table.values() for coordinate in row]

    # assert: every coordinate placed, and none placed twice
    assert sorted(listed) == sorted(set(listed)), "a coordinate is filed under two kinds of work"
    assert set(listed) == expected

    # assert: and it ruled on the whole catalogue rather than on nothing
    assert len(listed) == len(expected)
    assert len(listed) > 0


def test_the_page_says_how_many_kinds_of_work_there_are_and_the_table_agrees():
    """The prose prints a number the table is the source for, which is exactly the pair that drifts."""
    # act
    rows = _kinds_table()
    prose = "\n".join(_section(KINDS_HEADING))

    # assert
    assert len(rows) == 6
    assert "Six kinds of work" in prose


def test_the_two_ways_of_grouping_are_genuinely_different_groupings():
    """The section's actual claim, stated where it can stop being true: the kind of work a task IS and
    the phase it runs IN are two axes over one set. If they ever coincided, the whole section would be
    describing the namespace column a second time and should be deleted rather than left standing."""
    # arrange
    table = _kinds_table()

    # act
    namespaces_per_row = {work: {c.split(":", 1)[0] for c in row} for work, row in table.items()}
    rows_per_namespace: dict[str, set[str]] = {}
    for work, row in table.items():
        for coordinate in row:
            rows_per_namespace.setdefault(coordinate.split(":", 1)[0], set()).add(work)

    # assert: at least one kind of work spans several namespaces, and at least one namespace several kinds
    assert [work for work, spans in namespaces_per_row.items() if len(spans) > 1]
    assert [ns for ns, spans in rows_per_namespace.items() if len(spans) > 1]

    # assert: and the one word that is BOTH a phase and a kind of work is named as such. Review found
    # the first round claiming this was said when the section never said it - `test` is a group in the
    # catalogue and 'testing' is a row here, and a reader who is not told trips over it exactly once.
    assert "test" in catalogue_mod.load().groups
    assert [work for work in table if "testing" in work]
    assert "`test` is a phase, and testing is a kind of work" in "\n".join(_section(KINDS_HEADING))


def test_the_kind_of_work_with_no_catalogue_task_is_still_the_empty_one():
    """The section names running things as the kind of work the catalogue carries nothing for, and links
    the two empty ribs for it. The day a `deploy:` or `monitor:` task lands, that paragraph is wrong."""
    # arrange
    coordinates = set(_catalogue_helps())

    # act
    running = {c for c in coordinates if c.split(":", 1)[0] in ("deploy", "monitor")}

    # assert
    assert running == set()
    assert "../../building/phases/#the-two-empty-ribs" in "\n".join(_section(KINDS_HEADING))


def test_the_bodies_the_page_says_reach_no_external_tool_really_do_not():
    """The middle column is mostly editorial (see the file head), but two of its claims are absolute and
    therefore checkable: `tasks:generate`/`tasks:catalogue` shell out to nothing, and neither does
    `support:environments` - which review found missing from that row's tool list, where it had been
    filed under `oras`/`docker compose`/`claude` and reaches none of them.

    A negative claim is the kind most worth holding, because nothing about a passing suite would ever
    contradict it on its own.
    """
    # arrange: the bodies behind the three coordinates the page says reach nothing
    modules = ("simplon.tasks.tasks", "simplon.tasks.env")

    # act
    shelling = {}
    for module in modules:
        path = ROOT / "src" / (module.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        shelling[module] = sorted({
            (node.func.id if isinstance(node.func, ast.Name) else node.func.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Name) and node.func.id in ("run", "stream"))
                 or (isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "stream")))})

    # assert
    assert len(shelling) == len(modules)
    for module, calls in shelling.items():
        assert not calls, f"{module} now shells out ({calls}) - the page says it reaches nothing external"

    # assert: and the page still says so, in both places it says it
    section = "\n".join(_section(KINDS_HEADING))
    assert "nothing external" in section
    assert "nothing at all for `support:environments`" in section


# --- the terminology, across the whole site ------------------------------------------------------------


def test_the_word_discipline_keeps_exactly_one_meaning_on_the_site():
    """si#29's binding constraint, and the trap si#34 fell into once with 'phase'. The owner's goal
    calls these DISCIPLINES; this site already spends that word on self-restraint. So the chapter uses a
    plainer term and says so once - and that one mention is the only place on the site where the word
    appears outside its established sense."""
    # arrange
    pages = {page: page.read_text(encoding="utf-8") for page in sorted(CONTENT.rglob("*.md"))}
    assert pages, "no site content was read at all"

    # act
    mentions = {page: [line for line in body.split("\n") if "disciplin" in line.lower()]
                for page, body in pages.items()}
    carrying = {page: lines for page, lines in mentions.items() if lines}

    # assert: exactly two pages may say it - the one that owns the rigour sense, and the one that
    # explicitly declines to reuse the word
    assert set(carrying) == {TASKS_CHAPTER, CHAPTER}, f"'discipline' has spread to {sorted(carrying)}"

    # assert: the established sense is still there to be demarcated against
    assert any("the discipline that keeps the catalogue honest" in line
               for line in carrying[TASKS_CHAPTER])

    # assert: and why.md says the word only inside the callout that hands the meaning back - a mention
    # anywhere else on the page is the two-meanings-of-one-word defect the ticket is guarding against
    lines = _text().split("\n")
    inside = _demarcation_block(lines)
    said_at = [number for number, line in enumerate(lines) if "disciplin" in line.lower()]
    assert said_at, "why.md no longer demarcates the word at all"
    assert all(number in inside for number in said_at), (
        f"why.md uses 'discipline' outside its demarcation, at lines "
        f"{[n + 1 for n in said_at if n not in inside]}")

    # assert: and the demarcation really names the sense it is handing back
    block = "\n".join(lines[min(inside):max(inside) + 1])
    assert "self-restraint" in block

    # assert: the term it uses instead is really the one it uses
    assert CHOSEN_TERM in "\n".join(_section(KINDS_HEADING))


def test_the_kernel_source_keeps_the_meaning_the_callout_claims_for_it():
    """The half of the callout that `site/content/` cannot hold up: *"and so does the kernel's own
    source, throughout"*.

    The first round of si#29 asserted that over the site only, and the sentence was false - two
    docstrings in `simplon.clitaxonomy` said "when a discipline gains sibling commands", which is the
    owner's sense (a kind of work with its own commands), not rigour. Both are reworded; this is what
    stops the next one from landing unnoticed.

    WHAT IT CATCHES, and what it does not. It is a COLLOCATION rule, not a reading of meaning: the word
    beside the command vocabulary is the shape both violations had and the shape a reintroduction would
    have. A sentence that used the word for a kind of work without naming a command or a group would
    pass, and nothing here pretends otherwise - see the file head.
    """
    # arrange: the page still makes the claim this rule exists to hold up. Without it the kernel would
    # be held to a sentence nobody says any more, which is a rule outliving its reason.
    block = "\n".join(_text().split("\n")[n] for n in sorted(_demarcation_block(_text().split("\n"))))
    assert "the kernel's own source" in block

    sources = [path for tree in CODE for path in sorted(tree.rglob("*.py"))
               if path.name != "test_why_chapter.py"]     # this file is ABOUT the word
    assert len(sources) > 50, "the kernel trees were not read at all"

    # act
    offenders = []
    ruled = 0
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            if "disciplin" not in line.lower():
                continue
            ruled += 1
            said = line.lower()
            if (any(re.search(rf"\b{word}s?\b", said) for word in GROUP_WORDS)
                    or GROUP_TOKEN.search(said)):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

    # assert: the word is still there to be ruled on - a tree that had lost it would make this vacuous
    assert ruled > 0, "no occurrence of 'discipline' in the kernel at all - the callout claims one"

    # assert
    assert not offenders, ("'discipline' is used beside the command vocabulary, which is the owner's "
                           "sense and not the rigour one the callout claims:\n  " + "\n  ".join(offenders))


# --- the container section, against the code it describes ----------------------------------------------


def test_the_page_quotes_the_unpinned_image_refusal_word_for_word():
    """The reader is being shown what they will see. A full stop the loader does not print is a small lie
    in the one place a reader checks their own output against - which is how si#34 found this shape."""
    # arrange
    real = _unpinned_image_refusal()

    # act
    quoted = _quotes(CONTAINER_HEADING)

    # assert
    assert real in quoted, f"the page quotes {quoted!r}, the loader says {real!r}"


def test_the_page_quotes_every_catalogue_task_that_says_it_runs_in_a_container():
    """Derived, not listed: the set comes from the catalogue's own wording. A third containerised task
    would have to be quoted here too, and a task that stops running in one would have to leave."""
    # arrange
    helps = _catalogue_helps()
    containerised = {c: h for c, h in helps.items() if "in Docker" in h}

    # act
    quoted = _quotes(CONTAINER_HEADING)

    # assert: it is still exactly the two documentation renders, spelled from the catalogue
    assert set(containerised) == {"docs:render", "docs:site"}

    # assert: and each one's own sentence is on the page, unedited
    for coordinate, help_text in containerised.items():
        assert help_text in quoted, f"{coordinate} is not quoted as the catalogue words it"


def test_the_page_quotes_the_task_that_deliberately_stays_out_of_a_container():
    """The counter-example is the half that keeps the section from reading as dogma, so it is derived
    from the catalogue rather than remembered - and it is the ONLY task worded that way."""
    # arrange
    helps = _catalogue_helps()
    outside = {c: h for c, h in helps.items() if "no Docker" in h}

    # act
    quoted = _quotes(CONTAINER_HEADING)

    # assert
    assert set(outside) == {"test:typecheck-python"}
    assert outside["test:typecheck-python"] in quoted


def test_which_tasks_die_on_a_missing_docker_and_which_only_hint():
    """The section makes two claims about the missing/failed split, and the first round of si#29 got the
    second one wrong by omission: it introduced `docs:site` and `docs:render` as a pair, quoted both, and
    then stated the hint verdict without saying that `docs:render` does not share it.

    EVERY module that could carry the gate is ruled on here rather than only the two the prose is about,
    because the defect was a task left OUT of the sentence, not a task described wrongly in it. Parsed
    rather than grepped: all three modules DISCUSS `ensure_docker` in their docstrings, and a substring
    search would answer yes for every one of them.
    """
    # arrange
    dies = ("simplon.tasks.image", "simplon.tasks.docs")
    hints = ("simplon.tasks.site",)

    # act
    gates = {module: _calls_ensure_docker(module) for module in sorted(dies + hints)}

    # assert: the verdicts are what the page says they are
    for module in dies:
        assert gates[module], f"{module} no longer dies on a missing docker - the page says it does"
    for module in hints:
        assert not gates[module], f"{module} now dies on a missing docker - the page says it hints"
    assert len(gates) == 3

    # assert: and the page still makes both claims - otherwise this would be a test of the kernel that
    # outlived the paragraphs it exists to hold honest
    section = "\n".join(_section(CONTAINER_HEADING))
    assert {"build:image", "release:image"} <= set(_COORD.findall(section))
    costs = section[section.index("### What it costs"):]
    assert "`docs:render`" in costs, ("the cost list states the hint verdict without saying that "
                                      "docs:render does not share it - the omission review found")
    assert "`docs:site`" in costs


def test_the_two_known_costs_are_linked_rather_than_left_out():
    """The ticket's own words: link them instead of keeping quiet about them. A cost list that lost its
    open tickets would read as a page that had never used the thing it recommends."""
    # act
    section = "\n".join(_section(CONTAINER_HEADING))

    # assert
    for issue in COST_ISSUES:
        assert issue in section, f"the cost list no longer names {issue}"

    # assert: and they are in the cost list, not merely somewhere on the page
    costs = section[section.index("### What it costs"):]
    assert all(issue in costs for issue in COST_ISSUES)
