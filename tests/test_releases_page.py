"""simplon's OWN house rules about its OWN releases page (si#53, si#82, si#89).

WHAT MOVED, AND WHY THIS FILE DID NOT MOVE WITH IT. The rule this file used to carry - every release has
a section, no section describes a version that does not exist, every merge in a range names a ticket, and
every section from a floor on names each of them - is MECHANISM: it needs no product knowledge at all,
and si#89 is the ticket that says so. It lives in `simplon.tasks.releasenotes` now, reached as the
catalogue coordinate `test:release-notes`, and simplon runs it on itself with
`./simplon.sh test release-notes`, in `ci.yml`, like every other product that declares the section. That
is the whole point: a rule that lives in one product's `tests/` guards one product, and this one was
catching real failures for exactly one repository while every consumer of the same kernel could tag,
publish and never write a word.

WHAT IS LEFT HERE IS WHAT IS SIMPLON'S. Four assertions, and each is a statement about THIS page, THIS
manifest or THIS repository's own number:

  * the page's prose names the same floor `simplon.yaml` declares, and its introduction names the same
    completeness floor. Two sources for one number is the defect this whole suite exists to hunt, and the
    kernel cannot hold them together - it has no idea how a given product phrases its own prose;
  * exactly ONE section is excused from completeness, and it is the page's own floor. The kernel takes no
    view on how many a product excuses; simplon's answer is one, and an exemption's real cost is not the
    case it was written for but the second case somebody adds to it quietly;
  * that excused section is genuinely incomplete. An exemption is worth nothing if the thing it excuses
    would have passed anyway - it then guards nothing and merely stands there looking justified.

WHY THE FLOOR EXISTS AT ALL, kept here because it is the reason for simplon's own two numbers. Notes
start at 0.4.0, declared on the page itself. Demanding a section for all fourteen earlier tags would mean
writing them from memory now, and a reconstructed record is indistinguishable from a real one. 0.4.0's
own notes then predate the completeness rule and name no ticket anywhere: sixteen tickets arrived in its
thirteen merges and the section carries none, and two of them have no paragraph at all, so retro-fitting
would mean writing new prose about a released version from the outside. (That count said FIFTEEN until
si#89 measured it. si#103's rule reads a web merge one level down and found one more, and the typed
number beside it had simply never been re-run - which is the defect this suite exists for, in the
docstring of the exemption it excuses. The assertion below is what holds it; this sentence is not.)

THE FLOORS ARE READ THROUGH THE KERNEL'S OWN READER rather than retyped as constants here. That is not
tidiness: `FLOOR` and `COMPLETE_FROM` used to be module constants, and a constant beside a manifest is
exactly the second source these tests are about.

AAA throughout.
"""
from __future__ import annotations

from simplon import context
from simplon.tasks import releasenotes

from conftest import ROOT

PAGE = ROOT / "site" / "content" / "using" / "releases.md"


def _declared(monkeypatch) -> releasenotes.Declared:
    """simplon's own `releases:` section, read the way the gate reads it.

    Through `monkeypatch` rather than `set_current`, which is a module global: registering simplon as the
    process' product for the rest of the session would decide it for every other test module that shares
    it. pytest reverts the attribute at the end of the test that set it.
    """
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("simplon", ROOT, ROOT / "simplon.yaml"))
    spec = releasenotes.declared()
    assert spec is not None, "simplon.yaml's own `releases:` section must load - the gate reads it too"
    return spec


def test_the_page_states_the_floor_the_manifest_holds_it_to(monkeypatch):
    """The floor lives in two places - `simplon.yaml` and the page's own prose - so it is pinned here.

    Without this, moving the floor in the manifest alone would quietly excuse a missing section while the
    page still promised to cover it. The kernel cannot hold these two together: it reads the manifest and
    the headings, and how a product phrases a sentence about its own notes is not something a rule can
    know. That is exactly the kind of assertion that stays with the product.

    READ OUT OF THE INTRODUCTION, and si#89 is where that was found rather than reasoned. This assertion
    used to search the WHOLE page, which cannot fail while the floor has a section: `## 0.4.0` is itself
    the string `0.4.0`, so the page satisfied the rule by having the very section the rule exists to
    excuse. A check that cannot fail is this repository's most-hunted defect, and it was sitting inside
    the suite that hunts it. The introduction is the text before the first section, so a number there is
    one somebody wrote ABOUT the rule - the same reading its neighbour below already used.
    """
    # arrange
    floor = releasenotes.spell(_declared(monkeypatch).first)

    # act
    intro = PAGE.read_text(encoding="utf-8").split("\n## ", 1)[0]

    # assert
    assert floor in intro, (
        f"the page's introduction must name {floor} as the first release with notes, because that is "
        f"the floor simplon.yaml holds it to")


def test_the_page_says_from_which_release_every_ticket_is_named(monkeypatch):
    """The completeness boundary lives in two places too, and the same argument pins it.

    Read out of the INTRODUCTION rather than the whole page, and that is what makes it an assertion:
    every version has a `## X.Y.Z` heading, so a search over the whole file would find `0.5.0` whatever
    the page said about it. The introduction is the text before the first section, and a number there is
    one somebody wrote about the rule.
    """
    # arrange
    boundary = releasenotes.spell(_declared(monkeypatch).complete_from)

    # act
    intro = PAGE.read_text(encoding="utf-8").split("\n## ", 1)[0]

    # assert
    assert boundary in intro, (
        f"the page's introduction must name {boundary} as the release from which every merged ticket is "
        f"listed, because that is the boundary simplon.yaml holds it to")


def test_exactly_one_section_is_excused_from_completeness(monkeypatch):
    """Half of what pays for the gap between the two floors: the exemption may not grow.

    An exemption's real cost is not the case it was written for, it is the second case somebody adds to
    it quietly. So the excused population is pinned rather than described: exactly one documented version
    sits below the completeness floor, and it is the floor of the page itself. Raising `complete_from:`
    in the manifest to excuse a release somebody did not feel like writing up fails here, naming it.

    THIS NUMBER IS SIMPLON'S, which is why it stayed behind when the mechanism left. Another product
    adopting the gate may legitimately have three pre-rule releases, or none; the kernel takes no view,
    and a kernel rule pinning one would be simplon's history imposed on everybody.
    """
    # arrange
    spec = _declared(monkeypatch)
    documented = releasenotes.documented_versions(PAGE.read_text(encoding="utf-8"))

    # act
    excused = [version for version in documented if spec.first <= version < spec.complete_from]

    # assert
    assert excused == [spec.first], (
        f"exactly one section is excused from naming its tickets - "
        f"{releasenotes.tag_of(spec.first)}, whose notes predate the rule - and the excused set is now "
        f"{[releasenotes.tag_of(version) for version in excused]}; a release below "
        f"{releasenotes.tag_of(spec.complete_from)} that is not the page's own floor is a release nobody "
        f"wrote up")


def test_the_excused_section_really_is_the_one_that_could_not_pass(monkeypatch):
    """The other half, and the reason the exemption is not simply a hole.

    An exemption is worth nothing if the thing it excuses would have passed anyway - it then guards
    nothing and merely stands there looking justified. So the excused section is required to be genuinely
    incomplete. The day somebody writes those numbers into it, this goes red and says the useful thing:
    the exemption has outlived its reason, so move `complete_from:` down in `simplon.yaml` and delete it.

    Same shape as `REFUSED_VERSION` in `test_case_python_chapter.py`, where a version exempted from "must
    be a tag" is required, in its own assertion, to really never have been cut.
    """
    # arrange
    spec = _declared(monkeypatch)
    body = PAGE.read_text(encoding="utf-8")
    start, end = releasenotes.ranges_under_test(ROOT, body, spec.first)[spec.first]

    # act
    merged = {number for sha, subject in releasenotes.merges_in(ROOT, start, end)
              for number in releasenotes.tickets_of(ROOT, sha, subject)}
    named = releasenotes.tickets_in(releasenotes.sections(body)[spec.first])

    # assert
    assert merged, f"no ticket was merged into {start}..{end}, so the exemption rules on nothing"
    assert merged - named, (
        f"the {releasenotes.tag_of(spec.first)} section now names every one of the {len(merged)} tickets "
        f"merged into {start}..{end}, so its exemption guards nothing: set `complete_from:` to "
        f"{releasenotes.spell(spec.first)} in simplon.yaml and delete it")
