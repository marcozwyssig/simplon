"""`backend: devcontainer` - the development environment a repository describes about ITSELF.

The second backend this kernel ships, and the reason is the same one `PortainerBackend` gives for the
first: the chain underneath it is already the kernel's. `deploy <env> up` resolves an environment to a
backend, Docker is a thing this kernel installs and checks (`simplon.docker`), and what is missing in
between is thirty lines that read a file the repository already carries. A product that had to write
this class would be writing the far end of a pipe the kernel owns both ends of.

WHAT IT IS NOT. It is not an editor integration, and nothing in this module names one. `devcontainer.json`
is an OPEN specification with a reference CLI of its own (`@devcontainers/cli`), and it is read by more
than one consumer - JetBrains Gateway, DevPod and Codespaces among them. This backend brings the
environment up and takes it down; which editor a person then attaches, and how, is that person's business
and their product's. The owner decision of 2026-09-23 is exactly that line: "Kernel zieht hoch, firn
öffnet."

WHY IT REFUSES A PUBLISHED VERSION. `deploy dev up local` is the only sentence that means anything here:
a development environment is the working tree, mounted. A tag names something in a registry, which is a
deployment of a DIFFERENT thing under the same verb, and answering it would put a published artefact
behind a command whose whole purpose is the code you are editing.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from simplon import context, docker, log
from simplon.run import Result, run, stream

if TYPE_CHECKING:  # pragma: no cover - typing only
    from simplon.deployment import Version
    from simplon.environments import Environment

#: The `backend:` tag an environment names to reach this.
BACKEND = "devcontainer"

#: What the specification calls its file, relative to the product root.
SPEC = Path(".devcontainer") / "devcontainer.json"

#: The label the reference CLI puts on every container it starts, carrying the folder it was started for.
#: It is how a teardown finds what a bring-up made without keeping state of its own between two commands.
LABEL = "devcontainer.local_folder"


def cli() -> list[str]:
    """The devcontainer CLI as an argv prefix, or a refusal that names the way out.

    Two ways to have it and one way not to, which is the shape si#202 asked every host route to take: a
    tool that is missing must be named together with the command that installs it, because the refusal a
    person meets is the only documentation they read at that moment.
    """
    installed = shutil.which("devcontainer")
    if installed:
        return [installed]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "@devcontainers/cli"]
    raise ValueError(
        "no devcontainer CLI on this machine, so nothing was started. Install it with "
        "`npm install -g @devcontainers/cli`, or install node so that `npx @devcontainers/cli` can "
        "fetch it")


class DevcontainerBackend:
    """The lifecycle triad of `simplon.backend.Backend`, against one workspace folder."""

    name = BACKEND

    def deploy(self, env: "Environment", version: "Version") -> int:
        root = _root()
        _describes_itself(root, env)
        if not version.builds:
            raise ValueError(
                f"environment '{env.name}' is a devcontainer, which runs the working tree rather than a "
                f"published version - so '{version.selector}' names something it cannot start. Say "
                f"`local`")
        docker.ensure_docker()
        log.info(f"bringing up the devcontainer described by {SPEC}")
        rc = stream(cli() + ["up", "--workspace-folder", str(root)])
        if rc == 0:
            log.ok(f"the devcontainer for {root} is up; `deploy {env.name} status` says what it is")
        return rc

    def destroy(self, env: "Environment") -> int:
        """Removes what a bring-up made, by the label the specification's CLI writes.

        `devcontainer up` has no `down`, which is not an omission in the specification: the container is
        an ordinary one and Docker already removes containers. What the CLI gives us is the LABEL, and
        removing by label rather than by a name this module invents is what keeps a teardown correct when
        somebody has started the same workspace from an editor instead of from here.
        """
        root = _root()
        containers = _containers_of(root)
        if not containers:
            log.ok(f"no devcontainer is running for {root}; nothing to remove")
            return 0
        docker.ensure_docker()
        log.info(f"removing {len(containers)} devcontainer(s) for {root}")
        return run(["docker", "rm", "--force", *containers]).rc

    def status(self, env: "Environment") -> str:
        root = _root()
        if not (root / SPEC).is_file():
            return f"{env.name}: no {SPEC} in {root}, so this environment describes no container"
        containers = _containers_of(root)
        if not containers:
            return f"{env.name}: described by {SPEC}, not running"
        described = run(
            ["docker", "ps", "--filter", f"label={LABEL}={root}",
             "--format", "{{.ID}}  {{.Image}}  {{.Status}}"])
        return f"{env.name}: {described.out.strip() or 'running'}"


def _root() -> Path:
    return Path(context.current().root).resolve()


def _describes_itself(root: Path, env: "Environment") -> None:
    """Refuses an environment whose repository carries no specification, naming the file."""
    if not (root / SPEC).is_file():
        raise ValueError(
            f"environment '{env.name}' names the devcontainer backend, but {root / SPEC} does not "
            f"exist - so there is nothing describing what to start. The specification is at "
            f"https://containers.dev")


def _containers_of(root: Path) -> list[str]:
    """Every container the CLI started for this folder, running or not."""
    listed: Result = run(
        ["docker", "ps", "--all", "--quiet", "--filter", f"label={LABEL}={root}"])
    return [line.strip() for line in listed.out.splitlines() if line.strip()]
