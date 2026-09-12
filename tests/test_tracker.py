"""A refused acceptance step becomes a bug ticket on the product's tracker (si#206).

What is here is the tracker itself: the product's declaration, the identity that makes a second ticket
impossible, the evidence a ticket carries, and every way `gh` can let the kernel down. The half that
belongs to the walk - which refusals are collected, when the state is written relative to the network,
and what the record says afterwards - is in `test_walk.py`, beside the rest of the walk.

`gh` is never really run: `simplon.run.run` is replaced with a recorder, so what is measured is the argv
the kernel builds and the decision it takes on an answer, both of which are the thing that can be wrong.
The one claim a fake cannot support - that a real GitHub answers these argv the way the fake does - was
driven by hand against a real repository and written into the PR rather than asserted here.

AAA throughout.
"""
import json

import pytest

from simplon import context, run, tracker
from simplon.context import ProductContext


# --- the harness ------------------------------------------------------------------------------------


def _register(monkeypatch, tmp_path, document: dict) -> None:
    """Write `document` as a real manifest and make it the current product for ONE test.

    `monkeypatch.setattr` on the module global rather than `context.set_current`, for the reason
    `test_manifest_top_level._register` states: a real setter would decide the current product for every
    test module that runs after this one in the same process.
    """
    path = tmp_path / "sample.yaml"
    path.write_text(json.dumps(document), encoding="utf-8")   # JSON is YAML, and needs no dumper
    monkeypatch.setattr(context, "_current", ProductContext("sample", tmp_path, path))


SECTION = {"kind": "github", "repo": "acme/widget", "labels": ["bug", "acceptance"],
           "title": "Acceptance refused: {scenario}", "preamble": "A customer said no."}


def _refusal(**over) -> tracker.Refusal:
    fields = dict(address="tests/acceptance/gate.feature:The gate runs everything",
                  feature="One verdict", scenario="The gate runs everything",
                  step="Then it reports three steps", step_number=3, step_total=4,
                  said="it reported two, and the third row was blank",
                  at="2026-09-12 14:00:00", by="Marco <m@example.com>", product="widget",
                  version="v0.9.0-3-gdeadbee", revision="deadbeef", source="tests/acceptance",
                  selection="@gate")
    fields.update(over)
    return tracker.Refusal(**fields)


class _Recorder:
    """A stand-in for `run.run` that answers by argv prefix and keeps every call."""

    def __init__(self, *answers: tuple[str, run.Result]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs = kwargs
        joined = " ".join(argv)
        for needle, result in self.answers:
            if needle in joined:
                return result
        return run.Result(rc=0, out="", err="")


def _ok(out: str = "") -> run.Result:
    return run.Result(rc=0, out=out, err="")


def _bad(err: str) -> run.Result:
    return run.Result(rc=1, out="", err=err)


@pytest.fixture
def gh(monkeypatch):
    """`gh` is on the PATH for every test that does not say otherwise."""
    monkeypatch.setattr(tracker.shutil, "which", lambda tool: f"/usr/bin/{tool}")


# --- the product's declaration ------------------------------------------------------------------------

def test_a_product_that_declares_no_tracker_is_told_so_by_name(monkeypatch, tmp_path, capsys):
    # arrange: a manifest with everything but the section
    _register(monkeypatch, tmp_path, {"groups": {}})

    # act
    declared = tracker.declared()

    # assert
    assert declared is None
    assert "tracker" in capsys.readouterr().err


def test_a_mistyped_section_is_not_read_as_an_opt_out(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"trackre": SECTION})

    # act
    declared = tracker.declared()

    # assert: the reader names the key it wanted, so `trackre:` is not silently "no tracker"
    assert declared is None
    assert "tracker" in capsys.readouterr().err


def test_a_declaration_without_a_title_is_refused_naming_the_key(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"tracker": {"kind": "github", "repo": "acme/widget"}})

    # act
    declared = tracker.declared()

    # assert: the kernel will not word a product's bug for it
    assert declared is None
    assert "title" in capsys.readouterr().err


def test_an_unknown_kind_is_refused_naming_the_kinds_that_exist(monkeypatch, tmp_path, capsys):
    # arrange
    _register(monkeypatch, tmp_path, {"tracker": {**SECTION, "kind": "jira"}})

    # act
    declared = tracker.declared()

    # assert
    said = capsys.readouterr().err
    assert declared is None
    assert "jira" in said and tracker.KIND_GITHUB in said


def test_the_kind_defaults_to_github_and_the_rest_is_carried_verbatim(monkeypatch, tmp_path):
    # arrange: no `kind:`
    _register(monkeypatch, tmp_path, {"tracker": {k: v for k, v in SECTION.items() if k != "kind"}})

    # act
    declared = tracker.declared()

    # assert
    assert declared == tracker.Destination(
        kind=tracker.KIND_GITHUB, repo="acme/widget", labels=("bug", "acceptance"),
        title="Acceptance refused: {scenario}", preamble="A customer said no.")


# --- the identity -----------------------------------------------------------------------------------

def test_the_identity_is_the_same_for_the_same_scenario_at_the_same_version():
    # arrange / act
    first = tracker.identity("widget", "v1.0.0", "a.feature:One")
    second = tracker.identity("widget", "v1.0.0", "a.feature:One")

    # assert
    assert first == second


@pytest.mark.parametrize("product,version,address", [
    ("other", "v1.0.0", "a.feature:One"),
    ("widget", "v1.0.1", "a.feature:One"),
    ("widget", "v1.0.0", "a.feature:Two"),
])
def test_the_identity_moves_with_each_of_its_three_parts(product, version, address):
    # arrange
    base = tracker.identity("widget", "v1.0.0", "a.feature:One")

    # act
    moved = tracker.identity(product, version, address)

    # assert: one ticket per scenario per version, so all three have to separate
    assert moved != base


def test_the_three_parts_cannot_be_slid_across_each_other():
    # arrange: `wid` + `get` against `widget` + `` - the classic concatenation collision, and the reason
    # the parts are joined by a byte that cannot occur in any of them rather than by nothing at all
    left = tracker.identity("wid", "get", "a.feature:One")

    # act
    right = tracker.identity("widget", "", "a.feature:One")

    # assert
    assert left != right


# --- what the ticket says --------------------------------------------------------------------------

def test_the_body_carries_the_identity_so_the_lookup_can_find_it():
    # arrange
    refusal = _refusal()
    ident = tracker.identity(refusal.product, refusal.version, refusal.address)

    # act
    body = tracker.body_for(tracker.Destination(tracker.KIND_GITHUB, "", (), "t", ""), refusal, ident)

    # assert
    assert tracker.marker_line(ident) in body


def test_the_body_carries_the_evidence_a_ticket_is_worth_opening_for():
    # arrange
    refusal = _refusal()
    dest = tracker.Destination(tracker.KIND_GITHUB, "", (), "t", "The product's own words.")

    # act
    body = tracker.body_for(dest, refusal, "x")

    # assert: which scenario, which step, the version and provenance, when, who, and what was said
    for evidence in (refusal.address, refusal.step, "3 of 4", refusal.version, refusal.revision,
                     refusal.at, refusal.by, refusal.said, refusal.source, refusal.selection,
                     "The product's own words."):
        assert evidence in body


def test_a_refusal_nobody_explained_says_so_rather_than_reading_as_no_comment():
    # arrange
    refusal = _refusal(said="")

    # act
    body = tracker.body_for(tracker.Destination(tracker.KIND_GITHUB, "", (), "t", ""), refusal, "x")

    # assert
    assert "no reason was given" in body


def test_the_title_is_the_products_own_wording_with_the_refusal_filled_in():
    # arrange
    dest = tracker.Destination(tracker.KIND_GITHUB, "", (), "{product} {version}: {scenario}", "")

    # act
    title = tracker.title_for(dest, _refusal())

    # assert
    assert title == "widget v0.9.0-3-gdeadbee: The gate runs everything"


def test_a_title_naming_a_field_that_does_not_exist_is_refused_naming_the_ones_that_do():
    # arrange
    dest = tracker.Destination(tracker.KIND_GITHUB, "", (), "{sceanrio}", "")

    # act / assert
    with pytest.raises(KeyError) as raised:
        tracker.title_for(dest, _refusal())
    assert "scenario" in str(raised.value)


# --- reaching the tracker ------------------------------------------------------------------------------

def test_an_existing_ticket_is_found_and_no_second_one_is_opened(monkeypatch, gh):
    # arrange: the search answers with a ticket whose body carries this very identity
    refusal = _refusal()
    ident = tracker.identity(refusal.product, refusal.version, refusal.address)
    listing = json.dumps([{"number": 7, "url": "https://x/7", "body": tracker.marker_line(ident)}])
    recorder = _Recorder(("issue list", _ok(listing)))
    monkeypatch.setattr(run, "run", recorder)

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 refusal)

    # assert
    assert ticket.existed and ticket.url == "https://x/7" and not ticket.problem
    assert not any("issue create" in " ".join(call) for call in recorder.calls)


def test_a_ticket_the_search_returned_that_does_not_carry_the_identity_is_not_it(monkeypatch, gh):
    # arrange: GitHub's search is fuzzy, so the exact match is made here rather than trusted there
    listing = json.dumps([{"number": 7, "url": "https://x/7", "body": "an unrelated bug"}])
    recorder = _Recorder(("issue list", _ok(listing)),
                         ("issue create", _ok("https://x/8\n")))
    monkeypatch.setattr(run, "run", recorder)

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert
    assert not ticket.existed and ticket.url == "https://x/8"


def test_a_ticket_is_opened_with_the_products_labels_and_repository(monkeypatch, gh):
    # arrange
    recorder = _Recorder(("issue list", _ok("[]")), ("issue create", _ok("https://x/9\n")))
    monkeypatch.setattr(run, "run", recorder)
    dest = tracker.Destination(tracker.KIND_GITHUB, "acme/widget", ("bug", "acceptance"),
                               "Refused: {scenario}", "")

    # act
    ticket = tracker.open_ticket(dest, _refusal())

    # assert
    created = next(call for call in recorder.calls if "create" in call)
    assert ticket.url == "https://x/9"
    assert created[:3] == ["gh", "issue", "create"]
    assert "--repo" in created and "acme/widget" in created
    assert created.count("--label") == 2
    assert "Refused: The gate runs everything" in created


def test_a_tracker_that_cannot_be_reached_loses_no_refusal_and_says_what_failed(monkeypatch, gh):
    # arrange: the search itself fails - a wrong token, an unreachable host
    recorder = _Recorder(("issue list", _bad("HTTP 401: Bad credentials")))
    monkeypatch.setattr(run, "run", recorder)

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert: no url, a problem in the person's own words, and nothing raised
    assert not ticket.url and "401" in ticket.problem
    assert not any("create" in call for call in recorder.calls), (
        "a lookup that failed is not a lookup that found nothing - creating here is how a broken search "
        "opens a second ticket every run")


def test_a_creation_that_fails_is_a_problem_and_not_an_exception(monkeypatch, gh):
    # arrange
    recorder = _Recorder(("issue list", _ok("[]")), ("issue create", _bad("could not add label: 'bug'")))
    monkeypatch.setattr(run, "run", recorder)

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert
    assert not ticket.url and "label" in ticket.problem


def test_a_host_without_gh_is_told_which_tool_is_missing(monkeypatch):
    # arrange
    monkeypatch.setattr(tracker.shutil, "which", lambda tool: None)

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert
    assert not ticket.url and "gh" in ticket.problem


def test_a_search_answer_that_is_not_json_is_a_problem_rather_than_a_traceback(monkeypatch, gh):
    # arrange
    monkeypatch.setattr(run, "run", _Recorder(("issue list", _ok("not json at all"))))

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert
    assert not ticket.url and ticket.problem


def test_a_title_the_product_mis_spelled_is_a_problem_on_the_ticket_and_not_a_crash(monkeypatch, gh):
    # arrange
    monkeypatch.setattr(run, "run", _Recorder(("issue list", _ok("[]"))))
    dest = tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "{sceanrio}", "")

    # act
    ticket = tracker.open_ticket(dest, _refusal())

    # assert: the walk goes on and the record says why the ticket is missing
    assert not ticket.url and "sceanrio" in ticket.problem


def test_a_multi_line_complaint_from_gh_is_folded_onto_one_line(monkeypatch, gh):
    """FOUND BY DRIVING A WRONG TOKEN. `gh` answers `HTTP 401: Bad credentials (...)` and then `Try
    authenticating with: gh auth login` on a second line, and that newline landed in the walk's record,
    where the header is a label column - the second line hung outside it and read as a line of the
    transcript rather than as part of the reason."""
    # arrange
    monkeypatch.setattr(run, "run", _Recorder(
        ("issue list", _bad("HTTP 401: Bad credentials (https://api.github.com/graphql)\n"
                            "Try authenticating with:  gh auth login"))))

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert
    assert "\n" not in ticket.problem
    assert "401" in ticket.problem and "gh auth login" in ticket.problem


def test_a_gh_that_said_nothing_at_all_still_names_the_exit_code(monkeypatch, gh):
    # arrange: a tool that fails silently is the case where "no problem text" would read as no problem
    monkeypatch.setattr(run, "run", _Recorder(("issue list", run.Result(rc=7, out="", err=""))))

    # act
    ticket = tracker.open_ticket(tracker.Destination(tracker.KIND_GITHUB, "acme/widget", (), "t", ""),
                                 _refusal())

    # assert
    assert "7" in ticket.problem
