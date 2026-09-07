"""`release:asset` - attach declared FILES to a GitHub release.

THE OTHER HALF OF `release:artifact`. That one publishes a directory to a registry, where a consuming
BUILD pulls it with its own token; this one attaches files to a release, where a PERSON downloads them
from a page. Same act, different reader, and the choice between them is the product's to make - a
private repository can offer both, a public one has to decide what its licence lets it hand out.

WHY `gh` AND NOT A GITHUB CLIENT. The mechanics a publisher needs here are two: create the release if
nobody has yet, and replace an asset that is already there. `gh release create` and `gh release upload
--clobber` are exactly those two, and the alternative measured against them - asbundle's
PublishReleaseCommand - hand-rolls each in twenty lines of PyGithub plus a content-type table. A GitHub
client in the KERNEL's dependencies is not twenty lines: `pyproject.toml` says why a published
package's constraints are its consumers' constraints forever, and the token story `gh` already has is
the same two sources `githubpackages.token` documents.

WHAT IT DOES NOT DO: decide the version, name the files, or say which repository they belong to when the
product has not. Those are the product's, and they arrive through the manifest's `assets:` section.
"""
from __future__ import annotations

import shutil

from simplon import context, log, run

SECTION = "assets"


def _declared(name: str) -> dict:
    ctx = context.current()
    section = (ctx.manifest_data().get(SECTION) or {})
    if name not in section:
        raise ValueError(
            f"no asset '{name}' in {ctx.manifest_path.name}'s `{SECTION}:` section; declared are: "
            f"{', '.join(sorted(section)) or '(none)'}")
    return dict(section[name])


def _said(result: run.Result) -> str:
    """What `gh` reported, from whichever stream carried it."""
    return result.err.strip() or result.out.strip() or f"rc {result.rc}"


def _already_there(result: run.Result) -> bool:
    """Whether a failed create means someone else already made this release."""
    return "already exists" in f"{result.err} {result.out}".lower()


def publish(name: str = "", tag: str = "") -> int:
    """Attach the files `name` declares to the release for `tag`."""
    if not name:
        raise ValueError(f"which asset? pin one with `with: {{ name: ... }}` from the `{SECTION}:` "
                         f"section, or pass --name")
    if shutil.which("gh") is None:
        log.die("missing required tool: gh")

    spec = _declared(name)
    root = context.current().root
    source = spec.get("source", "")

    resolved = tag or spec.get("tag", "")
    if not resolved:
        raise ValueError(
            f"asset '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant one, "
            f"or pass --tag for a version that is only known after a build")

    # A `--repo` that reached only some of the calls would create the release in one repository and look
    # for it in another, so it is built once and appended to every argv.
    repository = spec.get("repository", "")
    where = ["--repo", repository] if repository else []

    files = sorted(root.glob(source))
    if not files:
        raise ValueError(f"nothing to publish: {source} matches no file under the product root. "
                         f"the assets are built by the product, not by this task")

    # `--notes` ALWAYS, declared or empty. Without it `gh` opens an editor where it has a terminal and
    # refuses where it does not, so a cell would hang or fail on a flag the manifest never mentioned.
    told = ["--title", spec.get("title", "") or resolved, "--notes", spec.get("notes", "")]

    created = run.run(["gh", "release", "create", resolved, *told, *where])
    if not created.ok and not _already_there(created):
        raise RuntimeError(f"could not create release {resolved}: {_said(created)}")

    uploaded = run.run(["gh", "release", "upload", resolved,
                        *[str(f) for f in files], "--clobber", *where])
    if not uploaded.ok:
        raise RuntimeError(f"could not attach to release {resolved}: {_said(uploaded)}")

    log.ok(f"published {len(files)} asset(s) to release {resolved}")
    return 0
