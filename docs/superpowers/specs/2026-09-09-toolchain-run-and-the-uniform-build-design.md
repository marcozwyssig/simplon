# `toolchain:run` and the uniform build

**Status:** design, not built. **Date:** 2026-09-09.

## The goal, in one sentence

A Java, C++, .NET or Python product built on this kernel should run the *same commands* to compile, test
and analyse itself, and differ only in which pinned image runs and which argv it is handed.

The value claimed is uniformity, not machinery. `./<product>.sh build compile` meaning the same thing in
four products is worth more than any one of the four toolchains being cleverly supported.

## What this is NOT

**Generating build files.** `CMakeLists.txt`, directory-specific CMake includes, `.sln` and `.csproj`
were the original request and they are deliberately out of scope here. They are a separate question with
a separate answer: a solution file is a format with GUIDs and configuration matrices, CMake is a
language, and inventing the conventions for either without a product to measure against is how a
generator ages faster than it helps. When a product needs them, they become their own coordinates -
`build:cmake-files`, `build:dotnet-solution` - writing into the same tree this design's task then
compiles. Two questions, separately answerable.

**Four language modules in the kernel.** The kernel learns no CMake, no MSBuild, no pip. It learns to run
a pinned image over the product tree as the calling user with named caches. Four language modules would
be four surfaces that age; one task plus four manifest entries is one surface and four lines.

## 1. `toolchain:run` - one task, declared as a FAMILY

```yaml
  toolchain:run:
    impl: simplon.tasks.toolchain:run
    help: "Run a pinned toolchain image over the product tree, as the calling user."
```

**A family, not a placement, and this is load-bearing.** si#34 makes a coordinate that opens with a GROUP
name a placement: `build:toolchain` could then be placed only under `build`, and `ctest`, `dotnet test`
and `gradle test` all belong under `test`. As a family - like `vcs:`, `docs:`, `tasks:` - it is free to
be filed wherever the product needs it. Declared, not placed: a product with no compiled toolchain should
not receive the command with the kernel.

### What a product writes, in full

This is the expanded form, which section 1c GENERATES. A product never has to type it - see 1b.

```yaml
build:
  commands:
    compile:
      task: "toolchain:run"
      help: "Compile in the containerised toolchain."
      with:
        image: "gradle:jdk25"          # pinned - docker.pinned_image() refuses :latest and empty tags
        workdir: /work
        argv: ["gradle", "build", "--no-daemon", "--console=plain"]
        env: { GRADLE_USER_HOME: /home/gradle/.gradle }
        caches:
          - { volume: gradle-cache, path: /home/gradle/.gradle }
          - { volume: vaadin-cache, path: /root/.vaadin }
```

Compiler AND version are therefore manifest data, and the version is not optional: `pinned_image()`
already refuses an untagged reference, an empty tag and the literal `latest`. Swapping clang for gcc, or
19 for 20, is a one-line diff rather than an edit to a script.

### The argv rule: manifest first, caller appends

The manifest pins the argv; everything the caller types after the command name is APPENDED.

    ./netctl.sh build compile                      -> gradle build --no-daemon --console=plain
    ./netctl.sh build compile --rerun-tasks        -> ... --rerun-tasks

This is the shape that satisfies both constraints already written down. A CI step stays a NAME, which is
what "one step per orchestrator command" asks for (netctl#510/#514) - the log then says which PHASE died
rather than which flag. And netctl#1091's promise survives: "everything after the command name reaches
gradle verbatim, so the full vocabulary survives".

### `--user`, from the first line

The container runs as the calling uid/gid via `docker.user_args()`. netctl's hand-written `gradle_argv`
does NOT, and that is not a theoretical gap: on 2026-09-08 it left the repo-root `build/` owned by root,
after which the host-side Python gate could not create `build/sidecar-stubs` and every CI run on a
freshly cleared runner died at that line (netctl#1778). Built here, every product inherits the right
answer instead of copying the wrong one.

### Cache volumes are per instance

`{ volume: gradle-cache }` resolves to `<product>-gradle-cache-<instance>`, with the instance coming from
`simplon.labinstance` - which is already the kernel's (netctl#1404). Today only netctl knows this
convention, written by hand; here every product gets it, and concurrent agents in separate worktrees stop
contending by construction.

## 1b. The product declares PARAMETERS; the kernel provides the rest

The requirement, stated plainly: *a user has only their configuration parameters, and everything else is
provided automatically.* The block in section 1 fails that - `argv`, `workdir`, `caches` and `env` are
kernel knowledge that every product would retype identically.

So the kernel carries a **profile** per language: the argv for compile / test / analyse, the cache paths
the toolchain uses, the working directory. A product says what is its own:

```yaml
build:
  toolchain: { language: cpp, compiler: clang, version: "19" }
```

and gets `compile`, `test unit` and `test analyse` with the right argv, the right cache volumes and a
pinned `silkeh/clang:19`. Java says `{ language: java, jdk: "25" }`; .NET says `{ language: dotnet, sdk:
"9.0" }`. Anything in the profile stays overridable by writing the field, so the escape hatch is the same
shape as the default.

### The move that makes this safe: SCAFFOLD, do not resolve at runtime

A profile resolved at RUN time means a kernel bump can silently change how a product builds - the same
class as an unpinned image, one level up. So the profile is written INTO the product's manifest by the
command in section 1c, and the product owns what it runs from then on. The kernel's table is a starting
point, not a runtime dependency, and it can evolve without moving anybody's build under them.

The price is stated rather than hidden: **the kernel now carries per-language knowledge**, which the
"What this is NOT" section above argues against for modules. The difference that makes it acceptable is
that a profile is DATA - a table of argv and paths - not a module with behaviour, and it is inert after
the scaffold. If a profile is wrong, the product edits its own manifest; nothing waits for a kernel
release.

## 1c. `support:toolchain` - the ready-made configuration, generated

```yaml
  support:toolchain:
    impl: simplon.tasks.toolchain:scaffold
    help: "Write a ready-made toolchain configuration for a language into this product's manifest."
    params:
      language: { help: "java | cpp | dotnet | python", argument: true }
```

`./<product>.sh support toolchain cpp` writes the `build:` and `test:` commands for C++ into the
manifest, with the profile's defaults spelled out rather than implied. The product then reads its own
build in its own file - which is also what makes a review of it possible.

This continues an existing seam rather than opening one: `simplon.bootstrap` already scaffolds a FRESH
product and its docstring carries a written list of what a "fuller scaffolder" would add. This is that,
for an existing product, and it belongs under `support` for the same reason `install` does - it touches
the product's own tree and reads no phase.

**Idempotent, and it must say what it changed.** A scaffolder that silently overwrites a hand-edited
command is worse than none; it prints the diff and refuses to clobber a command that already exists
unless asked.

## 2. The command set is a CONVENTION, not a mechanism

| command | Java | C++ | .NET | Python |
|---|---|---|---|---|
| `build compile` | `gradle build` | `cmake --build build` | `dotnet build` | - |
| `test unit` | `gradle test` | `ctest --test-dir build` | `dotnet test` | `pytest` |
| `test analyse` | SpotBugs / Error Prone | `clang-tidy` | Roslyn analyzers | `mypy` |

Documented, not enforced. A product that needs `configure` before `compile` writes one; a product with
two compilers writes `compile-clang` and `compile-gcc`. The kernel does not police the names, because a
rule here would buy nothing and cost the first product whose shape differs.

## 3. Static analysis runs where the compile runs

**The rule:** the analyse step uses the same environment - the same image - as `build compile`.

This is not tidiness. `typecheck.py` already states the measured reason for Python: *"The checker needs to
SEE the product's installed dependencies, or every third-party import degrades into a blanket exception
and the gate stops meaning anything."* The same holds in every language: `clang-tidy` needs
`compile_commands.json` and the include paths, Roslyn analyzers need the restored packages, SpotBugs needs
the classpath. Deciding the two environments separately means analysing a program nobody builds.

### `test:typecheck-python` has a sunset, and it is conditional

That task exists because Python's environment is the HOST venv - the orchestrator itself runs in it, so
`sys.executable` is already the right interpreter and there is nothing to bootstrap. It is also the
kernel's ONLY language-specific coordinate.

The moment a product's Python moves into a container (section 4), its type check moves with it and becomes
an ordinary `toolchain:run` entry. The task then has no reason to exist, and the kernel loses its last
language-specific coordinate. **It is not removed by this design** - it is removed by the first product
that no longer needs it, and it stays for as long as any product's Python is on the host.

## 4. Python in a container: a decision, with its price

netctl's Python is deliberately NOT containerised today. `unit_py_cmd` builds a venv on the host, and
`netctl.sh` bootstraps pip through `get-pip.py` (#475). The standing rule is "Docker only for what netctl
starts; the tooling runs natively".

Aligning Python reverses that. Both halves stated:

**What it buys.** The host venv bootstrap disappears, and with it the special cases it carries: a host
without `ensurepip`, the apt self-install, the half-created venv that #475 exists to heal. The gate then
depends on the same one thing every other gate depends on - a pinned image.

**What it costs.** The fastest gate gains a container start. The per-suite venvs become a cache volume
rather than a directory in the tree, which changes how they are inspected and cleared. And a developer
without docker can no longer run the Python gate at all, which today they can.

**This design does not decide it.** It records that the decision exists, that it is per product, and that
section 3 binds it: whichever environment a product picks for its Python build, its type check goes
there too.

## 5. Two things that do not generalise, named rather than smoothed over

**`--network` is a runtime value, not manifest data.** netctl's `component-db` gate joins the test JVM to
a scratch docker network so it can reach a throwaway Postgres by name, and that network's name exists only
at call time. So `toolchain:run` needs one parameter the manifest cannot supply. Proposed: an optional
`--network` on the command, passed through untouched, documented as the one runtime hole.

**Mirror flags reach two different places.** netctl's `mirror_args` returns TWO lists: `-e` flags for
docker, and flags for GRADLE'S OWN command line. The second is toolchain-specific - Conan, NuGet and CMake
have nothing at the same position - so generalising it means teaching the kernel how to hand an arbitrary
tool a mirror. That is the kind of generalisation one cuts wrong once and then carries.

**Proposed for the first cut: neither is generalised.** `toolchain:run` passes `env:` through and nothing
more; a product that wants a mirror writes the variables itself. `support:nexus` is already the kernel's
(netctl#1405), so the probe can be shared later - deliberately later, because the part of netctl's mirror
logic that carries the most special cases is "a dead proxy must never fail a gate", and that should be
generalised against a second case, not the first.

## 6. Migration for netctl

1. `toolchain:run` lands in the kernel; netctl pins the new version.
2. netctl's CI steps become named commands: `build compile`, `test unit`, `test analyse`.
3. `tooling.gradle_argv` and `_docker_gradle` are deleted - roughly forty lines and their test surface.
4. **`./netctl.sh gradle …` stays**, as netctl's own `impl:`. It is a tool for humans at a terminal, and
   the appending rule means the two do not conflict: the CI path is pinned, the human path is free.

## 7. Open questions

- Does `caches:` need a per-volume "clear" verb, or does `clean` reach them by name? netctl's `clean`
  removes them today by hand-written name (netctl#981).
- Does `toolchain:run` need to fail differently when the image cannot be pulled offline, or is docker's
  own error enough?
- Is `analyse` the right command name, against `lint`, `check`, `static`? The table above uses `analyse`
  because it covers type checking and bug patterns without claiming either.

## Verification this design implies

- The task's argv assembly is PURE and unit-tested, like `gradle_argv` is today: assembles, runs nothing.
- The appending rule gets a test with an empty and a non-empty caller argv.
- `pinned_image()` refusal is already covered; the new path must go through it.
- A product-level proof: netctl's CI green with `build compile` replacing `./netctl.sh unit-java`.
