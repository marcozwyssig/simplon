"""Build a product's documentation WEBSITE with Hugo, in Docker (#2).

WHY THIS IS THE KERNEL'S, and why it does not replace `simplon.tasks.docs`. Both render documentation,
and they are not two candidates for one job: `docs:render` produces a product's ARCHITECTURE
documentation (AsciiDoc through docToolchain, HTML *and* PDF, for the people working ON the system),
while this produces its product WEBSITE (Markdown through Hugo, HTML only, for the people working WITH
it). A product may want both, and netctl - which has the first today - would get the second BESIDE it,
not instead of it.

The mechanics are the same kind of product-free that made the docToolchain render the kernel's: invoking
the tool, wiping the destination and checking that a page came out needs no product knowledge at all.
What is the product's is the DATA - the image, where the sources live, where the output goes, which theme,
which base URL - and all of it flows in through the manifest's `site:` section. A kernel default for any
of them would be simplon's own directory layout imposed on every other product, which is exactly what a
catalogue task must not do: it is a promise to three products, not a convenience for one.

IN DOCKER, for the reason `docs.py` states for docToolchain (netctl#1280's rule): bring the tool rather
than provision the development machine. It also collapses the tool question. A Hextra-style theme is a
Hugo MODULE, and building one needs Hugo Extended, Go AND Git together - locally three installations with
three separate failure pictures, in an image none. "Which of the three is missing?" becomes "is docker
there?". The image is the product's to choose and must carry all three; what the kernel insists on is only
that the choice is PINNED.

`--user uid:gid` IS NOT CAUTION, IT IS A MEASUREMENT. The container writes into the bind-mounted product
root, so the uid the image runs as is the uid that ends up owning the output. `simplon.docker.user_args`
holds the rule and both measured failures; the one that applies here is the root direction: measured with
`hugomods/hugo` (default user uid 0), a run without `--user` wrote `index.html` as `0:0`, the caller's
`rm -rf` of its own build directory came back `Permission denied`, and the SOURCE tree kept a root-owned
`.hugo_build.lock` - enough that the next run failed with `failed to acquire a build lock` even when that
one passed `--user` correctly. It is the same defect #6 found from the other side, and it must not repeat.

A MISSING TOOL IS NOT A FAILED TOOL (the rule 0.1.7 learned in `simplon.allure`). No docker on the host is
a hint and rc 0 - not every machine that runs the loop is the one that publishes the site, and a tool that
was never there cannot be the reason a run goes red. This is why the module does NOT call
`docker.ensure_docker()`, which DIES: that gate is right for a step whose output is the point, and wrong
here. A docker that IS there and produces no site is the other case, and it is loud: `log.error` on stderr
and a non-zero rc. That includes the quiet variant, which is the one that bit us before: hugo exits 0 on an
empty content tree or a `contentDir` pointing at nothing, leaving a destination with no home page.
`allure.render_report` reported exactly that shape of nothing as success for two releases, so the
destination is wiped before the build (a stale `index.html` would make an empty build look like a good one)
and the home page is checked for afterwards.
"""
from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from simplon import context, docker, log
from simplon.bootstrap import validate_relative_dir
from simplon.run import run

#: The manifest section this module owns. A section rather than flat keys: it is five related values, and
#: a product that declares no website declares no section at all.
SECTION = "site"

#: Where the product root is bind-mounted inside the container. The kernel's own choice, like docs.py's
#: `/project`: it is a path INSIDE a container the kernel creates, so no product ever sees it.
MOUNT = PurePosixPath("/project")

#: The one file whose absence means "no site". Hugo's home page, at the publish root - the file a static
#: host serves for the site's own URL, so a destination without it is not a website whatever else is in it.
INDEX = "index.html"


@dataclass(frozen=True)
class Site:
    """The website data a product's manifest declares: the pinned Hugo image, where the Hugo project lives
    and where its HTML goes (both relative to the product root), plus the optional theme module and base
    URL."""

    image: str
    source: str
    output: str
    base_url: str = ""
    theme: str = ""


@dataclass(frozen=True)
class Build:
    """What one build attempt produced, so a caller can tell the TWO no-site cases apart (the #6 / 0.1.7
    distinction, in the shape `allure.Render` already uses).

    ``tool`` is the toolchain that was actually there (``"docker"``, or None on a host without it);
    ``index`` is the home page when one was written. Hence ``failed``: docker was there and no site came
    out - the case that must be visible - as against a host with no docker at all, which stays a hint.
    There is deliberately no third field naming WHICH tool was missing: in a container there is only one
    to miss, which is the whole point of building this way.
    """

    index: Path | None = None
    tool: str | None = None

    @property
    def ok(self) -> bool:
        """A site was built."""
        return self.index is not None

    @property
    def failed(self) -> bool:
        """The toolchain WAS available and produced no site."""
        return self.tool is not None and self.index is None


def _str(body: Mapping, key: str, where: str, *, required: bool = False) -> str:
    value = body.get(key)
    if value is None:
        if required:
            raise ValueError(f"{where}: '{key}' is required")
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


#: A docker tag: what may follow the ':' in an image reference. Used to reject the EMPTY tag ('hugo:',
#: 'hugo::'), which reads as pinned to a careless eye and is not.
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}\Z")
#: A content digest ('sha256:<hex>'): the strongest pin there is.
_DIGEST_RE = re.compile(r"[A-Za-z0-9]+(?:[.+_-][A-Za-z0-9]+)*:[A-Fa-f0-9]{32,}\Z")
#: A Go module version: a version TAG ('v0.9.6', 'v1.2.3-rc.1') or a commit. Anything else that `hugo mod
#: get` accepts - 'latest', 'upgrade', a branch name - is a query that resolves differently tomorrow.
_MODULE_VERSION_RE = re.compile(r"v\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}\Z")


def _pinned_image(image: str, where: str) -> str:
    """Refuse an image reference that does not name a version. A build that renders something different
    depending on when it ran is not a build, and a documentation site is committed-to prose: a generator
    change rewrites it wholesale. The same refusal `docs.py` makes for the docToolchain tag.

    The registry is split off by docker's OWN rule, which needs BOTH halves: a first component is a host
    when it carries a '.' or a ':' AND a '/' follows it, or when it is 'localhost'. That is what keeps a
    private registry with a port (`registry.example:5000/hugo:0.148.2`) from being read as a tagged image
    - and, just as important, what keeps `my.image:1.0` from being read as a registry. Without a slash
    there is no registry, dot or no dot; docker reads such a reference as an image with a tag, and so does
    this. `registry.example:5000` alone therefore passes as image `registry.example` tag `5000`, which is
    what docker itself would do with it: nothing here can tell that port from a version without guessing,
    and guessing costs valid references.
    """
    hint = ("pin it as '<image>:<tag>' (e.g. 'hugomods/hugo:exts-0.148.2'), or by digest")
    name, at, digest = image.partition("@")
    if at:
        if not name or not _DIGEST_RE.match(digest):
            raise ValueError(f"{where}: 'image' carries a broken digest in '{image}'; {hint}")
        return image
    parts = image.split("/")
    # A registry needs a '/' after it - `len(parts) > 1` IS that condition, and it is the half that stops
    # `my.image:1.0` from being mistaken for a host.
    registry = len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost")
    remainder = "/".join(parts[1:]) if registry else image
    repo, colon, tag = remainder.rpartition(":")
    if not colon:
        raise ValueError(f"{where}: 'image' must pin a version ('<image>:<tag>'), got '{image}' "
                         f"- an untagged image means ':latest', which moves under the build; {hint}")
    if not repo or not _TAG_RE.match(tag):
        raise ValueError(f"{where}: 'image' has no usable tag in '{image}'; {hint}")
    if tag == "latest":
        raise ValueError(f"{where}: 'image' must pin a version, not the moving tag 'latest' "
                         f"(got '{image}') - a build whose output depends on when it ran is not a build")
    return image


def _pinned_theme(theme: str, where: str) -> str:
    """Refuse a theme module reference that does not name a version - the SAME rule as the image pin, and
    it has to be the same rule rather than merely claim to be one. Checking only for an '@' lets
    `@latest`, `@master` and even `@` through, and `hugo mod get <module>@latest` fetches exactly the
    moving thing the pin exists to exclude: the look of a published page would be set by a release nobody
    in this repo chose.

    What passes is a version TAG (`v0.9.6`, `v1.2.3-rc.1`) or a commit - the two forms that name one
    revision for good.
    """
    hint = ("pin it as '<module>@<version>', e.g. 'github.com/imfing/hextra@v0.9.6' - a version tag or a "
            "commit, never a moving query like 'latest', 'upgrade' or a branch name")
    module, at, version = theme.partition("@")
    if not at:
        raise ValueError(f"{where}: 'theme' must pin a version ('<module>@<version>'), got '{theme}' "
                         f"- an unpinned module fetches whatever is newest; {hint}")
    if not module:
        raise ValueError(f"{where}: 'theme' names no module before the '@' in '{theme}'; {hint}")
    if not version:
        raise ValueError(f"{where}: 'theme' pins an empty version in '{theme}'; {hint}")
    if not (_MODULE_VERSION_RE.match(version) or _COMMIT_RE.match(version)):
        raise ValueError(f"{where}: 'theme' pins '{version}', which is a query rather than a version: "
                         f"`hugo mod get {theme}` fetches whatever that names on the day it runs; {hint}")
    return theme


def _inside_the_product(value: str, key: str, where: str) -> str:
    """A manifest path that must stay UNDER the product root, normalised.

    Not pedantry about tidy manifests: `root / value` collapses onto `value` the moment it is absolute, and
    `output` is then handed to `shutil.rmtree`. `output: /var/tmp/x` would delete `/var/tmp/x`, and `..`
    escapes just as far; an absolute `source` would simply point outside the mount. The rule is
    `bootstrap.validate_relative_dir`, the one `--orch-dir` already uses (#4) - the same escape, so the
    same check, in one place.
    """
    return validate_relative_dir(
        value, f"{where}: '{key}'",
        f"give a plain relative path under the product root, e.g. 'website' or 'build/website'",
        inside="the product root")


def declared(data: Mapping[str, object], source: str = "manifest") -> Site:
    """The website the manifest declares, validated LOUDLY.

    Every value is required to BE declared rather than defaulted, because each one is a statement about a
    product's own tree or its own toolchain: a kernel that assumed `site/` and `public/` would work for the
    product that happens to use those names and silently build the wrong thing - or nothing - for the next
    one, and a kernel that named the image would be choosing a generator on every product's behalf. A
    missing section fails here, naming the key, rather than as a container run against a path that is not
    there.
    """
    section = data.get(SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping "
                         f"- declare the pinned hugo image, where the sources live and where the site "
                         f"is built to")
    where = f"{source}: '{SECTION}'"
    # The REQUIRED keys first, then their shape: a section missing `image` altogether should say so, not
    # complain about the optional theme it also got wrong.
    image = _str(section, "image", where, required=True)
    src = _str(section, "source", where, required=True)
    out = _str(section, "output", where, required=True)
    theme = _str(section, "theme", where)
    return Site(image=_pinned_image(image, where),
                source=_inside_the_product(src, "source", where),
                output=_inside_the_product(out, "output", where),
                base_url=_str(section, "base_url", where),
                theme=_pinned_theme(theme, where) if theme else "")


def _hugo(cfg: Site, root: Path, argv: list[str]) -> bool:
    """Run one hugo command in the pinned image, from the site's own directory, and say whether it
    succeeded.

    `--entrypoint hugo` rather than the image's default: what the image does when handed no entrypoint is
    the image's business, and this way the same declaration works for one that starts a shell and one that
    starts hugo. No `--platform`: docs.py pins amd64 because ITS image publishes no arm64 variant, which is
    a fact about that image, not about containers - deciding it here would take the choice away from the
    product that picked the image.
    """
    return run(["docker", "run", "--rm", *docker.user_args(),
                "-v", f"{root}:{MOUNT}", "-w", str(MOUNT / cfg.source),
                "--entrypoint", "hugo", cfg.image, *argv], capture=False).ok


def _wipe(out: Path, cfg: Site) -> bool:
    """Clear the destination before the build, and say whether it is actually gone.

    A previous run's index.html left in place lets an empty build report a site that this build did not
    produce - the false green the output check exists to prevent, and the check cannot catch it, because
    the file it looks for is right there. So the wipe is NOT best-effort: `ignore_errors=True` would leave
    the tree standing and say nothing, which is the 0.1.7 defect wearing the costume of the fix for it.

    A failure here is a real one and gets the failed verdict. The way it happens is measured, not
    imagined: a container that ran without `--user` CREATES the output directories itself, root-owned and
    0755, and unlinking an entry needs write permission on the DIRECTORY that holds it - which the caller
    does not have. It is not about who owns the files.
    """
    try:
        shutil.rmtree(out)
    except FileNotFoundError:
        pass                                  # nothing to clear is the normal first-build case
    except OSError as exc:
        log.error(f"cannot clear {cfg.output}/ before the build ({exc}); no site was built rather than a "
                  f"stale one reported as fresh. a run whose container wrote as root leaves these "
                  f"directories root-owned, and deleting inside them needs write permission on THEM")
        return False
    return True


def build_site(cfg: Site, root: Path) -> Build:
    """Build the declared Hugo site under `root` and say what came of it. Never raises: the caller decides
    how red a build that did not happen gets, which is the whole point of the missing/failed split."""
    if shutil.which("docker") is None:
        log.warn(f"docker is not on PATH, so the site under {cfg.source}/ was not built. the build runs "
                 f"in {cfg.image}, which brings hugo, go and git with it - install docker to build the "
                 f"site here; this is a hint, not a failure")
        return Build()

    if cfg.theme:
        # The manifest is the single place the theme version is declared, and `hugo mod get` with a pin
        # writes exactly that into go.mod - idempotent, so a build never silently upgrades the theme.
        log.info(f"fetching the pinned theme module {cfg.theme}")
        if not _hugo(cfg, root, ["mod", "get", cfg.theme]):
            log.error(f"`hugo mod get {cfg.theme}` failed; the theme is not available, so no site was "
                      f"built (see output above)")
            return Build(tool="docker")

    out = root / cfg.output
    if not _wipe(out, cfg):
        return Build(tool="docker")
    argv = ["--destination", str(MOUNT / cfg.output)]
    if cfg.base_url:
        # Only when declared. An empty --baseURL would override the site's own configuration with nothing.
        argv += ["--baseURL", cfg.base_url]
    log.info(f"building the site with hugo in {cfg.image}: {cfg.source}/ -> {cfg.output}/")
    if not _hugo(cfg, root, argv):
        log.error(f"hugo failed in {cfg.image}; no site was built to {cfg.output}/ (see output above). "
                  f"if it could not take its build lock, an earlier run without --user left a root-owned "
                  f"{cfg.source}/.hugo_build.lock behind, and removing that one file takes a root shell")
        return Build(tool="docker")
    index = out / INDEX
    if not index.is_file():
        log.error(f"hugo exited 0 but wrote no {cfg.output}/{INDEX}; no site was built. check the site's "
                  f"contentDir and that {cfg.source}/ holds content - a build that produces nothing is "
                  f"not a green build")
        return Build(tool="docker")
    return Build(index=index, tool="docker")


def build() -> int:
    """Build the product's documentation website with Hugo, in the pinned image its manifest names, into
    the destination its manifest declares.

    Green when the site was built AND on a host with no docker at all: a tool that was never installed is a
    hint, because the machine that runs the loop is not always the one that publishes the page. Red only
    when docker WAS there and produced no site - including a hugo that exits 0 and leaves a destination with
    no home page, which is the failure shape that stayed invisible for two releases the last time a step
    reported success for nothing.
    """
    ctx = context.current()
    cfg = declared(ctx.manifest_data(), source=str(ctx.manifest_path))
    built = build_site(cfg, ctx.root)
    if built.failed:
        return 1
    if built.ok:
        log.ok(f"site built -> {cfg.output}/")
    return 0
