"""The two pages that show what `simplon init` writes, held against what it actually writes (si#130).

WHY THIS IS A GUARD AND NOT A PROOFREAD. si#130's finding was not that the documentation was wrong; it
was that it "leads with a shape nobody runs, so a reader learns the layout twice: once as shown, once as
corrected". Both pages print a file tree and then, four lines below it, the flag that every real product
passes to change that tree. The default has moved to what those products pass, and the tree on the page
is the one thing that cannot be derived by a reader - so it is derived here instead, from
`bootstrap.render`, which IS the scaffold.

WHY IT IS ITS OWN MODULE. `test_site_counts.py` is where the site's counted claims live, and it would be
the obvious home. It is also the file the publishing lane rewrites when a catalogue coordinate lands, and
a test added to a file another branch is rewriting buys a conflict for nothing.

THE SWEEP IS THE HALF WITH TEETH. Asserting that the new path appears would pass on a page that shows
both - which is exactly what a half-finished edit produces. So the pages are also swept for the two
spellings that MEAN "the block", and every occurrence has to hang off the default's parent.

AND THE SWEEP RULES ON A WIDER POPULATION THAN THE POSITIVE CHECKS (si#186). Splitting
`getting-started.md` moved the orchestrator-block prose onto a second page, and a negative claim that
only looks at two files stops being a claim about the site the moment a third one can carry the string.
`SWEPT` is that population; `PAGES` stays the two pages that really do show and count the tree.
"""
import re

from conftest import ROOT

import sitepages
from simplon import bootstrap

PRODUCT = "myctl"

#: The two pages that describe what a scaffold produces. Not a sweep of the site: every other page
#: legitimately shows a grown product's own layout, and `case-java.md` describing javademo's tree is not
#: a claim about the default.
#:
#: These two are the pages that show the TREE and count it, which is why si#186 did not simply add the
#: page it split out of `getting-started.md` here: `what-init-wrote.md` shows neither, and the three
#: positive assertions below would then demand of it what it never claimed.
PAGES = [sitepages.chapter("getting-started.md"), ROOT / "README.md"]

#: The pages the NEGATIVE sweep rules on, which is a wider population than the three positive checks and
#: has to be (si#186). "No page still shows the block at the target root" is a property of every page
#: that names the block at all, and si#186 moved half of what `getting-started.md` said about the
#: scaffold onto a second page - so a stale `orchestrator/requirements.txt` could now land somewhere the
#: sweep was not looking, which is exactly the silence the sweep exists to end. The positive checks stay
#: on `PAGES`; only the thing that must never be true anywhere widens.
SWEPT = [*PAGES, sitepages.chapter("what-init-wrote.md")]

#: The two spellings that mean "the orchestrator block", the same pair `test_own_orch_block.py` sweeps
#: this repository's own configuration for. Each has to be prefixed by everything the default puts in
#: front of it.
TAILS = ("orchestrator/src/python", "orchestrator/requirements.txt")

#: What the default puts in front of them: `deploy/provision/` for `deploy/provision/orchestrator`.
PREFIX = bootstrap.DEFAULT_ORCH_DIR[:-len("orchestrator")]


def _text(page):
    body = page.read_text(encoding="utf-8")
    assert body.strip(), f"{page} is empty, so every `in` below would rule on nothing"
    return body


def _scaffold() -> dict[str, str]:
    return bootstrap.render(PRODUCT)


def test_the_pages_list_exactly_the_files_a_scaffold_writes():
    """Every rendered path is on both pages, in the form the page shows it.

    The tree collapses the package into a directory line plus bare filenames, which is how a reader
    wants to see it, so the check follows that shape rather than demanding nine absolute paths.
    """
    # arrange
    rendered = _scaffold()
    package = f"{bootstrap.pkg_dir_for(bootstrap.DEFAULT_ORCH_DIR)}/"
    flat = sorted(rel for rel in rendered if not rel.startswith(package))
    inside = sorted(rel[len(package):] for rel in rendered if rel.startswith(package))

    # act / assert
    assert flat and inside, "the scaffold has no package, so this test rules on nothing"
    for page in PAGES:
        body = _text(page)
        assert package in body, f"{page.name} does not show the package directory {package}"
        for rel in flat:
            assert rel in body, f"{page.name} does not list {rel}"
        for name in inside:
            assert name in body, f"{page.name} does not list {name} under {package}"


def test_the_page_counts_the_files_the_scaffold_actually_writes():
    # arrange: the sentence under the tree spells the number out
    rendered = _scaffold()
    word = sitepages.number_word(len(rendered))

    # act / assert
    assert f"{word.capitalize()} files" in _text(PAGES[0]), (
        f"getting-started.md must say '{word.capitalize()} files'; the scaffold writes {len(rendered)}")


def test_no_page_still_shows_the_block_at_the_target_root():
    """The half a "does the new path appear" check cannot do: a page can show the new tree and keep the
    old one three paragraphs below, and every positive assertion above would still hold."""
    # arrange / act
    stray = []
    for page in SWEPT:
        body = _text(page)
        for tail in TAILS:
            for match in re.finditer(re.escape(tail), body):
                start = match.start()
                if not body[:start].endswith(PREFIX):
                    stray.append(f"{page.name}: ...{body[max(0, start - 40):match.end()]}")

    # assert
    assert stray == [], f"these still show the block at the target root: {stray}"


def test_both_pages_offer_the_short_form_as_the_alternative_rather_than_the_default():
    """si#130's open question, answered: the flag's documentation now shows the SHORT form as the
    exception, which is the mirror image of what both pages said before. A page that still presented
    `deploy/provision/orchestrator` as the thing to pass would be telling a reader to type the default."""
    # arrange / act / assert
    for page in PAGES:
        body = _text(page)
        assert "--orch-dir orchestrator" in body, (
            f"{page.name} does not show the short form as the alternative")
        assert f"--orch-dir {bootstrap.DEFAULT_ORCH_DIR}" not in body, (
            f"{page.name} still tells the reader to pass the default")


def test_both_pages_say_the_product_name_is_optional_and_where_it_comes_from():
    # arrange / act / assert: si#129 changed the first command a new user types, and a page that still
    # presents the argument as required is describing the previous release. The SOURCE has to be there
    # too: "optional" alone leaves a reader guessing which of the two names a clone would be given
    for page in PAGES:
        body = _text(page)
        assert "optional" in body.lower(), f"{page.name} does not say the product name is optional"
        assert "`origin` remote" in body, f"{page.name} does not say which name is read"
