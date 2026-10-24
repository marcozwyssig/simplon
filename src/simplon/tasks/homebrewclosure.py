"""The install closure of a Python wheel, measured inside the pinned Homebrew image (si#536).

The formula's resources are every distribution pip adds on top of the `depends_on` formulae. That set is not
computed from metadata here; it is MEASURED: the formulae are installed with brew, a venv with
`--system-site-packages` is made on their python, the wheel is pip-installed into it, and the venv's python
reports every distribution it can see. Whatever lives under the venv was added by pip; the rest came from
the formulae.

A FAILED MEASUREMENT IS NEVER AN EMPTY CLOSURE. An empty closure renders a formula without resources that
`brew install` then fails on a user's machine. So the container's answer is read only after a fixed marker
line, a run without that line is a `ValueError` carrying its last lines, and an answer that does not parse is
one too. Every refusal here is a `ValueError` that names what was measured and the way out.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from simplon.adapters import docker, hostpath
from simplon.kernel.run import run
from simplon.tasks import homebrewformula

#: The image the closure is measured in, pinned by tag and digest and validated by the kernel's own image
#: gate at import (as `tasks.allure.IMAGE` is). Its python formula is the one the formula's users get.
BREW_IMAGE = docker.pinned_image(
    "ghcr.io/homebrew/brew:7.0.9@sha256:00b643d72ab0ee27c64e3e552d08c66e1bb5272bdf4ed28964e27aa5764f2503",
    "simplon.tasks.homebrewclosure")

#: Seconds the whole container run may take: brew update, the bottle downloads (retried) and the pip install.
CLOSURE_TIMEOUT_S = 1800

#: The line the container prints right before its JSON answer. Nothing before it is the answer.
MARKER = "--- simplon closure ---"

#: `brew install` attempts inside the container. Measured: ghcr bottle downloads 404 intermittently.
INSTALL_ATTEMPTS = 5

TAIL_LINES = 20

#: The four environments one formula serves: each platform on each architecture, in the spelling each
#: platform's python reports for `platform_machine` (`aarch64` on Linux, `arm64` on macOS). A requirement's
#: marker is evaluated in all four, each laid over the container's own environment.
_LINUX = {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix"}
_DARWIN = {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix"}
ENVIRONMENTS = {
    "linux-x86_64": {**_LINUX, "platform_machine": "x86_64"},
    "linux-aarch64": {**_LINUX, "platform_machine": "aarch64"},
    "darwin-x86_64": {**_DARWIN, "platform_machine": "x86_64"},
    "darwin-arm64": {**_DARWIN, "platform_machine": "arm64"},
}

_VENV = "/tmp/v"

#: Runs on the venv's python inside the container and prints one JSON list on stdout. Each in-venv
#: distribution's requirement markers are evaluated with pip's vendored `packaging` (the kernel image does
#: not install `packaging`) in each of `ENVIRONMENTS`, with no extra requested. A requirement whose results
#: are not all equal is listed with every result.
_REPORT = (
    "import importlib.metadata as m, json\n"
    "from pip._vendor.packaging.requirements import Requirement\n"
    f"ENVIRONMENTS = {ENVIRONMENTS!r}\n"
    "def differs(reqs):\n"
    "    out = []\n"
    "    for req in reqs:\n"
    "        marker = Requirement(req).marker\n"
    "        if marker is None:\n"
    "            continue\n"
    "        # Recorded limit: a requirement behind an extra that another dist in the closure requests is\n"
    "        # evaluated here as not requested.\n"
    "        results = {name: marker.evaluate({'extra': '', **env}) for name, env in ENVIRONMENTS.items()}\n"
    "        if len(set(results.values())) > 1:\n"
    "            out.append([req, results])\n"
    "    return out\n"
    "dists = []\n"
    "for d in m.distributions():\n"
    f"    in_venv = str(d.locate_file('')).startswith('{_VENV}/')\n"
    "    dists.append({'name': d.metadata['Name'], 'version': d.version, 'requires': d.requires or [],\n"
    "                  'in_venv': in_venv, 'differs': differs(d.requires or []) if in_venv else []})\n"
    "print(json.dumps(dists))\n")


class Dist(NamedTuple):
    name: str
    version: str
    requires: tuple[str, ...]
    in_venv: bool
    #: (requirement, ((environment, result), ...)) for each requirement whose marker is not the same in all
    #: of `ENVIRONMENTS`.
    differs: tuple[tuple[str, tuple[tuple[str, bool], ...]], ...] = ()


def _key(name: str) -> str:
    """The PEP 503 normalised name: `PyYAML`, `pyyaml` and `py_yaml` are one distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _tail(text: str) -> str:
    return "\n".join(text.rstrip("\n").splitlines()[-TAIL_LINES:])


def script(wheel_name: str, depends_on: Sequence[str], python: str) -> str:
    """The bash the container runs: install the formulae (retried), make the venv, install the wheel, report."""
    # One source for the form, looked up at call time so either module may import the other.
    if not homebrewformula._PYTHON_FORMULA.match(python):
        raise ValueError(f"python must name a python formula of the form python@3.N, such as 'python@3.14', "
                         f"got {python!r}")
    formulae = " ".join(shlex.quote(f) for f in sorted(set(depends_on) | {python}))
    interpreter = "python" + python.split("@", 1)[1]
    return "\n".join([
        "set -euo pipefail",
        "brew update -q >&2",
        "export HOMEBREW_NO_INSTALL_CLEANUP=1",
        "ok=",
        f"for i in $(seq 1 {INSTALL_ATTEMPTS}); do",
        f"  if brew install -q {formulae} >/tmp/bi.log 2>&1; then ok=1; break; fi",
        f'  echo "brew install attempt $i of {INSTALL_ATTEMPTS} failed" >&2',
        f'  if [ "$i" -lt {INSTALL_ATTEMPTS} ]; then sleep $((i*5)); fi',
        "done",
        f'if [ -z "$ok" ]; then tail -n {TAIL_LINES} /tmp/bi.log >&2; exit 1; fi',
        f'"$(brew --prefix {shlex.quote(python)})/bin/{interpreter}" -m venv --system-site-packages {_VENV}',
        f"{_VENV}/bin/pip -q install /w/{shlex.quote(wheel_name)} >&2",
        f"echo {shlex.quote(MARKER)}",
        f"{_VENV}/bin/python -c {shlex.quote(_REPORT)}",
    ])


def _readable_by_the_container(wheel: Path) -> None:
    """Refuse a wheel the brew image's own user (uid 1000, not the caller) could not read through the mount.

    Measured: pytest's 0700 tmp_path made pip answer `Permission denied` inside the container. A host with
    no uid concept (Windows) carries no ownership through the mount, so there is nothing to check there.
    """
    if not wheel.is_file():
        raise ValueError(f"{wheel} does not exist or is not a file; build the wheel first")
    if not hasattr(os, "getuid"):
        return
    for path, needed, what, chmod in ((wheel.parent, 0o005, "read and search", "o+rx"), (wheel, 0o004, "read", "o+r")):
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & needed != needed:
            raise ValueError(f"{path} has mode {mode:o}, so the brew image's user (uid 1000, not yours) cannot "
                             f"{what} it through the mount; make it readable by others (chmod {chmod})")


def measure(wheel: Path, depends_on: Sequence[str], python: str) -> tuple[Dist, ...]:
    """Every distribution the venv sees after installing `wheel` on top of `depends_on` and `python`."""
    wheel = Path(wheel)
    _readable_by_the_container(wheel)
    bash = script(wheel.name, depends_on, python)
    container, lifecycle = docker.lifecycle()
    argv = ["docker", "run", "--rm", "--network", "bridge", *lifecycle,
            "-v", f"{hostpath.translate(wheel.parent)}:/w:ro",
            BREW_IMAGE, "bash", "-c", bash]
    try:
        with docker.stopped_on_interrupt(container):
            result = run(argv, timeout=CLOSURE_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise ValueError(f"measuring the closure of {wheel.name} in {BREW_IMAGE} took longer than "
                         f"CLOSURE_TIMEOUT_S ({CLOSURE_TIMEOUT_S} s) and was stopped; rerun it, and raise "
                         f"CLOSURE_TIMEOUT_S if the bottle downloads are that slow") from e
    if not result.ok:
        both = result.err.rstrip("\n") + "\n" + result.out
        raise ValueError(f"measuring the closure of {wheel.name} in {BREW_IMAGE} failed (rc {result.rc}); "
                         f"after a bottle download failure rerunning is safe. Last lines:\n"
                         f"{_tail(both)}")
    dists = parse(result.out)
    # A successful run whose venv does not show the product measured nothing pip installed: `added` would be
    # empty and the formula would ship without resources. The product's name is the wheel file name's first
    # field (`my_tool-1.0-...whl` for `My.Tool`), compared normalised.
    product = wheel.name.split("-", 1)[0]
    if not any(d.in_venv and _key(d.name) == _key(product) for d in dists):
        raise ValueError(f"the venv shows no {product}; the measurement did not see pip's install of "
                         f"{wheel.name}, so its closure is unknown. Last lines:\n{_tail(result.err)}")
    return dists


def parse(stdout: str) -> tuple[Dist, ...]:
    """The distributions in the JSON document printed after `MARKER`. No marker is a failed run."""
    lines = stdout.splitlines()
    if MARKER not in lines:
        raise ValueError(f"the closure run printed no '{MARKER}' line, so it did not get to measure anything. "
                         f"Last lines:\n{_tail(stdout)}")
    document = "\n".join(lines[lines.index(MARKER) + 1:])
    try:
        return tuple(Dist(str(d["name"]), str(d["version"]), tuple(str(r) for r in d["requires"]),
                          bool(d["in_venv"]),
                          tuple((str(r), tuple((str(e), bool(v)) for e, v in results.items()))
                                for r, results in d["differs"]))
                     for d in json.loads(document))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise ValueError(f"what followed '{MARKER}' is not the closure document ({e}). Last lines:\n"
                         f"{_tail(stdout)}") from e


def refusals(dists: Sequence[Dist], product: str) -> list[str]:
    """What makes this closure unfit for one formula that serves macOS and Linux alike.

    The platform rule reads the markers the container found to differ across `ENVIRONMENTS` (a Windows-only
    requirement is false in all four and passes), and only in the closure: what pip installed into the venv,
    the product included.
    A formula's own distribution (pydantic's `tzdata; platform_system == 'Windows' and extra == 'timezone'`,
    measured) is the formula's business, not this resource list's.
    """
    out = []
    for d in dists:
        if not d.in_venv:
            continue
        for req, results in d.differs:
            on = {value: ", ".join(env for env, v in results if v is value) for value in (True, False)}
            out.append(f"{d.name} {d.version} requires '{req}', whose marker is true on {on[True]} and false on "
                       f"{on[False]}, so one resource list cannot be right in all four; provide "
                       f"that dependency through a depends_on formula, or ask the maintainer of {d.name}")
    exempt = {_key(product), "pip"}
    outside = {_key(d.name): d for d in dists if not d.in_venv}
    for d in dists:
        brew = outside.get(_key(d.name))
        if d.in_venv and brew is not None and _key(d.name) not in exempt:
            out.append(f"pip installed {d.name} {d.version} into the venv although a depends_on formula provides "
                       f"{brew.name} {brew.version}; relax the requirement to accept the formula's version or drop "
                       f"the formula from depends_on")
    return out


def added(dists: Sequence[Dist], product: str) -> tuple[Dist, ...]:
    """The distributions pip installed into the venv, minus the product itself and pip."""
    exempt = {_key(product), "pip"}
    return tuple(d for d in dists if d.in_venv and _key(d.name) not in exempt)
