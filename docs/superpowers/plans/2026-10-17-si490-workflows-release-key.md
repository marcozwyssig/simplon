# si#490 `workflows: release:` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One workflow-level key, `release: <group> <name>`, from which workflowgen derives the whole dispatch release workflow of a release aggregate.

**Architecture:** Two new task fields in the command model (`publishes`, `token`) say which leaves a dry run skips and which steps receive `GITHUB_TOKEN`. `_workflow` parses `release:`, derives the trigger, `permissions` and `concurrency`, and refuses what would contradict them. At render time a `_release` expansion, the sibling of `_rollout`, turns the aggregate's plan into one ordinary `Job` that the existing `_render_job` writes. There is no new render path.

**Tech Stack:** Python 3.11, pydantic v2 (manifest model), PyYAML, pytest; the firn-generated catalogue is untouched (the new fields live beside `unattended:` in hand-written `catalogue.yaml`).

**Spec:** `docs/superpowers/specs/2026-10-17-si490-workflows-release-key-design.md`

## Global Constraints

- Python is always `deploy/orchestrator/.venv/bin/python`. Three `test_tasks_docs` failures are root-bound and pre-existing.
- Gates before the PR:
  - `./simplon.sh test model`;
  - `./simplon.sh test generated` (it compares against the COMMITTED state, so it is stale until commit);
  - `./simplon.sh support workflows --check`;
  - the full suite;
  - mypy.
- No `${{ inputs.` inside any `run:` value. The version reaches scripts via the job `env: RELEASE_VERSION: ${{ inputs.version }}` and commands via `EnvValue("RELEASE_VERSION")`.
- Input texts, verbatim:
  - `version`: `'The version to release, exactly as its tag will be: vX.Y.Z'`, type string, required.
  - `dry_run`: `'Rehearse: build and check everything, publish nothing'`, type boolean, required, `default: true`.
- Derived extras, verbatim:
  - `permissions: { contents: write, packages: write }`;
  - `concurrency: { group: '${{ github.workflow }}-${{ inputs.version }}', cancel-in-progress: false }`.
- The derived job is named `release`. The token line is `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.
- Every new load-time refusal is classified in `src/tests/test_refusal_census.py`. EXPRESSION entries get a `REACH_MERGED` reach. The census walk decides which raises it reaches, and every key it reports gets an entry.
- Commits use heredocs, env identity per commit (`GIT_AUTHOR_*`/`GIT_COMMITTER_*` = `Marco Zwyssig <marco@zwyssig.info>`) and the two trailer lines. See every new test red first.

## Review Focus

1. **A dispatch with a hostile version, e.g. `v1.0.0; touch pwned`.** It must reach every script and command as one quoted argument. `git tag` refuses it, and no file is created. Owned by Task 3 (bash test).
2. **A product workflow-level `env:` that sets `RELEASE_VERSION`.** It must be refused, not silently shadowed by the job's value. Owned by Task 2.
3. **A plan leaf needing a parameter nobody passes** (for example an env-first `cd` leaf). The existing `_parameters` refusal must name the leaf; the leaf is not rendered without its argument. Owned by Task 3.
4. **A re-run after the tag push.** The fetched tag must not break step 1 (rc 128 measured). Owned by Task 3 (bash test, "already at HEAD" case).
5. **A product's own job beside `release:`,** with `needs: release`. It renders after the derived job and keeps its `needs:`. Owned by Task 3 (golden).

---

### Task 1: The task fields `publishes:` and `token:`

**Files:**
- Modify:
  - `src/simplon/manifest/load.py` (`_CommandSpecModel` near :255, and `_command` near :893);
  - `src/simplon/model/command.py` (`Command`/`TaskCommand` fields beside `unattended`, :98);
  - `src/simplon/manifest/treeform.py:545-549` (`INHERITED`, `TASK_KEYS`);
  - `src/simplon/catalogue.yaml` (release, build-publish and other tasks, see Step 3);
  - `src/simplon/adapters/githubpackages.py:14` (the wrong "Actions injects `GITHUB_TOKEN`" sentence);
  - `src/tests/test_refusal_census.py`.
- Test:
  - `src/tests/test_catalogue_publishes_and_token.py` (new);
  - the existing manifest-load tests file for the validators (`src/tests/test_manifest_load.py` or wherever `unattended`'s tri-state is tested; grep `'unattended' is true or false`).

**Interfaces:**
- Produces:
  - `TaskCommand.publishes: bool` (default `False`);
  - `TaskCommand.token: str` (`""` or `"github"`);
  - both inherited from the task by every command instantiating it, and overridable by the command, exactly as `unattended`;
  - `PUBLISH_READS: frozenset[str]` in the new test module only.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_task_field_publishes_reaches_the_command_that_instantiates_it`: a product `tasks:` entry with `publishes: true` and a command `task:` naming it gives `spec.publishes is True`. A command without the field over a catalogue task gives the catalogue's value.
  - `test_publishes_is_true_or_false` and `test_token_names_a_known_issuer`: `publishes: "yes"` and `token: gitlab` refuse at load. The messages are pinned: `'publishes' is true or false` and `'token' is github or absent`.
  - `test_every_release_task_says_whether_it_publishes`: for every catalogue key starting `release:`, `publishes is True` or the key is in `PUBLISH_READS = {"release:notes", "release:github-unpublished"}`. The two sets are disjoint.
  - `test_token_is_declared_exactly_where_a_body_reads_github_credentials`: for every catalogue task, `token == "github"` iff its body module's source (`body = "simplon.tasks.x:fn"` → `src/simplon/tasks/x.py`) imports `githubpackages` or `simplon.adapters.github`, through `githubrelease` or directly.
- [ ] **Step 2: Run them.** Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_publishes_and_token.py -q`. Expected: FAIL. The field is unknown (pydantic ignores extra keys, so the attribute is missing) or the coverage asserts fail.
- [ ] **Step 3: Implement.**
  - **Model.** Add `publishes: bool = False` with a strict-bool validator (refuse a non-bool, never coerce), and `token: str = ""` with a validator accepting only `""`/`"github"`. Add both to `TASK_KEYS` and `INHERITED`, carry them through `common` in `_command` to `Command` (or `TaskCommand` only, if `Command` subclasses reject unknown fields; rule and ledger which), and add each to the catalogue task entries.
  - **`publishes: true`** goes on `release:tag`, `release:image`, `release:asset`, `release:github-draft`, `release:github-publish`, and every other `release:*` task that uploads (measure: `release:nuget`, `release:maven`, `release:conan` if present; anything the coverage test flags).
  - **`token: github`** goes on exactly the set the import test reports. If a body imports `githubpackages` for something that is not a credential, rule and ledger it, and exclude that body by name in the test with the reason.
  - **The comment.** Fix the `githubpackages.py:14` comment to say what is measured: the token comes from `GITHUB_TOKEN`/`GH_TOKEN` if set, else `gh auth token`, and Actions sets neither unless the workflow passes it.
- [ ] **Step 4: Run them, then the census.**
  - Run `deploy/orchestrator/.venv/bin/python -m pytest src/tests/test_catalogue_publishes_and_token.py src/tests/test_refusal_census.py -q`.
  - Expected: the new tests PASS. The census reports the two new validator refusals as unclassified (if it walks pydantic validators; see `test_the_rules_pydantic_runs_are_reached_through_the_model`).
  - Classify both as DIAGNOSIS and re-run until green.
- [ ] **Step 5: Regenerate and run the gates.**
  - `./simplon.sh build model` (the kinds/catalogue pages print task fields; if they do not, nothing changes).
  - Then the full suite: `deploy/orchestrator/.venv/bin/python -m pytest src/tests -q -x -p no:cacheprovider > <workspace>/t1.log; tail`.
  - Expected: green except the 3 known root-bound failures. Pins of catalogue field lists that fail get updated.
- [ ] **Step 6: Commit.** Message: `feat(si#490): publishes: and token: - the catalogue says which tasks publish and which read GitHub credentials`.

### Task 2: Parsing `release:` and what it derives

**Files:**
- Modify:
  - `src/simplon/tasks/workflowgen.py`: `Workflow` (:227), `_workflow` (:320), `_OWN_WORKFLOW_KEYS` (:440), the `on:`-missing message (:346), and the module docstring sentence "does not invent one";
  - `src/site/content/how/manifest.md` (the same sentence, if it echoes it; grep `invent`);
  - `src/tests/test_refusal_census.py`.
- Test: `src/tests/test_workflowgen.py`.

**Interfaces:**
- Produces:
  - `Workflow.release: str = ""` (the aggregate's command words, e.g. `"release all"`);
  - `RELEASE_KEY = "release"`, `RELEASE_JOB = "release"`, `RELEASE_ENV = "RELEASE_VERSION"`;
  - a parsed release `Workflow` with `on` equal to the derived dispatch mapping, and `extras` beginning with the derived `permissions` and `concurrency`, then the product's own extras in order;
  - `rollout_runs_on`/`rollout_env` set from `runner:` for a release workflow exactly as for `flow:`. Keep the field names, ledger the ruling: they now mean "the derived job's machine".

- [ ] **Step 1: Write the failing tests.**
  - `test_release_derives_the_dispatch_trigger`: `parse({"workflows": {"rel": {"release": "release all", "runner": {...}}}})[0].on` equals the dispatch mapping with both inputs, using the exact texts from Global Constraints.
  - `test_release_derives_permissions_and_concurrency`.
  - The refusals, one test each with the message pinned:
    - `on:` beside `release:`: `the trigger is derived from release:`;
    - `permissions:` and `concurrency:`: `is derived from release:`;
    - `flow:` beside `release:`: `a rollout or a release, not both`;
    - `release:` in a `handwritten:` workflow: the existing stray list now names `release`;
    - a product job named `release`: `the derived job is named 'release'`;
    - a workflow-level `env:` setting `RELEASE_VERSION`: `RELEASE_VERSION is the dispatch input's`;
    - `release:` not a non-empty string: `names a release aggregate as <group> <name>`.
  - `test_a_workflow_without_release_still_needs_its_own_on`: the existing refusal still fires, and its amended text still says the kernel derives a trigger only for `release:`.
- [ ] **Step 2: Run them.** `... -m pytest src/tests/test_workflowgen.py -q -k release`. Expected: FAIL (no `release` field, keys carried as extras).
- [ ] **Step 3: Implement in `_workflow`.**
  - Read `release:` before the `on:` check. Refuse each conflict.
  - Build `trigger` from constants, and extend `runner` resolution to `stages or release`.
  - Prepend the derived extras, and add `RELEASE_KEY` to `_OWN_WORKFLOW_KEYS`.
  - Amend the `on:` refusal and the docstring/site sentence: a workflow derives its trigger only from `release:`; every other workflow writes its own.
- [ ] **Step 4: Run them and the census.** The census lists each new raise. Classify:
  - `on`/`permissions`/`concurrency` beside `release:`: EXPRESSION, with `REACH_MERGED` in the reach table;
  - every other new raise: DIAGNOSIS.
  - Expected: `test_workflowgen.py` and `test_refusal_census.py` green, and `rules.md` counts follow when the page test demands it (the page test prints the computed numbers; update the page text it pins).
- [ ] **Step 5: Commit.** Message: `feat(si#490): workflows: <key>: release: - the dispatch trigger, permissions and concurrency are derived`.

### Task 3: The derived job

**Files:**
- Modify:
  - `src/simplon/tasks/workflowgen.py`: new `_release`, called in `render` beside `_rollout` (:1073), plus constants for the step names and scripts;
  - `src/tests/test_refusal_census.py`, if the walk reaches render-time raises (measured on main: `_rollout`'s render-time raises have no census entry, so expect none).
- Create:
  - `src/tests/fixtures/workflows/release-manifest.yaml` (a release aggregate: notes → draft → `test:image` leaf with evidence → `release:image` → `release:tag` → `release:github-publish`, `passes: [tag]`, `stop_on_failure: true`; plus a product job `announce` with `needs: release`);
  - `src/tests/fixtures/workflows/release.golden.yml`.
- Test: `src/tests/test_workflowgen.py`.

**Interfaces:**
- Consumes:
  - Task 1's `TaskCommand.publishes`/`.token`;
  - Task 2's `Workflow.release`, `RELEASE_JOB` and `RELEASE_ENV`;
  - `_leaves(manifest, Step(command=workflow.release), where)`, which gives `((words, TaskCommand), ...)`;
  - `resolve_command`;
  - `artifactsection.Declared.path`.
- Produces: `_release(workflow: Workflow, manifest: Manifest, artifacts: Mapping[str, artifactsection.Declared]) -> tuple[Job, ...]`. It returns `()` when `workflow.release` is empty, else one `Job(name=RELEASE_JOB, runs_on=workflow.rollout_runs_on, steps=..., extras={"env": {RELEASE_ENV: "${{ inputs.version }}", **workflow.rollout_env}}, runner=...)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_release_workflow_matches_its_golden`: render the fixture and compare it byte for byte with `release.golden.yml`. Write the golden by hand from the spec first, then let the first green run confirm it. Never generate it from the code under test.
  - `test_release_workflow_parses_as_yaml`: `yaml.safe_load` succeeds, and `True in doc` (the `on:` key), asserted with the reason in the message.
  - `test_no_dispatch_input_inside_a_run_script`: no `run:` value in the parsed document contains `${{ inputs.`.
  - `test_release_workflow_passes_actionlint`: skip when `shutil.which("actionlint")` is None.
  - `test_a_dry_run_skips_exactly_the_publishing_leaves`: the steps with `if: ${{ !inputs.dry_run }}` are exactly the leaves whose spec has `publishes`. The tail step has `if: ${{ inputs.dry_run }}`.
  - `test_only_token_leaves_see_the_token`: only steps of `token == "github"` leaves carry `env.GITHUB_TOKEN`, and the job `env:` does not.
  - `test_the_version_goes_only_to_passed_params`: `release:tag`'s run line ends `"$RELEASE_VERSION"`, and `test:image`'s run line has no `--tag`.
  - Refusals, messages pinned:
    - the command does not exist: the existing `resolve_command` message;
    - not a `ReleaseCommand`: `names 'X', which is not a release aggregate`;
    - `passes:` lacks `tag`: `the version would reach no command`;
    - a leaf with `unattended` not `True`: `cannot run in the release job unattended`.
  - Review Focus 3: a fixture leaf needing an unpassed required param → the existing `_parameters` refusal.
  - `test_the_cut_and_the_stamp_run_in_bash` (Review Focus 1 and 4): extract steps 1–2's `run:` scripts from the rendered file and run them with `bash -e` in a temporary git repo with one commit, `env={"RELEASE_VERSION": v, ...}`, for these cases:
    - fresh `v1.0.0`: rc 0;
    - tag already at HEAD (the re-run): rc 0;
    - a dirty tree, or HEAD not at the tag (describe unequal): rc 1, stderr `::error::the build would be stamped`;
    - `v1.0.0; touch pwned`: rc ≠ 0 and no `pwned` file.
  - `test_without_a_notes_leaf_the_tail_prints_only_its_line`.
- [ ] **Step 2: Run them.** `... -m pytest src/tests/test_workflowgen.py -q -k "release"`. Expected: FAIL (the job is not rendered).
- [ ] **Step 3: Implement `_release`.** Steps in this order, as `Step`s:
  1. Verbatim `run:` with a `name:`: `Cut the tag in this checkout`, script `git tag -d "$RELEASE_VERSION" >/dev/null 2>&1 || true` then `git tag "$RELEASE_VERSION"`.
  2. Verbatim `run:` with the name `The build will be stamped with the version`. It runs firn's script: `described="$(git describe --tags --always --dirty)"`, then compare it with `[ "$described" = "$RELEASE_VERSION" ]`, else `echo "::error::the build would be stamped $described, not $RELEASE_VERSION"; exit 1`.
  3. One `Step(command=words, params={p: EnvValue(RELEASE_ENV) for p in aggregate.passes if p in leaf.params}, modifiers=...)` per leaf. The modifiers carry `if: ${{ !inputs.dry_run }}` when `publishes`, and `env: {GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}}` when `token == "github"`.
     - Measure first: are a step's `modifiers` rendered as step-level keys by `_render_job`? `continue-on-error` already is (:1154).
     - Measure: is a leaf's `params` key set available on `TaskCommand`? Use whatever `_parameters` reads.
  4. Verbatim `run:` with the name `What a release would have published (dry run)` and `if: ${{ inputs.dry_run }}`. It echoes `dry run: no draft, no tag pushed, nothing published. The notes for $RELEASE_VERSION:` and then runs `cat <path>`. The path is shell-quoted and comes from the `release:notes` leaf's produced artifact's declared path. Without that leaf, print only `dry run: nothing published for $RELEASE_VERSION`.

  Each refusal raises `ValueError` with `workflow '<key>':` first, as `_rollout` does. Call `_release` in `render` so that `jobs = (*_rollout(...), *_release(...), *workflow.jobs)`. `artifacts` is read for it as `binds` reads it today.
- [ ] **Step 4: Run them, then the gates.**
  - The new tests and `test_refusal_census.py`.
  - The full suite to `<workspace>/t3.log`.
  - `./simplon.sh support workflows --check`. Expected: simplon's own workflows unchanged (its release is `handwritten:`).
  - mypy (`deploy/orchestrator/.venv/bin/python -m mypy` as the repo's `test typecheck-python` runs it).
- [ ] **Step 5: Commit.** Message: `feat(si#490): the release job - the aggregate's plan as steps, with the cut, the stamp and the dry run derived`.

### Task 4: How a release is finished

**Files:**
- Modify:
  - `src/site/content/how/manifest.md` (a `release:` paragraph beside `flow:`);
  - the releasing page. Find whether `how/releasing.md` exists: if it does, add a section; if not, create it with front matter copied from a sibling `how/` page, and add it to whatever index or menu lists the siblings.
  - `src/site/content/with-what/rules.md` only if Tasks 1–2's page test did not already settle it.
- Test: the existing docs tests (`test_tasks_docs`, the site link check through `build docs`, which is always docker per memory).

- [ ] **Step 1: Write the section.** Write the six half-release cases from the spec, each with how it is finished. Say that a re-run is safe (draft reused, a tag at the same commit resumed, one publish), and which cases `release:check` (si#487) will shorten. Name the `token:` and `publishes:` fields and what forgetting `publishes:` costs.
- [ ] **Step 2: Run the docs gates.** Run `./simplon.sh build docs` (docker Hugo) and the docs tests. Expected: green apart from the 3 known failures. No dead internal link.
- [ ] **Step 3: Commit.** Message: `docs(si#490): how a dispatch release is declared, and how a half-finished one is finished`.

After Task 4: the final whole-branch review, then push and a PR with `Closes #490`.
