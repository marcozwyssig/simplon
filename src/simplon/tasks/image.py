"""`build:image` and `release:image` - build a product's CONTAINER image and publish it (#31).

WHY THIS IS THE KERNEL'S, AND WHY IT IS NOT `release:artifact`. `simplon.tasks.artifact` publishes a
DIRECTORY as an OCI artifact and its own head states why it is not this: "a container image carries a
filesystem for one platform". That remains true and this is its missing neighbour, not its replacement.
What made it the kernel's is the same argument as everywhere else here: `docker build` with a
`-f`/`-t`/`--build-arg`/context line, `docker login`, `docker push` and a check that the push landed are
the same six commands in every product, and every product that wrote them itself got the last one wrong.
What stays the product's is DATA - which registry, which package, which Dockerfile, which context
directory, which extra build arguments, which tag - and all of it arrives through the manifest's
`images:` section. A kernel default for any of them would be simplon's own directory layout imposed on
every other product.

A MISSING DOCKER IS A FAILURE HERE, AND THAT IS THE OPPOSITE OF `tasks/site.py`. The site build
deliberately does NOT call `docker.ensure_docker()`, and says why: "that gate is right for a step whose
output is the point, and wrong here" - a machine that runs the loop is not always the one that publishes
the page, so a tool that was never installed cannot be the reason a run goes red. Both halves of that
sentence apply in reverse to these two commands. The output IS the point: `build:image` exists solely to
produce an image and `release:image` solely to put it into a registry, so a host without docker has not
"skipped an optional render", it has failed to do the only thing it was asked. The gate that DIES is
therefore the right one here, and the asymmetry is a decision rather than an oversight in one of the two.

WHERE VERSION AND REVISION COME FROM. The kernel derives both from git itself and passes them on every
build, local and in Actions alike, so the image that survives is the one that carries its provenance -
the defect #31 describes is a local build without `--build-arg` and a CI build with one, which stamps
only the image that gets thrown away.

NOT from setuptools-scm, although this repository has it: `simplon._version` is SIMPLON's release number,
read out of the installed kernel wheel, and stamping it into a product's image would label agile-cockpit
with the version of its build tool. A product has its own version, and the place it keeps it is its own
git checkout - `simplon.context.current().root`, never this package's `__file__`. The derivation is the
same one setuptools-scm performs (`git describe`), pointed at the product instead of at the kernel.

    VERSION  = git describe --tags --always --dirty   (a release tag when there is one; else the short
                                                       commit, which is what a shallow CI clone leaves)
    REVISION = git rev-parse HEAD                     (the full sha - the OCI convention, and the one
                                                       thing that is identical in both environments)

Both are DEFAULTS, not overrides: a product that declares `VERSION` in its own `build_args:` means it,
and a kernel that silently discarded a manifest statement would be worse than one that does not derive
anything. A tree that is not a git checkout at all (an exported tarball) gets neither argument and a
warning, rather than the literal string "unknown" presented as if it had been derived - the Dockerfile's
own `ARG VERSION=dev` default is the product's considered answer for that case, and overriding it with a
kernel placeholder would replace a real statement with an invented one.

A Dockerfile that declares neither ARG ignores both, at no cost: measured, `docker build --build-arg
VERSION=1.2.3 --build-arg REVISION=abc` against a Dockerfile with no `ARG` lines exits 0.

THE PUSH IS READ BACK, WHICH IS THE WHOLE POINT (#31 acceptance 3). This project has twice shipped a step
that reported rc 0 and left nothing behind: `allure.render_report` did it for two releases, and hugo
still exits 0 on an empty content tree - `tasks/site.py` wipes its destination and looks for a home page
for exactly that reason. A `docker push` whose result nobody reads is the same defect wearing a registry
for a costume, so `release:image` asks the REGISTRY whether the tag is there before it says OK.

THE REGISTRY, AND NOTHING THAT KEEPS A COPY. The read-back is worth exactly as much as its inability to
answer from local state, and that is a harder requirement than it looks. Three clients were measured
against a local `registry:2`, and two of them fail it:

  - `docker image inspect` - answers about the daemon, so it says yes for the image that never left the
    machine. The failure being guarded against, obviously excluded;
  - `docker manifest inspect` - reads `~/.docker/manifests/` FIRST and answers out of it. Measured:
    after `docker manifest create localhost:5555/probe:cached ...`, `docker manifest inspect` returned
    rc 0 for `:cached` while the registry's own tag list held only `t1`. FALSE GREEN, and not a curiosity
    - hand-rolled multi-arch publishing is `docker manifest create` + `docker manifest push`, so a failed
    push leaves precisely that entry behind for the next release to read as proof. It also reports `no
    such manifest` for a tag that IS there when the registry speaks plain HTTP and `--insecure` is not
    passed, in the same words it uses for real absence. Wrong in both directions, excluded;
  - `docker buildx imagetools inspect` - correct in every case measured, including the cached one. But it
    is a PLUGIN: the static CLI `simplon.docker` can bootstrap onto a bare runner does not carry it, so on
    the very host the bootstrap exists for there would have to be a fallback - and a rarely-walked
    fallback with different semantics from the main path is exactly how the false green above got in.

So the probe is `oras manifest fetch --descriptor <ref>`, and it is the ONLY probe. oras talks to the
registry over HTTP(S) and keeps no local manifest store at all, so it cannot answer from a cache the way
`docker manifest inspect` does; it needs no daemon and no plugin; and it is the one tool this kernel
PROVIDES rather than hopes for (`simplon.oras.ensure_oras`, `support:install`), so there is no host where
the check is merely optimistic. Measured: rc 0 for a tag that is there, rc 1 with `not found` for one
that is not, and rc 1 for the very `:cached` entry `docker manifest inspect` called present.

One probe rather than a chain, deliberately. A fallback means the answer depends on which host asked,
and "the answer depends on the host" is the whole shape of this defect.

Credentials for the probe come from the push's own login: measured, oras 1.3.4 reads `~/.docker/config.json`,
so a `docker login` is enough and no second authentication step exists to drift.

A probe that cannot answer goes RED, and the message names both readings ("not stored" / "could not be
asked"). Parsing the client's wording to separate them would be reading formatted text for a decision -
the mistake `tasks/cliref.py` is written to avoid - and here the two readings mean the same thing anyway:
an unverified push is not a publish.

WHAT THIS DOES NOT REUSE, AND WHY IT IS NOT AN OVERSIGHT. `simplon.imagenames` already holds `image_ref`,
`registry_prefix` and `require_registry`, and this module uses none of them. They are the netctl-extracted
shape, where a registry arrives from an `IMAGE_REGISTRY` environment variable that may be unset and the
refusal is a `log.die` at the point of use. Here the registry is a REQUIRED manifest key, so the same
refusal has to happen at declaration time and as a `ValueError` like every other manifest fault in this
file - a `log.die` inside `declared()` would exit the process out of a validator. `require_registry` is
cited above for the failure it records, which is the argument for making the key required; the code path
is genuinely a different one.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from simplon import context, docker, githubpackages, hostpath, log, outputs
from simplon.labhost import BINFMT_IMAGE
from simplon.bootstrap import validate_relative_dir
from simplon.run import Result, run, stream

#: The manifest section this module owns, in the shape `artifacts:` established: a mapping of NAME -> the
#: image's own data, because a product may build more than one.
SECTION = "images"

#: The two build arguments the kernel derives and passes itself. Spelled as the OCI label pair a
#: Dockerfile writes them into (`org.opencontainers.image.version` / `.revision`), which is the naming
#: agile-cockpit's Dockerfile already uses and the only reason these two names rather than any others.
VERSION_ARG = "VERSION"
REVISION_ARG = "REVISION"


@dataclass(frozen=True)
class Image:
    """The image data a product's manifest declares: where it is published (registry + repository), what
    is built (dockerfile + context, both relative to the product root), plus optional extra build
    arguments and a constant tag."""

    registry: str
    repository: str
    dockerfile: str
    context: str
    build_args: dict[str, str] = field(default_factory=dict)
    tag: str = ""
    #: si#347. Empty is the single-platform image this module always built, with the argv it always had.
    platforms: tuple[str, ...] = ()
    #: si#347. The declared images this one is built FROM, as (name, image) pairs in declaration order,
    #: each already validated - including its own contexts, so a cycle never reaches a build.
    contexts: tuple[tuple[str, "Image"], ...] = ()


def _str(body: Mapping, key: str, where: str, *, required: bool = False) -> str:
    value = body.get(key)
    if value is None:
        if required:
            raise ValueError(f"{where}: '{key}' is required")
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


def _inside_the_product(value: str, key: str, where: str) -> str:
    """A manifest path that must stay UNDER the product root, normalised - with '.' allowed, because the
    build context normally IS the product root.

    The rule and its reasoning are `bootstrap.validate_relative_dir`'s, shared rather than restated: an
    absolute or climbing value would land outside the tree the manifest is talking about, and here that
    means handing docker a build context somewhere else on the disk - `context: /` would stream the whole
    filesystem to the daemon. The one relaxation is the bare '.', which that validator refuses because
    its other callers scaffold into the path or hand it to `rmtree`; naming the product root is a normal
    and unambiguous thing for a build context to do, and it resolves to the root and nowhere else.
    """
    if value.strip() in (".", "./"):
        return "."
    return validate_relative_dir(
        value, f"{where}: '{key}'",
        "give a plain relative path under the product root, e.g. 'Dockerfile', 'docker/app.Dockerfile' "
        "or '.' for the root itself",
        inside="the product root")


def _build_args(body: Mapping, where: str) -> dict[str, str]:
    """The product's own `build_args:`, as strings. A mapping rather than a list of `K=V` strings: the
    manifest is YAML, and a list would make the caller quote a syntax the format already has."""
    declared = body.get("build_args")
    if declared is None:
        return {}
    if not isinstance(declared, Mapping):
        raise ValueError(f"{where}: 'build_args' must be a mapping of name to value")
    out: dict[str, str] = {}
    for key, value in declared.items():
        if value is None or isinstance(value, (list, dict, tuple)):
            raise ValueError(f"{where}: build argument '{key}' must be a scalar, not {type(value).__name__}")
        out[str(key)] = "true" if value is True else "false" if value is False else str(value)
    return out


#: `<os>/<arch>[/<variant>]`, lower case - the spelling buildx accepts and an OCI index records. Checked at
#: the declaration because buildx's own answer to `linux-arm64` arrives after the context has been sent.
_PLATFORM = re.compile(r"[a-z0-9]+/[a-z0-9_]+(?:/[a-z0-9]+)?\Z")

#: What a buildx bake target may be called. An image name becomes one the moment it is built with
#: `platforms:` or named as a context, and bake refuses anything else - after the build has started.
_BAKE_TARGET = re.compile(r"[A-Za-z0-9_-]+\Z")


def _platforms(body: Mapping, where: str) -> tuple[str, ...]:
    """The declared `platforms:`, in order, or () when the key is absent.

    A LIST AND NEVER A STRING. `platforms: linux/amd64,linux/arm64` is buildx's own CLI spelling, and
    accepting it here would make a YAML list and a comma-joined string two ways to say one thing.

    WHAT IS NOT REFUSED, on purpose. An empty list is the same statement as no key - one platform, the
    host's - and a platform listed twice is a restatement; both build a working image, so refusing them
    would be expression rules with nothing measured behind them. The duplicate is dropped, the empty
    list read as absent.
    """
    declared = body.get("platforms")
    if declared is None:
        return ()
    if not isinstance(declared, list):
        raise ValueError(f"{where}: 'platforms' must be a list of platforms such as "
                         f"[linux/amd64, linux/arm64]; leave the key out for an image built for the "
                         f"host's own platform only")
    for entry in declared:
        if not isinstance(entry, str) or not _PLATFORM.match(entry.strip()):
            raise ValueError(f"{where}: platform {entry!r} is not '<os>/<arch>[/<variant>]', "
                             f"e.g. linux/arm64 or linux/arm/v7")
    return tuple(dict.fromkeys(entry.strip() for entry in declared))


def _bake_name(name: str, where: str) -> str:
    """`name`, when it can be a buildx bake target - which an image becomes once it has `platforms:` or is
    another image's context."""
    if not _BAKE_TARGET.match(name):
        raise ValueError(f"{where}: the image name '{name}' cannot name a buildx bake target, which it "
                         f"becomes with `platforms:` or as a context - rename the entry using letters, "
                         f"digits, '-' and '_' only")
    return name


def _contexts(section: Mapping, body: Mapping, chain: tuple[str, ...], where: str,
              source: str) -> tuple[tuple[str, Image], ...]:
    """The declared images `body` is built FROM, each validated as an image in its own right.

    A LIST OF NAMES, NOT A MAP OF REFERENCES (si#347), and that is the design decision of this key. A
    Dockerfile's `FROM ghcr.io/owner/toolchain:25` has to meet the image that supplies it under that exact
    string, and the string already exists in this section: it is the dependency's own registry,
    repository and tag. A map from a typed reference to an image name would be a second place to keep
    those three values, and the first time the toolchain's tag moves the two would disagree in a way that
    no build reports - buildx would simply pull whatever the registry holds under the stale name. So the
    name is derived (`context_name`), under the tag the dependency would be built under anyway: its
    constant `tag:`, which is firn's case, or else the derived VERSION, which a Dockerfile can name with
    a global `ARG VERSION` before its FROM.

    A name listed twice is a restatement and is dropped rather than refused, for `_platforms`' reason.
    """
    declared = body.get("contexts")
    if declared is None:
        return ()
    if not isinstance(declared, list):
        raise ValueError(f"{where}: 'contexts' must be a list of image names from the '{SECTION}:' "
                         f"section, e.g. [toolchain]")
    out: list[tuple[str, Image]] = []
    for dep in dict.fromkeys(str(entry) for entry in declared):
        if dep in chain:
            raise ValueError(f"{where}: contexts form a cycle: {' -> '.join((*chain, dep))} - an image "
                             f"cannot be built from itself")
        if dep not in section:
            raise ValueError(f"{where}: context '{dep}' is not an image in the '{SECTION}:' section; "
                             f"declared are: {', '.join(sorted(str(key) for key in section))}")
        _bake_name(dep, where)
        out.append((dep, declared_image(section, dep, source, chain)))
    return tuple(out)


def declared(data: Mapping[str, object], name: str, source: str = "manifest") -> Image:
    """The image `name` declares, validated LOUDLY.

    The four required keys are required to BE declared rather than defaulted, for the reason every
    catalogue task states: each is a statement about a product's own tree or its own publishing target,
    and a kernel that assumed `Dockerfile` at the root would build the wrong thing - or nothing - for the
    next product. `registry` is required even for a purely local build, deliberately: the reference a
    build tags is the reference a release pushes, and an unqualified one is what docker resolves against
    Docker Hub (`simplon.imagenames.require_registry` records that failure in full). Building under one name
    and publishing under another is how an image gets pushed somewhere nobody meant.
    """
    section, blame, _ = context.section(data, SECTION)
    if blame:
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping - declare "
                         f"the registry, the repository, the Dockerfile and the build context of every "
                         f"image this product builds")
    if name not in section:
        raise ValueError(f"{source}: no image '{name}' in the '{SECTION}:' section; declared are: "
                         f"{', '.join(sorted(str(key) for key in section)) or '(none)'}")
    return declared_image(section, name, source, ())


def declared_image(section: Mapping, name: str, source: str, chain: tuple[str, ...]) -> Image:
    """One entry of the section, validated - `declared`'s body, split out so a context is validated by the
    very same reading as the image that names it (si#347). `chain` is the path of names that led here."""
    body = section[name]
    if not isinstance(body, Mapping):
        raise ValueError(f"{source}: image '{name}' is not a mapping")
    where = f"{source}: '{SECTION}.{name}'"
    platforms = _platforms(body, where)
    if platforms:
        _bake_name(name, where)
    return Image(
        registry=_str(body, "registry", where, required=True),
        repository=_str(body, "repository", where, required=True),
        dockerfile=_inside_the_product(_str(body, "dockerfile", where, required=True),
                                       "dockerfile", where),
        context=_inside_the_product(_str(body, "context", where, required=True), "context", where),
        build_args=_build_args(body, where),
        tag=_str(body, "tag", where),
        platforms=platforms,
        contexts=_contexts(section, body, (*chain, name), where, source),
    )


def _declared_for(name: str) -> tuple[Image, Path]:
    """The declared image and the product root, or a ValueError that says which pin is missing."""
    if not name:
        raise ValueError(f"which image? pin one with `with: {{ name: ... }}` from the `{SECTION}:` "
                         f"section, or pass --name")
    ctx = context.current()
    return declared(ctx.manifest_data(), name, source=str(ctx.manifest_path)), ctx.root


def missing_declared_paths(cfg: Image, root: Path) -> list[str]:
    """The declared paths that point at nothing, as ready-made lines - `dockerfile:` first, then `context:`.

    WHY BOTH, AND WHY THE ANSWER SAYS WHICH (si#74). An image declaration carries two paths into the
    product's tree and either can go stale on its own; the one that actually moved is the whole content of
    the answer. The finding that opened the ticket is exactly this shape - agile-cockpit's Dockerfile moved
    from the root into `deploy/` (ac#28) and nothing in the kernel noticed - and a message that said only
    "the build failed" would have left the reader to guess which of two lines to look at.

    WHY HERE AND NOT IN THE LOADER, which is the other half of si#74's question. `declared()` is handed the
    manifest DOCUMENT and nothing else: these paths are relative to the PRODUCT ROOT, which it has no way
    to know, and giving it one would make the manifest's parser touch the disk - it is used by tests and by
    the completion generator against manifests whose tree is not checked out. So the look belongs where the
    root is resolved, and `build` asks it BEFORE `ensure_docker`: a manifest that points at nothing is wrong
    on a host with no docker too, and "docker is missing" must not be the answer to a question about a path.

    A list rather than a bool: a caller that only wanted "is it broken" would have thrown away the half
    that makes the message worth printing.
    """
    missing = []
    if not (root / cfg.dockerfile).is_file():
        missing.append(f"dockerfile: {cfg.dockerfile} - no file under the product root answers to it")
    # `root / "."` IS `root`, so the normal `context: .` asks whether the product root is a directory and
    # gets yes. A context that named a file rather than a directory would fail in docker with a message
    # about tar, so `is_dir` is the question and not `exists`.
    if not (root / cfg.context).is_dir():
        missing.append(f"context: {cfg.context} - no directory under the product root answers to it")
    return missing


def resolve_tag(cfg: Image, tag: str, derived: str = "") -> str:
    """The tag to build and publish under: the argument, else the section's own `tag:`, else the VERSION
    the image is being STAMPED with.

    The first two, for the reason `release:artifact` gives and then reuses here: most products know their
    tag as a constant and should not retype it on every call, while some only learn it after a build and
    could not have declared one. A task that supported only the manifest would exclude the second kind.

    THE THIRD IS si#200's, and it is what makes a product that declares neither work at all. This module
    already derives a VERSION from the product's own `git describe` and stamps it into the image; taking
    the TAG from a different statement would be two sources for one number, which is the shape this
    repository removes wherever it finds it - simplon's own version is derived from the git tag by
    setuptools-scm for exactly that reason, and release.yml carries a step whose only job is to catch the
    two drifting apart. So the tag is the version, verbatim: `v0.13.0` stays `v0.13.0`, because stripping
    the 'v' would be a third rule about the same number and the reader would then have to know which of
    the three they are looking at.

    `derived` is passed in rather than computed here because the caller has already computed it -
    `build_arguments` runs `provenance` once, and running git a second time to answer the same question
    would also print its warnings twice.

    Precedence is `build_arguments`': anything DECLARED beats anything derived. It follows that a product
    stating `build_args: { VERSION: ... }` moves the tag with it, which is the property that keeps one
    number in one place whichever place that turns out to be.
    """
    resolved = tag or cfg.tag or derived
    if not resolved:
        raise ValueError(
            f"no tag: declare `tag:` in the `{SECTION}:` section for a constant one, or pass --tag for a "
            f"version that is only known after a build. Neither is needed in a git checkout - the tag "
            f"then defaults to the derived {VERSION_ARG} - and this tree is not one, or has no commit "
            f"yet (the warning above says which)")
    return resolved


def provenance(root: Path) -> dict[str, str]:
    """VERSION and REVISION derived from the PRODUCT's OWN git checkout, or an empty mapping with a
    warning when there is no such checkout to ask.

    Empty rather than a placeholder: see the module head.

    THE ROOT HAS TO BE THE REPOSITORY'S OWN, and checking that is the whole reason this is not two
    `git -C` calls. `git -C <dir>` CLIMBS: run in a directory with no `.git` of its own it answers out of
    the nearest enclosing repository, with rc 0 and no hint that it did. Measured - a product tree
    created inside this kernel's checkout returned `VERSION=v0.2.0-1-ga24eaf2` and simplon's own HEAD,
    which is the exact mislabelling the head above promises not to do, arriving through the back door.
    `rev-parse --show-toplevel` is the question that catches it, and both sides are resolved because a
    checkout reached through a symlink is still that checkout.

    A product that genuinely lives in a subdirectory of a larger repository is refused too, and gets a
    warning naming the repository that was found. That is the honest reading: from here a monorepo member
    and a stray directory inside somebody else's checkout look identical, so the kernel declines to guess
    and the product states its own values in `build_args:`, which already win over anything derived.
    """
    if shutil.which("git") is None:
        log.warn("git is not on PATH, so the image is built without VERSION/REVISION build arguments; "
                 "the Dockerfile's own ARG defaults apply")
        return {}
    toplevel = run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if not toplevel.ok:
        log.warn(f"{root} is not a git checkout, so the image is built without VERSION/REVISION build "
                 f"arguments; the Dockerfile's own ARG defaults apply")
        return {}
    # AN EMPTY ANSWER IS A THIRD STATE (si#274), and it is the one that used to be invisible. `Path("")`
    # is `PosixPath('.')` and resolves to the WORKING DIRECTORY, so an empty `--show-toplevel` walked
    # into the branch below, compared the cwd with the product root, found them different and reported
    # this tree as living inside somebody else's checkout - naming that checkout as `.`, which is what
    # the message read on the day: "the nearest one is .". Measured 2026-09-16 on a self-hosted runner.
    if not toplevel.answered:
        log.warn(f"`git rev-parse --show-toplevel` succeeded in {root} and printed nothing, which is "
                 f"neither an answer nor an error, so no VERSION/REVISION could be derived and none is "
                 f"guessed. The Dockerfile's own ARG defaults apply; if this repeats, it is si#274")
        return {}
    found = Path(toplevel.out.strip())
    if found.resolve() != Path(root).resolve():
        log.warn(f"{root} has no git checkout of its own - the nearest one is {found}, and stamping ITS "
                 f"version onto this image would label the product with somebody else's. Built without "
                 f"VERSION/REVISION; declare them in the image's `build_args:` if that repository is "
                 f"in fact this product's")
        return {}
    described = run(["git", "-C", str(root), "describe", "--tags", "--always", "--dirty"])
    revision = run(["git", "-C", str(root), "rev-parse", "HEAD"])
    if not (described.ok and revision.ok):
        log.warn(f"{root} is a git checkout with no commit yet, so the image is built without "
                 f"VERSION/REVISION build arguments; the Dockerfile's own ARG defaults apply")
        return {}
    # The same third state one line down, and this one has never been seen to fire - which is exactly
    # why it is here rather than after it has (si#274). An empty `describe` would stamp `VERSION=""`
    # into the image: a label that is present, empty and wrong, which is worse than the absent one the
    # branch above produces, because a reader of the image cannot tell it from a build that declined to
    # say. `ok` asks whether git succeeded; `answered` asks whether it said anything.
    if not (described.answered and revision.answered):
        log.warn(f"git succeeded in {root} and printed nothing for "
                 + " and ".join(name for name, res in (("`describe`", described), ("`rev-parse HEAD`", revision))
                                if not res.answered)
                 + ", so the image is built without VERSION/REVISION rather than with an empty one; "
                   "the Dockerfile's own ARG defaults apply (si#274)")
        return {}
    return {VERSION_ARG: described.out.strip(), REVISION_ARG: revision.out.strip()}


def build_arguments(cfg: Image, root: Path) -> dict[str, str]:
    """Every `--build-arg` the build passes: the derived provenance first, the product's declared ones
    over it.

    That precedence is the decision, not an accident of dict ordering: a `build_args:` entry naming
    VERSION is a product saying where its version really comes from, and the kernel's derivation is a
    default for the products that have not said. Silently winning over a manifest would make the manifest
    a suggestion.
    """
    return {**provenance(root), **cfg.build_args}


def reference(cfg: Image, tag: str) -> str:
    """`ghcr.io/owner/repo:tag` - the same joining `release:artifact` publishes under, from
    `githubpackages.reference`, so an image and an artifact of one product cannot end up spelled
    differently."""
    return githubpackages.reference(cfg.registry, cfg.repository, tag)


def build_image(cfg: Image, tag: str, root: Path, args: dict[str, str]) -> int:
    """Build the declared image under `root` and return docker's real rc.

    `--file` and the context are joined onto the product root rather than passed as the manifest wrote
    them, so the command means the same thing whatever directory the CLI was invoked from.

    `args` is handed in rather than computed here since si#200: the tag may BE the derived VERSION, so
    the caller has to hold the arguments before it can name the reference to build.
    """
    ref = reference(cfg, tag)
    argv = ["docker", "build", "--file", str(root / cfg.dockerfile), "--tag", ref]
    for key in sorted(args):
        argv += ["--build-arg", f"{key}={args[key]}"]
    # `root / "."` IS `root` - pathlib drops the segment - so the '.' the manifest may carry needs no
    # branch here, and a branch that can never take its second arm is a claim about the code that is
    # false.
    argv.append(str(root / cfg.context))
    log.info(f"building {ref} from {cfg.dockerfile} "
             f"({', '.join(f'{k}={args[k]}' for k in sorted(args)) or 'no build arguments'})")
    return stream(argv, cwd=str(root))


def published(ref: str) -> bool:
    """Whether the REGISTRY serves `ref` - the read-back that makes a push a publish.

    One client, and it is deliberately not a docker one: the module head carries the measurements,
    including the `docker manifest inspect` answer that came back rc 0 for a tag no registry held. oras
    keeps no manifest store, so it has nothing local to answer from; it authenticates off the same
    `~/.docker/config.json` the push's own login wrote.

    `require_oras` PROVIDES the tool rather than demanding it, and raises `PackageError` when even that
    could not - which the caller turns into a red release, because a push nobody could verify is not a
    publish.
    """
    githubpackages.require_oras()
    return run(["oras", "manifest", "fetch", "--descriptor", ref]).ok


def present_locally(ref: str) -> bool:
    """Whether the local daemon already holds `ref`. Asked before a push so that "you have not built it
    yet" is answered as itself, rather than as docker's `An image does not exist locally`."""
    return run(["docker", "image", "inspect", ref]).ok


#: The file `build:image` leaves behind, under `<output>/docker/` (si#314).
RECORD = "image.txt"


def local_id(ref: str) -> str:
    """The daemon's id for `ref`, or '' when it cannot be read. NOT a registry digest, and the two are
    not interchangeable: a freshly built image has no `RepoDigests` entry at all - that one comes into
    being when something is pushed or pulled - so calling this a digest would be a word that is wrong on
    the one day somebody relies on it."""
    result = run(["docker", "image", "inspect", "--format", "{{.Id}}", ref])
    return result.out.strip() if result.ok else ""


def record(ref: str, image_id: str, root: Path,
           platforms: Mapping[str, tuple[str, str]] | None = None) -> Path | None:
    """Write what the build produced into `<output>/docker/image.txt`, returning the path or None.

    A POINTER RATHER THAN CONTENT, which is the whole of si#314's answer for the one output that is not
    a file: a container image lives in a daemon, not in a directory, and what a deployment redeems is
    the reference. `docker save` was measured and rejected - about a gigabyte per build for a toolchain
    image, written by something nobody reads.

    A write that fails does NOT make the build red, and that is deliberate: the image exists, and
    reporting a built image as a failed build would be the opposite lie to the one this ticket is
    about. It is reported instead, because a promise quietly not kept is the defect this repository
    hunts - `tasks/docs.py` records the real case, a `build/` owned by root.
    """
    try:
        directory = outputs.for_kind("docker")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / RECORD
        path.write_text(
            f"# What `build:image` produced, and where to find it (si#314). A POINTER, not the image:\n"
            f"# a container image lives in a daemon rather than in a directory, and a deployment\n"
            f"# redeems this reference. Written on every build; this file is a build output like the\n"
            f"# rest of `{outputs.KEY}:` and dies with a clean.\n"
            f"reference: {ref}\n"
            f"image-id: {image_id or 'not readable'}\n"
            f"# `image-id` is the DAEMON's id, not a registry digest. A registry digest exists only\n"
            f"# once something has been pushed, which is `release:image` and not this command.\n"
            + _platform_lines(platforms or {}),
            encoding="utf-8")
        return path
    except (OSError, RuntimeError, ValueError) as broken:
        log.warn(f"{ref} was built, but {RECORD} could not be written: {broken}")
        return None


def _platform_lines(platforms: Mapping[str, tuple[str, str]]) -> str:
    """The record's lines for a multi-platform build (si#347): one per platform, naming the per-platform
    reference the daemon holds it under and that image's id."""
    if not platforms:
        return ""
    lines = ["# One image per declared platform, each loaded into the daemon under its own reference: the\n"
             "# daemon cannot hold a manifest list, the registry can, and `release:image` assembles it.\n"]
    lines += [f"{platform}: {ref} image-id: {image_id or 'not readable'}\n"
              for platform, (ref, image_id) in platforms.items()]
    return "".join(lines)


def build(name: str = "", tag: str = "", platform: str = "") -> int:
    """Build the container image `name` declares, tagged with the reference it will be published under.

    `name` is normally pinned per command with `with: { name: ... }`, the shape `test:gate` and
    `release:artifact` both use - a product with two images declares two commands rather than making the
    caller remember a string.

    `platform` builds ONE of the declared `platforms:` (si#347, fix round 1). Without it a multi-platform
    image is built for every declared platform, which is what a release needs; with it, the everyday
    "build the image I can run here" stays one native build on a host with no emulator, and a product
    pins it per command - firn's CI and devcontainer with `platform: linux/amd64`.
    """
    cfg, root = _declared_for(name)
    if not _platform_declared(cfg, name, platform):
        return 1
    # si#74, and the order is the point: the manifest's own paths are checked BEFORE the tool is demanded,
    # so a declaration that points at nothing is answered as itself on a host that has no docker either.
    # si#347 widened it to the images a multi-platform build bakes alongside this one, because their
    # Dockerfiles are read in the same run; a single-platform build does not build its contexts, so their
    # paths are not this run's business.
    checked = [cfg, *(dep for _, dep in dependencies(cfg))] if cfg.platforms else [cfg]
    missing = [line for one in checked for line in missing_declared_paths(one, root)]
    if missing:
        both = "two paths that do not exist" if len(missing) > 1 else "a path that does not exist"
        log.error(f"image '{name}' declares {both} under {root}:\n  " + "\n  ".join(missing)
                  + f"\n  fix the `{SECTION}.{name}:` entry, or move what it names - docker would have "
                    f"failed later, about something else")
        return 1
    docker.ensure_docker()
    if cfg.platforms:
        return _build_platforms(cfg, name, tag, root, platform)
    args = build_arguments(cfg, root)
    if not _contexts_in_the_daemon(cfg, name, args.get(VERSION_ARG, "")):
        return 1
    resolved = resolve_tag(cfg, tag, args.get(VERSION_ARG, ""))
    rc = build_image(cfg, resolved, root, args)
    if rc != 0:
        log.error(f"docker build failed (rc={rc}); {reference(cfg, resolved)} was not built "
                  f"(see output above)")
        return rc
    ref = reference(cfg, resolved)
    if not present_locally(ref):
        # The 0.1.7 shape again: a builder that reports success and leaves nothing behind. It is one
        # cheap question, and it is the only thing between here and a release step that pushes a
        # reference the daemon does not have.
        log.error(f"docker build exited 0 but the daemon does not hold {ref}; nothing was built")
        return 1
    written = record(ref, local_id(ref), root)
    log.ok(f"built {ref}" + (f" ({written.relative_to(root)})" if written else ""))
    return 0


def smoke(name: str = "", tag: str = "", argv: str = "", mount: str = "", expect: str = "",
          rc: int = 0, user: bool = True, platform: str = "") -> int:
    """Run the container image `name` declares and check that it answers (si#301).

    `rc` IS AN EXPECTATION AND NOT A TOLERANCE (si#303), which is the whole of why it takes a value
    rather than a list or a flag. `rc: 2` means "exactly 2, and 0 would then be red" - so a system level
    can say *the image REFUSES a broken input*, which is the other half of what it wants to say about a
    shipped artefact and which `rc != 0 is red` could not express at all. A tolerance would widen what
    counts as green; an expectation moves it, and only the second is still a gate. The wording is the
    consumer's who asked for it (firn), and it is better than the one this ticket opened with.

    The third verb over one image, and the one that was missing: `build:image` produces,
    `release:image` publishes, and until now nothing RAN what was produced. A product could therefore
    build an image, push it, and never once execute the runtime stage of its own Dockerfile - the
    directives that copy the binary into a base and set the entrypoint - which is exactly the half a
    unit test cannot reach.

    **It builds nothing and pulls nothing.** It runs what the daemon holds under the reference the
    build would have produced, so a missing image is a refusal that names `build image` rather than a
    silent pull of something older. The tag is resolved the way `build` and `release` resolve it, so
    the three verbs cannot end up naming three references.

    `mount` is `<product-relative dir>:<absolute path in the container>`, which is what makes a smoke
    test about a workspace rather than about `--version`: a product mounts a fixture, runs its own
    command over it, and the run proves the image can READ a bind mount as the invoking user.

    **Reading, and not writing, and that limit is measured rather than modest** (si#303). This
    sentence claimed both until the first consumer tried it: `mount` takes a product-relative
    directory, so the only thing a product can bind is a directory of its own checkout, and a
    command that wrote into it would leave the tree dirty. firn#110 therefore proves its image's
    runtime stage with a read-only `check` and says in its own notes that the write path stays
    unproven. A scratch mount would close it; until there is one, the claim is not this task's to
    make.

    **Every declared platform starts once** (si#347). For an image with `platforms:` the run is repeated
    per platform, each under `--platform` against the reference `build:image` loaded that platform under,
    so an arm64 image that cannot start is found before it is published rather than by an arm64 user.
    Every platform runs even after one has failed, because which of them failed is the whole content of
    the answer; `platform:` narrows the run to one.
    """
    cfg, root = _declared_for(name)
    docker.ensure_docker()
    resolved = resolve_tag(cfg, tag, build_arguments(cfg, root).get(VERSION_ARG, ""))
    ref = reference(cfg, resolved)
    if not _platform_declared(cfg, name, platform):
        return 1
    runs = ([(each, platform_reference(ref, each)) for each in ([platform] if platform else cfg.platforms)]
            if cfg.platforms else [("", ref)])
    absent = [each for _, each in runs if not present_locally(each)]
    if absent:
        log.error(f"the daemon does not hold {', '.join(absent)}; nothing was run.\n"
                  f"  this verb runs what a build produced and never pulls: build it first "
                  f"(`build image`), or name the tag you mean with `tag:`")
        return 1
    options: list[str] = []
    if user:
        options += ["--user", f"{os.getuid()}:{os.getgid()}"]
    if mount:
        bound = _mount_argv(mount, root)
        if bound is None:
            return 1
        options += bound
    verdicts = [_run_once(each, [*(["--platform", one] if one else []), *options], argv, expect, rc)
                for one, each in runs]
    return next((verdict for verdict in verdicts if verdict != 0), 0)


def _run_once(ref: str, options: list[str], argv: str, expect: str, rc: int) -> int:
    """One `docker run` of `ref` and its verdict: 0, or the code `smoke` hands back."""
    command = ["docker", "run", "--rm", *options, ref, *shlex.split(argv)]
    result = run(command)
    if result.rc != rc:
        log.error(f"{ref} exited {result.rc}" + (f", and {rc} was expected" if rc else "") + "\n"
                  + _indented(result))
        # `result.rc or 1` and not `result.rc`: when a REFUSAL was expected and the image exited 0, the
        # container's own code is the success this test is refusing to accept, and handing it back would
        # report the failure as green.
        return result.rc or 1
    if expect and expect not in result.out:
        log.error(f"{ref} exited {result.rc} and did not say what was expected.\n"
                  f"  expected to find: {expect}\n" + _indented(result))
        return 1
    log.ok(f"ran {ref}")
    return 0


def _mount_argv(mount: str, root: Path) -> list[str] | None:
    """`-v <host>:<container>` for a declared mount, or `None` after saying why it is not one.

    The host half is product-relative for `_inside_the_product`'s reason: a manifest that could name an
    absolute path would let one product's command reach into another's tree, and a smoke test is the
    last place that should be possible.
    """
    host, _, target = mount.partition(":")
    if not target or not target.startswith("/"):
        log.error(f"mount '{mount}' is not `<directory>:<absolute path in the container>`")
        return None
    try:
        inside = _inside_the_product(host, "mount", "a smoke run")
    except ValueError as refused:
        log.error(str(refused))
        return None
    path = root / inside
    if not path.is_dir():
        log.error(f"mount '{mount}' names {path}, which is not a directory under {root}")
        return None
    # si#201's rule, and it is why this returns a translated source rather than `path`: on the
    # container route the daemon resolves a mount source against the HOST, so an untranslated one
    # mounts an empty directory it creates there -- rc 0, no message, and a smoke test that proves
    # nothing over a workspace that is not the workspace.
    return ["-v", f"{hostpath.translate(path)}:{target}"]


def _indented(result: Result) -> str:
    """What the container said, under the line that reports it - both streams, because an image that
    fails usually says why on the one nobody printed."""
    said = "\n".join(part for part in (result.out.strip(), result.err.strip()) if part)
    return "\n".join(f"  {line}" for line in said.splitlines()) if said else "  (it said nothing)"


def release(name: str = "", tag: str = "") -> int:
    """Publish the container image `name` declares: log in, push, and CHECK THE REGISTRY HAS IT.

    Builds nothing. `build` and `release` are two of the five verbs and stay two commands, so a product
    that builds an image for a smoke test never accidentally publishes it; a product that wants both in
    one step declares an aggregate over them, which is where an ordering belongs.
    """
    docker.ensure_docker()
    cfg, root = _declared_for(name)
    # The same derivation the build used, so the two commands name one reference without the number being
    # typed twice - and a checkout that has moved since the build says so, by naming a tag that is not on
    # this machine, rather than by publishing the wrong one.
    derived = provenance(root)
    resolved = resolve_tag(cfg, tag, {**derived, **cfg.build_args}.get(VERSION_ARG, ""))
    ref = reference(cfg, resolved)

    if cfg.platforms:
        # si#347: the manifest list is pushed out of the builder, not out of the daemon, but the daemon
        # holding every platform is what proves the build ran for this tag - and what keeps the push an
        # export from a warm cache rather than a build nobody asked this command to do.
        absent = [platform for platform in cfg.platforms
                  if not present_locally(platform_reference(ref, platform))]
        if absent:
            log.error(f"{ref} has not been built on this machine for {', '.join(absent)}, so there is "
                      f"nothing to push - run `build image` WITHOUT `platform:`, so every declared "
                      f"platform is built, with the same --tag. A release publishes all of "
                      f"{', '.join(cfg.platforms)} or none of them")
            return 1
        if not _recorded_for_every_platform(cfg, name, ref):
            return 1
    elif not present_locally(ref):
        log.error(f"{ref} is not on this machine, so there is nothing to push - run the build first "
                  f"(`build:image`, with the same --tag)")
        return 1

    # The read-back's tool is provisioned BEFORE anything is pushed. A host that cannot get oras must
    # learn it here, not after an image is in a registry with no way to confirm that it is.
    try:
        githubpackages.require_oras()
    except githubpackages.PackageError as failure:
        log.error(f"the push would not be verifiable, so it was not attempted: {failure}")
        return 1

    host = githubpackages.registry_host(cfg.registry)
    if githubpackages.is_github_packages(cfg.registry):
        try:
            githubpackages.docker_login(cfg.registry)
        except githubpackages.PackageError as failure:
            # Caught rather than allowed to propagate: this message is the fix (it names `gh auth
            # refresh` and the two scopes), and a traceback would bury it under a stack from a wrapper
            # the reader did not write. Acceptance 4's second half - a missing scope names the command
            # that sets it.
            log.error(str(failure))
            return 1
    else:
        # A GITHUB token goes to GITHUB and nowhere else. `registry:` is a manifest key, so a product
        # writing `registry: registry.example.com/team` would otherwise have this task mint a GitHub PAT
        # and hand it to a third party - and then answer the 401 with `gh auth refresh`, advice that
        # means nothing there. The module this credential comes from exists because a token leaked once;
        # sending it to whatever host a YAML file names is the same mistake with more steps.
        #
        # si#200 added the second half of that sentence. Refusing to MINT a credential left the push with
        # none, and it went out anyway: docker answered `denied: requested access to the resource is
        # denied`, which names neither the host nor the account nor the fix. So the stored credential is a
        # PRECONDITION now, checked before anything is pushed and answered by naming the host and the one
        # command that authorises it. The kernel still holds no secret for this host - it reads no token,
        # writes no config and logs nobody in; it only declines to push into a registry that is going to
        # refuse it. Rejected on the way: a DOCKERHUB_TOKEN read here. It would put a second registry
        # secret into the process that `is_github_packages` exists to keep down to one, for no gain over
        # `docker login`, which every CI already has an action for.
        if not docker.has_stored_login(host):
            log.error(f"no credential for {host}, so {ref} was not pushed - the push would have been "
                      f"answered by `denied: requested access to the resource is denied`.\n"
                      f"  run `docker login {host}` first (in CI: log in with the registry's own token, "
                      f"never with a GitHub one).\n"
                      f"  this kernel mints a token for GitHub Packages and for nothing else, on "
                      f"purpose - see simplon.githubpackages.is_github_packages")
            return 1
        log.info(f"{host} is not GitHub Packages, so no GitHub token is minted for it - the push uses "
                 f"the credential `docker login {host}` has already stored")

    if cfg.platforms:
        return _push_platforms(cfg, name, root, ref, derived)

    log.info(f"pushing {ref}")
    rc = stream(["docker", "push", ref], cwd=str(root))
    if rc != 0:
        # The scope advice is a HINT, tied to a host and a condition, not a diagnosis appended to every
        # failure. A push fails on a full disk and a dead network too, and a message that says the same
        # thing whatever happened says nothing at all.
        advice = ("\nif the registry refused it rather than the network, the usual cause on GHCR is a "
                  "token without the package scopes:\n" + githubpackages.scope_advice()
                  if githubpackages.is_github_packages(cfg.registry) else "")
        log.error(f"docker push {ref} failed (rc={rc}; see output above){advice}")
        return rc

    try:
        there = published(ref)
    except githubpackages.PackageError as failure:
        log.error(f"{ref} was pushed, but the publish could not be verified: {failure}")
        return 1
    if not there:
        log.error(f"docker push exited 0 but {ref} is not in the registry. either the tag was not "
                  f"stored or the registry could not be asked - both mean the publish is unproven, and "
                  f"an unproven publish is what this check exists to stop being reported as done")
        return 1
    log.ok(f"published {ref}")
    return 0


# --- si#347: one image, several platforms, one manifest list -------------------------------------------
#
# WHY BUILDX BAKE, AND NOT `docker buildx build`. firn's Dockerfile starts `FROM` an image the same manifest
# declares and nobody publishes. The classic builder resolves that in the daemon; a buildx builder with the
# docker-container driver - the only kind that can produce a manifest list on a daemon without the
# containerd image store - cannot see the daemon at all, so the dependency has to be SUPPLIED, per
# platform. `docker buildx build --build-context name=...` takes a registry image, a directory or an OCI
# layout, and each of those means building and exporting the dependency once per platform by hand. A bake
# target can instead name another target (`target:toolchain`), and bake then builds the dependency for
# exactly the platforms the dependent asks for, inside the same builder, with no tag and no output - so
# it is never pushed anywhere. Measured 2026-10-10 against a local registry:2 with buildx v0.38.0: a
# `FROM ghcr.io/example/demo-toolchain:25` resolved through `contexts:` without a single request to ghcr,
# and the arm64 stage ran on the arm64 toolchain.
#
# WHY THE BUILD LOADS ONE IMAGE PER PLATFORM. A daemon with the classic image store cannot hold a manifest
# list, and whether a host has the containerd store is the host's business - an answer that depends on
# which host asked is the shape this module refuses everywhere else. So `build:image` loads each platform
# into the daemon under its own reference (`<ref>-linux-arm64`), which every daemon can hold; `test:image`
# runs each of those under `--platform`; and the host's own platform is also tagged under the plain
# reference, so everything that runs the image by name keeps running it. `release:image` then pushes the
# manifest list out of the builder, where the cache from the build makes it an export rather than a
# second build. Measured 2026-10-10 through these very functions, on an x86_64 host with a fresh
# `simplon` builder: `build:image` for linux/amd64 + linux/arm64 with the dependency baked alongside took
# 7.6s cold; `test:image` ran both platforms in 0.5s (`uname -m` said x86_64 and aarch64); `release:image`
# pushed the list in 1.0s, every step CACHED, and the dependency's repository was never created in the
# registry. An index re-tagged with only amd64 was read back as missing linux/arm64 - the tag-only probe
# answers rc 0 for that same reference.
#
# EMULATION IS WARNED ABOUT, NEVER REGISTERED, NEVER REFUSED. Registering binfmt handlers is a privileged
# `docker run` that changes the host KERNEL for every process on it until reboot - on a shared self-hosted
# runner that is a decision for whoever owns the machine, of the same kind as `support:ci-disk-hygiene`,
# which this catalogue also leaves to a person. Refusing up front would be an expression rule with no
# measured cause: a Dockerfile that cross-compiles with `FROM --platform=$BUILDPLATFORM` needs no emulator
# at all and would be refused for nothing. So the builder's own platform list is read, a platform it cannot
# run is named with the one command that registers it, and a failed build repeats that command.

#: The buildx builder the kernel creates and uses BY NAME, so it never changes which builder is a
#: developer's current one (`docker buildx use` is never run).
BUILDER = "simplon"


def context_name(cfg: Image, version: str = "") -> str:
    """The name a Dockerfile's FROM uses for a declared image: its own reference, under the tag it would
    be built under - its constant `tag:`, else the derived VERSION (`resolve_tag`'s order)."""
    return reference(cfg, resolve_tag(cfg, "", version))


def platform_reference(ref: str, platform: str) -> str:
    """`ghcr.io/o/app:1.0-linux-arm64` - where the daemon holds ONE platform of a multi-platform image."""
    return f"{ref}-{platform.replace('/', '-')}"


def platform_target(name: str, platform: str) -> str:
    """The bake target that builds `platform` alone and loads it into the daemon."""
    return f"{name}__{platform.replace('/', '_')}"


def dependencies(cfg: Image) -> list[tuple[str, Image]]:
    """Every image `cfg` is built from, transitively, each once, dependencies before their dependents."""
    out: list[tuple[str, Image]] = []

    def visit(image_: Image) -> None:
        for dep_name, dep in image_.contexts:
            visit(dep)
            if dep_name not in (name for name, _ in out):
                out.append((dep_name, dep))

    visit(cfg)
    return out


def _target_contexts(cfg: Image, version: str) -> dict[str, str]:
    return {context_name(dep, version): f"target:{dep_name}" for dep_name, dep in cfg.contexts}


def bake_definition(cfg: Image, name: str, ref: str, derived: Mapping[str, str], root: Path) -> dict:
    """The bake file for `cfg`: its dependencies, the pushing target `name`, and one loading target per
    platform. Pure.

    Every target is written out in full rather than through bake's `inherits`, so the file in
    `<output>/docker/` reads as what ran without its reader knowing bake's merge rules. A dependency is
    built for THE DEPENDENT's platforms, not for any it declares itself, and carries no tag and no output:
    it exists only as an input, so nothing can publish it.
    """
    def target(image_: Image) -> dict:
        body: dict = {"context": str(root / image_.context), "dockerfile": str(root / image_.dockerfile),
                      "platforms": list(cfg.platforms), "args": {**derived, **image_.build_args}}
        if image_.contexts:
            body["contexts"] = _target_contexts(image_, derived.get(VERSION_ARG, ""))
        return body

    targets = {dep_name: target(dep) for dep_name, dep in dependencies(cfg)}
    targets[name] = {**target(cfg), "tags": [ref], "output": ["type=registry"]}
    for platform in cfg.platforms:
        targets[platform_target(name, platform)] = {
            **target(cfg), "platforms": [platform],
            "output": [f"type=docker,name={platform_reference(ref, platform)}"]}
    return {"target": targets}


def write_bake(definition: dict, name: str) -> Path | None:
    """Write the bake file under `<output>/docker/`, or say why it could not be and return None. Unlike
    `record`, a failure here IS red: the build reads this file."""
    try:
        directory = outputs.for_kind("docker")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"bake-{name}.json"
        path.write_text(json.dumps(definition, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path
    except (OSError, RuntimeError, ValueError) as broken:
        log.error(f"the bake file for image '{name}' could not be written, so nothing was built: {broken}")
        return None


def builder_platforms(text: str) -> set[str] | None:
    """The platforms builder `BUILDER` can run, out of `docker buildx ls --format json` (one JSON object
    per line), or None when the answer does not say."""
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("Name") == BUILDER:
            found = {str(platform) for node in entry.get("Nodes") or [] if isinstance(node, dict)
                     for platform in node.get("Platforms") or []}
            return found or None
    return None


def missing_platforms(declared: Iterable[str], found: Iterable[str]) -> list[str]:
    """The declared platforms `found` does not carry, in declared order. Pure.

    A declared `linux/arm64` is carried by a `linux/arm64/v8`: a registry or a builder may add the variant
    the declaration left implicit. The reverse does not hold - `linux/arm/v7` is not `linux/arm/v6`.
    """
    have = set(found)
    return [platform for platform in declared
            if not any(f == platform or f.startswith(platform + "/") for f in have)]


def _emulation_command(platforms: Iterable[str]) -> str:
    arches = ",".join(dict.fromkeys(platform.split("/")[1] for platform in platforms))
    return f"docker run --privileged --rm {BINFMT_IMAGE} --install {arches}"


def _emulation_advice(unrunnable: list[str]) -> str:
    if not unrunnable:
        return ""
    return (f"\n  the builder could not run {', '.join(unrunnable)} before the build started, so if the "
            f"output above says `exec format error` this host has no emulator for it. Register one - a "
            f"privileged act on the whole host, which is why simplon does not do it for you:\n"
            f"    {_emulation_command(unrunnable)}\n"
            f"  then `docker buildx rm {BUILDER}`, so the builder is created again and sees it")


def prepare_builder(platforms: tuple[str, ...]) -> tuple[bool, list[str]]:
    """The builder, ready: (whether it is, the declared platforms it cannot run).

    buildx is DEMANDED, not provided. Unlike oras it is a docker CLI plugin and has to sit where that
    CLI looks; the static CLI `simplon.docker` bootstraps carries none, so the refusal names the two
    places one comes from.
    """
    if not run(["docker", "buildx", "version"]).ok:
        log.error("a multi-platform image is built with `docker buildx`, and this docker has no buildx "
                  "plugin. Install it: the `docker-buildx-plugin` package from Docker's repository, or "
                  "docker/setup-buildx-action in a workflow. The static docker CLI simplon can bootstrap "
                  "carries no plugins.")
        return False, []
    if not run(["docker", "buildx", "inspect", "--bootstrap", BUILDER]).ok:
        log.info(f"no buildx builder '{BUILDER}' yet; creating it with the docker-container driver, the "
                 f"one that can produce a manifest list on any daemon")
        create = ["docker", "buildx", "create", "--name", BUILDER, "--driver", "docker-container",
                  "--driver-opt", "network=host", "--bootstrap"]
        created = run(create)
        # TWO RUNS CAN GET HERE AT ONCE - two jobs on one daemon that both found no builder - and the one
        # that loses the race is told `existing instance`. That is not a failure of anything this run
        # needs, so the builder is asked about once more before the answer is red.
        if not created.ok and not run(["docker", "buildx", "inspect", "--bootstrap", BUILDER]).ok:
            log.error(f"`{' '.join(create)}` failed, so nothing was built: "
                      f"{(created.err or created.out).strip() or '(it said nothing)'}")
            return False, []
        if not created.ok:
            log.info(f"builder '{BUILDER}' was created meanwhile by another run; using it")
    runnable = builder_platforms(run(["docker", "buildx", "ls", "--format", "json"]).out)
    if runnable is None:
        log.warn(f"could not read which platforms builder '{BUILDER}' can run; building anyway")
        return True, []
    unrunnable = missing_platforms(platforms, runnable)
    if unrunnable:
        log.warn(f"builder '{BUILDER}' cannot run {', '.join(unrunnable)} (it can run "
                 f"{', '.join(sorted(runnable))}). A Dockerfile that RUNs anything in those stages needs "
                 f"an emulator; one that cross-compiles does not. To register one:\n"
                 f"    {_emulation_command(unrunnable)}")
    return True, unrunnable


def _native_platform() -> str:
    """The daemon's own platform, `linux/amd64`, or '' when it does not say."""
    result = run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"])
    return result.out.strip() if result.answered else ""


def _contexts_in_the_daemon(cfg: Image, name: str, version: str) -> bool:
    """For a SINGLE-platform image built from another: the dependency is in the daemon, or a refusal.

    The plain `docker build` resolves FROM in the daemon and, failing that, PULLS - from a registry that
    for firn's toolchain never had the image. The argv is untouched; this only answers the missing
    dependency as itself, before docker answers it as somebody else's registry.
    """
    for dep_name, dep in cfg.contexts:
        if not present_locally(context_name(dep, version)):
            log.error(f"image '{name}' is built FROM {context_name(dep, version)}, which the daemon does "
                      f"not hold.\n"
                      f"  build it first: `build:image` with `with: {{ name: {dep_name} }}`. Without "
                      f"`platforms:` the build resolves FROM in the daemon, and docker would otherwise "
                      f"try to pull an image that was never published")
            return False
    return True


def _platform_declared(cfg: Image, name: str, platform: str) -> bool:
    """Whether `platform` - '' for "all of them" - is one this image can be asked for, or a refusal that
    names the declared list. Shared by `build` and `smoke`, so the two answer one question in one way."""
    if platform and not cfg.platforms:
        log.error(f"`platform: {platform}` was given, but image '{name}' declares no `platforms:` - it is "
                  f"built for this host's platform only. Declare `platforms:` on `{SECTION}.{name}`, or "
                  f"drop `platform:`")
        return False
    if platform and platform not in cfg.platforms:
        log.error(f"image '{name}' is not built for {platform}; its declared platforms are "
                  f"{', '.join(cfg.platforms)}")
        return False
    return True


#: What `build:image` produced per platform, beside `image.txt` (si#347, fix round 1). A file the release
#: READS, unlike `image.txt`: it carries the manifest digest buildx reported for each platform it loaded,
#: and `release:image` holds the pushed index against it.
BUILT = "built-{name}.json"


def built_digests(text: str, name: str, platforms: Iterable[str]) -> dict[str, str]:
    """The manifest digest bake reported per platform, out of its `--metadata-file`. Pure.

    `containerimage.digest` of a `type=docker` target is the digest of that platform's image manifest.
    Measured 2026-10-10: after a warm build, the child manifests of the index `release:image` pushed
    carried exactly these digests, platform for platform.
    """
    try:
        document = json.loads(text)
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for platform in platforms:
        entry = document.get(platform_target(name, platform)) if isinstance(document, dict) else None
        digest = entry.get("containerimage.digest") if isinstance(entry, dict) else None
        if isinstance(digest, str) and digest:
            out[platform] = digest
    return out


def _built_path(name: str) -> Path:
    return outputs.for_kind("docker") / BUILT.format(name=name)


def read_built(name: str, ref: str) -> dict[str, str]:
    """The recorded digests for `ref`, or {} - a record about another reference says nothing about this one."""
    try:
        document = json.loads(_built_path(name).read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError):
        return {}
    if not isinstance(document, dict) or document.get("reference") != ref:
        return {}
    platforms = document.get("platforms")
    return {str(k): str(v) for k, v in platforms.items()} if isinstance(platforms, dict) else {}


def _write_built(name: str, ref: str, digests: Mapping[str, str]) -> None:
    """Merge `digests` into the record for `ref`: a one-platform build replaces its own platform's entry
    and keeps the others, so `build image platform: linux/amd64` after a full build does not make the
    release forget arm64."""
    try:
        path = _built_path(name)
        merged = {**read_built(name, ref), **digests}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"reference": ref, "platforms": merged}, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as broken:
        log.warn(f"{ref} was built, but {BUILT.format(name=name)} could not be written ({broken}); "
                 f"`release:image` will refuse until a build can record what it produced")


def _recorded_for_every_platform(cfg: Image, name: str, ref: str) -> bool:
    """Before a push: the build recorded a digest for every platform, or a refusal naming the fix."""
    unrecorded = [platform for platform in cfg.platforms if platform not in read_built(name, ref)]
    if unrecorded:
        log.error(f"no record of what `build image` produced for {', '.join(unrecorded)} under {ref} "
                  f"({BUILT.format(name=name)} in the `docker` output), so the push could not be held "
                  f"against what was built and smoked. Run `build image` WITHOUT `platform:`, with the "
                  f"same --tag, then release")
        return False
    return True


def _build_platforms(cfg: Image, name: str, tag: str, root: Path, platform: str = "") -> int:
    """`build` for an image with `platforms:` - see the block above for the shape and why. `platform`
    narrows it to one declared platform."""
    chosen = (platform,) if platform else cfg.platforms
    derived = provenance(root)
    resolved = resolve_tag(cfg, tag, {**derived, **cfg.build_args}.get(VERSION_ARG, ""))
    ref = reference(cfg, resolved)
    ready, unrunnable = prepare_builder(chosen)
    if not ready:
        return 1
    path = write_bake(bake_definition(cfg, name, ref, derived, root), name)
    if path is None:
        return 1
    metadata = path.parent / f"bake-{name}.metadata.json"
    log.info(f"building {ref} for {', '.join(chosen)}"
             + (", from " + ", ".join(context_name(dep, derived.get(VERSION_ARG, ""))
                                      for _, dep in cfg.contexts) + " built alongside"
                if cfg.contexts else ""))
    rc = stream(["docker", "buildx", "bake", "--builder", BUILDER, "--file", str(path),
                 "--metadata-file", str(metadata),
                 *(platform_target(name, each) for each in chosen)], cwd=str(root))
    if rc != 0:
        log.error(f"docker buildx bake failed (rc={rc}); {ref} was not built for "
                  f"{', '.join(chosen)} (see output above)" + _emulation_advice(unrunnable))
        return rc
    loaded = {each: platform_reference(ref, each) for each in chosen}
    absent = [each for each in loaded.values() if not present_locally(each)]
    if absent:
        log.error(f"docker buildx bake exited 0 but the daemon does not hold {', '.join(absent)}; "
                  f"nothing was built for that platform")
        return 1
    native = _native_platform()
    if native in loaded:
        if not run(["docker", "tag", loaded[native], ref]).ok:
            log.warn(f"{loaded[native]} was built but could not be tagged {ref}")
    else:
        log.info(f"this host ({native or 'platform not readable'}) is not among the declared platforms, "
                 f"so nothing is tagged {ref} here; each platform is under its own reference")
    try:
        reported = metadata.read_text(encoding="utf-8")
    except OSError:
        reported = ""
    digests = built_digests(reported, name, chosen)
    if len(digests) < len(chosen):
        log.warn(f"bake reported no image digest for "
                 f"{', '.join(each for each in chosen if each not in digests)}; `release:image` will "
                 f"refuse to publish until a build records one")
    _write_built(name, ref, digests)
    written = record(ref, local_id(ref) if native in loaded else "", root,
                     platforms={each: (loaded_ref, local_id(loaded_ref)) for each, loaded_ref in loaded.items()})
    log.ok(f"built {ref} for {', '.join(chosen)}"
           + (f" ({written.relative_to(root)})" if written else ""))
    return 0


def index_platforms(text: str) -> set[str] | None:
    """The platforms a manifest LIST carries, `os/arch[/variant]`, or None when `text` is not one. Pure."""
    manifests = index_manifests(text)
    return None if manifests is None else set(manifests)


def index_manifests(text: str) -> dict[str, str] | None:
    """Platform -> child manifest digest of a manifest LIST, or None when `text` is not one. Pure.

    `unknown/unknown` is not a platform: it is how buildx marks the attestation manifests it adds beside
    the images, measured in the index it pushed to a local registry:2.
    """
    try:
        document = json.loads(text)
    except ValueError:
        return None
    manifests = document.get("manifests") if isinstance(document, dict) else None
    if not isinstance(manifests, list):
        return None
    found: dict[str, str] = {}
    for entry in manifests:
        platform = entry.get("platform") if isinstance(entry, dict) else None
        if not isinstance(platform, dict):
            continue
        parts = [str(platform.get(key) or "") for key in ("os", "architecture", "variant")]
        if "unknown" in parts[:2] or not all(parts[:2]):
            continue
        found["/".join(part for part in parts if part)] = str(entry.get("digest") or "")
    return found


def digest_mismatches(declared: Iterable[str], published: Mapping[str, str],
                      built: Mapping[str, str]) -> list[str]:
    """One line per declared platform whose published manifest is not the one the build loaded. Pure.

    A published `linux/arm64/v8` answers for a declared `linux/arm64`, as in `missing_platforms`.
    """
    lines = []
    for platform in declared:
        there = next((digest for found, digest in published.items()
                      if found == platform or found.startswith(platform + "/")), "")
        if there != built.get(platform, ""):
            lines.append(f"{platform}: the registry holds {there or 'nothing'}, the build loaded "
                         f"{built.get(platform) or 'nothing recorded'}")
    return lines


def _push_platforms(cfg: Image, name: str, root: Path, ref: str, derived: Mapping[str, str]) -> int:
    """`release` for an image with `platforms:`: push the manifest list out of the builder, then ask the
    registry for the INDEX and find every declared platform in it.

    The single-platform probe asks only whether a tag resolves, and for a manifest list that is the wrong
    question: an index that lost a platform still resolves. So this fetches the index itself - with oras,
    for the reasons the module head gives - and reads which platforms it carries.
    """
    ready, unrunnable = prepare_builder(cfg.platforms)
    if not ready:
        return 1
    path = write_bake(bake_definition(cfg, name, ref, derived, root), name)
    if path is None:
        return 1
    log.info(f"pushing {ref} for {', '.join(cfg.platforms)}")
    rc = stream(["docker", "buildx", "bake", "--builder", BUILDER, "--file", str(path), name], cwd=str(root))
    if rc != 0:
        advice = ("\nif the registry refused it rather than the network, the usual cause on GHCR is a "
                  "token without the package scopes:\n" + githubpackages.scope_advice()
                  if githubpackages.is_github_packages(cfg.registry) else "")
        log.error(f"docker buildx bake {name} failed (rc={rc}; see output above)" + advice
                  + _emulation_advice(unrunnable))
        return rc
    try:
        githubpackages.require_oras()
        fetched = run(["oras", "manifest", "fetch", ref])
    except githubpackages.PackageError as failure:
        log.error(f"{ref} was pushed, but the publish could not be verified: {failure}")
        return 1
    if not fetched.ok:
        log.error(f"docker buildx bake exited 0 but {ref} could not be read back: either the tag was not "
                  f"stored or the registry could not be asked - both mean the publish is unproven")
        return 1
    manifests = index_manifests(fetched.out)
    if manifests is None:
        log.error(f"{ref} is in the registry but is not a manifest list, so it carries one platform at "
                  f"most and {', '.join(cfg.platforms)} were declared")
        return 1
    found = set(manifests)
    missing = missing_platforms(cfg.platforms, found)
    if missing:
        log.error(f"{ref} is in the registry without {', '.join(missing)}: its index carries "
                  f"{', '.join(sorted(found)) or 'no platform at all'}, and "
                  f"{', '.join(cfg.platforms)} were declared")
        return 1
    # WHAT WAS PUSHED IS WHAT WAS SMOKED, checked rather than assumed (fix round 1). The push re-runs bake,
    # and while the builder's cache holds the build that is an export of the very images `build:image`
    # loaded and `test:image` ran. If the cache was pruned in between, the push BUILT AGAIN - for firn a
    # second native-image compile - and published bytes nothing ever ran. The manifest digest names the
    # config and every layer, so it is the stricter equality of the two a registry can be asked about.
    mismatched = digest_mismatches(cfg.platforms, manifests, read_built(name, ref))
    if mismatched:
        log.error(f"{ref} is published, but not as built: the push rebuilt what the builder's cache no "
                  f"longer held, so the registry now serves images `test:image` never ran.\n  "
                  + "\n  ".join(mismatched)
                  + "\n  run `build image` (without `platform:`) and the smoke checks again, then release "
                    "again - the same tag is overwritten with the images that were checked")
        return 1
    log.ok(f"published {ref} for {', '.join(cfg.platforms)}, each found in the registry's index as the "
           f"image the build loaded")
    return 0
