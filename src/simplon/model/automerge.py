# GENERATED from src/firn/model/simplon/automerge/automerge.firn by `./simplon.sh build model`. Do not edit:
# firn rewrites the whole file on every run, and this file has no protected region.
"""The merge policy `merge: auto` switches on (si#874): its label, its method, its rules, and its script."""

#: The label that opts a pull request in.
LABEL = "auto-merge"

#: The `gh pr merge` method.
METHOD = "squash"

#: (key, reason, source) per rule, in the order the script applies them.
RULES: tuple[tuple[str, str, str], ...] = (
    ("token-scope", "A token that cannot read pull requests lists none, and an empty list reads as nothing to merge: netctl#965 merged under such a token and reported success while merging nothing, so the pulls endpoint is probed first and a failed probe is red.", "netctl#964"),
    ("labelled-pr", "Only an open pull request for the run's branch carrying the label is merged; the label is the opt-in. None is a green no-op, and a pull request merged by an earlier run is no longer open.", "si#874"),
    ("head-is-sha", "Merge what was verified: only the pull request whose head is the run's commit merges, a newer commit merges on its own run. Selecting by commit also keeps a fork's pull request with the same branch name from being picked.", "netctl#1788"),
    ("cross-repository", "A pull request from a fork is not merged: a fork's runs use the workflow files of the fork's own head, so a fork could turn its own runs green while the label stays on. It is merged by hand.", "si#874 security review"),
    ("labeller-can-merge", "The label is only an opt-in from someone who may merge: a triage-role user can add a label and may not merge, so whoever added the label most recently must have write, maintain or admin permission, read on both events. Anyone else is a green no-op that names them; a failed read is red.", "si#874 security review"),
    ("label-triggers", "Adding the label triggers too, a deviation from netctl: a pull request labelled after its runs are green merges without a new run. That event carries no run of its own, so the runs for the head commit are asked for.", "si#874"),
    ("trigger-runs-green", "Every run of every trigger workflow for the commit, schedule runs aside, must have completed successfully; a running or red one holds the merge, and its completion reconsiders it. A failed read is red: a missing verdict is not a green one.", "netctl#1788"),
    ("ci-run-exists", "The rules cover CI as well as the gates: a run of the CI workflow for the commit must exist, because a green gate says nothing about what CI runs, and the label event has no triggering run to stand in for it.", "si#874"),
    ("gate-label-needs-run", "A gate's label takes the role of netctl's needs-lab: a pull request carrying it with no run of that gate's workflow for the commit does not merge, and the dispatch command is named.", "netctl#1788"),
    ("squash-merge", "Merge with the policy's method and delete the branch, bound to the verified commit: GitHub refuses the merge if the head moved between the checks and the merge. The base is read before the merge, while the pull request is still open.", "si#874"),
    ("dispatch-ci-on-base", "A merge pushed under the workflow token starts no run, so the CI workflow is dispatched on the base branch afterwards; a failed dispatch is red, because the base then carries an unverified commit.", "netctl#964"),
)

#: The auto-merge job's `if:`.
CONDITION = "(github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event != 'schedule') || (github.event_name == 'pull_request_target' && github.event.label.name == 'auto-merge')"

#: (scope, access, reason) per scope of the auto-merge workflow's token.
PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("contents", "write", "the squash merge writes the base branch and deletes the head branch"),
    ("pull-requests", "write", "the merge itself, and reading the pull requests (rule token-scope)"),
    ("actions", "write", "a permissions block is a strict allowlist: without it the dispatch fails with HTTP 403 while the merge succeeds (netctl run 30950192001)"),
    ("issues", "write", "without it the merge succeeds and the linked issues silently stay open (netctl#1429)"),
)

#: The auto-merge step's `run:`. Its environment is its interface: GH_TOKEN, GH_REPO, BRANCH, SHA, CI_WORKFLOW,
#: TRIGGERS, GATES and EVENT, as the script's header says.
MERGE_SCRIPT = r"""set -euo pipefail
# GENERATED from src/firn/model/simplon/automerge/automerge.firn (si#874). Merges the open pull request
# labelled auto-merge whose head is $SHA once every trigger workflow's run for that commit is green: netctl's
# rules, and the ones si#874 decided on top. Each rule's comment is its reason and the ticket behind it.
#
# Set by the step: GH_TOKEN, GH_REPO, BRANCH (the pull request's head branch), SHA (the commit verified),
# CI_WORKFLOW (the CI workflow's file), TRIGGERS (every trigger workflow's file, CI first, space-separated),
# GATES (one `<workflow file> <label>` line per gate with a label, empty when none) and EVENT
# (workflow_run or pull_request_target). Writes merged_pr and base to $GITHUB_OUTPUT when it merged.
for name in GH_REPO BRANCH SHA CI_WORKFLOW TRIGGERS EVENT GITHUB_OUTPUT; do
  if [ -z "$(printenv "$name" || true)" ]; then
    echo "::error::$name is empty: the auto-merge step sets it, and without it there is no verdict." >&2
    exit 1
  fi
done
case "$EVENT" in
  workflow_run | pull_request_target) ;;
  *)
    echo "::error::EVENT is '$EVENT': the merge runs on workflow_run or pull_request_target only." >&2
    exit 1
    ;;
esac
gates=$(printenv GATES || true)
# The CI workflow and every gate are read as triggers below; one that is not among TRIGGERS would never be read.
for wf in "$CI_WORKFLOW" $(printf '%s\n' "$gates" | awk 'NF { print $1 }'); do
  case " $TRIGGERS " in
    *" $wf "*) ;;
    *)
      echo "::error::$wf is not among TRIGGERS ($TRIGGERS): its runs would never be read, so there is no verdict." >&2
      exit 1
      ;;
  esac
done
runs_dir=$(mktemp -d)
trap 'rm -rf "$runs_dir"' EXIT

# token-scope (netctl#964): A token that cannot read pull requests lists none, and an empty list reads as nothing to merge: netctl#965 merged under such a token and reported success while merging nothing, so the pulls endpoint is probed first and a failed probe is red.
if ! gh api "repos/$GH_REPO/pulls?state=open&per_page=1" >/dev/null; then
  echo "::error::the merge token cannot read the pull requests of $GH_REPO: auto-merge is not functional." >&2
  echo "::error::this is a token scope problem, NOT 'nothing to merge'." >&2
  exit 1
fi

# labelled-pr (si#874): Only an open pull request for the run's branch carrying the label is merged; the label is the opt-in. None is a green no-op, and a pull request merged by an earlier run is no longer open.
listed=$(gh pr list --head "$BRANCH" --state open --label "auto-merge" --json number,headRefOid,baseRefName,isCrossRepository \
  --jq '.[] | "\(.number) \(.headRefOid) \(.baseRefName) \(.isCrossRepository)"')
if [ -z "$listed" ]; then
  echo "No open PR labelled auto-merge for branch '$BRANCH'; nothing to do."
  exit 0
fi

# head-is-sha (netctl#1788): Merge what was verified: only the pull request whose head is the run's commit merges, a newer commit merges on its own run. Selecting by commit also keeps a fork's pull request with the same branch name from being picked.
pr=$(printf '%s\n' "$listed" | awk -v sha="$SHA" '$2 == sha { print $1; exit }')
if [ -z "$pr" ]; then
  echo "The labelled PR for '$BRANCH' has moved on: this run verified $SHA, and no open labelled PR has it as its head."
  printf '%s\n' "$listed" | awk '{ print "  PR #" $1 " is at " $2 }'
  echo "Not merging: the newer commit merges on its own run."
  exit 0
fi
base=$(printf '%s\n' "$listed" | awk -v sha="$SHA" '$2 == sha { print $3; exit }')

# cross-repository (si#874 security review): A pull request from a fork is not merged: a fork's runs use the workflow files of the fork's own head, so a fork could turn its own runs green while the label stays on. It is merged by hand.
cross=$(printf '%s\n' "$listed" | awk -v sha="$SHA" '$2 == sha { print $4; exit }')
case "$cross" in
  false) ;;
  true)
    echo "PR #$pr comes from a fork: a fork's runs use the fork's own workflow files; merge it by hand."
    exit 0
    ;;
  *)
    echo "::error::could not tell whether PR #$pr comes from a fork (isCrossRepository is '$cross'): no verdict." >&2
    exit 1
    ;;
esac

# labeller-can-merge (si#874 security review): The label is only an opt-in from someone who may merge: a triage-role user can add a label and may not merge, so whoever added the label most recently must have write, maintain or admin permission, read on both events. Anyone else is a green no-op that names them; a failed read is red.
labeller=$(gh api --paginate "repos/$GH_REPO/issues/$pr/events" \
  --jq '.[] | select(.event == "labeled" and .label.name == "auto-merge") | .actor.login') || {
  echo "::error::could not read who labelled PR #$pr auto-merge: no verdict, so no merge." >&2
  exit 1
}
labeller=$(printf '%s\n' "$labeller" | awk 'NF { last = $0 } END { print last }')
if [ -z "$labeller" ]; then
  echo "::error::PR #$pr carries auto-merge and no labeled event names who added it: no verdict, so no merge." >&2
  exit 1
fi
if ! access=$(gh api "repos/$GH_REPO/collaborators/$labeller/permission" --jq .permission); then
  echo "::error::could not read the permission of $labeller, who labelled PR #$pr auto-merge: no verdict, so no merge." >&2
  exit 1
fi
case "$access" in
  admin | maintain | write) ;;
  *)
    echo "$labeller added the label auto-merge to PR #$pr last, and has '$access' permission, not write, maintain or admin."
    echo "Not merging: the label opts in only from someone who may merge. Someone who may can remove it and add it again."
    exit 0
    ;;
esac

# label-triggers (si#874): Adding the label triggers too, a deviation from netctl: a pull request labelled after its runs are green merges without a new run. That event carries no run of its own, so the runs for the head commit are asked for.
if [ "$EVENT" = "pull_request_target" ]; then
  echo "The label auto-merge was added to PR #$pr: no run triggered this, so the runs for $SHA are read."
fi

# trigger-runs-green (netctl#1788): Every run of every trigger workflow for the commit, schedule runs aside, must have completed successfully; a running or red one holds the merge, and its completion reconsiders it. A failed read is red: a missing verdict is not a green one.
for wf in $TRIGGERS; do
  if ! gh api "repos/$GH_REPO/actions/workflows/$wf/runs?head_sha=$SHA&per_page=100" \
    --jq '.workflow_runs[] | select(.event != "schedule") | "\(.status) \(.conclusion)"' >"$runs_dir/$wf"; then
    echo "::error::could not read the runs of $wf for $SHA: no verdict, so no merge." >&2
    exit 1
  fi
  if grep '^completed ' "$runs_dir/$wf" | grep -qvx 'completed success'; then
    echo "A run of $wf for $SHA completed without success; not merging PR #$pr."
    echo "Re-run that run (a re-run replaces its conclusion) or push a new commit."
    exit 0
  fi
  if grep -qv '^completed ' "$runs_dir/$wf"; then
    echo "A run of $wf for $SHA is still running; not merging PR #$pr."
    echo "This is reconsidered when it completes: $wf is a trigger of this workflow."
    exit 0
  fi
done

# ci-run-exists (si#874): The rules cover CI as well as the gates: a run of the CI workflow for the commit must exist, because a green gate says nothing about what CI runs, and the label event has no triggering run to stand in for it.
if [ ! -s "$runs_dir/$CI_WORKFLOW" ]; then
  echo "No run of $CI_WORKFLOW for $SHA (schedule runs aside); not merging PR #$pr."
  echo "It merges when that run completes green: $CI_WORKFLOW is a trigger of this workflow."
  exit 0
fi

# gate-label-needs-run (netctl#1788): A gate's label takes the role of netctl's needs-lab: a pull request carrying it with no run of that gate's workflow for the commit does not merge, and the dispatch command is named.
if [ -n "$gates" ]; then
  labels=$(gh pr view "$pr" --json labels --jq '.labels[].name')
  while read -r file label; do
    [ -n "$file" ] || continue
    if printf '%s\n' "$labels" | grep -qxF -- "$label" && [ ! -s "$runs_dir/$file" ]; then
      echo "PR #$pr carries $label and no run of $file exists for $SHA; not merging."
      echo "Run it: gh workflow run $file --ref $BRANCH"
      exit 0
    fi
  done < <(printf '%s\n' "$gates")
fi

# squash-merge (si#874): Merge with the policy's method and delete the branch, bound to the verified commit: GitHub refuses the merge if the head moved between the checks and the merge. The base is read before the merge, while the pull request is still open.
echo "Every run for $SHA is green: merging PR #$pr into '$base' (squash) and deleting '$BRANCH'."
gh pr merge "$pr" --squash --delete-branch --match-head-commit "$SHA"
echo "merged_pr=$pr" >>"$GITHUB_OUTPUT"
echo "base=$base" >>"$GITHUB_OUTPUT"

# dispatch-ci-on-base (netctl#964): A merge pushed under the workflow token starts no run, so the CI workflow is dispatched on the base branch afterwards; a failed dispatch is red, because the base then carries an unverified commit.
echo "Dispatching $CI_WORKFLOW on '$base' so the merged tree gets a verdict."
if ! gh workflow run "$CI_WORKFLOW" --ref "$base"; then
  echo "::error::PR #$pr MERGED into '$base', but dispatching $CI_WORKFLOW on it failed." >&2
  echo "::error::'$base' now carries an UNVERIFIED commit. Run: gh workflow run $CI_WORKFLOW --ref $base" >&2
  exit 1
fi
"""
# Generated by firn, do not edit outside protected regions. id=[AutoMerge:,92070bd46e73fce4]
