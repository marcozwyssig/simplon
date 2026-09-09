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

from xml.sax.saxutils import quoteattr

from simplon import context, githubpackages, log

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


def index_url(registry: str) -> str:
    """`nuget.pkg.github.com/owner` -> `https://nuget.pkg.github.com/owner/index.json`. Pure.

    DERIVED rather than declared, so `registry:` is one fact read by two things: this URL, and
    `githubpackages.is_github_packages`, which decides whether the credential may go there at all. A
    second key holding the URL would be the copy that drifts, and the drift would send a token to
    whatever the copy said.

    A scheme is accepted and dropped because a manifest author will write one - the URL they know is the
    one with `https://` in it - and refusing that would be pedantry about a value this function is
    normalising anyway.
    """
    bare = registry.split("://", 1)[-1].strip("/")
    if "/" not in bare:
        raise ValueError(
            f"registry '{registry}' names no owner: GitHub's NuGet feed is per account, so the value has "
            f"to be `{bare}/<owner>`. Without the owner the index URL is a 404 that says nothing about "
            f"the manifest")
    return f"https://{bare}/index.json"


def owner(registry: str) -> str:
    """The account a feed belongs to: `owner` out of `nuget.pkg.github.com/owner`. Pure."""
    return registry.split("://", 1)[-1].strip("/").split("/", 1)[1]


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


def _github_registry(spec: dict, name: str) -> str:
    """The registry, refused unless it is GitHub's own.

    The generated block writes `%GITHUB_TOKEN%`, so a config for somebody else's host would instruct
    every build in the tree to send a GitHub PAT there - the exact failure `is_github_packages` exists
    to prevent, one level removed from the login it usually guards. A product publishing elsewhere writes
    its own config; the kernel does not generate one it cannot vouch for.
    """
    (registry,) = _required(spec, name, "registry")
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
    source_name = str(spec.get("source_name", "") or DEFAULT_SOURCE)

    root = context.current().root
    target = root / CONFIG_NAME
    target.write_text(config_text(source_name, index_url(registry), owner(registry)), encoding="utf-8")
    log.ok(f"wrote {CONFIG_NAME} naming '{source_name}' -> {index_url(registry)} "
           f"(the credential is %{TOKEN_VAR}%, read from the environment, never from this file)")
    return 0
