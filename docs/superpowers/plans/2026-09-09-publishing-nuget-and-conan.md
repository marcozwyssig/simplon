# Publishing a package: NuGet natively, Conan as a transport - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A .NET product can publish a library to GitHub Packages and a second product can resolve it; a
C++ product can hand a Conan package over as an OCI artifact and a second one can restore it into an
empty cache and build against it.

**Architecture:** Two task modules beside the `release:artifact` / `release:asset` / `release:image`
family, reading the manifest's existing `artifacts:` section. The mechanics are the kernel's, the data is
the product's, and the credential story is the one `githubpackages` already owns - widened by exactly one
host, never duplicated.

**Tech Stack:** Python 3.11+, pytest, mypy. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-the-language-cluster-design.md`, sections 2, 6, 7 and 8.
**Tickets:** si#127 (NuGet), si#128 (Conan).

---

## The open question the design left, answered by measurement

Design section 8 asks whether Conan 2 speaks an OCI remote natively by now, because si#128's transport
design rests on it not doing so. Measured on 2026-09-09 against the current release rather than read off a
blog post:

```
$ docker run --rm python:3.12-slim sh -c 'pip install -q conan; conan --version; conan remote add --help'
Conan version 2.32.0
usage: conan remote add [-h] [--out-file OUT_FILE] ... [-t {local-recipes-index}] [--recipes-only] name url
  -t {local-recipes-index}, --type {local-recipes-index}
                        Define the remote type
```

`local-recipes-index` is the ONLY remote type Conan 2.32.0 accepts. There is no OCI remote, no
`oci://` URL scheme and no container-registry backend, and the published documentation for the same
command lists the same single value. **The transport design stands unchanged**, and si#128's premise is
now a measurement rather than an assumption.

What would reopen it is countable, the way si#128's own rejected-alternative section asks for: a second
value in that `-t` list.

## The four measurements the NuGet half rests on

Driven against a real authenticated NuGet v3 feed (BaGet behind an nginx basic-auth proxy, which is the
shape GitHub Packages authenticates in - an `Authorization` header, not a query parameter), with the
.NET 9 SDK image the kernel's `dotnet` profile names:

1. **`--api-key` alone does not authenticate.** `dotnet nuget push --source <url> --api-key <key>` against
   the authenticated feed answers `Unable to load the service index ... 401 (Unauthorized)`. The api key is
   not a credential; it is a header the server may additionally require.
2. **NuGet expands `%VAR%` in `nuget.config` on Linux.** A `packageSourceCredentials` entry whose
   `ClearTextPassword` is the literal text `%NUGET_PROBE_TOKEN%` authenticated a push and a restore when
   that variable was set in the container's environment. **This is the fact the whole consume design
   rests on:** the generated `nuget.config` is committable, because it holds a variable NAME and never a
   token.
3. **The `<apikeys>` config section cannot hold a key on Linux.** `dotnet nuget push` against a config
   carrying one answers `error: Encryption is not supported on non-Windows platforms.` So an api key
   cannot be moved out of argv by putting it in the config, and any design that tried would have failed
   only on Linux, which is every host this kernel runs on.
4. **A push needs no api key when the source carries credentials.** `dotnet nuget push --source <named
   source>` with no `--api-key` at all pushed successfully, warning `No API Key was provided` and
   proceeding. Together with (1) and (3) this settles the design: **the token never reaches argv**, it
   reaches the container's environment, and NuGet reads it out of the config by name.

**What is NOT measured, and must be said plainly wherever this is claimed:** the GitHub Packages leg
itself. The `gh` token on the machine this was built on carries `gist, read:org, repo, workflow` and not
`read:packages, write:packages`, and `gh auth refresh` needs an interactive device flow. Every mechanism
above is proven against a real HTTP feed that authenticates the same way; that GitHub's own endpoint
accepts a keyless push is inferred from (4) and is NOT proven here.

## Global Constraints

- **One token story.** `githubpackages.token()`, `PACKAGE_SCOPES`, `scope_advice()` and
  `is_github_packages()` are reused, never re-implemented. `is_github_packages` gains exactly one host
  (`nuget.pkg.github.com`) because GitHub's NuGet registry is not on `ghcr.io`; nothing else about the
  module changes.
- **A token never lands in a committed file and never in argv.** The generated `nuget.config` holds
  `%GITHUB_TOKEN%`. The resolved token reaches a container through `docker run --env-file <0600 temp
  file>`, removed in a `finally`.
- **No new top-level manifest section** (design section 2). Both halves extend `artifacts:`. Each task
  validates its OWN keys by name; there is no `kind:` discriminator, because the command that pins
  `with: { name: ... }` also pins the task, so the task already knows the shape it wants.
- **Five new coordinates, all DECLARED, none placed.** Every one of them reads a manifest section or
  publishes, so placing any of them would hand every product a command that dies on its first line.
- **The seven counted guards go red the moment the coordinates exist. Task 7 is not optional, and no
  guard is weakened, skipped or reshaped to make it pass.**

**Before Task 1, read** `src/simplon/tasks/image.py` and `src/simplon/tasks/artifact.py` in full. They are
the shape this follows: a `SECTION` constant, a `_declared` reader that names every missing key, a login
that is skipped with a spoken reason for a non-GitHub host, and a thin executor. Do not invent a
different one.

---

## The coordinates, and why each exists

| coordinate | impl | what it is |
|---|---|---|
| `release:nuget` | `simplon.tasks.nuget:publish` | `dotnet pack` + `dotnet nuget push`, in the pinned SDK image |
| `build:nuget-config` | `simplon.tasks.nuget:config` | writes the committable `nuget.config` naming the source |
| `build:nuget-restore` | `simplon.tasks.nuget:restore` | `dotnet restore`, with the credential the container needs |
| `release:conan` | `simplon.tasks.conan:publish` | pushes a `conan cache save` archive as an OCI artifact |
| `build:conan-cache` | `simplon.tasks.conan:fetch` | pulls one back, for the product's own `conan cache restore` |

**Why the two halves are not symmetric, which is the question a reader will ask.** The NuGet consumer
needs the credential INSIDE the container, because `dotnet restore` is what talks to the registry. The
Conan consumer does not: the transport is a file, the registry conversation happens on the host, and
`conan cache restore` reads a path. So the .NET side needs a task that starts a container with a secret
in its environment and the C++ side needs no such thing. That asymmetry is the design, not an oversight.

**Why the kernel does not run `conan cache save` or `conan cache restore` itself.** It is a transport, and
a transport that learned conan would be the kernel learning a language toolchain - the thing the design
refuses everywhere else. The product runs both through its own `toolchain:run` commands, against its own
cache volume, with its own pattern. The kernel moves the file.

## The manifest shape

```yaml
artifacts:
  # si#127 - a NuGet package. `registry:` is the HOST and owner, not the index URL: it is the same
  # spelling `release:artifact` and `release:image` use, and it is what `is_github_packages` reads.
  corelib:
    registry: nuget.pkg.github.com/marcozwyssig
    image: mcr.microsoft.com/dotnet/sdk:9.0
    project: src/Core/Core.csproj
    source_name: github          # optional; the name the nuget.config gives the source
    tag: 1.4.0                   # optional; --tag otherwise

  # si#128 - a Conan cache archive, which is an ordinary OCI artifact
  cpplib:
    registry: ghcr.io/marcozwyssig
    repository: demo-conan
    source: build/conan/demo.tgz
    media_type: application/vnd.conan.cache.v1+tgz
```

---

### Task 1: the one host the credential may also reach

**Files:** `src/simplon/githubpackages.py`, `tests/test_githubpackages.py`

GitHub's NuGet registry is `nuget.pkg.github.com`, not `ghcr.io`. Without this, either the check is
bypassed for NuGet (a second token story by omission) or a legitimate registry is refused.

- [ ] **Step 1: Write the failing test.** Extend the existing parametrised table in
  `test_only_githubs_own_registry_may_receive_a_github_token` with
  `("nuget.pkg.github.com/owner", True)`, `("NUGET.PKG.GITHUB.COM/Owner", True)` and
  `("nuget.pkg.github.com.evil.example/owner", False)` - the third for the same reason `ghcr.io.evil.example`
  is already there.
- [ ] **Step 2: Watch it fail** with `assert False is True` on the new rows.
- [ ] **Step 3: Implement.** Replace the single comparison with a module-level frozenset of GitHub's
  package hosts and an exact membership test. The docstring gains one sentence saying WHY there are two
  hosts and not one: GitHub serves OCI artifacts and NuGet packages from different names, and the check is
  about the credential's destination rather than about a protocol.
- [ ] **Step 4: Green, and the whole existing table still green.**
- [ ] **Step 5: Commit** `feat(si#127): the credential check knows GitHub's NuGet host too`

---

### Task 2: `build:nuget-config` - the source, reachable, with no secret in it

**Files:** Create `src/simplon/tasks/nuget.py`, `tests/test_tasks_nuget_config.py`

**Interfaces produced:** `SECTION = "artifacts"`; `config(name: str = "") -> int`;
`config_text(source_name: str, index_url: str) -> str` (pure).

- [ ] **Step 1: Write the failing tests.**
  - a declared artefact writes `<root>/nuget.config`;
  - the file names the index URL derived from `registry:` (`nuget.pkg.github.com/owner` ->
    `https://nuget.pkg.github.com/owner/index.json`);
  - **the file contains the literal `%GITHUB_TOKEN%` and no token at all** - the test sets
    `GITHUB_TOKEN` to a recognisable string and asserts that string is absent from the written file.
    This is si#127's one security requirement and it is asserted directly rather than implied;
  - a registry that is not GitHub's is refused by name, saying which hosts are GitHub's;
  - an artefact with no `registry:` is refused naming the key;
  - an undeclared name lists the ones that are declared (the shape `artifact.py` established);
  - `config_text` is pure and its output parses as XML.
- [ ] **Step 2: Watch them fail** - the module does not exist.
- [ ] **Step 3: Implement.** `config_text` renders the four elements: `<clear/>`, nuget.org, the GitHub
  source, and a `packageSourceCredentials` block with `Username` = the owner and `ClearTextPassword` =
  `%GITHUB_TOKEN%`. The module docstring argues WHY the variable rather than the value, and cites
  measurement 3 above so the next reader does not try `<apikeys>`.
- [ ] **Step 4: Green.**
- [ ] **Step 5: Commit** `feat(si#127): build:nuget-config writes a source a build can reach and a repo can hold`

---

### Task 3: `release:nuget` - pack, then push

**Files:** `src/simplon/tasks/nuget.py`, `tests/test_tasks_nuget_publish.py`

**Interfaces produced:** `publish(name: str = "", tag: str = "") -> int`; a pure
`pack_argv`/`push_argv`/`docker_argv` trio; `_secret_env_file(token) -> Path` (context-managed).

- [ ] **Step 1: Write the failing tests.**
  - the pack line carries `-p:PackageVersion=<tag>` and the tag comes from `--tag` first, `tag:` second,
    and its absence names BOTH places (artifact.py's rule, and its wording);
  - the push line names the source and carries **no** `--api-key` (measurement 4), so a token cannot be
    in argv by construction;
  - the docker line carries `DOTNET_CLI_HOME` (si#102's measured fact: as uid 1000 `dotnet` dies on
    `/.dotnet` denied) and `docker.user_args()`;
  - the docker line carries `--env-file` and **never** `-e GITHUB_TOKEN=<value>`; the assertion is over
    the whole argv, not over one element;
  - the env file is removed even when the run raises;
  - the image goes through `docker.pinned_image`, so `:latest` is refused with the kernel's one wording;
  - a non-GitHub registry is refused before a token is minted.
- [ ] **Step 2: Watch them fail.**
- [ ] **Step 3: Implement**, following `image.py`: `_declared`, then the refusals, then the two
  container runs. A failed push appends `scope_advice()` **only** when the registry is GitHub's - the
  hint is tied to a host and a condition, never appended to every failure (image.py's own rule).
- [ ] **Step 4: Green.**
- [ ] **Step 5: Commit** `feat(si#127): release:nuget packs and pushes without the token ever reaching argv`

---

### Task 4: `build:nuget-restore` - the consuming half

**Files:** `src/simplon/tasks/nuget.py`, `tests/test_tasks_nuget_restore.py`

- [ ] **Step 1: Write the failing tests.** The restore runs the pinned image over the product tree with
  the same `--env-file` and `DOTNET_CLI_HOME`; it refuses when no `nuget.config` is there, naming
  `build:nuget-config` as the command that writes one; it says plainly when the registry is not GitHub's
  that no GitHub token is minted.
- [ ] **Step 2: Watch them fail. Step 3: Implement. Step 4: Green.**
- [ ] **Step 5: Commit** `feat(si#127): build:nuget-restore resolves a private feed inside the container`

---

### Task 5: `release:conan` and `build:conan-cache` - the transport

**Files:** Create `src/simplon/tasks/conan.py`, `tests/test_tasks_conan.py`

**Interfaces produced:** `publish(name: str = "", tag: str = "") -> int`; `fetch(name: str = "", tag: str = "") -> int`.

- [ ] **Step 1: Write the failing tests.**
  - a declared archive is pushed as a FILE (`githubpackages.push`), not zipped again
    (`push_directory` would wrap a `.tgz` in a `.zip` and the consumer's `conan cache restore` would be
    handed the wrong file);
  - the four keys are each named when missing;
  - a missing `source:` file says the archive is written by the product's own `conan cache save`, not by
    this task;
  - `fetch` pulls into the declared `source:` path's directory and reports where the file landed, because
    the next command the operator types is `conan cache restore <that path>`;
  - a non-GitHub registry skips the login with a spoken reason rather than minting a token for it;
  - a missing tag names both `--tag` and the manifest key.
- [ ] **Step 2: Watch them fail. Step 3: Implement. Step 4: Green.**
- [ ] **Step 5: Commit** `feat(si#128): a conan cache archive travels as an OCI artifact`

---

### Task 6: the coordinates

**Files:** `src/simplon/catalogue.yaml`

- [ ] **Step 1:** Declare the five, each with the comment the file's style asks for - what data it needs
  and why it is not placed. The `release:conan` comment states in as many words that this is a
  **transport and not a remote**: no `conan install` resolution, no version ranges, no graph solved
  remotely, and Conan 2.32.0 measured as having no OCI remote type.
- [ ] **Step 2:** `./simplon.sh test all` - `test_catalogue.py` and `test_surface.py` should now be green
  and only the counted guards red.
- [ ] **Step 3: Commit** `feat(si#127,si#128): five coordinates for handing a package over`

---

### Task 7: the seven guards, page first and number last

**Files:** `site/content/building/phases.md`, `site/content/building/rules.md`,
`site/content/using/why.md`, `tests/test_phases_chapter.py`

The guards, by name, and what each demands:

| guard | demands |
|---|---|
| `test_phases_chapter::test_the_overview_counts_are_the_catalogues_own` | the overview table's per-namespace counts: `build` 3 -> 6, `release` 4 -> 6 |
| `test_phases_chapter::test_each_sections_own_list_names_exactly_that_namespaces_coordinates[build,release]` | each section's own bullet list gains its new coordinates |
| `test_phases_chapter::test_no_section_writes_a_description_beside_a_coordinate` | every new bullet is a BARE backticked coordinate, and the census `listed == len(tasks)` |
| `test_phases_chapter::test_every_catalogue_coordinate_appears_somewhere_on_the_page` | the page-wide set check, AND its literal `== 30` -> `35` |
| `test_phases_chapter::test_the_summary_sentence_counts_the_catalogue_and_not_a_memory` | "Thirty coordinates: nineteen carrying a placement, eleven free to be filed." -> "Thirty-five ... twenty-four ... eleven" |
| `test_refusal_census::test_the_page_prints_the_catalogues_own_size_and_what_it_places` | `rules.md`'s "catalogue holds **30** coordinates" -> **35** (the second number, what its tree places, does not move: none of the five is placed) |
| `test_why_chapter::test_the_kinds_of_work_cover_the_whole_catalogue_exactly_once` | `why.md`'s kinds-of-work table files all five, exactly once each |

- [ ] **Step 1: Run the suite and let the assertions name the numbers.** Do not compute them from this
  table; the messages are the source.
- [ ] **Step 2: Update the pages FIRST, the test's literal LAST.** The guard's own message says so
  ("the count moved - update the page, then this number") and it is not decoration.
- [ ] **Step 3: the kinds-of-work row.** All five go in *packaging and publishing*; its middle column
  gains `dotnet`. They do NOT go in *the declarations themselves*, and the reason is measured by a
  sibling guard: `test_the_bodies_the_page_says_reach_no_external_tool_really_do_not` walks the MODULES
  behind that row for any `run`/`stream` call, and `tasks/nuget.py` shells out to docker.
- [ ] **Step 4: Commit** `docs(si#127,si#128): the pages carry the five coordinates`

---

### Task 8: the documentation a reader would otherwise get wrong

**Files:** `site/content/using/releasing.md` (or a new page under `using/`), and the suite that guards it

- [ ] **Step 1:** Write the two sections. The Conan one says, in as many words, that **there is no Conan
  registry in GitHub Packages** and that what this ships is a transport: an exact tag pulled and
  restored, with no remote resolution, no version ranges and no graph solved remotely. A reader who sees
  "Conan packages in GitHub Packages" will assume a remote and be wrong, and the page's job is to stop
  that before they design around it.
- [ ] **Step 2:** The NuGet one carries the two inherited si#102 facts (`DOTNET_CLI_HOME`, and the target
  framework that builds in a 9.0 image and refuses to run with rc 150) and the measured credential
  mechanism, including that `<apikeys>` cannot hold a key on Linux.
- [ ] **Step 3:** A test asserting the page says the words that matter, in the shape `tests/` already
  uses for the case chapters, so the claim cannot quietly rot.
- [ ] **Step 4: Commit** `docs(si#128): a transport, said in the words that stop the wrong assumption`

---

### Task 9: the end-to-end proof, which is the reason this ticket is one lane

Design section 6. **A string assertion over an argv is not evidence.** Both drives run for real; whatever
cannot be driven is stated as unproven, naming the step.

- [ ] **Step 1: NuGet - publish, then resolve from a second project.** Against a real authenticated NuGet
  v3 feed reachable from this machine (BaGet behind an nginx basic-auth proxy - the same authentication
  shape GitHub Packages uses). Drive `build:nuget-config`, `release:nuget`, then a SECOND project that
  `PackageReference`s the published package and prints a string that only the published assembly can
  produce. Capture the transcript.
- [ ] **Step 2: NuGet - see it red.** Remove the credential from the environment and confirm the restore
  FAILS. A green consume that would be green without the token proves nothing.
- [ ] **Step 3: Conan - save, push, empty cache, pull, restore, build.** `conan create` a package in a
  container, `conan cache save` it, `release:conan` it to a real registry, then in a container with an
  EMPTY cache: `conan list` shows nothing, `build:conan-cache` pulls, `conan cache restore` reads it back,
  `conan list` now shows the package, and a consumer project builds and RUNS against it.
- [ ] **Step 4: Conan - see it red.** In the empty cache, `conan install --requires=<pkg>` BEFORE the
  restore, and confirm it fails to resolve. Otherwise step 3 proves only that a container can compile.
- [ ] **Step 5: Say what is unproven.** The GitHub Packages leg itself, for both halves, if the machine's
  token still lacks `read:packages,write:packages`. Name the step, not a hedge.

---

### Task 10: review, release notes, PR

- [ ] **Step 1:** `./simplon.sh test all` and `./simplon.sh test typecheck-python`, compared against the
  baseline measured on `origin/main` before any of this started.
- [ ] **Step 2:** Dispatch `python-reviewer` on the diff and act on what it finds.
- [ ] **Step 3:** Release notes, if the repository's convention asks for them.
- [ ] **Step 4:** One PR against main, no labels, not merged.
