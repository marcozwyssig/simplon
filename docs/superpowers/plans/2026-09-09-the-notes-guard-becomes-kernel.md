# The release-notes guard becomes the kernel's - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the rule "a release that went out is written down, and its section names every ticket its
range carries" stops being a house rule in `tests/test_releases_page.py` and becomes a catalogue
coordinate any product can place. The product declares three values; the kernel imports none of them.

**Tickets:** [si#89](https://github.com/marcozwyssig/simplon/issues/89) (the guard is a house rule) and
[si#103](https://github.com/marcozwyssig/simplon/issues/103) (the notes PR brings its own number).

**Tech Stack:** Python 3.11+, pytest, mypy. One new catalogue coordinate, no new dependency, no new
load-time refusal.

## What the guard is, and what tonight proved about it

The rule already exists and already works. It fired twice on 2026-09-08, both times correctly and both
times as a surprise:

- **PR #124** was green on its branch tip and red on `refs/pull/124/merge`. The `pull_request` event
  checks out the branch *merged with the base*, and the base had moved, so the range carried merges the
  branch tip did not. The tip being green is exactly what hid it.
- **`main` went red the moment PR #135 merged**, because #135's own number was not in the 0.10.0
  section.

One shape, twice: **the range is `<last tag>..HEAD` of the state being checked, and which state that is
depends on the event.** Nothing in the current guard says so. Its failure line names the range - the
useful half - and never says what `HEAD` resolved to, which is the half that would have made both
surprises legible. That is a deliverable of this work, not a nicety.

## The three decisions

### 1. It is a **catalogue coordinate**, `test:release-notes`, declared and not placed

Not a test, and that refusal is the whole of si#89: `tests/test_releases_page.py` guards the product
that wrote it, so netctl, cleon and agile-cockpit can tag, publish and never write a word, and nothing
says anything. A `test:` coordinate guards whoever declares it.

Not a `release:` step either, and this one was a live option. Folding the check into `release:tag`
would put it exactly where the damage is - one command, no bypass. It is rejected because the notes are
written **before** the tag, by workflow (si#3: the tag points at a tree that already carries them). A
guard that only speaks when `release tag` is typed speaks after every chance to fix it cheaply has
passed, and it would have caught neither of tonight's two cases, both of which were pull requests days
from a tag. The prepared release's range already ends at `HEAD`, so the same question is answerable on
every push - and being answerable continuously is what makes it a gate.

`test` is a platform group name, so si#34 makes the namespace a **placement**: it may sit under `test`
and nowhere else, in every product. **Declared, not placed**, by si#58's bar: it reads a `releases:`
section, so placed it would be a command that dies on its first line in every product that has no
release notes.

### 2. si#103's self-reference resolves to: **a subject GitHub composed is not a statement about the work**

A pull request merged from the web interface gets `Merge pull request #N from <branch>`. The number is
the **pull request's** - a fact about the vorgang, not about the change - so the notes PR names itself,
and a follow-up PR would bring its own number too. The regress has no floor.

So `Merge pull request #N from ...` is not read for tickets. The commits it brought in are read
instead (`git log --no-merges <sha>^1..<sha>^2`), because that is where the author wrote what the work
was. The assurance does not weaken: `feat(#92)` and `docs(#95)` are still required in the section. What
falls away are numbers nobody wrote.

**Why this survives a person in a hurry**, which is the bar the ticket sets. The number a notes PR now
has to name is its own *ticket* number - one the author picked before opening the branch and typed into
every commit subject on it. The number it no longer has to name is the *pull request* number, which
does not exist until the branch is pushed. The rule asks only for what is already in the author's hand.

Two cases stay explicitly:

- **the fallback.** A web merge whose commits name nothing at all falls back to the PR number. Several
  merges from before the convention are like that, and dropping them would excuse work rather than
  describe it.
- **GitHub's ephemeral merge** (`Merge <40 hex> into <40 hex>`, si#97) is not a change any release
  carries - it is scaffolding the `pull_request` run is built on - so it is out of the population
  entirely. Matched in that exact machine format: a short hash, a branch name or one word past the
  second hash means a person wrote it, and a person can write a number in.

### 3. The floor comes from **the manifest**, as two versions and a page path

```yaml
releases:
  page: "site/content/using/releases.md"    # which page holds the notes
  from: "0.4.0"                             # the first release that must have a section at all
  complete_from: "0.5.0"                    # the first section that must name every ticket in its range
```

Three values, and si#89 names exactly these three: the page, the floor, and the exemption. The
exemption is not a list: it is the gap between the two floors, `[from, complete_from)`. A list would be
the thing `CLAUDE.md` warns about - an exemption whose real cost is the second entry somebody adds to
it quietly - while a second floor can only ever be raised in public, and simplon's own house rule below
pins its excused set at one.

`complete_from` may equal `from`, and then nothing is excused. Both are refused if absent or malformed,
at run time and by name.

## What the kernel takes and what simplon keeps

**The kernel takes the mechanism**, which is everything that needs no product knowledge: which versions
exist (`git tag`), which the page documents (`## X.Y.Z`), which merges lie in a range, what a merge
subject names, and the four verdicts over them -

1. every release at or above `from` has a section;
2. the page documents no version that has no tag, except the one being prepared;
3. every merge in a documented range names a ticket at all (the precondition the fourth rests on);
4. from `complete_from` up, a section names every ticket merged into its range.

**simplon keeps its house rules**, in `tests/test_releases_page.py`, written against the kernel's
mechanism rather than a copy of it: that the page's own prose names the same floor the manifest does,
that the introduction names `complete_from`, that exactly **one** section is excused, and that the
excused one really is incomplete. Every one of those is a statement about simplon's page and simplon's
number. A second product will want its own, or none.

**Prose is still not read.** The module docstring's line holds: what a change *meant* is knowledge no
tool has. The weakest claim that would have caught si#82 - a number appears - is the right one.

## The legibility deliverable

Every verdict line names the range **and what `HEAD` resolved to**:

```text
v0.9.0..HEAD  (HEAD 0f27e6c "Merge pull request #137 from marcozwyssig/feat/129-init-reads-the-repository")
```

and when `HEAD` is GitHub's ephemeral merge, it says so in as many words - that this is the
`pull_request` checkout, the branch **as merged with the base**, so the range can carry merges the
branch tip does not. That sentence is PR #124's whole surprise, printed before anybody has to
reconstruct it.

## Global Constraints

- **One new catalogue coordinate**, and it turns eight counted docs guards red at once. They are
  satisfied, never weakened, skipped or reshaped. Several state their own ordering: the page first, the
  number last.
- **No new load-time refusal.** The `releases:` section is read inside the task body and refused with
  `log.error` + `return 1`, the shape `tasks.buildfiles` already uses, so `rules.md`'s refusal counts
  and the census's kinds are untouched. The module joins `READS_INLINE` instead, and the census's
  "nine modules" becomes ten.
- House style: English, Swiss spelling, no em dashes in prose, docstrings that argue WHY.
- **Proof standard.** A guard that cannot fail is this project's recurring defect. Both halves are
  executed against a real git repository built in `tmp_path` - real commits, real merges with real
  subjects, real tags, a real page, a real manifest - never a string assembled and parsed back:
  - a merged ticket the notes do not name is **refused**, and the failure text is read;
  - the si#103 self-reference - a `Merge pull request #N` whose branch commits name a different ticket -
    is **accepted**.
- **Baseline, measured on `origin/main` (`0f27e6c`) in a throwaway worktree, 2026-09-08:**
  `./simplon.sh test all` -> **4 failed, 2730 passed, 3 skipped** in 39.67s;
  `./simplon.sh test typecheck-python` -> green, 84 source files, 3.3s. Three of the four are
  `tests/test_tasks_docs.py`'s uid checks, environmental (this host runs as root). **The fourth is the
  guard itself**: `test_every_ticket_merged_into_a_release_is_named_in_its_section` says *the v0.10.0
  section names 7 of the 12 tickets merged into v0.9.0..HEAD; missing: si#129, si#130, si#132, si#133,
  si#134*. `main` is red on unwritten notes right now. This work moves where that red appears - out of
  the pytest suite and into the placed command - and does not write the missing notes, which are five
  other lanes' prose. Final numbers are held against this baseline, not against zero.

**Before Task 1, read** `tests/test_releases_page.py` in full - `_GITHUB_MERGE`, `_GITHUB_PR_MERGE`,
`is_githubs_own_merge` and `tickets_of` encode traps already paid for once - plus
`src/simplon/tasks/release.py` for the house voice of a task body and `src/simplon/tasks/artifact.py`
for the `_declared()` shape a manifest section is read with.

---

### Task 1: the plan, committed

- [ ] This file, committed before any code.

---

### Task 2: the product's declaration - the `releases:` section

**Files:** `src/simplon/tasks/releasenotes.py` (new), `tests/test_releasenotes_declared.py` (new)

**Interfaces produced:** `Declared(page: Path, first: tuple[int, ...], complete_from: tuple[int, ...])`,
`declared() -> Declared | None`, `_version(str) -> tuple[int, ...] | None`.

- [ ] **Step 1: Write the failing tests** - a real manifest file, a real `ProductContext`:
  - a manifest with the three keys yields the three values, `page` resolved under the product root;
  - a manifest with no `releases:` section refuses, naming the section and the three keys;
  - each of the three keys missing refuses, naming that key;
  - a `from`/`complete_from` that is not `X.Y.Z` refuses, naming the value;
  - `complete_from` BELOW `from` refuses - it would excuse nothing and mean nothing;
  - `complete_from` EQUAL to `from` is accepted, and the test says why (a product with no pre-rule
    notes excuses nothing);
  - a `page` that is absolute or escapes the root refuses (the path is read, not written, but a
    manifest naming `/etc/passwd` as its release notes is a broken declaration and saying so costs
    nothing).
- [ ] **Step 2: Verify tests fail** - `ModuleNotFoundError`, then real assertion failures. Read each.
- [ ] **Step 3: Implement** - `declared()` reading `context.current().manifest_data()` inline, refusing
      with `log.error` and returning `None`. Docstring argues why the section is the product's and why
      the refusal is run-time rather than load-time.
- [ ] **Step 4: Verify tests pass**
- [ ] **Step 5:** `./simplon.sh test typecheck-python`

---

### Task 3: the mechanism, over a real repository

**Files:** `src/simplon/tasks/releasenotes.py`, `tests/test_releasenotes_mechanism.py` (new)

**Interfaces produced:** `released_versions(root)`, `sections(text)`, `documented_versions(text)`,
`tickets_in(text)`, `is_githubs_own_merge(subject)`, `merges_in(root, start, end)`,
`tickets_of(root, sha, subject)`, `ranges_under_test(root, declared)`.

The traps from `tests/test_releases_page.py` come across with their comments - they are the measured
part, and re-deriving them is how they get lost.

- [ ] **Step 1: Write the failing tests.** A helper builds a real git repository in `tmp_path`: commits
      with authored subjects, merges made with `git merge --no-ff -m`, tags cut on it. Then:
  - `released_versions` reads `vX.Y.Z` and skips a release candidate and a stray local tag;
  - `merges_in` returns merge subjects only, newest first, and drops GitHub's ephemeral merge;
  - **si#103**: `tickets_of` on a real `Merge pull request #94 from marcozwyssig/docs/92-...` whose
    branch commits say `docs(#92): ...` returns `{92}` and **not** `{94}`;
  - the fallback: the same shape whose branch commits name nothing returns `{94}`;
  - an authored merge subject is read as written, in both spellings (`si#87`, `si87-`);
  - the five human-written near-misses of the ephemeral format are NOT skipped;
  - `ranges_under_test` ends a released version's range at its own tag and the prepared one's at `HEAD`,
    and skips a version with no earlier tag.
- [ ] **Step 2: Verify tests fail** - each for its own reason, not one import error for all.
- [ ] **Step 3: Implement**
- [ ] **Step 4: Verify tests pass**
- [ ] **Step 5:** `./simplon.sh test typecheck-python`

---

### Task 4: the four verdicts, and the range that says what HEAD is

**Files:** `src/simplon/tasks/releasenotes.py`, `tests/test_releasenotes_verdict.py` (new)

**Interfaces produced:** `check() -> int`, `_head_note(root) -> str`.

- [ ] **Step 1: Write the failing tests**, all through `check()` against a real repository and a real
      manifest:
  - a page whose sections match the tags and name every merged ticket returns **0**;
  - a tagged release with no section returns 1 and names the version;
  - a section for a version that has no tag and is not the one being prepared returns 1;
  - a merge naming no ticket returns 1 and says a section cannot be asked to describe it;
  - a section missing one merged ticket returns 1 and names the number;
  - a version below `complete_from` is not held to completeness;
  - **the legibility assertion**: the output names the range AND the resolved `HEAD`, and when `HEAD`
    is GitHub's ephemeral merge it says the range is the branch as merged with the base;
  - a run where nothing was ruled on - no documented version has a measurable range - returns non-zero
    rather than green, because a gate that checked nothing must not report a pass (the recurring defect
    `CLAUDE.md` names).
- [ ] **Step 2: Verify tests fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Verify tests pass**
- [ ] **Step 5:** `./simplon.sh test typecheck-python`

---

### Task 5: the coordinate, and the eight guards it turns red

**Files:** `src/simplon/catalogue.yaml`, `site/content/building/phases.md`,
`site/content/building/rules.md`, `site/content/using/why.md`, `tests/test_refusal_census.py`

The page first, the number last - several guards state that ordering themselves.

- [ ] **Step 1:** `test:release-notes` in `catalogue.yaml`, with the comment that says declared-not-placed
      and why, and that si#34 makes `test:` a placement.
- [ ] **Step 2:** `phases.md` - the `### test` section's bullet list gains the coordinate; then its
      **In the catalogue today: N tasks** line; then the overview table's `test` row; then the page-wide
      sentence *Thirty-five coordinates: twenty-four carrying a placement, eleven free to be filed*.
- [ ] **Step 3:** `rules.md`'s **35** coordinates.
- [ ] **Step 4:** `why.md`'s kinds-of-work table. The coordinate goes in **version control** (`git`,
      `gh`), beside `release:tag`, and the page's own sentence is the argument: *`release:tag` is
      version-control work that happens in the release phase*. This is version-control work that
      happens in the test phase - it reads tags and merge subjects and shells out to nothing else. Any
      other row would make the middle column intersect and cost the page its claim.
- [ ] **Step 5:** `tests/test_refusal_census.py` - `READS_INLINE` gains `tasks.releasenotes` with its
      reason, and the docstring's *Nine modules* becomes ten.
- [ ] **Step 6: Verify** - `tests/test_phases_chapter.py`, `tests/test_site_counts.py`,
      `tests/test_why_chapter.py`, `tests/test_catalogue.py`, `tests/test_refusal_census.py`,
      `tests/test_site_links.py`. Satisfy each; weaken none.

---

### Task 6: simplon adopts it in its own house

**Files:** `simplon.yaml`, `.github/workflows/ci.yml` (generated), `tests/test_releases_page.py`

- [ ] **Step 1:** `simplon.yaml` declares the `releases:` section and places
      `release-notes: { task: "test:release-notes" }` under `test`, and gains the ci job step. The
      workflow is REGENERATED with `./simplon.sh support workflows`, never hand-edited.
- [ ] **Step 2:** `tests/test_releases_page.py` shrinks to simplon's four house rules, written against
      `simplon.tasks.releasenotes`: the page's prose floor, the introduction's `complete_from`, exactly
      one excused section, and that the excused one really is incomplete. The module docstring says
      what moved and why the four that stayed are simplon's own.
- [ ] **Step 3: Verify** - `./simplon.sh test all`; the guard's own red now comes from
      `./simplon.sh test release-notes`, which is run and its output recorded. Expect it RED on the
      five unwritten 0.10.0 tickets, which is the baseline's fourth failure wearing its new name.
- [ ] **Step 4:** `releases.md`'s introduction says `tests/test_releases_page.py` measures it. It does
      not any more. The sentence names the command.

---

### Task 7: document it where the manifest and the test levels are documented

**Files:** `site/content/building/manifest.md`, `site/content/building/test-levels.md`,
`site/content/using/releasing.md`

- [ ] **Step 1:** `manifest.md` - the `releases:` section beside the other product-data sections: the
      three keys, what each is for, and the real refusal text.
- [ ] **Step 2:** `test-levels.md` - a short section saying this is a gate that is NOT a `suites:`
      level: it declares no gate, runs no runner, and answers one question about the repository. Why it
      is in `test` at all, and why not in `release`.
- [ ] **Step 3:** `releasing.md` - the guard in the release flow, the range and what `HEAD` is under
      each event, and si#103's resolution stated for whoever writes the next notes PR.
- [ ] **Step 4: Verify** - `tests/test_site_links.py`, `tests/test_site_counts.py`, and every counted
      guard again.

---

### Task 8: the gate, the review, the PR

- [ ] **Step 1:** `./simplon.sh test all` and `./simplon.sh test typecheck-python`, held against the
      baseline.
- [ ] **Step 2:** the two red runs, executed and their real output recorded - the unnamed merged ticket
      refused, the si#103 self-reference accepted.
- [ ] **Step 3:** dispatch `python-reviewer` on the diff and act on what it finds.
- [ ] **Step 4:** one PR against main. No labels, no merge.
