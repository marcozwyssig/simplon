"""The GitHub REST API for a product's own repository, over PyGithub (si#486).

THREE ANSWERS, NOT TWO. Every question here has a found, an absent and an UNANSWERED outcome, and the
third is an exception (`Unanswered`) carrying the reason, never a None a caller could read as "absent".
That is the house defect in its plainest form: a release coordinate that took "could not ask" for "there
is no release" would draft over, or publish past, a release it never saw.

A 404 MEANS SOMETHING ONLY ONCE THE REPOSITORY HAS ANSWERED. GitHub answers 404 for a repository the
token cannot see, a misspelled one and a wrong API host alike - the same status as "no such release". So
`repository()` asks for the repository itself first, and a 404 on a release lookup is trusted only after
that answered 200.

WHERE THE REPOSITORY AND THE API ARE, decided by Marco on 2026-10-17. `GITHUB_REPOSITORY` and
`GITHUB_API_URL`, which Actions sets for every job, win when they are set. The container route's launcher
forwards neither (only the tokens), so otherwise both are read off origin's URL: the path names the
repository, and a `github.com` host means `https://api.github.com`.

THE TOKEN GOES TO GITHUB AND NOWHERE ELSE - `githubpackages`' own rule, and the reason the origin route
stops at github.com. A GitHub Enterprise origin would map to `https://<host>/api/v3`, but the token here
is a github.com one (`gh auth token` answers for github.com), and a host read out of a checkout's remote is
a host the checkout chose: a clone whose origin names any machine would have that machine handed the
token. So an Enterprise host is named by the person, in `GITHUB_API_URL` (Actions on GHES sets it), and
an origin that is not github.com is refused rather than followed. Measured by the commit security review
of si#486, which narrowed Marco's "derive it from origin" by its Enterprise half.

THE TOKEN is `githubpackages.token()`, the kernel's one token story: `GITHUB_TOKEN`, then `gh auth token`
(which answers `GH_TOKEN` on the container route, where the launcher forwards it and `gh` has no login).
Never an argument, never a file.

NO SILENT RETRIES. PyGithub retries a 5xx by default; here `retry=None`, so one question is one request
and an answer that did not come says so at once rather than after a minute of backoff.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import requests
from github import Auth, Github, GithubException, UnknownObjectException
from github.GitRelease import GitRelease
from github.GitReleaseAsset import GitReleaseAsset
from github.Repository import Repository

from simplon.adapters import githubpackages

#: How long one call may take. The calls are small; a hung connection must not hold the runner.
TIMEOUT_S = 30

#: Pages of 100 read looking for a release by tag. A DRAFT is not reachable through the tag lookup (it
#: answers published releases only), so the list is read; ten pages is a thousand releases, and a
#: repository with more is told so rather than answered "none".
PAGES = 10
PER_PAGE = 100

_ORIGIN = re.compile(r"^(?:[a-z+]+://)?(?:[^@/]+@)?(?P<host>[^/:]+)[:/](?P<path>[^/]+/[^/]+?)(?:\.git)?/?$")


class Unanswered(Exception):
    """GitHub did not answer the question; `str()` is the whole reason, fit to show a person."""


def locate(origin: str) -> tuple[str, str] | None:
    """(`owner/name`, API base) out of an origin URL on github.com, or None for any other origin - an
    Enterprise host included, which only `GITHUB_API_URL` may name (see the module docstring)."""
    found = _ORIGIN.match(origin.strip())
    if not found or found["host"].lower() != "github.com":
        return None
    return found["path"], "https://api.github.com"


def where(origin: str = "") -> tuple[str, str]:
    """(`owner/name`, API base): the environment first, the `origin` URL for what it leaves out. The caller
    reads origin (`gitops.origin_url()`), because an adapter sits below the tasks and asks no git."""
    name = os.environ.get("GITHUB_REPOSITORY", "").strip()
    api = os.environ.get("GITHUB_API_URL", "").strip().rstrip("/")
    if name and api:
        return name, api
    located = locate(origin)
    if located is None:
        raise Unanswered(
            f"no GitHub repository to ask: GITHUB_REPOSITORY and GITHUB_API_URL are "
            f"{'set' if name else 'not set'} / {'set' if api else 'not set'}, and origin is "
            f"{'not a github.com URL' if origin else 'not set'} - a GitHub Enterprise is named by "
            f"GITHUB_API_URL, never read off a remote. The Release workflow sets both; by hand, export them. On "
            f"the container route the launcher forwards neither, so declare "
            f"`launcher: env: pass: [GITHUB_REPOSITORY, GITHUB_API_URL]` (si#467) to carry them in")
    return name or located[0], api or located[1]


def repository(origin: str = "") -> Repository:
    """The product's repository, ASKED for - so that a later 404 means what it says."""
    name, api = where(origin)
    try:
        token = githubpackages.token()
    except githubpackages.PackageError as missing:
        raise Unanswered(str(missing)) from None
    except OSError as no_gh:
        # `token()` falls back to `gh auth token`, and on a host without `gh` that is FileNotFoundError, not
        # a PackageError - found by si#486's final review as a traceback where a sentence belongs.
        raise Unanswered(f"no GitHub token: GITHUB_TOKEN is not set and `gh` could not be run ({no_gh}). "
                         f"Export GITHUB_TOKEN; in GitHub Actions, pass `secrets.GITHUB_TOKEN` in the step's `env:`") from None
    return _asked(name, api, token, "(GITHUB_TOKEN, else `gh auth token`)")


def other(name: str, token: str) -> Repository:
    """Another repository, `owner/name`, ASKED for with the token given (si#535): the same client, the same
    three answers. The API is `GITHUB_API_URL`, else github.com's. A token of whitespace is no token."""
    token = token.strip()
    if not token:
        raise Unanswered(f"no token for {name}: none was given, so GitHub was not asked. Export the token "
                         f"that can see {name}")
    api = os.environ.get("GITHUB_API_URL", "").strip().rstrip("/") or "https://api.github.com"
    return _asked(name, api, token, "(the one given)")


def _asked(name: str, api: str, token: str, seen_by: str) -> Repository:
    """The one place a client is built and the repository asked for; `seen_by` names the token in a 404."""
    client = Github(auth=Auth.Token(token), base_url=api, timeout=TIMEOUT_S, retry=None, per_page=PER_PAGE,
                    lazy=False)
    try:
        # NOT lazy (PyGithub 2.x's default, and measured: `get_repo` issues the GET itself), which is the
        # whole point - the repository has to answer before a 404 below can be believed.
        repo = client.get_repo(name)
    except UnknownObjectException:
        raise Unanswered(
            f"{api} answers 404 for the repository {name}: it does not exist there, or the token "
            f"{seen_by} cannot see it - so no release question can be "
            f"answered") from None
    except GithubException as refused:
        raise Unanswered(f"{api} refused the repository {name}: {said(refused)}") from None
    except requests.exceptions.RequestException as unreachable:
        raise Unanswered(f"could not reach {api}: {unreachable}") from None
    return repo


def published(repo: Repository, tag: str) -> GitRelease | None:
    """The PUBLISHED release for `tag`, or None when there is none (a draft, or nothing)."""
    try:
        return repo.get_release(tag)
    except UnknownObjectException:
        return None
    except GithubException as refused:
        raise Unanswered(f"could not ask whether {tag} is published: {said(refused)}") from None
    except requests.exceptions.RequestException as unreachable:
        raise Unanswered(f"could not ask whether {tag} is published: {unreachable}") from None


def releases_for(repo: Repository, tag: str) -> list[GitRelease]:
    """Every release, draft or published, whose tag is `tag` - read off the list, PAGES pages at most."""
    found: list[GitRelease] = []
    try:
        listing = repo.get_releases()
        for page in range(PAGES):
            chunk = listing.get_page(page)
            found += [r for r in chunk if r.tag_name == tag]
            if len(chunk) < PER_PAGE:
                return found
    except GithubException as refused:
        raise Unanswered(f"could not list the releases: {said(refused)}") from None
    except requests.exceptions.RequestException as unreachable:
        raise Unanswered(f"could not list the releases: {unreachable}") from None
    raise Unanswered(f"the repository has more than {PAGES * PER_PAGE} releases, and the search for {tag} "
                     f"stops there rather than answer 'none' about the rest")


def assets(release: GitRelease) -> list[GitReleaseAsset]:
    """Every asset on `release`, as the API lists them (si#553). A failed read is Unanswered, never an empty
    list: an attach that took "could not ask" for "no assets" would upload over, or fail to clear, what it
    never saw."""
    try:
        return list(release.get_assets())
    except GithubException as refused:
        raise Unanswered(f"could not list the assets of release {release.id}: {said(refused)}") from None
    except requests.exceptions.RequestException as unreachable:
        raise Unanswered(f"could not list the assets of release {release.id}: {unreachable}") from None


def upload(release: GitRelease, path: Path, name: str) -> GitReleaseAsset:
    """Upload the file at `path` to `release` as the asset `name`, content type `application/octet-stream`
    (si#553). A taken name is GitHub's own HTTP 422 `already_exists`, a GithubException the caller sees as
    it is; only a transport failure is Unanswered."""
    try:
        return release.upload_asset(str(path), name=name, content_type="application/octet-stream")
    except requests.exceptions.RequestException as unreachable:
        raise Unanswered(f"could not upload {name} to release {release.id}: {unreachable}") from None


def delete(asset: GitReleaseAsset) -> None:
    """Delete `asset` from its release (si#553). A transport failure is Unanswered; a refusal is the
    GithubException, as for `upload`."""
    try:
        asset.delete_asset()
    except requests.exceptions.RequestException as unreachable:
        raise Unanswered(f"could not delete asset {asset.name}: {unreachable}") from None


def said(refused: GithubException) -> str:
    """HTTP status and GitHub's own words, `message` and `errors`, out of a refusal."""
    data = refused.data if isinstance(refused.data, dict) else {}
    message = data.get("message") or str(refused.data or "") or "no message"
    errors = data.get("errors")
    return f"HTTP {refused.status}, {message}" + (f" {errors}" if errors else "")
