# si#525: Claude support, switched on by one manifest section, centrally managed

Decided by Marco on 2026-10-23, in this session and on si#525 (comments of that day, including the two
smcctl addenda he confirmed). Measured on main c29ed28.

## Intent

Every product developed with Claude Code needs the same plugins and the same working agreements, and today
each product copies them by hand. smcctl copied simplon's whole `claude:` section, because `declared()`
refuses an empty one. netctl, biz-cockpit and agile-cockpit each keep their own `CLAUDE.md` (27.8, 20.5 and
5.3 KB), and the other products have none. A copy drifts the day simplon's list or agreements change.

So: **one setting turns Claude support on, and simplon owns what it brings**. Marco, 2026-10-23: "claude
or gh is simply a toolchain that is supported, just like firn." So the setting is a toolchain entry. That is the plugin default
and the central part of `CLAUDE.md`, both versioned with the simplon pin. A product states only what is
its own.

## Decisions (Marco)

1. **The switch is a toolchain entry.** A new top-level manifest list, `toolchains:`, names every
   toolchain the product uses: `python`, `java`, `cpp`, `dotnet`, `firn`, `claude` and `gh`.
   `support toolchain <name>` adds its name there.
   - For firn and the four languages it also writes the commands, as today.
   - `claude` and `gh` are host tools, so they bring no `toolchain:run` commands. Each brings a gate in
     `support install` instead.

   `claude` in the list turns Claude support on: the plugin step and `CLAUDE.md`. Without it, Claude
   support is off, with no plugin step, no `CLAUDE.md` and no warning, because a product that does not
   use Claude Code pays nothing. `gh` in the list makes `support install` provision gh (si#526).
   *(This replaces the earlier ruling of the same day, under which the `claude:` section itself was the
   switch.)* The `claude:` section is optional and carries only `plugins:`, `marketplaces:`,
   `exclude:` and `requires:` additions.
2. **Simplon ships the default, and a product only extends it.** The effective set is computed as follows:
   - start from the default, which is the base set plus the set of each declared language;
   - add the product's `plugins:`;
   - remove the product's `exclude:`.

   A product's `marketplaces:` names only what its additions need. An empty effective set is the one
   remaining "installs nothing" refusal.
3. **The base set has eight plugins:** `superpowers`, `feature-dev`, `code-review`, `code-simplifier`,
   `security-guidance`, `github`, `frontend-design` (all `@claude-plugins-official`) and
   `token-optimizer@alexgreensh-token-optimizer`. That makes the third-party marketplace
   `alexgreensh/token-optimizer` part of the default.
4. **The per-language sets** are keyed by `support:toolchain`'s `language` values:

   | language | plugins | `requires` |
   |---|---|---|
   | `python` | `pyright-lsp` | `pyright-langserver` |
   | `java` | `jdtls-lsp` | `jdtls` |
   | `cpp` | `clangd-lsp` | `clangd` |
   | `dotnet` | `csharp-lsp` | `csharp-ls` |

   *Measured on 2026-10-23:* each `requires` value is the `lspServers.<name>.command` of that plugin in
   `anthropics/claude-plugins-official`'s `.claude-plugin/marketplace.json`. `kotlin-lsp` would need
   `kotlin-lsp`.

   `kotlin-lsp` is not in the `java` set. A product adds it through `plugins:`. *(My call: "if Kotlin
   modules exist" is something the kernel cannot see.)* The `requires` column becomes part of the default
   `claude.requires`, so si#396's wording "installed, and this machine cannot run all of them" names the
   toolchain's runtime. 
5. **The languages come from `toolchains:`.** Every language in that list adds its set (table above),
   and so the mapping lives only in the kernel. A product that did not use `support toolchain` writes the
   names by hand. An unknown name is a DIAGNOSIS that names the known ones. The known names are
   `profiles.PROFILES` plus the host toolchains `claude` and `gh`. *(My call: the host toolchains get a
   table of their own beside `PROFILES`, because `Profile` requires an image, and that table is where
   each one's `support install` gate is named.)*
6. **Where the install runs: in `support install` and in the launcher.**
   - The plugin step becomes one entry in `hosttools._GATES`, beside `oras` and si#526's `gh`.
   - The launcher (`templates/launch.sh.j2`, and with it `simplon.sh`) runs the same step after a deps
     refresh, on the `.deps-stamp` condition.
   - It does not run on every launch. Measured: `claude plugin list --json` takes 528-549 ms,
     `support claude-plugins -n` 1421 ms, and a bare `./simplon.sh --help` 382 ms.
   - `support claude-plugins` stays as the explicit command.
7. **`simplon init` turns it on by default.** A new product gets `toolchains: [claude, gh]`. Removing
   `claude` turns Claude support off, and removing `gh` turns the gh gate off.
8. **The kernel generates `CLAUDE.md`, with a protected region for the product's own part.**
   - The central part comes from a kernel template.
   - The product's part sits between markers and survives every regeneration.
   - On the first generation over an existing `CLAUDE.md`, the whole existing file moves into the
     product's region and the central part is written above it. The product removes duplicates afterwards.

## The outcome values (the recurring defect)

"Not run" and "failed" must not look alike, at any of the three entry points:

- **off:** `claude` is not in `toolchains:`. Silent in the launcher; `support install` says nothing for it either.
- **skipped, with the reason:** no `claude` on PATH; CI (`CI=true` or `GITHUB_ACTIONS=true`); the
  container route, where `claude` lives on the host. One line, never red.
- **nothing missing:** the effective set is installed.
- **installed N:** the line also says that **Claude Code must be restarted** before they are active
  (smcctl addendum). Otherwise "installed" reads as "ready".
- **failed:** names the plugin and the reason. `support install` is rc 1, as every gate is today. The
  launcher only warns and the command still runs, because a plugin must never block a build.

## The CLAUDE.md template

- **Where it lives:** `src/simplon/templates/CLAUDE.md.j2` *(my call)*. It is package data, so it ships in
  the wheel, and si#378's one-top-level-name rule holds.
- **What it contains:** what holds for every product, taken from simplon's own `CLAUDE.md`:
  - the four quality goals;
  - the three kinds of refusal, and that self-binding is reach, not a kind;
  - the questions before building an expression rule;
  - the recurring defect and its generalisation;
  - the working practices: measure, see it red, report findings, quoted error text is a second source,
    heredoc or `--body-file` for commit and issue text.

  It leaves out what is simplon's own: census history, si# anecdotes, kernel file names, simplon's
  counts. *Which paragraph is central is a line-by-line ruling; the plan lists each one and Marco reviews
  the template in the PR.*
- **What the template may say about the product:** its name and its launcher (`./<product>.sh`). It
  says nothing else about the product.
- **Markers:** `<!-- Begin product region: keep this text on regeneration -->` and
  `<!-- End product region -->`.
  - Markers that are missing, duplicated or out of order are a refusal by name, never a silent rewrite.
  - Text outside the region is the kernel's. Editing it is drift, and `test generated` reports it.
- **Which command writes it:** a new `support:claude-md` (with `--check`, like `support workflows`),
  placed by the catalogue for every product that has a `claude:` section. `support install` and the
  launcher do NOT write `CLAUDE.md`: a file in the tree changes only on a command a person ran.
- **Drift gate:** `CLAUDE.md` is listed under the product's `generated:`, so `test generated` goes red
  when the committed file differs from what the pinned kernel produces. A kernel bump therefore brings
  the new central text as a reviewable diff.
- **simplon places it on itself.** Simplon's `CLAUDE.md` becomes the central part plus simplon's region,
  which holds everything that is simplon's own.

## `.claude/settings.json`

The `enabledPlugins` half is still the native route, for a person who only opens the repository.
`support claude-md` also writes or checks `enabledPlugins` (and `extraKnownMarketplaces` for a non-built-in
marketplace) against the effective set. It never touches other keys in the file. *(My call: this keeps
both files on one command and one drift gate, instead of a per-product parity test that every product
writes again.)*

## Census and surface

- **`claudeplugins.declared`:** the refusal "section is missing or is not a mapping" splits:
  - missing means "the default only" and is no longer a refusal;
  - present but not a mapping stays a DIAGNOSIS.
- **`toolchains:`** is a new top-level key, read raw through `manifest_data()`, which is a walked seam. Its
  reader is the module that owns the host-toolchain table (*my call:* `tasks/profiles.py`).
- **New load-time refusals:** `toolchains:` that is not a list, an unknown or duplicate name, `exclude:` that is
  not a list, and an exclusion that names nothing in the default. The last one is a DIAGNOSIS, because an
  exclusion of nothing is a typo. Each needs its census entry in `test_refusal_census.py`.
- **`support:claude-md`:** a new coordinate, with its catalogue entry. It is placed for every product,
  and with no `claude` toolchain it says "off" and exits 0.
- **si#526 joins here:** the `gh` gate in `hosttools._GATES` runs only when `gh` is in `toolchains:`,
  which leaves the open question of si#526's per-platform install route as the only part of it this spec
  does not settle.

## Non-goals

- Plugin installation in CI or on the container route.
- Writing `CLAUDE.md` from `support install` or the launcher.
- Migrating netctl, biz-cockpit and agile-cockpit. Each product does that itself after the release, and
  is told what the first generation will do to its file.

## Anti-goals

- A product that has to restate simplon's plugin list.
- A regeneration that loses a product's text.
- "installed" when Claude Code is not yet running them, and "nothing to do" when the step was skipped.
- A launcher that fails a build over a plugin.

## Acceptance

- A product scaffolded with `simplon init` and then `support toolchain python`:
  - its `support install` installs the eight base plugins plus `pyright-lsp`;
  - it says a restart is needed;
  - a second run says nothing is missing.
- The same product with `claude` removed from `toolchains:`: no plugin line anywhere, and no `CLAUDE.md`.
- With no `claude` on PATH: "skipped: no `claude` on PATH", and rc 0 in the launcher.
- `support claude-md` over an existing `CLAUDE.md` moves it into the product region. Running it twice
  is byte-identical, and `--check` is red after an edit outside the region.
- smcctl can delete its copied `claude:` section entirely and write `toolchains: [python, claude, gh]`.
