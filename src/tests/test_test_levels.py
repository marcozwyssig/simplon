"""The normed test levels (si#283): the set, the suffix rule, and the page that teaches them.

WHY THIS FILE EXISTS. `with-what/test-levels.md` defined a level precisely and then taught it with three
example names. The kernel checked a gate's name against the product's own manifest and nothing else, so
two products could spell one level differently and a third could put a way of REACHING the product where
a level goes - which the page itself did, teaching `ui` as a level for months because there was no list
to check it against.

WHAT IS ASSERTED, and the split matters. The SET is asserted against the code, not against a memory of
it. The WARNING is asserted by generating it and looking for it on the page, which is si#136's rule - the
half si#196 had to repair by hand on this very page - so a reworded message cannot leave a stale quote
behind.

WHAT IS NOT ASSERTED: that a product's suites live where the taxonomy says they do. That is measured and
reported on si#283 rather than checked, because this kernel's own `unit` gate runs pytest under `tests/`
and a rule the kernel breaks is the one CLAUDE.md says may not be written unexamined.

AAA throughout.
"""
import pytest

import sitepages
from simplon.tasks import testrun

PAGE = sitepages.chapter("test-levels.md")


def _text() -> str:
    return PAGE.read_text(encoding="utf-8")


# --- the set --------------------------------------------------------------------------------------------


def test_there_are_four_levels_and_the_page_names_the_same_four():
    """The page states the taxonomy; the kernel enforces it. Two sources for one truth is exactly what
    this repository refuses, so the page is read back against the constant rather than proofread."""
    text = _text()

    for level in testrun.LEVELS:
        assert f"| `{level}` |" in text, (
            f"`{level}` is in testrun.LEVELS and the page's taxonomy table does not carry it")
    assert len(testrun.LEVELS) == 4


@pytest.mark.parametrize("name, level", [
    ("unit", "unit"),
    ("integration", "integration"),
    ("system", "system"),
    ("acceptance", "acceptance"),
    ("acceptance-ui", "acceptance"),
    ("acceptance-dataplane", "acceptance"),
    ("acceptance-ui-firefox", "acceptance"),
    ("unit-java", "unit"),
])
def test_a_suite_of_a_level_is_that_level(name, level):
    """THE RULE WITHOUT WHICH THE NORM BREAKS EVERY REAL CONSUMER. netctl runs two acceptance suites and
    two unit runners; a set without the suffix rule would warn on all four."""
    assert testrun.level_of(name) == level


@pytest.mark.parametrize("name", ["ui", "delivery", "artefact", "acceptanceui", "", "unitary"])
def test_a_name_that_is_not_a_level_claims_none(name):
    """`acceptanceui` is the one worth reading: the separator is the rule, so a level's name glued to a
    suite's is not that level. `unitary` is the other - a prefix is not a level either."""
    assert testrun.level_of(name) == ""


# --- the warning ----------------------------------------------------------------------------------------


def test_a_gate_off_the_norm_is_warned_about_and_not_refused(capsys):
    """A NORM THAT BREAKS AN EXISTING MANIFEST ON UPGRADE IS NOT SHIPPABLE, and two manifests this family
    can reach declare a gate this set does not carry. So the product is told and the run goes on - the
    gate parses, and what comes back is a Gate."""
    gate = testrun._gate({"name": "delivery", "suite": "deploy/tests", "junit": "delivery.xml"},
                         "suites.gates[1]")

    assert gate.name == "delivery"
    assert "not one of the test levels" in capsys.readouterr().out


def test_the_warning_names_the_set_and_does_not_guess_at_what_was_meant():
    """A "did you mean" over four words is a spelling correction pretending to be a taxonomy. The two
    real cases are not misspellings of anything: `artefact` tests a built OVA, `delivery` tests a
    pipeline, and only those products can say which level that is."""
    said = testrun.warn_off_the_norm("artefact", "suites.gates[2]")

    for level in testrun.LEVELS:
        assert level in said
    assert "did you mean" not in said.lower()
    assert "artefact" in said


def test_a_normed_gate_is_not_warned_about(capsys):
    gate = testrun._gate({"name": "acceptance-ui", "suite": "test/acceptance", "junit": "ui.xml"},
                         "suites.gates[0]")

    assert gate.name == "acceptance-ui"
    assert "not one of the test levels" not in capsys.readouterr().out


def test_the_page_quotes_the_warning_the_kernel_actually_raises():
    """si#136's rule, and the half si#196 had to repair by hand ON THIS PAGE. The quote is generated and
    then looked for, so rewording the message turns this red instead of leaving a stale block quote that
    reads exactly like a real one."""
    said = testrun.warn_off_the_norm("delivery", "suites.gates[1]")
    quoted = said.split(": ", 1)[1]

    # The page carries it as a block quote, so the `>` markers come off before the comparison - they are
    # Markdown's, not the message's.
    page = " ".join(line.lstrip("> ") for line in _text().splitlines())
    page = " ".join(page.split())

    assert " ".join(quoted.split()) in page, (
        f"the page must quote the warning as the kernel raises it; it now says:\n{quoted}")


# --- si#290: what a gate assures, read back against the code ------------------------------------------


def test_the_page_names_every_verdict_a_gate_can_carry():
    """THE ANSWER si#290 ASKED FOR, held against the enum rather than against a memory of it.

    Four of eight products in this family declare no `suites: gates:`, and the one that was asked said
    nobody had ever named the benefit - *"Arbeit ohne erkennbaren Gewinn"*. The benefit is that a gate has
    five verdicts where an aggregate step has two, and the three extra ones are exactly the "nothing to
    do" cases this project separates from "failed".

    A number or a list typed into that page would be wrong on the first day nobody checks it, which is
    this repository's oldest lesson about documents. So the page is read back against `Verdict`."""
    from simplon.verdict import Verdict

    text = _text()

    for member in Verdict:
        assert member.name in text, (
            f"`{member.name}` is a verdict a gate can carry and the page does not name it - a product "
            f"reading it to decide whether gates are worth declaring would be told less than the truth")

    # AND EACH OF THE THREE EXTRA ONES IS EXPLAINED, not merely listed. The first draft of this test
    # asserted presence alone and stayed green when `KILLED` was struck from the table, because the name
    # still stood in the code block above it. A page that lists a verdict and does not say what it means
    # answers none of the question this chapter exists for.
    for name in ("SETUP_FAILED", "NOT_RUN", "KILLED"):
        assert f"| `{name}` |" in text, (
            f"`{name}` is listed but has no row saying what it means - listing it is not naming the "
            f"benefit, which is what si#290 asked for")


def test_the_page_says_an_aggregate_carries_only_two_of_them():
    """The comparison is the point, not the list. Without it the five verdicts read as trivia rather than
    as the reason to declare a section."""
    text = _text()

    assert "aggregate" in text
    assert "PASSED   FAILED" in text or "PASSED` or `FAILED" in text
