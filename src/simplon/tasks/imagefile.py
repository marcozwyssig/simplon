"""`build:image-file` - one file out of an image, for the platform its file entry names (si#552).

WHAT IT IS FOR. A product that ships a binary builds it inside its image, where its toolchain is pinned, and
then wants the bare file too - firn's release hands out `firn-linux-amd64` and `firn-linux-arm64`. Without
this task each product writes the same `docker create` / `docker cp` / `docker rm` lines itself, picks the
platform by hand, and forgets the `rm`. Here it is one coordinate: the image entry says what was built, the
`kind: file` entry says where the file goes AND FOR WHICH PLATFORM (`platform:`, decided by Marco on si#552:
one entry per platform, so a miswired platform is refused here instead of surfacing as `exec format error`).

WHY BESIDE `tasks.image` AND NOT IN IT. `image.py` is the image's own three verbs - build, smoke, release -
and already the longest module in the kernel. This one READS an image and WRITES a file entry: it uses
`image`'s declarations and references unchanged and adds nothing they need. Kept apart, the file side of
si#552 (this task and `test:file`) has one home and `image.py` does not grow a second subject.

WHERE IT READS FROM. Without `tag`: the platform's reference this checkout's `build:image` recorded
(`read_built`), held by the daemon as `platform_reference`. It never pulls then: a platform this checkout did
not build is a refusal that names the build, not a silent copy of something older. With `tag`: the PUBLISHED
image - the registry's multi-platform index is read with `oras manifest fetch`, and the platform's own manifest
is pulled by digest, `<repository>@<digest>`, so the bytes are the ones the registry serves for that platform
whatever the daemon holds under the tag. No credential is demanded before the registry is asked: a public
image pulls anonymously. A tag this host cannot read (absent, or not readable without a login), a single
manifest and an index without the platform are refusals; none of them falls back to a local build.

THE COPY LEAVES A REGULAR FILE OR NOTHING. `docker cp -L` follows a symlink (a measured `/link ->
/bin/busybox` arrives as the file); a directory arrives as a directory and is refused, and a symlink to
nothing or an absent path is docker's own `Could not find the file` (both measured 2026-10-28). The bytes land
beside `path` under a staging name and are renamed into place only once they are a regular file, mode 0755.
The container is removed whatever the copy said.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from simplon.adapters import docker, githubpackages
from simplon.kernel import log
from simplon.kernel.run import run
from simplon.manifest import artifactsection, context
from simplon.manifest.layout import validate_relative_dir
from simplon.model import artifactschema
from simplon.tasks import image

#: The manifest section this module reads.
SECTION = "artifacts"

COORDINATE = "build:image-file"

#: The kind `name` binds - the image read from, through `tasks.image`'s own reader. `test_generated_schema.py`
#: holds it to the model's READERS.
ENTRY = artifactschema.ImageEntry

#: The kind the `file` param binds: the entry written, and the one that names the platform.
FILE_ENTRY = artifactschema.FileEntry

#: The suffix the copied bytes carry until they are known to be a regular file.
STAGING = ".partial"

#: The command `docker create` is given and never runs: the container is only copied out of, and an image
#: with neither CMD nor ENTRYPOINT (a `FROM scratch` stage holding one binary) is refused by `docker create`
#: with "no command specified" without one (measured 2026-10-28).
NEVER_STARTED = "simplon-copy-only"


def file_entry(name: str, coordinate: str) -> tuple[artifactschema.FileEntry, Path]:
    """The `kind: file` entry `name` (bound through the `file` param of `coordinate`) with its `path`
    validated, and the product root; a ValueError names a missing entry, a wrong kind or a bad path."""
    if not name:
        raise ValueError(f"which file? bind one with `produces: {{ file: ... }}` from the `{SECTION}:` "
                         f"section, or pass --file")
    ctx = context.current()
    section = ctx.manifest_data().get(SECTION)
    section = section if isinstance(section, Mapping) else {}
    source = ctx.manifest_path.name
    if name not in section:
        raise ValueError(f"{source}: no artifact '{name}' in the `{SECTION}:` section; declared are: "
                         f"{', '.join(sorted(str(k) for k in section)) or '(none)'}")
    entry = artifactsection.entry(section, name, FILE_ENTRY, source, coordinate, param="file")
    # `or ""` is for the type checker: every coordinate that reads a file entry NEEDS `path`.
    path = validate_relative_dir(entry.path or "", f"{source}: '{SECTION}.{name}': 'path'",
                                 "give the file's path under the product root, e.g. 'build/firn-linux-amd64'",
                                 inside="the product root")
    return entry.model_copy(update={"path": path}), ctx.root


def extract(name: str = "", file: str = "", inside: str = "", tag: str = "") -> int:
    """Copy `inside` out of the image `name` declares, for the platform the file entry `file` names, to that
    entry's `path`, mode 0755.

    The platform is the FILE ENTRY's `platform:` and nothing else: there is no `platform` param, so one
    command cannot write one platform's bytes under another platform's entry.
    """
    cfg, root = image._declared_for(name, COORDINATE)
    entry, _ = file_entry(file, COORDINATE)
    platform = entry.platform or ""
    # Every refusal below is answered before docker is asked: each one is about the manifest.
    if not platform:
        choices = ", ".join(cfg.platforms) or f"the `platforms:` image '{name}' declares"
        log.error(f"file '{file}' declares no `platform:`, and {COORDINATE} copies one platform's file. Add "
                  f"`platform:` to `{SECTION}.{file}` - one of {choices} - and declare one file entry per "
                  f"platform")
        return 1
    # Not `_platform_declared`: its first message tells a command to "drop `platform:`", which a file entry
    # cannot, and its second names neither the file entry at fault nor a way out.
    if not cfg.platforms:
        log.error(f"image '{name}' declares no `platforms:`, so it has no per-platform build to copy "
                  f"{platform}'s file out of. Declare `platforms:` on `{SECTION}.{name}`, with {platform} "
                  f"among them")
        return 1
    if platform not in cfg.platforms:
        log.error(f"`{SECTION}.{file}.platform` is {platform}, and image '{name}' is not built for it; its "
                  f"declared platforms are {', '.join(cfg.platforms)}. Change the file entry's `platform:` "
                  f"to one of them, or add {platform} to `platforms:` on `{SECTION}.{name}`")
        return 1
    if not inside.startswith("/"):
        log.error(f"`inside:` is {inside!r}; give the file's absolute path inside the image, e.g. /usr/bin/firn")
        return 1
    docker.ensure_docker()
    if tag:
        return _copy_published(cfg, tag, platform, inside, str(entry.path), root)
    source = _built_reference(cfg, name, platform, root)
    if source is None:
        return 1
    return _copy(source, inside, str(entry.path), root)


def _copy(source: str, inside: str, path: str, root: Path) -> int:
    """`copy_out` from the daemon's `source` to the entry's `path`, naming the image id it copied from."""
    image_id = image.local_id(source)
    if not copy_out(source, inside, root / path):
        return 1
    log.ok(f"copied {inside} out of {source} ({image_id or 'its id could not be read'}) to {path}")
    return 0


def _copy_published(cfg: image.Image, tag: str, platform: str, inside: str, path: str, root: Path) -> int:
    """The published image's `platform` manifest, pulled by digest and copied from.

    NOTHING REFUSES FOR WANT OF A CREDENTIAL BEFORE THE REGISTRY IS ASKED: a public image pulls anonymously,
    and a push's precondition (`release:image` checks for a stored login) would turn that into a refusal of
    something that works. Only a failed fetch or pull refuses, and its message names the login as one way out.

    For GitHub Packages a token is minted, when there is one, into a docker config that ends with the block
    (si#443); the index read, the pull AND the `docker create` all happen inside it, so no credential
    outlives the command. Without a token the same block goes on anonymously. For any other host no GitHub
    token is minted (si#200), and the block is not entered: the scope keeps no credential of the caller's,
    so it would drop exactly the `docker login` the operator stored for that host.
    """
    try:
        githubpackages.require_oras()
    except githubpackages.PackageError as failure:
        log.error(f"the published index of {image.reference(cfg, tag)} cannot be read, so nothing was "
                  f"pulled: {failure}")
        return 1
    if not githubpackages.is_github_packages(cfg.registry):
        return _pull_and_copy(cfg, tag, platform, inside, path, root)
    with githubpackages.scoped_credentials():
        try:
            githubpackages.docker_login(cfg.registry)
        except githubpackages.PackageError as failure:
            log.warn(f"reading {image.reference(cfg, tag)} without a login, which a public package allows: "
                     f"{failure}")
        return _pull_and_copy(cfg, tag, platform, inside, path, root)


def _login_advice(cfg: image.Image) -> str:
    """The credential that lets this host read `cfg`'s registry: the GitHub token for GitHub Packages (a
    stored `docker login` is not read inside the scope), the operator's `docker login` for any other."""
    if githubpackages.is_github_packages(cfg.registry):
        return (f"a GitHub token that may read the package - set GITHUB_TOKEN or run `gh auth login`; "
                f"{githubpackages.scope_advice()}")
    return f"`docker login {githubpackages.registry_host(cfg.registry)}`"


def _pull_and_copy(cfg: image.Image, tag: str, platform: str, inside: str, path: str, root: Path) -> int:
    """Resolve, pull and copy from `platform`'s published manifest, in whatever credential scope the caller
    holds."""
    source = published_reference(cfg, tag, platform)
    if source is None:
        return 1
    pulled = run(["docker", "pull", source])
    if not pulled.ok:
        log.error(f"`docker pull {source}` failed, so nothing was copied: "
                  f"{(pulled.err or pulled.out).strip() or '(it said nothing)'}.\n"
                  f"  if the registry needs a login: {_login_advice(cfg)}")
        return 1
    return _copy(source, inside, path, root)


def published_reference(cfg: image.Image, tag: str, platform: str) -> str | None:
    """`<registry>/<repository>@<digest>` of `platform`'s manifest in the index the registry serves under
    `tag`, or None after saying why.

    A failed fetch is never read as "no index". From here an absent tag and a refused read look alike (a
    registry may answer either way for a package this host may not see), so the message names both, with
    oras's own words and the login that would let this host read it. A published `linux/arm64/v8` answers for a declared
    `linux/arm64`, as in `image.missing_platforms`.
    """
    ref = image.reference(cfg, tag)
    fetched = run(["oras", "manifest", "fetch", ref])
    if not fetched.ok:
        log.error(f"{ref} could not be read from the registry, so nothing was pulled: "
                  f"{(fetched.err or fetched.out).strip() or '(oras said nothing)'}.\n"
                  f"  either it is not published: publish it (`release:image` with the same tag), or drop "
                  f"`tag` to copy from this checkout's build;\n"
                  f"  or this host may not read it: if the registry needs a login: {_login_advice(cfg)}")
        return None
    manifests = image.index_manifests(fetched.out)
    if manifests is None:
        log.error(f"{ref} is published as a single manifest, not a multi-platform index, so it has no "
                  f"{platform} manifest to pull by digest; publish it from an image entry with "
                  f"`platforms:` (`release:image`)")
        return None
    if image.missing_platforms([platform], manifests):
        log.error(f"{ref} is published without {platform}: its index carries "
                  f"{', '.join(sorted(manifests)) or 'no platform at all'}. Publish {ref} for {platform} "
                  f"(`release:image`), or copy for a platform the index carries")
        return None
    digest = manifests.get(platform) or next((digest for found, digest in sorted(manifests.items())
                                              if found.startswith(platform + "/")), "")
    return f"{cfg.registry.rstrip('/')}/{cfg.repository.strip('/')}@{digest}"


def _built_reference(cfg: image.Image, name: str, platform: str, root: Path) -> str | None:
    """The daemon reference this checkout's `build:image` loaded `platform` under, or None after saying why.

    The tag is resolved the way `build:image` and `test:image` resolve it without one, so the three cannot
    name three references."""
    resolved = image.resolve_tag(cfg, "", image.build_arguments(cfg, root).get(image.VERSION_ARG, ""))
    ref = image.reference(cfg, resolved)
    source = image.platform_reference(ref, platform)
    if platform not in image.read_built(name, ref) or not image.present_locally(source):
        log.error(f"this checkout has no build of image '{name}' for {platform} under {ref}, so there is "
                  f"nothing to copy out of; nothing was pulled.\n"
                  f"  build it first: `build:image` with `with: {{ name: {name} }}`")
        return None
    return source


def copy_out(reference: str, inside: str, dest: Path) -> bool:
    """Copy the regular file `inside` out of the daemon's `reference` to `dest`, mode 0755, or say why not.

    `dest` holds the new bytes or is left as it was: they land at `<dest>.partial` first and replace `dest`
    only once they are a regular file. The container is NAMED before it is created, so an interrupt between
    the create and the rm still removes it (si#416, `docker.stopped_on_interrupt`).
    """
    staged = dest.with_name(dest.name + STAGING)
    _remove(staged)
    dest.parent.mkdir(parents=True, exist_ok=True)
    container, lifecycle = docker.lifecycle()
    with docker.stopped_on_interrupt(container):
        created = run(["docker", "create", *lifecycle, reference, NEVER_STARTED])
        if not created.ok:
            log.error(f"`docker create {reference}` failed, so nothing was copied: "
                      f"{(created.err or created.out).strip() or '(it said nothing)'}")
            return False
        try:
            # `-L`: a symlink in the image is followed to the file it names.
            copied = run(["docker", "cp", "-L", f"{container}:{inside}", str(staged)])
        finally:
            run(["docker", "rm", container])
    if not copied.ok:
        _remove(staged)
        log.error(f"copying {inside} out of {reference} failed, so nothing was written to {dest}: "
                  f"{(copied.err or copied.out).strip() or '(it said nothing)'}")
        return False
    if staged.is_symlink() or not staged.is_file():
        _remove(staged)
        log.error(f"{inside} in {reference} is not a regular file (a directory?), so nothing was written to "
                  f"{dest}; name the file itself with `inside:`")
        return False
    staged.chmod(0o755)
    os.replace(staged, dest)
    return True


def _remove(path: Path) -> None:
    """Remove whatever is at `path` - a file, a symlink or a directory a `docker cp` made - if anything is."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
