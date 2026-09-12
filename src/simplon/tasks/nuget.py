"""`release:nuget`, `build:nuget-config`, `build:nuget-restore` - hand a .NET library over, and take one (si#127).

WHY ALL THREE ARE THE KERNEL'S, AND WHY THEY ARE ONE MODULE. si#102 landed a uniform build that
compiles a .NET solution in a container and runs the assembly; what it could not do was hand the result
to anybody. Publishing is `dotnet pack` and `dotnet nuget push`, consuming is a source declaration and a
credential, and neither is a product's own business: they are the same eight lines wherever a product
publishes, and the one place a token can be got wrong. What stays the product's is DATA - which registry,
which project, which tag - and all of it arrives through the manifest's `artifacts:` section, the
neighbour `release:artifact` already reads (design section 2: the cluster adds no top-level section).

PUBLISHING ALONE IS HALF A FEATURE, which is si#127's own decision and the reason `build:nuget-config`
and `build:nuget-restore` are here rather than in a ticket after this one. A package nobody can resolve
has not been handed over.

WHERE THE TOKEN GOES, AND THE THREE MEASUREMENTS THAT DECIDE IT. Driven on 2026-09-09 against a real
authenticated NuGet v3 feed (BaGet behind an nginx basic-auth proxy - the shape GitHub Packages
authenticates in: an Authorization header), in the .NET 9 SDK image:

  - `dotnet nuget push --source <url> --api-key <key>` against an authenticated feed answers
    `Unable to load the service index ... 401 (Unauthorized)`. **An api key is not a credential.**
  - A `packageSourceCredentials` entry whose `ClearTextPassword` is the literal text `%VARNAME%` is
    EXPANDED from the environment, on Linux, and authenticated both a push and a restore. **This is the
    fact the whole design rests on:** the generated `nuget.config` holds a variable NAME, so it is a file
    a repository can carry, and si#127's one security requirement ("it must not land in a generated
    nuget.config that someone commits") is met by construction rather than by a warning in a doc.
  - The `<apikeys>` section cannot hold a key on Linux at all: `error: Encryption is not supported on
    non-Windows platforms.` So an api key cannot be moved out of argv by putting it in the config, and a
    design that tried would have failed on every host this kernel runs on. Named here so the next reader
    does not spend the measurement again.
  - `dotnet nuget push --source <named source>` with NO `--api-key` pushes successfully when the source
    carries credentials, warning `No API Key was provided` and proceeding. So the token never has to be
    an argv element, and this module never makes it one.

The token reaches the container through `docker run --env-file`, a 0600 file in a temp directory removed
in a `finally` - not `-e GITHUB_TOKEN=<value>`, because that IS argv, readable in `docker inspect` and in
the host's /proc. `githubpackages` states the same rule for `oras login` and `docker login`, where the
answer is stdin; here the answer is a file, because docker offers no stdin for an environment.

WHAT IS NOT PROVEN, said here rather than in a commit message nobody re-reads: the GitHub Packages
endpoint itself. Every mechanism above is driven against a feed that authenticates the same way, but the
machine this was built on carries a `gh` token without `read:packages`/`write:packages` and
`gh auth refresh` needs an interactive device flow. That GitHub accepts a keyless push is inferred from
the fourth measurement and is not measured.

TWO FACTS INHERITED FROM si#102, both of which cost a measurement there:

  - `dotnet` under `docker.user_args()` needs `DOTNET_CLI_HOME`. As uid 1000 it dies on `/.dotnet`
    denied and as uid 0 it passes, which is why it had to be measured rather than reasoned about. Every
    container this module starts sets it, into a directory inside the mounted tree.
  - The target framework must match the SDK image. `net8.0` BUILDS in a 9.0 image and then refuses to
    run with rc 150. This module cannot check that - it is a property of the product's `.csproj` - but
    the docs page says it, because the failure names neither.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from xml.sax.saxutils import quoteattr

from simplon import context, docker, githubpackages, hostpath, log
from simplon.run import stream

#: The manifest section this module reads. `artifacts:` rather than a new top-level key, per design
#: section 2: a registry, a package and a scope are the same three facts whatever the ecosystem, and a
#: section is cheap to add and expensive to remove.
SECTION = "artifacts"

#: The file NuGet reads, at the product root. NuGet walks up from the project directory, so one file at
#: the root serves every project in the tree - which is what makes a single generated file honest.
CONFIG_NAME = "nuget.config"

#: The environment variable the generated config refers to, and the one the token is written into when a
#: container is started. `githubpackages.token()` reads the same name first, so a caller who exported one
#: sees it used rather than a second one invented beside it.
TOKEN_VAR = "GITHUB_TOKEN"

#: Where `dotnet` may keep its per-user state. si#102 measured the failure without it; the path is inside
#: the mounted tree because that is the one directory a container running as the caller can always write.
CLI_HOME = "build/dotnet-home"

#: The default name the generated config gives GitHub's feed. A manifest may choose another with
#: `source_name:`; both halves read the same key, so the push and the restore cannot disagree.
DEFAULT_SOURCE = "github"

#: What a source name may be. It becomes an XML ELEMENT NAME in `packageSourceCredentials`, not an
#: attribute value, so escaping is not available to it: a space or a bracket produces a file NuGet
#: cannot parse, and the error a reader gets then is about XML rather than about the key they typed.
#: The pattern is XML's own NCName narrowed to ASCII, which is every name anybody would actually write.
SOURCE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")


def _declared(name: str) -> dict:
    """The `artifacts:` entry `name` names, or a refusal listing the ones that exist.

    The wording and the shape are `simplon.tasks.artifact`'s, deliberately: a product reading two
    refusals from two publishing tasks should read the same sentence twice.
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
    return dict(section[name])


def _required(spec: dict, name: str, *keys: str) -> list[str]:
    """The values of `keys`, refusing by KEY as soon as one is missing.

    One at a time rather than a list of all of them: a reader fixes the first, runs again, and is told
    the next - which is a shorter loop than being handed four keys and guessing which shape they want.
    """
    values = []
    for key in keys:
        value = str(spec.get(key, "") or "")
        if not value:
            raise ValueError(f"artifact '{name}' declares no `{key}:`; a NuGet package needs "
                             f"{', '.join(keys)}")
        values.append(value)
    return values


def _without_a_scheme(registry: str) -> str:
    """`registry` with its trailing slashes gone, refusing a scheme by name. Pure.

    CALLED FROM THE CHECK AND FROM THE URL, and the order is the whole reason it exists as a function:
    `_github_registry` runs FIRST, and `githubpackages.registry_host` splits on `/` - so without this,
    `https://nuget.pkg.github.com/owner` was refused as "not GitHub Packages" (the host it read was
    `https:`), which is a message about the wrong thing entirely and sends the reader to the wrong key.
    """
    bare = registry.strip("/")
    if "://" in bare:
        raise ValueError(
            f"registry '{registry}' carries a scheme: write it the way every other `registry:` in a "
            f"manifest is written, without the scheme - `{bare.split('://', 1)[-1]}`. The credential "
            f"check reads this value as a host, and a scheme makes it read `{bare.split(':', 1)[0]}:` "
            f"as one")
    return bare


def index_url(registry: str) -> str:
    """`nuget.pkg.github.com/owner` -> `https://nuget.pkg.github.com/owner/index.json`. Pure.

    DERIVED rather than declared, so `registry:` is one fact read by two things: this URL, and
    `githubpackages.is_github_packages`, which decides whether the credential may go there at all. A
    second key holding the URL would be the copy that drifts, and the drift would send a token to
    whatever the copy said.

    A SCHEME IS REFUSED rather than dropped, and that is a correction: dropping it here left the two
    functions disagreeing about what a registry string is. `githubpackages.registry_host` splits on `/`
    and reads `https:` as the host, so `_github_registry` - which runs FIRST - already refused
    `https://nuget.pkg.github.com/owner` as "not GitHub Packages", a message about the wrong thing
    entirely. One spelling for `registry:` across the kernel, and a refusal that names the key.
    """
    bare = _without_a_scheme(registry)
    if "/" not in bare:
        raise ValueError(
            f"registry '{registry}' names no owner: GitHub's NuGet feed is per account, so the value has "
            f"to be `{bare}/<owner>`. Without the owner the index URL is a 404 that says nothing about "
            f"the manifest")
    return f"https://{bare}/index.json"


def owner(registry: str) -> str:
    """The account a feed belongs to: `owner` out of `nuget.pkg.github.com/owner`. Pure.

    Called only after `index_url` has ruled on the same string, which is what makes the index safe.
    """
    return registry.strip("/").split("/", 1)[1]


def config_text(source_name: str, url: str, user: str) -> str:
    """The whole `nuget.config`, as text. Pure, and it renders a VARIABLE NAME rather than a secret.

    `<clear />` first, and it is the line with the most consequence in the file: without it, a source
    configured machine-wide joins the restore and two machines resolve the same reference differently.
    A generated file exists to close exactly that, so it starts by discarding what it did not write.

    nuget.org is then named explicitly, because clearing it is not the intent - a product's own
    dependencies still come from there, and leaving them to an inherited config would be the same
    defect one level down.
    """
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Written by `build:nuget-config`. Edits are overwritten; change the manifest's\n"
        f"     `{SECTION}:` section instead. It holds NO credential: {TOKEN_VAR} is read from the\n"
        "     environment when NuGet reads this file, so this is a file a repository may carry. -->\n"
        "<configuration>\n"
        "  <packageSources>\n"
        "    <clear />\n"
        '    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />\n'
        f"    <add key={quoteattr(source_name)} value={quoteattr(url)} />\n"
        "  </packageSources>\n"
        "  <packageSourceCredentials>\n"
        f"    <{source_name}>\n"
        f"      <add key=\"Username\" value={quoteattr(user)} />\n"
        f'      <add key="ClearTextPassword" value="%{TOKEN_VAR}%" />\n'
        f"    </{source_name}>\n"
        "  </packageSourceCredentials>\n"
        "</configuration>\n")


def _source_name(spec: dict, name: str) -> str:
    """The name the config gives the feed, refused unless it can be an XML element.

    Read here rather than in three task bodies, because a name the publish accepted and the config
    rejected would be a transport whose two ends do not meet - `--source github` against a file that
    never declared one.
    """
    chosen = str(spec.get("source_name", "") or DEFAULT_SOURCE)
    if not SOURCE_NAME.fullmatch(chosen):
        raise ValueError(
            f"artifact '{name}' declares `source_name: {chosen!r}`, which cannot be an XML element "
            f"name. It becomes one in the generated {CONFIG_NAME}, so it has to start with a letter or "
            f"an underscore and carry only letters, digits, `_`, `-` and `.`")
    return chosen


def _github_registry(spec: dict, name: str) -> str:
    """The registry, refused unless it is GitHub's own.

    The generated block writes `%GITHUB_TOKEN%`, so a config for somebody else's host would instruct
    every build in the tree to send a GitHub PAT there - the exact failure `is_github_packages` exists
    to prevent, one level removed from the login it usually guards. A product publishing elsewhere writes
    its own config; the kernel does not generate one it cannot vouch for.
    """
    (registry,) = _required(spec, name, "registry")
    _without_a_scheme(registry)
    if not githubpackages.is_github_packages(registry):
        raise ValueError(
            f"artifact '{name}' names registry '{registry}', which is not GitHub Packages "
            f"({', '.join(sorted(githubpackages.GITHUB_PACKAGE_HOSTS))}). This task writes a credential "
            f"block referring to %{TOKEN_VAR}%, and pointing that at another host would tell every build "
            f"in the tree to send a GitHub token there")
    return registry


def config(name: str = "") -> int:
    """Write the product's `nuget.config` from the artefact `name` declares.

    The file is COMMITTED, which is the whole point of the variable reference: the source a build resolves
    against is reviewable in the repository, and the credential is not in it.
    """
    spec = _declared(name)
    registry = _github_registry(spec, name)
    source_name = _source_name(spec, name)

    root = context.current().root
    target = root / CONFIG_NAME
    target.write_text(config_text(source_name, index_url(registry), owner(registry)), encoding="utf-8")
    log.ok(f"wrote {CONFIG_NAME} naming '{source_name}' -> {index_url(registry)} "
           f"(the credential is %{TOKEN_VAR}%, read from the environment, never from this file)")
    return 0


# --- publishing ---------------------------------------------------------------------------------------

#: Where the packed .nupkg lands inside the container. Under `build/` because that is what a product
#: gitignores, and the same directory the second command reads it back from - the two are one fact.
PACK_DIR = "build/nuget"

#: The container's view of the product tree. `/work`, the same mount point `toolchain:run` uses, so a
#: path printed by one command means the same thing in the other.
WORKDIR = "/work"


@contextmanager
def _env_file(token: str) -> Iterator[Path]:
    """A 0600 file holding `GITHUB_TOKEN=<token>`, gone by the time this returns.

    WHY A FILE AND NOT `-e NAME=VALUE`. `docker run -e GITHUB_TOKEN=ghp_...` puts the credential in the
    docker CLI's own argv, which `ps` shows to every user on the machine and `docker inspect` keeps in
    the container's config for as long as it exists. `githubpackages` states the rule for `oras login`
    and `docker login`, where the answer is stdin; docker offers no stdin for an environment, so the
    answer here is a file that only its owner can read and that does not outlive the call.

    `delete=False` plus a `finally`, rather than an open handle: docker has to open the path itself, and
    on a crashed run the deletion still has to happen - which is the case the `finally` is for.
    """
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".env", delete=False)
    path = Path(handle.name)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        handle.write(f"{TOKEN_VAR}={token}\n")
        handle.close()
        yield path
    finally:
        handle.close()
        path.unlink(missing_ok=True)


def docker_argv(image: str, root: Path, env_file: Path, argv: list[str]) -> list[str]:
    """The container line for one dotnet invocation. PURE: it assembles, it runs nothing.

    Pure for the reason `toolchain.docker_argv` is pure: the decisions here - whose uid, which mount,
    where dotnet may write, how the credential arrives - are exactly what a test should be able to read
    without a docker daemon in the room.

    NOT `toolchain.docker_argv`, and that is a decision rather than a missed reuse. That function takes a
    `Toolchain` built out of a manifest `with:` block, whose environment is "the environment the manifest
    names, and nothing else - no implicit inheritance from the caller"; a secret is precisely what a
    manifest may not name, so it has no `--env-file`. Widening it would put a credential into the one
    shape si#105 wrote to keep declarations reviewable.
    """
    return ["docker", "run", "--rm",
            *docker.user_args(),
            "-v", f"{hostpath.translate(root)}:{WORKDIR}", "-w", WORKDIR,
            "--env-file", str(env_file),
            "-e", f"DOTNET_CLI_HOME={WORKDIR}/{CLI_HOME}",
            "-e", "DOTNET_CLI_TELEMETRY_OPTOUT=1", "-e", "DOTNET_NOLOGO=1",
            image, *argv]


def pack_argv(project: str, version: str) -> list[str]:
    """`dotnet pack`, with the version the tag names. Pure.

    `-p:PackageVersion=` rather than an edit to the .csproj: the version is a property of the RELEASE,
    and a number checked into a project file is a number two people can pick at once - the argument
    `release:tag` is built on, one level down.
    """
    return ["dotnet", "pack", project, "-c", "Release", "-o", f"{WORKDIR}/{PACK_DIR}",
            f"-p:PackageVersion={version}"]


def push_argv(source_name: str) -> list[str]:
    """`dotnet nuget push`, with NO api key. Pure.

    MEASURED, and the module head carries the transcript: `--api-key` alone does not authenticate
    against a feed that wants an Authorization header (401), the `<apikeys>` config section cannot hold
    one on Linux at all, and a push against a source that carries credentials needs none. So the one
    element that would have had to be a secret is not there, and the warning NuGet prints about it
    ("No API Key was provided") is the sound of the design working.
    """
    return ["dotnet", "nuget", "push", f"{WORKDIR}/{PACK_DIR}/*.nupkg",
            "--source", source_name, "--skip-duplicate"]


def publish(name: str = "", tag: str = "") -> int:
    """Pack the project `name` declares and push it to the GitHub feed `name` names.

    Two container runs rather than one shell line, because a shell line is a third quoting layer between
    the manifest and the tool, and the rc of a pipeline is not the rc of the command that failed.
    """
    registry, pinned, project = _for_container(name)
    spec = _declared(name)
    source_name = _source_name(spec, name)

    resolved = tag or str(spec.get("tag", "") or "")
    if not resolved:
        raise ValueError(
            f"artifact '{name}' has no tag: declare `tag:` in the `{SECTION}:` section for a constant "
            f"one, or pass --tag for a version that is only known after a build")

    root = context.current().root
    _config_or_refuse(root, source_name)
    if not (root / project).is_file():
        raise ValueError(f"nothing to pack: {project} does not exist under the product root. the "
                         f"project is the product's, not this task's")

    docker.ensure_docker()
    (root / PACK_DIR).mkdir(parents=True, exist_ok=True)
    (root / CLI_HOME).mkdir(parents=True, exist_ok=True)

    with _env_file(githubpackages.token()) as env_file:
        log.info(f"packing {project} as {resolved}")
        rc = stream(docker_argv(pinned, root, env_file, pack_argv(project, resolved)))
        if rc != 0:
            log.error(f"dotnet pack {project} failed (rc={rc}; see output above)")
            return rc

        log.info(f"pushing {resolved} to {index_url(registry)}")
        rc = stream(docker_argv(pinned, root, env_file, push_argv(source_name)))

    if rc != 0:
        # The scope advice is a HINT tied to a host and a condition, never appended to every failure -
        # image.py's rule, and the reason is that a push fails on a full disk and a dead network too.
        log.error(f"dotnet nuget push to {registry} failed (rc={rc}; see output above)\n"
                  "if the registry refused it rather than the network, the usual cause is a token "
                  "without the package scopes:\n" + githubpackages.scope_advice())
        return rc

    log.ok(f"published {resolved} to {index_url(registry)}")
    return 0


# --- consuming ----------------------------------------------------------------------------------------

def _for_container(name: str) -> tuple[str, str, str]:
    """The three things both container commands need: registry, pinned image, project. Refuses by key.

    Shared by `publish` and `restore` because the refusals are the ones a product hits FIRST, and two
    copies of them are two wordings a reader would have to learn.
    """
    spec = _declared(name)
    registry = _github_registry(spec, name)
    (image, project) = _required(spec, name, "image", "project")
    pinned = docker.pinned_image(image, f"artifact '{name}'",
                                 hint="a published package names the SDK it was built with")
    return registry, pinned, project


def _config_or_refuse(root: Path, source_name: str) -> None:
    """The generated config has to be there, and the message names the command that writes it.

    Without it there is no source called `<source_name>` and no credential to reach it with, and what
    NuGet says instead is that a package could not be found - a sentence about the package, in a failure
    about the configuration.
    """
    if not (root / CONFIG_NAME).is_file():
        raise ValueError(
            f"no {CONFIG_NAME} at the product root, so there is no source called '{source_name}' and no "
            f"credential to reach it with. Write one first: `build:nuget-config`")


def restore(name: str = "") -> int:
    """Restore the project `name` declares, with the credential the container needs.

    A COORDINATE OF ITS OWN rather than a `toolchain:run` command, and the reason is si#105's rule
    rather than a preference: a toolchain command's environment is what the manifest names and nothing
    else, and a token is exactly what a manifest may not name. So the consuming half of si#127 needs a
    runner that can put a secret into a container, and a product cannot declare one.
    """
    registry, pinned, project = _for_container(name)
    spec = _declared(name)
    source_name = _source_name(spec, name)

    root = context.current().root
    _config_or_refuse(root, source_name)
    if not (root / project).is_file():
        raise ValueError(f"nothing to restore: {project} does not exist under the product root")

    docker.ensure_docker()
    (root / CLI_HOME).mkdir(parents=True, exist_ok=True)

    with _env_file(githubpackages.token()) as env_file:
        log.info(f"restoring {project} against {index_url(registry)}")
        rc = stream(docker_argv(pinned, root, env_file, ["dotnet", "restore", project]))

    if rc != 0:
        log.error(f"dotnet restore {project} failed (rc={rc}; see output above)\n"
                  "if the feed refused it rather than the network, the usual cause is a token without "
                  "the package scopes - `read:packages` is the one a CONSUMER needs:\n"
                  + githubpackages.scope_advice())
        return rc

    log.ok(f"restored {project} from {index_url(registry)}")
    return 0
