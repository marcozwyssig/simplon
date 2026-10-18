# si#491: simplon releases through its own `workflows: release:` dispatch flow

Part of si#463 (decision D7) and si#344. simplon is the first in-house user of the `release:` key from si#490.
Marco decided on 2026-10-18 after a measurement (si#491 comment 6246271640), then gave two more answers
after the builder check (decisions 5 and 6). Measured on main eaec324.

## Intent

simplon's `.github/workflows/release.yml` is hand-written today. A `push: tags: ["v*"]` triggers it, and
`simplon.yaml` names it `handwritten:`. A release is cut by typing `./simplon.sh release tag vX` and
then pushing. The workflow builds, tests and publishes only after the tag already exists. That is the
opposite of the order `release all` states: a red test or a failed publish leaves a public tag behind
(memory: v0.29.0). si#490 gave the kernel a derived dispatch release. simplon now uses it on itself
before firn takes it over (firn#1040). The rule is the one this repository has kept since #32: a step
the kernel never runs in its own house rots unseen.

## Goals

- `simplon.yaml` declares `workflows: release:` with `release: release all`. The `handwritten:` entry is
  gone. `.github/workflows/release.yml` is GENERATED, and `support workflows --check` holds it. The path
  stays `.github/workflows/release.yml` and the PyPI job keeps `environment: pypi`. PyPI's trusted
  publisher is configured by filename and environment on PyPI's side, which cannot be read from here.
  Only the first real cut can test it (see Acceptance).
- The button carries a release: `version` plus `dry_run`, both derived by si#490.
- **The test gate runs before the tag** (decision 2). `release all` becomes
  `depends_on: [suite, typecheck-python, generated, release-notes, notes, tag]`, with `passes: [tag]`,
  `stop_on_failure: true` and `produces: { release: kernel-release }` unchanged. Measured: this loads
  under rule 8 and renders as `test suite`, `test typecheck-python`, `test generated`,
  `test release-notes`, `release notes --tag "$RELEASE_VERSION"`, then
  `if: !inputs.dry_run` `release tag -- "$RELEASE_VERSION"`. A red test no longer leaves a tag.
  `release all` run locally now runs the suite too. That is intended and stated in its `help:` and comment.
- **Three product jobs beside `release:`.** `publish` has `needs: release`. `docs` and `image` keep
  `needs: publish`, today's rule that the image and the site carry the version PyPI serves
  (`test_own_image.py` holds it). Each job keeps what today's file does:
  - `publish`: `build wheel`, the si#3 wheel-is-the-tag check as a verbatim `run:` step (decision 4,
    with its reasoning moved into a `note:`), `pypa/gh-action-pypi-publish` under
    `if: ${{ !inputs.dry_run }}`, `environment: pypi`, `permissions: id-token: write`.
  - `docs`: `needs: publish`, `build docs`, the upload, and `deploy-pages` under
    `if: ${{ !inputs.dry_run }}`. It keeps `environment: github-pages` with its url, its `pages` and
    `id-token` permissions, and its `concurrency: pages`. Measured: the `github-pages` environment
    accepts deployments from `main` and from `v*` tags, so a dispatch from `main` may deploy.
  - `image` (decision 1): QEMU, `build image`, `test image` and `release push-image`, then the pin-PR
    script. The push and the pin run under `if: ${{ !inputs.dry_run }}`. It keeps its four permissions.
    `release all` drops `push-image`, and the command stays placed so a person can still type it.
- **A dry run builds and checks everything and publishes nothing**, in the product jobs too. The wheel,
  the site and the image are built and checked. Only the upload, the deploy, the push and the pin are
  skipped. *(My call: si#490's input text says "build and check everything", and skipping whole jobs
  would rehearse less than that.)*
- In product jobs the version reaches commands through `{ env: RELEASE_VERSION }`, with the job setting
  `env: RELEASE_VERSION: ${{ inputs.version }}`. si#490 refuses this only at workflow level. Every
  `GITHUB_REF_NAME` in today's scripts becomes `$RELEASE_VERSION`, because on a dispatch from `main` the
  ref name is `main`.
- **Every product job cuts the tag locally first** (decision 5). Its first step after the checkout is the
  release job's own cut script: `workflowgen.RELEASE_CUT`, as a verbatim `run:`. Copy it from the
  constant, and add a test that holds the copy equal to it. On a real run the fetched tag already sits
  at HEAD, so the cut changes nothing. On a dry run it makes the wheel, the site and the image carry
  the version, so the si#3 check passes honestly and `docs` and `image` run on a rehearsal too.
- The product jobs check out `github.sha`, the default. That is the commit the release job tagged, and
  with `fetch-depth: 0` the checkout fetches the tag the release job pushed. setuptools-scm therefore
  derives the tag's version with no `ref:`. *(My call.)*
- Product jobs declare `python: "3.12"`, as today. The derived release job has no setup-python step:
  `_release` sets no `python:`, and ubuntu-latest's system Python meets `requires-python >=3.11`.
  *(My call: not a kernel change for si#491.)*
- **The Allure archive leaves the release path** (decision 6). The suite now runs in the derived job,
  and that job cannot carry a `uses:` or `if: always()` step. `ci.yml` keeps its archive. The loss is
  stated in the release docs and in the PR, and si#509 holds the kernel question.
- **Off-main is refused, and the si#23 report goes** (decision 3). `release tag` already refuses a
  commit `main` does not carry, and the dispatch has no tag-push route. The report step and the four
  tests that hold it are deleted. The head-of-file prose explaining the split is replaced by one note
  saying the route is closed: a hotfix merges first.
- Docs: `how/releasing.md`, `README.md` and the case pages that say `git tag && git push` or
  `release tag vX` for *simplon's own* release describe the button. Pages about a *product's* release
  are only touched where they describe simplon. The memory file "a cut tag with a failed publish" holds:
  rerun the failed job and never cut a second tag.

## Non-goals

- `release:check` (si#487, waiting on cleon#80).
- A group-qualified `depends_on:` (`build image`), which would move the image ahead of the tag. Not
  ticketed by this decision. If wanted, a separate ticket.
- Moving PyPI ahead of the tag. It is a `uses:` action and cannot be a leaf.
- Rewriting `release all`'s behaviour for other products. This is simplon's manifest only, so the kernel
  is unchanged unless a builder finds a defect. A defect found is reported, not patched away.

## Anti-goals

- Any `${{ inputs.` inside a `run:` script, including in the product jobs' verbatim scripts.
- A dry run that publishes anything: a PyPI upload, a Pages deploy, an image push, a pin branch or a PR.
- A second release route. Nothing triggers on `push: tags`.

## Tests

- `test_release_workflow.py` and the release tests in `test_own_image.py` keep reading
  `.github/workflows/release.yml`. That file is now generated, so each test holds the generated text.
  - Rewrite the trigger test: `workflow_dispatch` and nothing else.
  - Delete the on-main tests.
  - Keep the wheel-check test, the history tests, the docs-job tests, the image-after-publish test and
    the pin-PR test, adjusted to `$RELEASE_VERSION`.
  - Add a test that every publishing step (`pypa/`, `deploy-pages`, `push-image`, the pin script) is
    under `!inputs.dry_run`.
  - Add a test that every product job's first step after the checkout equals `RELEASE_CUT`.
  - Delete the test that holds the Allure upload on the release path, or rewrite it to state its
    absence and point at si#509.
- `test_own_workflows.py` currently expects `release.yml` to be the one declined workflow. It changes
  to "no workflow is declined".
- `test_type_gate.py` must still find the gate on the release path. The release job names
  `test typecheck-python`, so `release.yml` stays in the verifying set. Check this, don't assume it.
- The census does not change unless the kernel does.

## Acceptance (from si#491)

- A dispatch with `dry_run: true` goes green on GitHub and publishes nothing.
- The next real cut goes through the button.
- The docs describe the button, not `git tag && git push`.
