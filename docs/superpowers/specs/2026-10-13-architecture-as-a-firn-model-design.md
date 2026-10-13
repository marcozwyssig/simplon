# The architecture as a firn model - part 1: components, layers, and a test

**Status:** design, approved section by section by Marco on 2026-10-13. Part 1 of four. Ticket: si#390;
the exceptions' tickets are si#391-si#394.

## The goal, in one sentence

Every module of `src/simplon/` belongs to one named component in a firn model, the model says which
direction imports may go, and a test turns red on an unassigned module, an import against the direction
that is not a named exception, and an exception that is no longer needed.

## Why

Marco, 2026-10-13: "Die Architektur in Simplon ist schwierig." The components exist in the code, but
nothing in the package says where one ends: `src/simplon/` is a flat directory of modules beside two
packages (`orchestrator/`, `tasks/`), and `orchestrator/` holds the step runtime, the manifest reader and
the Textual UI together. Nothing checks the direction of imports between them; `surface.py` (#37) only
says what a product may import.

The aim Marco chose is **preparation for firn**: simplon already models its pipeline and its manifest in
firn (`simplon.pipeline`, `simplon.manifest`, `simplon.vocabulary`) and generates the catalogue's kinds and
the artifact schema from them. Part 1 puts the architecture itself into the model, so that the later parts
(moving modules, generating the domain classes) have a checked map to move along.

## The four parts (only part 1 is specified here)

1. **The architecture as a firn model** (this spec): components, the assignment of every module, the
   allowed direction, the named exceptions, a generated data file and page, a hand-written test. Nothing
   moves.
2. **Package layout:** modules move into one package per component; the old paths stay importable
   through `surface.MOVED` until a stated release, and each product gets an issue.
3. **Resolve the exceptions** one ticket at a time.
4. **Base classes, and tasks modelled and generated.** The kernel defines `Task` and `Command` as the
   base classes of every task and command. The tasks are modelled in firn (`simplon.pipeline.Task`, with
   its ports and parameters) and their classes generated, the body by hand; the hand-written
   `CommandSpec`, `Manifest` and `_ManifestModel` go. Touches si#344 part C and si#346. See "Part 4,
   decided now" below.

## Decisions (Marco, 2026-10-13)

1. Aim: preparation for firn - including the architecture itself as a firn model.
2. Decomposition into the four parts above; part 1 first.
3. Layers, bottom to top: **kernel (0) < domain (1) < adapters (2) < tasks (3) < cli, ui (4)**.
   Adapters sit above the domain: an adapter may know the read configuration. (The alternative, adapters
   below the domain, measured 30 exceptions against 14 for this order - by the first throwaway script, which
   undercounted both; the real test finds 16 for this order.)
4. **No generators component.** `taskgen`, `completiongen` and `workflowgen` belong to the tasks that call
   them.
5. An exception is **one module edge**, never a whole component edge, so a new wrong import cannot pass
   behind an old one.
6. Approach: everything in the model, the test by hand (not generated - a check in a Jinja template is
   hard to read and to see red).
7. The generated data file is **test code**: `src/tests/generated/architecture.py`, not in the wheel and not on the
   surface.
8. The exceptions name tickets; four, grouped by cause, opened in the plan before the model names them.
9. The kernel **defines the base classes for tasks and commands**; every task derives from them (part 4).
10. **Every task must derive from the base class, the products' too** - a function body named by `impl:`
    will be refused. This is an **expression rule** and is costed before it ships (below).
11. The base classes stay **part 4**; part 1 changes only the kernel's sentence.

## The components

| layer | component | what it is for | modules |
|---|---|---|---|
| 0 | kernel | the base classes of tasks and commands (from part 4), and running a plan: steps, outcomes, the subprocess seam, the log | `orchestrator.steps`, `orchestrator.product`, `run`, `log`, `verdict`, `steplog`, `waits`, `degraded`, `filelock` |
| 1 | domain | reading the configuration, validating it, building the plan | `orchestrator.manifest`, `orchestrator.model.treeform`, `yamlkeys`, `artifactsection`, `artifactschema`, `environments`, `carrierspec`, `layout`, `outputs`, `deployment`, `signatures`, `context`, `catalogue`, `runners`, `manifestmodel`, `clitaxonomy` |
| 2 | adapters | the tools and platforms a task drives | `awake`, `backend`, `checksum`, `clablifecycle`, `clabrender`, `compose`, `credentials`, `devcontainer`, `disk`, `diskguard`, `docker`, `fetch`, `githubpackages`, `healthgate`, `host`, `hostpath`, `imagenames`, `interact`, `labegress`, `labhost`, `labinstance`, `labnet`, `linux`, `nexusproxy`, `oras`, `portainer`, `ports`, `pyvenv`, `tools`, `topology`, `tracker` |
| 3 | tasks | the catalogue's task bodies, and the generators they call | every module of `tasks/`, plus `taskgen`, `completiongen`, `workflowgen` |
| 4 | cli | the command line: `simplon` and `simplon init`, and what a product may import | `cli`, `bootstrap`, `surface` |
| 4 | ui | running a plan in front of a person | `orchestrator.tui` |

**Excluded, with the reason in the model:** the four `__init__` modules and `_version` (the package's
`__init__` imports only `_version`; the other three import nothing), and `test_impls` (bodies for the
generator tests; it imports `tasks.testrun`, and nothing imports it). An excluded module stands outside
the layers, so the test refuses a component that imports one - the edge would pass through a module no
layer holds - while an excluded module importing a component is a leaf at the top and allowed.

Borderline assignments, decided here: `context`, `catalogue`, `clitaxonomy` and `manifestmodel` are
domain (they read or interpret the configuration); `log`, `run`, `verdict` and `steplog` are kernel (run
time, no manifest knowledge intended); `bootstrap` and `surface` are cli. `checksum`, `credentials` and
`tracker` are adapters.

These lists are the design. The model carries them; the test computes every count, and no number of
modules or exceptions is typed into a document (CLAUDE.md).

## The rule

An import from module `a` to module `b` (both in `src/simplon/`) is allowed when

- `a` and `b` are in the same component, or
- `a`'s component has a **higher** layer than `b`'s.

Two components on the same layer may not import each other (cli and ui). Anything else is a violation,
allowed only as a named exception.

**The exceptions at the start**, measured 2026-10-13 over every import in every module (function-level
and relative imports included), grouped by the ticket that resolves them:

| ticket | edges |
|---|---|
| si#391: the kernel knows the manifest, the UI, the CLI and the lab | `orchestrator.product -> orchestrator.manifest`, `orchestrator.steps -> orchestrator.manifest`, `steplog -> context`, `orchestrator.product -> awake`, `steplog -> labinstance`, `orchestrator.steps -> orchestrator.tui`, `steplog -> cli`, `steplog -> outputs` |
| si#392: tasks and `outputs` import `bootstrap` (all of them `validate_relative_dir`) | `tasks.acceptance -> bootstrap`, `tasks.cliref -> bootstrap`, `tasks.image -> bootstrap`, `tasks.site -> bootstrap`, `outputs -> bootstrap` |
| si#393: `deployment` imports above the domain | `deployment -> tasks.image`, `deployment -> githubpackages` |
| si#394: a task imports the UI | `tasks.walk -> orchestrator.tui` |

The table above is the real test's answer. The throwaway script that first measured it counted only the
first name of each `from simplon import a, b` statement and missed `steplog -> outputs` and
`deployment -> githubpackages`; the test found both (2026-10-13).

## The model

A new M2 package **`simplon.architecture`** (`src/firn/model/simplon/architecture/architecture.firn`):

- **`Component`** (allowRoot): `key` (1..1), `layer` (an integer as text, `0`-`4`, 1..1), `summary` (1..1),
  and `module` (Composition of `Module`, 0..N): a module is written inside its component.
- **`Module`**: `path` (the dotted path below `simplon`, e.g. `"orchestrator.steps"`, 1..1 - a firn name
  has no `.`, as `ArtifactField.key` carries a spelling the name cannot). An exception references it by
  its nested name, `simplon.components.kernel.m_orchestrator_steps`; firn v0.1.0 accepts that (measured).
- **`Excluded`** (allowRoot): `path` (1..1), `reason` (1..1).
- **`Exception`** (allowRoot): `importer` and `imported` (Associations to `Module`, 1..1 each), `reason`
  (1..1), `ticket` (`si#<n>`, 1..1). (`from` is a Python keyword and a likely firn one; the plan uses
  `importer`/`imported` from the start.)

The instances live in an M1 package **`simplon.components`**
(`src/firn/model/simplon/components/components.firn`). If firn reserves a property name used above
(`layer`, `key`, `module`), the plan renames it and reports the reservation to firn rather than working
around it silently.

## What firn generates

A new template file `src/firn/templates/architecture.firnt` with two templates:

- **`ArchitectureData`** -> `src/tests/generated/architecture.py`, a whole file with no protected region,
  data only: `COMPONENTS` (key -> (layer, summary)), `MODULES` ((path, component) pairs - pairs, so a
  module named twice reaches the test twice), `EXCLUDED` ((path, reason) pairs), `EXCEPTIONS` ((importer,
  imported, reason, ticket) tuples). A new firn target `tests` with `path = "tests/generated"`, a directory
  firn owns whole: with `path = "tests"` firn v0.1.0 deleted `src/tests/test_own_whole_files.py` with rc 0,
  twice (it spells id lines in its test cases) - a finding for firn.
- **`ArchitecturePage`** -> `src/site/content/with-what/architecture.md`, in the existing `site` target:
  each component with its sentence and its modules, the rule, and the exceptions with their tickets.

Both files join `build model-whole`'s list and `simplon.yaml`'s `generated:` section, so a missing,
id-line-only or stale file is caught (firn#966 guard, `test generated`).

## The test

`src/tests/test_architecture.py`, hand-written, reads every module's imports with `ast` - function-level
imports and relative imports included - and resolves each to a module of `src/simplon/`:

1. **Complete both ways:** every `.py` file below `src/simplon/` is in `MODULES` or `EXCLUDED`, and every
   path there is a file.
2. **Direction:** every import edge between components follows the rule, or is in `EXCEPTIONS`.
3. **No stale exception:** every exception's edge still exists and still violates the rule.
4. **Every exception has a reason and a ticket** of the form `si#<n>`.

Each assertion is seen red once (CLAUDE.md): an unassigned module, a wrong import, a resolved exception
still listed, an exception without a ticket.

**The known limit, said on the page and in the test's docstring:** the test sees Python imports only. A
reference written as text - `impl: "orchestrator.cli:whole_files"` in the catalogue or a manifest - is
resolved at run time, and no layer applies to it. Whether that is a gap is for part 3 to measure.

## What this is NOT

- No module moves; no import changes; no behaviour changes; nothing for a product to do.
- No exception is resolved (part 3).
- No class is generated from `pipeline.firn` (part 4).
- No census change: nothing here is a refusal of a manifest.

## Part 4, decided now

Recorded here because Marco decided it during this design; part 4 gets its own spec.

- **Today there is no base class.** Every one of the catalogue's task bodies is a plain top-level
  function, named by text (`impl: "simplon.tasks.vcs:commit"`); `signatures.py` reads its parameters
  with `inspect` at run time to bind `with:` and to render the Typer commands (`taskgen`). Measured
  2026-10-13: 50 catalogue bodies, all `def`, most with 0-2 parameters, the largest with 8 and 9.
- **The products write their bodies the same way.** Measured 2026-10-13 through the GitHub API, the
  `impl:` entries under each live manifest's own `tasks:`: netctl 52 (in `orchestrator.cli` and
  `orchestrator.tooling`), biz-cockpit 22, asbundle 15, cleon 12, swi 11 (`packer.commands`), simplon 6,
  firn 4, agile-cockpit 3. Whether each target is a function was not measured; `impl:` names a callable.
- **The rule "every task derives from the base class" is an expression rule**: a function body produces
  a working product today. Before part 4 ships, each product's peer session measures what rewriting its
  bodies costs - not the count above, the surface: bodies, their tests, their callers (CLAUDE.md, #34).
  The migration path (a generated wrapper, a `migrate` step, or a deprecation window that still accepts a
  function and says so) is part 4's design.
- **The products model and generate their tasks too** (Marco, 2026-10-13). firn reaches every product
  through simplon (`support toolchain firn`), and `simplon.pipeline` is simplon's M2, so a product's own
  firn model imports it, declares its tasks as `simplon.pipeline.Task` instances, and generates their
  classes from simplon's templates; the product writes only the body. That is also what keeps the rule
  above affordable: the class a product would otherwise rewrite by hand is generated. Part 4's spec says
  how the templates reach a product (shipped in the wheel beside the M2, or fetched) and where the
  generated classes land in a product's tree.

## Gates

`test model` (firn check over the new packages), `build model` (gen; tree clean afterwards), `test
generated`, the suite, `typecheck-python`, `build docs`.

## Testing, per CLAUDE.md

- The exception table is re-measured by the real test before the model is written.
- Each of the four assertions is broken on purpose and seen red.
- `build model-whole` is seen red on an emptied `src/tests/generated/architecture.py`.
