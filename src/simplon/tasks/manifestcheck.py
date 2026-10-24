"""`test:manifest-model` (si#522): `firn validate` over this product's manifest, exported fresh, against the
M2 the kernel ships.

A THROWAWAY PROJECT, NOT THE PRODUCT'S. The export and the M2 are staged below the output root as a firn
project of their own: `firn.toml`, `model/<product>.firn`, and the M2 as a path dependency in `m2/` (firn
v0.2.0 reads a dependency outside a project's root, but refuses a model folder outside it, E104; measured
2026-10-24). The product's own `firn.toml` is neither read nor written, so a product with a firn model of
its own (netctl) keeps it. The stage is rebuilt from empty on every run, so an earlier export cannot reach
this verdict.

FRESH, NOT FROM DISK. The model is exported here, exactly as `support manifest model` writes it, so a stale
model on disk can never be validated green.

THE VERDICT IS FIRN'S. Its rc passes through: 0 clean, 1 model wrong, 2 usage, 3 no project, 70 firn's own
fault. A manifest that does not load or export is rc 1 with the reason, and firn never starts.
"""
from __future__ import annotations

import os
import shutil
from importlib.resources.abc import Traversable
from importlib.resources import as_file, files
from pathlib import Path

import typer

from simplon import __version__
from simplon.adapters import docker
from simplon.kernel import log
from simplon.manifest import context, layout, outputs
from simplon.tasks import manifestmodel, toolchain

#: What a product's exported manifest model references (measured over the export of simplon.yaml).
M2_PACKAGES = ("catalogue", "manifest", "pipeline", "vocabulary")
#: Where the stage lives, below the output root.
STAGE = "manifest-check"


def m2_source() -> Traversable:
    """The M2: in an installed simplon the package data the wheel carries (`setup.py` copies it there); in
    a source checkout, which is what an editable install runs, its one source in simplon's firn project."""
    shipped = files("simplon") / "m2" / "simplon"
    if shipped.is_dir():
        return shipped
    checkout = Path(str(files("simplon"))).parent / "firn" / "model" / "simplon"
    return checkout if checkout.is_dir() else shipped


def stage(directory: Path, name: str, text: str, m2: Traversable, version: str) -> str:
    """Rebuild `directory` as the check project; "" when it is staged, else the reason."""
    missing = [package for package in M2_PACKAGES if not (m2 / package).is_dir()]
    if missing:
        return (f"the installed simplon carries no M2 package {', '.join(missing)} at {m2}; "
                f"reinstall simplon")
    shutil.rmtree(directory, ignore_errors=True)
    (directory / "model").mkdir(parents=True)
    (directory / "firn.toml").write_text(
        f'name = "{name}-manifest-check"\nmodel = ["model"]\n\n[dependencies]\nsimplon = {{ path = "m2" }}\n',
        encoding="utf-8")
    (directory / "model" / f"{name}.firn").write_text(text, encoding="utf-8")
    (directory / "m2").mkdir()
    (directory / "m2" / "firn.toml").write_text(
        f'name = "simplon-m2"\nversion = "{version}"\nmodel = ["model"]\n', encoding="utf-8")
    for package in M2_PACKAGES:
        with as_file(m2 / package) as source:
            shutil.copytree(source, directory / "m2" / "model" / "simplon" / package)
    return ""


def _build_root() -> str:
    return layout.declared(context.current().manifest_data()).build_root


def check(ctx: typer.Context, image: str = "", network: str | None = "none") -> int:
    """Export, stage, `firn validate` in the pinned `image`; firn's rc, or 1 with the reason."""
    where = ctx.command_path or "test:manifest-model"
    try:
        name, text = manifestmodel.current()
    except (ValueError, RuntimeError) as exc:
        log.error(f"no model to check: {exc}")
        return 1
    directory = outputs.root() / STAGE
    start = context.current().root / _build_root()
    if not directory.is_relative_to(start):
        log.error(f"the output root {outputs.root()} is outside the build root {start}, where the container "
                  f"starts, so firn could not be started in {directory}")
        return 1
    reason = stage(directory, name, text, m2_source(), __version__)
    if reason:
        log.error(reason)
        return 1
    cwd = os.path.relpath(directory, start).replace(os.sep, "/")
    got = toolchain.invocation(where, image=image, argv=["validate"], workdir="/workspace", env=None,
                               caches=None, network=network, cwd=cwd, extra=[])
    if got is None:
        return 1
    rc = docker.run_container(*got).rc
    if rc == 0:
        log.ok(f"firn found the model of {name} valid against the M2 of simplon {__version__}")
    return rc
