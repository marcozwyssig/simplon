"""WHICH VERSION A DEPLOYMENT IS DEPLOYING (si#235).

Thirty-two deploy commands across the five products this kernel can reach, and not one of them could say.
What went up was decided by `IMAGE_VERSION` if it happened to be exported and by whatever the product's
build file said otherwise - an environment variable no manifest mentions and no command documents. That
is the shape si#223 decided against three days earlier: a side effect standing in for a statement.

THREE VALUES, THREE MEANINGS:

    1.4.0     this exact published version   a lookup, verified before anything runs
    latest    the newest published version   a lookup, verified by existing
    local     the current code base          a BUILD, and no registry is touched at all

That separation is the design and not a convenience. ONE value that silently meant two of them - `latest`
falling back to a build when nothing is published - would be exactly the defect this repository keeps
finding, an outcome that cannot tell "nothing to do" from "failed". CLAUDE.md's own resolution for that
class is to widen the range until each meaning has its own value, which is what these three are.

AN EMPTY SELECTOR IS REFUSED RATHER THAN DEFAULTED, for the same reason. "Whatever is newest" is a choice
somebody makes; a deployment that made it silently would be the side effect this module removes, wearing
a different hat.

THE SECTION POINTS, IT DOES NOT RESTATE. `images:` and `artifacts:` already carry the registry and the
repository - four of the seven reachable manifests declare `images:`, cleon declares `artifacts:` - so a
`deploy:` section carrying a registry of its own would be a second source for one fact, which is what
this repository removes everywhere else. It names an entry in a section that already exists:

    deploy:
      source: { images: app }

AND THE ENTRY MAY NOT CARRY WHAT IS NEEDED, measured rather than assumed. Across those manifests the
entries are not one shape: `registry` and `repository` are in three, biz-cockpit's images carry `name`
instead and no registry at all, and netctl's are bare strings rather than mappings. Each of those is
refused by name here, with the keys the entry does have in the message - because the reader's next
question is "what do I add", and a KeyError two frames down answers neither.

WHY THE LOOKUP IS NOT PER ENVIRONMENT. `dev|test|uat|prod` choose where a deployment GOES, not where the
artefact comes from: one source, many targets. Build once, deploy often - and a promotion is only
provable at all if the number that went to test is the number that goes to prod.
"""
from __future__ import annotations

from typing import NamedTuple

from simplon import context, githubpackages

#: The manifest section this module reads.
SECTION = "deploy"

#: The sections a `source:` may point into - the two that already carry a registry and a repository.
SOURCE_SECTIONS = ("images", "artifacts")

#: The newest published version.
LATEST = "latest"

#: The current code base, built now.
LOCAL = "local"


class Source(NamedTuple):
    """Where a deployment's artefacts come from, read off the section the `deploy:` section points at."""

    kind: str
    name: str
    registry: str
    repository: str

    @property
    def reference(self) -> str:
        """`registry/repository`, the half of an image reference that has no tag on it yet."""
        return f"{self.registry.rstrip('/')}/{self.repository.strip('/')}"


class Version(NamedTuple):
    """What a deployment resolved to.

    `selector` is kept verbatim beside the answer on purpose: a run that says "1.4.0" and a run that says
    "latest, which is 1.4.0 today" are the same deployment and a different statement, and the record has
    to be able to tell them apart a month later.

    `builds` is the one bit that decides whether anything is built, and it is a separate field rather
    than `tag == ""` so that no caller has to know that an empty tag means a build.
    """

    selector: str
    tag: str
    builds: bool


def _entry(document: dict, kind: str, name: str, where: str) -> dict:
    section = document.get(kind)
    if not isinstance(section, dict):
        declared = ", ".join(sorted(k for k in SOURCE_SECTIONS if isinstance(document.get(k), dict)))
        raise ValueError(
            f"{where}'s `{SECTION}: source:` names `{kind}:`, which this manifest does not declare as a "
            f"section. Declared here: {declared or '(neither images: nor artifacts:)'}")
    if name not in section:
        raise ValueError(
            f"{where}'s `{SECTION}: source:` names '{name}' in `{kind}:`, which carries: "
            f"{', '.join(sorted(section)) or '(nothing)'}")
    entry = section[name]
    if not isinstance(entry, dict):
        raise ValueError(
            f"{where}'s `{kind}: {name}:` is not a mapping ({entry!r}), so it carries no registry to "
            f"deploy from. A deployable entry needs `registry:` and `repository:`")
    return entry


def declared() -> Source:
    """The `deploy:` section's source, resolved against the section it points at.

    Raises rather than returning None with a log line, which differs from `tracker.declared` on purpose:
    a tracker problem must never cost a walk the answers a person already gave, while a deployment that
    cannot say where its artefact comes from has nothing to lose by stopping - and everything to lose by
    going on.

    THE DOCUMENT IS HANDED ON RATHER THAN READ AND RULED ON HERE, which is what keeps this module inside
    the refusal census rather than in its `READS_INLINE` exemption list. `tracker` and
    `tasks.releasenotes` are named there because they answer with a `log.error` and a None, so the walk
    would collect nothing from them even if it could follow them. These refusals RAISE, so they are
    collectable - and a refusal that can be counted and is not is exactly the quiet growth si#53 derived
    the population to prevent.
    """
    ctx = context.current()
    return source_of(ctx.manifest_data(), ctx.manifest_path.name)


def source_of(document: dict, where: str) -> Source:
    """The `deploy: source:` of an already-read manifest DOCUMENT, or a refusal naming what is wrong."""
    section = document.get(SECTION)
    if not isinstance(section, dict):
        raise ValueError(
            f"{where} declares no `{SECTION}:` section, so a deployment cannot say which version it is "
            f"deploying. It needs `source:` naming an entry of an existing section, for example "
            f"`{SECTION}: {{ source: {{ images: app }} }}`")
    source = section.get("source")
    if not isinstance(source, dict) or not source:
        raise ValueError(
            f"{where}'s `{SECTION}:` section declares no `source:`, so there is nowhere to look a "
            f"version up. It names one entry of an existing section: "
            f"`source: {{ images: <name> }}` or `source: {{ artifacts: <name> }}`")
    named = [k for k in SOURCE_SECTIONS if k in source]
    if len(named) != 1:
        raise ValueError(
            f"{where}'s `{SECTION}: source:` names {', '.join(sorted(source)) or 'nothing'}; it takes "
            f"exactly one of {' or '.join(SOURCE_SECTIONS)}")
    kind = named[0]
    name = str(source[kind] or "").strip()
    if not name:
        raise ValueError(f"{where}'s `{SECTION}: source: {kind}:` names no entry")
    entry = _entry(document, kind, name, where)
    registry = str(entry.get("registry", "") or "").strip()
    repository = str(entry.get("repository", "") or "").strip()
    if not registry or not repository:
        raise ValueError(
            f"{where}'s `{kind}: {name}:` carries no registry to deploy from: a deployable entry needs "
            f"`registry:` and `repository:`, and this one has {', '.join(sorted(entry)) or 'no keys'}")
    return Source(kind=kind, name=name, registry=registry, repository=repository)


def _newest(source: Source) -> str:
    """The newest published tag. Its own module records the fact this rests on - `oras repo tags` lists
    oldest first - so that fact stays in one place."""
    return githubpackages.newest_tag(source.registry, source.repository)


def _serves(source: Source, tag: str) -> bool:
    """Whether the registry really serves this reference.

    The same read-back `release:image` makes a push a publish with, asked before a deployment instead of
    after one: a version that is not there is a fact available in one call, and finding it out in the
    middle of a rollout costs an environment.
    """
    from simplon.tasks import image
    return image.published(f"{source.reference}:{tag}")


def resolve(selector: str, source: Source) -> Version:
    """`selector` as a concrete version, refusing one the registry does not serve.

    `local` returns FIRST, before any registry is touched. That ordering is load-bearing rather than an
    optimisation: the whole point of deploying the current code base is that it does not depend on
    anything having been published, so a registry that is unreachable, unauthenticated or empty must not
    be able to fail it.
    """
    selector = (selector or "").strip()
    if not selector:
        raise ValueError(
            f"which version? A deployment names one: a published version like `1.4.0`, `{LATEST}` for "
            f"the newest published one, or `{LOCAL}` to build the current code base and deploy that")
    if selector == LOCAL:
        return Version(selector=LOCAL, tag="", builds=True)
    if selector == LATEST:
        return Version(selector=LATEST, tag=_newest(source), builds=False)
    if not _serves(source, selector):
        raise ValueError(
            f"{source.reference} does not serve '{selector}', so nothing was deployed. Published "
            f"versions are what `{LATEST}` resolves against; `{LOCAL}` deploys the current code base "
            f"without needing one")
    return Version(selector=selector, tag=selector, builds=False)
