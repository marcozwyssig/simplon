"""The eight frozen manifests (fixtures/manifests), as their products hand them to the migration.

ONE hand edit, and it is the product's, not the kernel's. cleon's `updatesite` is published by cleon's own
code (`orchestrator.cli:publish_updatesite`), so no catalogue coordinate says which kind it is, and the
migration refuses it by name (si#344 B2, decision 5). cleon writes `kind: directory` itself; this writes it
the same way, in memory. The fixture file stays frozen (README: "Do not refresh these files").
"""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "manifests"

#: product -> (the anchor, what the product's own edit makes of it)
HAND_EDITS = {
    "cleon": ("  updatesite:\n", "  updatesite:\n    kind: directory\n"),
}


def text(product: str) -> str:
    """The fixture's text, with the product's own hand edit applied when it has one."""
    raw = (FIXTURES / f"{product}.yaml").read_text(encoding="utf-8")
    if product not in HAND_EDITS:
        return raw
    anchor, edited = HAND_EDITS[product]
    assert raw.count(anchor) == 1, f"{product}: the hand edit's anchor {anchor!r} is not there exactly once"
    return raw.replace(anchor, edited)
