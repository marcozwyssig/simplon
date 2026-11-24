"""`support sources` (si#873): check out the manifest's `sources:` submodules at their pinned commits.

A product that builds from a private submodule declares it (`sources: [{submodule: lib/platform, secret:
PLATFORM_REPO_TOKEN}]`) and this command makes it present, each with its token handed to git by ENVIRONMENT:
`GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0` carry one `url.<authenticated>.insteadOf` rewrite of
`https://github.com/`, so the token is on no command line (`secrets.check_argv` would refuse one) and in no
file. `secrets.read` registers it, so git's own error output is redacted before it is printed.

`GIT_CONFIG_GLOBAL=/dev/null` rides with it, and only on a call that carries a token. Measured (git 2.47.3):
a stale global `url.<wrong>.insteadOf` for the same prefix BEATS the environment's rewrite and the clone
fails; hiding the global file for this one call fixes it without deleting the user's own configuration.
A call with no token keeps the user's configuration, which is what makes a credential helper or an ssh
rewrite work.

AN EMPTY TOKEN. Under GitHub Actions it is refused before git runs: a fork or Dependabot pull request gets
no secrets, and an unauthenticated clone would fail three lines later with "repository not found". Outside
Actions it is not an error, the submodule is updated with the user's own git and the run says so.

KNOWN LIMITS, unmeasured or accepted:
- `GIT_CONFIG_GLOBAL=/dev/null` on a token call also hides a global `safe.directory` (unmeasured: a container job
  whose uid differs from the repo owner).
- The URL check reads `.gitmodules`; an already initialised submodule uses `submodule.<name>.url` from .git/config,
  which a local set-url or sync can make differ.
- A relative `.gitmodules` URL (`../x.git`) with a secret is refused by the prefix check. netctl, the one consumer
  with a private submodule, uses an absolute https://github.com/ URL (measured via the GitHub API 2026-11-24);
  a consumer with a relative URL reopens this.

Every refusal here happens at run time and is a logged diagnosis with a non-zero rc, not a raise, so the census
(which walks what a manifest can reach at load time) has nothing to count; the loader's own reading is
`simplon.manifest.sources`.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from simplon.kernel import log, secrets
from simplon.manifest import context
from simplon.manifest import sources as declared_sources
from simplon.tasks import gitops

#: The prefix a token is useful for, and the rewrite that supplies it. Module-level so a test can aim the
#: rewrite at a local repository while the mechanism stays the production one.
GITHUB = "https://github.com/"
REWRITE = "https://x-access-token:{token}@github.com/"


def git_env(token: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment that gives one git call `token` for GitHub and hides the global configuration.

    The rewrite is appended after any `GIT_CONFIG_*` entries `environ` (this process's by default) already
    carries, the way `gitops.remote_auth` does, so those survive."""
    source = os.environ if environ is None else environ
    at = int(source.get("GIT_CONFIG_COUNT", "0") or "0")
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": str(at + 1),
        f"GIT_CONFIG_KEY_{at}": f"url.{REWRITE.format(token=token)}.insteadOf",
        f"GIT_CONFIG_VALUE_{at}": GITHUB,
    }


def _submodules(root: Path) -> dict[str, str] | None:
    """`.gitmodules` as {path: url}, or None (already reported) when git could not read it."""
    result = gitops.git(root, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$")
    if result.rc not in (0, 1):  # 1: no match, an empty or absent file
        log.error(f"cannot read .gitmodules in {root}: {secrets.redact((result.out + result.err).strip())}")
        return None
    by_name: dict[str, dict[str, str]] = {}
    for line in result.out.splitlines():
        key, _, value = line.partition(" ")
        name, _, field = key[len("submodule."):].rpartition(".")
        by_name.setdefault(name, {})[field] = value
    return {fields["path"]: fields.get("url", "") for fields in by_name.values() if "path" in fields}


def sources_cmd() -> int:
    """Check out every declared source at its pinned commit; 0 when all are present, 1 otherwise."""
    ctx = context.current()
    try:
        declared = declared_sources.declared(ctx.manifest_data())
    except (ValueError, RuntimeError) as exc:  # RuntimeError: an unreadable manifest (context.py)
        log.error(str(exc))
        return 1
    if not declared:
        log.info("the manifest declares no `sources:`; nothing to check out")
        return 0
    known = _submodules(ctx.root)
    if known is None:
        return 1
    failed = 0
    for source in declared:
        if not _checkout(ctx.root, source, known):
            failed += 1
    return 1 if failed else 0


def _checkout(root: Path, source: declared_sources.Source, known: dict[str, str]) -> bool:
    path = source.submodule
    url = known.get(path)
    if url is None:
        have = ", ".join(sorted(known)) or "none"
        log.error(f"sources: '{path}' is not a submodule in .gitmodules (it has: {have}); "
                  f"add it with `git submodule add` or correct `sources:`")
        return False
    token = secrets.read(source.secret) if source.secret else ""
    if source.secret and not token:
        if os.environ.get(secrets.ACTIONS_ENV) == "true":
            log.error(f"sources: '{path}' needs the secret {source.secret} and it is empty. A fork or "
                      f"Dependabot pull request gets no secrets, and so does a repository that never "
                      f"set {source.secret}; the clone would fail unauthenticated")
            return False
        log.info(f"sources: {source.secret} is not set; updating '{path}' with your own git configuration "
                 f"(no token used)")
    if token and not url.startswith(GITHUB):
        log.error(f"sources: '{path}' has the URL {url} and `secret: {source.secret}` is declared, but the "
                  f"token is only applied to URLs starting with {GITHUB}; it would silently go unused")
        return False
    log.info(f"sources: checking out '{path}'" + (" with its token" if token else ""))
    result = gitops.git(root, "submodule", "update", "--init", "--recursive", "--", path,
                        env=git_env(token) if token else None)
    if not result.ok:
        shown = secrets.redact((result.out + result.err).strip())
        log.error(f"sources: git could not check out '{path}' (rc {result.rc}): {shown}")
        return False
    return True
