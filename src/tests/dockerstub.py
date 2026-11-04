"""A `docker` on PATH that is a real process, for the socket resolver and `support:docker-preflight` (si#564).

Not a mock of `run`: the code under test starts a real executable and reads its real exit code and output.
What it cannot show is a real daemon or a real Colima - no CI host has Colima - so the tests that use it
say which docker answer they stage, and the extension's own behaviour stays a reading of its code
(si#564's first comment), not a measurement here.
"""
from __future__ import annotations

from pathlib import Path


def docker_on_path(tmp_path: Path, script: str) -> Path:
    """Write `script` (POSIX sh, `$1` is docker's first argument) as `<tmp_path>/stubbin/docker`; return the dir."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    docker = bindir / "docker"
    docker.write_text("#!/bin/sh\n" + script, encoding="utf-8")
    docker.chmod(0o755)
    return bindir


def context_script(name: str, endpoint: str, *, inspect_rc: int = 0, version_rc: int = 0,
                   version_err: str = "") -> str:
    """A docker whose `context inspect` names `name|endpoint` and whose `version` answers or not."""
    return f"""
case "$1" in
  context) [ {inspect_rc} -eq 0 ] || exit {inspect_rc}; echo '{name}|{endpoint}' ;;
  version) [ {version_rc} -eq 0 ] || {{ echo '{version_err}' >&2; exit {version_rc}; }}; echo 29.5.2 ;;
  *) exit 0 ;;
esac
"""
