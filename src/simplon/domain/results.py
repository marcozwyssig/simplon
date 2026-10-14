"""A producer that exits 0 without writing its test result is a failed step (si#344 C.3, spec C.3).

A test result declared and never written would be "nothing to do" passing for "tested", which is the house
defect. So both dispatch paths - the generated module (`taskgen`) and `cli.assemble` - snapshot every test
result a command produces BEFORE its body runs, and `held` compares after it: a file that is absent, or no
newer than it was, was not written by this run. "Exists" would not do: yesterday's file exists.

Only `test-result` artifacts are watched. Which those are is read at run time from `artifacts:`, because the
generated module is rendered from the manifest's commands and does not carry the section.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from simplon.domain import artifactsection, context
from simplon.kernel import log

#: artifact name -> (its absolute path, its newest mtime_ns before the body ran, or None when absent)
Snapshot = dict[str, tuple[Path, "int | None"]]


def _section() -> dict:
    ctx = context.current()
    # The key literally, not `artifactsection.SECTION`: the refusal census resolves which section a read
    # takes by its literal key, and an unresolved one turns `test_every_unresolved_key_read_is_named` red.
    section = ctx.manifest_data().get("artifacts") or {}
    return section if isinstance(section, dict) else {}


def path_of(name: str) -> Path:
    """The absolute path of the `test-result` entry `name`, refused by name when it is not one."""
    ctx = context.current()
    body = _section().get(name)
    if not isinstance(body, dict):
        raise ValueError(f"no artifact '{name}' in {ctx.manifest_path.name}'s `artifacts:` section")
    kind = str(body.get("kind", ""))
    if not artifactsection.is_a(kind, "test-result"):
        raise ValueError(f"artifact '{name}' is a `{kind}`, not a `test-result` - a test writes its verdict "
                         f"only to a test result")
    if not body.get("path"):
        raise ValueError(f"test result '{name}' declares no `path:` - a test result is what the test writes")
    return ctx.root / str(body["path"])


def _newest(path: Path) -> "int | None":
    if path.is_file():
        return path.stat().st_mtime_ns
    if path.is_dir():
        stamps = [p.stat().st_mtime_ns for p in path.rglob("*") if p.is_file()]
        return max(stamps) if stamps else None
    return None


def before(produced: Sequence[str]) -> Snapshot:
    """Each produced artifact that is a test result, with its state before the body runs."""
    section = _section()
    out: Snapshot = {}
    for name in produced:
        body = section.get(name)
        if isinstance(body, dict) and artifactsection.is_a(str(body.get("kind", "")), "test-result"):
            path = path_of(name)
            out[name] = (path, _newest(path))
    return out


def held(snapshot: Snapshot, rc: int) -> int:
    """`rc`, unless it is 0 and a test result in `snapshot` was not written by this run: then 1."""
    if rc != 0:
        return rc
    root = context.current().root
    unwritten = [f"'{name}' ({path.relative_to(root) if path.is_relative_to(root) else path})"
                 for name, (path, then) in snapshot.items()
                 if (now := _newest(path)) is None or (then is not None and now <= then)]
    if unwritten:
        log.error(f"exited 0 and did not write the test result(s) {', '.join(unwritten)} - a test that "
                  f"wrote no result has not said it passed")
        return 1
    return 0
