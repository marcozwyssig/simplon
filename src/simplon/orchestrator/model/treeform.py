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

from collections.abc import Iterable

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


def shape_is_the_platforms(path: str, key: str) -> str:
    """The refusal a product gets for restating the SHAPE of a group the platform declares.

    One string with two callers, and that is the point (si#43). `merge` raises it for `env_first:` (or
    `help:`) written onto a platform group; `check_env_groups` raises it for `env_groups:`, which says
    `env_first: true` about a group from the top level of the same file. Two spellings of one statement
    have to be refused for one reason and point at one way out, or the second spelling reads as a
    separate rule with its own exceptions - which is exactly how it became a back door.
    """
    return (f"group '{path}' declares `{key}:`, which the platform's node already sets. A product may "
            f"add commands and sub-groups to a platform group, never change its shape - change it in "
            f"the platform's `groups:` instead, once, for everybody")


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
                raise ValueError(shape_is_the_platforms(".".join(path), key))
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


# --- the old flat form: gone, and the refusal names it rather than rewriting it (si#33, si#85) ---------
#
# The flat form wrote a body straight onto a command (`groups: build: wheel: { impl: ... }`) and placed a
# catalogue task through `import:` + a coordinate-keyed `tasks:` entry. Both are deleted (netctl#1469
# plan 3, si#33). What is NOT deleted is the DIAGNOSIS below: a manifest still written that way is caught
# by name, because without it the flat form dies further down as a missing key on some node - a message
# that names neither the shape the file is in nor the release that abolished it.
#
# WHAT si#85 STRUCK is the renderer that used to print the finished replacement inside that diagnosis.
# Some 250 lines of it, for a population measured empty: all six reachable manifests are off the flat
# form, and si#56 had just found the renderer carrying a property mis-documented from the day it was
# written. A second source of the manifest's shape that nobody reads is a source that rots, and the
# tree form is already written down where it is maintained. So the way out is now a pointer at the
# documentation rather than a rendering of it, and what stands here is the diagnosis alone.


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


#: Where the tree form is written down. The refusal points at the PAGE rather than printing the shape:
#: the page is maintained beside the loader and covers the cases a rendered block never could, while a
#: renderer of the same thing was the second source si#85 struck.
_TREE_FORM_DOCS = "https://marcozwyssig.github.io/simplon/building/manifest/"


def check_no_old_form(data: dict) -> None:
    """Reject a manifest still written in the flat form, naming the form, the release that abolished it
    and where its replacement is documented.

    The four things that say "flat" are checked together rather than one per load, because they are one
    manifest's one migration: a product that wrote `impl:` on a command almost always also placed its
    catalogue tasks through `import:`, and being told about the second only after fixing the first is
    two guessing games instead of none.

    WHY THIS OUTLIVED THE RENDERER IT USED TO INTRODUCE (si#85). The population is empty - not one of the
    six reachable manifests is on the flat form - but a population is not the set of possible INPUTS, and
    a new consumer can arrive with an old manifest. Delete this and such a manifest still fails, just
    further down and as something else: `commands` missing on a node, or a task named by nobody. The
    three facts a reader cannot recover from that failure are exactly the three this message carries -
    WHAT shape was found, WHEN it stopped loading, and WHERE the shape that replaced it is written down.
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

    # What each finding BECOMES, one line each, and only for the findings this manifest actually has. It
    # is not a rewrite and does not pretend to be one: it is the sentence that makes the linked page
    # searchable, so the reader arrives there knowing which section is theirs.
    notes = []
    if groups or placing:
        notes.append("a command is an INSTANCE of a task: declare the body once under `tasks:` and let "
                     "the command point at it with `task:`, under `groups: <group>: commands:`")
    if coordinate_keyed:
        notes.append("a catalogue task keeps its body in the kernel - the command names the coordinate "
                     "(`task: \"<namespace>:<name>\"`) and copies nothing")
    if stale_import:
        notes.append("the catalogue's own commands arrive by merging its tree, so `import:` has nothing "
                     "left to do - delete the section")
    raise ValueError(
        "this manifest is written in the flat command form, which no longer loads: the form was "
        "abolished in 0.4.0 and this kernel is past it.\n\nWhat says so here: "
        + "; ".join(found) + ".\n\nWhat it becomes:\n"
        + "\n".join(f"  - {note}" for note in notes)
        + "\n\nThe tree form is documented at " + _TREE_FORM_DOCS + " - \"The command tree\" for the "
          "shape, and \"The flat form, and how to leave it\" for this migration in particular. Nothing "
          "here rewrites the file for you: the sections have to be edited by hand, which is also the "
          "only way your comments survive the move.")


# --- a declared task nobody places is a task on OFFER (si#53) -----------------------------------------
#
# `check_every_task_is_used` stood here and refused it. It was the one expression rule the kernel did not
# apply to itself - "Scoped to the PRODUCT on purpose" - and si#48 measured what that exemption was worth:
# the rule would have refused 14 of the kernel's own 22 catalogue tasks. It was also the only one of the
# sixteen with no measured cause in ticket, commit or docstring, and over every reachable manifest - this
# kernel's own and the five in `surface.CONSUMERS` - it had never refused anything: `unused = 0` in every
# one of them, measured 2026-09-08 through the GitHub API.
#
# So it forbade a product exactly what the kernel does fourteen times over - declaring a catalogue as an
# OFFER rather than a duty roster - and caught nothing while doing it. The owner struck it in si#53.
# `test_a_declared_task_no_command_places_is_accepted` is what stands here now, and it is the assertion
# that matters: the deletion has to make an orphan task LOAD, not merely stop raising somewhere.
#
# What the deletion also took is below, and si#81 is the ticket that put it back at the size it is
# actually worth.


def check_no_shadowed_task_declaration(flat: dict, product_tasks: dict,
                                       catalogue_tasks: dict | None = None) -> None:
    """Reject a declared task whose NAME a command has taken for a different body (si#81).

    THE CASE, and it is the one si#53 measured as the price of striking `check_every_task_is_used`: a
    product moves a command onto a catalogue coordinate and leaves its own `tasks:` entry standing next
    to the new placement. The manifest loads, the CATALOGUE's body runs under that name, and the body
    the product still maintains is reachable from nowhere and reported by nothing. Same shape from the
    other side: two product tasks, one command, and the one the command does not name is dropped without
    a word. Both are pinned in `tests/test_catalogue.py`.

    WHY THIS IS NARROWER THAN THE RULE IT REPLACES, which is the whole content of si#81. The struck rule
    refused EVERY `tasks:` entry no command instantiated. This one refuses only the entry whose name a
    command has already taken - a typo or a half-finished move, never an offer. A product that declares
    a task and places it nowhere at all keeps doing exactly that: nothing here looks at it, and
    `test_a_declared_task_no_command_places_is_accepted` is the assertion that says so. The two sets are
    not the same size and the difference is the point.

    DIAGNOSIS, not an expression rule, by this repository's own sorting question. What is refused is a
    declaration that is accepted and INERT - the same call the kernel already makes for `hidden:` on a
    group-default namesake and for a `nexus:` block declaring no repositories. The manifest would run;
    what it would not do is run the body written in it.

    It reads the MERGED tree, so the kernel's own manifest goes through this call with no exemption
    path - unlike its predecessor, whose docstring said "Scoped to the PRODUCT on purpose".

    `catalogue_tasks` is here for the MESSAGE only: `commit` and `commit` read identically, and naming
    the two `module:function` bodies is what lets a human see which half is dead.
    """
    used = {str(spec.get("task")) for members in (flat or {}).values()
            for spec in (members or {}).values() if isinstance(spec, dict) and spec.get("task")}
    for name in sorted(str(key) for key in (product_tasks or {})):
        if name in used:
            continue
        for path in sorted(flat or {}):
            spec = ((flat or {})[path] or {}).get(name)
            if not isinstance(spec, dict) or str(spec.get("task") or "") == name:
                continue
            ref = spec.get("task")
            dead = _impl_of(name, product_tasks or {}, catalogue_tasks or {})
            runs = (f"runs `{ref}` ({_impl_of(str(ref), product_tasks or {}, catalogue_tasks or {})})"
                    if ref is not None else
                    "is an aggregate that plans other commands and runs no body of its own")
            raise ValueError(
                f"task '{name}' is declared under `tasks:` and instantiated by no command, while the "
                f"command '{path} {name}' - the one that bears its name - {runs} instead. That is a "
                f"half-finished move or a typo, not an offer: the body this manifest still carries "
                f"({dead}) is reachable from nowhere, and until now nothing said so. Either point "
                f"`groups: {path}: commands: {name}:` at `task: {name}`, or delete the `tasks: {name}:` "
                f"declaration whose body no longer runs. A task NO command names is untouched by this - "
                f"declaring more than you place is what a catalogue is for (si#53)")


# --- placement or family: what a coordinate's namespace says about where it may go (si#34) ------------


def check_coordinate_placement(flat: dict, platform_groups: frozenset[str]) -> int:
    """Reject a coordinate that names a platform group and is placed in a different one.

    THE RULE. A catalogue coordinate is `<namespace>:<name>`, and the namespace answers one of two
    questions depending on what it is:

      - it is one of the PLATFORM'S OWN GROUP NAMES, and then it is a PLACEMENT: `build:image` belongs
        under `build`, in every product, always;
      - it is anything else, and then it is a FAMILY - what kind of task this is, said without saying
        where it goes. `docs:site` is a documentation task; one product places it under `build` and
        another under `release`, and both are right.

    THE GROUPS ARE NOT ALL PHASES, and this docstring says so because the rule is easy to misremember as
    "phase or family". Five of the platform's groups are the phases of the delivery loop - `build`,
    `test`, `release`, `deploy`, `monitor`. `support` is not a sixth phase; it is the group that
    SUPPORTS the five, which is why `bootstrap` seeds it "beside the five rather than among them" and
    why the getting-started page counts five and then adds it. The rule still covers it - `support:install`
    would otherwise be the one placed coordinate nothing governed - so the rule is stated over the
    platform's GROUPS, and "phase" is left to mean the five things it means everywhere else.

    Coordinate and group are deliberately TWO AXES (netctl#1437), and this rule is what keeps them two
    without letting either become unpredictable. It costs the second axis nothing: a family namespace is
    still placed wherever the product wants it. What it removes is the third state - a namespace that
    reads like a group and is placed elsewhere - because that is the only case where a reader cannot tell
    which axis a name is on.

    Neighbour to the PLACEMENT HURDLE (si#39, `catalogue.yaml`'s `groups:` block), and the two must not
    be confused: that one decides whether the kernel places a command at all ("useful in every product,
    not merely harmless in most"), this one decides, once something IS placed, WHERE it may go. One
    guards the kernel's own tree, the other guards every product's.

    `platform_groups` is the platform's top-level group names, and it is a parameter rather than a
    constant because "which names carry a placement" is the CATALOGUE's statement. A caller with no
    catalogue hands in an empty set and every namespace is a family, which is right: with no platform
    there are no groups to name.

    The flat map this reads is the MERGED one - the product's tree folded onto the platform's - so the
    catalogue's OWN placed commands are ruled on beside the product's. That is deliberate: `support:install`
    and the `vcs:` verbs are placed by the kernel, and a rule the kernel exempted itself from would be a
    rule about other people's manifests.

    Only the FIRST path segment is compared. A group's sub-groups are still that group - `support:install`
    under `support git` would be oddly filed and is not a rule violation, because the rule is about which
    group a task runs in, not about the shelf it sits on inside one.

    RETURNS how many placements it ruled on, and that return value is the point of the function being
    written this way. A manifest whose coordinates are all families passes this check without the rule
    ever applying to anything, and a manifest with twenty group-named placements passes it too - both
    simply return. Only one of those two greens is evidence that the rule holds, so the count is handed
    back rather than discarded. It has to come from HERE rather than be recomputed by the caller: a test
    that counted the placements itself would still count seven while a broken check ruled on none, and
    the count would then be evidence about the test rather than about this function.
    """
    ruled = 0
    for group_path, members in (flat or {}).items():
        # The tree is dotted, the CLI and every manifest are spaced. A message that said `support.git`
        # would send its reader looking for a key that appears nowhere in the file they have to edit.
        placed_in = str(group_path).replace(".", " ")
        group = str(group_path).split(".", 1)[0]
        for name, spec in (members or {}).items():
            ref = (spec or {}).get("task")
            if ref is None or ":" not in str(ref):
                continue
            namespace = str(ref).split(":", 1)[0]
            if namespace not in platform_groups:
                continue
            if namespace == group:
                ruled += 1
                continue
            raise ValueError(
                f"command '{placed_in} {name}' places the coordinate '{ref}', and '{namespace}' is one "
                f"of the platform's own group names. A coordinate that starts with one says where the "
                f"task belongs, so '{ref}' belongs under `groups: {namespace}:` and nowhere else - this "
                f"places it under '{placed_in}'. Move the command to `groups: {namespace}: commands: "
                f"{name}:`, or - if this body really is a family each product places where it likes - "
                f"give it a namespace in the platform catalogue that names no group, the way `docs:site` "
                f"can sit under `build` in one product and under `release` in another. The names that "
                f"carry a placement are the platform's groups: {', '.join(sorted(platform_groups))} - "
                f"the phases of the delivery loop, plus the group that supports them")
    return ruled


# --- env_groups: the flat spelling of a group's env-first shape, and who owns it (si#43) --------------


def check_env_groups(merged: dict, env_groups: Iterable[str], platform_groups: frozenset[str]) -> int:
    """Reject an `env_groups:` entry that contradicts the merged node's `env_first:`.

    THE RULE is `merge`'s, and this function only reaches the one spelling `merge` never sees.
    `env_first: true` written onto a group the catalogue declares is refused there - not because it
    switches the gate the wrong way, but because a product may not STATE a platform group's shape at all.
    `env_groups: [<that group>]` says the same thing from the top level of the same file, so it lands on
    the same refusal, from `shape_is_the_platforms`.

    NOT "it only switches on, never off". That reading was the one this check replaces, and it does not
    survive contact with `merge`: `merge` allows no switching in either direction. `env_first: true` on a
    group the catalogue already calls env-first is refused just as flatly as `false` on one. There is no
    asymmetry to mirror.

    So the entry is measured against the MERGED node rather than allowed to overrule it:

      - the merged node is already env-first: the entry AGREES with the platform. Harmless, probably
        redundant, accepted - and counted, because agreement is the case a reader has to be able to tell
        apart from the entry having done something;
      - the merged node is not env-first and the platform owns the group: the entry CONTRADICTS the
        platform, and that is the refusal;
      - the merged node is not env-first and no platform owns the group: nothing has been contradicted.
        The group is the manifest's own - a loader running without a catalogue - and `env_groups:` is
        its own statement about it, which is the case the key was written for. `load` gates it on.

    `platform_groups` is the catalogue's own top-level group names, a parameter for the same reason
    `check_coordinate_placement`'s is: "which groups have a shape somebody else owns" is the CATALOGUE's
    statement, and a caller with no catalogue hands in an empty set and owns every group it declares.

    Only TOP-LEVEL entries reach here; the model's rule 2 rejects a dotted one before this runs, so a
    nested node's `env_first:` is never spoken about from this key.

    RETURNS how many entries it ruled on - entries measured against a group the platform owns - because a
    manifest with no `env_groups:` at all returns 0 exactly as a manifest whose every entry was checked
    against a platform node that agreed, and only the second is evidence that the rule ran. The count
    has to come from here rather than be recomputed by a caller, for the reason si#34's does: a test that
    counted the entries itself would count them while a check that ruled on none stayed green.
    """
    ruled = 0
    for group in env_groups or ():
        node = (merged or {}).get(str(group)) or {}
        if bool(node.get("env_first", False)):
            ruled += 1
            continue
        if str(group) not in platform_groups:
            continue
        ruled += 1
        raise ValueError(
            shape_is_the_platforms(str(group), "env_groups")
            + f". `env_groups: [{group}]` says `env_first: true` about '{group}', and the platform's "
              f"node says `env_first: false` - drop the entry, or turn the group env-first in the "
              f"platform's `groups:`, once, for every product that has it")
    return ruled
