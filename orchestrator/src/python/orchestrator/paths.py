"""simplon's product adapter onto the delivery kernel: derive the repo ROOT + the manifest path and
register ONE ProductContext at import, so kernel code reads them back product-agnostically via
simplon.context.current() and never hardcodes "simplon".

The walk up to the marker, the DELIVERY_* overrides and the fail-loud on a broken checkout are the
KERNEL's (simplon.context.bootstrap). What only this product knows is its name and where this file
sits, so that is all this module says. Extend it to read the manifest's raw build-data sections
(images/volumes/...) through CONTEXT.manifest_data() as your pipeline grows.
"""
from __future__ import annotations

from pathlib import Path

from simplon import context

CONTEXT = context.bootstrap("simplon", Path(__file__).resolve().parent)
ROOT = CONTEXT.root
MANIFEST = CONTEXT.manifest_path
