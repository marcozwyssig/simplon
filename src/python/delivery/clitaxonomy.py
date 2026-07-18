"""Pure CLI command taxonomy + env-gate decisions for a CI/CD-loop command layout. A product supplies its
GROUPS (group -> the command names it owns) and the subset of env-first groups; this engine answers whether
a token names a group or a flat command, whether it requires an env, and the env-gate verdict. Pure data +
decisions, no Typer, fully unit-testable.
"""
from __future__ import annotations


class CommandTaxonomy:
    """A CI/CD command taxonomy: which commands belong to which group, and which groups are env-first.

    Env-AGNOSTIC groups take no env; the env-first CD groups are invoked env-first (`<env> <group> <cmd>`).
    A command's GROUP - not a hand-maintained per-command set - decides whether it accepts an env.
    """

    def __init__(self, groups: dict[str, tuple[str, ...]], env_groups: frozenset[str]) -> None:
        self.groups = groups
        self.env_groups = env_groups
        # multi-owner index: command name -> EVERY group that owns it, in declaration order. The same
        # name may live in several groups (#519: `test all` next to `deploy all`); such a name is
        # addressable only via its group token and has no flat form.
        self.command_groups: dict[str, tuple[str, ...]] = {}
        for g, cmds in groups.items():
            for cmd in cmds:
                self.command_groups[cmd] = (*self.command_groups.get(cmd, ()), g)
        # flat reverse index: command name -> its group, for UNAMBIGUOUS names only. An ambiguous name
        # is deliberately absent, so resolve_group() treats its bare token as unknown and a CLI knows
        # not to register a flat alias for it.
        self.command_group: dict[str, str] = {
            cmd: gs[0] for cmd, gs in self.command_groups.items() if len(gs) == 1
        }

    def is_ambiguous(self, name: str) -> bool:
        """True iff the command name is owned by MORE than one group (so it has no flat form)."""
        return len(self.command_groups.get(name, ())) > 1

    def group_requires_env(self, group: str) -> bool:
        """True iff the group is one of the env-first CD groups."""
        return group in self.env_groups

    def is_flat_command_group(self, group: str) -> bool:
        """True for a single-member group whose only command shares the group's name (e.g. `build`).

        Registering such a group as a sub-app AND its member as a same-named flat command is a name
        collision (the group wins), so a CLI collapses these to ONE visible flat top-level command. The
        group stays in the taxonomy as the single source of truth for the env-gate, so an agnostic flat
        command still rejects an explicit env exactly as a grouped one would."""
        cmds = self.groups.get(group, ())
        return len(cmds) == 1 and cmds[0] == group

    def is_group_default_command(self, group: str) -> bool:
        """True for a MULTI-member group that ALSO contains a member whose name equals the group name.

        Such a group is a sub-app whose siblings are subcommands, but whose bare token (no subcommand)
        runs the namesake member as the group's DEFAULT action: `<product> build` runs the `build`
        member's pipeline, `<product> build diff` runs the `diff` sibling, and `<product> build --help`
        lists the siblings. It is the multi-member counterpart of is_flat_command_group (a single-member
        same-named group that collapses to ONE flat top-level command); the two are mutually exclusive.
        This preserves the bare group-token muscle memory when a discipline gains sibling commands."""
        cmds = self.groups.get(group, ())
        return len(cmds) > 1 and group in cmds

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
