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

WHERE IT READS FROM. The platform's reference this checkout's `build:image` recorded (`read_built`), held by
the daemon as `platform_reference`. It never pulls: a platform this checkout did not build is a refusal that
names the build, not a silent copy of something older.

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

from simplon.adapters import docker
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
    # Not `_platform_declared`'s first message: it tells a command to "drop `platform:`", and a file entry's
    # `platform:` is required here.
    if not cfg.platforms:
        log.error(f"image '{name}' declares no `platforms:`, so it has no per-platform build to copy "
                  f"{platform}'s file out of. Declare `platforms:` on `{SECTION}.{name}`, with {platform} "
                  f"among them")
        return 1
    if not image._platform_declared(cfg, name, platform):
        return 1
    if not inside.startswith("/"):
        log.error(f"`inside:` is {inside!r}; give the file's absolute path inside the image, e.g. /usr/bin/firn")
        return 1
    docker.ensure_docker()
    source = _built_reference(cfg, name, tag, platform, root)
    if source is None:
        return 1
    image_id = image.local_id(source)
    if not copy_out(source, inside, root / str(entry.path)):
        return 1
    log.ok(f"copied {inside} out of {source} ({image_id or 'its id could not be read'}) to {entry.path}")
    return 0


def _built_reference(cfg: image.Image, name: str, tag: str, platform: str, root: Path) -> str | None:
    """The daemon reference this checkout's `build:image` loaded `platform` under, or None after saying why.

    The tag is resolved the way `build:image` and `test:image` resolve it, so the three cannot name three
    references."""
    resolved = image.resolve_tag(cfg, tag, image.build_arguments(cfg, root).get(image.VERSION_ARG, ""))
    ref = image.reference(cfg, resolved)
    source = image.platform_reference(ref, platform)
    if platform not in image.read_built(name, ref) or not image.present_locally(source):
        log.error(f"this checkout has no build of image '{name}' for {platform} under {ref}, so there is "
                  f"nothing to copy out of; nothing was pulled.\n"
                  f"  build it first: `build:image` with `with: {{ name: {name} }}` and the same tag")
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
