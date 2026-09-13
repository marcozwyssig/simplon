"""IS THE COMMITTED GENERATED FILE WHAT REGENERATING PRODUCES? (si#240)

A generated artefact that is committed has two copies of one fact: the source it is generated from, and
the bytes in the tree. They drift, silently, and the drift is only visible to somebody who regenerates -
which is exactly the person who was not going to.

INVENTED TWICE BEFORE THIS, WHICH IS WHY IT IS HERE. biz-cockpit wrote `verify_spec` over its OpenAPI
contract and called it "the CI staleness gate"; this kernel wrote `test_own_completion.py` over its shell
completion. And `6ddecaf` is what happens in the gap: a command was added to `simplon.yaml` without
regenerating `deploy/completions/simplon.bash`, and `main` stood red - with an uncompletable command -
until a person noticed.

THE BORROWED IMPLEMENTATION HAD THIS REPOSITORY'S RECURRING DEFECT IN IT. `git diff --exit-code` over a
path git does not track exits 0. So an artefact that was never committed at all - the mistake this gate
exists to catch, in its most complete form - would have passed green. "Nothing to compare" and "compared
and matched" are one exit code with two meanings, and the fix is the one this repository always uses:
exclude the ambiguous case at the seam. Every entry is checked for being TRACKED before anything is
regenerated, and an untracked one is a failure with its own sentence.

THE SAME DEFECT ONE STEP LATER, and it is the reason `_regenerate`'s return code is read. A regeneration
that FAILED leaves the file exactly as it was, so the diff is empty and a gate that only looked at the
diff would report freshness. The rc is the difference between "regenerated, and it matched" and "did not
regenerate, and nothing changed".

IT REGENERATES INTO THE WORKING TREE, deliberately. Generating into a temporary directory would compare
two files the product's own command never produced side by side - the command writes where it writes, and
a gate that reroutes it is testing something else. A CI checkout is disposable; a developer gets told
that the tree was touched.
"""
from __future__ import annotations

import shlex
from pathlib import Path
from typing import NamedTuple

from simplon import context, log, run

#: The manifest section this gate reads: one entry per generated artefact that is committed.
SECTION = "generated"


class Entry(NamedTuple):
    """One generated artefact: where it lives, and the command that produces it."""

    name: str
    path: str
    by: str


def declared() -> list[Entry]:
    """The `generated:` section, or a refusal naming what it needs."""
    ctx = context.current()
    where = ctx.manifest_path.name
    return entries_of(ctx.manifest_data(), where)


def entries_of(document: dict, where: str) -> list[Entry]:
    """The `generated:` entries of an already-read manifest DOCUMENT."""
    section = document.get(SECTION)
    if not isinstance(section, dict) or not section:
        raise ValueError(
            f"{where} declares no `{SECTION}:` section, so there is nothing to check for staleness. "
            f"Each entry names a committed generated file and the command that produces it: "
            f"`{SECTION}: {{ completion: {{ path: ..., by: support completion }} }}`")
    entries: list[Entry] = []
    for name, spec in section.items():
        if not isinstance(spec, dict):
            raise ValueError(f"{where}'s `{SECTION}: {name}:` is not a mapping ({spec!r}); it needs "
                             f"`path:` and `by:`")
        path = str(spec.get("path", "") or "").strip()
        by = str(spec.get("by", "") or "").strip()
        if not path:
            raise ValueError(f"{where}'s `{SECTION}: {name}:` declares no `path:`, so there is no file "
                             f"to compare")
        if not by:
            raise ValueError(f"{where}'s `{SECTION}: {name}:` declares no `by:`, so nothing says how to "
                             f"regenerate {path}. It is the command a person would type, without the "
                             f"launcher - for example `support completion`")
        entries.append(Entry(name=name, path=path, by=by))
    return entries


def _tracked(root: Path, path: str) -> bool:
    """Whether git tracks this path. The check the borrowed implementation did not have."""
    return run.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", path]).ok


def _regenerate(entry: Entry, root: Path) -> int:
    """Run the product's own regenerating command, in the tree, and return its rc."""
    argv = [f"./{context.current().name}.sh", *shlex.split(entry.by)]
    return run.stream(argv, cwd=str(root))


def _differs(root: Path, path: str) -> bool:
    return not run.run(["git", "-C", str(root), "diff", "--exit-code", "--", path]).ok


def check() -> int:
    """Regenerate every declared artefact and fail if any of them was not what the tree carried.

    Returns 0 when every entry regenerated and matched, 1 otherwise. Every entry is ruled on before the
    verdict - a gate that stopped at the first stale file would hide the second one behind a fix for the
    first.
    """
    entries = declared()
    root = context.current().root
    stale: list[str] = []
    for entry in entries:
        if not _tracked(root, entry.path):
            log.error(f"{entry.name}: {entry.path} is not tracked by git, so nothing could be compared. "
                      f"A generated file this gate rules on has to be committed - an untracked one is "
                      f"the staleness it exists to catch, not an exemption from it")
            stale.append(entry.name)
            continue
        rc = _regenerate(entry, root)
        if rc != 0:
            log.error(f"{entry.name}: `{entry.by}` exited {rc}, so {entry.path} was NOT regenerated and "
                      f"this says nothing about whether it is fresh")
            stale.append(entry.name)
            continue
        if _differs(root, entry.path):
            log.error(f"{entry.name}: {entry.path} is not what `{entry.by}` produces. Run it and commit "
                      f"the result")
            stale.append(entry.name)
    if stale:
        log.warn(f"{len(stale)}/{len(entries)} generated file(s) stale: {', '.join(stale)}")
        return 1
    log.ok(f"all {len(entries)} generated file(s) are what their commands produce")
    return 0
