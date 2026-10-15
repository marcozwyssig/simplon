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

from simplon.domain import artifactsection, ports

# A group node's own keys. Everything else under a node would be ambiguous, which is why members live
# under `commands:` rather than directly on the node: otherwise `help:` would be a group attribute in one
# place and a command name in another.
NODE_KEYS = ("help", "env_first", "transparent", "groups", "commands")


def _check_node_keys(node: dict, where: str) -> None:
    """Reject a group node key outside NODE_KEYS, wherever a node is read.

    Shared by `lower` and `merge` so the kernel's own tree - which only `lower` ever walks directly - is
    checked exactly as strictly as a product's, rather than having a typo copied through verbatim.
    `where` is the node as its reader finds it: `merge` names the place a manifest writes it
    (`written_at`), `lower` the catalogue's dotted path.
    """
    for key in node:
        if key not in NODE_KEYS:
            raise ValueError(
                f"{where} declares unknown key '{key}'. A group node's keys are "
                f"help, env_first, transparent, groups and commands - rename it, or if this is meant to be a "
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
        # Dotted on purpose: by the time `load` lowers the merged tree, `merge` has already ruled on
        # every node a product wrote (in the product's own spelling), so what is left to refuse here is
        # the CATALOGUE's tree - read by kernel maintainers, under the catalogue's `groups:`.
        if node is not None and not isinstance(node, dict):
            raise ValueError(
                f"group '{'.'.join(path)}' is not a mapping: found {type(node).__name__} instead. A "
                f"group node's value must be a mapping with its own keys (help, env_first, transparent, "
                f"groups, commands) - check the indentation under this entry")
        node = node or {}
        _check_node_keys(node, f"group '{'.'.join(path)}'")
        shape = {key: node[key] for key in NODE_KEYS if key in node and key not in ("groups", "commands")}
        child_taxonomy, child_flat = lower(node.get("groups") or {}, path)
        if child_taxonomy:
            shape["groups"] = child_taxonomy
        taxonomy[str(name)] = shape
        flat[".".join(path)] = {str(command): dict(spec or {})
                                for command, spec in (node.get("commands") or {}).items()}
        flat.update(child_flat)
    return taxonomy, flat


# --- the transparent level (si#344): real in the tree, absent from the command line ---------------------


def elide_transparent(tree: dict) -> tuple[dict, dict[str, str]]:
    """The tree with every TRANSPARENT node replaced by its children, plus where each child came from.

    `ci` and `cd` are nodes of the platform's tree (si#344): the group lock sees them, so `ci: deploy:`
    is refused by the same rule that refuses any undeclared path, and the area of every phase is a
    statement the catalogue makes once. They are NOT part of a command's path: `./simplon.sh build image`
    stays exactly that (decision 1). Folding them away here, after `merge` and before `lower`, is what
    lets everything downstream - `Manifest.groups`, the CLI, taskgen, completion, the workflow generator
    - receive the paths it has always received.

    `env_first:` on a transparent node is handed to each child, because the child is what survives: `cd`
    is env-first so that whatever stands under it takes an environment (decision 5).

    Only the TOP level is walked. The catalogue declares transparent nodes nowhere else, and a product
    cannot declare one at all (`load` refuses it), so a deeper one would be a catalogue defect rather
    than a shape to support.

    A name hoisted twice - from two transparent siblings, or beside a visible sibling of the same name -
    would be two groups with one command-line path. That is refused here, naming both internal paths.

    A transparent node's OWN `commands:` are refused too, rather than dropped with the node: a command
    on it would have no path, and folding it away would load green a command that runs nowhere - the
    "nothing to do" that is really a failure.
    """
    elided: dict = {}
    origin: dict[str, str] = {}
    areas: dict[str, str] = {}
    for name, node in (tree or {}).items():
        name = str(name)
        node = node or {}
        if node.get("transparent"):
            if node.get("commands"):
                raise ValueError(
                    f"group '{name}' is transparent and declares `commands:`. A transparent node is "
                    f"skipped when the CLI path is built, so a command on it would have no path - place "
                    f"it on one of its groups")
            for child, child_node in (node.get("groups") or {}).items():
                child = str(child)
                _refuse_a_second_path(child, f"{name}.{child}", origin)
                hoisted = dict(child_node or {})
                if node.get("env_first"):
                    hoisted["env_first"] = True
                elided[child] = hoisted
                origin[child] = f"{name}.{child}"
                areas[child] = name
        else:
            _refuse_a_second_path(name, name, origin)
            elided[name] = node
            origin[name] = name
    return elided, areas


#: The three top-level sections a product declares its commands in (si#344). `ci` and `cd` are
#: transparent nodes of the platform's tree; `support` is a group node in its own right.
AREAS = ("ci", "cd", "support")

#: Keys under `cd:` that are product DATA rather than groups: the environment matrix (`default`,
#: `environments`, read by `simplon.domain.environments`) and the location axis (`site`, reserved, si#344).
CD_DATA_KEYS = ("default", "environments", "site")

#: The kernel tree a load WITHOUT a catalogue merges onto (`locked=False`). It exists only so that such a
#: load reads `ci:` the way every product does, with `build` on the command line rather than `ci build`.
#: It is a second statement of which areas are transparent, and
#: `test_the_skeleton_agrees_with_the_catalogue_on_the_areas` holds it to the catalogue's.
AREA_SKELETON = {"ci": {"transparent": True}, "cd": {"transparent": True, "env_first": True}}


def written_at(path: Iterable[str]) -> str:
    """Where a tree path is WRITTEN in a manifest (si#344): `ci: build:`, `support: groups: git:`.

    A refusal names the place its reader edits, and that place is neither the tree path (`ci.build`,
    which appears in no file) nor the command line (`build`, which drops the area). Under `ci:` and `cd:`
    the phase groups stand directly; every level below, and every level under `support:`, is a
    `groups:` key. The prefix is joined only when it is there, so an area on its own reads `support:`
    and never `support: :`.
    """
    parts = [str(part) for part in path]
    if not parts:
        return ""
    head, rest = parts[0], parts[1:]
    words = [f"{head}:"]
    if head in ("ci", "cd") and rest:
        words.append(f"{rest[0]}:")
        rest = rest[1:]
    words.extend(f"groups: {child}:" for child in rest)
    return " ".join(words)


def tree_path(path: str, areas: dict[str, str]) -> tuple[str, ...]:
    """A dotted path AFTER the transparent level was folded away (`build.wheel`), with its area put
    back (`('ci', 'build', 'wheel')`) - the inverse `written_at` needs. `areas` is what
    `elide_transparent` remembered; a path it does not name (`support`, or a catalogue-less load's own
    group) is its own tree path."""
    parts = tuple(str(path).split("."))
    area = (areas or {}).get(parts[0])
    return (area, *parts) if area else parts


def _cli_path(path: Iterable[str]) -> str:
    """A tree path as the command line spells it: the area is skipped, the rest is spaced."""
    parts = [str(part) for part in path]
    if len(parts) > 1 and parts[0] in ("ci", "cd"):
        parts = parts[1:]
    return " ".join(parts)


def tree_from_areas(data: dict, phases: dict[str, tuple[str, ...]]) -> dict:
    """The product's `ci:` / `cd:` / `support:` sections as ONE tree for `merge`.

    Under `ci:` and `cd:` the phase groups stand directly (`ci: build:`), where the tree nests children
    under `groups:`; this wraps them. The data keys under `cd:` are not groups and are left out here -
    `simplon.domain.environments` reads them from the document. `support:` already IS a group node.

    `phases` maps an area to the phase groups the PLATFORM declares under it (read off the catalogue's
    tree by the loader, so this module keeps no second list). It is empty for a load with no catalogue,
    and then there is nothing to name an unknown key against.
    """
    tree: dict = {}
    for area in ("ci", "cd"):
        section = data.get(area)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(
                f"`{area}:` is not a mapping: found {type(section).__name__} instead. It maps each phase "
                f"group ({_phases_of(area)}) to its node - check the indentation under this key")
        known = phases.get(area, ())
        groups = {}
        for name, node in section.items():
            if area == "cd" and name in CD_DATA_KEYS:
                continue
            # The area is skipped on the command line, so a command written on it has no path. Said here,
            # first, because left alone it is read as a phase group called "commands" and surfaces as a
            # group-lock message about a group the product never meant (or, with no catalogue, as a group).
            if name == "commands":
                first = known[0] if known else ("build" if area == "ci" else "deploy")
                raise ValueError(
                    f"`{area}: commands:` stands directly under the area. Commands belong to a phase "
                    f"group - `{area}: {first}: commands:` - because the area itself is skipped on the "
                    f"command line")
            if area == "cd" and known and name not in known:
                raise ValueError(
                    f"`cd: {name}:` is neither a phase group nor a data key. Under `cd:` stand the phase "
                    f"groups {', '.join(known)} and the data keys {', '.join(CD_DATA_KEYS)}")
            refuse_area_shape(node, area, name)
            groups[name] = node
        # A section holding only data (`cd:` with nothing but its environments) names no group. Left out
        # rather than handed to `merge` as an empty node, which a catalogue-less load would refuse as a
        # group that "declares no commands" - a promise the product never made.
        if groups:
            tree[area] = {"groups": groups}
    if data.get("support") is not None:
        # `support:` IS a group node, so its own `transparent:` is checked as well as its children's.
        refuse_area_shape(data["support"], "support", "")
        tree["support"] = data["support"]
    return tree


def refuse_area_shape(node: object, area: str, name: str, below: tuple[str, ...] = ()) -> None:
    """Refuse what a group under `ci:` / `cd:` / `support:` may not say about its own shape (si#344).

    `node` comes first because the census measures a rule by the first argument it was handed, and the
    loader also runs this over the CATALOGUE's `ci` groups - the kernel is held to `env_first:` too.
    `below` is the path from `name` down to `node` as the recursion walks it; the location is the tree
    path handed to `written_at`, so a nested group reads `ci: build: groups: x:` and not a hand-joined
    spelling that drops the colons.
    """
    if not isinstance(node, dict):
        return
    where = written_at((area, name, *below) if name else (area, *below))
    if "transparent" in node:
        raise ValueError(
            f"`{where}` declares `transparent:`. Which nodes are transparent is the platform's "
            f"statement (the catalogue's `groups:`), so that `ci` and `cd` are skipped on the command "
            f"line in every product and nothing else is - remove the key")
    if area == "ci" and "env_first" in node:
        raise ValueError(
            f"`{where}` declares `env_first:`. Nothing under `ci:` takes an environment - a build, a "
            f"test and a release run the same in every environment; what takes one stands under `cd:`, "
            f"which is env-first as a whole. Remove the key, or move the commands that need an "
            f"environment under `cd:`")
    for child, child_node in (node.get("groups") or {}).items():
        refuse_area_shape(child_node, area, name, (*below, str(child)))


def _phases_of(area: str) -> str:
    return "build, test, release" if area == "ci" else "deploy, monitor"


def _refuse_a_second_path(name: str, path: str, origin: dict[str, str]) -> None:
    if name in origin:
        raise ValueError(
            f"group '{name}' is reached through two transparent nodes, '{origin[name]}' and '{path}', "
            f"and both would be '{name}' on the command line. A transparent node is skipped when the CLI "
            f"path is built, so its children's names must be unique across all of them - rename one in "
            f"the platform's `groups:`")


def platform_groups(tree: dict) -> frozenset[str]:
    """The platform's group names as a coordinate can name them: the first VISIBLE level of its tree.

    si#34's placement rule is stated over these. Before si#344 they were simply the top-level keys; with
    `ci` and `cd` transparent, the top-level keys are `ci`, `cd` and `support`, and reading those would
    make `build:image` a family overnight - the exact failure si#344 measured.
    """
    return frozenset(elide_transparent(tree)[0])


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


def shape_is_the_platforms(path: Iterable[str], key: str) -> str:
    """The refusal a product gets for restating the SHAPE of a group the platform declares.

    It had two callers until si#344: `check_env_groups` raised it for `env_groups:`, the top-level
    spelling of `env_first: true` (si#43). That key went with the old form, and the rule with it, so
    `merge` is the one caller left. `path` is the TREE path, named where it is written (`written_at`).
    """
    return (f"`{written_at(path)}` declares `{key}:`, which the platform's node already sets. A product "
            f"may add commands and sub-groups to a platform group, never change its shape - change it in "
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
    to the catalogue it was given, which in every product is one (`simplon.domain.context` always passes it);
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
                f"`{written_at(path)}` is not a mapping: found {type(node).__name__} instead. A "
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
            # Named where it is written, and its siblings named as what stands beside it THERE: under
            # `ci:` that is build, release, test - never `ci, cd, support`, which are not groups to the
            # person writing `ci:` (si#344).
            beside = f"under `{written_at(_path)}`" if _path else "at the top level"
            raise ValueError(
                f"`{written_at(path)}` names a group the platform's tree does not declare. "
                f"The platform owns which groups exist, so that the same groups and the same general "
                f"tasks are there in every product. Available {beside}: "
                f"{', '.join(sorted(out)) or '(none)'}. Either put these commands in one of those, or "
                f"declare the new group in the platform's `groups:` - once, for everybody")
        _check_node_keys(node, f"`{written_at(path)}`")
        base = out[name]
        merged = dict(base)
        for key, value in node.items():
            if key == "groups":
                merged["groups"] = merge(base.get("groups") or {}, value, path,
                                         product_tasks=product_tasks, catalogue_tasks=catalogue_tasks,
                                         locked=locked)
            elif key == "commands":
                merged["commands"] = _merge_commands(base.get("commands") or {}, value, path,
                                                     product_tasks=product_tasks or {},
                                                     catalogue_tasks=catalogue_tasks or {})
            elif own:
                merged[key] = value
            else:
                raise ValueError(shape_is_the_platforms(path, key))
        if _is_empty(merged):
            raise ValueError(
                f"`{written_at(path)}` declares no commands. A group this manifest names is a "
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


def _merge_commands(base: dict, extra: dict, path: tuple[str, ...],
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

    `path` is the group's TREE path: a command is named the way the command line spells it, and the
    place to edit the way the manifest writes it (si#344).
    """
    where = _cli_path(path)
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
                    f"under this command in `{written_at(path)} commands: {name}:`. If it should not, drop "
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
#
# `unattended` (si#267) is here rather than on the command because it is a fact about the BODY: `test:walk`
# asks a person to answer each scenario, and it asks that of every product that imports it. Declared once
# in the catalogue, it is true for everybody - which is the same argument the coordinate space itself
# runs on. A command may still override it, because a product can wrap a body in a way that changes the
# answer, and the override is the instance's to make.
INHERITED = ("help", "passthrough_args", "unattended")

# What a TASK may declare. Everything else that `_CommandSpecModel` accepts belongs to the instance:
# a template that pinned a value, hid itself or planned other commands would not be a template.
TASK_KEYS = ("impl", "help", "passthrough_args", "params", "unattended", "input", "output")
COMMAND_ONLY_KEYS = ("hidden", "keep_awake", "stop_on_failure", "parallel", "depends_on", "with", "task")


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
                f"it instantiates. Move it to the command under `ci:`, `cd:` or `support:`")
        if key not in TASK_KEYS:
            raise ValueError(
                f"task '{name}' declares unknown key `{key}:`. A task takes "
                f"{', '.join(TASK_KEYS)} - check the spelling")
    ports.declared(name, spec)


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
        if "consumes" in spec:
            raise ValueError(
                f"command '{where}' declares `consumes:`, and an aggregate runs no task, so it has no port to "
                f"bind - bind the port on the command that runs the task")
        produced = spec.get("produces")
        if produced is not None:
            # si#344 C.3: the one output an aggregate names is its release bundle; which aggregates may name
            # one, and what kind it is, is rule 8 (ports._check_bundles), decided over the loaded manifest.
            if not isinstance(produced, dict) or not produced \
                    or not all(isinstance(v, str) and v.strip() for v in produced.values()):
                raise ValueError(
                    f"command '{where}' declares `produces:` as {produced!r}: an aggregate's one output is "
                    f"written `produces: {{ release: <artifact> }}`")
            spec["produces"] = {str(k): (v.strip(),) for k, v in produced.items()}
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
    task_ports = ports.of(ref, product_tasks)
    bound = ports.bindings(where, ref, spec, task_ports)
    # Rule 7 (spec C.5, si#344 C.2): a binding hands the artifact's name to its port's parameter, so `with:`
    # on that same parameter is a second source for one fact.
    twice = sorted(p.param for p in task_ports
                   if p.param and p.name in bound[ports.SIDE[p.direction]] and p.param in (with_ or {}))
    if twice:
        raise ValueError(
            f"command '{where}' binds a port and also pins {', '.join(twice)} with `with:`. The binding "
            f"hands the artifact's name to that parameter - drop it from `with:`")
    # `with: { name: X }` alone is read as the binding (decided 2026-10-14, si#344)
    # - stripped, as `produces:` and `consumes:` are, so both spellings of one binding read one name (si#420)
    for p in task_ports:
        side = bound[ports.SIDE[p.direction]]
        value = (with_ or {}).get(p.param)
        if p.param and p.name not in side and isinstance(value, str) and value.strip():
            side[p.name] = (value.strip(),)
    by_binding: dict[str, str] = {}
    handed: dict[str, str] = {}   # param -> the port that handed it, for the message below
    for p in task_ports:
        if not p.param or p.name not in bound[ports.SIDE[p.direction]]:
            continue
        artifact = bound[ports.SIDE[p.direction]][p.name][0]
        if p.param in by_binding and by_binding[p.param] != artifact:
            raise ValueError(
                f"command '{where}' binds port '{handed[p.param]}' to '{by_binding[p.param]}' and port "
                f"'{p.name}' to '{artifact}', and both hand their artifact's name to `{p.param}` - the body "
                f"receives one name, so the other binding would be lost; bind them to one artifact, or give "
                f"the task's ports their own `param:`")
        by_binding[p.param], handed[p.param] = artifact, p.name

    out = {"impl": template["impl"], **spec, "task": ref}
    out.pop("produces", None)
    out.pop("consumes", None)
    for key, side in bound.items():
        if side:
            out[key] = side
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
    pinned_values = {**(with_ or {}), **by_binding}
    presented = [p for p in task_ports if p.param in by_binding and p.param in own
                 and p.name in bound[ports.SIDE[p.direction]] and p.param not in (with_ or {})]
    if presented:
        port = presented[0]
        raise ValueError(
            f"command '{where}' binds port '{port.name}', which hands the artifact's name to `{port.param}`, and "
            f"also declares `params:` for {port.param}. A bound parameter is off the command line, so its "
            f"presentation renders nowhere - drop the `params:` entry")
    pinned = sorted(set(pinned_values) & set(own))
    if pinned:
        raise ValueError(
            f"command '{where}' pins {', '.join(pinned)} with `with:` and also declares `params:` for "
            f"it. A pinned parameter is off the command line, so its presentation renders nowhere - "
            f"drop the `params:` entry, or drop the pin if the user should still be able to set it")
    if by_binding:
        out["with"] = pinned_values
    params = {key: value for key, value in {**(template.get("params") or {}), **own}.items()
              if key not in pinned_values}
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
    """The flat-form entries of a block of group nodes, keyed as they are written."""
    if not isinstance(groups, dict):
        return {}
    return {str(name): node for name, node in groups.items() if _is_old_form_node(node)}


def _area_groups(data: dict) -> dict:
    """The group nodes a manifest writes under `ci:`, `cd:` and `support:` - where the flat form lands
    after `simplon manifest migrate` (si#344), which moves `groups:` into the areas without reading what
    each node holds. `support:` is a group node itself; under `cd:` the data keys are not groups."""
    found: dict = {}
    for area in ("ci", "cd"):
        section = data.get(area)
        if isinstance(section, dict):
            found.update({name: node for name, node in section.items()
                          if not (area == "cd" and name in CD_DATA_KEYS)})
    if "support" in data:
        found["support"] = data["support"]
    return found


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
#: renderer of the same thing was the second source si#85 struck. Deep-linked to the migration's own
#: heading rather than to the page root, because the page is long and "search it for a heading" is the
#: instruction a reader in the middle of a failed load least wants.
_TREE_FORM_DOCS = "https://marcozwyssig.github.io/simplon/how/manifest/"
_TREE_FORM_MIGRATION = _TREE_FORM_DOCS + "#the-flat-form-and-how-to-leave-it"


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
    # Read from the areas rather than from `groups:`: a `groups:` manifest is refused before this runs
    # (`check_no_pre_si344_form`), and its migration carries a flat node across unchanged - so the areas
    # are where a flat-form manifest is still found, one refusal after the cut's.
    groups = old_form_groups(_area_groups(data))
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
    #
    # One line per FINDING and not per SHAPE, with two exceptions that are not cosmetic - each is a case
    # where a reader following the shared line literally is refused a second time by this same function:
    #
    #  - `placing` shares the "a command instantiates a task" line with `groups`, but its body is ALREADY
    #    under `tasks:`; what makes it flat is the `group:` key, and a note that never says to delete it
    #    describes a fix that does not load.
    #  - `coordinate_keyed` covers two different files. A bare coordinate names the KERNEL's body. One
    #    carrying its own `impl:` is the PRODUCT's body under a name shaped like the platform's, and
    #    telling its owner that "the body stays in the kernel" points at a body that is not theirs.
    notes = []
    if groups:
        notes.append("a command is an INSTANCE of a task: declare the body once under `tasks:` and let "
                     "the command point at it with `task:`, under `ci: build: commands:` (or the "
                     "phase it belongs to), `cd: deploy: commands:` or `support: commands:`")
    if placing:
        notes.append("a task no longer places its own command: keep the body under `tasks:`, DELETE its "
                     "`group:` key, and add the command that instantiates it under "
                     "`ci: build: commands:` (or the phase it belongs to), `cd: deploy: commands:` or "
                     "`support: commands:` with `task:`")
    own_bodied = [name for name in coordinate_keyed
                  if isinstance(tasks.get(name), dict) and tasks[name].get("impl")]
    if [name for name in coordinate_keyed if name not in own_bodied]:
        notes.append("a catalogue task keeps its body in the kernel - the command names the coordinate "
                     "(`task: \"<namespace>:<name>\"`) and copies nothing")
    if own_bodied:
        notes.append(f"task(s) {', '.join(repr(name) for name in own_bodied)} declare an `impl:` of "
                     f"their own under a coordinate-shaped name, so the body is YOURS and not the "
                     f"platform's - keep it, rename the task to a bare name, and have the command point "
                     f"at that name rather than at the coordinate")
    if stale_import:
        notes.append("the catalogue's own commands arrive by merging its tree, so `import:` has nothing "
                     "left to do - delete the section")
    raise ValueError(
        "this manifest is written in the flat command form, which no longer loads: the form was "
        "abolished in 0.4.0 and this kernel is past it.\n\nWhat says so here: "
        + "; ".join(found) + ".\n\nWhat it becomes:\n"
        + "\n".join(f"  - {note}" for note in notes)
        + "\n\nThis migration is documented at\n  " + _TREE_FORM_MIGRATION
        + "\nand the shape it leads to at\n  " + _TREE_FORM_DOCS
        + "\n\nNothing here rewrites the file for you: the sections have to be edited by hand, which is "
          "also the only way your comments survive the move.")


# --- the cut: the form si#344 replaced, refused by name ------------------------------------------------
#
# `groups:`, `env_groups:`, a top-level `default:` / `environments:` and a top-level `site:` were the
# manifest's shape until si#344 put the commands under `ci:` / `cd:` / `support:`, the matrix under
# `cd:` and the documentation site under `website:`. The way out is `simplon manifest migrate`, which
# reads the document as YAML and loads no manifest - so it still works on one this kernel refuses.
#
# `env_groups:` took its rule with it (si#43, `check_env_groups`): the key let a product say
# `env_first: true` about a platform group from the top level of the file, and that rule refused the
# contradiction. With env-first decided by the area - everything under `cd:`, nothing under `ci:` - there
# is no second spelling left to contradict the first, and `Manifest.env_groups` is read off the tree.

#: The way out, named for both routes a product runs the kernel by. `<orch-dir>` and `<kernel image>` are
#: placeholders on purpose: this loader is handed TEXT, not a launcher, so it cannot know either.
#: `ProductContext.manifest` - the one place a product loads its manifest, and the one that knows the
#: product root - fills them from what the launcher exported (`LAUNCH_ORCH_DIR`, `LAUNCH_IMAGE_PIN`).
ORCH_DIR_PLACEHOLDER = "<orch-dir>"
IMAGE_PLACEHOLDER = "<kernel image>"
MIGRATE_COMMAND = "simplon manifest migrate"
_MIGRATE = (
    "Rewrite it with the migration, which loads no manifest and so works on this one:\n"
    f"  venv:      {ORCH_DIR_PLACEHOLDER}/.venv/bin/{MIGRATE_COMMAND} {{name}}\n"
    "  container: docker run --rm --user \"$(id -u):$(id -g)\" -v \"$PWD:/src\" -w /src "
    f"{IMAGE_PLACEHOLDER} {MIGRATE_COMMAND} {{name}}")

#: The keys that make a top-level `site:` the DOCUMENTATION site (now `website:`) rather than the
#: deployment location, which si#344 reserved under `cd:`.
DOCS_SITE_KEYS = ("image", "base_url", "theme", "source", "output")


AREAS = ("ci", "cd", "support")


def _distance(a: str, b: str) -> int:
    """Edits from `a` to `b` - insert, delete, substitute, or swap two neighbours - so `ic` is one from `ci`."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


_AREA_KEYS = ("commands", "environments")


def _area_key_at(value: object, path: str) -> str | None:
    """The first path below `value` that holds a key only an area carries (`_AREA_KEYS`), or None."""
    if isinstance(value, dict):
        for key in _AREA_KEYS:
            if key in value:
                return f"{path}.{key}"
        items: Iterable[tuple[str, object]] = ((f"{path}.{k}", v) for k, v in value.items())
    elif isinstance(value, list):
        items = ((f"{path}[{i}]", v) for i, v in enumerate(value))
    else:
        return None
    for where, inner in items:
        found = _area_key_at(inner, where)
        if found:
            return found
    return None


def check_no_misspelt_area(data: dict, manifest_path: str | None) -> None:
    """Refuse a top-level section that carries what only an area carries, but is not one (si#388).

    DIAGNOSIS. A top-level key the kernel does not read is a product data section (#159), so `ic:` for `ci:`
    used to load with rc 0 and lose every command under it - 21 of simplon's own 40, measured - while the
    catalogue's commands kept `help` looking whole; a misspelt `cd:` lost the environment matrix the same
    way. The shape tells the two apart: only an area places commands (`commands:`) or declares the matrix
    (`environments:`), so a data section that carries either at any depth is a misspelt area. Measured over
    the eight reachable manifests on 2026-10-13: no data section carries either key (`impl:` is carried -
    `suites:` gates in netctl and swi - and `default:` is, netctl's `instance:`, which is why neither is a
    test), and every area that places a command carries `commands:`. `tasks:` holds the bodies, not
    placements, and `groups:` is refused before this runs.
    """
    name = manifest_path or "the manifest"
    for key, value in data.items():
        if key in AREAS or key in ("tasks", "groups"):
            continue
        where = _area_key_at(value, str(key))
        if where is None:
            continue
        nearest = min(AREAS, key=lambda area: _distance(str(key), area))
        raise ValueError(
            f"{name} declares `{key}:`, which is not an area, yet it carries `{where}`: only `ci:`, `cd:` "
            f"and `support:` place commands or declare environments, and a top-level section the kernel "
            f"does not read is product data, so nothing in it would take effect. Did you mean `{nearest}:`?")


def check_no_pre_si344_form(data: dict, manifest_path: str | None) -> None:
    """Refuse every key of the form si#344 replaced, by name, with the way out.

    DIAGNOSIS, all of it: `_ManifestModel` ignores unknown top-level keys, so without this a `groups:`
    manifest would load as a product with no commands and a top-level `environments:` would leave every
    deploy without a matrix - green at load, wrong at the first command. Runs FIRST, before any check
    could report a symptom instead - `check_no_old_form` included: a manifest still on the flat form is
    on `groups:` too, and its first way out is this migration, after which the flat groups stand in the
    areas and that check names them there.

    Since si#344 B2 it refuses cut 2's spellings too - `images:`, an `artifacts:` entry with `source:` or
    with no `kind:`, and `deploy: source: { images: }` - which the same command rewrites.
    """
    name = manifest_path or "the manifest"
    if data is None:
        # si#388: an empty document (nothing, `---`, only comments) parses to None. It used to be read as
        # `{}` and load as a product with no `product:` and only the catalogue's commands - rc 0 for a
        # file that says nothing at all.
        raise ValueError(
            f"{name} is empty: it declares no `product:` and no commands - write at least `product: <name>` "
            f"and the areas (ci, cd, support) that place its commands")
    if not isinstance(data, dict):
        # Before any `in`: on a STRING that is a substring test, and the first `.get` after it an
        # AttributeError naming nothing. A document that parsed to a scalar or a list is said as one.
        raise ValueError(
            f"{name} is not a mapping: found {type(data).__name__} instead. A manifest maps its top-level "
            f"keys (product, tasks, ci, cd, support, ...) to their values")
    how = _MIGRATE.format(name=manifest_path or "<manifest>.yaml")
    if "groups" in data:
        raise ValueError(
            f"{name} declares `groups:`, which si#344 replaced: commands stand under `ci:` (build, test, "
            f"release), `cd:` (deploy, monitor) and `support:`, and the command line does not change:\n"
            f"  ci:\n    build:\n      commands: {{ ... }}\n{how}")
    if "env_groups" in data:
        raise ValueError(
            f"{name} declares `env_groups:`, which si#344 deleted: everything under `cd:` takes an "
            f"environment and nothing under `ci:` does, so the structure says it. Delete the key.\n{how}")
    for key in ("default", "environments"):
        if key in data:
            raise ValueError(
                f"{name} declares `{key}:` at the top level; since si#344 it stands under `cd:`, beside "
                f"the commands that take an environment.\n{how}")
    # si#344 B2 (cut 2): `images:` folded into `artifacts:`, `source:` renamed `path:`, a `kind:` on every
    # entry. Each would otherwise reach `artifactsection.check` as "an unknown kind" or be ignored outright,
    # which names a symptom; this names the form and the command that rewrites it.
    if "images" in data:
        raise ValueError(
            f"{name} declares `images:`, which si#344 folded into `artifacts:`: each image is an entry of "
            f"`kind: image`, and a bare reference such as `web: web:local` is "
            f"`web: {{ kind: image, local: \"web:local\" }}`:\n"
            f"  artifacts:\n    app:\n      kind: image\n      registry: ...\n{how}")
    artifacts = data.get("artifacts")
    if isinstance(artifacts, dict):
        for entry, body in artifacts.items():
            if isinstance(body, dict) and "source" in body:
                raise ValueError(
                    f"{name}: `artifacts: {entry}:` declares `source:`, which si#344 renamed `path:` - where "
                    f"the artifact lies once it is built.\n{how}")
            if isinstance(body, dict) and "kind" not in body:
                raise ValueError(
                    f"{name}: `artifacts: {entry}:` declares no `kind:`; since si#344 every entry names one "
                    f"of {', '.join(artifactsection.REFINES)}, and the migration derives it from the command "
                    f"that reads the entry.\n{how}")
    deploy = data.get("deploy")
    source = deploy.get("source") if isinstance(deploy, dict) else None
    if isinstance(source, dict) and "images" in source:
        raise ValueError(
            f"{name}'s `deploy: source:` names `images:`, which si#344 folded into `artifacts:` - write "
            f"`source: {{ artifacts: {source['images']} }}`.\n{how}")
    if "site" in data:
        # `in`, not `is not None`: a bare `site:` is a key of the old form too, and ignoring it is the
        # silence this function exists to break.
        site = data["site"]
        if isinstance(site, dict) and any(k in site for k in DOCS_SITE_KEYS):
            raise ValueError(
                f"{name} declares a top-level `site:` with the documentation site's keys; since si#344 "
                f"that section is `website:`, and `site:` is the deployment location under `cd:`.\n{how}")
        raise ValueError(
            f"{name} declares a top-level `site:`. The deployment location stands under `cd: site:` "
            f"(si#344), and the documentation site is `website:` - move it to whichever it is")


# --- a declared task nobody places is a task on OFFER (si#53) -----------------------------------------
#
# `check_every_task_is_used` stood here and refused it. It was the one expression rule the kernel did not
# apply to itself - "Scoped to the PRODUCT on purpose" - and si#48 measured what that exemption was worth:
# the rule would have refused 14 of the kernel's own 22 catalogue tasks. It was also the only one of the
# sixteen with no measured cause in ticket, commit or docstring, and over every reachable manifest - this
# kernel's own and the five then in `surface.CONSUMERS` - it had never refused anything: `unused = 0` in every
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
                                       catalogue_tasks: dict | None = None,
                                       areas: dict[str, str] | None = None) -> None:
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
                f"command '{_cli_path(tree_path(path, areas or {}))} {name}' - the one that bears its "
                f"name - {runs} instead. That is a half-finished move or a typo, not an offer: the "
                f"body this manifest still carries "
                f"({dead}) is reachable from nowhere, and until now nothing said so. Either point "
                f"`{written_at(tree_path(path, areas or {}))} commands: {name}:` at `task: {name}`, or "
                f"delete the `tasks: {name}:` declaration whose body no longer runs. A task NO command "
                f"names is untouched by this - declaring more than you place is what a catalogue is "
                f"for (si#53)")


# --- placement or family: what a coordinate's namespace says about where it may go (si#34) ------------


def check_coordinate_placement(flat: dict, platform_groups: frozenset[str],
                               areas: dict[str, str] | None = None) -> int:
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
            # Named where the manifest WRITES the group (si#344): `ci: build:`, `support:` - `areas` is
            # what the fold remembered of the level the flat path no longer carries.
            home = written_at(tree_path(namespace, areas or {}))
            raise ValueError(
                f"command '{placed_in} {name}' places the coordinate '{ref}', and '{namespace}' is one "
                f"of the platform's own group names. A coordinate that starts with one says where the "
                f"task belongs, so '{ref}' belongs under `{home}` and nowhere else - this "
                f"places it under '{placed_in}'. Move the command to `{home} commands: "
                f"{name}:`, or - if this body really is a family each product places where it likes - "
                f"give it a namespace in the platform catalogue that names no group, the way `docs:site` "
                f"can sit under `build` in one product and under `release` in another. The names that "
                f"carry a placement are the platform's groups: {', '.join(sorted(platform_groups))} - "
                f"the phases of the delivery loop, plus the group that supports them")
    return ruled
