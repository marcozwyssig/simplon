"""Every internal reference the documentation site carries, resolved against the sources (si#67).

WHY A TEST AND NOT HUGO. Hugo renders a dead relative link without a word: the anchor comes out with the
href it was given, the build exits 0, the page count is right, and the reader is the one who finds out.
That is the shape this repository refuses everywhere else - an outcome that cannot tell "nothing wrong"
from "nobody looked" - and it had been sitting on the site the whole time, unwatched, while nine other
suites read the pages for everything except whether their links go anywhere.

WHAT WAS MEASURED BEFORE ANYTHING WAS BUILT, because si#67 asks for the size first. On 8862ce2, the
commit this suite was written against: seventeen pages, eighty-four internal references, and NONE of
them dead. That is the answer the ticket wanted - "a dead link that has stood for months is the proof
the checker is missing" - and it came out the other way, so the check is being added while it is still
cheap rather than to clear a backlog. Those numbers are a dated measurement and nothing below asserts
them: `test_the_site_really_carries_links` holds a FLOOR instead, because the count moves every time
somebody writes a paragraph, and a suite that had to be edited for that would teach people to edit it
without reading it.

THE DECISION si#67 SAYS HAS TO BE MADE FIRST, and the reason it is not a detail. `with-what/commands.md` is
GENERATED into the content tree by `docs:reference` and is gitignored. Five links point at it. A checker
that walked the tree on disk would therefore be green after `build docs` and red before it - a verdict
that reports the order the commands ran in and calls it a statement about the site. The three ways out
si#67 lists are not equal:

  * check against the BUILT tree - then the checker needs docker and a Hugo run to say anything, and on
    a machine without them it is skipped, which is the same nothing in a different costume;
  * EXEMPT the target - a blind spot, and one that grows: the day a second page is generated, nobody
    remembers to add it, and its links stop being checked without a word;
  * check a generated target against ITS SOURCE - which is what `sitepages.generated_pages()` does.

The third is taken. The manifest declares the page: a command instantiating `docs:reference` with
`output:` pinned by `with:` is the promise that the file will exist, and it is READ rather than listed
here. So `../commands/` resolves whether or not the reference has been built, the answer does not depend
on what ran before, and deleting or moving that command turns every link to it red with the cause. The
exemption is therefore not an exemption at all, and `test_the_generated_targets_are_the_ones_the_
manifest_promises` is what keeps it from quietly becoming one.

WHAT IS NOT CHECKED, said rather than left as a gap:

  * a link into a GENERATED page's ANCHOR. The heading ids of a page that does not exist yet cannot be
    derived from the manifest, only from a build. There is no such link today and
    `test_no_link_reaches_into_a_generated_page_by_anchor` is what makes that visible instead of
    accidental - it names the one thing a future author would have to build the site to check;
  * EXTERNAL links. Whether github.com answers is not a fact about this repository, and a suite that
    went red on somebody else's outage would be turned off within a week.
  * EXTERNAL links, still. Whether github.com answers is not a fact about this repository.

WHAT THE GAP NOTE USED TO SAY, and why it is closed. `hugo.yaml`'s `menu.pageRef` entries were the one
known hole: the site's own `pageRef: "/using"` was pointed at a section that does not exist and hugo
built it with rc 0 and not one warning - the same silence, in a different file with a different parser.
si#170 rewrote that menu from two entries to five, which is exactly the edit the hole was waiting for,
so it is checked here now, together with the shape it navigates.

AAA throughout.
"""
from __future__ import annotations

import re
import subprocess

import pytest
import yaml

import sitepages
from sitepages import CONTENT

#: Every reference on the site, computed once. Module level because it parametrises the check below, and
#: pytest collects parameters before any fixture runs.
LINKS = sitepages.all_internal_links()

#: The pages the manifest promises rather than the repository carrying them.
GENERATED = sitepages.generated_pages()

#: The smallest number of internal references a site with this many chapters can plausibly carry. A
#: FLOOR, not the count: the count moves whenever anybody writes a paragraph, and a suite that had to be
#: edited for that would teach people to edit it without reading it. What this rules out is the one thing
#: that would make every assertion below vacuous - a regex that stopped matching, or a content tree that
#: moved - and for that a floor is exactly as strong as an equality.
AT_LEAST = 40


def _identify(link: sitepages.Link) -> str:
    """A parametrisation id a failure can be read from without opening the file."""
    return f"{link.page.relative_to(CONTENT)}::{link.target}"


# --- the checker is ruling on something ------------------------------------------------------------------


def test_the_site_really_carries_links():
    """The paired assertion that makes the parametrised one below evidence.

    Every case is computed from the pages, so a content tree that moved - or a regex that quietly stopped
    matching - would collect zero cases and report a green suite over a site nobody looked at. This is
    the assertion that has to fail first when that happens.
    """
    # act
    pages = sitepages.pages()

    # assert
    assert len(LINKS) >= AT_LEAST, f"the site carries {len(LINKS)} internal references, which is too few "\
                                   f"to be the whole site - has the content tree moved?"

    # assert: and they come from across the site rather than from one page that happens to be link-heavy
    assert len({link.page for link in LINKS}) >= len(pages) // 2


def test_both_shapes_of_reference_are_read():
    """Markdown links and theme shortcodes are two spellings of one thing, and a checker that read only
    the first would walk past the whole navigation.

    The home page carries its entire card grid as `link="..."` inside shortcodes and writes not one
    markdown link, so it is the page that PROVES the second pattern is load-bearing: drop it and the
    site's own front door stops being checked, silently, while every other page keeps this suite green.
    """
    # arrange: the home page, and how many ordinary markdown links it writes
    home = CONTENT / "_index.md"
    body = sitepages.without_code(home.read_text(encoding="utf-8"))

    # act
    from_home = [link for link in LINKS if link.page == home]

    # assert: it writes no markdown link at all, so every reference found on it came from a shortcode
    assert not re.search(r"\]\([^)]", body), (
        "the home page now writes markdown links too, so it no longer proves the shortcode pattern "
        "works - point this test at another shortcode-only page")
    assert len(from_home) >= 5, f"the home page contributes {len(from_home)} references, so the "\
                                f"shortcode pattern has stopped matching"

    # assert: and ordinary markdown links are read as well, from the chapters
    assert [link for link in LINKS if link.page.name != "_index.md"]


# --- every reference resolves ----------------------------------------------------------------------------


@pytest.mark.parametrize("link", LINKS, ids=_identify)
def test_every_internal_reference_points_at_a_page_this_site_has(link):
    """si#67's acceptance. A link that goes nowhere is not a typo - on a site whose design is to point at
    the page that owns each detail instead of retelling it, it is the design failing silently.

    A GENERATED target resolves too, and from the manifest rather than from the disk, so this verdict is
    the same before and after `build docs`. That is the whole of si#67's first decision; the module
    docstring says why the other two ways out were refused.
    """
    # act
    target = sitepages.resolve(link)

    # assert
    assert target is not None, (
        f"{link}: no page under site/content/ is served at that URL, and the manifest generates none "
        f"there either (it generates {sorted(str(page.relative_to(CONTENT)) for page in GENERATED)})")


@pytest.mark.parametrize("link", [link for link in LINKS if sitepages.fragment_of(link)], ids=_identify)
def test_every_fragment_names_a_heading_on_the_page_it_points_at(link):
    """The half a page-level check would miss, and the half that rots fastest: a heading is reworded far
    more often than a page is deleted, and `#the-two-empty-ribs` stops resolving the moment somebody
    writes "the two ribs that are empty" instead.

    The id rule is `sitepages.anchor`, which is Hugo's and was derived by running it over every link the
    site already carries. A checker built on a WRONG id rule is what si#67 warns about at length: the
    first one written for the Python chapter had the URL base wrong and would have reported nearly every
    valid link on that page as broken.
    """
    # arrange
    target = sitepages.resolve(link)
    assert target is not None, f"{link}: points at no page, so its fragment cannot be ruled on"

    # act
    available = sitepages.headings(target)

    # assert
    assert sitepages.fragment_of(link) in available, (
        f"{link}: '{target.relative_to(CONTENT)}' has no heading whose id is "
        f"'{sitepages.fragment_of(link)}' (it has {sorted(available)})")


def test_the_fragments_really_ruled_on_something():
    """The paired assertion for the parametrisation above. Deep links are the ones worth checking and the
    ones a page can lose without anybody noticing, so a site that had stopped writing them - or a
    `fragment_of` that stopped finding them - must be a red suite rather than zero silent cases."""
    # act
    deep = [link for link in LINKS if sitepages.fragment_of(link)]

    # assert
    assert len(deep) >= 10, f"the site writes {len(deep)} deep links; the fragment check rules on those"


# --- the generated half, which is the decision -----------------------------------------------------------


def test_the_generated_targets_are_the_ones_the_manifest_promises():
    """What keeps the generated-page rule from decaying into the blind spot si#67 refuses.

    `generated_pages()` is derived from the manifest, and this says the derivation really found the page
    - an empty set would silently turn every link to `../commands/` into a dead one, and a set built from
    a hard-coded name would keep the links green after somebody deleted the command that writes it.
    """
    # arrange
    promised = sorted(page.relative_to(CONTENT) for page in GENERATED)

    # act / assert: the manifest really declares one, and it is inside the content tree
    assert promised, ("the manifest declares no generated content page; the links to the command "
                      "reference then point at nothing, and this suite would say so for the wrong reason")

    # assert: and it is really generated rather than written - a page git tracks needs none of this
    # construction, and if the reference were ever committed the right change would be to delete the
    # construction rather than to keep pretending
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", *(str(page) for page in GENERATED)],
                             cwd=sitepages.ROOT, capture_output=True, text=True)
    assert tracked.returncode != 0, (
        f"git tracks {promised}, so it is a source and not an output; the generated-target rule in "
        f"sitepages.generated_pages() is then solving a problem this site no longer has")


def test_the_generated_page_is_really_linked_to():
    """The construction above is only worth its words if something points at the generated page. If
    nothing did, `generated_pages()` could be empty or wrong and every test here would stay green."""
    # act
    into_generated = [link for link in LINKS if sitepages.resolve(link) in GENERATED]

    # assert
    assert into_generated, ("nothing links at a generated page, so the order-independence this suite is "
                            "built around is not being exercised by anything")


def test_no_link_reaches_into_a_generated_page_by_anchor():
    """The one thing this suite cannot check, made visible instead of left as a hole.

    A generated page's headings come from the app the reference is read off, and deriving them here would
    mean re-implementing `simplon.tasks.cliref` - a second source for the exact thing that module exists
    to be the only source of. So a link into `../commands/#some-command` is refused, and the message says
    what to do about it. That is the "sichtbar, nicht als stiller blinder Fleck" the ticket asks for: the
    gap has a name and a red test behind it rather than being a silence.
    """
    # act
    offenders = [str(link) for link in LINKS
                 if sitepages.fragment_of(link) and sitepages.resolve(link) in GENERATED]

    # assert
    assert offenders == [], (
        "a link points into a GENERATED page by anchor, and this suite cannot check it: the headings of "
        "the command reference exist only after `./simplon.sh build reference` has run, and deriving "
        "them here would duplicate simplon.tasks.cliref. Link to the page and let the reader search, or "
        f"build the check on the built tree and say so: {offenders}")

    # assert: and the rule really has a population to rule on - links into the generated page exist, they
    # simply carry no fragment. Without this the assertion above would hold on a site with no such link
    # at all, which is a different statement.
    assert [link for link in LINKS if sitepages.resolve(link) in GENERATED]


# --- the shape the links are drawn across (si#170) -------------------------------------------------------

#: Hugo's own configuration, which is where the navigation is declared.
HUGO = sitepages.ROOT / "site" / "hugo.yaml"


def _menu() -> list[dict]:
    """The main menu's section entries, in the order hugo will render them.

    Only the entries that name a page: `Search` and `GitHub` are a widget and an outbound link, and a
    menu check that counted them would be counting two different things as one.
    """
    declared = yaml.safe_load(HUGO.read_text(encoding="utf-8"))["menu"]["main"]
    entries = [entry for entry in declared if "pageRef" in entry]
    if not entries:
        raise ValueError(f"{HUGO} declares no menu entry with a pageRef, so the navigation could not be "
                         f"read")
    return sorted(entries, key=lambda entry: entry["weight"])


def test_the_site_is_divided_into_the_sections_it_says_it_is():
    """si#170's acceptance, and the assertion that makes every path in every other suite mean something.

    The division is by QUESTION - why, what, how, with what, when - and a page has to sit in one of the
    five. A sixth directory is not a smaller version of the same site: it is a page nobody decided the
    question for, and it reaches the reader through a navigation that does not offer it.
    """
    # act
    found = {page.parent.name for page in sitepages.pages() if page.parent != CONTENT}

    # assert
    assert found == set(sitepages.SECTIONS), (
        f"the content tree holds {sorted(found)}; the site is divided into {list(sitepages.SECTIONS)}")

    # assert: and it really ruled on a tree with pages in it rather than on two empty sets
    assert len(sitepages.pages()) > len(sitepages.SECTIONS)


def test_every_section_carries_its_own_framing_text():
    """A section index is what a reader lands on from the navigation, so an empty one is a dead end at
    the exact moment the division is supposed to be doing its work."""
    for section in sitepages.SECTIONS:
        # act
        body = sitepages.index(section).read_text(encoding="utf-8")

        # assert: front matter, then something for the reader, then somewhere to go
        assert body.count("---") >= 2, f"{section}/_index.md carries no front matter"
        assert len(sitepages.without_code(body.split("---", 2)[2]).strip()) > 200, (
            f"{section}/_index.md offers cards and no framing text, so the section's own question is "
            f"answered nowhere")
        assert sitepages.internal_links(sitepages.index(section)), (
            f"{section}/_index.md links at no page in its own section")


def test_the_menu_offers_every_section_and_nothing_that_is_not_one():
    """The hole si#67 wrote down and left open, closed by the change that made it matter.

    `pageRef:` is resolved by hugo without a word when it names nothing - measured: rc 0, no warning,
    full page count - so the menu is the one place on this site where a dead reference is completely
    silent. It is read off the same `SECTIONS` the content tree is held to above, so the two cannot
    drift apart in the direction that leaves a section unreachable.
    """
    # act
    entries = _menu()

    # assert: the five sections, in their order, and no entry pointing anywhere else
    assert [entry["pageRef"] for entry in entries] == [f"/{section}" for section in sitepages.SECTIONS]

    # assert: every one of them names a section that really has an index page
    for entry in entries:
        assert sitepages.index(entry["pageRef"].lstrip("/")).is_file()

    # assert: and each carries a label, because an entry hugo would name after its path is not a choice
    assert all(entry.get("name") for entry in entries)


def test_the_sections_are_offered_in_the_order_their_own_front_matter_declares():
    """Two sources say what order the site reads in - the menu's `weight:` and each index's own - and
    only one of them is visible on the page. They have to agree, or the navigation offers one order and
    the section a reader is standing in belongs to another."""
    # arrange
    from_menu = [entry["pageRef"].lstrip("/") for entry in _menu()]

    # act
    weights = {}
    for section in sitepages.SECTIONS:
        match = re.search(r"^weight: (\d+)$", sitepages.index(section).read_text(encoding="utf-8"), re.M)
        assert match, f"{section}/_index.md declares no weight, so its place is left to a tie-break"
        weights[section] = int(match.group(1))

    # assert
    assert sorted(weights, key=weights.get) == from_menu
    assert len(set(weights.values())) == len(weights), f"two sections share a weight: {weights}"


#: A page named in PROSE rather than linked: `` `building/manifest.md` `` in a backtick span. Hugo
#: renders it as text, so `internal_links()` cannot see it and nothing above ever rules on it.
_NAMED_IN_PROSE = re.compile(r"`([A-Za-z0-9._-]+/)*([A-Za-z0-9._-]+\.md)`")


def test_no_page_names_another_page_by_a_section_it_does_not_sit_in():
    """The blind spot si#170 walked into, and the reason it is a test rather than a proofread.

    Two sentences in the release notes named `building/manifest.md` and `building/test-levels.md` after
    both had moved. Neither is a link - they are backtick spans in prose - so the resolution check above
    is structurally incapable of seeing them, and it stayed green over two pointers that went nowhere.
    A path a reader is told to open is a claim about this site whether or not it is clickable.

    Only a path that NAMES a section is ruled on: `manifest.md` on its own says nothing about where the
    page lives, and a sentence is allowed to name a file without placing it.
    """
    # arrange: where each page really is, read off the tree and off the manifest's promise
    section = {page.name: page.parent.name for page in sitepages.pages() if page.name != "_index.md"}
    section.update({page.name: page.parent.name for page in GENERATED})

    # act
    named, offenders = [], []
    for page in sitepages.pages():
        body = sitepages.without_code(page.read_text(encoding="utf-8"))
        for match in _NAMED_IN_PROSE.finditer(body):
            prefix, name = match.group(0)[1:-1].rsplit("/", 1) if "/" in match.group(0) else ("", "")
            if not prefix or name not in section:
                continue
            named.append(f"{page.relative_to(CONTENT)}: {match.group(0)}")
            if prefix.rsplit("/", 1)[-1] != section[name]:
                offenders.append(f"{page.relative_to(CONTENT)}: {match.group(0)} - {name} is served "
                                 f"from {section[name]}/")

    # assert
    assert offenders == [], f"a page names another page by the wrong section: {offenders}"

    # assert: and the sweep really found prose that places a page, rather than ruling on nothing
    assert named, ("no page names another by a path any more, so this check holds vacuously - point it "
                   "at whatever replaced that way of writing, or delete it")
