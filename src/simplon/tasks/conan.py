"""`release:conan` and `build:conan-cache` - a Conan package over GitHub Packages, as a TRANSPORT (si#128).

THE FACT THAT SHAPES THIS MODULE, and the reason it is not a remote: **GitHub Packages has no Conan
registry.** The kinds it serves are npm, RubyGems, Maven, Gradle, NuGet and Docker/Container, and nothing
else. So "Conan packages in GitHub Packages" cannot be built the way si#127's NuGet half is, and the
question is which of the wrong-shaped answers costs least.

THE OPEN QUESTION, MEASURED RATHER THAN ASSUMED. si#128 rests on Conan itself not speaking an OCI remote,
and the ticket does not claim an answer. Measured on 2026-09-09 against the current release:

    $ conan --version
    Conan version 2.32.0
    $ conan remote add --help
      -t {local-recipes-index}, --type {local-recipes-index}   Define the remote type

`local-recipes-index` is the only remote type Conan 2.32.0 accepts. There is no OCI remote, no `oci://`
scheme, no container-registry backend. The transport therefore stands, and what would reopen the
decision is countable: a second value in that list.

WHAT THIS IS, IN THE WORDS A READER NEEDS. `conan cache save` writes the recipes and binaries of a
package list to a `.tgz`; `conan cache restore` reads one back into another cache. This module moves that
file into a registry as an OCI artifact and back out again, using the machinery `githubpackages` already
owns. **It is a transport, not a remote.** There is no `conan install` resolution against the registry,
no version ranges, no dependency graph solved remotely: the consumer names an exact tag, pulls it, and
restores it. A reader who sees "Conan packages in GitHub Packages" will assume a remote and be wrong,
which is why that sentence is in the docs page as well as here.

WHY THE KERNEL DOES NOT RUN CONAN. `conan cache save` and `conan cache restore` are the product's, run
through its own `toolchain:run` commands, against its own cache volume, with its own package pattern.
The kernel moving a file is a transport; the kernel learning a package manager's cache semantics is the
kernel learning a language toolchain, which the design refuses everywhere else. So this module knows the
file's PATH and nothing about its contents.

WHY IT IS NOT `release:artifact` WITH A DIFFERENT MEDIA TYPE. That task publishes a DIRECTORY, and does
it by zipping: a `.tgz` put through it arrives in the registry as a `.zip` holding a `.tgz`, and the
consumer's `conan cache restore` is then handed a file conan cannot read. The failure is silent until the
restore, and the restore is on somebody else's machine. `githubpackages.push` moves the file as it is.

WHY THERE IS NO CREDENTIAL INSIDE A CONTAINER HERE, unlike si#127's NuGet half. The registry
conversation happens entirely on the HOST - oras pushes, oras pulls - and what reaches the container is
a path. The .NET consumer needs the token inside the container because `dotnet restore` is what talks to
the feed. That asymmetry is the design rather than an omission in one of the two.
"""
from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from simplon.domain import artifactsection, artifactschema, context
from simplon.adapters import githubpackages
from simplon.kernel import log

#: The manifest section this module reads, shared with `release:artifact` and si#127's NuGet tasks. No
#: new top-level section (design section 2): a registry, a package and a scope are the same three facts
#: whatever the ecosystem, and a section is cheap to add and expensive to remove.
SECTION = "artifacts"

#: The kind this module reads, read by `build:conan-cache` and `release:conan` (si#344 B2). Its keys, their
#: shapes and what each coordinate needs are the generated schema's.
ENTRY = artifactschema.ConanEntry


def _declared(name: str, coordinate: str) -> artifactschema.ConanEntry:
    """The `artifacts:` entry `name` names, in `simplon.tasks.artifact`'s wording deliberately."""
    if not name:
        raise ValueError(f"which artifact? pin one with `with: {{ name: ... }}` from the `{SECTION}:` "
                         f"section, or pass --name")
    ctx = context.current()
    section = (ctx.manifest_data().get(SECTION) or {})
    if name not in section:
        raise ValueError(
            f"no artifact '{name}' in {ctx.manifest_path.name}'s `{SECTION}:` section; declared are: "
            f"{', '.join(sorted(section)) or '(none)'}")
    return artifactsection.entry(section, name, ENTRY, ctx.manifest_path.name, coordinate)


def _reference(name: str, tag: str, coordinate: str) -> tuple[str, str, Path, str]:
    """The registry, the full reference, the archive path and the media type - everything both verbs need.

    One reader for both, because a publish and a fetch that disagreed about where the file lives would be a
    transport whose two ends do not meet, and that failure shows up only on the consumer's machine. What
    each verb NEEDS is the model's (si#344 B2): both need registry, repository, media_type and path.
    """
    spec = _declared(name, coordinate)
    resolved = tag or spec.tag or ""
    if not resolved:
        raise ValueError(
            f"artifact '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant "
            f"one, or pass --tag for a version that is only known after a build")
    registry = spec.registry or ""
    return (registry, githubpackages.reference(registry, spec.repository or "", resolved),
            context.current().root / (spec.path or ""), spec.media_type or "")


def _scope(registry: str) -> AbstractContextManager[object]:
    """The credential scope a transfer runs in (si#443): a fresh one where this task logs in with a GitHub
    token, and the caller's own config elsewhere - there the transfer uses the login the operator stored,
    which a scope would hide."""
    return githubpackages.scoped_credentials() if githubpackages.is_github_packages(registry) else nullcontext()


def _login_if_githubs(registry: str) -> None:
    """Log in only where the credential may go, and say out loud when it does not.

    A GITHUB token goes to GITHUB and nowhere else: `registry:` is a manifest key, so a product writing
    `registry: registry.example.com/team` would otherwise have a PAT minted and handed to a third party.
    The wording and the shape are `tasks/image.py`'s, which is the caller that already pays this check.
    """
    if githubpackages.is_github_packages(registry):
        githubpackages.login(registry)
        return
    host = githubpackages.registry_host(registry)
    log.info(f"{host} is not GitHub Packages, so no GitHub token is minted for it - the transfer uses "
             f"the credential `oras login {host}` has already stored")


def publish(name: str = "", tag: str = "") -> int:
    """Push the conan cache archive `name` declares, under `tag`, as an OCI artifact.

    The archive is the PRODUCT's: it is written by its own `conan cache save`, in its own container,
    against its own cache. This moves it.
    """
    registry, ref, archive, media_type = _reference(name, tag, "release:conan")
    if not archive.is_file():
        raise ValueError(
            f"nothing to publish: {archive} does not exist. The archive is written by the product's own "
            f"`conan cache save --file <path> '<pattern>'`, not by this task - this only moves it")

    # si#443: a login made here lives as long as this push, not in the runner's own docker config.
    with _scope(registry):
        _login_if_githubs(registry)
        githubpackages.push(ref, str(archive), media_type)
    log.ok(f"published {ref}\n"
           "    this is a TRANSPORT, not a remote: a consumer names this exact tag, pulls it and runs "
           "`conan cache restore`. There is no remote resolution and no version range.")
    return 0


def fetch(name: str = "", tag: str = "") -> int:
    """Pull the archive `name` declares back to the path the manifest gives it.

    The path is what the next command needs (`conan cache restore <path>`), so it is what the success
    line says. The file is then LOOKED FOR rather than assumed: a step that reports rc 0 and leaves
    nothing behind is a defect this repository has shipped twice, and a pull is not different in kind
    from a render.
    """
    registry, ref, archive, _ = _reference(name, tag, "build:conan-cache")
    archive.parent.mkdir(parents=True, exist_ok=True)
    # si#443: a login made here lives as long as this pull, not in the runner's own docker config.
    with _scope(registry):
        _login_if_githubs(registry)
        githubpackages.pull(ref, str(archive.parent))
    if not archive.is_file():
        raise RuntimeError(
            f"the pull of {ref} reported success and left no {archive.name} in {archive.parent}. Either "
            f"the artifact holds a differently named file or nothing was written; the manifest's "
            f"`path:` is what names the file this expects")

    root = context.current().root
    shown = archive.relative_to(root) if archive.is_relative_to(root) else archive
    log.ok(f"fetched {ref} -> {shown}\n"
           f"    restore it with the product's own toolchain command: `conan cache restore {shown}`")
    return 0
