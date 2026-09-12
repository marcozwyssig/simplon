"""The manual acceptance walk, everything about it that needs no terminal (si#205).

The half that DOES need one - the two keys, a person's verdict reaching a step, a stopped walk leaving a
third state, and a resume refusing across a change - is driven through Textual's own test driver in
`test_walk_tui.py`. What is here is selection, the run key and its invalidation rule, the state sidecar,
the plan's shape, and the header the record is made of.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from simplon import context, tracker
from simplon.orchestrator.steps import StepState, build_rows, summarise
from simplon.tasks import walk as walk_mod
from simplon.tasks.acceptance import features, read

ONE = """@gate
Feature: One verdict

  Background:
    Given a clean checkout

  @fast
  Scenario: The gate runs everything
    When I run the gate
    Then it reports three steps

  Scenario: A gate that found nothing is not green
    When the empty gate runs
    Then it does not report success
"""

TWO = """@documents
Feature: The documents cannot go stale

  @reference
  Scenario: The reference names every command
    When I build the reference
    Then the page lists them
"""


def _files(root: Path, **named: str) -> Path:
    source = root / "tests" / "acceptance"
    source.mkdir(parents=True)
    for name, text in named.items():
        (source / f"{name}.feature").write_text(text, encoding="utf-8")
    return source


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A product tree with two feature files and its context registered, so `state_path` answers."""
    _files(tmp_path, one=ONE, two=TWO)
    monkeypatch.setattr(context, "_current",
                        context.ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    return tmp_path


def _found(root: Path):
    return features(root, "tests/acceptance")


def _taken(root: Path, wanted: tuple[str, ...] = ()):
    return walk_mod.select(_found(root), wanted)[0]


def _key(root: Path, selection: str = "all scenarios",
         wanted: tuple[str, ...] = ()) -> walk_mod.RunKey:
    return walk_mod.RunKey(product="demo", version="v1.0.0", revision="abc123",
                           source="tests/acceptance", selection=selection,
                           scenarios=walk_mod.digest(_taken(root, wanted)))


# --- selection ------------------------------------------------------------------------------------------


def test_a_tag_selection_is_canonical_however_it_was_written():
    # arrange / act
    spaced = walk_mod.parse_tags("@gate, documents")
    reordered = walk_mod.parse_tags("documents gate")

    # assert: one selection, so the two spellings key ONE resume rather than two
    assert spaced == reordered == ("documents", "gate")


def test_a_feature_level_tag_selects_every_scenario_in_the_file(product):
    """pytest-bdd applies a feature tag to every scenario in the file, so a selection that read only
    `Scenario.tags` would walk a different set than the automatic mode - two answers over one source."""
    # act
    taken, left = walk_mod.select(_found(product), ("gate",))

    # assert
    assert [scenario.name for _, scenarios in taken for scenario in scenarios] == [
        "The gate runs everything", "A gate that found nothing is not green"]
    assert left == ["acceptance/two.feature:The reference names every command"]


def test_a_scenario_level_tag_selects_only_that_scenario(product):
    # act
    taken, left = walk_mod.select(_found(product), ("fast",))

    # assert
    assert [scenario.name for _, scenarios in taken for scenario in scenarios] == [
        "The gate runs everything"]
    assert len(left) == 2


def test_what_was_left_out_is_returned_by_address_and_not_only_counted(product):
    """si#205's document rule: a record saying `passed` when some of the scenarios were never walked is a
    false document, and the number 2 does not tell a reader WHICH functionality went unverified."""
    # act
    _, left = walk_mod.select(_found(product), ("fast",))

    # assert
    assert left == ["acceptance/one.feature:A gate that found nothing is not green",
                    "acceptance/two.feature:The reference names every command"]


def test_no_selection_walks_everything(product):
    # act
    taken, left = walk_mod.select(_found(product), ())

    # assert
    assert sum(len(scenarios) for _, scenarios in taken) == 3
    assert left == []


def test_a_selection_that_matched_nothing_is_refused_with_the_tags_that_exist(product):
    """A walk of no scenarios would end `no steps` and rc 1, which is right - but the REASON has to be the
    tag that matched nothing rather than a run that merely looks as though it went wrong."""
    # act
    message = walk_mod._no_selection(_found(product), ("nope",), "tests/acceptance")

    # assert
    assert "matched none of the 3 scenario(s)" in message
    assert "@documents, @fast, @gate, @reference" in message


# --- the run key and its invalidation rule ----------------------------------------------------------------


def test_the_digest_moves_when_a_step_is_reworded(product):
    # arrange
    before = walk_mod.digest(_taken(product))

    # act
    path = product / "tests" / "acceptance" / "one.feature"
    path.write_text(ONE.replace("Then it reports three steps", "Then it reports four steps"),
                    encoding="utf-8")

    # assert
    assert walk_mod.digest(_taken(product)) != before


def test_the_digest_moves_when_a_tag_moves_a_scenario_in_or_out_of_a_selection(product):
    # arrange
    before = walk_mod.digest(_taken(product))

    # act
    path = product / "tests" / "acceptance" / "one.feature"
    path.write_text(ONE.replace("  @fast\n", "  @slow\n"), encoding="utf-8")

    # assert
    assert walk_mod.digest(_taken(product)) != before


def test_the_digest_does_not_move_over_a_comment_nobody_was_shown(product):
    """Hashing the raw bytes would have been shorter and would invalidate a person's afternoon over a typo
    in a comment. The digest is over the QUESTIONS."""
    # arrange
    before = walk_mod.digest(_taken(product))

    # act
    path = product / "tests" / "acceptance" / "one.feature"
    path.write_text("# a note for whoever edits this\n" + ONE, encoding="utf-8")

    # assert
    assert walk_mod.digest(_taken(product)) == before


def test_the_digest_moves_when_a_step_gains_a_docstring_payload(product):
    # arrange
    before = walk_mod.digest(_taken(product))

    # act
    path = product / "tests" / "acceptance" / "one.feature"
    path.write_text(ONE.replace('    When I run the gate\n',
                                '    When I run the gate\n      """\n      ./demo.sh test all\n      """\n'),
                    encoding="utf-8")

    # assert
    assert walk_mod.digest(_taken(product)) != before


def test_the_digest_ignores_a_scenario_this_walk_does_not_ask(product):
    """FOUND IN REVIEW. The first version hashed every file under `source`, so a person half way through
    `--tags @fast` could not continue after a wording fix in a scenario they were never shown and never
    would be - a legitimate resume refused over a question that is not one of theirs."""
    # arrange
    before = walk_mod.digest(_taken(product, ("fast",)))

    # act: an edit inside the SAME file, to a scenario the @fast selection leaves out
    path = product / "tests" / "acceptance" / "one.feature"
    path.write_text(ONE.replace("Then it does not report success", "Then it reports no success"),
                    encoding="utf-8")

    # assert
    assert walk_mod.digest(_taken(product, ("fast",))) == before
    assert walk_mod.digest(_taken(product)) != before, "and the unselected walk still sees it"


def test_the_digest_still_sees_a_tag_that_moves_a_scenario_into_the_selection(product):
    """Nothing is lost on the safe side by scoping it: membership changes what is hashed."""
    # arrange
    before = walk_mod.digest(_taken(product, ("fast",)))

    # act
    path = product / "tests" / "acceptance" / "two.feature"
    path.write_text(TWO.replace("  @reference\n", "  @reference @fast\n"), encoding="utf-8")

    # assert
    assert walk_mod.digest(_taken(product, ("fast",))) != before


def test_the_run_key_takes_the_digest_of_the_selection_it_was_handed(product, monkeypatch):
    """The wiring, not only `digest`'s own scope: a key built over every file found would reintroduce the
    over-invalidation whatever `digest` does with what it is given. The signature makes the other spelling
    a type error, and this makes it a red test too."""
    # arrange: no git in the way - the version half of the key is not what this is about
    monkeypatch.setattr(walk_mod, "provenance", lambda root: {"VERSION": "v1", "REVISION": "r1"})
    narrow = _taken(product, ("fast",))

    # act
    key = walk_mod.run_key("demo", product, "tests/acceptance", "@fast", narrow)

    # assert
    assert key.scenarios == walk_mod.digest(narrow)
    assert key.scenarios != walk_mod.digest(_taken(product))


def test_a_moved_key_names_every_part_that_moved_and_both_values():
    # arrange
    earlier = walk_mod.RunKey("demo", "v1.0.0", "abc", "tests/acceptance", "all scenarios", "sha256:aa")
    now = walk_mod.RunKey("demo", "v1.0.1", "def", "tests/acceptance", "all scenarios", "sha256:aa")

    # act
    moved = now.moved_from(earlier)

    # assert
    assert moved == ["the product version ('v1.0.0' -> 'v1.0.1')",
                     "the product revision ('abc' -> 'def')"]


def test_an_unchanged_key_reports_nothing_moved():
    # arrange
    key = walk_mod.RunKey("demo", "v1.0.0", "abc", "tests/acceptance", "all scenarios", "sha256:aa")

    # act / assert
    assert key.moved_from(key) == []


def test_a_key_with_no_product_version_is_not_resumable():
    """Nothing in such a key could ever see a rebuild, so a resume against it would be a check that cannot
    fail - the defect class this repository hunts, in the one place where being wrong is silent."""
    # arrange
    key = walk_mod.RunKey("demo", "", "", "tests/acceptance", "all scenarios", "sha256:aa")

    # act / assert
    assert not key.resumable
    assert walk_mod.RunKey("demo", "v1", "", "t", "all scenarios", "sha256:aa").resumable


def test_a_walk_whose_product_moved_is_refused_and_the_message_says_how_to_go_on(tmp_path):
    # arrange
    earlier = walk_mod.State(
        key=walk_mod.RunKey("demo", "v1.0.0", "abc", "tests/acceptance", "all scenarios", "sha256:aa"),
        answers={"acceptance/one.feature:x": {"0": {"verdict": "ok", "at": "2026-09-12 10:00:00"}}})
    now = walk_mod.RunKey("demo", "v1.0.1", "def", "tests/acceptance", "all scenarios", "sha256:aa")

    # act
    refusal = walk_mod.refuse_to_resume(now, earlier, tmp_path / "acceptance-walk.json")

    # assert
    assert "cannot be continued" in refusal
    assert "1 step(s) were answered against a different state" in refusal
    assert "the product version ('v1.0.0' -> 'v1.0.1')" in refusal
    assert "--restart" in refusal


def test_a_walk_whose_scenarios_moved_is_refused_even_when_the_product_did_not(tmp_path):
    """The two halves of the key catch different things: a feature file edited in a dirty tree moves no
    version at all."""
    # arrange
    earlier = walk_mod.State(
        key=walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:aa"))
    now = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:bb")

    # act / assert
    assert "the scenarios themselves" in walk_mod.refuse_to_resume(now, earlier, tmp_path / "s.json")


def test_a_walk_of_a_different_selection_is_refused(tmp_path):
    # arrange
    earlier = walk_mod.State(
        key=walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "@gate", "sha256:aa"))
    now = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "@documents", "sha256:aa")

    # act / assert
    assert "the selection ('@gate' -> '@documents')" in walk_mod.refuse_to_resume(
        now, earlier, tmp_path / "s.json")


def test_a_walk_that_matches_but_cannot_be_checked_is_refused_too(tmp_path):
    # arrange: identical keys, and neither carries a version
    key = walk_mod.RunKey("demo", "", "", "tests/acceptance", "all scenarios", "sha256:aa")

    # act
    refusal = walk_mod.refuse_to_resume(key, walk_mod.State(key=key), tmp_path / "s.json")

    # assert
    assert "No version could be derived" in refusal


def test_an_unchanged_key_is_allowed_to_continue(tmp_path):
    # arrange
    key = walk_mod.RunKey("demo", "v1", "abc", "tests/acceptance", "all scenarios", "sha256:aa")

    # act / assert
    assert walk_mod.refuse_to_resume(key, walk_mod.State(key=key), tmp_path / "s.json") == ""


# --- the state sidecar ----------------------------------------------------------------------------------


def test_the_state_lives_beside_the_run_transcript(product):
    """si#155 lists what the kernel writes into a product tree and `build/logs/` is already on it, so this
    adds no directory, no gitignore line and nothing new to clean."""
    # act
    path = walk_mod.state_path()

    # assert
    assert path == product / "build" / "logs" / "acceptance-walk.json"


def test_a_state_written_is_a_state_read_back(product):
    # arrange
    state = walk_mod.State(key=_key(product), sittings=[{"started": "a", "ended": "b", "by": "c"}])
    state.record("acceptance/one.feature:x", 0, True, datetime(2026, 9, 12, 10, 0, 0), "Ada")
    state.record("acceptance/one.feature:x", 1, False, datetime(2026, 9, 12, 10, 1, 0), "Ada")
    path = walk_mod.state_path()

    # act
    walk_mod.save_state(path, state)
    back = walk_mod.load_state(path)

    # assert
    assert back is not None
    assert back.key == state.key
    assert back.sittings == state.sittings
    assert back.answer_for("acceptance/one.feature:x", 0) == {
        "verdict": "ok", "at": "2026-09-12 10:00:00", "by": "Ada"}
    assert back.answer_for("acceptance/one.feature:x", 1)["verdict"] == "failed"


def test_a_state_that_is_not_there_is_not_a_warning(product, capsys):
    # act
    back = walk_mod.load_state(walk_mod.state_path())

    # assert: no file is the ordinary first sitting, not a problem to report
    assert back is None
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("payload, why", [
    ("not json at all", "unreadable"),
    ('["a", "list"]', "not an object"),
    ('{"format": 99, "key": {}, "sittings": [], "answers": {}}', "a format from the future"),
    ('{"format": 2, "sittings": [], "answers": {}}', "a key that is not there"),
    ('{"format": 2, "key": {"product": "demo"}, "sittings": [], "answers": {}}', "half a key"),
    # FOUND BY DRIVING IT, and it was accepted before: `dict([])` is `{}`, so a document whose `answers`
    # was a LIST read as a state with no answers - and `[["a", {}]]` would have read as a real one.
    ('{"format": 2, "key": {"product": "d", "version": "v", "revision": "r", "source": "s", '
     '"selection": "a", "scenarios": "x"}, "sittings": [], "answers": [], "reasons": {}, '
     '"tickets": {}}', "a list where an object goes"),
    ('{"format": 2, "key": {"product": "d", "version": "v", "revision": "r", "source": "s", '
     '"selection": "a", "scenarios": "x"}, "sittings": "one", "answers": {}, "reasons": {}, '
     '"tickets": {}}', "sittings that is a string"),
    # FOUND IN REVIEW. Nothing checked the token, and everything downstream reads "not ok" as a refusal -
    # so a corrupted verdict would have been replayed as the customer saying no, silently.
    ('{"format": 2, "key": {"product": "d", "version": "v", "revision": "r", "source": "s", '
     '"selection": "a", "scenarios": "x"}, "sittings": [], '
     '"answers": {"a:b": {"0": {"verdict": "yes", "at": "t"}}}, "reasons": {}, '
     '"tickets": {}}', "a verdict token nobody writes"),
    # si#206 ADDED THE TWO RECORDS AND BUMPED THE FORMAT. A document written by the version before it is
    # therefore refused by number, not read as a state with no reasons in it - and a document claiming
    # the current format while missing one of them is half a state, which is the same fault as half a
    # key above.
    ('{"format": 1, "key": {"product": "d", "version": "v", "revision": "r", "source": "s", '
     '"selection": "a", "scenarios": "x"}, "sittings": [], "answers": {}}',
     "the format si#205 wrote, before the two records existed"),
    ('{"format": 2, "key": {"product": "d", "version": "v", "revision": "r", "source": "s", '
     '"selection": "a", "scenarios": "x"}, "sittings": [], "answers": {}, "tickets": {}}',
     "no reasons record at all"),
    ('{"format": 2, "key": {"product": "d", "version": "v", "revision": "r", "source": "s", '
     '"selection": "a", "scenarios": "x"}, "sittings": [], "answers": {}, "reasons": {}, '
     '"tickets": []}', "a list where the tickets object goes"),
])
def test_an_unusable_state_claims_nothing_and_says_so(product, capsys, payload, why):
    """UNUSABLE IS NOT THE SAME AS MOVED. A state the kernel cannot fully check means it does not know
    what was answered, so it claims nothing and every question is asked again - safe. A state it CAN read
    whose key has moved is the dangerous one, and that is a refusal rather than a fresh start."""
    # arrange
    path = walk_mod.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")

    # act
    back = walk_mod.load_state(path)

    # assert
    assert back is None, why
    assert "walk state" in capsys.readouterr().out


def test_a_state_that_cannot_be_written_costs_the_resume_and_not_the_run(product, capsys):
    # arrange: a FILE where the directory has to go
    path = product / "build" / "logs" / "acceptance-walk.json"
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    (product / "build" / "logs").write_text("in the way", encoding="utf-8")

    # act
    written = walk_mod.save_state(path, walk_mod.State(key=_key(product)))

    # assert
    assert written is None
    assert "cannot be continued later" in capsys.readouterr().out


# --- the plan ---------------------------------------------------------------------------------------------


def _plan(root: Path, state: walk_mod.State | None = None):
    taken, _ = walk_mod.select(_found(root), ())
    return walk_mod.plan(taken, state or walk_mod.State(key=_key(root)), walk_mod.Prompt())


def test_the_plan_is_feature_then_scenario_then_step(product):
    # act
    pipeline = _plan(product)
    root = build_rows(pipeline)

    # assert: the tree the runner draws is the Gherkin shape, and nothing had to be taught it
    assert root.label == "test.walk"
    assert [child.label for child in root.children] == ["acceptance/one.feature", "acceptance/two.feature"]
    assert [child.label for child in root.children[0].children] == [
        "The gate runs everything", "A gate that found nothing is not green"]
    assert [leaf.label for leaf in root.children[0].children[0].children] == [
        "1. Given a clean checkout", "2. When I run the gate", "3. Then it reports three steps"]


def test_every_scenario_stops_on_a_failure_and_nothing_above_it_does(product):
    """The mapping's load-bearing half: pytest-bdd stops a scenario at its first failing step and runs the
    next scenario anyway, and `abort_after` reproduces that from this flag alone."""
    # act
    tree = _plan(product).tree

    # assert
    assert tree is not None
    assert not tree.spec.stop_on_failure
    for feature in tree.children:
        assert not feature.spec.stop_on_failure
        for scenario in feature.children:
            assert scenario.spec.stop_on_failure


def test_the_pairing_the_display_and_the_abort_both_rest_on_is_verifiable(product):
    """`Pipeline.usable_tree` rejects a tree whose leaves do not pair with the steps, and a rejected tree
    silently drops every subtree's stop_on_failure - which would take the property above with it."""
    # act
    pipeline = _plan(product)

    # assert
    assert pipeline.usable_tree() is pipeline.tree


def test_the_address_travels_in_the_step_header_so_the_record_is_unambiguous(product):
    """The left pane reads as a scenario and the transcript still says which scenario each line belongs
    to - si#148's own division between the tree and the section header."""
    # act
    pipeline = _plan(product)

    # assert
    assert pipeline.steps[0].label == "1. Given a clean checkout"
    assert pipeline.steps[0].help == "acceptance/one.feature:The gate runs everything"
    assert pipeline.steps[3].help == "acceptance/one.feature:A gate that found nothing is not green"


def test_every_steps_identity_is_unique_across_the_whole_walk(product):
    """FOUND IN REVIEW, and it is not only a label: `steplog.log_name` turns `Step.command` into a
    filename under `build/logs/`, so two steps sharing one would overwrite each other's output the moment
    one crashes or somebody presses `s` on both. A feature with a `Background:` - the ordinary case, and
    this fixture - gives every scenario the same first step."""
    # act
    pipeline = _plan(product)
    commands = [step.command for step in pipeline.steps]

    # assert
    assert len(set(commands)) == len(commands)
    assert commands[:2] == ["1.1 Given a clean checkout", "1.2 When I run the gate"]
    assert commands[3] == "2.1 Given a clean checkout"
    # and the LEFT PANE still numbers inside its own scenario
    assert [step.label for step in pipeline.steps][:4] == [
        "1. Given a clean checkout", "2. When I run the gate", "3. Then it reports three steps",
        "1. Given a clean checkout"]


def test_the_background_is_walked_once_per_scenario(product):
    """si#204 prepends the background into every scenario's step list, because a person performs it once
    per scenario and so does the runner. Both scenarios of one.feature therefore open with it."""
    # act
    pipeline = _plan(product)

    # assert
    assert [step.label for step in pipeline.steps][:4] == [
        "1. Given a clean checkout", "2. When I run the gate", "3. Then it reports three steps",
        "1. Given a clean checkout"]


def test_a_step_answered_in_an_earlier_sitting_says_so_on_its_own_line(product):
    # arrange
    state = walk_mod.State(key=_key(product))
    state.record("acceptance/one.feature:The gate runs everything", 1, False,
                 datetime(2026, 9, 12, 10, 30, 0), "Ada")

    # act
    pipeline = _plan(product, state)

    # assert: per step, not per run - "resumed at least once" says nothing about which of forty
    assert pipeline.steps[1].help == ("acceptance/one.feature:The gate runs everything - REFUSED in an "
                                      "earlier sitting at 2026-09-12 10:30:00")
    assert pipeline.steps[0].help.endswith("The gate runs everything")


def test_a_replayed_step_takes_its_verdict_from_the_record_and_asks_nobody(product):
    """A resumed walk has no second path anywhere: the replay goes through the very same step body."""
    # arrange
    state = walk_mod.State(key=_key(product))
    state.record("acceptance/one.feature:The gate runs everything", 0, True,
                 datetime(2026, 9, 12, 10, 0, 0), "Ada")
    state.record("acceptance/one.feature:The gate runs everything", 1, False,
                 datetime(2026, 9, 12, 10, 1, 0), "Ada")
    pipeline = _plan(product, state)

    # act: no Prompt is ever answered, so a body that asked would block here
    accepted = pipeline.steps[0].run()
    refused = pipeline.steps[1].run()

    # assert
    assert accepted.rc == 0 and refused.rc == 1
    assert "already answered: accepted at 2026-09-12 10:00:00" in accepted.output
    assert "already answered: refused at 2026-09-12 10:01:00" in refused.output


def test_an_unanswered_step_shows_the_question_and_both_keys(product):
    # arrange
    taken, _ = walk_mod.select(_found(product), ("fast",))
    scenario = taken[0][1][0]

    # act
    lines = walk_mod.question(scenario, 1, scenario.steps[1], "")

    # assert
    assert lines[0] == "acceptance/one.feature:The gate runs everything"
    assert lines[1] == "step 2 of 3"
    assert "    When I run the gate" in lines
    assert lines[-1] == "press  a  to accept this step, or  r  to refuse it - one key either way"


def test_a_background_step_says_where_it_came_from(product):
    # arrange
    taken, _ = walk_mod.select(_found(product), ("fast",))
    scenario = taken[0][1][0]

    # act
    lines = walk_mod.question(scenario, 0, scenario.steps[0], "")

    # assert
    assert lines[1] == "step 1 of 3 (from the feature background)"


def test_a_step_payload_is_shown_to_the_person_although_it_is_not_in_the_address():
    """si#204 keeps a docstring off the address because the archive does not carry it either - but a
    person walking the step needs it, so it is on the page and it is here."""
    # arrange
    feature = read('Feature: f\n\n  Scenario: s\n    Given a config\n      """\n      key: value\n'
                   '      """\n', "tests/acceptance/f.feature", "acceptance/f.feature")
    scenario = feature.scenarios[0]

    # act
    lines = walk_mod.question(scenario, 0, scenario.steps[0], "")

    # assert
    assert "      key: value" in lines


# --- the record's header ----------------------------------------------------------------------------------


def _header(product: Path, wanted: tuple[str, ...], sittings: list[dict[str, str]]):
    taken, left = walk_mod.select(_found(product), wanted)
    key = _key(product, walk_mod.selection_text(wanted))
    return walk_mod.header(key, walk_mod.State(key=key, sittings=sittings), taken, left)


def test_the_record_says_the_verdicts_are_a_persons_and_not_a_measurement(product):
    # act
    lines = _header(product, (), [{"started": "2026-09-12 10:00:00", "ended": "", "by": "A Person"}])

    # assert
    assert any("a person's judgement, one answer per Gherkin step - not a measurement" in line
               for line in lines)


def test_the_record_names_who_and_says_the_name_is_only_claimed(product):
    # act
    lines = _header(product, (), [{"started": "s", "ended": "e", "by": "A Person <a@b.c>"}])

    # assert
    assert lines[0] == "walked by:    A Person <a@b.c> (claimed, not verified)"


def test_the_record_names_the_product_version_that_was_in_front_of_them(product):
    # act
    lines = _header(product, (), [{"started": "s", "ended": "e", "by": "x"}])

    # assert
    assert any(line.startswith("product:      demo v1.0.0 at abc123") for line in lines)


def test_the_record_carries_the_selection_and_names_every_scenario_left_out(product):
    """A record saying `passed` when one of three was walked is a false document."""
    # act
    lines = _header(product, ("fast",), [{"started": "s", "ended": "e", "by": "x"}])

    # assert
    assert any("selection:    @fast - 1 of 3 scenario(s) in 1 feature file(s)" in line for line in lines)
    assert any("2 scenario(s) were not selected and carry no verdict" in line for line in lines)
    assert any(line.strip() == "acceptance/two.feature:The reference names every command"
               for line in lines)


def test_a_record_of_a_full_walk_says_nothing_about_scenarios_left_out(product):
    # act
    lines = _header(product, (), [{"started": "s", "ended": "e", "by": "x"}])

    # assert
    assert not any("not walked" in line for line in lines)


def test_the_record_names_every_sitting_so_one_afternoon_reads_differently_from_three(product):
    # act
    lines = _header(product, (), [{"started": "2026-09-12 10:00:00", "ended": "2026-09-12 10:20:00",
                                   "by": "A"},
                                  {"started": "2026-09-14 09:00:00", "ended": "", "by": "B"}])

    # assert
    assert "sitting 1:    2026-09-12 10:00:00 to 2026-09-12 10:20:00, driven by A" in lines
    assert "sitting 2:    2026-09-14 09:00:00 to in progress, driven by B" in lines


def test_the_header_is_one_column_with_the_transcripts_own(product):
    """si#125's provenance line and si#148's header already exist; this is appended to them, in their
    label width, so the file carries one header and not two that nearly line up."""
    from simplon import steplog

    # act
    theirs = steplog.run_header("test.walk", datetime(2026, 9, 12, 10, 0, 0))
    mine = _header(product, (), [{"started": "s", "ended": "e", "by": "x"}])

    # assert: every value starts in the same column, in both halves of the one header
    columns = {len(line) - len(line.split(":", 1)[1].lstrip()) + len(line.split(":", 1)[1])
               - len(line.split(":", 1)[1]) for line in theirs[1:]}
    assert columns == {steplog._LABEL}
    assert {len(line) - len(line[steplog._LABEL:]) for line in mine[:5]} == {steplog._LABEL}
    assert all(line[steplog._LABEL - 1] == " " and line[steplog._LABEL] != " " for line in mine[:5])


# --- what a walk of nothing does --------------------------------------------------------------------------


def test_a_pipeline_nobody_answered_is_not_green(product):
    """`overall_rc` is 0 only when every step is OK, so PENDING - the state a stopped walk leaves - can
    never read as a pass. Nothing was added for this; it is what the runner already does."""
    # act
    pipeline = _plan(product)
    summary = summarise(build_rows(pipeline))

    # assert
    assert summary.pending == summary.total and not summary.passed
    assert all(step.state is StepState.PENDING for step in pipeline.steps)


def test_the_state_document_is_json_a_person_can_read(product):
    # arrange
    state = walk_mod.State(key=_key(product), sittings=[{"started": "s", "ended": "e", "by": "x"}])
    state.record("a:b", 0, True, datetime(2026, 9, 12, 10, 0, 0), "Ada")

    # act
    walk_mod.save_state(walk_mod.state_path(), state)
    document = json.loads(walk_mod.state_path().read_text(encoding="utf-8"))

    # assert
    assert document["format"] == walk_mod.STATE_FORMAT
    assert document["key"]["selection"] == "all scenarios"
    assert document["answers"]["a:b"]["0"] == {"verdict": "ok", "at": "2026-09-12 10:00:00",
                                              "by": "Ada"}


# --- a refusal becomes a ticket (si#206) ----------------------------------------------------------------


ADDRESS = "acceptance/one.feature:The gate runs everything"
SECOND = "acceptance/two.feature:The reference names every command"


def _refused_state(product, *, address: str = ADDRESS, index: int = 2) -> walk_mod.State:
    """A state in which one step of one scenario was refused."""
    state = walk_mod.State(key=_key(product), sittings=[{"started": "s", "ended": "e", "by": "Ada"}])
    state.record(address, index, False, datetime(2026, 9, 12, 10, 0, 0), "Ada")
    return state


def _manifest(product, section: dict | None) -> None:
    """Give the registered product a real manifest, with or without a `tracker:` section."""
    document = {"groups": {}} if section is None else {"groups": {}, "tracker": section}
    (product / "demo.yaml").write_text(json.dumps(document), encoding="utf-8")


TRACKER = {"kind": "github", "repo": "acme/demo", "labels": ["bug"],
           "title": "Refused: {scenario}"}


def test_every_refusal_the_state_holds_is_found_and_located_in_its_scenario(product):
    # arrange
    state = _refused_state(product)

    # act
    found = walk_mod.refused(_taken(product), state)

    # assert: the step's own text is there, which the state file does not carry
    assert [(one.scenario.address, one.index, one.step.announced) for one in found] == [
        (ADDRESS, 2, "Then it reports three steps")]
    assert found[0].at == "2026-09-12 10:00:00"


def test_a_refusal_from_an_earlier_sitting_is_still_found_so_its_ticket_can_be_opened_later(product):
    """The whole of si#206's 'can open it later': the retry path is the ordinary command, because the
    refusal is still in the state and `State.filed` still has nothing against it."""
    # arrange: written by one sitting, read back by the next
    walk_mod.save_state(walk_mod.state_path(), _refused_state(product))
    later = walk_mod.load_state(walk_mod.state_path())

    # act
    found = walk_mod.refused(_taken(product), later)

    # assert
    assert [one.scenario.address for one in found] == [ADDRESS]
    assert later.filed(ADDRESS) == {}


def test_an_accepted_step_is_not_a_refusal(product):
    # arrange
    state = walk_mod.State(key=_key(product))
    state.record(ADDRESS, 0, True, datetime(2026, 9, 12, 10, 0, 0), "Ada")

    # act / assert
    assert walk_mod.refused(_taken(product), state) == []


def test_the_person_is_asked_what_each_refusal_was_about_and_it_is_recorded(product, capsys):
    # arrange
    state = _refused_state(product)
    pending = walk_mod.refused(_taken(product), state)

    # act
    walk_mod.ask_reasons(pending, state, ask=lambda prompt: "  it showed two rows, not three  ")

    # assert
    assert state.reason_for(ADDRESS, 2) == "it showed two rows, not three"
    shown = capsys.readouterr().out
    assert ADDRESS in shown and "Then it reports three steps" in shown


def test_somebody_who_says_nothing_is_not_asked_again_on_the_next_sitting(product):
    """"" is a person who was asked and declined; None is one nobody has put the question to. The
    difference is what stops the next sitting nagging about a refusal already dealt with."""
    # arrange
    state = _refused_state(product)
    pending = walk_mod.refused(_taken(product), state)
    walk_mod.ask_reasons(pending, state, ask=lambda prompt: "")

    # act
    asked: list[str] = []
    still_unexplained = [one for one in walk_mod.refused(_taken(product), state)
                         if state.reason_for(one.scenario.address, one.index) is None]
    walk_mod.ask_reasons(still_unexplained, state, ask=lambda prompt: asked.append(prompt) or "late")

    # assert
    assert state.reason_for(ADDRESS, 2) == ""
    assert asked == []


def test_an_interrupted_reason_prompt_keeps_what_was_typed_and_says_so(product, capsys):
    # arrange: two refusals, and the person walks away after the first
    state = _refused_state(product)
    state.record(SECOND, 0, False, datetime(2026, 9, 12, 10, 5, 0), "Ada")
    pending = walk_mod.refused(_taken(product), state)
    answers = iter(["the third row was blank"])

    def _ask(prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt from None

    # act
    walk_mod.ask_reasons(pending, state, ask=_ask)

    # assert: nothing raised, the first answer kept, the second still unasked and said out loud
    assert state.reason_for(ADDRESS, 2) == "the third row was blank"
    assert state.reason_for(SECOND, 0) is None
    assert "next sitting" in capsys.readouterr().out


def test_a_ticket_already_in_the_state_is_not_looked_up_again(product, monkeypatch):
    """The immediately consistent half of the idempotence. GitHub's issue search is an index and not a
    read of the table, so a second walk minutes after the first must not depend on it having caught up."""
    # arrange
    _manifest(product, TRACKER)
    state = _refused_state(product)
    key = _key(product)
    ident = tracker.identity(key.product, key.version, ADDRESS)
    state.file(ADDRESS, ident, "https://x/1", datetime(2026, 9, 12, 10, 0, 0))
    monkeypatch.setattr(tracker, "open_ticket", lambda *a: pytest.fail("the tracker was reached"))

    # act
    filed = walk_mod.file_tickets(walk_mod.refused(_taken(product), state), key, state)

    # assert
    assert [(one.url, one.existed) for one in filed] == [("https://x/1", True)]


def test_a_recorded_ticket_for_another_version_does_not_answer_for_this_one(product, monkeypatch):
    """One ticket per scenario per VERSION. A refusal that survives a release is a new ticket, not a
    comment on an old one, so an identity that does not match is not a hit."""
    # arrange
    _manifest(product, TRACKER)
    state = _refused_state(product)
    state.file(ADDRESS, tracker.identity("demo", "v0.9.0", ADDRESS), "https://x/1",
               datetime(2026, 9, 12, 10, 0, 0))
    monkeypatch.setattr(tracker, "open_ticket",
                        lambda destination, refusal: tracker.Ticket(refusal.address, "i", "https://x/2"))

    # act
    filed = walk_mod.file_tickets(walk_mod.refused(_taken(product), state), _key(product), state)

    # assert
    assert [(one.url, one.existed) for one in filed] == [("https://x/2", False)]


def test_what_the_tracker_opened_is_written_into_the_state(product, monkeypatch):
    # arrange
    _manifest(product, TRACKER)
    state = _refused_state(product)
    key = _key(product)
    monkeypatch.setattr(tracker, "open_ticket",
                        lambda destination, refusal: tracker.Ticket(refusal.address, "i", "https://x/3"))

    # act
    walk_mod.file_tickets(walk_mod.refused(_taken(product), state), key, state)

    # assert
    assert state.filed(ADDRESS)["url"] == "https://x/3"
    assert state.filed(ADDRESS)["identity"] == tracker.identity(key.product, key.version, ADDRESS)


def test_the_evidence_the_walk_hands_the_tracker_is_the_whole_of_it(product, monkeypatch):
    # arrange
    _manifest(product, TRACKER)
    state = _refused_state(product)
    state.explain(ADDRESS, 2, "it showed two rows")
    sent: list[tracker.Refusal] = []
    monkeypatch.setattr(tracker, "open_ticket",
                        lambda destination, refusal: sent.append(refusal)
                        or tracker.Ticket(refusal.address, "i", "https://x/4"))

    # act
    walk_mod.file_tickets(walk_mod.refused(_taken(product), state), _key(product), state)

    # assert
    assert sent[0] == tracker.Refusal(
        address=ADDRESS, feature="One verdict", scenario="The gate runs everything",
        step="Then it reports three steps", step_number=3, step_total=3, said="it showed two rows",
        at="2026-09-12 10:00:00", by="Ada", product="demo", version="v1.0.0", revision="abc123",
        source="tests/acceptance", selection="all scenarios")


def test_a_product_with_no_tracker_section_still_records_the_refusal_and_says_no_ticket(product):
    # arrange
    _manifest(product, None)
    state = _refused_state(product)

    # act
    filed = walk_mod.file_tickets(walk_mod.refused(_taken(product), state), _key(product), state)

    # assert
    assert not filed[0].url and "tracker" in filed[0].problem
    assert state.filed(ADDRESS) == {}


def test_the_record_names_the_refusal_whose_ticket_is_missing_rather_than_counting_it(product):
    # arrange
    filed = [tracker.Ticket(ADDRESS, "i", url="https://x/1"),
             tracker.Ticket(SECOND, "j", problem="HTTP 401: Bad credentials")]

    # act
    lines = walk_mod.ticket_lines(filed)

    # assert
    written = "\n".join(lines)
    assert "1 ticket(s) opened, 0 already open, 1 NOT filed" in written
    assert f"{SECOND}" in written and "NO TICKET: HTTP 401: Bad credentials" in written


def test_a_walk_with_no_refusal_says_nothing_about_tickets():
    # act / assert: a record that mentions tickets on a green walk is noise in the one document that
    # must be readable
    assert walk_mod.ticket_lines([]) == []


def test_the_reasons_and_the_tickets_survive_the_state_file(product):
    # arrange
    state = _refused_state(product)
    state.explain(ADDRESS, 2, "it showed two rows")
    state.file(ADDRESS, "ident-1", "https://x/5", datetime(2026, 9, 12, 11, 0, 0))

    # act
    walk_mod.save_state(walk_mod.state_path(), state)
    back = walk_mod.load_state(walk_mod.state_path())

    # assert
    assert back is not None
    assert back.reason_for(ADDRESS, 2) == "it showed two rows"
    assert back.filed(ADDRESS) == {"identity": "ident-1", "url": "https://x/5",
                                   "at": "2026-09-12 11:00:00"}


def test_nothing_to_ask_about_says_nothing(product, capsys):
    """FOUND BY DRIVING A RESUMED WALK: the header printed "0 step(s) were refused" and then asked
    nothing, on a sitting whose one refusal already carried a ticket. A heading over an empty list is a
    sentence that cannot be true."""
    # arrange
    state = _refused_state(product)

    # act
    walk_mod.ask_reasons([], state, ask=lambda prompt: pytest.fail("nobody should have been asked"))

    # assert
    assert capsys.readouterr().out == ""


def test_a_refusal_whose_ticket_is_for_an_older_version_is_asked_about_again(product):
    """The two decision points have to agree. `file_tickets` compares the IDENTITY and the first version
    of this filter looked only for a url, so a state holding a ticket from an earlier product version
    asked nobody and then opened a new ticket with no reason on it. Unreachable today - a resume across a
    version change is refused and `--restart` discards the state - which is why it would never have been
    noticed."""
    # arrange
    state = _refused_state(product)
    state.file(ADDRESS, tracker.identity("demo", "v0.9.0", ADDRESS), "https://x/1",
               datetime(2026, 9, 12, 10, 0, 0))

    # act
    owed = walk_mod.unexplained(walk_mod.refused(_taken(product), state), _key(product), state)

    # assert
    assert [one.scenario.address for one in owed] == [ADDRESS]


def test_a_refusal_whose_ticket_is_the_current_one_is_not_asked_about_again(product):
    # arrange
    state = _refused_state(product)
    key = _key(product)
    state.file(ADDRESS, tracker.identity(key.product, key.version, ADDRESS), "https://x/1",
               datetime(2026, 9, 12, 10, 0, 0))

    # act / assert: the words are in the ticket, and a second account of one event would be filed nowhere
    assert walk_mod.unexplained(walk_mod.refused(_taken(product), state), key, state) == []


def test_a_refusal_somebody_already_explained_is_not_asked_about_again(product):
    # arrange
    state = _refused_state(product)
    state.explain(ADDRESS, 2, "")

    # act / assert
    assert walk_mod.unexplained(walk_mod.refused(_taken(product), state), _key(product), state) == []


def test_a_refusal_nobody_was_asked_about_is_held_back_rather_than_filed_without_a_reason(product):
    """FOUND IN REVIEW. `ask_reasons` returns early when the person walks away, so a refusal can still be
    unasked afterwards - and a ticket opened for it reads "no reason was given", which cannot be told
    from somebody who WAS asked and declined. `unexplained` would then treat it as filed for ever, so
    their words would be lost rather than collected on the next sitting."""
    # arrange: two refusals, one explained and one nobody reached
    state = _refused_state(product)
    state.record(SECOND, 0, False, datetime(2026, 9, 12, 10, 5, 0), "Ada")
    state.explain(ADDRESS, 2, "it showed two rows")
    pending = walk_mod.refused(_taken(product), state)

    # act
    ready, owed = walk_mod.ready_to_file(pending, _key(product), state)

    # assert
    assert [one.scenario.address for one in ready] == [ADDRESS]
    assert [one.scenario.address for one in owed] == [SECOND]


def test_a_refusal_that_already_carries_a_ticket_is_still_reported_rather_than_held_back(product):
    """It is not owed a reason - its words are in the ticket - so it belongs in the ready half, or the
    record would stop saying that it is already open."""
    # arrange
    state = _refused_state(product)
    key = _key(product)
    state.file(ADDRESS, tracker.identity(key.product, key.version, ADDRESS), "https://x/1",
               datetime(2026, 9, 12, 10, 0, 0))

    # act
    ready, owed = walk_mod.ready_to_file(walk_mod.refused(_taken(product), state), key, state)

    # assert
    assert [one.scenario.address for one in ready] == [ADDRESS] and owed == []


def test_the_ticket_names_who_refused_the_step_and_not_who_is_driving_this_sitting(product, monkeypatch):
    """FOUND IN REVIEW, and it is wrong exactly where the retry path is right: `refused` reads the whole
    state, so Ada refuses on Monday, the tracker is unreachable, and Bob resumes on Wednesday from his
    own machine. With the driver taken from the current sitting, Bob's ticket said Bob."""
    # arrange
    _manifest(product, TRACKER)
    state = walk_mod.State(key=_key(product),
                           sittings=[{"started": "s", "ended": "e", "by": "Ada"},
                                     {"started": "s", "ended": "", "by": "Bob"}])
    state.record(ADDRESS, 2, False, datetime(2026, 9, 12, 10, 0, 0), "Ada")
    state.explain(ADDRESS, 2, "it showed two rows")
    sent: list[tracker.Refusal] = []
    monkeypatch.setattr(tracker, "open_ticket",
                        lambda destination, refusal: sent.append(refusal)
                        or tracker.Ticket(refusal.address, "i", "https://x/6"))

    # act
    walk_mod.file_tickets(walk_mod.refused(_taken(product), state), _key(product), state)

    # assert
    assert sent[0].by == "Ada"


def test_an_answer_with_no_author_is_a_state_this_version_cannot_fully_check(product, capsys):
    # arrange: format 2 with an answer that names no `by`
    path = walk_mod.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "format": 2, "key": _key(product).as_dict(), "sittings": [], "reasons": {}, "tickets": {},
        "answers": {"a:b": {"0": {"verdict": "ok", "at": "2026-09-12 10:00:00"}}}}), encoding="utf-8")

    # act
    back = walk_mod.load_state(path)

    # assert: a ticket naming the wrong person is worse than a walk asked again
    assert back is None
    assert "walk state" in capsys.readouterr().out
