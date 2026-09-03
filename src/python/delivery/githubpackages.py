"""Moving a plain FILE in and out of a GitHub Packages registry as an OCI artifact, with `oras`.

WHY A LIBRARY AND NOT A PRODUCT'S BUSINESS. Two products arrived at the same twelve lines within a day
of each other - asbundle publishing its Eclipse bundles, cleon pulling one and republishing a bigger
one - and got them subtly differently: one told the caller how to fix a missing package scope, the other
did not. The mechanics are the same everywhere; only the NAMING is a product's own. So this owns the
mechanics and knows nothing about tags, media types or hosts.

WHY ORAS AND NOT A CONTAINER IMAGE. A container image carries a filesystem for one platform. A macOS or
Windows archive cannot live in a Linux image, and a consumer of one should not need docker to unpack a
zip. `oras` pushes an arbitrary file as an OCI artifact, which a registry stores and serves like any
other package - so one registry holds every platform's archive, distinguished by tag.

THE TOKEN. Actions injects `GITHUB_TOKEN`. Locally, someone already logged in with `gh` should not have
to mint and export a second credential, so `gh auth token` is the fallback. What `gh` does NOT grant is
the package scopes - `gh auth login` asks for gist, read:org, repo and workflow - so the very first
local publish fails with `denied: permission_denied: read_package` and points at the package rather than
at the token. Every failure here says the command that fixes it.
"""
from __future__ import annotations

import os
import shutil
from typing import Sequence

from delivery import log, run

# The scopes `gh auth login` does not request, and every package operation needs.
PACKAGE_SCOPES: tuple = ("read:packages", "write:packages")


class PackageError(RuntimeError):
    """A package operation failed. The message is written to be acted on, not just read."""


def scope_advice(scopes: Sequence[str] = PACKAGE_SCOPES) -> str:
    """The one command that grants a `gh` token the package permissions."""
    return ("`gh auth login` does not request package permissions. Run:\n"
            f"    gh auth refresh -h github.com -s {','.join(scopes)}")


def token() -> str:
    """The GitHub token: the environment first, then `gh`.

    NEVER from a config file. A token committed to one leaked into a product repository's history once,
    and the fix was to leave no field a secret could be written into.
    """
    from_env = os.getenv("GITHUB_TOKEN", "").strip()
    if from_env:
        return from_env

    result = run.run(["gh", "auth", "token"], capture=True)
    if result.rc == 0 and result.out.strip():
        log.info("using the token from `gh auth token` (GITHUB_TOKEN is not set)")
        return result.out.strip()

    raise PackageError(
        "no GitHub token: GITHUB_TOKEN is not set and `gh auth token` did not provide one. "
        "Either export a token or run `gh auth login`. In GitHub Actions it is automatic.")


def require_oras() -> None:
    """Fail with the reason oras is needed, not merely that it is absent."""
    if not shutil.which("oras"):
        raise PackageError(
            "oras is not on PATH. It is what moves a plain file in and out of a registry as an OCI "
            "artifact; a container image cannot carry a macOS or Windows archive. Install it, or add "
            "oras-project/setup-oras to the workflow.")


def reference(registry: str, repository: str, tag: str) -> str:
    """`ghcr.io/owner/repo:tag`, with no doubled or missing slash. Pure."""
    return f"{registry.rstrip('/')}/{repository.strip('/')}:{tag}"


def registry_host(registry: str) -> str:
    """The host to log in to: `ghcr.io` out of `ghcr.io/owner`. Pure."""
    return registry.split("/")[0]


def login(registry: str, *, username: str = "") -> None:
    """Log in to the registry that `registry` names.

    The token goes over STDIN, never as an argv element: argv is world-readable in /proc.

    `username` is ignored by GHCR when the password is a token, but oras requires one; the actor is used
    when the environment names it so a CI log shows who pushed.
    """
    require_oras()
    host = registry_host(registry)
    user = username or os.getenv("GITHUB_ACTOR") or os.getenv("GITHUB_USERNAME") or "x"

    result = run.run(["oras", "login", host, "-u", user, "--password-stdin"],
                     capture=True, input_text=token())
    if result.rc != 0:
        raise PackageError(f"oras login to {host} failed: {result.err or result.out}\n"
                           + scope_advice())


def push(reference_: str, file_path: str, media_type: str) -> None:
    """Push one file as an OCI artifact.

    Run from the file's OWN directory, because oras records the path it is GIVEN as the artifact's
    name: pushing an absolute path bakes the builder's directory layout into the manifest, and a
    consumer then pulls a file named after someone else's machine.
    """
    require_oras()
    directory, filename = os.path.split(os.path.abspath(file_path))
    if not os.path.isfile(file_path):
        raise PackageError(f"nothing to push: {file_path} does not exist")

    log.info(f"pushing {filename} to {reference_}")
    rc = run.stream(["oras", "push", reference_, f"{filename}:{media_type}"], cwd=directory)
    if rc != 0:
        raise PackageError(f"oras push {reference_} failed (rc={rc})\n" + scope_advice())


def pull(reference_: str, destination: str) -> None:
    """Pull an artifact into `destination`, which must already exist."""
    require_oras()
    log.info(f"pulling {reference_}")
    rc = run.stream(["oras", "pull", reference_, "-o", destination])
    if rc != 0:
        raise PackageError(f"oras pull {reference_} failed (rc={rc})\n" + scope_advice())


def tags(registry: str, repository: str) -> list:
    """Every tag in a package repository.

    A failure here has TWO causes that need different fixes, so the message names both: a token without
    the package scopes, or a package that has not granted the calling repository access. GHCR does not
    grant that across repositories in one account automatically, and only the first cause is guessable
    from the error text.
    """
    require_oras()
    result = run.run(["oras", "repo", "tags", f"{registry.rstrip('/')}/{repository.strip('/')}"],
                     capture=True)
    if result.rc != 0:
        raise PackageError(
            f"could not list tags of {repository}: {result.err or result.out}\n"
            + scope_advice() + "\n"
            "If the scopes are right, the package has to grant this repository read access - GHCR "
            "does not do that across repositories in one account automatically.")
    return result.out.split()
