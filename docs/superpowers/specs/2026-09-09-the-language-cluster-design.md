# The language cluster: what a product declares, and how the kernel proves it

**Status:** design, approved 2026-09-09.
**Tickets:** si#127, si#128, si#129, si#130, si#131, si#132, si#133, si#134.

## 1. Why these eight are one design

si#102 landed the uniform build: a tree read as a declaration, CMake and a solution rendered from it, a
container that configures, compiles, tests and runs. Driving it end to end immediately produced the next
eight tickets, and four of them need the SAME decision made once. A C++ target cannot say whether it is
an application, a shared library or a static one (si#131); a test cannot say which LEVEL it is (si#134);
a run cannot say whether it wants debug symbols (si#132); a level cannot say where its results landed
(si#133). Every one of those is the same sentence: **the product has something to say and the manifest
has no word for it**.

Answered separately, each grows its own key with its own shape, and a product ends up declaring four
unrelated dialects. This document fixes what they share; each ticket's own plan decides the rest.

## 2. Decision: no new top-level manifest section

A manifest already carries `build:`, `toolchain:`, `artifacts:`, `images:`, `site:` and `tests:`. The
cluster adds nothing beside them.

- Target shape (kind, includes, exports, nesting) extends `build: targets:`, which si#102 established as
  tree-by-default and manifest-as-exception. That rule is not renegotiated; the manifest still names only
  what the tree cannot say.
- Publishing a package (si#127 NuGet, si#128 Conan) extends `artifacts:`, which `release:artifact`
  already reads. A registry, a package name and a scope are the same three facts whatever the ecosystem.
- The build type (si#132) is NOT a target attribute and does not go in `targets:`. It is a property of
  the RUN, and a checked-in `set(CMAKE_BUILD_TYPE ...)` would decide it for every consumer of the
  generated tree forever.

**Why this is a decision and not an omission.** A new section is cheap to add and expensive to remove:
every product's manifest, every docs page that counts sections, and every reader's mental model carry it
from then on. The bar is a fact that genuinely fits nowhere, and none of the eight has one.

## 3. Decision: the location names the test level

- `src/<target>/<name>_test.<ext>` is a UNIT test. It sits beside its unit.
- `tests/` holds SYSTEM and ACCEPTANCE tests, which are about the assembled product and have no single
  unit to sit beside.

This is a rule about meaning, not a convenience: a reader must be able to tell a level from a path
without opening the file.

**The consequence si#134 has to carry.** `tests/` now holds two levels, so the generator must tell them
apart, and today it tells neither. **si#131 and si#134 are decided together or one of them is redone**,
and they belong to the same lane for that reason rather than because they are similar.

*Corrected by Lane A, which built it (si#131).* This paragraph first argued the pairing from a collision
between `tests/system/` and si#131's nesting question. There is none: folding is a rule about `src/`,
and `tests/` already had its own rule from si#102. Two real reasons stand in its place - under `tests/`
a directory has to be read as a LEVEL or as a test project and it cannot be both, and `_library_targets`'
recursive read and the lifting of a co-located test out of a library are the same twenty lines. The
pairing was right; the argument for it was not.

**The defect this rule exposes is not cosmetic.** `_sources` returns every source file directly in a
directory, so a co-located `net_test.cpp` is compiled INTO the library today. Test code, and its test
framework's symbols, ship inside the artefact. Nothing in any run says a word about it.

## 4. Decision: a gate may name where its results landed

si#133's real finding is not "Allure is pytest-only". It is that the kernel HAS the technology-agnostic
merge (`allure.merge_results`, which names foreign sources in its own docstring and carries si#70's
staleness cutoff) and exposes no declarative way to reach it. javademo gets an Allure archive from a
Gradle run today by writing an `impl:` gate in Python that calls the merge itself. A product that
declares the natural shape instead - a `command:` gate over a toolchain command, si#106 - gets an exit
code and the sentence *"the kernel ran a command here, not a suite, and cannot say whether one ran at
all"*.

So a `Gate` gains one key naming the directory the product's own runner wrote results into. The merge
already exists; this makes it reachable from the manifest.

**Correction, measured by Lane B after this section was written (si#136).** The paragraph above says a
`command:` gate over a toolchain command "gets an exit code". It gets less than that: it cannot be
declared at all. `run_toolchain` takes a `typer.Context` as its first parameter and the gate parser
refuses any body that does - `'build unit' takes a CLI context, which a gate has none of to give it`.
Every si#106 test resolves to a context-free stub, so no test ever touched the real coordinate, and both
case chapters promise a shape neither of them drove. The premise "a `command:` gate is how a C++ or .NET
level runs" is therefore false today, and si#136 owns fixing it. Nothing in this section's decision
changes - a gate naming its results dir is what a product needs either way - but the route a product
takes to get there is an `impl:` gate until si#136 lands.

**Three things this must not become.** It must not be a second `junit:` (that key is pytest-only by
construction and stays so). It must not silently succeed when the directory is empty, because an Allure
report rendered with a level missing looks exactly like one where the level passed. And it must not
assume anything unverified about formats: whether `allure generate` accepts raw allure-results JSON and
JUnit XML mixed in ONE directory, and whether a JUnit or TRX logger ships in the .NET SDK image without
a package reference, are both MEASUREMENTS this design does not make.

## 5. Decision: `simplon init` reads what the repository already knows

The product name defaults to the repository's name and stays overridable by the argument (si#129); the
orchestrator block defaults to `deploy/provision/orchestrator`, which is where every real product puts
it (si#130).

**Default, never decree, and si#102 is the fresh counter-example.** Its generator derived a CMake target
from `root.name` and got the product name wrong, because a directory is named for where it sits and not
for what it is. A repository can be `tooling`, or a monorepo holding two products. A name that becomes a
launcher filename, a manifest filename and a shell token must be REFUSED with the fix in the message
when it cannot be one, never mangled into something that half works.

## 6. The proof standard, which is the whole reason this document exists

**A string assertion over an argv is not evidence.** simplon 0.8.0 shipped a uniform build no product
could drive, because every test behind it stubbed `run`. si#102 fixed that by driving a real container,
and the first thing the drive found was `TARGET_FRAMEWORK = net8.0`: it BUILDS in a 9.0 SDK image and
then refuses to run, rc 150. No assertion about the generated XML would ever have seen it.

Each ticket in this cluster therefore states its own artefact-level proof, and the plan is not done until
it does:

| ticket | the claim | what proves it |
|---|---|---|
| si#131 | a target is shared / static / an app, and its includes are exported | build it, then read the produced file: `file` says shared or static, and a second target that only links it compiles without repeating the include path |
| si#132 | the build carries debug symbols | build it, then `nm` or `file` on the binary. A flag passed and ignored looks identical to one that works |
| si#134 | a unit test is not part of the library | build it, then confirm the library archive does NOT carry the test's symbols |
| si#133 | a level really contributed | assert the rendered report contains that level's cases, and see it RED with the level's results absent |
| si#127 | a published package can be consumed | publish, then resolve it from a second project |
| si#128 | a saved Conan package restores | `conan cache save`, push, pull into an empty cache, `conan cache restore`, build against it |

## 7. Lanes, and the one file that forces them apart

Four lanes can run at once. What decides the split is not subject matter but **which files two branches
would both rewrite**.

- **Lane A - the C++ model.** si#131, si#134, si#132. `tasks/buildfiles.py`, the cpp profile,
  `case-cpp.md`. si#131 and si#134 are one decision (section 3); si#132 is separable but shares the
  end-to-end drive and the same profile, so it costs less here than in a lane of its own.
- **Lane B - test reporting.** si#133. `tasks/testrun.py`, `tasks/allure.py`. Touches no coordinate.
- **Lane C - init defaults.** si#129, si#130. `bootstrap.py`, both launcher templates,
  `getting-started.md`. Both change what a scaffold produces, so they are one lane by construction.
- **Lane D - publishing.** si#127, si#128. New coordinates in `catalogue.yaml`.

**Lane D is alone in its space and must be, and si#102 measured the reason.** Declaring a coordinate
makes seven counted guards go red at once: the overview table's per-namespace count, the namespace
section's own list, the bare-list-item census, the page-wide coordinate check AND its literal total, the
summary sentence spelled out in words, `rules.md`'s catalogue size, and `why.md`'s kinds-of-work table.
Every one of those is a single line in a shared file. Two branches each adding a coordinate conflict in
seven places and the resolution is arithmetic, which is exactly the kind nobody rechecks.

Lanes A, B and C add no coordinate and do not collide with each other or with D.

**Prerequisite, now met:** si#102 is on main as `7ab6fe2`. Every lane branches from main, not from a
sibling lane.

## 8. What this document deliberately does not decide

- Whether Conan 2 speaks an OCI remote natively. si#128's transport design rests on it NOT doing so, and
  a search established neither answer. Ten minutes of measurement before that lane's design is written.
- How far the C++ export goes: usable within the generated project is a small change; installable and
  findable by a foreign project needs `install(TARGETS ... EXPORT ...)` and a package config. si#131's
  plan decides, and says which it built.
- Whether co-located unit tests are expressible in .NET at all. *Lane A measured the mechanism and this
  entry named the wrong one:* it is not the test framework's package references. The generated `.csproj`
  emits no `<Compile>` items at all, so the SDK's own `**/*.cs` glob compiles a co-located test into the
  library whatever the references say. The conclusion survives - saying "not expressible" plainly beats
  generating something that builds and is wrong - but it rests on the glob, not on the references.
- Windows. A `SHARED` target without symbol visibility links on Linux and not on Windows; the kernel
  ships no Windows toolchain, so this is named rather than solved.
