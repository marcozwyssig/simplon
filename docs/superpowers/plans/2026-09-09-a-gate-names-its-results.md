# A gate names where its results landed - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `Gate` may name the directory its own runner wrote results into, so a `command:` or `impl:`
gate contributes to the Allure report without the product writing Python - and a level that contributed
nothing goes RED instead of rendering as a hole that looks like a pass.

**Ticket:** [si#133](https://github.com/marcozwyssig/simplon/issues/133). **Design:**
`docs/superpowers/specs/2026-09-09-the-language-cluster-design.md`, section 4 (Lane B), proof standard in
section 6.

**Tech Stack:** Python 3.11+, pytest, mypy. No new dependency, no new catalogue coordinate.

## What the finding actually is

Not "Allure is pytest-only". `allure.merge_results` is technology-agnostic and always was: it names
foreign sources in its own docstring, copies non-result files through unchanged, tags a parent suite and
carries si#70's staleness cutoff. javademo gets a real archive out of a Gradle run today
(`case-java.md` row 4, rc 0) - by writing an `impl:` gate in Python that calls that merge itself.

The gap is that the capability is reachable **only by writing Python**. A product declaring the natural
shape - a `command:` gate over a toolchain command, si#106 - gets an exit code and the sentence *"the
kernel ran a command here, not a suite, and cannot say whether one ran at all"*. So the whole of this
work is one manifest key plus the check that makes it honest.

## The two measurements the design refused to assume

Both were made before this plan was written, on this machine, 2026-09-09. They decide the shape, so they
are recorded here rather than in a commit message.

**(a) Does `allure generate` read raw allure JSON, JUnit XML and TRX mixed in ONE directory?** YES.
Genuine inputs, not fixtures: two `*-result.json` from `pytest --alluredir` (allure-pytest 2.16.0), a
`ctest --output-junit` XML from a three-test CMake project compiled in `silkeh/clang:19`, and a
`dotnet test --logger trx` file from `mcr.microsoft.com/dotnet/sdk:9.0`. All three in one directory,
rendered by the kernel's pinned `frankescobar/allure-docker-service:2.44.0`:

```
{"statistic":{"failed":0,"broken":0,"skipped":0,"passed":6,"unknown":0,"total":6}}
suites: (empty), test_python_side, Demo.Tests.UnitTest1
```

2 + 3 + 1 = 6. The image ships `junit-xml-plugin`, `xunit-xml-plugin` and `trx-plugin` beside the allure2
reader, and the mix needs no separate directory and no conversion. **The design's shape holds** - one
results dir, one merge, one render.

The detail worth carrying: ctest writes `<testsuite name="(empty)">`, so its cases arrive under a suite
literally named `(empty)`. si#79 already measured that `parent_suite:` cannot reach a foreign format, so
that name cannot be improved from here. The cases are there; the grouping is the runner's.

**(b) Does a JUnit or TRX logger ship in the .NET SDK image without a package reference?** TRX yes, JUnit
no. `dotnet test --logger "trx;LogFileName=results.trx"` in `mcr.microsoft.com/dotnet/sdk:9.0` wrote the
file with no `PackageReference` at all. `--logger junit` answered
`Could not find a test logger with AssemblyQualifiedName, URI or FriendlyName 'junit'` and exited **1**
(measured unmasked - piping that command into `tail` reports the pipe's rc, not `dotnet`'s). So a .NET
product reaches the report through TRX and the SDK alone; JUnit costs it a `JunitXml.TestLogger`
reference. Nothing in this plan needs the JUnit answer to be yes.

## Decisions

**The key is `results_from:`, and it sits on a gate.** It names a directory relative to the product root
that this gate's own runner wrote its results into. `results:` says whose run the directory belongs to;
`results_from:` says where this level's results came from.

**It is legal on every kind, like `results:` and unlike `junit:`.** The mechanism does not vary by kind -
a directory is merged and the contribution is checked - so a refusal on a `suite:` gate would be a rule
with no defect behind it, and rules.md's own sorting question ("would the refused manifest have produced
a working product, just a different one?") answers yes. It therefore adds NO load-time refusal, and the
refusal census and `rules.md`'s counts are untouched. A pytest gate rarely wants it, because the kernel
already points `--alluredir` at the shared results dir.

**The merge happens in the gate, not in the report step, and carries the GATE's own cutoff.** The report
step's `since` is when the RUN began (si#70). A gate knows something tighter: when its own runner started.
That instant is taken immediately before the runner and floored to the whole second, for the reason
`merge_results` states - erring early keeps at most a second of the previous run's leavings, erring late
silently drops a result the run really did write. Without a cutoff at all this feature would ship the
si#70 defect back: nothing on the kernel's side of the seam ever empties a product's own results
directory, so a runner that wrote nothing would contribute the LAST run's results and the gate would go
green over them.

**A green runner that contributed nothing is FAILED.** Not a sixth verdict (`_abandoned`'s reasoning
holds: FAILED plus an explicit `detail` is the idiom for a statement about the STEP rather than about the
product), and not silence. This is the trap the ticket is made of: an Allure report rendered with a level
missing looks exactly like one where the level passed.

**A runner that was already red keeps its own rc and its own sentence.** Whatever partial results it wrote
are still merged - they are this run's evidence - but the rc is the primary fact and the record must not
replace "'build unit' returned this rc" with a sentence about an empty directory.

**Nothing is merged for a gate that did not run its body.** A failed precondition is `NOT_RUN` and touches
nothing; a failed preamble is `SETUP_FAILED` and the body never ran; a runner that dropped the setup
marker said its own preparation broke. In all three the run learned nothing about the product, and
harvesting there would invent evidence.

**`report.merge:` is untouched.** It stays what it is - directories other steps wrote, merged at the end,
unchecked. A product that names a directory in a gate's `results_from:` does not repeat it there.

**Out of scope, and it is a lane boundary rather than an omission.** The ticket's "likely route" also
names "the argv additions per profile" - `ctest --output-junit`, a TRX logger for `dotnet test`.
`src/simplon/tasks/profiles.py`'s cpp entry and `case-cpp.md` belong to Lane A (design section 7), and a
product reaches the same result today by pinning its own argv in its own command. Reported, not built.

## Global Constraints

- No new catalogue coordinate, and no new load-time refusal. Seven counted docs guards go red on a
  coordinate; `rules.md`'s refusal table goes red on a refusal. Neither is this ticket's to move.
- House style: English, Swiss spelling, no em dashes in prose, docstrings that argue WHY.
- The proof standard is design section 6: **a string assertion over an argv proves nothing.** The drive
  produces real results from a non-pytest runner, merges them, renders the archive and reads the cases
  back out of it - and sees the check RED with those results absent.
- `./simplon.sh test all` and `./simplon.sh test typecheck-python`. Baseline measured on `origin/main`
  (`7ab6fe2`) in a throwaway worktree: **3 failed, 2560 passed, 3 skipped**; typecheck green. The three
  are `tests/test_tasks_docs.py`'s uid checks, which assert a container is NOT run as `0:0` and fail
  because this host runs as root. Pre-existing and environmental; the final numbers are held against
  this, not against zero.

**Before Task 1, read** `src/simplon/tasks/testrun.py` and `src/simplon/tasks/allure.py` in full,
plus `tests/test_suites_command_gate.py`. `Merge` is the type that already answers "did anything
actually arrive"; do not write a second one.

---

### Task 1: the key exists and loads

**Files:** `src/simplon/tasks/testrun.py`, `tests/test_suites_results_from.py` (new)

**Interfaces produced:** `Gate.results_from: str = ""`, read by `_gate` through the existing `_str`.

- [ ] **Step 1: Write the failing tests**

- a `command:` gate declaring `results_from: "build/test-results"` loads and carries it;
- an `impl:` gate declaring it loads and carries it - that is javademo's hand-wiring, declared;
- a `suite:` gate declaring it loads too, and the test says why (no rule with no defect behind it);
- an empty `results_from: ""` is refused by the existing non-empty-string rule, naming the key, so a
  typo cannot be read as "not declared".

- [ ] **Step 2: Verify tests fail** - `TypeError: unexpected keyword argument 'results_from'`, or the
      loaded gate carrying `""`. Not an import error.
- [ ] **Step 3: Implement** - one field on the frozen dataclass, one `_str` read in `_gate`, and the
      docstring paragraph that says what the key means on each kind.
- [ ] **Step 4: Verify tests pass**
- [ ] **Step 5: Run the whole file plus `tests/test_suites_command_gate.py` and
      `tests/test_suites_impl_only.py`** - the loader is shared and the opacity lock must not have moved.

---

### Task 2: the harvest, and the red it produces

**Files:** `src/simplon/tasks/testrun.py`, `tests/test_suites_results_from.py`

**Interfaces produced:** `_harvested(gv, gate, cfg, results, since) -> GateVerdict`, `NO_RESULTS_RC`,
`NO_RESULTS_DETAIL`.

- [ ] **Step 1: Write the failing tests** (no docker; a real directory with real files in it)

- a green command gate whose runner wrote a JUnit XML into the declared directory reports `PASSED`, and
  that file is IN the run's results dir afterwards;
- **the red one, which is the deliverable**: the same gate with the declared directory EMPTY reports
  `FAILED`, carries a non-zero rc, and its line names the directory and says the level contributed
  nothing;
- the declared directory holding only a file OLDER than the gate's runner is the same red, and the line
  says the file is the previous run's rather than that the directory was empty;
- a gate whose runner returned non-zero keeps its own rc and its `'build unit' returned this rc`
  sentence, and its partial results are merged anyway;
- a gate that never ran its body (failed precondition, failed preamble, setup marker) merges NOTHING -
  asserted by leaving a file in the declared directory and finding the results dir untouched;
- a gate that declares no `results_from` behaves exactly as it does today.

- [ ] **Step 2: Verify tests fail** - the green-with-no-results case must fail by REPORTING PASSED, which
      is the defect. Read the failure text and confirm that is what it says.
- [ ] **Step 3: Implement** - `_harvested`, plus a `_say_merge` used by both it and `report()` so the
      warn/ok rule has one home.
- [ ] **Step 4: Verify tests pass**
- [ ] **Step 5: `./simplon.sh test typecheck-python`**

---

### Task 3: wire it into `assess_gate`

**Files:** `src/simplon/tasks/testrun.py`, `tests/test_suites_results_from.py`

- [ ] **Step 1: Write the failing tests** - through `assess_gate` rather than the helper: a command gate,
      an impl gate and a pytest gate each harvest; the call sits after the KILLED and setup-marker checks
      on the pytest branch, so a suite that was shot is not additionally judged on its results.
- [ ] **Step 2: Verify tests fail**
- [ ] **Step 3: Implement** - one call on each branch, the cutoff taken immediately before the runner.
- [ ] **Step 4: Verify tests pass**
- [ ] **Step 5: Run `tests/test_tasks_testrun.py`, `tests/test_suites_command_gate.py`,
      `tests/test_suites_impl_only.py`, `tests/test_verdict.py`**

---

### Task 4: the drive - a real ctest run reaches the rendered archive

**Files:** `tests/test_suites_results_from_e2e.py` (new)

This is the task the plan exists for. Shape it on `tests/test_buildfiles_e2e.py`: `needs_docker` as the
only skip, real images, no stubbed `run`.

- [ ] **Step 1: Write the failing tests**

- a three-test CMake project is compiled in `silkeh/clang:19` and run with `ctest --output-junit`, through
  `toolchain.run_toolchain` rather than a `docker run` written in the test;
- a manifest declares a `command:` gate over that command with `results_from:` naming where ctest wrote;
- `assess_gate` then `report()` render the single-file archive;
- the archive is DECODED (`d('<path>','<base64>')` payloads - `grep` answers 0 on a full archive and 0 on
  an empty one, which the Java chapter already had to say once) and `data/suites.json` is asserted to
  carry `AddsTwoNumbers`, `MultipliesTwoNumbers` and `SubtractsTwoNumbers`;
- **the red half in the same file**: the identical product with ctest's output deleted before the gate
  runs goes RED, and the archive carries none of the three.

- [ ] **Step 2: Verify tests fail**
- [ ] **Step 3: Implement** - nothing new in the kernel is expected here. If something is, it is a real
      finding and belongs in the plan before the code.
- [ ] **Step 4: Verify tests pass**, and record the rendered numbers in the commit message.

---

### Task 5: document it where the manifest is documented

**Files:** `site/content/building/test-levels.md`

- [ ] **Step 1** - a subsection under the gate-kinds part: what `results_from:` names, that the merge is
      `merge_results` and not a new mechanism, the cutoff and why, the red a level that contributed
      nothing gets, and the measured sentence that raw allure JSON, JUnit XML and TRX read out of one
      directory. Quote the real refusal and the real red line rather than inventing wording.
- [ ] **Step 2** - the "Checklist for adding a level" gains the one line it needs, and the `suite:` /
      `impl:` / `command:` table gains the key.
- [ ] **Step 3: Verify** - `tests/test_site_links.py`, `tests/test_site_counts.py`,
      `tests/test_setup_marker_pages.py`, `tests/test_case_java_chapter.py`. Every count on that page is
      computed by a guard; satisfy them, never weaken them.

---

### Task 6: the gate, and the review

- [ ] **Step 1** - `./simplon.sh test all` and `./simplon.sh test typecheck-python`, held against the
      baseline above.
- [ ] **Step 2** - dispatch `python-reviewer` on the diff and act on what it finds.
- [ ] **Step 3** - one PR against main. No labels, no merge.
