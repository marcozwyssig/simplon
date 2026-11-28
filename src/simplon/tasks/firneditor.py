"""si#900: which runtime runs firn for `support install`'s editor gates, `local` or `docker`.

The flag wins and is remembered per host; with no flag the stored choice is used; with neither, the default
comes from the release: `local` when it ships a binary for this host, else `docker`. A default is never stored,
so a later release that gains this host's binary changes it. A release that cannot be read gives no default
(NoToken, ReleaseUnreadable propagate): guessing docker there would turn "could not tell" into an answer.
"""
import os
import shlex
import json
import shutil
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from simplon.adapters import firnrelease, hostinstall, tools
from simplon.kernel import limits
from simplon.kernel.run import run
from simplon.tasks import gitops

RUNTIMES = ("local", "docker")
EXTENSION_ID = "zwyssig.firn"


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


def _code_unanswered(what: str) -> hostinstall.Outcome:
    return hostinstall.Outcome(hostinstall.State.FAILED, f"could not ask code ({what})")


def extension_gate(tag: str, release_of: Callable[[], firnrelease.Release], scratch: Path) -> hostinstall.Outcome:
    """firn's VS Code extension at `tag`: PRESENT when `code` lists it at that version, else the release's
    checked `.vsix` (downloaded into `scratch`, which the caller owns) is installed.

    A `code` that cannot list is not "not installed": nothing is installed over a tool that did not answer.
    """
    version = tag.removeprefix("v")
    code = shutil.which("code")
    if code is None:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   "`code` is not on PATH; install VS Code and its `code` command, or skip "
                                   "the editor gates")
    listed = run([code, "--list-extensions", "--show-versions"], timeout=hostinstall.VERSION_TIMEOUT_S,
                 terminal=False)
    if not listed.ok:
        why = "no answer in time" if listed.timed_out else (listed.not_started or listed.err.strip()
                                                            or f"exit code {listed.rc}")
        return _code_unanswered(f"code --list-extensions: {why}")
    if f"{EXTENSION_ID}@{version}" in listed.out.split():
        return hostinstall.Outcome(hostinstall.State.PRESENT, f"{EXTENSION_ID}@{version}")
    name = f"firn-{tag}.vsix"
    vsix = Path(scratch) / name
    try:
        firnrelease.fetch_checked(release_of(), name, vsix)
    except (firnrelease.NoToken, firnrelease.ReleaseUnreadable, firnrelease.AssetMissing,
            firnrelease.ChecksumMismatch) as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, str(e))
    installed = run([code, "--install-extension", str(vsix), "--force"], timeout=hostinstall.INSTALL_TIMEOUT_S,
                    terminal=False)
    if installed.timed_out:
        return _code_unanswered("code --install-extension: no answer in time")
    if not installed.ok:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"code --install-extension failed: "
                                   f"{(installed.err or installed.not_started).strip() or installed.rc}")
    return hostinstall.Outcome(hostinstall.State.INSTALLED, f"{EXTENSION_ID}@{version}")


WORKSPACE_TOML = "firn-workspace.toml"
JAVA_ISSUE = "firn#1460"


def _model_folders(data: Mapping[str, object]) -> list[str]:
    folders: list[str] = []
    for where, with_, _, _ in firnrelease.firn_commands(data):
        cwd = with_.get("cwd", ".")
        if not isinstance(cwd, str):
            raise ValueError(f"command '{where}' has `with: cwd: {cwd!r}`, which is not a folder name")
        folder = Path(cwd).as_posix()
        if folder not in folders:
            folders.append(folder)
    return folders


def projects(root: Path, data: Mapping[str, object]) -> list[str]:
    """The firn projects of the product as relative POSIX paths: `firn-workspace.toml`'s `projects` when the
    product has one, else the folder each model command runs in. A folder that does not exist is named."""
    toml = Path(root) / WORKSPACE_TOML
    if toml.is_file():
        try:
            listed = tomllib.loads(toml.read_text(encoding="utf-8")).get("projects")
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
            raise ValueError(f"{toml} cannot be read ({type(e).__name__}: {e})") from e
        if not isinstance(listed, list) or not all(isinstance(p, str) for p in listed):
            raise ValueError(f"{toml}: `projects` must be a list of folder names, got {listed!r}")
        folders = [Path(p).as_posix() for p in listed]
        source = str(toml)
    else:
        folders = _model_folders(data)
        source = "the commands that run firn's image"
    for folder in folders:
        if not (Path(root) / folder).is_dir():
            raise ValueError(f"project folder {folder} (from {source}) does not exist under {root}")
    return folders


def _walk_failed(error: OSError) -> None:
    raise error


def java_projects(root: Path, projects: list[str]) -> list[str]:
    """The projects whose folder holds a `*.java` file outside its `build/`. A folder that cannot be walked
    raises OSError: it is not "no Java"."""
    carrying = []
    for project in projects:
        base = Path(root) / project
        for here, dirs, files in os.walk(base, onerror=_walk_failed):
            if Path(here).relative_to(base).parts[:1] == ("build",):
                dirs[:] = []
                continue
            if any(f.endswith(".java") for f in files):
                carrying.append(project)
                break
    return carrying


def workspace_gate(root: Path, product: str, binary: Path, data: Mapping[str, object]) -> hostinstall.Outcome:
    """`<product>.code-workspace` at the product root: the firn projects as folders, `firn.binary` the runtime
    gate's target relative to the root. It is generated per host, so it must be git-ignored; it stays written
    and the gate fails when it is not."""
    root = Path(root)
    try:
        folders = projects(root, data)
        java = java_projects(root, folders)
    except ValueError:
        raise
    except OSError as e:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"could not tell which projects carry Java functions: {e}")
    relative = Path(os.path.relpath(binary, root)).as_posix()
    text = json.dumps({"folders": [{"path": f} for f in folders],
                       "settings": {"firn.mode": "stdio", "firn.binary": relative}}, indent=2) + "\n"
    name = f"{product}.code-workspace"
    path = root / name
    try:
        current = path.read_text(encoding="utf-8") if path.is_file() else None
    except (OSError, UnicodeDecodeError):
        current = None
    state = hostinstall.State.PRESENT
    if current != text:
        path.write_text(text, encoding="utf-8")
        state = hostinstall.State.INSTALLED
    asked = gitops.git(root, "check-ignore", "-q", name)
    if asked.timed_out or asked.not_started or asked.rc not in (0, 1):
        why = "no answer in time" if asked.timed_out else (asked.not_started or asked.err.strip() or asked.rc)
        return hostinstall.Outcome(hostinstall.State.FAILED, f"could not ask git whether {name} is ignored ({why})")
    if asked.rc == 1:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"{path} is written but not git-ignored; add the line /{name} to .gitignore")
    detail = str(path)
    if java:
        detail += (f"; the editor uses the stock firn for: {', '.join(java)} "
                   f"(their own binary needs {JAVA_ISSUE})")
    return hostinstall.Outcome(state, detail)
