"""A producer that exits 0 without writing its test result is a failed step (si#344 C.3, spec C.3).

A test result declared and never written would be "nothing to do" passing for "tested", which is the house
defect. So both dispatch paths - the generated module (`taskgen`) and `cli.assemble` - snapshot every test
result a command produces BEFORE its body runs, and `held` compares after it: a file that is absent, or no
newer than it was, was not written by this run. "Exists" would not do: yesterday's file exists.

Only `test-result` artifacts are watched. Which those are is read at run time from `artifacts:`, because the
generated module is rendered from the manifest's commands and does not carry the section.
"""
from __future__ import annotations

import json
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


# --- a release reads its evidence (si#434) ------------------------------------------------------------
#
# Rule 6 binds every test result about what a release publishes to the release's `evidence` port. Binding
# is not reading: until si#434 no release body opened the record, so a release after a red test ran
# exactly like one after a green test. The read sits HERE, in the wrapper both dispatch paths put around a
# body, and not in the five release bodies - one reader cannot drift from four others.
#
# The record is the verdict record `test:image` writes, the one producer of a test result in the catalogue
# (measured over the eight reachable manifests on 2026-10-15: no product task produces one). Its contract
# is a JSON object with an integer `verdict`, 0 for green. Three answers are kept apart, because each
# sends the reader somewhere else: NOT WRITTEN (the test has not run here - run it), RED (it ran and
# failed - read its runs), and NO VERDICT (something wrote the file, but nothing a release can read).

def _verdict(path: Path) -> "int | None":
    """The record's verdict, or None when the file is no verdict record."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    verdict = record.get("verdict") if isinstance(record, dict) else None
    # `bool` is an int to Python and not a verdict here: `true` would otherwise read as verdict 1.
    return verdict if isinstance(verdict, int) and not isinstance(verdict, bool) else None


def evidence_of(spec: object) -> tuple[str, ...]:
    """The artifacts a command binds to its input ports that take a test result - its evidence, in port
    order. Read off the ports rather than off the port NAME `evidence`, so a product task whose input port
    takes a test result under another name is read too."""
    consumes = getattr(spec, "consumes", None) or {}
    return tuple(name for port in getattr(spec, "ports", ()) or ()
                 if port.direction == "input" and port.accepts == "test-result"
                 for name in consumes.get(port.name, ()))


def refused(evidence: Sequence[str]) -> int:
    """1 when any test result in `evidence` is not written, red or no verdict, saying which and why; else 0.

    Every record is read before answering, because which of them failed is the whole content of the
    answer. The caller runs the release body only on 0.
    """
    root = context.current().root
    reasons: list[str] = []
    for name in evidence:
        path = path_of(name)
        shown = f"'{name}' ({path.relative_to(root) if path.is_relative_to(root) else path})"
        if not path.exists():
            reasons.append(f"{shown} has not been written - the test that produces it has not run here")
            continue
        verdict = _verdict(path) if path.is_file() else None
        if verdict is None:
            reasons.append(f"{shown} holds no verdict - a release reads a JSON record with an integer "
                           f"`verdict`, the one `test:image` writes")
        elif verdict != 0:
            reasons.append(f"{shown} is red: verdict {verdict} - its `runs` say which run failed")
    if reasons:
        log.error("nothing was published: the evidence this release is bound to does not say the test "
                  "passed\n  " + "\n  ".join(reasons))
        return 1
    return 0
