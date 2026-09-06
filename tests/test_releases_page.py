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
