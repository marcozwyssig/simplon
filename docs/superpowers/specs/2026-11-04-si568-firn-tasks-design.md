# si#568: firn over a product's own project - `test:model`, `test:model-format`, the product binary, and `build:model` without its second sources

Ticket: si#568, with its first comment (6626847385, the correction measured against firn v0.5.0).
Decided by Marco on 2026-11-04, by choice list, against main 82b608d (si#564 is on its own branch).

## Intent

Every firn-using product does four things with its own model: generate it, validate it, check its format,
and, if it has Java functions, build its own firn binary and generate and validate with that. The kernel
offers one of them, `build:model` (`firn gen`). cleon-firn writes the rest as five `toolchain:run` lines,
each with its own argv, image pin and reading of the exit code. firn's own session confirmed the list (its
point 5) and also said which of its own runs are firn's development rather than a product's need.

**Success (Marco, on my recommendation): cleon-firn's manifest needs no `toolchain:run` for firn.** Each
line names a kernel coordinate, and `support toolchain firn` gives a new firn product the same commands.
That can be counted (five lines today) and contains the other two goals: a kernel task brings its
diagnosis with it, and the product binary is one of the five.

## Measured (2026-11-04, from the consumers' sessions and firn's v0.5.0 tag)

- **cleon-firn** (`cleon-firn.yaml`, simplon 0.36.0, firn v0.5.0, every command with `--cwd <project>`,
  `network: none`):
  - `build model` is `toolchain:run` with `[gen]`, and `test model` below is `[validate]`. **The kernel
    wrote both**: `support toolchain firn` scaffolds exactly these lines (`tasks/profiles.py:479-489`,
    found by the builder check). The scaffold is where the fix starts.
  - `build binary` is `toolchain:run` in `firn-builder`, `GRADLE_USER_HOME=/workspace/.gradle`,
    `[gradle, --offline, firnBinary]`.
  - `build model-binary` is `[build/firn/firn, gen]` in `firn-builder`.
  - `test model` is `[validate]`.
  - `test model-binary` is `[build/firn/firn, validate]` in `firn-builder`.
- **firn's exit codes** (v0.5.0 `ExitCode.java`, unchanged on main): 0 OK, 1 MODEL_ERROR, 2 USAGE,
  3 IO, 4 OUTPUT_NOT_CURRENT, 5 RESOURCE_EXHAUSTED, 6 DUPLICATE_REGISTRY_KEY (product binary only),
  70 INTERNAL. firn#1196 (not on main) adds 7 BINARY_BOOTSTRAP for a product's first binary.
- **W300 and W301 alone end with rc 0** (GenCommand.java:241-251). rc 4 is W303, W304, E316, a
  superfluous file edited outside its regions, and an unrecorded file without an id line.
- **Since firn#966 (in docs/04 from v0.2.0 on):**
  - a file whose template reported an error is not written (rc 1);
  - a run that would delete every file of a target is E315 (rc 1);
  - a partial deletion is a normal sweep, named on every run.
- **The product binary** (firn docs/05 section 6, docs/07 section 9):
  - It is built by the product's own Gradle build in `firn-builder`, through the image's `firnBinary`.
    That build Execs `firn gen` and `firn library`.
  - It writes `build/firn/firn` (static musl), `build/firn/lsp.args` and `build/firn/entry`.
  - The project must be mounted **at the same path** inside and out, because `lsp.args` holds absolute
    host paths.
  - Anything that writes runs as `--user "$(id -u):$(id -g)"`; the image user is 65532.
  - A build takes about 42 s and 2.2 GB.

## Decisions (Marco, 2026-11-04)

1. **One ticket, all four parts, designed together.**
2. **Exit codes are passed through, and named.** A new task returns firn's code unchanged, so a CI can
   still branch on 4, and logs one line with what the code means and what to do. A code not in the table
   is red and is named as unknown. There is no second source for the meaning, only for the wording.
3. **The first binary (rc 7) is green only with an explicit `bootstrap: true`.** Never by inference.
   Nothing about it is built in this ticket: a parameter that accepts a code firn cannot yet give is a
   fake capability. The builder check showed rc 7 arises inside the product's Gradle build, under a
   bootstrap property, so `firnBinary`'s rc can never be 7 itself. How the switch reaches Gradle is
   designed when firn#1196 is released, in its own ticket.
4. **`build:model` loses its two stricter second sources**: the refusal of a file holding only firn's id
   line, and the refusal of any file firn reports deleted. firn covers both since #966 and judges more
   accurately: an empty body is valid output, and a partial deletion is a regeneration. The W300/W301 rule
   stays, because it is not a second source (rc 0 in firn). The 0644 stays (firn v0.1.0 wrote 0600, and
   whether later releases do is not measured here). `build:model` requires firn v0.2.0 or later; simplon
   pins v0.2.0.
5. **The other checks in `build:model`'s verdict stay, and firn's rc comes first** (after the builder
   check):
   - "firn reported no file at all" and "a reported file is not there" stay as diagnoses. A run that
     produced nothing must not be green, which is the recurring defect.
   - Output that is not firn's JSON report: when firn's rc is non-zero, that rc is returned (a usage text
     on 2, the registry refusal on 6). Only rc 0 without a report is red.
6. **The rc of a red verdict that is the kernel's own** (firn said 0):
   - W300/W301 return **4**: a file kept for its region, or one with an orphaned region appended, is
     "output not current" in substance.
   - "no file" and "a reported file is missing" return **1**.
   - The line says the verdict is the kernel's, not firn's.
   - Docker's own codes (125, 126, 127) are named as docker's: the image is missing, or the binary is not
     executable or not found. They are not "an unknown firn code".
7. **The scaffold switches to the kernel coordinates.** `support toolchain firn` writes `build model` as
   `build:model` and `test model` as `test:model`, plus `test model-format`. Products scaffolded before
   keep their lines, because the scaffold never overwrites, and the release notes say how to move.
   simplon's own `test model` (`simplon.yaml:337-345`, `cwd: src`, green in CI on v0.2.0) moves to
   `test:model` as well. Whether it joins `test all` is not changed here.
8. **The binary commands are their own profile**, `support toolchain firn-binary`. It writes
   `build model-binary`, plus `build model` and `test model` variants carrying `binary:`, under names the
   builder picks that do not collide. The builder image has the firn image's tag, because firn publishes
   both with every tag. There is no commented-out block, which a second run would append again.

## The tasks

All run through the existing `toolchain.invocation` (the image pin, the mount, `cwd`, `network`, running
as the caller, ownership checks) as `build:model` does. Params are as in `build:model`: `image`, `cwd`,
`network`.

| Coordinate | Runs | Verdict |
|---|---|---|
| `build:model` (changed) | `gen --format=json`, or `<binary> gen --format=json` with `binary:` | firn's rc passed through and named; rc 0 plus W300/W301 is red as today; 0644 as today |
| `test:model` (new) | `validate --format json`, or `<binary> validate ...` with `binary:` | firn's rc passed through and named |
| `test:model-format` (new) | `fmt --check` | firn's rc passed through and named |
| `build:model-binary` (new) | `gradle --offline firnBinary` in the `firn-builder` image, then a smoke run of `build/firn/firn --version` | Gradle's rc; then red if the binary is missing or does not run |

- **`binary:`** is a path relative to `cwd` (cleon-firn: `build/firn/firn`). It is run in the image the
  command names, normally `firn-builder`, with `--entrypoint` set to the binary. The firn image's
  ENTRYPOINT is `/firn`, which would otherwise run `/firn build/firn/firn gen`. It is refused at run time
  when the file does not exist, naming `build:model-binary` as the way to get it. That refusal is a
  diagnosis. `gen`/`validate` with the binary run under the normal mount; only `lsp.args`, which
  these do not read, needs absolute paths (docs/05 section 6). Treat this as an assumption: the first
  real run must confirm it.
- **`build:model-binary`'s mount is the same path inside as outside**: the product root is mounted at its
  own host path (as `hostpath.translate(root)` gives it) and is the workdir. It runs as the caller,
  `network: none` by default, with `GRADLE_USER_HOME` at `<cwd>/.gradle`, the path firn's own
  reference command uses (docs/07 section 9). cleon-firn's `/workspace/.gradle` is at the repo root and
  would not be found; the release notes say so. Whether the first run can be offline at all is
  firn-builder's business; the task passes Gradle's rc through.
- **The code table** lives once, in the kernel module that runs firn, as a mapping from code to a
  one-line meaning, taken from firn's `ExitCode.java` v0.5.0 and cited with that version. firn's `--help`
  lists no exit codes (measured on v0.2.0 by the builder check), so the table cannot be read from the
  image. The gap is recorded in the module.
- **`--format json` for `validate`**: the report is printed through, and the rc is the verdict
  (decision 2). The JSON is not read for a second verdict. Printing it in a readable form is the
  builder's call.

## firn's development is not this ticket

Bootstrap, the native build, the image and builder checks, `--version` and the benchmarks are firn's own
(firn's point 5). So is cleon-firn's `build import`, which is product knowledge.

## simplon itself and the scaffold

- See decisions 7 and 8. `test_profiles.py`'s expectations change with the scaffold, and that change is
  the point.

## Docs

- `with-what/phases.md`: the new coordinates, and the computed count sentence.
- Release notes: the next section, including that `build:model` no longer refuses an id-line-only file or
  a partial deletion (a product that relied on that has firn's E315 and rc 1 instead).
- The census: the `binary:`-missing refusal is a run-time diagnosis. If any load-time refusal joins, it
  gets its census entry.

## Tests (each seen red first)

- The code table: every firn code maps to its meaning; an unknown code is red and named.
- The verdicts are tested as `build:model`'s are today: `firngen.verdict()` and its new siblings are fed
  firn's JSON and rc (`test_firngen.py`). A real firn image is used where the suite already runs one
  (`firnrun.firn_rc`), for `test:model` and `test:model-format` on a fixture. The docker argv is asserted
  for the binary tasks (same-path mount, `--user`, `--entrypoint`).
- The rc rules of decisions 5 and 6: rc 2 or 6 without JSON is returned as 2 or 6; rc 0 without a report
  is 1; W300/W301 give 4; docker's 125, 126 and 127 are named as docker's.
- `build:model`: an id-line-only file and a partially deleted file are now green; W300/W301 still red.
  The old tests that pinned the two refusals are changed, not deleted silently, and the change is named
  in the commit.
- `binary:` missing: refused, naming `build:model-binary`.
- `build:model-binary`: the same-path mount and `--user` are in the docker argv. The smoke run is red on
  a missing binary and on one that exits non-zero.
- The scaffold: `support toolchain firn` writes the new commands, and the written manifest loads.

## Non-goals

- No reading of `--format json` into a verdict of the kernel's own.
- No `bootstrap:` until firn#1196 is released.
- No change to `test:manifest-model` (si#565 is its own ticket).
- No change to cleon-firn or firn. They move at their next bump, by their own choice.

## Left to the builder

- Module layout (one module for the firn tasks, or `firngen.py` grown).
- The exact wording of the code lines.
- Whether the smoke run is `--version` or `validate` in the project (`--version` unless it proves
  meaningless).
- The command names in the `firn-binary` profile.
