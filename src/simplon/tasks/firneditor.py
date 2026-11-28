"""si#900: which runtime runs firn for `support install`'s editor gates, `local` or `docker`.

The flag wins and is remembered per host; with no flag the stored choice is used; with neither, the default
comes from the release: `local` when it ships a binary for this host, else `docker`. A default is never stored,
so a later release that gains this host's binary changes it. A release that cannot be read gives no default
(NoToken, ReleaseUnreadable propagate): guessing docker there would turn "could not tell" into an answer.
"""
import os
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from simplon.adapters import firnrelease, hostinstall, tools
from simplon.kernel import limits
from simplon.kernel.run import run

RUNTIMES = ("local", "docker")


@dataclass(frozen=True)
class Choice:
    runtime: str
    source: str  # "flag", "stored" or "default (<why>)"


def runtime_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(base) / "simplon" / "firn-runtime"


def _stored(path: Path) -> str | None:
    if not os.path.lexists(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"{path} exists but cannot be read as the stored runtime ({type(e).__name__}: {e}). "
                         f"Delete it or pass --runtime to replace it.") from e
    for runtime in RUNTIMES:
        if text == f"{runtime}\n":
            return runtime
    raise ValueError(f"{path} holds {text!r}; it must hold exactly one of {' | '.join(RUNTIMES)} and a newline. "
                     f"Delete it or pass --runtime to replace it.")


def choose_runtime(flag: str, release_of: Callable[[], firnrelease.Release],
                   env: Mapping[str, str] | None = None) -> Choice:
    path = runtime_file(env)
    if flag:
        if flag not in RUNTIMES:
            raise ValueError(f"unknown firn runtime {flag!r}; use one of {' | '.join(RUNTIMES)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{flag}\n")
        return Choice(flag, "flag")
    stored = _stored(path)
    if stored is not None:
        return Choice(stored, "stored")
    release = release_of()
    binary = firnrelease.host_binary_name(release.tag)
    if binary is not None and binary in release.assets:
        return Choice("local", f"default ({binary} is in firn {release.tag})")
    if binary is None:
        return Choice("docker", "default (no firn binary exists for this OS and architecture, so docker)")
    return Choice("docker", f"default (firn {release.tag} has no asset {binary}, so docker)")


def docker_script(root: Path, image: str, uid: int, gid: int) -> str:
    """The stdio wrapper an editor runs as `firn.binary`: the product tree is mounted at its own host path, so
    the paths firn reports are the paths the editor knows."""
    mount = shlex.quote(f"{root}:{root}")
    return ("#!/bin/sh\n"
            f"exec docker run -i --rm -u {uid}:{gid} -v {mount} -w {shlex.quote(str(root))} "
            f"{shlex.quote(image)} \"$@\"\n")


def _local_gate(tag: str, release_of: Callable[[], firnrelease.Release]) -> tuple[hostinstall.Outcome, Path | None]:
    name = firnrelease.host_binary_name(tag)
    if name is None:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   "no firn binary exists for this OS and architecture; use --runtime docker"), None
    binary = tools.bin_dir() / name
    if binary.is_file() and os.access(binary, os.X_OK):
        return hostinstall.Outcome(hostinstall.State.PRESENT, f"{binary}"), binary
    try:
        firnrelease.fetch_checked(release_of(), name, binary)
    except (firnrelease.NoToken, firnrelease.ReleaseUnreadable, firnrelease.AssetMissing,
            firnrelease.ChecksumMismatch) as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, str(e)), None
    binary.chmod(0o755)
    return hostinstall.Outcome(hostinstall.State.INSTALLED, f"{binary}"), binary


def _could_not_ask(what: str) -> hostinstall.Outcome:
    return hostinstall.Outcome(hostinstall.State.FAILED, f"could not ask docker ({what} gave no answer in time)")


def _docker_ready(image: str) -> hostinstall.Outcome | None:
    """None when the CLI runs, the daemon answers and `image` is local (pulled when it was not); else why not.

    Presence of the CLI is not capability: each step is the smallest real instance of what the script needs.
    """
    try:
        cli = hostinstall.runs("docker")
    except hostinstall.NoAnswer:
        return _could_not_ask("docker --version")
    if not cli:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   "the docker CLI is not installed or does not run; install it or use --runtime local")
    daemon = run(["docker", "version"], timeout=hostinstall.VERSION_TIMEOUT_S, terminal=False)
    if daemon.timed_out:
        return _could_not_ask("docker version")
    if not daemon.ok:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"the docker daemon does not answer: {daemon.err.strip()}")
    inspected = run(["docker", "image", "inspect", image], timeout=hostinstall.VERSION_TIMEOUT_S, terminal=False)
    if inspected.timed_out:
        return _could_not_ask("docker image inspect")
    if inspected.ok:
        return None
    pulled = run(["docker", "pull", image], timeout=limits.DOCKER_PULL, terminal=False)
    if pulled.timed_out:
        return _could_not_ask(f"docker pull {image}")
    if not pulled.ok:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"docker pull {image} failed: {(pulled.err or pulled.not_started).strip()}")
    return None


def _docker_gate(tag: str, root: Path) -> tuple[hostinstall.Outcome, Path | None]:
    if ":" in str(root):
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"the product root {root} contains a colon, and docker's -v cannot mount a "
                                   f"path with a colon; use --runtime local or a root without one"), None
    image = f"{firnrelease.FIRN_IMAGE_REPOSITORY}:{tag}"
    not_ready = _docker_ready(image)
    if not_ready is not None:
        return not_ready, None
    script = tools.bin_dir() / "firn-docker"
    if script.is_dir():
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"{script} is a directory, so the docker wrapper cannot be written there; "
                                   f"remove it"), None
    text = docker_script(root, image, os.getuid(), os.getgid())
    try:
        current = script.read_text(encoding="utf-8") if script.is_file() else None
    except (OSError, UnicodeDecodeError):
        current = None  # unreadable counts as differing: it is rewritten below
    state = hostinstall.State.PRESENT
    if current != text:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(text, encoding="utf-8")
        state = hostinstall.State.INSTALLED
    script.chmod(0o755)
    return hostinstall.Outcome(state, f"{script}"), script


def runtime_gate(choice: Choice, tag: str, release_of: Callable[[], firnrelease.Release],
                 root: Path) -> tuple[hostinstall.Outcome, Path | None]:
    """Make the chosen runtime ready; the path is the `firn.binary` target, None when the gate left none."""
    if choice.runtime == "local":
        return _local_gate(tag, release_of)
    return _docker_gate(tag, root)
