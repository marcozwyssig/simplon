"""Publishing a jar in two steps: stage with `gradle publish` into a file repository, then upload what was staged and read it back (si#329, si#344 C.3).

WHY THIS EXISTS, MEASURED. The kernel BUILDS four languages - `tasks/profiles.py` carries cpp, java, dotnet
and python - and published two of them. It has pinned a Gradle image since si#316 (`gradle:9.7.1-jdk{version}`)
and had no way to hand the result to anybody. A product whose only consumption route is a jar therefore had
to write its own publish, which is the situation the catalogue exists to end.

WHICH OF THE TWO PRECEDENTS THIS FOLLOWS, and the choice was argued rather than copied. `release:nuget`
LEARNED the toolchain: it runs `dotnet` in a container at `/work` and knows what `DOTNET_CLI_HOME` has to
be. `release:conan` deliberately did NOT - its head says the product drives conan through its own
`toolchain:run` commands, and calls the alternative "the kernel learning a language toolchain, which the
design refuses everywhere else". Conan's reason was specific and is recorded there: GitHub Packages has no
Conan registry, so there was nothing to publish to and only a transport was possible. For Maven there IS a
registry - `release:conan`'s own comment lists the kinds GitHub serves, and Maven and Gradle are on it. So
conan's reason does not apply here and the nuget shape is the one the evidence supports.

WHY IT READS THE REGISTRY BACK, which nuget does not. `release:image` states the rule: "a push nobody
verifies is the same defect as a report nobody reads, and this project has shipped it twice". A `gradle
publish` that exits 0 having uploaded nothing is exactly that shape - and it is reachable, because a Gradle
build with no `maven-publish` plugin configured has no `publish` task work to do and does not fail for it.

WHY THE TWO HALVES ARE TWO TASKS (si#344 C.3). `gradle publish` builds and uploads in one run, so the jar
first existed inside its own release and no test could consume it - and the release rule asks for a test
result about every artifact a release publishes. `build:maven-pack` now runs the same `publish`, aimed at
a file repository the kernel's init script adds under the entry's `path:`; `release:maven` uploads exactly
those files, artefacts before metadata, and then runs the read-back it always ran. Gradle's own
`publishToMavenLocal` was the cheaper route and was not taken: Maven's local repository writes
`maven-metadata-local.xml` and no checksums, which is not the layout a remote repository holds.
NOT PROVEN: that GitHub's Maven registry accepts a plain PUT per file. `mvn deploy` does exactly that, and
the client here is measured against a local HTTP server, but the machine this was written on has no
`write:packages` token.
UNMEASURED CONSEQUENCE: `push` uploads the staged `maven-metadata.xml*`, which lists only the staged version.
If the registry honours a PUT over an existing metadata file, the module's version list is replaced by a
one-version file; `mvn deploy` merges the remote metadata first and this task does not. Not fixed, not measured.

AND THE VERIFICATION HAS THREE OUTCOMES, not two. `401` is not "the jar is missing", it is "we were not
allowed to look", and reporting the second as the first sends a reader to the build file when the answer is
a token scope. si#327 paid for that distinction three days before this module was written, in a module whose
rc meant four different things at once.

THE HOME IS `GRADLE_USER_HOME` AND NOT `HOME`, and this is a consumer's measurement rather than a
preference. si#319 gave a containerised run a home the caller owns; si#325 measured what that does NOT
reach: the JVM resolves `user.home` from the passwd entry and ignores `$HOME`, so for root - which is what
a CI job usually is - setting HOME moves nothing. A tool with a variable of its own needs that variable.
Gradle has one.

THE TOKEN NEVER REACHES ARGV. `--env-file`, a 0600 file removed in a `finally`, for the reason
`tasks/nuget.py` records: `docker run -e GITHUB_TOKEN=...` is readable in `ps` for every user on the
machine and stays in `docker inspect` for as long as the container exists.
"""
from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

from simplon.domain import artifactsection, artifactschema, context, outputs
from simplon.adapters import docker, githubpackages, hostpath
from simplon.kernel import log
from simplon.kernel.run import stream
# The CREDENTIAL helper is imported and not copied, deliberately, and it is the one thing here that is.
# `_env_file` writes a 0600 file and removes it in a `finally`; two copies of that is how one of them loses
# the `finally` on the day somebody edits the other. The SECTION READER below is copied instead - see its
# own docstring for why the asymmetry is the right way round.
from simplon.tasks.nuget import _env_file, _inside_the_output_root

#: The manifest section this module reads - the same one `tasks/artifact`, `tasks/asset`, `tasks/nuget` and
#: `tasks/conan` read. si#127's reasoning, applied a fourth time: a registry, a package and a scope are the
#: same three facts whatever the ecosystem, and a section is cheap to add and expensive to remove.
SECTION = "artifacts"

#: The kind this module reads, by `release:maven` (si#344 B2). Its keys, their shapes and what the coordinate
#: needs are the generated schema's.
ENTRY = artifactschema.MavenEntry

#: The container's view of the product tree - `/work`, the mount point `toolchain:run` and
#: `release:nuget` both use, so a path printed by one command means the same thing in another.
WORKDIR = "/work"

#: Where Gradle may keep its per-user state. Inside the mounted tree because that is the one directory a
#: container running as the caller can always write, and under `build/` because that is what a product
#: gitignores. See the module head for why this is `GRADLE_USER_HOME` and not `HOME`.
GRADLE_HOME = "build/gradle-home"

#: What the read-back can honestly say. Three values because `401` and `404` are different answers and
#: were one value in every hand-written publish this replaces.
PRESENT = "present"
ABSENT = "absent"
UNKNOWN = "unknown"

#: How long the read-back waits on one HTTP request. A verification that hangs is a release that hangs.
TIMEOUT = 30.0

#: Maven's own suffix for a mutable version, and the check against it is CASE-SENSITIVE because Maven's is:
#: `0.1.0-Snapshot` is an ordinary release version to every tool in that ecosystem, which is a trap rather
#: than a nicety.
SNAPSHOT_SUFFIX = "-SNAPSHOT"

#: The gradle task the pack runs (si#344 C.3): every publication, into the one repository the kernel's init
#: script adds. Fixed, for si#337's reason: a task the product names could aim anywhere, and this task's
#: claim is "the declared modules are staged where the push reads them".
STAGE_TASK = "publishAllPublicationsToSimplonStagingRepository"

#: The init script's file name, under `GRADLE_HOME` - inside the mounted tree, where the container can read it.
INIT_SCRIPT = "simplon-staging.gradle"


def init_script_text(staging: str) -> str:
    """The init script that adds a file repository named `simplonStaging` at `staging` to every project
    applying `maven-publish`, and changes nothing else. Pure."""
    return ("// Written by simplon's build:maven-pack (si#344 C.3). Adds one file repository; changes nothing else.\n"
            "allprojects {\n"
            "    plugins.withId(\"maven-publish\") {\n"
            "        publishing {\n"
            "            repositories {\n"
            "                maven {\n"
            "                    name = \"simplonStaging\"\n"
            f"                    url = uri(\"{staging}\")\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n")


def pack_argv(version: str) -> list[str]:
    """`gradle <STAGE_TASK>` with the version the tag names and the kernel's init script. Pure.

    `-Pversion=` rather than an edit to `build.gradle`: the version is a property of the RELEASE, and a
    number checked into a build file is a number two people can pick at once.

    `--no-daemon` because a Gradle daemon inside a `--rm` container is a process nobody reaps.
    """
    return ["gradle", STAGE_TASK, f"-Pversion={version}",
            "--init-script", f"{WORKDIR}/{GRADLE_HOME}/{INIT_SCRIPT}", "--no-daemon"]


#: Keys an `artifacts:` entry for this coordinate used to accept and no longer does. REFUSED rather than
#: ignored, because ignoring `task: ":core:publish"` would run the root `publish` instead - a different
#: publication with no word said, which is the defect this repository hunts. Withdrawn in 0.25.0; measured
#: before withdrawing: no reachable manifest declared it (si#337).
WITHDRAWN = ("task",)


def _declared(name: str, coordinate: str) -> artifactschema.MavenEntry:
    """The `artifacts:` entry `name` names, or a refusal listing the ones that exist.

    COPIED FROM `tasks/nuget` RATHER THAN IMPORTED, and the asymmetry with `_env_file` above is the point.
    The wording is deliberately identical - "a product reading two refusals from two publishing tasks
    should read the same sentence twice", which is `tasks/artifact`'s own note and why four siblings each
    carry this function.

    THE SECOND REASON IS THE CENSUS, and it was found by measurement rather than reasoned out. This module
    first imported `_declared` from `tasks/nuget`, every test passed, and
    `test_every_module_that_reads_the_manifest_is_accounted_for` stayed GREEN - because the population is
    derived from which modules call `manifest_data()`, and a module that borrows another's reader calls it
    nowhere. Three new manifest refusals were therefore invisible to the count whose whole purpose is that
    the sum cannot grow quietly. Reading the section here puts them back in the population. The general
    hole - a refusal decided on manifest values obtained through another module's reader - was si#331, and
    the census's `BORROWS_A_READER` now turns a borrowed reader red.

    Since si#344 B2 it hands the SECTION, never the document, to `artifactsection.entry`, which checks the
    kind, the keys and what `release:maven` needs - the census still reads that as an inline read, so the
    reasoning above holds. It asks `refuse_withdrawn` FIRST, on the raw entry: the schema would refuse `task:`
    too, as a key a maven artifact does not take, but only this sentence says what replaced it.
    """
    if not name:
        raise ValueError(f"which artifact? pin one with `with: {{ name: ... }}` from the `{SECTION}:` "
                         f"section, or pass --name")
    ctx = context.current()
    section = (ctx.manifest_data().get(SECTION) or {})
    if name not in section:
        raise ValueError(
            f"no artifact '{name}' in {ctx.manifest_path.name}'s `{SECTION}:` section; declared are: "
            f"{', '.join(sorted(section)) or '(none)'}")
    body = section[name]
    if isinstance(body, Mapping):
        refuse_withdrawn(body, name)
    return artifactsection.entry(section, name, ENTRY, ctx.manifest_path.name, coordinate)


def repository_url(registry: str, *, checked: bool = False) -> str:
    """`maven.pkg.github.com/owner/repo` -> `https://maven.pkg.github.com/owner/repo`. Pure.

    THE SCHEME IS ADDED HERE, so a manifest never carries one. With `checked=True` a scheme in the
    manifest and a host that is not GitHub's are refused BY NAME - the two refusals a product hits first,
    and the second is not tidiness: `registry:` is a manifest key and this module mints a GitHub token,
    so a product naming a third-party host would have that token posted to it.
    """
    if checked:
        if "://" in registry:
            raise ValueError(
                f"artifact registry '{registry}' carries a scheme; declare the host and the path only "
                f"(`maven.pkg.github.com/<owner>/<repo>`). The scheme is this task's, because a doubled "
                f"one produces a URL error reported as a missing package")
        if not githubpackages.is_github_packages(registry):
            raise ValueError(
                f"artifact registry '{registry}' is not GitHub's. This task sends a GitHub token, so it "
                f"publishes only to GitHub Packages - naming another host would hand that token to "
                f"somebody else. GitHub's Maven registry is `maven.pkg.github.com/<owner>/<repo>`")
    return "https://" + registry.strip("/")


def pom_url(registry: str, group: str, module: str, version: str) -> str:
    """Where one module's POM sits in Maven's layout. Pure.

    The group with every dot a directory, which is Maven's own rule and the half a hand-written check
    usually gets wrong - `info.zwyssig.firn` is three path segments, not one.
    """
    path = group.replace(".", "/")
    return f"{repository_url(registry)}/{path}/{module}/{version}/{module}-{version}.pom"


def is_snapshot(version: str) -> bool:
    """Whether `version` is a MUTABLE Maven coordinate. Pure.

    The whole of si#330's question rests on this one bit. A snapshot republishes under one coordinate,
    which is right while a shape is moving and wrong the moment something builds against it - so the two
    kinds cannot be published by the same rules, and the coordinate decides which it is rather than
    leaving every manifest to.
    """
    return version.endswith(SNAPSHOT_SUFFIX)


def refuse_withdrawn(spec: Mapping[str, object], name: str) -> None:
    """Refuse a key 0.24.0 accepted and si#337 withdrew, naming what to do instead."""
    for key in WITHDRAWN:
        if key in spec:
            raise ValueError(
                f"artifact '{name}': `{key}:` was withdrawn in 0.25.0 (si#337). `build:maven-pack` always runs "
                f"`gradle {STAGE_TASK}` and `release:maven` reads every module back from the registry - a task "
                f"that does not stage there cannot be held to that. Delete the key; a publish that is not a release "
                f"(`publishToMavenLocal`, a task with another name) is your own command through "
                f"`toolchain:run`")


def may_publish(registry: str, group: str, modules: "Sequence[str]", version: str,
                token: str) -> "tuple[bool, str]":
    """`(may we, what to say about it)` BEFORE anything is uploaded.

    THIS IS THE HALF THAT HAS TO RUN FIRST, and the reason is what a second publish of a RELEASE
    coordinate actually does: the version is immutable, so the attempt either fails part-way - leaving some
    modules uploaded and some not, which is worse than either outcome - or changes nothing while reporting
    success. Asking first turns both into one sentence naming the version.

    A SNAPSHOT IS NEVER PROBED. Republishing is its purpose, so an existence check there would refuse the
    normal case.

    AN UNASKABLE REGISTRY DOES NOT BLOCK. `401` means "we may not look", which is neither "the version is
    free" nor "it is taken" - blocking on it would make a token scope look like a version collision. It
    proceeds and says it could not check, which is the half that would otherwise be missing.
    """
    if is_snapshot(version):
        return True, (f"{version} is a snapshot: it republishes under one coordinate, so anything already "
                      f"built against it changes underneath")
    state, _ = verify(registry, group, modules, version, token)
    if state == PRESENT:
        return False, (
            f"{group}:*:{version} is already in {repository_url(registry)}, and a release version is "
            f"immutable there. Publishing again would either fail part-way - some modules replaced, some "
            f"not - or change nothing while reporting success. Cut a new version, or publish "
            f"{version}{SNAPSHOT_SUFFIX} while the shape is still moving")
    if state == UNKNOWN:
        return True, ("could not check whether this version is already published - the registry answered "
                      "neither 200 nor 404. Proceeding, because that is a token that may not read rather "
                      "than a version that is taken")
    return True, ""


def docker_argv(image: str, root: Path, env_file: Path, argv: list[str],
                lifecycle: Sequence[str] = ()) -> list[str]:
    """The container line for one gradle invocation. PURE: it assembles, it runs nothing.

    Pure for `nuget.docker_argv`'s reason: whose uid, which mount, where gradle may write and how the
    credential arrives are exactly the decisions a test should be able to read with no docker daemon in
    the room. `lifecycle` is `docker.lifecycle()`'s flags (si#412), handed in because the name in them is
    fresh per call - choosing it here would make the line impure.
    """
    return ["docker", "run", "--rm", *lifecycle,
            *docker.user_args(),
            "-v", f"{hostpath.translate(root)}:{WORKDIR}", "-w", WORKDIR,
            "--env-file", str(env_file),
            # si#325: the JVM ignores $HOME when the uid has a passwd entry, so this variable - not HOME -
            # is what keeps gradle out of a directory it cannot write.
            "-e", f"GRADLE_USER_HOME={WORKDIR}/{GRADLE_HOME}",
            image, *argv]


def _status(url: str, token: str) -> int:
    """The HTTP status of a GET against `url`, or 0 when the request could not be made at all.

    NOT `simplon.adapters.fetch`, and that is a decision rather than a missed reuse: `fetch` downloads a file with
    a progress bar and a resume, and this asks a yes/no question about one object. Widening `fetch` to
    answer it would put a credential into a function whose whole shape is about bytes on disk.

    A 0 is the "could not ask" case - DNS, a dead socket, a proxy - and it is kept distinct from every
    status the server actually sent, because the two need different advice.
    """
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return int(refused.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def verify(registry: str, group: str, modules: Sequence[str], version: str,
           token: str) -> "tuple[str, list[str]]":
    """`(state, the modules that are not there)` after a publish.

    `PRESENT` when every module answers 2xx. `ABSENT` when the registry says 404 for at least one, and
    then the list NAMES them, because a count sends a reader looking through eleven modules. `UNKNOWN`
    when any answer is neither - 401 and 403 mean the token may not look, 0 means the request never
    happened, and reporting either as "your jar is missing" points at the build file when the answer is a
    token scope.

    AN EMPTY LIST IS REFUSED, not answered (si#341). With nothing to ask about, the loop finds nothing to
    disagree with and the answer would be `PRESENT` - a true answer to a question nobody asked, which
    `publish` would print as "read back 0 module(s)" and `may_publish` as "already published". `_modules`
    keeps a manifest from getting here today, but that guarantee lived in a different function from the
    one making the claim, so it moves here: relax `_modules`, or add a caller, and this still says no.
    """
    if not modules:
        raise ValueError(
            f"verify was handed no modules for {group}:{version}, so it would report a read-back that "
            f"checked nothing. This is a caller's fault, not the registry's: `_modules` refuses an empty "
            f"`modules:` before any caller should get here")
    missing: list[str] = []
    for module in modules:
        status = _status(pom_url(registry, group, module, version), token)
        if 200 <= status < 300:
            continue
        if status == 404:
            missing.append(module)
            continue
        return UNKNOWN, []
    return (ABSENT, missing) if missing else (PRESENT, [])


def staged(staging: Path, group: str, modules: Sequence[str], version: str) -> tuple[list[Path], list[str]]:
    """The files to upload for `modules` at `version`, in upload order - each module's version directory
    with its own metadata last, then the module's `maven-metadata.xml*` - and the modules with nothing staged.

    METADATA LAST, because a reader who sees the metadata first may resolve a version whose jar is not there yet.
    """
    files: list[Path] = []
    missing: list[str] = []
    for module in modules:
        base = staging.joinpath(*group.split("."), module)
        here = base / version
        if not here.is_dir() or not any(here.glob("*.pom")):
            missing.append(module)
            continue
        inner = sorted(p for p in here.iterdir() if p.is_file())
        files += [p for p in inner if not p.name.startswith("maven-metadata")]
        files += [p for p in inner if p.name.startswith("maven-metadata")]
        files += sorted(p for p in base.glob("maven-metadata.xml*") if p.is_file())
    return files, missing


def _put(url: str, data: bytes, token: str) -> int:
    """The HTTP status of one PUT, or 0 when it could not be made - `_status`'s three-way shape."""
    request = urllib.request.Request(url, data=data, method="PUT")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return int(refused.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def upload(registry: str, staging: Path, files: Sequence[Path], token: str) -> tuple[int, str]:
    """PUT each file at its path relative to `staging`; `(0, "")`, or the first refusal and its path."""
    base = repository_url(registry)
    for path in files:
        relative = path.relative_to(staging).as_posix()
        status = _put(f"{base}/{relative}", path.read_bytes(), token)
        if not 200 <= status < 300:
            return status or 1, relative
    return 0, ""


def _modules(spec: artifactschema.MavenEntry, name: str) -> list[str]:
    """The modules `name` publishes, refusing an empty declaration by name.

    REQUIRED, and it would have been easy to make optional. Gradle knows which publications exist and
    this task does not - so without a declaration there is nothing to read back, and a publish that
    verifies nothing is the defect the read-back was added for. A product with one artifact writes a list
    of one.
    """
    declared = spec.modules
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, (list, tuple)) or not declared:
        raise ValueError(
            f"artifact '{name}' declares no `modules:`; a jar publish is verified by asking the registry "
            f"for each module's POM, so this task has to be told which coordinates to expect - gradle "
            f"knows its publications and this task does not. One artifact is a list of one")
    wrong = [item for item in declared if not isinstance(item, str) or not item]
    if wrong:
        raise ValueError(f"artifact '{name}': `modules:` is a list of module NAMES, and "
                         + ", ".join(repr(item) for item in wrong) + " is not one")
    return [str(item) for item in declared]


def _resolved(spec: artifactschema.MavenEntry, name: str, tag: str) -> str:
    resolved = tag or spec.tag or ""
    if not resolved:
        raise ValueError(
            f"artifact '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant "
            f"one, or pass --tag for a version that is only known after a build")
    return resolved


def pack(name: str = "", tag: str = "") -> int:
    """Stage the jars `name` declares into its `path:` as a Maven file repository (si#344 C.3)."""
    spec = _declared(name, "build:maven-pack")
    group = spec.group or ""
    modules = _modules(spec, name)
    pinned = docker.pinned_image(spec.image or "", f"artifact '{name}'",
                                 hint="a published jar names the JDK and Gradle it was built with")
    resolved = _resolved(spec, name, tag)
    root = context.current().root
    relative = spec.path or ""
    target = _inside_the_output_root(root, relative, name)

    docker.ensure_docker()
    # si#319: the tree this container writes has to be the CALLER'S, not merely writable.
    fault = docker.ownership_fault([outputs.root()], root)
    if fault:
        log.error(fault)
        raise ValueError(fault)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (root / GRADLE_HOME).mkdir(parents=True, exist_ok=True)
    (root / GRADLE_HOME / INIT_SCRIPT).write_text(init_script_text(f"{WORKDIR}/{relative}"), encoding="utf-8")

    with _env_file(githubpackages.token()) as env_file:
        log.info(f"staging {group}:{{{','.join(modules)}}}:{resolved} into {relative} with `gradle {STAGE_TASK}`")
        # si#412: named, labelled, and removed if this run is interrupted.
        container, lifecycle = docker.lifecycle()
        with docker.stopped_on_interrupt(container):
            rc = stream(docker_argv(pinned, root, env_file, pack_argv(resolved), lifecycle))
    if rc != 0:
        log.error(f"`gradle {STAGE_TASK}` failed (rc={rc}; see output above)")
        return rc
    _, missing = staged(target, group, modules, resolved)
    if missing:
        log.error(f"`gradle {STAGE_TASK}` exited 0 and staged nothing for {', '.join(missing)} at {resolved} "
                  f"under {relative}. A module without a `maven-publish` publication has nothing to publish "
                  f"and does not fail for it - which is what this check exists to catch")
        return 1
    log.ok(f"staged {len(modules)} module(s) as {group}:*:{resolved} into {relative}")
    return 0


def push(name: str = "", tag: str = "") -> int:
    """Upload what `build:maven-pack` staged for this version and read it back (si#344 C.3)."""
    spec = _declared(name, "release:maven")
    (registry, group) = (spec.registry or "", spec.group or "")
    repository_url(registry, checked=True)
    modules = _modules(spec, name)
    resolved = _resolved(spec, name, tag)
    root = context.current().root
    relative = spec.path or ""
    staging = (root / relative).resolve()
    files, missing = staged(staging, group, modules, resolved)
    if missing:
        raise ValueError(f"nothing staged for {resolved} under {relative}: run `build:maven-pack` first "
                         f"(missing: {', '.join(missing)})")

    token = githubpackages.token()
    # si#330: a release version that is already published is refused BEFORE anything is uploaded, because
    # the alternative is a half-replaced coordinate.
    allowed, said = may_publish(registry, group, modules, resolved, token)
    if not allowed:
        log.error(said)
        return 1
    if said:
        log.warn(said)

    log.info(f"uploading {len(files)} file(s) of {group}:{{{','.join(modules)}}}:{resolved} to "
             f"{repository_url(registry)}")
    status, refused = upload(registry, staging, files, token)
    if status != 0:
        log.error(f"the registry refused {refused} (HTTP {status})\n"
                  f"if it refused rather than the network, the usual cause is a token without the package "
                  f"scopes:\n" + githubpackages.scope_advice())
        return 1

    state, missing_back = verify(registry, group, modules, resolved, token)
    if state == ABSENT:
        log.error(f"every upload was accepted and {repository_url(registry)} does not carry "
                  f"{', '.join(f'{group}:{m}:{resolved}' for m in missing_back)}")
        return 1
    if state == UNKNOWN:
        log.warn(
            f"uploaded, but this task could not VERIFY it: {repository_url(registry)} answered neither "
            f"200 nor 404 for the modules' POMs. That is a token that may not read the registry, or a "
            f"request that never arrived - not evidence that the jars are missing.\n"
            + githubpackages.scope_advice())
        return 0
    # WHAT THE OK LINE MAY CLAIM DIFFERS BY KIND (si#330): for a release the read-back proves this run put
    # the artefact there, because `may_publish` established it was absent beforehand; for a snapshot only
    # presence.
    if is_snapshot(resolved):
        log.ok(f"{len(modules)} module(s) present as {group}:*:{resolved} at {repository_url(registry)} - a "
               f"snapshot, so this confirms they are THERE and not that this run put them there")
    else:
        log.ok(f"uploaded and read back {len(modules)} module(s) as {group}:*:{resolved} at "
               f"{repository_url(registry)}")
    return 0
