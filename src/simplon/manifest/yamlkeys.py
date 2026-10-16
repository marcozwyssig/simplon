"""A YAML loader that refuses a key written twice in one mapping (si#344 B2).

PyYAML keeps the LAST of two equal keys and drops the first without a word - which is how cleon's manifest
carried `release:` and `support:` twice, and why `simplon.tasks.migrate` keeps a line accounting at all.

A REFUSAL OF ITS OWN, NOT A PARSE ERROR (ruling T4a). The document parses; what it says is ambiguous,
because YAML loses the first copy silently and the kernel cannot tell a stale edit from a deliberate
repeat. So the loader raises `DuplicateKeyError` - a `ConstructorError`, so a caller that only knows
YAMLError still reports it with its line - and `manifest.load` answers it with a sentence and a census
entry of its own rather than under "is not valid YAML", whose reason ("a document that does not parse")
is false here: cleon's manifest, carrying two identical copies, produced a working product.

ONE CHECK, OVER THE COMPOSED GRAPH (review finding I1). The duplicates are found before construction,
on the nodes as written: PyYAML's `flatten_mapping` rewrites a mapping node IN PLACE when it is merged,
so a check made during construction saw a merged-in key and the override beside it as two written
copies whenever the mapping was merged elsewhere first. `duplicates` is also the walk `manifest migrate`
cuts copies by, so the loader and the migration cannot disagree on what a duplicate is.

A merge key (`<<: *base`) is not a duplicate: a key written beside it overrides the merged one on purpose.
"""
from __future__ import annotations

from collections.abc import Hashable
from typing import Any, NamedTuple

import yaml
from yaml.constructor import ConstructorError, SafeConstructor
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

MERGE_TAG = "tag:yaml.org,2002:merge"


class Duplicate(NamedTuple):
    """A scalar key one mapping writes twice: where (dotted path), the mapping, and both key nodes."""
    path: str
    mapping: MappingNode
    first: ScalarNode
    second: ScalarNode


class DuplicateKeyError(ConstructorError):
    """A key written twice in one mapping. `problem` names the key and the first copy's line;
    `problem_mark` is the second copy."""


def duplicates(root: Node | None) -> list[Duplicate]:
    """Every scalar key one mapping writes twice, in document order, over the COMPOSED graph. Each node is
    visited once, where it is first written: an alias is the anchored node itself, already checked there."""
    found: list[Duplicate] = []
    visited: set[int] = set()

    def walk(node: Node | None, path: str) -> None:
        if node is None or id(node) in visited:
            return
        visited.add(id(node))
        if isinstance(node, MappingNode):
            seen: dict[Hashable, ScalarNode] = {}
            for key, value in node.value:
                if isinstance(key, ScalarNode) and key.tag != MERGE_TAG:
                    where = f"{path}.{key.value}" if path else str(key.value)
                    # The CONSTRUCTED key, not the spelling: `yes:` and `true:` are both True, and YAML
                    # keeps only the second of them exactly as it does for two `true:` (review finding M4).
                    constructed = key_of(key)
                    if constructed in seen:
                        found.append(Duplicate(where, node, seen[constructed], key))
                    else:
                        seen[constructed] = key
                    walk(value, where)
                else:
                    walk(value, path)
        elif isinstance(node, SequenceNode):
            for item in node.value:
                walk(item, path)

    walk(root, "")
    return found


class UniqueKeyLoader(yaml.SafeLoader):
    """`yaml.SafeLoader`, refusing a scalar key one mapping writes twice."""

    def construct_document(self, node: Node) -> Any:
        found = duplicates(node)
        if found:
            first = found[0]
            spelled = "" if first.first.value == first.second.value else f", as `{first.first.value}:`"
            raise DuplicateKeyError(
                "while constructing a mapping", first.mapping.start_mark,
                f"found `{first.second.value}:` a second time (first on line {first.first.start_mark.line + 1}"
                f"{spelled}); YAML would keep only this copy, so the first one is lost", first.second.start_mark)
        return super().construct_document(node)


def key_of(node: ScalarNode) -> Hashable:
    """The key YAML constructs from a scalar key node - the value two keys collide on."""
    value: Hashable = SafeConstructor().construct_object(node)
    return value


def load(text: str) -> object:
    """`yaml.safe_load(text)`, refusing a duplicate key."""
    return yaml.load(text, Loader=UniqueKeyLoader)
