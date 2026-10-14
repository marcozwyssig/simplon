"""The delivery kernel's task catalogue: the coordinate space between the platform and a *ctl product
(netctl#1437).

Today a product's manifest points `impl:` at a kernel MODULE PATH, so moving a body inside the kernel
breaks the product's manifest. A coordinate `<namespace>:<name>` is the indirection: the catalogue maps
it to whatever module currently holds the body, and the product never names one.

The kernel is a product of itself too (simplon.yaml, deploy/orchestrator/): its own build/test/support
commands are assembled from this same catalogue, exactly like any other *ctl product. That reverses an
earlier rule ("only a product generates, because only a product has a surface") - the reversal exists
because a spike found this catalogue resolved by walking five directories up to the old monorepo's
root, correct only while vendored and silently wrong once installed. Nobody had noticed, because
nobody had ever run the kernel the way a consumer does. A tool never used in its own house rots unseen.

Deliberately small. It is a dict of coordinates with two lookups and four rejections, not a second
manifest loader: the value shape is `_CommandSpecModel`, the very model the manifest already validates a
command declaration with, so a coordinate cannot come to mean something a manifest entry could not.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import yaml

from simplon.domain.manifest import _CommandSpecModel

# The catalogue file belongs to the kernel, so it travels INSIDE the package. This used to read
# parents[5] -- a reach five levels up to the repo root, correct only as long as the code was
# vendored rather than installed.
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "catalogue.yaml"  # the package root, where the package data lives (si#399)


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
    # The artifact kinds (spec B.2): each kind mapped to the one kind it refines, "" for the root. The
    # section is GENERATED from simplon's firn model (si#344 B1); a product cannot declare kinds.
    kinds: dict[str, str] = {}

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
        is a ValueError rather than an empty map: a namespace typo would otherwise offer nothing at all
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


def _kinds(data: dict) -> dict[str, str]:
    """The `kinds:` section as {kind: parent}. Absent is a catalogue without kinds (every stub the suite
    builds); present-but-empty is what firn writes when its selector answers nothing, so it is refused."""
    if "kinds" not in data:
        return {}
    raw = data["kinds"]
    if raw is None or raw == {}:
        raise ValueError("catalogue 'kinds' is declared but empty")
    if not isinstance(raw, dict):
        raise ValueError("catalogue 'kinds' must be a mapping of kind name to its declaration")
    out: dict[str, str] = {}
    for kind, spec in raw.items():
        if spec is not None and not isinstance(spec, dict):
            raise ValueError(f"catalogue kind '{kind}' must be a mapping, got {spec!r}")
        parent = (spec or {}).get("refines", "")
        if not isinstance(parent, str):
            raise ValueError(f"catalogue kind '{kind}' must refine exactly one kind, got {parent!r}")
        out[str(kind)] = parent
    for kind, parent in out.items():
        if parent and parent not in out:
            raise ValueError(f"catalogue kind '{kind}' refines '{parent}', which the catalogue does not declare")
    # The circle first: a circle has no root either, and "no root" would send the reader to the wrong line.
    for kind in out:
        seen, at = set(), kind
        while out[at]:
            if at in seen:
                raise ValueError(f"catalogue kinds refines in a circle through '{kind}'")
            seen.add(at)
            at = out[at]
    roots = [kind for kind, parent in out.items() if not parent]
    if len(roots) != 1:
        raise ValueError(f"catalogue kinds need exactly one root kind, found {roots}")
    return out


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
    kinds = _kinds(data)
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
    return Catalogue(tasks=out, taxonomy=taxonomy, groups=groups, kinds=kinds)


def load(path: Path | str = DEFAULT_PATH) -> Catalogue:
    """Read the catalogue from disk."""
    cat = loads(Path(path).read_text(encoding="utf-8"))
    # Here and not in loads(): the hazard is the shipped file (firn leaves it task-less with rc 0 when a
    # region marker goes missing); group-only stubs built through loads() are legitimate test catalogues.
    if not cat.tasks:
        raise ValueError(f"catalogue {path} declares no tasks - a catalogue that offers nothing is a broken "
                         "file, not an empty platform")
    return cat
