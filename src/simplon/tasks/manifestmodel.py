"""`support manifest model` (si#346, spec D.2): this product's validated manifest, written as a firn model."""
from __future__ import annotations

from pathlib import Path

from simplon import context, log, manifestmodel, outputs


def _load():
    ctx = context.current()
    return ctx.name, ctx.manifest(), ctx.manifest_data()


def model(output: str = "") -> int:
    """Write the model; rc 1 and no file when the manifest is refused or cannot be modelled.

    The two outcomes stay apart (spec D.2): a model that was written is rc 0, a manifest that was refused
    is rc 1 with the refusal named - "no model because it is broken" must never read as "nothing to model".
    """
    try:
        name, mf, document = _load()
        text = manifestmodel.export(mf, document, name, manifestmodel.KERNEL_SECTIONS)
    except ValueError as exc:  # ModelExportError is a ValueError; so is every load refusal
        log.error(f"no model written: {exc}")
        return 1
    path = Path(output) if output else outputs.root() / "model" / f"{name}.firn"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log.ok(f"wrote the model of {name} to {path}")
    return 0
