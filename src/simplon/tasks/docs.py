"""Render a product's AsciiDoc documentation with docToolchain, in Docker (netctl#1280's rule).

WHY THIS IS THE KERNEL'S. Rendering AsciiDoc needs no product knowledge: the tool reads its own
`docToolchainConfig.groovy`, writes its own `build/docToolchain/` tree, and neither of those is a
netctl convention - they are docToolchain's. What IS the product's is the DATA: which version of the
image to pin, and what the config file names as input. Both flow in through the manifest, so a netctl
function forwarding this call would be a shim rather than a seam.

The split is deliberate about which side owns which failure. This module refuses when the image
produced nothing; whether the config points at files that still EXIST after a directory move is the
product's own assertion, because only the product knows where its documents live.

THE UID IS READ OFF THE TREE, IT IS NOT A CONSTANT (si#78). It used to be `--user 0:0` unconditionally,
justified by netctl#1133: the image's default user is uid 100 (`dtcuser`), while BOTH paths the render
must write are root-owned in a checkout where every other containerised step runs as root - gradle's
project-local `.gradle/` (created by the containerised gradle, netctl#1091) and the `build/` output tree.
Note this is the PROJECT-local `.gradle`, not GRADLE_USER_HOME: gradle writes per-project state there
whatever GRADLE_USER_HOME says, so a cache volume does not address it.

THAT JUSTIFICATION IS A CONDITIONAL, AND THE CONSTANT DROPPED THE CONDITION. It holds for a checkout
whose `.gradle/` and `build/` ARE root-owned; for a product whose own build runs `--user` it runs exactly
backwards, because then the render is the only thing making them root-owned and the next build cannot
write them. Measured on a Java product with `--user` gradle, in a fresh tree: `build docs` rc 0, then
`build jar` rc 1 with `Cannot create directory '/work/.gradle/8.14.3/fileHashes'`, and 113 root-owned
entries under the tree. Reversed - build first - four times rc 0. The order that hurts is the ordinary
one: in CI `docs` runs before `build`.

BOTH DIRECTIONS ARE MEASURED, WHICH IS WHY THIS IS A DECISION AND NOT A FLIP (2026-09-08, docToolchain
v3.5.0, one machine, each run under a time limit):

  * caller-owned tree, `--user <caller>`: rc 0, HTML and PDF written, ZERO root-owned entries left, and
    the `build jar` that used to die afterwards is rc 0;
  * root-owned `.gradle/` staged first, `--user <caller>`: rc 1, `Could not update
    /project/.gradle/8.1.1/fileChanges/last-build.bin` - the very file netctl#1133 named;
  * the same root-owned tree, `--user 0:0`: rc 0.

So netctl's reason still stands FOR NETCTL - its `gradle_argv` passes no `--user` today, so its gradle
container runs as root and its `.gradle/` is root-owned - and taking root away unconditionally would
break it. `_user_args` therefore asks the tree instead of assuming it: the caller's uid when the caller
can write what the render writes, root when it cannot, and a line saying which and why in the second
case. That line is the half si#78 asked for independently of the decision - a render that leaves a tree
a later `--user` step cannot write should say so rather than let gradle say it two commands later.

`--platform linux/amd64` for the same class of reason: the image publishes no arm64 variant, so on Apple
Silicon it runs under emulation or not at all.
"""
from __future__ import annotations

import os
from pathlib import Path

from simplon import context, docker, hostpath, log
from simplon.run import run

#: The manifest key holding the pinned image tag. Top-level rather than a section of its own: it is one
#: value, and the manifest already carries the other build-data pins (image names, cache volumes) flat.
VERSION_KEY = "doctoolchain_version"

#: The repository half of the image reference - the kernel's, because the tool IS docToolchain; only the
#: TAG is the product's to choose. Split out from the f-string it used to live in so `_version` can hand
#: the complete reference to the same pin gate a `site:` image goes through.
IMAGE_REPOSITORY = "doctoolchain/doctoolchain"

#: docToolchain's OWN conventions, not a product's: the config file it looks for and the tree it writes.
CONFIG_FILE = "docToolchainConfig.groovy"
OUTPUT_DIR = Path("build") / "docToolchain"

#: gradle's PROJECT-LOCAL state directory, which docToolchain's own gradle writes whatever GRADLE_USER_HOME
#: says. Named here because it is not the output tree and a reader looking only at `OUTPUT_DIR` would miss
#: half of what this render touches - and it is the half both measurements in the head died on.
GRADLE_STATE = Path(".gradle")

#: The two paths inside the bind-mounted product root that the render writes, and therefore the two whose
#: OWNER decides which uid the container may run as. `OUTPUT_DIR.parts[0]` rather than a second literal
#: `build`: the output tree moving would otherwise leave this list quietly pointing at the old one.
WRITTEN_PATHS = (GRADLE_STATE, Path(OUTPUT_DIR.parts[0]))

#: The two generators netctl's docs have always been rendered with. Kept here rather than in the
#: manifest until a second product wants a different pair - a knob nobody turns is speculation.
GENERATORS = ("generateHTML", "generatePDF")


def _version(data: dict) -> str:
    """The pinned docToolchain image tag, or a loud failure. An unpinned tool version would silently
    render against whatever `latest` happens to be, which is the one thing a documentation build must
    not do: the output is committed-to prose, and a generator change rewrites it wholesale.

    THE TAG IS HELD TO THE SAME RULE AS A `site:` IMAGE (si#47). This used to demand only that a tag be
    DECLARED, so `doctoolchain_version: latest` came through untouched - while `docs:site` refused
    exactly that in a product's manifest, at length and in writing. Two documentation renders in one
    kernel, one of them arguing for a pin the other did not ask for, is not a rule; it is a rule and an
    exception. `simplon.docker.pinned_image` is now the one gate, and it is handed the COMPLETE
    reference, because that is the string docker resolves - a tag is only pinned in the context of the
    repository it tags.

    AND THIS ONE IS AN EXPRESSION RULE, not a self-binding, so it owes the bar. si#47's other three
    changes cost a product nothing - they take an exemption away from the kernel. This one does not: a
    product may no longer write `doctoolchain_version: latest`, and that is the only kind of refusal
    that spends flexibility. The bar is the one #34 cleared, zero violations across the manifests that
    exist - and RE-MEASURED in #51, because the first measurement counted three manifests and one of
    them belonged to a repository that does not install this kernel at all (`simplon.surface`, which
    names it). There are six:

      * `netctl.yaml` declares `doctoolchain_version: v3.5.0` and places `docs:render` - passes;
      * `simplon.yaml`, `agile-cockpit.yaml`, `asbundle.yaml`, `biz-cockpit.yaml` and `cleon.yaml`
        place no `docs:render`, so none of them reaches this gate at all.

    So nothing that exists is refused, and what a product wanting the newest docToolchain does instead
    is what netctl already does: write the version it means and bump it. (Read from the repositories,
    not from memory - the first version of this reasoning checked simplon alone, which is the one
    manifest that cannot reach the gate at all, and the second one checked a repository that is not a
    consumer. `simplon.surface.CONSUMERS` is the list that says which repositories these are.)
    """
    version = str(data.get(VERSION_KEY, "")).strip()
    if not version:
        raise ValueError(f"manifest: '{VERSION_KEY}' is missing or empty - pin the docToolchain image tag")
    docker.pinned_image(f"{IMAGE_REPOSITORY}:{version}", f"manifest: '{VERSION_KEY}'",
                        hint=f"write the version you mean, e.g. \"{VERSION_KEY}: v3.5.0\" - this key "
                             f"holds a TAG, not a whole image reference")
    return version


def _unwritable(root: Path) -> list[Path]:
    """Every existing entry under `WRITTEN_PATHS` that the CALLING user cannot write, first one first.

    Empty on a tree the caller owns, which is the ordinary case and the whole reason the render may run as
    the caller. It WALKS rather than stats the two tops, because the state that produced si#78 is exactly
    the mixed one: after a root render and a `--user` build, `.gradle/` itself belongs to the caller and
    `.gradle/8.1.1/` below it belongs to root. A shallow check would call that tree writable and hand the
    render a uid that dies on its first bookkeeping write.

    `os.access` asks the kernel with the REAL uid, so it answers the question that matters - can this
    process write here - rather than the one an owner comparison answers.
    """
    blocked: list[Path] = []
    for rel in WRITTEN_PATHS:
        top = root / rel
        if not top.exists():
            continue
        for path in (top, *sorted(top.rglob("*"))):
            if not os.access(path, os.W_OK):
                blocked.append(path)
    return blocked


def _user_args(root: Path) -> list[str]:
    """``--user`` for the render container: the caller's uid on a tree the caller can write, root on one it
    cannot - and a sentence naming the path that forced the second, because that render leaves a tree the
    product's own build will fail in.

    The root branch is netctl#1133's case and it is unchanged for it. What changed (si#78) is that the case
    is now RECOGNISED instead of assumed, so a product whose build runs `--user` gets a render that does
    too. On a host with no uid concept `docker.user_args` returns nothing at all and the image's own
    `dtcuser` runs - documented there, and the mount carries no ownership to get wrong.
    """
    blocked = _unwritable(root)
    if not blocked:
        return docker.user_args()
    who = f"uid {os.getuid()}" if hasattr(os, "getuid") else "this user"
    log.warn(f"{len(blocked)} entr{'y' if len(blocked) == 1 else 'ies'} under "
             f"{'/, '.join(str(p) for p in WRITTEN_PATHS)}/ cannot be written by {who} - first: "
             f"{blocked[0].relative_to(root)}. An earlier container that ran without --user left them, so "
             f"this render runs as root (netctl#1133) and everything it writes will be root-owned too. A "
             f"later step running as {who} dies there with \"Cannot create directory\"; removing those two "
             f"trees takes a root shell.")
    return ["--user", "0:0"]


def render() -> int:
    """Render the product docs via docToolchain (generateHTML + generatePDF) in Docker."""
    ctx = context.current()
    version = _version(ctx.manifest_data())
    docker.ensure_docker()

    out = ctx.root / OUTPUT_DIR
    user = _user_args(ctx.root)
    log.info(f"rendering docs via docToolchain ({' + '.join(GENERATORS)}) in Docker -> {OUTPUT_DIR}/")
    rc = run(["docker", "run", "--rm", "--platform", "linux/amd64", "--entrypoint", "/bin/bash",
              *user,
              "-e", "DTC_HEADLESS=true", "-v", f"{hostpath.translate(ctx.root)}:/project",
              "-w", "/project",
              f"{IMAGE_REPOSITORY}:{version}", "-c",
              f"doctoolchain . {' '.join(GENERATORS)} -PmainConfigFile={CONFIG_FILE}"],
             capture=False).rc
    if rc != 0:
        # WHICH UID IT RAN AS IS PART OF THE CAUSE NOW. With one branch there was nothing to say; with two
        # it is the first thing a reader has to know, because the two failures look nothing alike - a
        # permission message from the caller branch means the tree changed under this run, one from the
        # root branch means something else entirely.
        ran_as = user[user.index("--user") + 1] if "--user" in user else "the image's own user"
        log.die(f"docToolchain render failed as {ran_as} (see output above)")
    # Exit 0 with no output is the failure mode this check exists for: docToolchain reports a config that
    # names a file which is not there as a warning, not an error, so a stale path after a directory move
    # produces a GREEN run and an empty tree (netctl#548).
    if not any(out.rglob("*.html")):
        log.die(f"docToolchain exited 0 but produced no HTML under {OUTPUT_DIR} (check {CONFIG_FILE} inputFiles)")
    log.ok(f"docs rendered -> {OUTPUT_DIR}/ (html5/ + pdf/)")
    return 0
