"""Put a compose stack into an existing Portainer (platform#155, from biz-cockpit#154; si#5 slice 3).

An operator who already runs Portainer does not want a second deployment path beside it. This module is
that path. Nothing here installs Portainer - `simplon.tasks.carrier` does that - and nothing here knows
which product is being deployed.

TWO ROUTES, AND THE SECOND ONE IS NOT A SECOND SOURCE. `deploy` sends a RESOLVED compose document as a
string; `deploy_from_repository` gives Portainer a repository and lets Portainer clone it. They are two
Portainer APIs for two different arrangements, not two ways of saying one thing:

  - the STRING route needs the caller to resolve the document and needs Portainer to have no read access
    to the source. It is what platform#155 built and what a consumer in this family calls today, through
    `PortainerTarget.from_env` and `deploy` - which is why those two are still here unchanged.
  - the GIT route is the owner's decision of 2026-09-15 for the kernel's own backend: Portainer holds the
    repository and re-clones it on every redeploy, so what ran is a commit rather than a string somebody's
    orchestrator assembled. It is also the only one of the two that survives an orchestrator that is not
    running - Portainer can redeploy the stack by itself.

The git route was MEASURED against a real Portainer before it was written (2026-09-15, carrier
`hausportainer`): a private repository with no credential answers *"Failed to download git repository:
authentication required: Repository not found."*, the same request with `repositoryAuthentication` and a
username and password answers 200 and creates the stack, a duplicate name answers 409 naming the
normalised name, and `PUT /stacks/{id}/git/redeploy` answers 200. Every one of those four is a branch
below.

NOTHING HERE IS AN ADDRESS (the kernel's rule 8 equivalent). Portainer URL, token, endpoint and stack
name arrive at runtime from the environment; the module knows only the mechanism. The one product-shaped
value, the DEFAULT stack name, is a parameter: a kernel that spelled a product's name would be the very
coupling this move removes.

Deliberately `urllib` from the standard library rather than httpx: the orchestrator must run without an
extra dependency, including on a host that has nothing but Python.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import posixpath
import re
import ssl
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import IO, TYPE_CHECKING, Callable, Mapping

import yaml

from simplon.adapters import docker
from simplon.manifest import environments

if TYPE_CHECKING:  # local: keeps the module head free of the manifest layer, the way `backend` does
    from simplon.model.carrierspec import Carrier
    from simplon.manifest.deployment import Version
    from simplon.manifest.environments import Directory, Environment, Repository

# The registry Portainer pulls the images from. A private package needs credentials stored IN Portainer;
# without them the pull fails with "unauthorized", and it fails at START time - the kind of failure worth
# announcing beforehand. Overridable, because not every product publishes to GHCR.
GHCR_HOST = "ghcr.io"

#: The backend tag this module answers to - the value an environment writes as `backend: portainer`. A
#: constant rather than a literal in two files, because `tasks.deploy` registers under it and the class
#: below must answer to the same string or `backend.resolve` finds an instance that says it is something
#: else.
BACKEND = "portainer"

#: The resolved version, handed to the stack as ONE variable. A compose document writes
#: `image: ghcr.io/acme/app:${SIMPLON_VERSION}` and the deployment means what it says.
#:
#: IT IS THE KERNEL'S, and `environments` owns the name because that is the module a manifest is refused
#: by for claiming it: the resolved version and an operator's exported value are two answers to one
#: question. Without this variable `deploy up --version 1.4.0` would print "deploying 1.4.0" and deploy
#: whatever the compose document happened to name - the defect this repository hunts, one command earlier.
VERSION_VAR = environments.KERNEL_VARIABLE

_TIMEOUT_S = 30.0

#: What Portainer's `Status` means, MEASURED against the real carrier on 2026-09-16 rather than read off
#: a document, because the numbers decide whether a deployment is reported as having worked:
#:
#:   1  the stack is up - a container of it was really running when this was seen
#:   3  Portainer is still working on it; it sat here for roughly twenty seconds while an image pulled
#:   4  it failed, and the last `DeploymentStatus` entry carries the sentence saying why
#:
#: The one that cost something to find is 3. `POST .../repository` answers **200 before any of this**:
#: the 200 means Portainer accepted the stack, not that the stack runs. A first draft of this module
#: returned "created" on that 200 and would have exited 0 on a deployment that failed to pull its images
#: - the defect this repository hunts, found by driving the real API instead of a double.
STATUS_UP = 1
STATUS_DEPLOYING = 3
STATUS_FAILED = 4

#: How long a deployment may take before the run stops waiting, and how often it looks. Pulling several
#: images over a home line is minutes, not seconds, so the wait is generous; what matters is that running
#: out of it is its own outcome and not silently one of the other two.
SETTLE_TIMEOUT_S = 600.0
_POLL_S = 2.0


#: What a carrier's `url_from:` prefix gains to name Portainer's address and its API token: `url_from: HAUS`
#: means `HAUS_URL` and `HAUS_TOKEN`. Written once, because two readers spell them: `from_carrier`, which
#: reads them, and `variables_read`, which tells the launcher to forward them (si#810).
URL_SUFFIX = "_URL"
TOKEN_SUFFIX = "_TOKEN"


def target_variables(url_from: str) -> "tuple[str, str]":
    """The (url, token) variable NAMES a carrier's `url_from:` prefix stands for."""
    return f"{url_from}{URL_SUFFIX}", f"{url_from}{TOKEN_SUFFIX}"


class PortainerError(RuntimeError):
    """A failure the caller can print as a sentence, not as a traceback."""


@dataclass(frozen=True)
class PortainerTarget:
    """Where the delivery goes. All of it is environment, none of it is code."""

    url: str
    token: str
    endpoint_id: int
    stack_name: str
    insecure: bool = False
    #: The credential PREFIX the ghcr.io registry entry is created from (si#783), `<url_from>_GHCR`; empty
    #: on a target that no carrier described, which then has nothing to create the entry from.
    registry_from: str = ""

    @staticmethod
    def from_carrier(carrier: "Carrier", stack_name: str,
                     environ: "dict[str, str] | None" = None) -> "PortainerTarget":
        """The target a manifest describes: the carrier says where and how, the environment says what.

        The carrier carries a PREFIX and never a value, so this is where the prefix becomes the two
        variables `credentials.py`'s convention stands for. It goes through `from_env` rather than beside
        it, because the refusal that names the missing variable is the half worth not having twice.
        """
        if carrier.portainer is None:
            raise PortainerError(
                f"carrier '{carrier.name}' declares no `portainer:` block, so this backend has nowhere "
                f"to put the stack. A carrier without one is a machine the kernel creates and does not "
                f"configure (si#258); give it `portainer: url_from: ...` to have a Portainer installed, "
                f"or point this environment at a backend the product registers itself")
        from simplon.kernel import secrets

        source = dict(os.environ if environ is None else environ)
        prefix = carrier.portainer.url_from
        url_var, token_var = target_variables(prefix)
        secrets.read(token_var, source)
        for suffix in (URL_SUFFIX, TOKEN_SUFFIX):
            if source.get(f"{prefix}{suffix}") and not source.get(f"PORTAINER{suffix}"):
                source[f"PORTAINER{suffix}"] = source[f"{prefix}{suffix}"]
        target = PortainerTarget.from_env(
            carrier.name, stack_name, environ=source,
            secrets_hint=f"The carrier names `url_from: {prefix}`, so it is read from "
                         f"{url_var} and {token_var}.")
        return replace(target, endpoint_id=carrier.portainer.endpoint,
                       insecure=carrier.portainer.insecure,
                       registry_from=registry_prefix(prefix))

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
        from simplon.kernel import secrets

        return PortainerTarget(
            url=source["PORTAINER_URL"].rstrip("/"),
            token=secrets.read("PORTAINER_TOKEN", source),
            endpoint_id=endpoint_id,
            stack_name=source.get("PORTAINER_STACK") or default_stack,
        )


def _context(target: PortainerTarget) -> "ssl.SSLContext | None":
    """The TLS context a target needs, or None for the default verifying one.

    MEASURED, not assumed (2026-09-16, against the Portainer `deploy carrier` had built): a verifying
    request to https://10.0.0.124:9443 fails with `CERTIFICATE_VERIFY_FAILED: self-signed certificate`
    and the same request with verification off answers 200. Portainer generates its own certificate on
    first start, so a carrier the kernel installed and did not give a certificate to is unreachable
    without this - and the manifest has to SAY so, which is what `portainer: insecure:` is for.
    """
    return ssl._create_unverified_context() if target.insecure else None


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
        with urllib.request.urlopen(  # noqa: S310
                request, timeout=_TIMEOUT_S, context=_context(target)) as response:
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

    AN ANSWER THAT IS NOT A LIST IS NOT "NO" (si#785). It used to come back as False, and a caller that
    refuses on False would send the operator to add an entry that may well be there. Portainer that
    could not be asked is neither "present" nor "missing", so it raises - as an unreachable one already
    does in `_request`.
    """
    registries = _request(target, "GET", "/registries")
    if not isinstance(registries, list):
        raise PortainerError(
            f"Portainer at {target.url} answered GET /registries with {type(registries).__name__} "
            f"rather than a list, so this run cannot tell whether it holds credentials for {host}")
    return any(host in str(registry.get("URL", "")) for registry in registries)


# --- the registry check before a deployment (si#785) -------------------------------------------------

#: What ghcr.io's anonymous token endpoint answered, MEASURED 2026-11-20 rather than read off a document,
#: because these three numbers are the whole of how the kernel tells a private package from a public one:
#:
#:   200  a public package: an anonymous pull token is handed out
#:   401  a private package: `UNAUTHORIZED`, "authentication required"
#:   403  a name ghcr.io does not serve: `DENIED`, "requested access to the resource is denied"
#:
#: Only the first two are verdicts. 403 is NOT "private" (the measured case was a repository that does not
#: exist), and a 5xx, a timeout or no connection says nothing at all; each of those is reported as "could
#: not tell" and refuses nothing - a failed probe is not a result.
GHCR_PUBLIC = "public"
GHCR_PRIVATE = "private"
_GHCR_ANSWERS = {200: GHCR_PUBLIC, 401: GHCR_PRIVATE}

#: The way out by hand. NOT "provider GitHub", which si#785 first wrote: Portainer CE 2.45.0 (the version
#: `tasks.carrier` installs) offers no GitHub registry type, neither in its UI (`registryTypes.js` ends at
#: 7, ECR) nor in `POST /registries` (`registry_create.go` validates 1-7). A custom registry is the form CE
#: has, and the one `create_registry` writes.
_REGISTRY_WAY_OUT = (
    "add one in Portainer under Registries (Custom registry, URL ghcr.io, authentication on, a GitHub "
    "token with read:packages)")

#: What `<url_from>` gains to name the ghcr.io credential (si#783): `url_from: HAUS` means `HAUS_GHCR_USER`
#: and `HAUS_GHCR_PASSWORD`, the latter a GitHub token with `read:packages`. `credentials.py`'s USER and
#: PASSWORD rather than a third spelling: the git clone credential (`credential_from:`) is a token in a
#: `_PASSWORD` already.
REGISTRY_SUFFIX = "_GHCR"


def registry_prefix(url_from: str) -> str:
    """The credential PREFIX the ghcr.io registry entry is created from, for a carrier's `url_from:`."""
    return f"{url_from}{REGISTRY_SUFFIX}"

#: Portainer's `RegistryType` for a custom registry: 3 in `api/portainer.go` and in the payload doc of
#: `api/http/handler/registries/registry_create.go`, both read at tag 2.45.0. `GithubRegistry` (8) exists
#: in the enum, and CE's create handler refuses it.
_PORTAINER_CUSTOM_REGISTRY = 3


def create_registry(target: PortainerTarget, username: str, token: str) -> dict:
    """Create Portainer's registry entry for ghcr.io from a read:packages token (si#783).

    The body is `registryCreatePayload` of Portainer CE 2.45.0. The token goes into the request body and
    nowhere else: not into a file, not into a message - `_request`'s error text carries the verb, the path
    and Portainer's answer, never the body. Portainer answers with the stored entry (`hideFields` drops
    the password); anything else is not "created" and raises, because the stack would then fail at start
    exactly as if nothing had been done.
    """
    created = _request(target, "POST", "/registries", {
        "Name": GHCR_HOST, "Type": _PORTAINER_CUSTOM_REGISTRY, "URL": GHCR_HOST,
        "Authentication": True, "Username": username, "Password": token})
    if not isinstance(created, dict) or "Id" not in created:
        raise PortainerError(
            f"Portainer at {target.url} answered POST /registries with {type(created).__name__} rather "
            f"than the entry it created, so this run cannot tell whether {GHCR_HOST} can be pulled from")
    return created


def _ensure_registry(target: PortainerTarget, private: "list[str]") -> None:
    """The ghcr.io entry the private images need: there, created from the environment, or refused.

    THE TOKEN IS READ HERE AND NOT EARLIER, and only when an entry is missing: a run whose Portainer
    already holds one is asked for nothing. Without it the entry stays absent and the run says which two
    variables would have created it - a missing capability is absent, never faked.
    """
    from simplon.adapters import credentials
    from simplon.kernel import log

    if has_registry(target):
        log.ok(f"Portainer holds a registry entry for {GHCR_HOST}, needed by {', '.join(private)}")
        return
    found = credentials.credential(target.registry_from, os.environ) if target.registry_from else None
    if found is None:
        refusal = (
            f"{', '.join(private)} {'is a private package' if len(private) == 1 else 'are private packages'}"
            f" on {GHCR_HOST} and the Portainer at {target.url} holds no registry entry for {GHCR_HOST}, "
            f"so the stack would fail at container start with 'unauthorized'.")
        if not target.registry_from:
            raise PortainerError(f"{refusal} To go on, {_REGISTRY_WAY_OUT}")
        user_var, password_var = credentials.variables(target.registry_from)
        unset = [name for name in (user_var, password_var) if not (os.environ.get(name) or "").strip()]
        raise PortainerError(
            f"{refusal} {' and '.join(unset)} {'is' if len(unset) == 1 else 'are'} not set: export "
            f"{user_var} (the GitHub account) and {password_var} (a token with read:packages) and the "
            f"entry is created on the next run, or {_REGISTRY_WAY_OUT}")
    username, token = found
    create_registry(target, username, token)
    log.ok(f"created Portainer's registry entry for {GHCR_HOST} as {username}, needed by "
           f"{', '.join(private)}")


def _ghcr_token_status(path: str) -> int:
    """The HTTP status ghcr.io's token endpoint gives an ANONYMOUS pull request for `owner/name`.

    Raises OSError when no answer came back at all, which the caller turns into "could not tell".
    """
    request = urllib.request.Request(
        f"https://{GHCR_HOST}/token?scope=repository:{path}:pull&service={GHCR_HOST}")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def ghcr_visibility(path: str) -> "tuple[str | None, str]":
    """Whether the ghcr.io package `owner/name` is public or private, or None with the reason why not."""
    try:
        status = _ghcr_token_status(path)
    except OSError as error:
        return None, f"ghcr.io could not be asked ({error})"
    verdict = _GHCR_ANSWERS.get(status)
    return verdict, "" if verdict else f"ghcr.io answered {status} to an anonymous pull token request"


_VARIABLE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?P<op>:?[-?])?(?P<default>[^}]*)\}"
                       r"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*)|(?P<dollar>\$))")


def _resolved(text: str, values: "Mapping[str, str]") -> str:
    """An image reference resolved the way compose resolves it against the values this deployment sends.

    `${X}`, `$X`, `${X:-default}` and `${X-default}` take the value or the default; a name with neither is
    left as written, so the caller sees a `$` and says it could not tell the registry rather than guessing
    one. Only the stack's own values are used - the kernel does not know what else Portainer holds.
    """
    def one(match: "re.Match[str]") -> str:
        if match.group("dollar"):
            return "$"
        name = match.group("braced") or match.group("bare")
        value = values.get(name, "")
        op = match.group("op") or ""
        if value or (name in values and op in ("-", "?")):
            return value
        if op in (":-", "-"):
            return _resolved(match.group("default"), values)
        return match.group(0)
    return _VARIABLE.sub(one, text)


def _ghcr_path(image: str) -> "str | None":
    """`owner/name` when `image` is on ghcr.io, otherwise None. The tag or digest is not part of it."""
    host, _, rest = image.partition("/")
    if host != GHCR_HOST or not rest:
        return None
    rest = rest.split("@", 1)[0]
    return rest.rsplit(":", 1)[0] if ":" in rest.rsplit("/", 1)[-1] else rest


def stack_images(compose: str, values: "Mapping[str, str]") -> "tuple[list[str], list[str]]":
    """The images a compose document names, resolved, and the ones whose reference stayed unresolved."""
    document = yaml.safe_load(compose) or {}
    services = document.get("services") if isinstance(document, dict) else None
    images: list[str] = []
    unresolved: list[str] = []
    for service in (services or {}).values():
        raw = service.get("image") if isinstance(service, dict) else None
        if not isinstance(raw, str) or not raw:
            continue
        image = _resolved(raw, values)
        (unresolved if "$" in image else images).append(image if "$" not in image else raw)
    return images, unresolved


def _compose_text(repository: "Repository") -> "str | None":
    """The compose document as THIS checkout holds it, or None when it is not here.

    A SECOND SOURCE, AND SAID SO. Portainer clones `repository.url` at `repository.ref`; this reads the
    file at the same path in the checkout the command runs in. For a product deploying its own repository
    that is the same document, give or take the ref; for one that is not, the file is absent and the
    caller says the check did not run rather than reading that as "no image".
    """
    from simplon.manifest import context  # was local for a leaf; si#808: `docker` loads it at import

    try:
        return (context.current().root / repository.compose).read_text(encoding="utf-8")
    except OSError:
        return None


def check_registry_access(target: PortainerTarget, repository: "Repository",
                          values: "Mapping[str, str]") -> None:
    """Refuse a stack naming a private ghcr.io image Portainer holds no registry entry for (si#785).

    WHY BEFORE AND NOT AFTER. Without the entry the stack is accepted, Portainer pulls, and the container
    fails at START with "unauthorized" - on the far side of the seam, after the stack exists. The facts
    that decide it are two calls away, so they are asked first.

    EVERY OUTCOME HAS ITS OWN VALUE, which is the point of the whole function:
      - no ghcr.io image, or only public ones: nothing to refuse, and Portainer is not asked;
      - a private one and Portainer holds a ghcr.io entry: deployed, and said;
      - a private one, Portainer holds none and `<url_from>_GHCR_USER`/`_PASSWORD` are set: the entry
        is created (si#783), and said;
      - a private one, Portainer holds none and the token is not set: refused, every such image named
        in one sentence, with the variables that would have created the entry;
      - Portainer could not say what it holds: `has_registry` raises - neither present nor missing;
      - ghcr.io could not say whether an image is private, its reference stayed unresolved, or the
        compose document is not in this checkout: said by name, refused on nothing.
    A PRESENT ENTRY IS NOT A PROVEN ONE: Portainer is not asked whether its token can read these packages.
    """
    from simplon.kernel import log

    compose = _compose_text(repository)
    if compose is None:
        log.warn(f"registry check did not run: {repository.compose} is not in this checkout, so the "
                 f"images Portainer will pull from {repository.url} could not be read here")
        return
    images, unresolved = stack_images(compose, values)
    for image in unresolved:
        log.warn(f"registry check: could not tell which registry {image} is on - its reference uses a "
                 f"value this deployment does not send")
    private: list[str] = []
    for image in images:
        path = _ghcr_path(image)
        if path is None:
            continue
        verdict, why = ghcr_visibility(path)
        if verdict == GHCR_PRIVATE:
            private.append(image)
        elif verdict is None:
            log.warn(f"registry check: could not tell whether {image} is private: {why}. If it is, "
                     f"Portainer needs a registry entry for {GHCR_HOST}")
    if private:
        _ensure_registry(target, private)


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


# --- the git route: Portainer holds the repository and re-clones it (si#5) ---------------------------

def _repository_url(url: str) -> str:
    """The URL Portainer clones, from what a manifest writes.

    A manifest says `url: github.com/you/myctl` because that is how a person writes a repository, and
    Portainer needs a scheme. Adding it here rather than refusing the short form keeps the manifest
    reading like the thing it describes; anything that already carries a scheme is passed through, so an
    ssh:// or a self-hosted https:// URL is untouched.
    """
    return url if "://" in url else f"https://{url}"


def _reference(ref: str) -> str:
    """The full git reference Portainer wants, from the branch name a manifest writes.

    `main` becomes `refs/heads/main`; anything already spelled as a reference is passed through, which is
    what lets a product deploy from a TAG (`refs/tags/v1.4.0`) without a second manifest key for the kind
    of reference it is.
    """
    return ref if ref.startswith("refs/") else f"refs/heads/{ref}"


def _authentication(credential: "tuple[str, str] | None") -> dict:
    """The three fields that decide whether Portainer authenticates the clone, or none of them.

    A public repository must not be sent `repositoryAuthentication: true` with two empty strings: the
    clone then fails on a credential nobody meant to supply, which is the same "nothing to do read as
    failed" shape this repository hunts everywhere else.
    """
    if credential is None:
        return {}
    user, password = credential
    return {"repositoryAuthentication": True,
            "repositoryUsername": user,
            "repositoryPassword": password}


def deploy_from_repository(target: PortainerTarget, repository: "Repository",
                           credential: "tuple[str, str] | None" = None,
                           env_vars: "dict[str, str] | None" = None) -> str:
    """Create the stack from its repository, or redeploy the one that is there. Returns what happened.

    THE TWO CALLS ARE NOT THE SAME CALL with a different verb, which is why this is not `deploy`'s shape
    with a URL swapped in. Creating takes the whole description - where the repository is, which
    reference, which file in it. Redeploying takes none of that: Portainer already holds it, and
    `PUT /stacks/{id}/git/redeploy` means "clone that again". Sending the description twice would put a
    second copy of it in Portainer's database, where nothing compares it with the manifest.

    The credential is sent with EVERY deployment rather than stored in Portainer (owner decision,
    2026-09-15), so a stack somebody opens in the Portainer UI carries no usable read access to the
    source repository.
    """
    payload_env = [{"name": name, "value": value}
                   for name, value in sorted((env_vars or {}).items())]
    existing = find_stack(target)
    if existing is None:
        _request(
            target,
            "POST",
            f"/stacks/create/standalone/repository?endpointId={target.endpoint_id}",
            {
                "name": target.stack_name,
                "repositoryURL": _repository_url(repository.url),
                "repositoryReferenceName": _reference(repository.ref),
                "composeFile": repository.compose,
                "env": payload_env,
                **_authentication(credential),
            },
        )
        _settled(target, find_stack(target), f"created from {repository.url} ({repository.ref})")
        return f"stack {target.stack_name} created from {repository.url} ({repository.ref})"
    stack_id = existing["Id"]
    _request(
        target,
        "PUT",
        f"/stacks/{stack_id}/git/redeploy?endpointId={target.endpoint_id}",
        {
            "env": payload_env,
            "prune": True,
            "pullImage": True,
            **_authentication(credential),
        },
    )
    _settled(target, find_stack(target), f"redeployed from {repository.url} ({repository.ref})")
    return f"stack {target.stack_name} redeployed from {repository.url} ({repository.ref})"


def _message(stack: dict) -> str:
    """The last thing Portainer said about this deployment, or nothing.

    The entries arrive oldest first and only the failing one carries a message, so the last non-empty one
    is the sentence a person needs. An empty answer is left empty rather than filled with "unknown error":
    a caller that invents a reason sends the reader looking for something that was never said.
    """
    said = [str(entry.get("Message") or "") for entry in (stack.get("DeploymentStatus") or [])]
    return next((message for message in reversed(said) if message), "")


def _settled(target: PortainerTarget, stack: "dict | None", what: str,
             timeout: float = SETTLE_TIMEOUT_S, now: "Callable[[], float]" = time.monotonic,
             sleep: "Callable[[float], None]" = time.sleep) -> dict:
    """Wait until the stack has stopped deploying, and refuse if it failed.

    WHY THIS EXISTS AT ALL, since the create call already answered 200. It answered 200 for accepting the
    stack. Against the real carrier a stack whose compose file did not exist was accepted with a 200 and
    then failed, and without this the command would have printed "created" and exited 0 over a deployment
    that pulled nothing - the recurring defect of this repository, at the last seam before the operator.

    THREE OUTCOMES, EACH WITH ITS OWN VALUE, which is the resolution this repository always reaches: up,
    failed with Portainer's own sentence, and still deploying when the wait ran out. The third is not
    folded into either of the others - a slow pull is not a failure, and an operator who is told the wait
    ended knows to look rather than to redeploy.
    """
    deadline = now() + timeout
    while stack is not None and stack.get("Status") == STATUS_DEPLOYING:
        if now() >= deadline:
            raise PortainerError(
                f"stack {target.stack_name} was {what} and is still deploying after {timeout:.0f}s, so "
                f"this run cannot say whether it came up. Portainer is still working on it - look there "
                f"rather than deploying again")
        sleep(_POLL_S)
        stack = find_stack(target)
    if stack is None:
        raise PortainerError(
            f"stack {target.stack_name} was {what} and is not there any more, so nothing of this "
            f"deployment survived to be reported on")
    if stack.get("Status") == STATUS_FAILED:
        raise PortainerError(
            f"stack {target.stack_name} was {what}, and Portainer could not bring it up: "
            f"{_message(stack) or 'it reports no reason'}")
    return stack


def remove(target: PortainerTarget) -> str:
    """Remove the stack, or say that it was not there.

    REFUSES rather than reporting success on an absent stack, the same way the kernel's client `down`
    refuses a version it never installed. "Removed nothing" and "removed the stack" are two outcomes and
    an operator tearing an environment down has to be able to tell them apart - especially here, where
    the likely cause is a `stack:` that does not say what they think it says.
    """
    existing = find_stack(target)
    if existing is None:
        raise PortainerError(
            f"there is no stack named '{target.stack_name}' on endpoint {target.endpoint_id}, so nothing "
            f"was removed. This Portainer carries: {_names(target) or '(no stacks)'}")
    _request(target, "DELETE", f"/stacks/{existing['Id']}?endpointId={target.endpoint_id}")
    return f"stack {target.stack_name} removed"


def _names(target: PortainerTarget) -> str:
    stacks = _request(target, "GET", "/stacks")
    return ", ".join(sorted(str(s.get("Name")) for s in stacks)) if isinstance(stacks, list) else ""


def describe(target: PortainerTarget) -> str:
    """What is deployed under this name, as a sentence a person reads.

    An absent stack is an ANSWER here and not a refusal, which is the opposite of `remove` on purpose:
    asking what is deployed and being told "nothing" is a complete answer to the question that was asked.
    """
    existing = find_stack(target)
    if existing is None:
        return (f"{target.stack_name}: not deployed on endpoint {target.endpoint_id} "
                f"({target.url} carries: {_names(target) or 'no stacks'})")
    origin = existing.get("GitConfig") or {}
    where = f" from {origin.get('URL')} ({origin.get('ReferenceName')})" if origin else ""
    return f"{target.stack_name}: stack {existing.get('Id')} on endpoint {target.endpoint_id}{where}"


# --- the backend the kernel ships (si#5 slice 3) -----------------------------------------------------

class PortainerBackend:
    """`backend: portainer` - a deployment the kernel itself can drive, with no product code at all.

    WHY THE KERNEL SHIPS THIS ONE AND NAMES NO OTHER. `simplon.adapters.backend` is the seam and stays what it is:
    a product registers an implementation per backend tag and nothing in that module names a backend. This
    class is not a hole in that design, it is the first thing the seam carries by default (owner decision,
    2026-09-15: "Backend im Kernel"). The reason is that the chain underneath it is already the kernel's:
    `deploy carrier` builds the Portainer, `carriers:` describes it, and `environments:` points at it. A
    product that had to write this class would be writing the far end of a pipe the kernel owns both ends
    of. A product that wants a DIFFERENT portainer backend still registers one and wins - see
    `tasks.deploy._backends`.

    WHAT IT PASSES TO THE DEPLOYMENT is `VERSION_VAR` plus whatever the environment's `required:` names,
    read out of the environment the command runs in. It carries NO COUNT of a consumer's variables here,
    and the omission is deliberate: this docstring used to say "~40, three of them secrets", taken off
    another repository's compose document on a day. The number was wrong within two days - a search for
    `[A-Z_]*` had stopped at a digit and missed four names - and nothing here could have noticed, because
    the truth lives in a repository this module cannot see. `surface.py` records the same lesson at
    length: a fact about somebody else's repository, copied into a comment, is a second source with no
    comparison. The ticket is biz-cockpit#263; read the count there, where it is measurable.
    """

    name = BACKEND

    def deploy(self, env: "Environment", version: "Version") -> int:
        from simplon.kernel import log

        target, repository = _target_for(env)
        if version.builds:
            raise ValueError(
                f"environment '{env.name}' is deployed by Portainer, which clones {repository.url} "
                f"itself - so there is nothing on this machine for it to deploy. Publish the version and "
                f"deploy that")
        values = {**stack_values(env), VERSION_VAR: version.tag}
        credential = _clone_credential(repository, env)
        # si#782, si#808 - the carrier is only asked about when there is something to check
        check_directories(target, env, create=bool(env.directories) and not _built_by_kernel(env),
                          values=values)
        check_registry_access(target, repository, values)
        log.info(f"{env.stack} <- {repository.url} ({repository.ref}), {repository.compose}")
        message = deploy_from_repository(target, repository, credential, env_vars=values)
        log.ok(f"{message}, {len(values)} value(s) incl. {VERSION_VAR}={version.tag}")
        return 0

    def destroy(self, env: "Environment") -> int:
        from simplon.kernel import log

        target, _ = _target_for(env)
        log.ok(remove(target))
        return 0

    def status(self, env: "Environment") -> str:
        target, _ = _target_for(env)
        return describe(target)


def stack_values(env: "Environment", environ: "Mapping[str, str] | None" = None) -> dict[str, str]:
    """The values this deployment is given, read out of the environment the command runs in.

    WHY THE COMMAND'S OWN ENVIRONMENT AND NOT PORTAINER'S STORED COPY (biz-cockpit#263, their answer):
    Portainer stores the stack's environment either way. The question is only whether its copy is an IMAGE
    that every deployment refreshes, or an ORIGINAL that nobody refreshes. Two sets of values, one in a
    repository and one maintained by hand in a web interface, are two masters of one thing - and once they
    drift the instance runs on values that are written down nowhere. So every deployment sends them again.

    AN EMPTY `required:` VALUE IS A FAILURE AND NOT A DEFAULT, and the consumer asked for this
    specifically, with the case that makes it worth the refusal. Their compose document writes
    `${COCKPIT_DATA_DIR:-${HOME}/.biz-cockpit}:/data`. If that variable does not arrive, compose does not
    fail - it falls back, and the bind mount lands in the CARRIER's `/root/.biz-cockpit` instead of
    `/srv/biz-cockpit/prod`. The container writes happily, the deployment looks green, and the database is
    outside everything `backup` knows about. An instance that runs and is not backed up is exactly this
    repository's recurring defect: green because nobody looks.

    AN ABSENT `optional:` VALUE IS NOT THE SAME THING AND MUST NOT BE MADE ONE. The same product writes
    `${SMALLINVOICE_CLIENT_SECRET:-}`, where empty is a STATEMENT - the integration is not connected, the
    composition root does not wire the port, and the route answers 409 with a reason. So an optional name
    with no value is left out of the payload entirely rather than sent as an empty string.

    THE CONDITION UNDER WHICH THAT CHOICE BECOMES VISIBLE IS WORTH NAMING, because it is this
    repository's own seam question - what meaning does a value carry on the far side that it did not carry
    on this side? Absent and `""` are the same to a consumer whose setting is a `str` defaulting to empty
    and whose decisions are truth tests. They stop being the same the moment a setting distinguishes "not
    said" from "explicitly empty" - a `None` beside a `""` - and that pattern is in deliberate use
    elsewhere in this family for exactly that distinction. Leaving the name out keeps the far side's
    two meanings two, where sending `""` would collapse them into one and nobody would have written down
    which.

    ALL OF THEM AT ONCE. An operator repairing eight variables one run at a time is being made to do the
    kernel's work; the refusal names every missing one.
    """
    from simplon.kernel import secrets

    source = os.environ if environ is None else environ

    def value(name: str) -> str:
        if name in env.secret:
            return secrets.read(name, source).strip()
        return (source.get(name) or "").strip()

    missing = [name for name in env.required if not value(name)]
    if missing:
        raise ValueError(
            f"environment '{env.name}' requires {len(env.required)} value(s) and "
            f"{len(missing)} of them {'is' if len(missing) == 1 else 'are'} not set: "
            f"{', '.join(missing)}. They are exported where the deploy command runs; a value that is "
            f"missing would let the deployed document fall back to its own default, which is how an "
            f"instance ends up running somewhere nobody is looking")
    return {name: value(name)
            for name in (*env.required, *env.optional) if value(name)}


def variables_read(env: "Environment", carriers: "Mapping[str, Carrier]", *,
                   deploying: bool) -> tuple[str, ...]:
    """Every variable NAME a deploy (`deploying`) or a destroy of `env` reads out of the environment the
    command runs in, derived from the manifest - the names the launcher has to forward for it (si#810).
    They are `variable_roles`' names: a reader that gains a name says in the same edit whether it is secret
    (si#833)."""
    return tuple(variable_roles(env, carriers, deploying=deploying))


def target_roles(url_from: str) -> "dict[str, str]":
    """`target_variables`, each with its role (si#833): the address is plain, the API token is secret."""
    from simplon.kernel import secrets

    url_var, token_var = target_variables(url_from)
    return {url_var: secrets.PLAIN, token_var: secrets.SECRET}


def variable_roles(env: "Environment", carriers: "Mapping[str, Carrier]", *,
                   deploying: bool) -> "dict[str, str]":
    """Every variable NAME a deploy (`deploying`) or a destroy of `env` reads, each with its role (si#810,
    si#833).

    ONE ANSWER PER READER BELOW, each from the reader's own spelling, so a reader that gains a name gains
    it here by the same edit: `from_carrier` (`target_roles`), `_ensure_registry` (`registry_prefix`
    through `credentials.variable_roles`), `_clone_credential` (`credentials.variable_roles` of
    `credential_from:`) and `stack_values` (`required:` and `optional:`, plain unless the environment lists
    them under `secret:`). A destroy only finds the stack, so it reads the target and nothing else.

    NOT HERE, ON PURPOSE: `PORTAINER_URL`/`PORTAINER_TOKEN` as the fallback `from_env` reads when the
    prefixed names are unset, `PORTAINER_ENDPOINT_ID` and `PORTAINER_STACK`. No manifest names them, so
    nothing derives them; a carrier writing `url_from: PORTAINER` gets the first two by derivation anyway.
    """
    from simplon.adapters import credentials
    from simplon.kernel import secrets

    roles: dict[str, str] = {}
    carrier = carriers.get(env.carrier) if env.carrier else None
    if carrier is not None and carrier.portainer is not None:
        url_from = carrier.portainer.url_from
        roles.update(target_roles(url_from))
        if deploying:
            roles.update(credentials.variable_roles(registry_prefix(url_from)))
    if deploying:
        if env.repository is not None and env.repository.credential_from:
            roles.update(credentials.variable_roles(env.repository.credential_from))
        for name in (*env.required, *env.optional):
            roles.setdefault(name, secrets.SECRET if name in env.secret else secrets.PLAIN)
    return roles


def _target_for(env: "Environment") -> "tuple[PortainerTarget, Repository]":
    """The carrier and the repository this environment names, resolved against the manifest.

    Each of the three refusals names the key that is missing, because an environment is half a chain until
    all three are there and "portainer backend failed" would send the reader through the whole file.
    """
    from simplon.model import carrierspec
    from simplon.manifest import context  # was local for a leaf; si#808: `docker` loads it at import

    if not env.carrier:
        raise ValueError(
            f"environment '{env.name}' has `backend: {BACKEND}` and no `carrier:`, so nothing says which "
            f"Portainer it is deployed to")
    if not env.stack:
        raise ValueError(
            f"environment '{env.name}' names a carrier and no `stack:`, so nothing says what the "
            f"deployment is called on it")
    if env.repository is None:
        raise ValueError(
            f"environment '{env.name}' names no `repository:`, and this backend deploys by handing "
            f"Portainer one to clone. It takes a `url:`, and a `compose:` when the document is not at "
            f"the repository root")
    carriers = carrierspec.declared(context.current().manifest_data())
    return PortainerTarget.from_carrier(carriers[env.carrier], env.stack), env.repository


def _built_by_kernel(env: "Environment") -> bool:
    """True when `deploy carrier` builds this environment's carrier, which it does for one with `proxmox:`.

    That run creates the declared directories, so `deploy up` leaves them to it and only checks. On any
    other carrier nothing in the kernel would ever create them, so `deploy up` does (si#808).
    """
    from simplon.model import carrierspec
    from simplon.manifest import context  # was local for a leaf; si#808: `docker` loads it at import

    return carrierspec.declared(context.current().manifest_data())[str(env.carrier)].proxmox is not None


def _clone_credential(repository: "Repository", env: "Environment") -> "tuple[str, str] | None":
    """The read credential Portainer clones with, or None for a public repository.

    A prefix that is NAMED and not set is refused rather than silently dropped: the manifest saying
    `credential_from: GIT` is a statement that this repository needs one, and deploying without it would
    fail inside Portainer with *"authentication required: Repository not found"* - a message that blames
    the repository for a variable that was never exported.
    """
    from simplon.adapters import credentials

    if not repository.credential_from:
        return None
    found = credentials.credential(repository.credential_from, os.environ)
    if found is None:
        user_var, password_var = credentials.variables(repository.credential_from)
        raise ValueError(
            f"environment '{env.name}' says the compose document is cloned with `credential_from: "
            f"{repository.credential_from}`, so {user_var} and {password_var} have to be set. Without "
            f"them Portainer answers 'authentication required: Repository not found', which names the "
            f"repository for a missing variable")
    return found


# --- the carrier's directories, checked before the stack is touched (si#782) -------------------------
#
# HOW A CARRIER'S FILESYSTEM IS READ FROM HERE AT ALL. `deploy up` holds a Portainer URL and a token and
# nothing else: no ssh key, no address of the machine (a carrier with no `proxmox:` has none the manifest
# knows), and on a CI runner not even a shell near the carrier. What it CAN reach is the Docker daemon
# Portainer manages, through Portainer's own proxy - and that daemon is the very one that will resolve the
# stack's bind mounts, so it is the honest witness rather than a stand-in for one. An ssh probe could stat
# a different machine than the one Portainer deploys to and still come back green.
#
# THE PROBE, MEASURED 2026-11-20 against Docker 29.1 directly and through a Portainer 2.45 on the same
# host (not the real carrier - none is reachable from where this was written):
#
#   - a container is CREATED and never started, binding the path read-only with a `Mounts` entry of type
#     bind. A missing source is refused at create with 400 "bind source path does not exist: <path>", and
#     - the point - NOTHING IS CREATED: `Mounts` does not make the directory the way `-v` does, so the
#     probe cannot cause the defect it looks for;
#   - `GET /containers/{id}/archive?path=/probe` answers on a created container with a tar whose first
#     header is the bound directory itself: uid, gid, mode and type, as the host has them;
#   - the image it is created from is an EMPTY one the kernel carries as bytes and loads with
#     `POST /images/load` when the daemon does not have it, so the probe needs no registry and no pull. Its
#     platform is fixed; on another architecture Docker warns and creates it all the same (measured with
#     an arm64 config on amd64), and it never runs.
#
# Every outcome has its own value: ready, missing, wrong (owner, mode, not a directory), and COULD NOT
# TELL - which is said by name and refuses nothing, the way si#785 treats a registry it could not ask.

#: The image the probe container is created from, never pulled and never run. NOT declared through
#: `docker.pinned_image`, and the rule that asks for it does not apply: its reason is a registry tag that
#: means different bytes next month, and these bytes are `_probe_image()`'s own, loaded by this module and
#: by nothing else. Named `_REFERENCE` so the sweep for `*_IMAGE` constants does not read it as a pull
#: nobody pinned. (`INSTALL_IMAGE` below IS pulled, so it is pinned through `docker.pinned_image`, si#808.)
PROBE_REFERENCE = "simplon-dirprobe:empty"
PROBE_LABEL = "simplon.probe"
_PROBE_TARGET = "/probe"
_MISSING = "bind source path does not exist"


def _probe_image() -> bytes:
    """`docker save` of an image with one empty layer, built here so no registry is ever involved."""
    def tar(members: "dict[str, bytes]") -> bytes:
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return out.getvalue()

    layer = tar({})
    config = json.dumps({"architecture": "amd64", "os": "linux", "config": {}, "rootfs": {
        "type": "layers", "diff_ids": ["sha256:" + hashlib.sha256(layer).hexdigest()]}},
        sort_keys=True).encode()
    name = hashlib.sha256(config).hexdigest() + ".json"
    manifest = json.dumps([{"Config": name, "RepoTags": [PROBE_REFERENCE], "Layers": ["layer.tar"]}])
    return tar({"layer.tar": layer, name: config, "manifest.json": manifest.encode()})


def _docker(target: PortainerTarget, method: str, path: str, body: "bytes | None" = None,
            content_type: str = "application/json") -> "IO[bytes]":
    """Open one call to the Docker API of the target's endpoint, through Portainer's proxy.

    Returns the open response, for the caller to read as much of as it needs: an archive of a data
    directory is the whole tree, and the probe wants its first header. Raises `urllib.error.HTTPError`
    for an answer that is not 2xx and `OSError` for none at all; the caller decides what each one means.
    """
    request = urllib.request.Request(
        f"{target.url}/api/endpoints/{target.endpoint_id}/docker{path}", method=method, data=body,
        headers={"X-API-Key": target.token,
                 **({"Content-Type": content_type} if body is not None else {})})
    return urllib.request.urlopen(  # noqa: S310
        request, timeout=_TIMEOUT_S, context=_context(target))


def _said(error: BaseException) -> str:
    """What a failed Docker call said - Docker's own `message` when it gave one."""
    if isinstance(error, urllib.error.HTTPError):
        detail = error.read().decode(errors="replace")[:300]
        try:
            detail = str(json.loads(detail).get("message", detail))
        except (ValueError, AttributeError):
            pass
        return f"{error.code} {detail}".strip()
    return str(error) or type(error).__name__


def _ensure_probe_image(target: PortainerTarget) -> None:
    """Load the empty probe image when the endpoint's daemon does not have it. Raises when it cannot."""
    try:
        with _docker(target, "GET", f"/images/{PROBE_REFERENCE}/json"):
            return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    with _docker(target, "POST", "/images/load?quiet=1", _probe_image(), "application/x-tar") as answer:
        answer.read()


def _stat(target: PortainerTarget, path: str) -> "tuple[tarfile.TarInfo | None, str]":
    """The carrier's own view of `path`: (its tar header, "") when it exists, (None, "") when it does
    not, and (None, why) when the probe could not tell - three values, never two."""
    from simplon.kernel import log

    spec = {"Image": PROBE_REFERENCE, "Cmd": ["probe"], "NetworkDisabled": True,
            "Labels": {PROBE_LABEL: "directories"},
            "HostConfig": {"Mounts": [{"Type": "bind", "Source": path, "Target": _PROBE_TARGET,
                                       "ReadOnly": True}]}}
    try:
        with _docker(target, "POST", "/containers/create", json.dumps(spec).encode()) as answer:
            container = str(json.loads(answer.read())["Id"])
    except urllib.error.HTTPError as error:
        said = _said(error)
        return (None, "") if error.code == 400 and _MISSING in said else (None, f"Docker answered {said}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return None, f"the probe container could not be created ({_said(error)})"
    try:
        with _docker(target, "GET", f"/containers/{container}/archive?path={_PROBE_TARGET}") as answer:
            with tarfile.open(fileobj=answer, mode="r|") as archive:
                header = archive.next()
        if header is None:
            return None, "Docker answered with an empty archive"
        return header, ""
    except (OSError, tarfile.TarError) as error:
        return None, f"its archive could not be read ({_said(error)})"
    finally:
        try:
            with _docker(target, "DELETE", f"/containers/{container}?force=1"):
                pass
        except OSError as error:
            log.warn(f"directory check: the probe container {container[:12]} (label {PROBE_LABEL}) "
                     f"could not be removed ({_said(error)}). It never ran and bound nothing writable")


def _wrong(directory: "Directory", seen: "tarfile.TarInfo", name: str = "") -> str:
    """What is wrong with a directory that exists, or "" when it is as declared. `name` is how the
    directory is said, when that is more than its path (`check_directories`, si#825)."""
    name = name or directory.path
    if not seen.isdir():
        return f"{name} is not a directory"
    found = []
    if (directory.uid is not None and seen.uid != directory.uid) or (
            directory.gid is not None and seen.gid != directory.gid):
        found.append(f"is owned by {seen.uid}:{seen.gid}, declared {directory.owner()}")
    mode = seen.mode & 0o7777
    if directory.mode is not None and mode != directory.mode:
        found.append(f"has mode 0{mode:o}, declared 0{directory.mode:o}")
    return f"{name} {' and '.join(found)}" if found else ""


def _install(directory: "Directory") -> str:
    """The one line that makes the directory as declared, for the refusal's way out."""
    owner = "" if directory.uid is None else f" -o {directory.uid}"
    group = "" if directory.gid is None else f" -g {directory.gid}"
    mode = "" if directory.mode is None else f" -m 0{directory.mode:o}"
    return f"install -d{owner}{group}{mode} {directory.path}"


# --- creating a missing one, on a carrier `deploy carrier` never builds (si#808) ---------------------
#
# A carrier with no `proxmox:` is a Portainer somebody else built, so `deploy carrier` never runs for it and
# nothing in the kernel would create its directories: si#782 left `deploy up` refusing with the
# `install -d` lines until somebody typed them on the host. Here `deploy up` runs that same line itself,
# through the same proxy. An existing directory with the wrong owner or mode is never touched: that stays a
# refusal, because rewriting it would change a tree somebody else may own.
#
# HOW. A short-lived container from `INSTALL_IMAGE` (busybox, pinned by digest, pulled through the proxy
# when the daemon lacks it) binds the deepest existing parent writable and runs `install -d [-o uid]
# [-g gid] [-m mode] <path below it>`, then is removed. The command is an argv list handed to Docker as
# JSON - no shell is involved anywhere - and every word of it is either a constant, a number the parser
# made (`Directory.uid`/`gid`/`mode` are ints), or the path, which has passed `environments.carrier_path`
# at load or, written as `${NAME}`, after resolution (si#809, `resolved_directories`). MEASURED 2026-11-21 with this image on Docker 29.10: `install -d -o 1000 -g 1000 -m 02770
# /probe/a/b/c` made `a` and `b` `0:0 755` and `c` `1000:1000 2770`, so one run makes the parents plainly,
# the way `deploy carrier`'s parents task does. The directory is then checked again, so a daemon that did
# something else (userns-remap, an Agent that proxies differently) is a refusal, not a "created".
#
# NOT `/`. When no parent below `/` exists, the helper would have to bind the carrier's root writable.
# That is refused instead, with the `install -d` line: a carrier without even `/srv` is not one a
# deployment should be laying out by itself.

#: What the directories are made with: `install` and nothing it needs from outside. The same pin as
#: `tasks.imagefile.FILE_TEST_IMAGE` (an adapter does not import a task); the index digest, so each
#: platform resolves to its own manifest.
INSTALL_IMAGE = docker.pinned_image(
    "busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092",
    "simplon.adapters.portainer")

#: The reference Docker's API is given: name and digest. The tag is for the reader; the digest is the pin.
_INSTALL_REFERENCE = INSTALL_IMAGE.split(":", 1)[0] + "@" + INSTALL_IMAGE.split("@", 1)[1]


def _nearest(target: PortainerTarget, path: str) -> "tuple[str | None, str]":
    """(the deepest existing ancestor of `path` below `/`, "") or (None, why) - never `/` itself.

    `path` is absolute, and that is checked HERE rather than trusted to `carrier_path` two calls up
    (si#825): the dirname of a relative path ends at "" and never at "/", so without it this loop would
    never end, and a run that hangs is neither green nor red. Reaching it is a kernel defect, not a
    refusal of the manifest, so it raises instead of answering a `why`.
    """
    if not path.startswith("/"):
        raise ValueError(f"internal error: the carrier directory {path!r} is not absolute, so its parents "
                         f"never reach / - `environments.carrier_path` should have refused it")
    parent = posixpath.dirname(path)
    while parent != "/":
        seen, why = _stat(target, parent)
        if why:
            return None, f"its parent {parent} could not be read: {why}"
        if seen is not None:
            return (parent, "") if seen.isdir() else (None, f"{parent} is not a directory")
        parent = posixpath.dirname(parent)
    return None, (f"no parent of it below / exists on the carrier, and `deploy up` does not bind the "
                  f"carrier's root writable to lay out a top-level tree")


def _install_argv(ancestor: str, directory: "Directory") -> "list[str]":
    """`install -d` for `directory`, as the helper sees it below `ancestor` - an argv, never a string.

    It becomes the helper container's command on the CARRIER, where `docker inspect` and `ps` show it, so
    a path templated from a secret is refused here rather than put there (si#833): a directory named after
    a secret cannot be created without exposing it."""
    from simplon.kernel import secrets

    argv = ["install", "-d"]
    if directory.uid is not None:
        argv += ["-o", str(directory.uid)]
    if directory.gid is not None:
        argv += ["-g", str(directory.gid)]
    if directory.mode is not None:
        argv += ["-m", f"0{directory.mode:o}"]
    argv.append(posixpath.join(_PROBE_TARGET, posixpath.relpath(directory.path, ancestor)))
    secrets.check_argv([*argv, ancestor])
    return argv


def _ensure_install_image(target: PortainerTarget) -> None:
    """Pull `INSTALL_IMAGE` through the proxy when the daemon lacks it. Raises when it cannot.

    Docker answers a pull 200 and streams its progress, and a failed pull is an `error` line INSIDE that
    200 - read as the status code alone it would be a pull that worked and an image that is not there.
    """
    from urllib.parse import quote

    try:
        with _docker(target, "GET", f"/images/{quote(_INSTALL_REFERENCE, safe='')}/json"):
            return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    with _docker(target, "POST", f"/images/create?fromImage={quote(_INSTALL_REFERENCE, safe='')}",
                 b"") as answer:
        for line in answer.read().decode(errors="replace").splitlines():
            try:
                said = json.loads(line)
            except ValueError:
                continue
            if isinstance(said, dict) and said.get("error"):
                raise OSError(f"the pull of {INSTALL_IMAGE} said: {said['error']}")


def _create(target: PortainerTarget, directory: "Directory") -> str:
    """Make a missing `directory` on the carrier. "" when `install -d` exited 0, otherwise why not."""
    from simplon.kernel import log

    ancestor, why = _nearest(target, directory.path)
    if ancestor is None:
        return why
    try:
        _ensure_install_image(target)
    except OSError as error:
        return f"{INSTALL_IMAGE} could not be found or pulled on the carrier ({_said(error)})"
    spec = {"Image": _INSTALL_REFERENCE, "Cmd": _install_argv(ancestor, directory), "Entrypoint": [],
            "User": "0:0", "NetworkDisabled": True, "Labels": {PROBE_LABEL: "create"},
            "HostConfig": {"Mounts": [{"Type": "bind", "Source": ancestor, "Target": _PROBE_TARGET,
                                       "ReadOnly": False}]}}
    try:
        with _docker(target, "POST", "/containers/create", json.dumps(spec).encode()) as answer:
            container = str(json.loads(answer.read())["Id"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        return f"the helper container could not be created ({_said(error)})"
    try:
        with _docker(target, "POST", f"/containers/{container}/start", b""):
            pass
        with _docker(target, "POST", f"/containers/{container}/wait", b"") as answer:
            code = json.loads(answer.read()).get("StatusCode")
        if code == 0:
            return ""
        with _docker(target, "GET", f"/containers/{container}/logs?stdout=1&stderr=1") as answer:
            said = answer.read().decode(errors="replace")
        return f"install -d exited {code}: {''.join(c for c in said if c.isprintable()).strip()[:300]}"
    except (OSError, ValueError, AttributeError) as error:
        return f"the helper container did not run to the end ({_said(error)})"
    finally:
        try:
            with _docker(target, "DELETE", f"/containers/{container}?force=1"):
                pass
        except OSError as error:
            log.warn(f"directory creation: the helper container {container[:12]} (label {PROBE_LABEL}) "
                     f"could not be removed ({_said(error)}). It binds {ancestor} writable")


def resolved_directories(env: "Environment", values: "Mapping[str, str]") -> "list[tuple[Directory, str]]":
    """Every declared directory with its path resolved against the values this deployment sends, each
    paired with the template it was written as, or "" when it was a literal path (si#809, si#825).
    Raises before the carrier is asked anything.

    THE SAME RESOLUTION AS A COMPOSE IMAGE (`_resolved`, si#785), over the same values - `stack_values`
    plus the version, exactly what Portainer is handed - so the directory checked and created is the one
    the stack's `${NAME}` bind mount will name, and not a second reading of the environment.

    THE RESOLVED STRING PASSES `carrier_path`, the rule a literal path passed at load: it reaches Docker
    as an argv word and the refusal's `install -d` line, and a value from the environment is no safer
    than one from the file. A name with no value is a refusal that names it, every one at once: the
    directory's place is not known, so there is nothing honest to check. Only an `optional:` name can get
    here empty; `stack_values` has already refused a missing `required:` one.

    THE RESOLVED PATH IS SAID, WITH ITS TEMPLATE BESIDE IT, AND NOT HIDDEN (si#825). The kernel has no
    notion of a secret value - `required:` and `optional:` are both values the deployment sends, and a
    compose image resolved from them is echoed the same way (si#785, `check_registry_access`). A value
    used as a path is written onto the carrier's filesystem and into the stack's bind mount, where
    `docker inspect` shows it to anyone who can reach the daemon, so masking it in this output would
    protect nothing and would leave the refusal's `install -d` line unrunnable. What the reader could not
    see was where the path came from; the template says it.
    """
    found: "list[tuple[Directory, str]]" = []
    unresolved: "dict[str, list[str]]" = {}
    for directory in env.directories:
        names = environments.path_variables(directory.path)
        if not names:
            found.append((directory, ""))
            continue
        missing = [name for name in names if not values.get(name)]
        if missing:
            for name in missing:
                unresolved.setdefault(name, []).append(directory.path)
            continue
        where = f"environment '{env.name}', `path: {directory.path}` resolved from the deployment's values"
        path = environments.carrier_path(_resolved(directory.path, values), where)
        found.append((directory._replace(path=path.rstrip("/") or "/"), directory.path))
    if unresolved:
        named = "; ".join(f"{name} in {', '.join(paths)}" for name, paths in unresolved.items())
        one = len(unresolved) == 1
        raise ValueError(
            f"environment '{env.name}': this deployment sends no value for {', '.join(unresolved)}, and "
            f"`directories:` names {'it' if one else 'them'} ({named}) - so where that directory is is "
            f"not known, and the carrier was asked about none. Export {'it' if one else 'them'} where "
            f"the deploy command runs")
    return found


def check_directories(target: PortainerTarget, env: "Environment", create: bool = False,
                      values: "Mapping[str, str] | None" = None) -> None:
    """Refuse a deployment whose bind-mount directories are not on the carrier as declared (si#782), and
    with `create`, make the missing ones first (si#808).

    WHY BEFORE: Docker would create a missing one as root at stack start, and the service would die on
    the far side of the seam with "unable to open database file" - after the stack exists. Every
    directory is checked and every wrong one named in ONE refusal; an operator repairing eight
    directories one run at a time is being made to do the kernel's work.

    A path written as `${NAME}` is resolved from `values` first (si#809, `resolved_directories`), and a
    resolved one is created whatever `create` says: `deploy carrier` does not have the deployment's
    values and leaves it alone, so nothing but this would make it.

    `create` is for a carrier `deploy carrier` never builds. It makes a MISSING directory and nothing else:
    one that exists with the wrong owner, mode or type is refused exactly as without it, and while anything
    is refused nothing is created, so a refused run leaves the carrier as it found it. A directory it
    could not make is a refusal too - it is known to be missing, and Docker would make it as root.

    A directory the probe could not tell about is said by name and refuses nothing - it is neither ready
    nor missing - and when the probe image cannot be put on the endpoint at all, nothing is checked and
    that is said once, naming every directory that went unchecked.
    """
    from simplon.kernel import log

    if not env.directories:
        return
    resolved = resolved_directories(env, values or {})
    directories = [directory for directory, _ in resolved]
    creatable = {directory.path for directory, templated in resolved if create or templated}
    shown = {d.path: f"{d.path} (from `{template}`)" if template else d.path for d, template in resolved}
    try:
        _ensure_probe_image(target)
    except OSError as error:
        log.warn(f"directory check did not run: the probe image could not be found or loaded on endpoint "
                 f"{target.endpoint_id} of {target.url} ({_said(error)}), so none of "
                 f"{', '.join(shown[d.path] for d in directories)} was checked")
        return
    wrong: list[str] = []
    fixes: list[str] = []
    missing: "list[Directory]" = []
    unchecked = 0
    for directory in directories:
        seen, why = _stat(target, directory.path)
        if why:
            unchecked += 1
            log.warn(f"directory check: could not tell whether {shown[directory.path]} is ready on the "
                     f"carrier: {why}")
            continue
        if seen is None:
            missing.append(directory)
            continue
        problem = _wrong(directory, seen, shown[directory.path])
        if problem:
            wrong.append(problem)
            if seen.isdir():  # `install -d` fixes an existing directory, not a file
                fixes.append(_install(directory))
    left = [d for d in missing if d.path not in creatable]
    if wrong or left:
        wrong = [f"{shown[d.path]} is missing" for d in missing] + wrong
        fixes = [_install(d) for d in missing] + fixes
        way = ("`deploy up` creates a missing one on this carrier, and created none because of the rest; "
               "it never rewrites one that exists, so run on the carrier: " if not left else
               "`deploy carrier` creates them on a carrier the kernel builds; on any other, run on the "
               "carrier: ")
        raise PortainerError(
            f"environment '{env.name}': {'; '.join(wrong)} on the carrier behind {target.url}, so the "
            f"stack was not touched - Docker would create a missing directory as root, and a service "
            f"running as another user fails at start. {way}"
            f"{'; '.join(fixes) or 'nothing until the file standing at that path is moved away'}")
    failed: "list[Directory]" = []
    for directory in missing:
        why = _create(target, directory)
        if not why:
            seen, why = _stat(target, directory.path)
            why = why or ("it is still missing afterwards" if seen is None else _wrong(directory, seen))
        if why:
            failed.append(directory)
            log.error(f"directory creation: {shown[directory.path]} was not made as declared: {why}")
            continue
        log.ok(f"created {shown[directory.path]} on the carrier"
               f"{f', owner {directory.owner()}' if directory.uid is not None else ''}"
               f"{f', mode 0{directory.mode:o}' if directory.mode is not None else ''}")
    if failed:
        raise PortainerError(
            f"environment '{env.name}': {', '.join(shown[d.path] for d in failed)} could not be made as "
            f"declared "
            f"through {target.url} (said above), so the stack was not touched - Docker would create a "
            f"missing directory as root. Run on the carrier: {'; '.join(_install(d) for d in failed)}")
    ready = len(directories) - unchecked
    if ready:
        log.ok(f"{ready} of {len(env.directories)} declared director"
               f"{'y' if len(env.directories) == 1 else 'ies'} ready on the carrier"
               f"{', nothing to create' if create and not missing else ''}")
