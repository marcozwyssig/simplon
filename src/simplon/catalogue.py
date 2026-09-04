"""The delivery kernel's task catalogue: the coordinate space between the platform and a *ctl product
(netctl#1437).

Today a product's manifest points `impl:` at a kernel MODULE PATH, so moving a body inside the kernel
breaks the product's manifest. A coordinate `<namespace>:<name>` is the indirection: the catalogue maps
it to whatever module currently holds the body, and the product never names one.

The kernel generates no module of its own. It has no CLI - only bodies and this registry. Only a product
generates, because only a product has a surface.

Deliberately small. It is a dict of coordinates with two lookups and four rejections, not a second
manifest loader: the value shape is `_CommandSpecModel`, the very model the manifest already validates a
command declaration with, so a coordinate cannot come to mean something a manifest entry could not.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import yaml

from delivery.orchestrator.manifest import _CommandSpecModel

# The catalogue ships beside the delivery block rather than inside the python package: it is DATA a
# product reads, the same way a product's own manifest is.
# .../lib/platform/src/delivery/src/python/delivery/catalogue.py -> .../lib/platform/delivery.yaml
DEFAULT_PATH = Path(__file__).resolve().parents[5] / "delivery.yaml"


class Catalogue(NamedTuple):
    """What the platform offers a product: the task coordinates, keyed `<namespace>:<name>`, and the
    shape of the command tree they live in.
    """

    tasks: dict[str, dict]
    # `taxonomy` is `groups`'s predecessor (netctl#1444, spec step 7, superseded by netctl#1469). It
    # survives only for a catalogue that has not yet moved to a command tree; the two never both carry
    # a group.
    taxonomy: dict[str, dict] = {}
    # The kernel's own command tree (netctl#1469): the groups that exist, and the baseline commands the
    # platform places in them. Every `*ctl` product runs the same build -> test -> release -> deploy ->
    # monitor loop, so declaring it once here beats each product restating it. A product contributes
    # MEMBERS to those groups and never redeclares their shape; it may still declare a group of its own,
    # which is the exception and visible as one.
    groups: dict[str, dict] = {}

    def resolve(self, coordinate: str) -> dict:
        """The declaration a coordinate names, or a ValueError listing what the namespace does offer."""
        if coordinate in self.tasks:
            return self.tasks[coordinate]
        namespace = coordinate.split(":", 1)[0]
        offered = sorted(self.namespace(namespace)) if self._has(namespace) else []
        raise ValueError(
            f"the catalogue offers no task '{coordinate}'" +
            (f" - namespace '{namespace}' offers: {', '.join(offered)}" if offered else ""))

    def namespace(self, name: str) -> dict[str, dict]:
        """Every task in one namespace, keyed by its bare name. A namespace the catalogue does not have
        is a ValueError rather than an empty map: an `import:` typo would otherwise offer nothing at all
        and read, at the point of use, as if the platform simply had no such tasks."""
        if not self._has(name):
            raise ValueError(f"the catalogue has no namespace '{name}' "
                             f"- it offers: {', '.join(self.namespaces())}")
        prefix = f"{name}:"
        return {key[len(prefix):]: spec for key, spec in self.tasks.items() if key.startswith(prefix)}

    def namespaces(self) -> list[str]:
        return sorted({key.split(":", 1)[0] for key in self.tasks})

    def _has(self, name: str) -> bool:
        return any(key.startswith(f"{name}:") for key in self.tasks)


def loads(text: str) -> Catalogue:
    """Parse a catalogue from YAML, rejecting a declaration a manifest could not have made either."""
    data = yaml.safe_load(text) or {}
    tasks = data.get("tasks") or {}
    if not isinstance(tasks, dict):
        raise ValueError("catalogue 'tasks' must be a mapping of '<namespace>:<name>' to a declaration")
    taxonomy = data.get("taxonomy") or {}
    if not isinstance(taxonomy, dict):
        raise ValueError("catalogue 'taxonomy' must be a mapping of group name to its declaration")
    groups = data.get("groups") or {}
    if not isinstance(groups, dict):
        raise ValueError("catalogue 'groups' must be a mapping of group name to its declaration")
    out: dict[str, dict] = {}
    for coordinate, spec in tasks.items():
        # A bare `commit:` has no coordinate space, so two namespaces could not both offer one and a
        # product could not say which it meant.
        if ":" not in str(coordinate) or str(coordinate).count(":") != 1:
            raise ValueError(f"catalogue task '{coordinate}' is not a '<namespace>:<name>' coordinate")
        namespace, name = str(coordinate).split(":", 1)
        if not namespace or not name:
            raise ValueError(f"catalogue task '{coordinate}' is not a '<namespace>:<name>' coordinate")
        model = _CommandSpecModel.model_validate(spec or {})
        if not model.impl:
            # The catalogue is where a body LIVES. An entry without one defines nothing, and a product
            # importing it would resolve a coordinate to no code at all.
            raise ValueError(f"catalogue task '{coordinate}' declares no impl")
        out[str(coordinate)] = dict(spec or {})
    return Catalogue(tasks=out, taxonomy=taxonomy, groups=groups)


def load(path: Path | str = DEFAULT_PATH) -> Catalogue:
    """Read the catalogue from disk."""
    return loads(Path(path).read_text(encoding="utf-8"))
