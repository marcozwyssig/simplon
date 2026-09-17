"""Named, isolated deployment environments: a product's environments.yml parsed into a validated Registry.

parse is pure (no I/O). The product supplies the set of valid backend names (each product knows its own
backends, e.g. a local lab vs a cloud provider) and owns the stateful registry lookup + the
active-environment gate on top of these types.
"""
from __future__ import annotations

import os
from typing import Iterable, Mapping, NamedTuple

import yaml

from simplon import carrierspec


#: What a `repository:` block accepts, and - as in `carrierspec` - everything else is REFUSED rather than
#: ignored. The reason is the same one and it is not tidiness: this block is where somebody reaches for a
#: `password:` when the clone needs one, and a parser that skipped what it did not recognise would let
#: that sit in a committed file. `credential_from:` is the field that is there instead, and it names a
#: PREFIX.
REPOSITORY_KEYS = ("url", "ref", "compose", "credential_from")

#: What a repository that states neither means. `main` is the branch; `docker-compose.yml` in the root is
#: where Portainer itself looks when a stack names no file, so a product that puts it there says nothing.
DEFAULT_REF = "main"
DEFAULT_COMPOSE = "docker-compose.yml"


class Repository(NamedTuple):
    """Where the compose document is pulled from - by Portainer itself, not by the orchestrator.

    WHY THIS IS A BLOCK AND NOT THE ONE STRING IT WAS. si#5's vocabulary slice wrote `repository:` as a
    bare URL and left the file path implied, because Portainer defaults it. The first real consumer broke
    that: biz-cockpit's compose document lives at `deploy/provision/docker-compose.yml`, and a string
    cannot say so. `ref:` joins it for the same reason one level along - a product that deploys from a
    release branch has nowhere else to write it. The form was widened before the vocabulary was ever
    released, so no manifest had to be migrated; what it costs is that the simple case now writes `url:`.

    `credential_from` is the PREFIX the clone credential is read from - `GIT` means `GIT_USER` and
    `GIT_PASSWORD`, `credentials.py`'s convention unchanged - and it is EMPTY by default, because a public
    repository needs none. It is sent with every deployment rather than stored in Portainer (owner
    decision, 2026-09-15): a credential Portainer keeps is one the next reader of that stack inherits
    without asking for it.
    """

    url: str
    ref: str = DEFAULT_REF
    compose: str = DEFAULT_COMPOSE
    credential_from: str = ""


class Environment(NamedTuple):
    """One named environment.

    `required` and `optional` are the environment variables whose values are handed to the deployment, and
    both names say what they ENFORCE rather than what they contain (the consuming product asked for that,
    biz-cockpit#263: "nennt sie nach dem, was sie erzwingt"). A name in `required` must have a non-empty
    value when the deployment runs; a name in `optional` travels when it has one and is simply absent when
    it does not. A name in neither does not reach the deployment at all, so what a reader sees in these two
    lists is exactly what goes over.

    IT WAS ONE LIST FIRST, AND THE SECOND ONE IS NOT SYMMETRY - it is a case that one list could not say,
    and the case is worth recording because the first form looked complete. The same consumer writes
    `${SMALLINVOICE_CLIENT_SECRET:-}` in its compose document, where EMPTY MEANS "not connected": the
    integration is deliberately optional (their ADR 0020, their ticket #201), the composition root then
    does not wire the port, and the route answers 409 with a reason rather than inventing a stub. With one
    list there was no honest place for that variable. In `required` it makes the product uninstallable
    without a Smallinvoice account - undoing the ticket that made the integration optional. Out of the
    lists it never reaches the stack, so the integration is not optional but impossible. "Travels" and
    "may not be empty" are two statements, and one list was quietly making them one.

    `carrier`, `stack` and `repository` arrived with si#5 and all three DEFAULT TO EMPTY, which is what
    keeps the six products that declare none of them working unchanged. They are the chain: what this
    environment is realised on, what the deployment is called there, and where the compose document is
    pulled from - by Portainer itself, which is the owner decision of 2026-09-05 and the reason the
    repository is named here rather than resolved by the orchestrator.
    """

    name: str
    backend: str
    description: str
    carrier: str = ""
    stack: str = ""
    repository: "Repository | None" = None
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


class Registry(NamedTuple):
    environments: dict[str, "Environment"]
    default: str


def parse(text: str, valid_backends: Iterable[str]) -> Registry:
    """Parse an environments.yml TEXT document into the registry (pure; unit-tested). Thin wrapper over
    parse_data for the standalone-file form; the validation lives in parse_data."""
    return parse_data(yaml.safe_load(text) or {}, valid_backends)


def _repository(raw: object, where: str) -> "Repository | None":
    """The `repository:` block of one environment, or None when it declares none.

    ABSENT IS NOT EMPTY, which is why this answers None rather than a `Repository("")`: an environment
    that names no repository and one that names a repository with no URL are two different mistakes, and
    the second has to be told apart from the first or the refusal blames the wrong line.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"{where}: `repository:` must be a mapping with a `url:`, not {type(raw).__name__}. It says "
            f"where PORTAINER pulls the compose document from, and `compose:` says which file in there")
    unknown = sorted(str(k) for k in raw if str(k) not in REPOSITORY_KEYS)
    if unknown:
        raise ValueError(
            f"{where}: `repository:` does not take {', '.join(unknown)} - it takes "
            f"{', '.join(REPOSITORY_KEYS)}. A credential does not belong in a manifest at all: name the "
            f"environment-variable prefix with `credential_from:` and keep the secret out of the file")
    url = str(raw.get("url", "")).strip()
    if not url:
        raise ValueError(
            f"{where}: `repository:` declares no `url:`, so nothing says where the compose document is "
            f"pulled from")
    return Repository(
        url=url,
        ref=str(raw.get("ref", "") or DEFAULT_REF).strip(),
        compose=str(raw.get("compose", "") or DEFAULT_COMPOSE).strip(),
        credential_from=str(raw.get("credential_from", "")).strip(),
    )


#: The one variable name the KERNEL owns in a deployment's environment. A manifest may not also claim it:
#: the resolved version and an operator's exported value are two answers to one question, and whichever
#: won would make `--version` mean something different depending on a variable nobody printed.
#:
#: Spelled here rather than imported from `simplon.portainer`, which is the reader of it - this module is
#: the leaf that every backend's vocabulary goes through, and importing a backend into it would turn the
#: seam around.
KERNEL_VARIABLE = "SIMPLON_VERSION"


def _names(raw: object, key: str, where: str) -> tuple[str, ...]:
    """One of the two variable lists, validated as NAMES and never as values.

    ONE FUNCTION FOR BOTH, because every rule below is about what a manifest may WRITE and none of them is
    about which list it was written in. The difference between the two lists is read at deployment time -
    one must have a value, the other may not - and duplicating four refusals to express it here would make
    the census grow by four rules that say the same thing twice.

    A manifest names variables here; it never holds one. That is the same guarantee `credential_from:` and
    `url_from:` give one line up, and it is why a value that looks like `NAME=value` is refused - somebody
    writing a value into this list is writing a secret into a committed file, and it must not be read as a
    variable name that happens to contain an equals sign.
    """
    if raw is None:
        return ()
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(
            f"{where}: `{key}:` must be a list of variable NAMES, not {type(raw).__name__}. It says "
            f"which variables the deployment is given, and the values come from the environment the "
            f"deploy command runs in")
    names = []
    for entry in raw:
        name = str(entry).strip()
        if not name or "=" in name:
            raise ValueError(
                f"{where}: `{key}:` takes variable names, and {entry!r} is not one. A manifest names a "
                f"variable and never holds its value - the value is exported where the command runs")
        if name == KERNEL_VARIABLE:
            raise ValueError(
                f"{where}: `{key}:` may not name {KERNEL_VARIABLE} - the kernel sets it from the "
                f"version being deployed, and a second answer to that question would make `--version` "
                f"mean whatever happened to be exported")
        names.append(name)
    return tuple(names)


def parse_data(data: Mapping[str, object], valid_backends: Iterable[str]) -> Registry:
    """Build the registry from an ALREADY-parsed mapping - a product's standalone environments.yml OR the
    `environments:`/`default:` section of its one manifest (simplon.context.manifest_data()). Validates
    that every backend is one of valid_backends and that `default` names a real environment, so a bad
    descriptor fails loudly here, not deep in a deployment."""
    valid = tuple(valid_backends)
    # The carriers are read FIRST so an environment pointing at one that is not declared is refused by
    # name rather than failing later with an empty lookup. `declared` returns nothing for an absent
    # section, which is why a product that names no carrier is unaffected by any of this.
    carrier_names = set(carrierspec.declared(data))
    envs: dict[str, Environment] = {}
    declared = data.get("environments") or {}
    if not isinstance(declared, Mapping):
        raise ValueError("'environments' must be a mapping of environment name -> descriptor")
    for name, spec in declared.items():
        spec = spec if isinstance(spec, Mapping) else {}
        backend = str(spec.get("backend", "")).strip()
        if backend not in valid:
            allowed = " or ".join(f"'{b}'" for b in valid)
            raise ValueError(f"environment '{name}': backend must be {allowed}, got '{backend}'")
        carrier = str(spec.get("carrier", "")).strip()
        if carrier and carrier not in carrier_names:
            known = ", ".join(sorted(carrier_names)) or "none"
            raise ValueError(
                f"environment '{name}': carrier '{carrier}' is not declared - the '{carrierspec.SECTION}' "
                f"section declares: {known}")
        stack = str(spec.get("stack", "")).strip()
        if stack and not carrier:
            raise ValueError(
                f"environment '{name}': declares `stack: {stack}` and no `carrier:`, so there is "
                f"nowhere for that stack to go")
        repository = _repository(spec.get("repository"), f"environment '{name}'")
        if repository and not stack:
            raise ValueError(
                f"environment '{name}': declares a `repository:` and no `stack:`, so nothing says what "
                f"the compose document pulled from it would be deployed as")
        required = _names(spec.get("required"), "required", f"environment '{name}'")
        optional = _names(spec.get("optional"), "optional", f"environment '{name}'")
        both = sorted(set(required) & set(optional))
        if both:
            raise ValueError(
                f"environment '{name}': {', '.join(both)} stand(s) in both `required:` and `optional:`, "
                f"which says a value must be there and may be absent. One of the two lists is the answer")
        if (required or optional) and not stack:
            raise ValueError(
                f"environment '{name}': declares `required:`/`optional:` and no `stack:`, so there is no "
                f"deployment for those values to be given to")
        envs[str(name)] = Environment(str(name), backend, str(spec.get("description", "")),
                                      carrier=carrier, stack=stack, repository=repository,
                                      required=required, optional=optional)
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

    Satisfies `simplon.cli.EnvironmentProvider` structurally, exactly as the generated module did, so a
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
        from simplon import context  # local: context imports the manifest layer, this module is a leaf

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
        `simplon.cli.main` consumes a leading env token only when that token names no GROUP, so an
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
        product has not implemented dies clean instead of mis-running the local path.

        STILL HERE AND STILL THE PRODUCT'S TO CALL: a body that only works against one backend says so.
        What changed in si#288 is the CLI's own gate, which used to call this with `LOCAL` for every
        environment - see `require_drivable`.
        """
        from simplon import log  # local: keeps this module importable by anything, log imports nothing

        wanted = backend or self.LOCAL
        env = self.current()
        if env.backend != wanted:
            log.die(f"environment '{env.name}' needs backend '{wanted}', has '{env.backend}'")

    def require_drivable(self, drivable: "Iterable[str]") -> None:
        """Gate a CD command on whether the active environment's backend CAN BE DRIVEN (si#288).

        WHAT THIS REPLACES, and why the old question stopped being the right one. The CLI asked
        `is_local`, and on a no for any non-local environment it demanded `LOCAL` - which was sound when
        `local` was the only backend anybody had implemented (#11): a CD command aimed at an
        unimplemented target should fail clean rather than mis-run the local containerlab path.

        The kernel now ships a backend of its own and resolves a product's registrations beside it, so
        "is this backend local" and "can this backend be driven" are two questions. Asking the first one
        made `deploy up` unreachable for `backend: portainer` - the feature 0.16.0 released, blocked by
        the CLI 0.16.0 assembles, and every product adopting it needed a `Provider` subclass to get past
        its own kernel.

        The replacement refuses exactly what #11 meant to refuse and nothing else: a backend nobody has
        implemented. It is strictly more permissive for backends that resolve and identical for those
        that do not.
        """
        from simplon import log  # local: keeps this module importable by anything, log imports nothing

        known = tuple(drivable)
        env = self.current()
        if env.backend not in known:
            log.die(f"environment '{env.name}' has backend '{env.backend}', which nothing here can "
                    f"drive - this run resolves {', '.join(sorted(known)) or 'no backend at all'}. "
                    f"Register an implementation for it with `simplon.backend.register`, or point this "
                    f"environment at a backend that is already resolvable")

    def command_hint(self, env: str, command: str) -> str:
        """How to reach `command` for environment `env` ON THE CLI, in the form that actually dispatches.

        The group/environment token collision is invisible until an error message hands an operator a
        line that silently targets something else: with a `test` GROUP present, `<shim> test deploy down`
        runs the group, not the test instance. Read off the live manifest taxonomy, so a renamed group
        cannot leave a stale instruction behind in a runbook."""
        from simplon import context

        if env in context.current().manifest().taxonomy().groups:
            return f"{self.ENV_VAR}={env} {self._shim} {command}"
        return f"{self._shim} {env} {command}"
