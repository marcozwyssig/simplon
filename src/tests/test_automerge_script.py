"""si#874: the merge policy firn generates (`simplon.model.automerge`), and its script run by bash.

The script is `MERGE_SCRIPT` as committed, started by bash with a `gh` on PATH (ghstub) that answers each call
from the test's table and records it. Where the script asks gh for `--jq`, the stand-in applies the filter with
the real `jq` to the JSON the table holds, so the filters are exercised and not restated here. What the table
holds is each test's assumption about GitHub's answer; the shapes are GitHub's REST and `gh --json` fields.

One test per rule of the policy (`RULES`), each with its rc, the line that decides, and whether the script
merged (`gh pr merge`) or dispatched (`gh workflow run`).

AAA; the name states the behaviour under test.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ghstub import calls_made, gh_on_path
from simplon.model import automerge

SHA = "a" * 40
OTHER = "b" * 40
REPO = "o/n"
BRANCH = "feat"

GREEN = {"event": "pull_request", "status": "completed", "conclusion": "success"}


def _pr(number: int, head: str, base: str = "main", cross: object = False, labels=("auto-merge",)) -> dict:
    """One pull request as `gh pr list --json` gives it; `cross=None` leaves isCrossRepository out."""
    pr = {"number": number, "headRefOid": head, "baseRefName": base, "labels": [{"name": n} for n in labels]}
    if cross is not None:
        pr["isCrossRepository"] = cross
    return pr

#: The stand-in `gh`: argv joined by spaces is matched against each key of the table in order (a substring);
#: the first match answers. `rc` != 0 fails the call with `err` on stderr; otherwise `json` is printed, or the
#: `--jq` filter applied to it with the real jq (`-r`, as gh prints strings raw). An unanswered call is rc 99,
#: so a call the table did not foresee is red, never an empty answer.
FAKE_GH = r'''
import json, subprocess, sys
table = json.load(open(sys.argv[1]))
argv = sys.argv[2:]
call = " ".join(argv)
for key, answer in table:
    if key in call:
        break
else:
    sys.stderr.write("fake gh: unanswered call: " + call + "\n")
    sys.exit(99)
if answer.get("rc", 0):
    sys.stderr.write(answer.get("err", "HTTP 403: Resource not accessible by integration") + "\n")
    sys.exit(answer["rc"])
text = json.dumps(answer.get("json", ""))
if "--jq" in argv:
    done = subprocess.run(["jq", "-r", argv[argv.index("--jq") + 1]], input=text, capture_output=True, text=True)
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    sys.exit(done.returncode)
if answer.get("json") is not None:
    sys.stdout.write(text + "\n")
'''


@dataclass
class Merge:
    """One staged GitHub, and what the script did against it."""
    prs: list = field(default_factory=lambda: [_pr(7, SHA)])
    runs: dict = field(default_factory=lambda: {"ci.yml": [GREEN], "ci-test-lab.yml": []})
    labels: tuple = ("auto-merge",)
    triggers: str = "ci.yml ci-test-lab.yml"
    gates: str = "ci-test-lab.yml needs-lab"
    #: The step's DERIVED_GATES; "" stages the gate as a hand-written one, which keeps only the label rule.
    derived: str = ""
    probe_rc: int = 0
    dispatch_rc: int = 0
    merge_rc: int = 0
    unreadable: str = ""
    labeller: str = "alice"
    permission: str = "write"
    events_rc: int = 0
    permission_rc: int = 0
    #: The issue events, where a test stages them itself; None is the default timeline below.
    events: list | None = None

    def run(self, tmp_path: Path):
        table = [["pulls?state=open&per_page=1", {"rc": self.probe_rc, "json": []}],
                 ["pr list", {"json": self.prs}],
                 ["/events", {"rc": self.events_rc, "json": self.events if self.events is not None else [
                     *([{"event": "labeled", "label": {"name": "auto-merge"}, "actor": {"login": "earlier"}}]
                       if self.labeller else []),
                     {"event": "labeled", "label": {"name": "needs-lab"}, "actor": {"login": "other"}},
                     *([{"event": "labeled", "label": {"name": "auto-merge"}, "actor": {"login": self.labeller}}]
                       if self.labeller else []),
                     {"event": "commented", "actor": {"login": "someone"}}]}],
                 ["/permission", {"rc": self.permission_rc, "json": {"permission": self.permission}}]]
        for wf, runs in self.runs.items():
            answer = {"rc": 1, "err": "HTTP 502"} if wf == self.unreadable else {"json": {"workflow_runs": runs}}
            table.append([f"actions/workflows/{wf}/runs?", answer])
        table += [["pr view", {"json": {"labels": [{"name": n} for n in self.labels]}}],
                  ["pr merge", {"rc": self.merge_rc}],
                  ["workflow run", {"rc": self.dispatch_rc,
                                    "err": "HTTP 403: Resource not accessible by integration"}]]
        (tmp_path / "table.json").write_text(json.dumps(table), encoding="utf-8")
        (tmp_path / "gh.py").write_text(FAKE_GH, encoding="utf-8")
        bin_dir, calls = gh_on_path(tmp_path, f'exec "{sys.executable}" -I "{tmp_path}/gh.py" '
                                              f'"{tmp_path}/table.json" "$@"\n')
        script = tmp_path / "merge.sh"
        script.write_text(automerge.MERGE_SCRIPT, encoding="utf-8")
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}",
               "GH_TOKEN": "t", "GH_REPO": REPO, "BRANCH": BRANCH, "SHA": SHA, "CI_WORKFLOW": "ci.yml",
               "TRIGGERS": self.triggers, "GATES": self.gates, "DERIVED_GATES": self.derived}
        assert set(env) - {"PATH"} == {name for name, *_ in automerge.INPUTS}, "the stage sets every input"
        done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
        return done, calls_made(calls)


def _merged(calls: str) -> bool:
    return any(line.startswith("pr merge") for line in calls.splitlines())


def _dispatched(calls: str) -> bool:
    return any(line.startswith("workflow run") for line in calls.splitlines())


@pytest.fixture(autouse=True)
def _jq_is_on_this_machine():
    """The stand-in applies `--jq` with the real jq; without it the stand-in dies on FileNotFoundError, and every
    test would fail on that traceback instead of on what it asserts. Said once here, and red, never a skip."""
    assert shutil.which("jq"), "jq is not on PATH: the stand-in gh cannot apply the script's --jq filters"


# --- the generated data ---------------------------------------------------------------------------------------

def test_label_and_method_are_the_models():
    # assert
    assert (automerge.LABEL, automerge.METHOD) == ("auto-merge", "squash")


def test_rules_are_data_with_a_reason_and_a_source():
    # act
    keys = [key for key, _, _ in automerge.RULES]

    # assert: netctl's rules, then the two si#874 decided on top, each with its reason and the ticket behind it
    assert keys == ["token-scope", "labelled-pr", "head-is-sha", "cross-repository", "labeller-can-merge",
                    "trigger-runs-green",
                    "ci-run-exists", "derived-gate-ran", "gate-label-needs-run", "squash-merge",
                    "dispatch-ci-on-base"]
    assert all(reason and re.match(r"(netctl|si)#\d+\b", source)
               for _, reason, source in automerge.RULES), automerge.RULES


def test_every_rule_is_commented_in_the_script_with_its_reason_and_source():
    # assert
    for key, reason, source in automerge.RULES:
        assert f"# {key} ({source}): {reason}" in automerge.MERGE_SCRIPT, key


def test_the_script_is_strict_bash_and_takes_label_and_method_from_the_model():
    # assert
    assert automerge.MERGE_SCRIPT.startswith("set -euo pipefail\n")
    assert f'select(any(.labels[]; .name == "{automerge.LABEL}"))' in automerge.MERGE_SCRIPT
    assert f'--{automerge.METHOD} --delete-branch --match-head-commit "$SHA"' in automerge.MERGE_SCRIPT


def test_the_script_never_turns_a_failed_read_into_an_empty_one():
    # assert: `|| echo '[]'` is how netctl's lab read made a missing verdict a green one
    assert "|| echo" not in automerge.MERGE_SCRIPT
    assert "2>/dev/null" not in automerge.MERGE_SCRIPT


# --- token-scope ----------------------------------------------------------------------------------------------

def test_token_without_pull_request_read_is_red(tmp_path):
    # act
    done, calls = Merge(probe_rc=1).run(tmp_path)

    # assert
    assert done.returncode == 1, done.stdout + done.stderr
    assert "token scope problem, NOT 'nothing to merge'" in done.stderr
    assert calls.splitlines() == [f"api repos/{REPO}/pulls?state=open&per_page=1"]


# --- labelled-pr ----------------------------------------------------------------------------------------------

def test_no_labelled_pr_is_a_green_no_op(tmp_path):
    # act
    done, calls = Merge(prs=[]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"No open PR labelled auto-merge for branch '{BRANCH}'; nothing to do." in done.stdout
    assert (_merged(calls), _dispatched(calls)) == (False, False)
    assert f"pr list --head {BRANCH} --state open --json" in calls


def test_the_listing_leaves_the_label_to_jq_not_to_github_search(tmp_path):
    """`gh pr list --label` goes through GitHub's search API (`GH_DEBUG=api` shows a `search(q: ... label:...)`
    query), whose index lags a label change: a PR labelled just before its run completes would not be listed yet."""
    # act
    _, calls = Merge().run(tmp_path)

    # assert
    listing = next(line for line in calls.splitlines() if line.startswith("pr list"))
    assert "--label" not in listing and "--search" not in listing
    assert "labels" in listing


def test_a_pr_carrying_the_label_among_others_is_found(tmp_path):
    # act
    done, calls = Merge(prs=[_pr(7, SHA, labels=("needs-lab", "auto-merge", "docs"))]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


def test_a_pr_without_the_label_is_not_found(tmp_path):
    # act
    done, calls = Merge(prs=[_pr(7, SHA, labels=("needs-lab", "auto-merge-later"))]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "nothing to do" in done.stdout
    assert not _merged(calls) and "actions/workflows" not in calls


def test_already_merged_is_a_no_op(tmp_path):
    """Review focus 3: CI and a gate completing together for one SHA queue; the second finds the PR merged, and
    a merged PR is not open, so the list is empty."""
    # act
    done, calls = Merge(prs=[]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "nothing to do" in done.stdout
    assert not _merged(calls) and "actions/workflows" not in calls


# --- head-is-sha ----------------------------------------------------------------------------------------------

def test_head_moved_does_not_merge(tmp_path):
    # act
    done, calls = Merge(prs=[_pr(7, OTHER)]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "moved on" in done.stdout and SHA in done.stdout
    assert not _merged(calls)


def test_selects_the_pr_whose_head_is_the_sha(tmp_path):
    """Review focus 5: a fork's PR with the same branch name is listed too; only the one at the SHA merges."""
    # act
    done, calls = Merge(prs=[_pr(5, OTHER, cross=True), _pr(9, SHA, base="dev")]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"pr merge 9 --squash --delete-branch --match-head-commit {SHA}" in calls.splitlines()
    assert "pr merge 5" not in calls
    assert "into 'dev'" in done.stdout


# --- cross-repository -----------------------------------------------------------------------------------------

def test_a_fork_pr_at_the_sha_is_not_merged(tmp_path):
    """si#874 security review: a fork's pull_request runs use the fork's own workflow files."""
    # act
    done, calls = Merge(prs=[_pr(7, SHA, cross=True)]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert ("PR #7 comes from a fork: a fork's runs use the fork's own workflow files; merge it by hand."
            in done.stdout)
    assert (_merged(calls), _dispatched(calls)) == (False, False)
    assert "isCrossRepository" in calls


def test_a_pr_whose_origin_is_unknown_is_red(tmp_path):
    # act
    done, calls = Merge(prs=[_pr(7, SHA, cross=None)]).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "could not tell whether PR #7 comes from a fork" in done.stderr
    assert not _merged(calls)


# --- labeller-can-merge ---------------------------------------------------------------------------------------

def test_a_label_added_by_someone_who_may_not_merge_does_not_merge(tmp_path):
    """si#874 security review: a triage-role user can add the label and may not merge."""
    # act
    done, calls = Merge(labeller="trudy", permission="read").run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "trudy added the label auto-merge to PR #7 last" in done.stdout and "read" in done.stdout
    assert (_merged(calls), _dispatched(calls)) == (False, False)
    assert f"api repos/{REPO}/collaborators/trudy/permission" in calls


@pytest.mark.parametrize("permission", ["write", "maintain", "admin"])
def test_a_label_added_by_someone_who_may_merge_merges(tmp_path, permission):
    # act
    done, calls = Merge(labeller="alice", permission=permission).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)
    assert f"api repos/{REPO}/collaborators/alice/permission" in calls
    assert "collaborators/earlier" not in calls


def test_a_label_last_removed_is_red(tmp_path):
    """The PR is listed with the label, and its last event for the label is `unlabeled`: an inconsistent timeline."""
    # act
    done, calls = Merge(events=[
        {"event": "labeled", "label": {"name": "auto-merge"}, "actor": {"login": "alice"}},
        {"event": "unlabeled", "label": {"name": "auto-merge"}, "actor": {"login": "alice"}}]).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "unlabeled" in done.stderr and "no verdict" in done.stderr
    assert not _merged(calls) and "/permission" not in calls


def test_a_labeller_with_no_login_is_red(tmp_path):
    # act
    done, calls = Merge(events=[
        {"event": "labeled", "label": {"name": "auto-merge"}, "actor": None}]).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "no login" in done.stderr and "bot or a deleted account" in done.stderr
    assert not _merged(calls) and "/permission" not in calls


@pytest.mark.parametrize("failing", ["events_rc", "permission_rc"])
def test_a_failed_read_of_who_labelled_is_red(tmp_path, failing):
    # act
    done, calls = Merge(**{failing: 1}).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "no verdict" in done.stderr
    assert not _merged(calls)


def test_a_label_with_no_labeled_event_is_red(tmp_path):
    # act
    done, calls = Merge(labeller="").run(tmp_path)

    # assert: no labeled event for the label is found; a label nobody added is no verdict
    assert done.returncode == 1
    assert "no verdict" in done.stderr
    assert not _merged(calls)


# --- ci-run-exists --------------------------------------------------------------------------------------------

def test_a_gate_run_without_any_ci_run_does_not_merge(tmp_path):
    """Rule 4 covers CI: a green gate run alone is no verdict on the unit levels."""
    # act
    done, calls = Merge(runs={"ci.yml": [], "ci-test-lab.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"No run of ci.yml for {SHA}" in done.stdout
    assert not _merged(calls)


# --- trigger-runs-green ---------------------------------------------------------------------------------------

RUNNING = {"event": "pull_request", "status": "in_progress", "conclusion": None}


@pytest.mark.parametrize(("runs", "said"), [
    ({"ci.yml": [GREEN], "ci-test-lab.yml": [RUNNING]},
     "A run of ci-test-lab.yml for {sha} is still running; not merging PR #7.\n"
     "This is reconsidered when it completes: ci-test-lab.yml is a trigger of this workflow."),
    ({"ci.yml": [GREEN, {"event": "workflow_dispatch", "status": "completed", "conclusion": "failure"}],
      "ci-test-lab.yml": []},
     "A run of ci.yml for {sha} completed without success; not merging PR #7.\n"
     "Re-run that run (a re-run replaces its conclusion) or push a new commit."),
    ({"ci.yml": [GREEN, {"event": "pull_request", "status": "completed", "conclusion": "cancelled"}, RUNNING],
      "ci-test-lab.yml": []},
     "A run of ci.yml for {sha} completed without success; not merging PR #7.\n"
     "Re-run that run (a re-run replaces its conclusion) or push a new commit."),
], ids=["gate-running", "ci-red", "ci-cancelled-beside-running"])
def test_red_or_running_trigger_run_blocks(tmp_path, runs, said):
    """A run still going is reconsidered on its own; a red or cancelled one never is, so it says what would."""
    # act
    done, calls = Merge(runs=runs).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert said.format(sha=SHA) in done.stdout
    assert not _merged(calls)


def test_schedule_runs_are_ignored(tmp_path):
    # arrange
    nightly = {"event": "schedule", "status": "completed", "conclusion": "failure"}

    # act
    done, calls = Merge(runs={"ci.yml": [GREEN], "ci-test-lab.yml": [nightly]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


def test_a_failed_run_read_is_red_not_green(tmp_path):
    # act
    done, calls = Merge(unreadable="ci-test-lab.yml").run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "could not read the runs of ci-test-lab.yml" in done.stderr
    assert not _merged(calls)


def test_every_trigger_is_read_for_the_sha(tmp_path):
    # act
    _, calls = Merge().run(tmp_path)

    # assert
    for wf in ("ci.yml", "ci-test-lab.yml"):
        assert f"api repos/{REPO}/actions/workflows/{wf}/runs?head_sha={SHA}&per_page=100" in calls


# --- gate-label-needs-run -------------------------------------------------------------------------------------

def test_gate_label_without_gate_run_blocks(tmp_path):
    """Review focus 4: a PR carrying the gate's label with no run of that gate for the SHA does not merge."""
    # act
    done, calls = Merge(labels=("auto-merge", "needs-lab")).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"carries needs-lab and no run of ci-test-lab.yml exists for {SHA}" in done.stdout
    assert f"gh workflow run ci-test-lab.yml --ref {BRANCH}" in done.stdout
    assert not _merged(calls)


def test_gate_label_with_green_gate_run_merges(tmp_path):
    """Review focus 4: a gate whose decide job said skip still ends its run successfully; that counts green."""
    # act
    done, calls = Merge(labels=("auto-merge", "needs-lab"),
                           runs={"ci.yml": [GREEN], "ci-test-lab.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


# --- derived-gate-ran -----------------------------------------------------------------------------------------

def test_a_derived_gate_with_no_run_for_the_sha_does_not_merge(tmp_path):
    """A stacked parent: its child merged into it and rule dispatch-ci-on-base dispatched CI there, so CI is green
    for the new head while the derived gate never ran on that tree. "No run" is not green."""
    # act
    done, calls = Merge(derived="ci-test-lab.yml", runs={"ci.yml": [GREEN], "ci-test-lab.yml": []}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"No run of the gate workflow ci-test-lab.yml for {SHA}" in done.stdout
    assert f"gh workflow run ci-test-lab.yml --ref {BRANCH}" in done.stdout
    assert not _merged(calls)


def test_a_derived_gate_whose_only_run_is_a_schedule_does_not_merge(tmp_path):
    # act
    done, calls = Merge(derived="ci-test-lab.yml", runs={
        "ci.yml": [GREEN], "ci-test-lab.yml": [{"event": "schedule", "status": "completed",
                                                "conclusion": "success"}]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "No run of the gate workflow ci-test-lab.yml" in done.stdout
    assert not _merged(calls)


def test_a_derived_gate_with_a_green_run_merges(tmp_path):
    """Its decide job runs on every pull request event, so a normal pull request always has one, skip or not."""
    # act
    done, calls = Merge(derived="ci-test-lab.yml", runs={"ci.yml": [GREEN], "ci-test-lab.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


def test_a_handwritten_gate_with_no_run_and_no_label_merges(tmp_path):
    """A hand-written gate (netctl's lab.yml runs on its label or a schedule only) keeps the label rule alone."""
    # act
    done, calls = Merge(derived="", runs={"ci.yml": [GREEN], "ci-test-lab.yml": []}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


def test_a_derived_gate_not_among_the_triggers_is_red(tmp_path):
    # act
    done, calls = Merge(gates="", derived="ci-test-lab.yml", triggers="ci.yml").run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "ci-test-lab.yml is not among TRIGGERS (ci.yml)" in done.stderr
    assert calls == ""


def test_a_gate_not_among_the_triggers_is_red(tmp_path):
    """Checked before any gh call, whatever the PR carries: a wiring defect is not a property of one PR."""
    # act
    done, calls = Merge(labels=("auto-merge",), triggers="ci.yml").run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "ci-test-lab.yml is not among TRIGGERS (ci.yml)" in done.stderr
    assert calls == ""


@pytest.mark.parametrize("ci_runs", [[GREEN], [{"event": "push", "status": "completed", "conclusion": "failure"}]],
                         ids=["ci-green", "a-trigger-red"])
def test_ci_workflow_not_among_the_triggers_is_red(tmp_path, ci_runs):
    """A red trigger run must not hide the wiring defect behind a green no-op."""
    # act
    done, calls = Merge(triggers="ci-test-lab.yml",
                           runs={"ci.yml": ci_runs, "ci-test-lab.yml": [ci_runs[0]]}).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "ci.yml is not among TRIGGERS (ci-test-lab.yml)" in done.stderr
    assert calls == ""


def test_no_gates_reads_no_labels(tmp_path):
    # act
    done, calls = Merge(gates="", triggers="ci.yml", runs={"ci.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "pr view" not in calls
    assert _merged(calls)


# --- squash-merge and dispatch-ci-on-base ---------------------------------------------------------------------

def test_green_merges_and_dispatches_ci_on_base(tmp_path):
    # act
    done, calls = Merge().run(tmp_path)

    # assert: the base came from the list read before the merge; the dispatch follows the merge
    assert done.returncode == 0, done.stdout + done.stderr
    lines = calls.splitlines()
    merge = lines.index(f"pr merge 7 --squash --delete-branch --match-head-commit {SHA}")
    dispatch = lines.index("workflow run ci.yml --ref main")
    assert merge < dispatch == len(lines) - 1


def test_failed_dispatch_is_red_after_merge(tmp_path):
    # act
    done, calls = Merge(dispatch_rc=1).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "MERGED" in done.stderr and "UNVERIFIED" in done.stderr
    assert "gh workflow run ci.yml --ref main" in done.stderr
    assert _merged(calls)


def test_a_failed_merge_is_red_and_dispatches_nothing(tmp_path):
    # act
    done, calls = Merge(merge_rc=1).run(tmp_path)

    # assert
    assert done.returncode != 0
    assert not _dispatched(calls)


# --- the inputs -----------------------------------------------------------------------------------------------

def test_the_inputs_name_no_label_event():
    """si#874, Marco 2026-11-25: no `pull_request_target` trigger, so neither the event's name nor its sender."""
    # assert
    assert {name for name, *_ in automerge.INPUTS}.isdisjoint({"EVENT", "LABELLER"})
    assert "pull_request_target" not in automerge.MERGE_SCRIPT and "pull_request_target" not in automerge.CONDITION


def test_inputs_are_data_with_a_source_and_a_meaning():
    # assert: each input comes from a GitHub expression or from the derivation, never both, never neither
    assert [name for name, *_ in automerge.INPUTS][:1] == ["GH_TOKEN"]
    for name, expression, source, meaning, _ in automerge.INPUTS:
        assert bool(expression) != bool(source), name
        assert meaning, name
    assert "GITHUB_OUTPUT" not in {name for name, *_ in automerge.INPUTS}


def test_the_script_header_names_every_input_with_its_meaning():
    # assert
    for name, _, _, meaning, required in automerge.INPUTS:
        assert f"#   {name}{' (required)' if required else ''}: {meaning}" in automerge.MERGE_SCRIPT, name


@pytest.mark.parametrize("name", [name for name, *_, required in automerge.INPUTS if required])
def test_a_missing_input_is_red_naming_it(tmp_path, name):
    # arrange: a gh that fails every call, so the real one is never reached
    bin_dir, calls = gh_on_path(tmp_path, "exit 98\n")
    script = tmp_path / "merge.sh"
    script.write_text(automerge.MERGE_SCRIPT, encoding="utf-8")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_REPO": REPO, "BRANCH": BRANCH, "SHA": SHA, "CI_WORKFLOW": "ci.yml",
           "TRIGGERS": "ci.yml", "GATES": "", name: ""}

    # act
    done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)

    # assert
    assert done.returncode == 1
    assert name in done.stderr
    assert calls_made(calls) == ""
