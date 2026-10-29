# si#553: `release:github-attach` attaches tested files to the draft release

Ticket: si#553, part A of si#449 (spec `2026-10-18-si449-homebrew-tap-design.md`, "A. `release:github-draft`
attaches assets"), decided by Marco on si#449 (2026-10-18, decision 2: the release uploads over PyGithub,
`release:asset` stays as it is). The first consumer is marcozwyssig/firn#1132 (Linux binaries as release
assets). Marco decided on 2026-10-26 that everything build-specific is simplon's and that firn moves to the
dispatch release flow (si#463) in the same step. Order firn waits on: si#552 (done) -> si#553 (this) -> si#463.

## Intent

firn's release should carry its bare binary per platform as a GitHub Release asset, with a checksum a user can
verify, and only bytes a test ran. si#552 takes the file out of the image and tests it (`build:image-file`,
`test:file`, a verdict record naming the file's path and sha256). This piece uploads exactly those bytes to the
tag's draft release, under a published name, with a `sha256sum -c` sidecar, reads back what GitHub stored, and
says what it attached in a form a later step (si#449 F, firn's Homebrew formula) can read.

## Goals

1. **A new coordinate `release:github-attach`**, the fourth moment of a GitHub Release beside
   `release:github-unpublished`, `-draft` and `-publish` (si#486). Ports: `files` (input, kind `file`, one or
   more), `evidence` (input, `test-result`), `release-assets` (output). Param: `tag`. Offered, not placed,
   for the reason the other three are: a misfire is public, and a product with no GitHub Release has nothing
   waiting for it. `release:github-draft` is unchanged.
2. **It attaches to the draft `release:github-draft` made.** No draft for the tag is a refusal naming
   `release:github-draft`; a published release, or two drafts, are refused by the same `_one_draft` answer
   `draft` and `publish` already ask, before any byte moves.
3. **The published name is a template on the file entry**: the kind `file` gains an optional
   `asset_name:`, e.g. `"firn-{tag}-linux-amd64"`, `{tag}` replaced with the task's `tag`. A file bound to
   `attach` whose entry has no `asset_name` is refused (*my call*: the path's basename carries no tag, so a
   fallback would publish a wrong name). Two bound files with the same expanded name are refused before
   GitHub is asked.
4. **A checksum per file**: the task writes `<asset_name>.sha256` (`<hex>  <asset_name>\n`, the `sha256sum -c`
   format) and uploads it next to the file.
5. **Read back after upload**: GitHub's `digest` of each uploaded asset (file and sidecar) equals the local
   sha256. A mismatch, or an asset GitHub reports without a digest, is a refusal.
6. **Evidence (rule 6)**: each uploaded file is one a bound test result ran. Before uploading, the body
   compares each file's (product-relative path, `sha256:<hex>`) with `results.tested()`. A file no record
   names, or names with another digest, is refused, as `release:homebrew-tap` refuses a formula changed after
   its test.
7. **After `attach`, the draft carries exactly the bound files and their sidecars** (Marco, 2026-10-29). An
   asset under a name this run uploads is deleted and uploaded again (measured: uploading an existing name is
   HTTP 422 `already_exists`). Every other asset on the draft is deleted too, and each deletion is named in
   the log. So everything a later publish makes public has evidence from this run.
8. **Output `release-assets`**: a JSON file at the bound artifact's `path:`, listing per bound file its asset
   name, public URL `https://github.com/<owner>/<repo>/releases/download/<tag>/<name>`, sha256, and its
   sidecar's name and URL.

## Non-goals

- Files on a published release, or attaching after publish. A published release is never modified.
- Changing `release:asset` (decision 2) or `release:github-draft`.
- Several files per entry (`{platform}` in a path). si#552 decided one entry per platform; reopened by the
  same trigger it named (a product with more than two platforms per file).
- Wiring firn's release workflow. That is firn's, on top of si#463.
- A Homebrew formula for a binary asset (si#449 F).

## Anti-goals

- **An asset whose bytes no test ran**, on the draft at publish time. The evidence comparison is per file and
  by digest, never "some test result is green", and Goal 7 removes what this run did not vouch for.
- **A green run that attached nothing.** `attach` bound to no files is refused (*my call*: a
  `release-assets` record with an empty list reads as "nothing to do" and would only surface later, at the
  formula step). A bound file that is missing on disk is a refusal, not a skip.
- **A `release-assets` record that names a URL as if it were already public.** The URL is the one GitHub
  serves after publishing; the record's field name or the task's docstring says so (measured: a draft's
  `browser_download_url` is `.../download/untagged-<hash>/<name>` and 404s anonymously).
- **A sidecar that disagrees with the file.** The sidecar is written from the same hash the upload is
  compared with, and its own digest is read back too.

## How a product uses it (firn, as a sketch)

```yaml
artifacts:
  firn-amd64: { kind: file, path: build/files/firn-linux-amd64, platform: linux/amd64,
                asset_name: "firn-{tag}-linux-amd64" }
  firn-arm64: { kind: file, path: build/files/firn-linux-arm64, platform: linux/arm64,
                asset_name: "firn-{tag}-linux-arm64" }
  firn-assets: { kind: release-assets, path: build/release/assets.json }
ci:
  release:
    commands:
      draft: { task: "release:github-draft", consumes: { release-notes: firn-notes } }
      # ... build and the test:file checks run between the two ...
      attach:
        task: "release:github-attach"
        consumes:
          files: [firn-amd64, firn-arm64]
          evidence: [firn-amd64-runs, firn-amd64-version, firn-arm64-runs, firn-arm64-version]
        produces: { release-assets: firn-assets }
      publish: { task: "release:github-publish" }
```

si#463 (Marco's decision D) drafts the release before the build; the files exist only after the build and
their tests; so attaching is its own moment, between the checks and the publish. A re-run of the whole flow
reuses the draft and `attach` puts the draft back to exactly this run's files.

## Constraints

- **One adapter, one client** (decision 2): PyGithub through `simplon.adapters.github`. Upload with
  `GitRelease.upload_asset`, delete with `GitReleaseAsset.delete_asset`, read `GitReleaseAsset.digest`
  (present in the pinned PyGithub; measured on a draft 2026-10-28, equal to the local `sha256sum`).
- **Every failure names the asset and says what is left**: which assets are on the draft, which are not, and
  that a re-run of `attach` puts the draft right. A half-attached draft is the normal state after a failure,
  and a re-run is its way out.
- **No secret in a log line**: the token reaches PyGithub only, as today.
- **Schema changes go through the firn model** (`./simplon.sh build model`), and the regenerated files are
  committed with the change: the kind `file` gains `asset_name`, a new kind `release-assets` refines
  `release`, the new task carries its three ports.
- **Rule 6 needs no change.** `file` is not in `OWN_KINDS`, so `attach` must bind a test result about each
  file it consumes. `release-assets` refines `release`, so it is an own kind (as `github-release` is) and
  needs no test result, if anything ever consumes it.
- Every new refusal gets its census entry (`tests/test_refusal_census.py`), saying which kind it is.

## Decided

- Part A in simplon, firn on si#463 in the same step (Marco, 2026-10-26, firn#1132).
- The release uploads over PyGithub; `release:asset` unchanged (si#449 decision 2, 2026-10-18).
- The ticket's five points: asset name template, sidecar, evidence, re-runs, `release-assets`.
- Marco, 2026-10-29 (questions skipped; this document is written from the ticket, the si#449 spec and the
  2026-10-28 measurements, and the builder check's open points went back to him once):
  - **A new coordinate `release:github-attach`**, not `release:github-draft` placed twice. Rejected: three new
    ports on `release:github-draft` and a second placement after the checks, which would have rewritten the
    body with the same notes and made the notes a required input of a moment that does not need them. The
    reason is si#486's: the ports differ per moment. Reopened if a product attaches files with no build
    between draft and attach.
  - **Foreign assets are removed and named** (Goal 7). Rejected: refusing and naming them (a re-run after a
    renamed `asset_name` would then always need a hand), and leaving them (they would be published without
    evidence).
  - **The end-to-end test runs on marcozwyssig/simplon**, with a throwaway draft deleted afterwards, as the
    2026-10-28 measurement did.

## Measured (2026-10-28, a throwaway draft on marcozwyssig/simplon, deleted afterwards)

- A draft asset carries `digest: "sha256:<hex>"` in the upload response and on a later GET, equal to the local
  `sha256sum`. So the ticket's fallback (download and hash when there is no digest) is not built: an asset
  without a digest is a refusal.
- `GET /repos/{o}/{r}/releases/assets/{id}` with `Accept: application/octet-stream` and the token returns a
  draft asset's bytes.
- A draft's `browser_download_url` is `.../releases/download/untagged-<hash>/<name>` and 404s unauthenticated.
- Uploading an existing name is HTTP 422 `already_exists`.
- From si#552: a `test:file` run on the host platform records `platform: ""`, a timed-out one `rc: null`; the
  subject is (product-relative path, `sha256:<hex>`).

## Left to the builder

- **How the body learns the bound file names.** A port with a `param` hands exactly one name today
  (`treeform` takes `[0]`), so `files` has `param: ""` and the names reach the body another way. Both entry
  paths must carry them: the assembled CLI (`simplon.cli`) and the generated module (`taskgen`), the two places
  `results.guarded` is wired. `results.tested()` (a ContextVar set by the wrapper) is the precedent.
- Where the sidecars are written before upload (under the output directory, not the product tree).
- The exact JSON field names of `release-assets`, as long as Goal 8's content is there and the URL's field or
  docstring says it is public only after publishing.
- Which characters `asset_name` may contain. GitHub rewrites some characters in asset names; whether it does,
  and which, is to be measured on a throwaway draft before a refusal is written.
- The order inside `attach` (delete foreign assets first or last), as long as a failure says what is left.

## Acceptance

1. Unit tests for every refusal and for the record, against a faked PyGithub where no network is wanted.
2. One end-to-end run against a real throwaway draft on marcozwyssig/simplon, deleted afterwards (no release
   and no tag remain): two files uploaded with sidecars, digests read back, a foreign asset removed, a re-run
   replaces the files, `release-assets` written. Seen red: break the digest comparison and the evidence
   comparison, watch each fail. *(My call:)* the refusal of a published release stays a unit test, because
   proving it for real would publish a release and a tag on simplon.
3. firn's release attaching its binaries is the ticket's acceptance after that (firn's, on si#463).
