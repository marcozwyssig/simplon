"""Build a product's documentation WEBSITE with Hugo (#2).

WHY THIS IS THE KERNEL'S, and why it does not replace `simplon.tasks.docs`. Both render documentation,
and they are not two candidates for one job: `docs:render` produces a product's ARCHITECTURE
documentation (AsciiDoc through docToolchain, HTML *and* PDF, for the people working ON the system),
while this produces its product WEBSITE (Markdown through Hugo, HTML only, for the people working WITH
it). A product may want both, and netctl - which has the first today - would get the second BESIDE it,
not instead of it.

The mechanics are the same kind of product-free that made the docToolchain render the kernel's: invoking
hugo, fetching a theme module, wiping the destination and checking that a page came out needs no product
knowledge at all. What is the product's is the DATA - where the sources live, where the output goes,
which theme, which base URL - and all four flow in through the manifest's `site:` section. A kernel
default for any of them would be simplon's own directory layout imposed on every other product, which is
exactly what a catalogue task must not do: it is a promise to three products, not a convenience for one.

THE THEME IS PRODUCT DATA, INCLUDING THE FACT THAT IT IS A MODULE. Declared, it names a Hugo module and
must carry its version, because `hugo mod get` without one fetches whatever is newest and the look of a
published page would then be set by a release nobody chose (the reasoning `docs.py` already applies to
the docToolchain image tag). Declared, it also means this build needs GO on the PATH - `hugo mod` shells
out to the go toolchain - and a host missing Go is reported as missing GO, not as missing hugo. Two
causes under one message is half a message: it would send a reader to install the tool that is already
there. A product whose theme lives in its own repo declares none, and then needs no Go at all.

A MISSING TOOL IS NOT A FAILED TOOL (the rule 0.1.7 learned in `simplon.allure`). No hugo on the host is
a hint and rc 0 - not every machine that runs the loop is the one that publishes the site, and a tool
that was never there cannot be the reason a run goes red. A hugo that IS there and produces no site is
the other case, and it is loud: `log.error` on stderr and a non-zero rc. That includes the quiet variant,
which is the one that bit us before: hugo exits 0 on an empty content tree or a `contentDir` pointing at
nothing, leaving a destination with no home page. `allure.render_report` reported exactly that shape of
nothing as success for two releases, so the destination is wiped before the build (a stale `index.html`
would make an empty build look like a good one) and the home page is checked for afterwards.
"""
from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from simplon import context, log
from simplon.run import run

#: The manifest section this module owns. A section rather than flat keys: it is four related values, and
#: a product that declares no website declares no section at all.
SECTION = "site"

#: The one file whose absence means "no site". Hugo's home page, at the publish root - the file a static
#: host serves for the site's own URL, so a destination without it is not a website whatever else is in it.
INDEX = "index.html"


@dataclass(frozen=True)
class Site:
    """The website data a product's manifest declares: where the Hugo project lives and where its HTML
    goes (both relative to the product root), plus the optional theme module and base URL."""

    source: str
    output: str
    base_url: str = ""
    theme: str = ""


@dataclass(frozen=True)
class Build:
    """What one build attempt produced, so a caller can tell the TWO no-site cases apart (the #6 / 0.1.7
    distinction, in the shape `allure.Render` already uses).

    ``tool`` is set when the toolchain was there to do the work; ``missing`` names the tool that was not,
    in which case nothing was attempted. Hence ``failed``: hugo was present and no site came out - the
    case that must be visible - as against a host with no hugo at all, which stays a hint.
    """

    index: Path | None = None
    tool: str | None = None
    missing: str | None = None

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


def declared(data: Mapping[str, object], source: str = "manifest") -> Site:
    """The website the manifest declares, validated LOUDLY.

    Every value is required to BE declared rather than defaulted, because each one is a statement about a
    product's own tree: a kernel that assumed `site/` and `public/` would work for the product that
    happens to use those names and silently build the wrong thing - or nothing - for the next one. A
    missing section fails here, naming the key, rather than as a hugo run against a path that is not there.
    """
    section = data.get(SECTION)
    if not isinstance(section, Mapping):
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping "
                         f"- declare where the Hugo sources live and where the site is built to")
    where = f"{source}: '{SECTION}'"
    theme = _str(section, "theme", where)
    if theme and "@" not in theme:
        # An unpinned module fetches whatever is newest at build time, so the published page's look would
        # change under a release nobody in this repo chose - the same reason docs.py refuses an unpinned
        # docToolchain tag.
        raise ValueError(f"{where}: 'theme' must pin a version ('<module>@<version>', e.g. "
                         f"'{theme}@v0.9.6') - an unpinned module fetches whatever is newest")
    return Site(source=_str(section, "source", where, required=True),
                output=_str(section, "output", where, required=True),
                base_url=_str(section, "base_url", where),
                theme=theme)


def config() -> Site:
    """The registered product's website data."""
    ctx = context.current()
    return declared(ctx.manifest_data(), source=str(ctx.manifest_path))


def build_site(cfg: Site, root: Path) -> Build:
    """Build the declared Hugo site under `root` and say what came of it. Never raises: the caller decides
    how red a build that did not happen gets, which is the whole point of the missing/failed split."""
    source, out = root / cfg.source, root / cfg.output
    if shutil.which("hugo") is None:
        log.warn(f"hugo is not on PATH, so the site under {cfg.source}/ was not built. "
                 f"install hugo extended (https://gohugo.io/installation/) to build it here; "
                 f"this is a hint, not a failure")
        return Build(missing="hugo")
    if cfg.theme and shutil.which("go") is None:
        # Explicitly NOT "hugo is missing": hugo is installed, and saying otherwise sends the reader to
        # reinstall the tool that already works.
        log.warn(f"hugo IS installed, but go is not on PATH, so the site under {cfg.source}/ was not "
                 f"built. the theme '{cfg.theme}' is a Hugo MODULE and `hugo mod` shells out to the go "
                 f"toolchain; install go (https://go.dev/dl/) to build it here; this is a hint, not a "
                 f"failure")
        return Build(missing="go")

    if cfg.theme:
        log.info(f"fetching the pinned theme module {cfg.theme}")
        if not run(["hugo", "mod", "get", cfg.theme], capture=False, cwd=str(source)).ok:
            log.error(f"`hugo mod get {cfg.theme}` failed; the theme is not available, so no site was "
                      f"built (see output above)")
            return Build(tool="hugo")

    # Wipe first: a previous run's index.html left in place would let an empty build report a site that
    # this build did not produce - the same false green the output check below exists to prevent.
    shutil.rmtree(out, ignore_errors=True)
    argv = ["hugo", "--source", str(source), "--destination", str(out)]
    if cfg.base_url:
        # Only when declared. An empty --baseURL would override the site's own configuration with nothing.
        argv += ["--baseURL", cfg.base_url]
    log.info(f"building the site with hugo: {cfg.source}/ -> {cfg.output}/")
    if not run(argv, capture=False).ok:
        log.error(f"hugo failed; no site was built to {cfg.output}/ (see output above)")
        return Build(tool="hugo")
    index = out / INDEX
    if not index.is_file():
        log.error(f"hugo exited 0 but wrote no {cfg.output}/{INDEX}; no site was built. check the site's "
                  f"contentDir and that {cfg.source}/ holds content - a build that produces nothing is "
                  f"not a green build")
        return Build(tool="hugo")
    return Build(index=index, tool="hugo")


def build() -> int:
    """Build the product's documentation website with Hugo, into the destination its manifest declares.

    Green when the site was built AND on a host that has no hugo (or, for a module theme, no Go) at all:
    a tool that was never installed is a hint, because the machine that runs the loop is not always the
    one that publishes the page. Red only when the toolchain WAS there and produced no site - including a
    hugo that exits 0 and leaves a destination with no home page, which is the failure shape that stayed
    invisible for two releases the last time a step reported success for nothing.
    """
    cfg = config()
    built = build_site(cfg, context.current().root)
    if built.failed:
        return 1
    if built.ok:
        log.ok(f"site built -> {cfg.output}/")
    return 0
