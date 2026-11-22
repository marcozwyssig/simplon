"""What the derived CI workflow of a product contains, decided from its manifest (si#858).

THIS MODULE DECIDES which leaves the workflow runs, in which order, and the model instances that
describe it (spec docs/superpowers/specs/2026-11-22-derived-workflows-design.md, sections 4 and 5).
It LEAVES TO `workflowgen` the text: how an instance is written out as a GitHub workflow file. The
split keeps the decision testable without parsing YAML and the rendering free of manifest knowledge.

This first part reads the one product value the decision needs before any leaf is chosen: the
machine the jobs run on.
"""
from __future__ import annotations

from collections.abc import Mapping

from simplon.manifest import context, runners


def runner_of(data: Mapping[str, object]) -> tuple[runners.Runner, tuple[str, ...]]:
    """The machine kind and the `runs-on:` labels for the product's top-level `runner:` section.

    An absent section is the normal case and means `github-ubuntu`; `runners.resolve` owns every
    refusal (an unknown kind, a self-hosted kind with no label), so this only reads and delegates.
    The key is the literal `"runner"` and not `runners.KEY`: the refusal census and the firn coverage
    test find a section by its literal key (si#435).
    """
    return runners.resolve(data.get("runner"), "runner:")


def runner() -> tuple[runners.Runner, tuple[str, ...]]:
    """`runner_of` for the registered product.

    The document is fetched and HANDED ON rather than read here: the refusal census walks what the
    kernel passes `manifest_data()` to, so this is what makes `runner:` a section the kernel reads
    (and `Product.runner` a modelled one) without this module being excused by hand.
    """
    return runner_of(context.current().manifest_data())
