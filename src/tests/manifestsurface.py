"""The CLI surface of a loaded manifest, as plain data a golden file can hold (si#344 plan A).

The surface is what decision 1 promises does not change: every group path, every command in it in
order, what each command runs (`impl`) or plans (`depends_on`), and which groups are env-first. Help
texts are included because a migration that lost a `help:` would change `--help`.
"""
from __future__ import annotations

from simplon.domain.manifest import Manifest


def cli_surface(mf: Manifest) -> dict:
    tax = mf.taxonomy()
    return {
        "groups": {group: list(members) for group, members in sorted(mf.groups.items())},
        "commands": {
            group: {name: {"impl": spec.impl, "depends_on": list(spec.depends_on), "help": spec.help}
                    for name, spec in sorted(specs.items())}
            for group, specs in sorted(mf.commands.items())
        },
        "env_first": sorted(group for group in mf.groups if tax.group_requires_env(group)),
    }
