---
title: "Handing a package over"
weight: 10
---

A build that nobody else can consume is half a build. This chapter is the other half: how a .NET product
publishes a library that a second product resolves, and how a C++ product hands a Conan package to one -
which turns out to be a different act entirely, for a reason that has nothing to do with C++.

## The short version

| you have | you publish with | a consumer gets it with |
|---|---|---|
| a .NET library | `release:nuget` | `build:nuget-config`, then an ordinary restore |
| a Conan package | `release:conan` | `build:conan-cache`, then `conan cache restore` |

Both read the manifest's existing `artifacts:` section - the same one `release:artifact` reads. There is
no new top-level key, and that is a decision: a section is cheap to add and expensive to remove, and a
registry, a package name and a scope are the same three facts whatever the ecosystem.

## NuGet: an ordinary registry

GitHub Packages serves NuGet natively, so both directions are ordinary commands against
`https://nuget.pkg.github.com/<owner>/index.json`.

```yaml
artifacts:
  corelib:
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    tag: 1.4.0
```

`release:nuget` runs `dotnet pack` and then `dotnet nuget push`, both inside the pinned SDK image. The
version comes from `--tag` if you pass one and from `tag:` if you do not - the same rule
`release:artifact` follows, and for the same reason: some products know their number before the build
and some only after it.

### The credential, and why it is not in the file

`build:nuget-config` writes the product's `nuget.config`. **That file is meant to be committed, and it
holds no token.** What it holds is the *name* of an environment variable:

```xml
<packageSourceCredentials>
  <github>
    <add key="Username" value="marcozwyssig" />
    <add key="ClearTextPassword" value="%GITHUB_TOKEN%" />
  </github>
</packageSourceCredentials>
```

NuGet expands `%GITHUB_TOKEN%` from the environment when it reads the file. That was measured on Linux
with the .NET 9 SDK rather than assumed, because the whole design rests on it: if it did not work, the
only remaining options would put a secret either into a file somebody commits or onto a command line
anybody with `ps` can read.

{{< callout type="warning" >}}
**Three neighbouring things that do not work, so you do not spend the afternoon finding out.**

`dotnet nuget push --api-key <token>` alone does **not** authenticate against a feed that wants an
`Authorization` header. Measured: `Unable to load the service index ... 401 (Unauthorized)`. An api key
is not a credential.

The `<apikeys>` section of a `nuget.config` cannot hold a key on Linux at all. Measured:
`error: Encryption is not supported on non-Windows platforms.` So you cannot move a key out of the
command line by putting it in the config.

A push against a source that already carries credentials needs **no** api key. Measured: it warns
`No API Key was provided` and pushes. That is why `release:nuget` puts nothing secret on a command line -
there is nothing it has to put there.
{{< /callout >}}

The token itself reaches the container as a `--env-file` that is created 0600, used, and deleted in a
`finally` - never as `-e GITHUB_TOKEN=<value>`, which `docker inspect` keeps and `ps` shows.

### Consuming, which is a coordinate and not a toolchain command

`build:nuget-restore` exists because a product **cannot** declare it. A `toolchain:run` command's
environment is what the manifest names and nothing else, and a token is exactly what a manifest may not
name. So the one step that has to carry a secret into a container is the kernel's.

{{< callout type="info" >}}
**Two facts inherited from the uniform build, both of which cost a measurement there.**

`dotnet` under a container running as the calling user needs `DOTNET_CLI_HOME`. As uid 1000 it dies on
`/.dotnet` denied; as uid 0 it passes - which is why it had to be measured rather than reasoned about.
Every container these coordinates start sets it.

**The target framework must match the SDK image.** `net8.0` *builds* in a 9.0 image and then refuses to
run with rc 150. Nothing in this kernel can check that for you: it is a property of your `.csproj`.
{{< /callout >}}

## Conan: a transport, not a remote

**GitHub Packages has no Conan registry.** The kinds it serves are npm, RubyGems, Maven, Gradle, NuGet
and Docker/Container - and nothing else. So the NuGet shape above simply cannot be built for Conan, and
what `release:conan` does instead is move a file.

`conan cache save` writes the recipes and binaries of a package list to a `.tgz`. `release:conan` pushes
that archive into a registry as an ordinary OCI artifact - the same mechanism `release:artifact` uses -
and `build:conan-cache` pulls it back. The consumer then runs `conan cache restore` and builds against
its own cache.

```yaml
artifacts:
  cpplib:
    registry: ghcr.io/marcozwyssig
    repository: demo-conan
    source: build/conan/demo.tgz
    media_type: application/vnd.conan.cache.v1+tgz
```

{{< callout type="warning" >}}
**Read this as a transport, because it is not a remote.** There is no `conan install` resolution against
the registry. There are no version ranges. No dependency graph is solved remotely. The consumer names an
**exact tag**, pulls it, and restores what was in it.

If you design around "Conan packages in GitHub Packages" expecting the usual remote semantics, every one
of those four sentences will surprise you later, in somebody else's build.
{{< /callout >}}

### Whether Conan could do better by itself

It is a fair question, and it was measured rather than looked up. Conan 2.32.0:

```text
$ conan remote add --help
  -t {local-recipes-index}, --type {local-recipes-index}   Define the remote type
```

`local-recipes-index` is the only remote type Conan accepts. There is no OCI remote, no `oci://` scheme
and no container-registry backend, so pointing Conan at GHCR is not an option that was passed over - it
does not exist. What would reopen this design is countable: a second value in that list.

### Why the kernel does not run Conan for you

`conan cache save` and `conan cache restore` stay your own `toolchain:run` commands, against your own
cache volume, with your own package pattern. The kernel moves a file and knows nothing about what is in
it. A kernel that learned a package manager's cache semantics would be a kernel that learned a language
toolchain, which is the thing it refuses to do everywhere else.

### Why the two halves are not symmetric

The .NET consumer needs the credential *inside* the container, because `dotnet restore` is what talks to
the feed. The Conan consumer does not: the whole registry conversation happens on the host, and what
reaches the container is a path. That asymmetry is the design, not an omission in one of the two.

## When a publish is refused

Both halves send a GitHub token only to GitHub's own hosts - `ghcr.io` and `nuget.pkg.github.com`.
Point either at another registry and the answer is a refusal that names the host, not a token quietly
handed to whoever the manifest named.

And the failure everyone hits once: `gh auth login` does not request the package scopes. The fix is in
every message that could be caused by it -

```text
gh auth refresh -h github.com -s read:packages,write:packages
```

`read:packages` is the one a **consumer** needs, which is worth knowing because the first person to hit
it is usually not the person who published.
