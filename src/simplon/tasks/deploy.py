"""The deploy commands the kernel owns (si#235).

ONE SHAPE FOR EVERY PRODUCT, and the axis is what the product IS rather than what it is written in: a
CLIENT application is installed into a directory on this machine, a SERVER application is brought up on a
target through the product's own backend. Both name the version they are deploying, in the same three
words (`1.4.0`, `latest`, `local`), and `simplon.deployment` is where that vocabulary lives.

WHAT IS OUT OF SCOPE, stated here because it is the half somebody will assume is coming. `client` means
installing a version HERE. Distributing one to a FLEET - an SCCM, an MDM, a software deployment server -
is not Simplon's business and is not what these commands grow into. A product that needs it drives its
own tool, with this vocabulary in front of it.

THE SERVER PATH NAMES NO BACKEND, which is the whole of `simplon.backend`'s design: the product registers
one implementation per backend tag and the kernel resolves the environment to an instance. What si#235
added there is a REGISTRATION seam, because a catalogue task is called by the CLI with manifest-pinned
parameters and nothing else - it cannot be handed a registry as an argument the way `backend.resolve` is.

THE CLIENT PATH INSTALLS INTO `into/<version>`, one directory per version rather than one directory
overwritten. Two reasons, and neither is tidiness: a rollback is then a second `up` rather than a
re-fetch, and `down` has something exact to remove instead of a directory it has to guess the contents of.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from simplon import backend, context, deployment, environments, githubpackages, log


def _environment() -> environments.Environment:
    """The environment this deployment targets, resolved the way the CLI resolved it.

    The name comes off `context.ENVIRONMENT_ENV`, which `cli.main` writes for exactly this reason - its
    own comment says the product's variable arrives through an injected provider, "so no kernel leaf can
    read the answer back out of it". This is such a leaf.

    The MATRIX comes off the manifest, and the valid backends are the registered ones: a product's
    registry is the list of backends it really implements, so an environment naming one nobody registered
    is refused by `parse_data` with both names in the message rather than failing later.
    """
    registered = backend.registered()
    matrix = environments.parse_data(context.current().manifest_data(), tuple(registered))
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


def up(version: str = "") -> int:
    """Deploy `version` - `1.4.0`, `latest`, or `local` for the current code base."""
    source = deployment.declared()
    resolved = deployment.resolve(version, source)
    if source.application == deployment.CLIENT:
        _refuse_a_local_client(resolved)
        target = _install_root(source, resolved)
        log.info(f"installing {source.reference}:{resolved.tag} into {target}")
        githubpackages.fetch_directory(f"{source.reference}:{resolved.tag}", target)
        log.ok(f"{resolved.tag} is installed in {target}")
        return 0
    env = _environment()
    log.info(f"deploying {resolved.tag} to {env.name} ({env.backend})")
    return backend.resolve(env, backend.registered()).deploy(env, resolved)


def down(version: str = "") -> int:
    """Remove a deployment - a client's installed `version`, or a server's environment.

    A client needs the version because `up` installed one directory per version: removing "the
    deployment" without saying which would mean guessing which of them somebody meant.
    """
    source = deployment.declared()
    if source.application == deployment.CLIENT:
        resolved = deployment.resolve(version, source)
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
    return backend.resolve(env, backend.registered()).destroy(env)
