# si#525: Claude support, switched on by one manifest section, centrally managed

Decided by Marco on 2026-10-23, in this session and on si#525 (comments of that day, including the two
smcctl addenda he confirmed). Measured on main c29ed28.

## Intent

Every product developed with Claude Code needs the same plugins and the same working agreements, and today
each product copies them by hand. smcctl copied simplon's whole `claude:` section, because `declared()`
refuses an empty one. netctl, biz-cockpit and agile-cockpit each keep their own `CLAUDE.md` (27.8, 20.5 and
5.3 KB), and the other products have none. A copy drifts the day simplon's list or agreements change.

So: **one setting turns Claude support on, and simplon owns what it brings**. That is the plugin default
and the central part of `CLAUDE.md`, both versioned with the simplon pin. A product states only what is
its own.

## Decisions (Marco)

1. **The switch is the `claude:` section.** If it is present, even empty, Claude support is on. If it is
   absent, Claude support is off: no plugin step and no `CLAUDE.md`, and no warning either, because a
   product that does not use Claude Code pays nothing.
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
   | `python` | `pyright-lsp` | `pyright` |
   | `java` | `jdtls-lsp` | a JDK (`java`) |
   | `cpp` | `clangd-lsp` | `clangd` |
   | `dotnet` | `csharp-lsp` | `dotnet` |

   `kotlin-lsp` is not in the `java` set. A product adds it through `plugins:`. *(My call: "if Kotlin
   modules exist" is something the kernel cannot see.)* The `requires` column becomes part of the default
   `claude.requires`, so si#396's wording "installed, and this machine cannot run all of them" names the
   toolchain's runtime. *The exact executable names are to be measured against each plugin's manifest
   before they are written into the table.*
5. **The languages come from `claude: languages:`.** `support toolchain <language>` adds its language
   there, beside the toolchain configuration it already writes, and creates the section if it is absent.
   A product that did not use `support toolchain` writes the line by hand. An unknown language is a
   DIAGNOSIS that names the known ones, from `profiles.PROFILES`.
6. **Where the install runs: in `support install` and in the launcher.**
   - The plugin step becomes one entry in `hosttools._GATES`, beside `oras` and si#526's `gh`.
   - The launcher (`templates/launch.sh.j2`, and with it `simplon.sh`) runs the same step after a deps
     refresh, on the `.deps-stamp` condition.
   - It does not run on every launch. Measured: `claude plugin list --json` takes 528-549 ms,
     `support claude-plugins -n` 1421 ms, and a bare `./simplon.sh --help` 382 ms.
   - `support claude-plugins` stays as the explicit command.
7. **`simplon init` turns it on by default.** A new product gets an empty `claude:` section, plus
   `languages:` once `support toolchain` has run. Deleting the section turns it off.
8. **The kernel generates `CLAUDE.md`, with a protected region for the product's own part.**
   - The central part comes from a kernel template.
   - The product's part sits between markers and survives every regeneration.
   - On the first generation over an existing `CLAUDE.md`, the whole existing file moves into the
     product's region and the central part is written above it. The product removes duplicates afterwards.

## The outcome values (the recurring defect)

"Not run" and "failed" must not look alike, at any of the three entry points:

- **off:** no `claude:` section. Silent in the launcher; `support install` says nothing for it either.
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
  - missing becomes "off" and is no longer a refusal;
  - present but not a mapping stays a DIAGNOSIS.
- **New load-time refusals:** `languages:` that is not a list, an unknown language, `exclude:` that is
  not a list, and an exclusion that names nothing in the default. The last one is a DIAGNOSIS, because an
  exclusion of nothing is a typo. Each needs its census entry in `test_refusal_census.py`.
- **`support:claude-md`:** a new coordinate, with its catalogue entry and placement.

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
- The same product with `claude:` deleted: no plugin line anywhere, and no `CLAUDE.md`.
- With no `claude` on PATH: "skipped: no `claude` on PATH", and rc 0 in the launcher.
- `support claude-md` over an existing `CLAUDE.md` moves it into the product region. Running it twice
  is byte-identical, and `--check` is red after an edit outside the region.
- smcctl can delete its copied `claude:` lists and keep an empty section.
