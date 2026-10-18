# si#449: Homebrew first - simplon in its own public tap

Decided by Marco on 2026-10-18 in two rounds, both on si#449. The measurements behind them are in the si#449
comments of 2026-10-17 (survey) and 2026-10-18 (Homebrew mechanics), measured on main 33c8ce5.

## Intent

simplon publishes to PyPI, to ghcr and to Pages, but to no OS package manager. A product that ships a CLI
needs one, and the kernel offers none. Homebrew comes first. As with si#491, the kernel uses the new
coordinates on itself before a product takes them over. The result is `brew install marcozwyssig/tap/simplon`
on macOS and Linux, released from the same button as everything else, in the same order rule 8 states.

## Goals

The work splits into five parts. Each is one sub-ticket and one plan, in this order: A and B are independent
of each other, C needs A, D needs B and C, and E needs all of them.

### A. `release:github-draft` attaches assets

- The coordinate gains an input port for files: kind `file`, `needs: path`, zero or more. Each file is
  uploaded to the draft over PyGithub (`adapters.github`), and an asset that already exists with the same
  name is replaced, the way a re-run reuses the draft today.
- **Read back after upload:** the asset's name, size and `digest`. If GitHub reports no `digest` on a
  draft asset (unmeasured, see Open measurements), the kernel downloads the asset it just uploaded,
  hashes it, and compares the hash with the local file. A mismatch is a refusal.
- Its output is the asset list: a JSON file under the output directory, written by the body, with each
  asset's name, deterministic public URL (`https://github.com/<owner>/<repo>/releases/download/<tag>/<name>`)
  and the sha256 GitHub serves.
  - *(My call, from the builder check:)* it is a declared artifact of a new kind **`release-assets`
    refining `release`**. Rule 6's `OWN_KINDS` matches by refinement, the way `github-release` does, so it
    is something a release says about itself and needs no test result. There is no new rule and no
    change to `OWN_KINDS`.
  - The files port has `param: ""`, because a port with a param refuses a list and `name` is already the
    notes port's. The body reads the bound names from the context.
- `release:asset` is unchanged. *Its draft behaviour stays unmeasured, and it is not on this path.*
- Rule 6 (`OWN_KINDS`): the uploaded `file` needs a test result about it. For simplon's wheel that is the
  si#3 wheel-is-the-tag check, promoted to a result-producing leaf (see E).

### B. `token: app`

- `token:` takes a second value, `app`, beside `github`. The value is checked the way `token: github` is
  (`manifest/load.py:335-345`), and anything else stays a DIAGNOSIS.
- workflowgen derives a step before such a leaf:
  `actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1` (v3.2.0; v3.3.0 is under two
  weeks old). It reads two fixed secrets, `${{ secrets.<PREFIX>_APP_ID }}` and
  `${{ secrets.<PREFIX>_APP_KEY }}`, and is scoped by `owner` plus `repositories` to the one repository the
  leaf writes to. The leaf gets the token as `GH_APP_TOKEN` in its step env, never in a `run:` line.
- *(My call, from the builder check:)* the target is a generic parameter, `repository: <owner>/<repo>`,
  bound with `with:` on the leaf. B defines it, so D and a later Scoop bucket reuse it. The secret prefix
  is DERIVED from the repository's name, upper-cased with `-` as `_`: `homebrew-tap` gives
  `HOMEBREW_TAP_APP_ID`/`HOMEBREW_TAP_APP_KEY`. One App secret pair per target repository, and nothing
  else to declare.
- Diagnosis at render: a `token: app` leaf whose target repository is not declared. A missing secret
  cannot be seen at render, so the leaf's body refuses an empty `GH_APP_TOKEN` by name.
- A census entry for each new load-time refusal.

### C. A shared adapter: commit one file to another repository

- `adapters.repofile` *(my call on the name)* writes `<path>` with `<content>` to a branch of
  `<owner>/<repo>` over PyGithub's contents API, with a commit message, using a given token.
- Its outcomes are three values, never two, which is this project's recurring defect:
  - `written` names the new commit;
  - `already current` means the file is byte-identical, so nothing is committed;
  - `refused` carries the API's status and message.

  "Already current" must not read as a failed push, nor a failed push as current.
- Read back: after a write, the file at the new commit equals the content.
- This adapter is what a later Scoop bucket reuses. Nothing manager-specific lives in it.

### D. The formula: rendered, checked, committed

- **New kind `homebrew-formula`**, refining `file`.
- **`build:homebrew-formula`** consumes the asset list (A) and the product's template, and produces a
  `homebrew-formula` file under the output directory.
  - It takes exactly one asset, named by `with: asset: <name>` *(my call)*. A formula has one `url`.
  - **On a dry run there is no draft** (Marco, 2026-10-18): `release:github-draft` is a publish leaf and is
    skipped. So the step falls back to the deterministic URL and the sha256 of the local file bound to the
    draft's files port. The asset list is the only source on a real run, and its absence there is a
    refusal, never a fallback.
  - The template is a product file named in the manifest. The kernel replaces only `{{version}}`,
    `{{url}}` and `{{sha256}}`, and refuses a template that lacks any of the three, or holds a placeholder
    it does not know.
  - The kernel writes nothing else into a formula, and every Homebrew decision stays in the product's
    template.
- **`test:homebrew-formula`** consumes it and produces a `test-result` about it, which is rule 6's evidence
  for the tap commit.
  - It runs `brew audit --strict --online` and `brew style` on the formula in a throwaway local tap, inside
    `ghcr.io/homebrew/brew:7.0.9@sha256:00b643d72ab0ee27c64e3e552d08c66e1bb5272bdf4ed28964e27aa5764f2503`,
    with the network.
  - Measured: 16 s and 2 s, and red on a `desc` that starts with an article.
  - Because audit does not catch a wrong sha256 (measured), the step also checks that the formula's
    `sha256` equals the digest A read back. On a dry run it checks it against the local wheel instead.
    The comparison with what GitHub serves happens only on a real run, before the tap commit, and the
    dry-run tail says so.
  - It runs on a dry run too: it publishes nothing.
  - The image must be pinned by digest, like every image (`docker.pinned_image`).
- **`release:homebrew-tap`** consumes the formula and commits it as `Formula/<name>.rb` to the tap
  through C, with `publishes: true` and `token: app`.
  - The dry run skips it via the `if:` (si#463 D2).
  - Its outcome reports C's three values.
- **Rule 8 stands:** the tap commit is a publish member and runs BEFORE `release:github-publish`.
  - The formula's URL is the deterministic public download URL.
  - Stated cost: between the tap commit and the publish, a `brew install` fails on a URL that is not
    public yet. The window is the length of one step.
  - If `release:github-publish` then fails, the tap points at an unpublished release until the job is
    rerun. "Rerun the failed job, never a second tag" (memory) covers it.

### E. simplon places it on itself

- **Python 3.14 in CI** (Marco, 2026-10-18): the formula runs simplon on `python@3.14`, because Homebrew's
  `cryptography` and `pydantic` exist only for 3.14/3.15. Measured: 0.34.0 runs on 3.14.8. So a second
  `ci.yml` job on `ubuntu-latest` with `python: "3.14"` runs the suite. The existing job on ghr-8 keeps the
  machine's python3, whose version is not pinned today.
- **One wheel** (Marco, 2026-10-18): the release job builds it once. The `publish` job takes it through
  `upload-artifact`/`download-artifact` instead of rebuilding, so PyPI, the Release and the tap carry the
  same bytes. A derived release job handing a file to a product job is new for workflowgen, and part of E.
  The si#3 wheel-is-the-tag check becomes a `ci: test:` leaf that produces the `test-result` rule 6 asks
  for about the wheel.
- **`release all` gains:** `release:github-draft` with the wheel as an asset (the wheel built and checked in
  the release job, which today happens in the `publish` product job), `build:homebrew-formula`,
  `test:homebrew-formula`, `release:homebrew-tap`, and then `release:github-publish`. The order is checked
  against rule 8 and stated in `release all`'s help.
- **The template** lives at `deploy/homebrew/simplon.rb.tmpl` *(my call)*, in the measured shape that passes
  `brew audit --strict --online --new`:
  - `url "{{url}}", using: :nounzip`, `sha256 "{{sha256}}"`, `version "{{version}}"`;
  - `depends_on "python@3.14"`, `"cryptography"`, `"pydantic"`, `"libyaml"`, `"libsodium"`;
  - 22 `resource` blocks for the rest of the closure;
  - the install does `virtualenv_create(libexec, "python3.14")`, then `venv.pip_install resources`, then
    `venv.pip_install_and_link buildpath/"simplon-#{version}-py3-none-any.whl"`, with
    `SODIUM_INSTALL=system`;
  - a `test do` that runs `simplon --help` and expects `usage:` (lowercase, measured; `--version` exits 2).
- **Resource blocks are product data**, committed in the template. A test in simplon checks them against the
  wheel's `requires_dist` closure minus what the two formulae carry. It is red when a dependency is added
  and the template is not updated. It is not regenerated by the kernel at release time.
- **The tap repository:** `marcozwyssig/homebrew-tap`, with `Formula/simplon.rb`.
- The README and `how/releasing.md` name `brew install marcozwyssig/tap/simplon`.

## Non-goals

- homebrew-core, casks, Chocolatey, Scoop, winget, apt and yum. C is built so that Scoop can reuse it
  later.
- `brew install`/`brew test` in the release. It was measured at about 4.5 minutes with a transient ghcr TLS
  failure, and it was decided against. The formula's `test do` is still written, so a person or a later
  ticket can run it.
- Changing `release:asset`.
- Generating resource blocks at release time.

## Anti-goals

- A tap commit on a dry run.
- A formula whose sha256 was not checked against what GitHub serves.
- `${{ secrets.* }}` or a token inside a `run:` line.
- An outcome where "already current" and "failed" look alike.

## Before building (Marco, outside this repository)

- Create `marcozwyssig/homebrew-tap` (public).
- Create the GitHub App:
  - contents read/write on that repository only;
  - install it there;
  - store its id and private key as the repository secrets `HOMEBREW_TAP_APP_ID` and `HOMEBREW_TAP_APP_KEY` in
    simplon *(my call on the names; the prefix is `HOMEBREW_TAP`)*.

## Open measurements (before or during A)

- **Does a draft release's asset carry `digest`?** It needs one throwaway draft release with one small asset
  on a repository Marco names, deleted afterwards. Until measured, A implements the fallback
  (download and hash), and the primary path is kept only if the measurement says so.
- **How a draft asset is downloaded with a token.** The API's asset endpoint with
  `Accept: application/octet-stream` is the expected route; it is unmeasured.
- *(Answered by the builder check: a product task with no `task:` may declare `produces:` (`ports.py`), so
  `wheel` produces a `file` artifact. An `artifacts:` entry with only a `path:` would be refused, because no
  command produces it.)*
- Each release now pays the measured 4.5-minute pull of the 3.2 GB Homebrew image. Accepted; stated in the
  release docs.

## Acceptance

- A `v0.N.0` dry run from `main`:
  - renders the formula, and audit and style are green;
  - the sha256 check passes;
  - nothing is committed to the tap;
  - no release is published.
- The next real cut leaves `Formula/simplon.rb` at the new version in the tap. On a clean macOS or Linux
  machine, `brew install marcozwyssig/tap/simplon` installs that version (checked by hand once, and stated
  in the PR).
