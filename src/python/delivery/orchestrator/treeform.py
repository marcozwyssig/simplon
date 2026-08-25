"""The new-form command tree (netctl#1469), lowered to the flat form the manifest model validates.

A task is a template; a command is an instance of one; a group is a slot in the CI/CD tree the platform
owns. This module is the whole of that model's front end: it merges a product's tree onto the kernel's,
resolves each command's `task:` into the `impl:` the rest of the loader already understands, and emits
exactly the two structures `_ManifestModel` accepts - a `taxonomy:` mapping and a flat `group path ->
members` mapping.

Lowering rather than replacing is deliberate. `CommandSpec`, `Manifest`, the six validation rules,
`taskgen` and `delivery.cli.assemble` all keep working on shapes they already consume, which is what
lets every migration step be proved by a zero-diff on the product's CLI-surface golden.

Pure functions over plain dicts: no pydantic, no I/O, no import of any body.
"""
from __future__ import annotations

# A group node's own keys. Everything else under a node would be ambiguous, which is why members live
# under `commands:` rather than directly on the node: otherwise `help:` would be a group attribute in one
# place and a command name in another.
NODE_KEYS = ("help", "env_first", "groups", "commands")


def lower(tree: dict, _path: tuple[str, ...] = ()) -> tuple[dict, dict]:
    """A command tree, split into the `taxonomy:` shape and the flat `group path -> members` map.

    The two spellings are not interchangeable and the difference is load-bearing: the taxonomy nests its
    children by BARE name under a `groups:` key, while the flat map keys every group by its DOTTED path.
    A group with no commands still appears in both - the shape exists whether or not anyone has put a
    command in it yet, and an empty member map is what stops it being registered in the CLI.
    """
    taxonomy: dict[str, dict] = {}
    flat: dict[str, dict] = {}
    for name, node in (tree or {}).items():
        node = node or {}
        path = _path + (str(name),)
        shape = {key: node[key] for key in ("help", "env_first") if key in node}
        child_taxonomy, child_flat = lower(node.get("groups") or {}, path)
        if child_taxonomy:
            shape["groups"] = child_taxonomy
        taxonomy[str(name)] = shape
        flat[".".join(path)] = {str(command): dict(spec or {})
                                for command, spec in (node.get("commands") or {}).items()}
        flat.update(child_flat)
    return taxonomy, flat
