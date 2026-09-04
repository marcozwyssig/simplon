"""Named, isolated deployment environments: a product's environments.yml parsed into a validated Registry.

parse is pure (no I/O). The product supplies the set of valid backend names (each product knows its own
backends, e.g. a local lab vs a cloud provider) and owns the stateful registry lookup + the
active-environment gate on top of these types.
"""
from __future__ import annotations

import os
from typing import Iterable, Mapping, NamedTuple

import yaml


class Environment(NamedTuple):
    name: str
    backend: str
    description: str


class Registry(NamedTuple):
    environments: dict[str, "Environment"]
    default: str


def parse(text: str, valid_backends: Iterable[str]) -> Registry:
    """Parse an environments.yml TEXT document into the registry (pure; unit-tested). Thin wrapper over
    parse_data for the standalone-file form; the validation lives in parse_data."""
    return parse_data(yaml.safe_load(text) or {}, valid_backends)


def parse_data(data: Mapping[str, object], valid_backends: Iterable[str]) -> Registry:
    """Build the registry from an ALREADY-parsed mapping - a product's standalone environments.yml OR the
    `environments:`/`default:` section of its one manifest (delivery.context.manifest_data()). Validates
    that every backend is one of valid_backends and that `default` names a real environment, so a bad
    descriptor fails loudly here, not deep in a deployment."""
    valid = tuple(valid_backends)
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


# --- the provider every adopting product had scaffolded into its own package -------------------------

LOCAL = "local"


class Provider:
    """The stateful half of the environments seam, built from a product's three values instead of copied.

    `bootstrap.py` used to WRITE this out as ~90 lines of `orchestrator/environments.py` into every
    product, and three products then carried three copies of the same logic. They did not stay the same:
    the scaffold's `default()` reads the manifest only while its `current()` also reads the env var, so
    the two answer differently the moment the variable is set - and biz-cockpit had already had to repair
    that by hand (#88). A copy that has to be repaired per product is a kernel object with the serial
    numbers filed off.

    What actually differs between products is three values: the env var the active environment rides in,
    the backend names that product implements, and how its shim spells a command. Everything else -
    reading the matrix out of the manifest, the precedence, the gate - is the same everywhere.

    Satisfies `delivery.cli.EnvironmentProvider` structurally, exactly as the generated module did, so a
    product swaps `environments` for `environments.Provider(...)` and nothing downstream notices.
    """

    def __init__(self, env_var: str, *, shim: str, valid_backends: Iterable[str] = (LOCAL,),
                 local: str = LOCAL, fallback: str = "dev") -> None:
        self.ENV_VAR = env_var
        self.LOCAL = local
        self._valid = tuple(valid_backends)
        self._shim = shim
        self._fallback = fallback

    def registry(self) -> Registry:
        """The environment matrix out of the product's ONE manifest.

        A manifest with no `environments:` section falls back to a single local environment rather than
        raising: a product that has not reached deployment yet still has to be able to run its CLI."""
        from delivery import context  # local: context imports the manifest layer, this module is a leaf

        data = context.current().manifest_data()
        if not data.get("environments"):
            name = self._fallback
            return Registry({name: Environment(name, self.LOCAL, "Local development environment.")}, name)
        return parse_data(data, self._valid)

    def names(self) -> list[str]:
        return list(self.registry().environments)

    def default(self) -> str:
        """The environment a command targets when no env token was given: the exported ENV_VAR when it
        names a known environment, else the manifest's `default:`.

        ONE precedence, and `current()` reads it too - which is the divergence this class removes.
        `delivery.cli.main` consumes a leading env token only when that token names no GROUP, so an
        environment whose name is also a group name (netctl and biz-cockpit both have some) can only be
        reached through the variable. If `default()` ignored it, the CLI would select one environment
        while the commands acted on another:

            explicit env token  >  exported ENV_VAR  >  the manifest's `default:`
        """
        registry = self.registry()
        wanted = os.environ.get(self.ENV_VAR, "").strip()
        return wanted if wanted in registry.environments else registry.default

    def get(self, name: str) -> "Environment | None":
        return self.registry().environments.get(name)

    def current(self) -> Environment:
        """The active environment - `default()` resolved against the matrix."""
        return self.registry().environments[self.default()]

    def is_local(self, name: str | None = None) -> bool:
        env = self.get(name) if name else self.current()
        return env is not None and env.backend == self.LOCAL

    def require_backend(self, backend: str = "") -> None:
        """Gate a deployment command on the active environment's backend, so a target whose backend the
        product has not implemented dies clean instead of mis-running the local path."""
        from delivery import log  # local: keeps this module importable by anything, log imports nothing

        wanted = backend or self.LOCAL
        env = self.current()
        if env.backend != wanted:
            log.die(f"environment '{env.name}' needs backend '{wanted}', has '{env.backend}'")

    def command_hint(self, env: str, command: str) -> str:
        """How to reach `command` for environment `env` ON THE CLI, in the form that actually dispatches.

        The group/environment token collision is invisible until an error message hands an operator a
        line that silently targets something else: with a `test` GROUP present, `<shim> test deploy down`
        runs the group, not the test instance. Read off the live manifest taxonomy, so a renamed group
        cannot leave a stale instruction behind in a runbook."""
        from delivery import context

        if env in context.current().manifest().taxonomy().groups:
            return f"{self.ENV_VAR}={env} {self._shim} {command}"
        return f"{self._shim} {env} {command}"
