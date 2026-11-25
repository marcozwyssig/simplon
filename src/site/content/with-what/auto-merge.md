---
title: "The auto-merge policy"
weight: 8
---

GENERATED from `src/firn/model/simplon/automerge/automerge.firn` by `./simplon.sh build model`.

What `merge: auto` switches on (how/manifest.md, section `merge:`): the derived
`.github/workflows/auto-merge.yml` merges an open pull request labelled `auto-merge` with `gh pr merge --squash`
once these rules pass. The generated workflow carries the same reason beside each rule, and its script is
generated from the same instance.

## The rules

They run in this order. A rule that holds the merge says why in the log; a failed read is red, never a green
"nothing to do".

| Rule | Why | Source |
|---|---|---|
| `token-scope` | A token that cannot read pull requests lists none, and an empty list reads as nothing to merge: netctl#965 merged under such a token and reported success while merging nothing, so the pulls endpoint is probed first and a failed probe is red. | netctl#964 |
| `labelled-pr` | Only an open pull request for the run's branch carrying the label is merged; the label is the opt-in. None is a green no-op, and a pull request merged by an earlier run is no longer open. The open pull requests are listed without a label filter and the label is matched in the listing: `gh pr list --label` asks GitHub's search API, whose index lags a label change, so a pull request labelled just before its run completes could be missing and read as nothing to merge. | si#874 |
| `head-is-sha` | Merge what was verified: only the pull request whose head is the run's commit merges, a newer commit merges on its own run. Selecting by commit also keeps a fork's pull request with the same branch name from being picked. | netctl#1788 |
| `cross-repository` | A pull request from a fork is not merged: a fork's runs use the workflow files of the fork's own head, so a fork could turn its own runs green while the label stays on. It is merged by hand. | si#874 security review |
| `labeller-can-merge` | The label is only an opt-in from someone who may merge: a triage-role user can add a label and may not merge, so whoever added the label most recently must have write, maintain or admin permission. That is the last labeled event of the issue timeline, and a timeline whose last event for the label is unlabeled is red. Anyone else is a green no-op that names them; a failed read, or a labeller with no login, is red. | si#874 security review |
| `trigger-runs-green` | Every run of every trigger workflow for the commit, schedule runs aside, must have completed successfully; a running or red one holds the merge, and its completion reconsiders it. A failed read is red: a missing verdict is not a green one. | netctl#1788 |
| `ci-run-exists` | The rules cover CI as well as the gates: a run of the CI workflow for the commit must exist, because a green gate's run, which triggers this one as well, says nothing about what CI runs. | si#874 |
| `derived-gate-ran` | A gate workflow the kernel derives must have a run for the commit, schedule runs aside: its decide job runs on every pull request event, so a pull request always has one, and none means no gate ever looked at this tree. That is a stacked parent after its child merged into it, whose head moved without a pull request event, so it waits for a push or for the gate's workflow to be dispatched, and the dispatch command is named. A hand-written gate may run on its label or a schedule only, so it keeps only the label rule below. | si#874 |
| `gate-label-needs-run` | A gate's label takes the role of netctl's needs-lab: a pull request carrying it with no run of that gate's workflow for the commit does not merge, and the dispatch command is named. | netctl#1788 |
| `squash-merge` | Merge with the policy's method and delete the branch, bound to the verified commit: GitHub refuses the merge if the head moved between the checks and the merge. The base is read before the merge, while the pull request is still open. | si#874 |
| `dispatch-ci-on-base` | A merge pushed under the workflow token starts no run, so the CI workflow is dispatched on the base branch afterwards; a failed dispatch is red, because the base then carries an unverified commit. | netctl#964 |

## The token

The workflow's `permissions:` block is a strict allowlist, so each scope is written with its reason, in the
generated file as here.

| Scope | Why |
|---|---|
| `contents: write` | the squash merge writes the base branch and deletes the head branch |
| `pull-requests: write` | the merge itself, and reading the pull requests (rule token-scope) |
| `actions: write` | a permissions block is a strict allowlist: without it the dispatch fails with HTTP 403 while the merge succeeds (netctl run 30950192001) |
| `issues: write` | without it the merge succeeds and the linked issues silently stay open (netctl#1429) |

## The script's inputs

The merge step's `env:`, in the order the step writes it, and the script's whole interface: it reads nothing
else, so nothing a pull request author controls is written into it. Each value is a GitHub expression, or a
field of the derived workflow model the kernel fills in. A required input that is empty is red before any call.

- `GH_TOKEN`: the workflow's token, which gh reads. From `${{ github.token }}`.
- `GH_REPO` (required): the repository, owner/name. From `${{ github.repository }}`.
- `BRANCH` (required): the pull request's head branch, the completed run's. From `${{ github.event.workflow_run.head_branch }}`.
- `SHA` (required): the commit verified, the completed run's. From `${{ github.event.workflow_run.head_sha }}`.
- `CI_WORKFLOW` (required): the CI workflow's file, the one dispatched on the base after a merge. From the derivation (`ci_workflow`).
- `TRIGGERS` (required): every trigger workflow's file, CI first, space-separated. From the derivation (`triggers`).
- `GATES`: one line of a gate's workflow file and its label per gate with a label, empty when none. From the derivation (`labels`).
- `DERIVED_GATES`: the file of every gate workflow the kernel derives, space-separated, empty when none. From the derivation (`derived_gates`).
<!-- Generated by firn, do not edit outside protected regions. id=[Docs:,3e520b39d5217992] -->
