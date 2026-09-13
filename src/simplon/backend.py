"""Backend - a deployment backend as a polymorphic object, not a dispatched string (netctl#735).

An environment names HOW it is realised through its `backend` tag (a local lab, a cloud provider, ...).
Everywhere else the delivery kernel is deliberately functional - stateless ops are functions - but the
backend is the ONE axis that is genuinely meant to be extended, and switching on the tag
(`if backend == "local": ... elif backend == "exoscale": ...`) across the deploy/destroy/status paths is
the classic non-polymorphic smell exactly there. So the kernel keeps backend SELECTION polymorphic: a
product registers one `Backend` implementation per backend name and `resolve` maps an `Environment` to that
INSTANCE. Adding or extending a backend is then a new class, never a new `if`.

This mirrors the kernel's other product seams (`ProductContext`, the `EnvironmentProvider` Protocol): the
Protocol lives here, the concrete implementations live in the PRODUCT (netctl's `LocalBackend` for
containerlab, its `ExoscaleBackend` skeleton, ...). The coupling flows product -> kernel, never the reverse:
this module names no backend and no product, so a second consumer would register its own backends against
the same seam without editing anything here ("gleiche Maschine, anderer Katalog").

There is no second one today: measured across every repository that installs the kernel (#51), netctl's
`orchestrator.backends` is the only consumer. That does not weaken the seam - what makes it one is that
nothing in this file names a product - but it is what the file may claim. See `simplon.surface` for who
consumes the kernel and how that was measured.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Protocol, runtime_checkable

from simplon.environments import Environment

if TYPE_CHECKING:  # local: keeps this module a runtime leaf - nothing here imports the manifest layer
    from simplon.deployment import Version


@runtime_checkable
class Backend(Protocol):
    """One deployment backend: the object a product registers per `backend:` tag. Structural, so a
    product's implementation need not import or subclass anything named here - any object exposing these
    members satisfies it.

    ``name`` is the backend tag it answers to (the `backend:` value in the env matrix); it MUST equal the
    key the product registers the instance under, so `resolve` and the product's env-gate can identify it.
    ``deploy``/``destroy``/``status`` are the environment lifecycle a CD command drives against ONE target
    ``Environment``: deploy/destroy return a process return code (for the caller's exit), status returns the
    rendered status report. An unbuilt op raises ``NotImplementedError`` so a half-scaffolded backend fails
    loud instead of silently mis-running another backend's path.
    """

    name: str

    def deploy(self, env: Environment, version: "Version") -> int: ...
    def destroy(self, env: Environment) -> int: ...
    def status(self, env: Environment) -> str: ...


#: The product's backend registry, registered once at import by its composition root - the same shape
#: `simplon.context.set_current` has, and for the same reason: a CATALOGUE TASK is called by the CLI with
#: manifest-pinned parameters and nothing else, so it cannot be handed a registry as an argument the way
#: `resolve` is. si#235's `deploy:up` and `deploy:down` are the first readers.
#:
#: `resolve(env, backends)` keeps its explicit argument and is unchanged: a product calling it from its
#: OWN body passes its own registry and needs none of this. Registration is what a product does when it
#: wants the kernel's deploy commands instead of writing its own.
_REGISTERED: "dict[str, Backend]" = {}


def register(backends: Mapping[str, "Backend"]) -> None:
    """Register the product's backend registry for the kernel's own deploy commands."""
    _REGISTERED.clear()
    _REGISTERED.update(backends)


def registered() -> "dict[str, Backend]":
    """The registered registry, or a refusal naming what the product has to do.

    Refuses rather than answering with an empty mapping, because an empty registry and a product that
    forgot to register are the same value with two meanings - and `resolve` would then blame the
    ENVIRONMENT for naming a backend nobody registered, which sends the reader to the wrong file.
    """
    if not _REGISTERED:
        raise ValueError(
            "no deployment backend is registered, so the kernel's deploy commands have nothing to run. "
            "A product registers its own at import, beside its context: "
            "`simplon.backend.register({\"local\": MyBackend()})`")
    return dict(_REGISTERED)


def resolve(env: Environment, backends: Mapping[str, Backend]) -> Backend:
    """Resolve an environment to its `Backend` INSTANCE by the env's backend tag - the polymorphic
    replacement for `if env.backend == ...` dispatch. ``backends`` is the product-supplied registry (tag ->
    instance); the kernel names no backend. Fails loud (a `ValueError` naming the tag and the known
    backends) when a manifest env references a backend with no registered implementation, so the mistake
    dies here at selection time, not deep inside a deployment - the same fail-loud discipline as
    `environments.parse`.
    """
    try:
        return backends[env.backend]
    except KeyError:
        known = ", ".join(sorted(backends)) or "(none registered)"
        raise ValueError(
            f"environment '{env.name}': no backend registered for '{env.backend}' (known: {known})"
        ) from None
