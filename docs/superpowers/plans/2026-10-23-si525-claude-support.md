# si#525 Claude Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `toolchains: [claude, …]` in a manifest turns Claude support on. Simplon owns the plugin default
(eight base plugins plus one LSP set per language) and the central `CLAUDE.md`. It installs the plugins
in `support install` and after a launcher deps refresh, and generates `CLAUDE.md` with a product region.

**Architecture:**
- **The toolchain list:** a new top-level `toolchains:` list, read raw through `manifest_data()`, owned by
  `tasks/profiles.py` together with a host-toolchain table beside `PROFILES`.
- **The plugin set:** `tasks/claudeplugins.py` computes the effective set as default + product additions −
  `exclude:`, and returns a five-valued outcome.
- **The install entry points:** `hosttools._GATES` gains a conditional `claude` gate, and the launcher
  templates call one module entry point.
- **The generated file:** a new `tasks/claudemd.py` renders `templates/CLAUDE.md.j2`, keeps a marked
  product region, and also writes `enabledPlugins` into `.claude/settings.json`.

**Tech Stack:** Python 3.12+, Typer, Jinja2 (the existing launcher templates), pytest, firn (`build model`
generates the task classes from the catalogue).

**Spec:** `docs/superpowers/specs/2026-10-23-si525-claude-support-design.md`

## Global Constraints

- **Known toolchain names:** `profiles.PROFILES` (`cpp`, `java`, `dotnet`, `python`, `firn`) plus the host
  toolchains `claude` and `gh`.
- **Base plugins, in this order:** `superpowers`, `feature-dev`, `code-review`, `code-simplifier`,
  `security-guidance`, `github`, `frontend-design` (all `@claude-plugins-official`), and
  `token-optimizer@alexgreensh-token-optimizer`.
- **Default marketplaces:**
  - `claude-plugins-official: { source: github, repo: anthropics/claude-plugins-official }`;
  - `alexgreensh-token-optimizer: { source: github, repo: alexgreensh/token-optimizer }`.
- **Language sets:** `python` → `pyright-lsp`, `java` → `jdtls-lsp`, `cpp` → `clangd-lsp`, `dotnet` →
  `csharp-lsp`, all `@claude-plugins-official`. `kotlin-lsp` is not in any default set.
- **Outcomes**, which are never collapsed: OFF, SKIPPED(reason), NOTHING_MISSING, INSTALLED(n) and FAILED.
  INSTALLED's line says Claude Code must be restarted.
- **Skip reasons:** no `claude` on PATH; `CI=true` or `GITHUB_ACTIONS=true`; the container route.
- **Exit codes:** the launcher never fails a command over a plugin. `support install` is rc 1 on FAILED
  only.
- **Markers:** `<!-- Begin product region: keep this text on regeneration -->` and
  `<!-- End product region -->`.
- **Where `CLAUDE.md` is written:** only `support claude-md` writes it, never `support install` or the
  launcher.
- **`simplon init`** writes `toolchains: [claude, gh]`.
- **Census:** every new load-time `ValueError` gets an entry in `src/tests/test_refusal_census.py`.
- **Commits:** through `-F` files, with the git identity in env.
- **Commands:** the suite runs with `./simplon.sh test suite`, and `git add` comes before
  `./simplon.sh --no-tui test generated`, because it compares against the index.

## Review Focus

1. A `toolchains:` entry with surrounding whitespace or a different case (`Claude`). Expect a DIAGNOSIS
   that names the known names, never a silent OFF. Test in Task 1.
2. A product that excludes a language plugin its own `toolchains:` brings (`exclude: [pyright-lsp@…]`
   with `python`). The exclusion must win, and its `requires` entry must go too. Test in Task 3.
3. `support claude-md` on a `CLAUDE.md` with CRLF line endings, or with a missing final newline. The
   region must survive byte for byte, and a second run must be identical. Test in Task 6.
4. `.claude/settings.json` holding keys of its own (`permissions`, `hooks`). They must stay untouched,
   with the key order kept. Test in Task 6.
5. The launcher on a host where `claude plugin list` hangs. The plugin step is bounded and reads as
   FAILED, and the command still runs. Test in Task 5.

---

### Task 0: Measure the LSP plugins' runtime binaries

**Files:**
- Modify: `docs/superpowers/specs/2026-10-23-si525-claude-support-design.md` (the `requires` column)

- [ ] **Step 1:** For each of `pyright-lsp`, `jdtls-lsp`, `clangd-lsp` and `csharp-lsp`, read its
  `.claude-plugin/plugin.json` (or `.lsp.json`) in `anthropics/claude-plugins-official` through
  `gh api repos/anthropics/claude-plugins-official/contents/...`, and note the `command` it launches.
- [ ] **Step 2:** Write the measured executable names into the spec table, with the file each one was
  read from. These names are the values of `LANGUAGE_REQUIRES` in Task 3.
- [ ] **Step 3:** Commit: `docs(si#525): the LSP plugins' binaries, measured`.

### Task 1: `toolchains:` and the host-toolchain table

**Files:**
- Modify: `src/simplon/tasks/profiles.py`
- Test: `src/tests/test_toolchains_section.py` (new), `src/tests/test_refusal_census.py`

**Interfaces:**
- Produces:
  - `profiles.HOST_TOOLCHAINS: dict[str, str]`, which maps a name to a one-line help:
    `{"claude": "Claude Code: plugins and CLAUDE.md", "gh": "the GitHub CLI"}`;
  - `profiles.TOOLCHAINS_KEY = "toolchains"`;
  - `profiles.known_toolchains() -> tuple[str, ...]`: the sorted keys of `PROFILES` and
    `HOST_TOOLCHAINS`;
  - `profiles.declared_toolchains(data: Mapping[str, object], source: str = "manifest") -> tuple[str, ...]`,
    which returns the names in manifest order.

- [ ] **Step 1: Write the failing tests:**
  - `test_absent_toolchains_is_empty`: `declared_toolchains({}) == ()`.
  - `test_toolchains_in_order`: `{"toolchains": ["python", "claude"]}` gives `("python", "claude")`.
  - `test_not_a_list_is_refused`: `{"toolchains": "claude"}` raises a `ValueError` matching
    `"'toolchains' must be a list of toolchain names"`.
  - `test_unknown_name_names_the_known_ones`: `["Claude"]` raises, and the message contains `'Claude'`
    and `claude, cpp, dotnet, firn, gh, java, python`.
  - `test_duplicate_is_refused`: `["gh", "gh"]` raises a message matching `"names 'gh' twice"`.
- [ ] **Step 2:** Run `pytest src/tests/test_toolchains_section.py`. Expect: FAIL with an
  `AttributeError` on `declared_toolchains`.
- [ ] **Step 3:** Implement it.
  - No stripping and no case folding: `"Claude"` and `" gh"` are unknown names. This is Review Focus 1.
  - Read the section through `context.section`'s raw data the way `claudeplugins.declared` does.
- [ ] **Step 4:** Run the tests. Expect PASS. Then run `pytest src/tests/test_refusal_census.py`. Expect
  FAIL on three unclassified refusals.
- [ ] **Step 5:** Add three `DIAGNOSIS` entries under a `# --- tasks/profiles.py: the toolchains: list`
  heading. If the census does not walk `profiles.py` yet, add it to the walked readers the way
  `claudeplugins` is. Run the census again. Expect PASS.
- [ ] **Step 6:** Commit: `feat(si#525): a toolchains: list, read and refused by name`.

### Task 2: `support toolchain <name>` writes the name

**Files:**
- Modify: `src/simplon/tasks/toolchain.py` (`scaffold`)
- Modify: `src/simplon/catalogue.yaml` (`support:toolchain`: `language` help becomes
  `java | cpp | dotnet | python | firn | claude | gh`; `version` gets `default: ""`)
- Generated: `src/simplon/tasks/support_toolchain.py`, via `./simplon.sh build model`
- Test: `src/tests/test_toolchain_scaffold.py`, or the file that tests `scaffold` today (find it with
  `grep -l "def test.*scaffold" src/tests`)

**Interfaces:**
- Consumes: `profiles.declared_toolchains`, `profiles.HOST_TOOLCHAINS`.
- Produces: `scaffold(language: str, version: str = "") -> int`.

- [ ] **Step 1: Write the failing tests:**
  - `test_host_toolchain_adds_only_the_list_entry`:
    - a manifest with no `toolchains:` and `scaffold("claude")` → the file gains `toolchains: [claude]`
      as a top-level line;
    - every other byte is unchanged;
    - the log says `claude: added to toolchains`.
  - `test_language_adds_commands_and_the_list_entry`: `scaffold("python", "3.12")` writes the commands
    as today, and `toolchains:` now contains `python`.
  - `test_second_run_changes_nothing`: running `scaffold("claude")` twice leaves the file byte-identical
    after the first run, and the log says `already in toolchains`.
  - `test_appends_to_an_existing_flow_list`: `toolchains: [python]` plus `scaffold("gh")` gives
    `toolchains: [python, gh]`.
  - `test_a_block_list_is_appended_in_block_style`: `toolchains:\n  - python\n` plus `scaffold("gh")`
    gives `  - gh` below it.
  - `test_image_toolchain_without_version_is_refused`: `scaffold("python")` dies with
    `python needs a version`.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement it.
  - A host toolchain returns after the list splice.
  - The splice is text-only, in the module's si#110 style. Add a helper
    `_toolchains_spliced(text: str, name: str, filename: str) -> str` that handles flow and block lists.
  - A shape it cannot read is refused by name and the file is not written.
- [ ] **Step 4:** Run `./simplon.sh --no-tui build model`, then the tests. Expect PASS. Then
  `git add -A` and `./simplon.sh --no-tui test generated`. Expect OK.
- [ ] **Step 5:** Commit: `feat(si#525): support toolchain writes its name into toolchains:, and claude and gh are toolchains`.

### Task 3: The plugin default and the effective set

**Files:**
- Modify: `src/simplon/tasks/claudeplugins.py`
- Test: `src/tests/test_claudeplugins.py` (the existing file), `src/tests/test_refusal_census.py`

**Interfaces:**
- Consumes: `profiles.declared_toolchains`.
- Produces:
  - `DEFAULT_MARKETPLACES: tuple[Marketplace, ...]`, `BASE_PLUGINS: tuple[str, ...]`,
    `LANGUAGE_PLUGINS: dict[str, tuple[str, ...]]` and `LANGUAGE_REQUIRES: dict[str, tuple[str, ...]]`,
    with the values from the Global Constraints and Task 0.
  - `@dataclass(frozen=True) class Effective: markets: tuple[Marketplace, ...]; plugins: tuple[str, ...];
    requires: tuple[str, ...]; origin: Mapping[str, str]`. The `origin` value is `"default"`,
    `"toolchain <lang>"` or `"product"`.
  - `effective(data: Mapping[str, object], source: str = "manifest") -> Effective | None`. It returns None
    when `claude` is not in `toolchains:`.
  - `declared()` stays, and validates only the product's additions: an absent or empty section is valid.

- [ ] **Step 1: Write the failing tests:**
  - `test_no_claude_toolchain_is_off`: `effective({"toolchains": ["python"]}) is None`.
  - `test_claude_alone_is_the_base_set`: `effective({"toolchains": ["claude"]}).plugins == BASE_PLUGINS`,
    and every `origin` is `"default"`.
  - `test_language_adds_its_set_and_requires`: `["claude", "python"]` adds
    `pyright-lsp@claude-plugins-official` with origin `"toolchain python"`, and its `requires` from
    Task 0.
  - `test_product_additions_and_their_marketplace`: a `claude:` section with `marketplaces: {acme: …}`
    and `plugins: [x@acme]` gives `x@acme` with origin `"product"`. A product plugin naming an undeclared
    marketplace is still refused with today's message.
  - `test_exclude_removes_and_takes_requires_with_it`: `["claude", "python"]` with
    `exclude: [pyright-lsp@claude-plugins-official]` gives no `pyright-lsp`, and the `requires` entry is
    gone. This is Review Focus 2.
  - `test_exclude_of_nothing_is_refused`: `exclude: [nope@claude-plugins-official]` raises a message
    matching `"excludes 'nope@claude-plugins-official', which is not in the default"`.
  - `test_exclude_not_a_list_is_refused`.
  - `test_excluding_everything_is_refused`: excluding all eight base plugins raises a message matching
    `"the effective plugin set is empty"`.
  - `test_empty_section_is_the_default`: `{"toolchains": ["claude"], "claude": {}}` gives the base set.
    This replaces the old empty-section refusal tests.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement it.
  - Order: base, then languages in `toolchains:` order, then product additions.
  - De-duplicate while keeping the first origin.
  - The `requires` of the effective set combine `LANGUAGE_REQUIRES` for the languages left in the set
    with the product's `claude.requires`.
- [ ] **Step 4:** Run the tests and then the census. Expect the census to FAIL on the new refusals and on
  the changed "missing or is not a mapping" text. The message becomes
  `the 'claude' section is not a mapping`.
- [ ] **Step 5:** Update the census entries: three new DIAGNOSIS entries and one changed text. Run it
  again. Expect PASS.
- [ ] **Step 6:** Commit: `feat(si#525): simplon owns the plugin default; a product adds or excludes`.

### Task 4: The five outcomes, `support install` and `support claude-plugins`

**Files:**
- Modify: `src/simplon/tasks/claudeplugins.py` (`install`, `_plugins`, `install_cmd`)
- Modify: `src/simplon/tasks/hosttools.py` (`_GATES`)
- Modify: `src/simplon/catalogue.yaml`: place `claude-plugins: { task: "support:claude-plugins" }` under
  the catalogue's `support:` beside `install`. It is now safe for every product, because OFF is a
  success. Update the comment at line 46-47.
- Modify: `simplon.yaml`: remove its own `claude-plugins` command, which is now placed by the catalogue
  (the same `dry_run` param moves into the catalogue entry).
- Test: `src/tests/test_claudeplugins.py`, `src/tests/test_hosttools.py` (create one if it does not exist)

**Interfaces:**
- Produces:
  - `class State(enum.Enum): OFF, SKIPPED, NOTHING_MISSING, INSTALLED, FAILED`;
  - `@dataclass(frozen=True) class Outcome: state: State; detail: str = ""; count: int = 0`;
  - `step(*, dry_run: bool = False, env: Mapping[str, str] | None = None, container: bool = False,
    timeout_s: float = 60.0) -> Outcome`, which never raises and never calls `log.die`;
  - `report(outcome: Outcome) -> None`, which logs one line per state;
  - `install(dry_run) -> int`, which becomes `report(step(...))` plus rc. The rc is 1 only for FAILED, and
    also for INSTALLED or NOTHING_MISSING when si#396 `requires` are missing, as today.

- [ ] **Step 1: Write the failing tests.** Use a fake `claude` executable on a tmp PATH, in the style of
  si#516's `test_clipboard.py`. It answers `plugin list --json` and `marketplace list --json` from files
  and records its argv.
  - `test_off_without_claude_toolchain`: State.OFF, and no process is started (the fake records nothing).
  - `test_skipped_without_claude_on_path`: the detail is exactly `no \`claude\` on PATH`.
  - `test_skipped_in_ci`: `CI=true` and `GITHUB_ACTIONS=true` each give SKIPPED with a detail naming the
    variable.
  - `test_skipped_on_the_container_route`: `container=True` gives SKIPPED with the detail
    `the container route: \`claude\` runs on the host`.
  - `test_nothing_missing`: the fake reports the whole set as installed.
  - `test_installed_counts_and_says_restart`: two missing plugins give INSTALLED with count 2, and the
    `report` line contains `restart Claude Code`.
  - `test_failed_names_the_plugin`: the fake exits 1 on `plugin install x` → FAILED, and the detail
    contains `x`.
  - `test_hung_claude_is_failed_not_hung`: the fake sleeps 30 on `plugin list`, and `timeout_s=1` gives
    FAILED within 5 s. This is Review Focus 5.
  - `test_dry_run_shows_origin`: the dry run's lines contain `(default)`, `(toolchain python)` and
    `(product)`.
  - `test_support_install_runs_the_claude_gate`: `hosttools.install()` with OFF prints no claude line.
    With FAILED it returns 1, and every gate is still attempted.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement it.
  - `_GATES` entries become `(name, gate: Callable[[], Outcome | None])`. The existing `oras` gate is
    wrapped so its behaviour and its lines are unchanged.
  - The claude gate is `claudeplugins.step` + `report`. OFF prints nothing in `support install`.
  - A subprocess timeout is a `TimeoutExpired`, caught and turned into FAILED.
- [ ] **Step 4:** Run `./simplon.sh --no-tui build model`, the tests and the census. Expect PASS.
- [ ] **Step 5:** Commit: `feat(si#525): the plugin step has five outcomes, and support install runs it`.

### Task 5: The launcher runs the step after a deps refresh

**Files:**
- Modify: `src/simplon/templates/launch.sh.j2`, the venv block at lines 403-408
- Modify: `src/simplon/tasks/claudeplugins.py`: add a `__main__` entry, `python -m simplon.tasks.claudeplugins launcher`
- Regenerate: `simplon.sh`, with whatever command re-renders it today (find it with
  `grep -n "launch.sh" src/tests/*.py`; the launcher-parity test names it)
- Test: the existing launcher tests (`grep -l "deps-stamp" src/tests`)

**Interfaces:**
- Consumes: `step`, `report`.
- Produces: the `launcher` mode, which calls `report(step(timeout_s=60))` and always exits 0.

- [ ] **Step 1: Write the failing tests:**
  - `test_launcher_runs_plugin_step_after_install`: the rendered template, inside the
    `if [ ! -f "$STAMP" ]` block and after `touch "$STAMP"`, contains
    `"$VENV/bin/python" -m simplon.tasks.claudeplugins launcher || true`.
  - `test_launcher_container_route_has_no_plugin_step`: the container block contains no
    `claudeplugins`.
  - `test_launcher_mode_exits_zero_on_failed`: run the module as a subprocess with the failing fake
    `claude` → rc 0 and a FAILED line on stderr.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement it. The plugin line runs from the product root so `context.current()` finds
  the manifest. Use `cd "$ROOT"` in a subshell.
- [ ] **Step 4:** Re-render `simplon.sh`, then run the tests and the launcher-parity test. Expect PASS.
- [ ] **Step 5:** Commit: `feat(si#525): the launcher installs the declared plugins when it refreshes its deps`.

### Task 6: `support claude-md`: the central CLAUDE.md and `enabledPlugins`

**Files:**
- Create: `src/simplon/templates/CLAUDE.md.j2`
- Create: `src/simplon/tasks/claudemd.py`
- Modify: `src/simplon/catalogue.yaml`: a `support:claude-md` coordinate with param
  `check: { help: "report drift and write nothing" }`, placed under the catalogue's `support:` as
  `claude-md`
- Generated: `src/simplon/tasks/support_claude_md.py`
- Modify: `src/simplon/cli/surface.py` and the `components.firn` `tasks` component; `with-what/surface.md`
  if the module is INTERNAL (it is, *my call*: the command is the interface)
- Test: `src/tests/test_claudemd.py` (new)

**Interfaces:**
- Consumes: `claudeplugins.effective`, `profiles.declared_toolchains`.
- Produces:
  - `BEGIN = "<!-- Begin product region: keep this text on regeneration -->"` and
    `END = "<!-- End product region -->"`;
  - `render(product: str, launcher: str, region: str) -> str`;
  - `region_of(text: str, source: str) -> str`: the text between the markers. A file with no markers
    returns the whole file (the first generation). Duplicated or out-of-order markers raise `ValueError`.
  - `settings(existing: Mapping[str, object], eff: Effective) -> dict[str, object]`;
  - `generate(check: bool = False) -> int`.

- [ ] **Step 1: Write the template.** Copy each central section of the repository's `CLAUDE.md`, as the
  spec lists them, into `CLAUDE.md.j2`.
  - Drop every si# number, every count, every kernel file name and the census history.
  - Write `{{ product }}` and `{{ launcher }}` where the text names the product or its launcher.
  - The region markers go at the end, with `{{ region }}` between them.
  - List in the commit message each paragraph of the old `CLAUDE.md` that was kept, generalised or
    dropped, so Marco can review that ruling.
- [ ] **Step 2: Write the failing tests:**
  - `test_off_without_claude_toolchain`: rc 0, the log says `off`, and no file is written.
  - `test_first_generation_moves_the_existing_file_into_the_region`: an existing `CLAUDE.md` with
    `# Mine\nkeep me\n` → the output starts with the central text and holds `# Mine\nkeep me\n` between
    the markers.
  - `test_regeneration_is_byte_identical`: a second `generate()` changes nothing, with CRLF input and
    with no final newline. This is Review Focus 3.
  - `test_check_is_red_after_an_edit_outside_the_region`: rc 1, and the message names `CLAUDE.md` and
    `support claude-md`.
  - `test_check_is_green_after_an_edit_inside_the_region`.
  - `test_broken_markers_are_refused`: END before BEGIN, and BEGIN twice, each raise a message naming the
    marker.
  - `test_settings_keeps_other_keys_and_order`: `{"permissions": {...}, "hooks": {...}}` is kept as it is,
    and `enabledPlugins` gets exactly the effective set as `{id: true}`. `extraKnownMarketplaces` gets the
    non-built-in marketplaces, and the order of the existing keys is kept. This is Review Focus 4.
  - `test_settings_drift_is_red_in_check`.
- [ ] **Step 3:** Run the tests. Expect FAIL.
- [ ] **Step 4:** Implement it.
  - Line endings: the region is read and written exactly as found. The central part uses `\n`.
  - JSON is written with `indent=2` and a final newline.
- [ ] **Step 5:** Run `./simplon.sh --no-tui build model`, the tests, the census (marker refusals run at
  command time, so expect no census entry; state that in the PR) and the surface and architecture tests.
  Expect PASS.
- [ ] **Step 6:** Commit: `feat(si#525): support claude-md writes the central CLAUDE.md and keeps the product's region`.

### Task 7: `simplon init` writes `toolchains: [claude, gh]`

**Files:**
- Modify: `src/simplon/cli/bootstrap.py` (`_MANIFEST`)
- Test: the existing scaffold tests (`grep -l "manifest_yaml" src/tests`)

- [ ] **Step 1: Write the failing tests:**
  - `test_starter_manifest_turns_claude_and_gh_on`:
    `declared_toolchains(yaml.safe_load(manifest_yaml("demo"))) == ("claude", "gh")`.
  - `test_starter_manifest_still_loads`: `manifest.load` accepts it.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Add a commented block with `toolchains: [claude, gh]` after `product:`. It says what each
  entry does and that `support toolchain <name>` adds more.
- [ ] **Step 4:** Run the tests. Expect PASS.
- [ ] **Step 5:** Commit: `feat(si#525): a new product starts with toolchains: [claude, gh]`.

### Task 8: simplon places it on itself, and the docs

**Files:**
- Modify: `simplon.yaml`:
  - add `toolchains: [python, firn, claude, gh]`;
  - delete the `claude:` section, because its list equals the new default (check with
    `support claude-plugins -n`: no `(product)` line);
  - add the `generated:` entries `claude-md` (path `CLAUDE.md`, by `support claude-md`) and
    `claude-settings` (path `.claude/settings.json`, by `support claude-md`).
- Modify: `CLAUDE.md`: generated. Simplon's own text, everything Task 6 dropped as simplon-specific, now
  sits in the product region.
- Modify: `.claude/settings.json`: generated.
- Docs:
  - `with-what/phases.md` § toolchain: the `toolchains:` list, `claude` and `gh`, and the five outcomes;
  - `how/manifest.md`: `toolchains:` and the `claude:` additions and `exclude:`;
  - `how/getting-started.md`: what `simplon init` turns on and how to turn it off;
  - `how/running.md`: the launcher's plugin line and the restart.

- [ ] **Step 1:** Make the manifest changes. Run `./simplon.sh --no-tui support claude-md`, then
  `./simplon.sh --no-tui support claude-plugins -n`. Expect `CLAUDE.md` regenerated and no `(product)`
  line.
- [ ] **Step 2:** Read `git diff CLAUDE.md`. No sentence of the old file may be lost: each one is either
  in the central part or in the region. State that in the PR.
- [ ] **Step 3:** Write the docs. Run `./simplon.sh build docs`. Expect OK.
- [ ] **Step 4:** Run `git add -A`, then `./simplon.sh --no-tui test generated` (expect OK) and
  `./simplon.sh test suite` (expect all green).
- [ ] **Step 5:** Commit: `feat(si#525): simplon declares its toolchains and generates its own CLAUDE.md`.
