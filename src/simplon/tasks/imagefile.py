"""`build:image-file` - one file out of an image, for the platform its file entry names (si#552).

WHAT IT IS FOR. A product that ships a binary builds it inside its image, where its toolchain is pinned, and
then wants the bare file too - firn's release hands out `firn-linux-amd64` and `firn-linux-arm64`. Without
this task each product writes the same `docker create` / `docker cp` / `docker rm` lines itself, picks the
platform by hand, and forgets the `rm`. Here it is one coordinate: the image entry says what was built, the
`kind: file` entry says where the file goes AND FOR WHICH PLATFORM (`platform:`, decided by Marco on si#552:
one entry per platform, so a miswired platform is refused here instead of surfacing as `exec format error`).

WHY BESIDE `tasks.image` AND NOT IN IT. `image.py` is the image's own three verbs - build, smoke, release -
and already the longest module in the kernel. This one READS an image and WRITES a file entry: it uses
`image`'s declarations and references unchanged and adds nothing they need. Kept apart, the file side of
si#552 (this task and `test:file`) has one home and `image.py` does not grow a second subject.

WHERE IT READS FROM. Without `tag`: the platform's reference this checkout's `build:image` recorded
(`read_built`), held by the daemon as `platform_reference`. It never pulls then: a platform this checkout did
not build is a refusal that names the build, not a silent copy of something older. With `tag`: the PUBLISHED
image - the registry's multi-platform index is read with `oras manifest fetch`, and the platform's own manifest
is pulled by digest, `<repository>@<digest>`, so the bytes are the ones the registry serves for that platform
whatever the daemon holds under the tag. No credential is demanded before the registry is asked: a public
image pulls anonymously. A tag this host cannot read (absent, or not readable without a login), a single
manifest and an index without the platform are refusals; none of them falls back to a local build.

THE COPY LEAVES A REGULAR FILE OR NOTHING. `docker cp -L` follows a symlink (a measured `/link ->
/bin/busybox` arrives as the file); a directory arrives as a directory and is refused, and a symlink to
nothing or an absent path is docker's own `Could not find the file` (both measured 2026-10-28). The bytes land
beside `path` under a staging name and are renamed into place only once they are a regular file, mode 0755.
The container is removed whatever the copy said.

`test:file` RUNS THAT FILE, ALONE (si#552). An image proves its binary works beside the image's libc; the bare
file is handed out without one, so it is run in `FILE_TEST_IMAGE` - busybox built on musl, pinned by digest -
where a binary that quietly links glibc fails here instead of on a user's machine (measured 2026-10-28: a
host's glibc `/bin/true` answers `exec /run/file: no such file or directory`, rc 255 - its loader is absent).
The platform is the file entry's `platform:` (absent: the host's, `--platform` omitted), `--network none`
because a file test that needs the network is a different test, and `timeout` is required because a run
without a limit has no verdict. The record names the file's sha256 as the subject `manifest.results` reads, so a release that
uploads the file can compare what it uploads with what was tested (si#553).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from simplon.adapters import docker, githubpackages, hostpath
from simplon.kernel import log
from simplon.kernel.run import run
from simplon.manifest import artifactsection, context
from simplon.manifest import results as results_mod
from simplon.manifest.layout import validate_relative_dir
from simplon.model import artifactschema
from simplon.tasks import image

#: The manifest section this module reads.
SECTION = "artifacts"

COORDINATE = "build:image-file"

#: The kind `name` binds - the image read from, through `tasks.image`'s own reader. `test_generated_schema.py`
#: holds it to the model's READERS.
ENTRY = artifactschema.ImageEntry

#: The kind the `file` param binds: the entry written, and the one that names the platform.
FILE_ENTRY = artifactschema.FileEntry

#: The suffix the copied bytes carry until they are known to be a regular file.
STAGING = ".partial"

#: The command `docker create` is given and never runs: the container is only copied out of, and an image
#: with neither CMD nor ENTRYPOINT (a `FROM scratch` stage holding one binary) is refused by `docker create`
#: with "no command specified" without one (measured 2026-10-28).
NEVER_STARTED = "simplon-copy-only"

CHECK_COORDINATE = "test:file"

#: What `test:file` runs a bare file in: a shell and nothing else, no glibc. The index digest, so every platform
#: resolves to its own manifest (measured with `docker pull` on 2026-10-28).
FILE_TEST_IMAGE = docker.pinned_image(
    "busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092",
    "simplon.tasks.imagefile")

#: Seconds the warm-up pull of `FILE_TEST_IMAGE` may take: a pull is a download, not the file's answer, so it is
#: outside `timeout`, and bounded so a hung registry cannot hang the test.
PULL_TIMEOUT = 300

#: Where the file is mounted, read-only, inside `FILE_TEST_IMAGE`.
MOUNTED = "/run/file"


def file_entry(name: str, coordinate: str) -> tuple[artifactschema.FileEntry, Path]:
    """The `kind: file` entry `name` (bound through the `file` param of `coordinate`) with its `path`
    validated, and the product root; a ValueError names a missing entry, a wrong kind or a bad path."""
    if not name:
        raise ValueError(f"which file? bind one with `produces: {{ file: ... }}` from the `{SECTION}:` "
                         f"section, or pass --file")
    ctx = context.current()
    section = ctx.manifest_data().get(SECTION)
    section = section if isinstance(section, Mapping) else {}
    source = ctx.manifest_path.name
    if name not in section:
        raise ValueError(f"{source}: no artifact '{name}' in the `{SECTION}:` section; declared are: "
                         f"{', '.join(sorted(str(k) for k in section)) or '(none)'}")
    entry = artifactsection.entry(section, name, FILE_ENTRY, source, coordinate, param="file")
    # `or ""` is for the type checker: every coordinate that reads a file entry NEEDS `path`.
    path = validate_relative_dir(entry.path or "", f"{source}: '{SECTION}.{name}': 'path'",
                                 "give the file's path under the product root, e.g. 'build/firn-linux-amd64'",
                                 inside="the product root")
    return entry.model_copy(update={"path": path}), ctx.root


def extract(name: str = "", file: str = "", inside: str = "", tag: str = "") -> int:
    """Copy `inside` out of the image `name` declares, for the platform the file entry `file` names, to that
    entry's `path`, mode 0755.

    The platform is the FILE ENTRY's `platform:` and nothing else: there is no `platform` param, so one
    command cannot write one platform's bytes under another platform's entry.
    """
    cfg, root = image._declared_for(name, COORDINATE)
    entry, _ = file_entry(file, COORDINATE)
    platform = entry.platform or ""
    # Every refusal below is answered before docker is asked: each one is about the manifest.
    if not platform:
        choices = ", ".join(cfg.platforms) or f"the `platforms:` image '{name}' declares"
        log.error(f"file '{file}' declares no `platform:`, and {COORDINATE} copies one platform's file. Add "
                  f"`platform:` to `{SECTION}.{file}` - one of {choices} - and declare one file entry per "
                  f"platform")
        return 1
    # Not `_platform_declared`: its first message tells a command to "drop `platform:`", which a file entry
    # cannot, and its second names neither the file entry at fault nor a way out.
    if not cfg.platforms:
        log.error(f"image '{name}' declares no `platforms:`, so it has no per-platform build to copy "
                  f"{platform}'s file out of. Declare `platforms:` on `{SECTION}.{name}`, with {platform} "
                  f"among them")
        return 1
    if platform not in cfg.platforms:
        log.error(f"`{SECTION}.{file}.platform` is {platform}, and image '{name}' is not built for it; its "
                  f"declared platforms are {', '.join(cfg.platforms)}. Change the file entry's `platform:` "
                  f"to one of them, or add {platform} to `platforms:` on `{SECTION}.{name}`")
        return 1
    if not inside.startswith("/"):
        log.error(f"`inside:` is {inside!r}; give the file's absolute path inside the image, e.g. /usr/bin/firn")
        return 1
    docker.ensure_docker()
    if tag:
        return _copy_published(cfg, tag, platform, inside, str(entry.path), root)
    source = _built_reference(cfg, name, platform, root)
    if source is None:
        return 1
    return _copy(source, inside, str(entry.path), root)


def _copy(source: str, inside: str, path: str, root: Path) -> int:
    """`copy_out` from the daemon's `source` to the entry's `path`, naming the image id it copied from."""
    image_id = image.local_id(source)
    if not copy_out(source, inside, root / path):
        return 1
    log.ok(f"copied {inside} out of {source} ({image_id or 'its id could not be read'}) to {path}")
    return 0


def _copy_published(cfg: image.Image, tag: str, platform: str, inside: str, path: str, root: Path) -> int:
    """The published image's `platform` manifest, pulled by digest and copied from.

    NOTHING REFUSES FOR WANT OF A CREDENTIAL BEFORE THE REGISTRY IS ASKED: a public image pulls anonymously,
    and a push's precondition (`release:image` checks for a stored login) would turn that into a refusal of
    something that works. Only a failed fetch or pull refuses, and its message names the login as one way out.

    For GitHub Packages a token is minted, when there is one, into a docker config that ends with the block
    (si#443); the index read, the pull AND the `docker create` all happen inside it, so no credential
    outlives the command. Without a token the same block goes on anonymously. For any other host no GitHub
    token is minted (si#200), and the block is not entered: the scope keeps no credential of the caller's,
    so it would drop exactly the `docker login` the operator stored for that host.
    """
    try:
        githubpackages.require_oras()
    except githubpackages.PackageError as failure:
        log.error(f"the published index of {image.reference(cfg, tag)} cannot be read, so nothing was "
                  f"pulled: {failure}")
        return 1
    if not githubpackages.is_github_packages(cfg.registry):
        return _pull_and_copy(cfg, tag, platform, inside, path, root)
    with githubpackages.scoped_credentials():
        try:
            githubpackages.docker_login(cfg.registry)
        except githubpackages.PackageError as failure:
            log.warn(f"reading {image.reference(cfg, tag)} without a login, which a public package allows: "
                     f"{failure}")
        return _pull_and_copy(cfg, tag, platform, inside, path, root)


def _login_advice(cfg: image.Image) -> str:
    """The credential that lets this host read `cfg`'s registry: the GitHub token for GitHub Packages (a
    stored `docker login` is not read inside the scope), the operator's `docker login` for any other."""
    if githubpackages.is_github_packages(cfg.registry):
        return (f"a GitHub token that may read the package - set GITHUB_TOKEN or run `gh auth login`; "
                f"{githubpackages.scope_advice()}")
    return f"`docker login {githubpackages.registry_host(cfg.registry)}`"


def _pull_and_copy(cfg: image.Image, tag: str, platform: str, inside: str, path: str, root: Path) -> int:
    """Resolve, pull and copy from `platform`'s published manifest, in whatever credential scope the caller
    holds."""
    source = published_reference(cfg, tag, platform)
    if source is None:
        return 1
    pulled = run(["docker", "pull", source])
    if not pulled.ok:
        log.error(f"`docker pull {source}` failed, so nothing was copied: "
                  f"{(pulled.err or pulled.out).strip() or '(it said nothing)'}.\n"
                  f"  if the registry needs a login: {_login_advice(cfg)}")
        return 1
    return _copy(source, inside, path, root)


def published_reference(cfg: image.Image, tag: str, platform: str) -> str | None:
    """`<registry>/<repository>@<digest>` of `platform`'s manifest in the index the registry serves under
    `tag`, or None after saying why.

    A failed fetch is never read as "no index". From here an absent tag and a refused read look alike (a
    registry may answer either way for a package this host may not see), so the message names both, with
    oras's own words and the login that would let this host read it. A published `linux/arm64/v8` answers for a declared
    `linux/arm64`, as in `image.missing_platforms`.
    """
    ref = image.reference(cfg, tag)
    fetched = run(["oras", "manifest", "fetch", ref])
    if not fetched.ok:
        log.error(f"{ref} could not be read from the registry, so nothing was pulled: "
                  f"{(fetched.err or fetched.out).strip() or '(oras said nothing)'}.\n"
                  f"  either it is not published: publish it (`release:image` with the same tag), or drop "
                  f"`tag` to copy from this checkout's build;\n"
                  f"  or this host may not read it: if the registry needs a login: {_login_advice(cfg)}")
        return None
    manifests = image.index_manifests(fetched.out)
    if manifests is None:
        log.error(f"{ref} is published as a single manifest, not a multi-platform index, so it has no "
                  f"{platform} manifest to pull by digest; publish it from an image entry with "
                  f"`platforms:` (`release:image`)")
        return None
    if image.missing_platforms([platform], manifests):
        log.error(f"{ref} is published without {platform}: its index carries "
                  f"{', '.join(sorted(manifests)) or 'no platform at all'}. Publish {ref} for {platform} "
                  f"(`release:image`), or copy for a platform the index carries")
        return None
    digest = manifests.get(platform) or next((digest for found, digest in sorted(manifests.items())
                                              if found.startswith(platform + "/")), "")
    return f"{cfg.registry.rstrip('/')}/{cfg.repository.strip('/')}@{digest}"


def _built_reference(cfg: image.Image, name: str, platform: str, root: Path) -> str | None:
    """The daemon reference this checkout's `build:image` loaded `platform` under, or None after saying why.

    The tag is resolved the way `build:image` and `test:image` resolve it without one, so the three cannot
    name three references."""
    resolved = image.resolve_tag(cfg, "", image.build_arguments(cfg, root).get(image.VERSION_ARG, ""))
    ref = image.reference(cfg, resolved)
    source = image.platform_reference(ref, platform)
    if platform not in image.read_built(name, ref) or not image.present_locally(source):
        log.error(f"this checkout has no build of image '{name}' for {platform} under {ref}, so there is "
                  f"nothing to copy out of; nothing was pulled.\n"
                  f"  build it first: `build:image` with `with: {{ name: {name} }}`")
        return None
    return source


def copy_out(reference: str, inside: str, dest: Path) -> bool:
    """Copy the regular file `inside` out of the daemon's `reference` to `dest`, mode 0755, or say why not.

    `dest` holds the new bytes or is left as it was: they land at `<dest>.partial` first and replace `dest`
    only once they are a regular file. The container is NAMED before it is created, so an interrupt between
    the create and the rm still removes it (si#416, `docker.stopped_on_interrupt`).
    """
    staged = dest.with_name(dest.name + STAGING)
    _remove(staged)
    dest.parent.mkdir(parents=True, exist_ok=True)
    container, lifecycle = docker.lifecycle()
    with docker.stopped_on_interrupt(container):
        created = run(["docker", "create", *lifecycle, reference, NEVER_STARTED])
        if not created.ok:
            log.error(f"`docker create {reference}` failed, so nothing was copied: "
                      f"{(created.err or created.out).strip() or '(it said nothing)'}")
            return False
        try:
            # `-L`: a symlink in the image is followed to the file it names.
            copied = run(["docker", "cp", "-L", f"{container}:{inside}", str(staged)])
        finally:
            run(["docker", "rm", container])
    if not copied.ok:
        _remove(staged)
        log.error(f"copying {inside} out of {reference} failed, so nothing was written to {dest}: "
                  f"{(copied.err or copied.out).strip() or '(it said nothing)'}")
        return False
    if staged.is_symlink() or not staged.is_file():
        _remove(staged)
        log.error(f"{inside} in {reference} is not a regular file (a directory?), so nothing was written to "
                  f"{dest}; name the file itself with `inside:`")
        return False
    staged.chmod(0o755)
    os.replace(staged, dest)
    return True


def _remove(path: Path) -> None:
    """Remove whatever is at `path` - a file, a symlink or a directory a `docker cp` made - if anything is."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def check(file: str = "", argv: str = "", expect: str = "", rc: int = 0, tag: str = "", stdin: str = "",
          timeout: int = 0, results: str = "") -> int:
    """Run the file the entry `file` names in `FILE_TEST_IMAGE`, for the entry's platform, and check its answer.

    `rc` is an expectation, not a tolerance, and `{tag}` in `expect` is the tag - `tag`, else the VERSION this
    checkout derives - exactly as on `test:image`. The record follows `test:image`'s rules too: an earlier one
    is removed before any refusal, a refused run writes none, and a red run writes its verdict.
    """
    record_path = results_mod.path_of(results) if results else None
    if record_path is not None:
        record_path.unlink(missing_ok=True)
    if timeout <= 0:
        log.error(f"{CHECK_COORDINATE} has no `timeout`, and a run without a limit has no verdict; give "
                  f"`timeout:` in seconds, greater than 0, e.g. `with: {{ timeout: 30 }}`")
        return 1
    entry, root = file_entry(file, CHECK_COORDINATE)
    path = str(entry.path)
    platform = entry.platform or ""
    stdin_text = ""
    if stdin:
        try:
            fed = root / image._inside_the_product(stdin, "stdin", CHECK_COORDINATE)
        except ValueError as refused:
            log.error(str(refused))
            return 1
        if not fed.is_file():
            log.error(f"`stdin:` names {fed}, which is not a file under {root}; give the file to feed the run")
            return 1
        # `newline=""`: read as written. Universal newlines would turn LSP's `\r\n` framing into `\n`.
        try:
            with open(fed, encoding="utf-8", newline="") as stream:
                stdin_text = stream.read()
        except UnicodeDecodeError as undecodable:
            log.error(f"`stdin:` names {stdin}, which is not UTF-8 text ({undecodable.reason} at byte "
                      f"{undecodable.start}); save it as UTF-8")
            return 1
    if not (root / path).is_file():
        log.error(f"file '{file}' has nothing at {path}, so there is nothing to run; write it first "
                  f"(`build:image-file` with `produces: {{ file: {file} }}`)")
        return 1
    expected = expect
    if "{tag}" in expect:
        resolved = tag or image.provenance(root).get(image.VERSION_ARG, "")
        if not resolved:
            log.error(f"`expect:` says {{tag}}, and no tag was given and none could be derived (the warning "
                      f"above says why); pass `tag:`")
            return 1
        expected = image.expand_tag(expect, resolved)
    subject = "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest()
    docker.ensure_docker()
    try:
        mount = hostpath.mount_argv(root, path, MOUNTED, readonly=True, must_exist=False)
    except ValueError as refused:
        log.error(str(refused))
        return 1
    _warm_up(platform)
    verdict, got = _run_file(path, platform, mount, argv, stdin_text, expected, rc, timeout)
    if record_path is not None:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps({
            "file": file, "verdict": verdict,
            "runs": [{"reference": path, "id": subject, "platform": platform, "argv": argv, "expected_rc": rc,
                      "rc": got, "verdict": verdict}]}, indent=2) + "\n", encoding="utf-8")
    return verdict


def _warm_up(platform: str) -> None:
    """Pull `FILE_TEST_IMAGE` for `platform` (the host's when empty) before the timed run, warning if it fails.

    A WARM-UP, NOT A GATE (Marco, 2026-10-28). Inside `timeout` a slow first pull would read as the file giving
    no answer, so it happens here, under its own `PULL_TIMEOUT`. A failed or hung pull is only a warning: the
    daemon may hold the image already (an offline host does), and the run decides - it is started with
    `--pull never`, so a local copy runs and no image at all is red with docker's own "No such image". So a
    pull failure is never reported as the file's timeout, and never as green. Measured 2026-10-28: with the
    image already held, the pull still asks the registry, about 3 s.
    """
    command = ["docker", "pull", *(["--platform", platform] if platform else []), FILE_TEST_IMAGE]
    try:
        pulled = run(command, timeout=PULL_TIMEOUT)
    except subprocess.TimeoutExpired:
        reason = f"no answer within {PULL_TIMEOUT} s"
    else:
        if pulled.ok:
            return
        reason = (pulled.err or pulled.out).strip() or "(it said nothing)"
    log.warn(f"`{' '.join(command)}` failed: {reason}; the run goes on with whatever the daemon holds")


def _run_file(path: str, platform: str, mount: list[str], argv: str, stdin_text: str, expect: str, rc: int,
              timeout: int) -> tuple[int, int | None]:
    """One `docker run` of the mounted file: its verdict and the container's own rc, None when it gave none.

    Stdin is always a pipe, empty without `stdin`, so `-i` never hands the run the caller's terminal. A run
    past `timeout` is stopped by name: `subprocess` kills only the client, and `stopped_on_interrupt` answers
    the exception with `docker rm -f` before it reaches here.
    """
    name, lifecycle = docker.lifecycle()
    command = ["docker", "run", "--rm", "-i", "--pull", "never", *(["--platform", platform] if platform else []),
               "--network", "none", *lifecycle, *mount, FILE_TEST_IMAGE, MOUNTED, *shlex.split(argv)]
    try:
        with docker.stopped_on_interrupt(name):
            result = run(command, timeout=timeout, input_text=stdin_text)
    except subprocess.TimeoutExpired:
        log.error(f"{path} gave no answer within {timeout} s; its container {name} was removed")
        return (1, None)
    if result.rc != rc:
        said = image._indented(result)
        advice = _emulation_advice(platform) if platform and "exec format error" in said else ""
        log.error(f"{path} exited {result.rc}" + (f", and {rc} was expected" if rc else "") + "\n" + said
                  + advice)
        # `or 1`: when a refusal was expected and the file exited 0, that 0 is the success being refused.
        return (result.rc or 1, result.rc)
    if expect and expect not in result.out:
        log.error(f"{path} exited {result.rc} and did not say what was expected.\n"
                  f"  expected to find: {expect}\n" + image._indented(result))
        return (1, result.rc)
    log.ok(f"ran {path} in {FILE_TEST_IMAGE}" + (f" for {platform}" if platform else ""))
    return (0, result.rc)


def _emulation_advice(platform: str) -> str:
    """What to do when the run says `exec format error`: the bake's register command, in a sentence about a
    run - there is no builder here to recreate."""
    return (f"\n  `exec format error` means this host has no emulator for {platform}. Register one - a "
            f"privileged act on the whole host, which is why simplon does not do it for you:\n"
            f"    {image._emulation_command([platform])}")
