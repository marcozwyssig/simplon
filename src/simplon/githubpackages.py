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
import zipfile
from pathlib import Path
from typing import Sequence

from simplon import log, oras, run

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
    """oras, PROVIDED rather than merely demanded - see simplon.oras for how.

    This used to raise "oras is not on PATH" with an install instruction, which is a correct message and
    a stopped build: the tool is one every package operation in the family needs, and no host ships it.
    The gate installs it (package manager first, pinned release as the fallback) and only fails when
    even that could not produce one. The failure is translated into this module's own error type,
    because PackageError is the contract every caller here catches on.
    """
    try:
        oras.ensure_oras()
    except oras.OrasError as failure:
        raise PackageError(str(failure)) from failure


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


# --- a DIRECTORY as an artifact ---------------------------------------------------------------------
#
# `push` and `pull` move a FILE, which is the registry's own shape. What products actually publish is
# usually a DIRECTORY - a p2 update site, a rendered website, a folder of jars - so each of them zipped
# it first, pulled and unzipped on the way back, and answered "which of these files is the archive"
# themselves. That is the same six lines in every product and one place they can each get subtly
# different, which is the argument this module was created with.


def newest_tag(registry: str, repository: str) -> str:
    """The most recently published tag of a package.

    `oras repo tags` lists OLDEST FIRST, so the answer is the last line - a fact about someone else's
    tool that was living in a shell pipeline in a workflow, where nothing tests it.
    """
    published = tags(registry, repository)
    if not published:
        raise PackageError(
            f"{repository} has no tags in {registry}: there is nothing published to fetch. Publish one "
            f"first, or check the name - a package that does not exist and one that is empty look the "
            f"same from here.")
    return published[-1]


def push_directory(reference_: str, directory: Path | str, media_type: str,
                   *, archive_dir: Path | None = None) -> Path:
    """Zip `directory` and push the archive as an OCI artifact; returns the archive that was pushed.

    The archive is named after the directory, beside it by default, because the name is what a consumer
    sees after pulling: `site.zip` out of `site/` says what it holds, and a temporary name does not.
    """
    source = Path(directory)
    if not source.is_dir():
        raise PackageError(f"nothing to publish: {source} is not a directory")
    target_dir = Path(archive_dir) if archive_dir else source.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / f"{source.name}.zip"
    # Rebuilt every time: the archive IS the directory, and a stale one would publish one version's
    # number over another version's content.
    archive.unlink(missing_ok=True)
    shutil.make_archive(str(archive)[: -len(".zip")], "zip", source)
    push(reference_, str(archive), media_type)
    return archive


def fetch_directory(reference_: str, destination: Path | str) -> Path:
    """Pull an artifact published with `push_directory` and unpack it into `destination`.

    The pulled archive's name is the publisher's business, not the consumer's, so this finds it rather
    than making the caller guess: exactly one zip is expected, and anything else is said out loud.
    """
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    scratch = target / ".pull"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        pull(reference_, str(scratch))
        archives = sorted(scratch.glob("*.zip"))
        if len(archives) != 1:
            raise PackageError(
                f"expected exactly one archive in {reference_}, found "
                f"{[a.name for a in archives] or 'none'}")
        with zipfile.ZipFile(archives[0]) as content:
            content.extractall(target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return target
