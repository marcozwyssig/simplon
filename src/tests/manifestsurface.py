"""The CLI surface of a loaded manifest, as plain data a golden file can hold (si#344 plan A).

The surface is what decision 1 promises does not change: every group path, every command in it in
order, what each command runs (`impl`) or plans (`depends_on`), and which groups are env-first. Help
texts are included because a migration that lost a `help:` would change `--help`.
"""
from __future__ import annotations

from simplon.domain.command import AggregateCommand, TaskCommand
from simplon.domain.manifest import Manifest


def cli_surface(mf: Manifest) -> dict:
    tax = mf.taxonomy()
    return {
        "groups": {group: list(members) for group, members in sorted(mf.groups.items())},
        "commands": {
            # si#400 4d: each kind carries only its own fields; the golden keeps both keys, empty on the other kind
            group: {name: {"impl": spec.impl if isinstance(spec, TaskCommand) else "",
                           "depends_on": list(spec.depends_on) if isinstance(spec, AggregateCommand) else [],
                           "help": spec.help}
                    for name, spec in sorted(specs.items())}
            for group, specs in sorted(mf.commands.items())
        },
        "env_first": sorted(group for group in mf.groups if tax.group_requires_env(group)),
    }
