# si#486: the GitHub Release coordinates (`release:github-unpublished`, `-draft`, `-publish`)

Part of si#463. Decisions: si#463 comment 6231282127 (D1, D1b) and this session's choice lists of
2026-10-17. Measured on main b70ca47.

## Intent

A release started from GitHub Actions (si#463) needs three moments around a GitHub Release, and the kernel
offers none of them today. `release:asset` creates a release only to attach files, with a constant body
from `assets:`, and it knows no draft. firn built the three moments as a product module
(`orchestrator/ghrelease.py`, 235 lines, branch `chore/1039-simplon-0.32`, read in full for this spec) and
is not merging it: the day the catalogue has them, that module goes (firn#1040).

The three moments, one coordinate each, and each with its own ports, `unattended:` and help:

| Coordinate | When in the flow | What it does |
|---|---|---|
| `release:github-unpublished <tag>` | before anything is built, when origin may already carry the tag | rc 0 when the tag has **no published** release (a draft or none), rc 1 when it has one, **and rc 1 when the API did not answer** |
| `release:github-draft <tag>` | before the build | creates the **draft** release with the notes as its body, or reuses a draft an earlier run left and replaces its body |
| `release:github-publish <tag>` | after the image push | publishes the draft. It refuses when origin does not carry the tag. It produces a `github-release` artifact |

## Goals

- The three coordinates in the catalogue, with bodies built on **PyGithub** (decided). firn's module can then
  be deleted.
- Every outcome tells "nothing to do", "done" and "failed" apart. In particular, a question the API did not
  answer is **never** read as "no release" (the house defect).
- Tests against a **local HTTP stand-in for the GitHub API**, through every failure point firn listed (see
  Acceptance).

## Non-goals

- `release:check`, the `vX.Y.Z` pattern and the from-main check belong to si#487.
- Rule 8 belongs to si#489, and the workflow key `workflows: release:` to si#490.
- Uploading assets. `release:asset` stays as it is (on `gh`); moving it onto the new adapter is not this
  ticket.
- A dry run. It is GitHub-level `if:` (D2), so the bodies have no dry-run parameter.
- A consumer of the new `github-release` kind (si#449 comes later).

## Anti-goals

- **No tag-pattern check in these three** (decided). They accept any tag `gitops.valid_tag_name` accepts. The
  fixed `vX.Y.Z` is a property of the dispatch flow (si#487/si#490), so that cleon, whose release tags are
  build stamps (`0.4.149.v20260907-1652-524d4cb`), can use the coordinates on their own.
- **No evidence input on `release:github-publish`** (decided). It publishes nothing that was built; it makes a
  draft public. The evidence sits on `release:image`. Under today's rule 8, an evidence input would also make
  every aggregate holding both `release:tag` and `release:github-publish` unloadable until si#489.
- The token is never an argument and never comes from a file (`githubpackages.token` docstring).

## Decided shape

### Catalogue

These coordinates are **OFFERED, not placed**, for `release:tag`'s reason (`catalogue.yaml`, the comment on
`release:tag`): each is one leaf of a release, it publishes, and a product without a GitHub release has
nothing waiting for it. All three are `unattended: true`, like every other `release:*` coordinate.

Each takes the param `tag`, the tag exactly as it exists or will exist, help text as on `release:notes`.
Ports, in the generated `artifactschema.PORTS` form:

```
"release:github-unpublished": (),
"release:github-draft": (
    Port("release-notes", "input", "release-notes", "name", ("path", )),
),
"release:github-publish": (
    Port("github-release", "output", "github-release", "", ()),
),
```

- `release:github-draft` reads the notes through the bound artifact's `path:`. The port's param is `name`,
  as on `release:notes`' output, so the body receives the artifact's name. Unlike `release:tag`'s port
  (param `""`), this one has to read the text.
- `release:github-publish` produces the new kind with param `""`, like `release:tag`'s `tag` output.

### The new kind `github-release`, which refines `release` (decided)

It goes in `src/firn/model/simplon/vocabulary/kinds.firn`, with **no fields**: the URL follows from
repository and tag at run time, and a declaration has nothing to state. A GitHub Release therefore **is** a
release bundle: `artifactsection.accepts(kinds, "release", "github-release")` is true, so an aggregate may
name a `github-release` artifact as its `release:`.

Measured consequences, which the plan must handle and test:

1. **`manifest/manifestmodel.py:265` skips every release-refining artifact** in the model export ("composed
   inside the aggregate that names it"). A `github-release` artifact produced by a leaf and named by **no**
   aggregate would then be missing from the firn model. Either compose it where it is produced, or measure
   that the export still holds it. Do not let it drop silently.
2. **`manifest/load.py:905-913`**: an aggregate's `produces` must be exactly `release:` with one artifact. If
   that artifact is the same `github-release` that its member `release:github-publish` produces, then **two
   commands produce one artifact**. Measure whether a one-producer rule refuses that, and what message it
   gives. Whether "the aggregate's bundle is its publish leaf's output" is to be allowed is si#489/si#490's
   question. **This ticket must not decide it by accident**, so the plan records the measured behaviour on
   si#489.
3. **`manifest/ports.py:320` `OWN_KINDS`** is matched by refinement, so `github-release` counts as a kind a
   release produces about itself, and rule 6 would ask no test result about it. Rule 6 looks only at
   *consumed* artifacts, though, and nothing consumes `github-release` in this ticket. So record it (in the
   kind's docstring and on si#449), and do not invent a consumer to pin it.
4. `manifest/ports.py:238`, the bundle-kind check, accepts it by refinement. Pin that too.

The census: the new kind adds no load-time refusal of its own. Run `tests/test_refusal_census.py` and see.

### Adapter `src/simplon/adapters/github.py`

It is built on PyGithub, imported at module level like any hard dependency.

- **Token:** `adapters/githubpackages.token()`, which reads `GITHUB_TOKEN`, then `gh auth token`. firn also
  reads `GH_TOKEN`. Whether `token()` should learn `GH_TOKEN` is the builder's measurement, so check si#479
  (cmd `GH_TOKEN`) first. Either way there is one token function for the kernel, not a second one. In the
  kernel image `gh auth token` has no login (the `tracker.py:337-345` comment), so the container route
  depends on the forwarded variables, and the refusal must say which ones it read.
- **Repository and API base (decided by Marco: derive from origin).** The container route's launcher forwards
  `GITHUB_TOKEN` and `GH_TOKEN` but **not** `GITHUB_REPOSITORY` or `GITHUB_API_URL` (`launch.sh.j2:242-258`).
  So:
  - A set `GITHUB_REPOSITORY` / `GITHUB_API_URL` wins. That covers the venv route in Actions and the tests.
  - Otherwise both come from origin's URL (HTTPS or SSH form): `owner/name` from the path, and the API base
    from the host. `github.com` maps to `https://api.github.com`. **Amended during the build:** the first
    draft also mapped any other host to `https://<host>/api/v3` (GitHub Enterprise). The commit security
    review showed that this hands the github.com token to whatever host a checkout's remote names, against
    `githubpackages`' "to GitHub, and to nowhere else". So an Enterprise host is named only by
    `GITHUB_API_URL`, and on the container route it is carried in by `launcher: env: pass:`.
  - An origin that is not a github.com URL, with neither variable set, refuses and names both variables
    and the launcher pass.
  - There is no launcher change.
  - The API base is passed to PyGithub as `base_url`.
- **Visibility first.** GitHub answers **404** for a repository the token cannot see, a misspelled repository
  and a wrong host alike. So a 404 on a release lookup is trusted **only after** the repository itself
  answered 200 (`GET /repos/{r}`, a non-lazy `get_repo`). A 404 or 401/403 on the repository is "unanswered",
  and the message names the repository, the API base and the token's source. This is the house rule applied
  at the first seam.
- **Timeout:** one bounded timeout per call (firn uses 30 s), so a hung connection does not hold the runner.
  PyGithub's own retry is left off, or bounded, as measured.
- **Lookups:**
  - The **published** release for a tag is one GET of `/releases/tags/{tag}` (`get_release(tag)`). It answers
    published releases only, so a 404 means a draft or none.
  - A **draft** cannot be reached by tag, so the release list is read (`get_releases()`, paged), looking for
    `tag_name == tag`. Bound it as firn does (ten pages of 100). Reaching the bound is a refusal, never "none".
  - **More than one release with the tag** (my call): if any of them is published, the published one wins,
    so `draft` and `publish` refuse it as published. Two or more drafts are refused, and the message names
    every URL so a person deletes the extras. The kernel does not choose one. The per-version concurrency
    group (si#490) should make this unreachable in the flow; it is not reachable by assumption, though.
- **Errors:** PyGithub raises `GithubException` (with `.status`) and `UnknownObjectException` (404), and
  network failures surface as `requests` exceptions. The adapter maps them onto **three answers: found, absent
  and unanswered**. Only a 404 on the tag lookup is "absent". Every other exception is "unanswered", and its
  message carries the status and GitHub's `message`/`errors` (firn's `_said`).

### Bodies, `src/simplon/tasks/githubrelease.py` (name the builder's call; it must not collide with a generated class file)

**`unpublished(tag)`**

| Tag lookup | Result |
|---|---|
| 404 | `log.ok`, rc 0: "no published release; an unfinished release may finish" |
| 200 | rc 1, with the `html_url`: "a published release is never overwritten; choose the next version" |
| anything else | rc 1, "could not tell whether … is published: HTTP …" |

**`draft(name, tag)`**

1. Read the notes from the `release-notes` artifact `name`'s `path:`, as `releasenotes.write` resolves it
   through `artifactsection.entry`. A missing or empty file refuses, and the message says to run
   `release:notes` before the tag is cut. (Since si#477 the range is right even with the tag present, so
   firn's hint "once the tag exists it is the previous one" is no longer true. **Do not copy it.**)
2. Find the release for the tag (list).
   - Published: refuse, and make no draft.
   - Draft: update `body` and `name`, then rc 0, saying "reused".
   - None: create it with `draft=True`, `name=tag`, `body=notes` and `target_commitish = gitops.head_commit()`,
     then rc 0, saying "created".
   - Unanswered: rc 1.
3. `target_commitish` comes from **`gitops.head_commit()`**, not from `GITHUB_SHA` as in firn (builder's
   call, marked as mine). It is the same commit in a dispatch run, and it is also right by hand.

**`publish(tag)`**

1. Origin must carry the tag. Ask with `gitops.remote_tag_commit(tag)`, the tri-state used by `release:tag`
   and si#487:
   - `""` refuses: "publishing would create it at the default branch's head".
   - `None` (could not ask) refuses.
   - Using git rather than the API's `git/ref` is my call, so that "origin carries" has one meaning in the
     kernel.
2. Find the release (list).
   - None: refuse, naming `release:github-draft`.
   - Already published: rc 1, "nothing was changed". It is not rc 0, because a publish step that finds the
     work done by someone else is not this run's publish, and in the flow it means a re-run raced a person.
     Revisit if the half-release cases say otherwise.
   - Unanswered: rc 1.
3. Update with `draft=False` and `tag_name=tag`. Success is asserted on the **answer** (`draft` is false),
   not on the status alone. On failure the message says it stays a draft and that a re-run publishes it.
4. Log the `html_url`. The `github-release` output port is satisfied by the act; there is no file to write.

Every refusal raises `ValueError` before any call where it is a usage error (an empty tag, an invalid tag,
an unknown artifact), like `releasenotes.write`. Run-time outcomes are `log.error` plus rc 1, like firn and
`release:image`.

### `pyproject.toml`

PyGithub is a **hard runtime dependency (decided by Marco)**, not an extra like `typecheck`. Add
`"PyGithub>=2.x,<3"` (the floor is the version verified against, measured 2.10.0) with a reason comment in
the house form:

- what it is for, and why the major is the boundary;
- the five transitive requirements;
- the platform measurement, made on PyPI on 2026-10-17. requests, urllib3, PyJWT and PyGithub ship
  `py3-none-any` wheels. PyNaCl 1.6.2 ships `cp38-abi3-win_arm64` among its 25 wheels. `pyjwt[crypto]`
  needs cryptography, which is already a dependency (≥46 for win_arm64). So no platform the kernel installs
  on today is lost. The kernel image picks it up through the wheel; check `deploy/image` installs no
separate requirements.

### Second sources that become false

- **`tasks/asset.py:7-13` and `catalogue.yaml:644-646`** argue against a GitHub client in the kernel's
  dependencies ("A GitHub client in the KERNEL's dependencies is not twenty lines"). After this ticket the
  kernel *has* one. Reword both: `release:asset` stays on `gh` because create-if-absent and
  replace-if-present are one flag each there, and because moving it is not this ticket. The dependency
  argument is withdrawn, with Marco's decision of 2026-10-17 named as the reason.
- **`adapters/portainer.py:31-32`** says "without an extra dependency". That is still true for portainer; leave
  it.

## Acceptance

Each assertion is seen red: break the property and watch it fail.

1. A draft is created when there is none. `target_commitish` is HEAD, the body is the notes file.
2. A draft is reused after a failed build: its body is replaced, and no second draft appears.
3. A draft is reused with the tag already on origin.
4. A publish that gets HTTP 500 leaves the draft, and the message says a re-run publishes it.
5. A published release is refused by all three coordinates.
6. An unanswered GET is red for all three, and never read as "unpublished" or "none". The cases:
   - a connection refused;
   - a 500 on the lookup;
   - a list beyond the page bound;
   - **a 404 on the repository itself** (a token without access, or a misspelled repository).
6a. Two drafts for one tag are refused, naming both. A draft beside a published release is treated as
    published.
6b. Repository and API base are derived from a github.com origin, in the HTTPS and the SSH form. A set
    variable wins over origin. Any other origin with no variable refuses, an Enterprise host included
    (amended, see above).
7. A publish without the tag on origin is refused, both when `remote_tag_commit` is `""` and when it is
   `None`.
8. Empty or missing notes are refused by `draft`, with the message pinned against the real text.
9. The model and generated files are current (`build model`, `test model`, `test generated`), the catalogue
   tests are green (`BODIES` == all coordinates), the census is green, and mypy is green.
10. The `github-release` consequences 1-4 above are each pinned, or measured and recorded on si#489.
11. `with-what/phases.md` and `rules.md` (and the kinds page, if one lists kinds) name the three coordinates
    and the kind.
12. Release notes at the next cut. They are written then, not now.

The local API stand-in is an `http.server` on 127.0.0.1, with `GITHUB_API_URL` pointed at it, so that
PyGithub really speaks HTTP. That is my call over mocking PyGithub: mocking would test our assumption about
PyGithub, not its behaviour.

## Left to the builder

- The module and adapter function names.
- How the catalogue, `tasks.firn` and the generated classes are produced (`./simplon.sh build model`). The
  si#400 4a-4c plans show the route.
- Whether `token()` learns `GH_TOKEN`, measured against si#479.
- The PyGithub retry and timeout configuration, measured.
- The exact message wording, pinned by tests.
