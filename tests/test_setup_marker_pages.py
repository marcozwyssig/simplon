"""What the website says about the setup marker, held against the kernel that offers it (si#80).

WHAT si#80 REPORTED, AND WHAT WAS ACTUALLY THERE. The ticket says the marker is unadvertised - "no page
names it, no chapter shows it, no example uses it" - and that a Java product therefore never reaches the
honest verdict. Measured against the tree: `building/test-levels.md` has named `SIMPLON_SETUP_FAILED`,
shown the import and used it in a worked example since 2026-09-07, which is in the released v0.6.0 and a
full day before the ticket was written; `using/case-java.md` has carried the same example since eleven
minutes before it. The premise was already false when it was filed.

SO WHAT WAS MISSING WAS NOT THE ADVERTISEMENT - IT WAS THIS FILE. Both pages spell a constant name, an
environment-variable name and a verdict word, and nothing anywhere compared any of them with the kernel.
Rename `SETUP_MARKER_ENV`, or change what it holds, and two pages go on teaching the old spelling in
green. That is the second-source drift this repository pins everywhere else and had not pinned here, and
it is worse than a missing page: a page that is absent is discovered by the first person who looks, and a
page that is confidently wrong is not.

THE TWO PAGES ARE NAMED RATHER THAN DERIVED, and that is the point of naming them. Deriving "the pages
that mention the marker" from the pages themselves would keep this suite green on the day both of them
stop mentioning it - the exact state si#80 believed it was reporting. These two are where a product
author looks: the chapter about test levels, and the case study for the language whose runner the kernel
cannot see into.

AAA throughout.
"""
import os
import re

import pytest

from simplon.tasks import testrun
from simplon.verdict import Verdict

from conftest import ROOT

CONTENT = ROOT / "site" / "content"

#: The pages that have to carry the seam, and why each one. A page that stops carrying it goes red here
#: rather than quietly becoming a page that used to explain something.
ADVERTISING = {
    "building/test-levels.md": "the chapter that explains what a gate may claim - where a product author "
                               "reading about `impl:` gates arrives",
    "using/case-java.md": "the case study for the language whose runner the kernel cannot see into, which "
                          "is the product that needs the seam most",
}


def _page(relative: str) -> str:
    path = CONTENT / relative
    body = path.read_text(encoding="utf-8")
    if not body.strip():
        raise ValueError(f"{path} is empty, so nothing below could be read off it")
    return body


@pytest.mark.parametrize("relative", sorted(ADVERTISING))
def test_the_page_names_the_marker_the_kernel_actually_offers(relative):
    """The spelling, pinned in both directions: the Python constant a page tells the reader to import, and
    the environment variable the kernel puts the path in."""
    # arrange
    body = _page(relative)

    # act / assert: the constant, and it is really importable under that name
    assert "SETUP_MARKER_ENV" in body, (
        f"{relative} no longer names the setup marker at all. It is one of the two places a product "
        f"author looks for it - {ADVERTISING[relative]}")
    assert hasattr(testrun, "SETUP_MARKER_ENV"), "the kernel no longer offers SETUP_MARKER_ENV"

    # assert: and the variable's own name, taken from the kernel rather than typed here
    assert testrun.SETUP_MARKER_ENV in body, (
        f"{relative} does not name '{testrun.SETUP_MARKER_ENV}' - the page and the kernel disagree about "
        f"what the variable is called, and only the page is wrong")


@pytest.mark.parametrize("relative", sorted(ADVERTISING))
def test_the_import_line_the_page_shows_is_one_that_works(relative):
    """A quoted import is a second source for a module path. This one is executed rather than read."""
    # arrange
    body = _page(relative)

    # act
    shown = re.findall(r"^from ([\w.]+) import SETUP_MARKER_ENV$", body, re.M)

    # assert
    assert shown, f"{relative} shows no import for the marker, so a reader has to guess where it lives"
    for module in set(shown):
        imported = __import__(module, fromlist=["SETUP_MARKER_ENV"])
        assert imported.SETUP_MARKER_ENV == testrun.SETUP_MARKER_ENV, (
            f"{relative} tells the reader to import SETUP_MARKER_ENV from '{module}', which resolves to "
            f"something else")


@pytest.mark.parametrize("relative", sorted(ADVERTISING))
def test_the_verdict_word_the_page_promises_is_the_kernels_own(relative):
    """The marker's whole payoff is the word the run then reports. A page promising an outcome the kernel
    does not have would be advertising a capability that is not there - the mirror image of si#80."""
    # arrange
    body = _page(relative)

    # act / assert
    assert Verdict.SETUP_FAILED.value in body, (
        f"{relative} shows the marker without the outcome it buys ('{Verdict.SETUP_FAILED.value}')")

    # assert: and that outcome really is the one that says no suite ran, which is what makes it worth
    # advertising at all
    assert not Verdict.SETUP_FAILED.ran


def test_the_page_that_explains_the_seam_says_the_variable_is_always_set():
    """si#80's first decision, and the measurement behind it.

    `SIMPLON_SETUP_FAILED` is exported before every gate and holds a PATH, so its presence carries no
    information: a runner testing `[ -n "$SIMPLON_SETUP_FAILED" ]` gets true on every run of every gate.
    That is this repository's own recurring defect wearing a variable name - a value that cannot tell
    "nothing to report" from "it happened" - and the decision was to state it rather than rename a seam
    already shipped in v0.6.0. So the chapter has to keep stating it.
    """
    # arrange
    body = _page("building/test-levels.md")

    # act / assert
    assert "always set" in body, (
        "the chapter no longer says the variable is always set, so a runner reading it as a flag has "
        "nothing warning it off")
    assert "Write the file; do not test the variable." in body


def test_the_variable_really_is_always_set_and_really_holds_a_path(tmp_path):
    """The other half: the sentence above is a claim about the kernel, so it is measured against it.

    Without this the chapter would be prose about behaviour, which is the one thing this repository does
    not accept - and if the marker ever became conditional, the page would be the last place to find out.
    """
    # arrange
    reports = str(tmp_path / "reports")
    before = os.environ.get(testrun.SETUP_MARKER_ENV)

    # act
    with testrun._setup_marker(reports) as marker:
        during = os.environ.get(testrun.SETUP_MARKER_ENV)
        exists_while_open = os.path.exists(marker)

    # assert: set for the whole of the gate, whatever the gate goes on to do
    assert during == marker, "the variable is not the path the marker was opened at"
    assert os.path.dirname(marker) == reports, "the marker does not sit in the run's own reports dir"

    # assert: and it is a slot, not a claim - nothing is there until a runner writes it
    assert not exists_while_open, (
        "the marker file exists before the runner has written anything, so a run could inherit a claim "
        "nobody made")

    # assert: and the environment is left as it was found
    assert os.environ.get(testrun.SETUP_MARKER_ENV) == before
