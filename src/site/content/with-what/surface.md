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

The second is ordinary Python. A product's own task bodies `import simplon.kernel.log`, `simplon.kernel.run`,
`simplon.adapters.host` and call them directly — that is not a workaround, it is the point of a kernel. But that
surface had no edge. Every module sat at the top level of the package side by side (since si#399 they sit
in one package per component - `kernel`, `domain`, `adapters`, `tasks`, `ui`, `cli`): the ones a product
may rely on, the ones the kernel merely shares between its own task bodies, and the ones that are pure
internal machinery. If you were extending the kernel, the only way to find out what you were allowed to
import was to read every consumer and guess.

## The rule

**A module that only the kernel's own task bodies import is not a library.** It does not belong in
the kernel's other packages; it belongs under `simplon/tasks/`, with the bodies that use it.

```
simplon/kernel/log.py         library — import it
simplon/kernel/run.py         library — import it
simplon/domain/catalogue.py   machinery — may change without notice
simplon/tasks/vcs.py          a task body — reach it by coordinate, `vcs:commit`
simplon/tasks/gitops.py       that body's innards — no promise at all
```

### One of them is worth naming: `simplon.adapters.fetch`

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

### And `simplon.adapters.checksum`, which is the same argument at a different seam

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
retry. `simplon.kernel.filelock` recognises the two Windows error numbers that mean it and raises
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
coordinate points its body at is reachable, by coordinate first and by import where a composition
root has reason to. A module in there that **no** coordinate names is innards — `allure`, `gitops`,
`handoff`, `profiles` and `proxmoxapi` today — and nothing outside the directory imports any of them.
`handoff` works out which artifacts cross a job boundary of a generated workflow; only `workflowgen` calls it.
`proxmoxapi` arrived as a demotion rather than as a new module: it was written beside `cli.py`, where
a library lives, and this rule moved it. It asks Proxmox one question — can this node really put a
container on this storage — so that a carrier's mistake is a refusal naming a line instead of an HTTP
500 three minutes into a provider run. Only `deploy:carrier`'s body calls it. `profiles` is the clearest
case of the rule: it is the language table `support:toolchain` reads while
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
from simplon.cli import surface

surface.LIBRARY     # modules you may import, by path: `kernel.run`, `adapters.host`
surface.PACKAGES    # the package promised whole: `tasks`
surface.INTERNAL    # the kernel's machinery; it may change without notice
surface.MOVED       # old path -> new home
```

That is deliberate. Everywhere it can, this repository derives a fact rather than restating it — the
command reference is read off the assembled app, the version comes off the tag. This one **cannot** be
derived, and it is worth saying why, because it looks like it can: you can measure who imports what
today, but a promise is about tomorrow. `simplon.kernel.verdict` has no consumer in any repository right now
and is a library all the same — it was written as one, it names no product, and the next product to read
a suite's outcome is meant to find it. `simplon.domain.catalogue` has no consumer either and is machinery. The
import graph cannot tell those two apart, because the difference is an intention.

The example used to be `simplon.adapters.compose`, and it has since acquired a consumer — which is the argument
rather than a dent in it. A module classified by who imports it today would have changed sides that day
without anybody deciding anything.

So the intention is written down once, in `simplon/cli/surface.py`, and `tests/test_surface.py` holds it to
the tree: every module — and the `tasks` package — has to appear in exactly one of the sets, so nothing
can be added to the kernel without somebody deciding which surface it is on.

That test, and the one forbidding a library module named after a task body, bind the **kernel**, not
you. A future kernel author may no longer place a module wherever they like or reuse a body's name;
no product manifest, command or import is affected either way.

### The machinery, by name

Short enough to state, and the half you most need, because everything else is yours:

`adapters.diskguard` · `adapters.oras` · `adapters.tools` · `cli.bootstrap` ·
`domain.artifactschema` · `domain.catalogue` · `domain.clitaxonomy` · `domain.launcherenv` · `domain.manifestmodel` ·
`domain.ports` · `domain.runners` · `domain.signatures` · `domain.task` · `domain.yamlkeys` · `kernel.moved` · `kernel.provenance` ·
`kernel.runhost` · `kernel.steplog` · `test_impls`

`runners` needs a word too, because `workflowgen` beside it is a library module and this is not. It is a
**table** of facts about kinds of CI machine — what a self-hosted Debian runner provides, why
`actions/setup-python` cannot help there — and a product reaches those facts by naming a kind in its
manifest, never by importing the table. That is the point of carrying it here: the kernel learns a
machine once, for everybody, and stays free to add a kind or correct a measured field without that being
a promise it broke.

`bootstrap` needs a word. It carries the `simplon` console script, so `simplon.cli.bootstrap:main` **is** a
promised entry point — what is not promised is importing the module for its other functions.

## When something moves

A move is a break in the public surface: a product that writes `from simplon import log` falls over. So a
moved module does not simply go. Its old path keeps importing and says so when it is imported:

```
FutureWarning: simplon.log has moved to simplon.kernel.log; import it from there.
The old path still works and is removed in 0.33.0.
```

A `FutureWarning` rather than the customary `DeprecationWarning`, and that is measured rather than
preferred. Python's default filters *ignore* a `DeprecationWarning` unless the frame that triggered it
is `__main__` — and the frame that triggers this one is a product's own module, which never is. The
notice would have been shown to nobody.

**The old path is the very same module, not a stand-in.** The first move (0.4.x) left stub modules that
forwarded attribute lookups. si#399 measured why that is not good enough: products patch the kernel by
string — `patch("simplon.orchestrator.steps.run_stream")`, thirteen such lines — and a patch on a stub
lands on the stub. The real function keeps running, and the product's test stays green while testing
nothing. Since si#399 an alias in `simplon.kernel.moved` answers an old path with the module that lives at
the new one, so a patch through either name reaches the code that runs, and a star-import gets the
module's real names.

That deadline is tracked rather than remembered. `simplon.cli.surface` carries `MOVED` (what is promised),
`MOVED_CONSUMERS` (every line in every repository that still imports an old path — measured, down to the
file and the line number) and `MOVED_DUE_AFTER` (the release the promise names), with a test that turns
red once a version past it is built.

**The second period: si#399, the package per component.** Every module moved into the package of its
component, and `simplon.orchestrator` was dissolved. The move ships in 0.31; the old paths work through
0.32 and are gone in 0.33.0 — two minors, because about two hundred lines in seven products name one. Each
product gets an issue listing its lines once the release is out.

| old path | new home |
|---|---|
| `simplon.artifactschema` | `simplon.domain.artifactschema` |
| `simplon.artifactsection` | `simplon.domain.artifactsection` |
| `simplon.awake` | `simplon.kernel.awake` |
| `simplon.backend` | `simplon.adapters.backend` |
| `simplon.bootstrap` | `simplon.cli.bootstrap` |
| `simplon.carrierspec` | `simplon.domain.carrierspec` |
| `simplon.catalogue` | `simplon.domain.catalogue` |
| `simplon.checksum` | `simplon.adapters.checksum` |
| `simplon.clablifecycle` | `simplon.adapters.clablifecycle` |
| `simplon.clabrender` | `simplon.adapters.clabrender` |
| `simplon.clitaxonomy` | `simplon.domain.clitaxonomy` |
| `simplon.completiongen` | `simplon.tasks.completiongen` |
| `simplon.compose` | `simplon.adapters.compose` |
| `simplon.context` | `simplon.domain.context` |
| `simplon.credentials` | `simplon.adapters.credentials` |
| `simplon.degraded` | `simplon.kernel.degraded` |
| `simplon.deployment` | `simplon.domain.deployment` |
| `simplon.devcontainer` | `simplon.adapters.devcontainer` |
| `simplon.disk` | `simplon.adapters.disk` |
| `simplon.diskguard` | `simplon.adapters.diskguard` |
| `simplon.docker` | `simplon.adapters.docker` |
| `simplon.environments` | `simplon.domain.environments` |
| `simplon.fetch` | `simplon.adapters.fetch` |
| `simplon.filelock` | `simplon.kernel.filelock` |
| `simplon.githubpackages` | `simplon.adapters.githubpackages` |
| `simplon.healthgate` | `simplon.adapters.healthgate` |
| `simplon.host` | `simplon.adapters.host` |
| `simplon.hostpath` | `simplon.adapters.hostpath` |
| `simplon.imagenames` | `simplon.adapters.imagenames` |
| `simplon.interact` | `simplon.adapters.interact` |
| `simplon.labegress` | `simplon.adapters.labegress` |
| `simplon.labhost` | `simplon.adapters.labhost` |
| `simplon.labinstance` | `simplon.adapters.labinstance` |
| `simplon.labnet` | `simplon.adapters.labnet` |
| `simplon.layout` | `simplon.domain.layout` |
| `simplon.linux` | `simplon.adapters.linux` |
| `simplon.log` | `simplon.kernel.log` |
| `simplon.manifestmodel` | `simplon.domain.manifestmodel` |
| `simplon.nexusproxy` | `simplon.adapters.nexusproxy` |
| `simplon.oras` | `simplon.adapters.oras` |
| `simplon.orchestrator.manifest` | `simplon.domain.manifest` |
| `simplon.orchestrator.model.treeform` | `simplon.domain.treeform` |
| `simplon.orchestrator.plan` | `simplon.kernel.plan` |
| `simplon.orchestrator.product` | `simplon.kernel.product` |
| `simplon.orchestrator.steps` | `simplon.kernel.steps` |
| `simplon.orchestrator.tui` | `simplon.ui.tui` |
| `simplon.outputs` | `simplon.domain.outputs` |
| `simplon.portainer` | `simplon.adapters.portainer` |
| `simplon.ports` | `simplon.adapters.ports` |
| `simplon.provenance` | `simplon.kernel.provenance` |
| `simplon.pyvenv` | `simplon.adapters.pyvenv` |
| `simplon.run` | `simplon.kernel.run` |
| `simplon.runhost` | `simplon.kernel.runhost` |
| `simplon.runners` | `simplon.domain.runners` |
| `simplon.signatures` | `simplon.domain.signatures` |
| `simplon.steplog` | `simplon.kernel.steplog` |
| `simplon.surface` | `simplon.cli.surface` |
| `simplon.taskgen` | `simplon.tasks.taskgen` |
| `simplon.tools` | `simplon.adapters.tools` |
| `simplon.topology` | `simplon.adapters.topology` |
| `simplon.tracker` | `simplon.adapters.tracker` |
| `simplon.verdict` | `simplon.kernel.verdict` |
| `simplon.waits` | `simplon.kernel.waits` |
| `simplon.workflowgen` | `simplon.tasks.workflowgen` |
| `simplon.yamlkeys` | `simplon.domain.yamlkeys` |

`simplon.orchestrator` and `simplon.orchestrator.model` themselves stay importable as empty packages until
then, so `from simplon.orchestrator import product` keeps working. `simplon.cli` did not move: the
command line is the `cli` package's own `__init__`.

**The first period ran through 0.4.x and ended at 0.5.0.** Four modules stood as tombstones and are now
gone; an import of one is a `ModuleNotFoundError`. The gate is what ended it: the test went red on the
release run, after the tag and before the publish, so v0.5.0 was cut, published nothing, and the period
closed the same afternoon rather than lasting a fifth release. See
[Releases](../../when/releases/#050) for what moved where.

The lesson worth carrying to the next removal is about the measurement, not the files. The record said six
import lines in three repositories; re-measured on the day, it was three lines in one — two of the
recorded lines had never been simplon's at all (a sibling kernel ships a module of the same name), and
one product had already migrated. **Re-measure before removing.** A count taken once decays, and that
one decayed inside a day.
