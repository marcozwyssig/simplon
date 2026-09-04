"""Pure CLI command taxonomy + env-gate decisions for a CI/CD-loop command layout. A product supplies its
GROUPS (group -> the command names it owns) and the subset of env-first groups; this engine answers whether
a token names a group or a flat command, whether it requires an env, and the env-gate verdict. Pure data +
decisions, no Typer, fully unit-testable.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaxonomyNode:
    """One node of the command tree: the commands it owns, its child groups, and whether it is env-first.

    A node is addressed by its dotted PATH from the root (`support`, `support.git`). `env_first` marks the
    ROOT of an env-first subtree; every descendant inherits it (see group_requires_env), so the flag is
    declared once and never restated per node.
    """
    name: str
    commands: tuple[str, ...] = ()
    groups: Mapping[str, "TaxonomyNode"] = field(default_factory=dict)
    env_first: bool = False


def merge_trees(catalogue: dict[str, TaxonomyNode],
                product: dict[str, TaxonomyNode]) -> dict[str, TaxonomyNode]:
    """Merge the platform catalogue's taxonomy with the product's own.

    Both arguments are SHAPE declarations - a `taxonomy:` block in one file each. A group declared in both
    is an error rather than a precedence rule: with a winner, a reader has to know which file won in order
    to predict the surface, and the shadowed declaration is invisible in the one that lost. With an error
    there is no winner to reason about, only a contradiction to fix - which is what lets the catalogue take
    the tree over one group at a time, leaving a half-migrated tree that works rather than one that
    silently disagrees with itself.

    What is NOT a contradiction, and never reaches here: a product's bare `groups:` key naming a group the
    catalogue shapes. That key carries the group's MEMBERS, and contributing members to a catalogue group
    is the entire point of the catalogue owning the loop (netctl#1444). The loader filters those out
    before merging; passing them in would have made "the platform owns the tree" unimplementable.
    """
    clashes = sorted(set(catalogue) & set(product))
    if clashes:
        raise ValueError(
            f"group(s) declared in BOTH the catalogue and the product manifest: {', '.join(clashes)}. "
            f"A group belongs to exactly one of them - remove it from the product manifest once the "
            f"catalogue owns it.")
    return {**catalogue, **product}


class CommandTaxonomy:
    """A CI/CD command taxonomy: which commands belong to which group, and which groups are env-first.

    Env-AGNOSTIC groups take no env; the env-first CD groups are invoked env-first (`<env> <group> <cmd>`).
    A command's GROUP - not a hand-maintained per-command set - decides whether it accepts an env.
    """

    def __init__(self, groups: dict[str, tuple[str, ...]], env_groups: frozenset[str]) -> None:
        self.groups = groups
        self.env_groups = env_groups
        # The DECLARED shape is flat (group -> commands), which is a tree of depth one. Building it here
        # rather than at every call site means the flat and the nested constructors share one engine.
        self.tree: dict[str, TaxonomyNode] = {
            name: TaxonomyNode(name=name, commands=tuple(cmds), env_first=name in env_groups)
            for name, cmds in groups.items()
        }
        self._index()

    @classmethod
    def from_tree(cls, tree: dict[str, TaxonomyNode]) -> "CommandTaxonomy":
        """Build a taxonomy from an already-nested tree (what a catalogue manifest declares).

        The flat constructor stays the product path until the catalogue exists; this is the nested one.
        Both end up holding the same `tree` attribute, so every method below is written once.
        """
        obj = cls.__new__(cls)
        obj.tree = tree
        obj.groups = {name: node.commands for name, node in tree.items()}
        obj.env_groups = frozenset(name for name, node in tree.items() if node.env_first)
        obj._index()
        return obj

    def resolve_path(self, path: str | None) -> TaxonomyNode | None:
        """The node a dotted path names (`support`, `support.git`), or None if no such node exists."""
        if not path:
            return None
        node: TaxonomyNode | None = None
        children: Mapping[str, TaxonomyNode] = self.tree
        for part in path.split("."):
            node = children.get(part)
            if node is None:
                return None
            children = node.groups
        return node

    def _index(self) -> None:
        """Index every leaf name against EVERY group PATH that owns it, walking the whole tree.

        A flat top-level alias depends on the NAME, not on the depth: `support.git`'s `commit` and a
        top-level `commit` produce the same leaf name, so nesting a group costs nothing at the surface.

        multi-owner index: command name -> EVERY group that owns it, in declaration order. The same
        name may live in several groups (#519: `test all` next to `deploy all`); such a name is
        addressable only via its group token and has no flat form. The flat reverse index holds the
        UNAMBIGUOUS names only - an ambiguous one is deliberately absent, so resolve_group() treats its
        bare token as unknown and a CLI knows not to register a flat alias for it.
        """
        owners: dict[str, tuple[str, ...]] = {}

        def walk(children: Mapping[str, TaxonomyNode], prefix: str) -> None:
            for name, node in children.items():
                here = f"{prefix}.{name}" if prefix else name
                for cmd in node.commands:
                    owners[cmd] = (*owners.get(cmd, ()), here)
                walk(node.groups, here)

        walk(self.tree, "")
        self.command_groups: dict[str, tuple[str, ...]] = owners
        self.command_group: dict[str, str] = {
            cmd: paths[0] for cmd, paths in owners.items() if len(paths) == 1
        }

    def is_ambiguous(self, name: str) -> bool:
        """True iff the command name is owned by MORE than one group (so it has no flat form)."""
        return len(self.command_groups.get(name, ())) > 1

    def group_requires_env(self, group: str) -> bool:
        """True iff the group PATH is inside an env-first subtree.

        The flag is declared on the subtree ROOT and inherited by every descendant, so `deploy.rescue` is
        env-first because `deploy` is, without restating it. Walking down and returning at the first
        env-first ancestor is the whole rule.
        """
        # The path must EXIST before its ancestors are consulted. Walking and short-circuiting at the
        # first env-first ancestor would answer True for `deploy.nope`, gating a group that does not
        # exist - and an unknown token has to reach the "ok" verdict, never a backend gate.
        if self.resolve_path(group) is None:
            return False
        children: Mapping[str, TaxonomyNode] = self.tree
        for part in group.split("."):
            node = children[part]
            if node.env_first:
                return True
            children = node.groups
        return False

    def is_flat_command_group(self, group: str) -> bool:
        """True for a single-member group whose only command shares the group's name (e.g. `build`).

        Registering such a group as a sub-app AND its member as a same-named flat command is a name
        collision (the group wins), so a CLI collapses these to ONE visible flat top-level command. The
        group stays in the taxonomy as the single source of truth for the env-gate, so an agnostic flat
        command still rejects an explicit env exactly as a grouped one would."""
        node = self.resolve_path(group)
        if node is None:
            return False
        # Compare against the node's own SEGMENT, not the full path: `support.doctor` collapses when its
        # single member is `doctor`. Resolving by path rather than reading the top-level projection is
        # what makes this answer correct at depth > 1 instead of silently False.
        return len(node.commands) == 1 and node.commands[0] == group.rsplit(".", 1)[-1]

    def is_group_default_command(self, group: str) -> bool:
        """True for a MULTI-member group that ALSO contains a member whose name equals the group name.

        Such a group is a sub-app whose siblings are subcommands, but whose bare token (no subcommand)
        runs the namesake member as the group's DEFAULT action: `<product> build` runs the `build`
        member's pipeline, `<product> build diff` runs the `diff` sibling, and `<product> build --help`
        lists the siblings. It is the multi-member counterpart of is_flat_command_group (a single-member
        same-named group that collapses to ONE flat top-level command); the two are mutually exclusive.
        This preserves the bare group-token muscle memory when a discipline gains sibling commands."""
        node = self.resolve_path(group)
        if node is None:
            return False
        return len(node.commands) > 1 and group.rsplit(".", 1)[-1] in node.commands

    def resolve_group(self, token: str | None) -> str | None:
        """The group a leading command token belongs to: the token itself if it names a group, else the
        group of the flat command with that name, else None (unknown token, --help, internal)."""
        if token is None:
            return None
        if token in self.groups:
            return token
        return self.command_group.get(token)

    def env_verdict(self, token: str | None, env_explicit: bool) -> str:
        """The env-gate decision for a leading command token:
          - "reject-env":   an explicit env was given to an agnostic group -> error.
          - "gate-backend": an env-first CD group -> the caller must gate on the active backend.
          - "ok":           nothing to do (agnostic without env, unknown token, --help path).
        """
        group = self.resolve_group(token)
        if group is None:
            return "ok"
        if self.group_requires_env(group):
            return "gate-backend"
        if env_explicit:
            return "reject-env"
        return "ok"
