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

The registry, not the daemon: `docker image inspect` would answer yes for the image that never left the
machine, which is the failure being guarded against. Two commands can ask a remote, and the choice
between them was measured against a local `registry:2`:

  - `docker buildx imagetools inspect <ref>` - rc 0 with the digest when the tag is there, rc 1 with
    "not found" when it is not, over plain HTTP and over HTTPS alike. Preferred;
  - `docker manifest inspect <ref>` - the fallback, because buildx is a PLUGIN and the static CLI that
    `simplon.docker` can bootstrap onto a bare runner does not carry it. It is still marked experimental,
    and against a plain-HTTP registry it reports `no such manifest` for a tag that IS there unless
    `--insecure` is passed - the same words it uses for genuine absence, so it cannot be the first choice.

A probe that fails goes RED without trying to tell "the tag is not there" apart from "the registry could
not be asked", and the message names both readings. Parsing the client's wording to separate them would
be reading formatted text for a decision (the mistake `tasks/cliref.py` is written to avoid), and the two
readings do not differ in what they mean here anyway: an unverified push is not a publish.
"""
from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from simplon import context, docker, githubpackages, log
from simplon.bootstrap import validate_relative_dir
from simplon.run import run, stream

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


def declared(data: Mapping[str, object], name: str, source: str = "manifest") -> Image:
    """The image `name` declares, validated LOUDLY.

    The four required keys are required to BE declared rather than defaulted, for the reason every
    catalogue task states: each is a statement about a product's own tree or its own publishing target,
    and a kernel that assumed `Dockerfile` at the root would build the wrong thing - or nothing - for the
    next product. `registry` is required even for a purely local build, deliberately: the reference a
    build tags is the reference a release pushes, and an unqualified one is what docker resolves against
    Docker Hub (`simplon.images.require_registry` records that failure in full). Building under one name
    and publishing under another is how an image gets pushed somewhere nobody meant.
    """
    section = data.get(SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping - declare "
                         f"the registry, the repository, the Dockerfile and the build context of every "
                         f"image this product builds")
    if name not in section:
        raise ValueError(f"{source}: no image '{name}' in the '{SECTION}:' section; declared are: "
                         f"{', '.join(sorted(str(key) for key in section)) or '(none)'}")
    body = section[name]
    if not isinstance(body, Mapping):
        raise ValueError(f"{source}: image '{name}' is not a mapping")
    where = f"{source}: '{SECTION}.{name}'"
    return Image(
        registry=_str(body, "registry", where, required=True),
        repository=_str(body, "repository", where, required=True),
        dockerfile=_inside_the_product(_str(body, "dockerfile", where, required=True),
                                       "dockerfile", where),
        context=_inside_the_product(_str(body, "context", where, required=True), "context", where),
        build_args=_build_args(body, where),
        tag=_str(body, "tag", where),
    )


def _declared_for(name: str) -> tuple[Image, Path]:
    """The declared image and the product root, or a ValueError that says which pin is missing."""
    if not name:
        raise ValueError(f"which image? pin one with `with: {{ name: ... }}` from the `{SECTION}:` "
                         f"section, or pass --name")
    ctx = context.current()
    return declared(ctx.manifest_data(), name, source=str(ctx.manifest_path)), ctx.root


def resolve_tag(cfg: Image, tag: str) -> str:
    """The tag to build and publish under: the argument, else the section's own `tag:`.

    Both sides, for the reason `release:artifact` gives and then reuses here: most products know their
    tag as a constant and should not retype it on every call, while some only learn it after a build and
    could not have declared one. A task that supported only the manifest would exclude the second kind.
    """
    resolved = tag or cfg.tag
    if not resolved:
        raise ValueError(
            f"no tag: declare `tag:` in the `{SECTION}:` section for a constant one, or pass --tag for a "
            f"version that is only known after a build")
    return resolved


def provenance(root: Path) -> dict[str, str]:
    """VERSION and REVISION derived from the PRODUCT's git checkout, or an empty mapping with a warning
    when there is no checkout to ask.

    Empty rather than a placeholder: see the module head. Both values come from one repository - `git -C
    <root>` - so a kernel installed from PyPI describes the product it is building and never itself.
    """
    if shutil.which("git") is None:
        log.warn("git is not on PATH, so the image is built without VERSION/REVISION build arguments; "
                 "the Dockerfile's own ARG defaults apply")
        return {}
    described = run(["git", "-C", str(root), "describe", "--tags", "--always", "--dirty"])
    revision = run(["git", "-C", str(root), "rev-parse", "HEAD"])
    if not (described.ok and revision.ok):
        log.warn(f"{root} is not a git checkout with a commit, so the image is built without "
                 f"VERSION/REVISION build arguments; the Dockerfile's own ARG defaults apply")
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


def build_image(cfg: Image, tag: str, root: Path) -> int:
    """Build the declared image under `root` and return docker's real rc.

    `--file` and the context are joined onto the product root rather than passed as the manifest wrote
    them, so the command means the same thing whatever directory the CLI was invoked from.
    """
    ref = reference(cfg, tag)
    args = build_arguments(cfg, root)
    argv = ["docker", "build", "--file", str(root / cfg.dockerfile), "--tag", ref]
    for key in sorted(args):
        argv += ["--build-arg", f"{key}={args[key]}"]
    argv.append(str(root / cfg.context) if cfg.context != "." else str(root))
    log.info(f"building {ref} from {cfg.dockerfile} "
             f"({', '.join(f'{k}={args[k]}' for k in sorted(args)) or 'no build arguments'})")
    return stream(argv, cwd=str(root))


def published(ref: str) -> bool:
    """Whether the REGISTRY serves `ref` - the read-back that makes a push a publish.

    Which client asks is decided here rather than configured, and the reasoning (buildx first, `docker
    manifest inspect` as the fallback for a host that has only the plain client) is in the module head
    together with the measurements behind it.
    """
    if run(["docker", "buildx", "version"]).ok:
        return run(["docker", "buildx", "imagetools", "inspect", ref]).ok
    return run(["docker", "manifest", "inspect", ref]).ok


def present_locally(ref: str) -> bool:
    """Whether the local daemon already holds `ref`. Asked before a push so that "you have not built it
    yet" is answered as itself, rather than as docker's `An image does not exist locally`."""
    return run(["docker", "image", "inspect", ref]).ok


def build(name: str = "", tag: str = "") -> int:
    """Build the container image `name` declares, tagged with the reference it will be published under.

    `name` is normally pinned per command with `with: { name: ... }`, the shape `test:gate` and
    `release:artifact` both use - a product with two images declares two commands rather than making the
    caller remember a string.
    """
    docker.ensure_docker()
    cfg, root = _declared_for(name)
    resolved = resolve_tag(cfg, tag)
    dockerfile = root / cfg.dockerfile
    if not dockerfile.is_file():
        log.error(f"no Dockerfile at {cfg.dockerfile}: the image '{name}' declares it, and nothing under "
                  f"the product root answers to that path")
        return 1
    rc = build_image(cfg, resolved, root)
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
    log.ok(f"built {ref}")
    return 0


def release(name: str = "", tag: str = "") -> int:
    """Publish the container image `name` declares: log in, push, and CHECK THE REGISTRY HAS IT.

    Builds nothing. `build` and `release` are two of the five verbs and stay two commands, so a product
    that builds an image for a smoke test never accidentally publishes it; a product that wants both in
    one step declares an aggregate over them, which is where an ordering belongs.
    """
    docker.ensure_docker()
    cfg, root = _declared_for(name)
    resolved = resolve_tag(cfg, tag)
    ref = reference(cfg, resolved)

    if not present_locally(ref):
        log.error(f"{ref} is not on this machine, so there is nothing to push - run the build first "
                  f"(`build:image`, with the same --tag)")
        return 1

    try:
        githubpackages.docker_login(cfg.registry)
    except githubpackages.PackageError as failure:
        # Caught rather than allowed to propagate: this message is the fix (it names `gh auth refresh`
        # and the two scopes), and a traceback would bury it under a stack from a wrapper the reader did
        # not write. Acceptance 4's second half - a missing scope names the command that sets it.
        log.error(str(failure))
        return 1

    log.info(f"pushing {ref}")
    rc = stream(["docker", "push", ref], cwd=str(root))
    if rc != 0:
        log.error(f"docker push {ref} failed (rc={rc}; see output above)\n"
                  + githubpackages.scope_advice())
        return rc

    if not published(ref):
        log.error(f"docker push exited 0 but {ref} is not in the registry. either the tag was not "
                  f"stored or the registry could not be asked - both mean the publish is unproven, and "
                  f"an unproven publish is what this check exists to stop being reported as done")
        return 1
    log.ok(f"published {ref}")
    return 0
