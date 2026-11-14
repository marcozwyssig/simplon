"""Run the pinned firn image over a firn project, the way `toolchain:run` would (si#371)."""
from pathlib import Path

import yaml

from simplon.kernel.run import run
from simplon.tasks import toolchain

#: The firn simplon's own gates run, read from the one place it is pinned: `test model` in simplon.yaml
#: (si#645). Not restated here, so the suite cannot test a firn the gates no longer run.
FIRN_IMAGE: str = yaml.safe_load((Path(__file__).resolve().parents[2] / "simplon.yaml").read_text(
    encoding="utf-8"))["ci"]["test"]["commands"]["model"]["with"]["image"]


def firn_rc(project: Path, *argv: str, cwd: str = "", image: str = FIRN_IMAGE) -> tuple[int, str]:
    """(rc, stdout) of `firn <argv>` started in `project/<cwd>`, as the caller, with no network. `image` is
    the pinned firn unless a test needs another release's report."""
    body = {"image": image, "workdir": "/workspace", "argv": list(argv)}
    if cwd:
        body["cwd"] = cwd
    cfg = toolchain.declared(body, where="firn")
    line = toolchain.docker_argv(cfg, root=project, product="firn-test", instance="", extra=[],
                                 network="none")
    result = run(line, capture=True)
    return result.rc, result.out
