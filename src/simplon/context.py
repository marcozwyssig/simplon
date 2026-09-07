"""ProductContext - how a product hands its ROOT + manifest to the delivery kernel (netctl#592 Train B).

The kernel must never hardcode a product name or a product's on-disk layout: "gleiche Maschine, anderer
Katalog". A product's paths adapter - `orchestrator/paths.py` in every consumer measured (#51) - DERIVES
its repo root and manifest path, builds ONE ProductContext and registers it at import. Normally through
`bootstrap()` below, which is the walk plus the `set_current()` in one line; netctl still spells the two
out by hand, which is the older shape and does the same thing.
Kernel code that needs the product root or its manifest reads it back through `current()`, so it stays
product-agnostic - the coupling flows product -> kernel via this seam, never the reverse.

Resolution honours two kernel-owned env vars (the DELIVERY_* namespace, netctl#592 decision 5), which
OVERRIDE the product-derived defaults:
  - ``DELIVERY_PRODUCT_ROOT`` - the repo root (a relocated checkout, or a test harness pointing at a
    fixture tree);
  - ``DELIVERY_MANIFEST``     - the manifest file path.
Product toggles keep their own ``<PRODUCT>_*`` namespace and never leak in here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from simplon.orchestrator.manifest import Manifest
from simplon.orchestrator.manifest import load as _load_manifest

ROOT_ENV = "DELIVERY_PRODUCT_ROOT"
MANIFEST_ENV = "DELIVERY_MANIFEST"


@dataclass(frozen=True)
class ProductContext:
    """One product's identity for the kernel: its name, repo root and manifest path. Immutable; built by
    the product's paths adapter and registered once via `set_current()`."""

    name: str
    root: Path
    manifest_path: Path

    def manifest_data(self) -> dict:
        """The RAW manifest mapping (``yaml.safe_load``), for the product's OWN build-data sections that
        the CLI engine ignores (image names, cache volumes, ...). Fails loudly with a clear RuntimeError so
        a missing/corrupt manifest never surfaces as a bare traceback deep in a build/lab command."""
        try:
            return yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise RuntimeError(f"simplon: cannot read manifest {self.manifest_path}: {exc}") from exc

    def manifest(self) -> Manifest:
        """The parsed + validated command manifest the CLI engine assembles the product's CLI from
        (delegates to ``simplon.orchestrator.manifest.load``).

        The kernel's task CATALOGUE is passed in, and it is not optional in practice: it carries both the
        coordinate space a command names instead of a module path (`task: "vcs:commit"`, netctl#1437) and
        the command TREE every product's groups hang off (netctl#1469). Without it a product would declare
        its own loop and reach no platform body at all.

        Imported lazily so this module keeps no import-time dependency on the catalogue, which itself
        imports the manifest models.
        """
        from simplon import catalogue

        return _load_manifest(self.manifest_path.read_text(encoding="utf-8"),
                              catalogue=catalogue.load())

    @classmethod
    def resolve(cls, name: str, root: Path, manifest_path: Path) -> "ProductContext":
        """Build a context, letting ``DELIVERY_PRODUCT_ROOT`` / ``DELIVERY_MANIFEST`` override the
        product-derived defaults. With neither env var set (the normal case) the result is exactly the
        product's own derivation, so the default UX is byte-identical."""
        env_root = os.environ.get(ROOT_ENV, "").strip()
        env_manifest = os.environ.get(MANIFEST_ENV, "").strip()
        return cls(
            name=name,
            root=Path(env_root) if env_root else root,
            manifest_path=Path(env_manifest) if env_manifest else manifest_path,
        )


_current: ProductContext | None = None


def shim(product: str) -> str:
    """The launcher FILE a product is driven through, as it is named on disk: `<product>.sh`.

    ONE spelling, in one place, because three things have to agree about it and two of them are read by
    something other than a human: the usage line Click prints (`simplon.cli.main` passes `launcher()` as
    `prog_name`), the `run:` line a generated workflow carries (`simplon.workflowgen.launcher`), and the
    command word a generated shell completion registers on (`simplon.completiongen`). A second spelling
    anywhere would be a completion registered on a name the usage line does not mention.

    THE BASENAME, not the typed path, and that is what the completion needs: measured on bash 5.3.9, a
    compspec registered for `simplon.sh` is what answers for `./simplon.sh` and for an absolute path too
    - bash falls back to the portion following the final slash when the full pathname has no compspec of
    its own (bash manual 5.3.9, Programmable Completion).

    `<product>.cmd` is the Windows entry point and is deliberately NOT derived here: nothing in this
    kernel registers a PowerShell completion or prints a `.cmd` usage line, and inventing a name for a
    mechanism that does not exist would be a second source for nothing.
    """
    return f"{product}.sh"


def launcher(product: str) -> str:
    """How a user types the product in a checkout: `./<product>.sh`.

    The `./` is not decoration. The launcher is not on `PATH` - it lives in the checkout and provisions
    the venv the CLI runs in - so a usage line or an error message that omitted it would hand somebody a
    line that does not dispatch, which is exactly the defect si#58 found in Click's derived
    `python -m orchestrator`.
    """
    return f"./{shim(product)}"


def set_current(ctx: ProductContext) -> ProductContext:
    """Register the process' product context (called once by the product's paths adapter at import) and
    return it, so the adapter can `CONTEXT = context.set_current(context.ProductContext.resolve(...))`."""
    global _current
    _current = ctx
    return ctx


def current() -> ProductContext:
    """The registered product context, or a clear RuntimeError when the product's paths adapter has not
    imported yet (which is what registers it) - never a silent None the kernel would trip over later."""
    if _current is None:
        raise RuntimeError(
            "simplon: no ProductContext registered; the product's paths adapter must call "
            "simplon.context.set_current(...) at import before the kernel reads the context")
    return _current


def bootstrap(product: str, start: Path, marker: str = "") -> ProductContext:
    """Derive a product's repo ROOT by walking up from `start` to the directory holding `marker`
    (default `<product>.yaml`), build the context and register it - the whole of what every scaffolded
    `orchestrator/paths.py` did in ~40 lines.

    The walk, not a fixed parent depth: an adapter package that moves deeper in the tree (biz-cockpit's
    sits under `deploy/provision/`) then needs no hand-edit. `start` is the CALLER's file location, which
    is the one thing the kernel cannot know - a product passes `Path(__file__).resolve().parent`.

    Fails loudly when the marker is never found, so a broken or partial checkout is caught HERE, at
    import, rather than as a wrong path in a command halfway through a deployment. The DELIVERY_*
    overrides still apply, through `resolve`.
    """
    name = marker or f"{product}.yaml"
    for candidate in (start, *start.parents):
        if (candidate / name).is_file():
            return set_current(ProductContext.resolve(product, candidate, candidate / name))
    raise RuntimeError(
        f"{product}: cannot locate '{name}' walking up from {start}; is the checkout intact?")
