"""si#900: `support install`'s firn editor gates (`editor`): the VS Code extension, the runtime that runs firn's
language server (`local` or `docker`) and the product's code-workspace. Each file they write goes through a
temporary file and `os.replace`, so a symlink at its path is replaced, never followed.

The flag wins and is remembered per host; with no flag the stored choice is used; with neither, the default
comes from the release: `local` when it ships a binary for this host, else `docker`. A default is never stored,
so a later release that gains this host's binary changes it. A release that cannot be read gives no default
(NoToken, ReleaseUnreadable propagate): guessing docker there would turn "could not tell" into an answer.
"""
import contextlib
import json
import os
import shlex
import shutil
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from simplon.adapters import firnrelease, hostinstall, tools
from simplon.kernel import limits, log
from simplon.kernel.run import run
from simplon.manifest import context
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


def _replace(path: Path, text: str, mode: int = 0o644) -> None:
    """Write `text` to `path` through a temporary file in the same directory and `os.replace`: whatever stood at
    `path`, a symlink included, is replaced, never followed. A symlink there may point outside the tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        try:
            stream = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _current(path: Path) -> str | None:
    """The text of the regular file at `path`, or None: a symlink, anything not a file, or an unreadable file
    counts as differing, so it is rewritten (and a symlink replaced)."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _stored(path: Path) -> str | None:
    if not os.path.lexists(path):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"{path} exists but cannot be read as the stored runtime ({type(e).__name__}: {e}). "
                         f"Delete it or pass --firn-runtime to replace it.") from e
    for runtime in RUNTIMES:
        if text == f"{runtime}\n":
            return runtime
    raise ValueError(f"{path} holds {text!r}; it must hold exactly one of {' | '.join(RUNTIMES)} and a newline. "
                     f"Delete it or pass --firn-runtime to replace it.")


def choose_runtime(flag: str, release_of: Callable[[], firnrelease.Release],
                   env: Mapping[str, str] | None = None) -> Choice:
    path = runtime_file(env)
    if flag:
        if flag not in RUNTIMES:
            raise ValueError(f"unknown firn runtime {flag!r}; use one of {' | '.join(RUNTIMES)}")
        _replace(path, f"{flag}\n")
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
                                   "no firn binary exists for this OS and architecture; "
                                   "use --firn-runtime docker"), None
    binary = tools.bin_dir() / name
    if binary.is_file() and os.access(binary, os.X_OK):
        return hostinstall.Outcome(hostinstall.State.PRESENT, f"{binary}"), binary
    try:
        firnrelease.fetch_checked(release_of(), name, binary)
        binary.chmod(0o755)
    except firnrelease.AssetMissing as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, f"{e}; or use --firn-runtime docker"), None
    except (firnrelease.NoToken, firnrelease.ReleaseUnreadable, firnrelease.ChecksumMismatch) as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, str(e)), None
    except OSError as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, f"could not write {binary}: {e}"), None
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
                                   "the docker CLI is not installed or does not run; "
                                   "install it or use --firn-runtime local")
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


def _docker_gate(image: str, root: Path) -> tuple[hostinstall.Outcome, Path | None]:
    if ":" in str(root):
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"the product root {root} contains a colon, and docker's -v cannot mount a "
                                   f"path with a colon; use --firn-runtime local or a root without one"), None
    not_ready = _docker_ready(image)
    if not_ready is not None:
        return not_ready, None
    script = tools.bin_dir() / "firn-docker"
    if script.is_dir() and not script.is_symlink():  # a symlink, even to a directory, is replaced below
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"{script} is a directory, so the docker wrapper cannot be written there; "
                                   f"remove it"), None
    text = docker_script(root, image, os.getuid(), os.getgid())
    state = hostinstall.State.PRESENT
    try:
        if _current(script) != text:
            _replace(script, text, 0o755)
            state = hostinstall.State.INSTALLED
        else:
            script.chmod(0o755)
    except OSError as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, f"could not write {script}: {e}"), None
    return hostinstall.Outcome(state, f"{script}"), script


def runtime_gate(choice: Choice, tag: str, release_of: Callable[[], firnrelease.Release],
                 root: Path, *, image: str) -> tuple[hostinstall.Outcome, Path | None]:
    """Make the chosen runtime ready; the path is the `firn.binary` target, None when the gate left none.
    `image` is the manifest's own reference at `tag` (a digest included), so docker runs what the build runs."""
    if choice.runtime == "local":
        return _local_gate(tag, release_of)
    return _docker_gate(image, root)


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
        return hostinstall.Outcome(hostinstall.State.NO_ROUTE,
                                   "`code` is not on PATH; install VS Code and its `code` command")
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
    except OSError as e:
        return hostinstall.Outcome(hostinstall.State.FAILED, f"could not write {vsix}: {e}")
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
    for _, with_, _, _ in firnrelease.firn_commands(data):
        cwd = with_.get("cwd")  # a string or null: firn_commands refuses any other cwd
        folder = Path("." if cwd is None else cwd).as_posix()
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
            dirs[:] = [d for d in dirs if d != ".git"]
            if any(f.endswith(".java") for f in files):
                carrying.append(project)
                break
    return carrying


def _outside(root: Path, folders: list[str]) -> list[str]:
    """The folders that do not lie under `root`, symlinks resolved: absolute elsewhere, or escaping by `..`."""
    real = os.path.realpath(root)
    return [f for f in folders if os.path.commonpath([real, os.path.realpath(root / f)]) != real]


def workspace_gate(root: Path, product: str, binary: Path, data: Mapping[str, object], *,
                   docker: bool = False) -> hostinstall.Outcome:
    """`<product>.code-workspace` at the product root: the firn projects as folders, `firn.binary` the runtime
    gate's target relative to the root. It is generated per host, so it must be git-ignored; it stays written
    and the gate fails when it is not. With `docker`, the container sees only the product root, so a project
    outside it fails the gate and nothing is written: the server would answer it with nothing (spec 2)."""
    root = Path(root)
    try:
        folders = projects(root, data)
        java = java_projects(root, folders)
    except OSError as e:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"could not tell which projects carry Java functions: {e}")
    outside = _outside(root, folders) if docker else []
    if outside:
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"project folder {', '.join(outside)} lies outside the product root {root}, "
                                   f"and the docker runtime mounts only that root, so firn would answer it with "
                                   f"nothing; use --firn-runtime local or move the project under the root")
    relative = Path(os.path.relpath(binary, root)).as_posix()
    text = json.dumps({"folders": [{"path": f} for f in folders],
                       "settings": {"firn.mode": "stdio", "firn.binary": relative}}, indent=2) + "\n"
    name = f"{product}.code-workspace"
    path = root / name
    state = hostinstall.State.PRESENT
    if _current(path) != text:
        try:
            _replace(path, text)
        except OSError as e:
            return hostinstall.Outcome(hostinstall.State.FAILED, f"could not write {path}: {e}")
        state = hostinstall.State.INSTALLED
    asked = gitops.git(root, "check-ignore", "-q", name)
    if asked.timed_out or asked.not_started or asked.rc not in (0, 1):
        why = "no answer in time" if asked.timed_out else (asked.not_started or asked.err.strip() or asked.rc)
        return hostinstall.Outcome(hostinstall.State.FAILED, f"could not ask git whether {name} is ignored ({why})")
    if asked.rc == 1:
        if gitops.git(root, "ls-files", "--error-unmatch", name).rc == 0:
            return hostinstall.Outcome(hostinstall.State.FAILED,
                                       f"{path} is written but tracked by git, which no .gitignore line "
                                       f"overrides; untrack it with: git rm --cached {name}")
        return hostinstall.Outcome(hostinstall.State.FAILED,
                                   f"{path} is written but not git-ignored; add the line /{name} to .gitignore")
    detail = str(path)
    if java:
        detail += (f"; the editor uses the stock firn for: {', '.join(java)} "
                   f"(their own binary needs {JAVA_ISSUE})")
    return hostinstall.Outcome(state, detail)


EDITOR_GATES = ("firn extension", "firn runtime", "firn workspace")


def _once(read: Callable[[], firnrelease.Release]) -> Callable[[], firnrelease.Release]:
    """`read`, asked at most once: its release, or its exception, is the answer for the rest of this run. The
    exception is raised again, never turned into a release, so a failed read stays a failure."""
    answer: list[firnrelease.Release] = []
    failure: list[Exception] = []

    def release_of() -> firnrelease.Release:
        if failure:
            raise failure[0]
        if not answer:
            try:
                answer.append(read())
            except Exception as e:
                failure.append(e)
                raise
        return answer[0]
    return release_of


def _pinned(document: Mapping[str, object], source: str) -> tuple[Mapping[str, object], str, str]:
    """The manifest document, the firn tag its commands run, and the image reference the first of them names
    (a digest included), which the docker runtime runs. The one function `editor` hands the document to, so
    the refusal census walks what is decided on the manifest with nothing run yet: the pin. The workspace
    gate's own refusals come after the runtime gate has consulted docker or the release."""
    tag = firnrelease.pinned_tag(document, source)
    image = next(image for _, _, image, at in firnrelease.firn_commands(document) if at == tag)
    return document, tag, image


def editor(container: bool, flag: str, declared: tuple[str, ...]) -> bool:
    """`support install`'s firn editor gates (si#900): extension, runtime, workspace, in that order, each
    reported in its own words. Says nothing and reads nothing when `firn` is not declared; on the container
    route and in CI all three are SKIPPED before the manifest's pin or the release is read. False when any
    gate failed."""
    if "firn" not in declared:
        if flag:
            log.info(f"--firn-runtime {flag} ignored: `firn` is not in toolchains:")
        return True
    skip = hostinstall.machine_skip_reason(os.environ, container, "editor tools")
    if skip:
        if flag:
            log.info(f"--firn-runtime {flag} ignored: the firn editor gates are skipped ({skip})")
        for name in EDITOR_GATES:
            hostinstall.report(name, hostinstall.Outcome(hostinstall.State.SKIPPED, skip))
        return True
    ctx = context.current()
    try:
        data, tag, image = _pinned(ctx.manifest_data(), str(ctx.manifest_path))
    except (ValueError, RuntimeError) as e:  # RuntimeError: an unreadable manifest (context.py)
        log.error(f"firn editor: {e}; not run: {', '.join(EDITOR_GATES)}")
        return False
    release_of = _once(lambda: firnrelease.read(tag))
    choice: Choice | None = None
    try:
        choice = choose_runtime(flag, release_of)
        log.info(f"firn runtime: {choice.runtime} ({choice.source})")
    except (ValueError, OSError, firnrelease.NoToken, firnrelease.ReleaseUnreadable) as e:
        unchosen = str(e)
    try:
        scratch = tempfile.TemporaryDirectory(prefix="simplon-firn-vsix-", ignore_cleanup_errors=True)
    except OSError as e:
        extension = hostinstall.Outcome(hostinstall.State.FAILED,
                                        f"could not make a scratch directory for the .vsix: {e}")
    else:
        with scratch as directory:
            extension = extension_gate(tag, release_of, Path(directory))
    hostinstall.report("firn extension", extension)
    ok = hostinstall.rc(extension) == 0
    if choice is None:
        # nothing was installed, so not the gate's "install failed": the runtime could not be chosen
        log.error(f"firn runtime: could not be chosen: {unchosen}")
        runtime, binary = hostinstall.Outcome(hostinstall.State.FAILED, unchosen), None
    else:
        runtime, binary = runtime_gate(choice, tag, release_of, ctx.root, image=image)
        hostinstall.report("firn runtime", runtime)
    ok = ok and hostinstall.rc(runtime) == 0
    if binary is None:
        log.error(f"firn workspace: not written, because the runtime gate left no firn binary to point the editor "
                  f"at ({runtime.state.value})")
        return False
    try:
        workspace = workspace_gate(ctx.root, ctx.name, binary, data, docker=choice.runtime == "docker")
    except ValueError as e:
        workspace = hostinstall.Outcome(hostinstall.State.FAILED, str(e))
    hostinstall.report("firn workspace", workspace)
    return ok and hostinstall.rc(workspace) == 0
