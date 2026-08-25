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
        path = _path + (str(name),)
        if node is not None and not isinstance(node, dict):
            raise ValueError(
                f"group '{'.'.join(path)}' is not a mapping: found {type(node).__name__} instead. A "
                f"group node's value must be a mapping with its own keys (help, env_first, groups, "
                f"commands) - check the indentation under this entry")
        node = node or {}
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
        name = str(name)
        path = _path + (name,)
        if node is not None and not isinstance(node, dict):
            raise ValueError(
                f"group '{'.'.join(path)}' is not a mapping: found {type(node).__name__} instead. A "
                f"group node's value must be a mapping with its own keys (help, env_first, groups, "
                f"commands) - check the indentation under this entry")
        node = dict(node or {})
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
            elif key in NODE_KEYS:
                merged[key] = value
            else:
                raise ValueError(
                    f"group '{'.'.join(path)}' declares unknown key '{key}'. A group node's keys are "
                    f"help, env_first, groups and commands - rename it, or if this is meant to be a "
                    f"command, move it under `commands:`")
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


# Keys a task supplies to every command that instantiates it, where the command does not say otherwise.
# `impl` is not here because it is never the command's to declare; `with` is not here because a template
# that pinned a value would not be a template.
INHERITED = ("help", "passthrough_args")


def resolve(flat: dict, product_tasks: dict, catalogue_tasks: dict) -> dict:
    """Every command's `task:` replaced by the template it names.

    ONE resolution function, two sources: a name CONTAINING a colon is a catalogue coordinate, a name
    without one is a task defined in the manifest doing the referring. The two name spaces cannot
    intersect, so nothing shadows anything and there is no precedence rule to remember.
    """
    out: dict[str, dict] = {}
    for path, members in (flat or {}).items():
        resolved: dict[str, dict] = {}
        for name, spec in (members or {}).items():
            resolved[str(name)] = _resolve_one(dict(spec or {}), f"{path} {name}",
                                               product_tasks, catalogue_tasks)
        out[str(path)] = resolved
    return out


def _resolve_one(spec: dict, where: str, product_tasks: dict, catalogue_tasks: dict) -> dict:
    if "impl" in spec:
        raise ValueError(
            f"command '{where}' declares `impl:`. A command is an instance of a task: declare the body "
            f"once under `tasks:` and point this command at it with `task:`")
    ref = spec.pop("task", None)
    if ref is None:
        if not spec.get("depends_on"):
            raise ValueError(
                f"command '{where}' declares neither `task:` nor `depends_on:`. A command either "
                f"instantiates a task or is an aggregate that plans other commands")
        return spec
    if spec.get("depends_on"):
        raise ValueError(
            f"command '{where}' declares both `task:` and `depends_on:`. A command either instantiates "
            f"a task or plans other commands, never both - split it into two")

    ref = str(ref)
    source, kind = (catalogue_tasks, "the platform catalogue") if ":" in ref else (product_tasks,
                                                                                  "this manifest")
    if ref not in (source or {}):
        offered = ", ".join(sorted(source or {})) or "(none)"
        raise ValueError(
            f"command '{where}' names no task: '{ref}' is not declared by {kind}. A name with a colon "
            f"is a platform coordinate, a name without one is a task in this manifest's `tasks:`. "
            f"Available there: {offered}")

    template = dict((source or {})[ref])
    out = {"impl": template["impl"], **spec}
    for key in INHERITED:
        if key not in out and key in template:
            out[key] = template[key]
    params = {**(template.get("params") or {}), **(spec.get("params") or {})}
    pinned = sorted(set(spec.get("with") or {}) & set(params))
    if pinned:
        raise ValueError(
            f"command '{where}' pins {', '.join(pinned)} with `with:` and also declares `params:` for "
            f"it. A pinned parameter is off the command line, so its presentation renders nowhere - "
            f"drop the `params:` entry, or drop the pin if the user should still be able to set it")
    if params:
        out["params"] = params
    return out


def is_new_form(groups: dict) -> bool:
    """Whether a `groups:` block is a command TREE rather than the old group -> member mapping.

    A node that declares any of the four node keys is a tree node; a node whose keys are all command
    names is an old-form group. Total in practice, and checked before this rule shipped: no group member
    in netctl.yaml or infractl.yaml is named `help`, `env_first`, `groups` or `commands`.
    """
    return any(isinstance(node, dict) and any(key in node for key in NODE_KEYS)
               for node in (groups or {}).values())


def check_no_stale_import(data: dict) -> None:
    """Reject an `import:` section in a new-form manifest (netctl#1469).

    `import:` made catalogue coordinates AVAILABLE so a product could place them. The platform now
    places the general ones itself and a command names any other coordinate directly, so the section has
    no meaning - and a section with no meaning that loads without complaint is how a product comes to
    believe it imported something.
    """
    if data.get("import"):
        raise ValueError(
            "`import:` has no meaning in a manifest that declares a command tree: the platform places "
            "the general commands itself, and a command names any other task directly with "
            "`task: \"<namespace>:<name>\"`. Delete the section")


def check_every_task_is_used(flat: dict, product_tasks: dict) -> None:
    """Reject a task this manifest declares and no command in it instantiates.

    Scoped to the PRODUCT on purpose. The kernel's `tasks:` is an offer - it deliberately declares more
    than its own `groups:` places, because a task needing product data (a `nexus:` section, a running
    lab) must not become a baseline command that dies on its first line.
    """
    used = {str(spec.get("task")) for members in (flat or {}).values()
            for spec in (members or {}).values() if spec.get("task")}
    orphans = sorted(name for name in (product_tasks or {}) if name not in used)
    if orphans:
        raise ValueError(
            f"task '{orphans[0]}' is declared and no command instantiates it"
            + (f" (also: {', '.join(orphans[1:])})" if len(orphans) > 1 else "")
            + ". A template nobody uses is a dead declaration: add a command for it under `groups:`, or "
              "delete it")
