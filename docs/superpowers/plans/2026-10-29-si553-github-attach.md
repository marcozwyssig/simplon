# si#553 `release:github-attach` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A catalogue coordinate `release:github-attach` that uploads tested files with `.sha256` sidecars to the tag's draft GitHub Release, reads GitHub's digests back, leaves the draft carrying exactly those files, and writes a `release-assets` record.

**Architecture:** A new body `attach` in `simplon/tasks/githubrelease.py` beside `draft`/`publish`, using three new asset functions in `simplon/adapters/github.py` (PyGithub). Bound file names reach the body through a new ContextVar module `simplon/manifest/bound.py`, set by the same two wrappers that already set `results.tested()` (assembled CLI and generated module). Schema (`asset_name` on `file`, kind `release-assets`, the task and its ports) goes through the firn model and `./simplon.sh build model`.

**Tech Stack:** Python 3.12+, PyGithub (pinned), pytest, the HTTP stand-in `src/tests/githubstandin.py`, firn model files under `src/firn/model/simplon/`.

**Spec:** `docs/superpowers/specs/2026-10-29-si553-github-draft-assets-design.md`

## Global Constraints

- Coordinate `release:github-attach`, body `simplon.tasks.githubrelease:attach`, `unattended: true`, `publishes: true`, `token: github`, offered, not placed.
- Ports: `files` (input, accepts `file`, `param = ""`, needs `path`), `evidence` (input, accepts `test-result`, no param), `release_assets` (output, accepts `release_assets`, `param = "assets"`, needs `path`). Param: `tag` (help and metavar exactly as `release:github-draft`'s).
- Kind `file` gains field `asset_name` (shape `text`). New kind `release_assets` (key `release-assets`) refines `release`, no fields.
- `{tag}` in `asset_name` is replaced with the task's `tag`.
- Sidecar name `<asset_name>.sha256`, content exactly `f"{hex}  {asset_name}\n"` (two spaces).
- Public URL `https://github.com/<owner>/<repo>/releases/download/<tag>/<name>`.
- Evidence subject per file: reference = product-relative path (as `test:file` writes it), id = `sha256:<hex>`.
- After a green `attach` the draft carries exactly the bound files and their sidecars; every other asset is deleted and named in the log.
- Never touch a published release; refusals before any upload go through `_one_draft`.
- Every update/upload against PyGithub names nothing that could publish: `attach` never calls `update_release`.
- English in code, docs, commits; no em dash (U+2014) anywhere.
- Commits: `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info"` and the same for `GIT_COMMITTER_*`, message via quoted heredoc, ending with the two attribution lines this session uses.
- Every task ends green on: `./simplon.sh test typecheck-python` and the task's own test files under `deploy/orchestrator/.venv/bin/python -m pytest` (run from `src/`). Schema tasks also `git add -A && ./simplon.sh test generated`.

## Review Focus

1. **A draft step that ran on another commit or in a previous run left assets with names this run no longer binds** (renamed `asset_name`, dropped platform). Expected: deleted and named, never published. Test in Task 4.
2. **A file rebuilt between `test:file` and `attach`** (same path, new bytes). Expected: refused before upload, naming both digests. Test in Task 3.
3. **An upload that succeeded but GitHub reports a different digest, or none.** Expected: red, naming the asset, saying it is on the draft and a re-run replaces it. Test in Task 4.
4. **`attach` run with no draft** (draft step skipped or failed, e.g. dry run wiring mistake). Expected: refusal naming `release:github-draft`, nothing uploaded. Test in Task 4.
5. **The same expanded `asset_name` from two entries** (e.g. `asset_name: "firn-{tag}"` copied to both platforms). Expected: refused before GitHub is asked, naming both entries. Test in Task 3.

---

### Task 0: Measure which characters GitHub rewrites in an asset name

Marco named marcozwyssig/simplon for throwaway drafts (2026-10-29). No code; the result decides Task 3's name check.

- [ ] **Step 1:** With `gh api`, create a draft release on marcozwyssig/simplon for tag `v0.0.0-si553-probe` (draft, `target_commitish` main). Upload one small file under each of these names: `a+b`, `a b`, `a~b`, `a@b`, `ä`, `a/b`, `.hidden`, `a,b`. Record for each the `name` GitHub returns.
- [ ] **Step 2:** Delete the draft (`gh api -X DELETE repos/marcozwyssig/simplon/releases/<id>`) and check `gh release list -R marcozwyssig/simplon` and `git ls-remote --tags origin v0.0.0-si553-probe` show nothing left.
- [ ] **Step 3:** Write the result as a comment on si#553 (measurement, date, the name table). Task 3 refuses exactly the characters GitHub rewrote (a diagnosis: a rewritten name makes the recorded URL wrong) and nothing else. If GitHub rewrote nothing, Task 3 refuses only `/` and an empty name.

### Task 1: Bound names reach the body (`simplon/manifest/bound.py`)

**Files:**
- Create: `src/simplon/manifest/bound.py`
- Modify: `src/simplon/cli/__init__.py:240-256` (the `_wrapped` body), `src/simplon/tasks/taskgen.py:175-200` (the rendered call) and the generated-module template it renders into (find with `grep -rn uses_results src/simplon`)
- Modify: `src/firn/model/simplon/components/components.firn`, add `module m_manifest_bound` with `path = "manifest.bound"` beside the other `manifest.*` modules; regenerate with `./simplon.sh build model`
- Test: `src/tests/test_manifest_bound.py` (new), plus one test each in `src/tests/test_cli.py` and `src/tests/test_taskgen.py`

**Interfaces:**
- Produces:
  - `bound.of(spec: object) -> dict[str, tuple[str, ...]]`: for each INPUT port of `spec.ports` with `param == ""` and `accepts != "test-result"`, the names bound to it in `spec.consumes` (absent port: not in the dict).
  - `bound.within(names: Mapping[str, tuple[str, ...]], body: Callable[[], int]) -> int`: runs `body()` with the ContextVar set, resets it after.
  - `bound.names(port: str) -> tuple[str, ...] | None`: None outside `within` (called directly, not as a command), else the port's names, `()` when the port is unbound. Two values for two answers, as `results.tested()`.

- [ ] **Step 1: Write failing tests** in `test_manifest_bound.py`: `test_names_is_none_outside_a_command`, `test_within_hands_the_bound_names_and_resets` (inside: `names("files") == ("a", "b")`, `names("other") == ()`; after: `None`), `test_of_reads_only_unparametrised_input_ports_that_take_no_test_result` (a fake spec with ports `files` (param ""), `image` (param "name"), `evidence` (test-result) and `consumes={"files": ["a","b"], "image": ["x"], "evidence": ["r"]}` gives `{"files": ("a","b")}`). In `test_cli.py`: a command whose impl reads `bound.names("files")` gets the bound tuple when invoked through the assembled CLI. In `test_taskgen.py`: the rendered call for a spec with a bound `files` port contains `_bound.within(` and the import.
- [ ] **Step 2: Run** `deploy/orchestrator/.venv/bin/python -m pytest tests/test_manifest_bound.py tests/test_cli.py tests/test_taskgen.py -q` (from `src/`). Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `bound.py`, then wrap in both places: `within` outside `guarded`, so the body sees both. Only when `of(spec)` is non-empty, like `evidence`.
- [ ] **Step 4: Run** the same tests plus `./simplon.sh build model`, `git add -A && ./simplon.sh test generated`, `./simplon.sh test typecheck-python`. Expected: green.
- [ ] **Step 5: Commit** `feat(si#553): a body reads the names bound to an unparametrised input port`

### Task 2: Asset functions in the adapter and the stand-in

**Files:**
- Modify: `src/simplon/adapters/github.py` (after `releases_for`)
- Modify: `src/tests/githubstandin.py`: serve `upload_url` on releases (pointing at the stand-in, `{base}/uploads/repos/{REPO}/releases/{id}/assets{{?name,label}}`), `GET /releases/{id}/assets`, `POST /uploads/.../assets?name=` (store bytes, return asset with `id`, `name`, `size`, `digest: "sha256:<hex>"`, 422 `already_exists` on a taken name), `DELETE /releases/assets/{id}`. Two switches in `state()`: `asset_digest` (`"real"` default, `"none"`, `"wrong"`).
- Test: `src/tests/test_adapters_github.py`

**Interfaces:**
- Produces:
  - `github.assets(release: GitRelease) -> list[GitReleaseAsset]`
  - `github.upload(release: GitRelease, path: Path, name: str) -> GitReleaseAsset` (content type `application/octet-stream`)
  - `github.delete(asset: GitReleaseAsset) -> None`
  - All three raise `github.Unanswered` for a transport failure and let `GithubException` through, as the existing functions do.

- [ ] **Step 1: Failing tests:** `test_upload_returns_the_asset_with_githubs_digest` (digest equals `"sha256:" + sha256(bytes)`), `test_uploading_a_taken_name_is_githubs_422` (raises `GithubException` with status 422), `test_assets_lists_what_was_uploaded`, `test_delete_removes_an_asset`.
- [ ] **Step 2: Run** `pytest tests/test_adapters_github.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the three functions and the stand-in routes.
- [ ] **Step 4: Run** again plus typecheck. Expected: green.
- [ ] **Step 5: Commit** `feat(si#553): adapters.github uploads, lists and deletes release assets`

### Task 3: The schema, the catalogue entry, and the refusals before GitHub

**Files:**
- Modify: `src/firn/model/simplon/vocabulary/kinds.firn`: `field f_asset_name { key = "asset_name"; shape = "text" }` on `file` (after `f_platform`); `release_assets typeOf simplon.pipeline.ArtifactKind { refines = simplon.vocabulary.release }` after `github_release`.
- Modify: `src/firn/model/simplon/catalogue/tasks.firn`: `release_github_attach` after `release_github_draft`, ports per Global Constraints.
- Modify: `src/simplon/catalogue.yaml`: entry after `release:github-draft`; the comment block above the three moments says four moments and why attach is its own (ports differ per moment, si#486; files exist only after the build, si#463 D).
- Generated by `./simplon.sh build model`: `artifactschema.py`, `tasks/release_github_attach.py` (protected region imports `attach`), architecture, kinds page. Commit them.
- Modify: `src/simplon/tasks/githubrelease.py`: module docstring gains the fourth moment; `attach` and its pre-GitHub checks.
- Test: `src/tests/test_tasks_githubrelease.py`, `src/tests/test_catalogue_ports.py` (PORTS literal), `src/tests/test_catalogue.py:196` (release namespace list), and whatever `test_generated_schema.py` pins.

**Interfaces:**
- Consumes: `bound.names("files")` (Task 1); `results.tested()`.
- Produces: `attach(tag: str = "", assets: str = "") -> int` in `githubrelease.py`; a private `_planned(tag) -> list[_Upload] | None` (or equivalent) returning per file: entry name, absolute path, product-relative path, expanded asset name, sha256 hex; None after saying why.

Refusals here, each before any GitHub call, each naming what and the way out:
- no tag / invalid tag (reuse `_tag`);
- `bound.names("files")` is None or `()` (*attach bound to no files*: "bind the files to attach with `consumes: { files: [...] }`");
- an entry with no `asset_name`;
- an `asset_name` with a character Task 0 found rewritten (or `/`, empty);
- two entries with the same expanded name (name both);
- a bound file missing on disk ("run the command that produces it first");
- evidence: `results.tested()` None ("bind the test:file results to `evidence`"); a file whose product-relative path no subject names; a subject naming it with another `sha256:` (say both digests: "the file changed after its test").

- [ ] **Step 1: Failing tests** in `test_tasks_githubrelease.py`, one per refusal above (name pattern `test_attach_refuses_<case>`), each asserting rc 1, a key phrase of the message, and that the stand-in saw no request (`shared["requests"] == []`). Plus `test_catalogue_ports` PORTS literal gains `"release:github-attach": (P("files","input","file","",("path",)), EVIDENCE, P("release-assets","output","release-assets","assets",("path",)))` and the release namespace list gains `"github-attach"`. Drive `attach` inside `bound.within({"files": (...)}, ...)` and `results.guarded(...)` with real record files written by the test, shaped as `test:file` writes them.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the model, catalogue entry, generation, and `attach` up to the first GitHub call. After the checks, `attach` raises `NotImplementedError("si#553 Task 4")`: never `return 0`, which would be a green run that attached nothing. Task 4 replaces the raise in the same branch, before anything is merged.
- [ ] **Step 4: Run** tests, `./simplon.sh build model`, `git add -A && ./simplon.sh test generated`, typecheck, `pytest tests/test_refusal_census.py -q`. If the census is red, add each new refusal with its kind (all are diagnoses: broken input with the way out).
- [ ] **Step 5: Commit** `feat(si#553): release:github-attach, asset_name and release-assets, refused before GitHub when the files are not the tested ones`

### Task 4: Upload, read back, foreign assets, the record

**Files:**
- Modify: `src/simplon/tasks/githubrelease.py`
- Test: `src/tests/test_tasks_githubrelease.py`

**Interfaces:**
- Consumes: Task 2's `assets`/`upload`/`delete`, Task 3's planned uploads, `_one_draft`, `_repository`, `github.where()` for owner/repo.
- Produces: the `release-assets` JSON at the bound artifact's path (resolve like `results.path_of`, but for kind `release-assets`; a missing `path:` is a ValueError). Shape (*builder's call within this*): `{"tag": ..., "assets": [{"name", "url_after_publish", "sha256", "sidecar": {"name", "url_after_publish", "sha256"}}]}`.

Order inside `attach` after Task 3's checks:
1. `_one_draft(repo, tag)`; unusable -> 1; None -> refusal "there is no draft release for <tag> to attach to: `release:github-draft` makes it, before the build".
2. Write sidecars under `<output>/release-assets/` (the product's output directory, as other tasks resolve it).
3. For each file then its sidecar: delete an existing asset of that name, upload, compare `asset.digest` with `"sha256:" + hex`. None or different -> red naming the asset, GitHub's answer and the local hash; say which assets are now on the draft and that a re-run replaces them.
4. Delete every asset whose name is not in this run's set; log each name.
5. Write the record; `log.ok` naming the count and the draft's `html_url`.

- [ ] **Step 1: Failing tests:** `test_attach_uploads_each_file_and_its_sidecar` (stand-in holds both, sidecar bytes exactly `"<hex>  <name>\n"`), `test_attach_replaces_an_asset_an_earlier_run_left`, `test_attach_removes_and_names_assets_it_did_not_upload`, `test_attach_refuses_without_a_draft`, `test_attach_refuses_a_published_release_and_uploads_nothing`, `test_attach_is_red_when_github_reports_another_digest` (`asset_digest="wrong"`), `test_attach_is_red_when_github_reports_no_digest` (`"none"`), `test_attach_writes_the_release_assets_record` (URL `https://github.com/<owner>/<repo>/releases/download/v1.2.3/<name>`), `test_attach_never_publishes` (no PATCH in `shared["requests"]`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file, typecheck, generated. Expected: green. See red: comment out the digest comparison, watch the two digest tests fail; restore.
- [ ] **Step 5: Commit** `feat(si#553): attach uploads, reads GitHub's digest back and leaves the draft carrying exactly the tested files`

### Task 5: End to end on a real throwaway draft

**Files:**
- Create: `src/tests/test_githubattach_e2e.py`

Opt-in: skipped unless `SIMPLON_E2E_GITHUB_REPO=marcozwyssig/simplon` and a token (`gh auth token`) are set, because it writes to a real repository. Not run in CI. The module docstring says so, and names the date and the repository Marco allowed.

- [ ] **Step 1:** Fixture: a tmp product with two `file` entries (`asset_name: "si553-{tag}-a"`, `"-b"`), two green `test:file`-shaped records naming them, a draft created through `release:github-draft`'s own `draft()` for a unique tag `v0.0.0-si553-<uuid8>`; `finally` deletes the draft and asserts no release and no remote tag remain.
- [ ] **Step 2:** Tests: `test_attach_puts_both_files_and_sidecars_on_a_real_draft` (digests via a fresh GET equal the local hashes), `test_a_rerun_replaces_and_a_foreign_asset_is_removed` (upload a third asset by hand first), `test_the_record_names_the_after_publish_urls`.
- [ ] **Step 3: Run** with the variables set. Expected: green. See red: change one file's bytes after writing its record, expect the evidence refusal.
- [ ] **Step 4: Commit** `test(si#553): attach end to end on a throwaway draft`

### Task 6: Docs and release notes

**Files:**
- Modify: `src/site/content/with-what/phases.md:282-283` (add `release:github-attach` to the list and one sentence on the fourth moment)
- Modify: `src/site/content/how/manifest.md` (the `kind: file` section: `asset_name`; mention `release-assets`)
- Modify: `src/site/content/when/releases.md`: a section `### release:github-attach attaches tested files to the draft release (si#553)` in the newest unreleased section (0.37.0 if v0.37.0 is still not tagged when this merges, else a new one), and the "gains N catalogue tasks" count in that section's opening (compute it, do not guess).
- Regenerate: `./simplon.sh build reference`.

- [ ] **Step 1:** Write the docs.
- [ ] **Step 2: Run** `./simplon.sh test release-notes`, `git add -A && ./simplon.sh test generated`, and the full `./simplon.sh test suite`. Expected: green; name any failure.
- [ ] **Step 3: Commit** `docs(si#553): release:github-attach in the phases, the manifest and the release notes`

## Not in this plan (spec non-goals)

- Changing `release:github-draft` or `release:asset`.
- Several files per entry.
- firn's workflow wiring (firn, on si#463).
- The Homebrew formula for a binary asset (si#449 F).
