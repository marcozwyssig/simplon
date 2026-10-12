"""A YAML loader that refuses a key written twice in one mapping (si#344 B2).

PyYAML keeps the LAST of two equal keys and drops the first without a word - which is how cleon's manifest
carried `release:` and `support:` twice, and why `simplon.tasks.migrate` keeps a line accounting at all. A
duplicate key is not valid YAML (the keys of a mapping are unique), so this raises the parser's own
`ConstructorError`: every caller that already reports a YAMLError with its line and column - the loader's
"is not valid YAML" diagnosis first among them - reports this one too, with the key and both lines, and the
refusal census gains no raise site.

A merge key (`<<: *base`) is not a duplicate: a key written beside it overrides the merged one on purpose.
"""
from __future__ import annotations

from collections.abc import Hashable
from typing import Any

import yaml
from yaml.constructor import ConstructorError, SafeConstructor
from yaml.nodes import MappingNode, ScalarNode

MERGE_TAG = "tag:yaml.org,2002:merge"


class UniqueKeyLoader(yaml.SafeLoader):
    """`yaml.SafeLoader`, refusing a scalar key one mapping writes twice."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: dict[Hashable, ScalarNode] = {}
        for key_node, _ in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.tag == MERGE_TAG:
                continue
            # The CONSTRUCTED key, not the spelling: `yes:` and `true:` are both True, and YAML keeps only
            # the second of them exactly as it does for two `true:` (measured, review finding M4).
            key = key_of(key_node)
            if key in seen:
                first = seen[key]
                spelled = "" if first.value == key_node.value else f", as `{first.value}:`"
                raise ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found `{key_node.value}:` a second time (first on line {first.start_mark.line + 1}"
                    f"{spelled}); YAML would keep only this copy, so the first one is lost", key_node.start_mark)
            seen[key] = key_node
        return super().construct_mapping(node, deep=deep)


def key_of(node: ScalarNode) -> Hashable:
    """The key YAML constructs from a scalar key node - the value two keys collide on."""
    value: Hashable = SafeConstructor().construct_object(node)
    return value


def load(text: str) -> object:
    """`yaml.safe_load(text)`, refusing a duplicate key."""
    return yaml.load(text, Loader=UniqueKeyLoader)
