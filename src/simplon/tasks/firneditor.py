"""si#900: which runtime runs firn for `support install`'s editor gates, `local` or `docker`.

The flag wins and is remembered per host; with no flag the stored choice is used; with neither, the default
comes from the release: `local` when it ships a binary for this host, else `docker`. A default is never stored,
so a later release that gains this host's binary changes it. A release that cannot be read gives no default
(NoToken, ReleaseUnreadable propagate): guessing docker there would turn "could not tell" into an answer.
"""
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from simplon.adapters import firnrelease

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
    if not path.is_file():
        return None
    text = path.read_text()
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
    return Choice("docker", f"default ({binary or 'no binary named for this host'} is not in firn {release.tag})")
