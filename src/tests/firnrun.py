"""Run the pinned firn image over a firn project, the way `toolchain:run` would (si#371)."""
from pathlib import Path

from simplon.kernel.run import run
from simplon.tasks import profiles, toolchain

FIRN = profiles.profile("firn", version="0.2.0")


def firn_rc(project: Path, *argv: str, cwd: str = "") -> tuple[int, str]:
    """(rc, stdout) of `firn <argv>` started in `project/<cwd>`, as the caller, with no network."""
    body = {"image": FIRN.image, "workdir": "/workspace", "argv": list(argv)}
    if cwd:
        body["cwd"] = cwd
    cfg = toolchain.declared(body, where="firn")
    line = toolchain.docker_argv(cfg, root=project, product="firn-test", instance="", extra=[],
                                 network="none")
    result = run(line, capture=True)
    return result.rc, result.out
