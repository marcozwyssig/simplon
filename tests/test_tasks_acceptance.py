"""`docs:acceptance` - the reader, the page, and the two properties the page exists for (si#204).

WHAT THIS SUITE HOLDS, in the order it matters.

  1. THE ADDRESS IS THE RUNNER'S. The whole format decision is that a scenario's address on the page is
     the string the run's archive already records, so a human verdict (si#205) and a machine one join on
     one key. That is a claim about ANOTHER TOOL, so it is pinned against a MEASUREMENT and not against
     a reading of the docs: `RUNNER` below is what pytest 9.1.1 / pytest-bdd 8.1.0 / allure-pytest-bdd
     2.16.0 really wrote into `<uuid>-result.json` when driven over this repository's own two feature
     files on 2026-09-12, transcribed from the run. `test_the_address_and_the_walk_are_what_the_runner_
     recorded` asserts the reader reproduces all nine of them byte for byte. Reword a scenario in
     `tests/acceptance/` and this goes red with a diff, which is the point: the literal is a second
     source for another tool's output and this repository pins those rather than trusting them.

  2. THE PAGE GROWS WITHOUT BEING EDITED. si#204 says asserting the generator was called proves nothing,
     so `test_a_new_scenario_reaches_the_page_and_nothing_else_was_touched` renders a real tree, adds a
     scenario to a `.feature` file, renders again, and holds the second page against the first: the new
     scenario is on it, the count in the lead sentence has gone up by exactly one, and no other line of
     the page moved.

  3. EVERY REFUSAL WAS SEEN RED - twenty of them: seventeen constructs of a feature file, a `source:`
     that escapes the product root, and the two ways a `source:` can be nothing. Each is driven with the
     input it refuses, and `test_the_legal_neighbour_of_every_refusal_below_is_accepted` drives the
     nearest legal one, so none of them is passing merely because the reader refuses everything.

     EIGHT OF THEM CAME FROM REVIEW rather than from writing the reader, and each is marked FOUND IN
     REVIEW at its own test. Two are worth naming here because they were silent rather than loud: a
     `source:` of `/etc` or `../..` read feature files from outside the product and baked them into a
     published page with no error at all, and a file ending inside an unterminated docstring payload
     dropped that payload and reported a valid feature.

AAA throughout. `read()` is driven with text rather than with files wherever the file system is not the
subject, because a feature file's TEXT is what the reader is about.
"""
from __future__ import annotations

import re

import pytest

from simplon.tasks import acceptance

from conftest import ROOT

#: This repository's own feature directory, which is also the `source:` its manifest leaves unpinned.
SOURCE = "tests/acceptance"


# --- the measurement the format rests on -----------------------------------------------------------------

#: WHAT THE RUNNER REALLY WROTE, on 2026-09-12, driven over `tests/acceptance/*.feature` with pytest
#: 9.1.1, pytest-bdd 8.1.0 and allure-pytest-bdd 2.16.0 and read back out of the Allure result files:
#: `fullName` on the left, the `steps[].name` list on the right. Transcribed rather than derived - a
#: derivation would be this module describing itself.
#:
#: THREE FACTS ARE VISIBLE IN IT and none of them is guessable, which is why si#204 asked for the
#: measurement before the design:
#:
#:   * the feature file is `acceptance/<name>.feature` and NOT `tests/acceptance/<name>.feature` -
#:     `pytest_bdd.parser.FeatureParser` sets `rel_filename = basename(basedir) + "/" + filename`, so the
#:     runner knows a feature file by the base directory's own NAME and not by a path in the repository;
#:   * a Scenario Outline is one result PER EXAMPLES ROW, with the placeholders substituted in the title;
#:   * the Background steps are prepended to every scenario's own, each keeping the keyword it was
#:     written with, and a step's name is exactly `<Keyword> <text>` with no payload in it.
RUNNER: dict[str, tuple[str, ...]] = {
    "acceptance/generated-documents.feature:The command reference names every command the assembled CLI "
    "offers": (
        "Given a clean checkout of simplon",
        "And docker is available to the caller",
        'When I run "./simplon.sh build reference"',
        'Then "docs/site/content/with-what/commands.md" exists',
        'And every command "./simplon.sh --help" lists has a section on that page',
        "And the page's own lead sentence states the number of commands it documents",
    ),
    "acceptance/generated-documents.feature:The acceptance document names every scenario the feature "
    "files carry": (
        "Given a clean checkout of simplon",
        "And docker is available to the caller",
        'When I run "./simplon.sh build acceptance"',
        'Then "docs/site/content/with-what/acceptance.md" exists',
        'And every scenario title in "tests/acceptance" appears on that page',
        "And each one is addressed by its feature file and its title, separated by a colon",
    ),
    "acceptance/generated-documents.feature:A new scenario reaches the page without anybody editing the "
    "page": (
        "Given a clean checkout of simplon",
        "And docker is available to the caller",
        "Given the acceptance document has been generated once",
        'When I add a scenario to any file under "tests/acceptance"',
        'And I run "./simplon.sh build acceptance" again',
        "Then the page carries the new scenario",
        "And the count in its lead sentence has grown by one",
        'And no file under "docs/site/content" was edited by hand',
    ),
    "acceptance/generated-documents.feature:Both pages reach the published website": (
        "Given a clean checkout of simplon",
        "And docker is available to the caller",
        'When I run "./simplon.sh build docs"',
        'Then "build/website/with-what/commands/index.html" exists',
        'And "build/website/with-what/acceptance/index.html" exists',
    ),
    "acceptance/one-verdict.feature:The local gate runs every test the pipeline runs": (
        "Given a clean checkout of simplon",
        'When I run "./simplon.sh test all"',
        "Then the run reports the pytest suite, the type gate and the release-notes guard",
        'And every leaf named in ".github/workflows/ci.yml" was one of them',
    ),
    "acceptance/one-verdict.feature:A failing suite turns the aggregate red": (
        "Given a clean checkout of simplon",
        "Given the suite step is made to fail",
        'When I run "./simplon.sh test all"',
        "Then the run exits non-zero",
        "And the summary names suite as the step that failed",
        "And the other steps still ran and still printed their own verdict",
    ),
    "acceptance/one-verdict.feature:A failing typecheck-python turns the aggregate red": (
        "Given a clean checkout of simplon",
        "Given the typecheck-python step is made to fail",
        'When I run "./simplon.sh test all"',
        "Then the run exits non-zero",
        "And the summary names typecheck-python as the step that failed",
        "And the other steps still ran and still printed their own verdict",
    ),
    "acceptance/one-verdict.feature:A failing release-notes turns the aggregate red": (
        "Given a clean checkout of simplon",
        "Given the release-notes step is made to fail",
        'When I run "./simplon.sh test all"',
        "Then the run exits non-zero",
        "And the summary names release-notes as the step that failed",
        "And the other steps still ran and still printed their own verdict",
    ),
    "acceptance/one-verdict.feature:A gate that found nothing to run is not green": (
        "Given a clean checkout of simplon",
        "Given a suite directory holding no test at all",
        "When the gate for it runs",
        "Then the run does not report success",
        "And the message says that nothing was collected rather than that nothing failed",
    ),
}


def _walked(features):
    return {scenario.address: tuple(step.announced for step in scenario.steps)
            for feature in features for scenario in feature.scenarios}


def test_the_address_and_the_walk_are_what_the_runner_recorded():
    """The reader against a real run of the same files - the one assertion the format stands on.

    Not a check that the reader is self-consistent: `RUNNER` is another tool's output, transcribed. If
    the two ever part, the page's addresses stop being join keys and si#205's verdicts land on nothing.
    """
    # arrange / act
    found = acceptance.features(ROOT, SOURCE)

    # assert
    walked = _walked(found)
    assert walked == RUNNER
    # and it ruled on something: an empty reader would satisfy an empty expectation
    assert len(walked) == 9


def test_every_scenario_the_repository_carries_has_its_own_address():
    """Nine scenarios, nine addresses. The uniqueness is what makes an address a key at all."""
    # arrange
    found = acceptance.features(ROOT, SOURCE)

    # act
    addresses = [scenario.address for feature in found for scenario in feature.scenarios]

    # assert
    assert len(addresses) == len(set(addresses)) == 9


# --- the reader ------------------------------------------------------------------------------------------

BACKGROUND = """\
@fast
Feature: A feature with a background

  Some prose about the feature.

  Background:
    Given a product
    And a manifest

  @one
  Scenario: A plain scenario
    When it runs
    Then it passes
"""

OUTLINE = """\
Feature: An outline

  Background:
    Given a product

  Scenario Outline: A gate named <level> reports <verdict>
    When the gate <level> runs
    Then the run reports <verdict>

    Examples:
      | level  | verdict |
      | unit   | green   |
      | system | red     |
"""


def test_a_background_step_is_part_of_every_scenarios_walk_and_says_so():
    """Prepended, not grouped - because the runner prepends them and si#205's person has to perform them
    once per scenario. `background` only lets the page mark them."""
    # arrange / act
    feature = acceptance.read(BACKGROUND, "f.feature", "f/f.feature")

    # assert
    scenario = feature.scenarios[0]
    assert [step.announced for step in scenario.steps] == [
        "Given a product", "And a manifest", "When it runs", "Then it passes"]
    assert [step.background for step in scenario.steps] == [True, True, False, False]
    assert feature.background == scenario.steps[:2]


def test_a_feature_carries_its_prose_and_both_levels_of_tag():
    # arrange / act
    feature = acceptance.read(BACKGROUND, "f.feature")

    # assert
    assert feature.name == "A feature with a background"
    assert feature.description == ("Some prose about the feature.",)
    assert feature.tags == ("fast",)
    assert feature.scenarios[0].tags == ("one",)


def test_an_outline_becomes_one_scenario_per_examples_row_with_the_values_filled_in():
    """The decision that could not be reasoned to: the archive knows only the expanded rows, so a page
    listing the outline once would carry an address matching nothing that ever ran."""
    # arrange / act
    feature = acceptance.read(OUTLINE, "o.feature", "o/o.feature")

    # assert
    assert [s.name for s in feature.scenarios] == ["A gate named unit reports green",
                                                   "A gate named system reports red"]
    assert [s.row for s in feature.scenarios] == [1, 2]
    assert {s.outline for s in feature.scenarios} == {"A gate named <level> reports <verdict>"}
    assert [step.announced for step in feature.scenarios[0].steps] == [
        "Given a product", "When the gate unit runs", "Then the run reports green"]


def test_a_step_keeps_its_docstring_and_its_table_and_neither_reaches_the_address():
    """A payload is what a person needs and what the archive does not carry, so it is on the step and out
    of `announced` - measured: an Allure step's name is `<Keyword> <text>` and nothing else."""
    # arrange
    text = '''\
Feature: Payloads

  Scenario: A step with arguments
    When the manifest says:
      """
      groups:
        test: {}
      """
    Then the rows are
      | key | value |
      | a   | 1     |
'''
    # act
    feature = acceptance.read(text, "p.feature")

    # assert
    when, then = feature.scenarios[0].steps
    assert when.payload == ("      groups:", "        test: {}")
    assert when.announced == "When the manifest says:"
    assert then.payload == ("| key | value |", "| a   | 1     |")
    assert then.announced == "Then the rows are"


def test_the_runner_path_is_the_base_directorys_name_and_not_the_repository_path():
    """`pytest_bdd.parser.FeatureParser`'s own rule, measured. The two spellings differ for every product
    whose feature directory is not at the root, so the page prints both."""
    # arrange
    source = ROOT / SOURCE

    # act
    rel = acceptance.runner_path(source, source / "sub" / "x.feature")

    # assert
    assert rel == "acceptance/sub/x.feature"
    assert rel != "tests/acceptance/sub/x.feature"


# --- the refusals, each seen red -------------------------------------------------------------------------

LEGAL = """\
Feature: A legal file

  Scenario: One
    Given a product
"""


def test_the_legal_neighbour_of_every_refusal_below_is_accepted():
    """Without this, each refusal below could be passing because the reader refuses everything."""
    # arrange / act
    feature = acceptance.read(LEGAL, "ok.feature")

    # assert
    assert feature.name == "A legal file"
    assert len(feature.scenarios) == 1


@pytest.mark.parametrize("text, fragment", [
    pytest.param("""\
Feature: A rule
  Rule: the interesting half
    Scenario: One
      Given a product
""", "'Rule:' is not supported", id="rule"),
    pytest.param("""\
# language: de
Funktionalitaet: Etwas
""", "renames every Gherkin keyword", id="language"),
    pytest.param("""\
Scenario: One
  Given a product
""", "a line before the 'Feature:' line", id="no-feature"),
    pytest.param("""\
Feature: One
Feature: Two
""", "a second 'Feature:'", id="two-features"),
    pytest.param("""\
Feature: A file
  Scenario:
    Given a product
""", "with no title", id="untitled"),
    pytest.param("""\
Feature: A file
  Scenario Outline: A <thing>
    Given a <thing>
""", "has no Examples row", id="outline-without-examples"),
    pytest.param("""\
Feature: A file
  Scenario: One
    Given a product
    Examples:
      | a |
      | 1 |
""", "'Examples:' outside a 'Scenario Outline:'", id="examples-without-outline"),
    pytest.param("""\
Feature: A file
  Given a product
""", "a 'Given' step outside a Background or a Scenario", id="step-without-scenario"),
    pytest.param("""\
Feature: A file
  Scenario: One
    | a | b |
""", "a table before any step", id="table-without-step"),
    pytest.param('''\
Feature: A file
  Scenario: One
    """
    text
    """
''', "a docstring before any step", id="docstring-without-step"),
    pytest.param("""\
Feature: A file
  Scenario: One
    Given a product
  Background:
    Given something
""", "a 'Background:' after a scenario", id="late-background"),
    pytest.param("""\
Feature: A file
  Scenario: One
    Given a product
  Scenario: One
    Given a product
""", "two scenarios are titled 'One'", id="duplicate-title"),
    pytest.param("""\
Feature: A file
  Scenario Outline: Always the same title
    Given a <thing>

    Examples:
      | thing |
      | a     |
      | b     |
""", "carries no placeholder that differs between rows", id="outline-title-without-placeholder"),
    pytest.param("""\
Feature: A file
  @leaked
  Background:
    Given a product

  Scenario: One
    When it runs
""", "on a 'Background:'", id="tags-on-a-background"),
    pytest.param("""\
Feature: A file
  Background:
    Given a

  Background:
    Given b

  Scenario: One
    Then c
""", "a second 'Background:'", id="two-backgrounds"),
    pytest.param(
        'Feature: A file\n  Scenario: One\n    Given a\n      """\n      no closing delimiter arrives\n',
        "ends inside a docstring payload", id="unterminated-docstring"),
    pytest.param("""\
Feature: A file
  Scenario Outline: A <a> and a <b>
    Given a <a>

    Examples:
      | a | b |
      | 1 |
""", "an Examples row with 1 cells under 2 headers", id="ragged-examples-row"),
])
def test_a_feature_file_that_would_describe_something_no_run_honours_is_refused(text, fragment):
    """Seventeen constructs, each either unexecutable by pytest-bdd or unaddressable once expanded.

    THE COMMON SHAPE is this project's recurring defect rather than pedantry: every one of them would
    otherwise produce a PAGE - a document headed "acceptance scenarios" describing something no run ever
    executed, published and read as evidence.
    """
    # act / assert
    with pytest.raises(ValueError, match=re.escape(fragment)):
        acceptance.read(text, "bad.feature")


def test_a_refusal_from_inside_a_closed_block_names_the_line_the_block_opened_on():
    """FOUND IN REVIEW. `close()` runs when the NEXT construct starts, so an unguarded `line_no` names
    the line that ENDED the block. `_refuse` exists so a reader does not have to search for what the
    parser already found, and a message pointing three lines past the fault is that search handed back.
    """
    # arrange: the outline is on line 2, the scenario that closes it on line 5
    text = """\
Feature: A file
  Scenario Outline: Bad
    Given a

  Scenario: Good
    Then b
"""
    # act / assert
    with pytest.raises(ValueError, match=r"bad\.feature:2: the outline 'Bad'"):
        acceptance.read(text, "bad.feature")


def test_two_tag_lines_above_one_scenario_both_survive():
    """FOUND IN REVIEW. Ordinary Gherkin style, and `pending_tags = ...` kept only the last of them. A
    tag becomes an Allure label AND a selection criterion, so a dropped one is a scenario missing from
    the run somebody selected it into - the same harm the Background-tag refusal above exists for."""
    # arrange
    text = """\
Feature: A file
  @fast
  @wip
  Scenario: One
    Given a product
"""
    # act
    feature = acceptance.read(text, "f.feature")

    # assert
    assert feature.scenarios[0].tags == ("fast", "wip")


def test_an_escaped_separator_inside_a_table_cell_is_one_cell():
    """FOUND IN REVIEW. Gherkin escapes `|` inside a cell and a plain split counts it as a column break -
    which on an Examples row changes the CELL COUNT, so a legal row is refused as ragged."""
    # arrange
    text = """\
Feature: A file
  Scenario Outline: A <verdict>
    Given a product

    Examples:
      | verdict     |
      | green \\| red |
"""
    # act
    feature = acceptance.read(text, "f.feature")

    # assert
    assert [s.name for s in feature.scenarios] == ["A green | red"]


@pytest.mark.parametrize("source", ["/etc", "../outside", "sub/../../outside"])
def test_a_source_outside_the_product_root_is_refused_before_anything_is_read(tmp_path, source):
    """FOUND IN REVIEW, and it was not theoretical. `root / source` DISCARDS root when source is absolute
    (pathlib's rule), and a `..` walks out of the product - in both cases the feature files found out
    there were read and their content baked into a published page, with no error at all.

    si#183's asymmetry is about whether the kernel supplies a DEFAULT for a key, never about whether the
    value a manifest wrote has to be a path under the product. `output` is checked because it is written
    to; this is checked because what it reads is published.
    """
    # act / assert
    with pytest.raises(ValueError, match="source directory"):
        acceptance.features(tmp_path, source)


def test_a_source_that_is_not_there_and_a_source_that_is_empty_refuse_differently(tmp_path):
    """Two nothings, two messages. A manifest pointing at nothing is not a product that has not written
    its scenarios yet, and a caller who cannot tell them apart looks in the wrong place."""
    # arrange
    (tmp_path / "empty").mkdir()

    # act / assert
    with pytest.raises(ValueError, match="is not a directory under the product root"):
        acceptance.features(tmp_path, "missing")
    with pytest.raises(ValueError, match="holds no .feature file"):
        acceptance.features(tmp_path, "empty")


def test_an_unknown_placeholder_is_left_as_written():
    """pytest-bdd leaves it too, so blanking it would make the page's address differ from the archive's
    on exactly the file that has a typo in it."""
    # arrange
    text = """\
Feature: A file
  Scenario Outline: A <known> and a <typo>
    Given a product

    Examples:
      | known |
      | one   |
"""
    # act
    feature = acceptance.read(text, "f.feature")

    # assert
    assert feature.scenarios[0].name == "A one and a <typo>"


# --- the page --------------------------------------------------------------------------------------------


def _render(text: str, path: str = "acceptance/f.feature") -> str:
    return acceptance.render([acceptance.read(text, f"tests/{path}", path)],
                             product="p", title="T", source="tests/acceptance")


def test_the_page_states_the_requirement_the_evidence_depends_on():
    """PR #198's finding is a requirement on the PRODUCT, and si#204 says whatever this document says
    about running the scenarios has to name it. Generated rather than written, for the same reason the
    counts are: a requirement typed into a document is one nothing reads back."""
    # act
    page = _render(BACKGROUND)

    # assert
    assert acceptance.PLUGIN in page
    assert "allure-pytest`" in page, "the plugin that is NOT enough has to be named beside the one that is"
    assert "cannot be compared" in page


def test_the_counts_in_the_lead_sentence_are_computed_and_not_typed():
    # arrange
    two = acceptance.read(OUTLINE, "tests/acceptance/o.feature", "acceptance/o.feature")
    one = acceptance.read(BACKGROUND, "tests/acceptance/f.feature", "acceptance/f.feature")

    # act
    page = acceptance.render([one, two], product="p", title="T", source="tests/acceptance")

    # assert: one plain scenario plus two expanded outline rows, across two files
    assert "This page lists 3 acceptance scenarios across 2 feature files" in page


def test_the_page_carries_every_scenarios_address_and_every_step():
    # act
    page = _render(BACKGROUND)

    # assert
    assert "`acceptance/f.feature:A plain scenario`" in page
    for step in ("Given** a product", "And** a manifest", "When** it runs", "Then** it passes"):
        assert step in page
    assert "*(background)*" in page


def test_the_page_says_where_the_file_is_as_well_as_what_the_runner_calls_it():
    """The address is not a repository path since the measurement, so the page has to say where the file
    sits or a reader cannot open it."""
    # act
    page = _render(BACKGROUND)

    # assert
    assert "Source: `tests/acceptance/f.feature`, which the runner knows as `acceptance/f.feature`." in page


def test_an_outlines_own_title_is_printed_in_a_code_span_so_hugo_keeps_the_placeholders():
    """`<level>` in prose is an HTML tag to Hugo's renderer and disappears - taking the template out of
    the one line whose job is to show it."""
    # act
    page = _render(OUTLINE)

    # assert
    assert "the outline `A gate named <level> reports <verdict>`" in page
    assert "*A gate named <level>" not in page


def test_a_docstring_holding_a_fence_does_not_close_the_pages_own_fence():
    """FOUND IN REVIEW. A literal ``` inside a ```-fenced block ends it under CommonMark, so everything
    below it renders as prose. The front-matter title is YAML-escaped for the same class of reason; this
    is the Markdown half of it, and a feature file documenting a code block is not exotic."""
    # arrange
    text = ('Feature: A file\n  Scenario: One\n    Given the readme says:\n      """\n'
            '      ```\n      code\n      ```\n      """\n')

    # act
    page = _render(text)

    # assert: the page's own fence is longer than the payload's
    assert "   ````text" in page
    inside = page.split("   ````text", 1)[1].split("   ````", 1)[0]
    assert "code" in inside, "the payload was cut short by its own fence"


def test_a_scenario_title_carrying_a_column_separator_does_not_break_the_index_table():
    # arrange
    text = """\
Feature: A file
  Scenario: A verdict is green | red and never both
    Given a product
"""
    # act
    page = _render(text)

    # assert
    row = next(line for line in page.splitlines() if line.startswith("| A verdict"))
    assert row.count("|") - row.count("\\|") == 5, row
    assert "green \\| red" in row


# --- the property the ticket is about --------------------------------------------------------------------


def test_a_new_scenario_reaches_the_page_and_nothing_else_was_touched(tmp_path):
    """THE ASSERTION si#204 ASKED FOR. "Asserting the generator was called proves nothing" - so this
    renders a tree, adds a scenario to a source file, renders again, and holds the two pages against each
    other.

    Three things at once, and the third is the half that would otherwise be assumed: the new scenario is
    on the page, the COUNT in the lead sentence went up by exactly one, and every other line of the page
    is unchanged - so the page grew rather than being rewritten, and nothing but the feature file was
    edited to make it grow.
    """
    # arrange
    source = tmp_path / "tests" / "acceptance"
    source.mkdir(parents=True)
    (source / "f.feature").write_text(BACKGROUND, encoding="utf-8")
    before = acceptance.render(acceptance.features(tmp_path, "tests/acceptance"),
                               product="p", title="T", source="tests/acceptance")

    # act
    (source / "f.feature").write_text(
        BACKGROUND + "\n  Scenario: A scenario nobody edited a page for\n    When it runs\n"
                     "    Then it also passes\n", encoding="utf-8")
    after = acceptance.render(acceptance.features(tmp_path, "tests/acceptance"),
                              product="p", title="T", source="tests/acceptance")

    # assert: it is there, addressed
    assert "A scenario nobody edited a page for" not in before
    assert "`acceptance/f.feature:A scenario nobody edited a page for`" in after
    assert "Then** it also passes" in after

    # assert: the count is the page's own and it moved by one
    assert "This page lists 1 acceptance scenario across 1 feature file" in before
    assert "This page lists 2 acceptance scenarios across 1 feature file" in after

    # assert: everything else stayed put - the page grew, it was not rewritten
    kept = [line for line in before.splitlines() if line and "This page lists" not in line]
    assert kept == [line for line in after.splitlines()
                    if line in kept][:len(kept)], "an existing line of the page moved or changed"


# --- the task --------------------------------------------------------------------------------------------


def test_the_task_writes_the_page_and_says_how_much_it_found(tmp_path, monkeypatch, capsys):
    # arrange
    source = tmp_path / "tests" / "acceptance"
    source.mkdir(parents=True)
    (source / "f.feature").write_text(OUTLINE, encoding="utf-8")
    monkeypatch.setattr(acceptance.context, "current",
                        lambda: type("Ctx", (), {"root": tmp_path, "name": "p"})())

    # act
    rc = acceptance.document("site/acceptance.md")

    # assert
    assert rc == 0
    page = (tmp_path / "site" / "acceptance.md").read_text(encoding="utf-8")
    assert page.startswith('---\ntitle: "p acceptance scenarios"\n---')
    assert "2 scenarios from 1 feature file)" in capsys.readouterr().out


def test_an_absolute_output_path_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    """The value comes from a manifest and is then WRITTEN to, so an absolute one would land outside the
    product entirely - `cliref.reference`'s rule, and the same guard."""
    # arrange
    monkeypatch.setattr(acceptance.context, "current",
                        lambda: type("Ctx", (), {"root": tmp_path, "name": "p"})())

    # act / assert
    with pytest.raises(ValueError, match="it must be relative"):
        acceptance.document("/etc/acceptance.md")
    assert not list(tmp_path.iterdir()), "the path was refused after something had already been written"
