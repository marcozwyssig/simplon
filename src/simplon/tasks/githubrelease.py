"""`release:github-unpublished`, `release:github-draft`, `release:github-attach` and `release:github-publish` (si#486, part of si#463; the attach is si#553).

FOUR COORDINATES, ONE PER MOMENT OF A RELEASE STARTED FROM GITHUB ACTIONS (Marco, si#463 D1):

  `unpublished`  before anything is built: does the tag have a PUBLISHED GitHub Release? A draft or none
                 is green, because that is an unfinished release, and a re-run may finish it. A published one is red,
                 because a published release is never overwritten. A question the API did not answer is red too:
                 nothing is released on an unanswered question.
  `draft`        before the build: a DRAFT release for the tag, with the `release-notes` artifact as its
                 body. A draft is not public and needs no tag on origin. A draft an earlier run left is
                 reused and its body replaced, so a failed run leaves at most one draft and the next run
                 picks it up.
  `attach`       after the build: the tested files, and a `.sha256` sidecar for each, become the assets of
                 the draft; every other asset on it is deleted. Its own moment because the files exist only
                 after the build (si#463 D) and its ports (files, evidence, the release-assets it produces)
                 are nobody else's. Every refusal that needs no GitHub comes first (`_planned`).
  `publish`      after the image push: the draft becomes the published release. Refused unless origin
                 carries the tag, because publishing a release whose tag does not exist makes GitHub create
                 that tag at the default branch's head - a tag nobody validated.

One coordinate each, not one with a `--step`, because the ports differ per moment (only `draft` reads the
notes, only `attach` reads files, only `publish` produces the release) and a port cannot depend on a parameter.

firn built these three as a product module (`orchestrator/ghrelease.py`, firn#1040) and is not merging it:
this is that module, moved where every product reaches it. The differences are deliberate.
- No `vX.Y.Z` check: the pattern is the dispatch flow's (`release:check`, si#487), and a product whose release
  tags are build stamps uses these as they are.
- The draft points at `gitops.head_commit()`, not `GITHUB_SHA`. That is the same commit in a dispatch run, and also
  right by hand.
- "Origin carries the tag" is `gitops.remote_tag_commit`, the tri-state `release:tag` already asks,
  so the phrase has one meaning in the kernel.

PyGithub's `update_release` DEFAULTS `draft` TO FALSE. A reuse that rewrote the body without saying
`draft=True` would publish the draft before the build. So every update here names `draft` explicitly.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from github import GithubException
from github.GitRelease import GitRelease
from github.Repository import Repository

from simplon.adapters import github
from simplon.kernel import log
from simplon.manifest import artifactsection, bound, context
from simplon.manifest import results as results_mod
from simplon.manifest.layout import validate_relative_dir
from simplon.model import artifactschema
from simplon.tasks import gitops

ARTIFACTS = "artifacts"
ENTRY = artifactschema.Release_notesEntry
ATTACH_COORDINATE = "release:github-attach"

#: What GitHub keeps of an asset name as it is (measured, si#553 Task 0). Any other ASCII character is stored as
#: `.`, a non-ASCII one or a leading `.` earns a `default.` prefix, so the URL the release would name is wrong.
_KEPT_NAME = re.compile(r"^[A-Za-z0-9_+@-][A-Za-z0-9_.+@-]*$")


def unpublished(tag: str = "") -> int:
    """0 when `tag` has no PUBLISHED GitHub Release (a draft or none); 1 when it has, or GitHub did not say."""
    name = _tag(tag)
    try:
        found = github.published(_repository(), name)
    except github.Unanswered as unanswered:
        log.error(f"could not tell whether {name} is published: {unanswered}. Nothing is released on a "
                  f"question that was not answered")
        return 1
    if found is not None:
        log.error(f"{name} is a published release ({found.html_url}); a published release is never "
                  f"overwritten. Choose the next version")
        return 1
    log.ok(f"{name} has no published release, so this is an unfinished release and may finish")
    return 0


def draft(name: str = "", tag: str = "") -> int:
    """Create, or reuse, the DRAFT release for `tag` with the `release-notes` artifact `name` as its body."""
    version = _tag(tag)
    body = _notes(name)
    if body is None:
        return 1
    try:
        repo = _repository()
        usable, found = _one_draft(repo, version)
        if not usable:
            return 1
        if found is not None:
            # `prerelease` is passed back as it is: PyGithub sends False for it otherwise, and a draft somebody
            # marked as a pre-release by hand would become a full release (si#486's final review)
            made = found.update_release(name=version, message=body, draft=True, prerelease=found.prerelease)
            said = f"reused the draft release {version} an earlier run left, with this run's notes"
        else:
            made = repo.create_git_release(version, name=version, message=body, draft=True,
                                           target_commitish=gitops.head_commit())
            said = f"created the draft release {version}; it is published after the image is"
    except github.Unanswered as unanswered:
        log.error(f"no draft release for {version}: {unanswered}")
        return 1
    except GithubException as refused:
        log.error(f"GitHub refused the draft release for {version}: {github.said(refused)}")
        return 1
    except requests.exceptions.RequestException as unreachable:
        log.error(f"GitHub could not be reached for the draft release {version}: {unreachable}")
        return 1
    # THE ANSWER, NOT THE STATUS, as `publish` asks it: a release GitHub reports public before the build is
    # the one outcome this step exists to prevent, and it must not be logged as a draft.
    if not made.draft:
        log.error(f"GitHub answered the draft release for {version} as not a draft ({made.html_url}): it is "
                  f"public before anything was built. Check it by hand")
        return 1
    log.ok(said)
    return 0


@dataclass(frozen=True)
class _Upload:
    """One file `attach` puts on the draft: its entry, where it is, and the name and digest it goes by."""
    entry: str
    path: Path
    relative: str
    name: str
    sha256: str


def attach(tag: str = "", assets: str = "") -> int:
    """Attach the tested files bound to `files`, and a `.sha256` sidecar for each, to the DRAFT release for `tag`.

    Only the refusals that need no GitHub are here (si#553 Task 3); `_planned` says why and returns None.
    What follows them is Task 4's, and until then the body raises rather than return 0: a green run that
    attached nothing is the defect this kernel is built against."""
    version = _tag(tag)
    plan = _planned(version)
    if plan is None:
        return 1
    raise NotImplementedError("si#553 Task 4")


def _planned(tag: str) -> list[_Upload] | None:
    """What `attach` would put on the draft, or None after saying why not, before GitHub was asked.

    Every refusal names the entry, what is wrong and the way out. Nothing is read from GitHub: a file that is
    not the tested one, or whose name GitHub would rewrite, costs a draft's assets once uploaded."""
    names = bound.names("files")
    if not names:
        log.error(f"{ATTACH_COORDINATE} is bound to no files, so there is nothing to attach: bind the files to "
                  f"attach with `consumes: {{ files: [...] }}`")
        return None
    ctx = context.current()
    section = ctx.manifest_data().get(ARTIFACTS) or {}
    source = ctx.manifest_path.name
    planned: list[_Upload] = []
    problems: list[str] = []
    for name in names:
        if name not in section:
            raise ValueError(f"{source}: no artifact '{name}' in the `{ARTIFACTS}:` section; declared are: "
                             f"{', '.join(sorted(str(k) for k in section)) or '(none)'}")
        entry = artifactsection.entry(section, name, artifactschema.FileEntry, source, ATTACH_COORDINATE,
                                      param="")
        if not entry.asset_name:
            problems.append(f"'{name}' has no `asset_name`: give the name the file is attached under, e.g. "
                            f"`asset_name: tool-{{tag}}-linux-amd64`")
            continue
        asset = entry.asset_name.replace("{tag}", tag)
        if not _KEPT_NAME.fullmatch(asset):
            problems.append(f"'{name}': the asset name '{asset}' is empty, starts with `.` or has a character "
                            f"outside A-Z a-z 0-9 _ . + @ -, and GitHub would store another name (other ASCII "
                            f"becomes `.`, non-ASCII and a leading dot get a `default.` prefix), so the "
                            f"`release-assets` URL would be wrong: rename it in `asset_name`")
            continue
        relative = validate_relative_dir(entry.path or "", f"{source}: '{ARTIFACTS}.{name}': 'path'",
                                         "give the file's path under the product root, e.g. 'build/tool'",
                                         inside="the product root")
        path = ctx.root / relative
        if not path.is_file():
            problems.append(f"'{name}' has nothing at {relative}: run the command that produces it first")
            continue
        planned.append(_Upload(name, path, relative, asset, hashlib.sha256(path.read_bytes()).hexdigest()))
    by_name: dict[str, list[str]] = {}
    for upload in planned:
        by_name.setdefault(upload.name, []).append(upload.entry)
    for asset, owners in by_name.items():
        if len(owners) > 1:
            problems.append(f"{' and '.join(repr(o) for o in owners)} both expand to the asset name {asset}: "
                            f"one would replace the other; make their `asset_name` differ")
    if problems:
        log.error(f"{ATTACH_COORDINATE} refused for {tag}, so no asset was uploaded or deleted:\n  "
                  + "\n  ".join(problems))
        return None
    return planned if _tested(planned) else None


def _tested(planned: list[_Upload]) -> bool:
    """True when the bound evidence names every file by its product-relative path with the digest it has now,
    else False after saying which does not (the `release:homebrew-tap` rule, for several files)."""
    subjects = results_mod.tested()
    if subjects is None:
        log.error(f"refused: {ATTACH_COORDINATE} has no evidence bound, so nothing says the files were tested. "
                  f"Bind the test:file results to `evidence` with `consumes:`")
        return False
    problems: list[str] = []
    for upload in planned:
        digest = "sha256:" + upload.sha256
        named = [s for s in subjects if s.reference == upload.relative]
        if not named:
            ran = ", ".join(s.reference for s in subjects) or "nothing"
            problems.append(f"{upload.relative} ('{upload.entry}'): no test names it (the evidence tested "
                            f"{ran}); run test:file on it with its result bound to `evidence`")
        elif all(s.id != digest for s in named):
            problems.append(f"{upload.relative} ('{upload.entry}') is {digest}, and the evidence tested "
                            f"{', '.join(s.id for s in named)}: the file changed after its test; run "
                            f"test:file on it again, then attach")
    if problems:
        log.error("refused, so no asset was uploaded or deleted:\n  " + "\n  ".join(problems))
        return False
    return True


def publish(tag: str = "") -> int:
    """Publish the draft release for `tag`, which origin must already carry."""
    version = _tag(tag)
    at = gitops.remote_tag_commit(version)
    if at is None:
        log.error(f"could not ask origin for the tag {version}, so nothing was published: publishing a tag "
                  f"origin may not carry would make GitHub create it")
        return 1
    if not at:
        log.error(f"origin has no tag {version}, and publishing would create it at the default branch's "
                  f"head: nothing was published. `release:tag` pushes it")
        return 1
    try:
        usable, found = _one_draft(_repository(), version, publishing=True)
        if not usable:
            return 1
        if found is None:
            log.error(f"there is no draft release for {version} to publish: `release:github-draft` makes it, "
                      f"before the build")
            return 1
        done = found.update_release(name=found.name or version, message=found.body or "", draft=False,
                                    prerelease=found.prerelease, tag_name=version)
    except github.Unanswered as unanswered:
        log.error(f"{version} was not published: {unanswered}")
        return 1
    except (GithubException, requests.exceptions.RequestException) as refused:
        why = github.said(refused) if isinstance(refused, GithubException) else str(refused)
        log.error(f"GitHub refused to publish {version}: {why}; it stays a draft, and a re-run publishes it")
        return 1
    if done.draft:
        log.error(f"GitHub answered the publish of {version} but the release is still a draft "
                  f"({done.html_url}); it stays a draft, and a re-run publishes it")
        return 1
    log.ok(f"published the GitHub Release {version}: {done.html_url}")
    return 0


def _tag(tag: str) -> str:
    """The tag, stripped, or a ValueError before anything is asked."""
    name = tag.strip()
    if not name:
        raise ValueError("which release? pass the tag exactly as it exists or will exist (e.g. v1.4.0)")
    if not gitops.valid_tag_name(name):
        raise ValueError(f"'{tag}' is not a tag git would accept (`git check-ref-format`)")
    return name


def _repository() -> Repository:
    gitops.configure(context.current().root)
    return github.repository(gitops.origin_url())


def _one_draft(repo: Repository, tag: str, *, publishing: bool = False) -> tuple[bool, GitRelease | None]:
    """(True, the one draft for `tag` or None when there is none), or (False, None) after saying why the
    matches may not be used.

    A published release among the matches wins, so it is never modified. Two drafts are refused, naming each:
    which one this run meant is not the kernel's to guess."""
    matches = github.releases_for(repo, tag)
    public = [r for r in matches if not r.draft]
    if public:
        if publishing:
            log.error(f"{tag} is already published ({public[0].html_url}); nothing was changed")
        else:
            log.error(f"{tag} is already a published release ({public[0].html_url}); it is never "
                      f"overwritten, so no draft was made")
        return False, None
    if len(matches) > 1:
        log.error(f"{len(matches)} draft releases carry the tag {tag}: "
                  f"{', '.join(r.html_url for r in matches)}. Delete all but one; which this run meant is "
                  f"not the kernel's to guess")
        return False, None
    return True, (matches[0] if matches else None)


def _notes(name: str) -> str | None:
    """The text of the `release-notes` artifact `name`, or None after saying why there is none."""
    if not name:
        raise ValueError(f"which artifact? pin the release notes with `consumes:` from the `{ARTIFACTS}:` "
                         f"section, or pass --name")
    ctx = context.current()
    section = ctx.manifest_data().get(ARTIFACTS) or {}
    if name not in section:
        raise ValueError(f"no artifact '{name}' in {ctx.manifest_path.name}'s `{ARTIFACTS}:` section; "
                         f"declared are: {', '.join(sorted(section)) or '(none)'}")
    entry = artifactsection.entry(section, name, ENTRY, ctx.manifest_path.name, "release:github-draft")
    path = ctx.root / str(entry.path)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not text.strip():
        log.error(f"{entry.path} holds no notes: run `release:notes` for this tag in this checkout first")
        return None
    return text
