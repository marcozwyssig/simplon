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


def merge(kernel: dict, product: dict, _path: tuple[str, ...] = ()) -> dict:
    """The product's tree merged onto the kernel's.

    Three outcomes, and the first is the group lock: a PATH the kernel does not declare is an error, a
    command NAME it does not declare is an addition, and a name it does declare is a refinement. The lock
    is therefore the structure rather than a check over it - there is one tree, so there is no second way
    to bring a group into existence (this replaces netctl#1462's separate enforcement).
    """
    out = {name: dict(node or {}) for name, node in (kernel or {}).items()}
    for name, node in (product or {}).items():
        name, node = str(name), dict(node or {})
        path = _path + (name,)
        if name not in out:
            raise ValueError(
                f"groups entry '{'.'.join(path)}' names a group the platform's tree does not declare. "
                f"The platform owns which groups exist, so that the same groups and the same general "
                f"tasks are there in every product. Available here: "
                f"{', '.join(sorted(out)) or '(none)'}. Either put these commands in one of those, or "
                f"declare the new group in the platform's `groups:` - once, for everybody")
        base = out[name]
        merged = dict(base)
        for key, value in node.items():
            if key == "groups":
                merged["groups"] = merge(base.get("groups") or {}, value, path)
            elif key == "commands":
                merged["commands"] = _merge_commands(base.get("commands") or {}, value,
                                                     ".".join(path))
            else:
                merged[key] = value
        out[name] = merged
    return out


def _merge_commands(base: dict, extra: dict, where: str) -> dict:
    """A group's members, with the product's refinements folded in per KEY rather than per node.

    Per-key matters: netctl pins `tasks generate`'s target with a `with:` and expects to keep the
    kernel's `params:` for `check`. Replacing the whole node would silently drop it.
    """
    out = {str(name): dict(spec or {}) for name, spec in (base or {}).items()}
    for name, spec in (extra or {}).items():
        name, spec = str(name), dict(spec or {})
        inherited = out.get(name)
        if inherited is None:
            out[name] = spec
            continue
        if ("depends_on" in spec and "task" in inherited) or ("task" in spec and "depends_on" in inherited):
            raise ValueError(
                f"command '{where} {name}' is declared as one kind of command and refined as another. A "
                f"refinement may set help, params, hidden, with and task; moving a command between "
                f"task-backed and aggregate is a different command wearing the same name - give it one")
        out[name] = {**inherited, **spec}
    return out
