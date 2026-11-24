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
    prs: list = field(default_factory=lambda: [{"number": 7, "headRefOid": SHA, "baseRefName": "main", "isCrossRepository": False}])
    runs: dict = field(default_factory=lambda: {"ci.yml": [GREEN], "ci-test-lab.yml": []})
    labels: tuple = ("auto-merge",)
    event: str = "workflow_run"
    triggers: str = "ci.yml ci-test-lab.yml"
    gates: str = "ci-test-lab.yml needs-lab"
    probe_rc: int = 0
    dispatch_rc: int = 0
    merge_rc: int = 0
    unreadable: str = ""

    def run(self, tmp_path: Path):
        table = [["pulls?state=open&per_page=1", {"rc": self.probe_rc, "json": []}],
                 ["pr list", {"json": self.prs}]]
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
        output = tmp_path / "output.txt"
        output.write_text("", encoding="utf-8")
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(output),
               "GH_TOKEN": "t", "GH_REPO": REPO, "BRANCH": BRANCH, "SHA": SHA, "CI_WORKFLOW": "ci.yml",
               "TRIGGERS": self.triggers, "GATES": self.gates, "EVENT": self.event}
        done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
        outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)
        return done, calls_made(calls), outputs


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
    assert keys == ["token-scope", "labelled-pr", "head-is-sha", "cross-repository", "label-triggers",
                    "trigger-runs-green",
                    "ci-run-exists", "gate-label-needs-run", "squash-merge", "dispatch-ci-on-base"]
    assert all(reason and re.match(r"(netctl|si)#\d+\b", source)
               for _, reason, source in automerge.RULES), automerge.RULES


def test_every_rule_is_commented_in_the_script_with_its_reason_and_source():
    # assert
    for key, reason, source in automerge.RULES:
        assert f"# {key} ({source}): {reason}" in automerge.MERGE_SCRIPT, key


def test_the_script_is_strict_bash_and_takes_label_and_method_from_the_model():
    # assert
    assert automerge.MERGE_SCRIPT.startswith("set -euo pipefail\n")
    assert f'--label "{automerge.LABEL}"' in automerge.MERGE_SCRIPT
    assert f'--{automerge.METHOD} --delete-branch --match-head-commit "$SHA"' in automerge.MERGE_SCRIPT


def test_the_script_never_turns_a_failed_read_into_an_empty_one():
    # assert: `|| echo '[]'` is how netctl's lab read made a missing verdict a green one
    assert "|| echo" not in automerge.MERGE_SCRIPT
    assert "2>/dev/null" not in automerge.MERGE_SCRIPT


# --- token-scope ----------------------------------------------------------------------------------------------

def test_token_without_pull_request_read_is_red(tmp_path):
    # act
    done, calls, _ = Merge(probe_rc=1).run(tmp_path)

    # assert
    assert done.returncode == 1, done.stdout + done.stderr
    assert "token scope problem, NOT 'nothing to merge'" in done.stderr
    assert calls.splitlines() == [f"api repos/{REPO}/pulls?state=open&per_page=1"]


# --- labelled-pr ----------------------------------------------------------------------------------------------

def test_no_labelled_pr_is_a_green_no_op(tmp_path):
    # act
    done, calls, outputs = Merge(prs=[]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"No open PR labelled auto-merge for branch '{BRANCH}'; nothing to do." in done.stdout
    assert (_merged(calls), _dispatched(calls), outputs) == (False, False, {})
    assert f"pr list --head {BRANCH} --state open --label auto-merge" in calls


def test_already_merged_is_a_no_op(tmp_path):
    """Review focus 3: CI and a gate completing together for one SHA queue; the second finds the PR merged, and
    a merged PR is not open, so the list is empty."""
    # act
    done, calls, _ = Merge(prs=[]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "nothing to do" in done.stdout
    assert not _merged(calls) and "actions/workflows" not in calls


# --- head-is-sha ----------------------------------------------------------------------------------------------

def test_head_moved_does_not_merge(tmp_path):
    # act
    done, calls, _ = Merge(prs=[{"number": 7, "headRefOid": OTHER, "baseRefName": "main", "isCrossRepository": False}]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "moved on" in done.stdout and SHA in done.stdout
    assert not _merged(calls)


def test_selects_the_pr_whose_head_is_the_sha(tmp_path):
    """Review focus 5: a fork's PR with the same branch name is listed too; only the one at the SHA merges."""
    # act
    done, calls, outputs = Merge(prs=[{"number": 5, "headRefOid": OTHER, "baseRefName": "main", "isCrossRepository": True},
                                      {"number": 9, "headRefOid": SHA, "baseRefName": "dev",
                                       "isCrossRepository": False}]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"pr merge 9 --squash --delete-branch --match-head-commit {SHA}" in calls.splitlines()
    assert "pr merge 5" not in calls
    assert outputs == {"merged_pr": "9", "base": "dev"}


# --- cross-repository -----------------------------------------------------------------------------------------

def test_a_fork_pr_at_the_sha_is_not_merged(tmp_path):
    """si#874 security review: a fork's pull_request runs use the fork's own workflow files."""
    # act
    done, calls, outputs = Merge(prs=[{"number": 7, "headRefOid": SHA, "baseRefName": "main",
                                       "isCrossRepository": True}]).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert ("PR #7 comes from a fork: a fork's runs use the fork's own workflow files; merge it by hand."
            in done.stdout)
    assert (_merged(calls), _dispatched(calls), outputs) == (False, False, {})
    assert "isCrossRepository" in calls


def test_a_pr_whose_origin_is_unknown_is_red(tmp_path):
    # act
    done, calls, _ = Merge(prs=[{"number": 7, "headRefOid": SHA, "baseRefName": "main"}]).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "could not tell whether PR #7 comes from a fork" in done.stderr
    assert not _merged(calls)


# --- label-triggers and ci-run-exists -------------------------------------------------------------------------

def test_label_event_needs_a_ci_run_for_the_sha(tmp_path):
    """Review focus 2: the label added with no CI run for the head SHA does not merge, and says why."""
    # act
    done, calls, _ = Merge(event="pull_request_target", runs={"ci.yml": [], "ci-test-lab.yml": []}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"No run of ci.yml for {SHA}" in done.stdout
    assert not _merged(calls)


def test_label_event_with_a_green_ci_run_merges(tmp_path):
    # act
    done, calls, _ = Merge(event="pull_request_target").run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "label" in done.stdout
    assert _merged(calls)


def test_a_gate_run_without_any_ci_run_does_not_merge(tmp_path):
    """Rule 4 covers CI: a green gate run alone is no verdict on the unit levels."""
    # act
    done, calls, _ = Merge(runs={"ci.yml": [], "ci-test-lab.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"No run of ci.yml for {SHA}" in done.stdout
    assert not _merged(calls)


def test_an_unknown_event_is_red(tmp_path):
    # act
    done, calls, _ = Merge(event="push").run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "EVENT" in done.stderr and "push" in done.stderr
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
    done, calls, _ = Merge(runs=runs).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert said.format(sha=SHA) in done.stdout
    assert not _merged(calls)


def test_schedule_runs_are_ignored(tmp_path):
    # arrange
    nightly = {"event": "schedule", "status": "completed", "conclusion": "failure"}

    # act
    done, calls, _ = Merge(runs={"ci.yml": [GREEN], "ci-test-lab.yml": [nightly]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


def test_a_failed_run_read_is_red_not_green(tmp_path):
    # act
    done, calls, _ = Merge(unreadable="ci-test-lab.yml").run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "could not read the runs of ci-test-lab.yml" in done.stderr
    assert not _merged(calls)


def test_every_trigger_is_read_for_the_sha(tmp_path):
    # act
    _, calls, _ = Merge().run(tmp_path)

    # assert
    for wf in ("ci.yml", "ci-test-lab.yml"):
        assert f"api repos/{REPO}/actions/workflows/{wf}/runs?head_sha={SHA}&per_page=100" in calls


# --- gate-label-needs-run -------------------------------------------------------------------------------------

def test_gate_label_without_gate_run_blocks(tmp_path):
    """Review focus 4: a PR carrying the gate's label with no run of that gate for the SHA does not merge."""
    # act
    done, calls, _ = Merge(labels=("auto-merge", "needs-lab")).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"carries needs-lab and no run of ci-test-lab.yml exists for {SHA}" in done.stdout
    assert f"gh workflow run ci-test-lab.yml --ref {BRANCH}" in done.stdout
    assert not _merged(calls)


def test_gate_label_with_green_gate_run_merges(tmp_path):
    """Review focus 4: a gate whose decide job said skip still ends its run successfully; that counts green."""
    # act
    done, calls, _ = Merge(labels=("auto-merge", "needs-lab"),
                           runs={"ci.yml": [GREEN], "ci-test-lab.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(calls)


def test_a_gate_not_among_the_triggers_is_red(tmp_path):
    """Checked before any gh call, whatever the PR carries: a wiring defect is not a property of one PR."""
    # act
    done, calls, _ = Merge(labels=("auto-merge",), triggers="ci.yml").run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "ci-test-lab.yml is not among TRIGGERS (ci.yml)" in done.stderr
    assert calls == ""


@pytest.mark.parametrize("ci_runs", [[GREEN], [{"event": "push", "status": "completed", "conclusion": "failure"}]],
                         ids=["ci-green", "a-trigger-red"])
def test_ci_workflow_not_among_the_triggers_is_red(tmp_path, ci_runs):
    """A red trigger run must not hide the wiring defect behind a green no-op."""
    # act
    done, calls, _ = Merge(triggers="ci-test-lab.yml",
                           runs={"ci.yml": ci_runs, "ci-test-lab.yml": [ci_runs[0]]}).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "ci.yml is not among TRIGGERS (ci-test-lab.yml)" in done.stderr
    assert calls == ""


def test_no_gates_reads_no_labels(tmp_path):
    # act
    done, calls, _ = Merge(gates="", triggers="ci.yml", runs={"ci.yml": [GREEN]}).run(tmp_path)

    # assert
    assert done.returncode == 0, done.stdout + done.stderr
    assert "pr view" not in calls
    assert _merged(calls)


# --- squash-merge and dispatch-ci-on-base ---------------------------------------------------------------------

def test_green_merges_and_dispatches_ci_on_base(tmp_path):
    # act
    done, calls, outputs = Merge().run(tmp_path)

    # assert: the base came from the list read before the merge; the dispatch follows the merge
    assert done.returncode == 0, done.stdout + done.stderr
    lines = calls.splitlines()
    merge = lines.index(f"pr merge 7 --squash --delete-branch --match-head-commit {SHA}")
    dispatch = lines.index("workflow run ci.yml --ref main")
    assert merge < dispatch == len(lines) - 1
    assert outputs == {"merged_pr": "7", "base": "main"}


def test_failed_dispatch_is_red_after_merge(tmp_path):
    # act
    done, calls, outputs = Merge(dispatch_rc=1).run(tmp_path)

    # assert
    assert done.returncode == 1
    assert "MERGED" in done.stderr and "UNVERIFIED" in done.stderr
    assert "gh workflow run ci.yml --ref main" in done.stderr
    assert _merged(calls) and outputs == {"merged_pr": "7", "base": "main"}


def test_a_failed_merge_is_red_and_dispatches_nothing(tmp_path):
    # act
    done, calls, outputs = Merge(merge_rc=1).run(tmp_path)

    # assert
    assert done.returncode != 0
    assert not _dispatched(calls) and outputs == {}


@pytest.mark.parametrize("name", ["GH_REPO", "BRANCH", "SHA", "CI_WORKFLOW", "TRIGGERS", "EVENT", "GITHUB_OUTPUT"])
def test_a_missing_input_is_red_naming_it(tmp_path, name):
    # arrange: a gh that fails every call, so the real one is never reached
    bin_dir, calls = gh_on_path(tmp_path, "exit 98\n")
    script = tmp_path / "merge.sh"
    script.write_text(automerge.MERGE_SCRIPT, encoding="utf-8")
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "GH_REPO": REPO, "BRANCH": BRANCH, "SHA": SHA, "CI_WORKFLOW": "ci.yml",
           "TRIGGERS": "ci.yml", "GATES": "", "EVENT": "workflow_run", "GITHUB_OUTPUT": str(tmp_path / "out"),
           name: ""}

    # act
    done = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)

    # assert
    assert done.returncode == 1
    assert name in done.stderr
    assert calls_made(calls) == ""
