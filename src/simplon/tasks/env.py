"""The environments listing command (netctl#1280, epic #1274 slice S6): a real Typer callback a
product's manifest points its `impl:` straight at.

Fully manifest-driven: the `environments:` mapping, the `default:` key and the new `env_var:` key (the
name of the environment variable a product's own env-first CLI prefix publishes the active environment
into, e.g. netctl's `NETCTL_ENV`) are all read RAW through `delivery.context.current().manifest_data()`.
`env_var:` is what makes this fully manifest-driven rather than needing a second, product-owned registry
beside `context` just to learn which variable to read.

Deliberately does NOT validate backend names against a registry (`delivery.environments.parse_data`
does that, with the product's own valid-backends set). A listing has nothing to reject: an unknown
backend must fail loudly the moment a command tries to USE that environment, which is the product's own
env parsing, not a read-only listing. Importing the product's backend registry here just to print a
column would be exactly the product knowledge this module must not carry.
"""
from __future__ import annotations

import os

from delivery import context, log


def _active(envs: dict, default: str, env_var: str) -> str:
    """The active environment name: the variable named by `env_var:` when it is set to a KNOWN
    environment, else `default:`. With `env_var:` absent from the manifest there is no variable to
    consult, so the default is the only sensible answer - not an error, since a listing must still work
    on a manifest that has not adopted the key yet."""
    if env_var:
        candidate = os.environ.get(env_var, "")
        if candidate in envs:
            return candidate
    return default


def environments() -> None:
    """List the named environments declared in the manifest, marking the active one. Select an
    environment env-first: `<product> <env> <command>` (falls back to `default:` with none given)."""
    ctx = context.current()
    data = ctx.manifest_data()

    envs = data.get("environments") or {}
    if not envs:
        raise ValueError(f"{ctx.manifest_path}: 'environments' section is missing or empty")
    default = str(data.get("default", "")).strip()
    if default not in envs:
        raise ValueError(f"{ctx.manifest_path}: 'default' must name a declared environment, got '{default}'")
    env_var = str(data.get("env_var", "")).strip()

    active = _active(envs, default, env_var)
    log.info(f"environments (active: {active}; select env-first, e.g. `{ctx.name} <env> <command>`)")
    for name, spec in envs.items():
        spec = spec or {}
        mark = "*" if name == active else " "
        backend = str(spec.get("backend", ""))
        description = str(spec.get("description", ""))
        print(f"  {mark} {name:<11} {backend:<9} {description}")
