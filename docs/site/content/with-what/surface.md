---
title: "What you may import"
weight: 2
aliases:
  - "/building/surface/"
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

### One of them is worth naming: `simplon.fetch`

si#142 added it, and why it is public is the rule in miniature. The kernel downloaded a file in three
places, and all three were a bare `urllib.request.urlretrieve`: no progress, no timeout, no temporary
name, and a `# noqa: S310` beside two of them arguing that the URL was a pinned https asset. That
argument is true of those three URLs and says nothing at all about the fourth one, which a product was
going to write. So there is one, and it is yours:

```python
from pathlib import Path
from simplon import fetch

fetch.download("https://example.test/tool.tgz", Path("build/tools/tool.tgz"), label="tool")
```

It refuses anything but https on **every hop** of a redirect chain, not only the URL you asked for and
the URL that answered: urllib follows the middle of a chain by its own rule, which admits `http` and
`ftp`, so `https` to `http` to `https` used to pass both of those checks with one hop in the clear. It
times out, so a server that accepts the connection and never answers fails instead of hanging your
command forever. It writes to a temporary name in the destination directory and renames on success, so
an interrupted download never leaves a file a later run reads as cached. It compares what arrived
against what was announced, because `HTTPResponse.read` on a truncated body returns nothing and raises
nothing. And it reports differently depending on who is reading: one line repainted in a terminal, two
lines and a rare heartbeat in a log, never a carriage return into CI.

`resume=True` (si#176) is the one thing it does not do by default. With it, a transfer that dies keeps
what arrived under `<dest>.part` and the next call continues from there, which is what a product
fetching a five-gigabyte medium over a link that sometimes drops needs, and what the three small
artefacts the kernel itself fetches do not. It resumes only what it can prove: a sidecar records the URL
and the object version those bytes came from, the request carries `If-Range`, and anything that is not a
`206` confirming the exact offset asked for truncates the partial file and downloads the whole object
again. A server with no range support is therefore a fresh download, never an append.

It also owns the pair that says how big something is, and the pair is two functions on purpose:

```python
fetch.human_bytes(450_000_000)         # '450.0 MB'  decimal, what a Content-Length announces
fetch.human_bytes_binary(450_000_000)  # '429.2 MiB' 1024-based, what a file manager reports
```

`human_bytes(n, binary=True)` would have been one function, and a flag is read once at the call site and
never again by whoever reads the log. The units differ too, and that is the part worth knowing before
you print either one: si#192 arrived from a product that caps a channel at 450'000'000 bytes because the
channel rejects at 500 MB decimal, and whose own 1024-based helper spelled that `429.2 MB` - comfortably
under a cap it was in fact sitting on. That cost it a publish. Below 1000 the two produce the same
string, because there is no ambiguity there to resolve.

### And `simplon.checksum`, which is the same argument at a different seam

si#177 added it for the same reason si#142 added `fetch`: the kernel had no way to hash a file, so the
first product that pins media by hash wrote its own - and the interesting half is not the hashing, it is
the cache beside it.

```python
from pathlib import Path
from simplon import checksum

digest = checksum.sha256_of(Path("media/win11.iso"), cache=checksum.cache_dir(root))
```

A command whose whole job is to report what is present should not read five gigabytes to answer, so the
digest is written to a sidecar and read back - and **a cache that can be wrong is worse than no cache**,
because a checksum is the one place where being wrong is silent. Three conditions have to hold before a
sidecar is believed: the size is unchanged, `st_mtime_ns` is unchanged, and the sidecar's stat was taken
at least a second after the mtime it records. The third is git's own answer to its "racily clean" index
entries, and it is what survives a write inside the same second - the case a sync client, `touch -d`,
`unzip` and `tar` all produce by stamping whole seconds, and the class of defect si#86 and si#169 both
were in one week.

What it still cannot see is a rewrite that restores **both** size and mtime, and the module says so
rather than leaving it to be discovered. Anything else - an unreadable sidecar, a malformed one, one
written by a version that spelled the record differently - recomputes; nothing trusts a record it could
not fully check.

On Windows the read can meet a file another process is holding, which is observed rather than
hypothetical: a synchronisation client or an on-access virus scanner takes byte-range locks while it
uploads or scans, and a 5 GB medium is held for minutes. si#193 gives that condition a name rather than a
retry. `simplon.filelock` recognises the two Windows error numbers that mean it and raises
`filelock.FileLockedError`, an `OSError` subclass whose message says which process class is likely
holding the file, what to exclude, and that no retry is coming. `fetch.download` takes the same position
in the spelling it already promised, appending the sentence to its `DownloadError`. **There is no retry
schedule, on purpose**: nobody has measured how long such a hold lasts, and this kernel does not carry a
number nothing derives.

The sidecars live in `build/checksums/`, which is deliberate and not a new decision: `/build/` is already
the first line of the `.gitignore` block si#155 scaffolds, so this module adds nothing to the list of
what the kernel writes into your tree. A dotfile beside the media would have.

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
[Releases](../../when/releases/#050) for what moved where.

The lesson worth carrying to the next move is about the measurement, not the files. The record said six
import lines in three repositories; re-measured on the day, it was three lines in one — two of the
recorded lines had never been simplon's at all (a sibling kernel ships a module of the same name), and
one product had already migrated. **Re-measure before removing.** A count taken once decays, and this
one decayed inside a day.
