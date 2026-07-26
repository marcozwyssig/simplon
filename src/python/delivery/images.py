"""Container-image build/publish naming primitives for the *ctl orchestrators (netctl#730, extracted from
netctl's orchestrator tooling).

Two pure string derivations the packaging/publish commands share: the image version TAG (from an
``IMAGE_VERSION`` override, else the Gradle ``version = "..."``, else a fallback) and the fully-qualified
registry repo string ``[registry/]namespace/name``. No docker, no I/O - product-agnostic, so a product's
package/publish commands read them the same way.
"""
from __future__ import annotations

import re


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
