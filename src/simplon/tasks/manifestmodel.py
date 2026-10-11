"""`support manifest model` (si#346, spec D.2): this product's validated manifest, written as a firn model."""
from __future__ import annotations

import os
from pathlib import Path

from simplon import context, log, manifestmodel, outputs


def _load():
    ctx = context.current()
    return ctx.name, ctx.manifest(), ctx.manifest_data()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def model(output: str = "") -> int:
    """Write the model; rc 1 and no new file when the manifest is refused, cannot be read or modelled, or
    the write fails.

    The outcomes stay apart (spec D.2): a model that was written is rc 0, anything else is rc 1 with the
    reason named - "no model because it is broken" must never read as "nothing to model". The file is
    written beside its target and renamed onto it, so a failed write leaves no partial `.firn`. A model
    from an EARLIER run is not removed by a refused run: it survives, stale, and the rc is what says so.
    """
    try:
        name, mf, document = _load()
        text = manifestmodel.export(mf, document, name, manifestmodel.KERNEL_SECTIONS)
    except (ValueError, RuntimeError) as exc:  # ModelExportError and every load refusal are ValueErrors;
        # an unreadable or corrupt manifest is the RuntimeError `manifest_data()` raises
        log.error(f"no model written: {exc}")
        return 1
    path = Path(output) if output else outputs.root() / "model" / f"{name}.firn"
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(tmp, text)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:  # the directory itself is the problem; the reason logged below is the one that matters
            pass
        log.error(f"no model written: cannot write {path}: {exc}")
        return 1
    log.ok(f"wrote the model of {name} to {path}")
    return 0
