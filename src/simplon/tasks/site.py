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

A MISSING TOOL IS NOT A FAILED TOOL (the rule 0.1.7 learned in `simplon.tasks.allure`). No docker on the host is
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
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from simplon import context, docker, log
from simplon.bootstrap import validate_relative_dir
from simplon.run import run

#: The manifest section this module owns. A section rather than flat keys: it is five related values, and
#: a product that declares no website declares no section at all.
SECTION = "site"

#: Where a product's Hugo sources are, when its manifest does not say (si#183). `docs/` is the
#: documentation root - architecture, specs, plans and the site all belong in it, so one repository stops
#: answering "where is the documentation" in two places - and this is the leaf simplon itself uses.
#:
#: A DEFAULT AND NOT A RULE, and the difference was measured rather than preferred. si#155 gave this key
#: no default at all, on the reasoning that one product's layout must not be imposed on the next. That
#: reasoning still holds for a REFUSAL and the census says so. Measured over the same population si#159
#: and si#172 used - every manifest this kernel can reach: its own, the five in
#: `simplon.surface.CONSUMERS`, and secure-windows-images - three of those seven declare a `site:`
#: section, and the three disagree: cleon at `site`, biz-cockpit at `docs/website`, simplon at
#: `docs/site`. A `source:` outside `docs/` refused would turn away two products that have done nothing
#: wrong, which is the expression rule si#53, si#85 and si#159 each declined to write.
#:
#: SO WHO IS IT FOR, since by that same count it serves none of the three? The FOURTH. All three existing
#: products name the key, so the default changes nothing for any of them and they keep whatever they
#: named. What it changes is the day a product gets a website: it writes four keys instead of five and
#: lands on the convention without having to have read about it. A default nobody currently reaches is
#: dead weight only if nobody arrives later, and products are the one thing this kernel exists to have
#: more of.
#:
#: `output` DELIBERATELY DOES NOT GET ONE, and the asymmetry is the point rather than an oversight. By
#: consumer agreement it has the better case - two of the three declare `build/website` and only cleon
#: differs, against one of three for `docs/site` - but `output` is handed to `shutil.rmtree` before every
#: build. A default there would recursively delete a directory the product never typed, on the first run
#: of a manifest whose author forgot a key. `source` is only ever read. The kernel may assume where to
#: LOOK; it may not assume what to DELETE.
DEFAULT_SOURCE = "docs/site"

#: Where the product root is bind-mounted inside the container. The kernel's own choice, like docs.py's
#: `/project`: it is a path INSIDE a container the kernel creates, so no product ever sees it.
MOUNT = PurePosixPath("/project")

#: Hugo's cache, kept on the HOST between runs (si#27) - the kernel's convention, like docs.py's
#: `build/docToolchain/` and `simplon.tools`' `build/tools/bin`, and covered by the same `build/` rule a
#: product's `clean` and `.gitignore` already carry.
#:
#: WHY IT EXISTS AT ALL. Every run is `docker run --rm` with nothing but the product root mounted, so
#: hugo's cache lived at `/tmp/hugo_cache` INSIDE the container and died with it. Two things therefore
#: went to the network on every single build, whether or not anything had changed:
#:
#:   * `hugo mod get <theme>@<version>`, which ends at `git ls-remote` when there is no network;
#:   * the BUILD ITSELF, which resolves the theme module again - and, with Hextra, fetches FlexSearch
#:     and mermaid through `resources.GetRemote` while rendering.
#:
#: MEASURED, on this repository's own site with the pinned image, `--network none` for the no-network
#: runs:
#:
#:   | run                                        | network | before | after |
#:   | `hugo mod get`, nothing cached             | yes     | 3.0 s  | 2.7 s |
#:   | `hugo mod get`, cache warm                 | yes     | 3.0 s  | 0.9 s |
#:   | `hugo mod get`, cache warm                 | NO      | rc 1   | rc 0  |
#:   | full build, module cached, nothing else    | NO      | rc 1   | rc 1  |
#:   | full build, cache warm from one net build  | NO      | rc 1   | rc 0, 26 pages |
#:
#: The fourth row is the one that decided the design. si#27 proposes making `hugo mod get` CONDITIONAL -
#: run it only when go.sum and the pin disagree - and calls that the likely answer. It is not sufficient:
#: with the fetch skipped entirely and no host cache, the build still died on `git ls-remote`, because
#: the module resolution the build does itself has nowhere to read from. And it would not have touched
#: the theme's remote JavaScript at all. A persistent cache fixes both; the condition fixes neither.
#:
#: SO THERE IS NO CONDITION, and that is the second half of the decision. With the cache warm the fetch
#: costs 0.9 s and needs no network, so a condition would buy under a second and cost exactly the defect
#: this repository hunts: a build that answers "are they the same?" wrongly and does NOT fetch a pin that
#: HAS moved renders against the old theme and says nothing. Without the condition that case is loud and
#: was measured too - with the cache warm for v0.12.3 and the pin moved to v0.11.1, `hugo mod get` under
#: `--network none` exits 1 naming the version it could not reach, and `build_site` returns the failed
#: verdict. "Nothing to do" and "did not look" stay different answers because nothing ever guesses.
CACHE_DIR = Path("build") / "hugo-cache"

#: The one file whose absence means "no site". Hugo's home page, at the publish root - the file a static
#: host serves for the site's own URL, so a destination without it is not a website whatever else is in it.
INDEX = "index.html"

#: The renderer the diagram gate checks with, PINNED by `docker.pinned_image` at import (si#47) - the
#: same demand this module makes of the hugo image a product declares.
#:
#: The KERNEL's choice rather than the manifest's, which is the opposite of the rule for the hugo image
#: one line up, and deliberately: the hugo image decides what the site LOOKS LIKE, so it is the
#: product's; this one only decides whether a diagram parses, and a product asked to declare a checker
#: it never invokes is a required manifest line bought with nothing. si#45 wanted a gate, not a new
#: section.
#:
#: 11.17.0 is what ':latest' resolved to when the pin was written (both tags,
#: sha256:a6fb0574dded4086888b5e38476899c9aff8963196f689f11a0f8fceee588ce1). WHAT THE PIN COSTS, stated
#: rather than hidden: this is a mermaid version, and the theme renders the page with a mermaid of its
#: own in the reader's browser. The two agreeing is the normal case and not a guarantee, so the gate is
#: a check that the source PARSES, not a promise that it draws identically in every browser.
MERMAID_IMAGE = docker.pinned_image("minlag/mermaid-cli:11.17.0", "simplon.tasks.site")

#: Where the diagram scratch is mounted inside the mermaid container. Its own mount rather than the
#: product root: a render must not be able to write into the tree it is checking.
MERMAID_MOUNT = PurePosixPath("/data")

#: Directories under a product's site source that belong to HUGO rather than to whoever writes the
#: pages: its asset cache, its default destination, a vendored module tree, npm's. Markdown found in
#: them is somebody else's, and a diagram somebody else shipped is not this build's to fail on.
_NOT_THE_AUTHORS = {"resources", "public", "_vendor", "node_modules", CACHE_DIR.name}


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

    ``diagrams`` and ``broken`` carry the render gate's verdict (si#45), and ``diagrams`` has THREE
    states on purpose, because a check that cannot tell them apart is the defect this repository keeps
    finding: None means the gate never ran (no docker, or the build failed before it), 0 means it ran
    and there was no diagram to rule on, and a number means it rendered that many. "Nothing to check" is
    therefore a thing the caller can SAY rather than something it infers from silence.
    """

    index: Path | None = None
    tool: str | None = None
    diagrams: int | None = None
    broken: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """A site was built, the diagram gate RAN, and every diagram in it renders.

        `diagrams is not None` is load-bearing rather than belt-and-braces: without it a Build carrying
        a home page and no verdict at all would be ok, and the caller would print one of the two greens
        over a gate that never ran. The ambiguous value is excluded at the seam instead of being read
        for its truthiness on the other side of it.
        """
        return self.index is not None and self.diagrams is not None and not self.broken

    @property
    def failed(self) -> bool:
        """The toolchain WAS available and produced no site worth publishing."""
        return self.tool is not None and not self.ok


def _str(body: Mapping, key: str, where: str, *, required: bool = False) -> str:
    value = body.get(key)
    if value is None:
        if required:
            raise ValueError(f"{where}: '{key}' is required")
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: '{key}' must be a non-empty string")
    return value.strip()


#: A Go module version: a version TAG ('v0.9.6', 'v1.2.3-rc.1') or a commit. Anything else that `hugo mod
#: get` accepts - 'latest', 'upgrade', a branch name - is a query that resolves differently tomorrow.
_MODULE_VERSION_RE = re.compile(r"v\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}\Z")


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

    `image` and `output` are required to BE declared rather than defaulted, because each one is a
    statement the kernel cannot make for a product: a kernel that named the image would be choosing a
    generator on every product's behalf, and one that guessed `output` would hand `shutil.rmtree` a
    directory nobody typed. A missing section fails here, naming the key, rather than as a container run
    against a path that is not there.

    `source` is the one that DOES default, to `DEFAULT_SOURCE`, and the block on that constant is where
    the reasoning and the census behind it live. A product that names a path still gets exactly what it
    named, and the default is normalised by the same `_inside_the_product` a declared path goes through
    rather than being exempted from it. `source: ""` is still a mistake rather than an omission, because
    `_str` rules on a value that is there; a bare `source:` carries no value at all and defaults, which
    is what `theme:` and `base_url:` have always done with one.
    """
    section, blame, _ = context.section(data, SECTION)
    if blame:
        raise ValueError(f"{source}: the '{SECTION}' section is missing or is not a mapping "
                         f"- declare the pinned hugo image and where the site is built to (the sources "
                         f"default to '{DEFAULT_SOURCE}')")
    where = f"{source}: '{SECTION}'"
    # The REQUIRED keys first, then their shape: a section missing `image` altogether should say so, not
    # complain about the optional theme it also got wrong.
    image = _str(section, "image", where, required=True)
    out = _str(section, "output", where, required=True)
    # Not `required=True`: a key that carries NO VALUE takes the convention, a key that carries a broken
    # one is ruled on. `_str` draws exactly that line and draws it the same way for every optional key in
    # this section, so `source: ""` and `source: 3` refuse while an omitted key and a bare `source:` (YAML
    # null, which `theme:` and `base_url:` have always read as "not declared") both default.
    src = _str(section, "source", where) or DEFAULT_SOURCE
    theme = _str(section, "theme", where)
    # The image pin is `simplon.docker.pinned_image` rather than a rule of this module's own (si#47):
    # `docs:render` holds its docToolchain tag to the SAME gate, and so do the images the kernel names
    # itself - which is what makes this refusal something the kernel keeps rather than only demands.
    return Site(image=docker.pinned_image(image, where),
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
    # The cache is created HERE rather than once in `build_site`, so it exists for every hugo run
    # whatever order they happen in - including after `_wipe`, which may sit between two of them and,
    # for a product whose `output:` is `build/` itself, takes the cache with it. That product then pays
    # a cold cache on every run, which is the behaviour it had before this existed; what it must not do
    # is hand hugo a HUGO_CACHEDIR that is not there.
    (root / CACHE_DIR).mkdir(parents=True, exist_ok=True)
    return run(["docker", "run", "--rm", *docker.user_args(),
                "-v", f"{root}:{MOUNT}", "-w", str(MOUNT / cfg.source),
                "-e", f"HUGO_CACHEDIR={MOUNT / CACHE_DIR}",
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


@dataclass(frozen=True)
class Diagram:
    """One mermaid block, with the page and the line a reader has to open to fix it. ``line`` is the
    fence's own line, 1-based - mermaid's parser reports a line INSIDE the block, so the two together
    name the character."""

    page: Path
    line: int
    body: str

    def where(self, root: Path) -> str:
        """`<page>:<line>`, relative to the product root, which is how an editor is told where to go."""
        try:
            page = self.page.relative_to(root)
        except ValueError:                     # a page outside the root cannot be named relative to it
            page = self.page
        return f"{page}:{self.line}"


#: A fenced block's opening: three or more backticks or tildes, then the info string. Both characters
#: and the LENGTH matter, because that is what decides which fence closes which block.
_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})\s*(?P<info>.*)$")


def diagrams_in(text: str, page: Path) -> list[Diagram]:
    """The mermaid blocks in one Markdown page.

    EVERY fenced block is walked, not only the mermaid ones, and that is the whole design. A scanner
    that looks for its own opening and then for the next ``` gets three things wrong, and the third is
    the one that bites: it misses a `~~~mermaid` fence, it misses an info string with attributes
    (```` ```mermaid {class=x} ````), and it reads a ```mermaid EXAMPLE inside a ````markdown block as a
    real diagram - so the first page that documents mermaid syntax goes red for a diagram nobody drew.
    Consuming each block by its own closing fence - same character, at least as long, which is
    CommonMark's rule - makes all three fall out at once, because an outer block swallows its contents
    whether or not they look like fences.

    The line reported is the fence's own, 1-based. mermaid's parser reports a line INSIDE the block, so
    the two together name the character.
    """
    found: list[Diagram] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        opened = _FENCE.match(lines[index].strip())
        if opened is None:
            index += 1
            continue
        fence, info = opened.group("fence"), opened.group("info").strip()
        # The info string's FIRST word names the language; anything after it is attributes.
        mermaid = info.split(" ")[0].split("{")[0].strip().lower() == "mermaid"
        start, body = index, []
        index += 1
        while index < len(lines):
            closing = _FENCE.match(lines[index].strip())
            if (closing is not None and not closing.group("info")
                    and closing.group("fence")[0] == fence[0]
                    and len(closing.group("fence")) >= len(fence)):
                break
            body.append(lines[index])
            index += 1
        if mermaid:
            found.append(Diagram(page=page, line=start + 1, body="\n".join(body)))
        index += 1
    return found


def diagrams_under(source: Path, skip: set[str] | None = None) -> list[Diagram]:
    """Every mermaid block under a site's source tree, in a stable order.

    The SOURCE rather than the built HTML, and the choice costs something either way. Hugo escapes the
    block into `<pre class="mermaid">`, so the output carries the same characters and would be just as
    checkable - but it carries no line number and no file an author edits, and the acceptance this
    exists for asks which page and which line. What the source misses in exchange is a diagram that
    reaches a page by some other route (a shortcode, a data file); the count is reported for exactly
    that reason, so a reader can see what the gate ruled on rather than assume it saw everything.
    """
    if not source.is_dir():
        # "No diagram" and "looked where there is nothing" are two answers, and returning the first for
        # the second is the defect this whole gate exists against - one level up from the one it catches.
        raise NotADirectoryError(f"{source} is not a directory, so no page could be read for diagrams")
    skipped = _NOT_THE_AUTHORS if skip is None else skip
    found: list[Diagram] = []
    for page in sorted(source.rglob("*.md")):
        parts = page.relative_to(source).parts[:-1]
        if any(part in skipped or part.startswith(".") for part in parts):
            continue
        found += diagrams_in(page.read_text(encoding="utf-8"), page)
    return found


def _renders(diagram: Diagram, scratch: Path) -> bool:
    """Render one block in the pinned mermaid image and say whether an SVG came out.

    NO `--entrypoint`, which is the opposite of `_hugo` one function up and was measured rather than
    reasoned: this image's entrypoint is `mmdc -p /puppeteer-config.json`, and that config is the only
    thing that tells puppeteer where chromium is and to drop its sandbox. Overriding it the way `_hugo`
    overrides hugo's replaces every verdict with `Could not find Chrome` - which is rc 1 for a diagram
    that is perfectly fine, a gate that is red on everything and therefore says nothing.

    `--user` for the reason `docker.user_args` documents: the container writes the SVG into a mounted
    directory. And the check is rc AND the file, because an exit code that reported nothing as success
    is what `allure.render_report` did for two releases.
    """
    src = scratch / "diagram.mmd"
    out = scratch / "diagram.svg"
    out.unlink(missing_ok=True)
    src.write_text(diagram.body, encoding="utf-8")
    ok = run(["docker", "run", "--rm", *docker.user_args(),
              "-v", f"{scratch}:{MERMAID_MOUNT}", MERMAID_IMAGE,
              "-i", str(MERMAID_MOUNT / src.name), "-o", str(MERMAID_MOUNT / out.name)],
             capture=False).ok
    return ok and out.is_file()


def render_diagrams(cfg: Site, root: Path) -> tuple[int, tuple[str, ...]]:
    """Render every mermaid block under the site source and report `(how many, which ones failed)`.

    WHY THIS IS IN THE BUILD AND NOT IN pytest (si#45). Hugo emits the block whether or not it parses,
    because mermaid draws in the reader's browser and not during the build - measured: a page whose
    diagram was replaced by obvious nonsense built with rc 0, the full page count, and the nonsense
    verbatim in the HTML. So a green build proved nothing about the picture, and two single-character
    errors (`flowchart` -> `flowchrt`, `.->` -> `.->>`) made the diagram invisible with the build and
    the suite both green.

    A pytest over `build/website/` would have been the wrong home for the fix and for a reason worth
    keeping: without docker it would be red or skipped - the result that cannot tell "nothing to do"
    from "failed" - and green for as long as any old build was lying around. HERE docker is a
    precondition rather than a coincidence, so the gate is red or green and never skipped.

    THE SECOND IMAGE IS ONLY PULLED WHEN THERE IS SOMETHING TO RENDER. It is cheaper, and it is also the
    honest split: no diagram is not the same statement as "checked, and fine", so the caller is handed
    the count and says which of the two happened.
    """
    found = diagrams_under(root / cfg.source)
    if not found:
        return 0, ()
    log.info(f"checking {len(found)} mermaid diagram(s) with {MERMAID_IMAGE}")
    broken = []
    scratch = Path(tempfile.mkdtemp(prefix="simplon-mermaid-"))
    try:
        for diagram in found:
            if not _renders(diagram, scratch):
                broken.append(diagram.where(root))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)   # our own temp dir; nothing of the product's is in it
    return len(found), tuple(broken)


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
    try:
        checked, broken = render_diagrams(cfg, root)
    except NotADirectoryError as exc:
        # The gate did NOT run, and saying "nothing to check" here would be the very confusion it was
        # built against. `diagrams` stays None for that reason, and the build is red.
        log.error(f"hugo reported a site, but {cfg.source}/ is not a directory, so no page could be read "
                  f"for diagrams ({exc}). 'no diagram' and 'looked where there is nothing' are different "
                  f"answers and this build will not give the first for the second")
        return Build(index=index, tool="docker", broken=(f"{cfg.source}/ could not be read",))
    for where in broken:
        log.error(f"the mermaid block at {where} does not render (see the parser's own message above), "
                  f"so that diagram is invisible in the browser. hugo emits the block whatever it says: "
                  f"it is drawn in the reader's browser, not during this build, which is why a green "
                  f"hugo is no statement about the picture")
    return Build(index=index, tool="docker", diagrams=checked, broken=broken)


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
        # SAID, not left to be inferred. A build with no diagram in it is green, and green here means
        # "there was nothing to render-check" rather than "every diagram renders" - the two are
        # different statements and a reader who cannot tell them apart has been told the stronger one.
        # `== 0` rather than a truthiness test: 0 and None are both falsey and mean opposite things
        # here, and `Build.ok` is what guarantees None never reaches this branch at all.
        if built.diagrams == 0:
            log.ok(f"no mermaid diagram under {cfg.source}/ - nothing to render-check")
        else:
            log.ok(f"{built.diagrams} mermaid diagram(s) render")
    return 0
