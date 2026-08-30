"""Put a compose stack into an existing Portainer (platform#155, from biz-cockpit#154).

An operator who already runs Portainer does not want a second deployment path beside it. This module is
that path: it sends a RESOLVED compose document to Portainer's API and lets Portainer pull the images.
Nothing here installs Portainer, and nothing here knows which product is being deployed.

Why the caller sends the compose file instead of letting Portainer fetch it from a repository: this way
there is still ONE place the truth lives - the file in the repository, resolved against the target's
environment - and Portainer needs no read access to the source.

NOTHING HERE IS AN ADDRESS (the kernel's rule 8 equivalent). Portainer URL, token, endpoint and stack
name arrive at runtime from the environment; the module knows only the mechanism. The one product-shaped
value, the DEFAULT stack name, is a parameter: a kernel that spelled a product's name would be the very
coupling this move removes.

Deliberately `urllib` from the standard library rather than httpx: the orchestrator must run without an
extra dependency, including on a host that has nothing but Python.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

# The registry Portainer pulls the images from. A private package needs credentials stored IN Portainer;
# without them the pull fails with "unauthorized", and it fails at START time - the kind of failure worth
# announcing beforehand. Overridable, because not every product publishes to GHCR.
GHCR_HOST = "ghcr.io"

_TIMEOUT_S = 30.0


class PortainerError(RuntimeError):
    """A failure the caller can print as a sentence, not as a traceback."""


@dataclass(frozen=True)
class PortainerTarget:
    """Where the delivery goes. All of it is environment, none of it is code."""

    url: str
    token: str
    endpoint_id: int
    stack_name: str

    @staticmethod
    def from_env(
        env: str,
        default_stack: str,
        environ: dict[str, str] | None = None,
        secrets_hint: str = "",
    ) -> "PortainerTarget":
        """Read the target from the environment and say WHICH variable is missing.

        "PORTAINER_URL is not set" is an instruction; "None has no attribute rstrip" is an imposition.

        ``default_stack`` is the product's own name for this stack, used when PORTAINER_STACK is unset;
        ``secrets_hint`` is where the product keeps its secrets, appended to the error so the reader is
        told not only what is missing but where it belongs.
        """
        source = os.environ if environ is None else environ
        missing = [key for key in ("PORTAINER_URL", "PORTAINER_TOKEN") if not source.get(key)]
        if missing:
            hint = f" {secrets_hint}" if secrets_hint else ""
            raise PortainerError(
                f"Portainer is not configured for '{env}': {', '.join(missing)} missing.{hint}"
            )
        raw_endpoint = source.get("PORTAINER_ENDPOINT_ID", "1")
        try:
            endpoint_id = int(raw_endpoint)
        except ValueError as error:
            raise PortainerError(
                f"PORTAINER_ENDPOINT_ID must be a number, is {raw_endpoint!r}"
            ) from error
        return PortainerTarget(
            url=source["PORTAINER_URL"].rstrip("/"),
            token=source["PORTAINER_TOKEN"],
            endpoint_id=endpoint_id,
            stack_name=source.get("PORTAINER_STACK") or default_stack,
        )


def _request(target: PortainerTarget, method: str, path: str, body: dict | None = None) -> object:
    request = urllib.request.Request(
        f"{target.url}/api{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "X-API-Key": target.token,
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            payload = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:400]
        raise PortainerError(f"Portainer answered {error.code} to {method} {path}: {detail}")
    except OSError as error:
        raise PortainerError(f"Portainer unreachable at {target.url}: {error}") from error
    return json.loads(payload) if payload else None


def find_stack(target: PortainerTarget) -> dict | None:
    """The stack of this name on this endpoint, or None.

    Name AND endpoint: the same name can exist on two endpoints, and overwriting a foreign one would be
    the worst conceivable outcome.
    """
    stacks = _request(target, "GET", "/stacks")
    if not isinstance(stacks, list):
        return None
    for stack in stacks:
        if stack.get("Name") == target.stack_name and stack.get("EndpointId") == target.endpoint_id:
            return stack
    return None


def has_registry(target: PortainerTarget, host: str = GHCR_HOST) -> bool:
    """Whether Portainer holds credentials for this registry.

    Without them a private package fails at start time with "unauthorized" - better said beforehand.
    """
    registries = _request(target, "GET", "/registries")
    if not isinstance(registries, list):
        return False
    return any(host in str(registry.get("URL", "")) for registry in registries)


def deploy(target: PortainerTarget, compose_yaml: str, env_vars: dict[str, str]) -> str:
    """Create or update the stack. Returns what happened.

    On update `pullImage` is set: the whole point of this path is that Portainer fetches the NEW image.
    Without it, it cheerfully keeps running the old one and the failure looks like "the deployment did
    nothing".
    """
    payload_env = [{"name": name, "value": value} for name, value in sorted(env_vars.items())]
    existing = find_stack(target)
    if existing is None:
        _request(
            target,
            "POST",
            f"/stacks/create/standalone/string?endpointId={target.endpoint_id}",
            {
                "name": target.stack_name,
                "stackFileContent": compose_yaml,
                "env": payload_env,
            },
        )
        return f"stack {target.stack_name} created"
    stack_id = existing["Id"]
    _request(
        target,
        "PUT",
        f"/stacks/{stack_id}?endpointId={target.endpoint_id}",
        {
            "stackFileContent": compose_yaml,
            "env": payload_env,
            "prune": True,
            "pullImage": True,
        },
    )
    return f"stack {target.stack_name} updated (images pulled again)"
