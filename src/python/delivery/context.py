"""ProductContext - how a product hands its ROOT + manifest to the delivery kernel (netctl#592 Train B).

The kernel must never hardcode a product name or a product's on-disk layout: "gleiche Maschine, anderer
Katalog". A product's paths adapter (netctl's `orchestrator.paths`, infractl's equivalent) DERIVES its
repo root and manifest path, builds ONE ProductContext, and registers it via `set_current()` at import.
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

from delivery.orchestrator.manifest import Manifest
from delivery.orchestrator.manifest import load as _load_manifest

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
            raise RuntimeError(f"delivery: cannot read manifest {self.manifest_path}: {exc}") from exc

    def manifest(self) -> Manifest:
        """The parsed + validated command manifest the CLI engine assembles the product's CLI from
        (delegates to ``delivery.orchestrator.manifest.load``)."""
        return _load_manifest(self.manifest_path.read_text(encoding="utf-8"))

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
            "delivery: no ProductContext registered; the product's paths adapter must call "
            "delivery.context.set_current(...) at import before the kernel reads the context")
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
