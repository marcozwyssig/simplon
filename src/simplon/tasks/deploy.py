"""The deploy commands the kernel owns (si#235).

ONE SHAPE FOR EVERY PRODUCT, and the axis is what the product IS rather than what it is written in: a
CLIENT application is installed into a directory on this machine, a SERVER application is brought up on a
target through the product's own backend. Both name the version they are deploying, in the same three
words (`1.4.0`, `latest`, `local`), and `simplon.manifest.deployment` is where that vocabulary lives.

WHAT IS OUT OF SCOPE, stated here because it is the half somebody will assume is coming. `client` means
installing a version HERE. Distributing one to a FLEET - an SCCM, an MDM, a software deployment server -
is not Simplon's business and is not what these commands grow into. A product that needs it drives its
own tool, with this vocabulary in front of it.

THE SERVER PATH DISPATCHES ON NOTHING, which is the whole of `simplon.adapters.backend`'s design: the product
registers one implementation per backend tag and the kernel resolves the environment to an instance. What
si#235 added there is a REGISTRATION seam, because a catalogue task is called by the CLI with
manifest-pinned parameters and nothing else - it cannot be handed a registry as an argument the way
`backend.resolve` is.

THIS MODULE NOW NAMES ONE BACKEND, and the sentence above used to say it named none. si#5 made
`backend: portainer` work with no product code at all, because the whole chain under it is the kernel's
own - `deploy carrier` builds the Portainer and `carriers:` describes it. `_backends` is where that is
said out loud, in one place, merged UNDER whatever the product registered. `simplon.adapters.backend` itself still
names nobody: the seam is unchanged, it simply arrives with something in it.

THE CLIENT PATH INSTALLS INTO `into/<version>`, one directory per version rather than one directory
overwritten. Two reasons, and neither is tidiness: a rollback is then a second `up` rather than a
re-fetch, and `down` has something exact to remove instead of a directory it has to guess the contents of.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from simplon.adapters import backend, devcontainer, githubpackages, portainer
from simplon.manifest import context, deployment, environments
from simplon.kernel import log
from simplon.model import artifactschema, carrierspec
from simplon.tasks import image


def drivable_backends() -> dict[str, backend.Backend]:
    """Every backend this run may resolve: the ones the kernel ships, with the product's own on top.

    THE ORDER IS THE DECISION. A product's registration wins on a name collision, because a product that
    writes its own `portainer` backend has a reason the kernel cannot know - and the alternative, refusing
    the collision, would mean the kernel shipping a backend could break a product that already had one.
    The kernel ships TWO: `portainer` (si#5) and `devcontainer` (si#308). Both are here for one reason rather
    than two - the chain underneath each is already the kernel's, so a product writing them would be
    writing the far end of a pipe the kernel owns both ends of. Everything else is still the product's
    to register.
    """
    shipped: dict[str, backend.Backend] = {
        portainer.BACKEND: portainer.PortainerBackend(),
        devcontainer.BACKEND: devcontainer.DevcontainerBackend(),
    }
    return {**shipped, **backend.product_registry()}


def _environment() -> environments.Environment:
    """The environment this deployment targets, resolved the way the CLI resolved it.

    The name comes off `context.ENVIRONMENT_ENV`, which `cli.main` writes for exactly this reason - its
    own comment says the product's variable arrives through an injected provider, "so no kernel leaf can
    read the answer back out of it". This is such a leaf.

    THE MATRIX IS PARSED AGAINST WHAT IT ITSELF DECLARES, not against the resolvable set, and si#298 is
    why. Parsing against the resolvable set made `parse_data` the refusal a person met:

        environment 'dev': backend must be 'portainer', got 'local'

    That names a REQUIREMENT where the cause is a MISSING REGISTRATION. It reads as though the matrix is
    misconfigured and sends the reader to the `environments:` section, while what is missing is a
    `backend.register` call in the composition root. The consumer who hit it put it exactly right: it
    sends you to the wrong neighbour.

    `backend.resolve` already has the sentence that fits - "no backend registered for 'local' (known:
    portainer)" - and it could not be reached, because this line refused first. Now it is reached.
    """
    matrix = environments.parse_data(context.current().manifest_data())
    name = os.environ.get(context.ENVIRONMENT_ENV, "").strip() or matrix.default
    env = matrix.environments.get(name)
    if env is None:
        raise ValueError(
            f"environment '{name}' is not in this manifest's `environments:` section; it declares: "
            f"{', '.join(sorted(matrix.environments)) or '(none)'}")
    return env


def _install_root(source: deployment.Source, version: deployment.Version) -> Path:
    return Path(source.into).expanduser() / version.tag


def _refuse_a_local_client(version: deployment.Version) -> None:
    """`local` on a client is refused rather than half-answered.

    Installing a published version is a fetch; installing the current code base would be a copy out of a
    build directory this task cannot name, because where a product's build lands is the product's own
    business. Refusing says that in one sentence. Answering it by fetching the newest published version
    instead would be the defect this whole ticket removes, one command later.
    """
    if version.builds:
        raise ValueError(
            f"`{deployment.LOCAL}` installs the current code base, and a client install fetches a "
            f"PUBLISHED version - this task cannot know where your build lands. Publish it and deploy "
            f"that version, or install it yourself")


def _newest(source: deployment.Source) -> str:
    """The newest published tag. Its own module records the fact this rests on - `oras repo tags` lists
    oldest first - so that fact stays in one place."""
    return githubpackages.newest_tag(source.registry, source.repository)


def _serves(source: deployment.Source, tag: str) -> bool:
    """Whether the registry really serves this reference.

    The same read-back `release:image` makes a push a publish with, asked before a deployment instead of
    after one: a version that is not there is a fact available in one call, and finding it out in the
    middle of a rollout costs an environment.
    """
    return image.published(f"{source.reference}:{tag}")


def up(version: str = "") -> int:
    """Deploy `version` - `1.4.0`, `latest`, or `local` for the current code base."""
    source = deployment.declared()
    resolved = deployment.resolve(version, source, newest=_newest, serves=_serves)
    if source.application == deployment.CLIENT:
        _refuse_a_local_client(resolved)
        target = _install_root(source, resolved)
        log.info(f"installing {source.reference}:{resolved.tag} into {target}")
        githubpackages.fetch_directory(f"{source.reference}:{resolved.tag}", target)
        log.ok(f"{resolved.tag} is installed in {target}")
        return 0
    env = _environment()
    log.info(f"deploying {resolved.tag} to {env.name} ({env.backend})")
    return backend.resolve(env, drivable_backends()).deploy(env, resolved)


def down(version: str = "") -> int:
    """Remove a deployment - a client's installed `version`, or a server's environment.

    A client needs the version because `up` installed one directory per version: removing "the
    deployment" without saying which would mean guessing which of them somebody meant.
    """
    source = deployment.declared()
    if source.application == deployment.CLIENT:
        resolved = deployment.resolve(version, source, newest=_newest, serves=_serves)
        _refuse_a_local_client(resolved)
        target = _install_root(source, resolved)
        if not target.is_dir():
            raise ValueError(
                f"{target} is not there, so nothing was removed. Installed versions are the directories "
                f"under {Path(source.into).expanduser()}")
        shutil.rmtree(target)
        log.ok(f"{resolved.tag} is removed from {target}")
        return 0
    env = _environment()
    log.info(f"destroying {env.name} ({env.backend})")
    return backend.resolve(env, drivable_backends()).destroy(env)


#: THE TASKS WHOSE NAMES THE KERNEL DERIVES (si#810), each with whether its body deploys (`up`) or destroys
#: (`down`). Read off the catalogue's own body table rather than typed, so the coordinates are whatever
#: `deploy:up`/`deploy:down` are bound to. `deploy:carrier` is not here: it reads `<url_from>_PASSWORD` and
#: the Proxmox token, which is a different reader and was not part of the decision.
READS: dict[str, bool] = {coordinate: ref == f"{__name__}:up" for coordinate, ref in artifactschema.BODIES.items()
                          if ref in (f"{__name__}:up", f"{__name__}:down")}


def variables_read(data: Mapping[str, object], task: str) -> tuple[str, ...]:
    """The variable NAMES `task` reads out of the environment it runs in, derived from this manifest, or ()
    for a task this module does not run (si#810).

    THE GAP IT CLOSES. On the container route the launcher forwards only names somebody declared, and the
    names `deploy:up` reads - the carrier's `<url_from>_URL`/`_TOKEN` and its ghcr.io credential, the
    repository's `credential_from:` pair, the environment's `required:` and `optional:` - are declared in
    the manifest already, as carriers and environments. A product that did not repeat them under `env:
    pass:` met "PORTAINER_URL, PORTAINER_TOKEN missing" on the container route only. Decided by Marco
    2026-11-20: the kernel derives them; the product re-renders its launchers.

    Every `backend: portainer` environment counts, not only the one a run targets: the launcher is rendered
    once for all of them. Another backend contributes nothing, because the kernel does not know what a
    backend it does not ship reads. A manifest with no `cd: environments:` (a client install) derives
    nothing; a malformed one is refused by `parse_data`, with its own sentence.
    """
    deploying = READS.get(task)
    if deploying is None or environments.matrix_section(data)["environments"] is None:
        return ()
    registry = environments.parse_data(data)
    carriers = carrierspec.declared(data)
    names = (name for env in registry.environments.values() if env.backend == portainer.BACKEND
             for name in portainer.variables_read(env, carriers, deploying=deploying))
    return tuple(dict.fromkeys(names))


def variables_kept(*tasks: str) -> tuple[str, ...]:
    """`variables_read` for each of `tasks` against the running product's manifest, each name once - what a
    command bound to one of them keeps when the kernel confines it (`launcherenv.confine`, si#810). Asks
    nothing of the manifest unless one of `tasks` is in `READS`."""
    if not any(task in READS for task in tasks):
        return ()
    data = context.current().manifest_data()
    return tuple(dict.fromkeys(name for task in tasks for name in variables_read(data, task)))
