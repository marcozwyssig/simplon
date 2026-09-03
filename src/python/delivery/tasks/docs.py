"""Render a product's AsciiDoc documentation with docToolchain, in Docker (netctl#1280's rule).

WHY THIS IS THE KERNEL'S. Rendering AsciiDoc needs no product knowledge: the tool reads its own
`docToolchainConfig.groovy`, writes its own `build/docToolchain/` tree, and neither of those is a
netctl convention - they are docToolchain's. What IS the product's is the DATA: which version of the
image to pin, and what the config file names as input. Both flow in through the manifest, so a netctl
function forwarding this call would be a shim rather than a seam.

The split is deliberate about which side owns which failure. This module refuses when the image
produced nothing; whether the config points at files that still EXIST after a directory move is the
product's own assertion, because only the product knows where its documents live.

RUNS AS ROOT (netctl#1133), and that is a container fact, not a preference. The image's default user is
uid 100 (`dtcuser`), while BOTH paths the render must write are root-owned in a checkout where every
other containerised step runs as root: gradle's project-local `.gradle/` (created by the containerised
gradle, netctl#1091) and the `build/` output tree. Measured as `dtcuser`: `touch /project/.gradle/_probe`
and `touch /project/build/_probe` both give "Permission denied", so the render died on its first
bookkeeping write (`.gradle/8.1.1/fileChanges/last-build.bin`) and could never have produced output
either. Note this is the PROJECT-local `.gradle`, not GRADLE_USER_HOME - gradle writes per-project state
there whatever GRADLE_USER_HOME says, so a cache volume does not address it.

`--platform linux/amd64` for the same class of reason: the image publishes no arm64 variant, so on Apple
Silicon it runs under emulation or not at all.
"""
from __future__ import annotations

from pathlib import Path

from delivery import context, docker, log
from delivery.run import run

#: The manifest key holding the pinned image tag. Top-level rather than a section of its own: it is one
#: value, and the manifest already carries the other build-data pins (image names, cache volumes) flat.
VERSION_KEY = "doctoolchain_version"

#: docToolchain's OWN conventions, not a product's: the config file it looks for and the tree it writes.
CONFIG_FILE = "docToolchainConfig.groovy"
OUTPUT_DIR = Path("build") / "docToolchain"

#: The two generators netctl's docs have always been rendered with. Kept here rather than in the
#: manifest until a second product wants a different pair - a knob nobody turns is speculation.
GENERATORS = ("generateHTML", "generatePDF")


def _version(data: dict) -> str:
    """The pinned docToolchain image tag, or a loud failure. An unpinned tool version would silently
    render against whatever `latest` happens to be, which is the one thing a documentation build must
    not do: the output is committed-to prose, and a generator change rewrites it wholesale."""
    version = str(data.get(VERSION_KEY, "")).strip()
    if not version:
        raise ValueError(f"manifest: '{VERSION_KEY}' is missing or empty - pin the docToolchain image tag")
    return version


def render() -> int:
    """Render the product docs via docToolchain (generateHTML + generatePDF) in Docker."""
    ctx = context.current()
    version = _version(ctx.manifest_data())
    docker.ensure_docker()

    out = ctx.root / OUTPUT_DIR
    log.info(f"rendering docs via docToolchain ({' + '.join(GENERATORS)}) in Docker -> {OUTPUT_DIR}/")
    rc = run(["docker", "run", "--rm", "--platform", "linux/amd64", "--entrypoint", "/bin/bash",
              "--user", "0:0",
              "-e", "DTC_HEADLESS=true", "-v", f"{ctx.root}:/project", "-w", "/project",
              f"doctoolchain/doctoolchain:{version}", "-c",
              f"doctoolchain . {' '.join(GENERATORS)} -PmainConfigFile={CONFIG_FILE}"],
             capture=False).rc
    if rc != 0:
        log.die("docToolchain render failed (see output above)")
    # Exit 0 with no output is the failure mode this check exists for: docToolchain reports a config that
    # names a file which is not there as a warning, not an error, so a stale path after a directory move
    # produces a GREEN run and an empty tree (netctl#548).
    if not any(out.rglob("*.html")):
        log.die(f"docToolchain exited 0 but produced no HTML under {OUTPUT_DIR} (check {CONFIG_FILE} inputFiles)")
    log.ok(f"docs rendered -> {OUTPUT_DIR}/ (html5/ + pdf/)")
    return 0
