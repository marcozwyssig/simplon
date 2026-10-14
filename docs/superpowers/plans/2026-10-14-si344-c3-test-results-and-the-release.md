# si#344 C.3 — the publish leaves are split, a test writes its result, and a release consumes it

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `release:nuget` and `release:maven` each become a pack task with an output port and a push task with an input port; a test writes its own `test-result` artifact; every publish leaf consumes the test results about what it publishes (rule 6); a release is an aggregate of `release:notes`, the publish leaves and `release:tag` that names one `kind: release` bundle (rule 8). simplon pays its own bill in the same branch.

**Architecture:** The catalogue's ports stay in the firn model (`src/firn/model/simplon/catalogue/tasks.firn`), generated into `artifactschema.PORTS`. Two new pack coordinates (`build:nuget-pack`, `build:maven-pack`) take the first half of the old bodies; `release:nuget` and `release:maven` keep their coordinates and become the push half. `test:image` gains an output port that writes a verdict record, and the five publish leaves gain an `evidence` input port. Rules 6 and 8 are new functions in `src/simplon/domain/ports.py`, called from `ports.check`. A new module `src/simplon/domain/results.py` holds the run-time check that a producer which exits 0 wrote its test result; both dispatch paths (the generated module and `cli.assemble`) call it. `releasenotes.py` gains the generating half, `write`, on the walk it already has.

**Tech Stack:** Python 3, pydantic, pytest, Gradle init scripts (Groovy), `urllib` for the Maven upload, firn v0.1.0 (`ghcr.io/marcozwyssig/firn:v0.1.0`, run by `./simplon.sh build model` and `./simplon.sh test model`).

**Spec:** `docs/superpowers/specs/2026-10-11-ci-cd-support-and-the-artifact-chain-design.md`, Parts C.3, C.4, C.5 (rules 6 and 8) and C.7. Decisions taken after the spec:
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6161492956 — C measured; C does not wait for product adoption.
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6162459829 — `with: name` alone stays the binding; rule 1 is per plan; port names follow the accepted kind.
- https://github.com/marcozwyssig/simplon/issues/344#issuecomment-6163686765 — **split `release:nuget` and `release:maven` into pack (output port) and push (input port), inside C.3, ahead of rule 6.**
- Decided 2026-10-14 in this planning session (choice list, Marco), recorded on si#344 as Task 0:
  1. **Maven:** `build:maven-pack` runs `gradle publish` into a file repository under the artifact's `path:`, injected by a kernel init script; `release:maven` uploads exactly those files with HTTP PUT and then reads them back as today.
  2. **Rule 6's X:** every artifact a command under `ci: release:` consumes, **except** those whose kind refines one of the four kinds a release produces about itself: `test-result`, `release-notes`, `tag`, `release`.
  3. **The deploy port** (`deploy: { consumes: { release: X } }`, spec C.4) is **not** in C.3.
  4. **Names:** `build:nuget-pack`, `build:maven-pack`.
  5. **simplon's release leaf becomes `release push-image`** (firn's name for the same act). Found while planning: `depends_on` takes only bare names one group owns (#519), so an aggregate cannot plan `image` while `build image` and `test image` exist. **Spec C.4's own example has this defect** (`all: depends_on: [notes, image, tag]` beside `build image`); Task 0 records it.

## Scope: what is C.3 and what is not

| Plan | Content |
|---|---|
| C.1 (merged, #417) | ports on catalogue tasks |
| C.2 (merged, #418) | `produces:`/`consumes:`, rules 1-5 and 7, `_bind`, manifest model references catalogue tasks |
| **C.3 (this)** | the nuget/maven split; test results and `evidence`; rule 6; `release:notes`; `release:tag`'s ports; the release aggregate and rule 8; the model's `TestResult`/`ReleaseCommand` export; simplon's own adoption |
| C.4 | workflowgen `upload-artifact`/`download-artifact` |

**Not in C.3:**
- **`deploy:up`'s `release` input port** (decision 3). Task 0 records it on si#344 as open work.
- **A refusal of the hand-written `releases:` page or of `test:release-notes`.** Spec C.4 keeps both.
- **`test:gate` ports.** `test:gate` selects a *suite*, not an artifact, and consumes nothing, so a result it wrote would be about nothing (spec C.3: "about" is what the producer consumes). Its results stay `results_from:`. A product that wants a gate's result as evidence runs the test through `toolchain:run`, which has `source`/`out` ports.
- **Migration of evidence.** `simplon manifest migrate` does not write evidence, test results, notes or the aggregate (spec C.4: nothing in today's manifest says which test is about which release).
- **#419 and #420** (C.2 follow-ups). Untouched.

## Global Constraints

- **Branch and PR:** branch `si344-c3-release-split` from `main` (created at 84f2e7f). The PR is in milestone "M3 - ci / cd / support" and its body says "Part of #344 (C.3 of four plans)". Do **not** write `Closes #344`. Never merge; Marco merges.
- **The PR stays a draft until agile-cockpit has answered** the release-rule cost question (asked 2026-10-14, still unanswered when this plan was written: no comment on agile-cockpit's issues or on si#344 since). Spec C.3: "Its cost is named by its peer session before this ships." If the answer names a cost that changes rule 6, stop and ask Marco.
- **Commits:** set the identity env on every commit; `git config` and `--amend` are blocked:
  `GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'`
  The message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
  ```
- **Python:** always `./deploy/orchestrator/.venv/bin/python`. `PY` below means that path.
  - Tests: `PY -m pytest src/tests -q -p no:cacheprovider` (about 2 min). Redirect the full run to a file and read its tail. Three `test_tasks_docs` failures are root-bound and pre-existing; any other failure is yours.
  - mypy: `PY -m mypy --config-file mypy.ini src/simplon`.
- **Generated files are never edited by hand:** `src/simplon/catalogue.yaml` outside its protected region; `src/simplon/domain/artifactschema.py`; `src/site/content/with-what/kinds.md`; `src/site/content/with-what/commands.md`; `src/firn/model/product/simplon/simplon.firn`; `src/site/content/with-what/architecture.md`; `src/tests/generated/architecture.py`. Edit the source, then `./simplon.sh build model`. `./simplon.sh test generated` compares against the git **index**, so stage regenerated files first. `./simplon.sh test generated` and `./simplon.sh test model` must be green before any commit touching `src/firn/`, `simplon.yaml` or a generated file.
- **firn v0.1.0 loses output with rc 0** (firn#966). After every `./simplon.sh build model`, run `git status --short src/simplon src/site src/tests/generated` and read each generated diff. If `artifactschema.py` is gone or holds only the id line: `git checkout -- src/simplon/domain/artifactschema.py` and fix the template.
- **CLAUDE.md:**
  - See every new assertion red: break the property, run the test, watch it fail, restore. Write down in the commit which break turned it red.
  - Report findings, do not patch them away.
  - **Every new `raise` on the load path gets a census entry in the same commit** in `src/tests/test_refusal_census.py` `CENSUS`, key `(module, function, literal fragment)`; an expression rule also gets a `REACH` entry. Then update the two count tables on `src/site/content/with-what/rules.md` to the numbers `test_the_page_prints_the_census_count_for_each_kind` and `test_the_page_prints_the_reach_of_the_expression_rules` print. Edit only the numbers.
  - A new module that calls `manifest_data()` goes red in `test_every_module_that_reads_the_manifest_is_accounted_for` until it is in `READS_INLINE` with its reason; its raises then need `CENSUS` entries (the census test names each one).
  - A quoted error text is a second source: every refusal a test asserts is matched on a fragment of the real message.
- **Kinds:** every rule asks `getattr(catalogue, "kinds", {}) or artifactsection.REFINES` and `artifactsection.accepts(kinds, wanted, kind)`; nothing restates the refinement table.
- **Port names follow the accepted kind** (Marco, C.2): `nuget`, `maven`, `test-result`, `release-notes`, `tag`. The one exception is `evidence`, which the spec and the decision name. A firn resource name has no `-`, so `test_result` in the model is `test-result` in `PORTS`; Task 4 makes the template do that replacement.
- **A path the kernel deletes is under the output root.** A pack that empties its `path:` refuses a path that is not strictly inside `outputs.root()`.

## Review Focus

1. **A stale result passing as a fresh one.** A test result file left by yesterday's run must not satisfy today's "the producer wrote its result". `results.held` compares the file's state before and after the body (mtime_ns, or absence), not "does it exist". Pinned in Task 4 (`test_a_result_left_from_an_earlier_run_does_not_count_as_written`).
2. **A pack's `path:` that is the product root or outside the output root.** `build:maven-pack` empties its staging directory; `path: .` must be refused before anything is deleted. Pinned in Task 2 (`test_a_staging_path_outside_the_output_root_is_refused_before_anything_is_deleted`).
3. **A push of a version that was not packed**, or of an older package still lying in the directory. Push names the exact file for its version and refuses when it is absent. Pinned in Tasks 1 and 2 (`test_a_push_with_nothing_packed_for_its_version_names_the_pack_command`, `test_a_push_with_nothing_staged_for_its_version_names_the_pack_command`).
4. **`release:tag` and the evidence port under rule 6.** A literal reading of rule 6 would demand a test result about the notes, and about each test result. The exclusion of the four own kinds (decision 2) must hold, and a tag after a publish must load. Pinned in Task 7 (`test_the_kernels_own_release_aggregate_loads`) and Task 5 (`test_a_release_command_consuming_only_its_own_kinds_needs_no_evidence`).
5. **Historical release notes rewritten.** `src/site/content/when/releases.md` mentions `release:nuget`/`release:maven` inside released versions. Those sections describe what shipped and are **not** edited (Task 3 says so; `test_releases_page.py` would not catch a rewrite).

## The measurement this plan stands on (2026-10-14)

The eight reachable manifests were fetched again through the API for this plan. Only two changed since comment 6161492956: firn.yaml (e091bce, 2026-10-13) and simplon.yaml (bfd1819, C.2's migration).

| manifest | form | catalogue publish leaf under `release` | tests that consume it | rule 6 |
|---|---|---|---|---|
| firn | `ci:`/`cd:` | `push-image` = `release:image` (`firn`, `with: { name: firn }`) | 6 × `test:image` on `firn` (3 anchored blocks, 3 `<<:` merges), none produces a result | **refused** at firn's next bump. Bill: six `test-result` entries, `produces: { test-result: ... }` on each test, `push-image` consumes all six as evidence |
| simplon | `ci:`/`cd:` | `image` = `release:image` (`kernel`) | none | **paid in this plan** (Tasks 4 and 7) |
| agile-cockpit | `groups:` | `image` = `release:image` (`app`) | none (`test:gate` ×3 tests code, not the image) | **refused** after its migration. Cost asked 2026-10-14, unanswered |
| biz-cockpit, asbundle, netctl, swi, cleon | `groups:` | none: every release path is a product task (`orchestrator.cli:*`, `packer.commands:*`) with no ports | — | not reached |

- **`release:nuget`, `release:maven`:** named by none of the eight (grep over the fetched files). The split costs no product.
- **`kind: test-result`, `release-notes`, `tag`, `release`:** declared by none of the eight. "Test result outside `ci: test:`" and rule 8 refuse nothing live.
- **`releases:` pages:** simplon and agile-cockpit. Both keep them.
- **Frozen fixtures:** `src/tests/fixtures/manifests/` holds the same eight in the pre-A form. After migration, rule 6 refuses exactly `agile-cockpit`, `firn` and `simplon` there. Task 5 pins that set as `realmanifests.RELEASE_RULE_BILL`, so the bill is a test, not a sentence.
- **The model's `TestResult.about` is broken for exported products since C.2.** Its selector is `self.owner().consumes`; C.2 made `produces` an Association, and `manifestmodel` emits every artifact as a child of the Product, so `owner()` is the Product and the answer is empty. The demo fixture still nests the result inside its command, which is why `test_firn_pipeline_e2e.py` stays green. Task 8 measures a selector that works or reports it to firn.

## File Structure

- **Modify** `src/firn/model/simplon/catalogue/tasks.firn`: two pack tasks; `release_nuget`/`release_maven` bodies and needs; `evidence` on five publish leaves; `test_image`'s result port; `release_notes`; `release_tag`'s two ports.
- **Modify** `src/firn/templates/schema.firnt` and `src/firn/templates/docs.firnt`: a port name has `_` replaced by `-` (Task 4).
- **Modify** `src/simplon/catalogue.yaml` (protected region only): `build:nuget-pack`, `build:maven-pack`, `release:notes`; new impls for `release:nuget`/`release:maven`; `results` on `test:image`.
- **Modify** `src/simplon/tasks/nuget.py` (`pack`, `push` replace `publish`), `src/simplon/tasks/maven.py` (`pack`, `push` replace `publish`).
- **Modify** `src/simplon/tasks/image.py` (`smoke` writes its verdict record).
- **Create** `src/simplon/domain/results.py`: `before`, `held`, `path_of`.
- **Modify** `src/simplon/tasks/taskgen.py` and `src/simplon/cli/__init__.py` (`_bound`): call `results.held`.
- **Modify** `src/simplon/domain/artifactsection.py`: `declared` returns `Declared(kind, registry, path)`.
- **Modify** `src/simplon/domain/ports.py`: aggregate outputs in `check`; `_check_results`, `_check_release` (rule 6), `_check_bundles` (rule 8).
- **Modify** `src/simplon/domain/treeform.py` (`_resolve_one`): an aggregate may carry `produces:`.
- **Modify** `src/simplon/tasks/releasenotes.py`: `render` and `write`.
- **Modify** `src/simplon/domain/manifestmodel.py`, `src/firn/model/simplon/pipeline/pipeline.firn` (Task 8).
- **Modify** `src/firn/model/simplon/components/components.firn`, `src/simplon/cli/surface.py` (the new module).
- **Modify** `simplon.yaml`, `.github/workflows/release.yml`.
- **Modify** pages: `src/site/content/what/handing-a-package-over.md`, `src/site/content/with-what/phases.md`, `src/site/content/why/the-design.md`, `src/site/content/how/manifest.md`, `src/site/content/how/task-and-command.md`, `src/site/content/with-what/rules.md` (numbers only).
- **Tests:** `src/tests/test_tasks_nuget_publish.py`, `src/tests/test_maven.py`, `src/tests/test_catalogue_ports.py`, `src/tests/test_tasks_image.py`, `src/tests/test_results.py` (new), `src/tests/test_taskgen.py`, `src/tests/test_release_rule.py` (new), `src/tests/test_tasks_releasenotes.py`, `src/tests/test_release_bundle.py` (new), `src/tests/test_manifestmodel.py`, `src/tests/test_firn_pipeline_e2e.py`, `src/tests/test_migrate.py`, `src/tests/realmanifests.py`, `src/tests/test_refusal_census.py`, `src/tests/test_release_workflow.py`.

---

### Task 0: Record the planning decisions on si#344

**Files:** none in the repository.

- [ ] **Step 1: Post the decisions**

```bash
cat > /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c3-decisions.md <<'EOF'
## C.3: decided before the plan (choice list, Marco, 2026-10-14)

1. **Maven split.** `build:maven-pack` runs `gradle publish` into a file repository under the artifact's `path:`, through an init script the kernel writes. `release:maven` uploads exactly those files with HTTP PUT and then reads the POMs back, as it does today. The PUT against GitHub's Maven registry is not measured from this machine (no `write:packages` token), the same gap `tasks/nuget.py` records; the client is measured against a local HTTP server.
2. **Rule 6's X.** The release rule asks for test results about every artifact a command under `ci: release:` consumes, except those whose kind refines one of the four kinds a release produces about itself: `test-result`, `release-notes`, `tag`, `release`. So `release:tag` consuming the notes needs no evidence, and neither does the evidence itself.
3. **The deploy port** (`deploy: { consumes: { release: X } }`, spec C.4) is not in C.3 and stays open on this ticket.
4. **Names:** `build:nuget-pack` and `build:maven-pack`.
5. **simplon's `release image` becomes `release push-image`.** Found while planning: `depends_on` takes only a bare name that exactly one group owns (#519), so a release aggregate cannot plan `image` while `build image` exists. Spec C.4's own example (`all: depends_on: [notes, image, tag]` beside `build image`) would be refused for that reason. firn already names the leaf `push-image`. Measured cost in simplon: one line in release.yml, three in `test_own_image.py`, and the command name a person types.

Measured again for the plan (all eight manifests fetched 2026-10-14): only firn.yaml and simplon.yaml changed since comment 6161492956. Rule 6 binds firn, simplon and agile-cockpit, as measured there. agile-cockpit's answer on the cost is still open; the C.3 PR stays a draft until it arrives.
EOF
gh issue comment 344 --repo marcozwyssig/simplon --body-file /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c3-decisions.md
```

Expected: a comment URL.

---

### Task 1: `release:nuget` splits into `build:nuget-pack` and a push

**Files:**
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (`release_nuget`, new `build_nuget_pack`)
- Modify: `src/simplon/catalogue.yaml` (protected region, the `release:nuget` entry at line 677 and its comment above)
- Modify: `src/simplon/tasks/nuget.py` (`publish` at line 350 becomes `pack` and `push`; `push_argv` at 337; module docstring)
- Regenerate: `src/simplon/domain/artifactschema.py`, `src/site/content/with-what/kinds.md`, `src/site/content/with-what/commands.md`
- Test: `src/tests/test_tasks_nuget_publish.py`, `src/tests/test_catalogue_ports.py`

**Interfaces:**
- Produces, in `simplon.tasks.nuget`:
  - `pack(name: str = "", tag: str = "") -> int`: `dotnet pack` into the entry's `path:`, rc 1 when it exits 0 and wrote no `*.<version>.nupkg`.
  - `push(name: str = "", tag: str = "") -> int`: `dotnet nuget push` of the one `*.<version>.nupkg` under `path:`.
  - `push_argv(source_name: str, package: str) -> list[str]` (`package` is relative to the product root).
  - `pack_argv(project: str, version: str, out: str) -> list[str]` (`out` is relative to the product root).
  - `packed(directory: Path, version: str) -> list[Path]`: the `.nupkg` files for exactly that version, sorted.
- Produces, in `PORTS`: `"build:nuget-pack": (Port("nuget", "output", "nuget", "name", ("image", "project", "path")),)` and `"release:nuget": (Port("nuget", "input", "nuget", "name", ("registry", "image", "path")),)`. Task 4 adds `evidence` to the second.

- [ ] **Step 1: Write the failing tests**

In `src/tests/test_catalogue_ports.py`, `test_the_ports_are_the_ones_measured_from_the_bodies`, replace the `release:nuget` line and add the pack line:

```python
        "build:nuget-pack": (P("nuget", "output", "nuget", "name", ("image", "project", "path")),),
        "release:nuget": (P("nuget", "input", "nuget", "name", ("registry", "image", "path")),),
```

In `src/tests/test_tasks_nuget_publish.py`:
- Change the module docstring's first line to: `"""`build:nuget-pack` and `release:nuget` - packing a .NET library, then pushing what was packed, without the token ever reaching argv (si#127, si#344 C.3)."""`
- Give every entry in `_MANIFEST` the line `    path: build/nuget` (four entries).
- Replace the `lines` fixture with one whose fake `dotnet pack` writes what a real one writes:

```python
@pytest.fixture
def lines(monkeypatch, _product):
    """Every container line the task assembled, with nothing run. A `dotnet pack` line leaves the package
    a real one would, named for the version in its `-p:PackageVersion=` - so `push` finds what `pack` made."""
    seen: list = []

    def _stream(argv, cwd=None):
        seen.append(list(argv))
        if "pack" in argv:
            version = next(a for a in argv if a.startswith("-p:PackageVersion=")).split("=", 1)[1]
            out = _product / "build" / "nuget"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"Core.{version}.nupkg").write_bytes(b"PK")
        return 0

    monkeypatch.setattr(nuget, "stream", _stream)
    return seen
```

- Every existing test that calls `nuget.publish(...)`: call `nuget.pack(...)` when it asserts the `pack` line, the tag, the image pin, `DOTNET_CLI_HOME`, the env file or the missing project; call `nuget.pack(...)` and then `nuget.push(...)` when it asserts the `push` line, the source, the config refusal, the scope advice or the non-GitHub registry. Concretely:

| test | calls |
|---|---|
| `test_the_pack_carries_the_version_the_tag_names` | `nuget.pack("corelib")` |
| `test_the_pack_and_the_push_each_name_and_label_their_own_container` | `nuget.pack("corelib")`, then `nuget.push("corelib")` |
| `test_an_interrupted_push_removes_the_container_it_named` | `nuget.pack("corelib")` first (with the interrupting stub installed after it), then `nuget.push("corelib")` |
| `test_a_tag_declared_in_the_manifest_needs_no_argument` | `nuget.pack("corelib")` |
| `test_without_a_tag_anywhere_it_names_both_places_one_could_be` | `nuget.pack("untagged")` and, in a second `pytest.raises`, `nuget.push("untagged")` |
| `test_the_push_names_the_source_and_carries_no_api_key` | `nuget.pack("corelib")`, `nuget.push("corelib")` |
| `test_the_token_is_in_no_line_at_all`, `test_the_credential_arrives_as_an_env_file`, `test_every_line_sets_dotnet_cli_home_and_runs_as_the_caller` | `nuget.pack("corelib")`, `nuget.push("corelib")` |
| `test_the_env_file_holds_the_token_while_the_run_lasts_and_is_gone_after`, `test_the_env_file_is_removed_even_when_the_run_raises` | `nuget.pack("corelib")` |
| `test_an_unpinned_image_is_refused_with_the_kernels_one_wording` | `nuget.pack("floating")` |
| `test_a_registry_that_is_not_githubs_is_refused_before_a_token_is_minted` | `nuget.pack("elsewhere")` succeeds (pack needs no registry), `nuget.push("elsewhere")` refuses |
| `test_a_project_that_is_not_there_is_named_before_anything_runs` | `nuget.pack("corelib")` |
| `test_without_a_generated_config_the_push_has_no_source_and_says_which_command_writes_one` | `nuget.pack("corelib")`, delete `nuget.config`, `nuget.push("corelib")` |
| `test_a_failed_push_appends_the_scope_advice` | `nuget.pack("corelib")`, then the failing stub, then `nuget.push("corelib")` |

Append these tests:

```python
# --- si#344 C.3: pack writes the package, push pushes exactly that one ----------------------------------

def test_the_pack_writes_into_the_artifacts_path(lines):
    # act
    rc = nuget.pack("corelib")

    # assert
    assert rc == 0
    assert "/work/build/nuget" in _of(lines, "pack")


def test_the_pack_removes_an_earlier_package_before_it_packs(lines, _product):
    # arrange: yesterday's package of another version lies in the directory
    out = _product / "build" / "nuget"
    out.mkdir(parents=True)
    (out / "Core.1.3.0.nupkg").write_bytes(b"PK")

    # act
    nuget.pack("corelib")

    # assert
    assert sorted(p.name for p in out.iterdir()) == ["Core.1.4.0.nupkg"]


def test_a_pack_that_exits_0_and_writes_no_package_is_a_failed_step(monkeypatch, capsys):
    # arrange: dotnet answers 0 and writes nothing
    monkeypatch.setattr(nuget, "stream", lambda argv, cwd=None: 0)

    # act
    rc = nuget.pack("corelib")

    # assert
    assert rc == 1
    assert "wrote no package for 1.4.0" in capsys.readouterr().err


def test_the_push_pushes_the_one_package_packed_for_that_version(lines, _product):
    # arrange: an older package lies beside the one this version packed
    nuget.pack("corelib")
    (_product / "build" / "nuget" / "Core.1.3.0.nupkg").write_bytes(b"PK")

    # act
    rc = nuget.push("corelib")

    # assert
    assert rc == 0
    push = _of(lines, "push")
    assert "/work/build/nuget/Core.1.4.0.nupkg" in push
    assert not any("1.3.0" in part for part in push)


def test_a_push_with_nothing_packed_for_its_version_names_the_pack_command(lines):
    # act / assert
    with pytest.raises(ValueError, match="nothing packed for 1.4.0 under build/nuget: run `build:nuget-pack` first"):
        nuget.push("corelib")
    assert not any("push" in line for line in lines)


def test_a_pack_path_outside_the_output_root_is_refused_before_anything_is_deleted(_product, lines):
    # arrange
    text = (_product / "demo.yaml").read_text(encoding="utf-8").replace("path: build/nuget", "path: .", 1)
    (_product / "demo.yaml").write_text(text, encoding="utf-8")
    (_product / "keep.nupkg").write_bytes(b"PK")

    # act / assert
    with pytest.raises(ValueError, match="is not inside the output root"):
        nuget.pack("corelib")
    assert (_product / "keep.nupkg").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PY -m pytest src/tests/test_tasks_nuget_publish.py src/tests/test_catalogue_ports.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'simplon.tasks.nuget' has no attribute 'pack'` and the `PORTS` literal mismatch.

- [ ] **Step 3: Change the model and regenerate**

In `src/firn/model/simplon/catalogue/tasks.firn`, replace the `release_nuget` block with:

```
build_nuget_pack typeOf simplon.pipeline.CatalogueTask {
  key = "build:nuget-pack"
  body = "simplon.tasks.nuget:pack"
  output nuget typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.nuget
    param = "name"
    needs = simplon.vocabulary.nuget.f_image
    needs = simplon.vocabulary.nuget.f_project
    needs = simplon.vocabulary.artifact.f_path
  }
}
release_nuget typeOf simplon.pipeline.CatalogueTask {
  key = "release:nuget"
  body = "simplon.tasks.nuget:push"
  input nuget typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.nuget
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.nuget.f_image
    needs = simplon.vocabulary.artifact.f_path
  }
}
```

and add one line to the file head's comment: `// si#344 C.3 (decided 2026-10-14): release:nuget and release:maven are split into a pack task (output) and a push task (input), so a test can sit between them.`

In `src/simplon/catalogue.yaml` (protected region), replace the `release:nuget:` entry with:

```yaml
  # si#344 C.3: PACK AND PUSH ARE TWO TASKS, so the package exists between them and a test can consume it.
  # The release rule (spec C.3) asks for a test result about what a release publishes, and a package that
  # first existed inside its own push could not have one. `build:nuget-pack` writes it to the entry's
  # `path:`; `release:nuget` pushes exactly the package that path holds for the version.
  build:nuget-pack:
    impl: simplon.tasks.nuget:pack
    help: "Pack the declared project into the artifact's path, as the version the tag names."
    unattended: true
    params:
      name: { help: "the artifact to pack (normally bound with `produces:`)" }
      tag:  { help: "the package version, for one only known after a build" }
  release:nuget:
    impl: simplon.tasks.nuget:push
    help: "Push the package `build:nuget-pack` wrote for this version to GitHub's NuGet feed."
    unattended: true
    params:
      name: { help: "the artifact to push (normally bound with `consumes:`)" }
      tag:  { help: "the package version to push, for one only known after a build" }
```

Run: `./simplon.sh build model && git status --short src/simplon src/site src/tests/generated`
Expected: `artifactschema.py`, `kinds.md`, `commands.md` modified; read each diff (firn#966).

- [ ] **Step 4: Split the body**

In `src/simplon/tasks/nuget.py`:

Change the module docstring's first line to `"""`build:nuget-pack`, `release:nuget`, `build:nuget-config`, `build:nuget-restore` - hand a .NET library over, and take one (si#127, si#344 C.3).` and add this paragraph after "PUBLISHING ALONE IS HALF A FEATURE ...":

```
PACKING AND PUSHING ARE TWO COMMANDS SINCE si#344 C.3, and the reason is the release rule rather than
tidiness: a release consumes the results of the tests on what it publishes, and a package that first
existed inside its own push could not be tested by anybody. `pack` writes `*.<version>.nupkg` into the
entry's `path:`; `push` pushes exactly that file. A pack that exits 0 and wrote no package for its version
is a failed step - "nothing to do" passing for "packed" is the defect this repository hunts.
```

Delete `PACK_DIR` (the path is the entry's `path:` now). Replace `pack_argv`, `push_argv` and `publish` with:

```python
def pack_argv(project: str, version: str, out: str) -> list[str]:
    """`dotnet pack`, with the version the tag names, into `out` (relative to the product root). Pure.

    `-p:PackageVersion=` rather than an edit to the .csproj: the version is a property of the RELEASE,
    and a number checked into a project file is a number two people can pick at once - the argument
    `release:tag` is built on, one level down.
    """
    return ["dotnet", "pack", project, "-c", "Release", "-o", f"{WORKDIR}/{out}",
            f"-p:PackageVersion={version}"]


def push_argv(source_name: str, package: str) -> list[str]:
    """`dotnet nuget push` of ONE package (relative to the product root), with NO api key. Pure.

    One file and not a glob (si#344 C.3): the directory may still hold an older version's package, and a
    glob would push it beside this one. MEASURED, and the module head carries the transcript: `--api-key`
    alone does not authenticate against a feed that wants an Authorization header (401), the `<apikeys>`
    config section cannot hold one on Linux at all, and a push against a source that carries credentials
    needs none.
    """
    return ["dotnet", "nuget", "push", f"{WORKDIR}/{package}", "--source", source_name, "--skip-duplicate"]


def packed(directory: Path, version: str) -> list[Path]:
    """The packages `dotnet pack` wrote for exactly `version` (`<id>.<version>.nupkg`), sorted. Pure."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob(f"*.{version}.nupkg") if p.is_file())


def _inside_the_output_root(root: Path, relative: str, name: str) -> Path:
    """`root/relative`, refused unless it lies strictly inside the output root - this task deletes in it."""
    target = (root / relative).resolve()
    top = outputs.root().resolve()
    if target == top or not target.is_relative_to(top):
        raise ValueError(
            f"artifact '{name}' declares `path: {relative}`, which is not inside the output root ({top}): "
            f"a pack empties its path first, so it may only be a directory the kernel owns")
    return target


def _version(spec: artifactschema.NugetEntry, name: str, tag: str) -> str:
    resolved = tag or spec.tag or ""
    if not resolved:
        raise ValueError(
            f"artifact '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant "
            f"one, or pass --tag for a version that is only known after a build")
    return resolved


def pack(name: str = "", tag: str = "") -> int:
    """Pack the project `name` declares into its `path:`, as the version the tag names (si#344 C.3)."""
    spec = _declared(name, "build:nuget-pack")
    pinned = docker.pinned_image(spec.image or "", f"artifact '{name}'",
                                 hint="a published package names the SDK it was built with")
    project, out = spec.project or "", spec.path or ""
    resolved = _version(spec, name, tag)
    root = context.current().root
    if not (root / project).is_file():
        raise ValueError(f"nothing to pack: {project} does not exist under the product root. the "
                         f"project is the product's, not this task's")
    target = _inside_the_output_root(root, out, name)

    docker.ensure_docker()
    # si#319: the tree this container writes must be the CALLER'S, not merely writable.
    fault = docker.ownership_fault([outputs.root()], root)
    if fault:
        log.error(fault)
        raise ValueError(fault)
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("*.nupkg"):
        old.unlink()
    (root / CLI_HOME).mkdir(parents=True, exist_ok=True)

    with _env_file(githubpackages.token()) as env_file:
        log.info(f"packing {project} as {resolved} into {out}")
        rc = _contained(pinned, root, env_file, pack_argv(project, resolved, out))
    if rc != 0:
        log.error(f"dotnet pack {project} failed (rc={rc}; see output above)")
        return rc
    if not packed(target, resolved):
        log.error(f"dotnet pack {project} exited 0 and wrote no package for {resolved} under {out} - "
                  f"a pack that made nothing is not a pack")
        return 1
    log.ok(f"packed {', '.join(p.name for p in packed(target, resolved))} into {out}")
    return 0


def push(name: str = "", tag: str = "") -> int:
    """Push the package `build:nuget-pack` wrote for this version to the GitHub feed `name` names."""
    registry, pinned, _ = _for_container(name, "release:nuget")
    spec = _declared(name, "release:nuget")
    source_name = _source_name(spec, name)
    resolved = _version(spec, name, tag)
    root = context.current().root
    out = spec.path or ""
    found = packed((root / out).resolve(), resolved)
    if not found:
        raise ValueError(f"nothing packed for {resolved} under {out}: run `build:nuget-pack` first")
    _config_or_refuse(root, source_name)

    docker.ensure_docker()
    (root / CLI_HOME).mkdir(parents=True, exist_ok=True)
    rc = 0
    with _env_file(githubpackages.token()) as env_file:
        for package in found:
            relative = package.relative_to(root.resolve()).as_posix()
            log.info(f"pushing {package.name} to {index_url(registry)}")
            rc = _contained(pinned, root, env_file, push_argv(source_name, relative))
            if rc != 0:
                break
    if rc != 0:
        # The scope advice is a HINT tied to a host and a condition, never appended to every failure -
        # image.py's rule, and the reason is that a push fails on a full disk and a dead network too.
        log.error(f"dotnet nuget push to {registry} failed (rc={rc}; see output above)\n"
                  "if the registry refused it rather than the network, the usual cause is a token "
                  "without the package scopes:\n" + githubpackages.scope_advice())
        return rc
    log.ok(f"published {resolved} to {index_url(registry)}")
    return 0
```

`_for_container` still reads `_declared(name, coordinate)` and `_github_registry`; `restore` keeps using it with `"build:nuget-restore"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PY -m pytest src/tests/test_tasks_nuget_publish.py src/tests/test_catalogue_ports.py src/tests/test_tasks_nuget_config.py src/tests/test_catalogue.py src/tests/test_generated_schema.py src/tests/test_artifactsection.py -q -p no:cacheprovider`
Expected: PASS. A literal elsewhere naming `nuget:publish` or the old `NEEDS` fails here; fix the literal to the new coordinate, never the model.

- [ ] **Step 6: See them red**

Delete the `if not packed(target, resolved):` block → `test_a_pack_that_exits_0_and_writes_no_package_is_a_failed_step` fails. Change `push_argv` back to the glob → `test_the_push_pushes_the_one_package_packed_for_that_version` fails. Delete the `_inside_the_output_root` call → the output-root test fails. Restore each.

- [ ] **Step 7: Full suite, mypy, generated, model; commit**

Run: `PY -m pytest src/tests -q -p no:cacheprovider > /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/t1.log 2>&1; tail -15 /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/t1.log`, then `PY -m mypy --config-file mypy.ini src/simplon`, then `git add -A && ./simplon.sh test generated && ./simplon.sh test model`.
Expected: only the three known `test_tasks_docs` failures; mypy clean; both gates green.

```bash
git add -A
GIT_AUTHOR_NAME="Marco Zwyssig" GIT_AUTHOR_EMAIL="marco@zwyssig.info" GIT_COMMITTER_NAME="Marco Zwyssig" GIT_COMMITTER_EMAIL="marco@zwyssig.info" git commit -q -F- <<'EOF'
feat(si#344): release:nuget splits into build:nuget-pack and a push of what was packed

C.3 Task 1, decided in si#344 comment 6163686765. The pack writes *.<version>.nupkg into
the entry's path: (inside the output root, emptied first) and fails when dotnet exits 0
having written nothing; the push pushes exactly that file. The model gives the pack an
output port and the push an input port.

Seen red: <which break turned which test red>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
```

---

### Task 2: `release:maven` splits into `build:maven-pack` and an upload of what was staged

**Files:**
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (`release_maven`, new `build_maven_pack`)
- Modify: `src/simplon/catalogue.yaml` (protected region, `release:maven` at line 719 and the comment above it)
- Modify: `src/simplon/tasks/maven.py` (`publish` at 338 becomes `pack` and `push`; `_declared` takes the coordinate; module docstring)
- Regenerate: as Task 1
- Test: `src/tests/test_maven.py`, `src/tests/test_catalogue_ports.py`

**Interfaces:**
- Consumes: `nuget._env_file` (already imported), `outputs.root()`.
- Produces, in `simplon.tasks.maven`:
  - `STAGE_TASK = "publishAllPublicationsToSimplonStagingRepository"`, `INIT_SCRIPT = "simplon-staging.gradle"`.
  - `init_script_text(staging: str) -> str` (pure; `staging` is the in-container path).
  - `pack_argv(version: str) -> list[str]` (pure).
  - `staged(staging: Path, group: str, modules: Sequence[str], version: str) -> tuple[list[Path], list[str]]`: the files to upload in upload order, and the modules with nothing staged.
  - `upload(registry: str, staging: Path, files: Sequence[Path], token: str) -> tuple[int, str]`: `(0, "")`, or the first refused file's status and relative path.
  - `pack(name: str = "", tag: str = "") -> int`, `push(name: str = "", tag: str = "") -> int`.
  - `_declared(name: str, coordinate: str) -> MavenEntry`.
- Removed: `publish`, `publish_argv`, `TASK`. `WITHDRAWN`/`refuse_withdrawn` stay.
- Produces, in `PORTS`: `"build:maven-pack": (Port("maven", "output", "maven", "name", ("image", "group", "modules", "path")),)` and `"release:maven": (Port("maven", "input", "maven", "name", ("registry", "group", "modules", "path")),)`.

- [ ] **Step 1: Write the failing tests**

In `test_catalogue_ports.py`'s literal, replace the `release:maven` line and add:

```python
        "build:maven-pack": (P("maven", "output", "maven", "name", ("image", "group", "modules", "path")),),
        "release:maven": (P("maven", "input", "maven", "name", ("registry", "group", "modules", "path")),),
```

In `src/tests/test_maven.py`:
- Delete `test_publish_argv_pins_the_version_and_takes_no_daemon` and `test_the_gradle_task_is_always_publish` (the names they pin are gone).
- `test_publish_refuses_a_declared_task_before_docker_is_touched`: call `maven.pack("firn")` instead of `maven.publish(...)` and rename it `test_pack_refuses_a_declared_task_before_docker_is_touched`.
- The `_publishable` fixture: add `    path: build/maven\n` to the written entry, and stub the staged layout the pack would leave (see `_stage` below). `test_the_publish_names_and_labels_its_container` and `test_an_interrupted_publish_removes_the_container_it_named` call `maven.pack("firn")` and are renamed `test_the_pack_names_and_labels_its_container` and `test_an_interrupted_pack_removes_the_container_it_named`.

Append:

```python
# --- si#344 C.3: pack stages, push uploads what was staged -----------------------------------------------

import http.server
import threading


def _stage(staging, group="g.h", module="core", version="1.0"):
    """The layout `gradle publish` writes into a file repository: artefacts and checksums per version,
    maven-metadata.xml per module."""
    base = staging.joinpath(*group.split("."), module)
    (base / version).mkdir(parents=True, exist_ok=True)
    for suffix in (".jar", ".jar.sha1", ".pom", ".pom.sha1", ".module"):
        (base / version / f"{module}-{version}{suffix}").write_text("x", encoding="utf-8")
    (base / "maven-metadata.xml").write_text("<metadata/>", encoding="utf-8")
    (base / "maven-metadata.xml.sha1").write_text("x", encoding="utf-8")


def test_pack_argv_runs_the_staging_task_with_the_kernels_init_script():
    # act
    argv = maven.pack_argv("1.4.0")

    # assert
    assert argv == ["gradle", "publishAllPublicationsToSimplonStagingRepository", "-Pversion=1.4.0",
                    "--init-script", "/work/build/gradle-home/simplon-staging.gradle", "--no-daemon"]


def test_the_init_script_adds_one_file_repository_and_nothing_else():
    # act
    text = maven.init_script_text("/work/build/maven")

    # assert
    assert 'name = "simplonStaging"' in text
    assert 'url = uri("/work/build/maven")' in text
    assert 'plugins.withId("maven-publish")' in text


def test_staged_lists_artefacts_before_each_modules_metadata(tmp_path):
    # arrange
    _stage(tmp_path)

    # act
    files, missing = maven.staged(tmp_path, "g.h", ["core"], "1.0")

    # assert
    names = [f.name for f in files]
    assert missing == []
    assert names.index("core-1.0.pom") < names.index("maven-metadata.xml")
    assert names[-2:] == ["maven-metadata.xml", "maven-metadata.xml.sha1"]


def test_staged_names_a_module_the_pack_did_not_stage(tmp_path):
    # arrange
    _stage(tmp_path, module="core")

    # act
    _, missing = maven.staged(tmp_path, "g.h", ["core", "api"], "1.0")

    # assert
    assert missing == ["api"]


class _Recorder(http.server.BaseHTTPRequestHandler):
    puts: list = []
    status = 201

    def do_PUT(self):  # noqa: N802 - the stdlib's spelling
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).puts.append((self.path, self.headers.get("Authorization")))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def _registry(monkeypatch):
    """A local HTTP server standing in for the registry; `repository_url` is pointed at it."""
    _Recorder.puts, _Recorder.status = [], 201
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(maven, "repository_url",
                        lambda registry, checked=False: f"http://127.0.0.1:{server.server_port}/o/r")
    yield _Recorder
    server.shutdown()


def test_upload_puts_every_staged_file_at_its_relative_path_with_the_token(tmp_path, _registry):
    # arrange
    _stage(tmp_path)
    files, _ = maven.staged(tmp_path, "g.h", ["core"], "1.0")

    # act
    status, refused = maven.upload("maven.pkg.github.com/o/r", tmp_path, files, "t")

    # assert
    assert (status, refused) == (0, "")
    paths = [p for p, _ in _registry.puts]
    assert paths[0] == "/o/r/g/h/core/1.0/core-1.0.jar"
    assert paths[-1] == "/o/r/g/h/core/maven-metadata.xml.sha1"
    assert {auth for _, auth in _registry.puts} == {"Bearer t"}


def test_upload_stops_at_the_first_refused_file_and_names_it(tmp_path, _registry):
    # arrange
    _stage(tmp_path)
    files, _ = maven.staged(tmp_path, "g.h", ["core"], "1.0")
    _registry.status = 403

    # act
    status, refused = maven.upload("maven.pkg.github.com/o/r", tmp_path, files, "t")

    # assert
    assert status == 403
    assert refused == "g/h/core/1.0/core-1.0.jar"
    assert len(_registry.puts) == 1


def test_a_push_with_nothing_staged_for_its_version_names_the_pack_command(_publishable, monkeypatch):
    # act / assert
    with pytest.raises(ValueError, match="nothing staged for 1.0 under build/maven: run `build:maven-pack` first"):
        maven.push("firn")


def test_the_push_uploads_and_then_reads_back(_publishable, monkeypatch, tmp_path):
    # arrange
    _stage(tmp_path / "build" / "maven")
    calls: list = []
    monkeypatch.setattr(maven, "upload", lambda *a: calls.append("upload") or (0, ""))
    monkeypatch.setattr(maven, "verify", lambda *a: calls.append("verify") or (maven.PRESENT, []))

    # act
    rc = maven.push("firn")

    # assert
    assert rc == 0
    assert calls == ["upload", "verify"]


def test_a_release_version_already_published_is_refused_before_anything_is_uploaded(_publishable, monkeypatch,
                                                                                   tmp_path):
    # arrange
    _stage(tmp_path / "build" / "maven")
    monkeypatch.setattr(maven, "may_publish", lambda *a: (False, "already in the registry"))
    monkeypatch.setattr(maven, "upload", lambda *a: pytest.fail("uploaded although refused"))

    # act
    rc = maven.push("firn")

    # assert
    assert rc == 1


def test_a_staging_path_outside_the_output_root_is_refused_before_anything_is_deleted(_publishable, tmp_path):
    # arrange
    path = tmp_path / "firn.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("path: build/maven", "path: ."), encoding="utf-8")
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")

    # act / assert
    with pytest.raises(ValueError, match="is not inside the output root"):
        maven.pack("firn")
    assert (tmp_path / "keep.txt").exists()


def test_a_pack_that_exits_0_and_staged_nothing_is_a_failed_step(_publishable, monkeypatch, capsys):
    # arrange: gradle answers 0 and writes nothing
    monkeypatch.setattr(maven, "stream", lambda argv: 0)

    # act
    rc = maven.pack("firn")

    # assert
    assert rc == 1
    assert "staged nothing for core" in capsys.readouterr().err
```

The `_publishable` fixture's entry must end with `    tag: '1.0'\n    path: build/maven\n`; its `stream` stub (where a test installs one that returns 0 for the pack's success path) calls `_stage(tmp_path / "build" / "maven")` before returning 0.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PY -m pytest src/tests/test_maven.py src/tests/test_catalogue_ports.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'simplon.tasks.maven' has no attribute 'pack_argv'`.

- [ ] **Step 3: Change the model and the catalogue, regenerate**

`tasks.firn`, replace `release_maven` with:

```
build_maven_pack typeOf simplon.pipeline.CatalogueTask {
  key = "build:maven-pack"
  body = "simplon.tasks.maven:pack"
  output maven typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.maven
    param = "name"
    needs = simplon.vocabulary.maven.f_image
    needs = simplon.vocabulary.maven.f_group
    needs = simplon.vocabulary.maven.f_modules
    needs = simplon.vocabulary.artifact.f_path
  }
}
release_maven typeOf simplon.pipeline.CatalogueTask {
  key = "release:maven"
  body = "simplon.tasks.maven:push"
  input maven typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.maven
    param = "name"
    needs = simplon.vocabulary.artifact.f_registry
    needs = simplon.vocabulary.maven.f_group
    needs = simplon.vocabulary.maven.f_modules
    needs = simplon.vocabulary.artifact.f_path
  }
}
```

`catalogue.yaml` (protected region): keep the long comment above `release:maven` and append to it:

```yaml
  #
  # si#344 C.3: STAGE AND UPLOAD ARE TWO TASKS, for `release:nuget`'s reason. `build:maven-pack` runs
  # `gradle publish` into a FILE repository under the entry's `path:`, added by an init script the kernel
  # writes, so the product's build file is not touched; `release:maven` uploads exactly those files with
  # HTTP PUT and reads the POMs back. The upload is not measured against GitHub from the machine it was
  # written on (no `write:packages` token) - the same gap tasks/nuget.py records.
```

then replace the entry with:

```yaml
  build:maven-pack:
    impl: simplon.tasks.maven:pack
    help: "Stage the declared Gradle modules into the artifact's path as a Maven file repository."
    unattended: true
    params:
      name: { help: "the artifact to stage (normally bound with `produces:`)" }
      tag:  { help: "the version to stage, for one only known after a build" }
  release:maven:
    impl: simplon.tasks.maven:push
    help: "Upload what `build:maven-pack` staged to GitHub's Maven registry and read the coordinates back."
    unattended: true
    params:
      name: { help: "the artifact to upload (normally bound with `consumes:`)" }
      tag:  { help: "the version to upload, for one only known after a build" }
```

Run `./simplon.sh build model` and read the generated diffs.

- [ ] **Step 4: Split the body**

In `src/simplon/tasks/maven.py`:

Module docstring: change the first line to `"""Publishing a jar in two steps: stage with `gradle publish` into a file repository, then upload what was staged and read it back (si#329, si#344 C.3).` and add after the "WHY IT READS THE REGISTRY BACK" paragraph:

```
WHY THE TWO HALVES ARE TWO TASKS (si#344 C.3). `gradle publish` builds and uploads in one run, so the jar
first existed inside its own release and no test could consume it - and the release rule asks for a test
result about every artifact a release publishes. `build:maven-pack` now runs the same `publish`, aimed at a
file repository the kernel's init script adds under the entry's `path:`; `release:maven` uploads exactly
those files, artefacts before metadata, and then runs the read-back it always ran. Gradle's own
`publishToMavenLocal` was the cheaper route and was not taken: Maven's local repository writes
`maven-metadata-local.xml` and no checksums, which is not the layout a remote repository holds.
NOT PROVEN: that GitHub's Maven registry accepts a plain PUT per file. `mvn deploy` does exactly that, and
the client here is measured against a local HTTP server, but the machine this was written on has no
`write:packages` token.
```

Replace the `TASK` constant and `publish_argv` with:

```python
#: The gradle task the pack runs (si#344 C.3): every publication, into the one repository the kernel's init
#: script adds. Fixed, for si#337's reason: a task the product names could aim anywhere, and this task's
#: claim is "the declared modules are staged where the push reads them".
STAGE_TASK = "publishAllPublicationsToSimplonStagingRepository"

#: The init script's file name, under `GRADLE_HOME` - inside the mounted tree, where the container can read it.
INIT_SCRIPT = "simplon-staging.gradle"


def init_script_text(staging: str) -> str:
    """The init script that adds a file repository named `simplonStaging` at `staging` to every project
    applying `maven-publish`, and changes nothing else. Pure."""
    return ("// Written by simplon's build:maven-pack (si#344 C.3). Adds one file repository; changes nothing else.\n"
            "allprojects {\n"
            "    plugins.withId(\"maven-publish\") {\n"
            "        publishing {\n"
            "            repositories {\n"
            "                maven {\n"
            "                    name = \"simplonStaging\"\n"
            f"                    url = uri(\"{staging}\")\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n")


def pack_argv(version: str) -> list[str]:
    """`gradle <STAGE_TASK>` with the version the tag names and the kernel's init script. Pure.

    `--no-daemon` because a Gradle daemon inside a `--rm` container is a process nobody reaps.
    """
    return ["gradle", STAGE_TASK, f"-Pversion={version}",
            "--init-script", f"{WORKDIR}/{GRADLE_HOME}/{INIT_SCRIPT}", "--no-daemon"]
```

Add `staged`, `_put`, `upload`:

```python
def staged(staging: Path, group: str, modules: Sequence[str], version: str) -> tuple[list[Path], list[str]]:
    """The files to upload for `modules` at `version`, in upload order - each module's version directory
    with its own metadata last, then the module's `maven-metadata.xml*` - and the modules with nothing staged.

    METADATA LAST, because a reader who sees the metadata first may resolve a version whose jar is not there yet.
    """
    files: list[Path] = []
    missing: list[str] = []
    for module in modules:
        base = staging.joinpath(*group.split("."), module)
        here = base / version
        if not here.is_dir() or not any(here.glob("*.pom")):
            missing.append(module)
            continue
        inner = sorted(p for p in here.iterdir() if p.is_file())
        files += [p for p in inner if not p.name.startswith("maven-metadata")]
        files += [p for p in inner if p.name.startswith("maven-metadata")]
        files += sorted(p for p in base.glob("maven-metadata.xml*") if p.is_file())
    return files, missing


def _put(url: str, data: bytes, token: str) -> int:
    """The HTTP status of one PUT, or 0 when it could not be made - `_status`'s three-way shape."""
    request = urllib.request.Request(url, data=data, method="PUT")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return int(refused.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def upload(registry: str, staging: Path, files: Sequence[Path], token: str) -> tuple[int, str]:
    """PUT each file at its path relative to `staging`; `(0, "")`, or the first refusal and its path."""
    base = repository_url(registry)
    for path in files:
        relative = path.relative_to(staging).as_posix()
        status = _put(f"{base}/{relative}", path.read_bytes(), token)
        if not 200 <= status < 300:
            return status or 1, relative
    return 0, ""
```

Change `_declared(name: str)` to `_declared(name: str, coordinate: str)` and its last line to `return artifactsection.entry(section, name, ENTRY, ctx.manifest_path.name, coordinate)`.

Replace `publish` with `pack` and `push`:

```python
def _staging(root: Path, relative: str, name: str) -> Path:
    """`root/relative`, refused unless strictly inside the output root - the pack empties it first."""
    target = (root / relative).resolve()
    top = outputs.root().resolve()
    if target == top or not target.is_relative_to(top):
        raise ValueError(
            f"artifact '{name}' declares `path: {relative}`, which is not inside the output root ({top}): "
            f"a pack empties its path first, so it may only be a directory the kernel owns")
    return target


def _resolved(spec: artifactschema.MavenEntry, name: str, tag: str) -> str:
    resolved = tag or spec.tag or ""
    if not resolved:
        raise ValueError(
            f"artifact '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant "
            f"one, or pass --tag for a version that is only known after a build")
    return resolved


def pack(name: str = "", tag: str = "") -> int:
    """Stage the jars `name` declares into its `path:` as a Maven file repository (si#344 C.3)."""
    spec = _declared(name, "build:maven-pack")
    group = spec.group or ""
    modules = _modules(spec, name)
    pinned = docker.pinned_image(spec.image or "", f"artifact '{name}'",
                                 hint="a published jar names the JDK and Gradle it was built with")
    resolved = _resolved(spec, name, tag)
    root = context.current().root
    relative = spec.path or ""
    target = _staging(root, relative, name)

    docker.ensure_docker()
    fault = docker.ownership_fault([outputs.root()], root)
    if fault:
        log.error(fault)
        raise ValueError(fault)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (root / GRADLE_HOME).mkdir(parents=True, exist_ok=True)
    (root / GRADLE_HOME / INIT_SCRIPT).write_text(init_script_text(f"{WORKDIR}/{relative}"), encoding="utf-8")

    with _env_file(githubpackages.token()) as env_file:
        log.info(f"staging {group}:{{{','.join(modules)}}}:{resolved} into {relative} with `gradle {STAGE_TASK}`")
        container, lifecycle = docker.lifecycle()
        with docker.stopped_on_interrupt(container):
            rc = stream(docker_argv(pinned, root, env_file, pack_argv(resolved), lifecycle))
    if rc != 0:
        log.error(f"`gradle {STAGE_TASK}` failed (rc={rc}; see output above)")
        return rc
    _, missing = staged(target, group, modules, resolved)
    if missing:
        log.error(f"`gradle {STAGE_TASK}` exited 0 and staged nothing for {', '.join(missing)} at {resolved} "
                  f"under {relative}. A module without a `maven-publish` publication has nothing to publish "
                  f"and does not fail for it - which is what this check exists to catch")
        return 1
    log.ok(f"staged {len(modules)} module(s) as {group}:*:{resolved} into {relative}")
    return 0


def push(name: str = "", tag: str = "") -> int:
    """Upload what `build:maven-pack` staged for this version and read it back (si#344 C.3)."""
    spec = _declared(name, "release:maven")
    (registry, group) = (spec.registry or "", spec.group or "")
    repository_url(registry, checked=True)
    modules = _modules(spec, name)
    resolved = _resolved(spec, name, tag)
    root = context.current().root
    relative = spec.path or ""
    staging = (root / relative).resolve()
    files, missing = staged(staging, group, modules, resolved)
    if missing:
        raise ValueError(f"nothing staged for {resolved} under {relative}: run `build:maven-pack` first "
                         f"(missing: {', '.join(missing)})")

    token = githubpackages.token()
    allowed, said = may_publish(registry, group, modules, resolved, token)
    if not allowed:
        log.error(said)
        return 1
    if said:
        log.warn(said)

    log.info(f"uploading {len(files)} file(s) of {group}:{{{','.join(modules)}}}:{resolved} to "
             f"{repository_url(registry)}")
    status, refused = upload(registry, staging, files, token)
    if status != 0:
        log.error(f"the registry refused {refused} (HTTP {status})\n"
                  f"if it refused rather than the network, the usual cause is a token without the package "
                  f"scopes:\n" + githubpackages.scope_advice())
        return 1

    state, missing_back = verify(registry, group, modules, resolved, token)
    if state == ABSENT:
        log.error(f"every upload was accepted and {repository_url(registry)} does not carry "
                  f"{', '.join(f'{group}:{m}:{resolved}' for m in missing_back)}")
        return 1
    if state == UNKNOWN:
        log.warn(
            f"uploaded, but this task could not VERIFY it: {repository_url(registry)} answered neither "
            f"200 nor 404 for the modules' POMs. That is a token that may not read the registry, or a "
            f"request that never arrived - not evidence that the jars are missing.\n"
            + githubpackages.scope_advice())
        return 0
    if is_snapshot(resolved):
        log.ok(f"{len(modules)} module(s) present as {group}:*:{resolved} at {repository_url(registry)} - a "
               f"snapshot, so this confirms they are THERE and not that this run put them there")
    else:
        log.ok(f"uploaded and read back {len(modules)} module(s) as {group}:*:{resolved} at "
               f"{repository_url(registry)}")
    return 0
```

Add `import shutil` to the imports. Note `push` does not check that `staging` is inside the output root: it only reads.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PY -m pytest src/tests/test_maven.py src/tests/test_catalogue_ports.py src/tests/test_catalogue.py src/tests/test_generated_schema.py src/tests/test_artifactsection.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Measure the staging against a real Gradle**

```bash
S=/tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/gradle-stage
mkdir -p $S/src/main/java/g/h && cd $S
printf 'plugins { id "java-library"; id "maven-publish" }\ngroup = "g.h"\npublishing { publications { core(MavenPublication) { from components.java; artifactId = "core" } } }\n' > build.gradle
printf 'rootProject.name = "core"\n' > settings.gradle
printf 'package g.h; public class A {}\n' > src/main/java/g/h/A.java
mkdir -p build/gradle-home
PY=/root/git/simplon/deploy/orchestrator/.venv/bin/python
$PY -c "from simplon.tasks import maven; print(maven.init_script_text('/work/build/maven'))" > build/gradle-home/simplon-staging.gradle
docker run --rm -u "$(id -u):$(id -g)" -v "$S:/work" -w /work -e GRADLE_USER_HOME=/work/build/gradle-home gradle:9.7.1-jdk21 \
  gradle publishAllPublicationsToSimplonStagingRepository -Pversion=1.0 --init-script /work/build/gradle-home/simplon-staging.gradle --no-daemon -q
find build/maven -type f | sort
$PY -c "from pathlib import Path; from simplon.tasks import maven; f,m=maven.staged(Path('build/maven'),'g.h',['core'],'1.0'); print(m); print([p.name for p in f])"
```

Expected: `build/maven/g/h/core/1.0/core-1.0.jar` (+ `.pom`, `.module`, checksums) and `build/maven/g/h/core/maven-metadata.xml*`; `staged` prints `[]` and the metadata last. Put the `find` output in the commit message. If the layout differs, fix `staged` and its test fixture `_stage` to the measured layout before committing — the measurement wins.

- [ ] **Step 7: See them red**

Make `staged` put metadata first → the order test fails. Drop the `if missing:` block in `pack` → `test_a_pack_that_exits_0_and_staged_nothing_is_a_failed_step` fails. Restore.

- [ ] **Step 8: Full suite, mypy, gates, commit**

As Task 1 Step 7, log file `t2.log`. Commit message title: `feat(si#344): release:maven splits into build:maven-pack and an upload of what was staged`; body names the decision (staging repo + PUT), the measured layout, that the PUT against GitHub is not measured, and the seen-red breaks.

---

### Task 3: The pages say pack, then push

**Files:**
- Modify: `src/site/content/what/handing-a-package-over.md` (lines 16, 38, 74, 186, 219)
- Modify: `src/site/content/with-what/phases.md` (lines 273-274, 291-294, 324)
- Modify: `src/site/content/why/the-design.md` (line 166)
- Modify: `src/site/content/how/manifest.md` (lines 364, 494)
- **Not modified:** `src/site/content/when/releases.md`. Every mention there is inside a released version's section and says what shipped then.
- Test: `src/tests/test_handing_a_package_over_page.py`

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_handing_a_package_over_page.py`:

```python
def test_the_page_says_a_package_is_packed_by_one_command_and_pushed_by_another():
    # arrange
    text = (ROOT / "src" / "site" / "content" / "what" / "handing-a-package-over.md").read_text(encoding="utf-8")

    # assert
    assert "`build:nuget-pack`" in text and "`build:maven-pack`" in text
    assert "a test can consume the package in between" in text
```

(`ROOT` is the name that file already imports from `conftest`; if it uses another name for the repo root, use that one.)

Run: `PY -m pytest src/tests/test_handing_a_package_over_page.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 2: Rewrite the passages**

- `handing-a-package-over.md` line 16 table row: `| a .NET library | `build:nuget-pack`, then `release:nuget` | `build:nuget-config`, then an ordinary restore |`; add a row for Java if the table has one per language: `| a jar | `build:maven-pack`, then `release:maven` | Gradle's own resolution against the registry |`.
- Line 38 paragraph: replace with "`build:nuget-pack` runs `dotnet pack` inside the pinned SDK image and writes `<id>.<version>.nupkg` into the artifact's `path:`. `release:nuget` then runs `dotnet nuget push` on exactly that file. They are two commands so that a test can consume the package in between: the release rule asks for a test result about every artifact a release publishes (si#344)."
- Line 74: `release:nuget` stays (it is still the push).
- Line 186: `| a manifest placing `build:nuget-pack`, `release:nuget` or `release:conan` | none |`.
- Line 219: unchanged (it is about why the coordinate exists).
- `phases.md` 273-274: list `build:maven-pack`, `build:nuget-pack` under build and keep `release:maven`, `release:nuget` under release; in 291-294 add one sentence: "Since si#344 C.3 each of `release:nuget` and `release:maven` pushes what a `build:` command packed, so a test sits between them."
- `the-design.md` 166: add `build:nuget-pack`, `build:maven-pack` to the coordinate list in that row.
- `manifest.md` 364: replace `release:nuget-*` with `build:nuget-pack`, `release:nuget`, and `release:maven` with `build:maven-pack`, `release:maven`. Line 494: "`release:nuget` needs `registry`, `image` and `path`; `build:nuget-pack` needs `image`, `project` and `path`".

- [ ] **Step 3: Pass, build the site, commit**

Run: `PY -m pytest src/tests/test_handing_a_package_over_page.py src/tests/test_tasks_docs.py -q -p no:cacheprovider` (the three root-bound failures stay), then `./simplon.sh build docs` (Hugo via the pinned docker image only).
Commit: `docs(si#344): the pages say a package is packed by one command and pushed by another`.

---

### Task 4: A test writes its result; the publish leaves take `evidence`; simplon tests its image

**Files:**
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (`test_image`, `release_image`, `release_artifact`, `release_conan`, `release_nuget`, `release_maven`)
- Modify: `src/firn/templates/schema.firnt` (lines 65-76), `src/firn/templates/docs.firnt` (where it prints a port's name)
- Modify: `src/simplon/catalogue.yaml` (`test:image` params)
- Create: `src/simplon/domain/results.py`
- Modify: `src/simplon/tasks/image.py` (`smoke`, `_run_once`)
- Modify: `src/simplon/tasks/taskgen.py` (`render`, the leaf branch near line 167), `src/simplon/templates/cli.py.j2` (an import line)
- Modify: `src/simplon/cli/__init__.py` (`_bound`, line 240)
- Modify: `src/simplon/domain/artifactsection.py` (`declared`), `src/simplon/domain/ports.py` (`check`'s annotation, `_check_results`)
- Modify: `src/firn/model/simplon/components/components.firn`, `src/simplon/cli/surface.py`
- Modify: `simplon.yaml`, `.github/workflows/release.yml`
- Test: `src/tests/test_results.py` (new), `src/tests/test_tasks_image.py`, `src/tests/test_taskgen.py`, `src/tests/test_catalogue_ports.py`, `src/tests/test_release_workflow.py`, `src/tests/test_refusal_census.py`

**Interfaces:**
- Produces, in `simplon.domain.results`:
  - `Snapshot = dict[str, tuple[Path, int | None]]` (artifact name -> its path and its newest mtime_ns before the body, `None` when absent).
  - `before(produced: Sequence[str]) -> Snapshot`: only the produced artifacts whose kind refines `test-result`.
  - `held(snapshot: Snapshot, rc: int) -> int`: `rc` when non-zero; else 1 with an error naming every result path the body did not write; else 0.
  - `path_of(name: str) -> Path`: the absolute path of the `test-result` entry `name`.
- Produces, in `simplon.domain.artifactsection`: `class Declared(NamedTuple): kind: str; registry: bool; path: str`, and `declared(document) -> dict[str, Declared]`.
- Produces, in `PORTS`: `test:image` gains `Port("test-result", "output", "test-result", "results", ("path",))`; each of `release:image`, `release:artifact`, `release:conan`, `release:nuget`, `release:maven` gains `Port("evidence", "input", "test-result", "", ())` after its artifact port.
- Produces, in `image.smoke`: a new keyword `results: str = ""`.

- [ ] **Step 1: Write the failing tests**

`test_catalogue_ports.py`, in the literal:

```python
        "test:image": (P("image", "input", "image", "name", IMAGE_NEEDS),
                       P("test-result", "output", "test-result", "results", ("path",))),
        "release:image": (P("image", "input", "image", "name", IMAGE_NEEDS), EVIDENCE),
        "release:artifact": (P("directory", "input", "directory", "name", OCI_NEEDS), EVIDENCE),
        "release:conan": (P("conan", "input", "conan", "name", OCI_NEEDS), EVIDENCE),
        "release:nuget": (P("nuget", "input", "nuget", "name", ("registry", "image", "path")), EVIDENCE),
        "release:maven": (P("maven", "input", "maven", "name", ("registry", "group", "modules", "path")), EVIDENCE),
```

with `EVIDENCE = P("evidence", "input", "test-result", "", ())` beside `OCI_NEEDS`.

Create `src/tests/test_results.py`:

```python
"""si#344 C.3: a producer that exits 0 without writing its test result is a failed step.

A test result declared and never written would be "nothing to do" passing for "tested" - the house defect -
so `results.held` compares each result's state before and after the body, not whether a file exists.

AAA; the name states the behaviour under test.
"""
import os
import time

import pytest

from simplon.domain import context, results
from simplon.domain.context import ProductContext

_MANIFEST = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  checked: { kind: test-result, path: build/test/app.json }
  report: { kind: test-result, path: build/test/report }
"""


@pytest.fixture(autouse=True)
def _product(tmp_path, monkeypatch):
    (tmp_path / "demo.yaml").write_text(_MANIFEST, encoding="utf-8")
    monkeypatch.setattr(context, "_current", ProductContext("demo", tmp_path, tmp_path / "demo.yaml"))
    return tmp_path


def test_a_result_the_body_wrote_holds_the_rc(_product):
    # arrange
    snap = results.before(("checked",))
    (_product / "build" / "test").mkdir(parents=True)
    (_product / "build" / "test" / "app.json").write_text("{}", encoding="utf-8")

    # act / assert
    assert results.held(snap, 0) == 0


def test_a_result_not_written_turns_rc_0_into_1_naming_the_path(_product, capsys):
    # arrange
    snap = results.before(("checked",))

    # act
    rc = results.held(snap, 0)

    # assert
    assert rc == 1
    assert "build/test/app.json" in capsys.readouterr().err


def test_a_result_left_from_an_earlier_run_does_not_count_as_written(_product):
    # arrange: yesterday's file is there before the body runs, and the body does not touch it
    (_product / "build" / "test").mkdir(parents=True)
    old = _product / "build" / "test" / "app.json"
    old.write_text("{}", encoding="utf-8")
    os.utime(old, ns=(time.time_ns() - 10**10, time.time_ns() - 10**10))
    snap = results.before(("checked",))

    # act / assert
    assert results.held(snap, 0) == 1


def test_a_directory_result_counts_when_a_file_inside_it_is_new(_product):
    # arrange
    snap = results.before(("report",))
    (_product / "build" / "test" / "report").mkdir(parents=True)
    (_product / "build" / "test" / "report" / "a.json").write_text("{}", encoding="utf-8")

    # act / assert
    assert results.held(snap, 0) == 0


def test_a_failing_body_keeps_its_own_rc(_product):
    # act / assert
    assert results.held(results.before(("checked",)), 3) == 3


def test_an_artifact_that_is_not_a_test_result_is_not_watched(_product):
    # act / assert
    assert results.before(("app",)) == {}


def test_path_of_refuses_an_entry_that_is_not_a_test_result(_product):
    # act / assert
    with pytest.raises(ValueError, match="is a `image`, not a `test-result`"):
        results.path_of("app")
```

In `src/tests/test_tasks_image.py`, after the smoke tests, add:

```python
def test_a_smoke_run_writes_its_verdict_record_to_the_result_it_is_bound_to(cli, _no_provenance, _product,
                                                                           _tagged, monkeypatch):
    # arrange
    text = (_product / "demo.yaml").read_text(encoding="utf-8")
    (_product / "demo.yaml").write_text(
        text + "  app-checked: { kind: test-result, path: build/test/app.json }\n", encoding="utf-8")
    monkeypatch.setattr(image, "present_locally", lambda ref: True)

    # act
    rc = image.smoke("app", argv="check", results="app-checked")

    # assert
    assert rc == 0
    record = json.loads((_product / "build" / "test" / "app.json").read_text(encoding="utf-8"))
    assert record["image"] == "app"
    assert record["verdict"] == 0
    assert record["runs"] == [{"reference": "ghcr.io/owner/demo-app:1.2.3", "platform": "", "argv": "check",
                               "expected_rc": 0, "rc": 0, "verdict": 0}]


def test_a_failing_smoke_run_still_writes_its_record_with_the_failure(cli, _no_provenance, _product, _tagged,
                                                                      monkeypatch):
    # arrange
    text = (_product / "demo.yaml").read_text(encoding="utf-8")
    (_product / "demo.yaml").write_text(
        text + "  app-checked: { kind: test-result, path: build/test/app.json }\n", encoding="utf-8")
    monkeypatch.setattr(image, "present_locally", lambda ref: True)
    cli.answer("docker", "run", rc=2)

    # act
    rc = image.smoke("app", argv="check", results="app-checked")

    # assert
    assert rc == 2
    record = json.loads((_product / "build" / "test" / "app.json").read_text(encoding="utf-8"))
    assert record["verdict"] == 2
```

Check how `_Cli` (top of `test_tasks_image.py`) lets a test choose a `docker run` exit code, and use that mechanism in place of `cli.answer(...)` if its name differs; the `_MANIFEST` there must already end with the `artifacts:` block's last entry (the appended line is indented as an entry). Add `import json` at the top if absent.

In `src/tests/test_taskgen.py`, add (using the manifest-building helper the file already has for a leaf command; copy its shape):

```python
def test_a_command_that_produces_wraps_its_call_in_the_result_check():
    # arrange: a leaf bound to produce `checked`
    text = _render_with_produces({"test-result": ("checked",)})

    # assert
    assert "_results.held(_results.before(('checked',)), _rc(" in text
    assert "from simplon.domain import results as _results" in text


def test_a_command_that_produces_nothing_has_no_result_check():
    # arrange
    text = _render_with_produces({})

    # assert
    assert "_results" not in text
```

where `_render_with_produces(produces)` builds a `Manifest` with one group `test` holding one command whose `CommandSpec(impl="simplon.test_impls:noop", help="h", produces=produces)`, and returns `taskgen.render(manifest, source="m.yaml", product="demo")`. Use an impl the file's other tests already render (search `test_taskgen.py` for `test_impls`), not a new one.

In `src/tests/test_release_workflow.py`, add:

```python
def test_the_release_tests_the_image_between_building_and_publishing_it():
    # arrange
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    # assert
    build = text.index("./simplon.sh build image --tag")
    test = text.index("./simplon.sh test image --tag")
    release = text.index("./simplon.sh release push-image --tag")
    assert build < test < release
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_results.py src/tests/test_tasks_image.py src/tests/test_taskgen.py src/tests/test_catalogue_ports.py src/tests/test_release_workflow.py -q -p no:cacheprovider`
Expected: FAIL (no module `simplon.domain.results`; `smoke() got an unexpected keyword argument 'results'`; literal mismatch; no `test image` line).

- [ ] **Step 3: Model, templates, catalogue; regenerate**

In `tasks.firn`, add to `test_image`, after its `input image` block:

```
  output test_result typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.test_result
    param = "results"
    needs = simplon.vocabulary.artifact.f_path
  }
```

and to each of `release_image`, `release_artifact`, `release_conan`, `release_nuget`, `release_maven`, after its artifact port:

```
  input evidence typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.test_result
  }
```

In `src/firn/templates/schema.firnt`, in the four `Port(...)` lines (65, 68, 73, 76), replace `Port("${p.name}"` with `Port("${p.name.replace("_", "-")}"`. In `src/firn/templates/docs.firnt`, apply the same `.replace("_", "-")` wherever a port's `name` is printed (search the file for `p.name`).

In `catalogue.yaml` (protected region), `test:image` `params:` gains:

```yaml
      results: { help: "the test result to write the verdict record to (normally bound with `produces:`)" }
```

Run `./simplon.sh build model`; read the diffs. `PORTS` must show `"test-result"`, not `"test_result"`.

- [ ] **Step 4: `artifactsection.declared` carries the path**

In `src/simplon/domain/artifactsection.py`, replace `declared` with:

```python
class Declared(NamedTuple):
    """What the port rules read of one `artifacts:` entry (si#344 C.2, C.3)."""

    kind: str
    registry: bool
    path: str


def declared(document: Mapping[str, object]) -> dict[str, Declared]:
    """Each `artifacts:` entry -> its kind, whether it names a `registry:`, and its `path:` ("" for none).
    `check` has refused an entry without a kind before this is asked."""
    section = document.get(SECTION)
    if not isinstance(section, Mapping):
        return {}
    return {str(name): Declared(str(body["kind"]), bool(body.get("registry")), str(body.get("path") or ""))
            for name, body in section.items() if isinstance(body, Mapping) and "kind" in body}
```

Add `from typing import NamedTuple` if absent. In `ports.py`, change `check`'s annotation to `declared: Mapping[str, "artifactsection.Declared"]`; the `[0]`/`[1]` reads stay valid, but write them as `.kind`/`.registry`.

- [ ] **Step 5: A produced test result needs a `path:`, and only `ci: test:` produces one**

The second half of this step is the spec's expression rule "test result produced outside `ci: test:`"; it lands here because simplon's adoption in Step 9 must already satisfy it. In `ports.py`, add after `_check_plan`:

```python
#: The kinds a release produces about itself (si#344 C.3, decided 2026-10-14). The release rule asks for test
#: results about every OTHER artifact a release command consumes: the notes, the tag, the bundle and the
#: evidence itself are not what a release publishes.
OWN_KINDS = ("test-result", "release-notes", "tag", "release")


def _top(group: str) -> str:
    return group.split(".", 1)[0]


def _check_results(manifest: "Manifest", declared: Mapping[str, "artifactsection.Declared"],
                   kinds: Mapping[str, str]) -> dict[str, set[str]]:
    """A produced test result has a `path:` and is produced under `ci: test:` (si#344 C.3). Returns what
    each artifact's test results are: artifact -> the results whose producer consumes it."""
    about: dict[str, set[str]] = {}
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            made = [a for names in spec.produces.values() for a in names
                    if artifactsection.accepts(kinds, "test-result", declared[a].kind)]
            if not made:
                continue
            where = f"{group} {name}"
            for result in made:
                if not declared[result].path:
                    raise ValueError(
                        f"command '{where}' produces the test result '{result}', which declares no `path:` - "
                        f"a test result is what the test writes, so name where")
            if (manifest.area_of(group), _top(group)) != ("ci", "test"):
                raise ValueError(
                    f"command '{where}' produces the test result '{made[0]}' outside `ci: test:` - a test "
                    f"result is evidence that a test ran, so only a command under `ci: test:` produces one")
            for subject in (a for names in spec.consumes.values() for a in names):
                about.setdefault(subject, set()).update(made)
    return about
```

and call it at the end of `check`: `_check_results(manifest, declared, kinds)` (Task 5 uses its return value).

Census, in `src/tests/test_refusal_census.py` `CENSUS` under the ports block:

```python
    ("ports", "_check_results", "a test result is what the test writes"): DIAGNOSIS,
    ("ports", "_check_results", "so only a command under `ci: test:` produces one"): EXPRESSION,
```

and in `REACH`: `("ports", "_check_results", "so only a command under `ci: test:` produces one"): REACH_MERGED,`. In `TREE_MODULES`, add `"ports"`: `TREE_MODULES = ("manifest", "treeform", "ports")`, and in `_populations`, extend the module loop to `for module in (treeform, manifest_mod, ports_mod):` with `from simplon.domain import ports as ports_mod` beside the other import there. Run the census suite: `test_every_merged_reach_expression_rule_ruled_on_the_kernels_own_declarations` now measures the new rule. If it says the rule was not handed the kernel's half, the label is wrong: change it to what the measurement says and report it in the commit, do not bend the measurement.

Add two tests to a new `src/tests/test_release_rule.py` (Task 5 extends it):

```python
"""si#344 C.3: test results, and the release rule (spec C.3, C.5 rule 6).

AAA; the name states the behaviour under test.
"""
import pytest

from simplon.domain import catalogue, manifest

HEAD = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
"""


def _load(text):
    return manifest.load(text, catalogue=catalogue.load())


def test_a_test_result_without_a_path_is_refused_by_name():
    # arrange
    text = HEAD.replace("{ kind: test-result, path: build/test/app.json }", "{ kind: test-result }") + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
"""

    # act / assert
    with pytest.raises(ValueError, match="which declares no `path:`"):
        _load(text)


def test_a_test_result_produced_outside_ci_test_is_refused():
    # arrange: a build command writes a result through toolchain:run's generic output port
    text = HEAD + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
      check: { task: "toolchain:run", consumes: { source: app }, produces: { out: app-checked } }
"""

    # act / assert
    with pytest.raises(ValueError, match="outside `ci: test:`"):
        _load(text)
```

Check `manifest.load`'s real signature in `src/simplon/domain/manifest.py` (the C.2 tests in `src/tests/test_port_bindings.py` call it; copy their `_load` helper verbatim instead of the one above if it differs). `toolchain:run` may need `with:` keys to load (its body's required parameters); copy a loading `toolchain:run` command from `test_port_bindings.py`.

- [ ] **Step 6: The run-time check**

Create `src/simplon/domain/results.py`:

```python
"""A producer that exits 0 without writing its test result is a failed step (si#344 C.3, spec C.3).

A test result declared and never written would be "nothing to do" passing for "tested", which is the house
defect. So both dispatch paths - the generated module (`taskgen`) and `cli.assemble` - snapshot every test
result a command produces BEFORE its body runs, and `held` compares after it: a file that is absent, or no
newer than it was, was not written by this run. "Exists" would not do: yesterday's file exists.

Only `test-result` artifacts are watched. Which those are is read at run time from `artifacts:`, because the
generated module is rendered from the manifest's commands and does not carry the section.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from simplon.domain import artifactsection, context
from simplon.kernel import log

#: artifact name -> (its absolute path, its newest mtime_ns before the body ran, or None when absent)
Snapshot = dict[str, tuple[Path, "int | None"]]


def _section() -> dict:
    ctx = context.current()
    section = ctx.manifest_data().get(artifactsection.SECTION) or {}
    return section if isinstance(section, dict) else {}


def path_of(name: str) -> Path:
    """The absolute path of the `test-result` entry `name`, refused by name when it is not one."""
    ctx = context.current()
    body = _section().get(name)
    if not isinstance(body, dict):
        raise ValueError(f"no artifact '{name}' in {ctx.manifest_path.name}'s `artifacts:` section")
    kind = str(body.get("kind", ""))
    if not artifactsection.is_a(kind, "test-result"):
        raise ValueError(f"artifact '{name}' is a `{kind}`, not a `test-result` - a test writes its verdict "
                         f"only to a test result")
    if not body.get("path"):
        raise ValueError(f"test result '{name}' declares no `path:` - a test result is what the test writes")
    return ctx.root / str(body["path"])


def _newest(path: Path) -> "int | None":
    if path.is_file():
        return path.stat().st_mtime_ns
    if path.is_dir():
        stamps = [p.stat().st_mtime_ns for p in path.rglob("*") if p.is_file()]
        return max(stamps) if stamps else None
    return None


def before(produced: Sequence[str]) -> Snapshot:
    """Each produced artifact that is a test result, with its state before the body runs."""
    section = _section()
    out: Snapshot = {}
    for name in produced:
        body = section.get(name)
        if isinstance(body, dict) and artifactsection.is_a(str(body.get("kind", "")), "test-result"):
            path = path_of(name)
            out[name] = (path, _newest(path))
    return out


def held(snapshot: Snapshot, rc: int) -> int:
    """`rc`, unless it is 0 and a test result in `snapshot` was not written by this run: then 1."""
    if rc != 0:
        return rc
    root = context.current().root
    unwritten = [f"'{name}' ({path.relative_to(root) if path.is_relative_to(root) else path})"
                 for name, (path, then) in snapshot.items()
                 if (now := _newest(path)) is None or (then is not None and now <= then)]
    if unwritten:
        log.error(f"exited 0 and did not write the test result(s) {', '.join(unwritten)} - a test that "
                  f"wrote no result has not said it passed")
        return 1
    return 0
```

Check `artifactsection.is_a(kind, wanted)` (line 69) answers refinement through the generated table; if it takes other arguments, use `artifactsection.accepts(artifactsection.REFINES, wanted, kind)`.

This module calls `manifest_data()`: add it to `READS_INLINE` in the census with `"domain.results": "`before`/`path_of` read `artifacts:` at RUN time, around a body the dispatcher is calling - the read and the run are one wrapper (si#344 C.3)",` and add `CENSUS` entries for its three raises (`("results", "path_of", "in {"` will not work: fragments are literal text, so use `"s `artifacts:` section"`, `"not a `test-result` - a test writes"`, `"a test result is what the test writes"` and let `test_every_census_key_names_exactly_one_refusal` tell you if one matches two — `_check_results` has the same last fragment in another module, which is fine because the key includes the module). All three are `DIAGNOSIS`.

Register the module in the architecture: in `components.firn`, beside `m_domain_ports`:

```
  module m_domain_results typeOf simplon.architecture.Module {
    path = "domain.results"
  }
```

It is NOT added to `surface.INTERNAL`: a generated product module imports it. Run `./simplon.sh build model` (regenerates `architecture.md` and `src/tests/generated/architecture.py`); if `test_surface` asks for a classification, follow its message.

Wire the generated path. In `taskgen.render`, in the leaf branch, after `call = _call(...)`:

```python
                produced = tuple(a for names in spec.produces.values() for a in names)
                if produced:
                    uses_results = True
                    wrapped = f"_results.held(_results.before({produced!r}), _rc({call}))"
                else:
                    wrapped = f"_rc({call})"
                tasks.append({"func": func, "help_repr": repr(_docstring(spec, impl_body)),
                              "signature": _signature(params, takes_context=takes_ctx),
                              "call": wrapped})
```

with `uses_results = False` initialised beside `has_aggregate = False`, and pass `uses_results=uses_results` into the template's `render(...)` call at line 263. `before` is the first argument, so Python evaluates it before the body runs. In `src/simplon/templates/cli.py.j2`, after `import typer`:

```
{% if uses_results %}
from simplon.domain import results as _results
{% endif %}
```

Wire the assembled path. In `src/simplon/cli/__init__.py` `_bound`, replace the wrapper body:

```python
    produced = tuple(a for names in (spec.produces or {}).values() for a in names)

    @functools.wraps(fn)
    def _wrapped(*args: object, **kwargs: object) -> None:
        if not produced:
            raise typer.Exit(code=_rc(fn(*args, **{**kwargs, **pinned})))
        snapshot = results.before(produced)
        raise typer.Exit(code=results.held(snapshot, _rc(fn(*args, **{**kwargs, **pinned}))))
```

with `from simplon.domain import results` among that module's imports. Add a test beside the existing `_bound` tests (search `src/tests/` for `_bound(` and put it in that file): a body bound with `produces={"test-result": ("checked",)}` that returns 0 and writes nothing exits 1.

- [ ] **Step 7: `test:image` writes its verdict record**

In `src/simplon/tasks/image.py`:

`_run_once` returns its verdict and the container's rc. Change its return type to `tuple[int, int]` — `(verdict, result.rc)` — at all three returns (`(result.rc or 1, result.rc)`, `(1, result.rc)`, `(0, result.rc)`), and in `smoke`:

```python
def smoke(name: str = "", tag: str = "", argv: str = "", mount: str = "", expect: str = "",
          rc: int = 0, user: bool = True, platform: str = "", results: str = "") -> int:
```

Add to the docstring: `**`results` is the test result the verdict record goes to** (si#344 C.3): the command binds it with `produces: { test-result: <artifact> }`. The record is written on a red run too - a release reads it as evidence that the test RAN, and the rc says how it went.`

After `if not _platform_declared(...)` and before the runs, resolve the path so a wrong entry is refused before docker starts: `record_path = results_mod.path_of(results) if results else None` (import `from simplon.domain import results as results_mod` — the module-level name `results` is the parameter). Replace the verdict lines:

```python
    outcomes = [(one, each, *_run_once(each, [*(["--platform", one] if one else []), *options], argv, expect, rc))
                for one, each in runs]
    verdict = next((v for _, _, v, _ in outcomes if v != 0), 0)
    if record_path is not None:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps({
            "image": name, "verdict": verdict,
            "runs": [{"reference": each, "platform": one, "argv": argv, "expected_rc": rc, "rc": got,
                      "verdict": v} for one, each, v, got in outcomes]}, indent=2) + "\n", encoding="utf-8")
    return verdict
```

Add `import json` if the module lacks it. The early `return 1`s (daemon does not hold the image; bad mount) write no record, and `results.held` does not turn a non-zero rc into anything else, so that stays rc 1.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PY -m pytest src/tests/test_results.py src/tests/test_tasks_image.py src/tests/test_taskgen.py src/tests/test_catalogue_ports.py src/tests/test_release_rule.py src/tests/test_refusal_census.py -q -p no:cacheprovider`
Expected: PASS except `test_the_release_tests_the_image_between_building_and_publishing_it` (Step 9).

- [ ] **Step 9: simplon tests its own image and releases with the evidence**

Measure first what the kernel image answers:

```bash
./simplon.sh build image --platform linux/amd64
docker run --rm "$(./deploy/orchestrator/.venv/bin/python -c "from simplon.tasks import image; print('ghcr.io/marcozwyssig/simplon')")":"$(git describe --tags --always)" --help | head -5; echo "rc=$?"
```

Use the reference `build image` printed in its last `ok` line if the second command names the wrong tag. Note the first line of the help output; `expect:` below takes a short, stable piece of it (the product's usage line). If the image does not answer `--help` with rc 0, stop and report: the test must assert something the image really does.

In `simplon.yaml`, under `ci: test: commands:`, add (comment in the file's own voice, keep it short):

```yaml
      # The kernel's image, RUN (si#344 C.3). The release rule asks for a test result about every artifact
      # a release publishes, and `release image` publishes `kernel` - which until this nothing ran. The
      # verdict record it writes is the evidence `release image` consumes.
      image:
        task: "test:image"
        consumes: { image: kernel }
        produces: { test-result: kernel-checked }
        with: { argv: "--help", expect: "<the measured usage fragment>" }
```

Under `ci: release: commands:`, rename `image:` to `push-image:` (decision 5: Task 7's aggregate must be able to name it, and `image` is also `build image` and `test image`) and bind the evidence. Keep the comment block above it and add one line to it: `# Named push-image, not image, since si#344 C.3: an aggregate plans a leaf by a name only one group owns (#519).`

```yaml
      push-image:
        task: "release:image"
        consumes:
          image: kernel
          evidence: [kernel-checked]
```

Follow the rename everywhere it is spelled (measured while planning): `.github/workflows/release.yml:325` becomes `./simplon.sh release push-image --tag "$GITHUB_REF_NAME"`; `src/tests/test_own_image.py:371,373,381` read `release push-image`. `grep -rn "release image" --include=*.py --include=*.yml --include=*.md . | grep -v when/releases.md` must then show only other products' commands (`agile-cockpit`, `myctl`) and the old plans.

Under `artifacts:`, after `kernel:`:

```yaml
  # The verdict record `test image` writes about `kernel` (si#344 C.3): one producer, and what it is about
  # is derived from what that producer consumes.
  kernel-checked:
    kind: test-result
    path: build/test/kernel-image.json
```

In `.github/workflows/release.yml`, between line 324 (`build image`) and line 325 (now `release push-image`):

```yaml
      - run: ./simplon.sh test image --tag "$GITHUB_REF_NAME"
```

`test image` runs every declared platform; arm64 runs under the same QEMU the arm64 build already needs.

Run: `./simplon.sh test image` (after the amd64 build above; it runs the declared platforms — if arm64 is not built locally, pass `--platform linux/amd64`) and then `cat build/test/kernel-image.json`.
Expected: rc 0, a record with `"verdict": 0`.

- [ ] **Step 10: See them red, full suite, gates, commit**

Break `held`'s `now <= then` into `now is None` only → `test_a_result_left_from_an_earlier_run_does_not_count_as_written` fails. Remove the record write → the smoke record test fails. Remove `produced` from `taskgen` → the taskgen test fails. Restore each. Full suite to `t4.log`, mypy, stage, `./simplon.sh test generated`, `./simplon.sh test model`. Update `rules.md`'s numbers. Commit: `feat(si#344): a test writes its result, the publish leaves take evidence, and simplon tests its image`.

---

### Task 5: Rule 6 — a release consumes every test result about what it publishes

**Files:**
- Modify: `src/simplon/domain/ports.py` (`check`, new `_check_release`)
- Modify: `src/tests/realmanifests.py`, `src/tests/test_migrate.py` (`test_a_migrated_real_manifest_assembles_the_cli_it_always_did`, line 793)
- Modify: `src/tests/test_refusal_census.py`, `src/site/content/with-what/rules.md`
- Test: `src/tests/test_release_rule.py`

**Interfaces:**
- Consumes: `_check_results(...) -> dict[str, set[str]]`, `OWN_KINDS`, `_top` (Task 4).
- Produces: `ports._check_release(manifest, declared, kinds, about) -> None`; `realmanifests.RELEASE_RULE_BILL = frozenset({"agile-cockpit", "firn", "simplon"})`.

- [ ] **Step 1: Write the failing tests**

Append to `src/tests/test_release_rule.py`:

```python
CHAIN = HEAD + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""


def test_a_release_with_every_result_about_its_artifact_loads():
    # act
    loaded = _load(CHAIN)

    # assert
    assert loaded.spec_for("release", "image").consumes["evidence"] == ("app-checked",)


def test_an_untested_release_is_refused_naming_the_artifact():
    # arrange: no test consumes `app`
    text = HEAD + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: app } }
"""

    # act / assert
    with pytest.raises(ValueError, match="releases 'app', and no test produces a result about it"):
        _load(text)


def test_a_release_leaving_out_one_result_is_refused_naming_it():
    # arrange: a second test on `app`, and the release consumes only the first result
    text = CHAIN.replace("artifacts:\n", "artifacts:\n  app-ran: { kind: test-result, path: build/test/ran.json }\n").replace(
        "  release:\n",
        '      ran: { task: "test:image", consumes: { image: app }, produces: { test-result: app-ran } }\n  release:\n')

    # act / assert
    with pytest.raises(ValueError, match=r"without the test result\(s\) app-ran about it"):
        _load(text)


def test_a_test_of_what_the_artifact_was_built_from_is_not_about_it():
    # arrange: the only test consumes the SOURCE directory, not the image built from it
    # `src` names a registry, so rule 2 (a consumer without a producer) lets it through as an external input
    text = HEAD.replace("artifacts:\n", "artifacts:\n  src: { kind: directory, path: src, registry: ghcr.io/o }\n") + """
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      unit: { task: "toolchain:run", consumes: { source: src }, produces: { out: app-checked } }
  release:
    commands:
      image: { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
"""

    # act / assert
    with pytest.raises(ValueError, match="releases 'app', and no test produces a result about it"):
        _load(text)


def test_a_release_command_consuming_only_its_own_kinds_needs_no_evidence():
    # arrange: release:tag consuming notes (Task 6 gives release:tag its port; until then a product task
    # with an input port accepting release-notes stands in)
    text = HEAD.replace("artifacts:\n", "artifacts:\n  notes: { kind: release-notes, path: build/notes.md }\n") + """
tasks:
  announce: { impl: "simplon.test_impls:noop", input: { notes: { accepts: release-notes } } }
  write:    { impl: "simplon.test_impls:noop", output: { notes: { accepts: release-notes } } }
ci:
  release:
    commands:
      notes:    { task: write, produces: { notes: notes } }
      announce: { task: announce, consumes: { notes: notes } }
"""

    # act / assert: loads
    _load(text)
```

(`simplon.test_impls` holds impls the suite already uses; pick one taking no required parameter, as `test_port_bindings.py` does for product tasks.)

Extend `src/tests/realmanifests.py`:

```python
#: The products whose migrated fixture the release rule refuses (si#344 C.3): each releases an image no test
#: writes a result about. Measured over the eight on 2026-10-14; the live manifests agree (si#344 C.3 plan).
RELEASE_RULE_BILL = frozenset({"agile-cockpit", "firn", "simplon"})
```

In `src/tests/test_migrate.py`, change `test_a_migrated_real_manifest_assembles_the_cli_it_always_did` (line 793) so a product in `RELEASE_RULE_BILL` asserts the refusal instead of the surface, and add a test that pins the set:

```python
def test_the_release_rule_refuses_exactly_the_products_that_release_untested():
    # arrange / act
    refused = set()
    for product in PRODUCTS:   # the parametrisation list the file already uses for the eight
        try:
            _assemble(product)    # the helper the surface test uses to migrate and load
        except ValueError as exc:
            if "no test produces a result about it" in str(exc):
                refused.add(product)

    # assert
    assert refused == realmanifests.RELEASE_RULE_BILL
```

Use the names `test_migrate.py` already has for the product list and for "migrate and load"; read lines 520-560 and 793-822 first.

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_release_rule.py src/tests/test_migrate.py -q -p no:cacheprovider`
Expected: FAIL — the untested release loads; the bill test finds an empty set.

- [ ] **Step 3: Implement rule 6**

In `ports.py`, add:

```python
def _check_release(manifest: "Manifest", declared: Mapping[str, "artifactsection.Declared"],
                   kinds: Mapping[str, str], about: Mapping[str, set[str]]) -> None:
    """Rule 6 (spec C.3, C.5): a command under `ci: release:` that consumes an artifact X consumes every test
    result about X, and at least one exists. X is every consumed artifact whose kind is not one of OWN_KINDS
    (decided 2026-10-14). "About" is direct: a result is about what its producer consumes."""
    for group, members in manifest.commands.items():
        if (manifest.area_of(group), _top(group)) != ("ci", "release"):
            continue
        for name, spec in members.items():
            where = f"{group} {name}"
            consumed = [a for names in spec.consumes.values() for a in names]
            evidence = {a for a in consumed if artifactsection.accepts(kinds, "test-result", declared[a].kind)}
            for subject in consumed:
                if any(artifactsection.accepts(kinds, own, declared[subject].kind) for own in OWN_KINDS):
                    continue
                wanted = about.get(subject, set())
                if not wanted:
                    raise ValueError(
                        f"command '{where}' releases '{subject}', and no test produces a result about it - add "
                        f"a command under `ci: test:` that consumes '{subject}' and produces a `test-result`, "
                        f"and bind that result to this command's `evidence` port")
                missing = sorted(wanted - evidence)
                if missing:
                    raise ValueError(
                        f"command '{where}' releases '{subject}' without the test result(s) "
                        f"{', '.join(missing)} about it - bind every one to its `evidence` port, so no "
                        f"release goes past a test that ran")
```

In `check`, replace the Task 4 call with:

```python
    about = _check_results(manifest, declared, kinds)
    _check_release(manifest, declared, kinds, about)
```

Census: `("ports", "_check_release", "and no test produces a result about it"): EXPRESSION,` and `("ports", "_check_release", "so no release goes past a test that ran"): EXPRESSION,`, both `REACH_MERGED` in `REACH`. Run the census suite; let the reach measurement confirm or correct the labels. Update `rules.md`'s two tables to the printed numbers.

- [ ] **Step 4: Pass, see red, full suite, commit**

Run the Step 2 command → PASS. Remove the `if not wanted:` raise → `test_an_untested_release_is_refused_naming_the_artifact` and the bill test fail; remove the `missing` raise → the leave-one-out test fails; delete the `OWN_KINDS` `continue` → the own-kinds test fails. Restore. Full suite to `t5.log`; `./simplon.sh test generated` (simplon.yaml loads under the rule because of Task 4). Commit: `feat(si#344): rule 6 - a release consumes every test result about what it publishes`; the body names the bill (firn, simplon paid, agile-cockpit) and that agile-cockpit's answer is open.

---

### Task 6: `release:notes` writes the notes; `release:tag` consumes them and produces the tag

**Files:**
- Modify: `src/firn/model/simplon/catalogue/tasks.firn` (new `release_notes`, `release_tag`)
- Modify: `src/simplon/catalogue.yaml` (protected region: `release:notes` before `release:tag`)
- Modify: `src/simplon/tasks/releasenotes.py` (new `render`, `write`; module docstring)
- Test: `src/tests/test_tasks_releasenotes.py`, `src/tests/test_catalogue_ports.py`

**Interfaces:**
- Consumes: `releasenotes.released_versions`, `merges_in`, `tickets_of`, `tag_of`, `_git` (all existing).
- Produces:
  - `releasenotes.render(root: Path, tag: str) -> str`: `## <tag>` and one bullet per merge since the previous `vX.Y.Z` tag (whole history when there is none), newest first, each `- <subject> (#n, #m)`.
  - `releasenotes.write(name: str = "", tag: str = "") -> int`: renders and writes to the `release-notes` entry's `path:`.
  - `PORTS["release:notes"] = (Port("release-notes", "output", "release-notes", "name", ("path",)),)`; `PORTS["release:tag"] = (Port("release-notes", "input", "release-notes", "", ()), Port("tag", "output", "tag", "", ()))`.

- [ ] **Step 1: Write the failing tests**

`test_catalogue_ports.py` literal gains:

```python
        "release:notes": (P("release-notes", "output", "release-notes", "name", ("path",)),),
        "release:tag": (P("release-notes", "input", "release-notes", "", ()), P("tag", "output", "tag", "", ())),
```

Append to `src/tests/test_tasks_releasenotes.py`:

```python
# --- release:notes - generating the notes from the same walk (si#344 C.3, spec decision 16) -------------

def test_the_notes_list_every_merge_since_the_previous_tag_with_its_tickets(tmp_path):
    # arrange
    root = _repo(tmp_path)
    _commit(root, "start")
    _git(root, "tag", "v0.1.0")
    _merge(root, "si12-thing", ["feat(si#12): a thing"], "Merge si12-thing (si#12)")
    _merge(root, "si13-other", ["fix(si#13): another"], "Merge si13-other (si#13, si#14)")

    # act
    text = releasenotes.render(root, "v0.2.0")

    # assert
    assert text.splitlines()[0] == "## v0.2.0"
    assert "- Merge si13-other (si#13, si#14) (#13, #14)" in text
    assert "- Merge si12-thing (si#12) (#12)" in text
    assert text.index("si13-other") < text.index("si12-thing")


def test_without_a_previous_tag_the_notes_cover_the_whole_history(tmp_path):
    # arrange
    root = _repo(tmp_path)
    _commit(root, "start")
    _merge(root, "si12-thing", ["feat(si#12): a thing"], "Merge si12-thing (si#12)")

    # act
    text = releasenotes.render(root, "v0.1.0")

    # assert
    assert "- Merge si12-thing (si#12) (#12)" in text


def test_a_range_with_no_merge_says_so_rather_than_writing_an_empty_section(tmp_path):
    # arrange
    root = _repo(tmp_path)
    _commit(root, "start")
    _git(root, "tag", "v0.1.0")

    # act
    text = releasenotes.render(root, "v0.1.1")

    # assert
    assert "no merge since v0.1.0" in text


def test_write_puts_the_notes_where_the_artifact_says(tmp_path, monkeypatch):
    # arrange
    root = _repo(tmp_path)
    _commit(root, "start")
    _manifest(monkeypatch, root, "product: sample\nartifacts:\n  notes: { kind: release-notes, path: build/release/notes.md }\n")

    # act
    rc = releasenotes.write("notes", "v0.1.0")

    # assert
    assert rc == 0
    assert (root / "build" / "release" / "notes.md").read_text(encoding="utf-8").startswith("## v0.1.0")


def test_write_without_a_tag_is_refused_by_name(tmp_path, monkeypatch):
    # arrange
    root = _repo(tmp_path)
    _manifest(monkeypatch, root, "product: sample\nartifacts:\n  notes: { kind: release-notes, path: build/notes.md }\n")

    # act / assert
    with pytest.raises(ValueError, match="which release\\? pass the tag"):
        releasenotes.write("notes", "")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_tasks_releasenotes.py src/tests/test_catalogue_ports.py -q -p no:cacheprovider` → FAIL (no `render`).

- [ ] **Step 3: Model and catalogue**

`tasks.firn`:

```
release_notes typeOf simplon.pipeline.CatalogueTask {
  key = "release:notes"
  body = "simplon.tasks.releasenotes:write"
  output release_notes typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.release_notes
    param = "name"
    needs = simplon.vocabulary.artifact.f_path
  }
}
release_tag typeOf simplon.pipeline.CatalogueTask {
  key = "release:tag"
  body = "simplon.tasks.release:tag"
  input release_notes typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.release_notes
  }
  output tag typeOf simplon.pipeline.Port {
    accepts = simplon.vocabulary.tag
  }
}
```

`catalogue.yaml`, protected region, before `release:tag`:

```yaml
  # The release NOTES (si#344 C.3, spec decision 16), generated from the merges since the previous tag and
  # the tickets they name - the walk `test:release-notes` already makes to check a hand-written page, not a
  # second one. OFFERED, not placed, for `release:tag`'s reason: it is one leaf of a release, and a product
  # that releases by hand-written notes alone has nothing waiting for it.
  release:notes:
    impl: simplon.tasks.releasenotes:write
    help: "Write the release notes for a tag from the merges and tickets since the previous one."
    unattended: true
    params:
      name: { help: "the release-notes artifact to write (normally bound with `produces:`)" }
      tag:  { help: "the tag being released, exactly as it will exist (e.g. v1.4.0)", metavar: "TAG" }
```

`./simplon.sh build model`; read the diffs.

- [ ] **Step 4: Implement `render` and `write`**

In `releasenotes.py`, extend the module docstring's first line to `"""`test:release-notes` and `release:notes` - a product's releases page against the tags and merges its repository carries, and the notes generated from the same walk.` and add a paragraph:

```
GENERATING IS THE SAME WALK (si#344 C.3, decision 16). `release:notes` writes, for the tag being cut, one
line per merge since the previous `vX.Y.Z` tag with the tickets it names, through `merges_in` and
`tickets_of` - the functions the guard reads with. It does not grow a second walk, and the hand-written
page stays: generated notes name every ticket in their range by construction, which is what the guard
enforces on prose, but they do not say what a change MEANT.
```

Add, after `_assess`:

```python
def render(root: Path, tag: str) -> str:
    """The notes for `tag`: one bullet per merge since the previous `vX.Y.Z` tag, newest first. Pure over git."""
    released = released_versions(root)
    previous = tag_of(released[-1]) if released else ""
    if previous:
        merges = merges_in(root, previous, "HEAD")
    else:
        out = _git(root, "log", "--merges", "--format=%H\t%s", "HEAD")
        merges = [(sha, subject.strip()) for sha, _, subject in (line.partition("\t") for line in out.splitlines())
                  if subject.strip() and not is_githubs_own_merge(subject.strip())]
    lines = [f"## {tag}", ""]
    if not merges:
        lines.append(f"No merge since {previous}." if previous else "No merge in this repository yet.")
    for sha, subject in merges:
        tickets = sorted(tickets_of(root, sha, subject))
        lines.append(f"- {subject}" + (f" ({', '.join(f'#{n}' for n in tickets)})" if tickets else ""))
    return "\n".join(lines) + "\n"


def write(name: str = "", tag: str = "") -> int:
    """`release:notes`: write `render(root, tag)` to the `release-notes` artifact `name`'s `path:`."""
    if not tag.strip():
        raise ValueError("which release? pass the tag being cut, exactly as it will exist (e.g. v1.4.0)")
    ctx = context.current()
    section = ctx.manifest_data().get(artifactsection.SECTION) or {}
    if name not in section:
        raise ValueError(f"no artifact '{name}' in {ctx.manifest_path.name}'s `artifacts:` section; declared "
                         f"are: {', '.join(sorted(section)) or '(none)'}")
    entry = artifactsection.entry(section, name, artifactschema.Release_notesEntry, ctx.manifest_path.name,
                                  "release:notes")
    target = ctx.root / str(entry.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(ctx.root, tag.strip()), encoding="utf-8")
    log.ok(f"wrote the notes for {tag.strip()} to {entry.path}")
    return 0
```

Add the imports this needs (`artifactsection`, `artifactschema` from `simplon.domain`; `context` and `log` are imported already — check). The test for "no merge" expects lowercase `no merge since v0.1.0`; make the sentence `f"no merge since {previous}."` to match, or fix the test to the real text — one source.

`releasenotes.py` is already a manifest reader; its new raises need `CENSUS` entries (the census test names them): both `DIAGNOSIS`.

- [ ] **Step 5: Pass, see red, full suite, commit**

Remove the `tickets_of` call (bullets without numbers) → the first test fails; make `render` start from the first commit always → the "since previous tag" assertion that excludes older merges fails (add `assert "start" not in text` to the first test to make this visible). Restore. Full suite to `t6.log`; gates. Commit: `feat(si#344): release:notes writes the notes from the walk the guard reads with; release:tag consumes them`.

---

### Task 7: The release aggregate names one bundle (rule 8), and simplon releases through it

**Files:**
- Modify: `src/simplon/domain/treeform.py` (`_resolve_one`, lines 597-607)
- Modify: `src/simplon/domain/ports.py` (`check`: aggregates in the producer loop; new `_check_bundles`)
- Modify: `simplon.yaml` (`ci: release:`, `artifacts:`)
- Modify: `src/tests/test_refusal_census.py`, `src/site/content/with-what/rules.md`
- Test: `src/tests/test_release_bundle.py` (new)

**Interfaces:**
- Consumes: `_top`, `OWN_KINDS` (Task 4), `release:notes`/`release:tag` ports (Task 6).
- Produces: an aggregate's `CommandSpec.produces == {"release": ("<artifact>",)}`; `ports._check_bundles(manifest, declared, kinds) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_release_bundle.py`:

```python
"""si#344 C.3: a release is one aggregate that names one `kind: release` bundle (spec C.4, C.5 rule 8).

AAA; the name states the behaviour under test.
"""
from pathlib import Path

import pytest

from simplon.domain import catalogue, manifest

ROOT = Path(__file__).resolve().parents[2]

HEAD = """
product: demo
artifacts:
  app: { kind: image, registry: ghcr.io/o, repository: app, dockerfile: Dockerfile, context: . }
  app-checked: { kind: test-result, path: build/test/app.json }
  app-notes: { kind: release-notes, path: build/release/notes.md }
  app-tag: { kind: tag }
  app-release: { kind: release }
ci:
  build:
    commands:
      image: { task: "build:image", produces: { image: app } }
  test:
    commands:
      image: { task: "test:image", consumes: { image: app }, produces: { test-result: app-checked } }
  release:
    commands:
      notes: { task: "release:notes", produces: { release-notes: app-notes } }
      push:  { task: "release:image", consumes: { image: app, evidence: [app-checked] } }
      tag:   { task: "release:tag", consumes: { release-notes: app-notes }, produces: { tag: app-tag } }
"""
# The publish leaf is `push`, not `image`: `depends_on` names a leaf by a bare name one group owns (#519),
# and `image` is also `build image` and `test image` here.


def _load(text):
    return manifest.load(text, catalogue=catalogue.load())


def test_a_release_aggregate_names_its_bundle():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, push, tag], produces: { release: app-release } }\n"

    # act
    loaded = _load(text)

    # assert
    assert loaded.spec_for("release", "all").produces == {"release": ("app-release",)}


def test_an_aggregate_outside_ci_release_naming_an_output_is_refused():
    # arrange
    text = HEAD.replace("  test:\n    commands:\n",
                        "  test:\n    commands:\n      all: { depends_on: [push], produces: { release: app-release } }\n")

    # act / assert
    with pytest.raises(ValueError, match="only an aggregate under `ci: release:` does"):
        _load(text)


def test_a_release_aggregate_naming_two_outputs_is_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, push, tag], produces: { release: app-release, tag: app-tag } }\n"

    # act / assert
    with pytest.raises(ValueError, match="a release aggregate names exactly one output"):
        _load(text)


def test_a_bundle_that_is_not_a_release_is_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, push, tag], produces: { release: app-tag } }\n"

    # act / assert
    with pytest.raises(ValueError, match="the bundle is a `kind: release`"):
        _load(text)


def test_a_tag_planned_before_a_publish_is_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, tag, push], produces: { release: app-release } }\n"

    # act / assert
    with pytest.raises(ValueError, match="plans 'tag' before 'push'"):
        _load(text)


def test_an_aggregate_consuming_is_still_refused():
    # arrange
    text = HEAD + "      all: { depends_on: [notes, push, tag], consumes: { image: app } }\n"

    # act / assert
    with pytest.raises(ValueError, match="an aggregate runs no task"):
        _load(text)


def test_the_kernels_own_release_aggregate_loads():
    # act
    loaded = _load((ROOT / "simplon.yaml").read_text(encoding="utf-8"))

    # assert
    spec = loaded.spec_for("release", "all")
    assert spec.produces == {"release": ("kernel-release",)}
    assert loaded.plan_for("all", group="release")[-1] == "tag"
```

(Use the `_load` shape `test_port_bindings.py` uses if `manifest.load` takes other arguments; the kernel's own manifest may need to be loaded the way `test_manifest.py` loads `simplon.yaml` — copy that.)

- [ ] **Step 2: Run them to verify they fail**

Run: `PY -m pytest src/tests/test_release_bundle.py -q -p no:cacheprovider`
Expected: FAIL — `an aggregate runs no task` on the first test.

- [ ] **Step 3: `_resolve_one` lets an aggregate carry `produces:`**

Replace lines 597-607 of `treeform.py` (the `if ref is None:` block) with:

```python
    if ref is None:
        if "consumes" in spec:
            raise ValueError(
                f"command '{where}' declares `consumes:`, and an aggregate runs no task, so it has no port to "
                f"bind - bind the port on the command that runs the task")
        produced = spec.get("produces")
        if produced is not None:
            # si#344 C.3: the one output an aggregate names is its release bundle; which aggregates may name
            # one, and what kind it is, is rule 8 (ports._check_bundles), decided over the loaded manifest.
            if not isinstance(produced, dict) or not produced \
                    or not all(isinstance(v, str) and v.strip() for v in produced.values()):
                raise ValueError(
                    f"command '{where}' declares `produces:` as {produced!r}: an aggregate's one output is "
                    f"written `produces: {{ release: <artifact> }}`")
            spec["produces"] = {str(k): (v.strip(),) for k, v in produced.items()}
        if not spec.get("depends_on"):
            raise ValueError(
                f"command '{where}' declares neither `task:` nor `depends_on:`. A command either "
                f"instantiates a task or is an aggregate that plans other commands")
        return spec
```

Census: the existing key `("treeform", "_resolve_one", "an aggregate runs no task")` still names exactly one refusal; add `("treeform", "_resolve_one", "an aggregate's one output is"): DIAGNOSIS,`.

- [ ] **Step 4: Rule 8 in `ports.py`**

In `check`'s first loop, skip the port loop for an aggregate and record its bundle as produced:

```python
        for name, spec in members.items():
            where = f"{group} {name}"
            if not spec.task:
                for artifact in (a for names in spec.produces.values() for a in names):
                    producers.setdefault(artifact, []).append(where)
                continue
```

(`check` raises "declares no" for a bound artifact `artifacts:` lacks; `_check_bundles` does that for the bundle.)

Add:

```python
def _check_bundles(manifest: "Manifest", declared: Mapping[str, "artifactsection.Declared"],
                   kinds: Mapping[str, str]) -> None:
    """Rule 8 (spec C.4, C.5): only an aggregate under `ci: release:` names an output, exactly one, of kind
    `release`; and its plan cuts no `release:tag` before a publish member. A publish member is one whose
    task takes evidence - an input port accepting `test-result` - so the set is derived, not listed."""
    for group, members in manifest.commands.items():
        for name, spec in members.items():
            if spec.task or not spec.produces:
                continue
            where = f"{group} {name}"
            if (manifest.area_of(group), _top(group)) != ("ci", "release"):
                raise ValueError(
                    f"aggregate '{where}' names an output, and only an aggregate under `ci: release:` does - "
                    f"its one output is the release bundle")
            if list(spec.produces) != ["release"] or len(spec.produces["release"]) != 1:
                raise ValueError(
                    f"aggregate '{where}' names {', '.join(spec.produces)}: a release aggregate names exactly "
                    f"one output, `produces: {{ release: <artifact> }}`")
            bundle = spec.produces["release"][0]
            if bundle not in declared:
                raise ValueError(
                    f"aggregate '{where}' names the bundle '{bundle}', and `artifacts:` declares no "
                    f"'{bundle}' - declare it with `kind: release`")
            if not artifactsection.accepts(kinds, "release", declared[bundle].kind):
                raise ValueError(
                    f"aggregate '{where}' names '{bundle}', a `{declared[bundle].kind}`, as its release - the "
                    f"bundle is a `kind: release`")
            plan = manifest.plan_for(name, group=group)
            specs = [manifest.spec_by_name(step) for step in plan]
            publishes = [at for at, s in enumerate(specs)
                         if s and any(p.direction == "input" and p.accepts == "test-result" for p in s.ports)]
            for at, (step, s) in enumerate(zip(plan, specs)):
                if s and s.task == "release:tag" and publishes and at < max(publishes):
                    raise ValueError(
                        f"aggregate '{where}' plans '{step}' before '{plan[max(publishes)]}' - a tag cut before "
                        f"the push it announces is a public statement that is false if the push fails; list "
                        f"the tag after every publish in `depends_on`")
```

Call it in `check` before `_check_results`: `_check_bundles(manifest, declared, kinds)`.

Census `CENSUS`:

```python
    ("ports", "_check_bundles", "only an aggregate under `ci: release:` does"): EXPRESSION,
    ("ports", "_check_bundles", "a release aggregate names exactly"): EXPRESSION,
    ("ports", "_check_bundles", "declare it with `kind: release`"): DIAGNOSIS,
    ("ports", "_check_bundles", "the bundle is a `kind: release`"): DIAGNOSIS,
    ("ports", "_check_bundles", "a tag cut before"): DIAGNOSIS,
```

and the two expression rules in `REACH` as `REACH_MERGED`; let the measurement correct them.

- [ ] **Step 5: simplon releases through one aggregate**

In `simplon.yaml`, `ci: release: commands:`, add before `tag:`:

```yaml
      # The release as one act (si#344 C.3, spec C.4): the notes, the image and the tag are three leaves
      # because each fails differently, and `all` plans them in the one order that keeps a failed push
      # from leaving a public tag behind. Its bundle is derived from what the leaves produce and consume.
      notes: { task: "release:notes", produces: { release-notes: kernel-notes } }
```

change `tag: { task: "release:tag" }` to:

```yaml
      tag: { task: "release:tag", consumes: { release-notes: kernel-notes }, produces: { tag: kernel-tag } }
```

and after `push-image:` add:

```yaml
      all:
        depends_on: [notes, push-image, tag]
        produces: { release: kernel-release }
        help: "Write the notes, publish the tested image, then cut the tag."
```

`depends_on` entries are bare names that exactly one group must own (#519). `notes`, `push-image` and `tag` are, in simplon.yaml after Task 4 — check with `grep -nE '^\s+(notes|push-image|tag):' simplon.yaml` (one hit each, plus the `artifacts:` keys, which are not commands). `all` is also a command in `ci: test:`; an aggregate's own name may be shared, because it is invoked as `release all`.

Under `artifacts:`:

```yaml
  # The release's own artifacts (si#344 C.3): the notes `release notes` writes, the tag `release tag` cuts
  # (no path - its value is the tag name) and the bundle `release all` names, whose content is derived.
  kernel-notes:
    kind: release-notes
    path: build/release/notes.md
  kernel-tag:
    kind: tag
  kernel-release:
    kind: release
```

The `release.yml` workflow is not changed here: it reacts to a tag a person cut with `release tag`, and `release all` is what a person runs now. Its `image` job keeps building, testing and publishing per tag (Task 4).

- [ ] **Step 6: Pass, see red, full suite, commit**

Run: `PY -m pytest src/tests/test_release_bundle.py src/tests/test_release_rule.py src/tests/test_port_bindings.py src/tests/test_refusal_census.py -q -p no:cacheprovider` → PASS. Break: drop the area check → the outside-release test fails; drop the tag-order raise → the order test fails. Restore. Full suite to `t7.log`; `./simplon.sh release --help` lists `notes`, `all`; gates; `rules.md` numbers. Commit: `feat(si#344): a release aggregate names one bundle, and its tag comes after every publish (rule 8)`.

---

### Task 8: The model exports test results and the release bundle, and `about` answers again

**Files:**
- Modify: `src/firn/model/simplon/pipeline/pipeline.firn` (`TestResult.about` selector)
- Modify: `src/simplon/domain/manifestmodel.py` (`_Export.artifacts`, `_Export.command`)
- Modify: `src/tests/fixtures/firn/pipeline_demo/model/demo/demo.firn`
- Regenerate: `src/firn/model/product/simplon/simplon.firn`
- Test: `src/tests/test_manifestmodel.py`, `src/tests/test_firn_pipeline_e2e.py`

**Interfaces:**
- Produces: a `test-result` entry is exported as `simplon.pipeline.TestResult`; an aggregate with `produces: { release: X }` is exported as `simplon.pipeline.ReleaseCommand` holding `release <X> typeOf simplon.pipeline.Release`, and X is not exported a second time among the Product's artifacts.

- [ ] **Step 1: Measure a selector that works with `produces` as an Association**

In the demo fixture, move `checked` out of `demo.test.image` to the Product level the way `manifestmodel` exports artifacts (read `_Export.artifacts` for the exact shape) and make the command reference it: `produces = demo.<path to checked>`. Then run:

```bash
PY -m pytest src/tests/test_firn_pipeline_e2e.py -q -p no:cacheprovider
```

Expected: `TestResult.about` answers empty — the C.2 defect, seen red. Then try these selectors in `pipeline.firn`, one at a time, rerunning the test after each: (a) `TaskCommand[produces == self].consumes`; (b) `self.referrers(simplon.pipeline.TaskCommand.produces).consumes`; (c) any inverse-navigation form `docs/04-template-syntax.md` in firn documents (`gh api repos/marcozwyssig/firn/contents/docs/04-template-syntax.md --jq .content | tr -d '\n' | base64 -d | less`).

- If one answers `demo.build.image.kernel`: keep it, and say which in the commit.
- **If none does: this is a finding, not a stub.** Write it up as a firn issue (`gh issue create --repo marcozwyssig/firn --body-file ...`: "a SelectorRelation cannot navigate an Association backwards; simplon's `TestResult.about` needs 'the commands whose `produces` holds self'"), note it on si#344, keep the old selector, and mark the e2e row `pytest.mark.xfail(strict=True, reason="firn#<n>: ...")` so the day firn ships it the test goes red and asks for the selector. The kernel's rule 6 is Python and does not depend on the model.

- [ ] **Step 2: Write the failing export tests**

In `src/tests/test_manifestmodel.py`, using the export helper the file already has (`_export()` and `_block(...)`), add:

```python
def test_a_test_result_is_exported_as_a_test_result():
    # act
    block = _block(_export(), "artifacts a_kernel_checked typeOf simplon.pipeline.TestResult {")

    # assert
    assert 'path = "build/test/kernel-image.json"' in block


def test_the_release_aggregate_is_exported_with_its_bundle_inside():
    # act
    text = _export()
    block = _block(text, "command all typeOf simplon.pipeline.ReleaseCommand {")

    # assert
    assert "release a_kernel_release typeOf simplon.pipeline.Release {" in block
    assert "artifacts a_kernel_release typeOf" not in text
```

Read `_export`/`_block` first: if the export's artifact heads are spelled differently (the prefix `a_` and the role name `artifacts` are what `command()` references as `{self.root}.a_<name>`), use the real spelling.

- [ ] **Step 3: Implement the export**

In `_Export.artifacts`, choose the class by kind: `simplon.pipeline.TestResult` when the kind refines `test-result`, skip an entry whose kind refines `release` (it is composed inside its aggregate), else `simplon.pipeline.Artifact` as now. In `_Export.command`, for an aggregate with `spec.produces.get("release")`, emit `ReleaseCommand` instead of `AggregateCommand` and append `_block(f"release a_{mangle(bundle)} typeOf simplon.pipeline.Release", [f"key = {_q(bundle)}", f"kind = simplon.vocabulary.release"])` to its body (copy the field lines `artifacts` emits for one entry, so a bundle carries what any artifact carries). References elsewhere to the bundle (none today: nothing consumes it in C.3) would need the composed path; say so in a comment.

Run `./simplon.sh build model`, read `src/firn/model/product/simplon/simplon.firn`'s diff, then `./simplon.sh test model`.

- [ ] **Step 4: Pass, see red, full suite, commit**

Run: `PY -m pytest src/tests/test_manifestmodel.py src/tests/test_manifestmodel_e2e.py src/tests/test_firn_pipeline_e2e.py -q -p no:cacheprovider` → PASS (or the strict xfail). Break: export the bundle among the artifacts too → the second test fails. Full suite to `t8.log`; gates. Commit: `feat(si#344): the model exports test results and the release bundle` (plus the firn finding, if any).

---

### Task 9: The pages say how a release is built, and the branch goes up

**Files:**
- Modify: `src/site/content/how/manifest.md` (the `produces:`/`consumes:` section C.2 wrote), `src/site/content/how/task-and-command.md`, `src/firn/templates/docs.firnt` (the kinds page: which ports take `evidence`)
- Test: `src/tests/test_catalogue_ports.py` (`test_the_kinds_page_says_how_a_command_binds_a_port` neighbour)

- [ ] **Step 1: Write the failing page test**

Append to `test_catalogue_ports.py`:

```python
def test_the_kinds_page_says_a_release_consumes_the_test_results():
    # arrange
    text = (ROOT / "src" / "site" / "content" / "with-what" / "kinds.md").read_text(encoding="utf-8")

    # assert
    assert "`evidence`" in text
    assert "every test result about" in text
```

(`ROOT` as the file's other page test uses it.) Run → FAIL.

- [ ] **Step 2: Write the passages**

- `docs.firnt` (kinds page, below the port table): "**A release consumes the results of the tests on what it publishes.** Every publish leaf has an `evidence` input port accepting `test-result`. A command under `ci: release:` that consumes an artifact must bind every test result about it there, and at least one must exist (rule 6). A test result is about what its producer consumes, directly: a unit test of the source is not a test of the image built from it. The notes, the tag, the bundle and the evidence itself need none." Regenerate with `./simplon.sh build model`.
- `how/manifest.md`, in the bindings section: a short example of the chain (build → test with `produces: { test-result: ... }` → release with `evidence:` → the `all` aggregate with `produces: { release: ... }`), taken from simplon.yaml, and one sentence each on rule 6 and rule 8, quoting their refusal fragments exactly as the code raises them.
- `how/task-and-command.md`: one paragraph: an aggregate runs no body and binds no port; the one output an aggregate may name is a release's bundle, under `ci: release:`.

- [ ] **Step 3: Pass, build docs, final verification**

Run: `PY -m pytest src/tests -q -p no:cacheprovider > /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/t9.log 2>&1; tail -15 /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/t9.log`, mypy, `./simplon.sh build docs`, `git add -A && ./simplon.sh test generated && ./simplon.sh test model`, `./simplon.sh test all`.
Expected: only the three root-bound `test_tasks_docs` failures.

Commit: `docs(si#344): the pages say a release consumes its test results and names one bundle`.

- [ ] **Step 4: Push and open the draft PR**

```bash
git push -u origin si344-c3-release-split
cat > /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c3-pr.md <<'EOF'
Part of #344 (C.3 of four plans). Plan: `docs/superpowers/plans/2026-10-14-si344-c3-test-results-and-the-release.md`.

- `release:nuget` / `release:maven` are split into `build:nuget-pack` / `build:maven-pack` (output port) and a push of exactly what was packed (input port) — decided in #344 (comment 6163686765).
- `test:image` writes a verdict record to a `test-result`; a producer that exits 0 without writing its result is rc 1.
- Every publish leaf has an `evidence` port; rule 6 refuses a release without every test result about what it publishes.
- `release:notes` generates the notes from the walk `test:release-notes` reads with; `release:tag` consumes them.
- A release aggregate names one `kind: release` bundle and cuts its tag after every publish (rule 8).
- simplon pays its own bill: `test image` on `kernel`, `release image` consumes the evidence, `release all` is the release.

**Draft until agile-cockpit has answered the cost question** (spec C.3). Rule 6 refuses firn's and agile-cockpit's live manifests at their next bump; the bill is pinned as `RELEASE_RULE_BILL`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UJTdTwXkTwG5ezBqD82YfG
EOF
gh pr create --draft --repo marcozwyssig/simplon --base main --head si344-c3-release-split --milestone "M3 - ci / cd / support" \
  --title "si#344 C.3: test results, evidence, the release rule and the release aggregate" --body-file /tmp/claude-0/-root-git-simplon/8829ce4c-eb41-4ec9-b3e2-d31d84cba0ad/scratchpad/c3-pr.md
```

Then request the final whole-branch review (superpowers:requesting-code-review).
