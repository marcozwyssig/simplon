"""Named, isolated deployment environments: a product's environments.yml parsed into a validated Registry.

parse is pure (no I/O). The product supplies the set of valid backend names (each product knows its own
backends, e.g. a local lab vs a cloud provider) and owns the stateful registry lookup + the
active-environment gate on top of these types.
"""
from __future__ import annotations

from typing import Iterable, NamedTuple

import yaml


class Environment(NamedTuple):
    name: str
    backend: str
    description: str


class Registry(NamedTuple):
    environments: dict[str, "Environment"]
    default: str


def parse(text: str, valid_backends: Iterable[str]) -> Registry:
    """Parse an environments.yml document into the registry (pure; unit-tested). Validates that every
    backend is one of valid_backends and that `default` names a real environment, so a bad descriptor
    fails loudly here, not deep in a deployment."""
    valid = tuple(valid_backends)
    data = yaml.safe_load(text) or {}
    envs: dict[str, Environment] = {}
    for name, spec in (data.get("environments") or {}).items():
        spec = spec or {}
        backend = str(spec.get("backend", "")).strip()
        if backend not in valid:
            allowed = " or ".join(f"'{b}'" for b in valid)
            raise ValueError(f"environment '{name}': backend must be {allowed}, got '{backend}'")
        envs[str(name)] = Environment(str(name), backend, str(spec.get("description", "")))
    if not envs:
        raise ValueError("environment registry defines no environments")
    default = str(data.get("default", "")).strip()
    if default not in envs:
        raise ValueError(f"environment registry default '{default}' is not a defined environment")
    return Registry(envs, default)
