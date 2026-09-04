"""Container-image build/publish naming primitives for the *ctl orchestrators (netctl#730, extracted from
netctl's orchestrator tooling).

Two pure string derivations the packaging/publish commands share: the image version TAG (from an
``IMAGE_VERSION`` override, else the Gradle ``version = "..."``, else a fallback) and the fully-qualified
registry repo string ``[registry/]namespace/name``. No docker, no I/O - product-agnostic, so a product's
package/publish commands read them the same way.
"""
from __future__ import annotations

import re

from delivery import log


def image_version(build_gradle_text: str, env_override: str | None = None) -> str:
    """The image tag: ``env_override`` if set (an explicit ``IMAGE_VERSION``), else the ``version = "..."``
    from a Gradle build script, else the ``0.1.0`` fallback."""
    if env_override:
        return env_override
    m = re.search(r'^\s*version = "(.*)".*', build_gradle_text, re.MULTILINE)
    return m.group(1) if m else "0.1.0"


def hub_repo(name: str, namespace: str, registry: str = "") -> str:
    """The fully-qualified repo string ``[registry/]namespace/name`` (a plain Docker Hub form when
    ``registry`` is empty, else a prefixed non-Hub registry like ghcr.io)."""
    prefix = f"{registry}/" if registry else ""
    return f"{prefix}{namespace}/{name}"



def registry_prefix(value: str | None) -> str:
    """A registry as it prefixes an image name: trimmed, without a trailing slash, empty when unset.

    Reads straight off an ``IMAGE_REGISTRY`` variable, where "unset", "empty", "whitespace" and "a stray
    trailing slash" all have to come out meaning the same thing."""
    return (value or "").strip().rstrip("/")


def image_ref(name: str, tag: str, registry: str | None = "") -> str:
    """The fully-qualified image reference ``[registry/]name:tag``.

    The tagging half of the same derivation ``hub_repo`` starts: that one builds the repo string for a
    product keeping its namespace as a separate field, this one stamps the tag on and accepts a
    ``registry`` that already carries the namespace (``ghcr.io/acme``) - the form an ``IMAGE_REGISTRY``
    variable normally has. Without a registry the reference is unqualified, which is right for a local
    build and wrong for a push (see ``require_registry``)."""
    prefix = registry_prefix(registry)
    return f"{prefix}/{name}:{tag}" if prefix else f"{name}:{tag}"


def require_registry(value: str | None, *, var: str = "IMAGE_REGISTRY",
                     example: str = "ghcr.io/<namespace>") -> str:
    """The registry prefix for a PUSH, or die naming the variable that is missing.

    Building an unqualified ``name:tag`` locally is normal; pushing one is not. Docker resolves an
    unqualified name against Docker Hub, so an unset variable does not fail the push - it publishes to
    somewhere else entirely, under a name that may not even be yours. Refusing is the only safe reading,
    and the variable's name is the caller's so the message names the one it actually reads."""
    prefix = registry_prefix(value)
    if not prefix:
        log.die(f"publishing needs {var} (e.g. {example}); refusing to push an unqualified image name, "
                f"which docker would resolve against Docker Hub")
    return prefix
