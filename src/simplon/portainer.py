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

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable, Mapping

from simplon import environments

if TYPE_CHECKING:  # local: keeps the module head free of the manifest layer, the way `backend` does
    from simplon.carrierspec import Carrier
    from simplon.deployment import Version
    from simplon.environments import Environment, Repository

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

    @staticmethod
    def from_carrier(carrier: "Carrier", stack_name: str,
                     environ: "dict[str, str] | None" = None) -> "PortainerTarget":
        """The target a manifest describes: the carrier says where and how, the environment says what.

        The carrier carries a PREFIX and never a value, so this is where the prefix becomes the two
        variables `credentials.py`'s convention stands for. It goes through `from_env` rather than beside
        it, because the refusal that names the missing variable is the half worth not having twice.
        """
        source = dict(os.environ if environ is None else environ)
        prefix = carrier.portainer.url_from
        for suffix in ("_URL", "_TOKEN"):
            if source.get(f"{prefix}{suffix}") and not source.get(f"PORTAINER{suffix}"):
                source[f"PORTAINER{suffix}"] = source[f"{prefix}{suffix}"]
        target = PortainerTarget.from_env(
            carrier.name, stack_name, environ=source,
            secrets_hint=f"The carrier names `url_from: {prefix}`, so it is read from "
                         f"{prefix}_URL and {prefix}_TOKEN.")
        return replace(target, endpoint_id=carrier.portainer.endpoint,
                       insecure=carrier.portainer.insecure)

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

    WHY THE KERNEL SHIPS THIS ONE AND NAMES NO OTHER. `simplon.backend` is the seam and stays what it is:
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
        from simplon import log

        target, repository = _target_for(env)
        if version.builds:
            raise ValueError(
                f"environment '{env.name}' is deployed by Portainer, which clones {repository.url} "
                f"itself - so there is nothing on this machine for it to deploy. Publish the version and "
                f"deploy that")
        values = {**stack_values(env), VERSION_VAR: version.tag}
        log.info(f"{env.stack} <- {repository.url} ({repository.ref}), {repository.compose}")
        message = deploy_from_repository(
            target, repository, _clone_credential(repository, env), env_vars=values)
        log.ok(f"{message}, {len(values)} value(s) incl. {VERSION_VAR}={version.tag}")
        return 0

    def destroy(self, env: "Environment") -> int:
        from simplon import log

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
    with no value is left out of the payload entirely rather than sent as an empty string: sending `""`
    and sending nothing are the same to that document today, and the day they differ, the one this kernel
    chose would be the one nobody wrote down.

    ALL OF THEM AT ONCE. An operator repairing eight variables one run at a time is being made to do the
    kernel's work; the refusal names every missing one.
    """
    source = os.environ if environ is None else environ

    def value(name: str) -> str:
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


def _target_for(env: "Environment") -> "tuple[PortainerTarget, Repository]":
    """The carrier and the repository this environment names, resolved against the manifest.

    Each of the three refusals names the key that is missing, because an environment is half a chain until
    all three are there and "portainer backend failed" would send the reader through the whole file.
    """
    from simplon import carrierspec, context  # local: this module is a leaf, the manifest layer is not

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


def _clone_credential(repository: "Repository", env: "Environment") -> "tuple[str, str] | None":
    """The read credential Portainer clones with, or None for a public repository.

    A prefix that is NAMED and not set is refused rather than silently dropped: the manifest saying
    `credential_from: GIT` is a statement that this repository needs one, and deploying without it would
    fail inside Portainer with *"authentication required: Repository not found"* - a message that blames
    the repository for a variable that was never exported.
    """
    from simplon import credentials

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
