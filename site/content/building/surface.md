---
title: "What you may import"
weight: 5
---

The kernel has **two** public surfaces, and until recently nothing said which was which.

The first one this site already describes at length: the **task catalogue**. A product writes
`<namespace>:<name>` in its manifest and never names a Python module, which is what lets a task body
move inside the kernel without breaking anybody.

The second is ordinary Python. A product's own task bodies `import simplon.log`, `simplon.run`,
`simplon.host` and call them directly — that is not a workaround, it is the point of a kernel. But that
surface had no edge. Every module sat at the top level of the package side by side: the ones a product
may rely on, the ones the kernel merely shares between its own task bodies, and the ones that are pure
internal machinery. If you were extending the kernel, the only way to find out what you were allowed to
import was to read every consumer and guess.

## The rule

**A module that only the kernel's own task bodies import is not a library.** It does not belong beside
`cli.py` and `context.py` where the kernel lives; it belongs under `simplon/tasks/`, with the bodies
that use it.

```
simplon/log.py            library — import it
simplon/run.py            library — import it
simplon/catalogue.py      machinery — may change without notice
simplon/tasks/vcs.py      a task body — reach it by coordinate, `vcs:commit`
simplon/tasks/gitops.py   that body's innards — no promise at all
```

### What `simplon/tasks/` is, stated carefully

The obvious phrasing — *"a product may not import a task body"* — is **false**, and it is worth being
exact about, because four of the five products that install the kernel import one today — sixteen
import sites, measured — and the kernel is what taught them to:

* a hand-written composition root imports a body to call or wrap it (`from simplon.tasks import image`
  in agile-cockpit, `from simplon.tasks import artifact` in cleon);
* the **generated** CLI imports every body it registers — and that generator is the kernel's own
  `templates/cli.py.j2`. Twelve such lines across netctl and asbundle were written by us.

So the coordinate is the **front door**, not the only door. `<namespace>:<name>` is what a *manifest*
may say — it never names a module path, which is what lets a body move inside the kernel without
breaking a product. A direct import is the deliberate exception a composition root and the generator
take.

The line that does hold inside `simplon/tasks/` is **named versus unnamed**: a module some catalogue
coordinate points its `impl:` at is reachable, by coordinate first and by import where a composition
root has reason to. A module in there that **no** coordinate names is innards — `allure`, `gitops` and
`profiles` today — and nothing outside the directory imports either. `profiles` is the newest of the
three and the clearest case of the rule: it is the language table `support:toolchain` reads while
writing a ready-made configuration into a product's manifest, so it is reached through that coordinate
and never named by one of its own. That split is derived from `catalogue.yaml`, not declared, so it
cannot drift.

There is a second half, and it is the one that cost a review its afternoon:

**A promised module may not share a name with a task body.** `simplon.images` sat one character of path
away from `simplon.tasks.image`, and the two were not even related — the task body builds and pushes
with docker and has never imported the other. Where such a pair exists, the *library* half is the half
that gets renamed, because it is the half a product types.

## Where the answer actually lives

In the package, not on this page:

```python
from simplon import surface

surface.LIBRARY     # top-level modules you may import
surface.PACKAGES    # the subpackages beside them: `orchestrator`, `tasks`
surface.INTERNAL    # the kernel's machinery; it may change without notice
surface.MOVED       # old path -> new home
```

That is deliberate. Everywhere it can, this repository derives a fact rather than restating it — the
command reference is read off the assembled app, the version comes off the tag. This one **cannot** be
derived, and it is worth saying why, because it looks like it can: you can measure who imports what
today, but a promise is about tomorrow. `simplon.verdict` has no consumer in any repository right now
and is a library all the same — it was written as one, it names no product, and the next product to read
a suite's outcome is meant to find it. `simplon.catalogue` has no consumer either and is machinery. The
import graph cannot tell those two apart, because the difference is an intention.

The example used to be `simplon.compose`, and it has since acquired a consumer — which is the argument
rather than a dent in it. A module classified by who imports it today would have changed sides that day
without anybody deciding anything.

So the intention is written down once, in `simplon/surface.py`, and `tests/test_surface.py` holds it to
the tree: every top-level name — module **and** subpackage — has to appear in exactly one of the sets,
so nothing can be added beside `cli.py` without somebody deciding which surface it is on.

That test, and the one forbidding a library module named after a task body, bind the **kernel**, not
you. A future kernel author may no longer place a module wherever they like or reuse a body's name;
no product manifest, command or import is affected either way.

### The machinery, by name

Short enough to state, and the half you most need, because everything else at the top level is yours:

`bootstrap` · `catalogue` · `clitaxonomy` · `diskguard` · `oras` · `signatures` · `steplog` ·
`test_impls` · `tools`

`bootstrap` needs a word. It carries the `simplon` console script, so `simplon.bootstrap:main` **is** a
promised entry point — what is not promised is importing the module for its other functions.

## When something moves

A move is a break in the public surface: a product that writes `from simplon import allure` falls over.
So a moved module does not simply go. It leaves a **tombstone** at the old path that still imports and
still serves every name — and says so on use:

```
FutureWarning: simplon.images has moved to simplon.imagenames; import it from there.
The old path still works and is removed at the next minor release.
```

A `FutureWarning` rather than the customary `DeprecationWarning`, and that is measured rather than
preferred. Python's default filters *ignore* a `DeprecationWarning` unless the frame that triggered it
is `__main__` — and the frame that triggers this one is a product's own task body, which never is. The
notice would have been shown to nobody. Point the tombstone at `DeprecationWarning` and the kernel's own
test goes red with an empty stderr, which is exactly the silent disappearance the tombstone exists to
prevent.

A star-import works too, and that took a fix rather than falling out for free: `from simplon.images
import *` asks a module for `__all__`, and a forwarding module that refuses the question binds its own
three private names instead — silently, with no warning at all. The tombstones answer `__all__` with the
target's own star-import surface, so the names and the notice both arrive.

The tombstones come out at the next **minor** release. Until then a product gets a working run with a
message in it rather than a stack trace, and knows where to point the line.

That deadline is tracked rather than remembered, and it has now been collected once. `simplon.surface`
carries `MOVED` (what is promised), `MOVED_CONSUMERS` (every line in every repository that still imports
an old path — measured, down to the file and the line number) and `MOVED_DUE_AFTER` (the release the
promise names), with a test that turns red once a version past it is built.

**The first period ran through 0.4.x and ended at 0.5.0.** Four modules stood as tombstones and are now
gone; an import of one is a `ModuleNotFoundError`. The gate is what ended it: the test went red on the
release run, after the tag and before the publish, so v0.5.0 was cut, published nothing, and the period
closed the same afternoon rather than lasting a fifth release. See
[Releases](../../using/releases/#050) for what moved where.

The lesson worth carrying to the next move is about the measurement, not the files. The record said six
import lines in three repositories; re-measured on the day, it was three lines in one — two of the
recorded lines had never been simplon's at all (a sibling kernel ships a module of the same name), and
one product had already migrated. **Re-measure before removing.** A count taken once decays, and this
one decayed inside a day.
