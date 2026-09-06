"""The command tree (netctl#1469), lowered to the structures the manifest model validates.

A task is a template; a command is an instance of one; a group is a slot in the CI/CD tree the platform
owns. This module is the whole of that model's front end: it merges a product's tree onto the kernel's,
resolves each command's `task:` into the `impl:` the rest of the loader already understands, and emits
exactly the two structures `_ManifestModel` accepts - a `taxonomy:` mapping and a flat `group path ->
members` mapping. ("Flat" there is the loader's internal member map, not the deleted flat manifest form
the last section of this module is about.)

Lowering rather than replacing is deliberate. `CommandSpec`, `Manifest`, the six validation rules,
`taskgen` and `simplon.cli.assemble` all keep working on shapes they already consume, which is what let
every step of the migration off the old form be proved by a zero-diff on the product's CLI-surface
golden.

Pure functions over plain dicts: no pydantic, no I/O, no import of any body.
"""
from __future__ import annotations

import re

# A group node's own keys. Everything else under a node would be ambiguous, which is why members live
# under `commands:` rather than directly on the node: otherwise `help:` would be a group attribute in one
# place and a command name in another.
NODE_KEYS = ("help", "env_first", "groups", "commands")


def _check_node_keys(node: dict, path: tuple[str, ...]) -> None:
    """Reject a group node key outside NODE_KEYS, wherever a node is read.

    Shared by `lower` and `merge` so the kernel's own tree - which only `lower` ever walks directly - is
    checked exactly as strictly as a product's, rather than having a typo copied through verbatim.
    """
    for key in node:
        if key not in NODE_KEYS:
            raise ValueError(
                f"group '{'.'.join(path)}' declares unknown key '{key}'. A group node's keys are "
                f"help, env_first, groups and commands - rename it, or if this is meant to be a "
                f"command, move it under `commands:`")


def lower(tree: dict, _path: tuple[str, ...] = ()) -> tuple[dict, dict]:
    """A command tree, split into the `taxonomy:` shape and the flat `group path -> members` map.

    The two spellings are not interchangeable and the difference is load-bearing: the taxonomy nests its
    children by BARE name under a `groups:` key, while the flat map keys every group by its DOTTED path.
    A group with no commands still appears in both - `lower` itself does not decide whether an empty
    group renders. That call belongs to `load()`, which is the one place that can tell a group nobody
    placed anything in APART FROM the catalogue (silently dropped, see `declared_paths`) from a group
    this very `tree` names itself with nothing in it (already rejected by `merge`, so `load()` never sees
    that shape here at all).
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
        _check_node_keys(node, path)
        shape = {key: node[key] for key in NODE_KEYS if key in node and key not in ("groups", "commands")}
        child_taxonomy, child_flat = lower(node.get("groups") or {}, path)
        if child_taxonomy:
            shape["groups"] = child_taxonomy
        taxonomy[str(name)] = shape
        flat[".".join(path)] = {str(command): dict(spec or {})
                                for command, spec in (node.get("commands") or {}).items()}
        flat.update(child_flat)
    return taxonomy, flat


def _is_empty(node: dict) -> bool:
    """Whether a merged group node's subtree carries no command anywhere - directly or in any
    descendant group.

    Used only for the load-error check in `merge` below: a group the PRODUCT names in its own tree and
    leaves this way announced something it does not have. Whether an empty group RENDERS at all is a
    separate question `merge` does not answer - see `declared_paths` and its caller in `load()`.
    """
    if node.get("commands"):
        return False
    return not node.get("groups")


def declared_paths(tree: dict) -> frozenset[str]:
    """Every dotted group path this tree names itself, at any depth - regardless of whether that group
    ends up with a command.

    Feed it the PRODUCT's own new-form tree (before `merge`) and the result is exactly the set of groups
    the product itself asked for. That is the other half of the empty-group question `merge` raises on: a
    kernel-only group left empty is not an error, it is a group the catalogue offers that this set proves
    the product never took - `load()` uses that proof to drop it from the assembled CLI rather than
    render a sub-app with nothing in it. `lower()` already computes exactly this key set as a side effect
    of building the flat member map, so this is that map's keys, named for what THIS caller wants from it.
    """
    return frozenset(lower(tree)[1])


def paths_with_commands(flat: dict) -> frozenset[str]:
    """Every path in a flat member map (`lower`'s second return value) whose own subtree - itself or any
    descendant path - carries at least one command.

    `flat` keys every group by its DOTTED path but each entry's members are that group's OWN, direct
    commands only - `support` and `support.git` are two separate keys, so `support` can look empty by
    that measure alone while `support.git` underneath it is not. A group is only truly unused if NOTHING
    anywhere in its subtree is, which is what `load()` needs to tell `release` (nothing under it, drop
    it) apart from a bare ancestor like `support` that merely holds no DIRECT command of its own while a
    child does (keep it, or its child has nowhere to hang from).
    """
    return frozenset(path for path in flat
                     if any(members for other, members in flat.items()
                            if other == path or other.startswith(f"{path}.")))


def merge(kernel: dict, product: dict, _path: tuple[str, ...] = (),
         *, product_tasks: dict | None = None, catalogue_tasks: dict | None = None,
         locked: bool = True) -> dict:
    """The product's tree merged onto the kernel's.

    `product_tasks`/`catalogue_tasks` are the RAW `tasks:` maps (product's own, and the catalogue's),
    threaded through for no reason but a better error message: `_merge_commands` needs them to name the
    two `impl:` a `task:` collision hides behind one command name, and this is the only path from
    `load()` down to it. Neither is otherwise this function's concern - it merges trees, not bodies.

    `locked` is the group lock, and it is the CATALOGUE's - which is why it is a parameter rather than
    an unconditional rule. "The platform owns which groups exist" is a statement about a platform, and a
    caller that hands in no catalogue at all has none: with `kernel` empty, an unconditional lock would
    make every possible tree illegal and the form unusable outside a product. `load()` therefore ties it
    to the catalogue it was given, which in every product is one (`simplon.context` always passes it);
    unlocked, a group the kernel does not declare is simply the manifest's own.

    Three outcomes, and the first is the group lock: a PATH the kernel does not declare is an error, a
    command NAME it does not declare is an addition, and a name it does declare is a refinement. The lock
    is therefore the structure rather than a check over it - there is one tree, so there is no second way
    to bring a group into existence (this replaces netctl#1462's separate enforcement).

    A product may add `groups:` and `commands:` to a group it already has - never rewrite `help:` or
    `env_first:`. Both are the platform's call on the group's SHAPE (env-gating in particular: a product
    switching `env_first` off would silently ungate every descendant), and the group lock exists so that
    shape is the same in every product.

    A group the PRODUCT itself names in ITS OWN tree - even as an empty node - is a promise: it exists, so
    it must have at least one command somewhere in its subtree. Left empty, that is a load error naming
    the group; deliberately NOT a decision this function makes for a group it only inherited from the
    KERNEL (`build`/`test`/`release`/`deploy`/`monitor` all start life as bare `{help: ...}` nodes in the
    catalogue) - a product that never mentions one of those has made no promise, and whether such a group
    renders is `load()`'s call, made with information (the OLD-form half of a still-migrating manifest,
    invisible here) this function does not have. Keeping the merged tree complete either way - the
    platform's own copy of every group it offers, touched or not - is what lets `load()` make that call
    correctly instead of guessing from an already-pruned result.
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
        own = name not in out and not locked
        if own:
            # Unlocked (no platform tree to own it): this group exists because THIS manifest declares it,
            # so its shape - `help:`, `env_first:` - is the manifest's to state. The refusal below is
            # about REDECLARING a shape the platform already set, and here there is no platform.
            out[name] = {}
        if name not in out:
            raise ValueError(
                f"groups entry '{'.'.join(path)}' names a group the platform's tree does not declare. "
                f"The platform owns which groups exist, so that the same groups and the same general "
                f"tasks are there in every product. Available here: "
                f"{', '.join(sorted(out)) or '(none)'}. Either put these commands in one of those, or "
                f"declare the new group in the platform's `groups:` - once, for everybody")
        _check_node_keys(node, path)
        base = out[name]
        merged = dict(base)
        for key, value in node.items():
            if key == "groups":
                merged["groups"] = merge(base.get("groups") or {}, value, path,
                                         product_tasks=product_tasks, catalogue_tasks=catalogue_tasks,
                                         locked=locked)
            elif key == "commands":
                merged["commands"] = _merge_commands(base.get("commands") or {}, value,
                                                     ".".join(path),
                                                     product_tasks=product_tasks or {},
                                                     catalogue_tasks=catalogue_tasks or {})
            elif own:
                merged[key] = value
            else:
                raise ValueError(
                    f"group '{'.'.join(path)}' declares `{key}:`, which the platform's node already "
                    f"sets. A product may add commands and sub-groups to a platform group, never "
                    f"change its shape - change it in the platform's `groups:` instead, once, for "
                    f"everybody")
        if _is_empty(merged):
            raise ValueError(
                f"group '{'.'.join(path)}' declares no commands. A group this manifest names is a "
                f"promise it has at least one, directly or in a subgroup - add one, or remove the "
                f"declaration and leave the group to the platform's default (nothing rendered)")
        out[name] = merged
    return out


def _impl_of(ref: str, product_tasks: dict, catalogue_tasks: dict) -> str:
    """The `impl:` a task ref names, for a COLLISION MESSAGE a human must act on.

    A bare name like `install` tells nobody which of two bodies it is - `install` and `install` read
    identically. Resolving it to `module:function` is what lets the message name the actual difference
    (oras vs Colima) rather than just the name they share. Same source rule `_resolve_one` uses: a colon
    means a catalogue coordinate, no colon means a task this manifest itself declares.

    Falls back to the bare ref when it does not resolve. This runs at MERGE time, before `resolve()` has
    validated that every ref exists - a typo'd ref belongs to that error, not to this message, so this
    never raises over one.
    """
    source = catalogue_tasks if ":" in ref else product_tasks
    spec = (source or {}).get(ref) or {}
    return str(spec.get("impl") or ref)


def _merge_commands(base: dict, extra: dict, where: str,
                    *, product_tasks: dict, catalogue_tasks: dict) -> dict:
    """A group's members, with the product's refinements folded in per KEY rather than per node.

    Per-key matters: netctl pins `tasks generate`'s target with a `with:` and expects to keep the
    kernel's `params:` for `check`. Replacing the whole node would silently drop it.

    A command the product ALSO names is a REFINEMENT only while it points at the same `task:` the base
    already does (or names none, leaving the base's untouched) - changing `help:`, `params:` or `with:`
    on the platform's own body. A product node that names a DIFFERENT `task:` for a name the base already
    places is not a refinement, it is a second, different body under one name, and simply letting the
    product's dict win (`{**inherited, **spec}`, key order be damned) is exactly the silence the loader
    used to produce: the command resolves, the help even reads plausibly, and the only proof of which
    body actually ran is what the host looks like afterwards (netctl's oras-vs-Colima `support install`).
    So a differing `task:` is rejected UNLESS the product's node opts in with `override: true` - the
    explicit "yes, I mean to replace it" the platform cannot infer from silence. `override: true` makes
    the product's node the WHOLE command (no merge with the base's `help:`/`params:`): those describe the
    body being replaced, not the one that now runs.
    """
    out: dict[str, dict] = {}
    for name, spec in (base or {}).items():
        name = str(name)
        _check_command_is_mapping(spec, where, name)
        out[name] = dict(spec or {})
    for name, spec in (extra or {}).items():
        name = str(name)
        _check_command_is_mapping(spec, where, name)
        spec = dict(spec or {})
        override = bool(spec.pop("override", False))
        inherited = out.get(name)
        if inherited is None:
            out[name] = spec
            continue
        if ("depends_on" in spec and "task" in inherited) or ("task" in spec and "depends_on" in inherited):
            raise ValueError(
                f"command '{where} {name}' is declared as one kind of command and refined as another. A "
                f"refinement may set help, params, hidden, with and task; moving a command between "
                f"task-backed and aggregate is a different command wearing the same name - give it one")
        new_task = spec.get("task")
        if new_task is not None and inherited.get("task") not in (None, new_task):
            if not override:
                old_ref, new_ref = inherited["task"], new_task
                old_impl = _impl_of(old_ref, product_tasks, catalogue_tasks)
                new_impl = _impl_of(new_ref, product_tasks, catalogue_tasks)
                raise ValueError(
                    f"command '{where} {name}' redeclares `task:` from '{old_ref}' to '{new_ref}' - two "
                    f"different bodies placed under one name: the platform's is `{old_impl}`, the "
                    f"product's is `{new_impl}`. Which one runs is exactly the silent choice this loader "
                    f"refuses to make - `{name}` and `{name}` look the same, `{old_impl}` and "
                    f"`{new_impl}` do not. If the product's body ({new_impl}) must deliberately replace "
                    f"the platform's ({old_impl}) here, add `override: true` next to `task: \"{new_ref}\"` "
                    f"under this command in `groups: {where}: commands: {name}:`. If it should not, drop "
                    f"the `task:` line here and keep refining the platform's command instead (help:, "
                    f"params:, with: only)")
            # A deliberate replacement stands alone: merging the base's `help:`/`params:` in would
            # describe the body it no longer runs.
            out[name] = spec
            continue
        out[name] = {**inherited, **spec}
    return out


def _check_command_is_mapping(spec, where: str, name: str) -> None:
    """Reject a command entry that is not a mapping, before a blind `dict(spec)` turns it into an
    unreadable stdlib TypeError naming no path (`commands: { push: "vcs:push" }` is the realistic typo -
    a `task:` string written where the whole command mapping belongs)."""
    if spec is not None and not isinstance(spec, dict):
        raise ValueError(
            f"command '{where} {name}' is not a mapping: found {type(spec).__name__} instead. A "
            f"command's value must be a mapping (task, with, params, help, depends_on) - check the "
            f"indentation under this entry")


# Keys a task supplies to every command that instantiates it, where the command does not say otherwise.
# `impl` is not here because it is never the command's to declare; `with` is not here because a template
# that pinned a value would not be a template.
INHERITED = ("help", "passthrough_args")

# What a TASK may declare. Everything else that `_CommandSpecModel` accepts belongs to the instance:
# a template that pinned a value, hid itself or planned other commands would not be a template.
TASK_KEYS = ("impl", "help", "passthrough_args", "params")
COMMAND_ONLY_KEYS = ("hidden", "keep_awake", "stop_on_failure", "depends_on", "with", "task")


def check_task(name: str, spec: dict) -> None:
    """Reject a task declaration that would be read only in part.

    Four keys are read; anything else was silently dropped before this check, including keys that read
    as entirely plausible on a template. `_ParamPresentationModel`'s `extra="forbid"` is the precedent:
    a declaration that renders nowhere is worse than one that fails.
    """
    if not isinstance(spec, dict):
        raise ValueError(
            f"task '{name}' is not a mapping: found {type(spec).__name__}. A task declares `impl:` and "
            f"optionally `help:`, `passthrough_args:` and `params:`")
    if not spec.get("impl"):
        raise ValueError(
            f"task '{name}' declares no `impl:`. A task is a template for a body, so it names one as "
            f"\"module:function\"; a command that plans other commands uses `depends_on:` instead")
    for key in spec:
        if key in COMMAND_ONLY_KEYS:
            raise ValueError(
                f"task '{name}' declares `{key}:`, which belongs on a command rather than on the task "
                f"it instantiates. Move it to the command under `groups:`")
        if key not in TASK_KEYS:
            raise ValueError(
                f"task '{name}' declares unknown key `{key}:`. A task takes "
                f"{', '.join(TASK_KEYS)} - check the spelling")


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

    with_ = spec.get("with")
    if with_ is not None and not isinstance(with_, dict):
        raise ValueError(
            f"command '{where}' declares `with:` as {type(with_).__name__}, not a mapping. `with:` "
            f"pins parameter values by name - make it a mapping of parameter name to pinned value")

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
    check_task(ref, template)
    out = {"impl": template["impl"], **spec}
    for key in INHERITED:
        if key not in out and key in template:
            out[key] = template[key]
    # The conflict this guards is a parameter THIS command pins with `with:` while also describing its
    # own presentation with `params:` - that presentation would render nowhere, since the value is off
    # the command line. It is scoped to the command's OWN `params:`, not the merged template+command map:
    # a parameter the TEMPLATE declares and this command pins is the design's canonical shape (one task
    # documents a parameter once, every instance may pin it), and any command that leaves it unpinned
    # still gets that documentation - so a pinned key is dropped from the merged map rather than rejected.
    own = spec.get("params") or {}
    pinned = sorted(set(with_ or {}) & set(own))
    if pinned:
        raise ValueError(
            f"command '{where}' pins {', '.join(pinned)} with `with:` and also declares `params:` for "
            f"it. A pinned parameter is off the command line, so its presentation renders nowhere - "
            f"drop the `params:` entry, or drop the pin if the user should still be able to set it")
    params = {key: value for key, value in {**(template.get("params") or {}), **own}.items()
              if key not in (with_ or {})}
    if params:
        out["params"] = params
    return out


# --- the old flat form: gone, and rewritten for whoever still has one ----------------------------------
#
# The flat form wrote a body straight onto a command (`groups: build: wheel: { impl: ... }`) and placed a
# catalogue task through `import:` + a coordinate-keyed `tasks:` entry. Both are deleted (netctl#1469
# plan 3, si#33). What is NOT deleted is the way out: a manifest still written that way is rejected with
# the REWRITE spelled out in its own names, because "no longer supported" leaves the one person who has
# to act guessing at the shape nobody can see any more.

# What of a flat command's spec belongs to the TASK (the body and how it presents itself) rather than to
# the command that instantiates it. Everything else - `with`, `hidden`, `depends_on`, `keep_awake`,
# `stop_on_failure` - is the placement's, and stays on the command. Mirrors INHERITED/TASK_KEYS above,
# narrowed to the keys the flat form could actually carry on a command.
_TASK_SIDE_KEYS = ("impl", "help", "passthrough_args", "params")

# How wide a rendered mapping may be before the rewrite breaks it across lines. The rewrite is read in a
# terminal, inside an error message that already carries prose - a 200-column flow mapping there is a
# rewrite nobody can check against their own file.
_FLOW_WIDTH = 92


def _is_old_form_node(node: object) -> bool:
    """Whether a top-level `groups:` entry is a flat-form group: a mapping of command names, with not one
    of the four node keys among them.

    A node with a node key is a tree node, even a wrong one - `_check_node_keys` reports that far better
    than this can. An EMPTY mapping is not the flat form either: it declares a group and nothing in it,
    which `merge` already refuses by name.
    """
    return isinstance(node, dict) and bool(node) and not any(key in node for key in NODE_KEYS)


def old_form_groups(groups: dict) -> dict:
    """The flat-form entries of a `groups:` block, keyed as they are written."""
    if not isinstance(groups, dict):
        return {}
    return {str(name): node for name, node in groups.items() if _is_old_form_node(node)}


def old_form_tasks(tasks: dict) -> dict:
    """The flat-form entries of a `tasks:` block: one keyed by a catalogue COORDINATE (the old way of
    placing a platform task), or one carrying `group:` (the old way of saying where its command goes).

    A bare-named entry with an `impl:` and no `group:` is the CURRENT form and is not returned here - it
    is the template a command instantiates with `task:`.
    """
    if not isinstance(tasks, dict):
        return {}
    return {str(name): (spec or {}) for name, spec in tasks.items()
            if ":" in str(name) or (isinstance(spec, dict) and "group" in spec)}


# A key YAML reads as a plain scalar. A coordinate's colon is excluded deliberately: `docs:reference:`
# unquoted is a nested mapping, not a key.
_PLAIN_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _quote(value: object) -> str:
    """One scalar, as YAML the reader can paste back into a manifest."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_quote(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(key)}: {_quote(item)}" for key, item in value.items()) + " }"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _key(name: object) -> str:
    """A mapping key, quoted only where YAML needs it (a coordinate's colon does, a hyphen does not)."""
    text = str(name)
    return text if _PLAIN_KEY_RE.match(text) and ":" not in text else f'"{text}"'


def _render_mapping(name: object, body: dict, indent: str) -> list[str]:
    """`name: { ... }` on one line where it fits, and a block mapping where it does not."""
    if not body:
        # A placement that says nothing but "yes, here": the command name IS already the whole of it, so
        # `{}` is the terse and correct spelling rather than an omission.
        return [f"{indent}{_key(name)}: {{}}"]
    flow = f"{indent}{_key(name)}: {{ " + ", ".join(
        f"{_key(key)}: {_quote(value)}" for key, value in body.items()) + " }"
    if len(flow) <= _FLOW_WIDTH:
        return [flow]
    lines = [f"{indent}{_key(name)}:"]
    for key, value in body.items():
        lines.append(f"{indent}  {_key(key)}: {_quote(value)}")
    return lines


def _render_tree(tree: dict, indent: str) -> list[str]:
    """The nested `groups:`/`commands:` shape, rendered depth-first in declaration order."""
    lines: list[str] = []
    for name, node in tree.items():
        lines.append(f"{indent}{_key(name)}:")
        for key in NODE_KEYS:
            if key not in ("groups", "commands") and key in node:
                lines.append(f"{indent}  {_key(key)}: {_quote(node[key])}")
        if node.get("commands"):
            lines.append(f"{indent}  commands:")
            for command, spec in node["commands"].items():
                lines.extend(_render_mapping(command, spec, indent + "    "))
        if node.get("groups"):
            lines.append(f"{indent}  groups:")
            lines.extend(_render_tree(node["groups"], indent + "    "))
    return lines


def _node_at(tree: dict, path: tuple[str, ...]) -> dict:
    """The node at a dotted group path, creating each level - so a flat `support.git` key becomes the
    nested `support: groups: git:` the tree form spells it as."""
    node: dict = {"commands": {}, "groups": tree}
    for segment in path:
        children = node["groups"]
        node = children.setdefault(segment, {"commands": {}, "groups": {}})
    return node


def rewrite_of_old_form(data: dict) -> str:
    """This manifest's `tasks:` and `groups:` sections, rewritten as the command tree - YAML, ready to
    paste over both.

    This is the whole of what the refusal below has to offer, so it is a function of its own and pure:
    a test can assert on the rewritten text without going near a load error, and the renderer can be
    read on its own terms. A key it does not recognise on a command travels across untouched, because
    such a key is far likelier to be the product's own than to be dead.

    BOTH sections in full, not only the flat parts, and that is the whole usability of it: a manifest
    part-way through the migration has some groups in each form, and a rewrite of only the flat half
    would be a block that silently DROPS the migrated one when pasted over. What is already a tree comes
    through unchanged.

    Two bodies that are byte-identical share ONE task, which is the point of the form: `test:gate`
    placed at four levels was four copies of one `impl:` in the flat form and is one template with four
    pins here. A name already taken by a different body is qualified with its group.

    WHAT THE REWRITE DOES NOT KNOW, and it is a real limit rather than a caveat: this function has no
    catalogue. A command whose name the CATALOGUE also places - `support install`, `release tag` - is
    printed without the `override: true` the merge then demands, and pasting it in fails with
    "redeclares `task:`". That second refusal names the fix exactly, so the reader is not stranded; but
    the printed block is a starting point in that case, not a finished manifest. Do not promise more.
    """
    all_groups = data.get("groups") or {}
    groups = old_form_groups(all_groups)
    tasks = old_form_tasks(data.get("tasks") or {})
    declared = {str(name): dict(spec or {}) for name, spec in (data.get("tasks") or {}).items()
                if str(name) not in tasks}
    tree: dict = {}

    def carry(node: dict) -> dict:
        """A node that is ALREADY a tree, copied into the renderer's own shape."""
        out = {key: node[key] for key in NODE_KEYS if key in node and key not in ("groups", "commands")}
        out["commands"] = {str(name): dict(spec or {})
                           for name, spec in (node.get("commands") or {}).items()}
        out["groups"] = {str(name): carry(dict(child or {}))
                         for name, child in (node.get("groups") or {}).items()}
        return out

    for name, node in all_groups.items():
        if not _is_old_form_node(node):
            tree[str(name)] = carry(dict(node or {}))

    def task_name_for(preferred: str, group: str, spec: dict) -> str:
        for name, existing in declared.items():
            if existing == spec:
                return name
        name = preferred if preferred not in declared else f"{group.replace('.', '-')}-{preferred}"
        suffix = 2
        while name in declared:
            name, suffix = f"{preferred}-{suffix}", suffix + 1
        declared[name] = spec
        return name

    for group, members in groups.items():
        node = _node_at(tree, tuple(group.split(".")))
        for command, spec in (members or {}).items():
            spec = dict(spec or {})
            if not spec.get("impl"):
                # An aggregate was never a body: `depends_on:` and the rest travel unchanged.
                node["commands"][str(command)] = spec
                continue
            body = {key: spec[key] for key in _TASK_SIDE_KEYS if key in spec}
            rest = {key: value for key, value in spec.items() if key not in _TASK_SIDE_KEYS}
            node["commands"][str(command)] = {"task": task_name_for(str(command), group, body), **rest}

    for coordinate, spec in tasks.items():
        spec = dict(spec or {})
        group = str(spec.pop("group", "") or (str(coordinate).split(":", 1)[0]))
        if ":" in str(coordinate) and not spec.get("impl"):
            # The body stays in the kernel: the command names the coordinate and nothing is copied here.
            name = str(coordinate).split(":", 1)[1]
            placement = {"task": str(coordinate), **spec}
        elif ":" in str(coordinate):
            # A coordinate key carrying its own `impl:` was never a placement of the platform's body - it
            # was the product's own body under a name that looks like the platform's. It becomes an
            # ordinary task, named after the half of the coordinate that was ever a command name.
            name = str(coordinate).split(":", 1)[1]
            body = {key: spec[key] for key in _TASK_SIDE_KEYS if key in spec}
            rest = {key: value for key, value in spec.items() if key not in _TASK_SIDE_KEYS}
            placement = {"task": task_name_for(name, group, body), **rest}
        else:
            # A bare name with an `impl:` was already a template - only its PLACEMENT moves out of the
            # `tasks:` block and into the tree.
            name = str(coordinate)
            body = {key: spec[key] for key in _TASK_SIDE_KEYS if key in spec}
            rest = {key: value for key, value in spec.items() if key not in _TASK_SIDE_KEYS}
            placement = {"task": task_name_for(name, group, body), **rest}
        _node_at(tree, tuple(group.split(".")))["commands"][name] = placement

    lines: list[str] = []
    if declared:
        lines.append("tasks:")
        for name, body in declared.items():
            lines.extend(_render_mapping(name, body, "  "))
        lines.append("")
    if tree:
        lines.append("groups:")
        lines.extend(_render_tree(tree, "  "))
    return "\n".join(lines)


def check_no_old_form(data: dict) -> None:
    """Reject a manifest still written in the flat form, showing what it becomes.

    The four things that say "flat" are checked together rather than one per load, because they are one
    manifest's one migration: a product that wrote `impl:` on a command almost always also placed its
    catalogue tasks through `import:`, and being told about the second only after fixing the first is
    two guessing games instead of none.

    The message carries the rewrite of THIS manifest's own sections (`rewrite_of_old_form`), not an
    example of the shape. That is the entire difference between a removal somebody can act on and one
    they have to reverse-engineer - and it is why the flat form's renderer outlived the flat form.
    """
    groups = old_form_groups(data.get("groups") or {})
    tasks = old_form_tasks(data.get("tasks") or {})
    stale_import = bool(data.get("import"))
    if not groups and not tasks and not stale_import:
        return

    found = []
    if groups:
        found.append(f"group(s) {', '.join(repr(name) for name in groups)} name commands directly, with "
                     f"`impl:` on them")
    coordinate_keyed = [name for name in tasks if ":" in name]
    if coordinate_keyed:
        found.append(f"task(s) {', '.join(repr(name) for name in coordinate_keyed)} are keyed by a "
                     f"platform coordinate")
    placing = [name for name in tasks if ":" not in name]
    if placing:
        found.append(f"task(s) {', '.join(repr(name) for name in placing)} place their own command with "
                     f"`group:`")
    if stale_import:
        found.append("an `import:` section makes catalogue coordinates available")

    rewrite = rewrite_of_old_form(data)
    notes = ["a command is an INSTANCE of a task: the body is declared once under `tasks:` and the "
             "command points at it with `task:`",
             "a catalogue task keeps its body in the kernel - the command names the coordinate "
             "(`task: \"<namespace>:<name>\"`) and copies nothing",
             "the catalogue's own commands arrive by merging its tree, so `import:` has nothing left to "
             "do - delete the section"]
    if not stale_import:
        notes = notes[:2]
    body = "\n".join(f"    {line}" if line else "" for line in rewrite.splitlines())
    raise ValueError(
        "this manifest is written in the flat command form, which this kernel no longer loads: "
        + "; ".join(found) + ". Rewrite those sections as:\n\n" + body + "\n\n"
        + "\n".join(f"  - {note}" for note in notes))


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
