---
title: "Releases"
weight: 9
---

What each release changed, and what a product has to do about it.

Notes start at **0.4.0**. Earlier releases have their tags and their commits;
writing their notes now would mean reconstructing them from memory, and a
reconstructed record reads exactly like a real one. The [release
procedure](../releasing/) explains how a version comes into being.

Every section from **0.5.0** on names the number of every ticket merged into
that release, and `tests/test_releases_page.py` measures it against the merges
in the release's own range, so a change cannot go out undescribed. The numbers
are issues and pull requests in [this
repository](https://github.com/marcozwyssig/simplon/issues). The 0.4.0 section
predates that rule: it describes its release in prose and names no numbers, and
it is the one section held only to existing.

## 0.10.0

**A C++ or a .NET product stops writing its build files by hand.** 0.9.0 gave every product one pinned
toolchain and one uniform way to run it over its tree; this release produces the files that toolchain
compiles. The two halves meet in the tree and nowhere else - two coordinates, no new subsystem.

A minor rather than a patch: two catalogue coordinates are a surface, not a repair.

### Two coordinates that write a product's build files (si#102)

`build:cmake-files` writes one `CMakeLists.txt` per source directory plus the root file that adds them.
`build:dotnet-solution` writes the `.sln` and one `.csproj` per project. Both are **declared, not
placed** - a product without the language never sees the command, and a product whose build outgrows the
shapes below keeps its hand-written files and declares neither. Nothing degrades; it does what every
product does today.

**The tree is the declaration, and the manifest is only the exception.** `src/<name>/` holding sources
is a library, one holding a `main.cpp` or a `Program.cs` is an executable, each `tests/<name>_test.cpp`
is one ctest case, and a directory under `tests/` is a test project. The one thing a directory cannot
show is what a target depends on:

```yaml
build:
  targets:
    net: { depends: [core], include: [vendor/asio/include] }
```

Guessing that from include paths was considered and refused - it reads a preprocessor approximately, and
an approximate answer in a build file fails at link time, in a message about symbols rather than about
the manifest. A `targets:` key naming no target is refused by name, with the targets that do exist
listed, because a typo there is otherwise silent and silently does nothing.

**What they write is committed, so it has to be deterministic.** Every list is sorted, and a solution's
GUIDs are derived with `uuid5` from the project's path relative to the product root rather than
generated: a `uuid4` would put a new GUID into the diff on every run and make the committed decision
unusable within a week. Each file carries a two-sentence `DO NOT EDIT` header, and the generator
overwrites without asking - deliberately the opposite of `support:toolchain`'s never-clobber rule,
because a manifest is a product's own statement and a `CMakeLists.txt` is a rendering of one. Reverting
a statement would be wrong; reverting a rendering is the point.

**Driven, not asserted, and that is why 0.9.0 exists at all.** `tests/test_buildfiles_e2e.py` generates
a real tree, runs `configure`, `compile` and `ctest` in the profile's own `silkeh/clang:19`, executes
the binary, and does the same for `dotnet build` in `mcr.microsoft.com/dotnet/sdk:9.0`. It earned its
place on the first run: the .NET half targeted `net8.0`, which BUILDS in a 9.0 SDK image because the
targeting pack is restored from NuGet, and then refuses to run - `You must install or update .NET to run
this application`, rc 150. It targets the framework the SDK image carries now.

One thing to know before adopting the CMake half: `add_subdirectory` puts a target's output under its
own directory, so an executable declared in `src/<name>/` lands at `build/src/<name>/<name>` and not at
`build/<name>`. A `deploy up` command that runs the binary has to name that path.

### A product can hand a package over, and a second one can take it (si#127, si#128)

Both languages could compile in 0.10.0's uniform build and neither could give the result to anybody.
Five coordinates close that, and they are two different answers because GitHub Packages gives two
different answers.

**NuGet is an ordinary registry.** `release:nuget` packs the declared project and pushes it to
`nuget.pkg.github.com/<owner>`; `build:nuget-config` writes the `nuget.config` a consumer restores
through, and `build:nuget-restore` runs that restore with the credential the feed wants. All three read
the manifest's existing `artifacts:` section - there is no new top-level key.

**The generated `nuget.config` is meant to be committed and holds no token.** What it holds is
`%GITHUB_TOKEN%`, which NuGet expands from the environment when it reads the file. The resolved token
reaches the container as a `--env-file` created 0600 and deleted in a `finally`, never as
`-e NAME=VALUE`, and never on a command line: measured, a push against a source that already carries
credentials needs no `--api-key` at all.

**Conan is not a registry there, and the docs say so in as many words.** GitHub Packages serves npm,
RubyGems, Maven, Gradle, NuGet and Docker/Container - and no Conan. So `release:conan` is a
**transport**: `conan cache save` writes an archive, the coordinate moves it into a registry as an
ordinary OCI artifact, and `build:conan-cache` pulls that exact tag back for the product's own
`conan cache restore`. No remote resolution, no version ranges, no graph solved remotely. Whether Conan
could do better by itself was measured rather than looked up: `conan remote add` in Conan 2.32.0 accepts
one remote type, `local-recipes-index`.

The whole loop was driven end to end rather than asserted over an argv - published, then resolved from a
second project, and for Conan restored into an empty cache and built against. [Handing a package
over](../handing-a-package-over/) is the chapter. Nothing to do: five declared coordinates, and a
product that declares none of them is unchanged.

### The help screen names the simplon that is answering (si#125)

`<product> --help` rendered byte for byte the same screen whether the kernel behind it was a released
wheel from PyPI, an editable checkout on the same machine, or a version pinned two releases ago. Both
facts existed the whole time - `simplon.__version__`, and `importlib.metadata` knows the distribution -
and neither was ever printed. The root app's epilog now carries one line under the command panels:

```text
assembled by simplon 0.9.0.post1.dev8+g4b69283dc.d20260909 (editable install, /tmp/wt-125/src/simplon)
assembled by simplon 0.9.0.post1.dev8+g4b69283dc.d20260909 (/tmp/wheelvenv/lib/python3.13/site-packages/simplon)
assembled by simplon 0.0.0.dev0+unknown (no installed distribution, /tmp/bare2/simplon)
```

It reads *assembled by* rather than a bare version because the line sits under the **product's** own
commands, where a number alone would be read as the product's. The editable marker comes from PEP 610
`direct_url.json`, which is what pip records for `pip install -e`, rather than from the shape of the
path. Every half degrades to a phrase instead of raising - a help screen that fails because the tool
could not introspect itself is worse than one that says *unknown* - and a product that declares its own
epilog keeps it, with the kernel's line below it. Top-level app only, and no `--version` flag comes with
it. Nothing to do.

### Before you bump

**The scaffolder no longer empties your manifest of its comments** (si#110). `support toolchain` read
the file with `yaml.safe_load` and wrote it back with `safe_dump`, so on a freshly scaffolded manifest
forty-two comment lines became zero and every flow mapping was expanded to block style. It splices its
commands into the text now, and everything you wrote survives. Nothing to do beyond bumping.

**The C++ `analyse` profile analyses something, and can go red** (si#111). `clang-tidy -p build` takes
its sources as positional arguments and named none, so the entry refused every run it was ever given.
It is `run-clang-tidy -p build -quiet -warnings-as-errors=*` now, which reads the compile database
`configure` already wrote and walks it. The last flag is what makes the command a check rather than a
report: clang-tidy reports its findings as warnings and exits 0 without it, so `analyse` was green on
every tree. Re-run `support toolchain cpp <version>` to pick the new argv up, or edit the one line in
your manifest - the scaffolder never overwrites a command you already have.

## 0.9.0

**0.8.0 shipped a uniform build that no product could drive.** This is the release that can, and the
reason it took a second one is worth stating plainly: every test in 0.8.0 was a unit test with a stubbed
`run`, and the plan's own end-to-end step - "netctl's CI green with `build compile`" - was never
executed. Two people writing use case chapters drove it for real within a day and found four defects
between the design, the scaffolder and the loader.

A minor rather than a patch, because si#106 adds a gate kind: a manifest surface, not a repair.

### Before you bump

**`support toolchain` takes the version as a second argument** (si#105). It always needed one - every
profile's image is a `{version}` template - but the catalogue declared only `language`, and
`signatures.bindable` drops `**kwargs`, so it raised `KeyError: 'version'` for every language:

```
./<product>.sh support toolchain cpp 19
```

or pinned per command with `with: { version: "19" }`.

**The block the scaffolder writes now assembles** (si#105). It did not: the loader binds `with:` keys to
impl PARAMETERS, and `run_toolchain` took none of `image`/`workdir`/`argv`/`env`/`caches`. A manifest
that a product's own scaffolder writes and the product's own loader then refuses is the shape this
release exists to remove. If you scaffolded under 0.8.0, re-run `support toolchain` - nothing else to do.

**A command's tail reaches the tool again** (si#105). "Manifest first, caller appends" is what the design
promises and 0.8.0 did not deliver: `./x.sh build compile --verbose` answered `No such option`. It needed
both halves - a variadic positional AND `passthrough_args: true` - and neither works alone.

**No `instance:` section is needed unless a command declares caches** (si#105). It was resolved before
anything asked whether a cache existed, so a freshly scaffolded product died on its first command.
`simplon.yaml` itself has no such section.

### A command in the product's tree can back a gate (si#106)

`Gate` took `suite:` (a pytest root) or `impl:` (a product callable). A `toolchain:run` command is
neither, so a product whose test runner is a containerised toolchain got an exit code and NO verdict - no
`setup-failed`, no marker, no Allure archive.

Measured, and this is the failure that made it urgent rather than untidy: a C++ product's `build compile`
exited 2 on a type error, and `build unit` then reported **`100% tests passed, 0 tests failed out of 3`**
off stale binaries. A positively wrong green.

A gate may now name a command:

```yaml
suites:
  unit:
    command: "build unit"
    preamble: "build compile"
```

The kernel resolves it the way the CLI does - the body its `task:` names, with that command's own `with:`
pinned - and turns the rc into the same verdict vocabulary every other gate produces. The alternative,
making `toolchain:run` usable as an `impl:`, was rejected: a gate's `impl:` is called with no arguments,
so it would need a second copy of image, argv and caches inside `suites:`, beside the command the product
already declares. Two declarations of one build drift, and then the verdict is about a line nobody runs.

The cost is stated in the code: the command is resolved at gate-run time, so a typo is a run-time
refusal - but everything resolves BEFORE the results directory is cleared, so a typo can no longer cost
the last real run's archive.

### Two use case chapters, driven rather than described (si#108, si#109)

`case-cpp` and `case-dotnet` walk the whole loop with real products - CMake and ctest, `dotnet build` and
xUnit - scaffolded, wired to the kernel and run. Every command on those pages is resolved against the
tree their fixture manifests assemble, every quoted refusal is pinned against the code that builds it,
and every step carries `run`, `derived` or `does not exist yet` with the ticket where a decision is open.

They are the reason this release exists: writing them is what drove the kernel, and driving it is what
found si#105 and si#106.

## 0.8.0

One merge, and it adds a catalogue coordinate - which is why this is 0.8.0 and not 0.7.2. Nothing existing
changes; the count on the [rules page](../../building/rules/) moves from 25 to 26.

### Before you bump

**Nothing.** `support:ci-privileges` is DECLARED and not placed, so no product's CLI grows a command it
did not ask for. If you want it, place it like any other offered task:

```yaml
support:
  commands:
    ci-privileges: { task: "support:ci-privileges" }
```

### The uniform build: one task, four languages (si#95, si#99, si#100, si#101)

The largest thing in this release, and the shape it took is the argument for it.

**`toolchain:run`** runs a pinned image over the product tree, as the calling user, with named caches. It
is the half of a build that is identical in every language: Java, C++, .NET and Python differ in which
image runs and which argv it is handed, not in how a container is wired to a source tree. It is a
FAMILY rather than a placement, because a toolchain is needed by `build` AND `test` - ctest, dotnet test
and gradle test all belong under the latter.

**`support:toolchain`** writes a language's ready-made configuration into the product's manifest:

```
./<product>.sh support toolchain cpp 19
```

lands `configure`, `compile`, `unit` and `analyse`, each a `toolchain:run` command with a pinned
`silkeh/clang:19`. A product declares its parameters and receives the rest.

**Scaffolded, not resolved at run time**, and that is a safety property rather than a convenience. A
profile read while a build runs would let a kernel release change what that build does - the same class
as an unpinned image, one level up. Written into the manifest, the product owns what it runs from then
on, and this kernel's table can move without moving anybody's build.

**It never clobbers.** A command that already exists is left as it is and named. The edit was somebody's
decision, and the scaffolder cannot tell a deliberate one from a stale one.

Both coordinates are DECLARED and not placed, so nothing appears in a product's CLI until the product
asks for it.

### A gate may be backed by a command, so a containerised runner gets a verdict (si#106)

The uniform build above buys a product the COMMAND and, until this, lost the VERDICT. A gate took a
pytest root (`suite:`) or a product callable (`impl:`); a `toolchain:run` command is neither, so a
product whose test runner is `ctest`, `dotnet test` or `gradle test` got an exit code and nothing else -
no `setup-failed`, no setup marker, no allure results, no archive.

A gate may now name a command in the product's own tree, and its two hooks name commands too:

```yaml
gates:
  - name: "unit"
    command: "build unit"          # what a person types, and what the gate reports on
    preamble: "build compile"      # the build that has to succeed first
    results: "clear"
```

**The `preamble:` line is why this is a kind and not a convenience.** Measured on a C++ product:
`build compile` exited 2 on a type error, and `build unit` then reported `100% tests passed, 0 tests
failed out of 3` - ctest over the binaries the failed compile had not replaced. Three passing tests for a
product that does not compile, and nothing could see the pair, because neither half was a gate. Named as
a gate's setup, a non-zero build ends the level as `setup-failed` and the test command never runs.

The command is resolved the way the CLI resolves it - the body its `task:` names, with its own `with:`
pinned - so the image and the argv are declared once, in the command, and the verdict is about the
command a person actually types.

**What a product has to do about it: nothing.** `command:` is a third alternative beside `suite:` and
`impl:`, both of which mean exactly what they did. Two load-time refusals are worded differently (the
exactly-one-kind lock now offers three, and the opacity lock names the kind it is refusing), and no
refusal was added or removed. The [test levels chapter](../../building/test-levels/) carries the whole
of it.

### The release guard asked for notes about pull requests (si#97, si#98, si#103)

Two defects in this repository's own gate, found by trying to cut this release four times.

**The first was red on every pull request** and had been for as long as the rule existed.
`test_every_merge_in_a_documented_range_names_its_ticket` asks that every merge in a release range names
a ticket. CI runs `on: [push, pull_request]`, and the `pull_request` event checks out
`refs/pull/N/merge` - an ephemeral merge GitHub composes, whose subject is exactly
`Merge <40 hex> into <40 hex>`, with no ticket and no way for an author to add one. So every PR carried
one permanently red check that had nothing to do with its content.

**The second was a catch-22 and stopped this very release.** A pull request merged from the web interface
gets `Merge pull request #N from <branch>`, so the PR carrying the release notes named ITSELF - and no
notes can anticipate their own merge. A follow-up PR would have brought its own number too; the regress
had no floor.

Both rest on one distinction. An **authored** merge subject is a statement about the WORK; GitHub's
wording is a statement about the VORGANG. The guard now reads the first as written, and for the second
reads the commits that merge BROUGHT IN, which is where the author put the number. The unit stays the
merge; only the place the statement is looked for moves one level down. With a floor: several merges
from before the convention name nothing in their commits either, and dropping those would excuse work
rather than describe it, so the subject's number remains the fallback.

**What a product has to do about it:** name the ticket in the COMMIT, not only in the pull request
title. `docs(#42): ...` rather than `docs: ...`. That is this repository's own convention already, and
it is now the thing the guard reads.

A defect in this repository's own gate, and it had been red on every pull request for as long as the
rule existed. `test_every_merge_in_a_documented_range_names_its_ticket` asks that every merge in a
release range names a ticket in its subject. CI runs `on: [push, pull_request]`, and the `pull_request`
event checks out `refs/pull/N/merge` - an ephemeral merge GitHub composes, whose subject is exactly
`Merge <40 hex> into <40 hex>`, with no ticket and no way for an author to add one.

So every PR carried one permanently red check that had nothing to do with its content. The fix skips
that one subject and only that one: a full match on the machine format, so a real merge whose author
forgot the number is still caught, and one that prefixes GitHub's wording to disguise itself is not
excused.

### Also in this range: a design and its plan, and nothing built from either (si#95, si#96)

The spec for `toolchain:run` and the uniform build across Java, C++, .NET and Python landed in this
range as a document, and its implementation plan behind it. **Nothing in 0.8.0 implements either** -
they are in `docs/superpowers/specs/` and `docs/superpowers/plans/`, to be read and argued with before
code exists.

Both numbers are here because their MERGES are in the range, and this paragraph is what keeps them from
reading as shipped changes. Worth noting for si#89: neither number appears in a single authored commit
subject - they come only from GitHub's automatic `Merge pull request #NN` line, so the guard is asking
for notes about pull requests rather than about work.

### The CI privileges of a host, as a task that refuses unless it is root (si#92, si#93)

Every product that puts a CI agent on a host was writing the same six lines by hand, and one of them is
easy to leave out:

```sh
grep -q '^#includedir /etc/sudoers.d' /etc/sudoers || echo '#includedir /etc/sudoers.d' >> /etc/sudoers
```

Without it the drop-in in that directory is **inert**, and everything still looks right. Measured on three
CI hosts that answered `sudo: a password is required` while the file sat at exactly the expected path with
exactly the expected content. Nothing in those six lines is product knowledge - only the user name.

Three things it does that a copied snippet does not:

- **It refuses unless it is root, and says why.** This grants the privilege the kernel needs in order to
  be allowed to do anything, so it cannot take it from inside a job - si#87 drew the same line one level
  down. The refusal names the cure; "it did not work" would be useless.
- **It validates the sudoers file before it is in force.** A broken file in `/etc/sudoers.d` does not fail
  the command, it breaks `sudo` for everyone on the host - and the way back needs the privilege that just
  stopped working. So it is written beside the directory, checked with `visudo -cqf`, and only then moved.
- **It verifies as the USER, not as root.** Root can always sudo, so a check from here would pass on a
  host where the grant did nothing. It also says that an agent which is already running must be restarted,
  because a process inherits its groups at start - and it does not restart anything, because it does not
  know what the service is called.

**Why it is not placed**, while `support:install` beside it is: this one hands out `NOPASSWD: ALL`. A
command that changes who may become root on a machine has to be something a product asked for, not
something it received along with the kernel.

## 0.7.1

Seven merges, and they have one thing in common worth saying first: **six of the
seven were found while doing something else and reported instead of quietly
repaired.** Four came out of driving the Java use case (#26), one out of fixing
a neighbouring ticket, one out of a consumer's migration. That is the habit this
kernel is trying to keep, and this release is what a week of it looks like.

### Before you bump

**`parent_suite:` no longer passes silently where it does nothing** (#79).
`report.merge` accepted the key and tagged nothing when the source was JUnit XML
- only Allure raw results (`*-result.json`) were ever tagged. A Java product
therefore declared a key that had no effect, and nothing said so. If your
product sets `parent_suite:` on a JUnit-XML suite, you were not getting what you
wrote.

**`docs:render` no longer runs as root** (#78). In the usual CI order it made the
next Gradle run impossible: the render wrote root-owned files into the tree, and
the build after it could not touch them. The uid is now read off the TREE rather
than set, so the render writes as whoever owns what it is writing into.

**`SETUP_MARKER_ENV` is advertised** (#80). Since #59 a product-owned runner may
report that its SETUP fell over - the run then says `setup-failed` with
`ran = False` instead of `failed`, which is the honest distinction between "the
suite ran and was red" and "there never was a suite". It was reachable and
undocumented, so no product reached it by default.

### The docker group membership belongs to the install (#87)

`_grant_socket_access` did two things of very different durability under one
name: `usermod -aG docker` is durable but takes effect only in a NEW session,
while the `setfacl` / `chmod 666` on the socket is transient and gone when the
daemon recreates it. Because the ACL works instantly, nothing ever revealed that
the membership had not reached a long-lived caller at all - a process inherits
its groups at start, so a service already running never gets it. And the whole
block sat behind `if not _daemon_reachable()`, on the failure path, so on a host
whose socket happened to be permissive it never ran.

Measured on three CI hosts that ran green for months and then failed at three
unrelated moments with no commit in common: `getent group docker` answered
`docker:x:991:` - the group exists and is EMPTY. `get.docker.com` creates it and
puts nobody in it, so a freshly installed host locks out every non-root caller.

The membership is now established by `_install_engine`, the one moment privilege
is known to be present and the state is being created from scratch, and
`_grant_socket_access` still calls it so an older host gets it too. root is
skipped - it reaches the socket by being root.

**What a product still has to do itself**, because the kernel cannot: grant the
passwordless sudo (the seed privilege the kernel needs in order to be allowed to
do anything), and, if it provisions a long-lived service, set the membership
before that service starts. A job-time call never reaches an agent that is
already running.

### The refusal says what re-applying costs (#56)

Found by a consumer migrating to 0.4.0, and it is this project's own defect class
in a tool built against it. The refusal for an old-form manifest prints a
complete rewrite - correct, loaded in one pass since #42, and carrying **zero
comments**, because it is generated from the parsed manifest. Applied, the
migration is green and the reasoning is gone. The refusal now says how many
comment lines re-applying it would throw away, so the choice is made with the
price visible instead of after it.

### The group description reaches the generated reference (#77)

Found while fixing #75 and reported rather than repaired along the way. #75 got
the group description from `catalogue.yaml` onto the screen - `--help` says
*"Produce the artefacts."* instead of *"build commands."*. The generated command
reference still showed the old text: a third surface of the same taxonomy that
nobody had counted. The surfaces are counted now, and the description reaches all
of them.

### Named here, and deliberately not shipped: the notes guard itself (#89)

Cutting this very release ran the guard into its own gap. `tests/test_releases_page.py` stopped the tag
because the section described one of seven merges - which is exactly what it exists for, and it worked.
But it is a HOUSE rule: it lives in this repository's `tests/`, `src/simplon/` knows nothing of it, and
the catalogue places nothing, so **no other product has it**. A product on this kernel can tag, publish
and never write it down, silently.

si#89 records lifting the mechanism into the kernel as a placeable gate - the rule is product-free, and
only the page path, the floor and the exemption list are product data. **None of it is in 0.7.1.** The
number appears in this release's merge range because the notes commit referenced it, and this paragraph
is here so that the number does not read as a shipped change.

### The self-exemption was measured against a population that never saw the rule (#83)

The fourth wrongly chosen population in this repository, and it concerns a number
that has been quoted repeatedly. The struck rule `check_every_task_is_used` read
only `product_tasks` - so the exemption granted in #48 was justified against a
set the rule never examined. The reach of an expression rule is now MEASURED
rather than labelled, which is the same move this repository has made four times
and, on the evidence, will make again.

## 0.7.0

One merge, and both halves of it are the same observation: a value every product
answered the same way was being carried as if it were a decision.

### Before you bump

**The committed shell completion moves to `deploy/completions/`** (#84). It was
written into `completions/` at the product root — which is where a reader looks
for what the product *is*, and a directory holding one generated shell file is
not that. `deploy/` is where this kernel's other outputs already live.

The path is still **not configurable**, for the reason it never was: a knob here
would be a second place to look for one file, and an installation instruction has
to be able to name the path without asking.

Migration is two steps and a shell:

```bash
git mv completions/<product>.bash deploy/completions/<product>.bash
./<product>.sh support completion          # rewrites it in place, and prints the source line
```

Then re-source it — the line in your `~/.bashrc` names the old path and will
silently complete nothing after the move. `support completion --check` returns 1
until the file is where the kernel now writes it, so a product whose CI runs that
check finds out rather than losing TAB quietly.

It is deliberately **not** `deploy/<orchestrator block>/completions`, which was
the first proposal: the block does not sit at one path across products — this
repository and agile-cockpit keep it at `deploy/orchestrator`, cleon at
`deploy/provision/orchestrator` — so a constant naming it would be right in one
checkout and wrong in the next. `deploy/` is the part they share.

**`suites.reports:` is now optional and defaults to `tests/reports`** (#84). It
was required until every product had written the same line, which is the point at
which a universal answer has been masquerading as a per-product decision — and a
required key with only one sensible answer teaches people to copy it rather than
choose it. `tests/reports` sits beside the suite rather than under the product
root, because the outputs of a test run belong with the tests and a root
directory called `reports/` says nothing about what produced it.

**Nothing changes for a manifest that declares the key**: a declared value still
wins, and no existing product moves unless it deletes the line. An *empty*
`reports:` is still refused rather than read as a request for the default —
`""` is a statement, and reading a typo as a default is exactly the silence a
default must not buy.

## 0.6.0

Seven merges. The theme, if there is one, is ownership: a test run learns which
results are its own, an image declaration is checked against the tree it points
into, and two rules the kernel had been carrying were measured and one of them
struck.

### Before you bump

**A test run now owns its results directory, and your report may count fewer
tests than it used to** (si#70, si#69). `test report` merged whatever stood in
the declared merge sources, and those sources are the *product's* directories — a
Gradle build's JUnit XML, an npm reporter's output — which no `results: clear` on
either kind of gate has ever touched. Measured: a build that stopped in
`:compileJava` shipped an archive reading `{"failed":0,"passed":3,"total":3}`,
decoded from a file 66 seconds older than the run that shipped it. The step now
knows when the run began; files written before that are left where they are and
**named in the line**, with the reason. The same run now reports
`{"passed":0,"total":0}`. If your numbers drop after the bump, that is the defect
leaving, not arriving — and `test report` on its own, which has no run behind it,
still merges everything present, because that is its documented job.

Alongside it, `wrote_results` no longer infers ownership from the gate verdicts
(si#69): reaching the clearing step *is* the ownership, and deriving the same
fact a second way from the outcome had already been wrong once.

**`results: clear` is now accepted on an `impl:` gate** (si#61). 0.5.0 recorded
this as a measurement and left it: a product with no pytest anywhere in it could
not write a taxonomy that loads, and the way out was a pytest gate containing
`assert True`, a 29 MB suite venv, and an archive that counted four tests for a
product that has three. **No new key was invented.** `results` was refused on an
`impl:` gate because it was ineffective there, and the ineffective half is what
got repaired — the `impl:` branch now honours the clear. It is the one key that
means the same thing on both kinds of gate, because it is not a statement about
what a gate writes but about whose run the directory belongs to. Migration: none.
Both manifests carrying a `suites:` section open with a pytest gate, so nothing
changes for them, no refusal was added or removed, and the [rules
page](../../building/rules/) is untouched.

**`build:image` refuses a declaration that points at nothing, before it asks for
docker** (si#74). Both `dockerfile:` and `context:` are checked against the
product root, the message says *which* of the two moved, and it is asked before
`ensure_docker` — so "my manifest points into thin air" no longer gets "you have
no docker" for an answer on a machine without one. The finding came from a real
product whose Dockerfile had moved into `deploy/` with nothing in the kernel
noticing; the kernel's own test fixtures then turned out to carry the same defect,
three of them building an image with a context that never existed.

**A nested group with a namesake member is refused** (si#60). `support.git` with
a member called `git` and a sibling beside it does not assemble: the taxonomy
matches on the last segment while the assembly looks the spec up under the full
dotted path, and the result was `KeyError: 'support.git'` — a stack trace where a
diagnosis belongs. The refusal names both halves and both ways out: rename the
member, or move the group to the top level, where the two names are the same
string. The capability was deliberately *not* built: measured over this kernel's
manifest and the five in `surface.CONSUMERS`, zero of six declare such a group,
so what a product needs is to be told where the floor is.

**A task you declare and no command places now loads** (si#53).
`check_every_task_is_used` is gone. It was the one expression rule that exempted
the kernel from itself, and measuring the exemption is what ended it: it would
have refused 14 of the kernel's own 22 catalogue tasks, it was the only refusal
with no measured cause in ticket, commit or docstring, and across all six
reachable manifests it had never refused anything. A catalogue is an offer, and a
product may now write one too. **The price is recorded rather than implied:** a
product that moves a command onto a catalogue coordinate and leaves its own body
standing beside it now loses that body *silently* — the manifest loads, the
catalogue body runs, and the product's own is reachable from nowhere.

**The narrower diagnosis was then built** (si#81), and it draws the line
somewhere other than "used" and "unused". A catalogue coordinate is placeable by
any product, so unplaced there means *offered*; a manifest's own `tasks:` entry
is a bare name reachable only from commands in that same manifest, so unplaced
there means *unreachable*, with no second reading. Refused is the narrow case
only: a declaration no command instantiates **and** whose name a command has
already spent on a different body. A task nobody names still loads. What the
narrow form does not catch is recorded rather than implied — a move that renames
at the same time. Measured over all six reachable manifests: zero violations, and
zero for the broad form too, so the narrowness costs nothing today and only stops
it costing something later.

**Group help text changes** (si#75). `catalogue.yaml` has declared a description
per group since it was written and nothing ever rendered it; the CLI built
`"release commands. Environment-agnostic (no env)."` out of the group name
instead. Measured across the catalogue and all six manifests: eight group paths,
all eight carrying a `help:`, and 33 of 40 rendered sub-apps showing the invented
sentence.

```
before   build commands. Environment-agnostic (no env).
after    Produce the artefacts. Environment-agnostic (no env).
```

**Prepended, not replaced**, and that was decided against the real texts:
replacing takes from `deploy --help` the only line saying the group does not run
without an environment token, and no `help:` carries that half.

**`docs:site` writes `build/hugo-cache/`** (si#27) — the kernel's convention,
under the same `build/` your `clean` and `.gitignore` already cover.

### A site build no longer needs the network

si#27 asked for `hugo mod get` to be made conditional and called that the likely
answer. **The premise is refuted, and the measurement is why.** With the fetch
skipped entirely and no host-side cache, the build still dies at `git ls-remote`,
because the build resolves the theme module itself — and the condition would never
have touched FlexSearch and mermaid, which Hextra pulls through
`resources.GetRemote` while rendering. A persistent cache fixes both; the
condition fixes neither. So there is no condition: it bought 0.9 s and would have
paid with a build that, on a wrongly answered question, renders against the old
theme and says nothing.

The proof is a build with **no network**, not a faster one: every container run
with `--network none`, rc 0, 26 pages, diagram rendered. The same run against the
previous kernel exits 1 at `git ls-remote`. Three pages that said an offline build
was impossible now say what it costs instead — a fresh checkout, a `clean`, and a
moved pin each need the network once.

### Also

- **`verdict.exit_code` is applied only where its precondition is carried**
  (si#71). The 128+n translation belongs to a child process's wait status; it was
  being applied to every gate's rc, including an `impl:` gate's, which is a Python
  callable's return value and names no signal however negative it is. Harmless in
  every case measured — and a docstring and a use that said different things,
  which is how the next reader widens the wrong one.

### Documentation

**A complete Java use case** (si#26), the other half of the pair 0.5.0 opened:
[Delivering a Java product](../case-java/). Nine of its thirteen steps were
driven rather than derived, including `build docs` with docToolchain producing
HTML and PDF — the step the Python chapter says outright it never saw. Three are
derived and one does not exist. The three number series come out of the archive
rather than out of prose, and the interesting one is the third:

```
green             rc 0   passed 3, total 3    verdict passed
one test broken   rc 1   failed 1, passed 2   verdict failed
compiler error    rc 1   passed 0, total 0    verdict setup-failed
```

Three tests, not four — the difference si#61 made, in one number.

**The site's own numbers are counted and its links resolved** (si#66, si#67).
Three pages counted the examples and all three were wrong — eight sections
described as "seven", "Seven" and "six" — so the counts are built from the source
rather than typed, along with five other unchecked numbers. And there is a link
checker: 84 internal links across 17 pages, none of them dead, with every anchor
checked against the target page's headings. Hugo renders a dead relative link
without complaining, and a dead `menu.pageRef` builds rc 0 with no warning at all
— measured, which is why the checker exists.

### About these notes

The section above 0.4.0 used to be checked only for *existing*. si#82 measured
what that permitted — 0.5.0 described two of its fourteen changes and was green —
and `tests/test_releases_page.py` now holds each section against the merges in
its own range: every ticket number merged into a release has to appear in that
release's section. Not the wording, which no tool can derive; the completeness,
which it can.

## 0.5.0

Fourteen changes went into this tag. This section named two of them for the first
weeks of its life, because it was written from the pull request the tag was cut
through rather than from the range the tag covers — si#82 measured that gap, and
the twelve below come from `git log v0.4.0..v0.5.0` rather than from anybody's
memory of the release.

### Before you bump

**Four modules that 0.4.0 announced as moved are gone** (si#73). If your product
still imports one of the old paths, it now fails with `ModuleNotFoundError` rather
than warning. The fix is the right-hand column:

| Gone | Import instead |
|---|---|
| `simplon.allure` | `simplon.tasks.allure` |
| `simplon.vcs` | `simplon.tasks.gitops` |
| `simplon.images` | `simplon.imagenames` |
| `simplon.nexus` | `simplon.nexusproxy` |

Measured through the API on the day of the release rather than assumed: **one
product is affected, at three lines** — netctl, at
`orchestrator/tooling.py:32`, `orchestrator/guard.py:55` and
`test/.../test_nexus_manifest.py:20`. It is not, however, a product this
grace period ever reached: netctl pins `simplon==0.3.0`, where `images` and
`nexus` are the *real* modules and `imagenames`/`nexusproxy` do not exist yet.
Those three lines are part of whatever upgrade takes netctl past 0.3.0, and
they change in the same commit that lifts the pin.

Two further lines the record named turned out never to have been simplon's:
asbundle reads `from delivery import images` — a different kernel that ships a
module of the same name — and biz-cockpit had already migrated. See
[Surface](../../building/surface/) for why re-measuring beats remembering.

**A killed run is a fifth outcome, and it leaves a different exit code**
(si#55). A run a signal ended used to be reported as `failed` with `ran = True` —
"the suite ran and reported failures", said about a suite whose output was empty.
It has its own outcome now: `killed`, `ran = False`, carrying the signal's *name*
rather than a negative number, because SIGTERM tells a reader something and `-15`
does not. Two things a product may notice. `simplon.verdict.Verdict` has a fifth
member, so anything that enumerates the four gets one more. And the exit code
changed: `sys.exit(-15)` reached the shell as 241, two numbers for one event and
neither of them saying "ended by a signal", where a killed gate now exits
`128 + n` — 143 for SIGTERM, the number a shell already writes into `$?` for the
same child. Measured end to end, and applied narrowly: the translation is derived
from a child process's wait status only, never from an arbitrary return value.

**Every product gains a `support completion` command** (si#58). It is *placed*
rather than offered, so it appears in your CLI whether you asked for it or not.
It clears the bar `support install` is placed on — it reads no manifest section
beyond the command tree every manifest already carries, it publishes nothing, and
it writes only under the product's own root — and the argument that settles it is
what the thing is: a completion you have to know about in order to ask for it is a
completion nobody has, because pressing TAB is the thing that does not work yet.
It writes `deploy/completions/<product>.bash`, and `--check` reports drift and writes
nothing, which is what makes committing the file worth anything. Generated rather
than switched on: Typer's own `--install-completion` runs the program on every
TAB, measured here at 340–360 ms, against 0.16 ms for the generated function.

**A scaffolded file's line endings now follow the file, not the machine**
(si#57). `bootstrap.write` used the *scaffolding* host's `os.linesep`, so two
machines scaffolding the same product produced 74 bytes of difference, and a
product scaffolded on Linux handed Windows users an LF `.cmd` built from five
multi-line `if` blocks. The endings are now decided per file by its extension —
CRLF for `.cmd`, LF for everything else. Nothing under you changes on the bump:
`simplon init` still refuses to overwrite an existing file, so a product that
wants the corrected bytes re-scaffolds with `--force`. The two halves are not
equally well evidenced and the code says so: the shell half is reproduced here (a
CRLF shim does not launch on this host at all — the kernel reads `bash\r` as the
interpreter name), while the `cmd.exe` half is this repository's standing claim,
carried in its `.gitattributes`, with no Windows machine behind it.

**An `impl:` gate now says less about your product, and that is the fix**
(si#65, si#59). A gate that hands the work to the product's own runner used to
get the default explanation — "the suite ran and reported failures" — and it got
it unchanged where Gradle had stopped in `:compileJava`, with nothing compiled,
no test run and no XML written. All three records claimed a green 1/1 table. The
line now reads:

```
unit: failed (rc 1) - the product's own runner returned this rc; the kernel did
                      not run a suite here and cannot say whether one ran at all
```

If anything of yours matches on the old sentence, it is gone. What the kernel
does *not* do is invent a level it has no basis for: a runner that says nothing
still gets `passed`/`failed` and no third state. A runner that *can* say more now
has a way to, because the setup marker is no longer pytest-only by placement — a
Gradle build that knows `:test` never ran writes it, and the run reports
`setup-failed (gradle build (:test never ran), rc 1)` with `ran = False`.

**Your orchestrator did not move** (si#24). The kernel moved *its own* to
`deploy/orchestrator`, using the `--orch-dir` it has offered since 0.1.9 rather
than any new capability — the same movement as pinning its own images: the kernel
submitting to what it already sells. No product directory relocates and no default
changed; `simplon init` still scaffolds `orchestrator/`. What did change is the
launcher it writes: a shim whose orchestrator directory is missing now fails
loudly and names the path, where before `python3 -m venv` created the very
directory the launcher was looking for and pip failed afterwards without naming
one.

### New

**`release:asset` attaches declared files to a GitHub release** (si#72). The other
half of `release:artifact`: that one publishes a directory to a registry, where a
consuming pipeline pulls it with its own token; this one puts files on a release
page, where a person downloads them. A product declares an `assets:` section and
pins one with `with: { name: ... }`, the same shape `release:artifact` uses.

```yaml
assets:
  bundle:
    source: "build-out/product_*.zip"   # glob, relative to the product root
    repository: owner/name              # optional — gh resolves it from the remote
    title: "..."                        # optional, defaults to the tag
    notes: "..."                        # optional
```

It runs `gh`, so the kernel gained no GitHub client and no new dependency, and
the token comes from the two sources `githubpackages.token` already documents.
Two behaviours are worth knowing because they are decisions rather than
defaults: a `create` that fails because another matrix cell got there first is
read as success and the upload proceeds, while any other failure stops before
anything is attached; and `--notes` is always passed, because `gh` opens an
editor where it has a terminal and refuses where it does not.

Which of the two a product offers is a question about its audience — and about
what its licence lets it hand out. Neither is placed; both are offered.

**Workflows come out of the manifest** (si#40). The manifest's second output:
`support:workflows` renders a product's `.github/workflows/*.yml` from a
`workflows:` section, so a renamed command breaks generation instead of leaving a
workflow calling something that is gone, and `--check` reports drift and returns
1. It is *offered* rather than placed, because it reads a manifest section and a
product without one would get a command that dies on its first line:

```yaml
groups:
  support:
    commands:
      workflows: { task: "support:workflows", help: "Regenerate the CI workflows." }
```

Three decisions are worth knowing before you declare it. Unknown keys at workflow
and job level are **carried through** rather than refused — measured against
sixteen real workflows, refusing them would have made eleven of the sixteen
inexpressible without the kernel ever needing an opinion about one of those keys;
a *step* is the exception, because it has exactly one body. `command:` is that
body rather than the whole step, which is what makes 34 of 41 real steps
expressible at all. And `handwritten: "<why>"` is how a file declines to be
generated: a file in the directory that nothing names is reported with rc 1, and
so is a `handwritten:` entry whose file has since disappeared — a name with
nothing behind it fails the same way an unowned file does, by looking accounted
for.

### Fixed — five findings, every one of them from running a real Java product

si#26's Java half was driven rather than described, and the drive produced five
defects sitting in one seam. Two are the `impl:` gate sentence above (si#65,
si#59). The other three:

- **si#63** — an exception inside the report step left `test-verdict.json` saying
  `passed` while the run ended red. The durable record was the thing that lied,
  which is the worst place for this defect to sit.
- **si#64** — the merge line announced its *intention*: "per-module results merged
  (parentSuite=X)" was printed when JUnit XML meant nothing was tagged, and again
  when the source directory was not there at all, and both times it read the same.
- **si#62** — `report.merge` raised `IsADirectoryError` on Gradle's standard
  layout, at `test-results/test/binary`. Settled by measurement rather than
  argument: an allure results directory is read *flat* — `aaa-result.json` plus
  `sub/bbb-result.json` yields `total: 1` — so recursive copying was moving bytes
  the renderer ignores, and skipping is the only true answer.

The capability that was already there was not taken along with the fix: JUnit XML
still arrives on Gradle's default layout without the detour.

### Measured, and deliberately not fixed here

**A test taxonomy with no pytest anywhere in it did not load** (si#61). Measured
against a real Java product: both spellings of the `suites:` section were refused,
and the way out was to ship a pytest gate containing `assert True`, a 29 MB suite
venv, and an archive that counted four tests for a product that has three. The
finding was recorded rather than patched, and it was classified twice before it
was believed: it is *diagnosis*, not an expression rule — without a clearing gate
nothing ever empties the results directory, and a stale result file survives the
whole run. What was actually missing was a word, not a rule, and that word ships
in 0.6.0.

Filing it turned up the larger finding. The two refusals stood in **no population
at all**: the refusal census counted two modules, and `tasks/testrun.py` was not
one of them — sixteen load-time refusals outside a census whose entire purpose is
that the sum cannot grow quietly. All sixteen were classified: fifteen diagnosis,
one expression rule. See [Rules](../../building/rules/) for the live split.

### Documentation

**A complete Python use case** (si#26), from `simplon init` to a deployed local
host: [Delivering a Python product](../case-python/). Every step carries one of
three labels — `run`, `derived`, `does not exist yet` — and the ratio is stated
rather than implied: eleven of fourteen steps were driven here, two are derived,
and one does not exist and names the open ticket instead of inventing a step. The
chapter is held against the product by `tests/test_case_python_chapter.py`: the
commands against the assembled command tree, the coordinates against the
catalogue, the five outcomes against `simplon.verdict.Verdict`, and every version
it names against `git tag`.

## 0.4.0

Thirty commits since 0.3.0. Three of them change what an existing product must
do; the rest add capability or explain what was already there.

### Before you bump

Two of the products that install this kernel do not load against 0.4.0 as
they stand, measured through the API rather than assumed:

| product | what stops it |
|---|---|
| biz-cockpit | still on the flat manifest form |
| netctl | `support install` redeclares a `task:` without `override: true`; `monitor accept` places `test:accept`, and a phase-named coordinate belongs in its phase |

*(A sixth manifest is on the flat form too and is deliberately not listed:
its product does not install this kernel at all, so no version of it can stop
that manifest loading. Counting it here would repeat the mistake 0.4.0 fixed in
five module heads, which named a consumer that never was one — see
[Surface](../../building/surface/) for how that is measured now.)*

Every one of those refusals prints the fix, and for the flat form it prints the
whole rewritten manifest. But the work is real, so plan it before the bump
rather than during it.

### What a product has to change

**The flat manifest form is gone.** A manifest that writes `impl:` directly
under a command no longer loads. The refusal prints the rewrite — the whole
manifest, in the tree form, ready to paste — and that rewrite was proved by
using it: the kernel's own `simplon.yaml` was migrated with exactly the printed
output. One case still needs a hand: where the catalogue places the same name
(`support install`, `release tag`), the printed block lacks the `override: true`
the merge then asks for, and the second refusal names that fix.

**And it replaces the structure, not your comments.** The rewrite is generated
from the parsed manifest, so a comment explaining *why* something stands where
it does does not survive it. A consumer whose manifest carried forty lines of
reasoning used the output as a blueprint and rebuilt by hand rather than
pasting — otherwise the migration would have been green and the reasons gone.
If your manifest is uncommented, paste it; if it is not, read it.

**`release tag` disappears from every product.** It was placed; it is now
offered. A placed command has to be useful in *every* product, and a product
with no release workflow does not need one. Declare it yourself if you want it:

```yaml
groups:
  release:
    commands:
      tag: { task: "release:tag", help: "Cut and push the release tag." }
```

**`env_groups:` may no longer CONTRADICT the platform.** An entry is measured
against the merged node: one that *disagrees* — naming a group the catalogue
shapes the other way — is refused, with the same sentence `env_first:` gets in
the same position. One that *agrees* is harmless, probably redundant, and
**accepted**. The key used to validate and do nothing at all in the tree form;
now it says which of the two it is. One consumer found the contradicting case on
the day it landed.

*(This paragraph said "naming a group the catalogue already shapes is now
refused", which is wrong for the agreeing case and was corrected after a
consumer's migration measured it: `env_groups: [deploy]` beside a catalogue that
declares `deploy` env-first **loads**. A reader who trusted the old wording would
have deleted a working line for no reason — the note was stricter than the
kernel, which is the direction nobody checks.)*

### Four modules moved

`allure`, `vcs`, `images` and `nexus` were kernel-level modules that were really
a task's innards, and three of them collided by name with a task body. The old
import paths still work, announce the move on use, and are removed in the next
minor:

| old | new |
|---|---|
| `simplon.allure` | `simplon.tasks.allure` |
| `simplon.vcs` | `simplon.tasks.gitops` |
| `simplon.images` | `simplon.imagenames` |
| `simplon.nexus` | `simplon.nexusproxy` |

The warning is a `FutureWarning` rather than a `DeprecationWarning`, and the
reason is measured: Python's default filters drop a DeprecationWarning unless
the frame that triggered it is `__main__`, and a product's task body never is.
A warning nobody sees is not a warning.

**Check the call, not the import.** The warning fires when a name is *used*,
not when the module is imported — `from simplon import images` is silent even
under `-W error::FutureWarning`, and `images.image_ref(...)` is what speaks. A
consumer who verifies "does it still import?" after the bump sees nothing and
meets the warning later, in operation. Measured by a consumer during their
migration, not by us.

Which modules are library and which are internals is now declared rather than
guessed — see [Surface](../../building/surface/).

### New

- **`build:image` and `release:image`** build a container image and publish it.
  The push is read back from the registry afterwards, because `docker push` can
  exit 0 without the tag arriving. `VERSION` and `REVISION` come from the
  product's git checkout, so a locally built image carries the same provenance
  as one built in CI.
- **`release:tag`** cuts the release tag and pushes it — `git push origin <tag>`,
  never `--tags`. It refuses a tag on a commit `main` does not carry.
- **A gate says why it is red.** "The setup failed" and "the suite ran and found
  something" are both a non-zero exit code, and they now read differently in the
  report — for the person reading it a week later, not just the one watching the
  terminal.
- **A results directory keeps the verdict it finds.** Merging one no longer
  copies `environment.properties` over the top of it.

### Stricter, in the kernel's own house

- A coordinate that starts with a phase name belongs in that phase; anything
  else is a family a product places where it likes. Measured against every
  existing manifest before it became a rule: no violations.
- The kernel pinned the three container images it was using without a tag,
  after refusing an unpinned image in a product's manifest. A rule the kernel
  breaks itself is a rule nobody believes twice.
- `docs:site` now renders each Mermaid diagram during the build. Hugo emits a
  diagram block whether or not its syntax parses, so a green build proved
  nothing about it.

### Documentation

New chapters on [the five phases](../../building/phases/) with a diagram, and
on what the kernel means by running in Docker. The coordinate table lost the
sentence beside each entry: those sentences were paraphrases of the catalogue's
own `help:`, nothing compared the two, and by the time anybody looked several
had drifted. The reliable fix is not to guard the copy but not to keep one.
