"""`release:artifact` - publish a declared DIRECTORY to a registry as an OCI artifact.

WHY THIS IS THE KERNEL'S. Three products publish folders: cleon its p2 update site, asbundle its
bundles, and any product that ships a rendered site could. Each was writing the same sequence - zip the
directory, log in, push it under a tag - and each could get it subtly different, which is the argument
`githubpackages` was created with in the first place. The mechanics belong here; what stays the
product's is DATA, and all of it arrives through the manifest's `artifacts:` section.

WHY THE TAG MAY COME FROM EITHER SIDE. Most products know their tag as a constant ("latest", a release
number in the manifest). cleon does not: its version is generated INTO a feature jar by the model and is
only readable after a build, so a manifest key could not hold it. The task therefore takes `--tag`, and
falls back to the section's own `tag:`. A task that only supported the manifest would have excluded the
product that asked for this.

WHAT IT DOES NOT DO: decide the version, name the media type, or know what a p2 repository is. Those are
the product's, and a kernel task guessing any of them would be simplon's layout imposed on everyone.
"""
from __future__ import annotations

from pathlib import Path

from simplon import context, githubpackages, log

#: The manifest section this task reads: a mapping of NAME -> the four things publishing a directory
#: needs. A section rather than flat keys, because a product may publish several.
SECTION = "artifacts"


def _declared(name: str) -> dict:
    ctx = context.current()
    section = (ctx.manifest_data().get(SECTION) or {})
    if name not in section:
        raise ValueError(
            f"no artifact '{name}' in {ctx.manifest_path.name}'s `{SECTION}:` section; declared are: "
            f"{', '.join(sorted(section)) or '(none)'}")
    return dict(section[name])


def publish(name: str = "", tag: str = "") -> int:
    """Publish the artifact `name` declares, under `tag`.

    `name` is normally pinned per command with `with: { name: ... }`, the same shape `test:gate` uses -
    a product with two artefacts declares two commands rather than making the caller remember a string.
    """
    if not name:
        raise ValueError(f"which artifact? pin one with `with: {{ name: ... }}` from the `{SECTION}:` "
                         f"section, or pass --name")
    spec = _declared(name)
    root = context.current().root

    registry, repository = spec.get("registry", ""), spec.get("repository", "")
    media_type, source = spec.get("media_type", ""), spec.get("source", "")
    for key, value in (("registry", registry), ("repository", repository),
                       ("media_type", media_type), ("source", source)):
        if not value:
            raise ValueError(f"artifact '{name}' declares no `{key}:`; publishing needs all four of "
                             f"registry, repository, source and media_type")

    resolved = tag or spec.get("tag", "")
    if not resolved:
        raise ValueError(
            f"artifact '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant "
            f"one, or pass --tag for a version that is only known after a build")

    directory = root / source
    if not directory.is_dir():
        raise ValueError(f"nothing to publish: {source} does not exist under the product root. "
                         f"the artifact is built by the product, not by this task")

    githubpackages.login(registry)
    reference = githubpackages.reference(registry, repository, resolved)
    githubpackages.push_directory(reference, directory, media_type)
    log.ok(f"published {reference}")
    return 0
