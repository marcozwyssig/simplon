"""What the documentation site is made of, read off its sources - the one place the site's own shape is
described, shared by every suite that holds a page against something (si#66, si#67).

WHY THIS IS A MODULE AND NOT A COPY IN EACH SUITE. Three suites now read the same pages: the chapter
tests hold one page against the catalogue, the count tests hold three pages against a fourth, and the
link checker walks every page there is. Each of them needs the same four facts - which files are pages,
what URL a page is served at, what a heading's id is, and which targets are GENERATED rather than
written - and each of them would otherwise state those facts again. That is the second source this
repository spends most of its time removing, and a helper duplicated across suites is the worst kind:
it drifts silently, because both copies stay green.

THE URL BASE IS THE PART THAT WAS ALREADY WRONG ONCE (si#67). Hugo serves `using/examples.md` at
`using/examples/`, so a relative link written on that page resolves against `using/examples/` and NOT
against `using/`. The first anchor check written for the Python chapter assumed the second, and with the
wrong base almost every relative link on that page fails to resolve - a checker that checks wrongly,
which is worse than none. `url_dir` is that rule, written once. `_index.md` is the exception and the
reason the rule needs a function at all: a section index IS its directory, so it resolves against
`using/` itself.

(si#67 states that count as "58 of the chapter's 60 links". Measured here rather than carried over: the
chapter carried sixteen markdown links, twelve of them relative, in 27ada9e - the commit that wrote it.
The ticket's scope number is itself a typed number that was never read back, which is the class of
defect si#66 is about, so it is recorded here rather than repeated.)

NOTHING HERE RETURNS AN EMPTY RESULT FOR A MISSING THING. `pages()` raises on an empty content tree and
`headings()` raises on a page that is not there, because a helper that answers "nothing" for "I could
not look" is the defect this repository hunts, one level below the suites that use it.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import NamedTuple

from simplon import catalogue as catalogue_mod
from simplon.orchestrator import manifest as manifest_mod

from conftest import ROOT

#: The Hugo content tree - every page the site renders lives under it.
CONTENT = ROOT / "site" / "content"

#: The product manifest, which is where a GENERATED content page is declared.
MANIFEST = ROOT / "simplon.yaml"

#: The catalogue coordinate whose task writes a Markdown page INTO the content tree. Named rather than
#: matched on an impl string: the coordinate is the kernel's own vocabulary, the impl behind it is an
#: implementation detail that `catalogue.yaml` may change without changing what the task does.
REFERENCE_TASK = "docs:reference"

#: The `with:` key that task takes for the file it writes.
REFERENCE_OUTPUT = "output"


# --- the pages ------------------------------------------------------------------------------------------


def pages() -> list[Path]:
    """Every Markdown page under the content tree, in a stable order.

    Raises on an empty tree rather than returning an empty list: every caller below iterates this, so a
    content directory that moved would turn every suite that uses it green over nothing.
    """
    found = sorted(CONTENT.rglob("*.md"))
    if not found:
        raise ValueError(f"{CONTENT} holds no Markdown page, so nothing could be read")
    return found


def url_dir(page: Path) -> Path:
    """The directory a page's own URL sits in, as a path in the content tree.

    `building/phases.md` is served at `building/phases/`, so `../manifest/` written on it means
    `building/manifest/` and not `manifest/`. A section index is its own directory, so `using/_index.md`
    is served at `using/` and resolves one level higher than its siblings.
    """
    return page.parent if page.name == "_index.md" else page.parent / page.stem


def without_code(text: str) -> str:
    """The page with its fenced blocks removed.

    A transcript holds strings that LOOK like links and coordinates and are neither - Hugo renders none
    of them - so reading them as claims would make a checker rule on the wrong text.
    """
    return re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)


# --- headings and their ids -----------------------------------------------------------------------------


def anchor(heading: str) -> str:
    """The id Hugo's markdown renderer gives a heading: inline code and emphasis dropped, lowercased,
    punctuation removed, spaces hyphenated.

    Derived rather than guessed: it was run over every internal link the site carries and all of them
    resolve, which is what makes it usable as a measure.
    """
    text = re.sub(r"[`*]", "", heading).strip().lower()
    text = re.sub(r"[^a-z0-9 _\-]", "", text)
    return re.sub(r"\s", "-", text)


def headings(page: Path) -> set[str]:
    """The heading ids one page offers, or a raised error if the page is not there."""
    if not page.is_file():
        raise FileNotFoundError(f"{page} is not a page, so its headings could not be read")
    return {anchor(match.group(1))
            for match in re.finditer(r"^#{1,6}\s+(.*?)\s*$", page.read_text(encoding="utf-8"), re.M)}


# --- the links ------------------------------------------------------------------------------------------


class Link(NamedTuple):
    """One internal reference: the page that writes it and the target as written.

    The page is carried with the target because the target alone cannot be resolved - `../examples/`
    means something different on every page that writes it.
    """

    page: Path
    target: str

    def __str__(self) -> str:
        return f"{self.page.relative_to(CONTENT)} -> {self.target}"


#: A markdown inline link's target. Whitespace ends it, which drops an optional title: `](x "y")`.
_MARKDOWN = re.compile(r"\]\(([^)\s]+)[^)]*\)")

#: A Hextra shortcode's target: `{{< card link="phases/" ... >}}`, `{{< hextra/feature-card link=... >}}`.
#: Written as `link="..."` in every shortcode this theme offers that points anywhere.
_SHORTCODE = re.compile(r'\blink="([^"]*)"')

#: What is not this site's to resolve.
_EXTERNAL = ("http://", "https://", "mailto:", "//")


def internal_links(page: Path) -> list[Link]:
    """Every reference on one page that points INTO this site - markdown links and theme shortcodes both.

    The shortcodes are not an afterthought: the two section indexes and the home page carry their whole
    navigation as `card link=` and nothing else, so a checker that read only markdown links would walk
    past a quarter of the site's references and report on a site whose front door it never opened.
    """
    body = without_code(page.read_text(encoding="utf-8"))
    found: list[Link] = []
    for pattern in (_MARKDOWN, _SHORTCODE):
        for match in pattern.finditer(body):
            target = match.group(1).strip()
            if not target or target.startswith(_EXTERNAL):
                continue
            found.append(Link(page=page, target=target))
    return found


def all_internal_links() -> list[Link]:
    """Every internal reference the site carries, in a stable order."""
    return [link for page in pages() for link in internal_links(page)]


def resolve(link: Link) -> Path | None:
    """The content file a link points at, or None when it points at nothing.

    None is the ONE ambiguous answer this module returns, and it is safe here because the caller does
    not have to tell it from "I did not look": every input is a link that was really written on a page
    that was really read, so None means exactly "no page under content/ is served at that URL".
    """
    path, _, _fragment = link.target.partition("#")
    if not path:
        return link.page                       # a bare '#anchor' is a link into the page it is written on
    resolved = (url_dir(link.page) / path).resolve()
    if not resolved.is_relative_to(CONTENT.resolve()):
        return None                            # a '../../..' that climbs out of the site is a dead link
    # A GENERATED page counts as present whether or not it has been built. That is si#67's decision, and
    # without it this function would answer differently depending on whether `docs:reference` had run -
    # the order-dependent verdict the checker exists to avoid. `generated_pages()` is what makes the
    # answer a statement about the SOURCES rather than about the state of the working tree.
    promised = generated_pages()
    for candidate in (resolved.with_suffix(".md"), resolved / "_index.md"):
        if candidate.is_file() or candidate in promised:
            return candidate
    return None


def fragment_of(link: Link) -> str:
    """The `#anchor` part of a link, or an empty string."""
    return link.target.partition("#")[2]


# --- the pages that are generated rather than written ----------------------------------------------------


@functools.lru_cache(maxsize=1)
def generated_pages() -> frozenset[Path]:
    """The content pages this product's manifest GENERATES, as paths in the content tree.

    THIS IS si#67'S DECISION, and it is the whole reason the function exists. `site/content/using/
    commands.md` is written by `docs:reference` during the build and is gitignored, so a link checker
    that walked the built tree would be green or red DEPENDING ON WHETHER THE REFERENCE HAD BEEN BUILT -
    an outcome that says nothing, which is the one shape this repository refuses everywhere else. The
    other two ways out are worse: exempting the target by name puts a blind spot in the checker, and
    building the site first makes a unit suite depend on docker.

    So a generated target is checked against its SOURCE instead. The manifest is what promises the page:
    a command that instantiates `docs:reference` and pins `output:` with `with:` is the declaration that
    the file will exist, and it is read here rather than remembered. Delete that command, rename the
    coordinate or move the output, and every link to `../commands/` goes red with the reason - which is
    exactly what a link checker owes its reader, and what "exempt it" would never have said.
    """
    catalogue = catalogue_mod.load()
    if REFERENCE_TASK not in catalogue.tasks:
        raise ValueError(f"the catalogue carries no '{REFERENCE_TASK}', so no generated page could be "
                         f"identified from the manifest")
    impl = catalogue.tasks[REFERENCE_TASK]["impl"]
    parsed = manifest_mod.load(MANIFEST.read_text(encoding="utf-8"), catalogue=catalogue)
    found: set[Path] = set()
    for members in parsed.commands.values():
        for spec in members.values():
            output = spec.with_.get(REFERENCE_OUTPUT) if spec.impl == impl else None
            if isinstance(output, str) and output:
                page = (ROOT / output).resolve()
                if page.is_relative_to(CONTENT.resolve()):
                    found.add(page)
    return frozenset(found)
