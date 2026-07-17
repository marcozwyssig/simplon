"""Process-global collector for 'degraded' (non-fatal) conditions surfaced during a bring-up. A degraded
condition is a defect that does not abort the run (an OOB bridge that did not come up, a kernel module
missing, a provisioning step left incomplete): the run still completes, but the verdict reports it and a
strict mode can promote it to a failure.

Process-global so guards and bring-up orchestration accumulate into the SAME list within one process.
When the orchestrator runs its phases as SEPARATE processes, it sets the env var named by
DEGRADED_FILE_ENV to a shared file; add() also appends there and items() unions the file's entries with
this process's in-memory ones, so the final verdict phase sees conditions recorded by earlier phases.
"""
from __future__ import annotations

import os

from platformcore import log

# Env var naming the cross-process degraded file. Product-neutral by default; a product may override this
# module constant at bootstrap if it needs its own name. Both the orchestrator that SETS the file and this
# collector that READS it must agree on the name.
DEGRADED_FILE_ENV = "PLATFORMCORE_DEGRADED_FILE"

_items: list[str] = []


def reset() -> None:
    """Clear the collector at the start of a bring-up."""
    _items.clear()


def add(msg: str) -> None:
    """Record a degraded condition: warn AND remember it for the verdict. Also append to the file named by
    DEGRADED_FILE_ENV when that env var is set, so a phase running as a separate process still surfaces to
    the shared verdict."""
    log.warn(msg)
    _items.append(msg)
    degfile = os.environ.get(DEGRADED_FILE_ENV)
    if degfile:
        with open(degfile, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")


def items() -> list[str]:
    """The degraded conditions for the verdict. When DEGRADED_FILE_ENV is set the bring-up ran its phases
    as separate processes, so union the file's entries (recorded by earlier phases) with this process's
    in-memory ones - else the finish phase's verdict would miss a condition recorded in another phase.
    Deduped, file entries first. With no file set it is the plain in-memory list (single-process path)."""
    degfile = os.environ.get(DEGRADED_FILE_ENV)
    if not degfile or not os.path.exists(degfile):
        return list(_items)
    with open(degfile, encoding="utf-8") as fh:
        file_items = [ln.rstrip("\n") for ln in fh if ln.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for it in (*file_items, *_items):
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out
