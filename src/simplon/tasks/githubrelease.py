"""`release:github-unpublished`, `release:github-draft` and `release:github-publish` (si#486, part of si#463).

THREE COORDINATES, ONE PER MOMENT OF A RELEASE STARTED FROM GITHUB ACTIONS (Marco, si#463 D1):

  `unpublished`  before anything is built: does the tag have a PUBLISHED GitHub Release? A draft or none
                 is green, because that is an unfinished release, and a re-run may finish it. A published one is red,
                 because a published release is never overwritten. A question the API did not answer is red too:
                 nothing is released on an unanswered question.
  `draft`        before the build: a DRAFT release for the tag, with the `release-notes` artifact as its
                 body. A draft is not public and needs no tag on origin. A draft an earlier run left is
                 reused and its body replaced, so a failed run leaves at most one draft and the next run
                 picks it up.
  `publish`      after the image push: the draft becomes the published release. Refused unless origin
                 carries the tag, because publishing a release whose tag does not exist makes GitHub create
                 that tag at the default branch's head - a tag nobody validated.

One coordinate each, not one with a `--step`, because the ports differ per moment (only `draft` reads the
notes, only `publish` produces the release) and a port cannot depend on a parameter.

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

import requests
from github import GithubException
from github.GitRelease import GitRelease
from github.Repository import Repository

from simplon.adapters import github
from simplon.kernel import log
from simplon.manifest import artifactsection, context
from simplon.model import artifactschema
from simplon.tasks import gitops

ARTIFACTS = "artifacts"
ENTRY = artifactschema.Release_notesEntry


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
