# si#486 GitHub Release coordinates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three catalogue coordinates, `release:github-unpublished`, `release:github-draft` and
`release:github-publish`, over a PyGithub adapter, plus the kind `github-release` (which refines `release`)
as publish's output.

**Architecture:**
- `adapters/github.py` turns PyGithub into **three answers per question**: found, absent and unanswered,
  where "unanswered" is an exception that carries the reason.
- `tasks/githubrelease.py` holds the three bodies, which return rc 0/1 like `release:image`.
- The catalogue, the firn model and the generated classes are wired with `./simplon.sh build model`, as in
  si#400 4a-4c.

**Tech Stack:** Python 3.13, PyGithub 2.10.0, firn (through `build model`), pytest with an
`http.server` stand-in.

**Spec:** `docs/superpowers/specs/2026-10-17-si486-github-release-coordinates-design.md`. Read it first;
this plan argues from it.

## Global Constraints

- PyGithub is a **hard** runtime dependency: `"PyGithub>=2.10.0,<3"`, with a house-form reason comment in
  `pyproject.toml` (see Task 1).
- **No `vX.Y.Z` check** anywhere in these three. A tag is valid iff `gitops.valid_tag_name(tag)`.
- **No evidence port** on `release:github-publish`.
- The token comes only from `githubpackages.token()`: never an argument, never a file.
- **Repository and API base:** `GITHUB_REPOSITORY` and `GITHUB_API_URL` win when set. Otherwise both come
  from origin's URL: `github.com` maps to `https://api.github.com`, any other host to
  `https://<host>/api/v3`.
- **A 404 is "absent" only after `GET /repos/{r}` answered 200.**
- A **published** release is never modified. Two or more drafts for one tag are refused, naming every URL.
- The coordinates are **offered, not placed**, and all three are `unattended: true`.
- Run Python through `deploy/orchestrator/.venv/bin/python`. Three `test_tasks_docs` failures are
  root-bound and pre-existing; name them if they show, do not fix them.
- Commits use `GIT_AUTHOR_*` and `GIT_COMMITTER_*` = `Marco Zwyssig <marco@zwyssig.info>` per commit, and a
  heredoc message ending in the two attribution lines.

## Review Focus

1. **Reusing a draft must not publish it.** PyGithub's `GitRelease.update_release(name, message,
   draft=False, …)` defaults `draft` to **False** (read at `github/GitRelease.py:286`, 2.10.0). A reuse that
   omits `draft=True` publishes the draft before the build. Task 2 pins it: after a reuse, the stand-in's
   PATCH body has `"draft": true`.
2. **A token without access reads as "no release".** GitHub answers 404 for an invisible repository.
   Task 1 pins that a 404 on `/repos/{r}` raises `Unanswered`.
3. **PyGithub retries silently.** `Github(retry=default_retry)` retries 5xx responses, so a 500 test would
   take long or pass by luck. Construct it with `retry=None` and `timeout=30`; Task 1 pins that one 500
   gives exactly one request.
4. **An SSH origin URL and a GitHub Enterprise host.** `git@github.com:o/n.git`, `https://github.com/o/n`
   (no `.git`, trailing slash) and `https://ghe.example/o/n.git` must all parse. Task 1 pins each.
5. **Publish's answer, not its status.** A PATCH can answer 200 with `draft` still true (a proxy, a race).
   Success is `release.draft is False` on the returned object. Task 2 pins it with a stand-in that answers
   200 but keeps `draft: true`.

---

### Task 1: The dependency and the adapter `simplon/adapters/github.py`

**Files:**
- Modify: `pyproject.toml` (`dependencies`, after `jinja2`)
- Create: `src/simplon/adapters/github.py`
- Create: `src/tests/githubstandin.py`, the shared stand-in (test helper, not a test module)
- Test: `src/tests/test_adapters_github.py`
- Modify: `src/firn/model/simplon/components/components.firn`. Add `module m_adapters_github` with
  `path = "adapters.github"`, next to the other adapters; it is the architecture census.

**Interfaces:**
- Produces:
  - `class Unanswered(Exception)`: its `str()` is the full user-facing reason.
  - `locate(origin_url: str) -> tuple[str, str] | None`: `(owner/name, api_base)` from an origin URL, or
    None when it is not a GitHub URL.
  - `repository() -> github.Repository.Repository`: resolves token, repository and API base, and proves the
    repository is visible. Raises `Unanswered`.
  - `published(repo, tag: str) -> GitRelease | None`: the published release, None for a 404. Raises
    `Unanswered` for anything else.
  - `releases_for(repo, tag: str) -> list[GitRelease]`: every release (draft or published) whose
    `tag_name == tag`. It reads at most 10 pages of 100, and raises `Unanswered` past the bound or on any
    error.
  - Stand-in (`githubstandin.py`): `serve(state: dict) -> tuple[str, Callable[[], None]]` starts a
    `ThreadingHTTPServer` on 127.0.0.1:0 and returns `(base_url, stop)`. Its `state` holds:
    - `repo`: `{"full_name": "o/n"} | None`; None means 404 on `/repos/o/n`;
    - `releases`: a list of dicts with `id`, `tag_name`, `draft`, `body`, `name`, `html_url`;
    - `fail`: `{(method, path_prefix): status}`, a forced status;
    - `requests`: a list of `(method, path, json_body)` the stand-in appends to.

    It serves:
    - `GET /repos/o/n`;
    - `GET /repos/o/n/releases/tags/{t}`, which answers published releases only;
    - `GET /repos/o/n/releases?per_page&page`;
    - `POST /repos/o/n/releases`;
    - `PATCH /repos/o/n/releases/{id}`;
    - and it gives each release `url` and `html_url` built from its own base.

    Pattern: `src/tests/test_fetch.py:91,295`.

- [ ] **Step 1: Add the dependency and install it**

Add to `dependencies` in `pyproject.toml`:

```toml
  "PyGithub>=2.10.0,<3", # the GitHub Release coordinates (si#486). A HARD dependency by Marco's decision of
                         # 2026-10-17, not an extra: release:github-* are kernel tasks. Brings pynacl,
                         # requests, pyjwt[crypto], typing-extensions and urllib3. Measured on PyPI that day,
                         # each has a wheel for every platform the kernel installs on (PyNaCl 1.6.2 ships
                         # cp38-abi3-win_arm64; the rest are py3-none-any; pyjwt's crypto extra is the
                         # cryptography already floored above). 3.x is PyGithub's announced break (lazy
                         # by default), so the major is the ceiling.
```

Run: `deploy/orchestrator/.venv/bin/pip install -q -e '.[typecheck,report]' && deploy/orchestrator/.venv/bin/python -c "import github; print(github.__version__ if hasattr(github,'__version__') else 'ok')"`
Expected: it prints without an ImportError.

- [ ] **Step 2: Write the failing tests**, in `src/tests/test_adapters_github.py`

```python
@pytest.mark.parametrize("url, expected", [
    ("https://github.com/o/n.git", ("o/n", "https://api.github.com")),
    ("https://github.com/o/n/", ("o/n", "https://api.github.com")),
    ("git@github.com:o/n.git", ("o/n", "https://api.github.com")),
    ("ssh://git@github.com/o/n.git", ("o/n", "https://api.github.com")),
    ("https://ghe.example/o/n.git", ("o/n", "https://ghe.example/api/v3")),
    ("git@ghe.example:o/n.git", ("o/n", "https://ghe.example/api/v3")),
    ("/srv/git/n.git", None),
    ("", None),
])
def test_locate_reads_repository_and_api_base_from_origin(url, expected):
    assert github.locate(url) == expected

def test_set_variables_win_over_origin(monkeypatch, standin): ...
    # GITHUB_REPOSITORY=o/n and GITHUB_API_URL=<standin base>, with origin set to an unrelated
    # github.com URL; repository().full_name == "o/n" and the stand-in saw GET /repos/o/n

def test_a_non_github_origin_with_no_variable_names_both_variables(monkeypatch, tmp_path): ...
    # pytest.raises(github.Unanswered) and both "GITHUB_REPOSITORY" and "GITHUB_API_URL" in str(e)

def test_a_repository_the_token_cannot_see_is_unanswered_not_absent(monkeypatch, standin): ...
    # state["repo"] = None; pytest.raises(github.Unanswered) from repository(), and "o/n" in str(e)

def test_a_404_on_the_tag_lookup_is_absent(monkeypatch, standin): ...
    # one draft for v1.0.0; published(repo, "v1.0.0") is None

def test_a_500_on_the_tag_lookup_is_unanswered_and_asked_once(monkeypatch, standin): ...
    # fail[("GET", "/repos/o/n/releases/tags")] = 500; raises Unanswered with "500" in str(e);
    # exactly one GET to that path in state["requests"]

def test_a_refused_connection_is_unanswered(monkeypatch): ...
    # GITHUB_API_URL=http://127.0.0.1:<a port nothing listens on>; repository() raises Unanswered

def test_releases_for_finds_drafts_and_published_by_tag(monkeypatch, standin): ...
    # two releases with tag v1.0.0 (one draft, one published) and one with v0.9.0; len == 2

def test_releases_past_the_page_bound_is_unanswered(monkeypatch, standin): ...
    # 1001 releases, none with the tag; raises Unanswered with "1000" in str(e)
```

The test environment has `GITHUB_TOKEN=t` set through `monkeypatch.setenv`, so `token()` never shells out
to `gh`. The `standin` fixture calls `serve`, sets `GITHUB_API_URL` and `GITHUB_REPOSITORY=o/n`, and stops
the server on teardown.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_adapters_github.py`
Expected: FAIL, with an ImportError of `simplon.adapters.github`.

- [ ] **Step 4: Implement `src/simplon/adapters/github.py`**

- **Construction:** `Github(auth=Auth.Token(githubpackages.token()), base_url=api, timeout=30, retry=None)`.
- **Making `get_repo` ask.** Measure whether `get_repo(name)` alone issues the GET in 2.10.0. If it does
  not, read one attribute (e.g. `.id`). Whichever way, the stand-in test proves the GET happens.
- **Error mapping:**
  - `UnknownObjectException` on the tag lookup means None.
  - `GithubException` elsewhere means `Unanswered(f"... HTTP {e.status}: {message} {errors}")`.
  - `requests.exceptions.RequestException` means `Unanswered("could not reach <api>: ...")`.
- **Origin:** read with `gitops._git(["config", "--get", "remote.origin.url"])` after
  `gitops.configure(context.current().root)`, or add a public `gitops.origin_url() -> str` if a test needs
  it. The builder's call; a public helper is preferred over a private reach.
- **Docstring:** state the three answers, and why a 404 needs the repository first.
- **`GH_TOKEN`:** read si#479's change (`git log --grep="si#479"`) first. If the kernel already treats
  `GH_TOKEN` as a token source somewhere, `githubpackages.token()` learns it too, with a test. If not, leave
  `token()` alone. Either way, the `Unanswered` message for a missing token names the variables it read.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_adapters_github.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/simplon/adapters/github.py src/tests/githubstandin.py src/tests/test_adapters_github.py src/firn/model/simplon/components/components.firn
git commit   # feat(si#486): adapters.github - found, absent or unanswered, over PyGithub
```

### Task 2: The bodies, `simplon/tasks/githubrelease.py`

**Files:**
- Create: `src/simplon/tasks/githubrelease.py`
- Test: `src/tests/test_tasks_githubrelease.py`
- Modify: `src/firn/model/simplon/components/components.firn`, adding `module m_tasks_githubrelease` with
  `path = "tasks.githubrelease"`.

**Interfaces:**
- Consumes: Task 1's `repository`, `published`, `releases_for`, `Unanswered`, and the stand-in.
- Produces (the bodies the catalogue names in Task 3):
  - `unpublished(tag: str = "") -> int`
  - `draft(name: str = "", tag: str = "") -> int`, where `name` is the `release-notes` artifact
  - `publish(tag: str = "") -> int`

**Refusals.** Usage errors raise `ValueError` before any call, as `releasenotes.write` does:
- an empty tag;
- a tag failing `gitops.valid_tag_name`;
- no `name`;
- an unknown artifact, read through `artifactsection.entry(..., "release:github-draft")`.

Run-time outcomes are `log.error` plus `return 1`.

- [ ] **Step 1: Write the failing tests**

Fixtures: a git repository via `_repo`/`_commit` and a manifest via `_manifest`, in the shape of
`src/tests/test_tasks_releasenotes.py:70-79`. The manifest declares
`notes: { kind: release-notes, path: build/release/notes.md }`. The stand-in comes from Task 1.
`gitops.remote_tag_commit` is monkeypatched where origin is involved; a test repository has no origin.

```python
def test_unpublished_is_green_for_none_and_for_a_draft(...)        # rc 0 both, "no published release" logged
def test_unpublished_refuses_a_published_release(...)               # rc 1, html_url in the log
def test_unpublished_is_red_when_the_api_does_not_answer(...)       # repo 404 -> rc 1; tag lookup 500 -> rc 1
def test_draft_is_created_at_head_with_the_notes_as_body(...)       # POST body: tag_name, name=tag, body=notes text,
                                                                    # draft True, target_commitish == gitops.head_commit()
def test_draft_reuse_replaces_the_body_and_stays_a_draft(...)       # existing draft -> one PATCH with "draft": true and the
                                                                    # new body; no POST; len(releases) unchanged
def test_draft_reuse_with_the_tag_already_on_origin(...)            # remote_tag_commit -> head sha; same as reuse
def test_draft_refuses_a_published_release(...)                     # rc 1, no POST, no PATCH
def test_draft_refuses_two_drafts_and_names_both(...)               # rc 1, both html_urls in the log, no write
def test_draft_refuses_missing_and_empty_notes(...)                 # missing file and "" -> rc 1, "release:notes" in the log,
                                                                    # and NOT "previous" (si#477 made firn's hint false)
def test_publish_turns_the_draft_public(...)                        # PATCH with "draft": false and tag_name; rc 0; html_url logged
def test_publish_checks_the_answer_not_the_status(...)              # stand-in answers 200 but keeps draft True -> rc 1
def test_publish_500_leaves_the_draft_and_says_a_rerun_finishes(...)  # rc 1, "re-run" in the log, release still draft
def test_publish_refuses_without_the_tag_on_origin(...)             # remote_tag_commit "" -> rc 1, "default branch" in the log;
                                                                    # None -> rc 1; neither touches the API
def test_publish_refuses_when_there_is_no_draft(...)                # rc 1, "release:github-draft" in the log
def test_publish_on_an_already_published_release_is_rc_1(...)       # rc 1, "nothing was changed", no PATCH
def test_an_invalid_tag_is_refused_before_any_request(...)          # ValueError for "", "a..b"; state["requests"] == []
```

Pin each message substring against the real text once it is written (the CLAUDE.md "quoted error text"
rule).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_tasks_githubrelease.py`
Expected: FAIL, with an ImportError.

- [ ] **Step 3: Implement the three bodies**

The order of checks, from the spec:
- `publish` asks git **before** the API.
- `draft` reads the notes **before** the API.
- **Reuse:** `update_release(name=tag, message=notes, draft=True)`.
- **Create:** `create_git_release(tag, name=tag, message=notes, draft=True, target_commitish=gitops.head_commit())`.
- **Publish:** `update_release(name=release.title, message=release.body, draft=False, tag_name=tag)`, then
  check `.draft is False` on the result.
- **Classifying the matches:** with `releases_for`, any published release among the matches means
  "published"; two or more drafts mean the refusal.

The module docstring carries the spec's "three moments" table in prose, and records that firn's
`ghrelease.py` is the reference this replaces.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_tasks_githubrelease.py src/tests/test_adapters_github.py`
Expected: all pass.

- [ ] **Step 5: See it red.** Remove `draft=True` from the reuse call. Expected:
  `test_draft_reuse_replaces_the_body_and_stays_a_draft` fails. Restore it.

- [ ] **Step 6: Commit**: `feat(si#486): release:github-unpublished/-draft/-publish bodies`

### Task 3: The catalogue, the model, the kind and the generated classes

**Files:**
- Modify: `src/firn/model/simplon/vocabulary/kinds.firn`. Add `github_release typeOf
  simplon.pipeline.ArtifactKind { refines = simplon.vocabulary.release }`, after `release`, with no fields.
- Modify: `src/firn/model/simplon/catalogue/tasks.firn`. Add three `CatalogueTask` instances after
  `release_tag`:
  - `release_github_unpublished`: no ports;
  - `release_github_draft`: `input release_notes { accepts = simplon.vocabulary.release_notes; param = "name";
    needs = simplon.vocabulary.artifact.f_path }`;
  - `release_github_publish`: `output github_release { accepts = simplon.vocabulary.github_release }`.

  Each has `body = "simplon.tasks.githubrelease:<fn>"`.
- Modify: `src/simplon/catalogue.yaml`, in the handwritten region after `release:tag`: three entries with
  `help:`, `unattended: true`, and `params: tag: { help: "the tag exactly as it exists or will exist (e.g.
  v1.4.0)", metavar: "TAG" }`; draft also takes `name: { help: "the release-notes artifact whose text is the
  body (normally bound with \`consumes:\`)" }`. Above them goes one comment block, in `release:tag`'s voice:
  offered, not placed, and why there are three moments.
- Generated by `./simplon.sh build model`:
  - `src/simplon/model/artifactschema.py` (REFINES, PORTS, BODIES and the entry class);
  - `src/simplon/tasks/release_github_{unpublished,draft,publish}.py`;
  - the kinds table in `src/site/content/with-what/kinds.md`;
  - the catalogue's kinds header.
- Test: `src/tests/test_catalogue_ports.py:22-44`, the pinned PORTS literal.

**Interfaces:**
- Consumes: Task 2's three body functions.
- Produces:
  - the coordinates `release:github-unpublished`, `release:github-draft` and `release:github-publish`;
  - the kind `github-release` (`REFINES["github-release"] == "release"`).

- [ ] **Step 1: Write the failing test.** Extend the PORTS literal in `test_catalogue_ports.py` with:

```python
        "release:github-draft": (P("release-notes", "input", "release-notes", "name", ("path",)),),
        "release:github-publish": (P("github-release", "output", "github-release", "", ()),),
```

`release:github-unpublished` has no ports, so it appears in BODIES but not in PORTS. That matches the
template's `if t.input or t.output` guard (si#400 4a).

- [ ] **Step 2: Run the test to verify it fails**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_catalogue_ports.py`
Expected: FAIL on the PORTS literal.

- [ ] **Step 3: Edit the firn sources and `catalogue.yaml`, then generate**

Run: `./simplon.sh build model`
Expected: it ends green. The three `release_github_*.py` files exist, and their `.imports` regions import
the Task 2 bodies.

- [ ] **Step 4: Verify**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests/test_catalogue_ports.py src/tests/test_generated_schema.py src/tests/test_refusal_census.py src/tests/test_architecture.py src/tests/test_architecture_page.py && ./simplon.sh test model && ./simplon.sh test generated`
Expected: all green. If the census reports a new refusal, classify it, but the spec expects none. If it
reports one, stop and record it.

- [ ] **Step 5: Commit**: `feat(si#486): the three coordinates and the kind github-release in the catalogue`

### Task 4: What "refines release" touches, the second sources, and the docs

**Files:**
- Test: `src/tests/test_release_bundle.py` (the existing home of bundle tests)
- Modify, only if the test in Step 1 is red: `src/simplon/manifest/manifestmodel.py:257-266`
- Modify: `src/simplon/tasks/asset.py:7-13` and `src/simplon/catalogue.yaml:644-646`, rewording the
  dependency argument
- Modify: `src/site/content/with-what/phases.md`, the release list (8 → 11 tasks) and the paragraph after it
- Modify: `src/site/content/with-what/rules.md` and `src/site/content/how/manifest.md`, if they enumerate
  release coordinates (grep `release:tag`)

**Interfaces:**
- Consumes: Task 3's coordinates and kind.

- [ ] **Step 1: Write the tests for the measured consequences**, each over a small manifest:

```python
def test_a_github_release_produced_by_a_leaf_is_in_the_model_export(...)
    # a `release publish` command (task release:github-publish, produces: { github-release: gh })
    # named by no aggregate; the firn model export contains `gh`
    # (manifestmodel's export entry point, as the existing export tests call it)

def test_an_aggregate_may_name_a_github_release_as_its_bundle(...)
    # `release all` with produces: { release: gh } (kind github-release) loads (ports.py:238 by refinement)

def test_the_aggregate_and_its_publish_leaf_producing_one_github_release(...)
    # the aggregate's bundle == the leaf's output: MEASURE. Assert whatever the loader does today
    # (loads, or refuses with message X), and name the test for what it found
```

- [ ] **Step 2: Run them.** If the export test is red (the `manifestmodel.py:265` skip drops it), compose a
  leaf-produced `github-release` there. A release-refining artifact that **no aggregate names** is exported as
  an `Artifact`. Re-run until green.

- [ ] **Step 3: Record the one-producer finding on si#489**, as a comment through `--body-file`: what the
  loader did, with the message quoted. Do not change the rule here.

- [ ] **Step 4: Reword the second sources.**
  - `asset.py` and `catalogue.yaml:644-646`: `release:asset` stays on `gh` because create-if-absent and
    replace-if-present are one flag each there. The kernel **has** a GitHub client since si#486 (Marco,
    2026-10-17), so the dependency argument is withdrawn, not restated. Moving `release:asset` onto
    `adapters.github` is not done.
  - `phases.md`: list the three new coordinates and say in one sentence what each moment is for.
  - **Consequence 3 (`ports.py:320` `OWN_KINDS`):** a comment there says that `github-release` matches by
    refinement, so rule 6 would ask no test result about it. Also comment on si#449, because the first
    consumer of the kind inherits that.

- [ ] **Step 5: Verify the whole branch**

Run: `deploy/orchestrator/.venv/bin/python -m pytest -q src/tests && deploy/orchestrator/.venv/bin/python -m mypy src/simplon && ./simplon.sh test model && ./simplon.sh test generated`
Expected: green, apart from the three named pre-existing `test_tasks_docs` failures if they appear (name
them). mypy is clean, since PyGithub ships `py.typed`.

- [ ] **Step 6: Commit**: `feat(si#486): github-release refines release, measured; asset's dependency argument withdrawn; docs`

## Not in this plan (spec non-goals)

- `release:check` (si#487);
- rule 8 (si#489);
- `workflows: release:` (si#490);
- moving `release:asset`;
- a consumer of `github-release` (si#449);
- release notes, which are written at the next cut.
